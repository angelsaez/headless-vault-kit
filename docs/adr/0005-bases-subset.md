# 0005 — Which part of Bases is supported

**Status:** accepted
**Date:** 2026-08-21
**Phase:** 3

## Context

Phase 3 asks for `.base` files to be parsed and their "documented subset" of filters and
formulas executed against the index. The plan does not say what that subset is; this ADR does.

A `.base` file is YAML with five top-level keys — `filters`, `formulas`, `properties`,
`summaries`, `views` — and the YAML is the easy half. The hard half is that every filter,
formula and summary is an **expression** in a language with comparison, logical and arithmetic
operators, property references in four namespaces (`note.`, `file.`, `formula.`, `this.`),
method chaining, and roughly seventy built-in functions across eight types.

Two things make the scope decision unavoidable rather than a matter of taste:

1. **Some of the language is meaningless without a screen.** `html()`, `image()`, `icon()` and
   `escapeHTML()` exist to render things in a view. On a server producing a Markdown table
   there is nothing for them to render.
2. **One function breaks the project's first principle.** `random()` would make the same base
   over the same vault produce different output on every run, and principle 1 of `CLAUDE.md`
   is that everything derived is reproducible.

## Alternatives

- **A handful of hard-coded comparisons**, enough for `status != "done"`. Rejected: it fails
  on the first real base, and "we support Bases" would be a claim the code cannot back.
- **The whole language.** Rejected for now, not on principle: `list.map`, `list.filter` and
  `list.reduce` take expressions as arguments, which means lambda scoping, and the regular
  expression type needs a literal syntax the documentation does not pin down. Both are real
  work for constructs that barely appear in filters, which is where the value is.
- **A real expression engine with a closed function library.** Chosen.

## Decision

The YAML structure is supported **in full**: all five top-level keys, filters nested with
`and` / `or` / `not` to any depth, per-view filters combined with the global ones, `order`,
`limit`, `groupBy`, `properties.displayName` and `summaries`.

The expression language is supported through a real tokeniser and parser — not pattern
matching — covering literals, the four reference namespaces, comparison operators, logical
operators in both spellings (`&&` and `and`), arithmetic, string concatenation, indexing,
method chaining and function calls.

**The function library is a closed list**, chosen for what filters and formulas actually
contain:

| Group | Supported |
|---|---|
| Global | `if`, `min`, `max`, `number`, `list`, `link`, `date`, `now`, `today`, `duration` |
| Any | `isTruthy`, `isType`, `toString` |
| File | `hasTag`, `hasLink`, `hasProperty`, `inFolder`, `asLink`, and the fields `name`, `basename`, `path`, `folder`, `ext`, `size`, `ctime`, `mtime`, `tags`, `links`, `properties` |
| String | `contains`, `containsAll`, `containsAny`, `startsWith`, `endsWith`, `isEmpty`, `lower`, `title`, `trim`, `replace`, `reverse`, `slice`, `split`, `repeat`, and `length` |
| Number | `abs`, `ceil`, `floor`, `round`, `toFixed`, `isEmpty` |
| Date | `date`, `format`, `time`, `relative`, `isEmpty`, and the fields `year`, `month`, `day`, `hour`, `minute`, `second` |
| List | `contains`, `containsAll`, `containsAny`, `isEmpty`, `join`, `flat`, `reverse`, `slice`, `sort`, `unique`, and `length` |
| Link | `asFile` |
| Object | `isEmpty`, `keys`, `values` |

**Deliberately excluded, and why:**

| Excluded | Reason |
|---|---|
| `html`, `image`, `icon`, `escapeHTML` | Rendering only; nothing to render without a screen |
| `random` | Would make output irreproducible, against principle 1 |
| `list.map`, `list.filter`, `list.reduce` | Take expressions as arguments, so they need lambda scoping; rare in filters |
| The regular expression type | Needs a literal syntax the published documentation does not pin down |
| `link.linksTo` | Needs link resolution from an arbitrary link value rather than from a file; revisit if it appears |
| `map` views | A view type that only means something on a screen |

**Nothing is silently ignored.** An unknown function, an unsupported view type or a reference
that cannot be resolved is reported as a named error against the specific base and view, and
`hvk base` exits non-zero rather than printing a table that quietly lost rows. Same principle
as ADR-0003: a wrong answer is worse than a stated gap.

### Semantics this project defines

The published documentation describes what functions do, not how the language treats missing
values, so these are our rules, recorded here so a divergence can be found rather than argued
about:

- A property that does not exist evaluates to **null**, never an error.
- `null` is untruthy, equals only `null`, and is unequal to everything else. So
  `status != "done"` is **true** for a note with no `status`, which matches the intuition of
  "this note is not done".
- Ordering comparisons (`<`, `<=`, `>`, `>=`) against `null` are **false**, in both
  directions, rather than raising or sorting arbitrarily.
- Comparing a string with a number coerces the string when it parses cleanly as one, and is
  false otherwise.
- Sorting puts nulls last, whichever direction is asked for, because "notes without a date"
  are never what a user means by "the earliest".
- Two values that cannot be coerced to a common type do not order: `"many" > 10` is **false**,
  not a lexicographic comparison of `"many"` against `"10"`, which would be nonsense dressed
  up as an answer.
- Division by zero is null, not a crash. A base is a query, and one bad row should not take
  the table down.
- **A row is a note.** Attachments and `.base` files are not rows, so an unfiltered base does
  not list its own file next to the notes. `file.ext` stays available for filtering, but the
  row set it filters is the vault's Markdown notes.

Two literal formats the documentation does not pin down, implemented here as documented
approximations rather than claims of parity:

- **`duration()`** accepts `<number> <unit>` with the unit spelled out or abbreviated —
  `"7 days"`, `"2w"`, `"1 hour"`. Months and years are treated as 30 and 365 days.
- **`date.format()`** translates the Moment.js tokens that occur in practice (`YYYY`, `MM`,
  `DD`, `HH`, `mm`, `ss`, month and day names, `A`) and passes anything else through
  untouched.

### `this.`

`this.` refers to the note a base is embedded in. Running a base from a command line has no
such note, so `hvk base` accepts `--this PATH`. Using `this.` without it is an error naming
the missing option, not an empty result.

## Consequences

**A base that uses an excluded function fails loudly**, naming the function and the view. That
is the point: the user learns their base is not fully supported instead of trusting a table
that silently dropped a filter.

**The parser is the expensive part and it is worth it.** Once expressions parse properly,
adding an excluded function later is a dozen lines in one table, and the Dataview subset of
phase 4 has an evaluator to build on rather than starting from pattern matching.

**Parity with the app is unverified until a real base is run through both.** The plan's exit
criterion for this phase is exactly that comparison, and it needs the real vault. Until then
this is a documented approximation, like link resolution in ADR-0003.

**`now()` and `today()` make output time-dependent.** That is inherent to what they mean, not
a defect, but it does mean a base using them is not reproducible across days — worth knowing
before wiring one into a materialised view in phase 4.
