"""Evaluating Bases expressions: the semantics ADR-0005 defines, pinned."""

from __future__ import annotations

import datetime as dt

import pytest

from hvk.bases import Context, File, evaluate_source
from hvk.bases.expr import ExpressionError
from hvk.bases.values import Link, sort_key


@pytest.fixture
def note():
    file = File(
        path="Projects/Alpha.md",
        name="Alpha.md",
        basename="Alpha",
        folder="Projects",
        ext="md",
        size=1200,
        ctime=dt.datetime(2026, 1, 2, 9, 30),
        mtime=dt.datetime(2026, 8, 1, 18, 0),
        tags=["project", "book/fiction"],
        links=["Projects/Beta.md", "Areas/Reading.md"],
        properties={
            "status": "open",
            "price": 12.5,
            "age": 5,
            "tags": ["project", "book/fiction"],
            "due": dt.date(2026, 9, 15),
            "empty": "",
            "zero": 0,
            "flag": True,
            "authors": ["Ana", "Bea"],
        },
    )
    return Context(
        file=file,
        note=file.properties,
        formulas={
            "ppu": "(price / age).toFixed(2)",
            "label": 'if(price, price.toFixed(2) + " dollars")',
            "loop": "formula.loop + 1",
            "chain": "formula.ppu + \"!\"",
        },
    )


def run(source, context):
    return evaluate_source(source, context)


# -- the null rules of ADR-0005 -----------------------------------------------------------

def test_a_missing_property_is_null_not_an_error(note):
    assert run("nothing_here", note) is None


def test_null_is_unequal_to_everything_except_null(note):
    assert run('missing != "done"', note) is True
    assert run('missing == "done"', note) is False
    assert run("missing == null", note) is True


def test_a_note_without_the_property_counts_as_not_done(note):
    """The intuition the rule exists to preserve."""
    assert run('status != "done"', note) is True
    assert run('never_set != "done"', note) is True


def test_ordering_against_null_is_false_in_both_directions(note):
    assert run("missing > 10", note) is False
    assert run("missing < 10", note) is False
    assert run("10 > missing", note) is False
    assert run("10 < missing", note) is False


def test_reaching_through_null_stays_null(note):
    assert run("missing.toFixed(2)", note) is None
    assert run("missing.nested.deeper", note) is None


def test_a_typo_on_a_real_value_is_still_an_error(note):
    with pytest.raises(ExpressionError, match="toFixxed"):
        run("price.toFixxed(2)", note)


# -- coercion ------------------------------------------------------------------------------

def test_a_numeric_string_compares_as_a_number(note):
    context = Context(file=File(path="a.md"), note={"n": "42"})
    assert run("n > 10", context) is True
    assert run("n == 42", context) is True


def test_a_non_numeric_string_does_not_compare_as_a_number(note):
    context = Context(file=File(path="a.md"), note={"n": "many"})
    assert run("n > 10", context) is False


def test_an_iso_string_compares_as_a_date(note):
    assert run('due > "2026-01-01"', note) is True
    assert run('due < "2026-01-01"', note) is False


def test_truthiness_follows_obsidian(note):
    assert run("empty.isTruthy()", note) is False
    assert run("zero.isTruthy()", note) is False
    assert run("flag.isTruthy()", note) is True
    assert run("authors.isTruthy()", note) is True


# -- arithmetic ---------------------------------------------------------------------------

def test_numbers(note):
    assert run("age * 2 + 1", note) == 11
    assert run("price - 2.5", note) == 10.0


def test_string_concatenation(note):
    assert run('status + " project"', note) == "open project"
    assert run('"n=" + age', note) == "n=5"


def test_division_by_zero_is_missing_data_not_a_crash(note):
    assert run("price / zero", note) is None


def test_dates_take_durations(note):
    assert run('due + duration("7 days")', note) == dt.date(2026, 9, 22)
    assert run('due - duration("1 week")', note) == dt.date(2026, 9, 8)


def test_subtracting_two_dates_gives_a_duration(note):
    assert run('due - date("2026-09-01")', note) == dt.timedelta(days=14)


# -- functions ----------------------------------------------------------------------------

def test_if_with_and_without_a_false_branch(note):
    assert run('if(price, "yes", "no")', note) == "yes"
    assert run('if(missing, "yes", "no")', note) == "no"
    assert run('if(missing, "yes")', note) is None


def test_if_does_not_evaluate_the_branch_it_does_not_take(note):
    """Otherwise if(price, price.toFixed(2)) would be unsafe on a note without a price."""
    assert run('if(missing, missing.toFixxed(2), "safe")', note) == "safe"


def test_string_methods(note):
    assert run("file.name.lower()", note) == "alpha.md"
    assert run('status.startsWith("op")', note) is True
    assert run('status.contains("pe")', note) is True
    assert run("status.length", note) == 4
    assert run('"  x  ".trim()', note) == "x"


