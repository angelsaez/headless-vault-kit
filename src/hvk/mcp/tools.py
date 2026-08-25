"""The tools an MCP client can call, and what each of them is allowed to touch (ADR-0018).

Every one of these is a call into something that already exists and is already tested. That is
the point: this package is a protocol, not a second implementation of the toolkit. When a tool
here disagrees with the command of the same name, the command is right and this is a bug.

Three properties are declared per tool rather than remembered per handler, because the checks
that use them run in :mod:`hvk.mcp.server` before the handler is reached:

* ``writes`` -- gated behind ``hvk mcp --write``. Without it the tool is not in ``tools/list``
  at all, so a client cannot call what it was never told about.
* ``paths`` -- arguments naming a file in the vault. Each goes through ``guard.decide()``, as a
  write when the tool writes and as a read otherwise, so the protected folders of ADR-0012 are
  protected against any client and not only against the one that happens to run a hook.
* ``filters`` -- arguments that are a *fragment* of a path rather than a path. They are checked
  the same way, because ``{"path": "_PRIVATE"}`` on a search is a request for the contents of a
  protected folder however the query engine spells it.

What the guard does **not** do, here or in the hook, is filter results. It refuses a call that
names a protected folder; it does not redact one that stumbles into it. ADR-0012 drew that line
and this does not move it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


class ToolError(Exception):
    """A tool cannot answer. Comes back as a result with ``isError``, not a protocol error."""


@dataclass(frozen=True)
class Tool:
    name: str
    summary: str
    schema: dict
    run: Callable
    writes: bool = False
    paths: tuple = ()
    filters: tuple = ()

    def described(self) -> dict:
        """This tool as ``tools/list`` describes it."""
        return {"name": self.name, "description": self.summary, "inputSchema": self.schema}


# -- reading arguments ------------------------------------------------------------------------
#
# A client's arguments are untrusted in exactly the way a note is. The schema published in
# tools/list is advisory -- nothing in the protocol makes a client honour it -- so every value
# is checked here before it reaches anything that touches a file.

def _schema(properties: dict, required: tuple = ()) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


STRING = {"type": "string"}
BOOLEAN = {"type": "boolean"}
INTEGER = {"type": "integer"}


def text(args: dict, name: str, *, required: bool = False, default: str | None = None):
    value = args.get(name, default)
    if value is None or value == "":
        if required:
            raise ToolError(f"{name} is required")
        return default
    if not isinstance(value, str):
        raise ToolError(f"{name} must be a string, not {type(value).__name__}")
    return value


def flag(args: dict, name: str) -> bool:
    value = args.get(name, False)
    if not isinstance(value, bool):
        raise ToolError(f"{name} must be true or false")
    return value


def number(args: dict, name: str, default: int) -> int:
    value = args.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{name} must be a whole number")
    return value


def strings(args: dict, name: str) -> list:
    value = args.get(name) or []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ToolError(f"{name} must be a list of strings")
    return value


def vault_file(session, name: str, suffix: str) -> Path:
    """A file named by a client, resolved *inside the vault*, extension optional.

    Deliberately stricter than the command line, which accepts an absolute path to anywhere
    because whoever typed it already has a shell. A client here may be a model reading a note
    somebody else wrote, so the path goes through ``Vault.resolve`` and an escape is refused
    before anything is opened.
    """
    vault = session.vault
    candidate = vault.resolve(name)
    if not candidate.is_file() and candidate.suffix != suffix:
        candidate = vault.resolve(name + suffix)
    if not candidate.is_file():
        raise ToolError(f"no such {suffix} file in the vault: {name}")
    return candidate


# -- querying ---------------------------------------------------------------------------------

def _info(session, args: dict):
    from hvk import query

    return query.info(session.index())


def _search(session, args: dict):
    from hvk import query

    return {"matches": query.search(
        session.index(), text(args, "query", required=True), limit=number(args, "limit", 20)
    )}


def _backlinks(session, args: dict):
    from hvk import query

    target, rows = query.backlinks(session.index(), text(args, "target", required=True))
    return {"target": target, "backlinks": rows}


def _links(session, args: dict):
    from hvk import query

    return {"links": query.links(
        session.index(), text(args, "source"),
        broken=flag(args, "broken"), ambiguous=flag(args, "ambiguous"),
    )}


def _tags(session, args: dict):
    from hvk import query

    return {"tags": query.tags(
        session.index(), count=flag(args, "count"), prefix=text(args, "prefix")
    )}


def _tasks(session, args: dict):
    from hvk import query

    return {"tasks": query.tasks(
        session.index(),
        pending=flag(args, "pending"), done=flag(args, "done"),
        due_before=text(args, "due_before"), path=text(args, "path"),
    )}


def _props(session, args: dict):
    from hvk import query

    return {"files": query.props(
        session.index(), strings(args, "where") or None, key=text(args, "key")
    )}


def _orphans(session, args: dict):
    from hvk import query

    return {"orphans": query.orphans(session.index(), attachments=flag(args, "attachments"))}


def _jsonable(value):
    """A base's values are richer than JSON: dates, files and links become their text."""
    from hvk.bases import values as bases_values

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return bases_values.as_text(value)


