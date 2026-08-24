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
# `find ... -delete` and `find ... -exec rm` walk past a check that only looks at argv[0].
FIND_DELETE = re.compile(r"\bfind\b.*(-delete\b|-exec\s+rm\b)")

ALLOW, DENY = "allow", "deny"


@dataclass
class Decision:
    permission: str
    reason: str = ""

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


def _is_destructive(command: str) -> bool:
    if FIND_DELETE.search(command):
        return True
    # Each segment of a pipeline or && chain is its own command, and only its first word is
    # the program being run.
    for segment in re.split(r"[;&|]+", command):
        words = segment.split()
        if words and Path(words[0]).name in DESTRUCTIVE:
            return True
    return False


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
            )

    # 2. Deletion. Only Bash can do it: every other tool either writes or reads.
    if tool == "Bash" and command and _is_destructive(command):
        return Decision(
            DENY,
            "Deleting files in a vault is done by moving them to .trash/, not with rm — that "
            "is how Obsidian behaves and how this project writes (ADR-0007). Use "
            "`mv <file> .trash/` if you really mean to remove it, so it can be recovered.",
        )

    return Decision(ALLOW)


def run(stdin_text: str, *, vault: Path | None = None, protected: list | None = None) -> str:
    """Read one hook payload, return the JSON to print. Never raises."""
    try:
        payload = json.loads(stdin_text)
    except ValueError:
        # A hook that fails closed on its own bugs breaks the session it was meant to protect.
        return ""
    if not isinstance(payload, dict):
        return ""
    decision = decide(payload, vault=vault, protected=protected)
    output = decision.as_hook_output()
    return json.dumps(output, ensure_ascii=False) if output else ""
