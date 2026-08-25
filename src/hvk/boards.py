"""Writing to a whiteboard: adding to one, and making one (phase 7, ADR-0022).

The reading half is :mod:`hvk.parse.canvas`. This is the other one, and it was postponed for
five phases with a good reason attached: *placing boxes is a set of decisions nobody has needed
yet*. Those decisions are made here, and the shape of them is what keeps this safe:

**Adding, never rearranging.** A node can be appended and an edge drawn. Nothing that is already
on the board is moved, resized, recoloured or removed. A canvas is the one thing in a vault
somebody arranged *by hand*, spatially, and there is no undo for a command that reflows it.

**Everything untouched survives byte for byte.** The file is JSON, so it is read as JSON and
written back with the existing node objects passed through exactly as they were parsed --
positions, colours, and any key a future Obsidian invents that this has never heard of. The
indentation is detected from the file rather than imposed, because a canvas that changes by one
box should not arrive at every device as a whole-file diff.

**Adding the same thing twice does nothing.** Node and edge ids are derived from what they point
at, not generated, so a command run again is a no-op and reports as one. That is the same
property `hvk views` has, and for the same reason: something that runs on a schedule must not
produce a diff when nothing changed.

**A node points at a file that exists.** Adding a note that is not in the vault would create a
broken link on a board silently, which is the state in which people delete things (ADR-0015).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from hvk import write

# What Obsidian gives a new box. A file node is a square because it shows a note's opening; a
# text node is wider than it is tall because it holds a sentence.
FILE_SIZE = (400, 400)
TEXT_SIZE = (400, 200)
GAP = 40
PER_ROW = 4

INDENT_RE = re.compile(r"^\{\r?\n([ \t]+)", re.MULTILINE)
DEFAULT_INDENT = "\t"


class BoardError(Exception):
    """A canvas cannot be changed as asked. Never raised for 'nothing to do'."""


@dataclass
class Outcome:
    """What one command did, or would do."""

    canvas: str
    created: bool = False
    nodes: list = field(default_factory=list)     # ids added
    edges: list = field(default_factory=list)     # ids added
    written: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.nodes or self.edges) or self.created

    def as_dict(self) -> dict:
        return {
            "canvas": self.canvas, "created": self.created, "nodes": self.nodes,
            "edges": self.edges, "changed": self.changed, "written": self.written,
        }


def node_id(kind: str, key: str) -> str:
    """A node's id, derived from what it points at rather than generated.

    This is what makes adding the same note twice a no-op instead of a duplicate box. Sixteen
    hex characters, which is the shape Obsidian's own ids have -- a canvas written here should
    not be recognisable as written here.
    """
    return hashlib.sha256(f"{kind}:{key}".encode("utf-8")).hexdigest()[:16]


def _indent(text: str) -> str:
    """The indentation the file already uses, or the default for a new one.

    Detected rather than chosen: re-indenting a canvas somebody's app wrote would turn a
    one-box change into a diff of every line, delivered to every device.
    """
    found = INDENT_RE.search(text)
    return found.group(1) if found else DEFAULT_INDENT


def _load(text: str, name: str) -> dict:
    if not text.strip():
        return {"nodes": [], "edges": []}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise BoardError(
            f"{name} is not valid JSON ({exc}). Refusing to rewrite a canvas this cannot read: "
            f"repairing it would be guessing, and a whiteboard is somebody's arrangement."
        ) from exc
    if not isinstance(data, dict):
        raise BoardError(f"{name}: the top level of a canvas is an object, not a list")
    data.setdefault("nodes", [])
    data.setdefault("edges", [])
    if not isinstance(data["nodes"], list) or not isinstance(data["edges"], list):
        raise BoardError(f"{name}: 'nodes' and 'edges' have to be lists")
    return data


def _dump(data: dict, indent: str) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent)


def _floor(nodes: list) -> int:
    """The lowest edge of everything already on the board.

    Measured once, before anything is added. Measuring it per node would mean each new box
    pushed the floor down and the grid came out as a staircase.
    """
    bottoms = []
    for node in nodes:
        try:
            bottoms.append(int(node.get("y", 0)) + int(node.get("height", 0)))
        except (TypeError, ValueError):
            continue
    # max(), not max(0, ...): a board somebody built entirely in negative space is still a board,
    # and starting from the origin would drop new boxes far away from everything on it.
    return max(bottoms) if bottoms else 0


def _position(floor: int, offset: int) -> tuple:
    """Where the *offset*-th new box goes: a grid, starting below everything already there.

    Below rather than beside, and never among: whatever is on the board was put there by a
    person, and new boxes arriving in the middle of it would be the rearrangement this refuses
    to do, achieved by accident.
    """
    row, column = divmod(offset, PER_ROW)
    return (
        column * (FILE_SIZE[0] + GAP),
        floor + GAP + row * (FILE_SIZE[1] + GAP),
    )


def _find(nodes: list, reference: str) -> str | None:
    """The id of the node *reference* names: its id, or the file it holds."""
    for node in nodes:
        if node.get("id") == reference:
            return node["id"]
    for node in nodes:
        if node.get("file") == reference:
            return node["id"]
    # A file named without its folder, the way a wikilink names one.
    for node in nodes:
        held = node.get("file")
        if isinstance(held, str) and held.rsplit("/", 1)[-1].removesuffix(".md") == reference:
            return node["id"]
    return None


def edit(
    vault: write.Vault,
    canvas: str,
    *,
    notes=(),
    texts=(),
    connect=(),
    create: bool = False,
    apply: bool = False,
) -> Outcome:
    """Add nodes and edges to a canvas. Returns what changed, or would.

    Without *apply* nothing is written and the outcome says what one more run would do, which is
    the same bargain `hvk views` strikes.
    """
    target = vault.resolve(canvas)
    if target.suffix != ".canvas":
        raise BoardError(f"{canvas} is not a .canvas file")

    original = vault.read(target)
    if not original.exists and not create:
        raise BoardError(
            f"no such canvas: {canvas}. Pass --create to make it, so that a typo in the name "
            f"cannot quietly start a new board instead of adding to the one you meant."
        )

    outcome = Outcome(canvas=target.relative_to(vault.root).as_posix(),
                      created=not original.exists)
    data = _load(original.text, outcome.canvas)
    known = {node.get("id") for node in data["nodes"]}
    floor = _floor(data["nodes"])
    placed = 0

    for note in notes:
        # Resolved and checked to exist, because a canvas is where a broken link is least
        # visible: a box that shows nothing looks like a box that has not loaded yet.
        note_path = vault.resolve(note)
        if not note_path.is_file():
            raise BoardError(f"no such note in the vault: {note}")
        relative = note_path.relative_to(vault.root).as_posix()
        identifier = node_id("file", relative)
        if identifier in known:
            continue
        x, y = _position(floor, placed)
        data["nodes"].append({
            "id": identifier, "type": "file", "file": relative,
            "x": x, "y": y, "width": FILE_SIZE[0], "height": FILE_SIZE[1],
        })
        known.add(identifier)
        outcome.nodes.append(identifier)
        placed += 1

    for body in texts:
        identifier = node_id("text", body)
        if identifier in known:
            continue
        x, y = _position(floor, placed)
        data["nodes"].append({
            "id": identifier, "type": "text", "text": body,
            "x": x, "y": y, "width": TEXT_SIZE[0], "height": TEXT_SIZE[1],
        })
        known.add(identifier)
        outcome.nodes.append(identifier)
        placed += 1

    existing_edges = {edge.get("id") for edge in data["edges"]}
    for source, destination in connect:
        ends = []
        for reference in (source, destination):
            found = _find(data["nodes"], reference)
            if found is None:
                raise BoardError(
                    f"nothing on this canvas is called {reference!r}. An edge joins two boxes "
                    f"that are already on the board -- add the note in the same command, or "
                    f"name a box by its id (see `hvk canvas {outcome.canvas}`)."
                )
            ends.append(found)
        if ends[0] == ends[1]:
            raise BoardError(f"an edge from {source!r} to itself is not a connection")
        identifier = node_id("edge", f"{ends[0]}->{ends[1]}")
        if identifier in existing_edges:
            continue
        data["edges"].append({
            "id": identifier, "fromNode": ends[0], "fromSide": "bottom",
            "toNode": ends[1], "toSide": "top",
        })
        existing_edges.add(identifier)
        outcome.edges.append(identifier)

    if apply and outcome.changed:
        outcome.written = vault.write(original, _dump(data, _indent(original.text)))
    return outcome
