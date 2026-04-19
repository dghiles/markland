"""Audit-log service — best-effort recorder. Never raises on write failure.

Callers (service/docs.py, service/grants.py, service/invites.py) can fire-and-forget.
If the DB is down or the row is malformed, we log and move on. Business logic must
never fail because auditing failed.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from markland.db import record_audit
from markland.service.auth import Principal

logger = logging.getLogger("markland.audit")

_ALLOWED_ACTIONS = frozenset(
    {
        "publish",
        "update",
        "delete",
        "grant",
        "revoke",
        "invite_create",
        "invite_accept",
    }
)


def record(
    conn: sqlite3.Connection,
    *,
    action: str,
    principal: Principal,
    doc_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write one audit row. Swallows all exceptions (logs at WARNING)."""
    if action not in _ALLOWED_ACTIONS:
        logger.warning("audit: unknown action %r (still recording)", action)
    try:
        record_audit(
            conn,
            doc_id=doc_id,
            action=action,
            principal_id=principal.principal_id,
            principal_type=principal.principal_type,
            metadata=metadata,
        )
    except Exception as exc:
        logger.warning(
            "audit: failed to record action=%s principal=%s doc=%s err=%s",
            action,
            principal.principal_id,
            doc_id,
            exc,
        )


def list_recent(
    conn: sqlite3.Connection,
    *,
    doc_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return most recent audit rows, newest first. Optionally filter by doc_id."""
    limit = max(1, min(int(limit), 1000))
    if doc_id is not None:
        cursor = conn.execute(
            """
            SELECT id, doc_id, action, principal_id, principal_type, metadata, created_at
            FROM audit_log
            WHERE doc_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (doc_id, limit),
        )
    else:
        cursor = conn.execute(
            """
            SELECT id, doc_id, action, principal_id, principal_type, metadata, created_at
            FROM audit_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
    rows: list[dict[str, Any]] = []
    for r in cursor.fetchall():
        try:
            meta = json.loads(r[5]) if r[5] else {}
        except json.JSONDecodeError:
            meta = {}
        rows.append(
            {
                "id": r[0],
                "doc_id": r[1],
                "action": r[2],
                "principal_id": r[3],
                "principal_type": r[4],
                "metadata": meta,
                "created_at": r[6],
            }
        )
    return rows
