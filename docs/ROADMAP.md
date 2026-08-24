# Roadmap and status

What is built, what is not, and what was deliberately dropped. The README says what the tool
does and how to use it; this is where "how far along is it" lives.

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Server baseline: Headless sync + an agent on Telegram + git, reboot-proof | **Done** |
| 1 | Vault inventory: which plugins and real-world usages need covering | **Done** |
| 2 | Tier-0 indexer + `hvk` CLI | **Done** |
| 3 | Obsidian's own formats, plus a Dataview subset | Bases, Canvas and DQL **done**; templates dropped, see below |
| 4 | Materialized views | **Done** |
| 5 | Order-notes: the vault as a job queue | **Done** |
| 6 | Security, healthchecks, rehearsed backups | **Done** |
| 7 | MCP server, community parser interface, packaging | Built, and **entered early** — see below |

## Phase 7 was entered before its condition was met

The plan set one entry condition for phase 7 and it was not a formality: **weeks of real
stability**, not days. It was built anyway, on 2026-08-25, with two days of production behind
it. That is a decision the owner made with the condition in front of him, and it is recorded
here rather than quietly satisfied.

What that costs is worth naming. The condition existed because publishing is the point at which
mistakes stop being yours alone, and two days is not enough time for the failure modes of one
installation to show up — let alone the ones that only appear on somebody else's machine. So:

- **Nothing is published.** No PyPI release, and `uv tool install --from git+...` remains the
  documented route. That part of the phase was always "leave it ready", and it still is.
- **The MCP server has never been driven by a client that is not a test.** Its protocol is
  exercised by a fake client in `tests/test_mcp.py`, which proves the framing and the boundary
  and proves nothing at all about interoperability.
- **The parser interface has one adapter, written here.** The plan's original exit criterion
  asked for one written by somebody else; the owner retired that on 2026-08-24 as a criterion
  measuring adoption rather than design. Kanban is what stands in its place.

## Maturity

It runs on one server, and has done since 2026-08-24: an ARM64 VPS that already hosted its own
Obsidian Headless and agent, where `hvk` indexes a vault of some 280 notes and keeps it current
as sync delivers changes. That is days of production on one machine, by one person. **Nothing
here has been through a second installation**, which is the single most useful thing to know
about it, and the reason the release half of phase 7 is still deliberately undone.

The whole loop has been exercised there rather than assumed: a note written on another device
arrives through sync and is indexed in about a second; the agent answers "what links to this"
from the index rather than by reading files; an order-note created on a device is claimed and
executed exactly once, stamping its own status where the author can see it; and the machine has
been rebooted, with every service, the agent's session and the index coming back on their own.

What phase 6 does not do is bound the interactive session's own permissions: those live in the
agent's settings file, which belongs to whoever runs the agent. What this project contributes
there is the `PreToolUse` hook — deletions, protected folders and writes outside the vault,
refused and recorded. Since phase 7 the MCP server applies those same rules itself, by calling
the same function, because a hook is a Claude Code feature and a client from anywhere else never
passes through one ([ADR-0018](adr/0018-an-mcp-server-that-writes.md)).

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

## What phase 7 added

- **`hvk mcp`** — the vault as tools for any MCP client, over stdio, with no network listener.
  Read-only unless the instance was started with `--write`, in which case the writing tools
  exist and every one of their writes goes through the layer of
  [ADR-0007](adr/0007-writing-to-the-vault.md) and leaves a line in `hvk.log`.
  [ADR-0018](adr/0018-an-mcp-server-that-writes.md) is mostly about what stands in front of it.
- **A parser interface**, extracted from the two parsers that already existed rather than
  designed for an imagined third, with **Obsidian Kanban** as the worked adapter: a board's
  cards now carry the list they sit in and the date Kanban writes in its own syntax, so
  `hvk tasks --due-before` answers a format it was blind to. Contract, registration point and
  how to write one: [CONTRIBUTING.md](../CONTRIBUTING.md#writing-a-parser-adapter) and
  [ADR-0017](adr/0017-a-parser-interface-extracted-from-two.md).
- **CONTRIBUTING.md**, and the licensing question settled before it could matter: contributions
  are MIT, inbound as outbound, and there is no CLA. That has to be decided before the first
  external pull request, not after.

## Postponed, and what would bring it back

Canvas used to be on this list, with the condition "when a vault actually contains one". One
did, so it was built ([ADR-0015](adr/0015-what-a-whiteboard-puts-in-the-index.md)): reading, not
writing, and edges stay out of the index on purpose.

So did the Dataview subset, on a criterion that changed rather than evidence that did: not "does
anyone here use it" but "is this a format the community writes"
([ADR-0016](adr/0016-a-subset-of-a-query-language.md)). `LIST` and `TABLE` with `FROM`, `WHERE`,
`SORT` and `LIMIT`; everything else refuses with its own name in the message. **DataviewJS
remains permanently out of scope** — its blocks are not even read.

- **DataviewJS**, and executing any plugin code. Permanently out of scope: this project
  replicates file formats, never a runtime.
- **Templates and periodic notes.** Dropped: creating tomorrow's daily note is a desktop
  feature, done in the app where you are already typing. It comes back if someone wants
  periodic notes created *without* the app in front of them.
- **Materialising a `dataview` block into a note.** `hvk views` does it for Bases; `hvk dql
  --note` reads the blocks and prints the answers. Nothing has asked for the writing half.
- **Discovering parser adapters from installed packages.** The interface supports an adapter
  living in somebody else's package; what it will not do is sweep the machine for entry points
  and run what it finds. Making `hvk scan` execute whatever is installed is a decision about
  trust, and it comes back the day publishing forces the question.
- **Publishing to PyPI.** Deliberately not done. The phase's own entry condition was weeks of
  stability and it has had days, so what is ready is the packaging, not the release.

## Where the rest of the reasoning is

One decision per file in [`docs/adr/`](adr/), and what changed when in
[`CHANGELOG.md`](CHANGELOG.md).
