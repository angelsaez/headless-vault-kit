# Change log

Repository journal: one entry per change, newest first.
Format: `## YYYY-MM-DD — title`, saying what changed and why.


## 2026-08-23 — The vault-writing layer, and the first code that can destroy something

- `src/hvk/write.py` and `docs/adr/0007-writing-to-the-vault.md`. Until now every line of this
  project only read, which meant a bug could give a wrong answer but never lose anything, and
  `hvk rebuild` fixed it. Phases 4 and 5 write into the vault, so that safety net is gone and
  every write now goes through one module, reached through a `Vault` object — the path check
  lives on the thing you need in order to write at all, the way ADR-0002's check lives on
  `Locations`.
- Atomic by temporary file and rename, in the same directory so the rename stays atomic. The
  temporary is a dotfile, which the exclusion rules of ADR-0002 already hide from the watcher
  and the index.
- **Writing identical content does nothing at all** — the file is not opened and its mtime is
  not touched. That is not an optimisation: it is what stops a view regenerated every half
  hour from waking the watcher and sync every half hour on every device, and it makes the
  plan's "regenerate twice, no diff" criterion true by construction.
- **A file that moved underneath is never overwritten.** Every write states the digest it
  expected; if sync delivered an edit from a phone while we were thinking, the write is
  refused and says so. A file that did not exist is the same mechanism with an expected digest
  of `None`, so "create only if still absent" needs no special case.
- Line endings, the final newline and a byte-order mark all survive a round trip. Frontmatter
  survives because it is never parsed: editing a note edits its text, so key order, comments,
  quoting and even duplicate keys stay exactly as their author wrote them.
- Invalid UTF-8 is refused rather than repaired, and deletion means moving to `.trash/`,
  keeping the path relative to the vault root so two notes called `Index.md` in different
  folders do not collide.
- Every path is resolved — the path itself, not just its parent — and checked to be inside the
  vault. A *broken* symlink pointing outside is precisely what a parent-only check waves
  through and `open()` then follows. A note is untrusted input, and a path that escapes the
  vault is the shape a prompt injection would take. Nothing under a dot path is written
  either: this module writes notes, not `.obsidian/` or `.git/`.
- Generated content lives between two markers, and the splicing machinery takes both as
  arguments rather than naming them: what a block is called belongs to the feature that
  generates it, so phase 4's views can use the `<!-- vista:inicio -->` the plan fixes without
  the writer knowing anything about views. An unclosed marker is refused, and so is a second
  opening marker before the first has closed — neither is an invitation to guess where the
  generated content ends.

## 2026-08-23 — The docs stop borrowing a private name

- Both READMEs opened by explaining the project in terms of a "Nexus" — a word from a private
  circle, which says nothing to anyone outside it and, worse, hides what the tool is actually
  for. They now say it plainly: this puts Obsidian's own functionality back on a vault that
  lives on a headless server, where the app never opens. `README.es.md` also drops "hablar con
  tu Nexus" and the aside addressed to people arriving from the club.
- The plan loses the same borrowed vocabulary: the goal is a vault operating 24/7 on the VPS,
  and phase 0 follows a recipe that already works for other people, rather than "the lessons of
  Nexus 5". Scope, phases and exit criteria are untouched — only the words.
- `nexus-agent.service` becomes **`hvk-agent.service`**, and the tmux session `nexus` becomes
  `hvk-agent`, matching `hvk-watch.service`. Nothing is deployed anywhere yet, so the rename
  costs a `git mv`; discovering it after installing on a server would have cost a migration.
- `.gitignore` drops `.nexus-index/`, left over from before ADR-0002 moved the index out of the
  repository entirely.
- ADR-0002 keeps the word, because rejecting it as a path name is the decision it records. Only
  the clause describing it was corrected: it is a name borrowed from the author's own circle,
  not the name of a personal vault.
- Why: the repository is meant to go public. A reader who has to already know what a Nexus is
  cannot tell what this project does from its first paragraph.

## 2026-08-21 — A throwaway container to test the deployment in

