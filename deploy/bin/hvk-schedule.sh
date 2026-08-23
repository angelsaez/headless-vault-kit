#!/bin/sh
# Run one of the scheduled hvk tasks from cron: the materialised views of phase 4, or the
# order-note runner of phase 5.
#
# Both are silent when they have nothing to do and speak only when something failed. cron
# mails every byte a job prints, so a task that printed its table every thirty minutes would
# turn into a mailbox nobody reads -- and then the one message that mattered is missed.
set -eu

TASK="${1:-}"
CONFIG="${HVK_DEPLOY_ENV:-$HOME/.config/hvk/deploy.env}"
[ -r "$CONFIG" ] || { echo "hvk-schedule: cannot read $CONFIG" >&2; exit 2; }
# shellcheck disable=SC1090
. "$CONFIG"

[ -x "${HVK_BIN:-}" ] || { echo "hvk-schedule: HVK_BIN is not an executable" >&2; exit 2; }
[ -d "${HVK_VAULT:-}" ] || { echo "hvk-schedule: HVK_VAULT is not a directory" >&2; exit 2; }

case "$TASK" in
    views)
        [ "${VIEWS_ENABLED:-1}" = "1" ] || exit 0
        # Writes only what actually changed, and nothing at all when nothing did, so running
        # it often costs a query per base and wakes neither sync nor the watcher (ADR-0007).
        if ! OUT=$("$HVK_BIN" --vault "$HVK_VAULT" views --apply 2>&1); then
            printf 'hvk views failed:\n%s\n' "$OUT" >&2
            exit 1
        fi
        ;;
    jobs)
        # No directories declared, no runner. There is no default on purpose (ADR-0009): a
        # runner that starts executing an agent because a folder happened to have the right
        # name is the failure the whole feature exists to prevent. Declaring them in
        # deploy.env is therefore the switch that turns the runner on -- no reinstall needed.
        [ -n "${HVK_JOBS_DIR:-}" ] && [ -n "${HVK_JOBS_PROFILES:-}" ] || exit 0
        if ! OUT=$("$HVK_BIN" --vault "$HVK_VAULT" jobs \
                       --dir "$HVK_JOBS_DIR" --profiles "$HVK_JOBS_PROFILES" --run 2>&1); then
            printf 'hvk jobs failed:\n%s\n' "$OUT" >&2
            exit 1
        fi
        ;;
    *)
        echo "usage: hvk-schedule.sh views|jobs" >&2
        exit 2
        ;;
esac
