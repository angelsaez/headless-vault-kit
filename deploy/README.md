# Phase 0 — putting it on a server

Everything here installs into **your own user account**: systemd *user* units, your own
crontab, files under `$HOME`. No package is installed, no system unit is written, no firewall
rule is touched. The reasoning is in [ADR-0006](../docs/adr/0006-deployment-leaves-the-system-alone.md);
the short version is that the server probably already runs other things, and a deployment
recipe that rearranges the machine is how those things break.

One consequence to keep in mind before anything else: **`systemctl` without `--user` will
report that these services do not exist.** That is not a broken install.

## What gets installed

| Piece | Where | What it does |
|---|---|---|
| `obsidian-headless.service` | `~/.config/systemd/user/` | `ob sync --continuous`, keeping the vault in step with Obsidian Sync |
| `hvk-watch.service` | same | Indexes changes as they land |
| `hvk-agent.service` | same | A tmux session running Claude Code with the Telegram channel |
| `vault-autocommit.sh` | `~/.local/share/hvk/deploy-bin/` | A git checkpoint of the vault, every 30 minutes |
| cron block | your crontab | The auto-commit, `hvk verify` nightly at 04:17, the materialised views, and the order-note runner |
| `hvk-schedule.sh` | `~/.local/share/hvk/deploy-bin/` | Runs the views and the runner from cron, quiet unless something failed |
| `.gitignore` | inside the vault | Only if it has none of its own |

## Prerequisites, which are not installed for you

Three runtimes, none of them ours to manage. Install them however this machine already does
that — apt, dnf, nvm, asdf, a tarball. `preflight.sh` checks and names what is missing.

| Needed by | What | Note |
|---|---|---|
| `hvk` | Python 3.11+ | `curl -LsSf https://astral.sh/uv/install.sh \| sh` then `uv tool install hvk` |
| `ob` | **Node.js 22+** | Obsidian Headless. Also needs an Obsidian Sync subscription |
| Telegram channel | **Bun** | `curl -fsSL https://bun.sh/install \| bash` |
| the agent session | `tmux`, `git` | |

## Runbook

### 1. Check the machine

```sh
mkdir -p ~/.config/hvk
cp deploy/deploy.env.example ~/.config/hvk/deploy.env
$EDITOR ~/.config/hvk/deploy.env        # vault path and three absolute binary paths
./deploy/preflight.sh
```

Absolute paths matter. A systemd unit does not inherit your interactive `PATH`, so `hvk`
alone works in your shell and fails at boot. `command -v hvk` gives you the right value.

Fix every `FAIL` before continuing. Warnings are yours to judge; the one about listening
sockets is reported and never acted on, because closing a port on a server already running
services is exactly the kind of help nobody asked for.

### 2. Log Obsidian Sync in, once, by hand

```sh
ob login
ob sync-setup --vault "My Vault"
```

Interactive on purpose: it holds your Obsidian credentials, and it belongs to you rather than
to a script. Exclude private folders **before the first sync**, in the same way on every
device — once a folder has synced, excluding it later does not un-sync what already left.

### 3. Build the index once

```sh
hvk --vault ~/vault scan
hvk --vault ~/vault info
```

Faster and more visible now than as the first thing a watcher does at boot.

### 4. Install

```sh
./deploy/install.sh --dry-run      # says what it would change
./deploy/install.sh
```

**If the machine already runs some of this**, install only the missing parts, or you will end
up with two syncers on one vault and two agents on one bot. The installer will not notice: its
"refuse to overwrite a unit that differs" check compares paths, and a system unit and a user
unit of the same name are different paths ([ADR-0010](../docs/adr/0010-installing-onto-a-server-that-is-already-running.md)).

```sh
./deploy/install.sh --only watch,schedules            # the index and the timers, nothing else
./deploy/install.sh --only watch,schedules --system   # ...as system units, if that is how the
                                                      #    machine's own services are managed
```

