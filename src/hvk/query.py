"""Read-only queries over the index.

This is what replaces reading files one by one: the agent asks the index and gets an answer
in milliseconds instead of spending tokens on the whole vault.
"""

from __future__ import annotations

import datetime as _dt
import re
import sqlite3

from hvk.links import FileEntry, FileIndex

FILTER_RE = re.compile(r"\b(path|tag):(\"[^\"]+\"|\S+)")
# key=value, key!=value, or a bare key. The operator group is optional, so a bare key
# leaves groups 2 and 3 as None.
CONDITION_RE = re.compile(r"([^=!]+?)\s*(?:(!=|=)\s*(.*))?")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class QueryError(Exception):
    """Raised for a malformed query or a target that cannot be found."""


# FTS5 reads bare punctuation as syntax: "subject-13" parses as an expression and "kind/3"
# looks like a column filter, so a perfectly ordinary search for a hyphenated word or a dated
# note name fails with a SQL error nobody can act on. Ordinary words are therefore quoted, and
# only the operators someone typed on purpose are passed through.
FTS_OPERATORS = {"AND", "OR", "NOT", "NEAR"}
FTS_TOKEN_RE = re.compile(r'"[^"]*"\*?|[()]|[^\s()]+\*?')


def to_fts_query(text: str) -> str:
    """Turn what a person typed into a valid FTS5 expression, preserving deliberate syntax."""
    parts = []
    for token in FTS_TOKEN_RE.findall(text):
        if token.startswith('"') or token in FTS_OPERATORS or token in ("(", ")"):
            parts.append(token)
            continue
        prefix = "*" if token.endswith("*") else ""
        bare = token[:-1] if prefix else token
        if not bare:
            continue
        parts.append('"' + bare.replace('"', '""') + '"' + prefix)
    return " ".join(parts)


def _file_entry(row: sqlite3.Row) -> FileEntry:
    return FileEntry(row["id"], row["path"], row["parent"], row["name"], row["stem"], row["ext"])


def _index(conn: sqlite3.Connection) -> FileIndex:
    rows = conn.execute("SELECT id, path, parent, name, stem, ext FROM files").fetchall()
    return FileIndex(_file_entry(r) for r in rows)


def find_file(conn: sqlite3.Connection, target: str) -> sqlite3.Row:
    """Find one file from a vault-relative path or a bare note name.

    Uses the same rules as link resolution (ADR-0003), seen from the vault root, so that
    ``hvk backlinks Alpha`` and ``hvk backlinks Projects/Alpha.md`` agree.
    """
    row = conn.execute(
        "SELECT id, path, parent, name, stem, ext FROM files WHERE path = ? OR path = ?",
        (target, f"{target}.md"),
    ).fetchone()
    if row:
        return row

    # Fast path: a bare name that matches exactly one note needs no tie-break, so there is no
    # reason to build an in-memory index of the whole vault to answer it. Anything ambiguous,
    # or written as a partial path, still goes through the full rules below.
    if "/" not in target:
        candidates = conn.execute(
            "SELECT id, path, parent, name, stem, ext FROM files "
            "WHERE stem_lower = lower(?) OR lower(name) = lower(?) LIMIT 2",
            (target, target),
        ).fetchall()
        if len(candidates) == 1:
            return candidates[0]

    root = FileEntry(-1, "", "", "", "", "")
    result = _index(conn).resolve(target, root)
    if result.target is None:
        raise QueryError(f"no file in the index matches {target!r}")
    found = conn.execute(
        "SELECT id, path, parent, name, stem, ext FROM files WHERE id = ?", (result.target.id,)
    ).fetchone()
    return found


def split_filters(query: str) -> tuple[str, str | None, str | None]:
    """Pull ``path:`` and ``tag:`` filters out of a search string.

    ``hvk search "budget tag:project path:Areas"`` searches for *budget* among notes tagged
    ``#project`` whose path contains *Areas*.
    """
    path = tag = None
    for match in FILTER_RE.finditer(query):
        value = match.group(2).strip('"')
        if match.group(1) == "path":
            path = value
        else:
            tag = value.lstrip("#")
    return FILTER_RE.sub("", query).strip(), path, tag


