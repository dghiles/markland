"""Dashboard 'first publish' welcome panel — visibility logic.

Renders iff: signed in AND no owned docs AND no mk_dismiss_welcome=1
cookie. Mirrors the _connect_claude_code panel pattern.

Plan: docs/plans/2026-05-29-pre-launch-cleanup.md Track D Task D2
(bead markland-14q).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import docs as docs_svc
from markland.service import sessions as sessions_mod
from markland.service.auth import Principal
from markland.service.users import create_user
from markland.web.app import create_app

SECRET = "test-session-secret"
PANEL_MARKER = 'aria-label="Welcome — publish your first doc"'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "test.db")
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    app = create_app(
        conn, mount_mcp=False,
        base_url="https://markland.dev",
        session_secret=SECRET,
    )
    with TestClient(app, base_url="http://testserver") as c:
        c.state_alice_id = user.id
        c.state_conn = conn
        yield c


def _login(client, user_id=None):
    uid = user_id or client.state_alice_id
    cookie = sessions_mod.make_session_cookie_value(uid, secret=SECRET)
    client.cookies.set(sessions_mod.SESSION_COOKIE_NAME, cookie)


def test_panel_absent_for_anon(client):
    r = client.get("/dashboard")
    assert PANEL_MARKER not in r.text


def test_panel_present_for_signed_in_with_no_docs(client):
    _login(client)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert PANEL_MARKER in r.text


def test_panel_absent_when_user_has_owned_docs(client):
    _login(client)
    alice = Principal(
        principal_id=client.state_alice_id,
        principal_type="user",
        display_name="Alice",
        is_admin=False,
        user_id=client.state_alice_id,
    )
    docs_svc.publish(
        client.state_conn, "https://markland.dev", alice,
        "body", title="T", public=False,
    )
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert PANEL_MARKER not in r.text


def test_panel_absent_when_dismiss_cookie_set(client):
    _login(client)
    client.cookies.set("mk_dismiss_welcome", "1")
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert PANEL_MARKER not in r.text
