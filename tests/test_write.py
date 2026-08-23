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
from hvk.write import Block, ConflictError, Vault, WriteError

BEGIN = "<!-- vista:inicio -->"
END = "<!-- vista:fin -->"


@pytest.fixture
def vault(tmp_path) -> Vault:
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    return Vault(root)


def put(vault: Vault, name: str, data: bytes) -> Path:
    path = vault.root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# -- the round trip ------------------------------------------------------------------------

def test_an_untouched_round_trip_changes_nothing(vault):
    put(vault, "Note.md", b"# Title\n\nBody\n")
    original = vault.read("Note.md")
    assert vault.write(original, original.text) is False
    assert (vault.root / "Note.md").read_bytes() == b"# Title\n\nBody\n"


def test_crlf_files_stay_crlf(vault):
    path = put(vault, "Windows.md", b"# Title\r\n\r\nBody\r\n")
    original = vault.read(path)
    assert original.newline == "\r\n"
    assert original.text == "# Title\n\nBody"

    vault.write(original, original.text + "\nMore")
    assert path.read_bytes() == b"# Title\r\n\r\nBody\r\nMore\r\n"


def test_lf_files_do_not_acquire_crlf_on_windows(vault):
    path = put(vault, "Unix.md", b"line\n")
    vault.write(vault.read(path), "line\nsecond")
    assert b"\r" not in path.read_bytes()


def test_a_missing_final_newline_stays_missing(vault):
    path = put(vault, "NoNewline.md", b"no trailing newline")
    original = vault.read(path)
    assert original.final_newline is False
    vault.write(original, "changed")
    assert path.read_bytes() == b"changed"


def test_a_present_final_newline_stays_present(vault):
    path = put(vault, "Note.md", b"text\n")
    vault.write(vault.read(path), "changed")
    assert path.read_bytes() == b"changed\n"


def test_a_byte_order_mark_is_written_back(vault):
    path = put(vault, "Bom.md", "﻿# Title\n".encode("utf-8"))
    original = vault.read(path)
    assert original.bom is True
    assert original.text == "# Title"
    vault.write(original, "# Other")
    assert path.read_bytes() == "﻿# Other\n".encode("utf-8")


def test_a_file_without_a_bom_does_not_gain_one(vault):
    path = put(vault, "Plain.md", b"# Title\n")
    vault.write(vault.read(path), "# Other")
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_mixed_line_endings_are_noticed_and_the_majority_wins(vault):
    path = put(vault, "Mixed.md", b"one\r\ntwo\r\nthree\n")
    original = vault.read(path)
    assert original.mixed_newlines is True
    assert original.newline == "\r\n"


def test_unicode_content_survives(vault):
    path = put(vault, "Unicode.md", "# Café 日本語 🚀\n".encode("utf-8"))
    original = vault.read(path)
    vault.write(original, original.text + "\nmás")
    assert path.read_text(encoding="utf-8") == "# Café 日本語 🚀\nmás\n"


def test_frontmatter_is_never_reserialised(vault):
    """Quoting, key order, comments and duplicate keys survive: the YAML is never parsed."""
    frontmatter = (
        b"---\n"
        b"zeta: 1\n"
        b"# a comment ruamel would drop on a round trip\n"
        b"alpha:   'single quoted'\n"
        b"acci\xc3\xb3n: [ 1,2 ,3 ]\n"
        b"zeta: 2\n"
        b"---\n"
    )
    path = put(vault, "Front.md", frontmatter + b"\nBody\n")
    original = vault.read(path)
    vault.write(original, original.text + "\nappended")
    assert path.read_bytes() == frontmatter + b"\nBody\nappended\n"


# -- refusals ------------------------------------------------------------------------------

def test_a_file_that_changed_underneath_is_not_overwritten(vault):
    """Sync delivering an edit mid-operation is normal. Clobbering it would not be."""
    path = put(vault, "Note.md", b"original\n")
    original = vault.read(path)
    path.write_bytes(b"arrived from another device\n")

    with pytest.raises(ConflictError, match="contents changed since it was read"):
        vault.write(original, "ours")
    assert path.read_bytes() == b"arrived from another device\n"


def test_a_file_that_appeared_is_not_overwritten(vault):
    path = vault.root / "New.md"
    original = vault.read(path)
    assert original.exists is False
    path.write_bytes(b"someone got there first\n")

    with pytest.raises(ConflictError, match="did not when it was read"):
        vault.write(original, "ours")
    assert path.read_bytes() == b"someone got there first\n"


