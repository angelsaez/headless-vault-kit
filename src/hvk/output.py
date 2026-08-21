"""Rendering results: a readable table for people, JSON for the agent.

CLI output is human-readable by default and switches to JSON with ``--json`` (CLAUDE.md).
Column widths account for East Asian wide characters, because a vault with CJK filenames
should not produce a ragged table.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from typing import Any, Iterable, Sequence


def display_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    """Render an aligned plain-text table. Returns an empty string when there are no rows."""
    body = [[("" if cell is None else str(cell)) for cell in row] for row in rows]
    if not body:
        return ""
    widths = [display_width(h) for h in headers]
    for row in body:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], display_width(cell))
    lines = [
        "  ".join(_pad(h, widths[i]) for i, h in enumerate(headers)).rstrip(),
        "  ".join("-" * widths[i] for i in range(len(headers))),
    ]
    lines.extend("  ".join(_pad(c, widths[i]) for i, c in enumerate(row)).rstrip() for row in body)
    return "\n".join(lines)


def emit(
    rows: Sequence[dict],
    *,
    headers: Sequence[str],
    columns: Sequence[str],
    as_json: bool,
    empty: str = "no results",
) -> None:
    """Print *rows* either as JSON or as a table over the given columns."""
    if as_json:
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return
    if not rows:
        print(empty)
        return
    print(table(headers, [[row.get(c) for c in columns] for row in rows]))


def emit_object(data: dict, *, as_json: bool) -> None:
    """Print a single record: JSON, or one ``key: value`` per line."""
    if as_json:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return
    width = max((display_width(k) for k in data), default=0)
    for key, value in data.items():
        print(f"{_pad(key, width)}  {value}")
