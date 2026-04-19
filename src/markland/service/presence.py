"""Advisory presence — who is reading or editing a document.

Non-enforcing: calling `set_status(status='editing')` does NOT prevent other
principals from writing. Conflict safety lives in service/docs via the version
column; presence is a coordination hint only.

Every time-dependent function accepts an optional `now: datetime | None`
parameter. Production code passes nothing; tests pass explicit timestamps to
avoid mocking the clock.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

_TTL = timedelta(minutes=10)

Status = Literal["reading", "editing"]
_VALID_STATUSES: tuple[str, ...] = ("reading", "editing")


class PresenceError(RuntimeError):
    """Raised when a presence operation fails (e.g. doc not found)."""


@dataclass(frozen=True)
class ActivePrincipal:
    """One row of `list_active` output."""

    principal_id: str
    principal_type: str
    display_name: str | None
    status: str
    note: str | None
    updated_at: str


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.utcnow()


def _doc_exists(conn: sqlite3.Connection, doc_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return row is not None


def set_status(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    principal,
    status: str,
    note: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Upsert this principal's presence on the doc. Refreshes expires_at.

    Returns `{doc_id, status, expires_at}` for the caller to echo back.
    """
    if status not in _VALID_STATUSES:
        raise ValueError(
            f"status must be one of {_VALID_STATUSES!r}, got {status!r}"
        )
    if principal.principal_type not in ("user", "agent"):
        raise ValueError(
            "principal.principal_type must be 'user' or 'agent', "
            f"got {principal.principal_type!r}"
        )
    if not _doc_exists(conn, doc_id):
        raise PresenceError(f"document {doc_id} not found")

    ts = _now(now)
    updated_at = ts.isoformat(timespec="seconds")
    expires_at = (ts + _TTL).isoformat(timespec="seconds")

    conn.execute(
        """
        INSERT INTO presence
          (doc_id, principal_id, principal_type, status, note, updated_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(doc_id, principal_id) DO UPDATE SET
            principal_type = excluded.principal_type,
            status         = excluded.status,
            note           = excluded.note,
            updated_at     = excluded.updated_at,
            expires_at     = excluded.expires_at
        """,
        (
            doc_id,
            principal.principal_id,
            principal.principal_type,
            status,
            note,
            updated_at,
            expires_at,
        ),
    )
    conn.commit()
    return {"doc_id": doc_id, "status": status, "expires_at": expires_at}


def clear_status(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    principal,
) -> dict:
    """Remove this principal's presence row. Idempotent."""
    conn.execute(
        "DELETE FROM presence WHERE doc_id = ? AND principal_id = ?",
        (doc_id, principal.principal_id),
    )
    conn.commit()
    return {"ok": True}


def list_active(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    now: datetime | None = None,
) -> list[ActivePrincipal]:
    """Return non-expired presence rows for the doc, with display_name joined.

    The `expires_at > ?` filter is applied in SQL so stale rows do not leak
    even if the background GC is behind or has crashed.
    """
    ts = _now(now).isoformat(timespec="seconds")
    rows = conn.execute(
        """
        SELECT
            p.principal_id,
            p.principal_type,
            CASE
                WHEN p.principal_type = 'user'  THEN u.display_name
                WHEN p.principal_type = 'agent' THEN a.display_name
                ELSE NULL
            END AS display_name,
            p.status,
            p.note,
            p.updated_at
        FROM presence p
        LEFT JOIN users  u ON p.principal_type = 'user'  AND u.id = p.principal_id
        LEFT JOIN agents a ON p.principal_type = 'agent' AND a.id = p.principal_id
        WHERE p.doc_id = ?
          AND p.expires_at > ?
        ORDER BY p.updated_at DESC
        """,
        (doc_id, ts),
    ).fetchall()
    return [
        ActivePrincipal(
            principal_id=r[0],
            principal_type=r[1],
            display_name=r[2],
            status=r[3],
            note=r[4],
            updated_at=r[5],
        )
        for r in rows
    ]


def gc_expired(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
) -> int:
    """Delete rows where expires_at <= now. Returns the count deleted.

    Safe to call from a background task concurrently with reads because
    `list_active` filters on `expires_at > now` independently.
    """
    ts = _now(now).isoformat(timespec="seconds")
    cursor = conn.execute("DELETE FROM presence WHERE expires_at <= ?", (ts,))
    conn.commit()
    return cursor.rowcount or 0
