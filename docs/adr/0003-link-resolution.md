# 0003 — Wikilink resolution and ambiguity

**Status:** accepted
**Date:** 2026-08-21
**Phase:** 2

## Context

Backlinks are the flagship query of the whole project, and a backlink is only ever as correct
as the link resolution underneath it. The plan (§5, phase 2) asks for "wikilinks, links and
embeds resolved according to `app.json`", and the annex (decision 4) asks to "document the
`app.json` convention and its limits".

Two facts complicate this:

**Obsidian's exact rule is not publicly specified.** The app is closed source, and its
`MetadataCache.getFirstLinkpathDest` is the only authority on how `[[Note]]` is resolved when
several files share that basename. Community write-ups contradict each other: some report a
preference for the vault root, others "the shortest distinguishing path", and none states the
full tie-break. One widely-shared gist also claims that resolution normalises spaces, `-` and
`_` as equivalent; that behaviour could not be corroborated and is **not** implemented here.

**The plan's phrasing is imprecise and this ADR corrects it.** `app.json`'s `newLinkFormat`
(`shortest` / `relative` / `absolute`) and `useMarkdownLinks` govern how Obsidian **writes new
links**, not how it reads existing ones. Resolution does not consult them: a vault whose
setting is `absolute` still resolves a hand-written `[[Note]]` perfectly well. So phase 2 reads
`app.json` and stores it as vault configuration for when `hvk` starts *writing* links (phase 3
onwards, templates and canvas), and resolution is defined independently of it.

## Alternatives

- **Reverse-engineer the app's exact tie-break by experiment.** The honest way to reach true
  parity, but it needs the GUI plus a matrix of purpose-built vaults, and the answer is a
  moving target across app versions. It would block phase 2 for an unbounded time in exchange
  for a behaviour that affects a minority of links. Deferred to the manual validation the plan
  already schedules for phase 1.
- **Refuse to resolve anything ambiguous** and leave those links unresolved. Rejected:
  backlinks would silently lose real edges, and a silent omission is worse than a documented,
  possibly-different choice. The user would have no way of knowing what they are missing.
- **Resolve with an explicit deterministic rule and record the ambiguity as data.** Chosen.

## Decision

Resolution is defined by this project, documented here, and **deliberately independent of
`app.json`**. Where it may differ from the app, the difference is recorded in the index rather
than hidden.

### Algorithm

For a link found in source file `S`:

1. **Strip the display text** — everything after `|` in a wikilink, the label of a Markdown
   link.
2. **Split the subpath** — a trailing `#heading` or `#^block-id`. It is stored on the link row
   but plays no part in choosing the target file.
3. **Set the link aside if it is external** — any target with a scheme (`http:`, `https:`,
   `mailto:`, `obsidian:`, …) or a protocol-relative `//`. It is stored with `kind='external'`
   and no target, so that `hvk links --broken` never reports it.
4. **An empty target** (`[[#Heading]]`, `[[#^block]]`) resolves to `S` itself.
5. **Find candidates**, comparing names folded to NFC and then lowercased. All three rules
   are evaluated; the winner comes from the most specific one that matched, while the
   candidate *count* is the union of all of them (see below for why):
   1. **Exact path** — the target read as a vault-relative path, first with the extension as
      written, then with `.md` appended. Also tried relative to `S`'s own folder.
   2. **Path suffix** — files whose vault-relative path ends in `/<target>`, with or without
      `.md`. This is what makes `[[sub/note]]` a valid way to disambiguate.
   3. **Basename** — files whose name without the `.md` extension equals the target. For
      non-Markdown files the extension must be part of the match, so `[[diagram.png]]` finds
      the attachment and `[[diagram]]` does not.
6. **Tie-break**, applied in this order and always producing one winner:
   1. A `.md` file beats a non-`.md` file. A bare name overwhelmingly means a note.
   2. An exact-case match beats a match that only agreed case-insensitively.
   3. A file in the same folder as `S`.
   4. Fewest path segments, i.e. closest to the vault root.
   5. Lexicographic path order — the backstop that guarantees the result never depends on
      filesystem order or insertion order, which is what a deterministic rebuild requires.
7. **The winner** is chosen from the most specific rule that produced anything: exact path
   beats path suffix, which beats basename. Only within that rule does the tie-break run.
8. **No candidate** means an unresolved link: `target_file_id` is `NULL`. This is a normal
   state, not an error — Obsidian displays these too — and it is what `hvk links --broken`
   reports.

**Names are folded to NFC before comparison.** macOS stores filenames decomposed (NFD) and
Linux stores whatever it is handed, so a vault synced between the two ends up holding both
forms. Comparing raw code points would report every cross-platform link as broken, which is
the kind of failure that looks like data loss to the person hitting it. Two files whose names
differ only in normalisation therefore also count as ambiguous, and are flagged.

**Aliases do not resolve links.** Frontmatter `aliases` are indexed and reachable through
`hvk search`, but `[[Some Alias]]` does not resolve to the note carrying that alias. This
follows the app, whose resolver ignores aliases even though its autocomplete offers them, and
it is listed below as a difference to confirm against the GUI.

### Ambiguity is stored, not swallowed

The `links` table carries a `candidates` column: how many distinct files matched **any** of
the three rules, not just the winning one. That distinction matters. Counting only within the
winning rule would report `[[Note]]` as unambiguous whenever a root-level `Note.md` existed,
even with two more `Note.md` elsewhere in the vault that the app might well have preferred —
a false all-clear, which is worse than no signal at all. Counting the union means
`candidates > 1` reads as "several files could plausibly have been meant here", which is
exactly the question a validation pass needs answered. It turns an unbounded worry into a
finite checklist:

```text
hvk links --ambiguous     # every link where our rule had to pick a winner
```

Validating against Obsidian then means checking a handful of specific links in the GUI instead
of trusting that thousands are right. This is the plan's "document the differences, do not
paper over them" (§7) made operational.

## Consequences

**Backlinks may differ from the app in vaults with duplicate basenames**, and only there. The
divergence is bounded, enumerable and queryable, which is the most that can honestly be
offered while the app's rule is unpublished.

**The schema in the plan (§6) grows three columns on `links`:** `subpath`, `kind`
(`wikilink` / `markdown` / `external`) and `candidates`. All three are derived and rebuildable,
so nothing about the "drop and rebuild" guarantee changes.

**The synthetic vaults have to carry these cases** before the resolver is written: the same
basename in two folders, a copy in the source's own folder, names differing only in case,
links to attachments, broken links, subpath links, empty-target links, embeds, external links,
and Markdown links with URL-encoded spaces.

**If the app's real tie-break is discovered later and differs, only the resolver changes.**
A rebuild fixes the whole index; there is no migration and no stored decision to undo. That is
the property that makes it safe to ship a documented approximation now.

### Known differences to validate against the GUI

| # | Ours | Suspected app behaviour |
|---|---|---|
| 1 | Tie-break: `.md` → exact case → same folder → closest to root → lexicographic | Unpublished; reports conflict between root preference and shortest distinguishing path |
| 2 | Aliases never resolve links | Same, per bug reports — but worth confirming per version |
| 3 | No normalisation of spaces, `-` and `_` | Claimed by one community gist, uncorroborated |
| 4 | Case-insensitive matching | Believed identical; matters only on case-sensitive filesystems, i.e. the Linux target |
| 5 | Names folded to NFC before comparison | Unknown; chosen because the alternative breaks macOS-to-Linux vaults outright |
