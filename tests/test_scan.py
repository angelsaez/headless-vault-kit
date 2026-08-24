"""Scanning: determinism, incremental behaviour and the exclusion rules of ADR-0002."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest

from hvk import db, paths
from hvk import scan as scanner
from conftest import VAULTS

VAULT_NAMES = ["basic", "links", "frontmatter", "unicode", "canvas"]

DUMP_TABLES = {
    "files": ["path", "name", "stem", "parent", "ext", "kind", "size", "hash"],
    "props": ["key", "value", "value_type", "idx", "inline", "line"],
    "tags": ["tag", "source", "line"],
    "headings": ["level", "text", "line"],
    "blocks": ["block_id", "line"],
    "links": ["target_raw", "subpath", "kind", "embed", "candidates", "line"],
    "tasks": ["text", "status", "done", "line"],
}


def logical_dump(db_path: Path) -> str:
    """A fingerprint of the index contents that ignores row ids and insertion order."""
    conn = sqlite3.connect(db_path)
    digest = hashlib.sha256()
    try:
        for table, columns in DUMP_TABLES.items():
            joined = ", ".join(f"t.{c}" for c in columns)
            if table == "files":
                sql = f"SELECT {joined} FROM files t ORDER BY {joined}"
            else:
                sql = (
                    f"SELECT f.path, {joined} FROM {table} t "
                    f"JOIN files f ON f.id = t.file_id ORDER BY f.path, {joined}"
                )
            rows = conn.execute(sql).fetchall()
            digest.update(f"::{table}:{len(rows)}::".encode())
            for row in rows:
                digest.update(repr(row).encode("utf-8"))
        rows = conn.execute(
            "SELECT f.path, fts.title, fts.body FROM fts JOIN files f ON f.id = fts.rowid "
            "ORDER BY f.path"
        ).fetchall()
        digest.update(f"::fts:{len(rows)}::".encode())
        for row in rows:
            digest.update(repr(row).encode("utf-8"))
    finally:
        conn.close()
    return digest.hexdigest()


@pytest.mark.parametrize("name", VAULT_NAMES)
def test_rebuild_is_deterministic(tmp_path, name):
    """The plan's exit criterion: drop the database, rebuild, get the same result."""
    location = paths.Locations(vault=(VAULTS / name).resolve(), index_dir=tmp_path / name)

    scanner.scan(location)
    after_scan = logical_dump(location.db_path)

    scanner.scan(location, rebuild=True)
    after_rebuild = logical_dump(location.db_path)

    shutil.rmtree(location.index_dir)
    scanner.scan(location)
    from_scratch = logical_dump(location.db_path)

    assert after_scan == after_rebuild == from_scratch


def test_second_scan_reparses_nothing(index):
    location, conn, first = index("basic")
    assert first.added == first.files
    second = scanner.scan(location)
    assert second.unchanged == second.files
    assert second.added == second.changed == second.removed == 0


def test_dot_directories_are_not_indexed(index):
    _, conn, _ = index("basic")
    paths_indexed = [r["path"] for r in conn.execute("SELECT path FROM files")]
    assert not any(p.startswith(".") or "/." in p for p in paths_indexed)
    assert "attachments/diagram.png" in paths_indexed


def test_attachments_are_inventoried_but_not_parsed(index):
    _, conn, _ = index("basic")
    row = conn.execute("SELECT * FROM files WHERE path = 'attachments/diagram.png'").fetchone()
    assert row["kind"] == "attachment"
    assert conn.execute(
        "SELECT count(*) FROM headings WHERE file_id = ?", (row["id"],)
    ).fetchone()[0] == 0


def test_changed_file_is_reparsed_and_deletions_are_noticed(tmp_path, index):
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "One.md").write_text("# One\n\n[[Two]]\n", encoding="utf-8", newline="\n")
    (vault / "Two.md").write_text("# Two\n", encoding="utf-8", newline="\n")

    location, conn, stats = index(vault)
    assert stats.added == 2
    assert conn.execute(
        "SELECT count(*) FROM links WHERE target_file_id IS NOT NULL"
    ).fetchone()[0] == 1

    (vault / "Two.md").unlink()
    after = scanner.scan(location)
    assert after.removed == 1
    # The surviving link must go stale even though One.md itself never changed.
    assert conn.execute(
        "SELECT count(*) FROM links WHERE target_file_id IS NULL"
    ).fetchone()[0] == 1


def test_a_new_file_can_make_an_existing_link_ambiguous(tmp_path, index):
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "Sub").mkdir()
    (vault / "Source.md").write_text("[[Target]]\n", encoding="utf-8", newline="\n")
    (vault / "Target.md").write_text("# Target\n", encoding="utf-8", newline="\n")

    location, conn, _ = index(vault)
    assert conn.execute("SELECT candidates FROM links").fetchone()[0] == 1

    (vault / "Sub" / "Target.md").write_text("# Other\n", encoding="utf-8", newline="\n")
    scanner.scan(location)
    row = conn.execute(
        "SELECT candidates, target_file_id FROM links"
    ).fetchone()
    assert row["candidates"] == 2, "resolution must be revisited when the file set changes"


def test_touching_a_file_without_changing_it_does_not_reparse(tmp_path, index):
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    note = vault / "One.md"
    note.write_text("# One\n", encoding="utf-8", newline="\n")

    location, _, _ = index(vault)
    contents = note.read_bytes()
    note.write_bytes(contents)  # same bytes, new mtime

    stats = scanner.scan(location)
    assert stats.changed == 0
    assert stats.unchanged == 1


def test_rebuild_recovers_from_an_older_schema(tmp_path, index):
    """The version-mismatch error tells people to rebuild, so rebuilding has to work."""
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "One.md").write_text("# One\n", encoding="utf-8", newline="\n")

    location, conn, _ = index(vault)
    conn.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    with pytest.raises(db.IndexError_, match="rebuild"):
        scanner.scan(location)

    stats = scanner.scan(location, rebuild=True)
    assert stats.added == 1
    fresh = db.connect(location.db_path)
    try:
        db.check_schema(fresh)
    finally:
        fresh.close()


def test_rebuild_starts_from_an_empty_database(tmp_path, index):
    """Stale rows from a previous shape of the index must not survive a rebuild."""
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "One.md").write_text("# One\n", encoding="utf-8", newline="\n")

    location, conn, _ = index(vault)
    conn.execute("INSERT INTO tags(file_id, tag, source, line) VALUES(1, 'ghost', 'inline', 1)")
    conn.commit()
    conn.close()

    scanner.scan(location, rebuild=True)
    fresh = db.connect(location.db_path)
    try:
        assert fresh.execute("SELECT count(*) FROM tags WHERE tag='ghost'").fetchone()[0] == 0
    finally:
        fresh.close()
