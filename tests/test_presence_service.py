"""Unit tests for service.presence.

Time-dependent behavior is tested by passing explicit `now` values to the
service functions — no freezegun or time-travel mocking required.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from markland.db import init_db
from markland.service import presence


@dataclass
class _P:
    """Minimal principal stub matching the shape service/presence.py expects."""

    principal_id: str
    principal_type: str  # 'user' | 'agent'


def _seed_doc(conn: sqlite3.Connection, doc_id: str = "doc_1") -> None:
    conn.execute(
        """
        INSERT INTO documents (id, title, content, share_token, created_at, updated_at, is_public, is_featured, version)
        VALUES (?, ?, ?, ?, ?, ?, 0, 0, 1)
        """,
        (doc_id, "T", "C", f"tok_{doc_id}", "2026-04-19T00:00:00", "2026-04-19T00:00:00"),
    )
    conn.commit()


def _seed_user(conn: sqlite3.Connection, user_id: str = "usr_alice", display: str = "Alice") -> None:
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) VALUES (?, ?, ?, 0, ?)",
        (user_id, f"{user_id}@example.com", display, "2026-04-19T00:00:00"),
    )
    conn.commit()


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "t.db")
    _seed_doc(c)
    _seed_user(c)
    yield c
    c.close()


def _fetch_presence_row(conn, doc_id, principal_id):
    return conn.execute(
        "SELECT doc_id, principal_id, principal_type, status, note, updated_at, expires_at "
        "FROM presence WHERE doc_id=? AND principal_id=?",
        (doc_id, principal_id),
    ).fetchone()


def test_set_status_inserts_row(conn):
    now = datetime(2026, 4, 19, 10, 0, 0)
    presence.set_status(
        conn,
        doc_id="doc_1",
        principal=_P(principal_id="usr_alice", principal_type="user"),
        status="editing",
        note="intro",
        now=now,
    )
    row = _fetch_presence_row(conn, "doc_1", "usr_alice")
    assert row is not None
    # status, note, updated_at, expires_at
    assert row[3] == "editing"
    assert row[4] == "intro"
    assert row[5] == "2026-04-19T10:00:00"
    assert row[6] == "2026-04-19T10:10:00"


def test_set_status_upsert_refreshes_expires_at(conn):
    first = datetime(2026, 4, 19, 10, 0, 0)
    presence.set_status(conn, doc_id="doc_1", principal=_P("usr_alice", "user"),
                        status="reading", note=None, now=first)
    second = datetime(2026, 4, 19, 10, 4, 0)
    presence.set_status(conn, doc_id="doc_1", principal=_P("usr_alice", "user"),
                        status="editing", note="now editing", now=second)
    rows = conn.execute(
        "SELECT status, note, updated_at, expires_at FROM presence "
        "WHERE doc_id=? AND principal_id=?",
        ("doc_1", "usr_alice"),
    ).fetchall()
    assert len(rows) == 1, "upsert must not create a second row"
    assert rows[0][0] == "editing"
    assert rows[0][1] == "now editing"
    assert rows[0][2] == "2026-04-19T10:04:00"
    assert rows[0][3] == "2026-04-19T10:14:00"


def test_set_status_rejects_invalid_status(conn):
    with pytest.raises(ValueError, match="status"):
        presence.set_status(conn, doc_id="doc_1", principal=_P("usr_alice", "user"),
                            status="done", note=None, now=datetime(2026, 4, 19, 10, 0, 0))


def test_set_status_requires_view_access_missing_doc(conn):
    with pytest.raises(presence.PresenceError):
        presence.set_status(conn, doc_id="doc_MISSING",
                            principal=_P("usr_alice", "user"),
                            status="reading", note=None,
                            now=datetime(2026, 4, 19, 10, 0, 0))


def test_ttl_is_ten_minutes(conn):
    now = datetime(2026, 4, 19, 10, 0, 0)
    presence.set_status(conn, doc_id="doc_1", principal=_P("usr_alice", "user"),
                        status="reading", note=None, now=now)
    row = conn.execute(
        "SELECT updated_at, expires_at FROM presence"
    ).fetchone()
    updated = datetime.fromisoformat(row[0])
    expires = datetime.fromisoformat(row[1])
    assert expires - updated == timedelta(minutes=10)


def test_clear_status_removes_row(conn):
    now = datetime(2026, 4, 19, 10, 0, 0)
    presence.set_status(conn, doc_id="doc_1", principal=_P("usr_alice", "user"),
                        status="editing", note=None, now=now)
    presence.clear_status(conn, doc_id="doc_1", principal=_P("usr_alice", "user"))
    rows = conn.execute("SELECT * FROM presence").fetchall()
    assert rows == []


def test_clear_status_is_idempotent(conn):
    # Clearing with no row present must not raise.
    presence.clear_status(conn, doc_id="doc_1", principal=_P("usr_alice", "user"))


def test_list_active_returns_rows_with_display_name(conn):
    now = datetime(2026, 4, 19, 10, 0, 0)
    presence.set_status(conn, doc_id="doc_1", principal=_P("usr_alice", "user"),
                        status="editing", note="intro", now=now)
    active = presence.list_active(conn, doc_id="doc_1", now=now)
    assert len(active) == 1
    a = active[0]
    assert a.principal_id == "usr_alice"
    assert a.principal_type == "user"
    assert a.display_name == "Alice"
    assert a.status == "editing"
    assert a.note == "intro"
    assert a.updated_at == "2026-04-19T10:00:00"


def test_list_active_filters_expired(conn):
    start = datetime(2026, 4, 19, 10, 0, 0)
    presence.set_status(conn, doc_id="doc_1", principal=_P("usr_alice", "user"),
                        status="reading", note=None, now=start)
    # Query 11 minutes later — row has expired (TTL 10m).
    later = datetime(2026, 4, 19, 10, 11, 0)
    active = presence.list_active(conn, doc_id="doc_1", now=later)
    assert active == []


def test_list_active_joins_agents_table(conn):
    # Seed a user-owned agent and a presence row for it.
    conn.execute(
        """
        INSERT INTO agents (id, display_name, owner_type, owner_id, created_at)
        VALUES (?, ?, 'user', ?, ?)
        """,
        ("agt_bot", "Worker Bot", "usr_alice", "2026-04-19T00:00:00"),
    )
    conn.commit()
    now = datetime(2026, 4, 19, 10, 0, 0)
    presence.set_status(conn, doc_id="doc_1", principal=_P("agt_bot", "agent"),
                        status="editing", note=None, now=now)
    active = presence.list_active(conn, doc_id="doc_1", now=now)
    agent_rows = [a for a in active if a.principal_type == "agent"]
    assert len(agent_rows) == 1
    assert agent_rows[0].display_name == "Worker Bot"


def test_list_active_scoped_to_doc(conn):
    _seed_doc(conn, doc_id="doc_2")
    now = datetime(2026, 4, 19, 10, 0, 0)
    presence.set_status(conn, doc_id="doc_1", principal=_P("usr_alice", "user"),
                        status="reading", note=None, now=now)
    presence.set_status(conn, doc_id="doc_2", principal=_P("usr_alice", "user"),
                        status="editing", note=None, now=now)
    d1 = presence.list_active(conn, doc_id="doc_1", now=now)
    d2 = presence.list_active(conn, doc_id="doc_2", now=now)
    assert len(d1) == 1 and d1[0].status == "reading"
    assert len(d2) == 1 and d2[0].status == "editing"


def test_gc_expired_deletes_stale_rows(conn):
    start = datetime(2026, 4, 19, 10, 0, 0)
    presence.set_status(conn, doc_id="doc_1", principal=_P("usr_alice", "user"),
                        status="reading", note=None, now=start)
    later = datetime(2026, 4, 19, 10, 11, 0)
    deleted = presence.gc_expired(conn, now=later)
    assert deleted == 1
    count = conn.execute("SELECT COUNT(*) FROM presence").fetchone()[0]
    assert count == 0


def test_gc_expired_preserves_live_rows(conn):
    _seed_user(conn, user_id="usr_bob", display="Bob")
    start = datetime(2026, 4, 19, 10, 0, 0)
    presence.set_status(conn, doc_id="doc_1", principal=_P("usr_alice", "user"),
                        status="editing", note=None, now=start)
    fresh = datetime(2026, 4, 19, 10, 9, 0)
    presence.set_status(conn, doc_id="doc_1", principal=_P("usr_bob", "user"),
                        status="reading", note=None, now=fresh)
    at = datetime(2026, 4, 19, 10, 11, 0)
    deleted = presence.gc_expired(conn, now=at)
    assert deleted == 1
    remaining = conn.execute("SELECT principal_id FROM presence").fetchall()
    assert {r[0] for r in remaining} == {"usr_bob"}


def test_gc_expired_returns_zero_when_no_stale_rows(conn):
    now = datetime(2026, 4, 19, 10, 0, 0)
    presence.set_status(conn, doc_id="doc_1", principal=_P("usr_alice", "user"),
                        status="reading", note=None, now=now)
    assert presence.gc_expired(conn, now=now) == 0


def test_ttl_expiry_end_to_end(conn):
    """Set at T=0 → list at T=9m shows row → list at T=11m empty → gc at T=11m deletes it."""
    t0 = datetime(2026, 4, 19, 10, 0, 0)
    presence.set_status(conn, doc_id="doc_1", principal=_P("usr_alice", "user"),
                        status="editing", note="work", now=t0)

    t9 = datetime(2026, 4, 19, 10, 9, 0)
    active = presence.list_active(conn, doc_id="doc_1", now=t9)
    assert len(active) == 1

    t11 = datetime(2026, 4, 19, 10, 11, 0)
    active = presence.list_active(conn, doc_id="doc_1", now=t11)
    assert active == []
    still_on_disk = conn.execute("SELECT COUNT(*) FROM presence").fetchone()[0]
    assert still_on_disk == 1, "list_active filters; it does not delete"

    deleted = presence.gc_expired(conn, now=t11)
    assert deleted == 1
    assert conn.execute("SELECT COUNT(*) FROM presence").fetchone()[0] == 0

    # Re-setting after expiry starts a fresh row with a fresh TTL.
    t12 = datetime(2026, 4, 19, 10, 12, 0)
    presence.set_status(conn, doc_id="doc_1", principal=_P("usr_alice", "user"),
                        status="reading", note=None, now=t12)
    row = conn.execute("SELECT expires_at FROM presence").fetchone()
    assert row[0] == "2026-04-19T10:22:00"