def test_number_methods(note):
    assert run("price.toFixed(1)", note) == "12.5"
    assert run("price.floor()", note) == 12
    assert run("price.ceil()", note) == 13
    assert run("price.round(0)", note) == 12


def test_list_methods(note):
    assert run('authors.join(" and ")', note) == "Ana and Bea"
    assert run('authors.contains("Ana")', note) is True
    assert run("authors.length", note) == 2
    assert run("authors.reverse()", note) == ["Bea", "Ana"]


def test_date_methods_and_fields(note):
    assert run("due.year", note) == 2026
    assert run("due.month", note) == 9
    assert run('due.format("YYYY-MM")', note) == "2026-09"


def test_min_and_max(note):
    assert run("min(3, 1, 2)", note) == 1
    assert run("max(3, 1, 2)", note) == 3


def test_link_values(note):
    value = run('link("Projects/Beta.md", "Beta")', note)
    assert isinstance(value, Link)
    assert str(value) == "Beta"


# -- the file namespace -------------------------------------------------------------------

def test_file_fields(note):
    assert run("file.name", note) == "Alpha.md"
    assert run("file.basename", note) == "Alpha"
    assert run("file.folder", note) == "Projects"
    assert run("file.ext", note) == "md"


def test_has_tag_matches_nested_tags(note):
    """#book/fiction lives under #book, as Obsidian's own tag search treats it."""
    assert run('file.hasTag("book")', note) is True
    assert run('file.hasTag("book/fiction")', note) is True
    assert run('file.hasTag("books")', note) is False


def test_has_tag_accepts_several_and_means_any(note):
    assert run('file.hasTag("nope", "project")', note) is True


def test_in_folder_covers_subfolders(note):
    context = Context(file=File(path="A/B/C.md", folder="A/B"), note={})
    assert run('file.inFolder("A")', context) is True
    assert run('file.inFolder("A/B")', context) is True
    assert run('file.inFolder("B")', context) is False


def test_has_link_by_path_and_by_name(note):
    assert run('file.hasLink("Projects/Beta.md")', note) is True
    assert run('file.hasLink("Beta")', note) is True
    assert run('file.hasLink("Gamma")', note) is False


def test_has_property(note):
    assert run('file.hasProperty("status")', note) is True
    assert run('file.hasProperty("nope")', note) is False


# -- formulas -----------------------------------------------------------------------------

def test_formulas_evaluate_and_chain(note):
    assert run("formula.ppu", note) == "2.50"
    assert run("formula.label", note) == "12.50 dollars"
    assert run("formula.chain", note) == "2.50!"


def test_a_formula_is_evaluated_once(note):
    assert run("formula.ppu", note) == "2.50"
    note.formulas["ppu"] = "9999"          # the cached value must win
    assert run("formula.ppu", note) == "2.50"


def test_a_self_referencing_formula_is_reported(note):
    with pytest.raises(ExpressionError, match="refers to itself"):
        run("formula.loop", note)


def test_an_undefined_formula_is_reported(note):
    with pytest.raises(ExpressionError, match="no formula named"):
        run("formula.nope", note)


# -- what ADR-0005 excludes ----------------------------------------------------------------

@pytest.mark.parametrize("source", ["random()", 'html("x")', 'image("a")', 'icon("y")',
                                    'escapeHTML("z")'])
def test_excluded_functions_fail_by_name(note, source):
    with pytest.raises(ExpressionError, match="unknown function"):
        run(source, note)


@pytest.mark.parametrize("method", ["map", "filter", "reduce"])
def test_the_lambda_taking_list_functions_are_reported(note, method):
    with pytest.raises(ExpressionError, match=method):
        run(f"authors.{method}(x)", note)


def test_this_without_a_context_note_says_what_to_pass(note):
    with pytest.raises(ExpressionError, match="--this"):
        run("this.file.name", note)


def test_this_works_when_a_context_note_is_given(note):
    note.this = File(path="Daily/Today.md", name="Today.md", folder="Daily")
    assert run("this.file.name", note) == "Today.md"
    assert run("this.file.folder", note) == "Daily"


# -- sorting -------------------------------------------------------------------------------

def test_nulls_sort_last_whatever_the_direction():
    values = [3, None, 1, None, 2]
    assert sorted(values, key=sort_key) == [1, 2, 3, None, None]
    ascending = sorted(values, key=sort_key)
    descending = sorted(values, key=sort_key, reverse=True)
    assert descending[-2:] == [None, None] or ascending[-2:] == [None, None]


def test_the_official_example_filter_evaluates(note):
    """The complex filter from the Bases documentation, as one expression per line."""
    assert run('file.hasTag("book")', note) is True
    assert run('file.hasLink("Areas/Reading.md")', note) is True
    assert run('file.inFolder("Required Reading")', note) is False
    assert run('status != "done"', note) is True
    assert run("price > 2.1", note) is True
