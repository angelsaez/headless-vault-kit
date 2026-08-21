"""The ``hvk`` command line.

Human-readable tables by default, ``--json`` for the agent. This is what the agent uses
instead of reading files one by one.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from hvk import __version__, db, output, paths, query, scan as scanner
from hvk.bases import base_file as _base_file
from hvk.bases import values as bases_values
from hvk.bases.expr import ExpressionError

EPILOG = """\
examples:
  hvk scan                            index the vault found from the current directory
  hvk search "budget tag:project"     full-text search, with a tag filter
  hvk backlinks Alpha                 what links to Alpha, by name or by path
  hvk links --ambiguous               links where more than one file matched (ADR-0003)
  hvk rebuild --json                  deterministic rebuild, machine-readable output
"""


def _add_global_options(parser: argparse.ArgumentParser, suffix: str) -> None:
    """Attach --vault/--index/--json, with a private dest so the two levels can be merged.

    They belong on the top-level parser *and* on every subcommand, because both
    ``hvk --json info`` and the far more natural ``hvk info --json`` should work. Sharing one
    dest across both levels does not survive argparse's subparser handling, so each level
    keeps its own and :func:`_merge_globals` picks the one that was actually given.
    """
    parser.add_argument(
        "--vault", type=Path, dest=f"vault{suffix}", default=None,
        help="vault directory (default: found by walking up from here)",
    )
    parser.add_argument(
        "--index", type=Path, dest=f"index{suffix}", default=None,
        help="index directory (default: per ADR-0002)",
    )
    parser.add_argument(
        "--json", action="store_true", dest=f"json{suffix}", default=False,
        help="machine-readable output",
    )


def _merge_globals(args: argparse.Namespace) -> argparse.Namespace:
    args.vault = args.vault_after or args.vault_before
    args.index = args.index_after or args.index_before
    args.json = args.json_after or args.json_before
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hvk",
        description="Query an Obsidian vault without the app.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"hvk {__version__}")
    _add_global_options(parser, "_before")

    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        child = sub.add_parser(name, help=help_text)
        _add_global_options(child, "_after")
        return child

    add("scan", "index new and changed files")
    add("rebuild", "drop the index and rebuild it from scratch")
    add("info", "what the index currently holds")

    search = add("search", "full-text search")
    search.add_argument("query", help="text, optionally with path: and tag: filters")
    search.add_argument("--limit", type=int, default=20)

    backlinks = add("backlinks", "what links to a note")
    backlinks.add_argument("target", help="note path or name")

    links = add("links", "outgoing links")
    links.add_argument("source", nargs="?", help="restrict to one note")
    links.add_argument("--broken", action="store_true", help="only unresolved links")
    links.add_argument("--ambiguous", action="store_true", help="only links with rival candidates")
    tags_cmd = add("tags", "every tag in the vault")
    tags_cmd.add_argument("--count", action="store_true", help="how many files carry each tag")
    tags_cmd.add_argument("--prefix", help="only this tag and its descendants")

    tasks_cmd = add("tasks", "tasks across the vault")
    tasks_cmd.add_argument("--pending", action="store_true", help="only unfinished tasks")
    tasks_cmd.add_argument("--done", action="store_true", help="only finished tasks")
    tasks_cmd.add_argument("--due-before", metavar="YYYY-MM-DD", help="tasks due before a date")
    tasks_cmd.add_argument("--path", help="restrict to paths containing this text")

    props_cmd = add("props", "files by property, or the catalogue of keys")
    props_cmd.add_argument(
        "--where", action="append", metavar="COND",
        help="key=value, key!=value, or a bare key; repeat to combine with AND",
    )
    props_cmd.add_argument("--key", help="which property to show in the output")

    orphans_cmd = add("orphans", "files nothing links to")
    orphans_cmd.add_argument(
        "--attachments", action="store_true", help="include unreferenced attachments"
    )
    watch_cmd = add("watch", "index changes as they happen, until interrupted")
    watch_cmd.add_argument(
        "--debounce", type=float, default=1.0, metavar="SECONDS",
        help="how long a file must be quiet before it is indexed (default: 1)",
    )

    add("verify", "re-hash every file as a safety net; run it nightly from cron")
    base_cmd = add("base", "run a view from a .base file against the index")
    base_cmd.add_argument("file", help="path to the .base file, absolute or inside the vault")
    base_cmd.add_argument("--view", help="which view to run (default: the first one)")
    base_cmd.add_argument(
        "--this", metavar="PATH",
        help="the note the base is embedded in, for expressions that use 'this'",
    )

    return parser


def _run(args: argparse.Namespace) -> int:
    location = paths.resolve(args.vault, args.index)

    if args.command in ("scan", "rebuild", "verify"):
        stats = scanner.scan(
            location, rebuild=args.command == "rebuild", verify=args.command == "verify"
        )
        output.emit_object(
            {"vault": str(location.vault), "index": str(location.index_dir), **stats.as_dict()},
            as_json=args.json,
        )
        # After a quiet period, anything the verification pass finds changed is something the
        # incremental path missed. Saying so is the entire point of running it.
        if args.command == "verify" and (stats.changed or stats.removed) and not args.json:
            print(
                f"note: {stats.changed} changed and {stats.removed} removed files were found "
                f"by re-hashing. If nothing edited the vault since the last scan, the "
                f"incremental path missed them."
            )
        return 0

    if args.command == "watch":
        return _watch(location, args)

    conn = db.connect(location.db_path)
    try:
        db.check_schema(conn)
        db.check_vault(conn, location.vault)

        if args.command == "info":
            output.emit_object(query.info(conn), as_json=args.json)

        elif args.command == "search":
            rows = query.search(conn, args.query, limit=args.limit)
            output.emit(
                rows,
                headers=("PATH", "TITLE", "SNIPPET"),
                columns=("path", "title", "snippet"),
                as_json=args.json,
                empty="no matches",
            )

        elif args.command == "backlinks":
            resolved, rows = query.backlinks(conn, args.target)
            if not args.json:
                print(f"backlinks to {resolved}")
            output.emit(
                rows,
                headers=("SOURCE", "LINE", "WROTE", "KIND"),
                columns=("source", "line", "wrote", "kind"),
                as_json=args.json,
                empty="nothing links here",
            )

        elif args.command == "links":
            rows = query.links(
                conn, args.source, broken=args.broken, ambiguous=args.ambiguous
            )
            output.emit(
                rows,
                headers=("SOURCE", "LINE", "TARGET", "RESOLVED", "CAND"),
                columns=("source", "line", "target_raw", "resolved", "candidates"),
                as_json=args.json,
                empty="no links match",
            )
        elif args.command == "tags":
            rows = query.tags(conn, count=args.count, prefix=args.prefix)
            if args.count:
                output.emit(rows, headers=("TAG", "FILES"), columns=("tag", "files"),
                            as_json=args.json, empty="no tags")
            else:
                output.emit([{"tag": r["tag"]} for r in rows], headers=("TAG",),
                            columns=("tag",), as_json=args.json, empty="no tags")

        elif args.command == "tasks":
            rows = query.tasks(
                conn, pending=args.pending, done=args.done,
                due_before=args.due_before, path=args.path,
            )
            output.emit(
                rows,
                headers=("PATH", "LINE", "ST", "DUE", "TEXT"),
                columns=("path", "line", "status", "due", "text"),
                as_json=args.json,
                empty="no tasks match",
            )

        elif args.command == "props":
            rows = query.props(conn, args.where, key=args.key)
            extra = [k for k in (rows[0] if rows else {}) if k != "path"]
            headers = ("PATH", *(k.upper() for k in extra)) if "path" in (rows[0] if rows else {}) \
                else ("KEY", "FILES", "OCCURRENCES")
            columns = ("path", *extra) if "path" in (rows[0] if rows else {}) \
                else ("key", "files", "occurrences")
            output.emit(rows, headers=headers, columns=columns, as_json=args.json,
                        empty="nothing matches")

        elif args.command == "orphans":
            rows = query.orphans(conn, attachments=args.attachments)
            output.emit(
                rows,
                headers=("PATH", "KIND", "OUT"),
                columns=("path", "kind", "outgoing"),
                as_json=args.json,
                empty="nothing is orphaned",
            )

        elif args.command == "base":
            _base(conn, location, args)

    finally:
        conn.close()
    return 0
def _jsonable(value):
    """Values a base produces are richer than JSON: dates, files and links become text."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return bases_values.as_text(value)


