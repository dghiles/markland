"""HTTP routes for invite creation and revocation."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.email import EmailClient
from markland.service.sessions import SESSION_COOKIE_NAME, issue_session
from markland.web.app import create_app


SECRET = "test-session-secret"


def _cookie_for(user_id: str) -> str:
    return issue_session(user_id, secret=SECRET)


@pytest.fixture
def client(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_mallory', 'm@m.com', 'Mallory', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "('doc_a', 'Alice doc', 'c', 'tok_a', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 0, 0, 'usr_alice')"
    )
    conn.commit()

    app = create_app(
        conn,
        base_url="https://test.markland.dev",
        session_secret=SECRET,
        email_client=EmailClient(api_key="", from_email="t@t.dev"),
    )
    with TestClient(app) as c:
        yield c, conn


def _login_as(client, user_id):
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, _cookie_for(user_id))


def test_create_invite_owner_succeeds(client):
    c, _ = client
    _login_as(c, "usr_alice")
    r = c.post(
        "/api/docs/doc_a/invites",
        json={"level": "view", "single_use": True},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"].startswith("inv_")
    assert body["url"].startswith("https://test.markland.dev/invite/")
    assert body["level"] == "view"


def test_create_invite_non_owner_denied(client):
    c, _ = client
    _login_as(c, "usr_mallory")
    r = c.post(
        "/api/docs/doc_a/invites",
        json={"level": "view", "single_use": True},
    )
    assert r.status_code in (403, 404)


def test_create_invite_unauthenticated_rejected(client):
    c, _ = client
    c.cookies.clear()
    r = c.post(
        "/api/docs/doc_a/invites",
        json={"level": "view", "single_use": True},
    )
    assert r.status_code == 401


def test_create_invite_bad_level_400(client):
    c, _ = client
    _login_as(c, "usr_alice")
    r = c.post(
        "/api/docs/doc_a/invites",
        json={"level": "admin", "single_use": True},
    )
    assert r.status_code == 400 or r.status_code == 422


def test_delete_invite_owner_succeeds(client):
    c, conn = client
    _login_as(c, "usr_alice")
    r = c.post("/api/docs/doc_a/invites", json={"level": "view", "single_use": True})
    invite_id = r.json()["id"]

    r2 = c.delete(f"/api/invites/{invite_id}")
    assert r2.status_code == 204
    row = conn.execute("SELECT revoked_at FROM invites WHERE id = ?", (invite_id,)).fetchone()
    assert row[0] is not None


def test_delete_invite_non_owner_denied(client):
    c, _ = client
    _login_as(c, "usr_alice")
    created = c.post("/api/docs/doc_a/invites", json={"level": "view", "single_use": True})
    invite_id = created.json()["id"]

    _login_as(c, "usr_mallory")
    r = c.delete(f"/api/invites/{invite_id}")
    assert r.status_code in (403, 404)


def test_create_invite_expires_in_days(client):
    c, _ = client
    _login_as(c, "usr_alice")
    r = c.post(
        "/api/docs/doc_a/invites",
        json={"level": "edit", "single_use": False, "expires_in_days": 14},
    )
    assert r.status_code == 201
    assert r.json()["expires_at"] is not None
