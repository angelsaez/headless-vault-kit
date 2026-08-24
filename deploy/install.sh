#!/bin/sh
# Install the phase 0 units and cron entries.
#
# By default everything goes into the current user's own scope: nothing outside $HOME is
# written, no package is installed, no firewall rule is touched (ADR-0006). Running it twice
# changes nothing the second time, and uninstall.sh reverses it.
#
# Two options exist for servers that already run something of their own, which is the normal
# case rather than the exception (ADR-0010):
#
#   --only LIST   install just those parts, so nothing already provided is duplicated
#   --system      install the units system-wide instead of user-scope, for a machine whose
#                 own services are system units and where nobody stays logged in
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CONFIG_DIR="$HOME/.config/hvk"
CONFIG="${HVK_DEPLOY_ENV:-$CONFIG_DIR/deploy.env}"
BIN_DIR="$HOME/.local/share/hvk/deploy-bin"
MARK_BEGIN="# >>> headless-vault-kit >>>"
MARK_END="# <<< headless-vault-kit <<<"

FORCE=0
DRY=0
SYSTEM=0
ONLY="sync agent watch git schedules backup"
ALL_PARTS="sync agent watch git schedules backup"

while [ $# -gt 0 ]; do
    case "$1" in
        --force) FORCE=1; shift ;;
        --dry-run) DRY=1; shift ;;
        --system) SYSTEM=1; shift ;;
        --only) ONLY=$(printf '%s' "${2:?--only needs a list}" | tr ',' ' '); shift 2 ;;
        --only=*) ONLY=$(printf '%s' "${1#--only=}" | tr ',' ' '); shift ;;
        -h|--help)
            cat <<'USAGE'
usage: install.sh [--only LIST] [--system] [--force] [--dry-run]

  --only LIST  comma-separated parts to install; the rest is left alone. Use this when the
               machine already provides something itself, so nothing ends up running twice.
                 sync       obsidian-headless.service
                 agent      hvk-agent.service (Claude Code in tmux)
                 watch      hvk-watch.service (the index, kept current)
                 git        checkpoints of the vault: git init, .gitignore, auto-commit
                 schedules  nightly verify, materialised views, the order-note runner
                 backup     the daily archive of the vault, and the restore script
               Default: all six.
  --system     install units into /etc/systemd/system rather than the user scope. Needs sudo,
               and survives a reboot without lingering. For machines whose own services are
               system units (ADR-0010).
  --force      replace units that exist with different contents
  --dry-run    say what would change, write nothing
USAGE
            exit 0 ;;
        *) echo "install.sh: unknown option $1" >&2; exit 2 ;;
    esac
done

for part in $ONLY; do
    case " $ALL_PARTS " in
        *" $part "*) ;;
        *) echo "install.sh: unknown part '$part'. Known: $(echo "$ALL_PARTS" | tr ' ' ',')" >&2
           exit 2 ;;
    esac
done
wants() { case " $ONLY " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

UNITS=""
wants sync  && UNITS="$UNITS obsidian-headless.service"
wants watch && UNITS="$UNITS hvk-watch.service"
wants agent && UNITS="$UNITS hvk-agent.service"

if [ "$SYSTEM" = 1 ]; then
    UNIT_DIR="/etc/systemd/system"
    SUDO="sudo"
    SYSTEMCTL="sudo systemctl"
else
    UNIT_DIR="$HOME/.config/systemd/user"
    SUDO=""
    SYSTEMCTL="systemctl --user"
fi

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

# A system unit differs from the user one in three exact ways, applied here rather than kept
# as a second copy of every file that would drift: %h means nothing outside the user manager,
# a system service has to say who it runs as, and it is wanted by a different target.
prepare_unit() {
    if [ "$SYSTEM" = 1 ]; then
        awk -v home="$HOME" -v user="$(id -un)" -v group="$(id -gn)" '
            { gsub(/%h/, home) }
            /^WantedBy=default\.target$/ { print "WantedBy=multi-user.target"; next }
            { print }
            /^\[Service\]$/ { print "User=" user; print "Group=" group }
        ' "$1"
    else
        cat "$1"
    fi
}

if [ -z "$UNITS" ]; then
    say "systemd units: none requested"
else
say "systemd units -> $UNIT_DIR"
[ "$DRY" = 1 ] || $SUDO mkdir -p "$UNIT_DIR"
CHANGED=0
for unit in $UNITS; do
    source_file="$HERE/systemd/$unit"
    staged=$(mktemp); prepare_unit "$source_file" > "$staged"
    target="$UNIT_DIR/$unit"
    if [ -e "$target" ]; then
        if cmp -s "$staged" "$target"; then
            act "unchanged: $unit"
            rm -f "$staged"
            continue
        fi
        if [ "$FORCE" != 1 ]; then
            say "  REFUSING: $target exists and differs."
            say "    Something else may own it. Compare with:"
            say "      diff $target $source_file"
            say "    Then re-run with --force to replace it."
            rm -f "$staged"
            exit 3
        fi
        act "replace: $unit"
    else
        act "install: $unit"
    fi
    # 644 explicitly: a unit copied off a Windows mount arrives world-writable and
    # executable, and systemd complains about both.
    [ "$DRY" = 1 ] || { $SUDO cp "$staged" "$target"; $SUDO chmod 644 "$target"; }
    rm -f "$staged"
    CHANGED=1
done
fi

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
SCRIPTS=""
wants git       && SCRIPTS="$SCRIPTS vault-autocommit.sh"
wants schedules && SCRIPTS="$SCRIPTS hvk-schedule.sh"
# The restore script is installed even though nothing calls it, and that is the point: the day
# it is wanted, going to fetch it from a repository is the last thing anyone wants to be doing.
wants backup    && SCRIPTS="$SCRIPTS vault-backup.sh vault-restore.sh"
for script in $SCRIPTS; do
    if [ -e "$BIN_DIR/$script" ] && cmp -s "$HERE/bin/$script" "$BIN_DIR/$script"; then
        act "unchanged: $script"
    else
        act "install: $script"
        [ "$DRY" = 1 ] || { cp "$HERE/bin/$script" "$BIN_DIR/$script"; chmod +x "$BIN_DIR/$script"; }
    fi
done

# --- the vault's own repository -------------------------------------------------------------

say ""
if ! wants git; then
    say "vault checkpoints: skipped (--only)"
else
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
fi

# --- crontab -------------------------------------------------------------------------------
# The user's own crontab, never /etc/cron.d. Existing entries are preserved: only the block
# between our markers is rewritten.

say ""
say "crontab (user scope)"
EXISTING=$(crontab -l 2>/dev/null || true)
LINES=""
wants git && LINES="$LINES
*/30 * * * * $BIN_DIR/vault-autocommit.sh >/dev/null 2>&1"
wants schedules && LINES="$LINES
17 4 * * * $HVK_BIN --vault \"$HVK_VAULT\" verify >/dev/null 2>&1
*/${VIEWS_EVERY_MINUTES:-30} * * * * $BIN_DIR/hvk-schedule.sh views
* * * * * $BIN_DIR/hvk-schedule.sh jobs"
# Declaring a destination is what turns the backup on, the way declaring a jobs directory turns
# the runner on (ADR-0009). Nobody gets a daily archive of a 40 GB vault onto a disk they did
# not choose, and nobody gets a cron entry that fails every night for want of one.
wants backup && [ -n "${BACKUP_DIR:-}" ] && LINES="$LINES
${BACKUP_CRON:-41 3 * * *} $BIN_DIR/vault-backup.sh"
# --only rewrites this block from scratch rather than merging into it, so a part left out of
# the list loses its entries -- silently, on a machine where they were already working. Adding
# one part to a server means naming the others too. Say what is about to disappear.
CURRENT=$(printf '%s
' "$EXISTING" | awk -v b="$MARK_BEGIN" -v e="$MARK_END" '
    $0 == b { inside = 1; next } $0 == e { inside = 0 } inside && $0 !~ /^#/ && NF { print }')
DROPPED=""
OLDIFS=$IFS; IFS='
'
for line in $CURRENT; do
    case "$LINES" in *"$line"*) ;; *) DROPPED="$DROPPED$line
