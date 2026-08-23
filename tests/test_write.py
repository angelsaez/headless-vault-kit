"""Writing to the vault: what survives a round trip, and what is refused (ADR-0007).

This is the first code in the project that can destroy something, so the refusals carry more
weight here than the successes. Each one exists because the failure it prevents would be
silent, and in a vault synced across devices, permanent.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hvk import write
from hvk.write import ConflictError, WriteError


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    return root


def put(vault: Path, name: str, data: bytes) -> Path:
    path = vault / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# -- the round trip ------------------------------------------------------------------------

def test_an_untouched_round_trip_changes_nothing(vault):
    path = put(vault, "Note.md", b"# Title\n\nBody\n")
    original = write.read(path, vault=vault)
    assert write.write(path, original.text, original, vault=vault) is False
    assert path.read_bytes() == b"# Title\n\nBody\n"


def test_crlf_files_stay_crlf(vault):
    path = put(vault, "Windows.md", b"# Title\r\n\r\nBody\r\n")
    original = write.read(path, vault=vault)
    assert original.newline == "\r\n"
    assert original.text == "# Title\n\nBody"

    write.write(path, original.text + "\nMore", original, vault=vault)
    assert path.read_bytes() == b"# Title\r\n\r\nBody\r\nMore\r\n"


def test_lf_files_do_not_acquire_crlf_on_windows(vault):
    path = put(vault, "Unix.md", b"line\n")
    original = write.read(path, vault=vault)
    write.write(path, "line\nsecond", original, vault=vault)
    assert b"\r" not in path.read_bytes()


def test_a_missing_final_newline_stays_missing(vault):
    path = put(vault, "NoNewline.md", b"no trailing newline")
    original = write.read(path, vault=vault)
    assert original.final_newline is False
    write.write(path, "changed", original, vault=vault)
    assert path.read_bytes() == b"changed"


def test_a_present_final_newline_stays_present(vault):
    path = put(vault, "Note.md", b"text\n")
    original = write.read(path, vault=vault)
    write.write(path, "changed", original, vault=vault)
    assert path.read_bytes() == b"changed\n"


def test_a_byte_order_mark_is_written_back(vault):
    path = put(vault, "Bom.md", "﻿# Title\n".encode("utf-8"))
    original = write.read(path, vault=vault)
    assert original.bom is True
    assert original.text == "# Title"
    write.write(path, "# Other", original, vault=vault)
    assert path.read_bytes() == "﻿# Other\n".encode("utf-8")


def test_a_file_without_a_bom_does_not_gain_one(vault):
    path = put(vault, "Plain.md", b"# Title\n")
    original = write.read(path, vault=vault)
    write.write(path, "# Other", original, vault=vault)
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_mixed_line_endings_are_noticed_and_the_majority_wins(vault):
    path = put(vault, "Mixed.md", b"one\r\ntwo\r\nthree\n")
    original = write.read(path, vault=vault)
    assert original.mixed_newlines is True
    assert original.newline == "\r\n"


def test_unicode_content_survives(vault):
    path = put(vault, "Unicode.md", "# Café 日本語 🚀\n".encode("utf-8"))
    original = write.read(path, vault=vault)
    write.write(path, original.text + "\nmás", original, vault=vault)
    assert path.read_text(encoding="utf-8") == "# Café 日本語 🚀\nmás\n"


def test_frontmatter_is_never_reserialised(vault):
    """Quoting, key order and comments survive because the YAML is never parsed."""
    raw = b"---\nzeta: 1\n# a comment\nalpha:   'single quoted'\n---\n\nBody\n"
    path = put(vault, "Front.md", raw)
    original = write.read(path, vault=vault)
    write.write(path, original.text + "\nappended", original, vault=vault)
    assert path.read_bytes().startswith(raw[: raw.index(b"\n\nBody")])


# -- refusals ------------------------------------------------------------------------------

def test_a_file_that_changed_underneath_is_not_overwritten(vault):
    """Sync delivering an edit mid-operation is normal. Clobbering it would not be."""
    path = put(vault, "Note.md", b"original\n")
    original = write.read(path, vault=vault)
    path.write_bytes(b"arrived from another device\n")

    with pytest.raises(ConflictError, match="changed since it was read"):
        write.write(path, "ours", original, vault=vault)
    assert path.read_bytes() == b"arrived from another device\n"


def test_a_file_that_appeared_is_not_overwritten(vault):
    path = vault / "New.md"
    original = write.read(path, vault=vault)
    assert original.exists is False
    path.write_bytes(b"someone got there first\n")

    with pytest.raises(ConflictError):
        write.write(path, "ours", original, vault=vault)
    assert path.read_bytes() == b"someone got there first\n"


def test_a_file_that_vanished_is_reported(vault):
    path = put(vault, "Note.md", b"here\n")
    original = write.read(path, vault=vault)
    path.unlink()
    with pytest.raises(ConflictError, match="deleted"):
        write.write(path, "ours", original, vault=vault)


def test_invalid_utf8_is_refused_rather_than_repaired(vault):
    path = put(vault, "Broken.md", b"# Title\n\xff\xfe not utf-8\n")
    with pytest.raises(WriteError, match="not valid UTF-8"):
        write.read(path, vault=vault)


def test_writing_outside_the_vault_is_refused(vault, tmp_path):
    outside = tmp_path / "elsewhere.md"
    original = write.read(vault / "Note.md", vault=vault)
    with pytest.raises(WriteError, match="outside the vault"):
        write.write(outside, "escaped", original, vault=vault)
    assert not outside.exists()


def test_a_path_escaping_through_dots_is_refused(vault):
    original = write.read(vault / "Note.md", vault=vault)
    with pytest.raises(WriteError, match="outside the vault"):
        write.write(vault / ".." / "escaped.md", "no", original, vault=vault)


def test_a_symlinked_directory_cannot_be_used_to_escape(vault, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = vault / "sneaky"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this platform does not allow creating symlinks here")

    original = write.read(vault / "Note.md", vault=vault)
    with pytest.raises(WriteError, match="outside the vault"):
        write.write(link / "escaped.md", "no", original, vault=vault)
    assert not (outside / "escaped.md").exists()


# -- not writing at all --------------------------------------------------------------------

def test_writing_identical_content_does_not_touch_the_file(vault):
    """What stops a half-hourly view regeneration waking sync every half hour."""
    path = put(vault, "Note.md", b"same\n")
    original = write.read(path, vault=vault)
    before = path.stat().st_mtime_ns

    os.utime(path, ns=(before - 10_000_000_000, before - 10_000_000_000))
    stamp = path.stat().st_mtime_ns
    changed = write.write(path, "same", original, vault=vault)

    assert changed is False
    assert path.stat().st_mtime_ns == stamp, "an unchanged write must not touch mtime"


def test_a_real_change_reports_itself(vault):
    path = put(vault, "Note.md", b"before\n")
    original = write.read(path, vault=vault)
    assert write.write(path, "after", original, vault=vault) is True
    assert path.read_bytes() == b"after\n"


def test_no_temporary_files_are_left_behind(vault):
    path = put(vault, "Note.md", b"before\n")
    original = write.read(path, vault=vault)
    write.write(path, "after", original, vault=vault)
    leftovers = [p.name for p in vault.iterdir() if p.name.startswith(write.TEMP_PREFIX)]
    assert leftovers == []


def test_a_new_file_is_created_with_its_parents(vault):
    path = vault / "Deep" / "Nested" / "New.md"
    original = write.read(path, vault=vault)
    assert write.write(path, "content", original, vault=vault) is True
    assert path.read_bytes() == b"content\n"


# -- trash ---------------------------------------------------------------------------------

def test_removing_a_file_moves_it_to_the_trash(vault):
    path = put(vault, "Folder/Note.md", b"content\n")
    target = write.trash(path, vault=vault)
    assert not path.exists()
    assert target == vault / ".trash" / "Folder" / "Note.md"
    assert target.read_bytes() == b"content\n"


def test_trashing_twice_keeps_both_copies(vault):
    put(vault, "Note.md", b"first\n")
    write.trash(vault / "Note.md", vault=vault)
    put(vault, "Note.md", b"second\n")
    second = write.trash(vault / "Note.md", vault=vault)

    assert (vault / ".trash" / "Note.md").read_bytes() == b"first\n"
    assert second.read_bytes() == b"second\n"
    assert second.name != "Note.md"


def test_trashing_outside_the_vault_is_refused(vault, tmp_path):
    outside = tmp_path / "victim.md"
    outside.write_bytes(b"not yours\n")
    with pytest.raises(WriteError, match="outside the vault"):
        write.trash(outside, vault=vault)
    assert outside.exists()


# -- generated blocks ----------------------------------------------------------------------

MARKED = (
    "# Note\n\n"
    'Intro paragraph.\n\n'
    '<!-- hvk:begin base="Projects.base" view="Table" -->\n'
    "old content\n"
    "<!-- hvk:end -->\n\n"
    "Text after, which must survive.\n"
)


def test_only_the_block_body_is_replaced():
    result = write.replace_block(MARKED, "new content")
    assert "Intro paragraph." in result
    assert "Text after, which must survive." in result
    assert "old content" not in result
    assert "new content" in result


def test_the_opening_marker_and_its_attributes_survive():
    result = write.replace_block(MARKED, "new")
    assert '<!-- hvk:begin base="Projects.base" view="Table" -->' in result
    assert "<!-- hvk:end -->" in result


def test_replacing_a_block_with_its_own_content_is_a_no_op():
    """The exit criterion of the plan, made structural rather than hoped for."""
    once = write.replace_block(MARKED, "generated")
    twice = write.replace_block(once, "generated")
    assert once == twice


def test_block_attributes_are_readable():
    blocks = write.find_blocks(MARKED)
    assert len(blocks) == 1
    assert blocks[0]["attributes"] == {"base": "Projects.base", "view": "Table"}


def test_an_empty_body_leaves_a_well_formed_block():
    result = write.replace_block(MARKED, "")
    assert "<!-- hvk:end -->" in result
    assert write.find_blocks(result)[0]["body"].strip() == ""


def test_several_blocks_are_addressed_by_index():
    text = (
        '<!-- hvk:begin name="a" -->\nA\n<!-- hvk:end -->\n'
        '<!-- hvk:begin name="b" -->\nB\n<!-- hvk:end -->\n'
    )
    result = write.replace_block(text, "second", index=1)
    assert "\nA\n" in result and "second" in result and "\nB\n" not in result


def test_an_unclosed_marker_is_refused():
    """Guessing where a generated block ends would put the rest of the file at risk."""
    with pytest.raises(WriteError, match="no matching"):
        write.replace_block("text\n<!-- hvk:begin -->\nrest of the note\n", "new")


def test_a_note_with_no_block_is_reported():
    with pytest.raises(WriteError, match="no <!-- hvk:begin"):
        write.replace_block("# Just a note\n", "new")


def test_asking_for_a_block_that_is_not_there_is_reported():
    with pytest.raises(WriteError, match="only 1"):
        write.replace_block(MARKED, "new", index=3)
