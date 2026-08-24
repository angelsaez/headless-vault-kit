# Permission profiles

Every order-note names one of these, and a job that names none is refused
([ADR-0009](../../docs/adr/0009-order-notes.md)). The note supplies only a *name*; what that
name is allowed to do is decided here, by whoever owns the server.

**This directory belongs outside the vault.** A profile that syncs is a permission grant a
phone could edit. Put the real ones somewhere like `~/hvk-profiles/` and point
`HVK_JOBS_PROFILES` at it — these files are examples to copy, not the live configuration.

## The two files a profile needs

A `<name>.json` read by `hvk jobs`, which says what to run:

```json
{ "command": ["claude", "-p", "--settings", "/home/you/hvk-profiles/read-only.settings.json"],
  "timeout": 900 }
```

and the settings file that command points at, which says what the agent may do. They are
separate because `hvk` never learns a single Claude Code flag: it executes an argument list.
Swap the agent and only these files change.

## Why read-only is usually enough

**The runner writes the output, not the agent.** Whatever the agent prints on stdout is what
lands in the note's declared `output:` path, written through the audited layer of ADR-0007.
So the ordinary job — read some notes, produce a report — needs an agent that can read and
nothing else.

That is what `read-only` grants: `Read`, `Glob` and `Grep`, and no `Bash`, no `Write`, no
`Edit`, no network. Anything not allowed is refused rather than asked, because `claude -p` is
not interactive: there is nobody to answer a prompt.

**Do not put `--dangerously-skip-permissions` in a profile.** It is exactly the flag these
files exist to avoid, and a job runs because a note said so — and a note can arrive from a web
capture or a shared folder.

## The gap this does not close

`hvk` checks that a profile exists and is well-formed, **not that it restricts anything**. A
profile called `read-only` that granted everything would be honoured. Making that guarantee
real is phase 6's work; until then, these files are the guarantee.
