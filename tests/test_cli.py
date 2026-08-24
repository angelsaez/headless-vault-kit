"""The command line: what the agent actually calls."""

from __future__ import annotations

import json

import pytest

from hvk import cli
from conftest import VAULTS


@pytest.fixture
def run(tmp_path):
    """Run hvk against a synthetic vault with a throwaway index, one index per vault."""
    scanned: set[str] = set()

    def _run(*args, vault="basic"):
        index_dir = tmp_path / f"{vault}-idx"
        base = ["--vault", str(VAULTS / vault), "--index", str(index_dir)]
        if vault not in scanned:
            cli.main([*base, "scan"])
            scanned.add(vault)
        return cli.main([*base, *args])

    _run("info")  # forces the default vault to be indexed before the test body runs
    return _run


def test_scan_reports_what_it_did(run, capsys):
    capsys.readouterr()
    assert run("scan", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["files"] == 8
    assert payload["unchanged"] == 8


def test_search_finds_a_note(run, capsys):
    capsys.readouterr()
    assert run("search", "milestones") == 0
    out = capsys.readouterr().out
    assert "Projects/Alpha.md" in out


def test_search_accepts_a_tag_filter(run, capsys):
    capsys.readouterr()
    run("search", "milestones tag:project", "--json")
    rows = json.loads(capsys.readouterr().out)
    assert {row["path"] for row in rows} == {"Projects/Alpha.md", "Projects/Beta.md"}


def test_search_accepts_a_path_filter(run, capsys):
    capsys.readouterr()
    run("search", "Alpha path:Daily", "--json")
    rows = json.loads(capsys.readouterr().out)
    assert [row["path"] for row in rows] == ["Daily/2026-08-20.md"]


def test_search_with_only_filters_is_an_error(run, capsys):
    assert run("search", "tag:project") == 2
    assert "nothing left to search" in capsys.readouterr().err


def test_backlinks_by_bare_name_and_by_path_agree(run, capsys):
    capsys.readouterr()
    run("backlinks", "Alpha", "--json")
    by_name = json.loads(capsys.readouterr().out)
    run("backlinks", "Projects/Alpha.md", "--json")
    by_path = json.loads(capsys.readouterr().out)
    assert by_name == by_path
    assert {row["source"] for row in by_name} == {
        "Areas/Reading.md", "Daily/2026-08-20.md", "Home.md", "Projects/Beta.md", "Tasks.md",
    }


def test_backlinks_of_an_unknown_note_is_an_error(run, capsys):
    assert run("backlinks", "Does Not Exist") == 2
    assert "no file in the index matches" in capsys.readouterr().err


def test_links_broken_and_ambiguous(run, capsys):
    run("info", vault="links")  # the implicit first scan prints; get it out of the way
    capsys.readouterr()
    run("links", "--broken", "--json", vault="links")
    broken = json.loads(capsys.readouterr().out)
    assert {row["target_raw"] for row in broken} == {"Missing Note", "diagram"}

    run("links", "--ambiguous", "--json", vault="links")
    ambiguous = json.loads(capsys.readouterr().out)
    assert all(row["candidates"] > 1 for row in ambiguous)


def test_links_of_one_note(run, capsys):
    capsys.readouterr()
    run("links", "Home.md", "--json")
    rows = json.loads(capsys.readouterr().out)
    assert {row["source"] for row in rows} == {"Home.md"}


def test_info_counts_match_the_vault(run, capsys):
    capsys.readouterr()
    run("info", "--json")
    payload = json.loads(capsys.readouterr().out)
    assert payload["notes"] == 7
    assert payload["attachments"] == 1
    assert payload["broken_links"] == 0
    assert payload["parse_errors"] == 0


def test_json_output_is_machine_readable_everywhere(run, capsys):
    for args in (("info",), ("search", "Alpha"), ("backlinks", "Alpha"), ("links",)):
        capsys.readouterr()
        run(*args, "--json")
        json.loads(capsys.readouterr().out)  # raises if it is not valid JSON


def test_querying_without_an_index_says_so(tmp_path, capsys):
    code = cli.main(
        ["--vault", str(VAULTS / "basic"), "--index", str(tmp_path / "empty"), "info"]
    )
    assert code == 2
    assert "Run 'hvk scan' first" in capsys.readouterr().err

def test_a_closed_pipe_says_nothing_on_stderr(tmp_path):
    """`hvk tasks | head` is what the skill tells an agent to do, so it must stay quiet.

    The size matters and is the whole trick. A table of a few tens of kilobytes fits in the
    buffers, so the write itself never fails and the pipe being gone is only discovered when
    Python flushes on the way out -- outside any handler, which is why the interpreter used to
    print "Exception ignored in ... BrokenPipeError" itself. Make the vault much larger and the
    write fails instead, the handler catches it, and the test passes with the fix removed.
    """
    import shutil
    import subprocess
    import sys

    if not shutil.which("head"):
        pytest.skip("needs head to build a real pipeline")

    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    for note in range(30):
        body = "".join(f"- [ ] task {note}-{item} {'x' * 60}\n" for item in range(10))
        (vault / f"N{note}.md").write_text(f"# N{note}\n{body}", encoding="utf-8")

    hvk = '"%s" -m hvk --vault "%s" --index "%s"' % (sys.executable, vault, tmp_path / "idx")
    subprocess.run(hvk + " scan", shell=True, capture_output=True, check=True)
    done = subprocess.run(hvk + " tasks | head -1", shell=True, capture_output=True)

    assert b"Exception ignored" not in done.stderr, done.stderr.decode("utf-8", "replace")
    assert b"BrokenPipeError" not in done.stderr, done.stderr.decode("utf-8", "replace")
