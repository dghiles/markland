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
