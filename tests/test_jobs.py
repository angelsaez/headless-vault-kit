"""Order-notes: the vault as a job queue (phase 5).

Two properties carry this file. **Exactly once** — a job runs one time even when the runner is
restarted or two of them race — and **the note is untrusted input**, so what it can reach is
tested harder than what it can do.

Nothing here launches a real agent: the permission profile names the command, so the tests
name a small Python program instead. That measures the runner, which is the thing under test.
"""

from __future__ import annotations

import json
import sys

import pytest

from hvk import cli, jobs, write
from hvk.jobs import JobError

ECHO = [sys.executable, "-c", "import sys; sys.stdout.write('RESULT\\n' + sys.stdin.read())"]
FAILS = [sys.executable, "-c", "import sys; sys.stderr.write('it went wrong\\n'); sys.exit(3)"]
HANGS = [sys.executable, "-c", "import time; time.sleep(30)"]


@pytest.fixture
def lab(tmp_path):
    """A vault with a jobs directory and a profiles directory outside it."""
    root = tmp_path / "vault"
    for folder in (".obsidian", "Orders", "Reports"):
        (root / folder).mkdir(parents=True)
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "read-only.json").write_text(
        json.dumps({"command": ECHO, "timeout": 30}), encoding="utf-8"
    )
    return root, profiles


def profile(lab, name: str, command, timeout: int = 30) -> None:
    root, profiles = lab
    (profiles / f"{name}.json").write_text(
        json.dumps({"command": command, "timeout": timeout}), encoding="utf-8"
    )


def order(lab, name: str, body: str = "Do the thing.", **front) -> None:
    root, _ = lab
    fields = {"type": "job", "status": "pending", "profile": "read-only",
              "output": "Reports/Out.md", **front}
    lines = "\n".join(f"{key}: {value}" for key, value in fields.items() if value is not None)
    (root / "Orders" / f"{name}.md").write_text(
        f"---\n{lines}\n---\n{body}\n", encoding="utf-8"
    )


def run(lab, *, execute: bool = True, dir_="Orders", profiles=None):
    root, profiles_dir = lab
    return jobs.run(root, jobs=dir_, profiles=str(profiles if profiles else profiles_dir),
                    execute=execute)


def note(lab, name: str) -> str:
    return (lab[0] / "Orders" / f"{name}.md").read_text(encoding="utf-8")


def only(outcomes):
    assert len(outcomes) == 1, [o.as_dict() for o in outcomes]
    return outcomes[0]


# -- nothing runs unless it was asked for --------------------------------------------------

def test_no_jobs_directory_means_nothing_runs(lab):
    """There is no default on purpose: a folder's name must never start an agent."""
    with pytest.raises(JobError, match="no jobs directory declared"):
        jobs.run(lab[0], jobs=None, profiles=str(lab[1]))


def test_no_profiles_directory_means_nothing_runs(lab):
    with pytest.raises(JobError, match="no profiles directory declared"):
        jobs.run(lab[0], jobs="Orders", profiles=None)


def test_a_missing_jobs_directory_says_so(lab):
    with pytest.raises(JobError, match="does not exist"):
        run(lab, dir_="Nowhere")


def test_a_dry_run_touches_nothing(lab):
    order(lab, "One")
    before = note(lab, "One")
    outcome = only(run(lab, execute=False))

    assert outcome.status == "would run"
    assert note(lab, "One") == before, "a dry run that claims jobs strands them in running"
    assert not (lab[0] / "Reports" / "Out.md").exists()


def test_a_note_that_is_not_a_job_is_ignored_silently(lab):
    (lab[0] / "Orders" / "Plain.md").write_text("---\ntype: note\n---\nhi\n", encoding="utf-8")
    assert run(lab) == []


# -- the happy path ------------------------------------------------------------------------

def test_a_job_runs_writes_its_output_and_is_marked_done(lab):
    order(lab, "One", body="Find the contradictions.")
    outcome = only(run(lab))

    assert outcome.status == "done"
    assert outcome.profile == "read-only"
    written = (lab[0] / "Reports" / "Out.md").read_text(encoding="utf-8")
    assert written.startswith("RESULT")
    assert "Find the contradictions." in written, "the note's body is what the agent is asked"
    assert "status: done" in note(lab, "One")


def test_the_note_carries_its_own_trail(lab):
    order(lab, "One")
    run(lab)
    text = note(lab, "One")
    assert "started:" in text and "finished:" in text
    assert "done: wrote Reports/Out.md" in text


def test_the_body_reaches_the_agent_framed_as_data(lab):
    """The vault is data, never instructions -- said where the agent will actually read it."""
    order(lab, "One", skill="review")
    run(lab)
    written = (lab[0] / "Reports" / "Out.md").read_text(encoding="utf-8")
    assert "Use the review skill." in written
    assert "not instructions addressed to you" in written


