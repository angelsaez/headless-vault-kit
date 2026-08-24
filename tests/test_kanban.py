"""The example parser adapter (ADR-0017): Obsidian Kanban boards.

Two halves, and the second matters more than the first. The board has to be read correctly --
and every file that merely resembles a board has to be left completely alone, because a parser
that claims too much puts fiction in the index and nothing downstream can tell.
"""

from __future__ import annotations

import json

import pytest

from hvk.parse import kanban

BOARD = """---
kanban-plugin: board
---

## Backlog

- [ ] A card @{2026-09-01}
"""


# -- what it claims ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    BOARD,
    "---\nkanban-plugin: board\ntags: [x]\n---\n\n## A\n",
    "---\ntags: [x]\nkanban-plugin:   board\n---\n",
    "---\nkanban-plugin: list\n---\n",           # a board in another of the plugin's modes
    "---\nkanban-plugin: board\n...\n",          # YAML's other closing fence
])
def test_a_board_is_recognised_by_its_frontmatter(text):
    assert kanban.is_board(text)


@pytest.mark.parametrize("text", [
    "# Just a note\n\n## Backlog\n\n- [ ] A card\n",
    "",
    "---\ntags: [project]\n---\n\n## Backlog\n",
    # The marker written in the body. Claiming this indexes an example as a real card.
    "# About Kanban\n\nThe plugin writes:\n\n```yaml\nkanban-plugin: board\n```\n",
    # And in the body of a note that does have frontmatter, past the closing fence.
    "---\ntags: [x]\n---\n\nkanban-plugin: board\n",
    "not frontmatter at all\n---\nkanban-plugin: board\n---\n",
])
def test_a_note_that_is_not_a_board_is_not_claimed(text):
    assert not kanban.is_board(text)


def test_the_claim_reads_the_frontmatter_and_stops():
    """It runs once per Markdown file on every scan, so it must not depend on file size. A
    marker buried past the limit is a file this does not claim -- the safe direction."""
    buried = "---\n" + ("filler: x\n" * 5000) + "kanban-plugin: board\n---\n"
    assert not kanban.is_board(buried)


def test_the_registered_parser_is_the_one_that_wins_for_a_board():
    from hvk.parse import registry

    assert registry.REGISTRY.select("md", BOARD, "B.md").name == "kanban"
    assert registry.REGISTRY.select("md", "# a note\n", "B.md").name == "markdown"


# -- what it contributes ----------------------------------------------------------------------

def test_every_card_carries_the_list_it_sits_in():
    parsed = kanban.parse_file(
        "---\nkanban-plugin: board\n---\n\n## Backlog\n\n- [ ] One\n\n## Done\n\n- [x] Two\n",
        "B.md",
    )
    assert [(t.text, t.extra.get("list")) for t in parsed.tasks] == [
        ("One", "Backlog"), ("Two", "Done"),
    ]


def test_a_card_above_every_heading_has_no_list_rather_than_a_wrong_one():
    parsed = kanban.parse_file(
        "---\nkanban-plugin: board\n---\n\n- [ ] Loose\n\n## Backlog\n\n- [ ] Filed\n", "B.md"
    )
    assert "list" not in parsed.tasks[0].extra
    assert parsed.tasks[1].extra["list"] == "Backlog"


def test_a_kanban_date_becomes_the_due_date_and_leaves_the_text():
    """The part worth having: `hvk tasks --due-before` reads the due column, so until this
    existed it was blind to every card on every board."""
    parsed = kanban.parse_file(BOARD, "B.md")
    assert parsed.tasks[0].due == "2026-09-01"
    assert parsed.tasks[0].text == "A card"


def test_a_time_is_kept_beside_the_date():
    parsed = kanban.parse_file(
        "---\nkanban-plugin: board\n---\n\n## A\n\n- [ ] Stand-up @{2026-08-28} @@{10:00}\n",
        "B.md",
    )
    assert parsed.tasks[0].due == "2026-08-28"
    assert parsed.tasks[0].extra["time"] == "10:00"
    assert parsed.tasks[0].text == "Stand-up"


