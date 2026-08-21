"""YAML conformance: the cost ADR-0001 accepted, pinned by fixtures.

Where a case is a known divergence risk from the app rather than settled behaviour, the test
says so in its name and docstring instead of pretending certainty.
"""

from __future__ import annotations

import pytest

from conftest import prop, props_of


@pytest.fixture(scope="module")
def fm(tmp_path_factory):
    from hvk import db, paths
    from hvk import scan as scanner
    from conftest import VAULTS

    location = paths.Locations(
        vault=(VAULTS / "frontmatter").resolve(),
        index_dir=tmp_path_factory.mktemp("fm-index"),
    )
    scanner.scan(location)
    conn = db.connect(location.db_path)
    yield conn
    conn.close()


@pytest.mark.parametrize("key", ["answer_no", "answer_yes", "switch_on", "switch_off"])
def test_yaml_11_booleans_stay_strings(fm, key):
    """The whole reason ADR-0001 pins ruamel: under YAML 1.1 these would be booleans."""
    assert prop(fm, "03-%", key) == (key.split("_")[1], "string")


def test_country_code_no_is_not_a_boolean(fm):
    assert prop(fm, "03-%", "country_code") == ("NO", "string")


def test_sexagesimal_is_not_a_number(fm):
    assert prop(fm, "03-%", "sexagesimal") == ("12:30", "string")


def test_duplicate_keys_keep_the_last_value(fm):
    """js-yaml assigns in document order, so the last wins. ruamel would keep the first."""
    assert prop(fm, "12-%", "status") == ("second", "string")


def test_malformed_frontmatter_is_recorded_and_survived(fm):
    rows = fm.execute("SELECT path, parse_error FROM files WHERE parse_error IS NOT NULL").fetchall()
    assert [row["path"] for row in rows] == ["08-malformed.md"]
    assert "frontmatter:" in rows[0]["parse_error"]


def test_only_the_malformed_file_failed(fm):
    total = fm.execute("SELECT count(*) FROM files WHERE parse_error IS NOT NULL").fetchone()[0]
    assert total == 1


@pytest.mark.parametrize("path_like", ["00-%", "01-%", "10-%"])
def test_files_without_real_frontmatter_have_no_properties(fm, path_like):
    assert props_of(fm, path_like) == []


def test_frontmatter_must_open_on_line_one(fm):
    """10-not-at-start.md has a fence, but preceded by text, so it is body."""
    assert prop(fm, "10-%", "not") is None


def test_horizontal_rule_does_not_end_the_note(fm):
    assert prop(fm, "09-%", "title") == ("Delimiter in body", "string")
    assert prop(fm, "09-%", "not") is None


def test_lists_become_one_row_per_item_in_order(fm):
    rows = [r for r in props_of(fm, "04-%") if r["key"] == "tags"]
    assert [(r["idx"], r["value"]) for r in rows] == [(0, "one"), (1, "two/nested")]


def test_empty_list_is_recorded_without_items(fm):
    rows = [r for r in props_of(fm, "04-%") if r["key"] == "empty_list"]
    assert len(rows) == 1
    assert rows[0]["value"] is None and rows[0]["value_type"] == "list"


def test_scalar_types_are_classified(fm):
    assert prop(fm, "02-%", "number") == ("42", "number")
    assert prop(fm, "02-%", "bool_true") == ("true", "bool")
    assert prop(fm, "02-%", "null_value") == (None, "null")
    assert prop(fm, "02-%", "quoted") == ("with: a colon", "string")


def test_dates_keep_their_type(fm):
    assert prop(fm, "07-%", "date") == ("2026-08-21", "date")
    assert prop(fm, "07-%", "datetime") == ("2026-08-21T10:30:00", "datetime")
    assert prop(fm, "07-%", "quoted_date") == ("2026-08-21", "string")


def test_nested_maps_are_stored_as_json(fm):
    value, kind = prop(fm, "05-%", "deep")
    assert kind == "map"
    assert value == '{"a": {"b": {"c": "value"}}}'


def test_unicode_keys_are_preserved(fm):
    assert prop(fm, "11-%", "título") == ("Con acentos", "string")
    assert prop(fm, "11-%", "日本語") == ("値", "string")
    assert prop(fm, "11-%", "emoji_\U0001F680") == ("launch", "string")


def test_leading_zero_is_read_as_decimal(fm):
    """Documented, not asserted as parity: js-yaml's octal handling is unconfirmed.

    ADR-0003's approach applies here too -- record what we do so a divergence is findable,
    rather than quietly assuming the app agrees.
    """
    assert prop(fm, "03-%", "leading_zero") == ("755", "number")
