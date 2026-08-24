"""The MCP server (ADR-0018), driven through the protocol by a client that is not a client.

Two things are being tested and only one of them is the protocol. The other is the boundary:
what a read-only instance will not do, what the guard refuses whoever asks, and whether a write
that would clobber somebody's phone edit is stopped. Those are the reasons the decision to
expose writing at all is defensible, so they get the most tests here.

Everything goes through `serve()` over real file objects, because the framing -- one JSON
message per line, nothing else on stdout -- is a thing a client depends on and a thing a stray
`print` breaks.
"""

from __future__ import annotations

import io
import json

import pytest

from hvk import paths
from hvk import scan as scanner
from hvk.mcp import protocol, server, tools

HELLO = {"jsonrpc": "2.0", "id": 0, "method": "initialize",
         "params": {"protocolVersion": protocol.PROTOCOL_VERSION, "capabilities": {},
                    "clientInfo": {"name": "tests", "version": "1"}}}


@pytest.fixture
def vault(tmp_path):
    """A small vault with the shapes these tests need, indexed."""
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    (root / "_PRIVATE").mkdir()
    (root / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (root / "One.md").write_text(
        "# One\n\nLinks to [[Two]]. #project\n\n- [ ] a task\n", encoding="utf-8"
    )
    (root / "Two.md").write_text("---\nstatus: open\n---\n\n# Two\n", encoding="utf-8")
    (root / "_PRIVATE" / "Secret.md").write_text("# secret\n", encoding="utf-8")

    location = paths.Locations(vault=root.resolve(), index_dir=tmp_path / "index")
    scanner.scan(location)
    return location


@pytest.fixture
def client(vault):
    """Send messages, get the responses back. One `serve()` per call, as a real client's is.

    Each call is a fresh process's worth of work, which also means the tests cannot accidentally
    depend on state held between calls -- and the server holds none by design.
    """
    def _talk(*messages, write: bool = False, protect: list | None = None):
        stdin = io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n")
        stdout = io.StringIO()
        server.serve(vault, allow_write=write, protected=protect or [],
                     stdin=stdin, stdout=stdout)
        return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]

    return _talk


def call(client, name, arguments=None, **kwargs):
    """One tools/call, with its payload already parsed. Returns (payload, is_error)."""
    responses = client(
        HELLO,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": name, "arguments": arguments or {}}},
        **kwargs,
    )
    result = responses[-1]["result"]
    text = result["content"][0]["text"]
    if result.get("isError"):
        return text, True
    return json.loads(text), False


# -- the protocol -----------------------------------------------------------------------------

def test_the_handshake_answers_with_a_version_and_a_name(client):
    result = client(HELLO)[0]["result"]
    assert result["protocolVersion"] == protocol.PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "hvk"
    assert "tools" in result["capabilities"]


def test_a_client_asking_for_a_version_this_does_not_speak_gets_the_one_it_does():
    """The specification's rule, and the honest one: a server answers with a version it
    supports, and the client decides whether that will do."""
    assert protocol.parse_message(json.dumps({
        **HELLO, "params": {"protocolVersion": "1999-01-01"}
    })).params["protocolVersion"] == "1999-01-01"


def test_a_version_this_does_not_know_is_not_echoed_back(client):
    responses = client({**HELLO, "params": {"protocolVersion": "1999-01-01"}})
    assert responses[0]["result"]["protocolVersion"] == protocol.PROTOCOL_VERSION


def test_a_notification_is_never_answered(client):
    """Replying to one is a protocol error, and `notifications/initialized` arrives on every
    single session right after the handshake."""
    responses = client(HELLO, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert len(responses) == 1
    assert responses[0]["id"] == 0


def test_every_response_is_one_line_of_json(client, vault):
    """The framing is newline-delimited, not Content-Length. A stray print or an indented dump
    would reach the client as a broken message and end the session."""
    stdin = io.StringIO(json.dumps(HELLO) + "\n" + json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "info", "arguments": {}}}) + "\n")
    stdout = io.StringIO()
    server.serve(vault, stdin=stdin, stdout=stdout)
    lines = stdout.getvalue().splitlines()
    assert len(lines) == 2
    assert all(json.loads(line) for line in lines)


