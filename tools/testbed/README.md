# Testbed

A disposable Debian box with systemd, for exercising `deploy/` without touching anyone's
machine. Development utility, not part of the product: nobody installing `hvk` needs it, and
anyone verifying that the deployment works before trusting it does.

It exists because `deploy/selftest.sh` has to install units, write a crontab and start
services to prove anything — and doing that on the developer's own machine is invasive even
when it cleans up after itself.

```sh
./tools/testbed/testbed.sh up          # build and boot it
./tools/testbed/testbed.sh selftest    # run deploy/selftest.sh inside
./tools/testbed/testbed.sh reboot      # restart, and see what came back on its own
./tools/testbed/testbed.sh shell       # a prompt as the hvk user
./tools/testbed/testbed.sh down        # throw it away
```

Needs Docker reachable from the shell you run it in. On Windows that means enabling WSL
integration in Docker Desktop, or running it from a Linux host.

## What is real and what is fake

| Real | Stubbed |
|---|---|
| Debian 12, systemd, a user instance with lingering | `ob` — Obsidian Headless needs a Sync subscription and your credentials |
| cron, git, tmux | `claude` — needs authentication, and a fixed answer measures the runner rather than the agent |
| `hvk`, installed from the mounted repository | |

Stubbing the two credentialed pieces is deliberate. The project is built so that it does not
care how files arrive on disk, which means a fake syncer tests the indexer just as well as a
real one and needs nobody's password.

To use the real ones anyway, build with `--runtimes` (adds Node 22 and Bun) and mount what
they need:

```sh
./tools/testbed/testbed.sh up --runtimes \
    --vault  /path/to/a/mirror \
    --claude ~/.claude
```

Two warnings on that, both worth reading twice. The vault is mounted **read-write**, because
phases 4 and 5 write to it — point it at a mirror made with `tools/mirror_vault.py`, never at
a vault you actually use. And mounting `~/.claude` hands your credentials to whatever runs
inside the container.

## Two things it taught us

Both would otherwise have been found on the server:

- Docker's default `tmpfs` is `noexec`, and systemd's user manager has to execute from `/run`.
  Without `exec` the container boots degraded and nothing user-scope works — which is
  everything `deploy/` installs.
- `libpam-systemd` and `dbus-user-session` are not optional. `pam_systemd` is what sets
  `XDG_RUNTIME_DIR` and creates `/run/user/<uid>`; without them `user@1000.service` fails with
  "Trying to run as user instance, but $XDG_RUNTIME_DIR is not set" and `systemctl --user`
  cannot connect to anything.

And `docker exec` opens no login session, so `XDG_RUNTIME_DIR` has to be passed in by hand —
which the script does for you.
