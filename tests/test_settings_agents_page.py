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


def test_settings_agents_token_create_surfaces_plaintext(client):
    c, conn = client
    a = agents_svc.create_agent(conn, "usr_alice", "scribe")
    r = c.post(
        f"/settings/agents/{a.id}/tokens/create",
        data={"label": "laptop"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    loc = r.headers["location"]
    assert loc.startswith("/settings/agents?new_token=mk_agt_")
