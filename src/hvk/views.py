"""Materialised views: the output of a base, kept up to date inside a note (phase 4).

Obsidian renders a base on screen, which is no use on a phone that is only syncing files, and
no use at all on a server with no screen. A materialised view writes the same table into a
note, so it arrives on every device the way any other note does.

A note declares what it wants and where to put it::

    %% view: base "Projects.base" view "Table" every 30m %%
    <!-- view:start -->
    (regenerated)
    <!-- view:end -->

The Spanish spellings work identically -- ``%% vista: %%`` with ``<!-- vista:inicio -->`` and
``<!-- vista:fin -->``, and ``base``/``vista``/``cada`` for the settings -- because the marker
lives in somebody's *notes* and a vault is written in whatever language its author thinks in.
A note picks one dialect and its markers must match it.

Nothing here writes a timestamp. Regenerating unchanged data has to produce the same bytes,
or the exit criterion of phase 4 -- regenerate twice, get no diff -- would be false on the
second run, every run.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from hvk import paths, scan as scanner, write
from hvk.bases import base_file, render as base_render, run as base_run
from hvk.bases.base_file import BaseError
from hvk.bases.expr import ExpressionError

# Dialect -> (opening marker, closing marker).
DIALECTS = {
    "vista": ("<!-- vista:inicio -->", "<!-- vista:fin -->"),
    "view": ("<!-- view:start -->", "<!-- view:end -->"),
}
# Spelling of a setting -> what it means. Both languages are accepted in either dialect: a
# typo should be an error, but writing "every" in a Spanish note should not be.
SETTINGS = {"base": "base", "vista": "view", "view": "view", "cada": "every", "every": "every"}

DIRECTIVE_RE = re.compile(
    r"%%[ \t]*(?P<dialect>vista|view)[ \t]*:(?P<settings>[^%]*)%%", re.IGNORECASE
)
SETTING_RE = re.compile(r'(?P<key>[^\s"]+)[ \t]+(?:"(?P<quoted>[^"]*)"|(?P<bare>[^\s"]+))')
EVERY_RE = re.compile(r"^(\d+)[ \t]*(m|min|mins|minutes?|h|hours?|d|days?)$", re.IGNORECASE)
MINUTES = {"m": 1, "min": 1, "mins": 1, "minute": 1, "minutes": 1,
           "h": 60, "hour": 60, "hours": 60, "d": 1440, "day": 1440, "days": 1440}


class ViewError(Exception):
    """A note declares a view that cannot be honoured. Never raised for 'nothing to do'."""


@dataclass(frozen=True)
class Declaration:
    """One ``%% vista: ... %%`` directive and the block it fills."""

    line: int
    dialect: str
    base: str
    view: str | None
    every: str | None
    every_minutes: int | None
    block: write.Block


@dataclass
class Outcome:
    """What happened to one declaration, or to one note that could not be read at all."""

    note: str
    line: int = 0
    base: str = ""
    view: str = ""
    rows: int | None = None
    status: str = "error"
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "note": self.note, "line": self.line, "base": self.base, "view": self.view,
            "rows": self.rows, "status": self.status, "detail": self.detail,
        }


@dataclass
class Report:
    outcomes: list = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "error")

    @property
    def changed(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status in ("stale", "written"))


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _settings(raw: str, where: str) -> dict:
    """Parse ``base "X.base" vista "Table" cada 30m`` into a dictionary.

    An unrecognised key is an error rather than something to ignore: a typo that is skipped
    silently produces a view that quietly renders the wrong thing, which is worse than one
    that refuses to render at all.
    """
    settings: dict[str, str] = {}
    consumed = 0
    for match in SETTING_RE.finditer(raw):
        consumed = match.end()
        key = match.group("key").lower()
        if key not in SETTINGS:
            raise ViewError(
                f"{where}: {match.group('key')!r} is not something a view understands. "
                f"Known settings: base, vista/view, cada/every."
            )
        name = SETTINGS[key]
        if name in settings:
            raise ViewError(f"{where}: {name} is given twice")
        settings[name] = match.group("quoted") or match.group("bare")

    if raw[consumed:].strip():
        raise ViewError(f"{where}: cannot make sense of {raw[consumed:].strip()!r}")
    if "base" not in settings:
        raise ViewError(f'{where}: no base named. Write base "Something.base".')
    return settings


def _minutes(value: str, where: str) -> int:
    match = EVERY_RE.match(value.strip())
    if not match:
        raise ViewError(
            f"{where}: {value!r} is not an interval. Write something like 30m, 2h or 1d."
        )
    return int(match.group(1)) * MINUTES[match.group(2).lower()]


def declarations(text: str) -> list[Declaration]:
    """Every view declared in *text*, each paired with the block it fills.

    Pairing is positional: a directive owns the first block of its own dialect that follows
    it. Anything ambiguous -- a directive with no block before the next directive, a block
    with no directive at all -- is an error. A generated block nobody claims is a block
    nothing will ever refresh, and saying so is the only way it gets noticed.
    """
    found = [
        (match, _line_of(text, match.start()))
        for match in DIRECTIVE_RE.finditer(text)
    ]
    if not found:
        for dialect, (begin, end) in DIALECTS.items():
            if begin in text:
                raise ViewError(
                    f"line {_line_of(text, text.index(begin))}: a {begin} block with nothing "
                    f"saying what generates it. Add a %% {dialect}: base \"...\" %% line "
                    f"above it, or delete the markers."
                )
        return []

    blocks: dict[str, list] = {
        dialect: write.find_blocks(text, begin, end)
        for dialect, (begin, end) in DIALECTS.items()
    }
    taken: dict[str, int] = {dialect: 0 for dialect in DIALECTS}
    declared: list[Declaration] = []

    for position, (match, line) in enumerate(found):
        where = f"line {line}"
        dialect = match.group("dialect").lower()
        settings = _settings(match.group("settings"), where)
        every = settings.get("every")

        candidates = list(enumerate(blocks[dialect]))[taken[dialect]:]
        found_at, block = next(
            ((at, b) for at, b in candidates if b.start >= match.end()), (None, None)
        )
        if block is None:
            begin, _ = DIALECTS[dialect]
            raise ViewError(f"{where}: no {begin} block follows this directive")
        following = found[position + 1][0].start() if position + 1 < len(found) else len(text)
        if block.start > following:
            raise ViewError(
                f"{where}: the next directive comes before this one's block. Every "
                f"%% {dialect}: ... %% needs its own markers directly underneath it."
            )
        taken[dialect] = found_at + 1

        declared.append(
            Declaration(
                line=line,
                dialect=dialect,
                base=settings["base"],
                view=settings.get("view"),
                every=every,
                every_minutes=_minutes(every, where) if every else None,
                block=block,
            )
        )

    orphaned = sum(len(found_blocks) for found_blocks in blocks.values()) - len(declared)
    if orphaned > 0:
        raise ViewError(
            f"{orphaned} generated block(s) in this note have no directive saying what "
            f"generates them. Nothing would ever refresh them."
        )
    return declared


def _indexed(conn: sqlite3.Connection, note: str) -> bool:
    return conn.execute("SELECT 1 FROM files WHERE path = ?", (note,)).fetchone() is not None


def _bases_named(conn: sqlite3.Connection, name: str) -> list:
    """Every indexed base whose path ends with *name*, matched on whole path segments.

    Bases are few -- one, in the vault this was written for -- so the filtering happens here
    rather than in SQL, where matching a trailing segment means escaping a LIKE pattern built
    out of untrusted text.
    """
    wanted = name if name.endswith(".base") else name + ".base"
    rows = conn.execute("SELECT path FROM files WHERE kind = 'base' ORDER BY path").fetchall()
    return [row["path"] for row in rows
            if row["path"] == wanted or row["path"].endswith("/" + wanted)]


def _render(conn: sqlite3.Connection, vault: write.Vault, note: str, indexed: bool,
            declaration: Declaration) -> tuple[str, int, str]:
    """Run one declaration's base view and return its Markdown, row count and any warning."""
    name = declaration.base
    # The base is named by a note, and a note is untrusted input, so the path is
    # resolved and checked to be inside the vault before anything is opened.
    candidate = vault.resolve(name)
    if not candidate.is_file() and candidate.suffix != ".base":
        candidate = vault.resolve(name + ".base")
    if not candidate.is_file():
        # Not a path, then. Try it as a *name*, which is how a note names anything else in a
        # vault -- a wikilink does not carry a folder either (ADR-0003), and somebody writing
        # a directive by hand has no reason to expect these to differ. The index already
        # knows every base there is, so this costs one query and no walk.
        matches = _bases_named(conn, name)
        if len(matches) > 1:
            raise ViewError(
                f"more than one base is called {name}: {', '.join(matches[:3])}. "
                f"Name it by its path in the vault to say which one."
            )
        if not matches:
            raise ViewError(
                f"no such base file in the vault: {name}. Name it by path from the vault "
                f"root, or by filename if there is only one with that name."
            )
        candidate = vault.resolve(matches[0])

    parsed = base_file.load(candidate)
    # 'this' is the note holding the view, which is what a base embedded in a note sees --
    # but only once the index knows the note exists. A view written on a phone thirty seconds
    # ago should still render, with a word about why 'this' is empty, rather than fail.
    result = base_run.run(parsed, conn, declaration.view, note if indexed else None)

    warnings = list(result.warnings)
    if not indexed:
        warnings.append(
            "not in the index yet, so expressions using 'this' see nothing; run hvk scan"
        )
    if any(row["path"] == note for row in result.rows):
        # Harmless for a table of properties, and a feedback loop for a view sorted by
        # file.mtime: writing the note changes the value the view is ordered by.
        warnings.append(
            "this note is one of its own rows; a view over file.mtime or file.size would "
            "then never settle"
        )
    return base_render.to_markdown(result, links=True), result.total, "; ".join(warnings)


