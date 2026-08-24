"""The PreToolUse hook: what an agent must not do to a vault (phase 6).

The interesting tests are the evasions. A guard that only catches `rm file.md` catches the
case nobody was worried about, so most of this file is `rm` wearing a hat: inside a pipeline,
behind an absolute path, hidden in a `find -delete`.

The other half is the opposite failure. This runs in front of every tool call an agent makes,
so a false deny is not a small annoyance — it is a session that cannot work. Moving a file,
reading a note, writing a report: all of those must pass, and they are tested as carefully as
the refusals.
"""

from __future__ import annotations

import json

import pytest

from hvk import audit, guard, paths


def decide(tool: str, protected=None, **tool_input) -> guard.Decision:
    return guard.decide(
        {"tool_name": tool, "tool_input": tool_input}, protected=protected or []
    )


# -- deletion, and the ways round it ---------------------------------------------------------

@pytest.mark.parametrize("command", [
    "rm note.md",
    "rm -rf Folder",
    "/bin/rm note.md",
    "rmdir Folder",
    "shred -u secret.md",
    "unlink note.md",
    "cat note.md && rm note.md",
    "ls | xargs echo; rm note.md",
    "find . -name '*.md' -delete",
    "find . -name '*.md' -exec rm {} +",
])
def test_deletion_is_refused_however_it_is_spelled(command):
    decision = decide("Bash", command=command)
    assert decision.permission == "deny", command
    assert ".trash/" in decision.reason, "a refusal has to say what to do instead"


@pytest.mark.parametrize("command", [
    "mv note.md .trash/",                 # the sanctioned way to remove something
    "ls -la",
    "grep -r 'rmarkdown' .",              # rm inside a longer word
    "git status",
    "echo 'rm is a word' > note.md",
    "hvk search 'rm'",
])
def test_ordinary_commands_pass(command):
    """A guard in front of every tool call cannot afford false refusals."""
    assert decide("Bash", command=command).permission == "allow", command


def test_only_bash_can_delete(tmp_path):
    """Write and Edit cannot remove a file, so they are not checked for it."""
    assert decide("Write", file_path="note.md", content="rm -rf /").permission == "allow"


# -- protected folders -----------------------------------------------------------------------

@pytest.mark.parametrize("tool,field", [
    ("Read", "file_path"),
    ("Write", "file_path"),
    ("Edit", "file_path"),
    ("NotebookEdit", "notebook_path"),
])
def test_a_protected_folder_is_off_limits_to_every_tool(tool, field):
    decision = decide(tool, protected=["_PRIVATE"], **{field: "_PRIVATE/keys.md"})
    assert decision.permission == "deny"
    assert "_PRIVATE" in decision.reason


@pytest.mark.parametrize("command", [
    "cat _PRIVATE/keys.md",
    "grep -r token _PRIVATE",
    "cp _PRIVATE/keys.md /tmp/",
    "cat '_PRIVATE/with spaces.md'",
    "cat Vault/_PRIVATE/keys.md",
])
def test_a_protected_folder_is_off_limits_from_the_shell(command):
    assert decide("Bash", command=command, protected=["_PRIVATE"]).permission == "deny"


def test_reading_is_refused_too_not_only_writing():
    """Protected means protected. Read-only access to secrets is still access to secrets."""
    assert decide("Read", file_path="_PRIVATE/keys.md", protected=["_PRIVATE"]).permission == "deny"


def test_a_similar_name_is_not_protected():
    """`_PRIVATE_NOTES` is a different folder, and refusing it would be a bug, not caution."""
    assert decide("Read", file_path="_PRIVATE_NOTES/one.md", protected=["_PRIVATE"]).permission == "allow"


def test_nothing_is_protected_by_default():
    """No default list: which folders are private is nobody's business but the owner's."""
    assert decide("Read", file_path="_PRIVATE/keys.md").permission == "allow"


def test_windows_separators_are_understood():
    assert decide("Read", file_path="_PRIVATE\\keys.md", protected=["_PRIVATE"]).permission == "deny"


def test_the_check_is_case_insensitive():
    assert decide("Read", file_path="_private/keys.md", protected=["_PRIVATE"]).permission == "deny"


# -- the hook contract ------------------------------------------------------------------------

def test_an_allow_says_nothing_at_all():
    """Silence is how a PreToolUse hook allows: any output at all is a decision."""
    assert guard.run(json.dumps({"tool_name": "Read", "tool_input": {"file_path": "a.md"}})) == ""


