"""The ``hvk`` command line.

Human-readable tables by default, ``--json`` for the agent. This is what the agent uses
instead of reading files one by one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hvk import __version__, db, output, paths, query, scan as scanner

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

    return parser


def _run(args: argparse.Namespace) -> int:
    location = paths.resolve(args.vault, args.index)

    if args.command in ("scan", "rebuild"):
        stats = scanner.scan(location, rebuild=args.command == "rebuild")
        output.emit_object(
            {"vault": str(location.vault), "index": str(location.index_dir), **stats.as_dict()},
            as_json=args.json,
        )
        return 0

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
    finally:
        conn.close()
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
    except (paths.VaultError, db.IndexError_, query.QueryError) as exc:
        print(f"hvk: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0