- `tools/testbed/`: a disposable Debian 12 box with systemd, so `deploy/selftest.sh` can
  install units, write a crontab and start services without doing any of that on the
  developer's own machine. Until now it did, and cleaned up afterwards — which works but is
  not something to ask of a contributor.
- Debian 12 on purpose: it is what most VPS run, and its Python 3.11 is exactly the minimum
  ADR-0001 targets, so a pass there means something.
- `ob` and `claude` are stubbed rather than installed. Both need credentials, and the project
  is built so that it does not care how files arrive on disk — a fake syncer exercises the
  indexer just as well as a real one and needs nobody's password. `--runtimes`, `--vault` and
  `--claude` are there for when the thing under test really is the agent.
- **The fire test now passes for real.** Restart the container and all three services come
  back on their own, with the tmux session alive, the cron block in place and the index
  answering. That is a phase 0 exit criterion that WSL could not check.
- Three things it found, all of which would otherwise have surfaced on the server: Docker's
  default `tmpfs` is `noexec` and systemd's user manager has to execute from `/run`;
  `libpam-systemd` and `dbus-user-session` are what set `XDG_RUNTIME_DIR` and create
  `/run/user/<uid>`, without which `systemctl --user` cannot connect to anything; and
  `docker exec` opens no login session, so that variable has to be handed over by hand.
- `deploy/install.sh` now explains itself when it cannot create its directories, instead of
  dying on a bare "Permission denied" from `mkdir` under `set -e`. Found by making that
  mistake in the testbed.

## 2026-08-21 — Phase 0: deployment that leaves the machine alone

- `deploy/` arrives: systemd **user** units for Obsidian Headless, `hvk watch` and a tmux
  session running Claude Code with the Telegram channel, plus an auto-commit of the vault
  every 30 minutes and `hvk verify` nightly, all in the invoking user's own crontab.
- `docs/adr/0006-deployment-leaves-the-system-alone.md` records why none of it is system-wide.
  The target server already runs other things: writing into `/etc/systemd/system`, dropping
  files in `/etc/cron.d`, installing packages or changing firewall rules can all quietly break
  something that was working, in a way that will not look like it came from here. So the
  install needs no root except one `loginctl enable-linger`, installs no runtime, and refuses
  to overwrite a unit it does not recognise.
- Git on the server is local only, with no remote (plan annex, decision 5, settled today):
  checkpoints, an audit trail and an immediate undo, without a deploy key to manage or a cron
  job that fails on a network blip. Surviving the loss of the server is phase 6's problem.
- `deploy/selftest.sh` exercises the whole thing against a throwaway vault and stub binaries —
  install, re-install, refusal, auto-commit, a real tmux session under systemd, and uninstall —
  then puts everything back. It passes on Ubuntu 26.04 with systemd 255.
- Two things it caught that would otherwise have been found on the server: `KillMode=none`,
  which every tmux-under-systemd recipe carries and systemd now deprecates, turns out to be
  unnecessary — oneshot with `RemainAfterExit` keeps the session and `ExecStop` still tears it
  down. And the units name `~/.config/hvk/deploy.env` as a literal, so a config kept anywhere
  else made every service fail at start with a message that names the file but not the cause;
  the installer now puts a copy where the units look.
- Also verified rather than assumed: the Telegram plugin is official
  (`anthropics/claude-plugins-official`) and **requires Bun**, and `ob` requires **Node 22+**.
  Neither prerequisite appears in the plan. Both are now checked by `preflight.sh` and stated
  in the runbook, which also spells out that pairing the bot is interactive and that leaving
  the policy at `pairing` rather than `allowlist` leaves an agent with vault access reachable
  by anyone who finds the bot.

## 2026-08-21 — A vault mirror, so real data can be tested against safely

- `tools/mirror_vault.py` copies a vault into a working directory and keeps it in step:
  re-running updates what changed and deletes what has gone. It leaves out `_PRIVATE` and
  `_PRIVADA` (both spellings, because getting that wrong once would copy secrets), `.git`,
  `.trash`, every other dot-directory and Obsidian's `workspace*`, while keeping
  `.obsidian/*.json`, which an inventory has to read.
