"""Absorb MCP client disconnects inside the `/mcp` sub-app.

mcp 2.x routes requests carrying a modern `MCP-Protocol-Version` header
(2026-07-28+) to `mcp.server._streamable_http_modern.handle_modern_request`,
which calls `await request.body()` with no exception handling. A client that
hangs up mid-POST makes Starlette raise `ClientDisconnect`, which escapes the
handler and is captured by Sentry's Starlette integration as an *unhandled*
error (`mechanism=starlette`, `handled=no`, no `logger`) -- a shape the
logger-keyed `before_send` filter in `markland.log_scrubbing` does not match.

A disconnect before the body is read means no JSON-RPC request was
dispatched, so there is nothing to roll back and nobody to answer: dropping
the exception here is the correct outcome, not suppression of a real fault.
Scoped to the MCP sub-app on purpose -- a `ClientDisconnect` elsewhere in the
app is left to surface until it is understood.

Placement constraints (both verified against sentry-sdk 2.58 / starlette 1.0):

* It must be registered as middleware *on the sub-app*. Sentry patches
  `Starlette.__call__`, so the sub-app captures an escaping exception itself
  before any wrapper outside it could catch it.
* It must send a response when none was started. The outer
  `PrincipalMiddleware` is a `BaseHTTPMiddleware`, which raises
  `RuntimeError("No response returned.")` -- another unhandled 500 -- if the
  inner app returns silently.
"""

from __future__ import annotations

import logging

from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("markland.mcp_disconnect")

# nginx's "client closed request". Non-standard, but unambiguous in access
# logs and outside the 5xx range the Sentry alert keys on. The peer is gone,
# so no client ever reads it.
CLIENT_CLOSED_REQUEST = 499


class AbsorbClientDisconnect:
    """ASGI middleware: turn `ClientDisconnect` from the wrapped app into a 499."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except ClientDisconnect:
            # INFO, not WARNING: client-controlled and not actionable, but the
            # rate stays visible in Fly logs.
            logger.info(
                "mcp client disconnected mid-request: %s %s",
                scope.get("method"),
                scope.get("path"),
            )
            if not response_started:
                await send(
                    {
                        "type": "http.response.start",
                        "status": CLIENT_CLOSED_REQUEST,
                        "headers": [(b"content-length", b"0")],
                    }
                )
                await send({"type": "http.response.body", "body": b""})
