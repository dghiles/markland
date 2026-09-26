"""An MCP client that hangs up must not surface as a server fault (markland-7rq).

Claude Code fires a burst of requests as it connects and abandons them if the
process exits first; a deploy or a CPU-throttled machine makes every client
reconnect or time out at once. An abandoned request used to escape as an
unhandled error: a 500 written to a dead socket, a uvicorn traceback, and
Sentry events (MARKLAND-9). Three shapes, all inside the `/mcp` sub-app:

1. Hang-up before the body is read. mcp 2.2.0's modern-protocol entry
   (`handle_modern_request`) calls `request.body()` outside the SDK's own
   exception boundary, so Starlette's `ClientDisconnect` escapes.
2. Hang-up while a modern request is being served. The SDK sees
   `http.disconnect`, cancels the handler and returns without a response, so
   the `BaseHTTPMiddleware` layers wrapped around the mount raise
   `RuntimeError("No response returned.")`. A legacy GET stream abandoned
   before it opens does the same.
3. Hang-up after the response started. Starlette's exception-handler wrapper
   refuses to run a handler at that point and raises
   `RuntimeError("Caught handled exception, but response already started.")`
   instead. Not reachable on mcp 2.2.0 -- see
   `test_disconnect_after_response_started_on_every_mcp_path` -- but a pure
   ASGI wrapper covers it for free, so the fix is a wrapper, not a handler.

See markland.web.mcp_disconnect for why the fix sits inside the sub-app.
Unit and Sentry-level tests here are salvaged from PR #82.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from dataclasses import dataclass

import anyio
import pytest
import sentry_sdk
import uvicorn
from sentry_sdk.transport import Transport
from starlette.requests import ClientDisconnect
from starlette.testclient import TestClient

from markland.db import init_db
from markland.log_scrubbing import scrub_sentry_event
from markland.service.auth import create_user_token
from markland.service.users import create_user
from markland.web.app import create_app
from markland.web.mcp_disconnect import CLIENT_CLOSED_REQUEST, AbsorbClientDisconnect

MODERN = "2026-07-28"
LEGACY = "2025-06-18"

# ---------------------------------------------------------------------------
# Unit: the ASGI wrapper in isolation
# ---------------------------------------------------------------------------


async def _run(app, scope_type: str = "http") -> list[dict]:
    sent: list[dict] = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        # Checkpoint before delivering, as the memory stream behind
        # BaseHTTPMiddleware does: a cancelled send delivers nothing.
        await anyio.lowlevel.checkpoint()
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
    """A second http.response.start would be a protocol error; the peer is gone anyway."""

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise ClientDisconnect()

    sent = await _run(app)
    assert [m["type"] for m in sent] == ["http.response.start"]
    assert sent[0]["status"] == 200


@pytest.mark.asyncio
async def test_silent_return_after_disconnect_sends_499():
    """The SDK's own cancel-on-disconnect path returns without answering."""

    async def app(scope, receive, send):
        assert (await receive())["type"] == "http.disconnect"

    sent = await _run(app)
    assert [m["type"] for m in sent] == ["http.response.start", "http.response.body"]
    assert sent[0]["status"] == CLIENT_CLOSED_REQUEST


@pytest.mark.asyncio
async def test_cancelled_response_start_does_not_count_as_started():
    """sse-starlette cancels its own http.response.start once it sees the disconnect."""

    async def app(scope, receive, send):
        assert (await receive())["type"] == "http.disconnect"
        with anyio.CancelScope() as cancelled:
            cancelled.cancel()
            await send({"type": "http.response.start", "status": 200, "headers": []})

    sent = await _run(app)
    assert [m["type"] for m in sent] == ["http.response.start", "http.response.body"]
    assert sent[0]["status"] == CLIENT_CLOSED_REQUEST


@pytest.mark.asyncio
async def test_silent_return_with_client_still_there_is_not_masked():
    """No disconnect seen means a genuine bug: leave it for upstream to flag."""

    async def app(scope, receive, send):
        return None

    assert await _run(app) == []


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
# Every MCP path, through the full app, with a scripted client
# ---------------------------------------------------------------------------


