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
    # RFC 9728 §2 values are placement identifiers (header|body|query),
    # NOT the scheme name. Markland accepts the bearer only in Authorization.
    assert body["bearer_methods_supported"] == ["header"]
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


def test_discovery_responses_do_not_set_cookies():
    """MCP clients may cache discovery metadata. Make sure these endpoints
    never attach session cookies — global middleware adding one would taint
    cached client state.
    """
    client = TestClient(_app())
    r1 = client.get("/.well-known/oauth-protected-resource")
    r2 = client.get("/.well-known/oauth-authorization-server")
    assert "set-cookie" not in {k.lower() for k in r1.headers.keys()}
    assert "set-cookie" not in {k.lower() for k in r2.headers.keys()}


def test_oauth_protected_resource_with_mcp_suffix_returns_json_404():
    """SDK probes /.well-known/oauth-protected-resource/mcp before the
    suffix-less variant. We must return JSON, not HTML, so JSON.parse()
    in the SDK doesn't crash on '<'.
    """
    client = TestClient(_app())
    r = client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["error"] == "not_found"
    # Body should hint at the static-bearer model so a human reading the
    # SDK's surfaced error has somewhere to go.
    assert "bearer" in body["error_description"].lower()


def test_oauth_authorization_server_with_mcp_suffix_returns_json_404():
    client = TestClient(_app())
    r = client.get("/.well-known/oauth-authorization-server/mcp")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["error"] == "not_found"


def test_openid_configuration_returns_json_404():
    """Some MCP SDKs probe OpenID Connect discovery as a fallback.
    We don't speak OIDC; respond with JSON so the parser doesn't crash.
    """
    client = TestClient(_app())
    r = client.get("/.well-known/openid-configuration")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["error"] == "not_found"


def test_openid_configuration_with_mcp_suffix_returns_json_404():
    client = TestClient(_app())
    r = client.get("/.well-known/openid-configuration/mcp")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["error"] == "not_found"
