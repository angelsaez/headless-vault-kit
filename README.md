**English** | [Español](README.es.md)

# headless-vault-kit

> Puts Obsidian's own functionality back on a vault that lives on a headless server, where the
> app never opens: a SQLite index, backlinks, Bases queries, and agent-driven
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
- **Queries without the app**: Bases (`.base`) executed against the index, plus materialized
  views rendered into your notes as Markdown — visible from any device. A Dataview (DQL)
  subset was planned and is postponed; see the roadmap.
- **The vault as a job queue**: order-notes with their state in frontmatter; a runner
  executes them with Claude Code and the results sync back to all your devices.
- **Harness**: permissions, hooks and auditing via Claude Code's native features + git.

The scope is governed by a three-tier model: the app's native behavior is replicated
exactly; Obsidian's official formats (Bases, Canvas, templates) get full support; and the
most popular community plugins are included only when their state lives in parseable files
— everything else goes through an extensible parser interface so anyone can contribute an
adapter. Plugin code is never executed and the UI is never reproduced.

## Status

**Phases 0, 1, 2, 4 and 5 are done, and the Bases half of phase 3.** Since 2026-08-24 it runs
on a real server: an ARM64 VPS that already hosted its own Obsidian Headless and agent, where
`hvk` indexes a 274-note vault, keeps it current as sync delivers changes, and answers from
Telegram. Phase 6 — making the permission profiles a guarantee of the code rather than of a
config file, and a rehearsed restore — is under way. Days of production, not months: read the
roadmap before relying on it.

✅ **Phase 2.** The tier-0 indexer parses a vault into SQLite and answers search, backlinks,
links, tags, tasks, properties and orphans, with a deterministic rebuild. A watcher keeps it
current as sync delivers changes, a nightly pass re-hashes everything as a safety net, and a
[Claude Code skill](skills/vault-queries/SKILL.md) teaches an agent which command answers which
question.

Measured against a generated 10,000-note vault, on the plan's own targets, on both
Ubuntu 26.04 and Windows 11:

| Criterion | Target | Measured on Linux | On Windows |
|---|---|---|---|
| Full rebuild | < 60 s | **4.9 s** | 8.2 s |
| Incremental update | < 5 s | **0.34 s**, or 0.19 s targeted | 0.76 s / 0.31 s |
| Index queries | < 100 ms | **0.5 – 35 ms** | 0.8 – 80 ms |

One exit criterion for the phase is not something a laptop can close: answering "what links to
X?" over Telegram end to end depends on phase 0 running on the server.

✅ **Phase 3, in part.** `.base` files parse and run: `hvk base Library.base` executes a
view's filters, formulas, sorting and grouping against the index and prints a Markdown table.
[ADR-0005](docs/adr/0005-bases-subset.md) records exactly which part of the Bases expression
language is supported and what is refused. Canvas is postponed until a vault actually contains
a `.canvas` file, and periodic notes wait on a decision rather than on work.

✅ **Phase 4.** A note can carry a base's answer inside itself, between
`<!-- vista:inicio -->` and `<!-- vista:fin -->`, so the table is readable on a phone where
nothing renders a base. `hvk views` reports what is stale and `hvk views --apply` rewrites it,
touching only the text between the markers and writing nothing at all when nothing changed —
which is what keeps a half-hourly refresh from waking sync every half hour on every device.
It is the first thing here that writes to a vault, so it goes through one audited layer
([ADR-0007](docs/adr/0007-writing-to-the-vault.md)); the declaration syntax is
[ADR-0008](docs/adr/0008-materialised-views.md). The Dataview DQL subset the phase originally
promised is postponed indefinitely: the vault it was written for has no Dataview installed.

✅ **Phase 5.** A note in a directory you nominate *is* a job:
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

Why the design is the way it is lives in [`docs/adr/`](docs/adr/), one decision per file,
and what changed and when is in [`docs/CHANGELOG.md`](docs/CHANGELOG.md). The implementation
plans themselves are working documents and are not published.

## Requirements

There are two different things you might want, and they ask for very different amounts.

**To use the `hvk` command** — index a vault, ask it questions, materialise views, run jobs:

| | |
|---|---|
| Python | **3.11 or newer**, and nothing else |
| Operating system | Linux, macOS or Windows. Tested on Linux and Windows |
| Obsidian | **Not required.** hvk reads the files; the app never has to be installed or open |
| A vault | Any folder of Markdown. A `.obsidian/` directory is only needed if you want hvk to find the vault by itself |

**To run the whole 24/7 system on a server** — sync, an agent on Telegram, scheduled jobs —
you also need Linux with systemd, Node.js 22+, Bun, tmux, git and an Obsidian Sync
subscription. That is phase 0, and it has [its own runbook](deploy/README.md) and its own
preflight check. Do not start there.

## Install

Not on PyPI yet, so both routes install from this repository. Pick one.