def _modern(method: str, params: dict | None = None, name: str | None = None) -> tuple[dict, bytes]:
    """Headers and body for a 2026-07-28 request that passes the SDK's envelope checks."""
    params = dict(params or {})
    params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": MODERN,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "hangup", "version": "0"},
    }
    headers = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": MODERN,
        "mcp-method": method,
    }
    if name is not None:
        headers["mcp-name"] = name
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    return headers, json.dumps(body).encode()


_LEGACY_HEADERS = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
_INITIALIZE = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": LEGACY, "capabilities": {}, "clientInfo": {"name": "hangup", "version": "0"}},
    }
).encode()


@dataclass
class _Stack:
    app: object
    token: str
    portal: object

    def exchange(self, method: str, headers: dict, body: bytes = b"", hang_up: str = "after_start") -> list[dict]:
        """Run one request through the whole app; return what it sent.

        `hang_up` is when the client's `http.disconnect` arrives:
          before_body -- first receive (gone before the handler reads anything)
          after_body  -- right after the body (gone while the request is served)
          after_start -- only once the response has started
          after_end   -- only once the response is complete (a normal exchange)
        Anything the app raises propagates, which fails the calling test.
        """
        return self.portal.call(self._exchange, method, headers, body, hang_up)

    async def _exchange(self, method, headers, body, hang_up):
        started, ended = anyio.Event(), anyio.Event()
        sent: list[dict] = []
        body_sent = hang_up == "before_body"

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            if hang_up == "after_start":
                await started.wait()
            elif hang_up == "after_end":
                await ended.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)
            if message["type"] == "http.response.start":
                started.set()
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                ended.set()

        raw_headers = [(b"host", b"testserver"), (b"authorization", f"Bearer {self.token}".encode())]
        raw_headers += [(k.encode(), v.encode()) for k, v in headers.items()]
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},  # what uvicorn 0.44 advertises
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": "/mcp/",
            "raw_path": b"/mcp/",
            "root_path": "",
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 5555),
            "state": {},
            "headers": raw_headers,
        }
        with anyio.fail_after(10):
            await self.app(scope, receive, send)
        return sent

    def legacy_session(self) -> dict:
        """Open a stateful legacy session; return headers that address it."""
        sent = self.exchange("POST", _LEGACY_HEADERS, _INITIALIZE, hang_up="after_end")
        start = next(m for m in sent if m["type"] == "http.response.start")
        session_id = dict(start["headers"])[b"mcp-session-id"].decode()
        headers = dict(_LEGACY_HEADERS, **{"mcp-session-id": session_id, "mcp-protocol-version": LEGACY})
        initialized = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode()
        self.exchange("POST", headers, initialized, hang_up="after_end")
        return headers


def _status(sent: list[dict]) -> int | None:
    return next((m["status"] for m in sent if m["type"] == "http.response.start"), None)


@pytest.fixture
def stack(tmp_path):
    os.environ.setdefault("MARKLAND_SESSION_SECRET", "x" * 32)
    conn = init_db(str(tmp_path / "t.db"))
    user = create_user(conn, email="hangup@example.com", display_name="Hangup")
    _, token = create_user_token(conn, user_id=user.id, label="hangup")
    app = create_app(
        conn,
        mount_mcp=True,
        base_url="http://testserver",
        session_secret="x" * 32,
        enable_presence_gc=False,
    )
    with TestClient(app) as client:  # runs the lifespan that starts the MCP task group
        yield _Stack(app, token, client.portal)


@pytest.fixture
def slow_tool(monkeypatch) -> threading.Event:
    """Make `markland_whoami` slow enough to give up on; the event is set once it is running."""
    import markland.server

    real = markland.server._whoami_for_principal
    running = threading.Event()

    def slow(principal):
        running.set()
        time.sleep(0.3)
        return real(principal)

    monkeypatch.setattr(markland.server, "_whoami_for_principal", slow)
    return running