def test_an_explicit_tasks_plugin_date_wins_over_the_kanban_one():
    """Both are dates on one card and they disagree. The Tasks plugin's emoji is the more
    deliberate of the two, and either way the Kanban syntax leaves the text -- what a card says
    and what is known about it are different things."""
    parsed = kanban.parse_file(
        "---\nkanban-plugin: board\n---\n\n## A\n\n- [ ] Both \U0001F4C5 2026-08-26 @{2026-12-31}\n",
        "B.md",
    )
    assert parsed.tasks[0].due == "2026-08-26"
    assert "2026-12-31" not in parsed.tasks[0].text


def test_a_board_is_still_an_ordinary_note_in_every_other_way():
    """The adapter parses Markdown first and adds to the result. Losing the tags, links or
    frontmatter of a board would be a silent regression on a file that used to index fine."""
    parsed = kanban.parse_file(
        "---\nkanban-plugin: board\ntags:\n  - project\n---\n\n"
        "## Backlog\n\n- [ ] Read [[Design]] #docs\n",
        "Boards/B.md",
    )
    assert parsed.frontmatter["kanban-plugin"] == "board"
    assert {t.tag for t in parsed.tags} == {"project", "docs"}
    assert [ln.target_raw for ln in parsed.links] == ["Design"]
    assert [h.text for h in parsed.headings] == ["Backlog"]
    assert parsed.title == "B"


def test_the_settings_block_contributes_nothing():
    """It is written in Obsidian's comment syntax, so the Markdown parser already drops it. If
    that ever changed, its JSON would arrive in the search index as prose."""
    parsed = kanban.parse_file(
        BOARD + '\n%% kanban:settings\n```\n{"kanban-plugin":"board"}\n```\n%%\n', "B.md"
    )
    assert "show-checkboxes" not in parsed.body
    assert len(parsed.tasks) == 1


# -- through a real scan ----------------------------------------------------------------------

def test_a_board_indexes_as_a_note_with_its_cards_filed(index):
    _, conn, stats = index("kanban")
    assert stats.errors == 0

    rows = conn.execute(
        "SELECT t.text, t.due, t.extra_json FROM tasks t JOIN files f ON f.id = t.file_id "
        "WHERE f.path = 'Boards/Roadmap.md' ORDER BY t.line"
    ).fetchall()
    lists = [json.loads(r["extra_json"])["list"] for r in rows]
    assert lists == ["Backlog", "Backlog", "Backlog", "In progress", "In progress", "Done"]
    assert rows[1]["due"] == "2026-09-01"
    assert rows[1]["text"] == "Rewrite the intro #docs"

    kind = conn.execute("SELECT kind FROM files WHERE path = 'Boards/Roadmap.md'").fetchone()
    assert kind["kind"] == "note", "a board is a note; queries that ask for notes must find it"


def test_a_note_that_only_looks_like_a_board_keeps_its_text(index):
    _, conn, _ = index("kanban")
    rows = conn.execute(
        "SELECT f.path, t.text, t.extra_json FROM tasks t JOIN files f ON f.id = t.file_id "
        "WHERE f.path LIKE 'Notes/%' ORDER BY f.path, t.line"
    ).fetchall()
    assert all(row["extra_json"] is None for row in rows)
    assert any("@{2026-09-01}" in row["text"] for row in rows), \
        "an unclaimed note keeps Kanban syntax as the literal text it is"


def test_a_card_on_a_board_answers_a_date_query(index):
    """End to end, and the reason the adapter earns its place: a command written in phase 2
    answers a file format read in phase 7, with no new column and no new flag."""
    from hvk import query

    _, conn, _ = index("kanban")
    found = query.tasks(conn, pending=True, due_before="2026-08-30")
    # Soonest first, which is what the ordering in query.tasks promises.
    assert [row["text"] for row in found] == [
        "A card with a Tasks-plugin date too", "Draft the guide",
    ]

# Determinism over this vault is checked where every other vault's is, in test_scan.py: the
# fingerprint there covers extra_json, which is the column a board writes and the one a dict
# serialised in a different order each run would break.