def _result_payload(result) -> dict:
    """A base or DQL result, flattened the way `--json` already flattens it."""
    return {
        "type": result.view.type,
        "columns": result.columns,
        "headers": result.headers,
        "total": result.total,
        "shown": len(result.rows),
        "rows": [
            {"path": row["path"], "values": {k: _jsonable(v) for k, v in row["values"].items()}}
            for row in result.rows
        ],
        "warnings": list(result.warnings),
    }


def _base(session, args: dict):
    from hvk.bases import base_file, run as base_run

    path = vault_file(session, text(args, "file", required=True), ".base")
    result = base_run.run(
        base_file.load(path), session.index(), text(args, "view"), text(args, "this")
    )
    return {"base": path.name, "view": result.view.name, **_result_payload(result)}


def _canvas(session, args: dict):
    from hvk.parse.canvas import parse_canvas

    path = vault_file(session, text(args, "file", required=True), ".canvas")
    canvas = parse_canvas(path.read_text(encoding="utf-8", errors="replace"))
    if canvas.error:
        raise ToolError(f"{path.name}: {canvas.error}")

    labels = {n.id: (n.file or n.text or n.url or n.id) for n in canvas.nodes}
    return {
        "canvas": path.name,
        "nodes": [
            {"id": n.id, "type": n.type, "file": n.file, "url": n.url, "text": n.text}
            for n in canvas.nodes
        ],
        "edges": [
            {"from": labels.get(e.from_node, e.from_node), "label": e.label,
             "to": labels.get(e.to_node, e.to_node)}
            for e in canvas.edges
        ],
    }


def _dql(session, args: dict):
    from hvk import dql as dataview

    note = text(args, "note")
    source = text(args, "query")
    if note:
        original = session.vault.read(note)
        if not original.exists:
            raise ToolError(f"no such note: {note}")
        queries = dataview.blocks_in(original.text)
    elif source:
        queries = [source]
    else:
        raise ToolError("give a query, or a note whose dataview blocks should be run")

    return {"results": [
        {"query": one, **_result_payload(dataview.run(dataview.parse(one), session.index()))}
        for one in queries
    ]}


def _note_read(session, args: dict):
    """A note's own text, with the digest that makes a later write safe.

    The digest is not decoration: it is how ADR-0007's refusal-to-clobber survives a protocol
    where the client cannot hold a file handle between calls. Hand it back to ``note_write`` as
    ``if_unchanged`` and an edit that arrived from a phone in between loses the race instead of
    being overwritten.
    """
    path = text(args, "path", required=True)
    original = session.vault.read(path)
    return {
        "path": path,
        "exists": original.exists,
        "text": original.text if original.exists else None,
        "digest": original.digest,
    }


# -- writing ----------------------------------------------------------------------------------

ABSENT = "absent"


