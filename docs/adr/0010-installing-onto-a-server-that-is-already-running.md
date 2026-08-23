# 0010 — Installing onto a server that is already running something

**Status:** accepted
**Date:** 2026-08-23
**Phase:** 0

## Context

ADR-0006 decided that the deployment leaves the machine alone: systemd **user** units, the
invoking user's own crontab, no packages, no firewall rules, and no root beyond one
`loginctl enable-linger`. The reasoning holds and is not revisited here.

What it did not anticipate is the machine it was aimed at. Putting `hvk` on the server it was
written for turned up a situation the installer cannot express:

- `obsidian-headless.service` is **already running** there, as a system unit, syncing the
  vault.
- Claude Code with the Telegram channel is **already running**, as `nexus-arranque.service`.
- The vault is **already** a git repository with its own auto-commit on a cron schedule.
- Nothing else of ours is there: no `hvk`, no index, no watcher, no scheduled views or jobs.

`install.sh` was all-or-nothing, so it would have installed a second `ob sync --continuous`
over the same vault and a second agent on the same bot. Worse, it would not have complained:
our units are user-scope and the machine's are system-scope, so the "refuse to overwrite a
unit that exists and differs" check never fires — the names collide but the paths do not.

Two smaller facts pointed the same way. The machine has `Linger=no`, so a user unit would not
survive a reboot until somebody changed that; and everything else on it is a system unit
managed with `sudo systemctl`, so a user unit would be the one thing an operator has to
remember is different.

**A server that already runs something is the normal case, not the exception.** Anyone with a
machine worth putting a vault on probably has something else on it already.

## Alternatives

- **Document "install it by hand on a busy machine".** Rejected: the runbook is the product
  here as much as the code is, and "copy these three files yourself" is where deployments rot.
- **Detect what is already running and skip it.** Attractive and wrong. Guessing that
  `nexus-arranque.service` is "the same thing as" `hvk-agent.service` means guessing about
  somebody else's machine from a name. Refusing to install is safe; deciding silently is not.
- **Let the caller say what to install.** Chosen. The operator knows what the machine already
  does; the installer does not.

## Decision

### `--only LIST`

Five parts, installable in any combination: `sync`, `agent`, `watch`, `git`, `schedules`. The
default is all five, so an empty machine behaves exactly as ADR-0006 describes and nothing
about the existing runbook changes.

Anything not listed is not installed, not started and not written into the crontab, and the
closing instructions only mention the steps that apply — no `ob login` when sync was not
installed, no lingering when nothing user-scope was.

An unknown part is an error rather than a no-op: a typo that silently installs nothing would
look identical to success.

### `--system`

Units go into `/etc/systemd/system` instead of the user scope, managed with `sudo systemctl`.
The unit files are not duplicated: the system variant is derived from the user one by three
exact substitutions — `%h` expanded, `User=`/`Group=` added, `WantedBy` retargeted at
`multi-user.target`. Two copies of every unit would drift; a transformation this small can be
read and checked in one pass.

This is a **departure from ADR-0006, not a replacement of it.** User scope stays the default
and stays the recommendation, because it needs no root and cannot break anything outside a
home directory. `--system` exists for machines where the alternative is worse: a host whose
own services are all system units, where nobody stays logged in, and where lingering would be
one more thing to know.

### `uninstall.sh` sweeps both scopes, always

Without being told which was used, and without asking. Whoever uninstalls has usually
forgotten, and a leftover unit that still starts at boot is exactly the kind of fault that
gets blamed on the next thing installed.

## Consequences

**`--system` needs `sudo`, which ADR-0006 avoided.** That is the cost, stated plainly. It is
opt-in, it is refusable, and the default path still needs no root at all.

**The installer can now leave a machine half-configured, and that is the point.** `--only
watch` installs a watcher with no syncer; on the target machine that is correct, because
something else syncs. It also means a mistaken `--only` produces a system that looks installed
and does not work. The dry run and the closing summary both name exactly what was done.

**Nothing detects duplication.** If somebody runs the default install on a machine that
already syncs, they still get two syncers. Refusing to guess was deliberate, but it means the
protection is the operator reading the runbook, not the code. If this bites more than once, the
next step is a `--check` that reports what looks already-provided without acting on it.

**The system-unit transformation is only as good as its three rules.** A unit that later uses
another `%`-specifier, or that assumes the user manager's environment, would need this
revisited. The selftest installs and starts both variants, so a divergence shows up as a unit
that fails to start rather than as a surprise on a server.
