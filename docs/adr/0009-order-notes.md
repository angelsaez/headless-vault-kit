# 0009 — Order-notes: what a job is, and what it is allowed to reach

**Status:** accepted
**Date:** 2026-08-23
**Phase:** 5

## Context

The v1 plan had a SQLite queue with leasing, heartbeats and a dead-letter table. The v2 plan
replaced all of it with one observation: **the vault is already the queue**. A note is the
job, its frontmatter is the state, and Sync carries both to every device — so the progress of
a job is visible on a phone without anything being built to show it.

That is a good trade, and it moves the hard parts somewhere else:

* **A queue with no transactions.** Two runners, or one runner restarted mid-flight, must not
  run the same job twice. There is no database row to lock, only a file that Sync may rewrite
  at any moment.
* **This is the first thing here that executes something.** Everything before it read files,
  and phase 4 wrote them. A runner launches an agent with access to the vault *because a note
  said so* — and a note can arrive from anywhere: a web capture, something forwarded to an
  inbox, a shared folder. `CLAUDE.md` already says vault content is data and never
  instructions; this is where that stops being a principle and becomes an attack surface.
* **The plan is written in one person's vocabulary.** `tipo: orden`, `estado: pendiente`, a
  folder called `Jobs/`. None of that can become a constant in a repository meant to be
  published, and a "sensible default" is the same mistake wearing a hat.

## Alternatives

- **A script in `runner/`, as the plan draws it.** It would duplicate vault discovery, the
  write layer, path containment, `--json` output and the test harness. Rejected: a subcommand
  gets all of that for free, and the plan's structure section is a sketch, not a requirement.
- **Leasing with a timeout** (claim, renew, expire). Correct for a real queue, and here it
  would mean a job that crashed the runner gets retried automatically — which is exactly what
  you do *not* want when the job spends money and writes to a vault.
- **A lock file, or an OS lock.** Sync does not honour locks, and a lock file in the vault
  would itself sync. It would look like safety without being any.
- **Claim by conditional write.** Chosen.

## Decision

`hvk jobs --dir PATH --profiles PATH [--run]`. No index is opened: a job is a file and its
state is its frontmatter, so this works on a vault whose index is stale or absent.

### Nothing has a default, and nothing runs unless asked

Neither the jobs directory nor the profiles directory has a default value. Both must be given
as `--dir` / `--profiles` or `HVK_JOBS_DIR` / `HVK_JOBS_PROFILES`, and without them the
command refuses to do anything.

This is the one place where "helpful default" is the wrong instinct. A runner that starts
executing an agent because a folder happened to be called `Jobs/` is precisely the failure
this whole ADR exists to prevent — and the name would be somebody else's word anyway. Nothing
in this repository is named after anybody's vault.

`--run` is likewise opt-in: without it the command reports what it would do and **touches
nothing**. A dry run that claimed jobs would strand every one of them in `running` with no
runner behind it.

### Exactly once is a conditional write, not a lock

Claiming a job means writing `status: running` through the layer of ADR-0007, which states the
digest the note had when it was read. If anything changed it in between — another runner, Sync
delivering an edit from a phone — the write is refused and this runner skips the job.

That is the entire mechanism. It needs no new state, no lease table and no clock, and it is
the same property that makes phase 4 idempotent, used for the opposite purpose.

Its honest limit: a runner killed **after** claiming leaves the job in `running` for ever.
That is deliberate. The alternative — expiring a claim after N minutes — turns a crash into an
automatic re-run of a job that may already have half-happened. Stuck and visible beats
repeated and invisible, and the note says exactly when it was claimed.

### A note chooses limits by name; it never supplies them

Every job **must** name a permission profile, and a job that does not is refused before
anything else happens. There is no fallback to "run with whatever the session has".

A profile is a JSON file in the profiles directory, written by whoever owns the server:

```json
{ "command": ["claude", "-p", "--settings", "…"], "timeout": 900 }
```

The note supplies a *name*, which is validated against a pattern that admits no separators and
no traversal, and looked up in a directory outside its reach. So the untrusted side of the
system chooses among options the trusted side defined, and can express nothing else. The
command is executed directly with an argument list — there is no shell anywhere in this path
(`CLAUDE.md`).

Putting the command in the profile rather than in the code is also what keeps this agnostic:
the runner never learns a single Claude Code flag, so it works with another agent, and a
change in someone's CLI is a configuration edit rather than a release.

### Where the output may go

A job declares its output, and two destinations are refused: **outside the vault** (ADR-0007
already refuses it; the message names it) and **inside the jobs directory**. The second is the
anti-loop rule made structural — a runner whose results land in its own inbox feeds itself
work for ever. Nothing else is watched, so nothing else can trigger a run.

### The note keeps its own language

Keys and states are accepted in English and Spanish (`status`/`estado`,
`pending`/`pendiente`, …) and the runner **writes back in the spelling the note already
used**, including for keys it adds itself. A note that says `estado:` gets `iniciada:`, not
`started:`. Same bargain as ADR-0008: the vocabulary lives in somebody's notes, not in this
codebase, and leaving a second language scattered through a note is a change its author did
not ask for.

### Failure is legible, and it is reported once

A failed job records the reason in its own frontmatter and appends one line to its body, so
the trail lives where the job does. The command exits non-zero when **this run** failed
something — not when the directory still contains a job that failed yesterday. An alarm that
fires every minute for ever is an alarm nobody reads.

## Consequences

**A crashed runner leaves a job stuck, and a person has to unstick it.** Named above as the
price of never re-running. If it turns out to happen often, the fix is a command that reports
jobs claimed long ago, not an automatic expiry.

**Profiles are trust.** Anyone who can write into the profiles directory can run anything, so
that directory must not be inside the vault — it would sync, and a phone could then edit it.
Nothing enforces that yet beyond documentation, which is a gap worth naming rather than
hiding.

**The runner cannot verify that a profile actually restricts anything.** It checks that a
profile exists and is well-formed, not that its `command` is careful. A profile called
`read-only` that grants everything would be honoured. Making permissions real is phase 6's
work; this ADR only guarantees that a job cannot run without one being chosen deliberately.

**`hvk jobs` executes arbitrary configured programs.** That is the point, and it means the
security of this feature is the security of the profiles directory and of whoever can drop
files into the jobs directory. Both are now explicit surfaces with names, rather than implicit
ones.

**Two exit criteria of phase 5 cannot be closed on a laptop.** "Created on a phone" needs Sync
and "notifies over Telegram" needs the bot — both belong to phase 0 on the server. Everything
else, including exactly-once under a killed runner, is testable in the disposable container.