_WHOAMI = {"name": "markland_whoami", "arguments": {}}


@pytest.mark.parametrize(
    "path",
    [
        "modern JSON (tools/list)",
        "modern SSE (subscriptions/listen)",
        "legacy POST, new session (initialize)",
        "legacy POST, existing session (tools/list)",
        "legacy GET stream",
        "legacy DELETE",
    ],
)
def test_disconnect_after_response_started_on_every_mcp_path(stack, path):
    """No MCP path raises once its response has started.

    Reachability, audited against mcp 2.2.0 / starlette 1.0.0 / uvicorn 0.44:
    ClientDisconnect comes only from `Request.body()`/`stream()`, and from
    Starlette's StreamingResponse, which converts OSError into it only under
    ASGI spec >= 2.4 (uvicorn advertises 2.3; mcp streams through
    sse-starlette, which never raises it). The modern entry reads the body
    only before it has sent anything; after that it watches `receive()`
    directly and a disconnect cancels its handler quietly. The legacy transport reads the
    body inside its own `except Exception`. GET and DELETE never read a body.
    So a disconnect after the response started never escapes, and #81's
    exception handler (which Starlette would have refused to run then) was
    never at risk. This test drives each path to catch an SDK upgrade that
    changes that.
    """
    if path == "modern JSON (tools/list)":
        headers, body = _modern("tools/list")
        sent = stack.exchange("POST", headers, body)
        assert _status(sent) == 200
    elif path == "modern SSE (subscriptions/listen)":
        headers, body = _modern("subscriptions/listen", {"notifications": {"toolsListChanged": True}})
        sent = stack.exchange("POST", headers, body)
        start = next(m for m in sent if m["type"] == "http.response.start")
        assert (start["status"], dict(start["headers"])[b"content-type"]) == (200, b"text/event-stream")
    elif path == "legacy POST, new session (initialize)":
        sent = stack.exchange("POST", _LEGACY_HEADERS, _INITIALIZE)
        assert _status(sent) == 200
    elif path == "legacy POST, existing session (tools/list)":
        headers = stack.legacy_session()
        body = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()
        sent = stack.exchange("POST", headers, body)
        assert _status(sent) == 200
    elif path == "legacy GET stream":
        headers = stack.legacy_session()
        sent = stack.exchange("GET", {"accept": "text/event-stream", **headers})
        assert _status(sent) == 200
    elif path == "legacy DELETE":
        headers = stack.legacy_session()
        sent = stack.exchange("DELETE", headers)
        assert _status(sent) == 200
    else:  # pragma: no cover
        raise AssertionError(path)


def test_disconnect_after_response_started_is_absorbed_too(stack, monkeypatch):
    """Shape 3, simulated: an SDK that loses the client mid-stream.

    Unreachable on mcp 2.2.0 (see above), so fake it where the real modern
    entry sits. #81's exception handler turned this into
    RuntimeError("Caught handled exception, but response already started.").
    """
    import mcp.server.streamable_http_manager as manager

    async def streams_then_loses_client(*args):
        send = args[-1]
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]})
        await send({"type": "http.response.body", "body": b": ping\r\n\r\n", "more_body": True})
        raise ClientDisconnect()

    monkeypatch.setattr(manager, "handle_modern_request", streams_then_loses_client)
    headers, body = _modern("tools/list")
    assert _status(stack.exchange("POST", headers, body)) == 200


def test_hang_up_before_modern_body_is_read_gets_499(stack):
    """Shape 1: ClientDisconnect from the modern entry's body read."""
    headers, body = _modern("tools/call", _WHOAMI, name="markland_whoami")
    assert _status(stack.exchange("POST", headers, body, hang_up="before_body")) == CLIENT_CLOSED_REQUEST


def test_hang_up_during_modern_request_gets_499(stack, slow_tool):
    """Shape 2: the SDK cancels the running handler and returns without answering."""
    headers, body = _modern("tools/call", _WHOAMI, name="markland_whoami")
    assert _status(stack.exchange("POST", headers, body, hang_up="after_body")) == CLIENT_CLOSED_REQUEST


