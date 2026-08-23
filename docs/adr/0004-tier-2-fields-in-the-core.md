# 0004 — Tier-2 fields in the core, ahead of the parser interface

**Status:** accepted
**Date:** 2026-08-21
**Phase:** 2

## Context

The plan's phase 2 CLI (§5) includes `hvk tasks --due-before 2026-09-01`. A due date is not
tier 0: a Markdown checkbox has no date, and nothing in Obsidian's own metadata cache produces
one. Due dates come from the **Tasks** community plugin's emoji syntax (`📅 2026-09-01`) and
from Dataview-style inline fields (`[due:: 2026-09-01]`).

Both belong to tier 2 (plan §3), which the plan says is supported "via an extensible parser
interface", and [ADR-0001](0001-indexer-language.md) recorded that this interface will be
subprocesses speaking JSON over stdio, decided when phase 7 arrives. So phase 2 needs a tier-2
field several phases before the tier-2 mechanism exists. That gap has to be closed
deliberately rather than by quietly writing plugin knowledge into the parser.

## Alternatives

- **Ship `hvk tasks` without `--due-before` and wait for phase 7.** Rejected: the plan lists
  it as part of this phase, and a task list the agent cannot filter by date is close to
  useless for the daily work the whole system exists to support.
- **Build the subprocess parser interface now.** Rejected: that is weeks of phase 7 work for a
  single field, and it would be designed with exactly one hypothetical consumer in mind. It is
  the over-engineering the plan names as its main risk (§7).
- **Extract the fields in the core, in a module deliberately shaped like a future adapter.**
  Chosen.

## Decision

A single module, `src/hvk/parse/tasks.py`, reads the Tasks-plugin and Dataview field syntax
from a checkbox line. It is constrained on purpose:

- **A pure function.** Text in, `(clean_text, fields)` out. No I/O, no state, no knowledge of
  SQLite, no imports from the rest of `hvk`. That is precisely the contract an out-of-process
  adapter will have, so moving it behind the interface later is a relocation, not a rewrite.
- **Syntax only, never plugin code** (principle 2 of the project). Nothing is executed and nothing
  is inferred; a field exists only if it is written in the file.
- **A closed list of recognised fields:** due, scheduled, start, done, created and cancelled
  dates; priority; recurrence rule. Anything else is left in the task text untouched.
- **The plugin's absence is not an error.** A vault that never installed Tasks simply has no
  such fields, and nothing about it changes.

## Consequences

**`tasks.due` and `tasks.extra_json` start being populated.** Both stay fully derived and
rebuildable, so the drop-and-rebuild guarantee is untouched.

**The core carries roughly sixty lines of tier-2 knowledge.** That is a debt, and this ADR is
where it is tracked. Phase 7 repays it by moving the module behind the parser interface; until
then, if the plugin changes its syntax, exactly one file changes.

**A precedent is set, and it is deliberately narrow.** A tier-2 format may enter the core only
when a phase's own exit criteria require it, and only as a pure function shaped like an
adapter. Anything wanted merely because it would be nice waits for the interface. Without that
line, "tier 2 is extensible" quietly becomes "tier 2 is whatever we felt like adding".