- The refusals are the point. It will not write inside a git repository, because a mirror
  there is one `git add -A` away from publishing personal notes; it will not write inside the
  source, or over anything that looks like a real vault it did not create.
- `CLAUDE.md` gains the rule: validating against real data goes through a mirror, never the
  vault. The mirror lives outside the repository and its path on a given machine is not
  recorded here.
- Why now: the phase 1 inventory and the pending Bases validation both need real data, and
  redoing an ad-hoc copy every session is how a private folder eventually gets copied by
  accident.

## 2026-08-21 — Phase 1 inventory, and the plan revised to v2.1 with its data

- The vault inventory ran against a copy of the real vault, excluding `_PRIVATE/`, `.git/`,
  `.trash/` and `workspace*`. The production vault was never touched.
- It found what this plan had been guessing at, and guessed wrong: **no community plugins at
  all**, no `.canvas` files, no Templater, no inline fields, and exactly two `dataview` blocks
  — both plain `TABLE … FROM "folder" SORT … ASC` in a single note, and dead, since the plugin
  is not installed to render them.
- `.plans/Plan-v2-headless-vault-kit.md` goes to v2.1: phase 1 marked done with its results,
  Canvas postponed until a `.canvas` file exists, the DQL subset of phase 4 downgraded to
  optional, and materialised views re-pointed at Bases rather than Dataview. The success
  indicators table now carries the measured numbers next to the targets, and §4 no longer
  contradicts ADR-0002 about where the index lives.
- Two decisions closed in the annex (index location, link resolution) and one added: templates
  and periodic notes need a folder, a filename format and a template decided from scratch,
  because the vault does not say — `templates.json` points at a folder that does not exist and
  there is no `daily-notes.json`.
- The order of work is now written down as it actually happened: phases 1 and 2 first in local
  development, phase 0 next, because everything built has real users in the vault and nothing
  runs anywhere yet.

## 2026-08-21 — Bases run: `.base` files against the index

- `hvk base FILE [--view NAME] [--this PATH]` reads a `.base` file, runs one of its views
  against the index and prints a Markdown table, or JSON with `--json`. Global and per-view
  filters, formulas, `displayName`, sorting, grouping, limits and the built-in summaries.
- `src/hvk/bases/base_file.py` validates the whole file before a single row is read, so a
  broken base is reported up front rather than halfway through printing a table.
- Unknown YAML keys **warn** and the view still runs, because Obsidian keeps adding to this
  format and refusing a newer key would break the tool the week after an app release. Unknown
  functions and unsupported view types still fail: those change the answer rather than merely
  going unread.
- Two semantics ADR-0005 now states outright, both discovered by looking at the output:
  a row is a note, so an unfiltered base does not list its own `.base` file next to the notes;
  and an empty group sorts last in either direction, the same rule nulls follow.
- `file.ctime` needed a column, so the schema goes to version 3. On Linux the filesystem
  rarely records a creation time, so `st_birthtime_ns` is used where it exists and the inode
  change time stands in where it does not — recorded rather than quietly wrong.
- A bug worth naming: base paths were resolved with `exists()`, so on a case-insensitive
  filesystem the folder `library/` answered to `hvk base Library` and was opened as if it
  were the base. It is `is_file()` now.
- Measured on the 10 000-note vault: a base with a filter, a formula and a sort runs in
  0.18 s.

## 2026-08-21 — Phase 3 begins: a real expression engine for Bases

- `docs/adr/0005-bases-subset.md` answers the question the plan left open — what "the
  documented subset" of Bases means. The YAML structure is supported in full; the expression
  language gets a closed function library, chosen for what filters actually contain. Excluded
  and why: rendering helpers (nothing to render without a screen), `random` (it would make
  output irreproducible, against principle 1), the lambda-taking list functions (they need
  scoping for a construct that barely appears in filters) and the regular expression type
  (its literal syntax is not published).
