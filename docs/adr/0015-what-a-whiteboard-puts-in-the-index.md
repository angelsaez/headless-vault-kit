# 0015 — What a whiteboard puts in the index

**Status:** accepted
**Date:** 2026-08-24
**Phase:** 3

## Context

Canvas was postponed with a condition written down rather than a feeling: *it gets built when a
vault actually contains one.* The inventory of phase 1 found zero `.canvas` files, JSON Canvas
is a published and stable specification, and building for nobody was the v1 mistake this plan
exists to avoid.

A vault now contains one, so the condition is met.

What was actually missing is worth stating precisely, because it is not "canvas support" in the
abstract. **A canvas points at notes without mentioning them in prose.** Put a note on a board
and nothing in any file's text refers to it: `hvk backlinks` answered *nothing*, `hvk orphans`
listed it, and both were wrong. An orphan that is not an orphan is the state in which people
delete things.

## Alternatives

- **Leave canvases as attachments.** What happened until now. It is not neutral: the index
  gives a confident wrong answer rather than an incomplete one, which is worse.
- **Index the whole board — nodes, geometry, edges — as a graph.** Attractive, and it invents a
  relationship the app does not derive: Obsidian's own metadata cache does not turn "these two
  boxes have an arrow between them" into a link between two notes. It also needs tables and a
  schema migration for a question nobody has asked yet.
- **Index what a canvas says about *notes*, and read the shape of the board from the file when
  the shape is the question.** Chosen.

## Decision

A `.canvas` contributes three things to the index, and nothing else:

- **Links.** A `file` node becomes a link to that path, marked as an **embed**, because a canvas
  places a note rather than mentioning it, and keeping its `subpath` if it had one. A `link`
  node becomes an external link. Markdown inside a `text` node is parsed as Markdown, so
  wikilinks written on a board resolve by exactly the rules of ADR-0003.
- **Tags**, from the Markdown in text nodes, with `source: canvas` so a query can tell where
  one came from.
- **Text**, for search: text nodes, group labels and edge labels, so a phrase written on a
  whiteboard is findable.

**Edges are not links between notes.** `hvk canvas --edges` prints them, resolving node ids to
the files they hold, read from the file at the moment you ask. That answers "what does this
board say connects to what" without teaching the index a relationship Obsidian does not have.

**A canvas has no lines.** Every link from one is stored at line 0. The position of a box on a
whiteboard is not something a line number describes, and inventing one would be a number people
would try to use.

**Unknown node types are skipped, not guessed at.** A canvas written by a future Obsidian must
not make a vault fail to index. Invalid JSON is a parse error on that file, exactly like invalid
frontmatter on a note: it is reported, and the rest of the vault indexes.

## Consequences

**Two counts change meaning, visibly.** `hvk info` now reports `canvases` and `bases` on their
own rather than folding them into `attachments`, because a file this project parses is not an
attachment. And `hvk doctor`'s check is now *"files parse cleanly"*: it used to say "invalid
frontmatter" about every parse error, which is a confusing thing to say about a canvas.

**Tags on a board are indexed, and that may be more than Obsidian does.** Whether the app's own
tag pane counts a `#tag` written inside a canvas text node was not verified, and guessing at
parity is how a project ends up with a difference nobody can explain. Tier 1 is a promise about
*the format*, not about the cache, so the format is read faithfully and the uncertainty is
written down here instead of being painted over.

**Writing canvases is not supported.** The plan lists tier 1 Canvas as "read and write", and
this is read. Writing means placing boxes — coordinates, sizes, what to do when they overlap —
and that is a set of decisions nobody has needed yet. The read side answers the question that
was actually wrong; the write side gets its own ADR when something concrete asks for it.

**A canvas that places a note keeps it out of `orphans` forever.** That is the point, and it is
also a way to hide a note from that list by accident. `hvk canvas` on the board says who is
holding it.
