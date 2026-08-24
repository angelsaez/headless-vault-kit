# 0014 — Blocked, and written down

**Status:** accepted
**Date:** 2026-08-24
**Phase:** 6

## Context

The phase asks for one thing in one sentence: *an attempt to write outside the permitted paths
is blocked and is recorded.* Neither half was true.

ADR-0012 built the hook and shipped it with the boundary missing. `guard.decide()` took a
`vault` argument and never read it: what it refuses is deletion, and folders the owner names
with `--protect`. Nothing stopped a `Write` to `~/.ssh/authorized_keys`, to a systemd unit, or
to the agent's own `settings.json` — which is the interesting one, because the vault is
untrusted input by this project's own principle, and a note can ask an agent to write a file.

And nothing was recorded anywhere. The refusal went back to the agent, was shown in that
session, and was gone. ADR-0002 reserved `hvk.log` in the index directory when the layout was
designed; four phases later nothing had ever written a line to it.

## Alternatives

- **Refuse reads outside the vault too.** Symmetrical, and wrong: an agent reading a man page
  or a config file it was asked about is ordinary work, and reading `/etc/hostname` is not how
  a vault agent damages a machine. The cost of that refusal is a session that cannot function;
  the benefit is close to nothing.
- **Judge `Bash` on where it might write.** A redirection cannot be found reliably in a command
  line — `>`, `tee`, `sed -i`, a heredoc, a script it writes and then runs. Catching the easy
  spellings would be the protection-that-only-looks-like-protection ADR-0012 already refused
  when it declined `deny: ["Bash(rm *)"]`.
- **Record every call, not just refusals.** A line per tool call is a log nobody reads and a
  disk nobody watches.
- **Record the command line.** More detail, and a log that then has to be guarded itself: a
  command can carry a token, a password, a signed URL.
- **Send it to journald or syslog.** Assumes systemd, or a daemon, on a machine this project
  deliberately leaves alone (ADR-0006). The index directory is already the answer to "where
  does hvk keep things".

## Decision

**A write whose path lands outside the vault is refused.** It applies to the tools that name a
path they will write — `Write`, `Edit`, `NotebookEdit` — and to nothing else. Paths are
*resolved* before being compared, so `../../.ssh/authorized_keys` is judged where it lands
rather than how it reads, and a relative path is resolved against the vault because that is the
agent's working directory. With no vault known, the rule does not apply.

**Every call leaves a heartbeat; every refusal leaves a line.** `guard-last-run` is an empty
file, touched on each invocation. `hvk.log` gets one line per refusal:

```
2026-08-24T04:41:09Z guard deny rule=outside-vault tool=Write match=/home/you/.ssh/authorized_keys
2026-08-24T04:41:22Z guard deny rule=delete tool=Bash match=rm
```

The rule that fired and what it matched — the protected folder's name, the resolved
destination, the word that removes files — and never the command itself. It rotates at 256 KB,
keeping one generation, which is the whole of the "basic log rotation" this phase asks for:
everything else this project runs logs to journald, which already rotates.

Both are written best-effort inside a `try` that catches everything. A bug in the
record-keeping must not become an agent that cannot make a single tool call.

### Why the heartbeat is a separate file

It answers the question the log cannot: whether the hook is installed at all. A guard that has
refused nothing and a guard that was never wired in look identical from the log, and the
difference is everything. `guard-last-run` costs one `touch` per tool call — nothing beside the
process the hook already starts — and turns "I think it is protected" into a timestamp.

## Consequences

**Still a speed bump, not a sandbox.** ADR-0012's consequence stands and this does not soften
it: `Bash` can write anywhere, and an agent that wants to escape has `sh -c` to do it in. What
this stops is the ordinary case — a tool call, made in passing, aimed outside the vault —
including the one a note might have asked for.

**A legitimate write outside the vault is now refused.** Exporting a report to `/srv/www`,
writing a scratch file to `/tmp` with `Write`: both are stopped. The escapes are real but
deliberate — narrow the hook's matcher, or do it by hand as the person who owns the server.

**The log inherits the index's sensitivity.** It names protected folders and paths on the
machine. It lives in the index directory, outside the vault (ADR-0002), so it does not sync and
does not wake the watcher — but it is not a file to publish.

**There is no `hvk doctor` check for this, on purpose.** Doctor's rule is that a check which
cannot fail is noise, and there is no failing condition here that hvk can observe: an idle
agent makes no tool calls, so a stale heartbeat is not a fault, and a hook whose command is
broken fails inside the agent where hvk cannot see it. The heartbeat and the log are there to
be looked at by a person who wants to know. As ADR-0011 put it: absence of a refusal is not
evidence of a limit.