def _note_write(session, args: dict):
    """Create or replace a note, through the write layer and nothing else (ADR-0007)."""
    from hvk import write

    path = text(args, "path", required=True)
    body = args.get("text")
    if not isinstance(body, str):
        raise ToolError("text is required, and is the note's whole new contents")

    original = session.vault.read(path)
    expected = text(args, "if_unchanged")
    if expected == ABSENT and original.exists:
        raise ToolError(
            f"{path} exists, and if_unchanged said it should not. Nothing was written."
        )
    if expected is not None and expected != ABSENT and expected != original.digest:
        raise ToolError(
            f"{path} has changed since it was read (if_unchanged does not match). Nothing was "
            f"written. Read it again and decide with the new content."
        )

    changed = session.vault.write(original, body)
    session.record("mcp write", tool="note_write", path=path, changed=str(changed).lower())
    return {"path": path, "created": not original.exists, "changed": changed}


def _note_set_property(session, args: dict):
    """Set one frontmatter key, leaving every other byte of the note alone.

    Worth having beside ``note_write`` rather than folded into it: the YAML is never parsed and
    re-emitted, so key order, comments, quoting and blank lines survive. A client that reads a
    note and writes it back whole loses all of that, and the diff reaches every device.
    """
    from hvk import write

    path = text(args, "path", required=True)
    key = text(args, "key", required=True)
    value = text(args, "value", required=True)

    original = session.vault.read(path)
    if not original.exists:
        raise ToolError(f"no such note: {path}")
    changed = session.vault.write(original, write.set_frontmatter(original.text, key, value))
    session.record("mcp write", tool="note_set_property", path=path, match=key)
    return {"path": path, "key": key, "value": value, "changed": changed}


def _views_apply(session, args: dict):
    from hvk import views as materialised

    path = text(args, "path")
    report = materialised.refresh(session.index(), session.location, path=path, apply=True)
    session.record("mcp write", tool="views_apply", path=path or "(whole vault)",
                   match=str(report.changed))
    return {
        "views": [outcome.as_dict() for outcome in report.outcomes],
        "changed": report.changed,
        "errors": report.errors,
    }


def _canvas_add(session, args: dict):
    """Put notes and arrows on a whiteboard, without moving anything already on it."""
    from hvk import boards

    connect = args.get("connect") or []
    if not isinstance(connect, list) or not all(
        isinstance(pair, list) and len(pair) == 2 and all(isinstance(e, str) for e in pair)
        for pair in connect
    ):
        raise ToolError("connect must be a list of [from, to] pairs of strings")

    outcome = boards.edit(
        session.vault, text(args, "file", required=True),
        notes=strings(args, "notes"), texts=strings(args, "texts"),
        connect=[tuple(pair) for pair in connect],
        create=flag(args, "create"), apply=True,
    )
    session.record("mcp write", tool="canvas_add", path=outcome.canvas,
                   match=str(len(outcome.nodes) + len(outcome.edges)))
    return outcome.as_dict()


def _jobs_run(session, args: dict):
    """Run the order-notes waiting in the server's jobs directory.

    **The directories are the server's, never the client's.** A client that could name its own
    profiles directory could name one it had just written, and a permission profile chosen by
    the thing being permitted is not a permission at all -- the whole of ADR-0009 is that a note
    picks a profile *by name* from a directory the server's owner controls. So there is no
    argument for it here, and without ``HVK_JOBS_DIR`` and ``HVK_JOBS_PROFILES`` this refuses
    exactly as the command line does.
    """
    from hvk import jobs as order_notes

    dry_run = flag(args, "dry_run")
    outcomes = order_notes.run(
        session.location.vault, jobs=session.jobs_dir, profiles=session.profiles_dir,
        execute=not dry_run,
    )
    if not dry_run:
        session.record("mcp write", tool="jobs_run", match=str(len(outcomes)))
    return {"jobs": [outcome.as_dict() for outcome in outcomes], "dry_run": dry_run}


# -- the table ----------------------------------------------------------------------------------

