"""Reading a .base file: the structure, the validation and the warnings."""

from __future__ import annotations

import pytest

from hvk.bases import base_file
from hvk.bases.base_file import BaseError

VAULT = "bases"


def write(tmp_path, text, name="Test.base"):
    path = tmp_path / name
    path.write_text(text.lstrip("\n"), encoding="utf-8", newline="\n")
    return path


def test_the_official_example_loads(tmp_path):
    """The complete example from the Bases documentation, verbatim."""
    path = write(tmp_path, """
filters:
  or:
    - file.hasTag("tag")
    - and:
        - file.hasTag("book")
        - file.hasLink("Textbook")
    - not:
        - file.hasTag("book")
        - file.inFolder("Required Reading")
formulas:
  formatted_price: 'if(price, price.toFixed(2) + " dollars")'
  ppu: "(price / age).toFixed(2)"
properties:
  status:
    displayName: Status
  formula.formatted_price:
    displayName: "Price"
  file.ext:
    displayName: Extension
views:
  - type: table
    name: "My table"
    limit: 10
    groupBy:
      property: note.age
      direction: DESC
    filters:
      and:
        - 'status != "done"'
        - or:
            - "formula.ppu > 5"
            - "price > 2.1"
    order:
      - file.name
      - file.ext
      - note.age
      - formula.ppu
      - formula.formatted_price
    summaries:
      formula.ppu: Average
""")
    base = base_file.load(path)

    assert base.filters.operator == "or"
    assert len(base.filters.children) == 3
    assert base.filters.children[1].operator == "and"
    assert set(base.formulas) == {"formatted_price", "ppu"}

    view = base.view(None)
    assert view.name == "My table" and view.type == "table" and view.limit == 10
    assert view.group_by.property == "note.age" and view.group_by.descending is True
    assert view.order[0] == "file.name" and len(view.order) == 5
    assert view.summaries == {"formula.ppu": "Average"}
    assert view.filters.operator == "and"
    assert base.warnings == []


def test_display_names_come_from_properties(tmp_path):
    base = base_file.load(write(tmp_path, """
properties:
  status:
    displayName: Estado
views:
  - type: table
    name: v
    order: [status, file.name, formula.x]
"""))
    assert base.display_name("status") == "Estado"
    assert base.display_name("file.name") == "name"     # prefix stripped when not configured


def test_a_single_string_filter_is_a_leaf(tmp_path):
    base = base_file.load(write(tmp_path, """
filters: 'status != "done"'
views:
  - type: table
    name: v
"""))
    assert base.filters.source == 'status != "done"'


def test_views_are_found_by_name(tmp_path):
    base = base_file.load(write(tmp_path, """
views:
  - type: table
    name: first
  - type: table
    name: second
"""))
    assert base.view(None).name == "first"
    assert base.view("second").name == "second"


def test_an_unknown_view_name_lists_the_real_ones(tmp_path):
    base = base_file.load(write(tmp_path, """
views:
  - type: table
    name: first
"""))
    with pytest.raises(BaseError, match="'first'"):
        base.view("nope")


def test_an_unsupported_view_type_is_refused(tmp_path):
    with pytest.raises(BaseError, match="map"):
        base_file.load(write(tmp_path, """
views:
  - type: map
    name: pins
"""))


def test_a_syntax_error_in_a_filter_names_the_view(tmp_path):
    with pytest.raises(BaseError, match="view 'v'"):
        base_file.load(write(tmp_path, """
views:
  - type: table
    name: v
    filters:
      and:
        - "status !== done"
"""))


def test_a_syntax_error_in_a_formula_names_the_formula(tmp_path):
    with pytest.raises(BaseError, match="formula 'broken'"):
        base_file.load(write(tmp_path, """
formulas:
  broken: "price +"
views:
  - type: table
    name: v
"""))


def test_a_filter_object_with_two_operators_is_refused(tmp_path):
    with pytest.raises(BaseError, match="exactly one"):
        base_file.load(write(tmp_path, """
filters:
  and:
    - "a"
  or:
    - "b"
views:
  - type: table
    name: v
"""))


def test_an_unknown_filter_operator_is_refused(tmp_path):
    with pytest.raises(BaseError, match="unless"):
        base_file.load(write(tmp_path, """
filters:
  unless:
    - "a"
views:
  - type: table
    name: v
"""))


def test_invalid_yaml_says_so(tmp_path):
    with pytest.raises(BaseError, match="not valid YAML"):
        base_file.load(write(tmp_path, 'views:\n  - type: table\n   name: "bad indent\n'))


def test_a_missing_file_says_so(tmp_path):
    with pytest.raises(BaseError, match="cannot read"):
        base_file.load(tmp_path / "absent.base")


def test_unknown_keys_warn_rather_than_fail(tmp_path):
    """Obsidian keeps adding to this format; refusing a newer key would break the tool."""
    base = base_file.load(write(tmp_path, """
somethingNew: 42
views:
  - type: table
    name: v
    futureOption: true
"""))
    assert any("somethingNew" in w for w in base.warnings)
    assert any("futureOption" in w for w in base.warnings)
    assert base.views[0].name == "v"


def test_a_custom_summary_is_declared_but_warned_about(tmp_path):
    base = base_file.load(write(tmp_path, """
summaries:
  customAverage: 'values.mean().round(3)'
views:
  - type: table
    name: v
"""))
    assert any("customAverage" in w for w in base.warnings)


def test_an_unknown_builtin_summary_is_refused(tmp_path):
    with pytest.raises(BaseError, match="Median"):
        base_file.load(write(tmp_path, """
views:
  - type: table
    name: v
    order: [price]
    summaries:
      price: Median
"""))


def test_a_base_with_no_views_says_so(tmp_path):
    base = base_file.load(write(tmp_path, "filters: 'a'\n"))
    with pytest.raises(BaseError, match="no views"):
        base.view(None)


def test_sort_accepts_a_bare_property_or_a_mapping(tmp_path):
    base = base_file.load(write(tmp_path, """
views:
  - type: table
    name: v
    sort:
      - price
      - property: age
        direction: DESC
"""))
    view = base.view(None)
    assert view.sort[0].property == "price" and view.sort[0].descending is False
    assert view.sort[1].property == "age" and view.sort[1].descending is True
