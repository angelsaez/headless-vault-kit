# 0021 — The third rewrite

**Status:** accepted
**Date:** 2026-08-25
**Phase:** 3

## Context

[ADR-0016](0016-a-subset-of-a-query-language.md) says the DQL subset reaches the Bases expression
engine "after exactly two rewrites": `=` to `==`, and `contains(a, b)` to `a.contains(b)`. That
sentence was true when it was written and was never tested against a query somebody else had
written.

The first time it was — the one `dataview` block in a real vault, on 2026-08-25 — it failed:

```
TABLE WITHOUT ID SP AS "Índice", file.link AS "Enlace"
FROM "400 - MEMORIA DIGITAL/405 - GESTIÓN DE PROYECTOS/PMP/Herramientas y Técnicas"
SORT SP ASC
```

```
hvk: file has no member 'link'
```

Everything else in that query worked: `WITHOUT ID`, two aliased columns, a `FROM` naming a folder
full of accents and brackets, and `SORT`. The single point of failure was `file.link`, which is
not an exotic corner of Dataview — it is how a table of notes is written, and `TABLE WITHOUT ID
..., file.link` is close to a house style in the wild.

The capability was already there. `link()` exists as a global function in the engine and returns
a `Link`. Dataview spells the same thing as a **member** of `file`. What was missing was the
translation, which is the one job this module has.

## Alternatives

- **Add `link` to the engine's file members.** One line, in `evaluate.py`. Rejected: that engine
  is the Bases engine, and Bases reads what the app reads ([ADR-0005](0005-bases-subset.md)). A
  base written against a member the app does not have is a base the app cannot open, and hvk
  would have taught somebody a syntax that only works here.
- **Leave it and refuse by name.** Consistent with the subset's philosophy, and wrong here: the
  refusal is not "Dataview has a feature this does not implement", it is "this has the feature
  and does not recognise the name". Refusing a spelling of something you already do is not a
  documented subset, it is a bug with a polite message.
- **A third rewrite in `dql.py`.** Chosen.

## Decision

**`file.link` becomes `link(file, file.basename)`**, rewritten in `hvk.dql` alongside the other
two, before the tree reaches the engine.

The display name is passed explicitly. A `Link` with none renders as its whole path, and
Dataview shows a note's name — a table of twenty full paths, each carrying the folder it lives
in, is not the same answer.

**The rewrites stay in `dql.py` and the engine stays the Bases engine.** That is the line ADR-0016
drew and this does not move it: this module learns Dataview's spellings, and there is a test
asserting that `file.link` still fails inside Bases.

## Consequences

**ADR-0016's "exactly two rewrites" is now wrong**, which is why this exists rather than an edit
to that file. There are three, and the mechanism for a fourth is a function in `dql.py` and a
line in a table.

**The list will grow, and each entry is a small bet on intent.** `file.link` means what it
obviously means; some future spelling will not, and the rule for adding one stays what ADR-0016
set out — translate what the engine already does, never invent behaviour to match a name.

**One real query is one real query.** This was found by running the only `dataview` block in one
vault. It is far better evidence than none and it is not evidence that the subset is now
adequate; the next vault to arrive will very likely find the fourth rewrite.
