# Synthetic test vaults

Everything in this directory exists to be indexed by the test suite. Per `CLAUDE.md`, the real
vault is never used during development: correctness is demonstrated here, edge cases included.

## Rules

1. **One vault per concern.** Mixing link resolution and YAML edge cases in a single vault
   makes every test depend on unrelated files.
2. **No documentation inside a vault.** Every `.md` file inside a vault is a note the tests
   count, so a `README.md` in there would change the expected results. All documentation lives
   in this file, which sits outside all of them.
3. **Only what checks out on every operating system.** Two files whose names differ only in
   case, or only in Unicode normalisation form, cannot coexist in a repository cloned on
   Windows or macOS. Those cases are real and are covered — but by fixtures that build a vault
   at run time and skip themselves when the filesystem cannot represent it. Nothing committed
   here may depend on a case-sensitive or normalisation-sensitive filesystem.
4. **Expectations live in the tests, not here.** This file describes intent; the assertions are
   the source of truth. Two copies of the same truth drift apart.
5. **UTF-8 and LF, always.** `.gitattributes` enforces the line endings, and a changed line
   ending silently alters parsing and breaks the deterministic-rebuild comparison.

## `basic/` — a small realistic vault

The default fixture for scanning, search and backlinks. Eight files, one attachment, nothing
pathological.

| File | What it contributes |
|---|---|
| `Home.md` | Frontmatter list-style tags, inline tags including a nested one (`#home/nested`), outgoing links |
| `Projects/Alpha.md` | Block-style tags, aliases, typed properties, inline fields (`Owner:: …`), tasks, a block id (`^alpha-note`), an embed, a heading subpath link |
| `Projects/Beta.md` | Inline field whose key contains a space, closed status for property filtering |
| `Areas/Reading.md` | **Duplicate heading** (`## Articles` twice), which makes `[[Reading#Articles]]` ambiguous at the subpath level |
| `Daily/2026-08-20.md`, `Daily/2026-08-21.md` | Periodic notes linking to each other, date properties |
| `Tasks.md` | Every checkbox state, a nested task, a task in a blockquote, and a task inside a code fence that must **not** be indexed |
| `attachments/diagram.png` | Link and embed target that is not a note |

## `links/` — link resolution, the fixture behind ADR-0003

Every link form the resolver has to handle. Expected results follow the algorithm in
[ADR-0003](../docs/adr/0003-link-resolution.md); `candidates` is how many distinct files
matched **any** of the three rules, which is not the same as how many the winning rule found —
that is what keeps `--ambiguous` from reading as a false all-clear.

From `Source.md`, which sits at the vault root:

| Link | Resolves to | `candidates` | Rule exercised |
|---|---|---|---|
| `[[Note]]` | `Note.md` | 3 | Tie-break: same folder as the source |
| `[[FolderB/Note]]` | `FolderB/Note.md` | 1 | Exact path |
| `[[Note.md]]` | `Note.md` | 3 | Exact path wins, but three files share the name |
| `[[Inner/Deep]]` | `Nested/Inner/Deep.md` | 1 | Path suffix |
| `[[Note\|shown like this]]` | `Note.md` | 3 | Display text stripped before resolving |
| `[[Note#Heading Two]]` | `Note.md` | 3 | Subpath stored, ignored when choosing the file |
| `[[Note#^ref-block]]` | `Note.md` | 3 | Block subpath |
| `[[#Source subheading]]` | `Source.md` | 1 | Empty target resolves to the containing file |
| `[[Unique Name]]` | `Unique Name.md` | 1 | Space in the filename |
| `[[Missing Note]]` | *unresolved* | 0 | Reported by `hvk links --broken` |
| `[[diagram.png]]` | `attachments/diagram.png` | 1 | Non-Markdown match requires the extension |
| `[[diagram]]` | *unresolved* | 0 | The same file must **not** match without it |
| `![[diagram.png]]` | `attachments/diagram.png` | 1 | Embed flag set |
| `![[Note]]` | `Note.md` | 3 | Embed of a note |
| `[a unique name](Unique%20Name.md)` | `Unique Name.md` | 1 | Markdown link, percent-decoded |
| `[heading](FolderA/Note.md#Heading%20Two)` | `FolderA/Note.md` | 1 | Markdown link with an anchor |
| `[example](https://example.com/page)` | *external* | 0 | Never reported as broken |
| `[write](mailto:someone@example.com)` | *external* | 0 | Scheme other than http |
| `[relative](//example.com/x)` | *external* | 0 | Protocol-relative |

