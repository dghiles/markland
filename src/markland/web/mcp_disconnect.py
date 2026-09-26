"""Answer MCP requests whose client has already hung up (markland-7rq).

Claude Code abandons its connect-time burst when the process exits, and every
client reconnects or times out at once after a deploy or while the machine is
CPU-throttled. mcp 2.2.0 turns an abandoned request into a server fault in two
ways, both inside the `/mcp` sub-app:

* The modern-protocol entry (`handle_modern_request`) calls `request.body()`
  outside the SDK's exception boundary, so a hang-up before the body is read
  raises Starlette's `ClientDisconnect` out of the sub-app.
* A hang-up while a modern request is being served makes the SDK cancel the
  handler and return without any response (a legacy GET stream abandoned
  before it opens does the same). The `BaseHTTPMiddleware` layers wrapped
  around the mount then raise `RuntimeError("No response returned.")`.

Either way the client is gone, no JSON-RPC answer can reach it, and nothing
is actionable. `AbsorbClientDisconnect` answers such a request with 499
(nginx's "client closed request", outside the 5xx range the Sentry alert
keys on) and lets everything else through. uvicorn drops a send to a gone
peer before its access log, so the INFO line below is the only trace.

Why this shape:

* It sits inside the sub-app (`mcp_app.add_middleware`). Sentry's Starlette
  integration wraps every Starlette instance, nested ones included, and
  captures on the way out of each, so a catch anywhere further out still
  pages.
* It must send a response when none was started, or the outer
  BaseHTTPMiddleware layers raise "No response returned." instead.
* It is a pure ASGI wrapper, not an exception handler. Starlette will not run
  a handler once the response has started (it raises "Caught handled
  exception, but response already started." instead), and a silent return
  raises nothing for a handler to catch.
* A silent return is absorbed only after the client was seen to disconnect,
  so a genuine no-response bug still surfaces upstream.
"""

from __future__ import annotations

import logging

from starlette.requests import ClientDisconnect
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

CLIENT_CLOSED_REQUEST = 499


class AbsorbClientDisconnect:
    """ASGI middleware: a request whose client hung up gets a 499, not a 500."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client_gone = False
        response_started = False

        async def watching_receive() -> Message:
            nonlocal client_gone
            message = await receive()
            if message["type"] == "http.disconnect":
                client_gone = True
            return message

        async def watching_send(message: Message) -> None:
            nonlocal response_started
            await send(message)
            # Only once delivered: sse-starlette's disconnect listener can
            # cancel its own http.response.start before it goes out.
            if message["type"] == "http.response.start":
                response_started = True

        try:
            await self.app(scope, watching_receive, watching_send)
        except ClientDisconnect:
            client_gone = True

        if client_gone and not response_started:
            # INFO: client-controlled and not actionable, but keep the rate
            # visible in Fly logs now that it no longer reaches Sentry.
            logger.info("MCP client hung up before a response: %s %s", scope.get("method"), scope.get("path"))
            await Response(status_code=CLIENT_CLOSED_REQUEST)(scope, receive, send)
