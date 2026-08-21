"""Reading a ``.base`` file into something executable.

The file is YAML with five top-level keys. This turns it into a small object graph and
validates what it can up front, so that a broken base is reported before any rows are read
rather than halfway through printing a table.

Unknown keys are collected as warnings rather than refused: Obsidian keeps adding to this
format, and failing on a key from a newer version would make the tool useless the week after
an app release. Unknown *functions* and unsupported *view types* still fail, because those
change the answer rather than merely being unread (ADR-0005).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML, YAMLError

from hvk.bases.expr import ExpressionError, parse

_yaml = YAML(typ="safe", pure=True)
_yaml.allow_duplicate_keys = True

SUPPORTED_VIEWS = {"table", "cards", "list"}
KNOWN_TOP_LEVEL = {"filters", "formulas", "properties", "summaries", "views"}
KNOWN_VIEW_KEYS = {
    "type", "name", "limit", "order", "sort", "filters", "groupBy", "group_by", "summaries",
    "image", "imageProperty", "cardSize", "columnSize",
}
BUILTIN_SUMMARIES = {"count", "sum", "average", "mean", "min", "max", "unique"}


class BaseError(Exception):
    """Raised when a ``.base`` file cannot be read or asks for something unsupported."""


@dataclass
class Filter:
    """A filter tree: either a leaf expression, or and/or/not over more filters."""

    operator: str | None = None            # 'and' | 'or' | 'not' | None for a leaf
    children: list = field(default_factory=list)
    source: str | None = None              # the expression, for a leaf

    @staticmethod
    def parse(node, where: str) -> "Filter | None":
        if node is None:
            return None
        if isinstance(node, str):
            _check_expression(node, where)
            return Filter(source=node)
        if isinstance(node, list):
            return Filter("and", [Filter.parse(child, where) for child in node])
        if isinstance(node, dict):
            if len(node) != 1:
                raise BaseError(
                    f"{where}: a filter object takes exactly one of 'and', 'or' or 'not', "
                    f"got {sorted(node)}"
                )
            operator, children = next(iter(node.items()))
            if operator not in ("and", "or", "not"):
                raise BaseError(f"{where}: unknown filter operator {operator!r}")
            if not isinstance(children, list):
                children = [children]
            return Filter(operator, [Filter.parse(child, where) for child in children])
        raise BaseError(f"{where}: cannot read a filter from {type(node).__name__}")

    def expressions(self):
        if self.source is not None:
            yield self.source
        for child in self.children:
            yield from child.expressions()


@dataclass
class Sort:
    property: str
    descending: bool = False


@dataclass
class View:
    type: str
    name: str
    limit: int | None = None
    order: list = field(default_factory=list)
    sort: list = field(default_factory=list)
    group_by: Sort | None = None
    filters: Filter | None = None
    summaries: dict = field(default_factory=dict)


@dataclass
class BaseFile:
    path: Path
    filters: Filter | None = None
    formulas: dict = field(default_factory=dict)
    properties: dict = field(default_factory=dict)
    summaries: dict = field(default_factory=dict)
    views: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def view(self, name: str | None) -> View:
        if not self.views:
            raise BaseError(f"{self.path.name} defines no views")
        if name is None:
            return self.views[0]
        for view in self.views:
            if view.name == name:
                return view
        available = ", ".join(repr(v.name) for v in self.views)
        raise BaseError(f"{self.path.name} has no view named {name!r}. It has: {available}")

    def display_name(self, column: str) -> str:
        configured = self.properties.get(column)
        if isinstance(configured, dict) and configured.get("displayName"):
            return str(configured["displayName"])
        return column.split(".", 1)[-1] if column.startswith(("note.", "file.", "formula.")) else column


def _check_expression(source: str, where: str) -> None:
    try:
        parse(source)
    except ExpressionError as exc:
        raise BaseError(f"{where}: {exc}") from exc


def _direction(value) -> bool:
    return str(value or "ASC").upper() in ("DESC", "DESCENDING")


def _parse_sort(node, where: str) -> list:
    if node is None:
        return []
    entries = node if isinstance(node, list) else [node]
    out = []
    for entry in entries:
        if isinstance(entry, str):
            out.append(Sort(entry))
        elif isinstance(entry, dict):
            name = entry.get("property") or entry.get("column")
            if not name:
                raise BaseError(f"{where}: a sort entry needs a 'property'")
            out.append(Sort(str(name), _direction(entry.get("direction"))))
        else:
            raise BaseError(f"{where}: cannot read a sort entry from {type(entry).__name__}")
    return out


def _parse_view(node, index: int, warnings: list) -> View:
    if not isinstance(node, dict):
        raise BaseError(f"view {index + 1}: expected a mapping, got {type(node).__name__}")
    name = str(node.get("name") or f"view {index + 1}")
    where = f"view {name!r}"

    kind = str(node.get("type") or "table").lower()
    if kind not in SUPPORTED_VIEWS:
        raise BaseError(
            f"{where}: view type {kind!r} is not supported. Supported: "
            f"{', '.join(sorted(SUPPORTED_VIEWS))} (see docs/adr/0005-bases-subset.md)"
        )

    unknown = set(node) - KNOWN_VIEW_KEYS
    if unknown:
        warnings.append(f"{where}: ignoring unknown key(s) {', '.join(sorted(unknown))}")

    group = node.get("groupBy") or node.get("group_by")
    group_by = None
    if group is not None:
        parsed = _parse_sort(group, where)
        group_by = parsed[0] if parsed else None

    order = [str(column) for column in (node.get("order") or [])]
    summaries = {str(k): str(v) for k, v in (node.get("summaries") or {}).items()}
    for column, summary in summaries.items():
        if summary.lower() not in BUILTIN_SUMMARIES:
            raise BaseError(
                f"{where}: summary {summary!r} on {column!r} is not one of "
                f"{', '.join(sorted(BUILTIN_SUMMARIES))}. Custom summary expressions are not "
                f"supported (see docs/adr/0005-bases-subset.md)"
            )

    limit = node.get("limit")
    return View(
        type=kind,
        name=name,
        limit=int(limit) if limit is not None else None,
        order=order,
        sort=_parse_sort(node.get("sort"), where),
        group_by=group_by,
        filters=Filter.parse(node.get("filters"), where),
        summaries=summaries,
    )


def load(path: Path) -> BaseFile:
    """Read and validate a ``.base`` file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BaseError(f"cannot read {path}: {exc}") from exc
    try:
        data = _yaml.load(text)
    except YAMLError as exc:
        raise BaseError(f"{path.name} is not valid YAML: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise BaseError(f"{path.name}: expected a mapping at the top level")

    warnings: list = []
    unknown = set(data) - KNOWN_TOP_LEVEL
    if unknown:
        warnings.append(f"ignoring unknown top-level key(s) {', '.join(sorted(unknown))}")

    formulas = {str(k): str(v) for k, v in (data.get("formulas") or {}).items()}
    for name, source in formulas.items():
        _check_expression(source, f"formula {name!r}")

    summaries = {str(k): str(v) for k, v in (data.get("summaries") or {}).items()}
    if summaries:
        warnings.append(
            f"custom summaries ({', '.join(sorted(summaries))}) are declared but not "
            f"evaluated; only the built-in summary names run"
        )

    views = [
        _parse_view(node, index, warnings)
        for index, node in enumerate(data.get("views") or [])
    ]

    return BaseFile(
        path=path,
        filters=Filter.parse(data.get("filters"), "global filters"),
        formulas=formulas,
        properties=data.get("properties") or {},
        summaries=summaries,
        views=views,
        warnings=warnings,
    )
