"""Running a base view against the index.

Every file in the vault becomes one row, the filters decide which survive, and the view's
``order`` decides which columns are computed. Rows are loaded in four queries and assembled in
memory rather than one query per file, because a base over a ten-thousand-note vault should
cost one pass, not ten thousand.
"""

from __future__ import annotations

import datetime as dt
import functools
import json
import sqlite3
from dataclasses import dataclass, field

from hvk.bases.base_file import BaseError, BaseFile, Filter, View
from hvk.bases.evaluate import Context, evaluate_source
from hvk.bases.expr import ExpressionError
from hvk.bases.values import File, as_number, as_text, sort_key, truthy

DEFAULT_COLUMNS = ["file.name"]


@dataclass
class Result:
    view: View
    columns: list = field(default_factory=list)          # expression per column
    headers: list = field(default_factory=list)          # what to print for each column
    rows: list = field(default_factory=list)             # list of {"path": str, "values": dict}
    groups: list = field(default_factory=list)           # (group value, rows) when grouped
    summaries: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    total: int = 0                                        # matches before any limit


def _typed(value: str | None, value_type: str):
    """Rebuild a frontmatter value from how the index stored it."""
    if value_type == "null" or value is None:
        return None
    if value_type == "bool":
        return value == "true"
    if value_type == "number":
        return as_number(value)
    if value_type == "date":
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return value
    if value_type == "datetime":
        try:
            return dt.datetime.fromisoformat(value)
        except ValueError:
            return value
    if value_type in ("map", "list"):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def load_files(conn: sqlite3.Connection) -> dict:
    """Build a File value for every file in the vault, keyed by row id."""
    files: dict[int, File] = {}
    # Rows are notes. An unfiltered base listing its own .base file and every attachment
    # alongside the notes is not what anyone means by "the files in this vault", and the app
    # does not do it either (ADR-0005).
    for row in conn.execute(
        "SELECT id, path, name, stem, parent, ext, size, ctime, mtime FROM files "
        "WHERE kind = 'note'"
    ):
        files[row["id"]] = File(
            path=row["path"],
            name=row["name"],
            basename=row["stem"],
            folder=row["parent"],
            ext=row["ext"],
            size=row["size"],
            ctime=dt.datetime.fromtimestamp(row["ctime"] / 1_000_000_000),
            mtime=dt.datetime.fromtimestamp(row["mtime"] / 1_000_000_000),
        )

    for row in conn.execute("SELECT file_id, tag FROM tags"):
        target = files.get(row["file_id"])
        if target is not None and row["tag"] not in target.tags:
            target.tags.append(row["tag"])

    for row in conn.execute(
        "SELECT l.file_id AS file_id, t.path AS path FROM links l "
        "JOIN files t ON t.id = l.target_file_id"
    ):
        target = files.get(row["file_id"])
        if target is not None and row["path"] not in target.links:
            target.links.append(row["path"])

    # Frontmatter only: Dataview-style inline fields are not Obsidian properties, and Bases
    # reads properties.
    lists: dict[tuple, list] = {}
    for row in conn.execute(
        "SELECT file_id, key, value, value_type, idx FROM props "
        "WHERE inline = 0 ORDER BY file_id, key, idx IS NULL, idx"
    ):
        target = files.get(row["file_id"])
        if target is None:
            continue
        value = _typed(row["value"], row["value_type"])
        if row["idx"] is None:
            target.properties[row["key"]] = [] if row["value_type"] == "list" else value
        else:
            bucket = lists.setdefault((row["file_id"], row["key"]), [])
            bucket.append(value)
            target.properties[row["key"]] = bucket
    return files


def _keep(filters: Filter | None, context: Context) -> bool:
    if filters is None:
        return True
    if filters.source is not None:
        return truthy(evaluate_source(filters.source, context))
    if filters.operator == "not":
        return not any(_keep(child, context) for child in filters.children)
    if filters.operator == "or":
        return any(_keep(child, context) for child in filters.children)
    return all(_keep(child, context) for child in filters.children)


def _order_rows(rows: list, sorts: list) -> None:
    """Sort in place, with nulls last whichever direction each key asks for."""
    if not sorts:
        return

    def compare(left, right) -> int:
        for entry in sorts:
            a, b = left["values"].get(entry.property), right["values"].get(entry.property)
            if a is None or b is None:
                if a is None and b is None:
                    continue
                return 1 if a is None else -1
            key_a, key_b = sort_key(a), sort_key(b)
            if key_a != key_b:
                result = -1 if key_a < key_b else 1
                return -result if entry.descending else result
        return 0

    rows.sort(key=functools.cmp_to_key(compare))


def _summarise(name: str, values: list, row_count: int):
    name = name.lower()
    if name == "count":
        return row_count
    present = [v for v in values if v is not None]
    if name == "unique":
        return len({as_text(v) for v in present})
    numbers = [n for n in (as_number(v) for v in present) if n is not None]
    if not numbers:
        return None
    if name == "sum":
        return sum(numbers)
    if name in ("average", "mean"):
        return round(sum(numbers) / len(numbers), 4)
    if name == "min":
        return min(numbers)
    return max(numbers)


def run(base: BaseFile, conn: sqlite3.Connection, view_name: str | None = None,
        this_path: str | None = None) -> Result:
    """Execute one view of *base* against the index."""
    view = base.view(view_name)
    warnings = list(base.warnings)

    files = load_files(conn)
    by_path = {value.path: value for value in files.values()}
    this = None
    if this_path is not None:
        this = by_path.get(this_path)
        if this is None:
            raise BaseError(f"--this {this_path!r} is not a file in the index")

    columns = view.order or list(DEFAULT_COLUMNS)
    if not view.order:
        warnings.append(
            "this view has no 'order', so only file.name is shown; add columns to the base "
            "to see more"
        )
    # A column or sort key that is not displayed still has to be computed to sort by it.
    needed = list(dict.fromkeys(columns + [entry.property for entry in view.sort]
                                + ([view.group_by.property] if view.group_by else [])))

    rows = []
    for value in sorted(files.values(), key=lambda f: f.path):
        context = Context(
            file=value,
            note=value.properties,
            formulas=base.formulas,
            this=this,
            resolve=by_path.get,
        )
        try:
            if not _keep(base.filters, context) or not _keep(view.filters, context):
                continue
            computed = {name: evaluate_source(name, context) for name in needed}
        except ExpressionError as exc:
            raise BaseError(f"{base.path.name}, view {view.name!r}, on {value.path}: {exc}") from exc
        rows.append({"path": value.path, "values": computed})

    total = len(rows)
    _order_rows(rows, view.sort)
    if view.limit is not None:
        rows = rows[: view.limit]

    groups = []
    if view.group_by is not None:
        key = view.group_by.property
        buckets: dict = {}
        for row in rows:
            buckets.setdefault(as_text(row["values"].get(key)), []).append(row)
        # Empty stays last in both directions, the same rule nulls follow when sorting.
        ordered = sorted(
            buckets.items(),
            key=lambda item: (item[0].lower(),),
            reverse=view.group_by.descending,
        )
        ordered = [item for item in ordered if item[0]] + [item for item in ordered if not item[0]]
        groups = [(name or "(none)", bucket) for name, bucket in ordered]

    summaries = {
        column: _summarise(name, [r["values"].get(column) for r in rows], len(rows))
        for column, name in view.summaries.items()
    }

    return Result(
        view=view,
        columns=columns,
        headers=[base.display_name(column) for column in columns],
        rows=rows,
        groups=groups,
        summaries=summaries,
        warnings=warnings,
        total=total,
    )
