"""Tests for /.well-known/oauth-protected-resource and /.well-known/oauth-authorization-server.

These endpoints exist to give MCP clients a JSON-shaped answer when they
auto-probe for OAuth discovery. They MUST NOT trip clients into a real OAuth
flow — Markland uses static bearer tokens.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from markland.web.well_known_routes import register_well_known_routes


def _app():
    app = FastAPI()
    register_well_known_routes(app, base_url="https://markland.dev")
    return app


def test_protected_resource_returns_json_200():
    client = TestClient(_app())
    r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    # RFC 9728 fields
    assert body["resource"] == "https://markland.dev/mcp"
    assert "Bearer" in body["bearer_methods_supported"]
    # Markland-specific hint pointing humans at the token-mint UI
    assert body["token_mint_url"].endswith("/settings/tokens")
    # Explicitly NO authorization_servers — we don't speak OAuth
    assert body.get("authorization_servers", []) == []


def test_authorization_server_returns_json_404():
    """SDK probes that fall through to /.well-known/oauth-authorization-server
    must get a JSON body with a 404 status — never HTML — so JSON.parse() succeeds.
    """
    client = TestClient(_app())
    r = client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["error"] == "no_oauth_server"
    assert "bearer" in body["error_description"].lower()


def test_protected_resource_path_is_exact():
    """Trailing-slash and case variants should NOT match — keeps the surface tight."""
    client = TestClient(_app())
    assert client.get("/.well-known/oauth-protected-resource/").status_code == 404
    assert client.get("/.WELL-KNOWN/oauth-protected-resource").status_code == 404
