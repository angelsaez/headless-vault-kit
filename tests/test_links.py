"""Link resolution: the table in test-vaults/README.md, asserted (ADR-0003)."""

from __future__ import annotations

import pytest

from conftest import links_of

# (line in Source.md, expected target, expected candidate count)
SOURCE_CASES = [
    (8, "Note.md", 3),                       # bare name, source at the root
    (9, "FolderB/Note.md", 1),               # exact path
    (10, "Note.md", 3),                      # exact path with the extension written out
    (11, "Nested/Inner/Deep.md", 1),         # path suffix
    (12, "Note.md", 3),                      # display text stripped
    (13, "Note.md", 3),                      # heading subpath ignored when choosing
    (14, "Note.md", 3),                      # block subpath ignored when choosing
    (15, "Source.md", 1),                    # empty target points at the containing file
    (16, "Unique Name.md", 1),               # space in the filename
    (17, None, 0),                           # unresolved
    (18, "attachments/diagram.png", 1),      # non-note needs its extension
    (19, None, 0),                           # ... and must not match without it
    (20, "attachments/diagram.png", 1),      # embed of an attachment
    (21, "Note.md", 3),                      # embed of a note
    (22, "Unique Name.md", 1),               # markdown link, percent-decoded
    (23, "FolderA/Note.md", 1),              # markdown link with an anchor
]

# The same bare link resolves differently depending on the folder it is written in.
LOCAL_CASES = [
    (3, "FolderA/Note.md", 3),               # same-folder tie-break
    (4, "FolderA/Note.md", 3),               # the extension does not make it root-absolute
    (5, "FolderA/Local.md", 1),              # a note linking to itself
]


@pytest.fixture(scope="module")
def links_vault(tmp_path_factory):
    from hvk import db, paths
    from hvk import scan as scanner
    from conftest import VAULTS

    location = paths.Locations(
        vault=(VAULTS / "links").resolve(),
        index_dir=tmp_path_factory.mktemp("links-index"),
    )
    scanner.scan(location)
    conn = db.connect(location.db_path)
    yield conn
    conn.close()


@pytest.mark.parametrize("line, expected, candidates", SOURCE_CASES)
def test_source_resolution(links_vault, line, expected, candidates):
    row = links_of(links_vault, "Source.md")[line]
    assert row["resolved"] == expected
    assert row["candidates"] == candidates


@pytest.mark.parametrize("line, expected, candidates", LOCAL_CASES)
def test_same_folder_beats_the_root(links_vault, line, expected, candidates):
    row = links_of(links_vault, "FolderA/Local.md")[line]
    assert row["resolved"] == expected
    assert row["candidates"] == candidates


def test_external_links_are_never_broken(links_vault):
    rows = links_of(links_vault, "Source.md")
    for line in (24, 25, 26):
        assert rows[line]["kind"] == "external"
        assert rows[line]["resolved"] is None
    broken = links_vault.execute(
        "SELECT count(*) FROM links WHERE target_file_id IS NULL AND kind != 'external'"
    ).fetchone()[0]
    assert broken == 2  # [[Missing Note]] and [[diagram]], and nothing else


def test_subpaths_are_stored_but_do_not_choose_the_file(links_vault):
    rows = links_of(links_vault, "Source.md")
    assert rows[13]["subpath"] == "#Heading Two"
    assert rows[14]["subpath"] == "#^ref-block"
    assert rows[13]["resolved"] == rows[14]["resolved"] == "Note.md"


def test_embeds_are_marked(links_vault):
    rows = links_of(links_vault, "Source.md")
    assert rows[20]["embed"] == 1
    assert rows[21]["embed"] == 1
    assert rows[8]["embed"] == 0


def test_code_and_comments_do_not_produce_links(links_vault):
    """Fences.md holds one real link and four decoys."""
    rows = links_of(links_vault, "Fences.md")
    assert list(rows) == [3]
    assert rows[3]["resolved"] == "Note.md"


def test_ambiguous_links_are_listed(links_vault):
    from hvk import query

    ambiguous = query.links(links_vault, ambiguous=True)
    assert ambiguous, "the validation list ADR-0003 promises must not be empty here"
    assert all(row["candidates"] > 1 for row in ambiguous)
    assert {row["source"] for row in ambiguous} == {"Source.md", "FolderA/Local.md", "Fences.md"}


def test_relative_paths_climb_out_of_the_source_folder(tmp_path, index):
    """Hand-written Markdown links use ../, and they point at real files."""
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "A" / "Deep").mkdir(parents=True)
    (vault / "B").mkdir()
    (vault / "B" / "Target.md").write_text(
        "# Target\n", encoding="utf-8", newline="\n")
    (vault / "A" / "Deep" / "Source.md").write_text(
        "[up](../../B/Target.md)\n[too far](../../../outside/Target.md)\n",
        encoding="utf-8", newline="\n")

    _, conn, _ = index(vault)
    rows = links_of(conn, "A/Deep/Source.md")
    assert rows[1]["resolved"] == "B/Target.md"
    assert rows[2]["resolved"] is None, "a path climbing past the vault root is not a link"
