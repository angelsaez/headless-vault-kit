"""The vault mirror: what it copies, what it refuses, and what it deletes.

The refusals matter more than the copying here. This script exists so that testing against
real data does not put the real vault, or the user's privacy, at risk -- and every one of its
guards is there because the failure it prevents would be silent and expensive.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from mirror_vault import MirrorError, mirror  # noqa: E402


@pytest.fixture
def source(tmp_path):
    vault = tmp_path / "Real Vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "app.json").write_text("{}", encoding="utf-8", newline="\n")
    (vault / ".obsidian" / "workspace.json").write_text("{}", encoding="utf-8", newline="\n")
    (vault / ".git").mkdir()
    (vault / ".git" / "HEAD").write_text("ref: x", encoding="utf-8", newline="\n")
    (vault / ".trash").mkdir()
    (vault / ".trash" / "Deleted.md").write_text("gone", encoding="utf-8", newline="\n")
    (vault / "_PRIVATE").mkdir()
    (vault / "_PRIVATE" / "tokens.md").write_text("secret", encoding="utf-8", newline="\n")
    (vault / "_PRIVADA").mkdir()
    (vault / "_PRIVADA" / "otros.md").write_text("secreto", encoding="utf-8", newline="\n")
    (vault / "Notes").mkdir()
    (vault / "Notes" / "One.md").write_text("# One\n", encoding="utf-8", newline="\n")
    (vault / "Notes" / "draft.tmp").write_text("x", encoding="utf-8", newline="\n")
    (vault / "Top.md").write_text("# Top\n", encoding="utf-8", newline="\n")
    return vault


def relatives(root: Path) -> set:
    return {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name != ".hvk-mirror"
    }


def test_it_copies_the_notes_and_the_configuration(source, tmp_path):
    dest = tmp_path / "mirror"
    mirror(source, dest)
    assert relatives(dest) == {"Top.md", "Notes/One.md", ".obsidian/app.json"}


@pytest.mark.parametrize("private", ["_PRIVATE", "_PRIVADA"])
def test_the_private_folder_is_never_copied(source, tmp_path, private):
    """Both spellings, because this project's own documents use both."""
    dest = tmp_path / "mirror"
    mirror(source, dest)
    assert not (dest / private).exists()


def test_git_trash_and_workspace_are_left_behind(source, tmp_path):
    dest = tmp_path / "mirror"
    mirror(source, dest)
    assert not (dest / ".git").exists()
    assert not (dest / ".trash").exists()
    assert not (dest / ".obsidian" / "workspace.json").exists()


def test_temporary_files_are_left_behind(source, tmp_path):
    dest = tmp_path / "mirror"
    mirror(source, dest)
    assert not (dest / "Notes" / "draft.tmp").exists()


def test_the_source_is_never_modified(source, tmp_path):
    before = relatives(source)
    mirror(source, tmp_path / "mirror")
    assert relatives(source) == before


def test_running_it_twice_copies_nothing_the_second_time(source, tmp_path):
    dest = tmp_path / "mirror"
    first = mirror(source, dest)
    second = mirror(source, dest)
    assert first["copied"] == 3
    assert second["copied"] == 0 and second["updated"] == 0
    assert second["unchanged"] == 3


def test_a_changed_file_is_updated(source, tmp_path):
    dest = tmp_path / "mirror"
    mirror(source, dest)
    (source / "Top.md").write_text("# Changed\n", encoding="utf-8", newline="\n")
    stats = mirror(source, dest)
    assert stats["updated"] == 1
    assert (dest / "Top.md").read_text(encoding="utf-8") == "# Changed\n"


def test_what_disappears_from_the_source_disappears_from_the_mirror(source, tmp_path):
    dest = tmp_path / "mirror"
    mirror(source, dest)
    (source / "Top.md").unlink()
    stats = mirror(source, dest)
    assert stats["removed"] == 1
    assert not (dest / "Top.md").exists()


# -- the refusals ---------------------------------------------------------------------------

def test_a_destination_inside_the_source_is_refused(source):
    with pytest.raises(MirrorError, match="inside the source"):
        mirror(source, source / "mirror")


def test_a_source_inside_the_destination_is_refused(source, tmp_path):
    with pytest.raises(MirrorError, match="inside the destination"):
        mirror(source, tmp_path)


def test_the_same_directory_twice_is_refused(source):
    with pytest.raises(MirrorError, match="the same directory"):
        mirror(source, source)


def test_a_destination_inside_a_git_repository_is_refused(source, tmp_path):
    """A vault mirror in a repository is one 'git add -A' away from being published."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(MirrorError, match="git repository"):
        mirror(source, repo / "mirror")


def test_a_repository_destination_can_be_allowed_explicitly(source, tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    mirror(source, repo / "mirror", allow_repo=True)
    assert (repo / "mirror" / "Top.md").exists()


def test_it_refuses_to_overwrite_something_that_looks_like_a_vault(source, tmp_path):
    victim = tmp_path / "another-vault"
    (victim / ".obsidian").mkdir(parents=True)
    with pytest.raises(MirrorError, match="looks like a real vault"):
        mirror(source, victim)


def test_it_will_overwrite_a_mirror_it_made_itself(source, tmp_path):
    dest = tmp_path / "mirror"
    mirror(source, dest)
    assert (dest / ".hvk-mirror").exists()
    mirror(source, dest)  # the marker says this one is ours, so it proceeds


def test_a_missing_source_is_reported(tmp_path):
    with pytest.raises(MirrorError, match="not a directory"):
        mirror(tmp_path / "nowhere", tmp_path / "mirror")
