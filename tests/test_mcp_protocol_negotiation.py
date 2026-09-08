"""Pins the protocol era markland negotiates with modern MCP clients.

Claude Code >=2.1.263 opens a connection by probing `server/discover` at
protocol 2026-07-28 instead of the legacy `initialize` handshake. On the
mcp 1.x SDK that probe was rejected (`400 Bad Request: Missing session ID`),
the client hung up mid-request, and each attempt cost two Sentry ERROR events
(markland-g1b). These tests fail if the SDK floor regresses below the era
that answers the probe, or if the `/mcp` mount stops carrying it.
"""

from __future__ import annotations

import os
import socket
import threading
import time

import pytest
import uvicorn

from markland.db import init_db
from markland.server import build_mcp
from markland.service.auth import create_user_token
from markland.service.users import create_user
from markland.web.app import create_app

MODERN_VERSION = "2026-07-28"


@pytest.mark.asyncio
async def test_discover_advertises_modern_protocol(tmp_path):
    """The tool server answers `server/discover`, not just `initialize`."""
    from mcp import Client

    conn = init_db(str(tmp_path / "t.db"))
    async with Client(build_mcp(conn, base_url="http://x"), mode="auto") as client:
        discover = client.session.discover_result
        assert discover is not None, "server/discover was not answered"
        assert MODERN_VERSION in discover.supported_versions


@pytest.fixture
def live_server(tmp_path):
    """Real uvicorn socket — TestClient can't exercise the streamable-HTTP client."""
    os.environ.setdefault("MARKLAND_SESSION_SECRET", "x" * 32)
    conn = init_db(str(tmp_path / "t.db"))
    user = create_user(conn, email="probe@example.com", display_name="Probe")
    _, token = create_user_token(conn, user_id=user.id, label="probe")
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

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "uvicorn did not start"

    yield f"http://127.0.0.1:{port}/mcp/", token

    server.should_exit = True
    thread.join(timeout=10)


@pytest.mark.asyncio
async def test_http_client_negotiates_discover_through_the_mount(live_server):
    """End-to-end over the real mount + PrincipalMiddleware, as Claude Code connects."""
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    url, token = live_server

    class BearerTransport:
        async def __aenter__(self):
            self._http = httpx2.AsyncClient(
                headers={"Authorization": f"Bearer {token}"}
            )
            self._cm = streamable_http_client(url, http_client=self._http)
            return await self._cm.__aenter__()

        async def __aexit__(self, *exc):
            try:
                return await self._cm.__aexit__(*exc)
            finally:
                await self._http.aclose()

    async with Client(BearerTransport(), mode="auto") as client:
        assert client.session.discover_result is not None
        assert MODERN_VERSION in client.session.discover_result.supported_versions
        assert len((await client.list_tools()).tools) > 0

    # Legacy clients must keep working off the same mount.
    async with Client(BearerTransport(), mode="legacy") as client:
        assert client.session.initialize_result is not None
        assert len((await client.list_tools()).tools) > 0