def search(
    conn: sqlite3.Connection, query: str, *, limit: int = 20
) -> list[dict]:
    """Full-text search with optional ``path:`` and ``tag:`` filters."""
    text, path, tag = split_filters(query)
    if not text:
        raise QueryError("nothing left to search for once the filters were removed")

    sql = [
        "SELECT f.path AS path, fts.title AS title,",
        "       snippet(fts, 2, '<<', '>>', '…', 12) AS snippet,",
        "       round(-bm25(fts), 3) AS score",
        "FROM fts JOIN files f ON f.id = fts.rowid",
        "WHERE fts MATCH ?",
    ]
    params: list = [to_fts_query(text)]
    if path:
        sql.append("AND f.path LIKE ?")
        params.append(f"%{path}%")
    if tag:
        sql.append(
            "AND EXISTS (SELECT 1 FROM tags t WHERE t.file_id = f.id "
            "AND (t.tag = ? OR t.tag LIKE ?))"
        )
        params.extend([tag, f"{tag}/%"])
    sql.append("ORDER BY bm25(fts) LIMIT ?")
    params.append(limit)

    try:
        rows = conn.execute("\n".join(sql), params).fetchall()
    except sqlite3.OperationalError as exc:
        raise QueryError(f"invalid search query: {exc}") from exc
    return [dict(row) for row in rows]


def backlinks(conn: sqlite3.Connection, target: str) -> tuple[str, list[dict]]:
    """Every link pointing at *target*. Backlinks are a query, never stored (plan §6)."""
    found = find_file(conn, target)
    rows = conn.execute(
        "SELECT f.path AS source, l.line AS line, l.target_raw AS wrote, "
        "       l.subpath AS subpath, l.kind AS kind, l.embed AS embed, "
        "       l.candidates AS candidates "
        "FROM links l JOIN files f ON f.id = l.file_id "
        "WHERE l.target_file_id = ? "
        "ORDER BY f.path, l.line",
        (found["id"],),
    ).fetchall()
    return found["path"], [dict(row) for row in rows]


def links(
    conn: sqlite3.Connection,
    source: str | None = None,
    *,
    broken: bool = False,
    ambiguous: bool = False,
) -> list[dict]:
    """Outgoing links, optionally restricted to broken or ambiguous ones.

    ``--ambiguous`` is the validation list ADR-0003 promised: every link where more than one
    file matched and our tie-break had to choose.
    """
    sql = [
        "SELECT f.path AS source, l.line AS line, l.target_raw AS target_raw, "
        "       l.subpath AS subpath, l.kind AS kind, l.embed AS embed, "
        "       l.candidates AS candidates, t.path AS resolved "
        "FROM links l JOIN files f ON f.id = l.file_id "
        "LEFT JOIN files t ON t.id = l.target_file_id "
        "WHERE 1 = 1"
    ]
    params: list = []
    if source:
        found = find_file(conn, source)
        sql.append("AND l.file_id = ?")
        params.append(found["id"])
    if broken:
        sql.append("AND l.target_file_id IS NULL AND l.kind != 'external'")
    if ambiguous:
        sql.append("AND l.candidates > 1")
    sql.append("ORDER BY f.path, l.line")
    rows = conn.execute("\n".join(sql), params).fetchall()
    return [dict(row) for row in rows]


