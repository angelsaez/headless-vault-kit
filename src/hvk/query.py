"""Read-only queries over the index.

This is what replaces reading files one by one: the agent asks the index and gets an answer
in milliseconds instead of spending tokens on the whole vault.
"""

from __future__ import annotations

import re
import sqlite3

from hvk.links import FileEntry, FileIndex

FILTER_RE = re.compile(r"\b(path|tag):(\"[^\"]+\"|\S+)")


class QueryError(Exception):
    """Raised for a malformed query or a target that cannot be found."""


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
        "SELECT id, path, parent, name, stem, ext FROM files WHERE path = ?", (target,)
    ).fetchone()
    if row:
        return row

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
    params: list = [text]
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


def info(conn: sqlite3.Connection) -> dict:
    """Counts and metadata, for checking the index is what you think it is."""
    def count(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]

    return {
        "vault": conn.execute("SELECT value FROM meta WHERE key='vault_path'").fetchone()[0],
        "hvk_version": conn.execute("SELECT value FROM meta WHERE key='hvk_version'").fetchone()[0],
        "schema_version": conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()[0],
        "files": count("SELECT count(*) FROM files"),
        "notes": count("SELECT count(*) FROM files WHERE kind='note'"),
        "attachments": count("SELECT count(*) FROM files WHERE kind!='note'"),
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
