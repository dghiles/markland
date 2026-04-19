"""Integration: set_status / clear_status MCP tools round-trip through the DB."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from markland.db import init_db
from markland.server import build_mcp
from markland.service.auth import Principal


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
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_bob', 'b@x', 'Bob', 0, '2026-04-19T00:00:00')"
    )
    # Grant Bob view access so he can see the doc.
    conn.execute(
        "INSERT INTO grants (doc_id, principal_id, principal_type, level, granted_by, granted_at) "
        "VALUES ('doc_1', 'usr_bob', 'user', 'view', 'usr_alice', '2026-04-19T00:00:00')"
    )
    conn.commit()


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "t.db")
    _seed(c)
    yield c
    c.close()


def _principal(user_id: str, display: str | None = None) -> Principal:
    return Principal(
        principal_id=user_id,
        principal_type="user",
        display_name=display,
        is_admin=False,
        user_id=user_id,
    )


def _ctx(principal: Principal):
    return SimpleNamespace(principal=principal)


def _call(mcp, name: str, principal: Principal, **kwargs):
    return mcp.markland_handlers[name](_ctx(principal), **kwargs)


def test_set_status_returns_doc_id_status_expires_at(conn):
    mcp = build_mcp(conn, base_url="http://localhost:8950")
    alice = _principal("usr_alice", "Alice")
    result = _call(mcp, "markland_set_status", alice,
                   doc_id="doc_1", status="editing", note="intro")
    assert result["doc_id"] == "doc_1"
    assert result["status"] == "editing"
    assert "expires_at" in result and result["expires_at"]


def test_set_status_rejects_invalid_status(conn):
    mcp = build_mcp(conn, base_url="http://localhost:8950")
    alice = _principal("usr_alice")
    with pytest.raises(ValueError):
        _call(mcp, "markland_set_status", alice,
              doc_id="doc_1", status="done", note=None)


def test_clear_status_removes_row(conn):
    mcp = build_mcp(conn, base_url="http://localhost:8950")
    alice = _principal("usr_alice")
    _call(mcp, "markland_set_status", alice,
          doc_id="doc_1", status="reading", note=None)
    out = _call(mcp, "markland_clear_status", alice, doc_id="doc_1")
    assert out == {"ok": True}
    assert conn.execute("SELECT COUNT(*) FROM presence").fetchone()[0] == 0


def test_set_status_requires_view_access(conn):
    """A principal without view access cannot set presence."""
    mcp = build_mcp(conn, base_url="http://localhost:8950")
    # usr_chuck has no grant on doc_1.
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_chuck', 'c@x', 'Chuck', 0, '2026-04-19T00:00:00')"
    )
    conn.commit()
    chuck = _principal("usr_chuck", "Chuck")
    result = _call(mcp, "markland_set_status", chuck,
                   doc_id="doc_1", status="editing", note=None)
    assert isinstance(result, dict) and result.get("error") in ("forbidden", "not_found")


def test_get_shows_two_active_principals_then_one_after_clear(conn):
    mcp = build_mcp(conn, base_url="http://localhost:8950")
    alice = _principal("usr_alice", "Alice")
    bob = _principal("usr_bob", "Bob")

    _call(mcp, "markland_set_status", alice,
          doc_id="doc_1", status="editing", note="intro")
    _call(mcp, "markland_set_status", bob,
          doc_id="doc_1", status="reading", note=None)

    result = _call(mcp, "markland_get", alice, doc_id="doc_1")
    assert "active_principals" in result
    by_id = {p["principal_id"]: p for p in result["active_principals"]}
    assert set(by_id.keys()) == {"usr_alice", "usr_bob"}
    assert by_id["usr_alice"]["status"] == "editing"
    assert by_id["usr_alice"]["display_name"] == "Alice"
    assert by_id["usr_alice"]["note"] == "intro"
    assert by_id["usr_bob"]["status"] == "reading"
    assert by_id["usr_bob"]["display_name"] == "Bob"

    _call(mcp, "markland_clear_status", alice, doc_id="doc_1")
    result2 = _call(mcp, "markland_get", alice, doc_id="doc_1")
    ids = {p["principal_id"] for p in result2["active_principals"]}
    assert ids == {"usr_bob"}


def test_get_has_empty_active_principals_when_nobody_is_active(conn):
    mcp = build_mcp(conn, base_url="http://localhost:8950")
    alice = _principal("usr_alice", "Alice")
    result = _call(mcp, "markland_get", alice, doc_id="doc_1")
    assert result.get("active_principals") == []
