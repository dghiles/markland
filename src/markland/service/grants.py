"""Grants CRUD — owner-only mutations, owner-or-edit list, best-effort email.

Supports both email targets (→ user grant) and `agt_…` targets (→ agent grant).
Emails are enqueued through the in-process EmailDispatcher; grant writes never
fail because of email problems.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from markland import db
from markland.service import audit, email_templates, metrics
from markland.service.auth import Principal
from markland.service.permissions import NotFound, check_permission

logger = logging.getLogger("markland.grants")


class GrantTargetNotFound(Exception):
    """Target email has no matching user row."""


class AgentGrantsNotSupported(Exception):
    """Retained for back-compat. Plan 4+ supports agt_ targets and never raises this."""


class InvalidGrantLevel(Exception):
    """Level not in {'view', 'edit'}."""


_VALID_LEVELS = frozenset({"view", "edit"})
_VALID_PRINCIPAL_TYPES = frozenset({"user", "agent"})


def _lookup_user_by_email(conn: sqlite3.Connection, email: str) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT id, email FROM users WHERE lower(email) = lower(?)",
        (email.strip(),),
    ).fetchone()
    return (row[0], row[1]) if row else None


def _resolve_target(
    conn: sqlite3.Connection, target: str
) -> tuple[str, str, str]:
    """Return (principal_id, principal_type, email)."""
    t = target.strip()
    if t.startswith("agt_"):
        raise AgentGrantsNotSupported(
            "Agent target should be handled in the agent branch before this call."
        )
    if "@" not in t:
        raise GrantTargetNotFound(
            "Grant target must be an email address or `agt_…` id."
        )
    match = _lookup_user_by_email(conn, t)
    if match is None:
        raise GrantTargetNotFound(
            f"No Markland user with email {t}."
        )
    user_id, email = match
    return user_id, "user", email


def _granter_display(conn: sqlite3.Connection, principal: Principal) -> str:
    row = conn.execute(
        "SELECT display_name, email FROM users WHERE id = ?",
        (principal.principal_id,),
    ).fetchone()
    if row is None:
        return "Someone"
    display, email = row
    return display or email or "Someone"


def grant_by_principal_id(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    principal_id: str,
    principal_type: str,  # Literal['user','agent']
    level: str,  # Literal['view','edit']
    granted_by: str,
) -> None:
    """Internal helper: idempotent upsert of a grant row.

    No permission check — caller has already authorized (e.g. Plan 5
    invite-accept flow, Plan 4 agent-id grants). No email — caller decides
    whether to notify. Public callers should use `grant(...)` instead.
    """
    if level not in _VALID_LEVELS:
        raise InvalidGrantLevel(f"level must be one of {_VALID_LEVELS}; got {level!r}")
    if principal_type not in _VALID_PRINCIPAL_TYPES:
        raise ValueError(
            f"principal_type must be one of {_VALID_PRINCIPAL_TYPES}; "
            f"got {principal_type!r}"
        )
    if principal_type == "agent" and not principal_id.startswith("agt_"):
        raise ValueError(
            f"agent principal_id must start with 'agt_'; got {principal_id!r}"
        )
    db.upsert_grant(
        conn,
        doc_id=doc_id,
        principal_id=principal_id,
        principal_type=principal_type,
        level=level,
        granted_by=granted_by,
    )


def _enqueue(dispatcher, **kwargs) -> None:
    """Best-effort enqueue: never raises."""
    if dispatcher is None:
        return
    try:
        dispatcher.enqueue(**kwargs)
    except Exception as exc:
        logger.warning("grant email enqueue failed: %s", exc)


def grant(
    conn: sqlite3.Connection,
    *,
    base_url: str,
    principal: Principal,
    doc_id: str,
    target: str,
    level: str,
    email_client=None,  # Back-compat: wraps into inline dispatcher if given.
    dispatcher=None,
) -> dict:
    """Owner only. Upserts a grant row and enqueues a best-effort email.

    `target` is an email address (→ user grant) or an `agt_…` id (→ agent
    grant). `dispatcher` is the canonical path; `email_client` is accepted
    for back-compat and wrapped in a synchronous inline shim.
    """
    if level not in _VALID_LEVELS:
        raise InvalidGrantLevel(f"level must be one of {_VALID_LEVELS}; got {level!r}")

    check_permission(conn, principal, doc_id, "owner")

    target_str = (target or "").strip()
    if not target_str:
        raise GrantTargetNotFound("Grant target required.")

    # Prefer dispatcher. Accept email_client via inline shim for back-compat.
    if dispatcher is None and email_client is not None:
        dispatcher = _inline_dispatcher_from_client(email_client)

    doc = db.get_document(conn, doc_id)
    assert doc is not None
    doc_url = f"{base_url}/d/{doc.share_token}"
    granter_display = _granter_display(conn, principal)

    # Agent-id branch.
    if target_str.startswith("agt_"):
        agent_row = conn.execute(
            "SELECT id, display_name, owner_type, owner_id, revoked_at "
            "FROM agents WHERE id = ?",
            (target_str,),
        ).fetchone()
        if agent_row is None:
            raise NotFound(f"agent_not_found: {target_str}")
        if agent_row[4] is not None:
            raise NotFound(f"agent_revoked: {target_str}")

        grant_by_principal_id(
            conn,
            doc_id=doc_id,
            principal_id=agent_row[0],
            principal_type="agent",
            level=level,
            granted_by=principal.principal_id,
        )
        row = db.get_grant(conn, doc_id, agent_row[0])
        assert row is not None

        # Only email when agent is user-owned; service-owned agents get no mail.
        if agent_row[2] == "user" and dispatcher is not None:
            owner_row = conn.execute(
                "SELECT email FROM users WHERE id = ?",
                (agent_row[3],),
            ).fetchone()
            if owner_row is not None:
                rendered = email_templates.agent_grant(
                    granter_display=granter_display,
                    agent_name=agent_row[1] or agent_row[0],
                    agent_id=agent_row[0],
                    doc_title=doc.title,
                    doc_url=doc_url,
                    level=level,
                )
                _enqueue(
                    dispatcher,
                    to=owner_row[0],
                    subject=rendered["subject"],
                    html=rendered["html"],
                    text=rendered.get("text"),
                    metadata={
                        "template": "agent_grant",
                        "doc_id": doc_id,
                        "agent_id": agent_row[0],
                    },
                )

        audit.record(
            conn,
            action="grant",
            principal=principal,
            doc_id=doc_id,
            metadata={"target": target_str, "level": level},
        )
        metrics.emit_first_time("first_grant", principal_id=principal.principal_id)
        return _row_to_dict(row)

    # User-email branch.
    prior = conn.execute(
        "SELECT g.level FROM grants g "
        "JOIN users u ON u.id = g.principal_id "
        "WHERE g.doc_id = ? AND lower(u.email) = lower(?) AND g.principal_type = 'user'",
        (doc_id, target_str),
    ).fetchone()
    prior_level = prior[0] if prior else None

    try:
        principal_id, principal_type, target_email = _resolve_target(conn, target_str)
    except GrantTargetNotFound:
        # P2-E / markland-yi1: when the email shape is valid but no user
        # row exists, silently create an invite for that email instead
        # of leaking "this email is/isn't a Markland account" via a
        # distinct error. The response shape mirrors a successful grant
        # so the caller can't distinguish the two cases.
        if "@" not in target_str:
            # Not an email shape — surface the original "target not found"
            # so callers can fix typos (e.g. malformed agt_… ids).
            raise
        return _grant_via_invite(
            conn,
            doc=doc,
            doc_url=doc_url,
            target_email=target_str,
            level=level,
            principal=principal,
            granter_display=granter_display,
            dispatcher=dispatcher,
        )

    grant_by_principal_id(
        conn,
        doc_id=doc_id,
        principal_id=principal_id,
        principal_type=principal_type,
        level=level,
        granted_by=principal.principal_id,
    )
    row = db.get_grant(conn, doc_id, principal_id)
    assert row is not None

    if dispatcher is not None:
        if prior_level is None:
            rendered = email_templates.user_grant(
                granter_display=granter_display,
                doc_title=doc.title,
                doc_url=doc_url,
                level=level,
            )
            meta = {"template": "user_grant", "doc_id": doc_id}
            _enqueue(
                dispatcher,
                to=target_email,
                subject=rendered["subject"],
                html=rendered["html"],
                text=rendered.get("text"),
                metadata=meta,
            )
        elif prior_level != level:
            rendered = email_templates.user_grant_level_changed(
                granter_display=granter_display,
                doc_title=doc.title,
                doc_url=doc_url,
                old_level=prior_level,
                new_level=level,
            )
            meta = {"template": "user_grant_level_changed", "doc_id": doc_id}
            _enqueue(
                dispatcher,
                to=target_email,
                subject=rendered["subject"],
                html=rendered["html"],
                text=rendered.get("text"),
                metadata=meta,
            )
        # else: same level — no email.

    audit.record(
        conn,
        action="grant",
        principal=principal,
        doc_id=doc_id,
        metadata={"target": target_str, "level": level},
    )
    metrics.emit_first_time("first_grant", principal_id=principal.principal_id)
    return _row_to_dict(row)


def _inline_dispatcher_from_client(email_client) -> Any:
    """Wrap a Plan-2/3 EmailClient-shaped mock into a synchronous dispatcher.

    Exists only for backward-compat with tests/callers that still pass
    `email_client=` instead of `dispatcher=`.
    """

    class _Inline:
        def __init__(self, c):
            self._c = c

        def enqueue(self, to, subject, html, text=None, metadata=None):
            try:
                self._c.send(
                    to=to, subject=subject, html=html, text=text, metadata=metadata,
                )
            except TypeError:
                try:
                    self._c.send(to=to, subject=subject, html=html)
                except Exception as exc:
                    logger.warning("grant email failed: %s", exc)
            except Exception as exc:
                logger.warning("grant email failed: %s", exc)

    return _Inline(email_client)


def _grant_via_invite(
    conn: sqlite3.Connection,
    *,
    doc,
    doc_url: str,
    target_email: str,
    level: str,
    principal: Principal,
    granter_display: str,
    dispatcher,
) -> dict:
    """P2-E / markland-yi1: grant-by-email to a non-user creates an
    invite and returns a response shape indistinguishable from a
    successful grant. From the caller's perspective, every valid-email
    target succeeds — they cannot enumerate which emails belong to
    Markland accounts.
    """
    from markland.service.invites import create_invite

    base_url = doc_url.rsplit(f"/d/{doc.share_token}", 1)[0]
    created = create_invite(
        conn,
        doc_id=doc.id,
        created_by_user_id=principal.principal_id,
        level=level,
        base_url=base_url,
        single_use=True,
        expires_in_days=7,
    )

    if dispatcher is not None:
        # Reuse the user_grant template — the recipient sees "Alice
        # shared a doc with you" with the invite URL. They click and
        # the invite-accept flow walks them through sign-up.
        rendered = email_templates.user_grant(
            granter_display=granter_display,
            doc_title=doc.title,
            doc_url=created.url,
            level=level,
        )
        _enqueue(
            dispatcher,
            to=target_email,
            subject=rendered["subject"],
            html=rendered["html"],
            text=rendered.get("text"),
            metadata={
                "template": "user_grant_invite",
                "doc_id": doc.id,
                "invite_id": created.id,
            },
        )

    audit.record(
        conn,
        action="grant",
        principal=principal,
        doc_id=doc.id,
        metadata={"target": target_email, "level": level, "via": "invite"},
    )
    metrics.emit_first_time(
        "first_grant", principal_id=principal.principal_id
    )

    # Return the same shape as a successful grant. Use the invite's
    # creator + creation timestamp so the response is structurally
    # consistent and leak-free. principal_id is set to the email-shape
    # target rather than a user id we don't have.
    return {
        "doc_id": doc.id,
        "principal_id": target_email,
        "principal_type": "user",
        "level": level,
        "granted_by": principal.principal_id,
        "granted_at": created.expires_at or "",
    }


def _row_to_dict(row) -> dict:
    return {
        "doc_id": row.doc_id,
        "principal_id": row.principal_id,
        "principal_type": row.principal_type,
        "level": row.level,
        "granted_by": row.granted_by,
        "granted_at": row.granted_at,
    }


def revoke(
    conn: sqlite3.Connection,
    *,
    principal: Principal,
    doc_id: str,
    principal_id: str,
) -> dict:
    check_permission(conn, principal, doc_id, "owner")
    deleted = db.delete_grant(conn, doc_id, principal_id)
    if deleted:
        audit.record(
            conn,
            action="revoke",
            principal=principal,
            doc_id=doc_id,
            metadata={"target_principal_id": principal_id},
        )
        # P2-F / markland-1e8: rotate share_token on grant-revoke for
        # private docs. /d/{share_token} bypasses the grants table — so
        # revoking a grant alone leaves the old URL working forever.
        # Public docs keep their share_token (the URL IS the capability).
        doc = db.get_document(conn, doc_id)
        if doc is not None and not doc.is_public:
            db.rotate_share_token(conn, doc_id)
    return {"revoked": deleted, "doc_id": doc_id, "principal_id": principal_id}


def list_grants(
    conn: sqlite3.Connection,
    *,
    principal: Principal,
    doc_id: str,
) -> list[dict]:
    """Visible to owner or any principal with edit access on the doc."""
    check_permission(conn, principal, doc_id, "edit")
    rows = db.list_grants_for_doc(conn, doc_id)
    return [
        {
            "doc_id": r.doc_id,
            "principal_id": r.principal_id,
            "principal_type": r.principal_type,
            "level": r.level,
            "granted_by": r.granted_by,
            "granted_at": r.granted_at,
        }
        for r in rows
    ]


def list_grants_paginated(
    conn: sqlite3.Connection,
    *,
    principal: Principal,
    doc_id: str,
    limit: int = 50,
    cursor: str | None = None,
    cap: int = 200,
) -> tuple[list[dict], str | None]:
    """Paginated grants for a doc. Returns (rows, next_cursor).

    Order: (granted_at DESC, principal_id DESC). The cursor's
    `last_updated_at` field carries the `granted_at` timestamp.
    """
    from markland._mcp_envelopes import decode_cursor, encode_cursor

    check_permission(conn, principal, doc_id, "edit")

    limit = min(max(1, int(limit)), cap)

    where_clauses = ["doc_id = ?"]
    params: list = [doc_id]
    if cursor:
        last_id, last_granted_at = decode_cursor(cursor)
        where_clauses.append("(granted_at, principal_id) < (?, ?)")
        params.extend([last_granted_at, last_id])

    sql = (
        "SELECT doc_id, principal_id, principal_type, level, "
        "granted_by, granted_at FROM grants "
        f"WHERE {' AND '.join(where_clauses)} "
        "ORDER BY granted_at DESC, principal_id DESC LIMIT ?"
    )
    params.append(limit + 1)

    rows = conn.execute(sql, params).fetchall()
    has_more = len(rows) > limit
    page = rows[:limit]

    items = [
        {
            "doc_id": r[0],
            "principal_id": r[1],
            "principal_type": r[2],
            "level": r[3],
            "granted_by": r[4],
            "granted_at": r[5],
        }
        for r in page
    ]

    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(
            last_id=last["principal_id"], last_sort_key=last["granted_at"]
        )

    return items, next_cursor


__all__ = [
    "GrantTargetNotFound",
    "AgentGrantsNotSupported",
    "InvalidGrantLevel",
    "grant",
    "grant_by_principal_id",
    "revoke",
    "list_grants",
    "list_grants_paginated",
]
