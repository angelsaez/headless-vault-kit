# Change log

Repository journal: one entry per change, newest first.
Format: `## YYYY-MM-DD — title`, saying what changed and why.


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
