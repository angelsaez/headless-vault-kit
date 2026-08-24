#!/bin/sh
# Remove exactly what install.sh added. The vault, the index and the rest of the machine are
# left untouched (ADR-0006).
set -eu

BIN_DIR="$HOME/.local/share/hvk/deploy-bin"
UNITS="obsidian-headless.service hvk-watch.service hvk-agent.service"
MARK_BEGIN="# >>> headless-vault-kit >>>"
MARK_END="# <<< headless-vault-kit <<<"

say() { printf '%s\n' "$*"; }

# Both scopes are swept, always, without asking which was used. Whoever uninstalls has usually
# forgotten -- and a leftover unit that still starts at boot is exactly the kind of thing that
# gets blamed on the next thing installed.
say "stopping and disabling units"
for scope in user system; do
    if [ "$scope" = user ]; then
        dir="$HOME/.config/systemd/user"; ctl="systemctl --user"; remove="rm -f"
    else
        dir="/etc/systemd/system"; ctl="sudo systemctl"; remove="sudo rm -f"
    fi
    for unit in $UNITS; do
        [ -e "$dir/$unit" ] || continue
        $ctl stop "$unit" >/dev/null 2>&1 || true
        $ctl disable "$unit" >/dev/null 2>&1 || true
        $remove "$dir/$unit"
        say "  removed $unit ($scope scope)"
    done
    $ctl daemon-reload >/dev/null 2>&1 || true
done

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
say "  every backup archive already written (BACKUP_DIR is yours, not ours to empty)"
say "  the index (delete it yourself if you want: hvk info shows where it is)"
say "  ~/.config/hvk/deploy.env"
say "  every runtime, package and firewall rule on this machine"
