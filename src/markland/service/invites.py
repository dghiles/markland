"""Invite-link service: create, resolve, accept, revoke, list.

Invites are URLs (`/invite/<urlsafe-token>`) that grant an incoming user access
to a specific doc at a specific level. Tokens are stored hashed (argon2id),
identical to how user/agent tokens are stored elsewhere in the service layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from markland import db
from markland.models import Grant, Invite
from markland.service import audit, metrics
from markland.service.auth import Principal, hash_token, verify_token
from markland.db import get_grant
from markland.service.grants import grant_by_principal_id


@dataclass
class CreatedInvite:
    """Returned from `create_invite`; carries the plaintext URL shown to the owner once."""

    id: str
    url: str
    level: str
    expires_at: str | None


_INVITE_COLUMNS = (
    "id, token_hash, doc_id, level, single_use, uses_remaining, "
    "created_by, created_at, expires_at, revoked_at"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_invite(row: tuple) -> Invite:
    return Invite(
        id=row[0],
        token_hash=row[1],
        doc_id=row[2],
        level=row[3],
        single_use=bool(row[4]),
        uses_remaining=row[5],
        created_by=row[6],
        created_at=row[7],
        expires_at=row[8],
        revoked_at=row[9],
    )


def create_invite(
    conn,
    *,
    doc_id: str,
    created_by_user_id: str,
    level: str,
    base_url: str,
    single_use: bool = True,
    expires_in_days: int | None = None,
    expires_at_override: str | None = None,
) -> CreatedInvite:
    """Create an invite row, return the plaintext URL and its id.

    The plaintext token is shown only once — in the returned URL — and then
    discarded. The DB stores only its argon2id hash.
    """
    if level not in ("view", "edit"):
        raise ValueError(f"invalid level: {level!r} (must be 'view' or 'edit')")

    invite_id = Invite.generate_id()
    plaintext_token = Invite.generate_token()
    token_hash = hash_token(plaintext_token)

    created_at = _now_iso()
    if expires_at_override is not None:
        expires_at = expires_at_override
    elif expires_in_days is not None:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=expires_in_days)
        ).isoformat()
    else:
        expires_at = None

    uses_remaining = 1 if single_use else 1_000_000  # "effectively unlimited"

    conn.execute(
        "INSERT INTO invites (id, token_hash, doc_id, level, single_use, uses_remaining, "
        "created_by, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            invite_id,
            token_hash,
            doc_id,
            level,
            1 if single_use else 0,
            uses_remaining,
            created_by_user_id,
            created_at,
            expires_at,
        ),
    )
    conn.commit()

    url = f"{base_url.rstrip('/')}/invite/{plaintext_token}"
    audit.record(
        conn,
        action="invite_create",
        principal=Principal(
            principal_id=created_by_user_id,
            principal_type="user",
            display_name="",
            is_admin=False,
            user_id=created_by_user_id,
        ),
        doc_id=doc_id,
        metadata={"invite_id": invite_id, "level": level, "single_use": single_use},
    )
    return CreatedInvite(id=invite_id, url=url, level=level, expires_at=expires_at)


def resolve_invite(conn, token_plaintext: str) -> Invite | None:
    """Return the Invite matching `token_plaintext`, or None if no active invite exists.

    Active = not revoked, uses_remaining > 0, not expired.

    We do a linear scan over non-revoked rows with uses_remaining > 0 and
    verify each against argon2id. In practice the set of live invites per
    server is tiny (tens to hundreds); scan is fine.
    """
    if not token_plaintext:
        return None
    now = _now_iso()
    rows = conn.execute(
        f"SELECT {_INVITE_COLUMNS} FROM invites "
        "WHERE revoked_at IS NULL AND uses_remaining > 0 "
        "AND (expires_at IS NULL OR expires_at > ?)",
        (now,),
    ).fetchall()

    for row in rows:
        if verify_token(token_plaintext, row[1]):
            inv = _row_to_invite(row)
            if inv.is_active(now=now):
                return inv
            return None
    return None


_LEVEL_ORDER = {"view": 1, "edit": 2}


def _level_at_least(existing: str, wanted: str) -> bool:
    return _LEVEL_ORDER.get(existing, 0) >= _LEVEL_ORDER.get(wanted, 0)


def accept_invite(conn, *, invite_token: str, user_id: str) -> Grant | None:
    """Consume one use of the invite and ensure `user_id` has a grant at
    (at least) the invite's level on the invite's doc.

    Idempotent: if the user already has a grant at equal-or-higher level, the
    existing grant is returned unchanged — but `uses_remaining` is still
    decremented, because the URL was presented.

    Returns the resulting Grant, or None if the invite was not acceptable
    (unknown / expired / revoked / used up).

    Note: acceptance uses the internal-helper path
    `service.grants.grant_by_principal_id` (not the public `grant()`, which
    expects an email + principal authorization). The invite token itself is
    the authorization to create a grant for `user_id`.
    """
    inv = resolve_invite(conn, invite_token)
    if inv is None:
        return None

    # Decrement uses_remaining (single_use → 0 after first use).
    new_remaining = 0 if inv.single_use else max(inv.uses_remaining - 1, 0)
    conn.execute(
        "UPDATE invites SET uses_remaining = ? WHERE id = ?",
        (new_remaining, inv.id),
    )
    conn.commit()

    # Decide whether to upsert the grant.
    existing = get_grant(conn, doc_id=inv.doc_id, principal_id=user_id)
    if existing is not None and _level_at_least(existing.level, inv.level):
        # Don't downgrade; return the existing grant. Still audit the accept
        # because the invite URL was presented and one use was consumed.
        _record_accept(conn, user_id=user_id, doc_id=inv.doc_id, invite_id=inv.id)
        return existing

    grant_by_principal_id(
        conn,
        doc_id=inv.doc_id,
        principal_id=user_id,
        principal_type="user",
        level=inv.level,
        granted_by=inv.created_by,
    )
    result = db.get_grant(conn, doc_id=inv.doc_id, principal_id=user_id)
    _record_accept(conn, user_id=user_id, doc_id=inv.doc_id, invite_id=inv.id)
    return result


def _record_accept(conn, *, user_id: str, doc_id: str, invite_id: str) -> None:
    audit.record(
        conn,
        action="invite_accept",
        principal=Principal(
            principal_id=user_id,
            principal_type="user",
            display_name="",
            is_admin=False,
            user_id=user_id,
        ),
        doc_id=doc_id,
        metadata={"invite_id": invite_id},
    )
    metrics.emit_first_time("first_invite_accept", principal_id=user_id)


def revoke_invite(conn, *, invite_id: str, owner_user_id: str) -> None:
    """Mark an invite revoked. Caller must be the invite's creator."""
    row = conn.execute(
        "SELECT created_by, revoked_at FROM invites WHERE id = ?",
        (invite_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"invite not found: {invite_id}")
    if row[0] != owner_user_id:
        raise PermissionError(
            f"user {owner_user_id} cannot revoke invite {invite_id} (not creator)"
        )
    if row[1] is not None:
        return  # already revoked — idempotent no-op
    conn.execute(
        "UPDATE invites SET revoked_at = ? WHERE id = ?",
        (_now_iso(), invite_id),
    )
    conn.commit()


def list_invites(conn, *, doc_id: str, include_revoked: bool = False) -> list[Invite]:
    """Return invites for `doc_id`, ordered newest first.

    By default, revoked invites are hidden.
    """
    if include_revoked:
        where = "WHERE doc_id = ?"
    else:
        where = "WHERE doc_id = ? AND revoked_at IS NULL"
    params = (doc_id,)
    rows = conn.execute(
        f"SELECT {_INVITE_COLUMNS} FROM invites {where} ORDER BY created_at DESC",
        params,
    ).fetchall()
    return [_row_to_invite(r) for r in rows]


__all__ = [
    "CreatedInvite",
    "accept_invite",
    "create_invite",
    "list_invites",
    "resolve_invite",
    "revoke_invite",
]