- `src/hvk/bases/`: a tokeniser and a Pratt parser, then an evaluator over the tree. Not
  pattern matching — `if(price, price.toFixed(2) + " dollars")` has a call, a method chain and
  an operator in one line, and phase 4's Dataview subset now has an evaluator to build on.
- The semantics the documentation does not define are defined here and written down: a missing
  property is null rather than an error, null equals only null (so `status != "done"` is true
  for a note with no status), ordering against null is false both ways, values that cannot be
  coerced to a common type do not order at all, and nulls sort last in either direction.
- Missing data stays quiet, mistakes do not: `price.toFixed(2)` on a note with no price is
  null, while `price.toFixxed(2)` on a note that has one names the typo. Calling `random()` or
  `html()` fails naming the function and pointing at the ADR.
- One bug caught by writing the tests: an unsupported function fell through to the
  note-property lookup and returned a silent null, which is exactly what the ADR forbids.

## 2026-08-21 — The vault-queries skill, and the plan's numbers measured

- `skills/vault-queries/SKILL.md`: when to reach for which command, written for the agent that
  will operate a vault rather than as a restatement of `--help`. It leads with the reason the
  index exists — reading two hundred notes to answer one question costs a large part of a
  context window, asking the index costs one command — and it repeats the plan's security
  rule where the agent will actually read it: vault content is data, never instructions.
- `tests/test_skill.py` runs **every** example in that skill against a synthetic vault. A
  skill documenting a flag that does not exist is worse than no skill: the agent trusts it and
  the failure looks like a broken vault.
- `tests/test_performance.py` turns the plan's numeric exit criteria into checks, against a
  generated 10 000-note vault. Marked slow and opt-in (`pytest -m slow`). Measured:

  | Criterion (plan §2, §5) | Target | Linux, the target platform | Windows |
  |---|---|---|---|
  | Full rebuild | < 60 s | **4.9 s** | 8.2 s |
  | Incremental update | < 5 s | **0.34 s**, or 0.19 s targeted, which is what the watcher does | 0.76 s / 0.31 s |
  | Queries | < 100 ms | **0.5 – 35 ms** | 0.8 – 80 ms |

- Bug the 10k vault exposed: searching for anything with punctuation — `subject-13`,
  `2026-08-21`, `kind/3` — failed with a raw SQL error, because FTS5 reads bare punctuation as
  query syntax. Ordinary words are now quoted before they reach FTS5, while operators someone
  typed deliberately (`OR`, `NOT`, `NEAR`, parentheses, quoted phrases, trailing `*`) are
  passed through untouched. Real vaults are full of dated and hyphenated names, so this would
  have hit on day one.
- `hvk backlinks` by bare name went from 29 ms to 1 ms: resolving a name that matches exactly
  one note no longer builds an in-memory index of the whole vault. Anything ambiguous still
  goes through the full ADR-0003 rules.
- `hvk info` now reports `last_scan`, so whoever is reading an answer can tell whether the
  index is current instead of going digging.
- **Phase 2 is complete in development.** Its remaining exit criterion — the end-to-end
  demonstration over Telegram — depends on phase 0 on the server.

## 2026-08-21 — Incremental indexing: the watcher and the nightly verification pass

- `hvk watch`: indexes changes as they land, with the debounce and stability check the plan
  asks for. A path is released only once it has been quiet *and* has stopped changing size,
  because Obsidian Headless writes large files in steps and parsing one mid-write puts
  garbage in the index. Batches take about 25 ms against the synthetic vaults.
- `hvk verify`: re-hashes every file instead of trusting mtime and size, as the nightly safety
  net. When it reports changes after a quiet period, it says so explicitly — that means the
  incremental path missed something, which is the only reason to run it.
- `src/hvk/watch.py`: the decision logic lives in `ChangeQueue`, which takes the current time
  as an argument and knows nothing about watchdog or threads, so debounce and stability are
  tested with a made-up clock rather than by sleeping. Directory events and very large batches
  fall back to a full scan, which settles folder moves correctly without reimplementing them.
