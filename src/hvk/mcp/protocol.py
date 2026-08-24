"""JSON-RPC 2.0 over stdio, which is all MCP is on the wire (ADR-0018).

Written by hand rather than pulled in from the official SDK, and that was a real decision: a
server with tools and no resources, no prompts, no sampling and no HTTP transport needs to read
a line, parse JSON, look up a name and write a line. This file is that, and the dependency list
stays at two.

Framing is **one JSON message per line** -- not the `Content-Length` headers of the Language
Server Protocol, which is the thing people expect it to be and is not. So nothing written to
stdout may contain a raw newline, and nothing else may write to stdout at all: a stray `print`
inside a tool would arrive at the client as a malformed message and end the session. Every human
word this process has to say goes to stderr.

Three shapes travel here, and telling them apart is the whole of the routing:

* a **request** has an ``id`` and expects exactly one response;
* a **notification** has no ``id`` and must not be answered -- ``notifications/initialized``
  arrives right after the handshake, and replying to it is a protocol error;
* a **response** is what goes back, carrying either ``result`` or ``error``, never both.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

VERSION = "2.0"

# The revision this speaks. A client asking for one this does not know is answered with this
# one rather than refused: the specification says a server replies with a version it supports,
# and letting the client decide whether that will do is better than deciding for it.
PROTOCOL_VERSION = "2025-06-18"

# JSON-RPC's own codes. Everything a *tool* does wrong is a result with isError set, not one of
# these -- see ADR-0018, and `errors are for the protocol` below.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class ProtocolError(Exception):
    """Something wrong with the message itself, to be reported with a JSON-RPC code."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Request:
    method: str
    params: dict
    id: object = None

    @property
    def is_notification(self) -> bool:
        """A message with no id. It gets no response, however it goes."""
        return self.id is None


def parse_message(line: str) -> Request:
    """One line from the client. Raises :class:`ProtocolError` for anything unusable."""
    try:
        payload = json.loads(line)
    except ValueError as exc:
        raise ProtocolError(PARSE_ERROR, f"not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProtocolError(INVALID_REQUEST, "a message is a JSON object")

    method = payload.get("method")
    if not isinstance(method, str) or not method:
        raise ProtocolError(INVALID_REQUEST, "a request names a method")

    params = payload.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        # By-position parameters are legal JSON-RPC and MCP never uses them. Refusing is
        # honest; pretending to understand and indexing into a list is not.
        raise ProtocolError(INVALID_PARAMS, "params must be an object, not a list")

    return Request(method=method, params=params, id=payload.get("id"))


def result(request_id: object, payload: dict) -> dict:
    return {"jsonrpc": VERSION, "id": request_id, "result": payload}


def error(request_id: object, code: int, message: str) -> dict:
    return {"jsonrpc": VERSION, "id": request_id, "error": {"code": code, "message": message}}


def encode(message: dict) -> str:
    """One message, on one line. `ensure_ascii=False` keeps a vault's accents as themselves."""
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


def serve(handle: Callable[[Request], dict | None], stdin, stdout) -> None:
    """Read messages until the client goes away, answering each through *handle*.

    *handle* returns the response to send, or None for a notification. Its own exceptions are
    turned into internal errors rather than allowed to end the loop: a bug in one tool must cost
    that one call, not the session.

    A blank line is skipped rather than treated as a parse error -- some clients send one on
    shutdown -- and end of input is the normal way this finishes.
    """
    for line in stdin:
        line = line.strip()
        if not line:
            continue

        request = None
        try:
            request = parse_message(line)
            response = handle(request)
        except ProtocolError as exc:
            # A malformed message has no usable id, so the response carries null -- which is
            # what JSON-RPC says to do and is why this is not simply re-raised.
            response = error(getattr(request, "id", None), exc.code, str(exc))
        except Exception as exc:                    # noqa: BLE001 - see the docstring
            response = error(
                getattr(request, "id", None), INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"
            )

        if response is None:
            continue
        stdout.write(encode(response) + "\n")
        stdout.flush()
