"""Format parsers, and the point at which one is registered (ADR-0017).

Tier 0 -- what the app itself derives from a note -- is :mod:`hvk.parse.markdown`. Tier 1 is
Obsidian's own formats: :mod:`hvk.parse.canvas`, and `.base`, which the index records the
existence of and the Bases machinery reads on demand. Tier 2 is community formats whose state
lives in files somebody can parse, and :mod:`hvk.parse.kanban` is the first of them.

Plugin code is never executed. Only file formats are read.

**Adding a parser is one line.** The tuple below is the registration point, and everything
about how a file gets read follows from it:

    from hvk.parse.registry import Parser, register
    register(Parser(name="mine", extensions=("mine",), kind="note", parse=my_parse))

An adapter that lives in this repository is added to ``BUILT_IN``. One that lives in your own
package calls :func:`~hvk.parse.registry.register` when it is imported, and is named in the
``HVK_PARSERS`` environment variable so that something imports it::

    HVK_PARSERS=hvk_excalidraw hvk scan

Nothing is discovered automatically: see :mod:`hvk.parse.registry` for why a vault scan does not
go looking for code to run, and ADR-0019 for why naming the modules is the middle ground.

The contract itself -- what a parser is handed and what it gives back -- is
:mod:`hvk.parse.model`.
"""

from hvk.parse import canvas, kanban, markdown
from hvk.parse.model import Block, Heading, Parsed, Prop, RawLink, Tag, Task
from hvk.parse.markdown import ParsedNote, parse_note
from hvk.parse.registry import (
    ENV_VAR, REGISTRY, Parser, ParserError, Registry, load_declared, register,
)

# `.base` has no parser on purpose: the index records that a base exists so that `hvk views`
# can find one by name, and the file is read whole, on demand, by the Bases machinery. Shredding
# a query definition into rows would derive nothing anybody asks the index for.
BASE = Parser(name="base", extensions=("base",), kind="base")

#: Registered in order, most general first. Where two could read the same file, priority
#: decides -- kanban sits above markdown and claims only the files it recognises.
BUILT_IN = (markdown.PARSER, canvas.PARSER, BASE, kanban.PARSER)

for _parser in BUILT_IN:
    register(_parser)

__all__ = [
    "BASE", "BUILT_IN", "Block", "ENV_VAR", "Heading", "Parsed", "ParsedNote", "Parser",
    "ParserError", "Prop", "REGISTRY", "RawLink", "Registry", "Tag", "Task", "canvas",
    "kanban", "load_declared", "markdown", "parse_note", "register",
]
