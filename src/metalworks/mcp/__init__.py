"""The metalworks MCP server surface.

A FastMCP server (``[mcp]`` extra) exposing the library as agent-callable
tools, split into two tiers:

- **Tier 1** is zero-key: public Reddit reads, offline Arctic pulls, the
  deterministic compliance lint, and reads of the local store.
- **Tier 2** is key-gated: the research pipeline (run as a background job so it
  never blocks a tool call past the MCP timeout), reply generation, and the
  posting path — which is the security boundary and is double-gated.

Every tool returns a machine-readable error envelope
(``{error_code, message, fix, docs_url}``) on failure rather than raising a raw
exception, so the host model always gets an actionable, structured result.

``mcp`` is imported lazily in :func:`metalworks.mcp.server.build_server`; this
package and :mod:`metalworks.mcp.tools` import cleanly with the extra absent, so
the tool bodies stay unit-testable on a bare install.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metalworks.mcp.server import build_server, serve

__all__ = ["build_server", "serve"]


def __getattr__(name: str) -> object:
    # Lazy re-export so `from metalworks.mcp import build_server` does not pull
    # in the `mcp` SDK at import time (it's only needed when actually serving).
    if name in __all__:
        from metalworks.mcp import server

        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
