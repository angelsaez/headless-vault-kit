"""Obsidian Kanban boards (tier 2, phase 7, ADR-0017).

**This is the example adapter**, and it is here to be read as much as to be used. It is written
against the published interface and nothing else: it imports :class:`~hvk.parse.registry.Parser`
and the Markdown parser, contributes two fields the index did not have, and touches no part of
the core. Deleting this file removes the feature and breaks nothing.

## What a board is

A Kanban board is a Markdown file. The plugin marks it in the frontmatter and writes the rest in
ordinary Markdown, which is why the format is readable at all::

    ---
    kanban-plugin: board
    ---

    ## Backlog

    - [ ] Rewrite the intro @{2026-09-01}
    - [ ] Ask about the licence

    ## In progress

    - [ ] Draft the guide @{2026-08-28} @@{10:00}

    %% kanban:settings
    ...
    %%

Every card is a task and every heading is a list, so the ordinary Markdown parser already sees
almost all of it: the tasks, their text, their tags, their links. Almost.

## The two things it does not see

**Which list a card is in.** A card in *Done* and a card in *Backlog* are the same row in the
index. This adapter writes the list's name into the task's ``extra`` (ADR-0004), where the Tasks
plugin's fields already live.

**The date on a card.** Kanban writes dates as ``@{2026-09-01}``, its own syntax and nobody
else's, so ``hvk tasks --due-before`` -- which reads the ``due`` column -- was blind to every
card on every board. It is not any more, and that is the part worth having: an existing query
answers a new kind of file, with no new column, no new command and no change to the schema.

Both are read as **syntax in a file**. No plugin code is executed and no plugin has to be
installed; a board exported from someone else's vault reads the same as one written here.

## What it deliberately does not do

The settings block at the bottom of a board -- lane widths, colours, which date format the
plugin displays -- is Obsidian's comment syntax, so the Markdown parser already drops it. None
of it is worth a row in an index, and reading it would mean this adapter had opinions about a
plugin's configuration rather than about a vault's content.
"""

from __future__ import annotations

import re

from hvk.parse.markdown import ParsedNote, parse_file as parse_markdown
from hvk.parse.registry import Parser

# The line the plugin writes into a board's frontmatter, and nothing else writes anywhere.
MARKER_RE = re.compile(r"^kanban-plugin[ \t]*:", re.MULTILINE)

# How far into a file to look for that line. The claim runs once for every Markdown file in the
# vault, on every scan, so it reads the frontmatter and stops -- not the note. A board's
# frontmatter is three lines; four kilobytes is a wide margin around a generous one.
FRONTMATTER_LIMIT = 4096

# Kanban's own date and time syntax, configurable in the plugin and left at its defaults here.
# A board that changed the trigger character is read as a board with no dates rather than as a
# board with wrong ones -- the same bargain ADR-0004 struck for the Tasks plugin's vocabulary.
DATE_RE = re.compile(r"@\{(\d{4}-\d{2}-\d{2})\}")
TIME_RE = re.compile(r"@@\{(\d{1,2}:\d{2})\}")


def is_board(text: str, path: str = "") -> bool:
    """Whether this Markdown file is a Kanban board.

    Only the frontmatter counts. A note *about* Kanban that quotes ``kanban-plugin:`` in its
    body is a note, and reading it as a board would put its example cards in the index as real
    tasks -- which is the kind of wrong answer nobody thinks to check for.
    """
    if not text.startswith("---"):
        return False
    window = text[:FRONTMATTER_LIMIT]
    closes = [at for at in (window.find("\n---", 3), window.find("\n...", 3)) if at != -1]
    frontmatter = window[: min(closes)] if closes else window
    return MARKER_RE.search(frontmatter) is not None


def _lists(note: ParsedNote) -> list:
    """``(line, name)`` for every heading on the board, which is what a list is.

    Any level, not only ``##``. The plugin writes level two, but a board edited by hand is
    still a board, and "the heading this card is under" is what a person reading it sees.
    """
    return sorted((heading.line, heading.text) for heading in note.headings)


def _list_at(lists: list, line: int) -> str:
    """The name of the list a card on *line* belongs to: the nearest heading above it."""
    name = ""
    for at, heading in lists:
        if at > line:
            break
        name = heading
    return name


def parse_file(text: str, path: str) -> ParsedNote:
    """Parse a board: ordinary Markdown, plus the list and the date on each card."""
    note = parse_markdown(text, path)
    lists = _lists(note)

    for task in note.tasks:
        name = _list_at(lists, task.line)
        if name:
            task.extra["list"] = name

        # The date is stripped from the card's own text, exactly as the Tasks plugin's markers
        # are (ADR-0004): what the card says and what is known about it are different things,
        # and leaving '@{2026-09-01}' in the text means every search for a card matches its
        # syntax as readily as its words.
        date = DATE_RE.search(task.text)
        time = TIME_RE.search(task.text)
        if date and not task.due:
            task.due = date.group(1)
        if time:
            task.extra["time"] = time.group(1)
        if date or time:
            stripped = TIME_RE.sub(" ", DATE_RE.sub(" ", task.text))
            task.text = re.sub(r"[ \t]{2,}", " ", stripped).strip()

    return note


#: Priority 10, above Markdown's 0: a board is a Markdown file, and both parsers can read it.
#: The claim is what decides, and the priority is what makes it get asked first.
PARSER = Parser(
    name="kanban",
    extensions=("md",),
    kind="note",
    parse=parse_file,
    claims=is_board,
    priority=10,
)
