# 0016 — A subset of a query language, and the parts that refuse

**Status:** accepted
**Date:** 2026-08-24
**Phase:** 3

## Context

A Dataview subset was planned, then dropped, and the reason was evidence: the vault this was
built against has no Dataview installed and its two `dataview` blocks render nothing. Building a
query language for zero users is the v1 mistake in miniature.

The owner changed the criterion rather than the evidence, which is the honest way to reopen
something: not *"does anyone here use it"* but *"is this a format the community writes"*. A vault
arriving from anywhere else is full of `dataview` blocks, and a tool whose whole claim is that it
reads a vault without the app should be able to say what they mean. Recorded plainly: this ADR
exists against the recommendation in the room, and the reasoning that overruled it is better than
the one it replaced.

## Alternatives

- **Leave it dropped.** Defensible right up to the first vault that arrives with query blocks in
  it, at which point the tool reads the file and has nothing to say about the only part of it the
  author cared about.
- **Aim at Dataview compatibility.** A moving target implemented in JavaScript, with a surface
  including `TASK`, `CALENDAR`, `GROUP BY`, `FLATTEN`, durations, links-as-values and a function
  library. Worse, DataviewJS is permanently out of scope here — so "compatible" would be a claim
  this project could never make and would spend forever half-failing.
- **A documented subset that refuses the rest by name.** Chosen, and it is the same shape ADR-0005
  chose for Bases, for the same reason.

## Decision

**The clause structure is parsed here; the expressions are not.** `LIST`, `TABLE`, `FROM`,
`WHERE`, `SORT`, `LIMIT` are read by this module. Everything inside them — `status = "active"`,
`rating > 3`, `file.name` — goes to the expression engine Bases already uses, after exactly two
rewrites:

- **`=` becomes `==`.** Dataview spells equality with one sign. The rewrite uses a lookaround so
  `!=`, `>=` and `<=` cannot be damaged by it.
- **`contains(field, x)` becomes `field.contains(x)`.** Dataview calls functions where this engine
  calls methods on values. Only a **named list** is rewritten; anything outside it arrives at the
  engine as a bare call and is refused there, by name, because ADR-0005 already decided that an
  unknown function is an error and never a silent null.

**Inline fields are visible, and this is the real difference from Bases.** `hvk base` sees
Obsidian properties, which are frontmatter and nothing else. A DQL query sees frontmatter **and**
`key:: value` written in the body, because that is what Dataview writes and reads — a query that
ignored them would be answering a different question from the one the block asks. Two dialects
over one index, with different ideas of what a field is, on purpose.

**What is not implemented refuses with its own name in the message**: `TASK`, `CALENDAR`,
`GROUP BY`, `FLATTEN`, `FROM [[link]]`, and sources combined with `and`/`or`. Not "syntax error"
— the word that was not supported, so the difference between a person fixing a query and a person
filing a bug is one line of output.

**`dataviewjs` blocks are not read at all**, not even to report them. Executing plugin code is
permanently out of scope, and a half-answer about a script is worse than silence.

## Consequences

**The `=` rewrite is a guess about intent that will hold until it does not.** If a future
Dataview gives one `=` another meaning, this is the line that breaks, and it will break by
returning a wrong answer rather than an error. It is one regex with a test beside it, which is
the most that can be said for it.

**The function map will go stale**, exactly like the bypass-flag list of ADR-0011. A Dataview
function nobody mapped is refused by name, which is the safe direction to fail in: a query stops
rather than answering something else.

**A `dataview` block is not materialised into a note.** `hvk views` does that for Bases and
nothing does it for DQL yet. `hvk dql --note` runs the blocks and prints the answers, which is
the reading half. Materialising them would need the same directive-and-markers machinery pointed
at a different source, and nothing has asked for it.

**`SORT` reuses the ordering from Bases**, which puts nulls last whichever way the sort points and
compares numbers as numbers. That is a decision inherited rather than made here, and it is worth
knowing that Dataview's own null handling was not audited against it.

**This is tier 2 and it changes the promise of that tier slightly.** The three-level model says
tier 2 is "community plugins with state in parseable files, through an extensible parser
interface". A query language has no file state to parse: what it has is a syntax to read. The
model survives the stretch, and phase 7's parser interface is where the shape of tier 2 gets
settled properly.
