**English** | [Español](README.es.md)

# headless-vault-kit

> Headless toolkit for Obsidian vaults: SQLite index, backlinks, Dataview/Bases queries
> and agent-driven automation on a 24/7 server — no app required. The CLI installs as **`hvk`**.

## The problem

A "digital brain" (an Obsidian vault + AI agent + automations) needs to live on an
always-on machine. On a headless server, Obsidian Headless keeps the vault in sync, but
without the app running you lose everything Obsidian computes on startup: backlinks,
Dataview queries, Bases, the CLI, plugins. The result: synced notes, switched-off brain.

## The solution

Don't emulate Obsidian — **replicate its data**. Everything the app derives at startup is
state that can be rebuilt from the files themselves. This project rebuilds it on the server:

- **Indexer**: parses the vault into SQLite the same way the app's metadata cache does
  (frontmatter, tags, links, backlinks, tasks, headings, full text), with incremental
  updates as sync delivers changes.
- **`hvk` CLI**: search, backlinks, tasks and properties in milliseconds, so agents can
  query the vault without burning tokens reading files one by one.
- **Queries without the app**: Bases (`.base`) and a Dataview (DQL) subset executed against
  the index, plus materialized views rendered to Markdown — visible from any device.
- **The vault as a job queue**: order-notes with their state in frontmatter; a runner
  executes them with Claude Code and the results sync back to all your devices.
- **Harness**: permissions, hooks and auditing via Claude Code's native features + git.

The scope is governed by a three-tier model: the app's native behavior is replicated
exactly; Obsidian's official formats (Bases, Canvas, templates) get full support; and the
most popular community plugins are included only when their state lives in parseable files
— everything else goes through an extensible parser interface so anyone can contribute an
adapter. Plugin code is never executed and the UI is never reproduced.

## Status

✅ **Phase 2 is done.** The tier-0 indexer parses a vault into SQLite and answers search,
backlinks, links, tags, tasks, properties and orphans, with a deterministic rebuild. A watcher
keeps it current as sync delivers changes, a nightly pass re-hashes everything as a safety net,
and a [Claude Code skill](skills/vault-queries/SKILL.md) teaches an agent which command answers
which question.

Measured against a generated 10,000-note vault, on the plan's own targets, on both
Ubuntu 26.04 and Windows 11:

| Criterion | Target | Measured on Linux | On Windows |
|---|---|---|---|
| Full rebuild | < 60 s | **4.9 s** | 8.2 s |
| Incremental update | < 5 s | **0.34 s**, or 0.19 s targeted | 0.76 s / 0.31 s |
| Index queries | < 100 ms | **0.5 – 35 ms** | 0.8 – 80 ms |

One exit criterion for the phase is not something a laptop can close: answering "what links to
X?" over Telegram end to end depends on phase 0 running on the server.

**Phase 3 is under way.** `.base` files parse and run: `hvk base Library.base` executes a
view's filters, formulas, sorting and grouping against the index and prints a Markdown table.
[ADR-0005](docs/adr/0005-bases-subset.md) records exactly which part of the Bases expression
language is supported and what is refused. Canvas and template-driven periodic notes are next.

The full plan, with phases and exit criteria, lives in
[`.plans/Plan-v2-headless-vault-kit.md`](.plans/Plan-v2-headless-vault-kit.md) (Spanish); the
decisions behind the design are in [`docs/adr/`](docs/adr/).

## Try it

Not published yet, so it runs from a checkout. Python 3.11 or newer, no other prerequisites:

```bash
git clone https://github.com/angelsaez/headless-vault-kit
cd headless-vault-kit
uv venv && uv pip install -e ".[dev]"        # or python -m venv .venv && .venv/bin/pip install -e ".[dev]"

.venv/bin/hvk --vault /path/to/vault scan
.venv/bin/hvk --vault /path/to/vault backlinks "Some Note"
```

Inside a vault, `--vault` can be omitted: hvk walks up until it finds `.obsidian/`.

