"""Canonical MCP error factory. See spec §7 for the closed code set."""

from __future__ import annotations

import json

from mcp.server.fastmcp.exceptions import ToolError

ERROR_CODES: frozenset[str] = frozenset({
    "unauthenticated",
    "forbidden",
    "not_found",
    "conflict",
    "invalid_argument",
    "rate_limited",
    "internal_error",
})


def tool_error(code: str, **data) -> ToolError:
    """Build a ToolError with structured `code` and optional `data` fields.

    The structured payload is exposed two ways:

    - `err.data` — a Python attribute readable by direct-mode callers (the
      harness reads this for `mode="direct"`).
    - The `ToolError`'s message is a JSON dump of the same payload, so when
      FastMCP serializes the error onto the wire (which only carries the
      message string and an `isError: true` flag — `err.data` is lost),
      HTTP clients can recover the structured shape by parsing the text.

    Use this everywhere a tool needs to surface an error to the MCP client.
    """
    if code not in ERROR_CODES:
        raise ValueError(f"{code!r} not in ERROR_CODES")
    payload = {"code": code, **data}
    err = ToolError(json.dumps(payload, sort_keys=True))
    err.data = payload
    return err
