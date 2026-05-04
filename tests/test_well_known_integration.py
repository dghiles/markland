"""End-to-end: the discovery routes are reachable on the main FastAPI app
and the WWW-Authenticate header on /mcp 401s points at a URL that actually
returns JSON 200."""

import re
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


def build_app_for_test(conn):
    """Single source of truth for test-app construction. Mirrors the kwargs
    that the existing two integration tests use; centralising lets the
    parametrized test below stay tight.
    """
    return create_app(
        conn,
        base_url="http://testserver",
        enable_presence_gc=False,
        mount_mcp=False,
    )


def test_discovery_url_in_www_authenticate_returns_json(tmp_path):
    conn = init_db(tmp_path / "t.db")
    app = create_app(
        conn,
        base_url="http://testserver",
        enable_presence_gc=False,
        mount_mcp=False,  # PrincipalMiddleware still gates /mcp paths even unmounted
    )
    client = TestClient(app)

    r = client.get("/mcp/anything")
    assert r.status_code == 401
    www_auth = r.headers["www-authenticate"]
    m = re.search(r'resource_metadata="([^"]+)"', www_auth)
    assert m, f"no resource_metadata in {www_auth!r}"
    metadata_url = m.group(1)

    # Strip scheme+host — TestClient is single-origin.
    path = urlparse(metadata_url).path
    r2 = client.get(path)
    assert r2.status_code == 200
    assert r2.headers["content-type"].startswith("application/json")
    assert r2.json()["resource"] == "http://testserver/mcp"


def test_authorization_server_endpoint_is_mounted(tmp_path):
    """Smoke test: the authz-server 404-JSON route is also wired."""
    conn = init_db(tmp_path / "t.db")
    app = create_app(
        conn,
        base_url="http://testserver",
        enable_presence_gc=False,
        mount_mcp=False,
    )
    client = TestClient(app)

    r = client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["error"] == "no_oauth_server"


@pytest.mark.parametrize("method,path", [
    # Already-fixed paths (from markland-2yj). Listed here so the regression
    # net catches a future change that breaks them.
    ("GET", "/.well-known/oauth-protected-resource"),
    ("GET", "/.well-known/oauth-authorization-server"),
    ("GET", "/.well-known/oauth-protected-resource/"),
    # New paths fixed in markland-6o6.
    ("GET", "/.well-known/oauth-protected-resource/mcp"),
    ("GET", "/.well-known/oauth-authorization-server/mcp"),
    ("GET", "/.well-known/openid-configuration"),
    ("GET", "/.well-known/openid-configuration/mcp"),
    ("GET", "/register"),
    ("POST", "/register"),
    # Middleware-protected /mcp/* probe — middleware returns JSON 401, which
    # is also fine for the SDK's parser. We assert JSON to lock that in.
    ("GET", "/mcp/.well-known/openid-configuration"),
])
def test_every_observed_probe_path_returns_json(tmp_path, method, path):
    """Every path the Claude Code MCP SDK was observed to probe in production
    logs (2026-05-04 production install) must return JSON, not
    HTML. The exact status code varies by path (200, 401, 404), but the
    content-type MUST be application/json — anything else crashes the SDK's
    JSON.parse with `Unrecognized token <` and breaks the install.
    """
    conn = init_db(tmp_path / "t.db")
    app = build_app_for_test(conn)
    client = TestClient(app)
    r = client.request(method, path)
    assert r.headers["content-type"].startswith("application/json"), (
        f"{method} {path} returned content-type "
        f"{r.headers['content-type']!r} (status {r.status_code}); "
        f"body starts with {r.text[:80]!r}"
    )
