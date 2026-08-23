#!/bin/sh
# Commit whatever changed in the vault. Local only, no remote (ADR-0006).
#
# Run from cron every thirty minutes. It is a checkpoint, an audit trail and an immediate
# undo, all from one command that does nothing when nothing changed.
set -eu

CONFIG="${HVK_DEPLOY_ENV:-$HOME/.config/hvk/deploy.env}"
[ -r "$CONFIG" ] || { echo "vault-autocommit: cannot read $CONFIG" >&2; exit 2; }
# shellcheck disable=SC1090
. "$CONFIG"

[ "${AUTOCOMMIT_ENABLED:-1}" = "1" ] || exit 0
[ -d "${HVK_VAULT:-}" ] || { echo "vault-autocommit: HVK_VAULT is not a directory" >&2; exit 2; }

cd "$HVK_VAULT"

if [ ! -d .git ]; then
    echo "vault-autocommit: $HVK_VAULT is not a git repository. Run deploy/install.sh, or" >&2
    echo "  git init, before enabling the cron job." >&2
    exit 2
fi

# A vault is not a source tree: another process may be writing while this runs, and a partly
# written note committed now is simply committed again complete on the next pass. That is the
# point of a checkpoint, so no locking is attempted.
git add -A

# --quiet and a check, rather than letting commit fail: cron mails every non-zero exit, and
# "nothing to commit" would mean a message every half hour forever.
if git diff --cached --quiet; then
    exit 0
fi

STAMP=$(date '+%Y-%m-%d %H:%M')
COUNT=$(git diff --cached --name-only | wc -l | tr -d ' ')
git -c user.name="${AUTOCOMMIT_NAME:-hvk}" \
    -c user.email="${AUTOCOMMIT_EMAIL:-hvk@localhost}" \
    commit --quiet --no-gpg-sign \
    -m "${AUTOCOMMIT_MESSAGE:-checkpoint} $STAMP ($COUNT files)"
