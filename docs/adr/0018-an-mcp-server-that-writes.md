# 0018 — An MCP server that writes

**Status:** accepted
**Date:** 2026-08-25
**Phase:** 7

## Context

The exit criterion for this phase is that a second agent — one that is not Claude Code — can
query the vault. MCP is how that happens: it is the protocol the clients agree on, and without
one, "an agent" means "an agent with a shell and this CLI installed", which is a smaller claim
than the plan makes.

The decision that shapes everything else was taken on 2026-08-24: **the server exposes writing
too**, not only queries. That is not the cautious choice and it was made deliberately — a vault
you can only read is half the system, and the order-note runner and the materialised views have
been writing to a live vault since phase 4. What it means here is that this ADR is mostly not
about MCP. It is about what stands between a JSON-RPC message and somebody's notes.

Five things already exist that this must not go around, and each of them exists because of a
specific failure:

- **ADR-0007**, the write layer: atomic replacement, refusal when the file changed underneath,
  line endings and frontmatter and file mode preserved, nothing outside the vault.
- **ADR-0009 and ADR-0013**, the shape of a dangerous capability: the mechanism ships, and each
  deployment declares whether *this* instance may use it. No default.
- **ADR-0012**, the guard: which folders an agent may not touch, which today is enforced in a
  Claude Code `PreToolUse` hook.
- **ADR-0014**, the record: a refusal that leaves no trace is a refusal nobody can check.

The guard is the interesting one. It lives in a hook, and **a hook is a Claude Code feature**. An
MCP client from anywhere else does not pass through it. So a server that did not apply the rules
itself would mean the protected folders were protected against exactly one client — which is not
a boundary, it is a habit.

## Alternatives

- **Read-only, and revisit.** The safe answer, and it was rejected on 2026-08-24 before this was
  written. Recorded because it is the fallback if any of the following turns out not to hold.
- **The official MCP Python SDK.** A new runtime dependency, which `CLAUDE.md` requires
  justifying. It brings a session abstraction, transports this does not use, resources and
  prompts this does not expose, and a release cadence tracking a protocol that moves. What is
  actually needed is: read a line, parse JSON, look up a name, write a line.
- **Implement JSON-RPC over stdio by hand.** Chosen. It is what the plan recommended and it came
  out at about a hundred lines. Revisit the day a capability is wanted that is not tool calls.
- **One opt-in flag per dangerous thing** — writing, views, jobs — instead of one. Rejected as
  more knobs than boundaries: see below for why `jobs` ends up gated twice anyway, by a mechanism
  that already existed.

## Decision

**Transport is stdio, and there is no network listener.** JSON-RPC messages, one per line, on
stdin and stdout. A server that writes to your notes does not open a port, and this one cannot
be reached by anything that did not start it. That also settles authentication by removing the
question: the operating system already decided who may run the process.

**Every tool that is not a query is opt-in, per instance, with no default.** `hvk mcp` is a
read-only server. `hvk mcp --write` is not. The mechanism ships in both; the deployment decides,
which is the shape ADR-0009 and ADR-0013 both landed on. Starting it wrong fails safe, because
the failure is a tool that is not in `tools/list` — a client cannot call what it was never told
about.

**`jobs_run` is gated twice, and the second gate is not new.** It launches an agent process,
which is a different class of thing from writing a note, so `--write` is necessary but not
sufficient: the jobs and profiles directories have had no default since phase 5, on purpose
(ADR-0009), and without them declared the tool refuses exactly as the CLI does. The second gate
was already there. It is worth saying out loud that it is doing work here.

**Every write goes through `hvk.write.Vault`.** Not "should" — there is no other path in the
module. Atomic replacement, a conflict when the file changed since it was read, frontmatter and
line endings and mode preserved, and a refusal for anything resolving outside the vault. A note
is untrusted input and a path that escapes the vault is the shape a prompt injection takes.

**The guard's rules are applied by the server, reusing `guard.decide()`.** Not reimplemented,
not approximated — the same function the hook calls, so a folder that is protected from the
agent is protected from any MCP client, and a change to the rules changes both. Path-naming
tools are presented to it as `Read` or `Write` accordingly, which is what makes the
outside-the-vault rule apply to writes and the protected-folder rule apply to everything,
including reads. `Vault.resolve()` refuses escapes independently; both run, because one of them
is the vault's own invariant and the other is this deployment's policy, and they fail for
different reasons.

**Every write and every refusal leaves a line in `hvk.log`** (ADR-0014). If any agent can write
to the vault, "who wrote this" has to have an answer. Refusals are recorded through the same
path the hook uses, so they read identically whichever client was turned away. As there, what is
recorded is the rule and what it matched — never the content, which can carry anything.

**The tools are the CLI's commands, and nothing new.** `search`, `backlinks`, `links`, `tags`,
`tasks`, `props`, `orphans`, `info`, `base`, `canvas`, `dql`, `note_read`; and behind `--write`,
`note_write`, `note_set_property`, `views_apply` and `jobs_run`. Each is a call into something
that already exists and is already tested; this server is a protocol, not a second
implementation. `dql` is there because it landed between the plan being written and this being
built.

**Tool failures are results, not protocol errors.** A vault that has no such note is an answer
to a question, and returning `isError` with a sentence the model can read is more useful than a
JSON-RPC error code, which most clients surface as a crash. Protocol errors stay for what they
are for: a method that does not exist, a message that is not JSON.

## Consequences

**The attack surface is now the union of every tool, and it is bigger than the CLI's.** The CLI
is run by whoever has the shell; this can be driven by a model reading a note that a stranger
wrote. That is the trade accepted on 2026-08-24, and the five constraints above are the whole of
what is offered in exchange. If one of them is ever bypassed for convenience, this ADR is the
thing that was traded away.

**A hand-written protocol will drift.** MCP is versioned and moving; this speaks one revision and
answers `initialize` with the version it knows. A client that requires something newer gets a
version it did not ask for and may refuse to proceed — a visible failure, which is the right
direction, but it is a maintenance debt with no test that can see the future.

**Nothing here bounds *what* a client asks for.** There is no rate limit, no quota, no
per-tool allowlist within `--write`. A confused agent can rewrite a hundred notes as fast as the
disk allows, and every one of those writes will be correct, atomic, and recorded. The recovery
story is the one the project already has — git in the vault, and the rehearsed restore of
ADR-0013 — not anything in this module.

**`note_read` can read any note in the vault**, subject to the protected folders. That is the
same reach the query tools have collectively, and less than a client with a filesystem tool of
its own; it is listed here because it is the tool most likely to be regretted and the one whose
absence would make `note_write` unusable.

**The guard's protected folders have no default here either**, exactly as in ADR-0012: unset
means the rule does not apply. A server started without `--protect` and without `HVK_PROTECTED`
protects nothing by that rule, and that is the documented behaviour rather than an oversight —
which folders are private is nobody's business but the vault owner's.

**This is the first thing in the project that speaks a protocol somebody else defines.** Every
other format here — Markdown, YAML, JSON Canvas, `.base` — is read from files that already
exist, so being wrong shows up as a wrong answer about a file. Being wrong about MCP shows up as
a client that will not talk to it, and the only test for that is a client.
