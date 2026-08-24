"""An MCP server over this vault (phase 7, ADR-0018).

`hvk mcp` speaks the Model Context Protocol on stdin and stdout, so an agent that is not Claude
Code can ask the vault questions -- and, when the instance is started with `--write`, change it.

Three files, in the order they matter:

* :mod:`hvk.mcp.tools` -- the tools, and what each is allowed to touch. Every one is a call into
  a command that already exists; this package is a protocol, not a second implementation.
* :mod:`hvk.mcp.server` -- the session, and the guard in front of every call.
* :mod:`hvk.mcp.protocol` -- JSON-RPC over stdio, by hand, because a tools-only server needs a
  line reader and a dispatch table rather than a dependency.

There is no network listener. A server that writes to your notes is reachable only by whatever
started it, which is also the whole of its authentication: the operating system already decided
who may run this process.
"""

from hvk.mcp.server import Session, serve

__all__ = ["Session", "serve"]
