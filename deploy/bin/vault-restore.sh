#!/bin/sh
# Put a backup back, somewhere that is not the vault, and then check that what came back is a
# vault: the files are there, the git history is intact, and hvk can index it.
#
#   vault-restore.sh <archive.tar.gz> <target-directory>
#
# It never writes over the live vault. Replacing a vault means stopping the syncer first, and
# a script that does it while sync is running turns a local mistake into one on every device.
# That procedure is in deploy/RESTORE.md, by hand, on purpose (ADR-0013).
set -eu

usage() {
    echo "usage: vault-restore.sh <archive.tar.gz> <target-directory>" >&2
    echo "  the target must not exist, or must be empty, and cannot be the vault" >&2
    exit 2
}
[ $# -eq 2 ] || usage
ARCHIVE=$1
TARGET=$2
die() { echo "vault-restore: $*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }

[ -r "$ARCHIVE" ] || die "cannot read $ARCHIVE"

# The configuration is a convenience here, not a requirement: a restore may well be happening
# on a machine where nothing is installed yet, which is exactly when it is needed most.
CONFIG="${HVK_DEPLOY_ENV:-$HOME/.config/hvk/deploy.env}"
if [ -r "$CONFIG" ]; then
    # shellcheck disable=SC1090
    . "$CONFIG"
fi
HVK_BIN=${HVK_BIN:-$(command -v hvk || true)}

# Resolved before anything is compared against it. The guards below are string comparisons, and
# "." or "vault/.." would walk straight past them while pointing exactly where they forbid.
if [ -d "$TARGET" ]; then
    TARGET=$(CDPATH= cd -- "$TARGET" && pwd)
else
    PARENT=$(CDPATH= cd -- "$(dirname -- "$TARGET")" 2>/dev/null && pwd)         || die "no such directory: $(dirname -- "$TARGET")"
    TARGET="$PARENT/$(basename -- "$TARGET")"
fi

# Where the vault is comes first, before the target is judged on anything else. Both of these
# would otherwise be reported as "not empty", which is true and tells you nothing about the
# thing you were one command away from overwriting.
VAULT=""
if [ -n "${HVK_VAULT:-}" ] && [ -d "$HVK_VAULT" ]; then
    VAULT=$(CDPATH= cd -- "$HVK_VAULT" && pwd)
    case "$TARGET" in
        "$VAULT"|"$VAULT"/*) die "that is the vault, or inside it. Restore somewhere else." ;;
    esac
    case "$VAULT" in
        "$TARGET"/*) die "the vault is inside $TARGET. Restore somewhere else." ;;
    esac
fi

if [ -e "$TARGET" ]; then
    [ -d "$TARGET" ] || die "$TARGET exists and is not a directory"
    [ -z "$(ls -A "$TARGET" 2>/dev/null)" ] || die "$TARGET is not empty. Restore into a new directory."
fi

say "archive"
say "  $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
if [ -r "$ARCHIVE.sha256" ]; then
    if ( cd "$(dirname "$ARCHIVE")" && sha256sum -c --status "$(basename "$ARCHIVE").sha256" ); then
        say "  checksum ok"
    else
        die "checksum does NOT match. Fetch it again before trusting it."
    fi
else
    # Not fatal: an archive fetched from somewhere that never carried the sidecar is still
    # worth restoring. But say it, because "it extracted" is a weaker claim than people hear.
    say "  no .sha256 beside it -- integrity not verified, only readability"
fi
MEMBERS=$(tar -tzf "$ARCHIVE" 2>/dev/null | wc -l)
[ "$MEMBERS" -gt 0 ] || die "the archive cannot be read"
say "  $MEMBERS entries"

say ""
say "restoring into $TARGET"
mkdir -p "$TARGET"
tar -xzf "$ARCHIVE" -C "$TARGET"
FILES=$(find "$TARGET" -type f ! -path '*/.git/*' | wc -l)
say "  $FILES files on disk, $(du -sh "$TARGET" | cut -f1)"
[ -d "$TARGET/.obsidian" ] && say "  .obsidian/ is there, so it is a vault and not just a folder of notes" || true
[ -d "$TARGET/.trash" ] && say "  .trash/ came too: deleted notes are recoverable from here" || true

if [ -d "$TARGET/.git" ]; then
    say ""
    say "git history"
    if git -C "$TARGET" fsck --no-progress --no-dangling >/dev/null 2>&1; then
        say "  intact ($(git -C "$TARGET" rev-list --count HEAD 2>/dev/null || echo 0) checkpoints)"
    else
        say "  DAMAGED: git fsck reports errors. The files are still there; the history is not trustworthy."
    fi
    say "  last checkpoint: $(git -C "$TARGET" log -1 --format='%h %ad %s' --date=short 2>/dev/null || echo none)"
    # What the archive adds over the history: everything the vault's .gitignore keeps out of a
    # checkpoint -- the trash and the private folders -- and anything written since the last one.
    UNTRACKED=$(git -C "$TARGET" status --porcelain --untracked-files=all 2>/dev/null | grep -c '^??' || true)
    say "  in the archive but not in that history: $UNTRACKED files"
fi

if [ -n "$VAULT" ]; then
    say ""
    say "against the live vault"
    ONLY_BACKUP=0; ONLY_VAULT=0; DIFFER=0
    # The same things the archive leaves out, or every run would report them as added since.
    OUT=$(diff -rq -x '.git' -x 'workspace*' -x 'file-recovery*'                     -x '*.tmp' -x '*.partial' -x '~$*' "$TARGET" "$VAULT" 2>/dev/null || true)
    if [ -n "$OUT" ]; then
        ONLY_BACKUP=$(printf '%s\n' "$OUT" | grep -c "^Only in $TARGET" || true)
        ONLY_VAULT=$(printf '%s\n' "$OUT" | grep -c "^Only in $VAULT" || true)
        DIFFER=$(printf '%s\n' "$OUT" | grep -c '^Files ' || true)
    fi
    say "  $DIFFER changed since the backup, $ONLY_VAULT added since, $ONLY_BACKUP gone from the vault"
    say "  (a vault in use differs from its backup; a vault that does not is one nobody edits)"
fi

if [ -n "$HVK_BIN" ] && [ -x "$HVK_BIN" ]; then
    say ""
    say "indexing the restored copy"
    # A throwaway index outside both vaults. The restored copy has a path of its own, so its
    # index would land in a directory of its own anyway (ADR-0002) -- this only avoids leaving
    # one behind after a rehearsal.
    IDX=$(mktemp -d)
    trap 'rm -rf "$IDX"' EXIT
    if "$HVK_BIN" --vault "$TARGET" --index "$IDX" scan >/dev/null 2>&1; then
        "$HVK_BIN" --vault "$TARGET" --index "$IDX" info | sed 's/^/  /'
    else
        say "  hvk could not index it. The files are restored; something about them is not a vault."
    fi
else
    say ""
    say "hvk is not installed here, so the restored copy was not indexed."
fi

say ""
say "Restored, and not in use. To make this the vault, see deploy/RESTORE.md:"
say "the syncer has to be stopped first, or every device gets whatever you do next."
