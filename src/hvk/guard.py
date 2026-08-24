"""A PreToolUse hook: what an agent must not do to a vault (phase 6).

The permission profiles of ADR-0009 bound what an order-note's agent may do. They say nothing
about the interactive session — the one on Telegram, which a person talks to and which
therefore runs with more freedom on purpose. Two things should be true of both:

* **A delete is a move to `.trash/`.** Obsidian works that way, the write layer works that way
  (ADR-0007), and an agent reaching for `rm` should be stopped rather than trusted to remember.
* **Some folders are not the agent's business.** Which ones is nobody's business but the
  vault owner's, so there is no default list: unset means the rule does not apply.

This runs as a hook rather than as a rule inside hvk because the thing to constrain is the
agent's own tools. `hvk` never deletes anything; `rm` in a Bash call does.

The contract is Claude Code's: the tool call arrives as JSON on stdin, and a decision goes back
as JSON on stdout. Anything this cannot parse is allowed through — a hook that fails closed on
its own bugs turns a bad parse into a broken session, and the failure mode of a *missed* deny
is the status quo without the hook at all.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

# Commands that remove a file for good. `mv` is deliberately absent: moving things around is
# what a vault is for, and the destination is what matters, not the verb.
DESTRUCTIVE = ("rm", "rmdir", "shred", "unlink")
# The tools that put bytes on disk at a path they name. Bash is deliberately not among them:
# a redirection cannot be found reliably in a command line, and pretending otherwise would be
# the protection-that-only-looks-like-protection this project keeps refusing to ship.
WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")
# `find ... -delete` and `find ... -exec rm` walk past a check that only looks at argv[0].
FIND_DELETE = re.compile(r"\bfind\b.*(-delete\b|-exec\s+rm\b)")

ALLOW, DENY = "allow", "deny"


@dataclass
class Decision:
    permission: str
    reason: str = ""
    # What fired and what it matched. Carried on the decision rather than parsed back out of
    # the reason, because the audit line is written from these two fields (ADR-0014).
    rule: str = ""
    match: str = ""

    def as_hook_output(self) -> dict:
        if self.permission == ALLOW:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": DENY,
                "permissionDecisionReason": self.reason,
            }
        }


def _paths_in(command: str) -> list:
    """Every argument of a shell command that could be a path. Best effort, on purpose.

    A hook cannot become a shell parser, and it does not need to be one: the question is
    whether a protected name appears anywhere in the command, and a name that appears is worth
    stopping over even if this cannot prove it is the target.
    """
    try:
        return [word for word in shlex.split(command) if not word.startswith("-")]
    except ValueError:                      # unbalanced quotes: fall back to whitespace
        return command.split()


def _touches(value: str, protected: list) -> str | None:
    """The first protected path *value* mentions, or None."""
    lowered = value.replace("\\", "/").lower()
    for name in protected:
        needle = name.replace("\\", "/").lower().strip("/")
        if not needle:
            continue
        if lowered == needle or f"/{needle}/" in f"/{lowered}/" or lowered.startswith(needle + "/"):
            return name
    return None


def _outside_vault(value: str, vault: Path):
    """Where a write to *value* would land, if that is outside *vault*. None if it is inside.

    Relative paths resolve against the vault because that is the agent's working directory.
    Resolving rather than comparing text is the point: ``../../.ssh/authorized_keys`` is inside
    the vault as a string and outside it as a location.
    """
    try:
        target = Path(value)
        if not target.is_absolute():
            target = vault / target
        landing = target.resolve()
        root = vault.resolve()
    except (OSError, ValueError, RuntimeError):     # unresolvable, or a symlink loop
        return None
    if landing == root or root in landing.parents:
        return None
    return landing


def _destructive_word(command: str):
    """The word that removes a file, or None. Named rather than counted, so the record can
    say which spelling was used without keeping the command line itself."""
    if FIND_DELETE.search(command):
        return "find"
    # Each segment of a pipeline or && chain is its own command, and only its first word is
    # the program being run.
    for segment in re.split(r"[;&|]+", command):
        words = segment.split()
        if words and Path(words[0]).name in DESTRUCTIVE:
            return Path(words[0]).name
    return None


def decide(payload: dict, *, vault: Path | None = None, protected: list | None = None) -> Decision:
    """What to do about one tool call."""
    protected = [p for p in (protected or []) if p.strip()]
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return Decision(ALLOW)

    command = tool_input.get("command") if isinstance(tool_input.get("command"), str) else ""
    named = [
        value for key, value in tool_input.items()
        if key in ("file_path", "path", "notebook_path") and isinstance(value, str)
    ]

    # 1. Protected folders, whatever the tool. Checked first: a protected path is off limits
    #    even to a read, which is the point of calling it protected rather than read-only.
    for value in [*named, *(_paths_in(command) if command else [])]:
        hit = _touches(value, protected)
        if hit:
            return Decision(
                DENY,
                f"{hit} is a protected folder in this vault, and this tool call names it "
                f"({value}). Nothing in there is the agent's to read or change.",
                rule="protected", match=hit,
            )

    # 2. A write that lands outside the vault. The vault is the whole job; everything else on
    #    the machine is somebody else's. This is the rule that answers the vault's own content
    #    being untrusted input: a note can ask an agent to write, and ~/.ssh/authorized_keys,
    #    a systemd unit and the agent's own settings.json are all one Write call away.
    #
    #    Reads are deliberately left alone. Refusing those breaks ordinary work -- a man page,
    #    a config file someone asked about -- and reading is not how a vault agent damages a
    #    machine.
    if vault is not None and tool in WRITE_TOOLS:
        for value in named:
            landing = _outside_vault(value, vault)
            if landing is not None:
                return Decision(
                    DENY,
                    f"{landing} is outside the vault ({vault}), and writing outside it is not "
                    f"this agent's business. Anything that has to leave the vault is a job for "
                    f"whoever runs the server, by hand.",
                    rule="outside-vault", match=str(landing),
                )

    # 3. Deletion. Only Bash can do it: every other tool either writes or reads.
    destructive = _destructive_word(command) if tool == "Bash" and command else None
    if destructive:
        return Decision(
            DENY,
            "Deleting files in a vault is done by moving them to .trash/, not with rm — that "
            "is how Obsidian behaves and how this project writes (ADR-0007). Use "
            "`mv <file> .trash/` if you really mean to remove it, so it can be recovered.",
            rule="delete", match=destructive,
        )

    return Decision(ALLOW)


def _write_record(location, payload: dict, decision: Decision) -> None:
    """Leave the two traces a refusal has to leave. Best effort, like everything else here.

    The heartbeat is touched on *every* call and the log line only on a refusal. That
    asymmetry is the point: a line per tool call would be a log nobody reads, while an empty
    file's timestamp answers the one question the log cannot -- whether the hook is wired in
    at all, or whether a quiet guard is simply absent (ADR-0014).
    """
    from hvk import audit

    try:
        location.index_dir.mkdir(parents=True, exist_ok=True)
        location.guard_seen_path.touch()
    except OSError:
        pass
    if decision.permission != DENY:
        return
    audit.record(
        location.log_path, "guard deny",
        rule=decision.rule,
        tool=payload.get("tool_name") or "",
        match=decision.match,
    )


def run(stdin_text: str, *, location=None, protected: list | None = None) -> str:
    """Read one hook payload, return the JSON to print. Never raises."""
    try:
        payload = json.loads(stdin_text)
    except ValueError:
        # A hook that fails closed on its own bugs breaks the session it was meant to protect.
        return ""
    if not isinstance(payload, dict):
        return ""
    decision = decide(payload, vault=getattr(location, "vault", None), protected=protected)
    if location is not None:
        try:
            _write_record(location, payload, decision)
        except Exception:                   # noqa: BLE001 - see the module docstring
            # Not defensive programming for its own sake: this is the last thing between a bug
            # in the record-keeping and an agent session that cannot make a single tool call.
            pass
    output = decision.as_hook_output()
    return json.dumps(output, ensure_ascii=False) if output else ""
