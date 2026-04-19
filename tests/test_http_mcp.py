"""Integration test: MCP tools reachable over HTTP with a real user token."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.auth import create_user_token
from markland.service.users import create_user
from markland.web.app import create_app


@pytest.fixture
def client_and_token(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    from markland.config import reset_config
    reset_config()
    conn = init_db(db_path)
    user = create_user(conn, email="smoke@example.com", display_name="Smoke")
    _, plaintext = create_user_token(conn, user_id=user.id, label="smoke")
    app = create_app(
        conn,
        mount_mcp=True,
        base_url="http://testserver",
        session_secret="test-secret",
    )
    with TestClient(app) as c:
        yield c, plaintext


def test_mcp_endpoint_rejects_unauthenticated(client_and_token):
    client, _ = client_and_token
    r = client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert r.status_code == 401


def test_mcp_endpoint_rejects_unknown_bearer(client_and_token):
    client, _ = client_and_token
    r = client.post(
        "/mcp/",
        headers={"Authorization": "Bearer mk_usr_unknown"},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert r.status_code == 401


def test_mcp_endpoint_accepts_valid_user_token(client_and_token):
    client, plaintext = client_and_token
    r = client.post(
        "/mcp/",
        headers={
            "Authorization": f"Bearer {plaintext}",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
    )
    assert r.status_code == 200


def test_web_routes_still_public(client_and_token):
    client, _ = client_and_token
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/explore").status_code == 200