**A. As a command, with [uv](https://docs.astral.sh/uv/)** — recommended if you just want to
use it. `hvk` lands on your `PATH` in its own isolated environment:

```bash
uv tool install --from git+https://github.com/angelsaez/headless-vault-kit headless-vault-kit
```

`uv tool upgrade headless-vault-kit` updates it later; `uv tool uninstall headless-vault-kit`
removes it completely.

**B. From a checkout** — if you want to read the code, change it, or run the tests:

```bash
git clone https://github.com/angelsaez/headless-vault-kit
cd headless-vault-kit
python -m venv .venv
```

Then, on Linux or macOS:

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/hvk --version
```

On Windows (PowerShell):

```powershell
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\hvk --version
```

In Git Bash use forward slashes instead: `.venv/Scripts/pip`, `.venv/Scripts/hvk`.

The `[dev]` part adds pytest and nothing else. Leave it out if you are not running tests.

## Check it worked

Point it at a vault — a real one is fine, hvk only reads, and its index is written outside the
vault ([ADR-0002](docs/adr/0002-index-location.md)):

```bash
hvk --vault /path/to/vault scan
hvk --vault /path/to/vault info
hvk --vault /path/to/vault backlinks "Some Note"
```

`scan` prints how many files it indexed and how long it took; on a few hundred notes that is
well under a second. If `backlinks` names the notes you expected, everything below this line
works too.

Two things worth knowing straight away:

- **Run it inside a vault and `--vault` can be dropped.** hvk walks up from the working
  directory until it finds a `.obsidian/` folder.
- **`hvk rebuild` is always safe.** The index is derived from your files and nothing else, so
  deleting it costs time and nothing more. Nothing in `scan`, `search`, `backlinks`, `links`,
  `tags`, `tasks`, `props`, `orphans`, `base` or `info` ever writes to your vault; only
  `views --apply` and `jobs --run` do, and both say so in their names.

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
| `hvk doctor [--jobs-dir D]` | Is this installation healthy? For calling from monitoring you already have |
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

Once this is on PyPI, installing it will be `uv tool install hvk` and nothing else. That
belongs to phase 7, which the plan keeps behind weeks of real stability rather than a
feeling of readiness.

## Roadmap

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Server baseline: Headless sync + Claude Code/Telegram + git, reboot-proof | **Done**, running on a server |
| 1 | Vault inventory: which plugins and real-world usages need covering | **Done** |
| 2 | Tier-0 indexer + `hvk` CLI | **Done** |
| 3 | Bases, Canvas, templates and periodic notes | Bases **done**; the rest postponed |
| 4 | Materialized views (Dataview DQL postponed) | **Done** |
| 5 | Order-notes: the vault as a job queue | **Done** (Sync and Telegram wait on phase 0) |
| 6 | Security, healthchecks, rehearsed backups | **In progress** |
| 7 | MCP server + community parsers + packaging | Future |

## What do I need to use it?

It depends on the layer — the project is usable in independent pieces:

| Layer | What it does | What it requires |
|---|---|---|
| Index + CLI (Phases 2–4) | Search, backlinks, tasks, properties, Bases queries, materialized views | **Just your files** (any Obsidian vault or Markdown folder) + the runtime. No AI, no app, no subscriptions. Zero tokens |
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
src/hvk/      The package: indexer, parsers, the write layer, and the hvk CLI
tests/        pytest, run against the synthetic vaults below
test-vaults/  Synthetic vaults, including the awkward cases: Unicode, odd YAML,
              duplicate headings, ambiguous and broken links
deploy/       systemd user units, cron and the runbook for putting it on a server
tools/        Development utilities, not part of the product (vault mirror, testbed)
skills/       Claude Code skills, so an agent knows which command to reach for
docs/adr/     Architecture decision records — the "why" behind every design choice
docs/         CHANGELOG.md, the repository journal
```

Written in Python 3.11+ ([ADR-0001](docs/adr/0001-indexer-language.md)), with `ruamel.yaml`
and `watchdog` as its only runtime dependencies.

## Contributing

Not yet: the early phases are personal and the system has not run on a server for a day.
Phase 7 will open the parser interface and the documentation so the community can contribute
plugin adapters. Feedback on the plan is welcome anytime.

If you are reading the code, the tests are the map:

```bash
.venv/bin/pytest              # the suite, a few seconds
.venv/bin/pytest -m slow      # the plan's numeric criteria, against a generated 10k-note vault
```

Every push and pull request runs the suite on Python 3.11 and 3.13, installs the built package
and checks it answers against a vault it has never seen, and parses every shell script
([the workflow](.github/workflows/ci.yml)). Linux only, by the plan's own decision: the server
is Linux, and a three-OS matrix was one of the costs v2 dropped.

The deployment is not exercised there — it needs a systemd user instance and a machine to throw
away. It lives in [`tools/testbed/`](tools/testbed/), a disposable Debian container, and that is
where to run `deploy/selftest.sh` before trusting a change to `deploy/`.

## Name and command

The repository and tool are **headless-vault-kit** (descriptive, self-explanatory); the
CLI binary is **`hvk`** (`hvk search`, `hvk backlinks`, `hvk base "..."`) — long clear repo
name, short comfortable command.

## License

**MIT.** Do what you like with it, including commercially; keep the copyright notice, and
there is no warranty. The full text is in [LICENSE](LICENSE).

Both runtime dependencies are permissive too — `ruamel.yaml` is MIT and `watchdog` is
Apache-2.0 — so nothing here constrains what you build on top.
