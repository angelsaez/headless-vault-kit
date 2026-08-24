# 0017 — A parser interface, extracted from the two that existed

**Status:** accepted
**Date:** 2026-08-25
**Phase:** 7

## Context

The three-tier model has promised an "extensible parser interface" since the plan was written,
and until now that promise had nothing behind it. `scan.py` chose a parser with a dictionary of
three extensions and an `if` with two branches:

```python
KIND_BY_EXT = {"md": "note", "canvas": "canvas", "base": "base"}
...
if fields["kind"] == "note":
    error = _store_note(...)
elif fields["kind"] == "canvas":
    error = _store_canvas(...)
```

That was honest while there were two parsers and no way for anyone else to add a third. It is
not a thing a stranger can write against.

The plan's instruction was specific and it is the reason this ADR is short: **do not invent the
interface, extract it.** Two implementations were already in the tree, and their shape was
already common — declare an extension, return links, tags, properties and tasks. A contract
pulled out of two working cases is a contract that fits at least two things. One designed for an
imagined third fits nothing.

The plan also named the example adapter before any of this was written: **Kanban**, because its
board is Markdown with a known structure, it produces something the index does not already hold,
and it does not duplicate what Canvas does. That choice turned out to constrain the design more
than anything else here, and the next section is mostly about why.

## Alternatives

- **Dispatch on the extension alone.** The obvious reading of "a module that declares which
  extensions it understands", and it would have been enough for Markdown, Canvas and `.base`.
  It has nothing to say about a Kanban board, which is a `.md` file marked by a line in its own
  frontmatter — so the interface would have been published, and then the first adapter anyone
  actually wanted could not have been written against it. Rejected on the strength of the one
  example available.
- **A second kind of thing: parsers, plus "enrichers" that run afterwards.** Models Kanban
  honestly — it really is Markdown plus extra. It also doubles the surface, needs an ordering
  rule between enrichers, and asks an adapter author to decide which of two categories they are
  in before they have written a line. Rejected: Canvas already showed the cheaper move, which is
  for a specialised parser to *call* the general one and add to its result.
- **Discover parsers from installed packages** via `importlib.metadata` entry points, the way
  Python usually does this. Rejected, and not on cost — it is fifteen lines of standard library.
  See the decision.
- **Publish nothing; keep the two parsers hardcoded and write the Kanban support inline.**
  Cheapest, and it would have worked. It also leaves the tier-2 promise unbacked for a second
  year and makes the exit criterion — an adapter that works without touching the core —
  unmeasurable, because there would be no "without touching the core" to measure.

## Decision

**A parser declares its extensions and, optionally, a claim.** `hvk.parse.registry.Parser` is a
frozen dataclass: a name, the extensions it answers for, the `files.kind` it produces, a `parse`
function, an optional `claims` predicate and a priority. `scan.py` asks the registry which parser
reads a file and stores whatever comes back. The two branches are gone; there is one `_store`.

The claim is the part that is not decoration. It is given the file's text and its path and
answers whether this particular file is its business — which is how a Kanban board is told from
a Markdown note, and equally how a note *about* Kanban is told from a board. It runs once per
file on every scan, so it reads the frontmatter and stops rather than the whole file.

**The contract is `hvk.parse.model.Parsed`, and every field on it is a table in the index.** A
contract that can express something the index cannot store is a contract with a lie in it, and
there is a test asserting the two lists are the same. The row shapes — `Prop`, `Tag`, `Heading`,
`Block`, `RawLink`, `Task` — moved out of `parse/markdown.py` into `parse/model.py`, so that a
parser written by someone else has somewhere to import them from that is not the Markdown
parser. They are re-exported from their old home, because that is where every existing caller
knows to look.

**A parser returns errors; it does not raise them.** One unparseable file is recorded in
`files.parse_error` and the walk goes on. A parser that raises can take a whole vault's index
down with a single bad note, and that failure mode must not be reachable from a file.

**`parse` may be `None`.** `.base` is exactly that: a known kind of file that derives no rows.
The index records that a base exists so `hvk views` can find one by name, and the Bases machinery
reads the file whole, on demand. Shredding a query definition into rows would derive nothing
anybody asks the index for.

**Registration is explicit, and nothing is discovered.** `hvk.parse.BUILT_IN` is the registration
point for a parser living in this repository — one line — and `register()` is public, so an
adapter in somebody else's package registers itself by being imported. What does *not* happen is
`hvk scan` sweeping installed distributions for anything declaring an entry point. Making a
vault scan load and execute whatever third-party code is installed on the machine is a decision
about trust, not about parsing, and this project does not make that one as a side effect of a
packaging convenience. Entry points can be added the day publishing forces the question; the
interface does not change if they are.

**The example adapter is `hvk.parse.kanban`, and it contributes two things.** Which list a card
sits in, written into the task's `extra` beside the Tasks plugin's fields (ADR-0004); and the
date, because Kanban writes `@{2026-09-01}` in its own syntax and nobody else's, so `hvk tasks
--due-before` was blind to every card on every board. The second is the one that earns its place:
a command written in phase 2 answers a file format read in phase 7, with no new column, no new
flag and no change to `scan.py`. The adapter imports the registry and the Markdown parser and
nothing else; deleting the file removes the feature and breaks nothing.

## Consequences

**The schema version goes to 5, so every existing index needs `hvk rebuild`.** The same reason
Canvas forced version 4: the boards already indexed have no list and no date on their cards, their
hashes are unchanged, and nothing would ever go back for them. A rebuild is seconds and the
version check is the mechanism that already exists to demand one.

**A claim runs on every Markdown file, on every scan.** It is bounded — the first four kilobytes,
and only the frontmatter within them — but it is not free, and the cost grows with the number of
registered adapters rather than with the number that match. Two of them and it is unmeasurable
against parsing; twenty claiming `.md` and this is the line to look at. The 10,000-note benchmark
is where that would show, and it has not moved.

**A board whose owner changed Kanban's date trigger reads as a board with no dates.** The plugin
lets you configure the character. This reads the default and nothing else, exactly as ADR-0004
decided for the Tasks plugin's vocabulary: the failure is a missing field, never a wrong one.

**The Tasks plugin's date wins when a card carries both.** An arbitrary rule between two things
that should not disagree. It is written down here and tested, which is the most that can be said
for it.

**"Without touching the core" is now a claim someone can check**, and the check is the Kanban
adapter itself: it is a file that imports the published interface, is named in one list, and
touches nothing else. That is what stands in for the exit criterion the plan retired on
2026-08-24 — an adapter written by somebody who is not Ángel. It is a weaker claim than the
original, and it is the one that measures the design rather than the adoption.

**Two parsers can now claim the same file, and the priority number is what decides.** A number is
a poor way to express "specialised beats general", and the day there are three adapters competing
for `.md`, whoever picks the numbers is making an ordering decision with no help from the type
system. It is the same shape every plugin registry ends up with, and the alternative — an explicit
dependency graph — is a great deal of machinery for four parsers.