def test_hang_up_before_legacy_get_stream_opens_gets_499(stack):
    """Shape 2, legacy: sse-starlette sees the disconnect before it starts the stream."""
    headers = stack.legacy_session()
    sent = stack.exchange("GET", {"accept": "text/event-stream", **headers}, hang_up="before_body")
    assert _status(sent) == CLIENT_CLOSED_REQUEST


# ---------------------------------------------------------------------------
# Sentry: real uvicorn socket + real Sentry SDK instrumentation
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
        # Prod samples 10%; always sample so the tracing wrappers run every time.
        traces_sample_rate=1.0,
        send_default_pii=False,
        before_send=scrub_sentry_event,
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


def _post(
    port: int,
    token: str,
    path: str,
    headers: dict,
    body: bytes,
    *,
    send_bytes: int,
    linger: float = 0.3,
    until: threading.Event | None = None,
) -> bytes:
    """POST `body` but send only its first `send_bytes`; close after `linger` seconds or once `until` is set."""
    head = f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {token}\r\n"
    head += "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    head += f"Content-Length: {len(body)}\r\n\r\n"
    with socket.create_connection(("127.0.0.1", port)) as c:
        c.sendall(head.encode() + body[:send_bytes])
        if until is not None:
            assert until.wait(5), "the request never got going"
            return b""
        c.settimeout(linger)
        try:
            return c.recv(65536)
        except TimeoutError:
            return b""


def _wait_quiet(events: list[dict], seconds: float = 1.0) -> list[dict]:
    time.sleep(seconds)
    sentry_sdk.flush()
    return events


def _describe(events: list[dict]) -> list:
    return [
        (e.get("logger"), [(v.get("type"), v.get("value")) for v in (e.get("exception") or {}).get("values", [])])
        for e in events
    ]


@pytest.mark.parametrize(
    "path,protocol_version",
    [
        # The production signature: modern era, trailing-slash mount.
        ("/mcp/", MODERN),
        # Bare-path route (markland-dfj) delegates to the same sub-app.
        ("/mcp", MODERN),
        # Legacy era: already covered by before_send; guard against regressions.
        ("/mcp/", LEGACY),
    ],
)
def test_client_hangup_mid_body_reports_nothing_to_sentry(live_mcp, sentry_events, path, protocol_version):
    port, token = live_mcp
    headers = dict(_LEGACY_HEADERS, **{"MCP-Protocol-Version": protocol_version})
    _post(port, token, path, headers, b'{"jsonrpc":"2.0",' + b" " * 483, send_bytes=17)
    events = _wait_quiet(sentry_events)
    assert events == [], _describe(events)


def test_client_hangup_during_modern_request_reports_nothing_to_sentry(live_mcp, sentry_events, slow_tool):
    port, token = live_mcp
    headers, body = _modern("tools/call", _WHOAMI, name="markland_whoami")
    _post(port, token, "/mcp/", headers, body, send_bytes=len(body), until=slow_tool)
    events = _wait_quiet(sentry_events)
    assert events == [], _describe(events)


def test_genuine_mcp_error_still_reaches_sentry(live_mcp, sentry_events, monkeypatch):
    """The wrapper absorbs hang-ups only; a real fault on the same path still pages."""
    import mcp.server.streamable_http_manager as manager

    async def broken(*args, **kwargs):
        raise RuntimeError("genuine MCP fault")

    monkeypatch.setattr(manager, "handle_modern_request", broken)
    port, token = live_mcp
    headers, body = _modern("tools/list")
    reply = _post(port, token, "/mcp/", headers, body, send_bytes=len(body), linger=2.0)
    assert reply.startswith(b"HTTP/1.1 500")
    events = _wait_quiet(sentry_events, seconds=0.2)
    assert ("RuntimeError", "genuine MCP fault") in [pair for _, pairs in _describe(events) for pair in pairs]
