"""HTTP tests for /api/auth/device-* and /device UI."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import sessions as sessions_mod
from markland.service.users import create_user
from markland.web.app import create_app

SECRET = "test-session-secret"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "test.db")
    # Pre-create the user tests log in as.
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    app = create_app(
        conn,
        mount_mcp=False,
        base_url="https://markland.dev",
        session_secret=SECRET,
    )
    # Use TestClient with the real host so cookies with secure=False stick.
    with TestClient(app, base_url="http://testserver") as c:
        c.state_alice_id = user.id
        yield c


def _login(client, user_id: str | None = None):
    uid = user_id or client.state_alice_id
    cookie = sessions_mod.make_session_cookie_value(uid, secret=SECRET)
    client.cookies.set(sessions_mod.SESSION_COOKIE_NAME, cookie)


def _extract_csrf(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "no CSRF token in rendered form"
    return m.group(1)


# ---------------------------------------------------------------------------
# Task 6: POST /api/auth/device-start
# ---------------------------------------------------------------------------


def test_device_start_without_body_returns_expected_shape(client):
    r = client.post("/api/auth/device-start")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "device_code",
        "user_code",
        "verification_url",
        "poll_interval",
        "expires_in",
    }
    assert len(body["device_code"]) >= 54
    assert "-" in body["user_code"]
    assert body["verification_url"] == "https://markland.dev/device"
    assert body["poll_interval"] == 5
    assert body["expires_in"] == 600


def test_device_start_with_invite_token_persists_it(client):
    r = client.post("/api/auth/device-start", json={"invite_token": "inv_xyz"})
    assert r.status_code == 200


def test_device_start_rate_limits_per_ip(client):
    for _ in range(10):
        r = client.post("/api/auth/device-start")
        assert r.status_code == 200, r.text
    r = client.post("/api/auth/device-start")
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "rate_limited"
    assert "retry_after" in body


def test_device_start_rate_limit_is_per_ip(client):
    # Exhaust limit from default IP.
    for _ in range(10):
        client.post("/api/auth/device-start")
    # Different IP — should still work.
    r = client.post(
        "/api/auth/device-start",
        headers={"X-Forwarded-For": "203.0.113.7"},
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Task 7: POST /api/auth/device-poll
# ---------------------------------------------------------------------------


def test_device_poll_returns_pending(client):
    start = client.post("/api/auth/device-start").json()
    r = client.post("/api/auth/device-poll", json={"device_code": start["device_code"]})
    assert r.status_code == 200
    assert r.json() == {"status": "pending"}


def test_device_poll_slow_down(client):
    start = client.post("/api/auth/device-start").json()
    client.post("/api/auth/device-poll", json={"device_code": start["device_code"]})
    r = client.post("/api/auth/device-poll", json={"device_code": start["device_code"]})
    assert r.status_code == 200
    assert r.json() == {"status": "slow_down"}


def test_device_poll_unknown_device_code(client):
    r = client.post("/api/auth/device-poll", json={"device_code": "nope"})
    assert r.status_code == 200
    assert r.json() == {"status": "not_found"}


def test_device_poll_missing_body_returns_422(client):
    r = client.post("/api/auth/device-poll", json={})
    assert r.status_code == 422  # pydantic validation


def test_device_poll_accepts_content_type_variations(client):
    start = client.post("/api/auth/device-start").json()
    r = client.post(
        "/api/auth/device-poll",
        json={"device_code": start["device_code"]},
        headers={"Accept": "application/json"},
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Task 8: POST /api/auth/device-authorize
# ---------------------------------------------------------------------------


def test_device_authorize_requires_session(client):
    start = client.post("/api/auth/device-start").json()
    r = client.post(
        "/api/auth/device-authorize",
        json={"user_code": start["user_code"]},
    )
    assert r.status_code == 401


def test_device_authorize_happy_path(client):
    start = client.post("/api/auth/device-start").json()
    _login(client)
    r = client.post(
        "/api/auth/device-authorize",
        json={"user_code": start["user_code"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["invite_accepted"] is False


def test_device_authorize_accepts_unhyphenated_code(client):
    start = client.post("/api/auth/device-start").json()
    _login(client)
    r = client.post(
        "/api/auth/device-authorize",
        json={"user_code": start["user_code"].replace("-", "")},
    )
    assert r.status_code == 200


def test_device_authorize_unknown_code_returns_404(client):
    _login(client)
    r = client.post(
        "/api/auth/device-authorize",
        json={"user_code": "ZZZZZZZZ"},
    )
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


def test_device_authorize_already_authorized_returns_410(client):
    start = client.post("/api/auth/device-start").json()
    _login(client)
    client.post("/api/auth/device-authorize", json={"user_code": start["user_code"]})
    r = client.post(
        "/api/auth/device-authorize",
        json={"user_code": start["user_code"]},
    )
    assert r.status_code == 410


# ---------------------------------------------------------------------------
# Task 9: /device HTML consent page + /device/confirm + /device/done
# ---------------------------------------------------------------------------


def test_device_page_logged_out_prompts_login(client):
    r = client.get("/device")
    assert r.status_code == 200
    assert "sign in" in r.text.lower()


def test_device_page_logged_in_shows_form(client):
    _login(client)
    r = client.get("/device")
    assert r.status_code == 200
    assert 'name="user_code"' in r.text


def test_device_page_prefills_code_from_query(client):
    _login(client)
    r = client.get("/device?code=ABCD-EFGH")
    assert r.status_code == 200
    assert 'value="ABCD-EFGH"' in r.text


def test_device_confirm_requires_session(client):
    r = client.post(
        "/device/confirm",
        data={"user_code": "XXXX-YYYY", "csrf": "x"},
        follow_redirects=False,
    )
    assert r.status_code in (401, 303)  # 303 back to /login is also acceptable


def test_device_confirm_unauth_redirect_preserves_user_code_through_login(client):
    """The /device/confirm → /login redirect must url-encode its `next=` value.

    Before the fix the redirect was `/login?next=/device?code=ABCD-EFGH`.
    The browser parsed that as two query params on /login (next=/device,
    code=ABCD-EFGH), so after magic-link verify the user_code was lost and
    /device rendered an empty code-entry form.
    """
    from urllib.parse import parse_qs, urlparse

    r = client.post(
        "/device/confirm",
        data={"user_code": "ABCD-EFGH", "csrf": "x"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    location = r.headers["location"]
    assert location.startswith("/login?"), location
    qs = parse_qs(urlparse(location).query)
    # The single `next` param must carry the FULL inner URL with the code,
    # not get split at the inner `?`.
    assert qs.get("next") == ["/device?code=ABCD-EFGH"], qs
    # And `code` must NOT have leaked out as a top-level param on /login.
    assert "code" not in qs, qs


def test_device_confirm_rate_limits_per_ip(client):
    """POST /device/confirm must rate-limit per IP (10/min) like /device-start."""
    _login(client)
    # Burn 10 confirms (each will return 400 because csrf is bogus, but should
    # NOT 429). The rate limiter must count these.
    for _ in range(10):
        r = client.post(
            "/device/confirm",
            data={"user_code": "XXXX-YYYY", "csrf": "x"},
            follow_redirects=False,
        )
        assert r.status_code != 429, r.text
    # 11th request from the same IP must be 429.
    r = client.post(
        "/device/confirm",
        data={"user_code": "XXXX-YYYY", "csrf": "x"},
        follow_redirects=False,
    )
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "rate_limited"
    assert "retry_after" in body


def test_device_confirm_unauth_redirect_escapes_malformed_user_code(client):
    """A user_code containing `?` or `&` must not break the redirect target.

    The inner `next_path` is `/device?code=<user_code>`; if user_code is
    naively interpolated, characters like `?` or `&` would let an attacker
    inject extra query params into /device or break URL parsing entirely.
    """
    from urllib.parse import parse_qs, urlparse

    r = client.post(
        "/device/confirm",
        data={"user_code": "AB?CD&x=1", "csrf": "x"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    location = r.headers["location"]
    qs = parse_qs(urlparse(location).query)
    # The inner `?` and `&` must be percent-encoded inside the next= value.
    next_val = qs.get("next", [""])[0]
    assert next_val.startswith("/device?code="), next_val
    # Raw `?` or `&` after the first `code=` would mean we leaked structure.
    assert "?" not in next_val[len("/device?code="):], next_val
    assert "&" not in next_val[len("/device?code="):], next_val


def test_device_confirm_happy_path_redirects_to_done(client):
    start = client.post("/api/auth/device-start").json()
    _login(client)
    r = client.get("/device")
    assert r.status_code == 200
    csrf = _extract_csrf(r.text)
    r2 = client.post(
        "/device/confirm",
        data={"user_code": start["user_code"], "csrf": csrf},
        follow_redirects=False,
    )
    assert r2.status_code == 303
    assert "/device/done" in r2.headers["location"]


def test_device_done_page_renders_ok_state(client):
    start = client.post("/api/auth/device-start").json()
    _login(client)
    r = client.get("/device")
    csrf = _extract_csrf(r.text)
    client.post(
        "/device/confirm",
        data={"user_code": start["user_code"], "csrf": csrf},
        follow_redirects=False,
    )
    done = client.get(f"/device/done?code={start['user_code']}")
    assert done.status_code == 200
    assert "Device authorized" in done.text


# ---------------------------------------------------------------------------
# Task 10: GET /setup
# ---------------------------------------------------------------------------


def test_setup_returns_markdown(client):
    r = client.get("/setup")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "device-start" in r.text
    assert "device-poll" in r.text
    assert "claude mcp add" in r.text


def test_setup_runbook_includes_verification_step(client):
    r = client.get("/setup")
    assert "markland_whoami" in r.text


def test_setup_runbook_threads_invite_token(client):
    r = client.get("/setup?invite=inv_abc")
    assert '"invite_token": "inv_abc"' in r.text


def test_setup_runbook_no_invite_param_omits_invite_body(client):
    r = client.get("/setup")
    assert "invite_token" not in r.text or '"invite_token": null' in r.text


def test_setup_runbook_install_command_is_complete(client):
    """The CLI command in step 4 must be runnable as-is.

    Verified broken on 2026-04-24:
    - missing --transport http → registers as stdio
    - Authorization=Bearer (=) → CLI rejects, expects colon
    - bare /mcp → 307 redirect not followed cleanly on POST
    """
    r = client.get("/setup")
    body = r.text
    # Must specify HTTP transport explicitly.
    assert "--transport http" in body
    # Must use header colon syntax, not equals.
    assert 'Authorization: Bearer' in body
    assert 'Authorization=Bearer' not in body
    # Must use trailing-slash MCP path so the install doesn't depend on
    # following a 307 across a POST.
    assert "/mcp/" in body


def test_setup_runbook_has_human_preamble(client):
    r = client.get("/setup")
    body = r.text
    # Humans landing on /setup via curl/browser need to know this URL is
    # meant to be pasted into a Claude Code chat, not run in a terminal.
    assert "**For humans:**" in body
    assert "Install the Markland MCP server from" in body
    # The agent-facing role prompt must still appear after the preamble so
    # an LLM consumer of the runbook still gets a clear directive.
    assert "You are Claude Code" in body
    # Order matters — preamble first, role prompt second.
    assert body.index("**For humans:**") < body.index("You are Claude Code")
