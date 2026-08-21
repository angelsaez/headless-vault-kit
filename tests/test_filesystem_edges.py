"""Cases that cannot be committed to git, so the vault is built at run time.

Two files whose names differ only in case, or only in Unicode normalisation form, cannot be
checked out on Windows or macOS. They are real all the same -- a Linux server is exactly where
they show up -- so they are built here and skipped where the filesystem cannot hold them.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

NFC = unicodedata.normalize("NFC", "Café")
NFD = unicodedata.normalize("NFD", "Café")


def _make_vault(root: Path) -> Path:
    (root / ".obsidian").mkdir(parents=True)
    return root


def _write(path: Path, text: str) -> bool:
    """Write a file, reporting whether the filesystem actually kept it apart from its twin."""
    before = {p.name for p in path.parent.iterdir()}
    path.write_text(text, encoding="utf-8", newline="\n")
    return len({p.name for p in path.parent.iterdir()} - before) == 1


def test_case_only_duplicates_are_flagged_and_exact_case_wins(tmp_path, index):
    vault = _make_vault(tmp_path / "vault")
    (vault / "Note.md").write_text("# Upper\n", encoding="utf-8", newline="\n")
    if not _write(vault / "note.md", "# Lower\n"):
        pytest.skip("case-insensitive filesystem: both files cannot coexist")

    (vault / "Source.md").write_text("[[note]]\n", encoding="utf-8", newline="\n")
    _, conn, _ = index(vault)

    row = conn.execute(
        "SELECT l.candidates, t.path AS resolved FROM links l "
        "LEFT JOIN files t ON t.id = l.target_file_id "
        "JOIN files f ON f.id = l.file_id WHERE f.path = 'Source.md'"
    ).fetchone()
    assert row["candidates"] == 2, "both files match case-insensitively, so it is ambiguous"
    assert row["resolved"] == "note.md", "the exact-case match wins the tie-break"


def test_case_insensitive_links_still_resolve(tmp_path, index):
    vault = _make_vault(tmp_path / "vault")
    (vault / "Note.md").write_text("# Note\n", encoding="utf-8", newline="\n")
    (vault / "Source.md").write_text("[[nOtE]]\n", encoding="utf-8", newline="\n")
    _, conn, _ = index(vault)

    resolved = conn.execute(
        "SELECT t.path FROM links l JOIN files t ON t.id = l.target_file_id"
    ).fetchone()
    assert resolved[0] == "Note.md"


def test_normalisation_only_duplicates_are_flagged(tmp_path, index):
    vault = _make_vault(tmp_path / "vault")
    (vault / f"{NFC}.md").write_text("# Precomposed\n", encoding="utf-8", newline="\n")
    if not _write(vault / f"{NFD}.md", "# Decomposed\n"):
        pytest.skip("this filesystem normalises filenames: both forms cannot coexist")

    (vault / "Source.md").write_text(f"[[{NFC}]]\n", encoding="utf-8", newline="\n")
    _, conn, _ = index(vault)

    row = conn.execute(
        "SELECT l.candidates FROM links l JOIN files f ON f.id = l.file_id "
        "WHERE f.path = 'Source.md'"
    ).fetchone()
    assert row["candidates"] == 2


def test_a_link_written_in_nfd_finds_a_file_stored_in_nfc(tmp_path, index):
    """The macOS-writes, Linux-reads case: without folding, this link would be broken."""
    vault = _make_vault(tmp_path / "vault")
    (vault / f"{NFC}.md").write_text("# Precomposed\n", encoding="utf-8", newline="\n")
    (vault / "Source.md").write_text(f"[[{NFD}]]\n", encoding="utf-8", newline="\n")
    _, conn, _ = index(vault)

    resolved = conn.execute(
        "SELECT t.path FROM links l LEFT JOIN files t ON t.id = l.target_file_id "
        "JOIN files f ON f.id = l.file_id WHERE f.path = 'Source.md'"
    ).fetchone()
    assert resolved[0] is not None, "NFD and NFC must fold to the same key"


def test_files_being_written_are_not_indexed_as_empty(tmp_path, index):
    """A note whose bytes change between scans must be reparsed, not left stale."""
    vault = _make_vault(tmp_path / "vault")
    note = vault / "Growing.md"
    note.write_text("# Partial\n", encoding="utf-8", newline="\n")

    location, conn, _ = index(vault)
    assert conn.execute("SELECT count(*) FROM headings").fetchone()[0] == 1

    note.write_text("# Partial\n\n## Rest arrived\n", encoding="utf-8", newline="\n")
    from hvk import scan as scanner

    scanner.scan(location)
    assert conn.execute("SELECT count(*) FROM headings").fetchone()[0] == 2
