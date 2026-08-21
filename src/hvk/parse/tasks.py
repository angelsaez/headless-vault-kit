"""Tier-2 field extraction from a task line (ADR-0004).

Reads the syntax of the **Tasks** community plugin and of Dataview inline fields. Deliberately
a pure function -- text in, ``(clean_text, fields)`` out, no I/O, no state, no imports from the
rest of ``hvk`` -- because that is the contract an out-of-process parser adapter will have when
phase 7 lands. Moving this behind that interface should be a relocation, not a rewrite.

Nothing here executes plugin code. Only syntax is read, and a field exists only if it is
written in the file.
"""

from __future__ import annotations

import re

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# The Tasks plugin's emoji vocabulary. A closed list on purpose (ADR-0004).
DATE_EMOJI = {
    "\U0001F4C5": "due",         # 📅
    "⏳": "scheduled",       # ⏳
    "\U0001F6EB": "start",       # 🛫
    "✅": "done",            # ✅
    "➕": "created",         # ➕
    "❌": "cancelled",       # ❌
}

PRIORITY_EMOJI = {
    "\U0001F53A": "highest",     # 🔺
    "⏫": "high",            # ⏫
    "\U0001F53C": "medium",      # 🔼
    "\U0001F53D": "low",         # 🔽
    "⏬": "lowest",          # ⏬
}

RECURRENCE_EMOJI = "\U0001F501"  # 🔁

# Dataview-style fields on a task line, written bracketed so they survive rendering.
BRACKET_RE = re.compile(r"\[([A-Za-z][\w -]*?)::[ \t]*([^\]]*)\]")

DATE_KEYS = frozenset(DATE_EMOJI.values())
FIELD_KEYS = DATE_KEYS | {"priority", "recurrence"}

_DATE_EMOJI_RE = re.compile(
    "(" + "|".join(re.escape(e) for e in DATE_EMOJI) + r")[ \t]*(\d{4}-\d{2}-\d{2})"
)
_PRIORITY_RE = re.compile("(" + "|".join(re.escape(e) for e in PRIORITY_EMOJI) + ")")
# A recurrence rule is free text ("every week"), so it runs until the next known marker.
_OTHER_MARKERS = "".join(re.escape(e) for e in (*DATE_EMOJI, *PRIORITY_EMOJI))
_RECURRENCE_RE = re.compile(
    re.escape(RECURRENCE_EMOJI) + r"[ 	]*([^" + _OTHER_MARKERS + r"]*)"
)


def extract(text: str) -> tuple[str, dict[str, str]]:
    """Split a task's own text from the tier-2 fields written into it.

    Returns the text with recognised field markers removed and whitespace collapsed, plus a
    mapping of field name to value. Unrecognised emoji and text are left exactly where they
    were: this reads a known vocabulary, it does not try to tidy the line.
    """
    fields: dict[str, str] = {}

    def take_bracket(match: re.Match) -> str:
        key = match.group(1).strip().lower()
        value = match.group(2).strip()
        if key in DATE_KEYS and DATE_RE.fullmatch(value):
            fields[key] = value
        elif key == "priority" and value:
            fields["priority"] = value.lower()
        elif key == "repeat" or key == "recurrence":
            fields["recurrence"] = value
        else:
            return match.group(0)  # not ours; leave it alone
        return " "

    remaining = BRACKET_RE.sub(take_bracket, text)

    def take_date(match: re.Match) -> str:
        fields[DATE_EMOJI[match.group(1)]] = match.group(2)
        return " "

    remaining = _DATE_EMOJI_RE.sub(take_date, remaining)

    def take_recurrence(match: re.Match) -> str:
        rule = match.group(1).strip()
        if rule:
            fields["recurrence"] = rule
            return " "
        return match.group(0)

    remaining = _RECURRENCE_RE.sub(take_recurrence, remaining)

    def take_priority(match: re.Match) -> str:
        fields.setdefault("priority", PRIORITY_EMOJI[match.group(1)])
        return " "

    remaining = _PRIORITY_RE.sub(take_priority, remaining)

    return re.sub(r"[ \t]{2,}", " ", remaining).strip(), fields
