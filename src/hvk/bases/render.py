"""A base result as Markdown: what ``hvk base`` prints, and what a materialised view stores.

Both need the same tables, so they share this rather than growing two renderers that drift.
The one difference is linking: a table printed in a terminal cannot be clicked, and a table
written into a note is meant to be, so ``links=True`` turns the file column into wikilinks.
"""

from __future__ import annotations

from hvk.output import markdown_table
from hvk.bases.values import File, as_text

NO_ROWS = "no rows match"

# Columns that name the row's own file. Obsidian renders these as links to the note, so a
# materialised view does too -- a table of plain names on a phone is a table you cannot follow.
FILE_COLUMNS = {"file", "file.name", "file.basename", "file.path", "file.link"}


def wikilink(path: str, display: str) -> str:
    """A link Obsidian can follow, showing exactly what the plain-text cell would show.

    The target is the full path, so two notes with the same name never send the reader to the
    wrong one, with the extension dropped for notes as links are written everywhere else in a
    vault. The display text is left alone: a materialised view should read the same as
    ``hvk base``, only clickable. The pipe is escaped later by ``markdown_table``, which is
    exactly what a wikilink alias needs inside a table cell.
    """
    target = path[:-3] if path.endswith(".md") else path
    if not target or not display:
        return display
    return f"[[{target}]]" if display == target else f"[[{target}|{display}]]"


def cell(value, *, links: bool) -> str:
    if links and isinstance(value, File):
        return wikilink(value.path, as_text(value))
    if links and isinstance(value, (list, tuple)):
        return ", ".join(cell(item, links=True) for item in value)
    return as_text(value)


def to_markdown(result, *, links: bool = False) -> str:
    """Render *result* -- groups, table and summaries -- with no timestamp anywhere.

    Nothing here may vary between two runs over unchanged data. A "generated at" line would
    be friendly and would also make every regeneration a diff, which is precisely the exit
    criterion phase 4 has to meet.
    """
    def cells(row) -> list:
        rendered = []
        for column in result.columns:
            text = cell(row["values"].get(column), links=links)
            # file.name evaluates to a plain string, so the link has to come from the row
            # itself rather than from the type of the value.
            if links and column in FILE_COLUMNS:
                text = wikilink(row["path"], text)
            rendered.append(text)
        return rendered

    def table(rows) -> str:
        return markdown_table(result.headers, [cells(row) for row in rows])

    parts: list[str] = []
    if result.groups:
        for name, rows in result.groups:
            parts.extend([f"### {name}", "", table(rows), ""])
    elif result.rows:
        parts.append(table(result.rows))
    else:
        parts.append(NO_ROWS)

    if result.summaries:
        parts.append("")
        parts.extend(
            f"{result.view.summaries[column]} of {column}: {as_text(value)}"
            for column, value in result.summaries.items()
        )
    return "\n".join(parts)