def test_a_deny_is_the_shape_claude_code_expects():
    answer = json.loads(guard.run(json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "rm a.md"}}
    )))
    specific = answer["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["permissionDecision"] == "deny"
    assert specific["permissionDecisionReason"]


@pytest.mark.parametrize("text", ["", "not json", "[]", "null", '{"tool_input": "not a dict"}'])
def test_anything_unparseable_is_allowed_through(text):
    """A hook that fails closed on its own bugs breaks the session it exists to protect."""
    assert guard.run(text) == ""


def test_an_unbalanced_quote_does_not_crash_it():
    decision = decide("Bash", command="rm 'unterminated", protected=["_PRIVATE"])
    assert decision.permission == "deny", "and it still catches the rm"


# -- the vault is the boundary ----------------------------------------------------------------

@pytest.fixture
def vault(tmp_path):
    """A vault with something outside it, which is the whole point of these tests."""
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    (root / "Note.md").write_text("# A note", encoding="utf-8")
    (tmp_path / "elsewhere").mkdir()
    return root


@pytest.mark.parametrize("tool, field", [
    ("Write", "file_path"), ("Edit", "file_path"), ("NotebookEdit", "notebook_path"),
])
def test_a_write_outside_the_vault_is_refused(vault, tool, field):
    decision = guard.decide({"tool_name": tool, "tool_input": {field: str(vault.parent / "elsewhere" / "x.md")}},
                            vault=vault)
    assert decision.permission == "deny"
    assert decision.rule == "outside-vault"


def test_a_write_inside_the_vault_passes(vault):
    decision = guard.decide({"tool_name": "Write", "tool_input": {"file_path": str(vault / "Sub" / "x.md")}},
                            vault=vault)
    assert decision.permission == "allow"


def test_a_relative_path_is_read_against_the_vault(vault):
    """The agent's working directory is the vault, so `Notes/x.md` is inside it."""
    assert guard.decide({"tool_name": "Write", "tool_input": {"file_path": "Notes/x.md"}},
                        vault=vault).permission == "allow"


def test_climbing_out_with_dot_dot_is_caught(vault):
    """Inside the vault as a string, outside it as a location. Resolving is what catches it."""
    decision = guard.decide(
        {"tool_name": "Write", "tool_input": {"file_path": "../../.ssh/authorized_keys"}}, vault=vault)
    assert decision.permission == "deny"
    assert ".ssh" in decision.match


def test_reading_outside_the_vault_is_allowed(vault):
    """Refusing reads breaks ordinary work and is not how an agent damages a machine."""
    assert guard.decide({"tool_name": "Read", "tool_input": {"file_path": "/etc/hostname"}},
                        vault=vault).permission == "allow"


def test_without_a_vault_the_rule_does_not_apply():
    assert guard.decide({"tool_name": "Write", "tool_input": {"file_path": "/etc/passwd"}}).permission == "allow"


def test_bash_is_not_judged_on_paths_it_might_write(vault):
    """A redirection cannot be found reliably in a command line, so it is not looked for."""
    assert guard.decide({"tool_name": "Bash", "tool_input": {"command": "echo hi > /tmp/out"}},
                        vault=vault).permission == "allow"


# -- what it writes down ----------------------------------------------------------------------

@pytest.fixture
def location(vault, tmp_path):
    return paths.Locations(vault=vault.resolve(), index_dir=tmp_path / "idx")


def call(location, payload, **kwargs):
    return guard.run(json.dumps(payload), location=location, **kwargs)


def test_a_refusal_is_written_down(location):
    call(location, {"tool_name": "Bash", "tool_input": {"command": "rm Note.md"}})
    line = location.log_path.read_text(encoding="utf-8").strip()
    assert "guard deny" in line and "rule=delete" in line and "match=rm" in line


def test_the_command_itself_is_not(location):
    """An audit needs the rule that fired, not the text: a command line can carry a token."""
    call(location, {"tool_name": "Bash", "tool_input": {"command": "rm Secret-$TOKEN-file.md"}})
    assert "TOKEN" not in location.log_path.read_text(encoding="utf-8")


def test_an_allow_writes_no_line(location):
    call(location, {"tool_name": "Read", "tool_input": {"file_path": "Note.md"}})
    assert not location.log_path.exists()


def test_every_call_leaves_a_heartbeat(location):
    """The one question the log cannot answer: is the hook wired in at all?"""
    assert not location.guard_seen_path.exists()
    call(location, {"tool_name": "Read", "tool_input": {"file_path": "Note.md"}})
    assert location.guard_seen_path.exists()


def test_a_protected_folder_refusal_names_the_folder_only(location):
    call(location, {"tool_name": "Read", "tool_input": {"file_path": "_PRIVATE/keys.md"}},
         protected=["_PRIVATE"])
    written = location.log_path.read_text(encoding="utf-8")
    assert "rule=protected" in written and "match=_PRIVATE" in written
    assert "keys.md" not in written


def test_recording_never_breaks_the_hook(location, monkeypatch):
    """Whatever goes wrong writing the record, the decision still reaches the agent.

    The record exists to make a refusal checkable afterwards. A bug in it that stopped the
    refusal from being *made* would be the worst possible trade.
    """
    def explode(*args, **kwargs):
        raise RuntimeError("the disk, the permissions, a bug in here")
    monkeypatch.setattr(audit, "record", explode)
    answer = call(location, {"tool_name": "Bash", "tool_input": {"command": "rm a.md"}})
    assert json.loads(answer)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_the_log_is_capped(location, monkeypatch):
    """Basic rotation: one generation, so a busy month cannot fill a disk."""
    monkeypatch.setattr(audit, "MAX_BYTES", 200)
    for _ in range(20):
        call(location, {"tool_name": "Bash", "tool_input": {"command": "rm Note.md"}})
    assert location.log_path.stat().st_size < 400
    assert location.log_path.with_name(location.log_path.name + ".1").exists()
