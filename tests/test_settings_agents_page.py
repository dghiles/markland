"""Smoke tests for /settings/agents HTML page."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import agents as agents_svc
from markland.service.sessions import SESSION_COOKIE_NAME, issue_session
from markland.web.app import create_app


SECRET = "test-session-secret"


@pytest.fixture
def client(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users(id, email, display_name, is_admin, created_at) "
        "VALUES (?, ?, ?, 0, ?)",
        ("usr_alice", "alice@x", "Alice", "2026-04-19T00:00:00+00:00"),
    )
    conn.commit()
    app = create_app(conn, mount_mcp=False, session_secret=SECRET)
    with TestClient(app) as c:
        c.cookies.set(
            SESSION_COOKIE_NAME, issue_session("usr_alice", secret=SECRET)
        )
        yield c, conn


def test_settings_agents_requires_login(tmp_path):
    conn = init_db(tmp_path / "t2.db")
    app = create_app(conn, mount_mcp=False, session_secret=SECRET)
    with TestClient(app) as c:
        r = c.get("/settings/agents", follow_redirects=False)
        assert r.status_code in (302, 303, 401)


def test_settings_agents_renders(client):
    c, conn = client
    agents_svc.create_agent(conn, "usr_alice", "scribe")
    r = c.get("/settings/agents")
    assert r.status_code == 200
    assert "scribe" in r.text
    assert "Create agent" in r.text or "New agent" in r.text


def test_settings_agents_create_via_form(client):
    c, conn = client
    r = c.post(
        "/settings/agents/create",
        data={"display_name": "web-scribe"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    agents = agents_svc.list_agents(conn, owner_user_id="usr_alice")
    assert any(a.display_name == "web-scribe" for a in agents)


def test_settings_agents_token_create_redirects_without_query_string(client):
    c, conn = client
    a = agents_svc.create_agent(conn, "usr_alice", "scribe")
    r = c.post(
        f"/settings/agents/{a.id}/tokens/create",
        data={"label": "laptop"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    loc = r.headers["location"]
    assert loc == "/settings/agents", loc
    assert "new_token" not in loc
    assert "mk_agt_" not in loc


def test_settings_agents_token_create_sets_signed_flash_cookie(client):
    from markland.service.agent_token_flash import (
        AGENT_TOKEN_FLASH_COOKIE_NAME,
        read_agent_token_flash,
    )

    c, conn = client
    a = agents_svc.create_agent(conn, "usr_alice", "scribe")
    r = c.post(
        f"/settings/agents/{a.id}/tokens/create",
        data={"label": "laptop"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    set_cookie = r.headers.get("set-cookie", "")
    assert AGENT_TOKEN_FLASH_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()

    cookie_value = r.cookies.get(AGENT_TOKEN_FLASH_COOKIE_NAME)
    assert cookie_value, "flash cookie should be set on the redirect response"
    plaintext = read_agent_token_flash(cookie_value, secret=SECRET)
    assert plaintext.startswith("mk_agt_")


def test_settings_agents_renders_flash_token_once_then_clears(client):
    from markland.service.agent_token_flash import AGENT_TOKEN_FLASH_COOKIE_NAME

    c, conn = client
    a = agents_svc.create_agent(conn, "usr_alice", "scribe")
    r = c.post(
        f"/settings/agents/{a.id}/tokens/create",
        data={"label": "laptop"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    flash_cookie = c.cookies.get(AGENT_TOKEN_FLASH_COOKIE_NAME)
    assert flash_cookie

    r1 = c.get("/settings/agents")
    assert r1.status_code == 200
    assert "mk_agt_" in r1.text
    set_cookie = r1.headers.get("set-cookie", "")
    assert AGENT_TOKEN_FLASH_COOKIE_NAME in set_cookie
    assert (
        "Max-Age=0" in set_cookie
        or '=""' in set_cookie
        or f"{AGENT_TOKEN_FLASH_COOKIE_NAME}=;" in set_cookie
    )

    r2 = c.get("/settings/agents")
    assert r2.status_code == 200
    assert "mk_agt_" not in r2.text


def test_settings_agents_ignores_query_string_new_token(client):
    """Defence-in-depth: a stale bookmarked link with ?new_token=... must NOT echo."""
    c, _ = client
    r = c.get("/settings/agents?new_token=mk_agt_should_not_render")
    assert r.status_code == 200
    assert "mk_agt_should_not_render" not in r.text


def test_settings_agents_revoke_uses_data_attribute_not_inline_js(client):
    """Adversarial display_name with apostrophes must not break out of JS.

    Previously the revoke form used onsubmit="return confirm('Revoke agent
    {{ a.display_name }}?...')" which is XSS-vulnerable. The fix moves the
    name to a data-* attribute (autoescaped by Jinja) and reads it from a
    JS handler at the bottom of the page.
    """
    c, conn = client
    payload = "x'); alert('pwn');//"
    agents_svc.create_agent(conn, "usr_alice", payload)
    r = c.get("/settings/agents")
    assert r.status_code == 200
    body = r.text
    # No inline confirm() with a quote-escaped name (the legacy unsafe form).
    assert "onsubmit=" not in body
    assert "alert('pwn')" not in body
    assert "alert(\"pwn\")" not in body
    # Name is rendered (HTML-escaped) inside the data-* attribute.
    assert "data-display-name=" in body
    # The single quote should be HTML-entity-encoded by Jinja autoescape.
    assert "&#39;" in body or "&apos;" in body or "&#x27;" in body