def test_a_message_that_is_not_json_is_a_parse_error_and_does_not_end_the_session(vault):
    stdin = io.StringIO("this is not json\n" + json.dumps(HELLO) + "\n")
    stdout = io.StringIO()
    server.serve(vault, stdin=stdin, stdout=stdout)
    first, second = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert first["error"]["code"] == protocol.PARSE_ERROR
    assert first["id"] is None, "a malformed message has no id to answer with"
    assert "result" in second


def test_an_unknown_method_is_a_protocol_error(client):
    responses = client(HELLO, {"jsonrpc": "2.0", "id": 9, "method": "vault/incinerate"})
    assert responses[-1]["error"]["code"] == protocol.METHOD_NOT_FOUND


def test_positional_parameters_are_refused_rather_than_guessed_at(client):
    responses = client({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": ["a"]})
    assert responses[-1]["error"]["code"] == protocol.INVALID_PARAMS


def test_blank_lines_are_skipped(vault):
    stdout = io.StringIO()
    server.serve(vault, stdin=io.StringIO("\n\n" + json.dumps(HELLO) + "\n\n"), stdout=stdout)
    assert len(stdout.getvalue().splitlines()) == 1


def test_ping_answers(client):
    assert client(HELLO, {"jsonrpc": "2.0", "id": 2, "method": "ping"})[-1]["result"] == {}


# -- what is offered --------------------------------------------------------------------------

def listed(client, **kwargs):
    responses = client(HELLO, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, **kwargs)
    return responses[-1]["result"]["tools"]


def test_a_read_only_server_does_not_offer_the_writing_tools(client):
    """The opt-in of ADR-0018, and the reason it is safe: a client cannot call what it was
    never told about."""
    names = {tool["name"] for tool in listed(client)}
    assert "search" in names and "backlinks" in names
    assert not names & {"note_write", "note_set_property", "views_apply", "jobs_run"}


def test_the_writing_tools_appear_only_with_write(client):
    names = {tool["name"] for tool in listed(client, write=True)}
    assert {"note_write", "note_set_property", "views_apply", "jobs_run"} <= names


def test_a_writing_tool_called_without_write_is_simply_not_there(client):
    """Worded identically to a name that does not exist. A client that is not offered these
    should learn they are absent, not that they exist somewhere it cannot reach."""
    message, failed = call(client, "note_write", {"path": "X.md", "text": "x"})
    assert failed and "no such tool" in message
    unknown, _ = call(client, "vault_incinerate", {})
    assert unknown == message.replace("note_write", "vault_incinerate")


def test_every_tool_publishes_a_schema_and_a_description():
    for tool in tools.ALL:
        described = tool.described()
        assert described["description"].strip(), tool.name
        assert described["inputSchema"]["type"] == "object", tool.name
        assert described["inputSchema"]["additionalProperties"] is False, tool.name


def test_every_declared_path_argument_is_in_the_schema():
    """The guard checks arguments by name, so a typo in `paths` would silently protect nothing."""
    for tool in tools.ALL:
        for name in (*tool.paths, *tool.filters):
            assert name in tool.described()["inputSchema"]["properties"], f"{tool.name}.{name}"


# -- querying ---------------------------------------------------------------------------------

def test_backlinks_answers_the_question_the_app_answers_on_its_sidebar(client):
    payload, failed = call(client, "backlinks", {"target": "Two"})
    assert not failed
    assert payload["target"] == "Two.md"
    assert [row["source"] for row in payload["backlinks"]] == ["One.md"]


def test_search_returns_matches(client):
    payload, _ = call(client, "search", {"query": "Links"})
    assert [m["path"] for m in payload["matches"]] == ["One.md"]


def test_a_query_that_cannot_be_answered_is_a_result_and_not_a_crash(client):
    """Most clients surface a JSON-RPC error as a dead server. "There is no note called that"
    is an answer to a question."""
    message, failed = call(client, "backlinks", {"target": "Nope"})
    assert failed and "no file in the index matches" in message


def test_a_refusal_keeps_the_sentence_it_was_written_with(client):
    """The DQL refusals cost an ADR to word (ADR-0016). Reducing them to an error code here
    would throw away the whole of that."""
    message, failed = call(client, "dql", {"query": "TASK WHERE done"})
    assert failed and "TASK queries are not implemented" in message


def test_a_missing_argument_is_named(client):
    message, failed = call(client, "search", {})
    assert failed and message == "query is required"


def test_an_argument_of_the_wrong_type_is_refused_before_it_reaches_anything(client):
    """The published schema is advisory -- nothing in the protocol makes a client honour it."""
    message, failed = call(client, "search", {"query": "x", "limit": "lots"})
    assert failed and "whole number" in message


def test_note_read_hands_back_a_digest(client):
    payload, _ = call(client, "note_read", {"path": "Two.md"})
    assert payload["exists"] and payload["digest"]
    assert payload["text"].startswith("---")


def test_note_read_on_a_missing_note_says_so_rather_than_returning_nothing(client):
    payload, failed = call(client, "note_read", {"path": "Nope.md"})
    assert not failed
    assert payload["exists"] is False and payload["text"] is None and payload["digest"] is None


def test_the_index_is_opened_on_first_use_and_not_at_startup(tmp_path):
    """A client shows a dead server if the process exits. "Run hvk scan" has to arrive as a
    sentence, not as a crash."""
    root = tmp_path / "unscanned"
    (root / ".obsidian").mkdir(parents=True)
    location = paths.Locations(vault=root.resolve(), index_dir=tmp_path / "nothing")

    stdout = io.StringIO()
    server.serve(location, stdin=io.StringIO(json.dumps(HELLO) + "\n" + json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "info", "arguments": {}}}) + "\n"), stdout=stdout)
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert "result" in responses[0], "the handshake succeeds without an index"
    assert responses[1]["result"]["isError"]
    assert "hvk scan" in responses[1]["result"]["content"][0]["text"]


