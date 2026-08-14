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

🚧 **Planning phase.** No code yet. The full plan, with phases and exit criteria, lives in
[`.plans/Plan-v2-headless-vault-kit.md`](.plans/Plan-v2-headless-vault-kit.md) (Spanish).

## Roadmap

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Server baseline: Headless sync + Claude Code/Telegram + git, reboot-proof | Pending |
| 1 | Vault inventory: which plugins and real-world usages need covering | Pending |
| 2 | Tier-0 indexer + `hvk` CLI | Pending |
| 3 | Bases, Canvas, templates and periodic notes | Pending |
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
CLAUDE.md   Guide for the agent developing and operating this repo
README.md   This file (English) · README.es.md (Spanish)
```

Remaining folders (`indexer/`, `cli/`, `runner/`, `deploy/`, `docs/adr/`, `test-vaults/`)
will appear as their phases are implemented.

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
