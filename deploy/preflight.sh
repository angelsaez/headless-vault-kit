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

check_bin hvk    "${HVK_BIN:-}"    "Install with: uv tool install hvk"
check_bin ob     "${OB_BIN:-}"     "Obsidian Headless needs Node 22+; see github.com/obsidianmd/obsidian-headless"
check_bin claude "${CLAUDE_BIN:-}" "Install Claude Code, then set the absolute path"

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

if command -v git >/dev/null 2>&1; then
    ok "git: $(command -v git)"
else
    bad "git: not found. Needed for the vault checkpoints."
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
    if [ "$LINGER" = "yes" ]; then
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
