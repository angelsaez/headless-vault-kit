"""Scanning a vault into the index.

The initial scan walks the vault comparing mtime, size and hash against what is already
stored, so only what actually changed is reparsed — the same trick the app's persistent cache
uses. Exclusions follow list A of ADR-0002.

Resolution runs as a second pass, after every file is known, because a link can point at a
file the walk has not reached yet.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from hvk import __version__, db
from hvk.links import FileEntry, FileIndex
from hvk.parse.markdown import parse_note
from hvk.paths import Locations

# Operating-system litter that is never content (ADR-0002, list A).
LITTER = {".DS_Store", "Thumbs.db", "desktop.ini"}

KIND_BY_EXT = {"md": "note", "canvas": "canvas", "base": "base"}


@dataclass
class ScanStats:
    files: int = 0
    notes: int = 0
    added: int = 0
    changed: int = 0
    removed: int = 0
    unchanged: int = 0
    errors: int = 0
    seconds: float = 0.0

    def as_dict(self) -> dict:
        return {
            "files": self.files,
            "notes": self.notes,
            "added": self.added,
            "changed": self.changed,
            "removed": self.removed,
            "unchanged": self.unchanged,
            "errors": self.errors,
            "seconds": round(self.seconds, 3),
        }


def iter_vault_files(vault: Path):
    """Yield every indexable file in *vault*, in a stable order.

    One rule covers .obsidian/, .git/, .trash/ and whatever plugins invent next: anything
    whose name starts with a dot is not content. `.obsidian/app.json` is still read, but by
    explicit path, which is not the same as indexing it.
    """
    for root, dirnames, filenames in os.walk(vault):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for filename in sorted(filenames):
            if filename.startswith(".") or filename in LITTER:
                continue
            yield Path(root) / filename


def _relative(vault: Path, path: Path) -> str:
    return path.relative_to(vault).as_posix()


def _file_fields(vault: Path, path: Path, stat: os.stat_result, digest: str) -> dict:
    rel = _relative(vault, path)
    parent, _, name = rel.rpartition("/")
    stem, dot, ext = name.rpartition(".")
    if not dot:  # no extension at all
        stem, ext = name, ""
    ext = ext.lower()
    return {
        "path": rel,
        "name": name,
        "stem": stem,
        "stem_lower": stem.lower(),
        "parent": parent,
        "ext": ext,
        "kind": KIND_BY_EXT.get(ext, "attachment"),
        "mtime": stat.st_mtime_ns,
        "size": stat.st_size,
        "hash": digest,
    }


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _clear_derived(conn: sqlite3.Connection, file_id: int) -> None:
    for table in ("props", "tags", "headings", "blocks", "links", "tasks"):
        conn.execute(f"DELETE FROM {table} WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM fts WHERE rowid = ?", (file_id,))


def _store_note(conn: sqlite3.Connection, file_id: int, path: str, text: str) -> str | None:
    """Parse a note and write everything derived from it. Returns a parse error, if any."""
    stem = path.rsplit("/", 1)[-1].removesuffix(".md")
    note = parse_note(text, fallback_title=stem)

    conn.executemany(
        "INSERT INTO props(file_id, key, value, value_type, idx, inline, line) "
        "VALUES(?, ?, ?, ?, ?, ?, ?)",
        [(file_id, p.key, p.value, p.value_type, p.idx, int(p.inline), p.line) for p in note.props],
    )
    conn.executemany(
        "INSERT INTO tags(file_id, tag, source, line) VALUES(?, ?, ?, ?)",
        [(file_id, t.tag, t.source, t.line) for t in note.tags],
    )
    conn.executemany(
        "INSERT INTO headings(file_id, level, text, line) VALUES(?, ?, ?, ?)",
        [(file_id, h.level, h.text, h.line) for h in note.headings],
    )
    conn.executemany(
        "INSERT INTO blocks(file_id, block_id, line) VALUES(?, ?, ?)",
        [(file_id, b.block_id, b.line) for b in note.blocks],
    )
    conn.executemany(
        "INSERT INTO tasks(file_id, text, status, done, line, due, extra_json) "
        "VALUES(?, ?, ?, ?, ?, ?, ?)",
        [
            (
                file_id, t.text, t.status, int(t.done), t.line, t.due,
                # sort_keys keeps the stored JSON byte-identical across rebuilds.
                json.dumps(t.extra, ensure_ascii=False, sort_keys=True) if t.extra else None,
            )
            for t in note.tasks
        ],
    )
    # Links go in unresolved; the second pass fills target_file_id and candidates.
    conn.executemany(
        "INSERT INTO links(file_id, target_raw, target_file_id, subpath, kind, embed, "
        "candidates, line) VALUES(?, ?, NULL, ?, ?, ?, 0, ?)",
        [
            (file_id, ln.target_raw, ln.subpath, ln.kind, int(ln.embed), ln.line)
            for ln in note.links
        ],
    )
    conn.execute(
        "INSERT INTO fts(rowid, path, title, body) VALUES(?, ?, ?, ?)",
        (file_id, path, note.title, note.body),
    )
    return note.error


def _build_index(conn: sqlite3.Connection) -> FileIndex:
    rows = conn.execute("SELECT id, path, parent, name, stem, ext FROM files").fetchall()
    return FileIndex(
        FileEntry(r["id"], r["path"], r["parent"], r["name"], r["stem"], r["ext"]) for r in rows
    )


def resolve_links(conn: sqlite3.Connection) -> None:
    """Second pass: resolve every stored link against the current file index (ADR-0003)."""
    index = _build_index(conn)
    sources = {
        r["id"]: FileEntry(r["id"], r["path"], r["parent"], r["name"], r["stem"], r["ext"])
        for r in conn.execute("SELECT id, path, parent, name, stem, ext FROM files")
    }
    updates = []
    rows = conn.execute(
        "SELECT rowid, file_id, target_raw, kind FROM links WHERE kind != 'external'"
    ).fetchall()
    for row in rows:
        source = sources[row["file_id"]]
        result = index.resolve(row["target_raw"], source, decode=row["kind"] == "markdown")
        target_id = result.target.id if result.target else None
        updates.append((target_id, result.candidates, row["rowid"]))
    conn.executemany(
        "UPDATE links SET target_file_id = ?, candidates = ? WHERE rowid = ?", updates
    )


def index_file(
    conn: sqlite3.Connection,
    vault: Path,
    path: Path,
    previous: sqlite3.Row | dict | None,
    stats: ScanStats,
    *,
    rehash: bool = False,
) -> None:
    """Bring one file's rows up to date. Shared by the full scan and by the watcher.

    *previous* is the row already in ``files`` for this path, or None. With *rehash*, the
    mtime and size shortcut is skipped and the file is hashed no matter what -- which is the
    whole point of the nightly verification pass, since a sync can land identical metadata on
    different content.
    """
    try:
        stat = path.stat()
    except OSError:
        return
    rel = _relative(vault, path)
    stats.files += 1

    unchanged_metadata = (
        previous is not None
        and previous["mtime"] == stat.st_mtime_ns
        and previous["size"] == stat.st_size
    )
    if unchanged_metadata and not rehash:
        stats.unchanged += 1
        return

    data = path.read_bytes()
    digest = _hash(data)
    if previous is not None and previous["hash"] == digest:
        # Touched but identical: record the new mtime and skip the reparse.
        conn.execute("UPDATE files SET mtime = ? WHERE id = ?", (stat.st_mtime_ns, previous["id"]))
        stats.unchanged += 1
        return

    fields = _file_fields(vault, path, stat, digest)
    if previous is not None:
        file_id = previous["id"]
        conn.execute(
            "UPDATE files SET name=:name, stem=:stem, stem_lower=:stem_lower, "
            "parent=:parent, ext=:ext, kind=:kind, mtime=:mtime, size=:size, "
            "hash=:hash, parse_error=NULL WHERE id = :id",
            {**fields, "id": file_id},
        )
        _clear_derived(conn, file_id)
        stats.changed += 1
    else:
        cursor = conn.execute(
            "INSERT INTO files(path, name, stem, stem_lower, parent, ext, kind, "
            "mtime, size, hash) VALUES(:path, :name, :stem, :stem_lower, :parent, "
            ":ext, :kind, :mtime, :size, :hash)",
            fields,
        )
        file_id = cursor.lastrowid
        stats.added += 1

    if fields["kind"] == "note":
        stats.notes += 1
        error = _store_note(conn, file_id, rel, data.decode("utf-8", errors="replace"))
        if error:
            stats.errors += 1
            conn.execute("UPDATE files SET parse_error = ? WHERE id = ?", (error, file_id))


def forget_file(conn: sqlite3.Connection, row: sqlite3.Row | dict, stats: ScanStats) -> None:
    """Drop every row belonging to a file that is no longer in the vault."""
    conn.execute("DELETE FROM fts WHERE rowid = ?", (row["id"],))
    conn.execute("DELETE FROM files WHERE id = ?", (row["id"],))
    stats.removed += 1


def apply_changes(loc: Locations, paths) -> ScanStats:
    """Index exactly the paths given, and forget the ones that no longer exist.

    This is what the watcher calls, so that a single edit costs a single parse instead of a
    walk of the whole vault. Link resolution still runs over the whole table afterwards,
    because one new file can change what an untouched note's links mean.
    """
    started = time.monotonic()
    stats = ScanStats()

    conn = db.connect(loc.db_path, create=True)
    try:
        db.check_schema(conn)
        db.check_vault(conn, loc.vault)
        for path in sorted(set(paths)):
            rel = _relative(loc.vault, path)
            previous = conn.execute(
                "SELECT id, path, mtime, size, hash FROM files WHERE path = ?", (rel,)
            ).fetchone()
            if path.is_file():
                index_file(conn, loc.vault, path, previous, stats)
            elif previous is not None:
                forget_file(conn, previous, stats)
        if stats.added or stats.changed or stats.removed:
            resolve_links(conn)
            db.set_meta(conn, "last_scan", str(int(time.time())))
            conn.commit()
    finally:
        conn.close()

    stats.seconds = time.monotonic() - started
    return stats


def scan(loc: Locations, *, rebuild: bool = False, verify: bool = False) -> ScanStats:
    """Bring the index up to date with the vault, or rebuild it from scratch.

    With *verify*, every file is hashed rather than trusting mtime and size. That is the
    nightly safety net the plan asks for: if it reports anything as changed straight after a
    quiet period, the incremental path missed something.
    """
    started = time.monotonic()
    stats = ScanStats()

    if rebuild:
        # Start from an empty file rather than emptying tables, so that a rebuild also
        # recovers an index written by an older schema version.
        db.remove(loc.db_path)

    conn = db.connect(loc.db_path, create=True)
    try:
        db.check_schema(conn)
        if not rebuild:
            db.check_vault(conn, loc.vault)

        known = {
            r["path"]: r
            for r in conn.execute("SELECT id, path, mtime, size, hash FROM files")
        }
        seen: set[str] = set()

        for path in iter_vault_files(loc.vault):
            rel = _relative(loc.vault, path)
            seen.add(rel)
            index_file(conn, loc.vault, path, known.get(rel), stats, rehash=verify)

        for rel in sorted(set(known) - seen):
            forget_file(conn, known[rel], stats)

        # Links from untouched notes can change meaning when other files appear or vanish,
        # so resolution always runs over the whole table. It is cheap: no file is reread.
        resolve_links(conn)

        db.set_meta(conn, "vault_path", str(loc.vault))
        db.set_meta(conn, "hvk_version", __version__)
        db.set_meta(conn, "last_scan", str(int(time.time())))
        conn.commit()
    finally:
        conn.close()

    stats.seconds = time.monotonic() - started
    return stats
