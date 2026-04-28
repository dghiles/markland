"""Full flow: anon user → magic-link form → email sent → verify → invite accepted → redirect."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.email import EmailClient
from markland.service.invites import create_invite
from markland.web.app import create_app


SECRET = "test-session-secret"


class _RecordingEmailClient(EmailClient):
    """Captures every .send() call for assertions."""

    def __init__(self):
        super().__init__(api_key="", from_email="noreply@test.markland.dev")
        self.sent: list[dict] = []

    def send(self, *, to, subject, html):
        self.sent.append({"to": to, "subject": subject, "html": html})
        return "email_test_id"


@pytest.fixture
def harness(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "('doc_a', 'Alice plan', 'c', 'tok_a', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 0, 0, 'usr_alice')"
    )
    conn.commit()

    email_client = _RecordingEmailClient()
    app = create_app(
        conn,
        base_url="http://testserver",
        session_secret=SECRET,
        email_client=email_client,
    )
    client = TestClient(app)
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="http://testserver",
    )
    token = r.url.rsplit("/", 1)[1]
    yield client, conn, email_client, token
    client.close()


def test_anon_invite_flow_end_to_end(harness):
    client, conn, email_client, token = harness

    # 1. Anon visits /invite/{token}, sees the email form.
    page = client.get(f"/invite/{token}")
    assert page.status_code == 200
    assert "Send magic link" in page.text

    # 2. Submits the email form. Handler creates a magic-link token AND emails.
    resp = client.post(
        "/api/auth/magic-link",
        data={"email": "bob@example.com", "return_to": f"/invite/{token}"},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302), resp.text
    assert len(email_client.sent) >= 1
    assert email_client.sent[-1]["to"] == "bob@example.com"
    magic_html = email_client.sent[-1]["html"]
    match = re.search(r'href=["\']([^"\']*verify[^"\']*)["\']', magic_html)
    assert match is not None, f"no verify link in email: {magic_html}"
    # HTML attributes are autoescaped (`&amp;`); unescape for HTTP follow.
    import html as _html
    verify_url = _html.unescape(match.group(1))

    # 3. "Click" the magic link — establishes session + redirects to return_to.
    verify_resp = client.get(verify_url, follow_redirects=False)
    assert verify_resp.status_code in (302, 303)
    assert verify_resp.headers["location"].endswith(f"/invite/{token}")

    # 4. Re-fetch the invite page; shows accept button for the new user.
    accept_page = client.get(f"/invite/{token}")
    assert accept_page.status_code == 200
    assert "Accept and open document" in accept_page.text

    # 5. Accept.
    accept = client.post(f"/api/invites/{token}/accept")
    assert accept.status_code == 200
    body = accept.json()
    assert body["doc_id"] == "doc_a"
    assert body["level"] == "view"

    # Grant row exists for some non-Alice user.
    g = conn.execute(
        "SELECT principal_id, level FROM grants WHERE doc_id = ?", ("doc_a",)
    ).fetchall()
    principals = {r[0] for r in g}
    assert any(p != "usr_alice" for p in principals)

    # Invite is now consumed.
    inv_row = conn.execute("SELECT uses_remaining FROM invites").fetchone()
    assert inv_row[0] == 0


def test_form_post_to_magic_link_returns_html_not_raw_json(harness):
    """A browser form submit (no JSON header) should land on a 'check your
    email' HTML page, not display raw {"ok":true}."""
    client, conn, email_client, token = harness

    resp = client.post(
        "/api/auth/magic-link",
        data={"email": "carol@example.com", "return_to": f"/invite/{token}"},
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.text
    ctype = resp.headers.get("content-type", "")
    assert "text/html" in ctype, f"expected HTML, got {ctype}: {resp.text[:200]}"
    assert "Check your email" in resp.text
    assert '{"ok"' not in resp.text


def test_form_post_url_encodes_return_to_in_request_new_link(harness):
    """The 'request a new one' link must URL-encode return_to so query strings
    inside it survive a round trip through /login?next=…"""
    client, _conn, _email_client, _token = harness
    tricky = "/d/abc?x=1&y=2"

    resp = client.post(
        "/api/auth/magic-link",
        data={"email": "eve@example.com", "return_to": tricky},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    # The reserved '?' and '&' from return_to must be percent-encoded inside
    # the next= value so they don't leak as sibling query params on /login.
    assert "next=" in resp.text
    assert "%3F" in resp.text  # encoded '?'
    assert "%26" in resp.text  # encoded '&'
    assert "y=2" not in resp.text  # would indicate a sibling param leak


def test_json_post_to_magic_link_still_returns_json(harness):
    """JSON callers (login page JS, API clients) keep getting JSON."""
    client, conn, email_client, token = harness

    resp = client.post(
        "/api/auth/magic-link",
        json={"email": "dave@example.com", "return_to": "/"},
    )
    assert resp.status_code == 200
    assert "application/json" in resp.headers.get("content-type", "")
    assert resp.json() == {"ok": True}
