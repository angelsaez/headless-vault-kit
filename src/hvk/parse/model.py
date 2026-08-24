"""What a parser hands back, and what the index stores (phase 7, ADR-0017).

This is the contract, and it was **extracted rather than invented**. Two parsers were already
written -- Markdown and JSON Canvas -- and everything they had in common was already here, spread
between them: a title, some searchable text, and five kinds of row. Pulling it into one place
adds no capability. It makes the shape sayable, so a third parser can be written against it
without reading the second one.

Every field is what ``scan.py`` writes into a table of the same name. That is deliberate: a
contract that can express something the index cannot store is a contract with a lie in it.

A parser returns :class:`Parsed`, or a subclass of it carrying whatever else that format has
that nobody else does -- :class:`hvk.parse.markdown.ParsedNote` adds the frontmatter mapping,
:class:`hvk.parse.canvas.Canvas` adds the boxes and the arrows. The index ignores the extras;
the commands that ask about one format use them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Prop:
    """One property: frontmatter, or a Dataview-style ``key:: value`` written in the body."""

    key: str
    value: str | None
    value_type: str          # string|number|bool|null|date|datetime|list|map
    idx: int | None          # position within a list, None for a scalar
    inline: bool             # True for 'key:: value', False for frontmatter
    line: int


@dataclass
class Tag:
    tag: str                 # without '#', nesting preserved: 'home/nested'
    source: str              # 'frontmatter' | 'inline' | 'canvas'
    line: int


@dataclass
class Heading:
    level: int
    text: str
    line: int


@dataclass
class Block:
    block_id: str
    line: int


@dataclass
class RawLink:
    """A link as written, before it is resolved against the file index (ADR-0003).

    Resolution is not a parser's job and must not be: it needs every file in the vault, and a
    parser only ever sees one. Handing back what the author wrote and letting the second pass
    decide what it points at is what makes a link from a canvas resolve by exactly the rules a
    link from a note does.
    """

    target_raw: str
    subpath: str | None      # '#Heading' or '#^block-id', without the target
    kind: str                # 'wikilink' | 'markdown' | 'external' | 'canvas'
    embed: bool
    line: int


@dataclass
class Task:
    text: str
    status: str              # the raw character between the brackets
    done: bool
    line: int
    due: str | None = None
    # Tier-2 fields: whatever a plugin's syntax puts on the line (ADR-0004). Stored as JSON,
    # so an adapter can contribute a field the schema never heard of without a migration.
    extra: dict = field(default_factory=dict)


@dataclass
class Parsed:
    """Everything one file contributes to the index.

    ``body`` is what full-text search will match on, which is not always the file's text: a
    canvas is JSON, and what belongs in the search index is the prose written on it, not its
    coordinates.

    ``error`` is how a parser reports a file it could not read. **Returning it is the contract;
    raising is not.** One unparseable file must never stop a scan -- it is recorded against that
    file in ``files.parse_error`` and the walk goes on -- so a parser that raises is a parser
    that can take a vault down with a single bad note.
    """

    title: str = ""
    body: str = ""
    props: list[Prop] = field(default_factory=list)
    tags: list[Tag] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    links: list[RawLink] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    error: str | None = None
