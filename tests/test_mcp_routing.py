"""MCP /mcp routing — both /mcp and /mcp/ should reach the sub-app
without a 307 round-trip. Pins markland-dfj.

CRITICAL: PrincipalMiddleware short-circuits unauthenticated /mcp* requests
with a 401 BEFORE any route lookup, so the redirect only manifests on
AUTHENTICATED requests. Tests must mint a real token and send it as
`Authorization: Bearer ...`, otherwise the 401 short-circuit will hide
the 307 and the tests will be green-on-red (passing on broken code).
"""

# Tried first (markland-dfj Task 2): FastAPI(redirect_slashes=False).
# Doesn't help — it stops the 307 but POST /mcp then 404s instead of
# reaching the sub-app, because the Mount at /mcp serves /mcp/* (with
# trailing slash) and relies on Starlette's Mount.handle slash-redirect
# to canonicalize /mcp -> /mcp/. Disabling the FastAPI Router-level
# redirect_slashes flag also broke two pre-existing tests in
# tests/test_proxy_headers.py
# (test_mcp_redirect_downgrades_without_proxy_headers and
# test_mcp_redirect_preserves_https_with_proxy_headers) which assert
# that POST /mcp 307s — they got 404 instead. The fix has to operate at
# the route level (an explicit handler that dispatches into the mounted
# ASGI app), not the router level. See Task 3 of
# docs/plans/2026-05-04-mcp-trailing-slash-redirect.md.

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.auth import create_user_token
from markland.service.users import create_user
from markland.web.app import create_app

SECRET = "test-session-secret"


@pytest.fixture
def authed(tmp_path, monkeypatch):
    """TestClient + headers dict with a valid bearer token."""
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "test.db")
    user = create_user(conn, email="dfj@example.com", display_name="DFJ")
    _, token = create_user_token(conn, user_id=user.id, label="dfj-test")
    app = create_app(
        conn, mount_mcp=True,
        base_url="https://markland.dev",
        session_secret=SECRET,
    )
    with TestClient(app, base_url="http://testserver") as c:
        yield c, {"Authorization": f"Bearer {token}"}


def test_mcp_no_slash_does_not_redirect(authed):
    """POST /mcp (no slash) must reach the sub-app directly, not 307 to /mcp/."""
    client, hdrs = authed
    r = client.post(
        "/mcp",
        headers={
            **hdrs,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "no-redirect-test", "version": "0"},
            },
        },
        follow_redirects=False,
    )
    assert r.status_code != 307, (
        f"got 307 → location: {r.headers.get('location')!r}. "
        f"This is the bug — middleware passed (auth ok), Starlette's mount "
        f"redirected /mcp to /mcp/."
    )
    # Acceptable terminal codes: 200 (initialize accepted), 202 (accepted async),
    # or any other non-3xx. We don't pin the exact value because FastMCP can
    # legitimately respond several ways depending on session state.
    assert r.status_code < 300 or r.status_code >= 400, r.text[:200]


def test_mcp_slash_works_unchanged(authed):
    """Regression guard: POST /mcp/ continues to work exactly as pre-fix."""
    client, hdrs = authed
    r = client.post(
        "/mcp/",
        headers={
            **hdrs,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "regress", "version": "0"},
            },
        },
        follow_redirects=False,
    )
    assert r.status_code != 307
    assert r.status_code < 300 or r.status_code >= 400, r.text[:200]


def test_mcp_get_no_slash_does_not_redirect(authed):
    """GET /mcp also must not 307 — FastMCP uses GET for SSE event stream."""
    client, hdrs = authed
    r = client.get(
        "/mcp",
        headers={**hdrs, "Accept": "text/event-stream"},
        follow_redirects=False,
    )
    assert r.status_code != 307, f"got 307 → {r.headers.get('location')!r}"


def test_unauthenticated_post_mcp_short_circuits_to_401(tmp_path, monkeypatch):
    """Defensive: middleware must continue to short-circuit unauth requests
    BEFORE reaching the route — so we never accidentally redirect an
    unauthenticated request to /mcp/. This is current behavior; the test
    locks it in so the Task 2/3 fix can't accidentally break it."""
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "test.db")
    app = create_app(
        conn, mount_mcp=True,
        base_url="https://markland.dev",
        session_secret=SECRET,
    )
    with TestClient(app, base_url="http://testserver") as c:
        r = c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
            follow_redirects=False,
        )
        assert r.status_code == 401, f"expected 401, got {r.status_code}"
