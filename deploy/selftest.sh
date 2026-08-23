#!/bin/bash
# Exercise install.sh, uninstall.sh and the units against a throwaway vault and stub binaries.
#
# Needs Linux with a systemd user instance, tmux and git. Nothing real is touched: the vault,
# the runtimes and the services are all fakes in a temporary directory, and the crontab is
# saved and restored. Run it on any machine before trusting the deployment there.
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FAILS=0
check() {
    if eval "$2" >/dev/null 2>&1; then printf '  ok    %s\n' "$1"
    else printf '  FAIL  %s\n' "$1"; FAILS=$((FAILS + 1)); fi
}

command -v systemctl >/dev/null || { echo "selftest: needs systemd"; exit 1; }
systemctl --user show-environment >/dev/null 2>&1 || { echo "selftest: no systemd user instance"; exit 1; }
command -v tmux >/dev/null || { echo "selftest: needs tmux"; exit 1; }
command -v git  >/dev/null || { echo "selftest: needs git"; exit 1; }

LAB=$(mktemp -d)
export HVK_DEPLOY_ENV="$LAB/deploy.env"
mkdir -p "$LAB/vault/.obsidian" "$LAB/bin"
echo '{}' > "$LAB/vault/.obsidian/app.json"
echo '# A note' > "$LAB/vault/Note.md"
printf '#!/bin/sh\nexit 0\n' > "$LAB/bin/ob"; chmod +x "$LAB/bin/ob"
# The hvk stub records how it was called, so the scheduled tasks can be judged on what they
# asked for and not only on whether they exited zero. The interesting assertion is a NEGATIVE
# one: that the runner starts nothing until it has been told where to look.
printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s/hvk-calls.log"\nexit 0\n' "$LAB" > "$LAB/bin/hvk"
chmod +x "$LAB/bin/hvk"
# The claude stub has to stay alive. A command that exits takes the tmux session with it, and
# the test would then be measuring the stub rather than the unit.
printf '#!/bin/sh\nsleep 300\n' > "$LAB/bin/claude"; chmod +x "$LAB/bin/claude"

cat > "$HVK_DEPLOY_ENV" <<EOF
HVK_VAULT="$LAB/vault"
HVK_BIN="$LAB/bin/hvk"
OB_BIN="$LAB/bin/ob"
CLAUDE_BIN="$LAB/bin/claude"
TMUX_SESSION="hvk-selftest"
CLAUDE_CHANNELS="plugin:telegram@example"
AUTOCOMMIT_ENABLED=1
AUTOCOMMIT_MESSAGE="checkpoint"
EOF

# An unrelated crontab entry, to prove the installer leaves other people's lines alone.
CRON_BACKUP=$(crontab -l 2>/dev/null || true)
printf '%s\n' "# someone else's job" "0 3 * * * /bin/true" | crontab -
restore() {
    systemctl --user stop hvk-agent.service >/dev/null 2>&1
    tmux kill-session -t hvk-selftest >/dev/null 2>&1
    "$HERE/uninstall.sh" >/dev/null 2>&1
    if [ -n "$CRON_BACKUP" ]; then printf '%s\n' "$CRON_BACKUP" | crontab -
    else crontab -r >/dev/null 2>&1; fi
    rm -rf "$LAB"
}
trap restore EXIT

echo "a dry run writes nothing"
"$HERE/install.sh" --dry-run >"$LAB/dry.txt" 2>&1
check "it reports what it would do"  "[ -s '$LAB/dry.txt' ]"
check "no unit installed"            "[ ! -e \"\$HOME/.config/systemd/user/hvk-watch.service\" ]"
check "crontab untouched"            "crontab -l | grep -q \"someone else\""
check "vault not turned into a repo" "[ ! -d '$LAB/vault/.git' ]"

echo ""
echo "installing"
"$HERE/install.sh" >"$LAB/install.txt" 2>&1 || { echo "  FAIL  install.sh exited non-zero"; cat "$LAB/install.txt"; FAILS=$((FAILS+1)); }
for unit in obsidian-headless hvk-watch hvk-agent; do
    check "unit present: $unit"      "[ -f \"\$HOME/.config/systemd/user/$unit.service\" ]"
done
check "units are mode 644"           "[ \"\$(stat -c %a \"\$HOME/.config/systemd/user/hvk-watch.service\")\" = 644 ]"
check "systemd parses them"          "systemctl --user cat hvk-watch.service"
check "vault is a git repository"    "[ -d '$LAB/vault/.git' ]"
check "vault .gitignore installed"   "[ -f '$LAB/vault/.gitignore' ]"
check "managed cron block written"   "crontab -l | grep -q headless-vault-kit"
check "other cron lines survived"    "crontab -l | grep -q \"someone else\""
check "autocommit script installed"  "[ -x \"\$HOME/.local/share/hvk/deploy-bin/vault-autocommit.sh\" ]"
check "schedule script installed"    "[ -x \"\$HOME/.local/share/hvk/deploy-bin/hvk-schedule.sh\" ]"
check "views are scheduled"          "crontab -l | grep -q 'hvk-schedule.sh views'"
check "the runner is scheduled"      "crontab -l | grep -q 'hvk-schedule.sh jobs'"

