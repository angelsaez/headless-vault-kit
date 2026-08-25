"""Writing to a whiteboard (ADR-0022).

The behaviour worth most of these tests is not what gets added. It is what survives: a canvas is
the one thing in a vault somebody arranged *by hand*, spatially, and a command that quietly moved
a box has destroyed work nobody can get back from a diff.
"""

from __future__ import annotations

import json

import pytest

from hvk import boards, write

BY_HAND = {
    "nodes": [{
        "id": "mine", "type": "text", "text": "placed by hand",
        "x": -900, "y": -300, "width": 250, "height": 60,
        # A colour, and a key no version of this project has heard of.
        "color": "4", "customFutureKey": {"a": 1},
    }],
    "edges": [],
}


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    (root / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    for name in ("Alpha", "Beta", "Gamma"):
        (root / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")
    (root / "Notes").mkdir()
    (root / "Notes" / "Deep.md").write_text("# Deep\n", encoding="utf-8")
    return write.Vault(root)


def board(vault, name="Board.canvas") -> dict:
    return json.loads((vault.root / name).read_text(encoding="utf-8"))


# -- creating ---------------------------------------------------------------------------------

def test_a_canvas_can_be_made_from_notes(vault):
    outcome = boards.edit(vault, "Board.canvas", notes=["Alpha.md", "Beta.md"],
                          create=True, apply=True)
    assert outcome.created and outcome.written and len(outcome.nodes) == 2
    nodes = board(vault)["nodes"]
    assert [n["file"] for n in nodes] == ["Alpha.md", "Beta.md"]
    assert all(n["type"] == "file" for n in nodes)


def test_a_name_that_does_not_exist_is_an_error_without_create(vault):
    """So that a typo adds nothing to a new board instead of nothing to the one you meant."""
    with pytest.raises(boards.BoardError, match="--create"):
        boards.edit(vault, "Nope.canvas", notes=["Alpha.md"], apply=True)
    assert not (vault.root / "Nope.canvas").exists()


def test_only_a_canvas_can_be_edited(vault):
    with pytest.raises(boards.BoardError, match="not a .canvas"):
        boards.edit(vault, "Alpha.md", texts=["x"], create=True, apply=True)


def test_a_note_that_is_not_in_the_vault_is_refused(vault):
    """A box pointing at nothing looks like a box that has not loaded yet, which is why this is
    an error and not a broken link nobody notices."""
    with pytest.raises(boards.BoardError, match="no such note"):
        boards.edit(vault, "Board.canvas", notes=["Ghost.md"], create=True, apply=True)


def test_a_note_outside_the_vault_is_refused(vault):
    with pytest.raises(write.WriteError, match="outside the vault"):
        boards.edit(vault, "Board.canvas", notes=["../escaped.md"], create=True, apply=True)


def test_a_canvas_outside_the_vault_is_refused(vault):
    with pytest.raises(write.WriteError, match="outside the vault"):
        boards.edit(vault, "../escaped.canvas", texts=["x"], create=True, apply=True)


# -- what survives ----------------------------------------------------------------------------

def test_a_hand_placed_node_is_returned_byte_for_byte(vault):
    """Including a key this project has never heard of. A canvas written by a newer Obsidian
    must come back out of here intact, not reduced to the fields this version knows."""
    (vault.root / "Board.canvas").write_text(json.dumps(BY_HAND, indent=2), encoding="utf-8")
    boards.edit(vault, "Board.canvas", notes=["Alpha.md"], apply=True)
    assert board(vault)["nodes"][0] == BY_HAND["nodes"][0]


def test_nothing_already_there_is_moved(vault):
    (vault.root / "Board.canvas").write_text(json.dumps(BY_HAND, indent=2), encoding="utf-8")
    boards.edit(vault, "Board.canvas", notes=["Alpha.md", "Beta.md"], apply=True)
    kept = board(vault)["nodes"][0]
    assert (kept["x"], kept["y"]) == (-900, -300)


def test_new_boxes_go_below_everything_on_the_board(vault):
    (vault.root / "Board.canvas").write_text(
        json.dumps({"nodes": [{"id": "a", "type": "text", "text": "t",
                               "x": 0, "y": 1000, "width": 400, "height": 400}],
                    "edges": []}, indent=2),
        encoding="utf-8",
    )
    boards.edit(vault, "Board.canvas", notes=["Alpha.md"], apply=True)
    added = board(vault)["nodes"][1]
    assert added["y"] >= 1400


def test_a_board_entirely_in_negative_space_is_still_a_board(vault):
    """Starting the floor at the origin would drop new boxes far away from everything on it."""
    (vault.root / "Board.canvas").write_text(json.dumps(BY_HAND, indent=2), encoding="utf-8")
    boards.edit(vault, "Board.canvas", notes=["Alpha.md"], apply=True)
    assert board(vault)["nodes"][1]["y"] < 0


def test_the_indentation_of_the_file_is_kept(vault):
    """Re-indenting somebody's canvas turns a one-box change into a diff of every line,
    delivered to every device."""
    (vault.root / "Board.canvas").write_text(json.dumps(BY_HAND, indent=2), encoding="utf-8")
    boards.edit(vault, "Board.canvas", notes=["Alpha.md"], apply=True)
    assert (vault.root / "Board.canvas").read_text(encoding="utf-8").startswith('{\n  "nodes"')


def test_a_tab_indented_canvas_stays_tab_indented(vault):
    (vault.root / "Board.canvas").write_text(json.dumps(BY_HAND, indent="\t"), encoding="utf-8")
    boards.edit(vault, "Board.canvas", notes=["Alpha.md"], apply=True)
    assert (vault.root / "Board.canvas").read_text(encoding="utf-8").startswith('{\n\t"nodes"')


def test_a_canvas_that_cannot_be_parsed_is_refused_rather_than_repaired(vault):
    (vault.root / "Board.canvas").write_text("{not json", encoding="utf-8")
    with pytest.raises(boards.BoardError, match="not valid JSON"):
        boards.edit(vault, "Board.canvas", notes=["Alpha.md"], apply=True)
    assert (vault.root / "Board.canvas").read_text(encoding="utf-8") == "{not json"


# -- doing it twice ---------------------------------------------------------------------------

def test_adding_the_same_note_twice_does_nothing(vault):
    """Ids come from what a node points at, not from a counter. Something that runs on a
    schedule must not produce a diff when nothing changed."""
    boards.edit(vault, "Board.canvas", notes=["Alpha.md"], create=True, apply=True)
    before = (vault.root / "Board.canvas").read_text(encoding="utf-8")
    outcome = boards.edit(vault, "Board.canvas", notes=["Alpha.md"], apply=True)
    assert not outcome.changed and not outcome.written
    assert (vault.root / "Board.canvas").read_text(encoding="utf-8") == before


def test_an_unchanged_canvas_is_not_even_opened_for_writing(vault):
    boards.edit(vault, "Board.canvas", notes=["Alpha.md"], create=True, apply=True)
    before = (vault.root / "Board.canvas").stat().st_mtime_ns
    boards.edit(vault, "Board.canvas", notes=["Alpha.md"], apply=True)
    assert (vault.root / "Board.canvas").stat().st_mtime_ns == before


def test_the_same_edge_twice_does_nothing(vault):
    boards.edit(vault, "Board.canvas", notes=["Alpha.md", "Beta.md"],
                connect=[("Alpha.md", "Beta.md")], create=True, apply=True)
    outcome = boards.edit(vault, "Board.canvas", connect=[("Alpha.md", "Beta.md")], apply=True)
    assert not outcome.changed
    assert len(board(vault)["edges"]) == 1


def test_without_apply_nothing_is_written_and_the_change_is_reported(vault):
    outcome = boards.edit(vault, "Board.canvas", notes=["Alpha.md"], create=True)
    assert outcome.changed and not outcome.written
    assert not (vault.root / "Board.canvas").exists()


# -- edges ------------------------------------------------------------------------------------

def test_boxes_can_be_connected_by_note_path_or_by_name(vault):
    boards.edit(vault, "Board.canvas", notes=["Alpha.md", "Notes/Deep.md"],
                connect=[("Alpha.md", "Deep")], create=True, apply=True)
    edges = board(vault)["edges"]
    assert len(edges) == 1
    nodes = {n["id"]: n["file"] for n in board(vault)["nodes"]}
    assert nodes[edges[0]["fromNode"]] == "Alpha.md"
    assert nodes[edges[0]["toNode"]] == "Notes/Deep.md"


def test_an_edge_can_name_a_node_by_its_id(vault):
    first = boards.edit(vault, "Board.canvas", notes=["Alpha.md", "Beta.md"],
                        create=True, apply=True)
    outcome = boards.edit(vault, "Board.canvas",
                          connect=[(first.nodes[0], first.nodes[1])], apply=True)
    assert len(outcome.edges) == 1


def test_an_edge_to_a_box_that_is_not_there_names_it(vault):
    with pytest.raises(boards.BoardError, match="Ghost"):
        boards.edit(vault, "Board.canvas", notes=["Alpha.md"],
                    connect=[("Alpha.md", "Ghost")], create=True, apply=True)


def test_an_edge_from_a_box_to_itself_is_refused(vault):
    with pytest.raises(boards.BoardError, match="to itself"):
        boards.edit(vault, "Board.canvas", notes=["Alpha.md"],
                    connect=[("Alpha.md", "Alpha.md")], create=True, apply=True)


def test_a_note_added_in_the_same_call_can_be_connected(vault):
    outcome = boards.edit(vault, "Board.canvas", notes=["Alpha.md", "Beta.md"],
                          connect=[("Alpha.md", "Beta.md")], create=True, apply=True)
    assert len(outcome.nodes) == 2 and len(outcome.edges) == 1


# -- text boxes -------------------------------------------------------------------------------

def test_a_text_box_holds_markdown(vault):
    boards.edit(vault, "Board.canvas", texts=["A **note** with [[Alpha]]"],
                create=True, apply=True)
    node = board(vault)["nodes"][0]
    assert node["type"] == "text" and node["text"] == "A **note** with [[Alpha]]"


def test_what_is_written_reads_back_through_the_parser(vault):
    """The two halves have to agree: a canvas written here is one `hvk canvas` can list and one
    the indexer derives links from."""
    from hvk.parse.canvas import parse_canvas

    boards.edit(vault, "Board.canvas", notes=["Alpha.md"], texts=["see [[Beta]] #board"],
                create=True, apply=True)
    parsed = parse_canvas((vault.root / "Board.canvas").read_text(encoding="utf-8"))
    assert parsed.error is None
    assert sorted(link.target_raw for link in parsed.links) == ["Alpha.md", "Beta"]
    assert [tag.tag for tag in parsed.tags] == ["board"]


def test_a_written_canvas_reaches_the_index(index, tmp_path):
    """End to end: a board made here contributes backlinks like any other."""
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    (root / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (root / "Alpha.md").write_text("# Alpha\n", encoding="utf-8")
    boards.edit(write.Vault(root), "Board.canvas", notes=["Alpha.md"], create=True, apply=True)

    _, conn, stats = index(root)
    assert stats.errors == 0
    rows = conn.execute(
        "SELECT f.path AS source FROM links l JOIN files f ON f.id = l.file_id "
        "JOIN files t ON t.id = l.target_file_id WHERE t.path = 'Alpha.md'"
    ).fetchall()
    assert [row["source"] for row in rows] == ["Board.canvas"]