# -- the guard --------------------------------------------------------------------------------

def test_a_protected_folder_is_protected_from_a_client_that_runs_no_hook(client):
    """The reason the server applies the rules itself. The guard lives in a Claude Code hook,
    and an MCP client does not pass through it -- so without this, "protected" would mean
    protected against exactly one program."""
    message, failed = call(client, "note_read", {"path": "_PRIVATE/Secret.md"},
                           protect=["_PRIVATE"])
    assert failed and "protected folder" in message


def test_a_protected_folder_is_protected_from_a_search_filter_too(client):
    """The filter lives inside the query string, so it has to be pulled out. Otherwise a rule
    written to stop exactly this is one `path:` away from useless."""
    message, failed = call(client, "search", {"query": "secret path:_PRIVATE"},
                           protect=["_PRIVATE"])
    assert failed and "protected folder" in message


def test_nothing_is_protected_by_default(client):
    """ADR-0012's decision, unchanged: which folders are private is nobody's business but the
    vault owner's, so unset means the rule does not apply."""
    payload, failed = call(client, "note_read", {"path": "_PRIVATE/Secret.md"})
    assert not failed and payload["exists"]


def test_a_refusal_is_written_down(client, vault):
    call(client, "note_read", {"path": "_PRIVATE/Secret.md"}, protect=["_PRIVATE"])
    log = vault.log_path.read_text(encoding="utf-8")
    assert "mcp deny rule=protected tool=note_read match=_PRIVATE" in log


def test_the_log_records_the_rule_and_not_the_content(client, vault):
    """As in ADR-0014: what an audit needs is which rule fired and what it matched. Content can
    carry anything, and a log that has to be guarded itself is not an improvement."""
    call(client, "note_read", {"path": "_PRIVATE/Secret.md"}, protect=["_PRIVATE"])
    assert "secret" not in vault.log_path.read_text(encoding="utf-8").lower().replace(
        "_private", ""
    )


# -- writing ----------------------------------------------------------------------------------

def test_a_note_can_be_created(client, vault):
    payload, failed = call(client, "note_write",
                           {"path": "New.md", "text": "# New\n", "if_unchanged": "absent"},
                           write=True)
    assert not failed and payload["created"] and payload["changed"]
    assert (vault.vault / "New.md").read_text(encoding="utf-8") == "# New\n"


def test_if_unchanged_absent_refuses_to_overwrite_an_existing_note(client, vault):
    message, failed = call(client, "note_write",
                           {"path": "Two.md", "text": "clobber", "if_unchanged": "absent"},
                           write=True)
    assert failed and "Nothing was written" in message
    assert "# Two" in (vault.vault / "Two.md").read_text(encoding="utf-8")


