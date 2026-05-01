"""End-to-end tests for the signed-in nav banner across landing/doc/explore."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.email import EmailClient
from markland.service.sessions import SESSION_COOKIE_NAME, issue_session
from markland.service.users import create_user
from markland.web.app import create_app


SECRET = "test-session-secret"


class _NoopEmail(EmailClient):
    def __init__(self):
        super().__init__(api_key="", from_email="noreply@test.markland.dev")

    def send(self, *, to, subject, html):
        return "noop"


@pytest.fixture
def harness(tmp_path):
    conn = init_db(tmp_path / "t.db")
    app = create_app(
        conn,
        base_url="http://testserver",
        session_secret=SECRET,
        email_client=_NoopEmail(),
    )
    client = TestClient(app)
    yield client, conn
    client.close()


def _signed_in_client(harness, *, email: str = "alice@example.com"):
    """Return (client, user) where the client carries a valid session cookie."""
    client, conn = harness
    user = create_user(conn, email=email)
    cookie = issue_session(user.id, secret=SECRET)
    client.cookies.set(SESSION_COOKIE_NAME, cookie)
    return client, user


def test_anon_landing_has_no_signed_in_banner(harness):
    client, _ = harness
    r = client.get("/")
    assert r.status_code == 200
    assert "Signed in as" not in r.text


def test_signed_in_landing_shows_email_and_links(harness):
    client, user = _signed_in_client(harness, email="alice@example.com")
    r = client.get("/")
    assert r.status_code == 200
    assert "Signed in as" in r.text
    assert "alice@example.com" in r.text
    assert 'href="/explore?view=mine"' in r.text
    assert 'action="/api/auth/logout"' in r.text


def test_signed_in_doc_page_shows_banner(harness):
    client, conn = harness
    user = create_user(conn, email="bob@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    client.cookies.set(SESSION_COOKIE_NAME, cookie)

    # Insert a public doc the user can view.
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, "
        "updated_at, is_public, is_featured, owner_id) VALUES "
        "('doc_x', 'Hello', '# hi', 'tok_x', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 1, 0, ?)",
        (user.id,),
    )
    conn.commit()

    r = client.get("/d/tok_x")
    assert r.status_code == 200
    assert "Signed in as" in r.text
    assert "bob@example.com" in r.text


def test_anon_doc_page_has_no_banner(harness):
    """Belt-and-suspenders: also drop the cookie mid-fixture and confirm the
    banner disappears, so a future bug that leaks signed-in state across an
    anon visit gets caught."""
    client, conn = harness
    user = create_user(conn, email="bob@example.com")
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, "
        "updated_at, is_public, is_featured, owner_id) VALUES "
        "('doc_y', 'Public', '# hi', 'tok_y', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 1, 0, ?)",
        (user.id,),
    )
    conn.commit()

    # Anon hit — banner must NOT render.
    r = client.get("/d/tok_y")
    assert r.status_code == 200
    assert "Signed in as" not in r.text

    # Sign in, confirm the banner appears.
    cookie = issue_session(user.id, secret=SECRET)
    client.cookies.set(SESSION_COOKIE_NAME, cookie)
    r2 = client.get("/d/tok_y")
    assert r2.status_code == 200
    assert "Signed in as" in r2.text

    # Clear cookies, confirm the banner disappears again — guards against any
    # caching or state-leak regressions.
    client.cookies.clear()
    r3 = client.get("/d/tok_y")
    assert r3.status_code == 200
    assert "Signed in as" not in r3.text


def test_signed_in_explore_view_mine_lists_user_docs(harness):
    """The 'Your docs' link must actually work for cookie-auth'd users.

    This is the reachability bug: today /explore?view=mine returns the
    public list because principal is None for cookie users.
    """
    client, conn = harness
    user = create_user(conn, email="carol@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    client.cookies.set(SESSION_COOKIE_NAME, cookie)

    # Carol has one private doc.
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, "
        "updated_at, is_public, is_featured, owner_id) VALUES "
        "('doc_carol', 'Carol Plan', 'secret', 'tok_c', "
        "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 0, 0, ?)",
        (user.id,),
    )
    conn.commit()

    r = client.get("/explore?view=mine")
    assert r.status_code == 200
    assert "Carol Plan" in r.text  # would fail before fix — view=mine returned
                                   # public list for cookie users
    assert "Signed in as" in r.text


def test_banner_email_truncates_when_long(harness):
    """Long emails must not push 'Your docs / Sign out' off the viewport.

    The fix is CSS: max-width + text-overflow: ellipsis on the email span,
    plus flex-shrink: 0 on the action links. Asserting CSS in HTML is a
    weak signal but enough to catch a future refactor that strips the
    rules wholesale.
    """
    client, conn = harness
    user = create_user(conn, email="long+banner-test+long-alias@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    client.cookies.set(SESSION_COOKIE_NAME, cookie)

    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    # The email itself appears.
    assert "long+banner-test+long-alias@example.com" in body
    # The truncation rules are present in the partial's inline styles.
    assert "text-overflow:ellipsis" in body or "text-overflow: ellipsis" in body
    assert "flex-shrink:0" in body or "flex-shrink: 0" in body


def test_verify_sent_page_shows_banner(harness):
    """A naked sign-in (no return_to) lands on the verify_sent page.

    Pre-fix this rendered as a standalone light-themed page with no
    banner — the worst place for that gap, since it's the user's first
    impression after sign-in.
    """
    from markland.service.magic_link import issue_magic_link_token

    client, _ = harness
    token = issue_magic_link_token("alice@example.com", secret=SECRET)
    r = client.get(f"/verify?token={token}", follow_redirects=False)
    assert r.status_code == 200  # naked sign-in renders verify_sent
    body = r.text
    # Banner present
    assert "Signed in as" in body
    assert "alice@example.com" in body
    # Inherits base.html chrome
    assert 'href="/explore"' in body  # site-nav links


def test_settings_tokens_page_shows_banner_and_drops_bespoke_signout(harness):
    """Settings page should use the shared signed-in banner, not its own
    bespoke 'Sign out' fetch link."""
    client, conn = harness
    user = create_user(conn, email="bob@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    client.cookies.set(SESSION_COOKIE_NAME, cookie)

    r = client.get("/settings/tokens")
    assert r.status_code == 200
    body = r.text
    # Banner present
    assert "Signed in as" in body
    assert "bob@example.com" in body
    # Bespoke sign-out fetch JS removed.
    assert "fetch('/api/auth/logout'" not in body
