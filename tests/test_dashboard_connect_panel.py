"""Connect Claude Code dashboard panel — visibility logic.

The panel renders iff: signed in AND no authorized device AND no dismiss
cookie. Three negatives (anonymous / authorized / dismissed) and one
positive — four cases.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import device_flow
from markland.service import sessions as sessions_mod
from markland.service.users import create_user
from markland.web.app import create_app

SECRET = "test-session-secret"
PANEL_MARKER = 'aria-label="Connect Claude Code"'


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


def test_panel_absent_when_anonymous(client):
    r = client.get("/dashboard")
    # Anonymous returns 401 today; even if that changed, the panel must not
    # leak into an anonymous response.
    assert PANEL_MARKER not in r.text


def test_panel_present_when_signed_in_with_no_authorized_device(client):
    _login(client)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert PANEL_MARKER in r.text


def test_panel_absent_when_signed_in_with_authorized_device(client):
    _login(client)
    start = device_flow.start(client.state_conn, base_url="https://markland.dev")
    device_flow.authorize(client.state_conn, start.user_code, user_id=client.state_alice_id)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert PANEL_MARKER not in r.text


def test_panel_absent_when_dismiss_cookie_set(client):
    _login(client)
    client.cookies.set("mk_dismiss_connect", "1")
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert PANEL_MARKER not in r.text
