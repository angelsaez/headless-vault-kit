# 0011 — A profile has to be a limit

**Status:** accepted
**Date:** 2026-08-24
**Phase:** 6

## Context

ADR-0009 made every order-note name a permission profile, and closed by admitting what that
does not buy:

> The runner cannot verify that a profile actually restricts anything. […] A profile called
> `read-only` that grants everything would be honoured.

The first real deployment turned that from a footnote into something concrete. The machine's
own agent runs with `--dangerously-skip-permissions` — a reasonable choice for an interactive
session the owner is talking to — and the obvious way to write a profile is to copy the
invocation that already works. Copy that one, and every note dropped into the jobs directory
runs an agent with no limits at all, under a file named `read-only.json`.

The same shape appears in the other direction. ADR-0009 says the profiles directory must live
outside the vault, because a profile that syncs can be edited from a phone. It says it in
prose, and nothing checked it.

Both are the same mistake: a guarantee the documentation asserts and the code does not.

## Alternatives

- **Leave it to the documentation.** It is already there and it is already not enough: the
  first person to configure this was going to copy a working command line, and the docs would
  have been read afterwards.
- **Verify that the settings a profile points at really restrict.** The honest version of this
  needs the runner to parse another tool's configuration format and reason about its
  precedence rules — exactly the coupling ADR-0009 avoided, and a rule it would get wrong.
- **Refuse the specific shapes that are unambiguously not limits.** Chosen.

## Decision

Two refusals, both at load time, both fatal to the job rather than to the run.

**A `command` carrying a known bypass argument is refused.** The list is short and lives in
one place: `--dangerously-skip-permissions`, `--dangerously-bypass-approvals-and-sandbox`,
anything containing `bypasspermissions`, `--yolo`. A profile with one of those is not a limit;
it is the absence of a limit wearing the name of one, and the entire point of making a note
choose a profile is that it cannot choose "no limits".

**A profiles directory inside the vault is refused.** Anything that can write a note can then
rewrite what an agent may do, and Sync carries the change from any device.

### About knowing those flags

This is a deliberate exception to ADR-0009's rule that the runner learns no agent's flags, and
it is worth being precise about its size. Nothing here builds a command line, chooses an
agent, or changes what is executed: it is a refusal on a string. An agent whose bypass flag is
not on the list is simply not protected, and adding one is a line of code. That is a
safeguard, not an integration.

## Consequences

**A careless profile can still grant everything.** A `command` that runs an agent with no
settings file at all, or with a permissive one, passes both checks. What is now impossible is
the specific, likely mistake of copying an invocation that names a bypass flag. The rest of
ADR-0009's consequence stands, and the shipped examples in `deploy/profiles/` remain the
recommendation rather than an enforcement.

**Someone will hit this legitimately.** A person who genuinely wants an unrestricted job —
testing, a trusted one-off — is refused, with a message that says why, and their recourse is
to run the agent by hand rather than through a queue that anything can write into. That is the
right trade for a directory a phone can drop files in.

**The list will go stale.** Agents rename flags. When one does, this catches nothing and says
nothing, which is the failure mode to remember: absence of a refusal is not evidence of a
limit.
