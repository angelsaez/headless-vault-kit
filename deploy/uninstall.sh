#!/bin/sh
# Remove exactly what install.sh added. The vault, the index and the rest of the machine are
# left untouched (ADR-0006).
set -eu

UNIT_DIR="$HOME/.config/systemd/user"
BIN_DIR="$HOME/.local/share/hvk/deploy-bin"
UNITS="obsidian-headless.service hvk-watch.service hvk-agent.service"
MARK_BEGIN="# >>> headless-vault-kit >>>"
MARK_END="# <<< headless-vault-kit <<<"

say() { printf '%s\n' "$*"; }

say "stopping and disabling units"
for unit in $UNITS; do
    if [ -e "$UNIT_DIR/$unit" ]; then
        systemctl --user stop "$unit" >/dev/null 2>&1 || true
        systemctl --user disable "$unit" >/dev/null 2>&1 || true
        rm -f "$UNIT_DIR/$unit"
        say "  removed $unit"
    fi
done
systemctl --user daemon-reload 2>/dev/null || true

say "removing the managed crontab block"
EXISTING=$(crontab -l 2>/dev/null || true)
if printf '%s\n' "$EXISTING" | grep -qF "$MARK_BEGIN"; then
    printf '%s\n' "$EXISTING" | awk -v b="$MARK_BEGIN" -v e="$MARK_END" '
        $0 == b { skip = 1 } skip != 1 { print } $0 == e { skip = 0 }' | crontab -
    say "  removed"
else
    say "  nothing to remove"
fi

say "removing helper scripts"
rm -rf "$BIN_DIR"

say ""
say "Left alone on purpose:"
say "  the vault and its git history"
say "  the index (delete it yourself if you want: hvk info shows where it is)"
say "  ~/.config/hvk/deploy.env"
say "  every runtime, package and firewall rule on this machine"
