"""Route tests for magic-link login flow."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.magic_link import issue_magic_link_token
from markland.service.sessions import SESSION_COOKIE_NAME
from markland.service.users import get_user_by_email
from markland.web.app import create_app


@pytest.fixture
def client_and_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "t.db")
    email_client = MagicMock()
    email_client.send.return_value = None
    app = create_app(
        conn,
        mount_mcp=False,
        base_url="http://testserver",
        session_secret="test-secret",
        email_client=email_client,
    )
    with TestClient(app) as c:
        yield c, conn, email_client


def test_login_page_renders(client_and_conn):
    client, _, _ = client_and_conn
    r = client.get("/login")
    assert r.status_code == 200
    assert "magic link" in r.text.lower() or "email" in r.text.lower()


def test_post_magic_link_sends_email(client_and_conn):
    client, _, email_client = client_and_conn
    r = client.post("/api/auth/magic-link", json={"email": "alice@example.com"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    email_client.send.assert_called_once()


def test_post_magic_link_rejects_missing_email(client_and_conn):
    client, _, _ = client_and_conn
    r = client.post("/api/auth/magic-link", json={})
    assert r.status_code == 400 or r.status_code == 422


def test_verify_with_valid_token_creates_user_and_session(client_and_conn):
    client, conn, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    r = client.post("/api/auth/verify", json={"token": token})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert SESSION_COOKIE_NAME in r.cookies
    assert get_user_by_email(conn, "alice@example.com") is not None


def test_verify_with_bad_token_returns_400(client_and_conn):
    client, _, _ = client_and_conn
    r = client.post("/api/auth/verify", json={"token": "garbage"})
    assert r.status_code == 400


def test_logout_clears_session_cookie(client_and_conn):
    client, _, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    client.post("/api/auth/verify", json={"token": token})
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    # After logout, /api/me should be 401
    r2 = client.get("/api/me")
    assert r2.status_code == 401


def test_verify_page_renders(client_and_conn):
    client, _, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    r = client.get(f"/verify?token={token}")
    # Page sets cookie and shows success OR redirects to /settings/tokens.
    assert r.status_code in (200, 302, 303)
