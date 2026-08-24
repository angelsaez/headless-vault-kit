"""A subset of Dataview's query language, answered from the index (tier 2, ADR-0016).

Dataview is not installed in the vault this was built for, and its query blocks render nothing
there. It is built anyway because the criterion changed: not "does someone here use it" but
"is this a format the community writes". A vault arriving from anywhere else is full of
```dataview blocks, and a tool that reads a vault should be able to say what they mean.

**Nothing here re-implements a language.** The clause structure is parsed here; every
*expression* — `status = "active"`, `file.name`, `rating > 3` — goes through the engine Bases
already uses, after two rewrites:

* ``=`` becomes ``==``. Dataview spells equality with one sign and this engine with two;
  ``!=``, ``>=`` and ``<=`` are left alone by a lookaround, so the rewrite cannot damage them.
* ``contains(field, x)`` becomes ``field.contains(x)``. Dataview calls functions and this
  engine calls methods on values. Only a named list is rewritten, and everything else keeps
  the engine's own refusal — an unknown function is an error, never a silent null.

What is *not* supported fails naming itself, which is the rule ADR-0005 set for Bases and the
reason to trust either of them: a query that quietly drops a clause returns a table that looks
right and is not.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from hvk.bases import expr as ast
from hvk.bases.base_file import Sort, View
from hvk.bases.evaluate import Context
from hvk.bases.expr import ExpressionError
from hvk.bases.run import Result, load_files

# Every clause Dataview understands. The ones this does not implement are named here anyway,
# so the refusal can say "not supported" rather than "unexpected word", which is the difference
# between a person fixing a query and a person filing a bug.
CLAUSES = ("FROM", "WHERE", "SORT", "LIMIT", "GROUP", "FLATTEN")
SUPPORTED_CLAUSES = ("FROM", "WHERE", "SORT", "LIMIT")
QUERY_TYPES = ("LIST", "TABLE")
UNSUPPORTED_TYPES = ("TASK", "CALENDAR")

# Dataview functions worth answering, mapped to the method the engine already has. Anything
# outside this reaches the engine as a bare call and is refused there, by name.
FUNCTION_TO_METHOD = {
    "contains": "contains",
    "containsall": "containsAll",
    "containsany": "containsAny",
    "startswith": "startsWith",
    "endswith": "endsWith",
    "lower": "lower",
    "upper": "title",
}

_EQUALS = re.compile(r"(?<![!<>=])=(?!=)")
_CLAUSE_RE = re.compile(rf"\b({'|'.join(CLAUSES)})\b", re.IGNORECASE)


class DqlError(Exception):
    """Raised for a query this does not support, always naming what it was."""


@dataclass
class Source:
    """What FROM narrows to. One shape at a time, on purpose."""

    kind: str               # 'tag' | 'folder'
    value: str
    negated: bool = False


@dataclass
class Query:
    type: str                                     # 'list' | 'table'
    columns: list = field(default_factory=list)   # (expression source, header)
    without_id: bool = False
    source: Source | None = None
    where: str | None = None
    sorts: list = field(default_factory=list)     # (expression source, descending)
    limit: int | None = None


# -- the expression rewrites -------------------------------------------------------------------

def _rewrite_calls(node):
    """Turn Dataview's `contains(a, b)` into the engine's `a.contains(b)`, recursively."""
    if isinstance(node, ast.Call):
        arguments = tuple(_rewrite_calls(a) for a in node.arguments)
        callee = node.callee
        if isinstance(callee, ast.Name):
            method = FUNCTION_TO_METHOD.get(callee.identifier.lower())
            if method and arguments:
                return ast.Call(ast.Member(arguments[0], method), arguments[1:])
        return ast.Call(_rewrite_calls(callee), arguments)
    if isinstance(node, ast.Binary):
        return ast.Binary(node.operator, _rewrite_calls(node.left), _rewrite_calls(node.right))
    if isinstance(node, ast.Unary):
        return ast.Unary(node.operator, _rewrite_calls(node.operand))
    if isinstance(node, ast.Member):
        return ast.Member(_rewrite_calls(node.target), node.name)
    if isinstance(node, ast.Index):
        return ast.Index(_rewrite_calls(node.target), _rewrite_calls(node.key))
    if isinstance(node, ast.ListLiteral):
        return ast.ListLiteral(tuple(_rewrite_calls(e) for e in node.elements))
    return node


def parse_expression(source: str):
    """One Dataview expression, as a tree the Bases evaluator can run."""
    try:
        return _rewrite_calls(ast.parse(_EQUALS.sub("==", source)))
    except ExpressionError as exc:
        raise DqlError(f"cannot read the expression {source.strip()!r}: {exc}") from exc


# -- the query ----------------------------------------------------------------------------------

def _split_clauses(text: str) -> list:
    """Cut a query at its clause keywords, keeping each keyword with what follows it."""
    parts, last, name = [], 0, None
    for match in _CLAUSE_RE.finditer(text):
        parts.append((name, text[last:match.start()].strip()))
        name, last = match.group(1).upper(), match.end()
    parts.append((name, text[last:].strip()))
    return parts


def _columns(text: str) -> list:
    """`a, b AS "Header", c` -> [(expression, header)]."""
    columns = []
    for piece in _split_top_level(text):
        if not piece:
            continue
        match = re.search(r"\s+AS\s+", piece, re.IGNORECASE)
        if match:
            expression = piece[: match.start()].strip()
            header = piece[match.end():].strip().strip("\"'")
        else:
            expression, header = piece.strip(), piece.strip()
        columns.append((expression, header))
    return columns


def _split_top_level(text: str) -> list:
    """Split on commas that are not inside brackets or quotes."""
    pieces, depth, quote, current = [], 0, None, []
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == "," and depth == 0:
            pieces.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    pieces.append("".join(current).strip())
    return pieces


def _source(text: str) -> Source:
    text = text.strip()
    negated = text.startswith("-")
    if negated:
        text = text[1:].strip()
    if " and " in f" {text.lower()} " or " or " in f" {text.lower()} ":
        raise DqlError(
            "FROM takes one source here: a #tag or a \"folder\". Combining them with and/or "
            "is Dataview syntax this does not implement (ADR-0016)."
        )
    if text.startswith("#"):
        return Source("tag", text[1:].strip(), negated)
    if text.startswith(("\"", "'")):
        return Source("folder", text.strip("\"'").strip("/"), negated)
    if text.startswith("[["):
        raise DqlError("FROM [[link]] is not implemented; use a #tag or a \"folder\".")
    raise DqlError(f"cannot read FROM {text!r}: expected a #tag or a \"folder\".")


def parse(source: str) -> Query:
    """One DQL query. Anything unsupported raises, naming itself."""
    text = " ".join(source.split())
    if not text:
        raise DqlError("empty query")

    clauses = _split_clauses(text)
    head = clauses[0][1]
    words = head.split(None, 1)
    kind = words[0].upper() if words else ""
    if kind in UNSUPPORTED_TYPES:
        raise DqlError(f"{kind} queries are not implemented; this reads LIST and TABLE.")
    if kind not in QUERY_TYPES:
        raise DqlError(f"a query starts with LIST or TABLE, not {words[0]!r}" if words
                       else "a query starts with LIST or TABLE")

    query = Query(type=kind.lower())
    rest = words[1].strip() if len(words) > 1 else ""

    if kind == "TABLE":
        if re.match(r"(?i)WITHOUT\s+ID\b", rest):
            query.without_id = True
            rest = re.sub(r"(?i)^WITHOUT\s+ID\b", "", rest).strip()
        query.columns = _columns(rest)
    elif rest:
        # LIST <expression> prints that expression instead of the file link.
        query.columns = [(rest, rest)]

    for name, body in clauses[1:]:
        if name in ("GROUP", "FLATTEN"):
            raise DqlError(
                f"{name} is Dataview syntax this does not implement. Supported clauses: "
                f"{', '.join(SUPPORTED_CLAUSES)} (ADR-0016)."
            )
        if name == "FROM":
            query.source = _source(body)
        elif name == "WHERE":
            if not body:
                raise DqlError("WHERE with no condition")
            query.where = body
        elif name == "SORT":
            for piece in _split_top_level(body):
                if not piece:
                    continue
                descending = bool(re.search(r"\bDESC\b", piece, re.IGNORECASE))
                expression = re.sub(r"(?i)\s+(ASC|DESC)\s*$", "", piece).strip()
                query.sorts.append((expression, descending))
        elif name == "LIMIT":
            try:
                query.limit = int(body.strip())
            except ValueError:
                raise DqlError(f"LIMIT takes a number, not {body.strip()!r}") from None
    return query


# -- running it ---------------------------------------------------------------------------------

def _inline_props(conn: sqlite3.Connection) -> dict:
    """Dataview's own fields: `key:: value` written in the body.

    This is where the two dialects genuinely differ. Bases sees Obsidian properties, which are
    frontmatter and nothing else (ADR-0005). Dataview sees frontmatter *and* inline fields,
    because that is what Dataview writes and reads — so a DQL query that ignored them would be
    answering a different question than the one the block asks.
    """
    from hvk.bases.run import _typed

    inline: dict = {}
    for row in conn.execute(
        "SELECT file_id, key, value, value_type FROM props WHERE inline = 1"
    ):
        inline.setdefault(row["file_id"], {})[row["key"]] = _typed(row["value"], row["value_type"])
    return inline


def run(query: Query, conn: sqlite3.Connection) -> Result:
    """Answer a query, in the shape `hvk base` already returns so the renderer is shared."""
    from hvk.bases.evaluate import evaluate
    from hvk.bases.run import _order_rows

    files = load_files(conn)
    notes = {
        row["file_id"]: {} for row in conn.execute("SELECT DISTINCT file_id FROM props")
    }
    for file_id, values in _inline_props(conn).items():
        notes.setdefault(file_id, {}).update(values)

    where = parse_expression(query.where) if query.where else None
    column_trees = [(parse_expression(source), source, header)
                    for source, header in query.columns]
    sort_trees = [(parse_expression(source), descending) for source, descending in query.sorts]

    rows = []
    for file_id, value in files.items():
        if not _in_source(value, query.source):
            continue
        # Frontmatter first, then inline fields on top: a `key:: value` in the body is what
        # Dataview would have read last.
        note = dict(value.properties)
        note.update(notes.get(file_id, {}))
        context = Context(file=value, note=note)
        if where is not None:
            from hvk.bases.values import truthy

            if not truthy(evaluate(where, context)):
                continue
        values = {source: evaluate(tree, context) for tree, source, _ in column_trees}
        # Sort keys live beside the columns under names a query cannot collide with, so the
        # ordering machinery Bases already has -- nulls last whichever way the sort points,
        # numbers compared as numbers -- can be reused instead of written again here.
        for position, (tree, _) in enumerate(sort_trees):
            values[f"::sort{position}"] = evaluate(tree, context)
        rows.append({"path": value.path, "values": values})

    _order_rows(rows, [Sort(property=f"::sort{position}", descending=descending)
                       for position, (_, descending) in enumerate(sort_trees)])
    total = len(rows)
    if query.limit is not None:
        rows = rows[: query.limit]
    for row in rows:
        for position in range(len(sort_trees)):
            row["values"].pop(f"::sort{position}", None)

    columns = [source for _, source, _ in column_trees]
    headers = [header for _, _, header in column_trees]
    if query.type == "list" and not columns:
        columns, headers = ["file.name"], ["File"]
        for row in rows:
            row["values"] = {"file.name": row["path"].rsplit("/", 1)[-1].removesuffix(".md")}
    elif query.type == "table" and not query.without_id:
        columns.insert(0, "file.name")
        headers.insert(0, "File")
        for row in rows:
            row["values"]["file.name"] = row["path"].rsplit("/", 1)[-1].removesuffix(".md")

    view = View(type=query.type, name=query.type.upper(), limit=query.limit)
    return Result(view=view, columns=columns, headers=headers, rows=rows, total=total)


def _in_source(value, source: Source | None) -> bool:
    if source is None:
        return True
    if source.kind == "tag":
        wanted = source.value.lstrip("#").lower()
        matched = any(tag.lower() == wanted or tag.lower().startswith(wanted + "/")
                      for tag in value.tags)
    else:
        folder = source.value.lower()
        matched = value.path.lower().startswith(folder + "/") if folder else True
    return matched != source.negated


# -- blocks inside notes ------------------------------------------------------------------------

BLOCK_RE = re.compile(r"```+\s*dataview\s*\n(.*?)```+", re.DOTALL | re.IGNORECASE)


def blocks_in(text: str) -> list:
    """Every ```dataview block in a note, in order. `dataviewjs` is deliberately not matched."""
    return [match.group(1).strip() for match in BLOCK_RE.finditer(text)
            if not re.match(r"```+\s*dataviewjs", match.group(0), re.IGNORECASE)]
