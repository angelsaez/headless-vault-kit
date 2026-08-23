"""Materialised views: a base's table kept up to date inside a note (phase 4).

The exit criterion of the plan is negative -- regenerating twice with no changes must produce
no diff -- so most of what matters here is asserted on the *bytes of the note*, not on what
the command printed.

Nothing in this file writes into ``test-vaults/``. Anything that applies a change copies the
vault into ``tmp_path`` first, for the same reason development never points at the real vault.
"""

from __future__ import annotations

import json
import shutil

import pytest

from hvk import cli, views, write
from hvk.views import ViewError
from conftest import VAULTS

BEGIN, END = views.DIALECTS["vista"]


@pytest.fixture
def views_vault(tmp_path):
    """A writable copy of ``test-vaults/views``, with its own index."""
    vault = tmp_path / "views"
    shutil.copytree(VAULTS / "views", vault)
    return vault


@pytest.fixture
def run(views_vault, tmp_path, capsys):
    base = ["--vault", str(views_vault), "--index", str(tmp_path / "idx")]
    cli.main([*base, "scan"])
    capsys.readouterr()

    def _run(*args):
        code = cli.main([*base, *args])
        return code, capsys.readouterr()

    return _run


def note(vault, name: str) -> bytes:
    return (vault / name).read_bytes()


# -- reading the declaration ---------------------------------------------------------------

def test_a_note_with_nothing_declared_yields_nothing():
    assert views.declarations("# Just a note\n") == []


def test_the_plan_s_own_example_parses():
    text = (
        '%% vista: base "000 BASE habilidades.base" vista "Tabla" cada 30m %%\n'
        f"{BEGIN}\n{END}\n"
    )
    declared = views.declarations(text)
    assert len(declared) == 1
    assert declared[0].base == "000 BASE habilidades.base"
    assert declared[0].view == "Tabla"
    assert declared[0].every == "30m"
    assert declared[0].every_minutes == 30


def test_the_english_dialect_says_the_same_thing():
    text = '%% view: base "X.base" view "Table" every 2h %%\n<!-- view:start -->\n<!-- view:end -->\n'
    declared = views.declarations(text)
    assert (declared[0].base, declared[0].view, declared[0].every_minutes) == ("X.base", "Table", 120)


def test_the_view_and_the_interval_are_optional():
    text = f'%% vista: base "X.base" %%\n{BEGIN}\n{END}\n'
    declared = views.declarations(text)
    assert declared[0].view is None and declared[0].every is None


def test_a_directive_with_no_base_is_refused():
    with pytest.raises(ViewError, match="no base named"):
        views.declarations(f'%% vista: vista "Tabla" %%\n{BEGIN}\n{END}\n')


def test_a_misspelled_setting_is_refused_rather_than_ignored():
    """Silently skipping a typo renders the wrong thing, which is worse than rendering none."""
    with pytest.raises(ViewError, match="not something a view understands"):
        views.declarations(f'%% vista: base "X.base" vsita "Tabla" %%\n{BEGIN}\n{END}\n')


def test_an_interval_that_is_not_an_interval_is_refused():
    with pytest.raises(ViewError, match="is not an interval"):
        views.declarations(f'%% vista: base "X.base" cada siempre %%\n{BEGIN}\n{END}\n')


def test_a_directive_without_markers_is_refused():
    with pytest.raises(ViewError, match="no <!-- vista:inicio --> block follows"):
        views.declarations('%% vista: base "X.base" %%\nplain text\n')


def test_markers_without_a_directive_are_refused():
    """A block nothing claims is a block nothing will ever refresh."""
    with pytest.raises(ViewError, match="nothing saying what generates it"):
        views.declarations(f"# Note\n\n{BEGIN}\nstale forever\n{END}\n")


def test_two_directives_sharing_one_block_are_refused():
    text = f'%% vista: base "A.base" %%\n%% vista: base "B.base" %%\n{BEGIN}\n{END}\n'
    with pytest.raises(ViewError, match="needs its own markers"):
        views.declarations(text)


def test_a_note_may_hold_several_views():
    text = (
        f'%% vista: base "A.base" %%\n{BEGIN}\none\n{END}\n\n'
        f'%% vista: base "B.base" %%\n{BEGIN}\ntwo\n{END}\n'
    )
    declared = views.declarations(text)
    assert [d.base for d in declared] == ["A.base", "B.base"]
    assert declared[0].block.start < declared[1].block.start


# -- rendering -----------------------------------------------------------------------------

def test_the_dry_run_reports_what_would_change_and_writes_nothing(run, views_vault):
    before = note(views_vault, "Panel.md")
    code, output = run("views")
    assert code == 0
    assert "stale" in output.out
    assert note(views_vault, "Panel.md") == before


def test_applying_writes_the_table_between_the_markers(run, views_vault):
    code, _ = run("views", "--apply")
    assert code == 0
    text = note(views_vault, "Panel.md").decode("utf-8")

    assert "| Habilidad | Autor | delegable |" in text
    assert "Escritura" in text and "Negociación" in text
    assert "Una nota cualquiera" not in text, "the base's filter has to be honoured"
    assert text.index(BEGIN) < text.index("| Habilidad") < text.index(END)


def test_everything_outside_the_markers_survives(run, views_vault):
    before = note(views_vault, "Panel.md").decode("utf-8")
    run("views", "--apply")
    after = note(views_vault, "Panel.md").decode("utf-8")

    head, tail = before.split(BEGIN)[0], before.split(END)[1]
    assert after.startswith(head), "frontmatter and heading must be untouched"
    assert after.endswith(tail), "the text after the block must be untouched"


