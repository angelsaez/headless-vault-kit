#!/bin/sh
# Check whether this machine can run the phase 0 setup. Changes nothing (ADR-0006).
#
# Every failure here is something the operator fixes their own way. This script deliberately
# does not install runtimes or touch the firewall: on a server already running other things,
# that is how a deployment recipe breaks somebody else's service.
set -u

CONFIG="${HVK_DEPLOY_ENV:-$HOME/.config/hvk/deploy.env}"
FAILURES=0
WARNINGS=0

# Same parts as install.sh, so a machine that only needs some of them is not told it fails a
# prerequisite for something it will never install. A check that always fails gets ignored,
# and then the one that mattered is ignored too.
ONLY="sync agent watch git schedules"
SYSTEM=0
while [ $# -gt 0 ]; do
    case "$1" in
        --only) ONLY=$(printf '%s' "${2:?--only needs a list}" | tr ',' ' '); shift 2 ;;
        --system) SYSTEM=1; shift ;;
        --only=*) ONLY=$(printf '%s' "${1#--only=}" | tr ',' ' '); shift ;;
        -h|--help) echo "usage: preflight.sh [--only sync,agent,watch,git,schedules] [--system]"; exit 0 ;;
        *) echo "preflight.sh: unknown option $1" >&2; exit 2 ;;
    esac
done
wants() { case " $ONLY " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

say()  { printf '%s\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
bad()  { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
warn() { printf '  warn  %s\n' "$*"; WARNINGS=$((WARNINGS + 1)); }

say "configuration"
if [ -r "$CONFIG" ]; then
    ok "$CONFIG"
    # shellcheck disable=SC1090
    . "$CONFIG"
else
    bad "$CONFIG is missing. Copy deploy/deploy.env.example there and edit it."
    say ""
    say "$FAILURES problem(s). Nothing else can be checked without it."
    exit 1
fi

# systemd reads deploy.env itself and runs no shell over it, so "$HOME/vault" reaches the
# service as those eleven literal characters: the unit dies with status 127 and "not found",
# naming a path that looks perfectly correct in a terminal because the shell expands it there.
# It cost a real deployment an hour, so it is checked before anything else.
say ""
say "paths in $CONFIG"
# The RAW TEXT of the file, not the variables: this script sourced it, and the shell expanded
# $HOME on the way in. systemd will not, so what matters is what is written on the line.
while IFS= read -r line; do
    case "$line" in
        HVK_VAULT=*|HVK_BIN=*|OB_BIN=*|CLAUDE_BIN=*|HVK_INDEX_DIR=*|HVK_JOBS_DIR=*|HVK_JOBS_PROFILES=*) ;;
        *) continue ;;
    esac
    name=${line%%=*}
    value=$(printf '%s' "${line#*=}" | tr -d '"'"'"'"')
    [ -n "$value" ] || continue
    case "$value" in
        *'$'*|'~'*|*'`'*)
            bad "$name is not a literal path: $value"
            say "        systemd reads this file itself and expands nothing, so the service"
            say "        dies with status 127 and 'not found'. Paste the value: echo \$HOME" ;;
        *CHANGE-ME*)
            bad "$name still says CHANGE-ME. Edit $CONFIG before going on." ;;
        *) ok "$name: $value" ;;
    esac
done < "$CONFIG"

say ""
say "runtimes (prerequisites: none of these are installed for you)"

check_bin() {
    name=$1; path=$2; hint=$3
    if [ -z "$path" ]; then
        bad "$name: not set in $CONFIG"
    elif [ -x "$path" ]; then
        ok "$name: $path"
    elif command -v "$name" >/dev/null 2>&1; then
        bad "$name: $path is not executable, but one exists at $(command -v "$name"). Fix the path."
    else
        bad "$name: $path not found. $hint"
    fi
}