QUERY_TOOLS = (
    Tool(
        name="info", run=_info, schema=_schema({}),
        summary="What the index currently holds: counts of files, notes, links, tags and "
                "tasks, when it was last scanned, and how many links are broken or ambiguous. "
                "Call this first when you need to know whether the index is current.",
    ),
    Tool(
        # No `filters` here even though a search can be narrowed by path: this one's filter is
        # written inside the query string rather than passed as an argument, so the guard has
        # to pull it out. Session.check does exactly that, by name.
        name="search", run=_search,
        schema=_schema({
            "query": {**STRING, "description":
                      "Text to find. Accepts 'tag:name' and 'path:fragment' filters inline, "
                      "e.g. 'budget tag:project path:Areas'."},
            "limit": {**INTEGER, "description": "Maximum matches (default 20)."},
        }, required=("query",)),
        summary="Full-text search across the vault, returning a path, title and snippet per "
                "match. Far cheaper than reading notes one by one; use it to find the handful "
                "worth reading.",
    ),
    Tool(
        name="backlinks", run=_backlinks,
        schema=_schema({"target": {**STRING, "description":
                                   "A note's path, or just its name."}}, required=("target",)),
        summary="Every link pointing at a note, with the file and line each was written on. "
                "Includes links from canvases. This is the question the app answers on its "
                "sidebar and nothing else here can.",
    ),
    Tool(
        name="links", run=_links, filters=("source",),
        schema=_schema({
            "source": {**STRING, "description": "Restrict to links written in this note."},
            "broken": {**BOOLEAN, "description": "Only links that resolve to nothing."},
            "ambiguous": {**BOOLEAN, "description":
                          "Only links where more than one file matched and a tie-break chose."},
        }),
        summary="Outgoing links. With 'broken', the ones pointing nowhere; with 'ambiguous', "
                "the ones where several files matched the name and the answer may differ from "
                "what the app would show.",
    ),
    Tool(
        name="tags", run=_tags,
        schema=_schema({
            "count": {**BOOLEAN, "description": "Include how many files carry each tag."},
            "prefix": {**STRING, "description":
                       "Only this tag and its nested children, e.g. 'home' matches 'home/diy'."},
        }),
        summary="The vocabulary of the vault: every distinct tag, from frontmatter and from "
                "the body. Use it before guessing at a tag name in another query.",
    ),
    Tool(
        name="tasks", run=_tasks, filters=("path",),
        schema=_schema({
            "pending": {**BOOLEAN, "description": "Only unfinished tasks."},
            "done": {**BOOLEAN, "description": "Only finished tasks."},
            "due_before": {**STRING, "description": "YYYY-MM-DD. Tasks with no date never match."},
            "path": {**STRING, "description": "Restrict to paths containing this text."},
        }),
        summary="Every checkbox in the vault, wherever it was written, with its due date and "
                "any plugin fields on the line. Kanban cards are included, carrying the list "
                "they sit in.",
    ),
    Tool(
        name="props", run=_props,
        schema=_schema({
            "where": {"type": "array", "items": STRING, "description":
                      "Conditions like 'status=open', 'status!=done', or a bare key meaning "
                      "the property exists. Several combine with AND."},
            "key": {**STRING, "description": "Which property's value to show in the result."},
        }),
        summary="Files by their frontmatter properties, or -- with no arguments -- the "
                "catalogue of every property key in the vault and how many files use it.",
    ),
    Tool(
        name="orphans", run=_orphans,
        schema=_schema({"attachments": {**BOOLEAN, "description":
                                        "Include unreferenced attachments as well as notes."}}),
        summary="Files nothing links to. With attachments, this is the list worth reading "
                "before deleting anything.",
    ),
    Tool(
        name="base", run=_base, paths=("file",),
        schema=_schema({
            "file": {**STRING, "description": "The .base file, by path inside the vault."},
            "view": {**STRING, "description": "Which view to run (default: the first)."},
            "this": {**STRING, "description":
                     "The note the base is embedded in, for expressions using 'this'."},
        }, required=("file",)),
        summary="Run a view from an Obsidian .base file against the index and return its rows. "
                "This is what the app renders on screen, computed without it.",
    ),
    Tool(
        name="canvas", run=_canvas, paths=("file",),
        schema=_schema({"file": {**STRING, "description":
                                 "The .canvas file, by path inside the vault."}},
                       required=("file",)),
        summary="What is on a whiteboard: its boxes, and the arrows between them. Read from "
                "the file, because the shape of a board is not in the index (only its links "
                "and text are).",
    ),
    Tool(
        name="dql", run=_dql, paths=("note",),
        schema=_schema({
            "query": {**STRING, "description":
                      "A Dataview query, e.g. 'TABLE status FROM #project WHERE status = \"open\"'."},
            "note": {**STRING, "description":
                     "Instead of a query: run every ```dataview block in this note."},
        }),
        summary="Answer a Dataview query from the index. LIST and TABLE with FROM, WHERE, SORT "
                "and LIMIT are supported; anything else refuses by name rather than returning "
                "a table that looks right and is not. dataviewjs is never executed.",
    ),
    Tool(
        name="note_read", run=_note_read, paths=("path",),
        schema=_schema({"path": {**STRING, "description":
                                 "The note's path inside the vault."}}, required=("path",)),
        summary="One note's raw Markdown, plus a digest of it. Pass that digest back as "
                "note_write's 'if_unchanged' so an edit that arrived from another device in "
                "the meantime is refused rather than overwritten.",
    ),
)

