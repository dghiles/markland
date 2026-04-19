"""Invite-acceptance triggers a best-effort email to the invite creator."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.email import EmailClient, EmailSendError
from markland.service.invites import create_invite
from markland.service.sessions import SESSION_COOKIE_NAME, issue_session
from markland.web.app import create_app


SECRET = "test-session-secret"


class _RecordingEmailClient(EmailClient):
    def __init__(self, *, fail: bool = False):
        super().__init__(api_key="test", from_email="noreply@test.markland.dev")
        self.sent: list[dict] = []
        self._fail = fail

    def send(self, *, to, subject, html):
        self.sent.append({"to": to, "subject": subject, "html": html})
        if self._fail:
            raise EmailSendError("fake failure")
        return "email_test_id"


def _make_app(tmp_path, email_client):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_bob', 'bob@example.com', 'Bob Q', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "('doc_a', 'Plans 2026', 'c', 'tok_a', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 0, 0, 'usr_alice')"
    )
    conn.commit()
    app = create_app(
        conn,
        base_url="http://testserver",
        session_secret=SECRET,
        email_client=email_client,
    )
    return app, conn


def _login(c, user_id):
    c.cookies.clear()
    c.cookies.set(SESSION_COOKIE_NAME, issue_session(user_id, secret=SECRET))


def test_accept_sends_email_to_creator(tmp_path):
    ec = _RecordingEmailClient()
    app, conn = _make_app(tmp_path, ec)
    r = create_invite(conn, doc_id="doc_a", created_by_user_id="usr_alice",
                      level="view", base_url="http://testserver")
    token = r.url.rsplit("/", 1)[1]
    with TestClient(app) as c:
        _login(c, "usr_bob")
        accept = c.post(f"/api/invites/{token}/accept")
        assert accept.status_code == 200

    assert len(ec.sent) == 1
    msg = ec.sent[0]
    assert msg["to"] == "alice@example.com"
    assert "Bob Q" in msg["html"]
    assert "Plans 2026" in msg["html"]
    assert "accepted" in msg["subject"].lower()


def test_accept_succeeds_even_when_email_fails(tmp_path):
    ec = _RecordingEmailClient(fail=True)
    app, conn = _make_app(tmp_path, ec)
    r = create_invite(conn, doc_id="doc_a", created_by_user_id="usr_alice",
                      level="view", base_url="http://testserver")
    token = r.url.rsplit("/", 1)[1]
    with TestClient(app) as c:
        _login(c, "usr_bob")
        accept = c.post(f"/api/invites/{token}/accept")
    # Invite still accepted despite email failure.
    assert accept.status_code == 200
    assert accept.json()["doc_id"] == "doc_a"
    g = conn.execute(
        "SELECT level FROM grants WHERE doc_id = ? AND principal_id = ?",
        ("doc_a", "usr_bob"),
    ).fetchone()
    assert g[0] == "view"