def test_regenerating_twice_produces_no_diff(run, views_vault):
    """The exit criterion of phase 4, asserted on the bytes rather than on the report."""
    run("views", "--apply")
    first = note(views_vault, "Panel.md")

    code, output = run("views", "--apply")
    assert code == 0
    assert note(views_vault, "Panel.md") == first
    assert "unchanged" in output.out and "written" not in output.out


def test_a_view_that_is_up_to_date_is_reported_as_such(run):
    run("views", "--apply")
    code, output = run("views")
    assert code == 0
    assert "up to date" in output.out
    assert "would change" not in output.out


def test_the_file_column_becomes_a_link_that_survives_a_table_cell(run, views_vault):
    run("views", "--apply")
    text = note(views_vault, "Panel.md").decode("utf-8")
    # Escaped pipe: that is how a wikilink alias is written inside a Markdown table.
    assert "[[Habilidades/Escritura\\|Escritura.md]]" in text


def test_nothing_stamps_the_output_with_a_time(run, views_vault):
    """A "generated at" line would make every regeneration a diff, forever."""
    run("views", "--apply")
    body = note(views_vault, "Panel.md").decode("utf-8").split(BEGIN)[1].split(END)[0]
    assert "202" not in body, f"the generated block looks like it carries a date: {body!r}"


def test_both_dialects_are_rendered(run, views_vault):
    run("views", "--apply")
    assert "| Habilidad |" in note(views_vault, "Dashboard.md").decode("utf-8")


def test_a_note_can_be_singled_out(run, views_vault):
    before = note(views_vault, "Dashboard.md")
    code, output = run("views", "Panel.md", "--apply")
    assert code == 0
    assert "Dashboard.md" not in output.out
    assert note(views_vault, "Dashboard.md") == before


def test_json_output_carries_one_record_per_view(run):
    code, output = run("views", "--json")
    payload = json.loads(output.out)
    assert {row["note"] for row in payload} == {"Panel.md", "Dashboard.md"}
    assert all(row["status"] == "stale" for row in payload)
    assert all(row["rows"] == 2 for row in payload)


# -- line endings and frontmatter, through the whole command -------------------------------

def test_a_crlf_note_stays_crlf(run, views_vault):
    """Built here rather than committed: .gitattributes would normalise it in the repository."""
    path = views_vault / "Panel.md"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    run("views", "--apply")

    written = path.read_bytes()
    assert b"| Habilidad" in written
    assert written.count(b"\r\n") == written.count(b"\n"), "a lone \\n slipped in"


def test_frontmatter_is_returned_byte_for_byte(run, views_vault):
    path = views_vault / "Panel.md"
    original = path.read_bytes()
    frontmatter = original[: original.index(b"---", 3) + 4]
    run("views", "--apply")
    assert path.read_bytes().startswith(frontmatter)


# -- failure, one note at a time -----------------------------------------------------------

def test_a_missing_base_is_reported_without_stopping_the_others(run, views_vault):
    (views_vault / "Roto.md").write_text(
        f'%% vista: base "Nope.base" %%\n{BEGIN}\n{END}\n', encoding="utf-8"
    )
    code, output = run("views", "--apply")

    assert code == 1, "cron has to be able to see that something failed"
    assert "no such base file" in output.out
    assert "| Habilidad |" in note(views_vault, "Panel.md").decode("utf-8")


def test_a_base_outside_the_vault_is_refused(run, views_vault):
    """The base is named by a note, and a note is untrusted input."""
    (views_vault / "Fuga.md").write_text(
        f'%% vista: base "../../escape.base" %%\n{BEGIN}\n{END}\n', encoding="utf-8"
    )
    code, output = run("views", "--apply")
    assert code == 1
    assert "outside the vault" in output.out


def test_a_view_over_its_own_note_is_flagged(run, views_vault):
    """The shape a feedback loop takes: writing the note changes what the view sorts by."""
    (views_vault / "Habilidades" / "Panel propio.md").write_text(
        "---\ncategoría: habilidad\nautor: nadie\n---\n"
        f'%% vista: base "Habilidades.base" %%\n{BEGIN}\n{END}\n',
        encoding="utf-8",
    )
    run("scan")  # the warning can only fire once the index knows the note exists
    code, output = run("views", "--apply")
    assert code == 0
    assert "one of its own rows" in output.out


def test_a_note_that_declares_nothing_is_not_reported(run):
    code, output = run("views")
    assert "Una nota cualquiera" not in output.out


# -- the writer's guarantees, reached through this command ---------------------------------

def test_an_unchanged_view_does_not_touch_the_note(run, views_vault, tmp_path):
    import os

    run("views", "--apply")
    path = views_vault / "Panel.md"
    older = path.stat().st_mtime_ns - 10_000_000_000
    os.utime(path, ns=(older, older))
    stamp = path.stat().st_mtime_ns

    run("views", "--apply")
    assert path.stat().st_mtime_ns == stamp, "sync and the watcher must not be woken for nothing"


def test_a_note_holding_two_views_is_written_once(run, views_vault, monkeypatch):
    (views_vault / "Doble.md").write_text(
        f'%% vista: base "Habilidades.base" %%\n{BEGIN}\n{END}\n\n'
        f'%% vista: base "Habilidades.base" vista "Tabla" %%\n{BEGIN}\n{END}\n',
        encoding="utf-8",
    )
    writes = []
    original_write = write.Vault.write

    def counting(self, original, text):
        writes.append(str(original.path))
        return original_write(self, original, text)

    monkeypatch.setattr(write.Vault, "write", counting)
    run("views", "--apply")

    assert sum(1 for path in writes if path.endswith("Doble.md")) == 1
    assert note(views_vault, "Doble.md").decode("utf-8").count("| Habilidad |") == 2
