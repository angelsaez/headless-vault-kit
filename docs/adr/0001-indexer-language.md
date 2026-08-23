# 0001 — Implementation language for the indexer and CLI

**Status:** accepted
**Date:** 2026-08-21
**Phase:** 2

## Context

The v2 plan (§5, phase 2) leaves the choice open between Python (`watchdog` + `sqlite3`, no
build step) and TypeScript (`chokidar` + `better-sqlite3`, a better fit for the MCP server in
phase 7), and the working rules forbid starting the indexer until this ADR is closed.

The choice is not purely technical. This project will be open source, and its audience splits
into two groups with opposite needs. **Most users do not write code**: for them the only thing
that matters is whether the install command works on the first try and whether the error, when
it comes, is readable. **A minority does write code** and will customise the tool. Optimising
for one group hurts the other, so the decision is made by measuring both axes rather than by
arguing about them.

Measurements taken on 2026-08-21, on Windows 11 and on Ubuntu 26.04 under WSL2 (the latter
standing in for the target VPS):

| | Python | Node / TypeScript |
|---|---|---|
| Windows 11 | 3.14.6 · sqlite 3.50.4 · **FTS5 available** | v24.18.0 · `node:sqlite` 3.53.1 · **FTS5 available** |
| Ubuntu 26.04 | 3.14.4 · sqlite 3.46.1 · **FTS5 available** | Node **not installed** |
| CLI start-up, Linux | **29 ms** | ~46 ms |
| CLI start-up, Windows | 147 ms | 46 ms |
| `pip install --user` on Ubuntu | **blocked by PEP 668** (`EXTERNALLY-MANAGED` marker present) | n/a |
| `pipx` / `uv` preinstalled | neither | n/a |

Two findings invalidate assumptions the plan was written under:

1. **`node:sqlite` is built into Node 24 and ships FTS5.** That removes `better-sqlite3` and
   with it the native-module rebuild on every major Node release, which was the main cost the
   plan attributed to TypeScript. Node 24 also runs TypeScript without a build step. The
   TypeScript option is considerably better today than the plan assumed.
2. **PEP 668 is active on current distributions.** Having Python installed no longer implies
   being able to install a Python tool: `pip install` fails with a message that confuses even
   experienced developers, and neither `pipx` nor `uv` ships by default.

## Alternatives

### TypeScript on Node ≥ 22

In favour: Obsidian parses frontmatter with `js-yaml` (YAML 1.2), so using that same library
buys **exact parity with the app for free** at the most delicate point of tier 0. Obsidian
plugin authors are, without exception, TypeScript developers — the whole ecosystem is — so
they could contribute to the core and not just to adapters, and some of their parsing logic
could be lifted as-is. Static types catch what an agent-driven refactor breaks. And
`npm install -g` is the canonical way to install a CLI, with no equivalent of the PEP 668
wall.

Against: the runtime ships with no operating system. Worse, the LTS releases running on most
VPS today (Debian 12, Ubuntu 24.04) serve Node 18 through `apt`, below the Node 22 minimum
`node:sqlite` requires — the install appears to succeed and then fails at run time. The
correct path means adding a third-party repository with `sudo`, or `nvm` with a shell
restart. And anyone wanting to customise the tool still has `npm install`, `node_modules` and
a lockfile standing between them and their change.

### Go or Rust

Either would settle the installation question outright with a single binary and no runtime,
but they wreck the customisation axis: nobody in the Obsidian ecosystem writes either, which
contradicts the stated goal of phase 7 (outside contributors supplying adapters). Rejected,
but they were considered.

## Decision

**Python**, 3.11 or newer, for both the indexer and the `hvk` CLI, with `uv` as the documented
installation path.

The reason in one sentence: under the criterion "most users do not program, a minority
customises", the two heaviest axes fall on Python's side — installation in two commands with
no `sudo` and no third-party repository, and editing the source without a build step — while
TypeScript's strongest argument, attracting plugin authors, is better answered by an
architectural decision than by the choice of language.

Specifics:

- **Installation:** `curl -LsSf https://astral.sh/uv/install.sh | sh`, then
  `uv tool install hvk`. Two commands, no `sudo`, no repositories added, and `uv` installs and
  pins the Python version itself, so a system upgrade cannot break the tool. `pip install hvk`
  is documented only as an alternative **inside a virtual environment**, never as the main
  path.
- **Runtime dependencies:** `ruamel.yaml` (YAML 1.2) and, once incremental indexing lands,
  `watchdog`. Nothing else. `sqlite3` and FTS5 come from the standard library, verified on all
  three operating systems. The CLI uses `argparse` and formats tables by hand: no `click`, no
  `typer`, no `rich` (a standing rule of the project: no heavy frameworks).
- **Minimum version 3.11**, which is what Debian 12 ships. CI runs against 3.11 and 3.14.
- **`pytest`** as the only development dependency.

## Consequences

**The YAML cost is accepted.** `PyYAML` implements YAML 1.1 and differs from the app on cases
that occur in real vaults: `status: no` is a boolean under 1.1 and a string under 1.2, same for
`yes`/`on`/`off`, and leading zeros are read as octal. That is why the dependency is
`ruamel.yaml`, which is 1.2 and closes most of the gap. What remains is handled by a
**frontmatter conformance suite** built from edge cases in `test-vaults/` — which has to be
written either way: not even `js-yaml` would let us claim parity without fixtures, because
Obsidian layers its own property typing on top. Whatever divergence survives gets documented,
not papered over (plan, §7).

**Phase 7 opens adapters to any language.** So that plugin authors are not shut out, the parser
interface will not be in-process modules but **subprocesses speaking JSON over stdio** (input:
a batch of files and metadata; output: rows for the index), with long-lived processes and
batching, LSP-style, to avoid paying a `spawn` per file. An adapter can then be written in
TypeScript, Python or anything else. That gets its own ADR when phase 7 arrives; what is
recorded here is that choosing Python must **not** become an excuse to require Python from
contributors.

**Start-up cost is uneven.** 29 ms on Linux — better than Node — but 147 ms on Windows. The
deployment target is Linux, where this is a non-issue, but anyone running `hvk` on a Windows
laptop will feel it. If it ever becomes a real problem, the answer is a long-lived daemon the
CLI talks to over a socket, not a change of language.

**The planned directory layout changes.** The original tree separated `indexer/` and
`cli/` at the root; that was drawn before a language was chosen and is not packageable in
Python, which needs a single importable package. It becomes `src/hvk/` with internal modules,
and both READMEs are updated in this same commit.

**Node stops being a project dependency**, even though it will still be present on the VPS
because Claude Code runs on it. The two are independent: `hvk` works without an agent, and the
agent works without `hvk`.