def _base(conn, location: paths.Locations, args: argparse.Namespace) -> None:
    """Run one view of a .base file and print it as a Markdown table, or as JSON."""
    from hvk.bases import base_file, run as base_run

    # is_file, not exists: on a case-insensitive filesystem a folder named "library" answers
    # to "Library" and would be opened as if it were the base.
    candidate = Path(args.file)
    if not candidate.is_absolute() and not candidate.is_file():
        candidate = location.vault / args.file
    if not candidate.is_file() and candidate.suffix != ".base":
        candidate = candidate.with_suffix(".base")
    if not candidate.is_file():
        raise base_file.BaseError(f"no such base file: {args.file}")

    parsed = base_file.load(candidate)
    result = base_run.run(parsed, conn, args.view, args.this)

    for warning in result.warnings:
        print(f"hvk: {warning}", file=sys.stderr)

    if args.json:
        output.emit_object(
            {
                "base": candidate.name,
                "view": result.view.name,
                "type": result.view.type,
                "columns": result.columns,
                "headers": result.headers,
                "total": result.total,
                "shown": len(result.rows),
                "rows": [
                    {"path": row["path"],
                     "values": {k: _jsonable(v) for k, v in row["values"].items()}}
                    for row in result.rows
                ],
                "groups": [
                    {"group": name, "paths": [row["path"] for row in rows]}
                    for name, rows in result.groups
                ],
                "summaries": {k: _jsonable(v) for k, v in result.summaries.items()},
                "warnings": result.warnings,
            },
            as_json=True,
        )
        return

    shown = len(result.rows)
    counted = f"{shown} of {result.total} rows" if shown != result.total else f"{shown} rows"
    print(f"{candidate.name} - view {result.view.name!r} ({counted})")
    print()

    def table(rows) -> str:
        return output.markdown_table(
            result.headers,
            [[bases_values.as_text(row["values"].get(column)) for column in result.columns]
             for row in rows],
        )

    if result.groups:
        for name, rows in result.groups:
            print(f"### {name}")
            print()
            print(table(rows))
            print()
    elif result.rows:
        print(table(result.rows))
    else:
        print("no rows match")

    if result.summaries:
        print()
        for column, value in result.summaries.items():
            label = result.view.summaries[column]
            print(f"{label} of {column}: {bases_values.as_text(value)}")


