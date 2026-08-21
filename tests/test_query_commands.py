"""tags, tasks, props and orphans -- the rest of the phase 2 query surface."""

from __future__ import annotations

import json

import pytest

from hvk import cli, query
from conftest import VAULTS


@pytest.fixture
def run(tmp_path, capsys):
    """Run hvk and return the parsed JSON, with any implicit scan output discarded."""
    scanned: set[str] = set()

    def _run(*args, vault="basic"):
        base = ["--vault", str(VAULTS / vault), "--index", str(tmp_path / f"{vault}-idx")]
        if vault not in scanned:
            cli.main([*base, "scan"])
            scanned.add(vault)
        capsys.readouterr()
        code = cli.main([*base, *args, "--json"])
        assert code == 0, capsys.readouterr().err
        return json.loads(capsys.readouterr().out)

    return _run


# -- tags -------------------------------------------------------------------------------

def test_tags_lists_every_distinct_tag(run):
    tags = {row["tag"] for row in run("tags")}
    assert tags == {"index", "home", "home/nested", "project", "active", "area", "daily", "tasks"}


def test_tags_count_orders_by_how_many_files_carry_them(run):
    rows = run("tags", "--count")
    assert rows[0]["files"] >= rows[-1]["files"]
    assert {r["tag"]: r["files"] for r in rows}["project"] == 2


def test_tags_prefix_includes_descendants(run):
    """Obsidian treats #home/nested as living under #home, and so does this."""
    assert {r["tag"] for r in run("tags", "--prefix", "home")} == {"home", "home/nested"}


def test_tags_prefix_tolerates_the_hash(run):
    assert run("tags", "--prefix", "#home") == run("tags", "--prefix", "home")


# -- tasks ------------------------------------------------------------------------------

def test_tasks_lists_everything_by_default(run):
    assert len(run("tasks", vault="tasks")) == 19


def test_pending_excludes_finished_tasks(run):
    rows = run("tasks", "--pending", vault="tasks")
    assert rows and all(row["done"] == 0 for row in rows)


def test_done_is_the_complement_of_pending(run):
    total = len(run("tasks", vault="tasks"))
    assert len(run("tasks", "--pending", vault="tasks")) + \
           len(run("tasks", "--done", vault="tasks")) == total


def test_due_before_filters_by_date(run):
    rows = run("tasks", "--due-before", "2026-09-03", vault="tasks")
    assert [row["due"] for row in rows] == ["2026-08-20", "2026-09-01", "2026-09-02"]


def test_undated_tasks_are_never_due(run):
    """A task with no due date is absent from a date filter, not treated as due forever."""
    rows = run("tasks", "--due-before", "2099-01-01", vault="tasks")
    assert all(row["due"] is not None for row in rows)
    assert len(rows) == 8


def test_due_before_rejects_a_malformed_date(tmp_path, capsys):
    base = ["--vault", str(VAULTS / "tasks"), "--index", str(tmp_path / "idx")]
    cli.main([*base, "scan"])
    capsys.readouterr()
    assert cli.main([*base, "tasks", "--due-before", "next tuesday"]) == 2
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_tasks_can_be_restricted_by_path(run):
    rows = run("tasks", "--path", "Priorities", vault="tasks")
    assert {row["path"] for row in rows} == {"Priorities.md"}


def test_dated_tasks_sort_before_undated_ones(run):
    dues = [row["due"] for row in run("tasks", vault="tasks")]
    first_undated = dues.index(None)
    assert all(d is not None for d in dues[:first_undated])
    assert all(d is None for d in dues[first_undated:])


# -- props ------------------------------------------------------------------------------

def test_props_without_arguments_is_a_catalogue_of_keys(run):
    rows = {row["key"]: row for row in run("props")}
    assert rows["tags"]["files"] == 7
    assert rows["status"]["files"] == 2


def test_props_filters_by_equality(run):
    assert [row["path"] for row in run("props", "--where", "status=open")] == ["Projects/Alpha.md"]


def test_props_comparison_ignores_case(run):
    assert run("props", "--where", "status=OPEN") == run("props", "--where", "status=open")


def test_props_negation(run):
    paths = [row["path"] for row in run("props", "--where", "status!=open")]
    assert "Projects/Beta.md" in paths
    assert "Projects/Alpha.md" not in paths


def test_several_conditions_combine_with_and(run):
    rows = run("props", "--where", "tags=project", "--where", "status!=open")
    assert [row["path"] for row in rows] == ["Projects/Beta.md"]


def test_a_bare_key_means_the_property_exists(run):
    paths = [row["path"] for row in run("props", "--where", "priority")]
    assert paths == ["Projects/Alpha.md", "Projects/Beta.md"]


def test_the_matched_key_is_shown_in_the_output(run):
    row = run("props", "--where", "status=open")[0]
    assert row["status"] == "open"


def test_key_chooses_a_different_column(run):
    row = run("props", "--where", "status=open", "--key", "priority")[0]
    assert row["priority"] == "1"


def test_list_valued_properties_are_joined_in_order(run):
    row = run("props", "--where", "status=open", "--key", "tags")[0]
    assert row["tags"] == "project, active"


def test_a_malformed_condition_is_reported(tmp_path, capsys):
    base = ["--vault", str(VAULTS / "basic"), "--index", str(tmp_path / "idx")]
    cli.main([*base, "scan"])
    capsys.readouterr()
    assert cli.main([*base, "props", "--where", "=nokey"]) == 2
    assert "cannot read the condition" in capsys.readouterr().err


# -- orphans ----------------------------------------------------------------------------

def test_orphans_lists_notes_nothing_links_to(run):
    assert [row["path"] for row in run("orphans")] == ["Tasks.md"]


def test_an_embedded_attachment_is_not_an_orphan(run):
    paths = [row["path"] for row in run("orphans", "--attachments")]
    assert "attachments/diagram.png" not in paths


def test_a_note_linking_to_itself_is_still_an_orphan(tmp_path, index):
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "Lonely.md").write_text("[[Lonely]]\n", encoding="utf-8", newline="\n")
    _, conn, _ = index(vault)
    assert [row["path"] for row in query.orphans(conn)] == ["Lonely.md"]
