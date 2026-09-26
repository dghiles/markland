"""A client hanging up mid-POST on /mcp must not reach Sentry.

Production signature (Sentry, 2026-09-25): `ClientDisconnect` raised from
`mcp/server/_streamable_http_modern.py` `handle_modern_request` ->
`request.body()`, `mechanism=starlette`, `handled=no`. mcp 2.x sends requests
with a modern `MCP-Protocol-Version` header down a path with no exception
handling around the body read, so the logger-keyed `before_send` filter
(test_log_scrubbing.py) never matched. See markland.web.mcp_disconnect.
"""

from __future__ import annotations

import os
import socket
import threading
import time

import pytest
import sentry_sdk
import uvicorn
from sentry_sdk.transport import Transport
from starlette.requests import ClientDisconnect

from markland.db import init_db
from markland.log_scrubbing import scrub_sentry_event
from markland.service.auth import create_user_token
from markland.service.users import create_user
from markland.web.app import create_app
from markland.web.mcp_disconnect import CLIENT_CLOSED_REQUEST, AbsorbClientDisconnect

# ---------------------------------------------------------------------------
# Unit: the ASGI middleware in isolation
# ---------------------------------------------------------------------------


async def _run(app, scope_type: str = "http") -> list[dict]:
    sent: list[dict] = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await AbsorbClientDisconnect(app)({"type": scope_type, "method": "POST", "path": "/"}, receive, send)
    return sent


@pytest.mark.asyncio
async def test_disconnect_before_response_sends_499():
    """BaseHTTPMiddleware upstream raises RuntimeError if no response is sent."""

    async def app(scope, receive, send):
        raise ClientDisconnect()

    sent = await _run(app)
    assert [m["type"] for m in sent] == ["http.response.start", "http.response.body"]
    assert sent[0]["status"] == CLIENT_CLOSED_REQUEST


@pytest.mark.asyncio
async def test_disconnect_after_response_started_sends_nothing_more():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise ClientDisconnect()

    sent = await _run(app)
    assert [m["type"] for m in sent] == ["http.response.start"]
    assert sent[0]["status"] == 200


@pytest.mark.asyncio
async def test_other_exceptions_still_propagate():
    async def app(scope, receive, send):
        raise ValueError("real bug")

    with pytest.raises(ValueError, match="real bug"):
        await _run(app)


@pytest.mark.asyncio
async def test_non_http_scopes_pass_through_untouched():
    async def app(scope, receive, send):
        raise ClientDisconnect()

    with pytest.raises(ClientDisconnect):
        await _run(app, scope_type="lifespan")


# ---------------------------------------------------------------------------
# End-to-end: real uvicorn socket + real Sentry SDK instrumentation
# ---------------------------------------------------------------------------


class _CapturingTransport(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events: list[dict] = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == "event":
                self.events.append(item.payload.json)


@pytest.fixture
def sentry_events():
    """Initialise Sentry as run_app does, but capture events in-process."""
    transport = _CapturingTransport()
    sentry_sdk.init(
        dsn="https://public@o0.ingest.sentry.io/1",
        transport=transport,
        before_send=scrub_sentry_event,
        send_default_pii=False,
    )
    try:
        yield transport.events
    finally:
        # Detach so later tests run with Sentry disabled, as they expect.
        sentry_sdk.get_client().close()
        sentry_sdk.get_global_scope().set_client(None)


@pytest.fixture
def live_mcp(tmp_path, sentry_events):
    # Sentry must be initialised before the app is built so the Starlette
    # integration is patched in, exactly as in production.
    os.environ.setdefault("MARKLAND_SESSION_SECRET", "x" * 32)
    conn = init_db(str(tmp_path / "t.db"))
    user = create_user(conn, email="hangup@example.com", display_name="Hangup")
    _, token = create_user_token(conn, user_id=user.id, label="hangup")
    app = create_app(
        conn,
        mount_mcp=True,
        base_url="http://127.0.0.1",
        session_secret="x" * 32,
        enable_presence_gc=False,
    )

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "uvicorn did not start"

    yield port, token

    server.should_exit = True
    thread.join(timeout=10)


def _post_then_hang_up(port: int, token: str, path: str, protocol_version: str) -> None:
    """Send headers + a truncated body (Content-Length promises more), then close."""
    head = (
        f"POST {path} HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        f"Authorization: Bearer {token}\r\n"
        "Content-Type: application/json\r\n"
        "Accept: application/json, text/event-stream\r\n"
        f"MCP-Protocol-Version: {protocol_version}\r\n"
        "Content-Length: 500\r\n\r\n"
    )
    with socket.create_connection(("127.0.0.1", port)) as c:
        c.sendall(head.encode() + b'{"jsonrpc":"2.0",')
        time.sleep(0.3)


def _wait_quiet(events: list[dict], seconds: float = 1.0) -> list[dict]:
    time.sleep(seconds)
    sentry_sdk.flush()
    return events


@pytest.mark.parametrize(
    "path,protocol_version",
    [
        # The production signature: modern era, trailing-slash mount.
        ("/mcp/", "2026-07-28"),
        # Bare-path route (markland-dfj) delegates to the same sub-app.
        ("/mcp", "2026-07-28"),
        # Legacy era: already covered by before_send; guard against regressions.
        ("/mcp/", "2025-06-18"),
    ],
)
def test_client_hangup_mid_post_reports_nothing_to_sentry(
    live_mcp, sentry_events, path, protocol_version
):
    port, token = live_mcp
    _post_then_hang_up(port, token, path, protocol_version)
    events = _wait_quiet(sentry_events)
    assert events == [], [
        (e.get("logger"), [v.get("type") for v in (e.get("exception") or {}).get("values", [])])
        for e in events
    ]