def tags(conn: sqlite3.Connection, *, count: bool = False, prefix: str | None = None) -> list[dict]:
    """Every distinct tag, with how many files carry it.

    A nested tag is stored as written (``home/nested``); ``prefix`` matches a tag and all of
    its descendants, the way Obsidian treats them.
    """
    where, params = "", []
    if prefix:
        prefix = prefix.lstrip("#")
        where = "WHERE tag = ? OR tag LIKE ?"
        params = [prefix, f"{prefix}/%"]
    order = "ORDER BY files DESC, tag" if count else "ORDER BY tag"
    rows = conn.execute(
        f"SELECT tag, count(DISTINCT file_id) AS files FROM tags {where} GROUP BY tag {order}",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def tasks(
    conn: sqlite3.Connection,
    *,
    pending: bool = False,
    done: bool = False,
    due_before: str | None = None,
    path: str | None = None,
) -> list[dict]:
    """Tasks across the vault, filtered by state, due date or path.

    Due dates come from the tier-2 fields of ADR-0004. A task without one is never returned by
    a date filter, rather than being treated as due forever.
    """
    if due_before and not DATE_RE.fullmatch(due_before):
        raise QueryError(f"expected a date as YYYY-MM-DD, got {due_before!r}")

    sql = [
        "SELECT f.path AS path, t.line AS line, t.status AS status, t.done AS done, "
        "       t.due AS due, t.text AS text, t.extra_json AS extra "
        "FROM tasks t JOIN files f ON f.id = t.file_id WHERE 1 = 1"
    ]
    params: list = []
    if pending:
        sql.append("AND t.done = 0")
    if done:
        sql.append("AND t.done = 1")
    if due_before:
        sql.append("AND t.due IS NOT NULL AND t.due < ?")
        params.append(due_before)
    if path:
        sql.append("AND f.path LIKE ?")
        params.append(f"%{path}%")
    # Dated tasks first, soonest first; undated ones after, by where they live.
    sql.append("ORDER BY t.due IS NULL, t.due, f.path, t.line")
    return [dict(row) for row in conn.execute(chr(10).join(sql), params)]


def _parse_condition(condition: str) -> tuple[str, list, str]:
    """Turn one ``--where`` into an EXISTS clause. Returns ``(sql, params, key)``."""
    match = CONDITION_RE.fullmatch(condition.strip())
    if not match or not match.group(1).strip():
        raise QueryError(
            f"cannot read the condition {condition!r}. Expected key=value, key!=value, or a "
            f"bare key meaning the property exists."
        )
    key, operator, value = match.group(1).strip(), match.group(2), match.group(3)
    if operator is None:
        return (
            "AND EXISTS (SELECT 1 FROM props p WHERE p.file_id = f.id "
            "AND lower(p.key) = lower(?))",
            [key],
            key,
        )
    # Values are compared case-insensitively: "Abierto" and "abierto" are the same thing to
    # whoever typed them.
    value = value.strip().strip("\"'")
    negate = "NOT " if operator == "!=" else ""
    return (
        f"AND {negate}EXISTS (SELECT 1 FROM props p WHERE p.file_id = f.id "
        f"AND lower(p.key) = lower(?) AND lower(p.value) = lower(?))",
        [key, value],
        key,
    )


def props(
    conn: sqlite3.Connection,
    where: list[str] | None = None,
    *,
    key: str | None = None,
) -> list[dict]:
    """Files filtered by their properties, or the catalogue of keys when nothing is asked for.

    Each condition is ``key=value``, ``key!=value`` or a bare ``key`` meaning "has it";
    several of them combine with AND.
    """
    if not where and not key:
        rows = conn.execute(
            "SELECT key, count(DISTINCT file_id) AS files, count(*) AS occurrences "
            "FROM props GROUP BY key ORDER BY files DESC, key"
        ).fetchall()
        return [dict(row) for row in rows]

    clauses: list[str] = []
    params: list = []
    shown = key
    for condition in where or []:
        clause, values, condition_key = _parse_condition(condition)
        clauses.append(clause)
        params.extend(values)
        shown = shown or condition_key

    matching = ["SELECT f.id AS id, f.path AS path FROM files f WHERE f.kind = 'note'"]
    matching.extend(clauses)
    rows = conn.execute(
        chr(10).join(matching) + chr(10) + "ORDER BY f.path", params
    ).fetchall()

    # Two queries, whatever the answer's size. This used to fetch one file's values per file,
    # which is one round trip per row: on a 10,000-note vault a query matching two thirds of it
    # ran seven thousand statements and missed the plan's 100 ms budget by a factor of two. The
    # file-selection clause is repeated as a subquery rather than passing the ids back in,
    # because a few thousand of them is well past what SQLite will bind in one statement.
    grouped: dict = {}
    if shown and rows:
        selection = chr(10).join(["SELECT f.id FROM files f WHERE f.kind = 'note'", *clauses])
        for row in conn.execute(
            f"SELECT p.file_id AS file_id, p.value AS value FROM props p "
            f"WHERE lower(p.key) = lower(?) AND p.file_id IN ({selection}) "
            f"ORDER BY p.file_id, p.idx IS NULL, p.idx",
            [shown, *params],
        ):
            if row["value"] is not None:
                grouped.setdefault(row["file_id"], []).append(row["value"])

    out = []
    for row in rows:
        item = {"path": row["path"]}
        if shown:
            item[shown] = ", ".join(grouped.get(row["id"], ()))
        out.append(item)
    return out


def orphans(conn: sqlite3.Connection, *, attachments: bool = False) -> list[dict]:
    """Files nothing links to.

    Notes by default. With *attachments*, unreferenced attachments too, which is the list
    worth reading before deleting anything. A file linking to itself does not save it.
    """
    kinds = ("note", "attachment") if attachments else ("note",)
    placeholders = ", ".join("?" for _ in kinds)
    rows = conn.execute(
        f"SELECT f.path AS path, f.kind AS kind, "
        f"       (SELECT count(*) FROM links l WHERE l.file_id = f.id) AS outgoing "
        f"FROM files f "
        f"WHERE f.kind IN ({placeholders}) "
        f"  AND NOT EXISTS (SELECT 1 FROM links l WHERE l.target_file_id = f.id "
        f"                  AND l.file_id != f.id) "
        f"ORDER BY f.path",
        kinds,
    ).fetchall()
    return [dict(row) for row in rows]


def info(conn: sqlite3.Connection) -> dict:
    """Counts and metadata, for checking the index is what you think it is."""
    def count(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]

    last_scan = conn.execute("SELECT value FROM meta WHERE key='last_scan'").fetchone()
    return {
        "vault": conn.execute("SELECT value FROM meta WHERE key='vault_path'").fetchone()[0],
        # Whoever is reading this needs to know whether the answers are current, so the age of
        # the index is part of the report rather than something to go digging for.
        "last_scan": (
            _dt.datetime.fromtimestamp(int(last_scan[0])).isoformat(timespec="seconds")
            if last_scan else None
        ),
        "hvk_version": conn.execute("SELECT value FROM meta WHERE key='hvk_version'").fetchone()[0],
        "schema_version": conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()[0],
        "files": count("SELECT count(*) FROM files"),
        "notes": count("SELECT count(*) FROM files WHERE kind='note'"),
        # Canvases and bases are parsed, so counting them as attachments would say the index
        # holds less than it does. Everything genuinely unparsed stays an attachment.
        "canvases": count("SELECT count(*) FROM files WHERE kind='canvas'"),
        "bases": count("SELECT count(*) FROM files WHERE kind='base'"),
        "attachments": count("SELECT count(*) FROM files WHERE kind='attachment'"),
        "links": count("SELECT count(*) FROM links"),
        "broken_links": count(
            "SELECT count(*) FROM links WHERE target_file_id IS NULL AND kind!='external'"
        ),
        "ambiguous_links": count("SELECT count(*) FROM links WHERE candidates > 1"),
        "tags": count("SELECT count(DISTINCT tag) FROM tags"),
        "tasks": count("SELECT count(*) FROM tasks"),
        "headings": count("SELECT count(*) FROM headings"),
        "parse_errors": count("SELECT count(*) FROM files WHERE parse_error IS NOT NULL"),
    }
