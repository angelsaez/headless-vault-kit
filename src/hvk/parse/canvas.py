"""JSON Canvas: what a `.canvas` file contributes to the index (tier 1, phase 3).

A canvas is JSON, not Markdown, and Obsidian publishes the format as a specification of its
own. Four node types matter here:

* ``file`` — a note or attachment placed on the canvas, by **vault-relative path**, optionally
  with a ``subpath`` anchor. This is the one that matters most: a canvas that places a note on
  it is pointing at that note, and a backlinks answer that ignored canvases would be wrong in
  a way nobody would notice until they deleted something.
* ``text`` — Markdown written directly on the canvas. Parsed as Markdown, so the wikilinks and
  tags inside it count like any others, and its text is searchable.
* ``link`` — an external URL.
* ``group`` — a labelled box. Only its label is worth anything to a query.

**Edges are deliberately not indexed as links between notes.** An edge joins two *nodes*, and
turning "these two boxes have an arrow between them" into a link in the index would invent a
relationship Obsidian does not derive either. `hvk canvas` shows them, read from the file, for
the times when the shape of the canvas is the question.

A canvas has no lines, so every link from one is stored at line 0. The position of a box on a
whiteboard is not the kind of place a line number describes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from hvk.parse.markdown import RawLink, Tag, parse_note

# The four node types the specification defines. Anything else is skipped rather than guessed
# at: a canvas written by a future Obsidian should not make a vault fail to index.
TEXT, FILE, LINK, GROUP = "text", "file", "link", "group"


@dataclass
class CanvasNode:
    """One box, as far as anything outside the canvas is concerned."""

    id: str
    type: str
    text: str = ""          # text nodes: the Markdown; group nodes: the label
    file: str = ""          # file nodes: the vault-relative path
    subpath: str | None = None
    url: str = ""


@dataclass
class CanvasEdge:
    id: str
    from_node: str
    to_node: str
    label: str = ""


@dataclass
class Canvas:
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    links: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    body: str = ""
    error: str | None = None


def _text_of(node: dict) -> str:
    for key in ("text", "label"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def parse_canvas(text: str) -> Canvas:
    """Everything a `.canvas` file contributes. Never raises: a bad canvas is a parse error."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        return Canvas(error=f"invalid JSON Canvas: {exc}")
    if not isinstance(data, dict):
        return Canvas(error="invalid JSON Canvas: the top level is not an object")

    canvas = Canvas()
    raw_nodes = data.get("nodes")
    raw_edges = data.get("edges")
    searchable: list = []

    for raw in raw_nodes if isinstance(raw_nodes, list) else []:
        if not isinstance(raw, dict):
            continue
        node = CanvasNode(
            id=str(raw.get("id", "")),
            type=str(raw.get("type", "")),
            text=_text_of(raw),
            file=raw.get("file") if isinstance(raw.get("file"), str) else "",
            subpath=raw.get("subpath") if isinstance(raw.get("subpath"), str) else None,
            url=raw.get("url") if isinstance(raw.get("url"), str) else "",
        )
        canvas.nodes.append(node)

        if node.type == FILE and node.file:
            # Embed, because that is what a canvas does with a note: it puts it on the board
            # rather than mentioning it. The subpath keeps a heading anchor if there was one.
            canvas.links.append(RawLink(
                target_raw=node.file, subpath=node.subpath,
                kind="canvas", embed=True, line=0,
            ))
        elif node.type == LINK and node.url:
            canvas.links.append(RawLink(
                target_raw=node.url, subpath=None, kind="external", embed=False, line=0,
            ))
        elif node.type == TEXT and node.text:
            # Markdown on a whiteboard is still Markdown. Reusing the note parser is what keeps
            # a wikilink written in a canvas resolving by exactly the rules of ADR-0003.
            inner = parse_note(node.text, fallback_title="")
            for link in inner.links:
                canvas.links.append(RawLink(
                    target_raw=link.target_raw, subpath=link.subpath,
                    kind=link.kind, embed=link.embed, line=0,
                ))
            canvas.tags.extend(Tag(tag=t.tag, source="canvas", line=0) for t in inner.tags)
            searchable.append(node.text)
        elif node.type == GROUP and node.text:
            searchable.append(node.text)

    for raw in raw_edges if isinstance(raw_edges, list) else []:
        if not isinstance(raw, dict):
            continue
        edge = CanvasEdge(
            id=str(raw.get("id", "")),
            from_node=str(raw.get("fromNode", "")),
            to_node=str(raw.get("toNode", "")),
            label=raw.get("label") if isinstance(raw.get("label"), str) else "",
        )
        canvas.edges.append(edge)
        if edge.label:
            searchable.append(edge.label)

    canvas.body = "\n".join(searchable)
    return canvas