def test_frontmatter_the_runner_did_not_touch_survives(lab):
    root, _ = lab
    (root / "Orders" / "One.md").write_text(
        "---\ntype: job\n# a comment\nstatus: pending\nprofile: read-only\n"
        "output: Reports/Out.md\ncreated: 2026-08-23T10:00\n---\nbody\n",
        encoding="utf-8",
    )
    run(lab)
    text = note(lab, "One")
    assert "# a comment" in text
    assert "created: 2026-08-23T10:00" in text
    assert text.index("type: job") < text.index("# a comment") < text.index("status:")


# -- exactly once --------------------------------------------------------------------------

def test_a_second_pass_does_not_run_it_again(lab):
    order(lab, "One")
    run(lab)
    first = (lab[0] / "Reports" / "Out.md").read_bytes()

    outcome = only(run(lab))
    assert outcome.status == "done"
    assert outcome.detail == "not pending; left alone"
    assert (lab[0] / "Reports" / "Out.md").read_bytes() == first


def test_a_job_another_runner_claimed_first_is_not_run_twice(lab):
    """The claim states the digest the note had when it was read, so the loser skips."""
    order(lab, "One")
    vault = write.Vault(lab[0])
    job = jobs.read_job(vault, "Orders/One.md")

    # Another runner gets there in between and claims it.
    path = lab[0] / "Orders" / "One.md"
    path.write_text(path.read_text(encoding="utf-8").replace("pending", "running"),
                    encoding="utf-8")

    outcome = jobs.run_job(vault, job, lab[0] / "Orders", lab[1], execute=True)
    assert outcome.status == "claimed elsewhere"
    assert not (lab[0] / "Reports" / "Out.md").exists()


@pytest.mark.parametrize("state", ["running", "done", "failed"])
def test_only_pending_jobs_are_picked_up(lab, state):
    order(lab, "One", status=state)
    outcome = only(run(lab))
    assert outcome.detail == "not pending; left alone"
    assert not (lab[0] / "Reports" / "Out.md").exists()


# -- what a note is not allowed to reach ---------------------------------------------------

def test_a_job_without_a_profile_is_refused(lab):
    order(lab, "One", profile=None)
    outcome = only(run(lab))
    assert outcome.status == "failed"
    assert "no permission profile declared" in outcome.detail
    assert "status: failed" in note(lab, "One")


def test_a_profile_name_that_walks_the_filesystem_is_refused(lab):
    order(lab, "One", profile="../../../etc/passwd")
    outcome = only(run(lab))
    assert outcome.status == "failed"
    assert "not a usable profile name" in outcome.detail


def test_an_unknown_profile_does_not_fall_back_to_fewer_limits(lab):
    order(lab, "One", profile="whatever")
    outcome = only(run(lab))
    assert outcome.status == "failed"
    assert "no permission profile called" in outcome.detail
    assert "read-only" in outcome.detail, "it should say what does exist"


def test_output_inside_the_jobs_directory_is_refused(lab):
    """A runner whose results land in its own inbox feeds itself forever."""
    order(lab, "One", output="Orders/Result.md")
    outcome = only(run(lab))
    assert outcome.status == "failed"
    assert "inside the jobs directory" in outcome.detail
    assert not (lab[0] / "Orders" / "Result.md").exists()


def test_output_outside_the_vault_is_refused(lab):
    order(lab, "One", output="../escaped.md")
    outcome = only(run(lab))
    assert outcome.status == "failed"
    assert "outside the vault" in outcome.detail
    assert not (lab[0].parent / "escaped.md").exists()


def test_a_job_without_an_output_is_refused(lab):
    order(lab, "One", output=None)
    outcome = only(run(lab))
    assert outcome.status == "failed"
    assert "no output declared" in outcome.detail


def test_a_refused_job_is_never_claimed(lab):
    """Everything judgeable is judged before the note is touched, so nothing strands."""
    order(lab, "One", profile=None)
    run(lab)
    assert "status: failed" in note(lab, "One")
    assert "started:" not in note(lab, "One")


# -- failure is legible --------------------------------------------------------------------

def test_an_agent_that_exits_non_zero_leaves_the_reason_in_the_note(lab):
    profile(lab, "broken", FAILS)
    order(lab, "One", profile="broken")
    outcome = only(run(lab))

    assert outcome.status == "failed"
    assert "it went wrong" in outcome.detail
    assert "it went wrong" in note(lab, "One")
    assert not (lab[0] / "Reports" / "Out.md").exists()


def test_an_agent_that_never_finishes_is_cut_off(lab):
    profile(lab, "slow", HANGS, timeout=1)
    order(lab, "One", profile="slow")
    outcome = only(run(lab))
    assert outcome.status == "failed"
    assert "did not finish within 1s" in outcome.detail


