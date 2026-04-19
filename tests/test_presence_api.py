"""HTTP API tests for /api/docs/{id}/presence."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.auth import Principal
from markland.web.app import create_app


def _seed(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO documents (id, title, content, share_token, created_at, updated_at, is_public, is_featured, owner_id, version)
        VALUES ('doc_1', 'T', 'C', 'tok_1', '2026-04-19T00:00:00', '2026-04-19T00:00:00', 0, 0, 'usr_alice', 1)
        """
    )
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'a@x', 'Alice', 0, '2026-04-19T00:00:00')"
    )
    conn.commit()


def _principal(user_id: str, display: str | None = None) -> Principal:
    return Principal(
        principal_id=user_id,
        principal_type="user",
        display_name=display,
        is_admin=False,
        user_id=user_id,
    )


@pytest.fixture
def client(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed(conn)
    alice = _principal("usr_alice", "Alice")
    app = create_app(
        conn,
        mount_mcp=False,
        base_url="https://markland.test",
        session_secret="test",
        test_principal_by_token={"alice": alice},
    )
    with TestClient(app) as c:
        yield c


def test_post_presence_creates_row(client):
    r = client.post(
        "/api/docs/doc_1/presence",
        headers={"Authorization": "Bearer alice"},
        json={"status": "editing", "note": "intro"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["doc_id"] == "doc_1"
    assert body["status"] == "editing"
    assert "expires_at" in body


def test_post_presence_without_note(client):
    r = client.post(
        "/api/docs/doc_1/presence",
        headers={"Authorization": "Bearer alice"},
        json={"status": "reading"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "reading"


def test_post_presence_rejects_invalid_status(client):
    r = client.post(
        "/api/docs/doc_1/presence",
        headers={"Authorization": "Bearer alice"},
        json={"status": "done"},
    )
    assert r.status_code == 400


def test_get_presence_lists_active(client):
    client.post(
        "/api/docs/doc_1/presence",
        headers={"Authorization": "Bearer alice"},
        json={"status": "editing", "note": "x"},
    )
    r = client.get(
        "/api/docs/doc_1/presence",
        headers={"Authorization": "Bearer alice"},
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["principal_id"] == "usr_alice"
    assert body[0]["status"] == "editing"
    assert body[0]["display_name"] == "Alice"


def test_delete_presence_clears_row(client):
    client.post(
        "/api/docs/doc_1/presence",
        headers={"Authorization": "Bearer alice"},
        json={"status": "reading"},
    )
    r = client.delete(
        "/api/docs/doc_1/presence",
        headers={"Authorization": "Bearer alice"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    r2 = client.get(
        "/api/docs/doc_1/presence",
        headers={"Authorization": "Bearer alice"},
    )
    assert r2.json() == []


def test_presence_endpoints_require_auth(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed(conn)
    app = create_app(
        conn,
        mount_mcp=False,
        base_url="https://markland.test",
        session_secret="test",
        test_principal_by_token={"alice": _principal("usr_alice", "Alice")},
    )
    with TestClient(app) as c:
        r = c.post("/api/docs/doc_1/presence", json={"status": "editing"})
        assert r.status_code == 401
        r = c.delete("/api/docs/doc_1/presence")
        assert r.status_code == 401
        r = c.get("/api/docs/doc_1/presence")
        assert r.status_code == 401


def test_presence_endpoints_404_on_missing_doc(client):
    r = client.post(
        "/api/docs/doc_MISSING/presence",
        headers={"Authorization": "Bearer alice"},
        json={"status": "editing"},
    )
    assert r.status_code == 404
