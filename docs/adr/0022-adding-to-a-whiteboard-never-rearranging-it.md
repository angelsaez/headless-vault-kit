# 0022 — Adding to a whiteboard, never rearranging it

**Status:** accepted
**Date:** 2026-08-25
**Phase:** 7

## Context

Canvas writing has been on the postponed list since phase 3, with a reason attached that was
never a placeholder: *reading is done; placing boxes is a set of decisions nobody has needed
yet*. Somebody has now needed it, so the decisions get made.

What makes a canvas different from everything else this project writes is that **it is the one
thing in a vault a person arranged spatially, by hand**. A note's meaning does not depend on
where its paragraphs sit on a screen. A whiteboard's does: the left-hand column, the thing you
put slightly apart from the others, the two boxes you moved next to each other because they
turned out to be the same idea. None of that is recoverable from a diff, and none of it is
written down anywhere but the coordinates.

Everything else this project writes has a safety net for the same worry. A note's frontmatter
survives because [ADR-0007](0007-writing-to-the-vault.md) never reparses it. A materialised view
replaces only what is between two markers. The equivalent question here is: what is a canvas
edit allowed to touch?

## Alternatives

- **Only create new canvases**, never open an existing one. Zero risk to anything hand-made, and
  it answers "build me a board from these notes" while failing the far more common "put this on
  my board". Rejected as too small to be the feature that was asked for.
- **Full editing** — move, resize, recolour, delete. This is reimplementing the app's editor
  without its interface, and its failure mode is a command that silently reflows work somebody
  spent an afternoon on. It is also the version with no natural stopping point: alignment,
  grouping, z-order.
- **Adding, and nothing else.** Chosen.

## Decision

**A canvas can be added to. It can never be rearranged.** `hvk canvas FILE --add-note`,
`--add-text` and `--connect` append nodes and edges. Nothing already on the board is moved,
resized, recoloured, reordered or removed, and there is no flag that does those things. The MCP
tool `canvas_add` is named for what it does.

**Everything untouched survives byte for byte.** The file is parsed as JSON and written back with
the existing node objects passed through exactly as they came out — positions, colours, and any
key a future Obsidian invents that this has never heard of. That last part is not hypothetical:
the JSON Canvas specification is Obsidian's and it will grow.

**Indentation is detected, not imposed.** A canvas that gains one box must not arrive at every
device as a whole-file diff. A new file gets tabs.

**Ids are derived from what a node points at, never generated.** `sha256("file:Alpha.md")[:16]`,
which is the shape Obsidian's own ids have. So adding the same note twice is a no-op that reports
as one, and running the same command on a schedule produces no diff — the property `hvk views`
has, for the same reason.

**A node points at a file that exists**, resolved inside the vault first. A box pointing at
nothing looks like a box that has not finished loading, which is the least visible kind of broken
link there is (ADR-0015 built canvas *reading* precisely because an unlinked note is the state in
which people delete things).

**New boxes go below everything already on the board**, in a grid, measured once from the lowest
edge before anything is added. Below and never among: boxes appearing in the middle of somebody's
arrangement would be the rearrangement this refuses to do, achieved by accident.

**`--apply` writes; without it nothing is touched and the change is listed**, the same bargain
`hvk views` strikes.

## Consequences

**"Add-only" is a promise that gets less comfortable over time.** The first person to ask for
`--move` will have a reasonable case, and the answer will have to be an ADR that supersedes this
one rather than a flag. That is the intended cost.

**A board can only be tidied by a person, in the app.** Twenty notes added from the command line
land in a grid below the existing content and stay there until somebody drags them. That is the
right way round — a machine that guesses at a layout is guessing at meaning — but a large
`--from-tag`-style bulk add would produce something nobody would call a whiteboard.

**Deriving ids from content means a note's box moves with its path.** Rename a note, add it
again, and a second box appears: the id is a hash of the path, so the new path is a new node. The
old box is left pointing at a file that no longer exists, which is a broken link on a board — the
exact thing this refuses to create in the first place. Nothing here repairs it, and `hvk links
--broken` is what finds it.

**There is no `--remove`, so a mistake is undone by hand or by git.** Adding the wrong note to a
board leaves it there. Given that the vault on the server is a git repository (ADR-0006) and that
the alternative is a delete operation on somebody's arrangement, that is the trade taken.

**Edges are drawn bottom-to-top with no routing.** `fromSide` and `toSide` are fixed rather than
chosen from the geometry, so an arrow between two boxes that happen to sit side by side takes an
odd path. Obsidian re-routes on open; this does not.
