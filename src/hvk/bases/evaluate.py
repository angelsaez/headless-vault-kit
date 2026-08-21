"""Evaluating Bases expression trees against a row.

The function library is the closed list of ADR-0005. Anything outside it raises, naming what
was asked for: a base that uses an unsupported function should tell its author so, not quietly
return a table with a filter missing.

The one place that stays quiet is missing data. Reaching into a property that does not exist
gives null all the way down, so ``price.toFixed(2)`` on a note without a price is null rather
than an error — while ``price.toFixxed(2)`` on a note that has one is still a mistake worth
reporting.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from hvk.bases import expr as ast
from hvk.bases.expr import ExpressionError, parse
from hvk.bases.values import (
    File,
    Link,
    arity,
    as_date,
    as_duration,
    as_number,
    as_text,
    compare,
    equals,
    tag_matches,
    truthy,
    type_name,
)

# Moment.js tokens that appear in practice. Anything else is passed through untouched, which
# is a documented approximation rather than a claim of parity (ADR-0005).
MOMENT_TOKENS = [
    ("YYYY", "%Y"), ("YY", "%y"), ("MMMM", "%B"), ("MMM", "%b"), ("MM", "%m"),
    ("DDDD", "%j"), ("DD", "%d"), ("dddd", "%A"), ("ddd", "%a"),
    ("HH", "%H"), ("hh", "%I"), ("mm", "%M"), ("ss", "%S"), ("A", "%p"),
]


class FormulaNamespace:
    """The ``formula.`` prefix. Resolving a member evaluates that formula."""

    def __init__(self, context: "Context"):
        self.context = context


@dataclass(frozen=True)
class Bound:
    """A method looked up on a value but not yet called."""

    target: object
    name: str
    implementation: object


@dataclass
class Context:
    """Everything one row of a base can see."""

    file: File
    note: dict = field(default_factory=dict)
    formulas: dict = field(default_factory=dict)   # name -> expression source
    this: File | None = None
    resolve: object = None                          # optional path -> File, supplied by the runner
    _values: dict = field(default_factory=dict, repr=False)
    _running: set = field(default_factory=set, repr=False)

    def formula(self, name: str):
        if name in self._values:
            return self._values[name]
        if name not in self.formulas:
            raise ExpressionError(f"no formula named {name!r} is defined in this base")
        if name in self._running:
            raise ExpressionError(f"formula {name!r} refers to itself")
        self._running.add(name)
        try:
            value = evaluate_source(self.formulas[name], self)
        finally:
            self._running.discard(name)
        self._values[name] = value
        return value


_PARSED: dict[str, object] = {}


def evaluate_source(source: str, context: Context):
    """Parse (once, cached) and evaluate an expression."""
    tree = _PARSED.get(source)
    if tree is None:
        tree = _PARSED[source] = parse(source)
    return evaluate(tree, context)


def evaluate(node, context: Context):
    if isinstance(node, ast.Literal):
        return node.value
    if isinstance(node, ast.ListLiteral):
        return [evaluate(element, context) for element in node.elements]
    if isinstance(node, ast.Name):
        return _name(node.identifier, context)
    if isinstance(node, ast.Member):
        return _member(evaluate(node.target, context), node.name, context)
    if isinstance(node, ast.Index):
        return _index(evaluate(node.target, context), evaluate(node.key, context))
    if isinstance(node, ast.Call):
        return _call(node, context)
    if isinstance(node, ast.Unary):
        value = evaluate(node.operand, context)
        if node.operator == "!":
            return not truthy(value)
        number = as_number(value)
        return None if number is None else -number
    if isinstance(node, ast.Binary):
        return _binary(node, context)
    raise ExpressionError(f"cannot evaluate {node!r}")


def _name(identifier: str, context: Context):
    if identifier == "file":
        return context.file
    if identifier == "note":
        return context.note
    if identifier == "formula":
        return FormulaNamespace(context)
    if identifier == "this":
        if context.this is None:
            raise ExpressionError(
                "'this' refers to the note a base is embedded in; pass --this PATH to say "
                "which note that is"
            )
        return _ThisNamespace(context.this)
    if identifier in GLOBALS:
        return Bound(None, identifier, GLOBALS[identifier])
    # A bare name is a frontmatter property. Missing means null, never an error.
    return context.note.get(identifier)


@dataclass(frozen=True)
class _ThisNamespace:
    file: File


def _member(target, name: str, context: Context):
    if target is None:
        return None                       # missing data propagates; it is not a mistake
    if isinstance(target, FormulaNamespace):
        return target.context.formula(name)
    if isinstance(target, _ThisNamespace):
        if name == "file":
            return target.file
        raise ExpressionError(f"'this' has no member {name!r}; use this.file")
    if isinstance(target, File):
        return _file_member(target, name)
    if isinstance(target, dict):
        if name in target:
            return target[name]
        if name in OBJECT_METHODS:
            return Bound(target, name, OBJECT_METHODS[name])
        return None
    kind = type_name(target)
    if kind == "string" and name == "length":
        return len(target)
    if kind == "list" and name == "length":
        return len(target)
    if kind == "date":
        field_value = _date_field(target, name)
        if field_value is not None:
            return field_value
    table = METHODS.get(kind, {})
    if name in table:
        return Bound(target, name, table[name])
    if name in ANY_METHODS:
        return Bound(target, name, ANY_METHODS[name])
    raise ExpressionError(f"{kind} values have no member {name!r}")


def _file_member(target: File, name: str):
    if name in ("name", "basename", "path", "folder", "ext", "size", "ctime", "mtime",
                "tags", "links", "properties"):
        return getattr(target, name)
    if name in FILE_METHODS:
        return Bound(target, name, FILE_METHODS[name])
    if name in ANY_METHODS:
        return Bound(target, name, ANY_METHODS[name])
    raise ExpressionError(f"file has no member {name!r}")


def _date_field(value, name: str):
    if name in ("year", "month", "day"):
        return getattr(value, name)
    if name in ("hour", "minute", "second", "millisecond"):
        if isinstance(value, dt.datetime):
            return getattr(value, name if name != "millisecond" else "microsecond") // (
                1000 if name == "millisecond" else 1
            )
        return 0
    return None


def _index(target, key):
    if target is None:
        return None
    if isinstance(target, dict):
        return target.get(key if isinstance(key, str) else as_text(key))
    if isinstance(target, (list, tuple, str)):
        position = as_number(key)
        if position is None:
            return None
        position = int(position)
        return target[position] if -len(target) <= position < len(target) else None
    return None


def _call(node: ast.Call, context: Context):
    # if() decides which branch to evaluate, so the branch not taken never runs. That is what
    # makes if(price, price.toFixed(2)) safe on a note with no price.
    if isinstance(node.callee, ast.Name) and node.callee.identifier == "if":
        arity("if", node.arguments, 2, 3)
        condition = evaluate(node.arguments[0], context)
        if truthy(condition):
            return evaluate(node.arguments[1], context)
        return evaluate(node.arguments[2], context) if len(node.arguments) == 3 else None

    # A bare name in call position can only be a global function. Falling through to the
    # note-property lookup would turn random() or html("x") into a silent null, which is
    # exactly what ADR-0005 says must not happen: an unsupported base should say so.
    if isinstance(node.callee, ast.Name):
        name = node.callee.identifier
        if name in ("file", "note", "formula", "this"):
            raise ExpressionError(f"{name!r} is a namespace, not a function")
        if name not in GLOBALS:
            raise ExpressionError(
                f"unknown function {name}(); see docs/adr/0005-bases-subset.md for what "
                f"this project supports"
            )

    callee = evaluate(node.callee, context)
    if callee is None:
        return None                       # calling a method of missing data is missing data
    if not isinstance(callee, Bound):
        raise ExpressionError(f"{type_name(callee)} values cannot be called")
    arguments = [evaluate(argument, context) for argument in node.arguments]
    if callee.target is None:
        return callee.implementation(arguments, context)
    return callee.implementation(callee.target, arguments, context)


def _binary(node: ast.Binary, context: Context):
    operator = node.operator
    if operator == "&&":
        return truthy(evaluate(node.left, context)) and truthy(evaluate(node.right, context))
    if operator == "||":
        return truthy(evaluate(node.left, context)) or truthy(evaluate(node.right, context))

    left = evaluate(node.left, context)
    right = evaluate(node.right, context)
    if operator == "==":
        return equals(left, right)
    if operator == "!=":
        return not equals(left, right)
    if operator in ("<", "<=", ">", ">="):
        return compare(operator, left, right)
    return _arithmetic(operator, left, right)


def _arithmetic(operator: str, left, right):
    if operator == "+":
        date, duration = as_date(left), as_duration(right)
        if date is not None and duration is not None:
            return _shift(date, duration)
        if isinstance(left, str) or isinstance(right, str):
            return as_text(left) + as_text(right)
        if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
            return list(left) + list(right)
    if operator == "-":
        left_date, right_date = as_date(left), as_date(right)
        duration = as_duration(right)
        if left_date is not None and right_date is not None and not isinstance(right, (int, float)):
            return _as_datetime(left_date) - _as_datetime(right_date)
        if left_date is not None and duration is not None:
            return _shift(left_date, -duration)

    a, b = as_number(left), as_number(right)
    if a is None or b is None:
        return None
    if operator == "+":
        return a + b
    if operator == "-":
        return a - b
    if operator == "*":
        return a * b
    if b == 0:
        return None                       # division by zero is missing data, not a crash
    if operator == "/":
        return a / b
    return a % b


def _as_datetime(value):
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.combine(value, dt.time.min)


def _shift(date, duration: dt.timedelta):
    if isinstance(date, dt.datetime):
        return date + duration
    if duration % dt.timedelta(days=1) == dt.timedelta(0):
        return date + duration
    return _as_datetime(date) + duration


# -- the function library, closed by ADR-0005 --------------------------------------------

def _global_min(arguments, context):
    numbers = [n for n in (as_number(a) for a in arguments) if n is not None]
    return min(numbers) if numbers else None


def _global_max(arguments, context):
    numbers = [n for n in (as_number(a) for a in arguments) if n is not None]
    return max(numbers) if numbers else None


def _global_list(arguments, context):
    arity("list", arguments, 1)
    value = arguments[0]
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _global_link(arguments, context):
    arity("link", arguments, 1, 2)
    target = arguments[0]
    path = target.path if isinstance(target, File) else as_text(target)
    return Link(path, as_text(arguments[1]) if len(arguments) == 2 else None)


GLOBALS = {
    "min": _global_min,
    "max": _global_max,
    "list": _global_list,
    "link": _global_link,
    "number": lambda arguments, context: as_number(arguments[0]) if arguments else None,
    "date": lambda arguments, context: as_date(arguments[0]) if arguments else None,
    "duration": lambda arguments, context: as_duration(arguments[0]) if arguments else None,
    "now": lambda arguments, context: dt.datetime.now(),
    "today": lambda arguments, context: dt.date.today(),
}

ANY_METHODS = {
    "isTruthy": lambda target, arguments, context: truthy(target),
    "isType": lambda target, arguments, context: type_name(target) == as_text(arguments[0]),
    "toString": lambda target, arguments, context: as_text(target),
    "isEmpty": lambda target, arguments, context: not truthy(target),
}


def _string_replace(target, arguments, context):
    arity("replace", arguments, 2)
    return target.replace(as_text(arguments[0]), as_text(arguments[1]))


def _string_split(target, arguments, context):
    arity("split", arguments, 1, 2)
    separator = as_text(arguments[0])
    limit = as_number(arguments[1]) if len(arguments) == 2 else None
    parts = target.split(separator)
    return parts[: int(limit)] if limit is not None else parts


def _slice(target, arguments, context):
    arity("slice", arguments, 1, 2)
    start = int(as_number(arguments[0]) or 0)
    end = int(as_number(arguments[1])) if len(arguments) == 2 else None
    return target[start:end]


STRING_METHODS = {
    "contains": lambda t, a, c: as_text(a[0]) in t,
    "containsAll": lambda t, a, c: all(as_text(v) in t for v in a),
    "containsAny": lambda t, a, c: any(as_text(v) in t for v in a),
    "startsWith": lambda t, a, c: t.startswith(as_text(a[0])),
    "endsWith": lambda t, a, c: t.endswith(as_text(a[0])),
    "lower": lambda t, a, c: t.lower(),
    "title": lambda t, a, c: t.title(),
    "trim": lambda t, a, c: t.strip(),
    "reverse": lambda t, a, c: t[::-1],
    "repeat": lambda t, a, c: t * int(as_number(a[0]) or 0),
    "replace": _string_replace,
    "split": _string_split,
    "slice": _slice,
}


def _number_round(target, arguments, context):
    digits = int(as_number(arguments[0])) if arguments else 0
    value = round(target, digits)
    return int(value) if digits <= 0 else value


NUMBER_METHODS = {
    "abs": lambda t, a, c: abs(t),
    "ceil": lambda t, a, c: int(-(-t // 1)),
    "floor": lambda t, a, c: int(t // 1),
    "round": _number_round,
    "toFixed": lambda t, a, c: f"{t:.{int(as_number(a[0]) or 0)}f}",
}


def _date_format(target, arguments, context):
    arity("format", arguments, 1)
    pattern = as_text(arguments[0])
    for token, directive in MOMENT_TOKENS:
        pattern = pattern.replace(token, directive)
    return _as_datetime(target).strftime(pattern)


def _date_relative(target, arguments, context):
    delta = dt.datetime.now() - _as_datetime(target)
    days = delta.days
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days == -1:
        return "tomorrow"
    return f"{abs(days)} days ago" if days > 0 else f"in {abs(days)} days"


DATE_METHODS = {
    "date": lambda t, a, c: t.date() if isinstance(t, dt.datetime) else t,
    "time": lambda t, a, c: _as_datetime(t).strftime("%H:%M:%S"),
    "format": _date_format,
    "relative": _date_relative,
}


def _list_contains(target, arguments, context):
    return any(equals(item, arguments[0]) for item in target)


LIST_METHODS = {
    "contains": _list_contains,
    "containsAll": lambda t, a, c: all(any(equals(i, v) for i in t) for v in a),
    "containsAny": lambda t, a, c: any(any(equals(i, v) for i in t) for v in a),
    "join": lambda t, a, c: (as_text(a[0]) if a else ", ").join(as_text(i) for i in t),
    "flat": lambda t, a, c: [
        item for element in t for item in (element if isinstance(element, (list, tuple)) else [element])
    ],
    "reverse": lambda t, a, c: list(reversed(t)),
    "sort": lambda t, a, c: sorted(t, key=lambda v: (as_text(v) or "").lower()),
    "unique": lambda t, a, c: list(dict.fromkeys(as_text(i) for i in t)),
    "slice": _slice,
}

OBJECT_METHODS = {
    "keys": lambda t, a, c: list(t.keys()),
    "values": lambda t, a, c: list(t.values()),
}


def _file_has_tag(target: File, arguments, context):
    if not arguments:
        return bool(target.tags)
    return any(
        tag_matches(tag, as_text(wanted)) for wanted in arguments for tag in target.tags
    )


def _file_has_link(target: File, arguments, context):
    arity("hasLink", arguments, 1)
    wanted = arguments[0]
    if isinstance(wanted, File):
        wanted_text = wanted.path
    elif isinstance(wanted, Link):
        wanted_text = wanted.path
    else:
        wanted_text = as_text(wanted)
    wanted_text = wanted_text.lower()
    for link in target.links:
        lowered = link.lower()
        if lowered == wanted_text or lowered.removesuffix(".md") == wanted_text:
            return True
        if lowered.rsplit("/", 1)[-1].removesuffix(".md") == wanted_text.rsplit("/", 1)[-1]:
            return True
    return False


def _file_in_folder(target: File, arguments, context):
    arity("inFolder", arguments, 1)
    folder = as_text(arguments[0]).strip("/").lower()
    here = target.folder.strip("/").lower()
    return here == folder or here.startswith(folder + "/")


FILE_METHODS = {
    "hasTag": _file_has_tag,
    "hasLink": _file_has_link,
    "hasProperty": lambda t, a, c: as_text(a[0]) in t.properties,
    "inFolder": _file_in_folder,
    "asLink": lambda t, a, c: Link(t.path, as_text(a[0]) if a else None),
}


def _link_as_file(target: Link, arguments, context):
    if context.resolve is None:
        raise ExpressionError(
            "asFile() needs the index to resolve a link, which is not available here"
        )
    return context.resolve(target.path)


LINK_METHODS = {"asFile": _link_as_file}

METHODS = {
    "string": STRING_METHODS,
    "number": NUMBER_METHODS,
    "date": DATE_METHODS,
    "list": LIST_METHODS,
    "link": LINK_METHODS,
    "object": OBJECT_METHODS,
}
