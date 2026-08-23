# Architecture decision records

One decision per file, numbered, one page long. Filename: `NNNN-title-in-kebab-case.md`.

Working rule (see `CLAUDE.md`): **no relevant decision is made silently**. When implementation
runs into a fork that constrains the rest of the system, the code stops and the ADR is written
first.

## Format

```markdown
# NNNN — Title

**Status:** proposed | accepted | superseded by NNNN | reverted
**Date:** YYYY-MM-DD
**Phase:** n

## Context       · the problem that forces a decision, with measurements where they exist
## Alternatives  · the real options and what they cost, no straw men
## Decision      · what is chosen, in one sentence
## Consequences  · what is accepted in exchange, including the bad parts
```

Status only moves forward. An accepted ADR is never edited to change its mind; it is
**superseded** by a new one that references it. The record of decisions that turned out
wrong is part of what makes the log worth keeping.

## Index

| ADR | Title | Status | Phase |
|---|---|---|---|
| [0001](0001-indexer-language.md) | Implementation language for the indexer and CLI | accepted | 2 |
| [0002](0002-index-location.md) | Index location and exclusion rules | accepted | 2 |
| [0003](0003-link-resolution.md) | Wikilink resolution and ambiguity | accepted | 2 |
| [0004](0004-tier-2-fields-in-the-core.md) | Tier-2 fields in the core, ahead of the parser interface | accepted | 2 |
| [0005](0005-bases-subset.md) | Which part of Bases is supported | accepted | 3 |
| [0006](0006-deployment-leaves-the-system-alone.md) | Deployment leaves the system alone | accepted | 0 |
| [0007](0007-writing-to-the-vault.md) | Writing to the vault | accepted | 4 |
| [0008](0008-materialised-views.md) | How a note declares a materialised view | accepted | 4 |