From `FolderA/Local.md`, which does **not** sit at the root — the same bare link must resolve
differently depending on where it is written:

| Link | Resolves to | `candidates` | Rule exercised |
|---|---|---|---|
| `[[Note]]` | `FolderA/Note.md` | 3 | Same-folder tie-break, opposite outcome to `Source.md` |
| `[[Note.md]]` | `FolderA/Note.md` | 3 | Writing the extension does not make a link root-absolute: both the root and the sibling match by exact path, and proximity still decides |
| `[[Local]]` | `FolderA/Local.md` | 1 | A file linking to itself |

`Fences.md` contains one real link and four decoys — inside a fenced block, inside inline
code, inside an indented block and inside an Obsidian `%% … %%` comment. Only the first is a
link. The comment case is marked in ADR-0003 as pending confirmation against the app.

## `frontmatter/` — YAML conformance, the cost accepted in ADR-0001

Numbered so failures are easy to name.

| File | What it pins |
|---|---|
| `00-none.md`, `01-empty.md` | No frontmatter at all, and delimiters with no keys |
| `02-scalars.md` | Strings, numbers, booleans, three ways of writing null, an empty value |
| `03-yaml11-traps.md` | `no`/`yes`/`on`/`off`, `0755`, `12:30`, `NO` — the exact cases where YAML 1.1 and 1.2 disagree, and the reason ADR-0001 pins `ruamel.yaml` |
| `04-lists.md` | Block and flow sequences, a nested tag, an empty list, mixed types |
| `05-nested.md` | Nested maps, three levels deep |
| `06-multiline.md` | Literal (`|`), folded (`>`) and escaped scalars |
| `07-dates.md` | Date, datetime, quoted date, bare time, partial date |
| `08-malformed.md` | Invalid YAML: the scan must survive it and record the failure |
| `09-delimiter-in-body.md` | A horizontal rule and a fake fence in the body, after valid frontmatter |
| `10-not-at-start.md` | A frontmatter-looking block that is not frontmatter, because it does not open on line 1 |
| `11-unicode-keys.md` | Accented, CJK, quoted-with-spaces and emoji keys |
| `12-duplicate-keys.md` | The same key twice — last one wins |

## `tasks/` — tier-2 task fields, the fixture behind ADR-0004

Due dates and priorities are not tier 0: a Markdown checkbox has neither. These come from the
Tasks plugin's emoji vocabulary and from Dataview inline fields, and this vault pins what is
read and — just as importantly — what is left alone.

| File | What it pins |
|---|---|
| `Dates.md` | Each date marker (due, scheduled, start, done, created), several on one line, a recurrence rule, and a marker followed by prose instead of a date |
| `Priorities.md` | All five priority markers, plus a task with none |
| `Dataview.md` | Bracketed `[due:: …]`, a field we deliberately do not read (`[owner:: …]`) left in the text, and a bracketed value that is not a date |
| `Plain.md` | A vault that never installed the plugin: tasks still index, the fields are simply absent |

Checkbox *states* stay in `basic/Tasks.md`, which is tier 0. The split is deliberate: one
vault covers what Obsidian itself derives, the other what a plugin adds.

## `unicode/` — names and content outside ASCII

Accented (NFC), CJK and astral-plane (emoji) filenames, plus a note whose body carries a
combining diacritic in NFD form, a zero-width joiner and right-to-left text. Links between
these files check that resolution survives all of it.

## Deliberately not committed here

These cases are covered by fixtures that build a vault at run time, because a repository
cannot carry them portably or because they are about behaviour rather than content:

- Two files whose names differ **only in case** (`Note.md` / `note.md`) — impossible to check
  out on Windows and macOS. The fixture skips itself where the filesystem cannot hold both.
- Two files whose names differ **only in Unicode normalisation** (NFC / NFD) — same problem.
- A file **being written** while the scan runs, for the stability check in list B of
  [ADR-0002](../docs/adr/0002-index-location.md).
- Symlinks, including one pointing outside the vault.
- Volume: thousands of notes, generated for the performance targets in the plan (§2), never
  stored in git.
