"""End-to-end spec §6.3: owner creates invite → signs out → anon opens URL →
magic-link sign-up → invite accepted → redirected to doc. Single test, full arc."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.email import EmailClient
from markland.service.sessions import SESSION_COOKIE_NAME, issue_session
from markland.web.app import create_app


SECRET = "test-session-secret"


class _Recorder(EmailClient):
    def __init__(self):
        super().__init__(api_key="", from_email="noreply@test")
        self.sent = []

    def send(self, *, to, subject, html):
        self.sent.append({"to": to, "subject": subject, "html": html})
        return "e"


def test_invite_spec_6_3_happy_path(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "('doc_a', 'Launch doc', 'body', 'tok_a', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 0, 0, 'usr_alice')"
    )
    conn.commit()

    ec = _Recorder()
    app = create_app(
        conn,
        base_url="http://testserver",
        session_secret=SECRET,
        email_client=ec,
    )
    with TestClient(app) as c:
        # 1. Alice logs in (session cookie) and creates the invite via HTTP.
        c.cookies.set(SESSION_COOKIE_NAME, issue_session("usr_alice", secret=SECRET))
        create = c.post(
            "/api/docs/doc_a/invites",
            json={"level": "edit", "single_use": True},
        )
        assert create.status_code == 201
        invite_url = create.json()["url"]
        token = invite_url.rsplit("/", 1)[1]

        # 2. Alice signs out; Bob visits the URL.
        c.post("/api/auth/logout")
        c.cookies.clear()

        # 3. Anon GET: email form.
        anon_page = c.get(f"/invite/{token}")
        assert anon_page.status_code == 200
        assert "Send magic link" in anon_page.text

        # 4. Anon POSTs email form.
        n_before = len(ec.sent)
        c.post(
            "/api/auth/magic-link",
            data={"email": "bob@example.com", "return_to": f"/invite/{token}"},
        )
        assert len(ec.sent) == n_before + 1

        # 5. Extract magic-link URL from the email and follow it.
        match = re.search(r'href=["\']([^"\']*verify[^"\']*)["\']', ec.sent[-1]["html"])
        assert match
        # HTML attributes are autoescaped (`&amp;`); unescape for HTTP follow.
        import html as _html
        verify = _html.unescape(match.group(1))
        follow = c.get(verify, follow_redirects=False)
        assert follow.status_code in (302, 303)
        assert follow.headers["location"].endswith(f"/invite/{token}")

        # 6. Bob is now signed in; landing page shows the Accept button.
        landing = c.get(f"/invite/{token}")
        assert landing.status_code == 200
        assert "Accept and open document" in landing.text

        # 7. Bob accepts. Grant row is created.
        accept = c.post(f"/api/invites/{token}/accept")
        assert accept.status_code == 200
        assert accept.json() == {"doc_id": "doc_a", "level": "edit"}

    # 8. Verify grant row exists for Bob at edit level.
    bob_row = conn.execute(
        "SELECT u.id, g.level FROM users u JOIN grants g ON g.principal_id = u.id "
        "WHERE u.email = 'bob@example.com' AND g.doc_id = 'doc_a'"
    ).fetchone()
    assert bob_row is not None
    assert bob_row[1] == "edit"

    # 9. Creator received a notification email.
    subjects = [m["subject"] for m in ec.sent]
    assert any("accepted" in s.lower() for s in subjects)

    # 10. Invite is consumed (single-use).
    inv_row = conn.execute("SELECT uses_remaining FROM invites").fetchone()
    assert inv_row[0] == 0
