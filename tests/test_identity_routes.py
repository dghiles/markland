"""Tests for /api/me, /api/tokens, and /settings/tokens."""

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
        mount_mcp=False,
        base_url="http://testserver",
        session_secret="test-secret",
        email_client=email_client,
    )
    with TestClient(app) as c:
        yield c


def _sign_in(client, email: str) -> None:
    token = issue_magic_link_token(email, secret="test-secret")
    r = client.post("/api/auth/verify", json={"token": token})
    assert r.status_code == 200


def test_me_requires_session(client):
    r = client.get("/api/me")
    assert r.status_code == 401


def test_me_returns_user(client):
    _sign_in(client, "alice@example.com")
    r = client.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["user_id"].startswith("usr_")
    assert body["is_admin"] is False


def test_create_token_requires_session(client):
    r = client.post("/api/tokens", json={"label": "laptop"})
    assert r.status_code == 401


def test_create_token_returns_plaintext_once(client):
    _sign_in(client, "alice@example.com")
    r = client.post("/api/tokens", json={"label": "laptop"})
    assert r.status_code == 200
    body = r.json()
    assert body["token"].startswith("mk_usr_")
    assert body["id"].startswith("tok_")
    assert body["label"] == "laptop"


def test_list_tokens_omits_plaintext(client):
    _sign_in(client, "alice@example.com")
    client.post("/api/tokens", json={"label": "laptop"})
    client.post("/api/tokens", json={"label": "phone"})
    r = client.get("/api/me")
    labels = {t["label"] for t in r.json()["tokens"]}
    assert labels == {"laptop", "phone"}
    for t in r.json()["tokens"]:
        assert "token" not in t


def test_delete_token_revokes(client):
    _sign_in(client, "alice@example.com")
    created = client.post("/api/tokens", json={"label": "laptop"}).json()
    token_id = created["id"]
    r = client.delete(f"/api/tokens/{token_id}")
    assert r.status_code == 200
    me = client.get("/api/me").json()
    assert all(t["id"] != token_id for t in me["tokens"])


def test_delete_token_other_user_returns_404(client):
    _sign_in(client, "alice@example.com")
    created = client.post("/api/tokens", json={"label": "laptop"}).json()
    token_id = created["id"]

    # Sign in as a different user
    client.post("/api/auth/logout")
    _sign_in(client, "bob@example.com")
    r = client.delete(f"/api/tokens/{token_id}")
    assert r.status_code == 404


def test_settings_tokens_page_requires_session(client):
    r = client.get("/settings/tokens", follow_redirects=False)
    assert r.status_code in (302, 303, 401)


def test_settings_tokens_page_renders_when_signed_in(client):
    _sign_in(client, "alice@example.com")
    r = client.get("/settings/tokens")
    assert r.status_code == 200
    assert "Tokens" in r.text or "tokens" in r.text