def _refresh_note(conn: sqlite3.Connection, vault: write.Vault, note: str,
                  apply: bool) -> list[Outcome]:
    original = vault.read(note)
    if not original.exists:
        return [Outcome(note=note, detail="indexed, but not on disk any more")]

    text = original.text
    indexed = _indexed(conn, note)
    outcomes: list[Outcome] = []
    index = 0
    while True:
        declared = declarations(text)
        if index >= len(declared):
            break
        declaration = declared[index]
        body, rows, warning = _render(conn, vault, note, indexed, declaration)
        updated = write.replace_block(text, declaration.block, body)
        outcomes.append(
            Outcome(
                note=note, line=declaration.line, base=declaration.base,
                view=declaration.view or "(first)", rows=rows,
                status="stale" if updated != text else "up to date", detail=warning,
            )
        )
        text = updated
        index += 1

    if not outcomes:
        return []

    changed = text != original.text
    if apply:
        # One write per note, however many views it holds: a note with two tables should be
        # one atomic change, not two, and should wake the watcher once rather than twice.
        wrote = vault.write(original, text) if changed else False
        for outcome in outcomes:
            if outcome.status != "error":
                outcome.status = "written" if (wrote and outcome.status == "stale") else "unchanged"
    return outcomes


def notes_with_views(location: paths.Locations, prefix: str | None = None) -> list[str]:
    """Every note in the vault, optionally under *prefix*, as vault-relative paths.

    Discovery walks the vault rather than the index, through the scanner's own iterator so
    that the exclusion rules of ADR-0002 come from one place. Asking the index instead would
    be cheaper and would make a note invisible until the next scan -- a view written on a
    phone would then do nothing until something else happened to run.
    """
    wanted = prefix.replace("\\", "/").strip("/") if prefix else None
    found = []
    for path in scanner.iter_vault_files(location.vault):
        if path.suffix.lower() != ".md":
            continue
        relative = path.relative_to(location.vault).as_posix()
        if wanted and relative != wanted and not relative.startswith(wanted + "/"):
            continue
        found.append(relative)
    return found


def refresh(conn: sqlite3.Connection, location: paths.Locations, *,
            path: str | None = None, apply: bool = False) -> Report:
    """Regenerate every declared view, or report what would change.

    One note failing does not stop the others: a cron job that gives up on the whole vault
    because one note has a typo is a cron job that quietly stops working.
    """
    vault = write.Vault(location.vault)
    report = Report()

    for note in notes_with_views(location, path):
        try:
            raw = (location.vault / note).read_text(encoding="utf-8", errors="strict")
        except (OSError, ValueError):
            # Unreadable notes are the scanner's problem to report, not this command's.
            continue
        if "%%" not in raw and not any(begin in raw for begin, _ in DIALECTS.values()):
            continue
        try:
            report.outcomes.extend(_refresh_note(conn, vault, note, apply))
        except (ViewError, BaseError, ExpressionError, write.WriteError) as exc:
            report.outcomes.append(Outcome(note=note, detail=str(exc)))

    return report
