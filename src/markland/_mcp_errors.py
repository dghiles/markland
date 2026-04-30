"""Canonical MCP error factory. See spec §7 for the closed code set."""

from __future__ import annotations

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
    """Build a ToolError with `data = {"code": code, **data}`.

    Use this everywhere a tool needs to surface an error to the MCP client.
    The harness's Response wrapper normalizes against the same shape.
    """
    if code not in ERROR_CODES:
        raise ValueError(f"{code!r} not in ERROR_CODES")
    msg = code.replace("_", " ")
    err = ToolError(msg)
    err.data = {"code": code, **data}
    return err
