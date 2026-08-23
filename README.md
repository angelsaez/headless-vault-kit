**English** | [Español](README.es.md)

# headless-vault-kit

> Puts Obsidian's own functionality back on a vault that lives on a headless server, where the
> app never opens: a SQLite index, backlinks, Dataview and Bases queries, and agent-driven
> automation running 24/7. The CLI installs as **`hvk`**.

## The problem

Move an Obsidian vault to a headless server — a machine with no screen, so an agent and its
automations can work on the notes around the clock — and the files arrive fine: Obsidian
Headless keeps them in sync. What never happens is Obsidian itself opening, and with it you
lose everything the app computes at startup: backlinks, Dataview queries, Bases, the CLI,
plugins. The result: synced notes, and nothing that can answer a question about them.

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
language is supported and what is refused. Canvas is postponed until a vault actually contains
a `.canvas` file, and periodic notes wait on a decision rather than on work.

**Phase 4 has its valuable half.** A note can carry a base's answer inside itself, between
`<!-- vista:inicio -->` and `<!-- vista:fin -->`, so the table is readable on a phone where
nothing renders a base. `hvk views` reports what is stale and `hvk views --apply` rewrites it,
touching only the text between the markers and writing nothing at all when nothing changed —
which is what keeps a half-hourly refresh from waking sync every half hour on every device.
It is the first thing here that writes to a vault, so it goes through one audited layer
([ADR-0007](docs/adr/0007-writing-to-the-vault.md)); the declaration syntax is
[ADR-0008](docs/adr/0008-materialised-views.md). The Dataview DQL subset the phase originally
promised is postponed indefinitely: the vault it was written for has no Dataview installed.

**Phase 5 turns the vault into the job queue.** A note in a directory you nominate *is* a job:
its frontmatter is the state, so its progress is readable on a phone like any other note.
`hvk jobs --run` claims each pending job with a write that states the digest the note had when
it was read — which is what makes a job run exactly once even if two runners race or one is
restarted mid-flight — launches the agent, and records the outcome and the reason in the note.

It is also the first thing here that *executes* something because a note said so, and a note
can arrive from anywhere. So: every job must name a permission profile, chosen by name from a
directory the note cannot reach; the jobs and profiles directories have **no defaults**, and
nothing runs until somebody says where they are; and an output path inside the jobs directory
is refused, because that is how a runner feeds itself work for ever.
[ADR-0009](docs/adr/0009-order-notes.md) has the reasoning.

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
| `hvk views [Path] [--apply]` | Refresh the base tables materialised inside notes; without `--apply` it only lists what is stale |
| `hvk jobs --dir D --profiles P [--run]` | Run the order-notes waiting in a directory; without `--run` it only reports |
| `hvk info` | What the index currently holds |

Every command takes `--json` for machine-readable output; `hvk watch` emits JSON Lines, one
object per batch, so it can be piped into a log.

To keep the index current, run `hvk watch` as a service and re-hash nightly from cron:

```cron
17 4 * * *   hvk --vault /path/to/vault verify
*/30 * * * *  hvk --vault /path/to/vault views --apply
```

The second line is what keeps materialised views current. It is safe to run as often as you
like: it writes only what actually changed, and nothing at all when nothing did. Wiring it
into `deploy/` is still to do.

The systemd unit for the watcher belongs to phase 0 and will live in `deploy/`.

When the tool is published, installing it will be two commands and no `sudo`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install hvk
```

## Roadmap

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Server baseline: Headless sync + Claude Code/Telegram + git, reboot-proof | Built, not yet run on a server |
| 1 | Vault inventory: which plugins and real-world usages need covering | **Done** |
| 2 | Tier-0 indexer + `hvk` CLI | **Done** |
| 3 | Bases, Canvas, templates and periodic notes | Bases **done**; the rest postponed |
| 4 | Materialized views (Dataview DQL postponed) | **Done** |
| 5 | Order-notes: the vault as a job queue | **Done** (Sync and Telegram wait on phase 0) |
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
