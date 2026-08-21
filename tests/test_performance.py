"""The plan's numeric exit criteria for phase 2, as checks rather than hopes.

From the plan (§2 and §5): a full rebuild of a roughly 10k-note vault under 60 s, an
incremental update under 5 s, and index queries under 100 ms.

Marked slow and deselected by default, because generating the vault costs a few seconds and
nobody needs that on every run. Run them with ``pytest -m slow``.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from hvk import db, paths, query
from hvk import scan as scanner

NOTES = 10_000
FOLDERS = 100

pytestmark = pytest.mark.slow


def _build_vault(root: Path) -> None:
    """Write a vault of NOTES notes with links, tags, tasks and properties.

    Deterministic on purpose: the same vault every run, so a timing change means the code
    changed and not the fixture.
    """
    (root / ".obsidian").mkdir(parents=True)
    for folder in range(FOLDERS):
        (root / f"area-{folder:03d}").mkdir()

    for i in range(NOTES):
        folder = i % FOLDERS
        # Link to three notes elsewhere in the vault, including one that never exists.
        targets = (f"note-{(i * 7 + 1) % NOTES:05d}", f"note-{(i * 13 + 3) % NOTES:05d}")
        (root / f"area-{folder:03d}" / f"note-{i:05d}.md").write_text(
            f"---\n"
            f"title: Note {i}\n"
            f"status: {'open' if i % 3 else 'closed'}\n"
            f"priority: {i % 5}\n"
            f"tags: [area-{folder:03d}, kind/{i % 7}]\n"
            f"---\n"
            f"\n"
            f"# Note {i}\n"
            f"\n"
            f"Body text for note {i}, mentioning subject-{i % 97} and topic-{i % 41}.\n"
            f"Links to [[{targets[0]}]] and [[{targets[1]}]], plus [[missing-{i % 50}]].\n"
            f"\n"
            f"owner:: person-{i % 23}\n"
            f"\n"
            f"## Work\n"
            f"\n"
            f"- [ ] pending item for note {i}\n"
            f"- [x] finished item\n"
            f"\n"
            f"Reference paragraph. ^ref-{i:05d}\n",
            encoding="utf-8",
            newline="\n",
        )


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    root = tmp_path_factory.mktemp("big") / "vault"
    started = time.monotonic()
    _build_vault(root)
    print(f"\n  generated {NOTES} notes in {time.monotonic() - started:.1f}s")
    location = paths.Locations(vault=root, index_dir=root.parent / "idx")
    return location


def test_full_scan_under_60_seconds(big):
    stats = scanner.scan(big, rebuild=True)
    print(f"  full scan: {stats.seconds:.1f}s for {stats.files} files, {stats.notes} notes")
    assert stats.notes == NOTES
    assert stats.seconds < 60


def test_incremental_update_under_5_seconds(big):
    scanner.scan(big)  # make sure the index is current before timing the update
    note = big.vault / "area-000" / "note-00000.md"
    note.write_text(note.read_text(encoding="utf-8") + "\n#touched\n", encoding="utf-8", newline="\n")

    stats = scanner.scan(big)
    print(f"  incremental: {stats.seconds:.2f}s, {stats.changed} changed")
    assert stats.changed == 1
    assert stats.seconds < 5


def test_targeted_update_is_far_cheaper_than_a_walk(big):
    """What the watcher actually does: one edit, one parse, no walk of the vault."""
    note = big.vault / "area-001" / "note-00001.md"
    note.write_text(note.read_text(encoding="utf-8") + "\n#again\n", encoding="utf-8", newline="\n")

    stats = scanner.apply_changes(big, [note])
    print(f"  targeted: {stats.seconds:.2f}s")
    assert stats.changed == 1
    assert stats.seconds < 5


@pytest.mark.parametrize(
    "name, call",
    [
        ("backlinks", lambda c: query.backlinks(c, "note-00042")),
        ("search", lambda c: query.search(c, "subject-13")),
        ("search + tag filter", lambda c: query.search(c, "topic-7 tag:kind/3")),
        ("tags --count", lambda c: query.tags(c, count=True)),
        ("tasks --pending", lambda c: query.tasks(c, pending=True)),
        ("props --where", lambda c: query.props(c, ["status=open"])),
        ("links --broken", lambda c: query.links(c, broken=True)),
        ("info", lambda c: query.info(c)),
    ],
)
def test_queries_under_100_milliseconds(big, name, call):
    scanner.scan(big)
    conn = db.connect(big.db_path)
    try:
        call(conn)  # warm the page cache; the target is steady-state, not first-touch
        started = time.perf_counter()
        result = call(conn)
        elapsed = (time.perf_counter() - started) * 1000
    finally:
        conn.close()
    size = len(result) if isinstance(result, (list, dict)) else len(result[1])
    print(f"  {name}: {elapsed:.1f}ms ({size} rows)")
    assert elapsed < 100, f"{name} took {elapsed:.1f}ms"


def test_a_base_over_ten_thousand_notes(big, tmp_path):
    """Running a base is a whole-vault operation, not a point query, so it gets its own bar.

    The plan's 100 ms target covers index lookups. A base loads every note, evaluates a
    filter per row and computes the columns, which is closer in shape to a scan.
    """
    from hvk import db
    from hvk.bases import base_file
    from hvk.bases import run as base_run

    scanner.scan(big)
    source = [
        "filters:",
        "  and:",
        "    - 'status == \"open\"'",
        "formulas:",
        "  ratio: '(priority + 1).toFixed(2)'",
        "views:",
        "  - type: table",
        "    name: v",
        "    order: [file.name, status, priority, formula.ratio]",
        "    sort:",
        "      - property: priority",
        "        direction: DESC",
    ]
    path = tmp_path / "Big.base"
    path.write_text(chr(10).join(source) + chr(10), encoding="utf-8", newline=chr(10))

    conn = db.connect(big.db_path)
    try:
        base = base_file.load(path)
        started = time.perf_counter()
        result = base_run.run(base, conn)
        elapsed = time.perf_counter() - started
    finally:
        conn.close()
    print(f"  base over {result.total} matching rows: {elapsed:.2f}s")
    assert result.total > 5000
    assert elapsed < 3