echo ""
echo "running it again changes nothing"
"$HERE/install.sh" >"$LAB/again.txt" 2>&1
check "units reported unchanged"     "grep -q 'unchanged: hvk-watch.service' '$LAB/again.txt'"
check "cron block still appears once" "[ \"\$(crontab -l | grep -c 'headless-vault-kit >>>')\" = 1 ]"

echo ""
echo "it refuses to overwrite a unit it does not recognise"
echo "# edited by something else" >> "$HOME/.config/systemd/user/hvk-watch.service"
"$HERE/install.sh" >"$LAB/refuse.txt" 2>&1; rc=$?
check "exits 3"                      "[ $rc -eq 3 ]"
check "says so plainly"              "grep -q REFUSING '$LAB/refuse.txt'"
check "left the file alone"          "grep -q 'edited by something else' \"\$HOME/.config/systemd/user/hvk-watch.service\""
"$HERE/install.sh" --force >/dev/null 2>&1
check "--force replaces it"          "! grep -q 'edited by something else' \"\$HOME/.config/systemd/user/hvk-watch.service\""

echo ""
echo "the scheduled tasks"
SCHEDULE="$HOME/.local/share/hvk/deploy-bin/hvk-schedule.sh"
: > "$LAB/hvk-calls.log"
check "an unknown task is refused"   "! '$SCHEDULE' nonsense 2>/dev/null"

"$SCHEDULE" views
check "views calls hvk"              "grep -q 'views --apply' '$LAB/hvk-calls.log'"

# The guarantee of ADR-0009, checked where it actually matters: with no directories declared
# the runner is scheduled every minute and still starts nothing at all.
: > "$LAB/hvk-calls.log"
"$SCHEDULE" jobs
check "no dirs declared, no runner"  "[ ! -s '$LAB/hvk-calls.log' ]"

mkdir -p "$LAB/vault/Orders" "$LAB/profiles"
printf 'HVK_JOBS_DIR="Orders"\nHVK_JOBS_PROFILES="%s/profiles"\n' "$LAB" >> "$HVK_DEPLOY_ENV"
"$SCHEDULE" jobs
check "declaring them turns it on"   "grep -q 'jobs --dir Orders' '$LAB/hvk-calls.log'"
check "and the profiles go with it"  "grep -q -- '--profiles $LAB/profiles' '$LAB/hvk-calls.log'"

echo ""
echo "vault checkpoints"
AUTOCOMMIT="$HOME/.local/share/hvk/deploy-bin/vault-autocommit.sh"
"$AUTOCOMMIT"
check "first run commits"            "git -C '$LAB/vault' log --oneline | grep -q checkpoint"
BEFORE=$(git -C "$LAB/vault" rev-list --count HEAD)
"$AUTOCOMMIT"
check "no changes, no commit"        "[ \"\$(git -C '$LAB/vault' rev-list --count HEAD)\" = '$BEFORE' ]"
echo "more" >> "$LAB/vault/Note.md"
"$AUTOCOMMIT"
check "a change does commit"         "[ \"\$(git -C '$LAB/vault' rev-list --count HEAD)\" -gt '$BEFORE' ]"
mkdir -p "$LAB/vault/_PRIVATE" && echo secret > "$LAB/vault/_PRIVATE/token.md"
"$AUTOCOMMIT"
check "_PRIVATE never committed"     "! git -C '$LAB/vault' ls-files | grep -q _PRIVATE"

echo ""
echo "the agent unit really starts"
systemctl --user start hvk-agent.service >/dev/null 2>&1
sleep 2
check "unit is active"               "[ \"\$(systemctl --user is-active hvk-agent.service)\" = active ]"
check "tmux session is alive"        "tmux has-session -t hvk-selftest"
systemctl --user stop hvk-agent.service >/dev/null 2>&1
sleep 1
check "stopping tears it down"       "! tmux has-session -t hvk-selftest"

echo ""
echo "selective install, for a machine that already runs some of this itself"
"$HERE/uninstall.sh" >/dev/null 2>&1
"$HERE/install.sh" --only watch,schedules >"$LAB/only.txt" 2>&1
check "installs the unit asked for"  "[ -f \"$HOME/.config/systemd/user/hvk-watch.service\" ]"
check "and not the ones it was not"  "[ ! -e \"$HOME/.config/systemd/user/obsidian-headless.service\" ] && [ ! -e \"$HOME/.config/systemd/user/hvk-agent.service\" ]"
check "no auto-commit line in cron"  "! crontab -l | grep -q vault-autocommit"
check "the schedules are there"      "crontab -l | grep -q 'hvk-schedule.sh jobs'"
check "an unknown part is refused"   "! '$HERE/install.sh' --only nonsense >/dev/null 2>&1"
"$HERE/uninstall.sh" >/dev/null 2>&1

echo ""
echo "uninstalling"
"$HERE/uninstall.sh" >/dev/null 2>&1
check "units removed"                "[ ! -e \"\$HOME/.config/systemd/user/hvk-watch.service\" ]"
check "cron block removed"           "! crontab -l 2>/dev/null | grep -q headless-vault-kit"
check "other cron lines survived"    "crontab -l 2>/dev/null | grep -q \"someone else\""
check "vault untouched"              "[ -f '$LAB/vault/Note.md' ] && [ -d '$LAB/vault/.git' ]"

echo ""
if [ "$FAILS" = 0 ]; then echo "all checks passed"; else echo "$FAILS check(s) failed"; fi
exit "$FAILS"
