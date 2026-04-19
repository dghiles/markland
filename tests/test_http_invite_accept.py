"""POST /api/invites/{token}/accept."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.invites import create_invite
from markland.service.sessions import SESSION_COOKIE_NAME, issue_session
from markland.web.app import create_app


SECRET = "test-session-secret"


@pytest.fixture
def client(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_bob', 'bob@example.com', 'Bob', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "('doc_a', 'P', 'c', 'tok_a', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 0, 0, 'usr_alice')"
    )
    conn.commit()
    app = create_app(conn, base_url="http://testserver", session_secret=SECRET)
    with TestClient(app) as c:
        yield c, conn


def _login(c, user_id):
    c.cookies.clear()
    c.cookies.set(SESSION_COOKIE_NAME, issue_session(user_id, secret=SECRET))


def _invite(conn, level="view", single_use=True):
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level=level,
        base_url="http://testserver",
        single_use=single_use,
    )
    return r.url.rsplit("/", 1)[1]


def test_accept_unauthenticated_returns_401(client):
    c, conn = client
    token = _invite(conn)
    r = c.post(f"/api/invites/{token}/accept")
    assert r.status_code == 401


def test_accept_authenticated_creates_grant(client):
    c, conn = client
    token = _invite(conn, level="edit")
    _login(c, "usr_bob")
    r = c.post(f"/api/invites/{token}/accept")
    assert r.status_code == 200
    assert r.json() == {"doc_id": "doc_a", "level": "edit"}


def test_accept_same_invite_twice_single_use_second_is_410(client):
    c, conn = client
    token = _invite(conn)
    _login(c, "usr_bob")
    first = c.post(f"/api/invites/{token}/accept")
    assert first.status_code == 200

    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_carol', 'c@c.com', 'C', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    _login(c, "usr_carol")
    second = c.post(f"/api/invites/{token}/accept")
    assert second.status_code == 410


def test_accept_unknown_token_410(client):
    c, _ = client
    _login(c, "usr_bob")
    r = c.post("/api/invites/not_a_real_token_aaaaaaaaaaaaaaaaaaa/accept")
    assert r.status_code == 410
