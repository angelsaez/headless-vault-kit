"""Running base views against the index, and the hvk base command."""

from __future__ import annotations

import json

import pytest

from hvk import cli, db, paths
from hvk import scan as scanner
from hvk.bases import base_file
from hvk.bases import run as base_run
from hvk.bases.base_file import BaseError
from conftest import VAULTS


@pytest.fixture(scope="module")
def indexed_bases(tmp_path_factory):
    location = paths.Locations(
        vault=(VAULTS / "bases").resolve(),
        index_dir=tmp_path_factory.mktemp("bases-index"),
    )
    scanner.scan(location)
    conn = db.connect(location.db_path)
    yield location, conn
    conn.close()


def run_view(indexed_bases, name, view=None, this=None):
    location, conn = indexed_bases
    base = base_file.load(location.vault / name)
    return base_run.run(base, conn, view, this)


def names(result):
    return [row["values"]["file.name"] for row in result.rows]


# -- filters --------------------------------------------------------------------------------

def test_global_and_view_filters_both_apply(indexed_bases):
    result = run_view(indexed_bases, "Library.base", "Open books")
    assert names(result) == ["Textbook.md", "Bases.md", "Dune.md"]
    assert "Solaris.md" not in names(result), "excluded by the view filter status != done"
    assert "Notes.md" not in names(result), "excluded by the global filter hasTag(book)"


def test_nested_and_or_not_filters(indexed_bases):
    result = run_view(indexed_bases, "Nested.base")
    assert "Textbook.md" not in names(result), "the not() branch excludes Required Reading"
    assert "Dune.md" in names(result)


def test_a_row_is_a_note_not_every_file(indexed_bases):
    """An unfiltered base must not list its own .base file next to the notes."""
    result = run_view(indexed_bases, "Nested.base")
    assert not any(name.endswith(".base") for name in names(result))


# -- columns, formulas and display names ------------------------------------------------------

def test_formulas_are_computed_per_row(indexed_bases):
    result = run_view(indexed_bases, "Library.base", "Open books")
    values = {row["values"]["file.name"]: row["values"]["formula.ppu"] for row in result.rows}
    assert values["Dune.md"] == "2.50"          # 12.50 / 5
    assert values["Bases.md"] == "10.00"        # 30 / 3


def test_display_names_reach_the_headers(indexed_bases):
    result = run_view(indexed_bases, "Library.base", "Open books")
    assert result.headers[0] == "Name"
    assert result.headers[1] == "Status"
    assert result.headers[2] == "Per unit"


def test_a_view_without_order_falls_back_and_says_so(indexed_bases):
    location, conn = indexed_bases
    path = location.index_dir / "NoOrder.base"
    path.write_text("views:\n  - type: table\n    name: v\n", encoding="utf-8", newline="\n")
    result = base_run.run(base_file.load(path), conn)
    assert result.columns == ["file.name"]
    assert any("no 'order'" in warning for warning in result.warnings)


# -- sorting, limits and grouping ---------------------------------------------------------------

def test_sorting_descending(indexed_bases):
    result = run_view(indexed_bases, "Library.base", "Open books")
    prices = [row["values"].get("price") for row in result.rows]
    assert names(result)[0] == "Textbook.md", "the most expensive first"
    del prices


def test_limit_applies_after_sorting_and_reports_the_total(indexed_bases):
    result = run_view(indexed_bases, "Library.base", "Top two")
    assert len(result.rows) == 2
    assert result.total > 2
    assert names(result) == ["Textbook.md", "Bases.md"]


def test_grouping(indexed_bases):
    result = run_view(indexed_bases, "Library.base", "Everything, grouped")
    groups = {name: [row["values"]["file.name"] for row in rows] for name, rows in result.groups}
    assert groups["done"] == ["Solaris.md"]
    assert set(groups["open"]) == {"Textbook.md", "Bases.md", "Dune.md"}


def test_nulls_sort_last_in_either_direction(indexed_bases, tmp_path):
    location, conn = indexed_bases
    ascending = tmp_path / "Asc.base"
    ascending.write_text(
        "views:\n  - type: table\n    name: v\n    order: [file.name, price]\n"
        "    sort:\n      - property: price\n        direction: ASC\n",
        encoding="utf-8", newline="\n")
    descending = tmp_path / "Desc.base"
    descending.write_text(
        "views:\n  - type: table\n    name: v\n    order: [file.name, price]\n"
        "    sort:\n      - property: price\n        direction: DESC\n",
        encoding="utf-8", newline="\n")

    for path in (ascending, descending):
        result = base_run.run(base_file.load(path), conn)
        prices = [row["values"]["price"] for row in result.rows]
        assert prices[-1] is None, f"{path.name}: the note without a price must sink"
        assert all(p is not None for p in prices[:-1])


