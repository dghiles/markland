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
