"""End-to-end: user signs up via magic link, creates a token, calls markland_whoami over HTTP."""

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.magic_link import issue_magic_link_token
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "t.db")
    email_client = MagicMock()
    email_client.send.return_value = None
    app = create_app(
        conn,
        mount_mcp=True,
        base_url="http://testserver",
        session_secret="test-secret",
        email_client=email_client,
    )
    with TestClient(app) as c:
        yield c


def test_full_onboarding_flow_and_whoami(client):
    # 1. Request magic link
    r = client.post("/api/auth/magic-link", json={"email": "alice@example.com"})
    assert r.status_code == 200

    # 2. Simulate clicking the email link (test bypasses the email itself)
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    r = client.post("/api/auth/verify", json={"token": token})
    assert r.status_code == 200

    # 3. Create a bearer token while session is active
    r = client.post("/api/tokens", json={"label": "claude-code"})
    assert r.status_code == 200
    bearer = r.json()["token"]
    assert bearer.startswith("mk_usr_")

    # 4. Hit /mcp with the bearer and call markland_whoami
    r = client.post(
        "/mcp/",
        headers={
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            },
        },
    )
    assert r.status_code == 200


def test_mcp_rejects_without_bearer_even_with_session(client):
    # Verify that a logged-in session (cookie) does NOT authorize /mcp.
    # /mcp requires a bearer token, full stop.
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    client.post("/api/auth/verify", json={"token": token})
    r = client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert r.status_code == 401
