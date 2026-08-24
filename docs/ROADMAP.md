# Roadmap and status

What is built, what is not, and what was deliberately dropped. The README says what the tool
does and how to use it; this is where "how far along is it" lives.

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Server baseline: Headless sync + an agent on Telegram + git, reboot-proof | **Done** |
| 1 | Vault inventory: which plugins and real-world usages need covering | **Done** |
| 2 | Tier-0 indexer + `hvk` CLI | **Done** |
| 3 | Obsidian's own formats: Bases, Canvas, templates | Bases and Canvas **done**; templates blocked on a decision, see below |
| 4 | Materialized views | **Done** |
| 5 | Order-notes: the vault as a job queue | **Done** |
| 6 | Security, healthchecks, rehearsed backups | **Done** |
| 7 | MCP server, community parser interface, packaging | Not started |

## Maturity

It runs on one server, and has done since 2026-08-24: an ARM64 VPS that already hosted its own
Obsidian Headless and agent, where `hvk` indexes a vault of some 280 notes and keeps it current
as sync delivers changes. That is days of production on one machine, by one person. Nothing
here has been through a second installation, and phase 7 — publishing it properly —
deliberately waits for weeks of stability rather than for a feeling of readiness.

The whole loop has been exercised there rather than assumed: a note written on another device
arrives through sync and is indexed in about a second; the agent answers "what links to this"
from the index rather than by reading files; an order-note created on a device is claimed and
executed exactly once, stamping its own status where the author can see it; and the machine has
been rebooted, with every service, the agent's session and the index coming back on their own.

What phase 6 does not do is bound the interactive session's own permissions: those live in the
agent's settings file, which belongs to whoever runs the agent. What this project contributes
there is the `PreToolUse` hook — deletions, protected folders and writes outside the vault,
refused and recorded.

Restoring that vault from a backup has been rehearsed twice on that machine, both on
2026-08-24: once from the archive beside it, and once **from the off-site copy**, fetched back
to a clean directory as if the server were gone. Both times it came back file for file and indexed to the
same numbers as the live vault — see [deploy/RESTORE.md](../deploy/RESTORE.md).

## Measured, on a generated 10,000-note vault

The numbers the plan set as its exit criteria for phase 2:

| Criterion | Target | Linux | Windows |
|---|---|---|---|
| Full rebuild | < 60 s | **4.9 s** | 8.2 s |
| Incremental update | < 5 s | **0.34 s**, or 0.19 s targeted | 0.76 s / 0.31 s |
| Index queries | < 100 ms | **0.5 – 35 ms** | 0.8 – 80 ms |

Run them yourself with `pytest -m slow`.

## Postponed, and what would bring it back

Canvas used to be on this list, with the condition "when a vault actually contains one". One
did, so it was built ([ADR-0015](adr/0015-what-a-whiteboard-puts-in-the-index.md)): reading, not
writing, and edges stay out of the index on purpose.

- **A Dataview (DQL) subset.** Planned, then dropped: the vault this was written for has no
  Dataview installed, and its two `dataview` blocks are dead code that nothing renders. The
  Bases expression engine exists, so starting later is cheaper than starting now. It comes
  back if a vault with real DQL use appears.
- **DataviewJS**, and executing any plugin code. Permanently out of scope: this project
  replicates file formats, never a runtime.
- **Templates and periodic notes.** Blocked on a decision rather than on work — which folder,
  which filename format, which template.

## Where the rest of the reasoning is

One decision per file in [`docs/adr/`](adr/), and what changed when in
[`CHANGELOG.md`](CHANGELOG.md).
