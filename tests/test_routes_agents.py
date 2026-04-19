"""HTTP tests for /api/agents and /api/agents/{id}/tokens."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.sessions import SESSION_COOKIE_NAME, issue_session
from markland.web.app import create_app


SECRET = "test-session-secret"


def _session_cookie_for(user_id: str) -> str:
    return issue_session(user_id, secret=SECRET)


@pytest.fixture
def client(tmp_path):
    conn = init_db(tmp_path / "t.db")
    for uid, email in [("usr_alice", "alice@x"), ("usr_bob", "bob@x")]:
        conn.execute(
            "INSERT INTO users(id, email, display_name, is_admin, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (uid, email, uid, "2026-04-19T00:00:00+00:00"),
        )
    conn.commit()
    app = create_app(conn, mount_mcp=False, session_secret=SECRET)
    with TestClient(app) as c:
        c.cookies.set(SESSION_COOKIE_NAME, _session_cookie_for("usr_alice"))
        yield c


def test_post_api_agents_creates_agent(client):
    r = client.post("/api/agents", json={"display_name": "scribe"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["display_name"] == "scribe"
    assert body["id"].startswith("agt_")


def test_post_api_agents_rejects_empty_name(client):
    r = client.post("/api/agents", json={"display_name": "  "})
    # pydantic Field(min_length=1) after strip isn't enforced — our service
    # raises ValueError("display_name_required") → 400. But pydantic rejects
    # whitespace-only only if min_length counts raw chars. Two spaces pass
    # min_length=1; server then raises 400.
    assert r.status_code == 400


def test_get_api_agents_lists_session_user_agents(client):
    client.post("/api/agents", json={"display_name": "a1"})
    client.post("/api/agents", json={"display_name": "a2"})
    r = client.get("/api/agents")
    assert r.status_code == 200
    names = [a["display_name"] for a in r.json()]
    assert set(names) == {"a1", "a2"}


def test_delete_api_agents_revokes_agent(client):
    r = client.post("/api/agents", json={"display_name": "scribe"})
    agent_id = r.json()["id"]
    d = client.delete(f"/api/agents/{agent_id}")
    assert d.status_code == 204
    assert client.get("/api/agents").json() == []


def test_delete_other_users_agent_rejected(client):
    r = client.post("/api/agents", json={"display_name": "scribe"})
    agent_id = r.json()["id"]
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, _session_cookie_for("usr_bob"))
    d = client.delete(f"/api/agents/{agent_id}")
    assert d.status_code in (403, 404)


def test_post_api_agent_token_returns_plaintext_once(client):
    r = client.post("/api/agents", json={"display_name": "scribe"})
    agent_id = r.json()["id"]
    t = client.post(f"/api/agents/{agent_id}/tokens", json={"label": "laptop"})
    assert t.status_code == 201
    body = t.json()
    assert body["plaintext"].startswith("mk_agt_")
    assert body["id"].startswith("tok_")
    assert body["label"] == "laptop"


def test_delete_api_agent_token_revokes(client):
    r = client.post("/api/agents", json={"display_name": "scribe"})
    agent_id = r.json()["id"]
    t = client.post(f"/api/agents/{agent_id}/tokens", json={"label": "x"})
    tok_id = t.json()["id"]
    d = client.delete(f"/api/agents/{agent_id}/tokens/{tok_id}")
    assert d.status_code == 204


def test_unauthenticated_returns_401(tmp_path):
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, session_secret=SECRET)
    with TestClient(app) as c:
        r = c.get("/api/agents")
        assert r.status_code == 401