def test_a_stale_digest_loses_the_race_instead_of_winning_it(client, vault):
    """ADR-0007's refusal-to-clobber, carried across a protocol where the client cannot hold a
    file open. An edit that arrived from a phone in between is the case this exists for."""
    message, failed = call(client, "note_write",
                           {"path": "Two.md", "text": "clobber", "if_unchanged": "0" * 64},
                           write=True)
    assert failed and "has changed since it was read" in message
    assert "# Two" in (vault.vault / "Two.md").read_text(encoding="utf-8")


def test_a_matching_digest_is_allowed_through(client, vault):
    read, _ = call(client, "note_read", {"path": "Two.md"}, write=True)
    payload, failed = call(client, "note_write",
                           {"path": "Two.md", "text": "replaced",
                            "if_unchanged": read["digest"]},
                           write=True)
    assert not failed and payload["changed"]
    assert (vault.vault / "Two.md").read_text(encoding="utf-8") == "replaced\n"


def test_writing_identical_content_changes_nothing_and_says_so(client, vault):
    """Not an optimisation: it is what keeps something regenerated on a schedule from waking
    the watcher, and sync, on every device, every time (ADR-0007)."""
    before = (vault.vault / "Two.md").stat().st_mtime_ns
    read, _ = call(client, "note_read", {"path": "Two.md"}, write=True)
    payload, failed = call(client, "note_write",
                           {"path": "Two.md", "text": read["text"]}, write=True)
    assert not failed and payload["changed"] is False
    assert (vault.vault / "Two.md").stat().st_mtime_ns == before


def test_one_property_can_be_set_without_touching_the_rest_of_the_note(client, vault):
    payload, failed = call(client, "note_set_property",
                           {"path": "Two.md", "key": "status", "value": "done"}, write=True)
    assert not failed and payload["changed"]
    assert (vault.vault / "Two.md").read_text(encoding="utf-8") == \
        "---\nstatus: done\n---\n\n# Two\n"


def test_a_write_outside_the_vault_is_refused(client):
    """The vault's own content is untrusted input, and a path that escapes it is the shape a
    prompt injection takes."""
    message, failed = call(client, "note_write",
                           {"path": "../escaped.md", "text": "x"}, write=True)
    assert failed and "outside the vault" in message


def test_a_write_into_a_protected_folder_is_refused(client):
    message, failed = call(client, "note_write",
                           {"path": "_PRIVATE/New.md", "text": "x"},
                           write=True, protect=["_PRIVATE"])
    assert failed and "protected folder" in message


def test_every_write_is_written_down(client, vault):
    """If any agent can write to the vault, "who wrote this" has to have an answer."""
    call(client, "note_write", {"path": "New.md", "text": "x"}, write=True)
    log = vault.log_path.read_text(encoding="utf-8")
    assert "mcp write tool=note_write path=New.md changed=true" in log
    assert "mcp start" in log and "read-write" in log


def test_jobs_run_cannot_be_told_where_the_profiles_are(client):
    """A permission profile chosen by the thing being permitted is not a permission. The
    directories are the server's configuration and there is no argument for them."""
    assert "profiles" not in tools.BY_NAME["jobs_run"].schema["properties"]
    assert "dir" not in tools.BY_NAME["jobs_run"].schema["properties"]


def test_jobs_run_still_refuses_without_its_directories(client, monkeypatch):
    """The second gate, and it is not new: since phase 5 there has been no default (ADR-0009)."""
    monkeypatch.delenv("HVK_JOBS_DIR", raising=False)
    monkeypatch.delenv("HVK_JOBS_PROFILES", raising=False)
    message, failed = call(client, "jobs_run", {}, write=True)
    assert failed and "no jobs directory declared" in message


def test_views_apply_writes_a_materialised_view(client, vault, tmp_path):
    (vault.vault / "Board.base").write_text(
        "views:\n  - type: table\n    name: All\n    order:\n      - file.name\n",
        encoding="utf-8",
    )
    (vault.vault / "Dash.md").write_text(
        '%% view: base "Board.base" %%\n<!-- view:start -->\n<!-- view:end -->\n',
        encoding="utf-8",
    )
    scanner.scan(vault)

    payload, failed = call(client, "views_apply", {"path": "Dash.md"}, write=True)
    assert not failed, payload
    assert payload["errors"] == 0
    assert "One.md" in (vault.vault / "Dash.md").read_text(encoding="utf-8")