" ;; esac
done
IFS=$OLDIFS
if [ -n "$DROPPED" ]; then
    say "  NOTE: these entries are scheduled now and will not be after this run:"
    printf '%s' "$DROPPED" | sed 's/^/    /'
    say "    Name every part you want, not only the new one: --only watch,schedules,backup"
fi

BLOCK=$(printf '%s
%s%s
%s
'     "$MARK_BEGIN" "# Managed by deploy/install.sh. Edit deploy.env, not these lines."     "$LINES" "$MARK_END")
KEPT=$(printf '%s\n' "$EXISTING" | awk -v b="$MARK_BEGIN" -v e="$MARK_END" '
    $0 == b { skip = 1 } skip != 1 { print } $0 == e { skip = 0 }')
NEW=$(printf '%s\n%s\n' "$(printf '%s' "$KEPT" | sed '/^$/d')" "$BLOCK")

if printf '%s\n' "$EXISTING" | grep -qF "$MARK_BEGIN" && \
   [ "$(printf '%s' "$EXISTING" | tr -d '[:space:]')" = "$(printf '%s' "$NEW" | tr -d '[:space:]')" ]; then
    act "unchanged"
else
    act "write the managed block ($(printf '%s' "$LINES" | grep -c . ) entries)"
    [ "$DRY" = 1 ] || printf '%s\n' "$NEW" | crontab -
fi

# --- enable ---------------------------------------------------------------------------------

say ""
if [ "$DRY" = 1 ]; then
    say "dry run: nothing was written."
    exit 0
fi

if [ -n "$UNITS" ]; then
    $SYSTEMCTL daemon-reload
    for unit in $UNITS; do
        $SYSTEMCTL enable "$unit" >/dev/null 2>&1 || true
    done
    say "units installed and enabled. They are not started yet."
else
    say "no units requested; nothing to enable."
fi
say ""
say "Before starting them, once, by hand:"
STEP=1
if wants sync; then
    say "  $STEP. $OB_BIN login          and  $OB_BIN sync-setup --vault \"\${OB_VAULT_NAME:-\$(basename \"$HVK_VAULT\")}\""
    STEP=$((STEP + 1))
fi
# Only user-scope services need lingering. A system unit is started by the machine, not by a
# session, so saying this there would send someone to fix a problem they do not have.
if [ "$SYSTEM" != 1 ]; then
    say "  $STEP. sudo loginctl enable-linger $(id -un)   so they survive a reboot"
    STEP=$((STEP + 1))
fi
[ "$STEP" = 1 ] && say "  (nothing -- what you installed needs no manual step)"

if [ -n "$UNITS" ]; then
    STARTABLE=$(printf '%s' "$UNITS" | sed 's/\.service//g')
    say ""
    say "Then:"
    if [ "$SYSTEM" = 1 ]; then
        say "  sudo systemctl start$STARTABLE"
        say "  systemctl status$(printf '%s' "$STARTABLE" | awk '{print " "$1}')"
    else
        say "  systemctl --user start$STARTABLE"
        say "  systemctl --user status$(printf '%s' "$STARTABLE" | awk '{print " "$1}')   # note the --user, or it reports 'not found'"
    fi
fi
[ "$CHANGED" = 1 ] || say ""
