#!/usr/bin/env bash
# Build and drive the testbed container.
#
#   ./tools/testbed/testbed.sh up            start it, with a synthetic vault inside
#   ./tools/testbed/testbed.sh up --vault D   ... using a copy of a real vault instead
#   ./tools/testbed/testbed.sh selftest       run deploy/selftest.sh inside
#   ./tools/testbed/testbed.sh shell          get a prompt as the hvk user
#   ./tools/testbed/testbed.sh reboot         restart it, to check things come back
#   ./tools/testbed/testbed.sh down           remove it
#
# Development utility, not part of the product (ADR-0006 keeps deployment out of the machine's
# way; this keeps testing out of the developer's way).
set -euo pipefail

IMAGE=hvk-testbed
NAME=hvk-testbed
USER_IN=hvk
UID_IN=1000
# docker exec opens no login session, so the variable that points systemctl --user at its
# bus has to be handed over explicitly.
RUNTIME_ENV=(-e XDG_RUNTIME_DIR=/run/user/1000)
HOME_IN="/home/$USER_IN"
REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)

VAULT_MOUNT=""
CLAUDE_MOUNT=""
WITH_RUNTIMES=0

die() { printf 'testbed: %s\n' "$*" >&2; exit 1; }
running() { [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null || echo false)" = true ]; }

cmd=${1:-help}; shift || true
while [ $# -gt 0 ]; do
    case "$1" in
        --vault)    VAULT_MOUNT=${2:?--vault needs a path}; shift 2 ;;
        --claude)   CLAUDE_MOUNT=${2:?--claude needs a path}; shift 2 ;;
        --runtimes) WITH_RUNTIMES=1; shift ;;
        *) die "unknown option $1" ;;
    esac
done

build() {
    docker build --quiet \
        --build-arg "WITH_RUNTIMES=$WITH_RUNTIMES" \
        -t "$IMAGE" "$REPO/tools/testbed" >/dev/null
}