def _watch(location: paths.Locations, args: argparse.Namespace) -> int:
    """Run the watcher until interrupted, reporting one line per batch."""
    from hvk import watch as watcher

    def report(stats) -> None:
        output.emit_line(
            {"time": time.strftime("%H:%M:%S"), **stats.as_dict()},
            as_json=args.json,
            human=(
                f"{time.strftime('%H:%M:%S')}  "
                f"{stats.added} added, {stats.changed} changed, {stats.removed} removed"
                f"  ({stats.seconds:.2f}s)"
            ),
        )

    if not args.json:
        print(
            f"watching {location.vault} (debounce {args.debounce:g}s) -- Ctrl-C to stop",
            flush=True,
        )
    # Catch up first: whatever changed while nothing was watching is still a change.
    report(scanner.scan(location))
    try:
        watcher.watch(location, debounce=args.debounce, on_batch=report)
    except KeyboardInterrupt:
        pass
    return 0




def main(argv: list[str] | None = None) -> int:
    # Vaults contain CJK, emoji and accents; a Windows console defaulting to cp1252 would
    # crash on the first result rather than print it.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    args = _merge_globals(build_parser().parse_args(argv))
    try:
        return _run(args)
    except (paths.VaultError, db.IndexError_, query.QueryError,
            _base_file.BaseError, ExpressionError) as exc:
        print(f"hvk: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0
