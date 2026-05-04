"""End-to-end: the discovery routes are reachable on the main FastAPI app
and the WWW-Authenticate header on /mcp 401s points at a URL that actually
returns JSON 200."""

import re
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


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