| Command | What it answers |
|---|---|
| `hvk scan` / `hvk rebuild` | Index new and changed files, or rebuild from scratch |
| `hvk search "text tag:project path:Areas"` | Full-text search, with optional tag and path filters |
| `hvk backlinks "Note"` | What links here, by note name or by path |
| `hvk links [Note] [--broken] [--ambiguous]` | Outgoing links, unresolved ones, or ones where more than one file matched |
| `hvk tags [--count] [--prefix home]` | Every tag, with how many files carry it; a prefix includes nested tags |
| `hvk tasks [--pending] [--due-before 2026-09-01]` | Tasks across the vault, by state, due date or path |
| `hvk props --where "status=open"` | Files by property; repeat `--where` to combine with AND, or omit it for the catalogue of keys |
| `hvk orphans [--attachments]` | Files nothing links to |
| `hvk watch` | Index changes as they land, until interrupted; meant to run as a service |
| `hvk verify` | Re-hash every file as a safety net; run it nightly from cron |
| `hvk base File.base [--view Name]` | Run a view from a `.base` file against the index, as a Markdown table |
| `hvk info` | What the index currently holds |

Every command takes `--json` for machine-readable output; `hvk watch` emits JSON Lines, one
object per batch, so it can be piped into a log.

To keep the index current, run `hvk watch` as a service and re-hash nightly from cron:

```cron
17 4 * * *  hvk --vault /path/to/vault verify
```

The systemd unit for the watcher belongs to phase 0 and will live in `deploy/`.

When the tool is published, installing it will be two commands and no `sudo`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install hvk
```

## Roadmap

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Server baseline: Headless sync + Claude Code/Telegram + git, reboot-proof | Pending |
| 1 | Vault inventory: which plugins and real-world usages need covering | Pending |
| 2 | Tier-0 indexer + `hvk` CLI | **Done** |
| 3 | Bases, Canvas, templates and periodic notes | **In progress** |
| 4 | Dataview (DQL) + materialized views | Pending |
| 5 | Order-notes: the vault as a job queue | Pending |
| 6 | Security, healthchecks, rehearsed backups | Pending |
| 7 | MCP server + community parsers + packaging | Future |

## What do I need to use it?

It depends on the layer — the project is usable in independent pieces:

| Layer | What it does | What it requires |
|---|---|---|
| Index + CLI (Phases 2–4) | Search, backlinks, tasks, properties, Bases/DQL queries, materialized views | **Just your files** (any Obsidian vault or Markdown folder) + the runtime. No AI, no app, no subscriptions. Zero tokens |
| Sync | Up-to-date vault on the server | Obsidian Sync + Obsidian Headless, **or** git as transport. The index doesn't care how files arrive |
| Intelligent automation (Phase 5) | Order-notes that need judgment ("review", "summarize", "detect") | A CLI agent. **Claude Code is supported out of the box**; the formats (YAML, Markdown, SQLite) are neutral and swapping agents means changing one line in the runner. Deterministic jobs (regenerate views, create the daily note) need no agent at all |
| 24/7 chat access | Talk to your vault from your phone | Claude Code + Telegram plugin (or equivalent) |

Obsidian as an application is only needed where it always was: on your devices, for
reading and writing as a human.

## Reference server

- Linux VPS (tested on 2 cores / 12 GB — plenty).
- Git.

## Repository layout

```text
.plans/     Implementation plans (source of truth for scope)
docs/adr/   Architecture decision records (the "why" behind the design)
skills/     Claude Code skills, so an agent knows which command to reach for
docs/       CHANGELOG.md — repository journal
CLAUDE.md   Guide for the agent developing and operating this repo
README.md   This file (English) · README.es.md (Spanish)
```

Remaining folders (`src/hvk/`, `tests/`, `test-vaults/`, `runner/`, `deploy/`) will appear as
their phases are implemented. The tool is written in Python 3.11+ (see
[ADR-0001](docs/adr/0001-indexer-language.md)).

## Contributing

Not yet: the project is in planning and the early phases are personal. Phase 7 will open
the parser interface and documentation so the community can contribute plugin adapters.
Feedback on the plan is welcome anytime.

## Name and command

The repository and tool are **headless-vault-kit** (descriptive, self-explanatory); the
CLI binary is **`hvk`** (`hvk search`, `hvk backlinks`, `hvk dv "..."`) — long clear repo
name, short comfortable command.

## License

To be decided before the repository goes public (see `.plans/`, Annex).
