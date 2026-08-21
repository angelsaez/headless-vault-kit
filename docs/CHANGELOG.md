# Change log

Repository journal: one entry per change, newest first.
Format: `## YYYY-MM-DD — title`, saying what changed and why.


## 2026-08-21 — ADR-0003 refined while implementing it

- `docs/adr/0003-link-resolution.md`: two corrections found by writing the resolver.
  `candidates` now counts the union of every matching rule rather than only the winning one —
  counting within the winner alone would have reported a link as unambiguous whenever a
  root-level file matched, hiding rival files elsewhere in the vault and turning the
  validation list into a false all-clear. And names are folded to NFC before comparison,
  because macOS stores filenames decomposed while Linux stores what it is given, so raw
  code-point comparison would report every link in a cross-platform vault as broken.
- Recorded here rather than quietly changed: an ADR that no longer describes the code is
  worse than no ADR.

## 2026-08-21 — ADR-0003: wikilink resolution and ambiguity

- `docs/adr/0003-link-resolution.md`: an explicit, deterministic resolution algorithm —
  exact path, then path suffix, then basename; tie-break `.md` → exact case → same folder →
  closest to root → lexicographic — plus a `candidates` column on `links` so ambiguous
  resolutions can be listed with `hvk links --ambiguous`.
- Corrects the plan: `app.json`'s `newLinkFormat` and `useMarkdownLinks` govern how links are
  **written**, not how they are read, so resolution is defined independently of them.
- Why: Obsidian is closed source and its tie-break for duplicate basenames is unpublished,
  with community sources contradicting each other. Rather than guess silently or drop
  ambiguous links, the choice is made explicit and the ambiguity is stored as data, turning
  GUI validation into a finite checklist.

## 2026-08-21 — ADR-0002: index location and exclusion rules

- `docs/adr/0002-index-location.md`: the index lives in
  `${XDG_DATA_HOME:-~/.local/share}/hvk/<vault>-<hash8>/`, one directory per vault, with
  precedence `--index` > `HVK_INDEX_DIR` > default, and the vault discovered by walking up
  until a `.obsidian/` appears.
- Splits the two lists the plan mentioned as one: what is not indexed (any directory starting
  with `.`, with `.obsidian/*.json` read by path as the exception) and what is not watched
  (additionally `workspace*`, temporaries and files that have not settled).
- Why: `~/.nexus-index/` carried a personal vault's name into a public tool and did not
  support multiple vaults. Adds a hard rule — if the index directory resolves inside the
  vault, `hvk` aborts — which is what prevents the sync ↔ watcher loop.

## 2026-08-21 — ADR-0001: the indexer and CLI are written in Python

- `docs/adr/` (new): index, format and lifecycle of the decision records.
- `docs/adr/0001-indexer-language.md`: Python 3.11+, with `uv` as the documented install path
  and `ruamel.yaml` + `watchdog` as the only runtime dependencies.
- Why: measured on Windows 11 and Ubuntu 26.04. PEP 668 blocks `pip install --user` and
  neither `pipx` nor `uv` ships by default; Node is absent and current LTS releases serve
  Node 18, below the minimum `node:sqlite` requires. Given the audience — most users do not
  write code — installing in two commands without `sudo` and editing the source without a
  build step outweigh the free `js-yaml` parity, whose cost is absorbed with `ruamel.yaml`
  and a conformance suite.
- `CLAUDE.md` and both READMEs: the tree moves from `indexer/` + `cli/` to `src/hvk/`, because
  Python needs a single importable package.

## 2026-08-21 — Repository docs and git history move to English

- `docs/registro-cambios.md` → `docs/CHANGELOG.md`, translated; existing entries preserved.
- `CLAUDE.md`: everything that ships with the repository is now written in English — code,
  commit messages, branch names, ADRs and this change log. Spanish stays where the work is
  internal: `.plans/`, `CLAUDE.md` itself, and day-to-day conversation.
- Why: the repository is meant to be published. Commit messages and branch names are the
  most public and the least translatable part of a project — history cannot be rewritten
  after the fact — and ADRs are the "why" an outside contributor reads before touching
  anything. Doing this now costs one rewritten branch; doing it later costs the history.

## 2026-08-15 — Line endings forced to LF

- `.gitattributes` (new): `* text=auto eol=lf`, with binaries marked as such.
- Why: the target is Linux, and on Windows `core.autocrlf` was converting to CRLF on
  checkout. With synthetic vaults in play, a changed line ending alters parsing and breaks
  the very comparison a deterministic rebuild depends on.

## 2026-08-15 — .gitignore and the journal rule

- `.gitignore`: secrets, machine-local Claude Code settings, derived SQLite artifacts,
  Node/Python dependencies and test vault state.
- `CLAUDE.md`: the minimum verification checklist now includes adding an entry here.
- Note: entry added after the fact, when this file was created.
