"""The watcher: debounce, stability, exclusions, and the nightly verification pass.

Most of this runs without threads or sleeping. ``ChangeQueue`` takes the current time as an
argument precisely so its behaviour can be tested with a made-up clock; only the last test
starts a real observer.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from hvk import db, paths, watch
from hvk import scan as scanner


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    (root / "One.md").write_text("# One\n\n[[Two]]\n", encoding="utf-8", newline="\n")
    return root


# -- what is worth reacting to (ADR-0002, lists A and B) --------------------------------

@pytest.mark.parametrize(
    "relative, watchable",
    [
        ("Note.md", True),
        ("Folder/Note.md", True),
        ("attachments/diagram.png", True),
        (".obsidian/workspace.json", False),
        (".obsidian/app.json", False),
        (".git/HEAD", False),
        (".trash/Deleted.md", False),
        (".hidden-note.md", False),
        ("Note.md.tmp", False),
        ("Note.partial", False),
        ("Note.md~", False),
        ("~$Note.md", False),
        (".DS_Store", False),
        ("Folder/.DS_Store", False),
    ],
)
def test_is_watchable(vault, relative, watchable):
    assert watch.is_watchable(vault, vault / relative) is watchable


def test_paths_outside_the_vault_are_ignored(vault, tmp_path):
    assert watch.is_watchable(vault, tmp_path / "elsewhere.md") is False


# -- debounce and stability, on a clock we control --------------------------------------

def test_a_path_is_held_until_it_goes_quiet(vault):
    queue = watch.ChangeQueue(debounce=1.0)
    note = vault / "One.md"

    queue.record(note, now=0.0)
    assert queue.release(now=0.5) == [], "still inside the debounce window"

    # First release past the window only measures the file; the second confirms it settled.
    assert queue.release(now=1.5) == []
    assert queue.release(now=1.6) == [note]


def test_further_events_restart_the_window(vault):
    queue = watch.ChangeQueue(debounce=1.0)
    note = vault / "One.md"

    queue.record(note, now=0.0)
    queue.record(note, now=0.9)
    assert queue.release(now=1.5) == [], "the window restarted at 0.9"
    assert queue.release(now=2.0) == []
    assert queue.release(now=2.1) == [note]


def test_a_growing_file_is_not_released(vault):
    """The case the plan cares about: a large file still arriving over sync."""
    queue = watch.ChangeQueue(debounce=0.0)
    note = vault / "Growing.md"
    note.write_text("first\n", encoding="utf-8", newline="\n")

    assert queue.release(now=1.0) == []  # nothing recorded yet
    queue.record(note, now=0.0)
    assert queue.release(now=1.0) == [], "first look only measures"

    note.write_text("first\nsecond\n", encoding="utf-8", newline="\n")
    assert queue.release(now=2.0) == [], "it moved between looks, so hold it"

    assert queue.release(now=3.0) == [note], "still at last, so release it"


def test_a_deleted_path_is_released_at_once(vault):
    queue = watch.ChangeQueue(debounce=0.0)
    missing = vault / "Gone.md"
    queue.record(missing, now=0.0)
    assert queue.release(now=1.0) == [missing], "a deletion is settled by definition"


def test_released_paths_are_forgotten(vault):
    queue = watch.ChangeQueue(debounce=0.0)
    note = vault / "One.md"
    queue.record(note, now=0.0)
    queue.release(now=1.0)
    assert queue.release(now=2.0) == [note]
    assert queue.release(now=3.0) == []
    assert queue.pending == {}


# -- indexing a subset ------------------------------------------------------------------

def test_apply_changes_indexes_only_what_it_is_given(vault, tmp_path):
    location = paths.Locations(vault=vault, index_dir=tmp_path / "idx")
    scanner.scan(location)

    (vault / "Two.md").write_text("# Two\n", encoding="utf-8", newline="\n")
    (vault / "Three.md").write_text("# Three\n", encoding="utf-8", newline="\n")

    stats = scanner.apply_changes(location, [vault / "Two.md"])
    assert stats.added == 1

    conn = db.connect(location.db_path)
    try:
        indexed = {r["path"] for r in conn.execute("SELECT path FROM files")}
    finally:
        conn.close()
    assert indexed == {"One.md", "Two.md"}, "Three.md was never handed over"


def test_a_new_file_repairs_an_existing_broken_link(vault, tmp_path):
    """One.md links to Two.md, which does not exist yet and is never itself re-read."""
    location = paths.Locations(vault=vault, index_dir=tmp_path / "idx")
    scanner.scan(location)
    conn = db.connect(location.db_path)
    try:
        assert conn.execute(
            "SELECT count(*) FROM links WHERE target_file_id IS NULL"
        ).fetchone()[0] == 1

        (vault / "Two.md").write_text("# Two\n", encoding="utf-8", newline="\n")
        scanner.apply_changes(location, [vault / "Two.md"])

        assert conn.execute(
            "SELECT count(*) FROM links WHERE target_file_id IS NOT NULL"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_apply_changes_forgets_a_deleted_file(vault, tmp_path):
    location = paths.Locations(vault=vault, index_dir=tmp_path / "idx")
    scanner.scan(location)
    (vault / "One.md").unlink()

    stats = scanner.apply_changes(location, [vault / "One.md"])
    assert stats.removed == 1

    conn = db.connect(location.db_path)
    try:
        assert conn.execute("SELECT count(*) FROM files").fetchone()[0] == 0
    finally:
        conn.close()


def test_drain_skips_paths_that_are_never_watched(vault, tmp_path):
    location = paths.Locations(vault=vault, index_dir=tmp_path / "idx")
    scanner.scan(location)
    (vault / "draft.tmp").write_text("x", encoding="utf-8", newline="\n")

    stats = watch.drain(location, [vault / "draft.tmp"])
    assert stats.added == 0


# -- the nightly safety net --------------------------------------------------------------

def test_verify_rehashes_files_the_shortcut_would_skip(vault, tmp_path):
    """Content changed behind identical metadata is exactly what the shortcut misses."""
    location = paths.Locations(vault=vault, index_dir=tmp_path / "idx")
    scanner.scan(location)

    note = vault / "One.md"
    original = note.stat()
    note.write_text("# One\n\n[[Two]]\n\n#drifted\n", encoding="utf-8", newline="\n")
    import os

    os.utime(note, ns=(original.st_atime_ns, original.st_mtime_ns))
    # Same mtime, and the fixture makes the size match too, so a normal scan sees nothing.

    if note.stat().st_size == original.st_size:
        assert scanner.scan(location).changed == 0
    assert scanner.scan(location, verify=True).changed == 1

    conn = db.connect(location.db_path)
    try:
        assert conn.execute("SELECT count(*) FROM tags WHERE tag='drifted'").fetchone()[0] == 1
    finally:
        conn.close()


def test_verify_finds_nothing_when_the_index_is_current(vault, tmp_path):
    location = paths.Locations(vault=vault, index_dir=tmp_path / "idx")
    scanner.scan(location)
    stats = scanner.scan(location, verify=True)
    assert stats.changed == 0 and stats.removed == 0 and stats.added == 0


# -- one real observer -------------------------------------------------------------------

def test_the_watcher_indexes_a_new_note(vault, tmp_path):
    location = paths.Locations(vault=vault, index_dir=tmp_path / "idx")
    scanner.scan(location)

    stop = threading.Event()
    thread = threading.Thread(
        target=watch.watch,
        args=(location,),
        kwargs={"debounce": 0.2, "poll": 0.05, "stop": stop.is_set},
        daemon=True,
    )
    thread.start()
    try:
        time.sleep(0.4)
        (vault / "Two.md").write_text("# Two\n", encoding="utf-8", newline="\n")

        deadline = time.monotonic() + 15
        found = False
        while time.monotonic() < deadline and not found:
            conn = db.connect(location.db_path)
            try:
                found = conn.execute(
                    "SELECT count(*) FROM files WHERE path = 'Two.md'"
                ).fetchone()[0] == 1
            finally:
                conn.close()
            if not found:
                time.sleep(0.1)
        assert found, "the watcher never picked up the new note"
    finally:
        stop.set()
        thread.join(timeout=10)
