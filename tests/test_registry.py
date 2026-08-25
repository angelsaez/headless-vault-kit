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


# -- adapters from outside this repository (ADR-0019) -------------------------------------------

# A pretend third-party adapter, in nobody's repository but its author's. Written to a temporary
# directory rather than kept as a file here, because the point being tested is that hvk can use
# a parser it has never seen and does not ship.
ADAPTER = """
from hvk.parse.model import Parsed, Tag
from hvk.parse.registry import Parser, register


def parse_file(text, path):
    return Parsed(title="from outside", body=text,
                  tags=[Tag(tag="sketching", source="sketch", line=1)])


register(Parser(name="sketch", extensions=("sk",), kind="sketch", parse=parse_file))
"""


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    """Write an adapter module somewhere importable, and undo its registration afterwards.

    The registry is process-wide, so a test that registers a parser and walks away changes what
    every later test sees. Restoring the list is what keeps these independent.
    """
    import sys

    package = tmp_path / "pkg"
    package.mkdir()
    (package / "hvk_sketch.py").write_text(ADAPTER, encoding="utf-8")
    monkeypatch.syspath_prepend(str(package))
    monkeypatch.setattr(registry.REGISTRY, "parsers", list(registry.REGISTRY.parsers))
    yield "hvk_sketch"
    sys.modules.pop("hvk_sketch", None)


def test_nothing_is_loaded_when_nothing_is_declared(monkeypatch):
    """No default, like every other dangerous setting here. Unset means no adapter loads, and it
    must cost nothing: this runs once per command, in front of the guard hook included."""
    monkeypatch.delenv(registry.ENV_VAR, raising=False)
    assert registry.load_declared() == []


def test_a_declared_module_is_imported_and_registers_itself(adapter, monkeypatch):
    monkeypatch.setenv(registry.ENV_VAR, adapter)
    assert registry.load_declared() == [adapter]
    assert registry.REGISTRY.select("sk", "", "Board.sk").name == "sketch"


@pytest.mark.parametrize("spec", ["hvk_sketch", " hvk_sketch ", "hvk_sketch,", "hvk_sketch  ,"])
def test_the_list_is_read_forgivingly(adapter, spec):
    assert registry.load_declared(spec) == ["hvk_sketch"]


def test_a_module_that_cannot_be_imported_stops_the_command(monkeypatch):
    """Loudly, on purpose. The quiet alternative is worse: an adapter named with a typo loads
    nothing, the vault indexes without it, and every file of that format is silently missing
    what the adapter contributes. Nobody checks an index for the absence of something."""
    monkeypatch.setenv(registry.ENV_VAR, "no_such_module_anywhere")
    with pytest.raises(registry.ParserError, match="could not be imported"):
        registry.load_declared()


def test_the_failure_names_the_module_and_the_variable(monkeypatch):
    monkeypatch.setenv(registry.ENV_VAR, "no_such_module_anywhere")
    with pytest.raises(registry.ParserError) as failure:
        registry.load_declared()
    assert "no_such_module_anywhere" in str(failure.value)
    assert registry.ENV_VAR in str(failure.value)


def test_a_declared_adapter_reaches_a_real_scan_from_the_command_line(
    adapter, tmp_path, monkeypatch, capsys
):
    """The whole point of ADR-0019, and the gap it closes: before this, an adapter living in
    somebody else's package could be reached from Python and never from `hvk`."""
    from hvk import cli, db

    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (vault / "Board.sk").write_text("a sketch", encoding="utf-8")

    monkeypatch.setenv(registry.ENV_VAR, adapter)
    assert cli.main(["--vault", str(vault), "--index", str(tmp_path / "idx"), "scan"]) == 0
    capsys.readouterr()

    conn = db.connect(tmp_path / "idx" / "index.sqlite")
    try:
        assert conn.execute(
            "SELECT kind FROM files WHERE path = 'Board.sk'"
        ).fetchone()["kind"] == "sketch"
        assert [r["tag"] for r in conn.execute("SELECT tag FROM tags")] == ["sketching"]
    finally:
        conn.close()


def test_the_same_file_is_an_attachment_when_no_adapter_is_declared(tmp_path, monkeypatch, capsys):
    """The other half of the previous test, and the failure it is protecting against: a format
    nothing claims indexes silently, as a name and a hash."""
    from hvk import cli, db

    monkeypatch.delenv(registry.ENV_VAR, raising=False)
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (vault / "Board.sk").write_text("a sketch", encoding="utf-8")

    cli.main(["--vault", str(vault), "--index", str(tmp_path / "idx"), "scan"])
    capsys.readouterr()
    conn = db.connect(tmp_path / "idx" / "index.sqlite")
    try:
        assert conn.execute(
            "SELECT kind FROM files WHERE path = 'Board.sk'"
        ).fetchone()["kind"] == "attachment"
    finally:
        conn.close()


def test_a_bad_declaration_is_one_line_on_stderr_and_not_a_traceback(tmp_path, monkeypatch, capsys):
    from hvk import cli

    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    monkeypatch.setenv(registry.ENV_VAR, "no_such_module_anywhere")
    code = cli.main(["--vault", str(vault), "--index", str(tmp_path / "idx"), "scan"])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.err.startswith("hvk: ")
    assert "Traceback" not in captured.err


def test_doctor_says_which_parsers_are_loaded(adapter, tmp_path, monkeypatch):
    """`HVK_PARSERS` is read per process, so a variable set in the watcher's unit and not in
    your shell means the two disagree about what a file even is. This is the one place that can
    say so out loud."""
    from hvk import doctor

    monkeypatch.setenv(registry.ENV_VAR, adapter)
    check = doctor._parsers()
    assert check.status == doctor.OK
    assert "sketch" in check.detail and registry.ENV_VAR in check.detail


def test_doctor_fails_rather_than_hides_a_declaration_that_will_not_load(monkeypatch):
    from hvk import doctor

    monkeypatch.setenv(registry.ENV_VAR, "no_such_module_anywhere")
    assert doctor._parsers().status == doctor.FAIL
