"""The parser interface (ADR-0017): what registering one does, and what the index does with it.

The point of these is not that a dataclass holds fields. It is that the two questions
``scan.py`` used to answer with a hardcoded dictionary -- *what kind of file is this* and *what
reads it* -- still get the same answers now that a stranger can change them.
"""

from __future__ import annotations

import pytest

from hvk.parse import BUILT_IN, Parsed, Parser, Registry, model, registry


# -- choosing a parser ------------------------------------------------------------------------

def test_an_extension_nobody_claims_has_no_parser():
    """Which is how an attachment is recognised. A PNG is still indexed; it just derives no rows."""
    assert registry.REGISTRY.select("png", "", "diagram.png") is None
    assert registry.REGISTRY.select("", "", "Makefile") is None


@pytest.mark.parametrize("ext, name", [("md", "markdown"), ("canvas", "canvas"), ("base", "base")])
def test_the_built_in_formats_still_answer_for_themselves(ext, name):
    assert registry.REGISTRY.select(ext, "# a note\n", f"A.{ext}").name == name


def test_the_extension_is_matched_however_it_is_written():
    assert registry.REGISTRY.select("MD", "", "A.MD").name == "markdown"
    assert registry.REGISTRY.select(".md", "", "A.md").name == "markdown"


def test_a_base_is_a_known_kind_of_file_that_derives_nothing():
    """Not an oversight: the index records that a base exists so `hvk views` can find it, and
    the Bases machinery reads the file whole. Shredding a query definition into rows would
    derive nothing anybody asks the index for."""
    parser = registry.REGISTRY.select("base", "", "Library.base")
    assert parser.kind == "base"
    assert parser.parse is None


def test_priority_decides_between_two_parsers_for_one_extension():
    own = Registry()
    general = own.register(Parser(name="general", extensions=("x",)))
    special = own.register(Parser(name="special", extensions=("x",), priority=5))
    assert own.candidates("x") == [special, general]


def test_a_claim_can_hand_a_file_back_to_the_general_parser():
    own = Registry()
    general = own.register(Parser(name="general", extensions=("x",)))
    own.register(Parser(
        name="special", extensions=("x",), priority=5,
        claims=lambda text, path: text.startswith("SPECIAL"),
    ))
    assert own.select("x", "SPECIAL", "a.x").name == "special"
    assert own.select("x", "ordinary", "a.x") is general


def test_registering_the_same_name_twice_replaces_rather_than_stacks():
    """Importing an adapter twice has to be harmless, and taking a built-in's name has to be a
    deliberate override rather than a second parser nobody can see."""
    own = Registry()
    own.register(Parser(name="mine", extensions=("x",), kind="note"))
    own.register(Parser(name="mine", extensions=("x",), kind="canvas"))
    assert len(own.parsers) == 1
    assert own.select("x", "", "a.x").kind == "canvas"


def test_equal_priorities_keep_registration_order():
    """A rebuild has to be deterministic (the first non-negotiable principle), so the tie-break
    must not depend on how a dict happened to hash."""
    own = Registry()
    for name in ("a", "b", "c", "d"):
        own.register(Parser(name=name, extensions=("x",)))
    assert [p.name for p in own.candidates("x")] == ["a", "b", "c", "d"]


def test_extensions_lists_everything_that_gets_read():
    assert {"md", "canvas", "base"} <= registry.REGISTRY.extensions()


# -- the contract itself ----------------------------------------------------------------------

def test_the_two_built_in_parsers_return_the_contract():
    """Extracted, not invented (ADR-0017): both of these were already this shape."""
    from hvk.parse import canvas, markdown

    assert isinstance(markdown.parse_file("# One\n", "One.md"), Parsed)
    assert isinstance(canvas.parse_file('{"nodes": []}', "Board.canvas"), Parsed)


def test_a_parser_names_the_file_when_the_file_cannot_name_itself():
    """A canvas has no frontmatter and no H1, so without this its contents would be findable
    only under an empty title."""
    from hvk.parse import canvas

    assert canvas.parse_file('{"nodes": []}', "Boards/Plan.canvas").title == "Plan"


def test_a_broken_file_comes_back_as_an_error_and_is_not_raised():
    """The contract, and the reason for it: one unreadable file must not stop a scan."""
    from hvk.parse import canvas

    result = canvas.parse_file("{not json", "Broken.canvas")
    assert result.error and "JSON" in result.error


def test_the_contract_holds_only_what_the_index_can_store():
    """A contract that can express something the index cannot store is a contract with a lie in
    it. If a field is added here, a table has to be added with it."""
    stored = {"title", "body", "props", "tags", "headings", "blocks", "links", "tasks", "error"}
    assert {f.name for f in model.Parsed.__dataclass_fields__.values()} == stored


# -- through a real scan ----------------------------------------------------------------------

def test_the_registry_decides_what_kind_each_file_is(index):
    _, conn, _ = index("basic")
    kinds = dict(conn.execute("SELECT path, kind FROM files"))
    assert kinds["Home.md"] == "note"
    assert kinds["attachments/diagram.png"] == "attachment"


def test_a_parser_registered_at_runtime_reaches_the_index(index, tmp_path, monkeypatch):
    """The whole claim of the interface, tested the only way that means anything: register a
    parser from outside the package and watch a scan use it, with no change to the core."""
    from hvk.parse.model import Tag

    def parse(text: str, path: str) -> Parsed:
        return Parsed(title="from the adapter", body=text,
                      tags=[Tag(tag="adapted", source="test", line=1)])

    monkeypatch.setattr(
        registry.REGISTRY, "parsers",
        [*registry.REGISTRY.parsers,
         Parser(name="test-format", extensions=("frob",), kind="frobnicated", parse=parse)],
    )

    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (vault / "Thing.frob").write_text("a searchable sentence", encoding="utf-8")

    _, conn, stats = index(vault)
    row = conn.execute("SELECT kind FROM files WHERE path = 'Thing.frob'").fetchone()
    assert row["kind"] == "frobnicated"
    assert stats.errors == 0
    assert [r["tag"] for r in conn.execute("SELECT tag FROM tags")] == ["adapted"]
    assert conn.execute(
        "SELECT title FROM fts WHERE fts MATCH 'searchable'"
    ).fetchone()["title"] == "from the adapter"


def test_the_registration_point_is_a_list_anyone_can_read():
    """`BUILT_IN` is the documented place a parser in this repository is added, and adding one
    is meant to be one line. If this ever grows a mechanism, the docs have to grow with it."""
    assert [p.name for p in BUILT_IN] == ["markdown", "canvas", "base", "kanban"]