- `scan.py` gained `index_file` and `apply_changes`, shared by the full scan and the watcher,
  so a single edit costs a single parse. Link resolution still runs over the whole table after
  every batch: one new file can repair a broken link in a note that was never re-read.
- New dependency: `watchdog`, which ADR-0001 authorised. Verified on both backends —
  ReadDirectoryChangesW on Windows and inotify on Linux.
- Phase 2 now has only the Claude Code skill left.

## 2026-08-21 — The rest of the phase 2 query commands

- `hvk tags [--count] [--prefix]`, `hvk tasks [--pending] [--done] [--due-before] [--path]`,
  `hvk props [--where COND]... [--key]` and `hvk orphans [--attachments]`. Every one of them
  takes `--json`, like the rest.
- `docs/adr/0004-tier-2-fields-in-the-core.md`: due dates are not tier 0, so reading them
  means letting tier-2 knowledge into the core several phases before the parser interface
  exists. The ADR records the shortcut, constrains it to a pure function shaped like a future
  adapter, and sets the rule for when it may happen again.
- `src/hvk/parse/tasks.py`: reads the Tasks plugin's date and priority markers and bracketed
  Dataview fields; `tasks.due` and `tasks.extra_json` are now populated. Schema version 2.
- `test-vaults/tasks/`: a vault per concern, covering what is read and what is deliberately
  left in the task text.
- Bug found and fixed: `hvk rebuild` checked the schema version before doing anything, so an
  index written by an older version could not be rebuilt — while the version-mismatch error
  told people to run exactly that. Rebuilding now deletes the database first, which also
  guarantees no stale rows survive.
- Still open in phase 2: the filesystem watcher, the nightly verification scan, and the
  Claude Code skill.

## 2026-08-21 — Tier-0 indexer and the first hvk commands

- `src/hvk/`: the package decided in ADR-0001 — `paths` (vault and index location),
  `db` (schema), `parse/markdown` (frontmatter, tags, headings, blocks, links, tasks, inline
  fields), `links` (resolution), `scan` (walk, hash, two-pass resolve), `query` and `cli`.
- Commands: `scan`, `rebuild`, `search` (FTS5 with `tag:` and `path:` filters), `backlinks`,
  `links --broken --ambiguous`, `info`. All of them take `--json`.
- `tests/`: 106 tests, including a three-way determinism check (scan, rebuild, from scratch)
  over all four synthetic vaults, and the filesystem cases that cannot be committed to git.
- Verified on Windows 11 and on Ubuntu 26.04, with identical results. On Linux the two tests
  Windows has to skip — filenames differing only in case, and only in Unicode normalisation —
  run and pass. `uv` installed there in one command without `sudo`, as ADR-0001 predicted.
- Three findings from writing it, each fixed rather than worked around:
  - ruamel keeps the **first** of a repeated frontmatter key while js-yaml keeps the last, so
    the mapping is now built by a constructor that matches the app.
  - The ADR-0002 safety rule could be bypassed by building `Locations` directly, so the check
    moved into the object itself.
  - Link resolution compared raw code points, which would have broken every link in a vault
    synced between macOS (NFD) and Linux (NFC). Names are now folded to NFC before comparison.
- Still open in phase 2: the filesystem watcher, the nightly verification scan, and the
  `tags`, `tasks`, `props` and `orphans` commands.

## 2026-08-21 — Synthetic test vaults

- `test-vaults/`: four vaults — `basic/` (realistic, the default fixture), `links/` (every
  link form ADR-0003 has to resolve), `frontmatter/` (the YAML 1.1 vs 1.2 conformance cases
  ADR-0001 accepted as a cost) and `unicode/` (non-ASCII filenames and content).
- `test-vaults/README.md`: what each vault covers, and a per-link table of expected
  resolutions that doubles as the spec the resolver is tested against.
- Deliberately left out of git, to be built by fixtures at run time: filenames differing only
  in case or only in Unicode normalisation, which cannot be checked out on Windows or macOS;
  plus files mid-write, symlinks and volume tests.
- Why: `CLAUDE.md` forbids developing against the real vault. Nothing can be indexed until
  there is something safe to index.

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
