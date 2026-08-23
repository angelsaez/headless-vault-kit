#!/bin/sh
# Install the phase 0 units and cron entries into the current user's own scope.
#
# Nothing outside $HOME is written, no package is installed, no firewall rule is touched
# (ADR-0006). Running it twice changes nothing the second time, and uninstall.sh reverses it.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CONFIG_DIR="$HOME/.config/hvk"
CONFIG="${HVK_DEPLOY_ENV:-$CONFIG_DIR/deploy.env}"
UNIT_DIR="$HOME/.config/systemd/user"
BIN_DIR="$HOME/.local/share/hvk/deploy-bin"
UNITS="obsidian-headless.service hvk-watch.service hvk-agent.service"
MARK_BEGIN="# >>> headless-vault-kit >>>"
MARK_END="# <<< headless-vault-kit <<<"

FORCE=0
DRY=0
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        --dry-run) DRY=1 ;;
        -h|--help)
            cat <<'USAGE'
usage: install.sh [--force] [--dry-run]

  --force    replace units that exist with different contents
  --dry-run  say what would change, write nothing
USAGE
            exit 0 ;;
        *) echo "install.sh: unknown option $arg" >&2; exit 2 ;;
    esac
done

say() { printf '%s\n' "$*"; }
act() { if [ "$DRY" = 1 ]; then printf '  would %s\n' "$*"; else printf '  %s\n' "$*"; fi; }

[ -r "$CONFIG" ] || {
    say "No configuration at $CONFIG."
    say "Copy it and edit it first:"
    say "  mkdir -p $CONFIG_DIR && cp $HERE/deploy.env.example $CONFIG"
    exit 2
}
# shellcheck disable=SC1090
. "$CONFIG"

# The units carry EnvironmentFile=%h/.config/hvk/deploy.env as a literal, because systemd has
# no way to learn where else you keep it. So if HVK_DEPLOY_ENV pointed somewhere else, the
# install would succeed and every service would then fail at start with "Failed to load
# environment files" -- which names the file but not the reason. Put a copy where the units
# look, and say so.
CANONICAL="$CONFIG_DIR/deploy.env"
if [ "$CONFIG" != "$CANONICAL" ]; then
    say "configuration"
    act "copy $CONFIG -> $CANONICAL (the path baked into the units)"
    [ "$DRY" = 1 ] || { mkdir -p "$CONFIG_DIR"; cp "$CONFIG" "$CANONICAL"; }
    say ""
fi

# --- units ---------------------------------------------------------------------------------

say "systemd user units -> $UNIT_DIR"
[ "$DRY" = 1 ] || mkdir -p "$UNIT_DIR"
CHANGED=0
for unit in $UNITS; do
    source_file="$HERE/systemd/$unit"
    target="$UNIT_DIR/$unit"
    if [ -e "$target" ]; then
        if cmp -s "$source_file" "$target"; then
            act "unchanged: $unit"
            continue
        fi
        if [ "$FORCE" != 1 ]; then
            say "  REFUSING: $target exists and differs."
            say "    Something else may own it. Compare with:"
            say "      diff $target $source_file"
            say "    Then re-run with --force to replace it."
            exit 3
        fi
        act "replace: $unit"
    else
        act "install: $unit"
    fi
    # 644 explicitly: a unit copied off a Windows mount arrives world-writable and
    # executable, and systemd complains about both.
    [ "$DRY" = 1 ] || { cp "$source_file" "$target"; chmod 644 "$target"; }
    CHANGED=1
done

# --- helper scripts ------------------------------------------------------------------------

say ""
say "scripts -> $BIN_DIR"
# A bare "Permission denied" from mkdir under set -e says nothing about which of the two
# usual causes it is, and both are common on a machine someone else set up.
if [ "$DRY" != 1 ] && ! mkdir -p "$BIN_DIR" 2>/dev/null; then
    say "  cannot create $BIN_DIR."
    say "    Check that you own the directories above it: ls -ld $HOME/.local $HOME/.local/share"
    say "    Everything here is user-scope, so nothing in your home should be owned by root."
    exit 4
fi
for script in vault-autocommit.sh; do
    if [ -e "$BIN_DIR/$script" ] && cmp -s "$HERE/bin/$script" "$BIN_DIR/$script"; then
        act "unchanged: $script"
    else
        act "install: $script"
        [ "$DRY" = 1 ] || { cp "$HERE/bin/$script" "$BIN_DIR/$script"; chmod +x "$BIN_DIR/$script"; }
    fi
done

# --- the vault's own repository -------------------------------------------------------------

say ""
say "vault checkpoints"
if [ ! -d "$HVK_VAULT/.git" ]; then
    act "git init in $HVK_VAULT"
    if [ "$DRY" != 1 ]; then
        git -C "$HVK_VAULT" init --quiet
        git -C "$HVK_VAULT" config commit.gpgsign false
    fi
else
    act "already a git repository"
fi
if [ ! -e "$HVK_VAULT/.gitignore" ]; then
    act "install .gitignore into the vault"
    [ "$DRY" = 1 ] || cp "$HERE/vault.gitignore.example" "$HVK_VAULT/.gitignore"
else
    act "vault already has a .gitignore, leaving it alone"
fi

# --- crontab -------------------------------------------------------------------------------
# The user's own crontab, never /etc/cron.d. Existing entries are preserved: only the block
# between our markers is rewritten.

say ""
say "crontab (user scope)"
EXISTING=$(crontab -l 2>/dev/null || true)
BLOCK=$(cat <<CRON
$MARK_BEGIN
# Managed by deploy/install.sh. Edit deploy.env, not these lines.
*/30 * * * * $BIN_DIR/vault-autocommit.sh >/dev/null 2>&1
17 4 * * * $HVK_BIN --vault "$HVK_VAULT" verify >/dev/null 2>&1
$MARK_END
CRON
)
KEPT=$(printf '%s\n' "$EXISTING" | awk -v b="$MARK_BEGIN" -v e="$MARK_END" '
    $0 == b { skip = 1 } skip != 1 { print } $0 == e { skip = 0 }')
NEW=$(printf '%s\n%s\n' "$(printf '%s' "$KEPT" | sed '/^$/d')" "$BLOCK")

if printf '%s\n' "$EXISTING" | grep -qF "$MARK_BEGIN" && \
   [ "$(printf '%s' "$EXISTING" | tr -d '[:space:]')" = "$(printf '%s' "$NEW" | tr -d '[:space:]')" ]; then
    act "unchanged"
else
    act "write the managed block (auto-commit every 30 min, verify nightly at 04:17)"
    [ "$DRY" = 1 ] || printf '%s\n' "$NEW" | crontab -
fi

# --- enable ---------------------------------------------------------------------------------

say ""
if [ "$DRY" = 1 ]; then
    say "dry run: nothing was written."
    exit 0
fi

systemctl --user daemon-reload
for unit in $UNITS; do
    systemctl --user enable "$unit" >/dev/null 2>&1 || true
done
say "units installed and enabled. They are not started yet."
say ""
say "Before starting them, once, by hand:"
say "  1. $OB_BIN login          and  $OB_BIN sync-setup --vault \"\${OB_VAULT_NAME:-\$(basename \"$HVK_VAULT\")}\""
say "  2. sudo loginctl enable-linger $(id -un)   so they survive a reboot"
say ""
say "Then:"
say "  systemctl --user start obsidian-headless hvk-watch hvk-agent"
say "  systemctl --user status hvk-watch        # note the --user, or it reports 'not found'"
[ "$CHANGED" = 1 ] || say ""
