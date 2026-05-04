"""Tests that PrincipalMiddleware advertises auth scheme via WWW-Authenticate.

Per RFC 9728 + MCP authorization spec (2026-05-03 / 2025-03-26), a 401 from a
protected MCP endpoint should carry a WWW-Authenticate header pointing the
client at the resource-metadata URL. Without this, MCP SDK clients fall through
to speculative OAuth discovery and crash on Markland's HTML 404 page.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.auth import create_user_token
from markland.service.users import create_user
from markland.web.principal_middleware import PrincipalMiddleware


def _app(conn):
    app = FastAPI()
    app.add_middleware(PrincipalMiddleware, db_conn=conn, protected_prefixes=("/mcp",))

    @app.get("/mcp/ping")
    def mcp_ping(request: Request):
        p = request.state.principal
        return JSONResponse({"id": p.principal_id})

    @app.get("/public")
    def public():
        return JSONResponse({"ok": True})

    return app


def test_401_missing_header_advertises_bearer(tmp_path):
    conn = init_db(tmp_path / "t.db")
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping")
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}
    www_auth = r.headers.get("www-authenticate", "")
    assert www_auth.startswith("Bearer "), f"expected Bearer scheme, got {www_auth!r}"
    assert 'realm="markland"' in www_auth
    assert 'resource_metadata=' in www_auth
    assert "/.well-known/oauth-protected-resource" in www_auth


def test_401_unknown_token_advertises_bearer(tmp_path):
    conn = init_db(tmp_path / "t.db")
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping", headers={"Authorization": "Bearer mk_usr_unknown"})
    assert r.status_code == 401
    assert r.headers.get("www-authenticate", "").startswith("Bearer ")


def test_200_does_not_set_www_authenticate(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="a@example.com", display_name="A")
    _, plaintext = create_user_token(conn, user_id=u.id, label="l")
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping", headers={"Authorization": f"Bearer {plaintext}"})
    assert r.status_code == 200
    assert "www-authenticate" not in {k.lower() for k in r.headers.keys()}


def test_unprotected_path_does_not_set_www_authenticate(tmp_path):
    conn = init_db(tmp_path / "t.db")
    client = TestClient(_app(conn))
    r = client.get("/public")
    assert r.status_code == 200
    assert "www-authenticate" not in {k.lower() for k in r.headers.keys()}
