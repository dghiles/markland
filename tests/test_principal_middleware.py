"""Tests for PrincipalMiddleware — bearer-token → request.state.principal on /mcp."""

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
        return JSONResponse({"id": p.principal_id, "type": p.principal_type})

    @app.get("/public")
    def public():
        return JSONResponse({"ok": True})

    return app


def test_public_path_does_not_require_token(tmp_path):
    conn = init_db(tmp_path / "t.db")
    client = TestClient(_app(conn))
    assert client.get("/public").status_code == 200


def test_missing_auth_header_returns_401(tmp_path):
    conn = init_db(tmp_path / "t.db")
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping")
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}


def test_malformed_auth_header_returns_401(tmp_path):
    conn = init_db(tmp_path / "t.db")
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping", headers={"Authorization": "nonsense"})
    assert r.status_code == 401


def test_unknown_token_returns_401(tmp_path):
    conn = init_db(tmp_path / "t.db")
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping", headers={"Authorization": "Bearer mk_usr_unknown"})
    assert r.status_code == 401


def test_revoked_token_returns_401(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="a@example.com", display_name="A")
    token_id, plaintext = create_user_token(conn, user_id=u.id, label="l")
    from markland.service.auth import revoke_token
    revoke_token(conn, token_id=token_id, user_id=u.id)
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping", headers={"Authorization": f"Bearer {plaintext}"})
    assert r.status_code == 401


def test_valid_token_attaches_principal(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="a@example.com", display_name="A")
    _, plaintext = create_user_token(conn, user_id=u.id, label="l")
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping", headers={"Authorization": f"Bearer {plaintext}"})
    assert r.status_code == 200
    assert r.json() == {"id": u.id, "type": "user"}
