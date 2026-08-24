"""Which parser reads which file (phase 7, ADR-0017).

``scan.py`` used to answer this with a dictionary of three extensions and an ``if`` with two
branches. That was honest while there were two parsers and no way for anyone else to add a
third. This is the same answer, said out loud.

A parser declares the extensions it understands and, optionally, a **claim**: a cheap look at
the text deciding whether this particular file is its business. That second part is not
decoration. The one community format worth reading first -- a Kanban board -- is a Markdown
file, marked by a line in its own frontmatter. An interface that could only dispatch on the
extension would have had nothing to say about it, and the plan named it as the example adapter
before this was written.

**Registration is explicit.** Nothing is discovered from installed packages. `hvk scan` walks a
vault and reads its files; making it also load and execute whatever third-party code happens to
declare an entry point is a decision about trust, not about parsing, and this project does not
make that one quietly. :func:`register` is public, so an adapter living outside this repository
registers itself by being imported -- one line, in the open, in something that already chose to
run it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from hvk.parse.model import Parsed


@dataclass(frozen=True)
class Parser:
    """One format this project can read.

    ``parse`` is called with the file's decoded text and its vault-relative path, and returns a
    :class:`~hvk.parse.model.Parsed`. It must not raise: a file it cannot read comes back with
    ``error`` set (see :class:`~hvk.parse.model.Parsed`).

    ``parse`` may be ``None``, which means "this extension is a known kind of file, and nothing
    is derived from it". `.base` is exactly that: the index records that a base exists, and the
    file is read by the Bases machinery on demand rather than shredded into rows.

    ``claims`` decides whether a file with a matching extension is really this parser's. Given
    the text and the path, cheaply -- it runs once per file in the vault, so it looks at the
    first few kilobytes, not at everything. ``None`` means "every file with my extension".

    ``priority`` orders parsers that could both claim a file; the highest wins, and ties go to
    whichever registered first. A specialised parser sits above the general one, which is why
    Kanban is 10 and Markdown is 0.
    """

    name: str
    extensions: tuple = ()
    kind: str = "note"                                  # what files.kind becomes
    parse: Callable[[str, str], Parsed] | None = None
    claims: Callable[[str, str], bool] | None = None
    priority: int = 0


@dataclass
class Registry:
    """Every parser known to this process, in the order they were registered."""

    parsers: list = field(default_factory=list)

    def register(self, parser: Parser) -> Parser:
        """Add *parser*, replacing any earlier one with the same name.

        Replacing rather than appending means importing an adapter twice is harmless, and that
        an adapter can override a built-in by taking its name -- which is a thing somebody will
        eventually want to do, and doing it by accident is what the name check prevents.
        """
        self.parsers = [p for p in self.parsers if p.name != parser.name]
        self.parsers.append(parser)
        return parser

    def extensions(self) -> set:
        """Every extension any registered parser answers for."""
        return {ext for parser in self.parsers for ext in parser.extensions}

    def candidates(self, ext: str) -> list:
        """Parsers that could read a file with this extension, best first."""
        ext = ext.lower().lstrip(".")
        matching = [p for p in self.parsers if ext in p.extensions]
        # sorted() is stable, so equal priorities keep registration order -- which is what
        # makes a rebuild deterministic rather than dependent on how a dict happened to hash.
        return sorted(matching, key=lambda p: -p.priority)

    @staticmethod
    def choose(candidates: list, text: str, path: str) -> Parser | None:
        """The first of *candidates* that claims this file, or None when none does.

        Split from :meth:`select` so a caller that already has the candidate list -- because it
        used it to decide whether reading the file was worth it at all -- does not look them up
        twice.
        """
        for parser in candidates:
            if parser.claims is None or parser.claims(text, path):
                return parser
        return None

    def select(self, ext: str, text: str, path: str) -> Parser | None:
        """The parser for this file, or None when nothing claims it.

        None is not a failure. It is how an attachment is recognised: a PNG has no parser and
        is still indexed, as a file with a name, a size and a hash.
        """
        return self.choose(self.candidates(ext), text, path)


#: The registry ``scan.py`` uses. Built-ins are registered by :mod:`hvk.parse`.
REGISTRY = Registry()


def register(parser: Parser) -> Parser:
    """Register *parser* for the rest of this process. The public way in."""
    return REGISTRY.register(parser)
