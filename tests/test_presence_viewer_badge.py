"""The /d/{share_token} page shows a small badge when principals are active."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import presence
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


def test_badge_rendered_with_display_name_and_status(conn):
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
    with TestClient(app) as client:
        r = client.get("/d/tok_share_1")
    assert r.status_code == 200
    assert "data-presence-badge" in r.text
    assert "Alice" in r.text
    assert "editing" in r.text


def test_badge_handles_multiple_principals(conn):
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
    with TestClient(app) as client:
        r = client.get("/d/tok_share_1")
    assert "Alice" in r.text
    assert "Bob" in r.text
