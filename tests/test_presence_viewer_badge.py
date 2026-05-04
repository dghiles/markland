"""The /d/{share_token} page shows a small badge when principals are active.

P1-E / markland-7e1: anonymous viewers see "Someone" placeholders only;
signed-in viewers see real display_name + note.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import presence
from markland.service.sessions import SESSION_COOKIE_NAME, issue_session
from markland.web.app import create_app


def _seed(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO documents (id, title, content, share_token, created_at, updated_at, is_public, is_featured, version)
        VALUES ('doc_1', 'Hello', '# hi', 'tok_share_1', '2026-04-19T00:00:00', '2026-04-19T00:00:00', 1, 0, 1)
        """
    )
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'a@x', 'Alice', 0, '2026-04-19T00:00:00')"
    )
    conn.commit()


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "t.db")
    _seed(c)
    yield c
    c.close()


def test_no_badge_when_no_active_principals(conn):
    app = create_app(conn, session_secret="test")
    with TestClient(app) as client:
        r = client.get("/d/tok_share_1")
    assert r.status_code == 200
    assert "data-presence-badge" not in r.text


def _signed_in_client(app, user_id: str, secret: str) -> TestClient:
    cookie = issue_session(user_id, secret=secret)
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, cookie)
    return client


def test_badge_rendered_with_display_name_and_status_for_signed_in(conn):
    """Signed-in viewers see the real display_name + status."""
    presence.set_status(
        conn,
        doc_id="doc_1",
        principal=SimpleNamespace(
            principal_id="usr_alice", principal_type="user"
        ),
        status="editing",
        note=None,
        now=datetime.utcnow(),
    )
    app = create_app(conn, session_secret="test")
    client = _signed_in_client(app, "usr_alice", "test")
    r = client.get("/d/tok_share_1")
    assert r.status_code == 200
    assert "data-presence-badge" in r.text
    assert "Alice" in r.text
    assert "editing" in r.text


def test_badge_handles_multiple_principals_for_signed_in(conn):
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_bob', 'b@x', 'Bob', 0, '2026-04-19T00:00:00')"
    )
    conn.commit()
    now = datetime.utcnow()
    presence.set_status(
        conn,
        doc_id="doc_1",
        principal=SimpleNamespace(
            principal_id="usr_alice", principal_type="user"
        ),
        status="editing",
        note=None,
        now=now,
    )
    presence.set_status(
        conn,
        doc_id="doc_1",
        principal=SimpleNamespace(
            principal_id="usr_bob", principal_type="user"
        ),
        status="reading",
        note=None,
        now=now,
    )
    app = create_app(conn, session_secret="test")
    client = _signed_in_client(app, "usr_alice", "test")
    r = client.get("/d/tok_share_1")
    assert "Alice" in r.text
    assert "Bob" in r.text


def test_anonymous_viewer_does_not_see_presence_identity(conn):
    """P1-E / markland-7e1: an anonymous (no session) viewer of a public
    doc must NOT see other viewers' identity. Public-doc presence still
    surfaces the count + status, but display_name + principal_id + note
    are stripped to 'Someone' / None / ''."""
    presence.set_status(
        conn,
        doc_id="doc_1",
        principal=SimpleNamespace(
            principal_id="usr_alice", principal_type="user"
        ),
        status="editing",
        note="working on the conclusion",
        now=datetime.utcnow(),
    )
    app = create_app(conn, session_secret="test")
    with TestClient(app) as client:
        r = client.get("/d/tok_share_1")
    assert r.status_code == 200
    # Identity must NOT leak.
    assert "Alice" not in r.text
    assert "usr_alice" not in r.text
    assert "working on the conclusion" not in r.text
    # But the badge still renders with a generic placeholder + status.
    assert "data-presence-badge" in r.text
    assert "Someone" in r.text
    assert "editing" in r.text
