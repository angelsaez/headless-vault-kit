"""`hvk doctor`: what only hvk can know about its own installation (phase 6).

The distinction that matters here is failure against warning. Something else on the machine
already watches the services; this exists to answer "does the index still describe the vault",
and to do it with an exit code a cron line can branch on. A check that wakes somebody over a
note with broken YAML is a check they will stop reading, so those are warnings and the exit
code stays zero.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from hvk import cli, doctor, paths
from hvk import scan as scanner


@pytest.fixture
def vault(tmp_path):
    """A small vault, indexed, with its locations."""
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    (root / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (root / "One.md").write_text("# One\n\nLinks to [[Two]].\n", encoding="utf-8")
    (root / "Two.md").write_text("# Two\n", encoding="utf-8")

    location = paths.Locations(vault=root.resolve(), index_dir=tmp_path / "idx")
    scanner.scan(location)
    return location


def statuses(report) -> dict:
    return {check.name: check.status for check in report.checks}


def test_a_healthy_installation_reports_no_failures(vault):
    report = doctor.run(vault)
    assert report.failures == 0
    assert statuses(report)["index matches the vault"] == "ok"


def test_a_note_added_without_indexing_is_a_failure(vault):
    """The question the machine's own monitoring cannot answer."""
    (vault.vault / "Three.md").write_text("# Three\n", encoding="utf-8")

    report = doctor.run(vault)
    assert statuses(report)["index matches the vault"] == "fail"
    assert report.failures == 1
    detail = next(c.detail for c in report.checks if c.name == "index matches the vault")
    assert "3 notes on disk, 2 in the index" in detail
    assert "hvk scan" in detail, "a failure should say what fixes it"


def test_a_note_deleted_without_indexing_is_also_a_failure(vault):
    (vault.vault / "Two.md").unlink()
    report = doctor.run(vault)
    assert statuses(report)["index matches the vault"] == "fail"
    assert "indexed but gone" in next(
        c.detail for c in report.checks if c.name == "index matches the vault"
    )


def test_freshness_is_not_measured_by_timestamp(vault):
    """A vault nobody has touched for a week is healthy, and a stale `last_scan` says nothing.

    This is the reason the check counts notes instead of reading a clock, so it is worth a test
    of its own: doing nothing must not degrade the report.
    """
    report = doctor.run(vault)
    assert report.failures == 0


def test_broken_frontmatter_warns_but_does_not_fail(vault):
    (vault.vault / "Bad.md").write_text("---\nthis: [never closes\n---\n# Bad\n", encoding="utf-8")
    scanner.scan(vault)

    report = doctor.run(vault)
    assert statuses(report)["notes parse cleanly"] == "warn"
    assert report.failures == 0, "the vault's own YAML is not an outage"


def test_broken_links_warn_but_do_not_fail(vault):
    (vault.vault / "One.md").write_text("# One\n\n[[Nowhere]]\n", encoding="utf-8")
    scanner.scan(vault)

    report = doctor.run(vault)
    assert statuses(report)["links resolve"] == "warn"
    assert report.failures == 0


def test_a_missing_index_fails_and_stops_there(tmp_path):
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    report = doctor.run(paths.Locations(vault=root.resolve(), index_dir=tmp_path / "nothing"))

    assert report.failures == 1
    assert report.checks[0].name == "index is readable"


# -- stuck jobs ------------------------------------------------------------------------------

def order(vault, name: str, status: str, started: str | None) -> None:
    lines = ["type: job", f"status: {status}", "profile: p", "output: Out.md"]
    if started:
        lines.append(f"started: {started}")
    body = "---\n" + "\n".join(lines) + "\n---\nbody\n"
    (vault.vault / "Jobs" / f"{name}.md").write_text(body, encoding="utf-8")


def test_a_job_claimed_long_ago_is_a_failure(vault):
    """ADR-0009 never retries a stuck job on purpose, so something has to say it is stuck."""
    (vault.vault / "Jobs").mkdir()
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=9)).isoformat()
    order(vault, "Stalled", "running", old)

    report = doctor.run(vault, jobs_dir="Jobs", stuck_hours=6)
    assert statuses(report)["no job is stuck"] == "fail"
    assert "Jobs/Stalled.md" in next(c.detail for c in report.checks if c.name == "no job is stuck")


def test_a_job_claimed_just_now_is_not_stuck(vault):
    (vault.vault / "Jobs").mkdir()
    order(vault, "Working", "running", dt.datetime.now(dt.timezone.utc).isoformat())

    report = doctor.run(vault, jobs_dir="Jobs", stuck_hours=6)
    assert statuses(report)["no job is stuck"] == "ok"


def test_finished_and_pending_jobs_are_not_stuck(vault):
    (vault.vault / "Jobs").mkdir()
    order(vault, "Done", "done", None)
    order(vault, "Waiting", "pending", None)

    report = doctor.run(vault, jobs_dir="Jobs", stuck_hours=6)
    assert statuses(report)["no job is stuck"] == "ok"


def test_jobs_are_only_checked_when_a_directory_is_given(vault):
    assert "no job is stuck" not in statuses(doctor.run(vault))


# -- through the command line ----------------------------------------------------------------

def test_the_command_exits_zero_when_only_warnings(vault, capsys):
    (vault.vault / "Bad.md").write_text("---\nbroken: [\n---\n", encoding="utf-8")
    scanner.scan(vault)

    code = cli.main(["--vault", str(vault.vault), "--index", str(vault.index_dir), "doctor"])
    assert code == 0, "warnings must not page anybody"
    assert "warn" in capsys.readouterr().out


def test_the_command_exits_non_zero_on_a_real_failure(vault, capsys):
    (vault.vault / "Unindexed.md").write_text("# New\n", encoding="utf-8")
    code = cli.main(["--vault", str(vault.vault), "--index", str(vault.index_dir), "doctor"])
    assert code == 1


def test_json_output_is_one_record_per_check(vault, capsys):
    cli.main(["--vault", str(vault.vault), "--index", str(vault.index_dir), "doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert {row["check"] for row in payload} >= {"index is readable", "index matches the vault"}
    assert all(row["status"] in ("ok", "warn", "fail") for row in payload)
