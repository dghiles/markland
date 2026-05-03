"""Admin funnel metrics aggregated from existing tables.

Pure aggregation: reads users/audit_log/waitlist and returns a flat dict.
Window is operator-supplied seconds; waitlist_total is unwindowed.

first_mcp_call is a known gap - emitted to stdout only, not persisted.
Returned as None until a metrics_events table is added (see FOLLOW-UPS).
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import Any


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _shift(iso: str, seconds: int) -> str:
    ts = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    ts = ts - _dt.timedelta(seconds=seconds)
    return ts.isoformat().replace("+00:00", "Z")


def summary(
    conn: sqlite3.Connection,
    *,
    window_seconds: int,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Aggregate funnel events over a time window.

    Args:
      conn: SQLite connection.
      window_seconds: window size, e.g. 86400 (24h), 604800 (7d).
      now_iso: override for "now" in tests; defaults to current UTC.

    Returns:
      dict with keys: window_seconds, window_start_iso, window_end_iso,
      signups, publishes, grants_created, invites_accepted, users_total,
      waitlist_total, documents_total, documents_public_total,
      first_mcp_call.
    """
    end_iso = now_iso or _now_iso()
    start_iso = _shift(end_iso, window_seconds)

    def _count(query: str, params: tuple) -> int:
        row = conn.execute(query, params).fetchone()
        return int(row[0]) if row else 0

    # Counts user-row inserts, not auth events. Inflated by admin-side seeded
    # users (e.g., grant targets created via email lookup before they sign up).
    signups = _count(
        "SELECT COUNT(*) FROM users WHERE created_at >= ? AND created_at < ?",
        (start_iso, end_iso),
    )
    publishes = _count(
        "SELECT COUNT(*) FROM audit_log WHERE action = 'publish' "
        "AND created_at >= ? AND created_at < ?",
        (start_iso, end_iso),
    )
    grants_created = _count(
        "SELECT COUNT(*) FROM audit_log WHERE action = 'grant' "
        "AND created_at >= ? AND created_at < ?",
        (start_iso, end_iso),
    )
    invites_accepted = _count(
        "SELECT COUNT(*) FROM audit_log WHERE action = 'invite_accept' "
        "AND created_at >= ? AND created_at < ?",
        (start_iso, end_iso),
    )
    waitlist_total = _count("SELECT COUNT(*) FROM waitlist", ())
    users_total = _count("SELECT COUNT(*) FROM users", ())
    documents_total = _count("SELECT COUNT(*) FROM documents", ())
    documents_public_total = _count(
        "SELECT COUNT(*) FROM documents WHERE is_public = 1", ()
    )

    return {
        "window_seconds": window_seconds,
        "window_start_iso": start_iso,
        "window_end_iso": end_iso,
        "signups": signups,
        "publishes": publishes,
        "grants_created": grants_created,
        "invites_accepted": invites_accepted,
        "users_total": users_total,
        "waitlist_total": waitlist_total,
        "documents_total": documents_total,
        "documents_public_total": documents_public_total,
        "first_mcp_call": None,  # not persisted; see flyctl logs
    }
