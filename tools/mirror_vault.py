#!/usr/bin/env python3
"""Mirror a vault into a working copy, so real data can be tested against safely.

A standing rule forbids pointing anything at the production vault during development, and that
rule is worth keeping even though ``hvk`` only ever reads. This makes the sanctioned
alternative one command: a mirror that leaves the original untouched, drops what must never be
copied, and refuses the destinations that would turn a convenience into an incident.

    python tools/mirror_vault.py --source "C:/Obsidian/My Vault" --dest "C:/work/mirror"

Re-running it updates the mirror in place and deletes what has disappeared from the source, so
it can be repeated whenever the real vault has moved on.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import shutil
import sys
from pathlib import Path

# Never copied. The private folder appears under both spellings across this project's
# documents, and getting that wrong once would copy secrets.
EXCLUDED_DIRS = {"_private", "_privada", ".git", ".trash", ".obsidian-git", "node_modules"}
# Dot-directories are skipped wholesale, except this one: its JSON files are the vault's
# configuration, which is exactly what an inventory needs to read.
KEPT_DOT_DIR = ".obsidian"
EXCLUDED_FILE_PATTERNS = ("workspace", "workspace.json", "workspace-mobile.json",
                          "*.tmp", "*.partial", "~$*", ".DS_Store", "Thumbs.db", "desktop.ini")


class MirrorError(Exception):
    """Raised when the mirror would be unsafe or pointless."""


def is_excluded_dir(name: str) -> bool:
    lowered = name.lower()
    if lowered in EXCLUDED_DIRS:
        return True
    return name.startswith(".") and name != KEPT_DOT_DIR


def is_excluded_file(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in EXCLUDED_FILE_PATTERNS)


def iter_source(source: Path):
    """Yield every path to mirror, relative to *source*, in a stable order."""
    stack = [source]
    while stack:
        current = stack.pop()
        for entry in sorted(current.iterdir(), key=lambda p: p.name):
            if entry.is_dir():
                if not is_excluded_dir(entry.name):
                    stack.append(entry)
            elif not is_excluded_file(entry.name):
                yield entry.relative_to(source)


def inside_a_git_repository(path: Path) -> Path | None:
    for candidate in [path, *path.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def check(source: Path, dest: Path, *, allow_repo: bool) -> None:
    if not source.is_dir():
        raise MirrorError(f"source is not a directory: {source}")
    if source == dest:
        raise MirrorError("source and destination are the same directory")
    if dest.is_relative_to(source):
        raise MirrorError(
            f"the destination sits inside the source ({dest}); mirroring would recurse"
        )
    if source.is_relative_to(dest):
        raise MirrorError(
            f"the source sits inside the destination ({source}); mirroring would delete it"
        )
    if (dest / ".obsidian").is_dir() and not (dest / ".hvk-mirror").exists():
        raise MirrorError(
            f"{dest} looks like a real vault and was not created by this script. Refusing to "
            f"overwrite it. Choose an empty directory."
        )
    repository = inside_a_git_repository(dest)
    if repository is not None and not allow_repo:
        raise MirrorError(
            f"the destination is inside the git repository at {repository}. A vault mirror is "
            f"personal data and one 'git add -A' away from being committed. Choose a path "
            f"outside it, or pass --allow-inside-repo if you have gitignored it deliberately."
        )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mirror(source: Path, dest: Path, *, allow_repo: bool = False, verbose: bool = False) -> dict:
    check(source, dest, allow_repo=allow_repo)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / ".hvk-mirror").write_text(
        f"Mirror of {source}\nMade by tools/mirror_vault.py. Safe to delete.\n",
        encoding="utf-8", newline="\n",
    )

    wanted = set()
    stats = {"copied": 0, "updated": 0, "unchanged": 0, "removed": 0, "bytes": 0}

    for relative in iter_source(source):
        wanted.add(relative)
        origin, target = source / relative, dest / relative
        if target.exists():
            same_size = target.stat().st_size == origin.stat().st_size
            if same_size and digest(target) == digest(origin):
                stats["unchanged"] += 1
                continue
            stats["updated"] += 1
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            stats["copied"] += 1
        shutil.copy2(origin, target)
        stats["bytes"] += origin.stat().st_size
        if verbose:
            print(f"  + {relative.as_posix()}")

    for existing in sorted(dest.rglob("*"), reverse=True):
        if existing.is_file():
            relative = existing.relative_to(dest)
            if relative.name != ".hvk-mirror" and relative not in wanted:
                existing.unlink()
                stats["removed"] += 1
        elif existing.is_dir() and not any(existing.iterdir()):
            existing.rmdir()

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mirror_vault",
        description="Mirror an Obsidian vault into a working copy for safe testing.",
        epilog=(
            "Never copied: _PRIVATE and _PRIVADA, .git, .trash, any other dot-directory, "
            "and Obsidian's workspace files. .obsidian/*.json is kept, because a vault "
            "inventory has to read the configuration."
        ),
    )
    parser.add_argument("--source", required=True, type=Path, help="the real vault")
    parser.add_argument("--dest", required=True, type=Path, help="where the mirror goes")
    parser.add_argument("--allow-inside-repo", action="store_true",
                        help="permit a destination inside a git repository (rarely right)")
    parser.add_argument("--verbose", action="store_true", help="list every file copied")
    args = parser.parse_args(argv)

    try:
        stats = mirror(
            args.source.expanduser().resolve(),
            args.dest.expanduser().resolve(),
            allow_repo=args.allow_inside_repo,
            verbose=args.verbose,
        )
    except MirrorError as exc:
        print(f"mirror_vault: {exc}", file=sys.stderr)
        return 2

    print(
        f"copied {stats['copied']}, updated {stats['updated']}, unchanged {stats['unchanged']}, "
        f"removed {stats['removed']}  ({stats['bytes'] / 1_048_576:.1f} MB written)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