up() {
    running && { echo "already up"; return; }
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    build

    args=(
        -d --name "$NAME"
        --cgroupns=host
        # exec matters: Docker's default tmpfs is noexec, and systemd's user manager has to
        # execute from /run. Without it the container boots degraded and nothing user-scope
        # works, which is everything deploy/ installs.
        --tmpfs "/run:rw,exec,mode=755"
        --tmpfs "/run/lock:rw,exec,mode=1777"
        --tmpfs "/tmp:rw,exec,mode=1777"
        -v /sys/fs/cgroup:/sys/fs/cgroup:rw
        # The repository is read-only inside: the tests run deploy/ from here, and nothing in
        # the container has any business writing to your working tree.
        -v "$REPO:/repo:ro"
    )

    if [ -n "$VAULT_MOUNT" ]; then
        [ -d "$VAULT_MOUNT" ] || die "no such vault: $VAULT_MOUNT"
        # Read-write on purpose: phases 4 and 5 write to the vault, and that has to be tested.
        # Point this at a mirror (tools/mirror_vault.py), never at a real vault.
        args+=(-v "$VAULT_MOUNT:$HOME_IN/vault")
        echo "mounting vault read-write: $VAULT_MOUNT"
        echo "  make sure that is a mirror, not the vault you actually use."
    fi
    if [ -n "$CLAUDE_MOUNT" ]; then
        [ -d "$CLAUDE_MOUNT" ] || die "no such directory: $CLAUDE_MOUNT"
        args+=(-v "$CLAUDE_MOUNT:$HOME_IN/.claude:ro")
        echo "mounting Claude credentials read-only: $CLAUDE_MOUNT"
        echo "  anything running inside can use them. Only do this deliberately."
    fi

    if ! docker run "${args[@]}" "$IMAGE" >/dev/null 2>&1; then
        echo "plain run failed; retrying with --privileged (some hosts need it for systemd)"
        docker run "${args[@]}" --privileged "$IMAGE" >/dev/null
    fi

    printf 'waiting for systemd'
    for _ in $(seq 1 30); do
        if docker exec "$NAME" systemctl is-system-running --wait >/dev/null 2>&1 ||
           docker exec "$NAME" systemctl is-system-running 2>/dev/null | grep -qE 'running|degraded'; then
            echo " ok"
            break
        fi
        printf '.'; sleep 1
    done
    echo ""

    docker exec "$NAME" sh -c "mkdir -p $HOME_IN/vault/.obsidian && chown -R $USER_IN $HOME_IN/vault"
    if [ -z "$VAULT_MOUNT" ]; then
        docker exec -u "$USER_IN" "${RUNTIME_ENV[@]}" "$NAME" sh -c "
            printf '{}' > $HOME_IN/vault/.obsidian/app.json
            printf '# One\n\nLinks to [[Two]].\n' > $HOME_IN/vault/One.md
            printf '# Two\n' > $HOME_IN/vault/Two.md"
        echo "synthetic vault created at $HOME_IN/vault"
    fi

    # Stubs for the two things that need credentials. Testing the runner against a real
    # agent would measure the agent; a fixed answer measures the runner, which is the point.
    # Both sleep rather than exit, because `ob sync --continuous` and `claude` are daemons:
    # a stub that returns immediately leaves its unit restarting on a timer, which reads as
    # a broken unit rather than as a stub doing the wrong thing.
    # Created as the user and not as root, or root would own ~/.local and the whole
    # user-scope install would then fail inside the user's own home directory.
    docker exec -u "$USER_IN" "${RUNTIME_ENV[@]}" "$NAME" sh -c "
        mkdir -p $HOME_IN/.local/bin $HOME_IN/.local/share $HOME_IN/.config
        printf '#!/bin/sh\nsleep infinity\n' > $HOME_IN/.local/bin/ob
        printf '#!/bin/sh\nsleep infinity\n' > $HOME_IN/.local/bin/claude
        chmod +x $HOME_IN/.local/bin/ob $HOME_IN/.local/bin/claude"

    # hvk itself is installed from the mounted repository, so the container tests this code
    # rather than a published release.
    docker exec -u "$USER_IN" "${RUNTIME_ENV[@]}" "$NAME" sh -c "
        python3 -m venv $HOME_IN/.venv >/dev/null 2>&1
        $HOME_IN/.venv/bin/pip install --quiet -e /repo 2>/dev/null ||
        $HOME_IN/.venv/bin/pip install --quiet /repo
        ln -sf $HOME_IN/.venv/bin/hvk $HOME_IN/.local/bin/hvk"

    echo "up. Try: $0 selftest"
}

case "$cmd" in
    up) up ;;
    down) docker rm -f "$NAME" >/dev/null 2>&1 && echo "removed" || echo "not running" ;;
    shell) running || die "not up"; docker exec -it -u "$USER_IN" "${RUNTIME_ENV[@]}" "$NAME" bash ;;
    reboot)
        running || die "not up"
        docker restart "$NAME" >/dev/null
        sleep 5
        echo "restarted. What came back on its own:"
        docker exec -u "$USER_IN" "${RUNTIME_ENV[@]}" "$NAME" systemctl --user list-units 'hvk*' 'obsidian*' --no-pager || true
        ;;
    selftest)
        running || die "not up"
        # Copied out of the read-only mount: the scripts must be executable, and /repo is ro.
        docker exec -u "$USER_IN" "${RUNTIME_ENV[@]}" "$NAME" sh -c "
            rm -rf $HOME_IN/deploy && cp -r /repo/deploy $HOME_IN/deploy && chmod +x $HOME_IN/deploy/*.sh $HOME_IN/deploy/bin/*.sh"
        docker exec -u "$USER_IN" "${RUNTIME_ENV[@]}" "$NAME" bash "$HOME_IN/deploy/selftest.sh"
        ;;
    logs) docker exec "$NAME" journalctl --no-pager -n 50 ;;
    *)
        sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
        ;;
esac
