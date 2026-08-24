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