def test_a_file_that_vanished_is_reported(vault):
    path = put(vault, "Note.md", b"here\n")
    original = vault.read(path)
    path.unlink()
    with pytest.raises(ConflictError, match="deleted"):
        vault.write(original, "ours")


def test_invalid_utf8_is_refused_rather_than_repaired(vault):
    path = put(vault, "Broken.md", b"# Title\n\xff\xfe not utf-8\n")
    with pytest.raises(WriteError, match="not valid UTF-8"):
        vault.read(path)


def test_reading_outside_the_vault_is_refused(vault, tmp_path):
    outside = tmp_path / "elsewhere.md"
    outside.write_bytes(b"not yours\n")
    with pytest.raises(WriteError, match="outside the vault"):
        vault.read(outside)


def test_a_path_escaping_through_dots_is_refused(vault):
    with pytest.raises(WriteError, match="outside the vault"):
        vault.read("../escaped.md")


def test_the_vault_root_itself_is_not_a_file(vault):
    with pytest.raises(WriteError, match="vault root itself"):
        vault.read(vault.root)


def test_a_symlinked_directory_cannot_be_used_to_escape(vault, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = vault.root / "sneaky"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this platform does not allow creating symlinks here")

    with pytest.raises(WriteError, match="outside the vault"):
        vault.read(link / "escaped.md")
    assert not (outside / "escaped.md").exists()


def test_a_broken_symlink_pointing_outside_is_refused(vault, tmp_path):
    """The case a check on the parent directory waves through, and open() then follows."""
    target = tmp_path / "not-there-yet.md"
    link = vault.root / "Note.md"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("this platform does not allow creating symlinks here")

    assert not link.exists(), "the fixture is only interesting while the target is missing"
    with pytest.raises(WriteError, match="outside the vault"):
        vault.read(link)
    assert not target.exists()


@pytest.mark.parametrize(
    "target",
    [".obsidian/app.json", ".git/config", ".trash/Note.md", ".hidden.md"],
)
def test_hidden_paths_are_not_written_by_hvk(vault, target):
    with pytest.raises(WriteError, match="writes notes, not the hidden files"):
        vault.read(target)


def test_a_vault_that_is_not_a_directory_is_refused(tmp_path):
    with pytest.raises(WriteError, match="not a directory"):
        Vault(tmp_path / "nowhere")


# -- not writing at all --------------------------------------------------------------------

def test_writing_identical_content_does_not_touch_the_file(vault):
    """What stops a half-hourly view regeneration waking sync every half hour."""
    path = put(vault, "Note.md", b"same\n")
    original = vault.read(path)

    older = path.stat().st_mtime_ns - 10_000_000_000
    os.utime(path, ns=(older, older))
    stamp = path.stat().st_mtime_ns

    assert vault.write(original, "same") is False
    assert path.stat().st_mtime_ns == stamp, "an unchanged write must not touch mtime"


def test_a_real_change_reports_itself(vault):
    path = put(vault, "Note.md", b"before\n")
    assert vault.write(vault.read(path), "after") is True
    assert path.read_bytes() == b"after\n"


def test_no_temporary_files_are_left_behind(vault):
    path = put(vault, "Note.md", b"before\n")
    vault.write(vault.read(path), "after")
    leftovers = [p.name for p in vault.root.iterdir() if p.name.startswith(write.TEMP_PREFIX)]
    assert leftovers == []


def test_a_new_file_is_created_with_its_parents(vault):
    path = vault.root / "Deep" / "Nested" / "New.md"
    original = vault.read(path)
    assert vault.write(original, "content") is True
    assert path.read_bytes() == b"content\n"


# -- trash ---------------------------------------------------------------------------------

def test_removing_a_file_moves_it_to_the_trash(vault):
    path = put(vault, "Folder/Note.md", b"content\n")
    target = vault.trash(path)
    assert not path.exists()
    assert target == vault.root / ".trash" / "Folder" / "Note.md"
    assert target.read_bytes() == b"content\n"


def test_trashing_twice_keeps_both_copies(vault):
    put(vault, "Note.md", b"first\n")
    vault.trash("Note.md")
    put(vault, "Note.md", b"second\n")
    second = vault.trash("Note.md")

    assert (vault.root / ".trash" / "Note.md").read_bytes() == b"first\n"
    assert second.read_bytes() == b"second\n"
    assert second.name != "Note.md"


def test_the_relative_path_keeps_same_named_notes_apart(vault):
    put(vault, "A/Index.md", b"a\n")
    put(vault, "B/Index.md", b"b\n")
    first, second = vault.trash("A/Index.md"), vault.trash("B/Index.md")
    assert first != second
    assert first.read_bytes() == b"a\n" and second.read_bytes() == b"b\n"


def test_trashing_outside_the_vault_is_refused(vault, tmp_path):
    outside = tmp_path / "victim.md"
    outside.write_bytes(b"not yours\n")
    with pytest.raises(WriteError, match="outside the vault"):
        vault.trash(outside)
    assert outside.exists()


def test_trashing_something_that_is_not_a_file_is_refused(vault):
    (vault.root / "Folder").mkdir()
    with pytest.raises(WriteError, match="not a file"):
        vault.trash("Folder")
    with pytest.raises(WriteError, match="not a file"):
        vault.trash("Missing.md")


# -- generated blocks ----------------------------------------------------------------------

MARKED = (
    "# Note\n\n"
    "Intro paragraph.\n\n"
    f"{BEGIN}\n"
    "old content\n"
    f"{END}\n\n"
    "Text after, which must survive.\n"
)


def only_block(text: str) -> Block:
    blocks = write.find_blocks(text, BEGIN, END)
    assert len(blocks) == 1
    return blocks[0]


def test_only_the_block_body_is_replaced():
    result = write.replace_block(MARKED, only_block(MARKED), "new content")
    assert result == MARKED.replace("old content", "new content")


def test_the_markers_themselves_survive():
    result = write.replace_block(MARKED, only_block(MARKED), "new")
    assert BEGIN in result and END in result


def test_replacing_a_block_with_its_own_content_is_a_no_op():
    """The exit criterion of the plan, made structural rather than hoped for."""
    once = write.replace_block(MARKED, only_block(MARKED), "generated")
    twice = write.replace_block(once, only_block(once), "generated")
    assert once == twice


def test_an_empty_body_leaves_a_well_formed_block():
    result = write.replace_block(MARKED, only_block(MARKED), "")
    assert result.count(BEGIN) == 1 and result.count(END) == 1
    assert only_block(result).body == "\n"


def test_the_body_is_reported_between_the_markers():
    assert only_block(MARKED).body == "\nold content\n"


def test_several_blocks_are_found_in_order_and_replaced_independently():
    text = f"{BEGIN}\nA\n{END}\nbetween\n{BEGIN}\nB\n{END}\n"
    blocks = write.find_blocks(text, BEGIN, END)
    assert len(blocks) == 2

    result = write.replace_block(text, blocks[1], "second")
    assert result == f"{BEGIN}\nA\n{END}\nbetween\n{BEGIN}\nsecond\n{END}\n"


def test_indented_markers_are_found_and_kept_where_they_are():
    text = f"- item\n  {BEGIN}\n  old\n  {END}\n"
    result = write.replace_block(text, only_block(text), "new")
    assert result == f"- item\n  {BEGIN}\nnew\n  {END}\n"


def test_an_unclosed_marker_is_refused():
    """Guessing where a generated block ends would put the rest of the file at risk."""
    with pytest.raises(WriteError, match="no matching"):
        write.find_blocks(f"text\n{BEGIN}\nrest of the note\n", BEGIN, END)


def test_a_marker_opened_twice_is_refused():
    with pytest.raises(WriteError, match="again before the first one was closed"):
        write.find_blocks(f"{BEGIN}\nA\n{BEGIN}\nB\n{END}\n", BEGIN, END)


def test_a_note_with_no_block_yields_nothing_rather_than_an_error():
    assert write.find_blocks("# Just a note\n", BEGIN, END) == []


def test_the_markers_are_the_caller_s_business():
    text = "<!-- view:start -->\nold\n<!-- view:end -->\n"
    block = write.find_blocks(text, "<!-- view:start -->", "<!-- view:end -->")[0]
    assert write.replace_block(text, block, "new") == (
        "<!-- view:start -->\nnew\n<!-- view:end -->\n"
    )


# -- the two halves together ---------------------------------------------------------------

def test_regenerating_an_unchanged_block_never_touches_the_note(vault):
    """Phase 4's exit criterion, end to end: same content in, no write out."""
    path = put(vault, "View.md", (f"---\ntipo: vista\n---\n\n{MARKED}").encode("utf-8"))

    def regenerate() -> bool:
        original = vault.read(path)
        block = write.find_blocks(original.text, BEGIN, END)[0]
        return vault.write(original, write.replace_block(original.text, block, "| a |\n| - |"))

    assert regenerate() is True
    before = path.read_bytes()
    assert regenerate() is False
    assert path.read_bytes() == before
