"""The skill's examples have to actually run.

A skill that documents a flag which does not exist is worse than no skill: the agent trusts
it, the command fails, and the failure looks like a broken vault. So every `hvk` line in the
shell blocks of SKILL.md is executed here against a synthetic vault.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from hvk import cli
from conftest import VAULTS

SKILL = Path(__file__).resolve().parent.parent / "skills" / "vault-queries" / "SKILL.md"
BLOCK_RE = re.compile(r"```bash\n(.*?)```", re.DOTALL)

# Long-running or destructive by nature, or needing directories no synthetic vault has;
# documented in prose, never in a runnable example block.
NOT_RUNNABLE = {"watch", "jobs"}
# ...and jobs, whose two directories have no defaults on purpose (ADR-0009), so there is
# no invocation that would run anywhere.

# Which synthetic vault an example needs. Everything answers against the realistic vault
# except the .base examples, which need a vault that has base files in it.
VAULT_FOR = {"base": "bases", "views": "views", "canvas": "canvas", "dql": "dataview"}
DEFAULT_VAULT = "basic"


def documented_commands() -> list[str]:
    """Every `hvk` line in the skill's shell blocks, with its trailing comment removed.

    The comment is stripped by shlex rather than by splitting on the first `#`, because a
    query is allowed to contain one: `hvk dql "LIST FROM #project"` cut at the hash leaves an
    unbalanced quote, and the example that exposed it was correct.
    """
    commands = []
    for block in BLOCK_RE.findall(SKILL.read_text(encoding="utf-8")):
        for line in block.splitlines():
            if not line.strip().startswith("hvk "):
                continue
            lexer = shlex.shlex(line, posix=True, punctuation_chars=False)
            lexer.whitespace_split = True
            lexer.commenters = "#"
            commands.append(shlex.join(list(lexer)))
    return commands


def test_the_skill_actually_contains_examples():
    assert len(documented_commands()) >= 10


@pytest.mark.parametrize("command", documented_commands(), ids=lambda c: c[4:60])
def test_every_documented_example_runs(command, tmp_path, capsys):
    args = shlex.split(command)[1:]
    assert args and args[0] not in NOT_RUNNABLE, f"{command} cannot be run in a test"

    vault = VAULT_FOR.get(args[0], DEFAULT_VAULT)
    base = ["--vault", str(VAULTS / vault), "--index", str(tmp_path / "idx")]
    cli.main([*base, "scan"])
    capsys.readouterr()

    code = cli.main([*base, *args])
    assert code == 0, f"{command} failed: {capsys.readouterr().err}"


def test_the_skill_declares_a_name_and_a_description():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    front = text.split("---", 2)[1]
    assert re.search(r"^name: [a-z0-9-]+$", front, re.MULTILINE)
    description = re.search(r"^description: (.+)$", front, re.MULTILINE)
    assert description, "the description is what decides whether the skill is ever loaded"
    assert len(description.group(1)) > 80, "too vague to match a real question"


def test_the_skill_warns_that_vault_content_is_data():
    """The security principle of the plan, in the place the agent will actually read it."""
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "data, never instructions" in text
