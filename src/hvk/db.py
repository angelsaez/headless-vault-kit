"""SQLite schema and connection handling.

The schema follows the reference in the plan (§6) with the additions ADR-0003 announced on
``links``. Everything here is derived from the vault and rebuildable: dropping the database
and running ``hvk rebuild`` must always produce the same logical result.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Bumped whenever what gets *derived* changes, not only when a table does. Canvas support
# (ADR-0015) added no column and still made every existing index wrong-by-omission: the files
# were already there with their hashes, so nothing would have re-parsed them and a note on a
# board would have stayed orphaned until someone happened to touch the canvas. Refusing to run
# until 'hvk rebuild' is the mechanism that already exists for exactly this, and a rebuild is
# seconds.
SCHEMA_VERSION = 4

# FTS5 with diacritics folded, so that searching "cafe" finds "café" -- which matters in a
# vault written in Spanish.
SCHEMA = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE files (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,   -- vault-relative, always with '/' separators
    name        TEXT NOT NULL,          -- basename with extension
    stem        TEXT NOT NULL,          -- basename without extension
    stem_lower  TEXT NOT NULL,          -- case-insensitive matching for link resolution
    parent      TEXT NOT NULL,          -- vault-relative folder, '' at the root
    ext         TEXT NOT NULL,          -- lowercased, no dot, '' when there is none
    kind        TEXT NOT NULL,          -- 'note' | 'attachment'
    ctime       INTEGER NOT NULL,       -- creation time where the filesystem has one
    mtime       INTEGER NOT NULL,
    size        INTEGER NOT NULL,
    hash        TEXT NOT NULL,          -- sha256 of the file bytes
    parse_error TEXT                    -- NULL when parsing succeeded
);

-- A list-valued property produces one row per item, with idx preserving order. That keeps
-- aliases queryable (key='aliases') without a table of their own.
CREATE TABLE props (
    file_id    INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    key        TEXT NOT NULL,
    value      TEXT,
    value_type TEXT NOT NULL,           -- string|number|bool|null|date|datetime|list|map
    idx        INTEGER,                 -- position within a list, NULL for scalars
    inline     INTEGER NOT NULL,        -- 1 for Dataview-style 'key:: value'
    line       INTEGER NOT NULL
);

CREATE TABLE tags (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,              -- without '#', nesting preserved: 'home/nested'
    source  TEXT NOT NULL,              -- 'frontmatter' | 'inline'
    line    INTEGER NOT NULL
);

CREATE TABLE headings (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    level   INTEGER NOT NULL,
    text    TEXT NOT NULL,
    line    INTEGER NOT NULL
);

CREATE TABLE blocks (
    file_id  INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    block_id TEXT NOT NULL,
    line     INTEGER NOT NULL
);

-- target_file_id NULL means unresolved (broken) or external.
-- candidates is how many files matched before the tie-break ran: > 1 marks a link where our
-- rule had to choose and the app may choose differently (ADR-0003).
CREATE TABLE links (
    file_id        INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    target_raw     TEXT NOT NULL,
    target_file_id INTEGER REFERENCES files(id) ON DELETE SET NULL,
    subpath        TEXT,                -- '#Heading' or '#^block-id', without the target
    kind           TEXT NOT NULL,       -- 'wikilink' | 'markdown' | 'external'
    embed          INTEGER NOT NULL,
    candidates     INTEGER NOT NULL,
    line           INTEGER NOT NULL
);

CREATE TABLE tasks (
    file_id    INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    text       TEXT NOT NULL,
    status     TEXT NOT NULL,           -- the raw character between the brackets
    done       INTEGER NOT NULL,        -- 1 for 'x'/'X'
    line       INTEGER NOT NULL,
    due        TEXT,
    extra_json TEXT
);

CREATE INDEX idx_files_stem       ON files(stem_lower);
CREATE INDEX idx_files_parent     ON files(parent);
CREATE INDEX idx_props_key        ON props(key, value);
CREATE INDEX idx_props_file       ON props(file_id);
CREATE INDEX idx_tags_tag         ON tags(tag);
CREATE INDEX idx_tags_file        ON tags(file_id);
CREATE INDEX idx_headings_file    ON headings(file_id);
CREATE INDEX idx_blocks_id        ON blocks(block_id);
CREATE INDEX idx_links_target     ON links(target_file_id);
CREATE INDEX idx_links_file       ON links(file_id);
CREATE INDEX idx_tasks_file       ON tasks(file_id);
CREATE INDEX idx_tasks_done       ON tasks(done);
CREATE INDEX idx_tasks_due        ON tasks(due);

CREATE VIRTUAL TABLE fts USING fts5(
    path, title, body,
    tokenize = "unicode61 remove_diacritics 2"
);
"""


class IndexError_(Exception):
    """Raised when the index is missing, stale or written by another version."""


def connect(db_path: Path, *, create: bool = False) -> sqlite3.Connection:
    """Open the index database, creating the schema when asked to."""
    exists = db_path.exists()
    if not exists and not create:
        raise IndexError_(
            f"no index at {db_path}. Run 'hvk scan' first."
        )
    if create:
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # WAL keeps the index queryable while it is being rewritten, which is the normal case
    # when the agent works and sync delivers changes at the same time (ADR-0002).
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if not exists:
        conn.executescript(SCHEMA)
        set_meta(conn, "schema_version", str(SCHEMA_VERSION))
        conn.commit()
    return conn


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def check_schema(conn: sqlite3.Connection) -> None:
    """Fail loudly on an index written by a different schema version."""
    found = get_meta(conn, "schema_version")
    if found != str(SCHEMA_VERSION):
        raise IndexError_(
            f"index schema version is {found}, this hvk expects {SCHEMA_VERSION}. "
            f"Run 'hvk rebuild'."
        )


def check_vault(conn: sqlite3.Connection, vault: Path) -> None:
    """Fail when the index belongs to a different vault than the one being queried."""
    recorded = get_meta(conn, "vault_path")
    if recorded is not None and recorded != str(vault):
        raise IndexError_(
            f"this index was built for {recorded}, not for {vault}. Either the vault moved "
            f"or --index points at the wrong directory. Run 'hvk rebuild' to rebuild it."
        )


def remove(db_path: Path) -> None:
    """Delete the database and its write-ahead files.

    This is what ``hvk rebuild`` does before scanning. Deleting rather than emptying tables
    means a rebuild also recovers from an index written by an older schema -- which matters,
    because rebuilding is exactly what the version-mismatch error tells people to do.
    """
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(db_path) + suffix)
        try:
            candidate.unlink(missing_ok=True)
        except OSError as exc:
            raise IndexError_(
                f"cannot delete {candidate}: {exc}. Something else is holding the index open "
                f"-- a running 'hvk watch', most likely. Stop it and try again."
            ) from exc
