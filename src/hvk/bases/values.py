"""The value model behind Bases expressions: types, coercions and the function library.

ADR-0005 fixes which functions exist and what happens to missing values. The published
documentation says what each function does but not how the language treats a property that
is not there, so those rules are defined here and stated in the ADR:

* a missing property is **null**, never an error;
* null equals only null, so ``status != "done"`` is true for a note with no status;
* ordering comparisons against null are false in both directions;
* a string is coerced when it parses cleanly as the number or date it is compared against.

Deliberately absent: rendering helpers, ``random``, the lambda-taking list functions and the
regular expression type. Calling one of those is an error naming it, never a silent null.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass, field

from hvk.bases.expr import ExpressionError

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?")
NUMBER_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")

# "3 days", "2w", "1 hour". The published documentation does not pin the literal format, so
# this is a documented approximation (ADR-0005) rather than a claim of parity.
DURATION_RE = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*"
    r"(ms|milliseconds?|s|secs?|seconds?|m|mins?|minutes?|h|hours?|d|days?|"
    r"w|weeks?|mo|months?|y|years?)\s*$",
    re.IGNORECASE,
)
DURATION_UNITS = {
    "ms": 0.001, "millisecond": 0.001, "milliseconds": 0.001,
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "week": 604800, "weeks": 604800,
    "mo": 2592000, "month": 2592000, "months": 2592000,
    "y": 31536000, "year": 31536000, "years": 31536000,
}


@dataclass(frozen=True)
class Link:
    """A wikilink value: where it points, and how it is displayed."""

    path: str
    display: str | None = None

    def __str__(self) -> str:
        return self.display or self.path


@dataclass
class File:
    """A file as Bases sees it.

    Plain data, filled in by whoever is running the base. Keeping it free of any database
    access is what lets the evaluator be tested without an index.
    """

    path: str
    name: str = ""
    basename: str = ""
    folder: str = ""
    ext: str = ""
    size: int = 0
    ctime: dt.datetime | None = None
    mtime: dt.datetime | None = None
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    properties: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return self.name or self.path


def type_name(value) -> str:
    """The Bases type of a Python value. bool is checked first: it is an int in Python."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (dt.datetime, dt.date)):
        return "date"
    if isinstance(value, dt.timedelta):
        return "duration"
    if isinstance(value, (list, tuple)):
        return "list"
    if isinstance(value, File):
        return "file"
    if isinstance(value, Link):
        return "link"
    if isinstance(value, dict):
        return "object"
    return "object"


def truthy(value) -> bool:
    """Obsidian's isTruthy: empty is false, and so is a missing property."""
    if value is None or value is False:
        return False
    if isinstance(value, (str, list, tuple, dict)):
        return len(value) > 0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return True


def as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return ", ".join(as_text(item) for item in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def as_number(value):
    """Return *value* as a number, or None when it is not one."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str) and NUMBER_RE.match(value.strip()):
        text = value.strip()
        return float(text) if "." in text else int(text)
    return None


def as_date(value):
    """Return *value* as a date or datetime, or None when it is not one."""
    if isinstance(value, (dt.datetime, dt.date)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if ISO_DATE_RE.match(text):
            return dt.date.fromisoformat(text)
        if ISO_DATETIME_RE.match(text):
            try:
                return dt.datetime.fromisoformat(text.replace(" ", "T"))
            except ValueError:
                return None
    return None


def as_duration(value):
    if isinstance(value, dt.timedelta):
        return value
    if isinstance(value, str):
        match = DURATION_RE.match(value)
        if match:
            amount = float(match.group(1))
            return dt.timedelta(seconds=amount * DURATION_UNITS[match.group(2).lower()])
    return None


def _comparable_pair(left, right):
    """Coerce two values to a comparable pair, or return None when they are not."""
    if isinstance(left, bool) or isinstance(right, bool):
        return None
    left_number, right_number = as_number(left), as_number(right)
    if left_number is not None and right_number is not None:
        return left_number, right_number
    left_date, right_date = as_date(left), as_date(right)
    if left_date is not None and right_date is not None:
        if type(left_date) is not type(right_date):
            left_date = _to_datetime(left_date)
            right_date = _to_datetime(right_date)
        return left_date, right_date
    if isinstance(left, str) and isinstance(right, str):
        return left, right
    return None


def _to_datetime(value):
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.combine(value, dt.time.min)


def equals(left, right) -> bool:
    """Equality with the null rule of ADR-0005: null equals only null."""
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return truthy(left) == truthy(right) if isinstance(left, bool) and isinstance(right, bool) else False
    pair = _comparable_pair(left, right)
    if pair is not None:
        return pair[0] == pair[1]
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return list(left) == list(right)
    if isinstance(left, (File, Link)) or isinstance(right, (File, Link)):
        return as_text(left) == as_text(right)
    return left == right


def compare(operator: str, left, right) -> bool:
    """Ordering comparison. Anything involving null is false, in both directions."""
    if left is None or right is None:
        return False
    pair = _comparable_pair(left, right)
    if pair is None:
        # Values that cannot be coerced to a common type do not order. Falling back to
        # comparing their text would make "many" > 10 true, which is nonsense dressed as an
        # answer -- and ADR-0005 says the comparison is false instead.
        return False
    a, b = pair
    if operator == "<":
        return a < b
    if operator == "<=":
        return a <= b
    if operator == ">":
        return a > b
    return a >= b


def sort_key(value):
    """Sort key that puts nulls last, whichever direction is asked for.

    "The earliest" never means "the ones with no date", so nulls sink regardless of the
    direction the view asked for (ADR-0005).
    """
    if value is None:
        return (2, 0, "")
    number = as_number(value)
    if number is not None:
        return (0, number, "")
    date = as_date(value)
    if date is not None:
        return (0, _to_datetime(date).timestamp(), "")
    return (1, 0, as_text(value).lower())


def tag_matches(tag: str, wanted: str) -> bool:
    """A nested tag matches its ancestors, the way Obsidian's own tag search does."""
    tag, wanted = tag.lstrip("#").lower(), wanted.lstrip("#").lower()
    return tag == wanted or tag.startswith(wanted + "/")


def arity(name: str, arguments, minimum: int, maximum: int | None = None) -> None:
    maximum = minimum if maximum is None else maximum
    if not (minimum <= len(arguments) <= (math.inf if maximum < 0 else maximum)):
        expected = f"{minimum}" if minimum == maximum else f"{minimum} to {maximum}"
        raise ExpressionError(
            f"{name}() takes {expected} argument(s), got {len(arguments)}"
        )
