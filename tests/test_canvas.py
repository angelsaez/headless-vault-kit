"""Canvas: what a whiteboard contributes to the index (tier 1, ADR-0015).

The case that matters is the one prose cannot produce: a note that nothing mentions in text,
placed on a board. Before this it looked orphaned, which is the state in which people delete
things.

The other half of the file is the deliberate gaps — edges are not links between notes, and a
canvas has no line numbers — because a gap nobody wrote down is indistinguishable from a bug.
"""

from __future__ import annotations

import json

import pytest

from hvk.parse.canvas import parse_canvas


def links_from(conn, path: str):
    return conn.execute(
        "SELECT l.target_raw, l.kind, l.embed, l.subpath, t.path AS resolved "
        "FROM links l JOIN files f ON f.id = l.file_id "
        "LEFT JOIN files t ON t.id = l.target_file_id "
        "WHERE f.path = ? ORDER BY l.rowid",
        (path,),
    ).fetchall()


# -- what a canvas puts in the index ----------------------------------------------------------

def test_a_note_only_on_a_board_still_has_backlinks(index):
    """The whole reason this exists. Nothing in prose mentions Beta."""
    _, conn, _ = index("canvas")
    rows = conn.execute(
        "SELECT f.path FROM links l JOIN files f ON f.id = l.file_id "
        "JOIN files t ON t.id = l.target_file_id WHERE t.path = 'Notes/Beta.md'"
    ).fetchall()
    assert [r["path"] for r in rows] == ["Board.canvas"]


def test_a_file_node_resolves_to_the_file_it_places(index):
    _, conn, _ = index("canvas")
    by_target = {r["target_raw"]: r for r in links_from(conn, "Board.canvas")}
    alpha = by_target["Notes/Alpha.md"]
    assert alpha["resolved"] == "Notes/Alpha.md"
    assert alpha["kind"] == "canvas"
    assert alpha["embed"] == 1, "a canvas places a note rather than mentioning it"


def test_a_subpath_survives(index):
    _, conn, _ = index("canvas")
    beta = {r["target_raw"]: r for r in links_from(conn, "Board.canvas")}["Notes/Beta.md"]
    assert beta["subpath"] == "#Somewhere"


def test_markdown_written_on_the_board_is_read_as_markdown(index):
    """A wikilink in a text node resolves by exactly the rules of ADR-0003."""
    _, conn, _ = index("canvas")
    wikilinks = [r for r in links_from(conn, "Board.canvas") if r["kind"] == "wikilink"]
    assert [r["resolved"] for r in wikilinks] == ["Notes/Alpha.md"]


def test_a_tag_on_the_board_is_a_tag(index):
    _, conn, _ = index("canvas")
    rows = conn.execute(
        "SELECT t.tag, t.source FROM tags t JOIN files f ON f.id = t.file_id "
        "WHERE f.path = 'Board.canvas'"
    ).fetchall()
    assert [(r["tag"], r["source"]) for r in rows] == [("roadmap", "canvas")]


def test_a_link_node_stays_external(index):
    _, conn, _ = index("canvas")
    external = [r for r in links_from(conn, "Board.canvas") if r["kind"] == "external"]
    assert any("obsidian.md" in r["target_raw"] for r in external)
    assert all(r["resolved"] is None for r in external), "external links resolve to nothing"


def test_the_text_of_a_board_is_searchable(index):
    """Including a group's label, which is the only thing a group is."""
    location, conn, _ = index("canvas")
    from hvk import query

    hits = [row["path"] for row in query.search(conn, "quarter", limit=10)]
    assert "Board.canvas" in hits


def test_a_canvas_is_counted_as_a_canvas_not_an_attachment(index):
    _, conn, _ = index("canvas")
    from hvk import query

    counts = query.info(conn)
    assert counts["canvases"] == 2
    assert counts["attachments"] == 0


# -- the deliberate gaps ------------------------------------------------------------------------

def test_edges_are_not_links_between_notes(index):
    """An arrow joins two boxes. Calling that a link would invent a relationship Obsidian
    does not derive either — and `hvk canvas --edges` shows them without inventing anything."""
    _, conn, _ = index("canvas")
    assert not [r for r in links_from(conn, "Board.canvas") if r["target_raw"] == "depends on"]
    # Two file nodes, a wikilink and a markdown link inside a text node, and the link node.
    assert len(links_from(conn, "Board.canvas")) == 5


def test_links_from_a_canvas_have_no_line(index):
    _, conn, _ = index("canvas")
    lines = conn.execute(
        "SELECT DISTINCT l.line FROM links l JOIN files f ON f.id = l.file_id "
        "WHERE f.path = 'Board.canvas'"
    ).fetchall()
    assert [r["line"] for r in lines] == [0], "a whiteboard has no line numbers"


# -- surviving what a real vault contains ------------------------------------------------------

def test_a_broken_canvas_is_a_parse_error_and_stops_nothing(index):
    _, conn, stats = index("canvas")
    row = conn.execute(
        "SELECT parse_error FROM files WHERE path = 'Broken.canvas'"
    ).fetchone()
    assert row["parse_error"] and "JSON" in row["parse_error"]
    assert conn.execute("SELECT count(*) FROM files").fetchone()[0] == 5, "the rest indexed"


def test_an_unknown_node_type_is_skipped_rather_than_guessed_at(index):
    """A canvas written by a future Obsidian must not make a vault fail to index."""
    _, conn, _ = index("canvas")
    assert conn.execute(
        "SELECT parse_error FROM files WHERE path = 'Board.canvas'"
    ).fetchone()["parse_error"] is None


# -- the parser on its own ----------------------------------------------------------------------

@pytest.mark.parametrize("text", ["", "not json", "[]", "null", '{"nodes": "not a list"}'])
def test_nothing_shaped_like_a_canvas_yields_nothing_rather_than_raising(text):
    canvas = parse_canvas(text)
    assert canvas.links == []
    assert canvas.nodes == []


def test_a_node_that_is_not_an_object_is_skipped():
    canvas = parse_canvas(json.dumps({"nodes": ["nonsense", {"id": "a", "type": "link",
                                                            "url": "https://example.org"}]}))
    assert [n.id for n in canvas.nodes] == ["a"]


def test_a_file_node_with_no_file_is_not_a_link():
    canvas = parse_canvas(json.dumps({"nodes": [{"id": "a", "type": "file"}]}))
    assert canvas.links == []
