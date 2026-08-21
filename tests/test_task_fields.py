"""Tier-2 task fields: the Tasks plugin and Dataview syntax (ADR-0004)."""

from __future__ import annotations

import json

import pytest

from hvk.parse.tasks import extract

DUE, SCHEDULED, START, DONE, CREATED = "\U0001F4C5", "⏳", "\U0001F6EB", "✅", "➕"
HIGHEST, HIGH, MEDIUM, LOW, LOWEST = "\U0001F53A", "⏫", "\U0001F53C", "\U0001F53D", "⏬"
REPEAT = "\U0001F501"


@pytest.fixture(scope="module")
def tasks_vault(tmp_path_factory):
    from hvk import db, paths
    from hvk import scan as scanner
    from conftest import VAULTS

    location = paths.Locations(
        vault=(VAULTS / "tasks").resolve(),
        index_dir=tmp_path_factory.mktemp("tasks-index"),
    )
    scanner.scan(location)
    conn = db.connect(location.db_path)
    yield conn
    conn.close()


def test_a_single_due_date():
    assert extract(f"buy milk {DUE} 2026-09-01") == ("buy milk", {"due": "2026-09-01"})


def test_several_dates_at_once():
    text, fields = extract(f"report {SCHEDULED} 2026-08-25 {DUE} 2026-09-01 {DONE} 2026-08-30")
    assert text == "report"
    assert fields == {"scheduled": "2026-08-25", "due": "2026-09-01", "done": "2026-08-30"}


def test_priority_markers():
    for marker, name in ((HIGHEST, "highest"), (HIGH, "high"), (MEDIUM, "medium"),
                         (LOW, "low"), (LOWEST, "lowest")):
        assert extract(f"task {marker}") == ("task", {"priority": name})


def test_recurrence_runs_until_the_next_marker():
    text, fields = extract(f"water plants {REPEAT} every week {DUE} 2026-09-02")
    assert text == "water plants"
    assert fields == {"recurrence": "every week", "due": "2026-09-02"}


def test_a_marker_without_a_date_is_left_alone():
    """The vocabulary is read, not guessed at: no date means no field."""
    text, fields = extract(f"vague {DUE} soon")
    assert fields == {}
    assert DUE in text


def test_bracketed_dataview_fields():
    assert extract("review [due:: 2026-10-01]") == ("review", {"due": "2026-10-01"})


def test_fields_we_do_not_read_stay_in_the_text():
    text, fields = extract("review [due:: 2026-10-01] [owner:: Ana]")
    assert fields == {"due": "2026-10-01"}
    assert "[owner:: Ana]" in text


def test_a_bracketed_value_that_is_not_a_date_is_not_a_due_date():
    text, fields = extract("review [due:: soon]")
    assert fields == {}
    assert "[due:: soon]" in text


def test_a_task_with_no_fields_is_untouched():
    assert extract("plain task") == ("plain task", {})


def test_created_and_cancelled_dates():
    _, fields = extract(f"x {CREATED} 2026-08-01 {START} 2026-09-10")
    assert fields == {"created": "2026-08-01", "start": "2026-09-10"}


# -- as stored in the index -------------------------------------------------------------

def test_due_dates_reach_the_database(tasks_vault):
    rows = tasks_vault.execute(
        "SELECT f.path, t.text, t.due FROM tasks t JOIN files f ON f.id = t.file_id "
        "WHERE t.due IS NOT NULL ORDER BY t.due"
    ).fetchall()
    assert [r["due"] for r in rows] == [
        "2026-08-20", "2026-09-01", "2026-09-02", "2026-09-03",
        "2026-09-04", "2026-09-05", "2026-09-06", "2026-12-31",
    ]


def test_the_rest_of_the_fields_land_in_extra_json(tasks_vault):
    row = tasks_vault.execute(
        "SELECT extra_json FROM tasks WHERE text = 'recurring'"
    ).fetchone()
    assert json.loads(row["extra_json"]) == {"recurrence": "every week"}


def test_tasks_without_fields_store_no_json(tasks_vault):
    row = tasks_vault.execute(
        "SELECT extra_json FROM tasks WHERE text = 'just a task'"
    ).fetchone()
    assert row["extra_json"] is None


def test_a_vault_without_the_plugin_still_indexes(tasks_vault):
    rows = tasks_vault.execute(
        "SELECT t.text, t.due, t.extra_json FROM tasks t JOIN files f ON f.id = t.file_id "
        "WHERE f.path = 'Plain.md'"
    ).fetchall()
    assert len(rows) == 2
    assert all(r["due"] is None and r["extra_json"] is None for r in rows)


def test_field_markers_are_stripped_from_the_task_text(tasks_vault):
    texts = [r["text"] for r in tasks_vault.execute("SELECT text FROM tasks")]
    assert "due only" in texts
    assert not any(DUE in t and "soon" not in t for t in texts)
