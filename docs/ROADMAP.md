# Roadmap and status

What is built, what is not, and what was deliberately dropped. The README says what the tool
does and how to use it; this is where "how far along is it" lives.

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Server baseline: Headless sync + an agent on Telegram + git, reboot-proof | **Done** |
| 1 | Vault inventory: which plugins and real-world usages need covering | **Done** |
| 2 | Tier-0 indexer + `hvk` CLI | **Done** |
| 3 | Obsidian's own formats: Bases, Canvas, templates | Bases **done**; the rest postponed, see below |
| 4 | Materialized views | **Done** |
| 5 | Order-notes: the vault as a job queue | **Done** |
| 6 | Security, healthchecks, rehearsed backups | **In progress** |
| 7 | MCP server, community parser interface, packaging | Not started |

## Maturity

It runs on one server, and has done since 2026-08-24: an ARM64 VPS that already hosted its own
Obsidian Headless and agent, where `hvk` indexes a 274-note vault and keeps it current as sync
delivers changes. That is days of production on one machine, by one person. Nothing here has
been through a second installation, and phase 7 — publishing it properly — deliberately waits
for weeks of stability rather than for a feeling of readiness.

Restoring that vault from a backup has been rehearsed once, on that machine, on 2026-08-24:
the archive went back into a directory beside the live vault and indexed to the same numbers,
file for file. What has not been rehearsed is a restore from off the machine, because no
off-site destination is configured yet — see [deploy/RESTORE.md](../deploy/RESTORE.md).

## Measured, on a generated 10,000-note vault

The numbers the plan set as its exit criteria for phase 2:

| Criterion | Target | Linux | Windows |
|---|---|---|---|
| Full rebuild | < 60 s | **4.9 s** | 8.2 s |
| Incremental update | < 5 s | **0.34 s**, or 0.19 s targeted | 0.76 s / 0.31 s |
| Index queries | < 100 ms | **0.5 – 35 ms** | 0.8 – 80 ms |

Run them yourself with `pytest -m slow`.

## Postponed, and what would bring it back

- **Canvas** (`.canvas`). JSON Canvas is a published, stable specification, so waiting costs
  nothing. It gets built when a vault actually contains one.
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