# -- summaries -------------------------------------------------------------------------------

def test_a_summary_is_computed_over_the_shown_rows(indexed_bases):
    result = run_view(indexed_bases, "Library.base", "Open books")
    assert result.summaries["price"] == pytest.approx(45.0 + 30.0 + 12.5)


# -- errors ----------------------------------------------------------------------------------

def test_an_unsupported_function_names_the_base_the_view_and_the_note(indexed_bases):
    with pytest.raises(BaseError) as caught:
        run_view(indexed_bases, "Unsupported.base")
    message = str(caught.value)
    assert "Unsupported.base" in message
    assert "random()" in message


def test_this_without_a_note_says_what_to_pass(indexed_bases, tmp_path):
    location, conn = indexed_bases
    path = tmp_path / "This.base"
    path.write_text(
        'views:\n  - type: table\n    name: v\n    filters:\n      and:\n'
        '        - "file.folder == this.file.folder"\n',
        encoding="utf-8", newline="\n")
    with pytest.raises(BaseError, match="--this"):
        base_run.run(base_file.load(path), conn)


def test_this_resolves_when_a_note_is_given(indexed_bases, tmp_path):
    location, conn = indexed_bases
    path = tmp_path / "This.base"
    path.write_text(
        'views:\n  - type: table\n    name: v\n    filters:\n      and:\n'
        '        - "file.folder == this.file.folder"\n',
        encoding="utf-8", newline="\n")
    result = base_run.run(base_file.load(path), conn, this_path="library/Dune.md")
    assert "Dune.md" in [row["values"]["file.name"] for row in result.rows]
    assert "Textbook.md" not in [row["values"]["file.name"] for row in result.rows]


def test_an_unknown_this_path_is_reported(indexed_bases, tmp_path):
    location, conn = indexed_bases
    path = tmp_path / "Plain.base"
    path.write_text("views:\n  - type: table\n    name: v\n", encoding="utf-8", newline="\n")
    with pytest.raises(BaseError, match="not a file in the index"):
        base_run.run(base_file.load(path), conn, this_path="nope.md")


# -- the command ------------------------------------------------------------------------------

@pytest.fixture
def run_cli(tmp_path, capsys):
    index_dir = tmp_path / "idx"
    base = ["--vault", str(VAULTS / "bases"), "--index", str(index_dir)]
    cli.main([*base, "scan"])
    capsys.readouterr()

    def _run(*args):
        code = cli.main([*base, *args])
        return code, capsys.readouterr()

    return _run


def test_the_command_prints_a_markdown_table(run_cli):
    code, output = run_cli("base", "Library.base")
    assert code == 0
    assert "| Name | Status | Per unit |" in output.out
    assert "|---|---|---|" in output.out
    assert "| Dune.md | open | 2.50 |" in output.out


def test_the_extension_may_be_left_out(run_cli):
    assert run_cli("base", "Library")[0] == 0


def test_json_output_carries_rows_and_summaries(run_cli):
    code, output = run_cli("base", "Library.base", "--json")
    payload = json.loads(output.out)
    assert payload["view"] == "Open books"
    assert payload["headers"][0] == "Name"
    assert {row["path"] for row in payload["rows"]} == {
        "Required Reading/Textbook.md", "library/Bases.md", "library/Dune.md"
    }
    assert payload["summaries"]["price"] == 87.5


def test_grouped_output_prints_a_section_per_group(run_cli):
    code, output = run_cli("base", "Library.base", "--view", "Everything, grouped")
    assert "### done" in output.out and "### open" in output.out


def test_warnings_go_to_stderr_and_do_not_stop_the_table(run_cli):
    code, output = run_cli("base", "Extra keys.base")
    assert code == 0
    assert "somethingNew" in output.err
    assert "| name |" in output.out


def test_an_unsupported_view_type_exits_non_zero(run_cli):
    code, output = run_cli("base", "Map.base")
    assert code == 2
    assert "map" in output.err


def test_an_unknown_function_exits_non_zero(run_cli):
    code, output = run_cli("base", "Unsupported.base")
    assert code == 2
    assert "random()" in output.err


def test_a_missing_base_file_says_so(run_cli):
    code, output = run_cli("base", "Nope.base")
    assert code == 2
    assert "no such base file" in output.err
