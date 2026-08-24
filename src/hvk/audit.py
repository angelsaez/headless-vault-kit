"""The record of what was refused (phase 6).

ADR-0002 reserved ``hvk.log`` in the index directory when the layout was designed, and nothing
wrote to it for four phases. The guard is what it was reserved for: a refusal that leaves no
trace is a refusal nobody can check afterwards, and "blocked **and recorded**" is what the
phase asks for.

Two properties matter more than the format:

* **It never raises.** This is called from a hook that runs in front of every tool call. An
  audit trail that can break the session it audits is worse than no audit trail, so every
  failure here — no directory, no space, no permission — ends as silence.
* **It records what was matched, not what was typed.** A command line can carry a token, a
  password, a one-off URL. What an audit needs is which rule fired and what it matched; the
  full text buys detail nobody needs at the price of a log that has to be guarded itself.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

# One generation, a quarter of a megabyte. "Basic log rotation" for the only file this project
# writes outside the database: enough history to answer what happened last night, small enough
# that nobody has to configure logrotate for it (and on a machine that has logrotate, this
# file is welcome to be managed there too).
MAX_BYTES = 256 * 1024


def _quote(value: str) -> str:
    """One field, on one line, never able to end the line it is on."""
    flat = " ".join(str(value).split())[:200]
    return f'"{flat}"' if (" " in flat or not flat) else flat


def _rotate(log_path: Path) -> None:
    try:
        if log_path.stat().st_size >= MAX_BYTES:
            log_path.replace(log_path.with_name(log_path.name + ".1"))
    except OSError:
        pass


def record(log_path: Path, event: str, **fields) -> None:
    """Append one ``timestamp event key=value ...`` line. Best effort, always."""
    try:
        _rotate(log_path)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        pairs = " ".join(f"{key}={_quote(value)}" for key, value in fields.items() if value)
        line = " ".join(part for part in (stamp, event, pairs) if part)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