WRITE_TOOLS = (
    Tool(
        name="note_write", run=_note_write, writes=True, paths=("path",),
        schema=_schema({
            "path": {**STRING, "description": "The note's path inside the vault."},
            "text": {**STRING, "description": "The note's whole new contents."},
            "if_unchanged": {**STRING, "description":
                             "'absent' to refuse if the note already exists, or a digest from "
                             "note_read to refuse if it has changed since. Omit at your peril."},
        }, required=("path", "text")),
        summary="Create or replace a note. The write is atomic, keeps the file's line endings "
                "and permissions, and does nothing at all when the content is identical. Read "
                "the note first and pass its digest as 'if_unchanged' unless you are creating "
                "it.",
    ),
    Tool(
        name="note_set_property", run=_note_set_property, writes=True, paths=("path",),
        schema=_schema({
            "path": {**STRING, "description": "The note's path inside the vault."},
            "key": {**STRING, "description": "The frontmatter key to set."},
            "value": {**STRING, "description": "Its new value."},
        }, required=("path", "key", "value")),
        summary="Set one frontmatter property, leaving every other byte of the note alone. "
                "Prefer this over rewriting a note to change a field: the YAML is never "
                "reparsed, so key order, comments and quoting all survive.",
    ),
    Tool(
        name="views_apply", run=_views_apply, writes=True, paths=("path",),
        schema=_schema({"path": {**STRING, "description":
                                 "Restrict to one note or folder (default: the whole vault)."}}),
        summary="Regenerate the base tables materialised inside notes, and write them. Safe to "
                "run often: it writes only what actually changed, and nothing when nothing did.",
    ),
    Tool(
        name="canvas_add", run=_canvas_add, writes=True, paths=("file",),
        schema=_schema({
            "file": {**STRING, "description": "The .canvas file, by path inside the vault."},
            "notes": {"type": "array", "items": STRING, "description":
                      "Notes to put on the board, by path inside the vault."},
            "texts": {"type": "array", "items": STRING, "description":
                      "Markdown text boxes to put on the board."},
            "connect": {"type": "array", "items": {"type": "array", "items": STRING},
                        "description":
                        "Arrows, as [from, to] pairs. Each end is a note path, a note name or a "
                        "node id, and must already be on the board or be added in this call."},
            "create": {**BOOLEAN, "description":
                       "Make the canvas if it is not there. Without it a name that does not "
                       "exist is an error, so a typo cannot start a new board."},
        }, required=("file",)),
        summary="Add notes, text boxes and arrows to a whiteboard. Only ever adds: nothing "
                "already on the board is moved, resized, recoloured or removed, because a "
                "canvas is the one thing in a vault somebody arranged by hand. Adding the same "
                "note twice does nothing.",
    ),
    Tool(
        name="jobs_run", run=_jobs_run, writes=True,
        schema=_schema({"dry_run": {**BOOLEAN, "description":
                                    "Report what would run without claiming or executing "
                                    "anything."}}),
        summary="Run the order-notes waiting in the server's jobs directory, each under the "
                "permission profile its own frontmatter names. The directories are the "
                "server's configuration and cannot be chosen here.",
    ),
)

ALL = (*QUERY_TOOLS, *WRITE_TOOLS)
BY_NAME = {tool.name: tool for tool in ALL}


def available(allow_write: bool) -> list:
    """The tools this instance offers. Without ``--write``, the writing ones do not exist."""
    return [tool for tool in ALL if allow_write or not tool.writes]
