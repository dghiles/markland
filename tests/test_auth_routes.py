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


def test_logout_json_api_returns_ok(client_and_conn):
    """JSON callers (e.g. settings page JS) keep getting JSON {"ok": true}."""
    client, _, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    client.post("/api/auth/verify", json={"token": token})
    r = client.post("/api/auth/logout", headers={"accept": "application/json"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    # After logout, /api/me should be 401
    r2 = client.get("/api/me")
    assert r2.status_code == 401


def test_logout_form_post_redirects_to_root(client_and_conn):
    """Real <form method=post> submits (no JSON Accept) get a 303 redirect home,
    not raw {"ok":true}."""
    client, _, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    client.post("/api/auth/verify", json={"token": token})
    r = client.post("/api/auth/logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    # After logout, /api/me should be 401
    r2 = client.get("/api/me")
    assert r2.status_code == 401


def test_verify_page_renders(client_and_conn):
    client, _, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    r = client.get(f"/verify?token={token}")
    # Page sets cookie and shows success OR redirects to /settings/tokens.
    assert r.status_code in (200, 302, 303)


def test_login_threads_next_param_into_magic_link(client_and_conn, monkeypatch):
    """When /login has ?next=/device, the issued magic link must return there.

    Background: /device redirects unauth'd users to /login?next=/device.
    If `next` doesn't make it into the magic-link `return_to`, users land
    on /settings/tokens after sign-in and the device flow stays pending.
    """
    client, _, _ = client_and_conn
    captured = {}

    def fake_send_magic_link(*, dispatcher, email, secret, base_url, return_to=None, **_):
        captured["email"] = email
        captured["return_to"] = return_to
        return "fake_token"

    monkeypatch.setattr(
        "markland.web.auth_routes.send_magic_link", fake_send_magic_link
    )

    # The login page must render the `next` value so the JS can include it.
    page = client.get("/login?next=/device")
    assert page.status_code == 200
    assert "/device" in page.text

    # Posting the magic-link request with return_to set must thread through.
    r = client.post(
        "/api/auth/magic-link",
        json={"email": "test@example.com", "return_to": "/device"},
    )
    assert r.status_code == 200
    assert captured["return_to"] == "/device"


def test_magic_link_sent_page_sets_honest_expectations(client_and_conn):
    client, _, _ = client_and_conn
    r = client.post(
        "/api/auth/magic-link",
        data={"email": "alice@example.com"},
    )
    assert r.status_code == 200
    body = r.text
    assert "up to a minute" in body, "expected honest delivery-time copy in magic_link_sent"


def test_verify_json_rejects_replay(client_and_conn):
    """A magic-link token that has already been redeemed must be rejected on
    a second verify, even within the 15-minute signature window."""
    client, _, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")

    r1 = client.post("/api/auth/verify", json={"token": token})
    assert r1.status_code == 200, r1.text

    r2 = client.post("/api/auth/verify", json={"token": token})
    assert r2.status_code == 400, r2.text
    # Replay must not be distinguishable from "expired/invalid" to the caller.
    body = r2.text.lower()
    assert "already used" not in body, "replay state must not leak in JSON response"


def test_verify_get_rejects_replay(client_and_conn):
    """The browser /verify GET path must also enforce single-use."""
    client, _, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")

    r1 = client.get(f"/verify?token={token}", follow_redirects=False)
    # First use: 200 (verify_sent_tpl) or 303 (return_to redirect). Either way, not 400.
    assert r1.status_code in (200, 303), r1.text

    r2 = client.get(f"/verify?token={token}", follow_redirects=False)
    assert r2.status_code == 400, r2.text
    # Generic wording — must not echo "already used".
    body = r2.text.lower()
    assert "expired" in body or "invalid" in body
    assert "already used" not in body


def test_verify_json_sets_session_cookie_samesite_strict(client_and_conn):
    """P1-A: session cookie issued by /api/auth/verify must be SameSite=Strict."""
    client, _, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    r = client.post("/api/auth/verify", json={"token": token})
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    assert "samesite=strict" in set_cookie.lower()
    assert "samesite=lax" not in set_cookie.lower()


def test_verify_get_sets_session_cookie_samesite_strict(client_and_conn):
    """P1-A: session cookie issued by /verify GET (link click) must be SameSite=Strict.

    With Strict, magic-link clicks from email still work because /verify
    issues a *fresh* session cookie on success — no pre-existing session is
    needed for the GET to function.
    """
    client, _, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    r = client.get(f"/verify?token={token}", follow_redirects=False)
    assert r.status_code in (200, 303)
    set_cookie = r.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    assert "samesite=strict" in set_cookie.lower()
    assert "samesite=lax" not in set_cookie.lower()


def test_magic_link_click_creates_authenticated_session(client_and_conn):
    """P1-A regression: even with Strict, GET /verify?token=... fully
    authenticates the user — subsequent same-origin requests carry the
    session cookie."""
    client, _, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    r = client.get(f"/verify?token={token}", follow_redirects=False)
    assert r.status_code in (200, 303)
    # Same-origin request after sign-in: /api/me should return 200
    r2 = client.get("/api/me")
    assert r2.status_code == 200


# ---------------------------------------------------------------------------
# Server-side session revocation (markland-bul)
# ---------------------------------------------------------------------------


def test_logout_invalidates_outstanding_cookie(client_and_conn):
    """A signed-in user logs out; the previously issued cookie no longer
    works on a subsequent request from a different tab."""
    from markland.service.sessions import issue_session
    from markland.service.users import upsert_user_by_email

    client, conn, _ = client_and_conn
    user = upsert_user_by_email(conn, "alice@test")
    cookie_value = issue_session(user.id, secret="test-secret", conn=conn)

    # Cookie works pre-logout.
    r = client.get(
        "/api/me", cookies={SESSION_COOKIE_NAME: cookie_value}
    )
    assert r.status_code == 200

    # Logout bumps the user's epoch — even attacker-with-stolen-cookie hits this.
    r = client.post(
        "/api/auth/logout",
        cookies={SESSION_COOKIE_NAME: cookie_value},
        follow_redirects=False,
    )
    assert r.status_code in (200, 303)

    # Old cookie no longer works.
    r = client.get(
        "/api/me", cookies={SESSION_COOKIE_NAME: cookie_value}
    )
    assert r.status_code == 401


def test_new_cookie_after_logout_carries_current_epoch(client_and_conn):
    """Sign in (epoch 0). Logout (bump to 1). Sign in again — new cookie works.

    Proves the issuance side reads the bumped epoch; without that, every
    post-logout sign-in would be born stale.
    """
    from markland.service.sessions import issue_session
    from markland.service.users import upsert_user_by_email

    client, conn, _ = client_and_conn
    user = upsert_user_by_email(conn, "bob@test")
    cookie1 = issue_session(user.id, secret="test-secret", conn=conn)

    client.post(
        "/api/auth/logout",
        cookies={SESSION_COOKIE_NAME: cookie1},
        follow_redirects=False,
    )

    cookie2 = issue_session(user.id, secret="test-secret", conn=conn)

    r = client.get("/api/me", cookies={SESSION_COOKIE_NAME: cookie1})
    assert r.status_code == 401
    r = client.get("/api/me", cookies={SESSION_COOKIE_NAME: cookie2})
    assert r.status_code == 200


def test_logout_with_invalid_cookie_does_not_crash(client_and_conn):
    """Tampered/expired/garbage cookie on logout: the bump is skipped
    silently. No 500."""
    client, _, _ = client_and_conn
    r = client.post(
        "/api/auth/logout",
        cookies={SESSION_COOKIE_NAME: "garbage"},
        follow_redirects=False,
    )
    assert r.status_code in (200, 303)


def test_verify_endpoint_issues_cookie_with_current_epoch(client_and_conn):
    """End-to-end: magic-link verify embeds the user's current epoch so
    a sign-in after a prior logout produces a valid cookie."""
    from markland.service.sessions import bump_session_epoch
    from markland.service.users import upsert_user_by_email

    client, conn, _ = client_and_conn
    # Pre-existing user with epoch already bumped (simulates "logged out before").
    user = upsert_user_by_email(conn, "carol@test")
    bump_session_epoch(conn, user_id=user.id)
    bump_session_epoch(conn, user_id=user.id)  # epoch = 2

    token = issue_magic_link_token("carol@test", secret="test-secret")
    r = client.post("/api/auth/verify", json={"token": token})
    assert r.status_code == 200

    # The cookie issued by /verify must work.
    r = client.get("/api/me")
    assert r.status_code == 200


def test_security_page_renders_single_use_wording(client_and_conn):
    """Regression: post single-use enforcement, /security must claim
    'single-use' and must NOT carry the old 'captured link can be used'
    caveat."""
    client, _, _ = client_and_conn
    r = client.get("/security")
    assert r.status_code == 200
    body_lower = r.text.lower()
    assert "single-use" in body_lower
    assert "captured link can be used" not in body_lower