check_bin hvk    "${HVK_BIN:-}"    "Not on PyPI yet: see 'Getting hvk onto the server' in deploy/README.md"
wants sync  && check_bin ob     "${OB_BIN:-}"     "Obsidian Headless needs Node 22+; see github.com/obsidianmd/obsidian-headless"
wants agent && check_bin claude "${CLAUDE_BIN:-}" "Install Claude Code, then set the absolute path"

# bun and tmux belong to the agent session; git to the vault checkpoints. A machine that is
# not installing those parts does not need them, and telling it otherwise is noise.
if wants agent; then
    if command -v bun >/dev/null 2>&1; then
        ok "bun: $(command -v bun)"
    else
        bad "bun: not found. The Telegram channel plugin requires it (curl -fsSL https://bun.sh/install | bash)"
    fi

    if command -v tmux >/dev/null 2>&1; then
        ok "tmux: $(command -v tmux)"
    else
        bad "tmux: not found. The agent session runs inside it."
    fi
fi

if wants git; then
    if command -v git >/dev/null 2>&1; then
        ok "git: $(command -v git)"
    else
        bad "git: not found. Needed for the vault checkpoints."
    fi
fi

say ""
say "vault"
if [ -d "${HVK_VAULT:-}" ]; then
    ok "$HVK_VAULT"
    if [ -d "$HVK_VAULT/.obsidian" ]; then
        ok ".obsidian/ present, so hvk can find it without --vault"
    else
        warn "no .obsidian/ inside it. hvk works with --vault, but sync will not have set up yet."
    fi
    if [ -d "$HVK_VAULT/.git" ]; then
        ok "already a git repository"
    else
        warn "not a git repository yet; install.sh will offer to initialise it"
    fi
else
    bad "HVK_VAULT is not a directory: ${HVK_VAULT:-<unset>}"
fi

say ""
say "index location"
if [ -x "${HVK_BIN:-}" ] && [ -d "${HVK_VAULT:-}" ]; then
    if "$HVK_BIN" --vault "$HVK_VAULT" info >/dev/null 2>&1; then
        ok "an index exists and answers"
    else
        warn "no index yet, or it is stale. Run: $HVK_BIN --vault \"$HVK_VAULT\" scan"
    fi
fi

say ""
say "systemd user scope"
if ! command -v systemctl >/dev/null 2>&1; then
    bad "systemctl not found. These units need systemd."
elif ! systemctl --user show-environment >/dev/null 2>&1; then
    bad "no systemd user instance for $(id -un). Units cannot be managed with --user here."
else
    ok "systemctl --user works"
    LINGER=$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null || echo "unknown")
    if [ "$SYSTEM" = 1 ]; then
        # A system unit is started by the machine, not by a session, so lingering is not part
        # of the picture. Warning about it would send someone to fix a problem they do not have.
        ok "installing system-wide, so lingering does not apply"
    elif [ "$LINGER" = "yes" ]; then
        ok "lingering enabled, so the services survive a reboot with nobody logged in"
    else
        warn "lingering is off. Until someone runs: sudo loginctl enable-linger $(id -un)"
        warn "  the services will only run while you have a session open."
    fi
fi

say ""
say "exposure (reported, never changed)"
if command -v ss >/dev/null 2>&1; then
    LISTEN=$(ss -tlnH 2>/dev/null | awk '{print $4}' | grep -v '^127\.' | grep -v '^\[::1\]' | sort -u)
    if [ -z "$LISTEN" ]; then
        ok "nothing listening beyond loopback"
    else
        warn "listening on non-loopback addresses:"
        printf '        %s\n' $LISTEN
        warn "  nothing installed here opens a port; the plan asks for SSH only. Your call."
    fi
else
    warn "ss not available; cannot report listening sockets"
fi

say ""
if [ "$FAILURES" -gt 0 ]; then
    say "$FAILURES problem(s) and $WARNINGS warning(s). Fix the failures, then run install.sh."
    exit 1
fi
say "ready. $WARNINGS warning(s), none blocking."
