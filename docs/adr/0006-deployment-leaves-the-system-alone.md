# 0006 — Deployment leaves the system alone

**Status:** accepted
**Date:** 2026-08-21
**Phase:** 0

## Context

Phase 0 puts the pieces on a server: Obsidian Headless syncing, `hvk watch` indexing, Claude
Code answering Telegram, and cron keeping git checkpoints. The plan describes it as a fresh
install following a known recipe.

The server is not fresh. It already runs things, and it will keep running them. And this is
meant to become a project other people install, on machines whose contents are none of our
business. So the constraint is not "install these components" but **"install these components
without assuming or disturbing anything else on the machine"**.

That rules out the shape a deployment recipe usually takes. Writing units into
`/etc/systemd/system`, dropping files in `/etc/cron.d`, running `apt install`, or setting
firewall rules all assume the machine is ours to arrange. On a server with an existing setup,
any of them can quietly break something that was working, and the failure will not look like
it came from here.

## Alternatives

- **System-wide systemd units, root install.** The conventional shape, and the wrong one here:
  it needs root for everything, puts our files where another tool may also be writing, and a
  mistake in a unit can affect the whole machine. It also makes uninstalling a matter of
  remembering what was touched.
- **A container.** Genuinely isolating, and it solves the "do not disturb" problem outright.
  Rejected for now because the thing being deployed is an agent that reads and writes a vault
  on the host, talks to a sync daemon that holds credentials, and is meant to be attached to
  interactively. Containerising all of that is its own project, and the plan warns against
  exactly that kind of scope inflation. Worth revisiting if the project is ever packaged for
  strangers rather than for one server.
- **User-scope everything, no root.** Chosen.

## Decision

Everything phase 0 installs lives in the invoking user's own scope, and nothing outside it is
written, installed or reconfigured.

- **systemd user units** in `~/.config/systemd/user/`, not system units. Managed with
  `systemctl --user`. Surviving a reboot without a login session needs lingering enabled once
  (`loginctl enable-linger $USER`) — the single command in this whole phase that needs a
  privileged hand, and it is a per-user flag rather than a change to any service.
- **The user's own crontab**, never `/etc/cron.d` or `/etc/crontab`.
- **One configuration file**, `~/.config/hvk/deploy.env`, read by every unit through
  `EnvironmentFile=`. Nothing else holds paths, and nothing is compiled into a unit.
- **No package installation.** Node 22+ for `ob`, Bun for the Telegram plugin and Python 3.11+
  for `hvk` are stated as prerequisites and *checked*, never installed. Which package manager
  the machine uses, and whether those runtimes come from apt, dnf, nvm, asdf or a tarball, is
  the operator's business.
- **No firewall changes.** The plan asks for "only SSH exposed". `preflight.sh` reports what it
  can see and says what to do about it; it does not touch a rule. Nothing installed here
  listens on a port, so there is nothing to open, and closing something on a server already
  running services is precisely the kind of change that breaks what was working.
- **Refuse rather than overwrite.** The installer stops if a unit of the same name already
  exists with different contents, naming the file, unless `--force` is passed.
- **Idempotent, and reversible.** Running the installer twice changes nothing the second time.
  `uninstall.sh` removes exactly what was installed and leaves the vault, the index and the
  rest of the machine untouched.

Git on the server is **local only** (decision 5 of the plan's annex, settled 2026-08-21): an
auto-commit every thirty minutes into a repository inside the vault, with no remote. That
gives checkpoints, an audit trail and an immediate undo, without a deploy key to manage or a
cron job that can fail on a network blip. Surviving the loss of the whole server is a backup
concern, and belongs to phase 6.

## Consequences

**No root is needed except once**, for lingering. Someone who cannot get that command run can
still use everything; the services just will not start until they log in, which is worth
saying in the runbook rather than letting them discover it after a reboot.

**User units are less familiar than system units.** `systemctl status hvk-watch` without
`--user` reports "not found", which reads like a broken install. The runbook leads with that.

**Pairing Telegram cannot be automated.** The bot hands out a code in a chat and it has to be
typed into a live Claude session. That is a deliberate security property of the plugin, not an
obstacle to route around, so the runbook has an interactive step and says so.

**"Do not touch the firewall" is a real gap, honestly stated.** The plan's exit criterion for
exposure is not met by anything in `deploy/`; it is met by the operator, guided by a check
that tells them what is listening. Claiming otherwise would be worse than the gap.

**Three runtimes are required and none is installed.** If they are missing, `preflight.sh`
says which, and stops. That is friction by design: silently installing a Node version on a
server that already had one is how a deployment recipe breaks somebody's unrelated service.
