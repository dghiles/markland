"""Unit tests for the admin_metrics service aggregator."""

from __future__ import annotations

import sqlite3

import pytest

from markland.db import init_db
from markland.service.admin_metrics import summary


@pytest.fixture
def conn(tmp_path) -> sqlite3.Connection:
    return init_db(tmp_path / "metrics.db")


def _seed_user(conn: sqlite3.Connection, user_id: str, email: str, created_at: str) -> None:
    conn.execute(
        "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
        (user_id, email, created_at),
    )
    conn.commit()


def _seed_audit(
    conn: sqlite3.Connection,
    principal_id: str,
    action: str,
    doc_id: str | None,
    created_at: str,
) -> None:
    conn.execute(
        "INSERT INTO audit_log (doc_id, action, principal_id, principal_type, created_at) "
        "VALUES (?, ?, ?, 'user', ?)",
        (doc_id, action, principal_id, created_at),
    )
    conn.commit()


def _seed_doc(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    is_public: int = 0,
    created_at: str = "2026-05-01T00:00:00Z",
    owner_id: str | None = None,
) -> None:
    # documents has UNIQUE share_token NOT NULL — pass through doc_id as a stand-in.
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, is_public, owner_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (doc_id, "t", "c", f"tok_{doc_id}", created_at, created_at, is_public, owner_id),
    )
    conn.commit()


def test_summary_empty_db(conn):
    result = summary(conn, window_seconds=86400)
    assert result["window_seconds"] == 86400
    assert result["signups"] == 0
    assert result["publishes"] == 0
    assert result["grants_created"] == 0
    assert result["invites_accepted"] == 0
    assert result["waitlist_total"] == 0
    assert result["first_mcp_call"] is None  # known gap, explicit


def test_summary_counts_signups_in_window(conn):
    recent = "2026-04-30T12:00:00Z"  # within 24h
    old = "2026-04-01T12:00:00Z"  # outside 24h
    _seed_user(conn, "usr_a", "a@x.com", recent)
    _seed_user(conn, "usr_b", "b@x.com", old)
    result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
    assert result["signups"] == 1


def test_summary_counts_audit_events(conn):
    now = "2026-05-01T00:00:00Z"
    _seed_audit(conn, "usr_a", "publish", "doc_1", "2026-04-30T22:00:00Z")
    _seed_audit(conn, "usr_a", "publish", "doc_2", "2026-04-30T23:00:00Z")
    _seed_audit(conn, "usr_a", "grant", "doc_1", "2026-04-30T22:30:00Z")
    _seed_audit(conn, "usr_a", "invite_accept", "inv_1", "2026-04-30T23:30:00Z")
    result = summary(conn, window_seconds=86400, now_iso=now)
    assert result["publishes"] == 2
    assert result["grants_created"] == 1
    assert result["invites_accepted"] == 1


def test_summary_waitlist_total_unbounded_by_window(conn):
    conn.execute(
        "INSERT INTO waitlist (email, source, created_at) VALUES (?, ?, ?)",
        ("c@x.com", "landing", "2025-01-01T00:00:00Z"),
    )
    conn.commit()
    result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
    assert result["waitlist_total"] == 1  # waitlist is total, not windowed


def test_summary_includes_window_start_and_end(conn):
    result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
    assert result["window_end_iso"] == "2026-05-01T00:00:00Z"
    assert result["window_start_iso"] == "2026-04-30T00:00:00Z"


def test_summary_includes_users_total_unwindowed(conn):
    # Two users — one inside the window, one outside. Both should be counted.
    _seed_user(conn, "usr_recent", "r@x.com", "2026-04-30T12:00:00Z")
    _seed_user(conn, "usr_old", "o@x.com", "2025-01-01T00:00:00Z")
    result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
    assert result["users_total"] == 2
    assert result["signups"] == 1  # window-bound, unchanged behavior


def test_summary_documents_total_counts_all_docs(conn):
    _seed_doc(conn, "d1", is_public=0)
    _seed_doc(conn, "d2", is_public=1)
    _seed_doc(conn, "d3", is_public=1)
    result = summary(conn, window_seconds=86400, now_iso="2026-05-02T00:00:00Z")
    assert result["documents_total"] == 3
    assert result["documents_public_total"] == 2


def test_summary_documents_created_in_window(conn):
    # One inside the 24h window, one outside.
    _seed_doc(conn, "d_recent", created_at="2026-04-30T12:00:00Z")
    _seed_doc(conn, "d_old", created_at="2026-04-01T12:00:00Z")
    result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
    assert result["documents_created"] == 1
    assert result["documents_total"] == 2  # unwindowed sees both


def test_summary_invites_total_counts_live_invites(conn):
    from markland.db import ensure_invites_schema

    ensure_invites_schema(conn)
    # Two live, one revoked — total should be 2.
    conn.execute(
        "INSERT INTO invites (id, token_hash, doc_id, level, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("inv1", "h1", "d1", "view", "usr_a", "2026-04-30T22:00:00Z"),
    )
    conn.execute(
        "INSERT INTO invites (id, token_hash, doc_id, level, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("inv2", "h2", "d2", "edit", "usr_a", "2026-04-30T23:00:00Z"),
    )
    conn.execute(
        "INSERT INTO invites (id, token_hash, doc_id, level, created_by, created_at, revoked_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("inv3", "h3", "d3", "view", "usr_a", "2026-04-29T22:00:00Z", "2026-04-30T22:00:00Z"),
    )
    conn.commit()
    result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
    assert result["invites_total"] == 2


def test_summary_invites_total_returns_zero_when_table_missing(conn):
    # init_db does not create the invites table; summary should not raise.
    result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
    assert result["invites_total"] == 0


def test_summary_grants_total_counts_active_rows(conn):
    # Seed two grant rows directly.
    conn.execute(
        "INSERT INTO grants (doc_id, principal_id, principal_type, level, granted_by, granted_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("doc_1", "usr_b", "user", "view", "usr_a", "2026-04-30T22:00:00Z"),
    )
    conn.execute(
        "INSERT INTO grants (doc_id, principal_id, principal_type, level, granted_by, granted_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("doc_2", "usr_c", "user", "edit", "usr_a", "2025-01-01T00:00:00Z"),
    )
    conn.commit()
    result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
    assert result["grants_total"] == 2  # unwindowed


def test_summary_counts_additional_audit_events_in_window(conn):
    now = "2026-05-01T00:00:00Z"
    in_window = "2026-04-30T22:00:00Z"
    out_of_window = "2026-04-01T22:00:00Z"

    # In window — should be counted
    _seed_audit(conn, "usr_a", "update", "doc_1", in_window)
    _seed_audit(conn, "usr_a", "update", "doc_2", in_window)
    _seed_audit(conn, "usr_a", "delete", "doc_3", in_window)
    _seed_audit(conn, "usr_a", "revoke", "doc_1", in_window)
    _seed_audit(conn, "usr_a", "invite_create", "doc_2", in_window)

    # Out of window — should NOT be counted
    _seed_audit(conn, "usr_a", "update", "doc_4", out_of_window)
    _seed_audit(conn, "usr_a", "delete", "doc_5", out_of_window)
    _seed_audit(conn, "usr_a", "revoke", "doc_6", out_of_window)
    _seed_audit(conn, "usr_a", "invite_create", "doc_7", out_of_window)

    result = summary(conn, window_seconds=86400, now_iso=now)
    assert result["documents_updated"] == 2
    assert result["documents_deleted"] == 1
    assert result["grants_revoked"] == 1
    assert result["invites_created"] == 1
