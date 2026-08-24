#!/bin/sh
# One file holding the whole vault, so that losing the machine is not losing the vault.
#
# Run daily from cron. Sync, the git checkpoints and the other devices already cover a bad
# edit; none of them covers the machine going away, and Sync in particular replicates a
# deletion as faithfully as it replicates a note (ADR-0013).
#
# The artefact carries everything the vault holds -- notes, attachments, .obsidian, .trash and
# the git history -- so wherever it lands is as sensitive as the vault itself.
set -eu

CONFIG="${HVK_DEPLOY_ENV:-$HOME/.config/hvk/deploy.env}"
[ -r "$CONFIG" ] || { echo "vault-backup: cannot read $CONFIG" >&2; exit 2; }
# shellcheck disable=SC1090
. "$CONFIG"

die() { echo "vault-backup: $*" >&2; exit 2; }

[ -d "${HVK_VAULT:-}" ] || die "HVK_VAULT is not a directory"
# Configuring a destination is what turns the backup on, exactly as declaring a jobs directory
# is what turns the runner on. Reaching this point without one means cron is calling a backup
# that has nowhere to write, and that has to be loud: a runner that does not run is safe, a
# backup that does not run is discovered on the day it was needed.
[ -n "${BACKUP_DIR:-}" ] || die "BACKUP_DIR is not set. Set it in $CONFIG, or remove the cron entry."

VAULT=$(CDPATH= cd -- "$HVK_VAULT" && pwd)
case "$BACKUP_DIR" in
    "$VAULT"|"$VAULT"/*)
        # It would sync, it would be indexed, and tomorrow's copy would contain today's. The
        # same rule the index lives by (ADR-0002).
        die "BACKUP_DIR is inside the vault. Put it somewhere the vault does not reach." ;;
esac

mkdir -p "$BACKUP_DIR"
STAMP=$(date +%F)
ARCHIVE="$BACKUP_DIR/vault-$STAMP.tar.gz"
PART="$BACKUP_DIR/.vault-$STAMP.tar.gz.part"
trap 'rm -f "$PART"' EXIT

# Built under a different name and moved into place at the end. A half-written archive that
# already carries the final name is the one that gets picked up as a backup on the day it
# matters.
#
# Excluded, and nothing else: Obsidian's own UI state and recovery snapshots -- one changes
# every time a pane moves, the other is large and is itself a recovery mechanism -- and the
# half-written files editors and sync leave lying around. .trash/ and .git/ are kept on
# purpose: the trash is where a deleted note went, and the history is what turns a copy of the
# damage into an undo.
set -f                     # the patterns are for tar to expand, not for the shell
set -- --exclude='./.obsidian/workspace*' \
       --exclude='./.obsidian/file-recovery*' \
       --exclude='*.tmp' --exclude='*.partial' --exclude='~$*'
for pattern in ${BACKUP_EXCLUDE:-}; do set -- "$@" --exclude="$pattern"; done
set +e
tar -C "$VAULT" -czf "$PART" "$@" .
rc=$?
set -e
set +f
# A vault is not a source tree: sync or an editor may write while tar reads, and GNU tar
# reports that as a warning (1) rather than a failure (2 and up). Tomorrow's copy has the
# file whole. Refusing to keep the archive over it would mean a machine that is being used
# never gets a backup at all.
[ "$rc" -le 1 ] || die "tar failed with status $rc"

# Read it back before trusting it. Not the same claim as the exit code above: this one says
# the bytes on disk can actually be listed.
tar -tzf "$PART" >/dev/null || die "the archive it just wrote cannot be read back"

mv "$PART" "$ARCHIVE"
trap - EXIT
( cd "$BACKUP_DIR" && sha256sum "vault-$STAMP.tar.gz" > "vault-$STAMP.tar.gz.sha256" )

# Off the machine, which is the whole point. A hook rather than a command line to eval: it
# receives the archive and its checksum as arguments and nothing here has to know whether the
# destination is rclone, scp or a tape robot. Its failure is this script's failure, because a
# backup that stayed on the server is not a backup.
if [ -n "${BACKUP_OFFSITE_HOOK:-}" ]; then
    [ -x "$BACKUP_OFFSITE_HOOK" ] || die "BACKUP_OFFSITE_HOOK is not executable: $BACKUP_OFFSITE_HOOK"
    "$BACKUP_OFFSITE_HOOK" "$ARCHIVE" "$ARCHIVE.sha256" || die "the offsite hook failed"
fi

# Local copies are the convenience; the one off the machine is the backup. Keep a few, oldest
# first out.
KEEP=${BACKUP_KEEP:-7}
cd "$BACKUP_DIR"
ls -1t vault-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
    rm -f -- "$old" "$old.sha256"
done
