# 0012 — A hook in front of the agent

**Status:** accepted
**Date:** 2026-08-24
**Phase:** 6

## Context

ADR-0009 bounded what an *order-note's* agent may do, by making every job name a permission
profile. It says nothing about the interactive session — the one a person talks to over
Telegram, which runs with more freedom deliberately, because a person is steering it.

Two rules should hold for both, and neither can be enforced from inside `hvk`:

* **A delete is a move to `.trash/`.** Obsidian works that way and so does the write layer
  (ADR-0007) — but `hvk` never deletes anything. The delete that matters is `rm` in a shell
  call, which belongs to the agent's tools, not to ours.
* **Some folders are not the agent's business at all.** A vault that holds credentials or
  private material holds them in a folder, and no amount of care in `hvk` keeps an agent's
  `cat` out of it.

Claude Code answers both with `PreToolUse`: a command that receives the tool call as JSON and
returns a decision. That is the only place these rules can live.

## Alternatives

- **Permission rules in `settings.json`** (`deny: ["Bash(rm *)"]`). Simpler, and it catches
  `rm note.md` while missing `cat x && rm note.md`, `/bin/rm`, and `find -delete`. A rule that
  stops only the careless case is worse than none, because it reads as protection.
- **Refuse deletion inside `hvk`.** Nothing to refuse: `hvk` has no delete. The tool that can
  is the agent's shell.
- **A hook, running `hvk guard`.** Chosen: the check ships and is versioned with the project,
  is tested like the rest of it, and reuses vault resolution.

## Decision

`hvk guard` reads one hook payload on stdin and prints a decision, or nothing.

**Deletion is refused for every spelling that removes a file**: `rm`, `rmdir`, `shred`,
`unlink`, each segment of a pipeline or `&&` chain checked separately, absolute paths
resolved to their program name, and `find … -delete` / `find … -exec rm`. `mv` is deliberately
absent — moving things is what a vault is for, and `mv x .trash/` is the sanctioned way to
remove something. The refusal says so, because a refusal that does not name the alternative
just gets worked around.

**Protected folders have no default.** Which folders are private is nobody's business but the
vault owner's, and a shipped default would be somebody else's word — the same reasoning as the
jobs directory in ADR-0009. Unset means the rule does not apply.

**Protected means unreadable, not just unwritable.** Read-only access to a folder of secrets is
still access to secrets.

### It fails open

Anything this cannot parse — malformed JSON, an unexpected shape, an unbalanced quote — is
allowed through. That is the uncomfortable half of the decision, and it is deliberate: this
runs in front of *every* tool call, so a bug that fails closed does not protect a vault, it
stops a session from working at all. The failure mode of a missed deny is the situation
without the hook; the failure mode of a wrong deny is an agent that cannot do anything.

The same reasoning drives the path matching. It compares folder names rather than resolving
them, so a command that names a protected folder is refused even when the guard cannot prove
that folder is the target. Refusing `grep -r token _PRIVATE` without proving intent is right;
the cost is the occasional false refusal, and that cost is bounded by the owner choosing the
list.

## Consequences

**This is a speed bump, not a sandbox.** An agent with a shell can write a script that deletes
a file without any of these words appearing in the command line. Anyone who needs a real
boundary needs the operating system's — a user without write access, or a container. What this
buys is that the ordinary mistake, made in passing by a capable agent, is stopped and
redirected to the trash.

**A false refusal is possible and will look like a bug.** A note legitimately called
`_PRIVATE-template.md`… is fine, because matching is on whole path segments. A command that
mentions a protected folder in a comment is not, and it will be refused. The message names
what it matched, so the person can see why.

**Nothing installs it.** The hook has to be configured in the agent's own settings, which is a
file this project does not own and will not edit; `deploy/hooks/` carries the snippet to paste.
That is the same line drawn in ADR-0006 — the deployment leaves the machine's own configuration
alone.