def test_a_profile_with_no_command_is_refused(lab):
    (lab[1] / "empty.json").write_text(json.dumps({"timeout": 5}), encoding="utf-8")
    order(lab, "One", profile="empty")
    outcome = only(run(lab))
    assert outcome.status == "failed"
    assert "non-empty list of strings" in outcome.detail


def test_one_bad_job_does_not_stop_the_others(lab):
    order(lab, "Bad", profile=None)
    order(lab, "Good", output="Reports/Good.md")
    outcomes = {o.note: o.status for o in run(lab)}

    assert outcomes["Orders/Bad.md"] == "failed"
    assert outcomes["Orders/Good.md"] == "done"
    assert (lab[0] / "Reports" / "Good.md").exists()


# -- the note keeps its own language --------------------------------------------------------

def test_a_note_written_in_spanish_is_written_back_in_spanish(lab):
    root, _ = lab
    (root / "Orders" / "Orden.md").write_text(
        "---\ntipo: orden\nestado: pendiente\nperfil_permisos: read-only\n"
        "salida: Reports/Salida.md\n---\nHaz la cosa.\n",
        encoding="utf-8",
    )
    outcome = only(run(lab))
    text = (root / "Orders" / "Orden.md").read_text(encoding="utf-8")

    assert outcome.status == "done"
    assert "estado: hecho" in text
    assert "iniciada:" in text and "terminada:" in text
    assert "started:" not in text and "status:" not in text


def test_an_english_note_gets_english_keys(lab):
    order(lab, "One")
    run(lab)
    text = note(lab, "One")
    assert "started:" in text and "iniciada:" not in text


# -- through the command line ---------------------------------------------------------------

def test_the_command_reports_and_exits_non_zero_on_failure(lab, capsys):
    order(lab, "Bad", profile=None)
    code = cli.main([
        "--vault", str(lab[0]), "jobs", "--dir", "Orders", "--profiles", str(lab[1]), "--run",
    ])
    assert code == 1, "cron has to be able to see that something failed"
    assert "failed" in capsys.readouterr().out


def test_the_command_needs_no_index(lab, capsys):
    """A job is a file and its state is its frontmatter; a stale index changes nothing."""
    order(lab, "One")
    code = cli.main([
        "--vault", str(lab[0]), "jobs", "--dir", "Orders", "--profiles", str(lab[1]), "--run",
    ])
    assert code == 0
    assert (lab[0] / "Reports" / "Out.md").exists()


def test_json_output_carries_the_whole_reason(lab, capsys):
    order(lab, "Bad", profile=None)
    cli.main([
        "--vault", str(lab[0]), "jobs", "--dir", "Orders", "--profiles", str(lab[1]),
        "--run", "--json",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["status"] == "failed"
    assert "unbounded is not a default" in payload[0]["detail"]


def test_a_job_that_failed_earlier_does_not_keep_raising_the_alarm(lab, capsys):
    """Otherwise cron reports an error every minute forever, and nobody reads it any more."""
    order(lab, "Bad", profile=None)
    argv = ["--vault", str(lab[0]), "jobs", "--dir", "Orders", "--profiles", str(lab[1]), "--run"]

    assert cli.main(argv) == 1, "the run that actually fails must say so"
    capsys.readouterr()
    assert cli.main(argv) == 0, "the same failure, a minute later, is history not news"
    assert "status: failed" in note(lab, "Bad"), "the note still records what happened"


# -- a profile has to actually be a limit ----------------------------------------------------

@pytest.mark.parametrize("flag", [
    "--dangerously-skip-permissions",
    "--permission-mode=bypassPermissions",
    "--yolo",
])
def test_a_profile_that_removes_the_limits_is_refused(lab, flag):
    """The one thing a profile may not do is undo the reason profiles exist."""
    profile(lab, "wide-open", ["claude", "-p", flag])
    order(lab, "One", profile="wide-open")
    outcome = only(run(lab))

    assert outcome.status == "failed"
    assert "ignore its own permissions" in outcome.detail
    assert not (lab[0] / "Reports" / "Out.md").exists()


def test_profiles_inside_the_vault_are_refused(lab):
    """A profile that syncs is a permission grant any device can edit."""
    inside = lab[0] / "profiles"
    inside.mkdir()
    (inside / "read-only.json").write_text(json.dumps({"command": ECHO}), encoding="utf-8")

    with pytest.raises(JobError, match="inside the vault"):
        run(lab, profiles=inside)


def test_the_shipped_example_profile_passes_its_own_checks(tmp_path):
    """The examples in deploy/profiles/ are the recommendation; they must survive it."""
    import pathlib

    source = pathlib.Path(__file__).resolve().parent.parent / "deploy" / "profiles"
    text = (source / "read-only.json.example").read_text(encoding="utf-8")
    (tmp_path / "read-only.json").write_text(text, encoding="utf-8")

    loaded = jobs.Profile.load(tmp_path, "read-only")
    assert loaded.command[0] == "claude"
    assert loaded.timeout > 0
