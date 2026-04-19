"""GET /invite/{token} renders the accept page when signed in."""

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
        "VALUES ('usr_alice', 'alice@example.com', 'Alice Owner', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_bob', 'bob@example.com', 'Bob', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "('doc_a', 'Secret Plans', 'c', 'tok_a', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 0, 0, 'usr_alice')"
    )
    conn.commit()

    app = create_app(
        conn, base_url="https://test.markland.dev", session_secret=SECRET
    )
    with TestClient(app) as c:
        yield c, conn


def _token_for_new_invite(conn, level="view"):
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level=level,
        base_url="https://test.markland.dev",
    )
    return r.url.rsplit("/", 1)[1]


def test_invite_page_signed_in_shows_accept_button(client):
    c, conn = client
    token = _token_for_new_invite(conn, level="edit")
    c.cookies.set(SESSION_COOKIE_NAME, issue_session("usr_bob", secret=SECRET))
    r = c.get(f"/invite/{token}")
    assert r.status_code == 200
    assert "Accept and open document" in r.text
    assert "Secret Plans" in r.text
    assert "edit" in r.text
    assert "Alice Owner" in r.text


def test_invite_page_signed_out_shows_email_form(client):
    c, conn = client
    token = _token_for_new_invite(conn)
    # No login.
    r = c.get(f"/invite/{token}")
    assert r.status_code == 200
    assert "Send magic link" in r.text
    assert "Secret Plans" in r.text


def test_invite_page_gone_for_unknown_token(client):
    c, _ = client
    r = c.get("/invite/not_a_real_token_aaaaaaaaaaaaaaaaaaaa")
    assert r.status_code == 410


def test_invite_page_gone_after_revoke(client):
    c, conn = client
    token = _token_for_new_invite(conn)
    row = conn.execute("SELECT id FROM invites ORDER BY created_at DESC LIMIT 1").fetchone()
    conn.execute(
        "UPDATE invites SET revoked_at = '2026-04-19T00:00:00+00:00' WHERE id = ?",
        (row[0],),
    )
    conn.commit()
    r = c.get(f"/invite/{token}")
    assert r.status_code == 410
