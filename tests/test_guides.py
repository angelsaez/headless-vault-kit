"""The guides' examples have to be real commands.

`test_skill.py` already runs every example in the skill, because an agent that trusts a flag
which does not exist fails in a way that looks like a broken vault. The guides are read by
people, who fail more quietly and blame themselves — and they are the longest documents here,
the ones that drift first.

Running every example is not possible: a guide is allowed to say `hvk backlinks "Project Alpha"`
about a vault it is describing rather than one that exists. So what is checked is the part that
can rot without anyone noticing — that the command exists, that every flag is real, and that a
documented query is one this project can actually parse.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from hvk import dql
from hvk.cli import build_parser

GUIDES = [
    Path(__file__).resolve().parent.parent / "docs" / "GUIDE.md",
    Path(__file__).resolve().parent.parent / "docs" / "GUIDE.es.md",
]
BLOCK_RE = re.compile(r"```(?:sh|bash)\n(.*?)```", re.DOTALL)


def documented() -> list:
    """Every `hvk` line in either guide, as (guide name, command)."""
    found = []
    for guide in GUIDES:
        for block in BLOCK_RE.findall(guide.read_text(encoding="utf-8")):
            for line in block.splitlines():
                if not line.strip().startswith("hvk "):
                    continue
                lexer = shlex.shlex(line, posix=True, punctuation_chars=False)
                lexer.whitespace_split = True
                lexer.commenters = "#"          # a query may contain a #tag; shlex knows
                found.append((guide.name, shlex.join(list(lexer))))
    return found


def test_both_guides_are_there_and_full_of_examples():
    for guide in GUIDES:
        assert guide.is_file(), guide
    assert len(documented()) >= 40


@pytest.mark.parametrize("guide, command", documented(), ids=lambda v: v[:60])
def test_every_documented_command_is_a_real_command(guide, command):
    """Argparse decides. An unknown subcommand or a flag that never existed exits here."""
    try:
        build_parser().parse_args(shlex.split(command)[1:])
    except SystemExit as exc:                     # argparse's way of saying no
        pytest.fail(f"{guide} documents a command hvk would refuse: {command} ({exc})")


@pytest.mark.parametrize(
    "guide, command",
    [(g, c) for g, c in documented() if shlex.split(c)[1:2] == ["dql"]],
    ids=lambda v: v[:60],
)
def test_every_documented_query_parses(guide, command):
    """A guide that shows a query this cannot read is worse than one that shows none."""
    arguments = build_parser().parse_args(shlex.split(command)[1:])
    if not arguments.query:
        return                                    # --note, whose queries live in the note
    dql.parse(arguments.query)


# -- the MCP tool reference -------------------------------------------------------------------
#
# The guides document every MCP tool and every argument in a table. A client is handed those
# names by `tools/list` and never reads the guide, so nothing in the running system notices when
# the two disagree -- which makes this the exact shape of documentation that rots silently.

TOOL_ROW_RE = re.compile(r"^\| `(\w+)` \| (.*?) \| ", re.MULTILINE)
# Every argument in those tables is written `name` — description, and the dash is what tells an
# argument from an example: `home` matches `home/diy` names no argument, and neither does
# ```dataview```. Requiring it means this needs no list of words to forgive, which is the kind of
# list that quietly grows until it is hiding a real mistake.
ARGUMENT_RE = re.compile(r"`(\w+)`(?:\*\*)? — ")


def documented_tools(guide: Path) -> dict:
    """`{tool: {arguments}}` as one guide's tables describe them."""
    text = guide.read_text(encoding="utf-8")
    found = {}
    for name, arguments in TOOL_ROW_RE.findall(text):
        # The argument cell also names types and examples in backticks -- 'YYYY-MM-DD', 'this',
        # 'home/diy'. Only what the schema actually calls an argument counts, and anything the
        # schema does not know is caught by the comparison below.
        found[name] = set(ARGUMENT_RE.findall(arguments))
    return found


def published_tools() -> dict:
    from hvk.mcp import tools

    return {tool.name: set(tool.schema["properties"]) for tool in tools.ALL}


@pytest.mark.parametrize("guide", GUIDES, ids=lambda g: g.name)
def test_every_mcp_tool_is_documented(guide):
    assert set(documented_tools(guide)) == set(published_tools()), (
        f"{guide.name} and hvk.mcp.tools disagree about which tools exist"
    )


@pytest.mark.parametrize("guide", GUIDES, ids=lambda g: g.name)
def test_every_argument_of_every_tool_is_documented(guide):
    documented, published = documented_tools(guide), published_tools()
    for name, arguments in published.items():
        # A subset check on the guide's side would let a documented argument that no longer
        # exists survive, which is the more misleading of the two failures.
        assert documented[name] >= arguments, (
            f"{guide.name} does not document {sorted(arguments - documented[name])} "
            f"for the {name} tool"
        )
        invented = documented[name] - arguments
        assert not invented,             f"{guide.name} documents {sorted(invented)} on {name}, which is not an argument"


@pytest.mark.parametrize("guide", GUIDES, ids=lambda g: g.name)
def test_the_required_arguments_are_marked(guide):
    """A client is not obliged to honour the published schema, so a reader of the guide has to
    be able to see which arguments a tool refuses to run without."""
    from hvk.mcp import tools

    text = guide.read_text(encoding="utf-8")
    for tool in tools.ALL:
        for argument in tool.schema["required"]:
            assert "**" + chr(92) + f"*`{argument}`**" in text, (
                f"{guide.name} does not mark {argument} as required anywhere "
                f"(needed by {tool.name})"
            )