The five parts are `sync`, `agent`, `watch`, `git` and `schedules`; `install.sh --help` says
what each one covers. `--system` writes to `/etc/systemd/system` and needs `sudo`, and in
exchange needs no lingering — a system unit is started by the machine, not by your session.
`uninstall.sh` sweeps both scopes without being told which you used.

It refuses, with exit code 3, if a unit of the same name already exists with different
contents — something else may own it. Compare, then use `--force` if you are sure. Running it
twice changes nothing the second time.

### 5. Survive a reboot

```sh
sudo loginctl enable-linger "$USER"
```

The single command in this phase that needs a privileged hand. Without it, user services stop
when your last session ends and do not come back until you log in — so the reboot test fails
in a way that looks like a systemd problem and is not.

### 6. Start, and pair Telegram

```sh
systemctl --user start obsidian-headless hvk-watch hvk-agent
systemctl --user status hvk-watch
```

Then the interactive half, which cannot be scripted and should not be:

1. Create a bot: message [@BotFather](https://t.me/BotFather), `/newbot`, keep the token.
2. Attach to the session: `tmux attach -t hvk-agent`
3. `/plugin install telegram@claude-plugins-official`
4. `/telegram:configure <token>` — writes it to `~/.claude/channels/telegram/.env`
5. Message your bot. It answers with a six-character code.
6. Back in the session: `/telegram:access pair <code>`
7. Lock it down: `/telegram:access policy allowlist`

Step 7 is not optional. Until it runs, the policy is `pairing`, and anyone who finds your bot
can pair with it and reach an agent that can read and write your vault.

Detach with `Ctrl-b d`. The session keeps running.

### 7. The fire test

```sh
sudo reboot
```

Then, without touching anything:

```sh
systemctl --user status obsidian-headless hvk-watch hvk-agent
hvk --vault ~/vault info          # last_scan should be recent
git -C ~/vault log --oneline -5   # checkpoints from today
```

Create a note on your phone, wait a few seconds, and ask the bot what links to it. That is the
whole system in one question.

## When something is wrong

| Symptom | Where to look |
|---|---|
| `Unit ... not found` | You left out `--user` |
| `Failed to load environment files` | `~/.config/hvk/deploy.env` is missing. The units read that exact path |
| Service dies and restarts forever | `journalctl --user -u hvk-watch -n 50`. After five failures in a minute it stops trying and stays failed, on purpose |
| Everything stops when you log out | Lingering is off — step 5 |
| The bot ignores you | `tmux attach -t hvk-agent` and check the session is alive and paired |
| `ob` fails on start | It needs `ob login` first; credentials are per-user and interactive |

Removing it all:

```sh
./deploy/uninstall.sh
```

Takes out exactly what was installed. The vault, its git history, the index and every runtime
on the machine are left alone.

## Verifying the machinery itself

```sh
./deploy/selftest.sh
```

Safer still, and the way it is developed, is to run it inside the throwaway container in
[`tools/testbed/`](../tools/testbed/README.md), which needs nothing of yours at all:

```sh
./tools/testbed/testbed.sh up && ./tools/testbed/testbed.sh selftest
./tools/testbed/testbed.sh reboot     # and check what comes back on its own
```

Installs everything against a throwaway vault and stub binaries, checks the units load, the
agent session really starts, the auto-commit skips when nothing changed and never commits
`_PRIVATE/`, that a second run changes nothing, that an unrecognised unit is refused rather
than overwritten, and that uninstalling leaves your other crontab lines intact. Then it puts
everything back. Safe to run on the target machine before trusting it.

## What this does not do, and you still should

- **The firewall.** The plan asks for SSH only. Nothing installed here opens a port, so there
  is nothing to open; closing what is already there is your decision, not a script's.
- **Backups off the server.** Git here is local only, with no remote (plan annex, decision 5).
  It gives checkpoints and an undo, not survival of the machine. That is phase 6.
- **Healthchecks and alerting.** Also phase 6.
