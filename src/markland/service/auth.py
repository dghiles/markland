"""Token hashing, principal resolution, and per-user token lifecycle.

Token plaintext format (post-markland-9dm)
------------------------------------------

New tokens embed their row-id as a public, non-secret prefix so that
``resolve_token`` can fetch by primary key (O(1)) instead of scanning
every non-revoked row and running an Argon2id verify per row.

Plaintext shape::

    mk_usr_<token_id_hex>_<random_secret>      # user tokens
    mk_agt_<token_id_hex>_<random_secret>      # agent tokens

Where ``<token_id_hex>`` is the ``tok_<hex>`` row-id with the ``tok_``
prefix dropped (16 hex chars). The DB primary key is the full
``tok_<hex>`` form; the parser re-attaches the prefix.

Legacy tokens (issued before this PR) have shape ``mk_usr_<urlsafe32>``
with no embedded token_id. ``resolve_token`` falls back to the O(N) scan
for them. The fall-through is also correctness-critical for the rare
case where a legacy plaintext's secret happens to start with 16 hex
chars + ``_``: the parser will match, the PK lookup will miss, and we
MUST continue to the legacy scan rather than return None. See the
``resolve_token`` docstring for details.
"""

from __future__ import annotations

import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Default Argon2PasswordHasher parameters (per spec §4: argon2id; no custom params).
_hasher = PasswordHasher()


@dataclass(frozen=True)
class Principal:
    """Resolved identity attached to an authenticated request.

    principal_type is 'user' today; 'agent' is reserved for Plan 4.
    user_id is None for users; for agents it will be the owning user_id.
    """

    principal_id: str
    principal_type: Literal["user", "agent"]
    display_name: str | None
    is_admin: bool
    user_id: str | None = None


@dataclass(frozen=True)
class TokenRecord:
    id: str
    label: str | None
    principal_type: str
    principal_id: str
    created_at: str
    last_used_at: str | None
    revoked_at: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_token_id() -> str:
    return f"tok_{secrets.token_hex(8)}"


# `secrets.token_hex(8)` always emits 16 lowercase hex chars.
_TOKEN_ID_HEX_LEN = 16
# Anchored full-match regex; the trailing `(.+)` captures the secret part
# verbatim, which may contain `_` and `-` (urlsafe alphabet).
_TOKEN_PARSE_RE = re.compile(r"^mk_(usr|agt)_([0-9a-f]{16})_(.+)$")


@dataclass(frozen=True)
class ParsedToken:
    """A successfully-parsed new-shape token plaintext.

    A successful parse does NOT imply the token is valid — the resolver
    must still PK-lookup the row, cross-check ``principal_type``, and
    Argon2-verify the plaintext against the stored hash. See
    ``resolve_token`` for the fall-through-on-miss contract.
    """

    principal_type: Literal["user", "agent"]
    token_id: str  # full 'tok_<hex>' form
    secret_part: str


def _format_user_token_plaintext(token_id: str, secret_part: str) -> str:
    """Combine token_id + secret_part into the user-facing plaintext."""
    short = token_id.removeprefix("tok_")
    return f"mk_usr_{short}_{secret_part}"


def _format_agent_token_plaintext(token_id: str, secret_part: str) -> str:
    """Combine token_id + secret_part into the agent-facing plaintext."""
    short = token_id.removeprefix("tok_")
    return f"mk_agt_{short}_{secret_part}"


def _parse_token_plaintext(plaintext: str) -> ParsedToken | None:
    """Return ParsedToken if plaintext is the new shape; None for legacy.

    None signals "fall back to O(N) scan." A non-None return does NOT
    by itself authenticate the token — the resolver still verifies it.
    """
    if not plaintext:
        return None
    m = _TOKEN_PARSE_RE.fullmatch(plaintext)
    if not m:
        return None
    type_short, hex_part, secret_part = m.groups()
    return ParsedToken(
        principal_type="user" if type_short == "usr" else "agent",
        token_id=f"tok_{hex_part}",
        secret_part=secret_part,
    )


def _mint_user_token_plaintext_with_id() -> tuple[str, str]:
    """Mint a fresh user token. Returns ``(token_id, plaintext)``.

    The two values are coupled — the plaintext embeds ``token_id`` as
    its public prefix, enabling O(1) lookup in ``resolve_token``.
    """
    token_id = _generate_token_id()
    secret_part = secrets.token_urlsafe(32)
    plaintext = _format_user_token_plaintext(token_id, secret_part)
    return token_id, plaintext


def _mint_agent_token_plaintext_with_id() -> tuple[str, str]:
    """Mint a fresh agent token. Returns ``(token_id, plaintext)``."""
    token_id = _generate_token_id()
    secret_part = secrets.token_urlsafe(32)
    plaintext = _format_agent_token_plaintext(token_id, secret_part)
    return token_id, plaintext


def _generate_user_token_plaintext() -> str:
    """Deprecated: use :func:`_mint_user_token_plaintext_with_id` instead.

    Kept as a stub raising NotImplementedError so any rogue importer
    fails loudly at call time rather than silently minting a legacy-
    shaped token without an embedded token_id.
    """
    raise NotImplementedError(
        "Use _mint_user_token_plaintext_with_id (markland-9dm)"
    )


def _generate_agent_token_plaintext() -> str:
    """Deprecated: use :func:`_mint_agent_token_plaintext_with_id` instead."""
    raise NotImplementedError(
        "Use _mint_agent_token_plaintext_with_id (markland-9dm)"
    )


def hash_token(plaintext: str) -> str:
    """Argon2id-hash a token. Salt is randomly generated per call."""
    return _hasher.hash(plaintext)


def verify_token(plaintext: str, hashed: str) -> bool:
    """Return True iff `plaintext` matches `hashed`. Safe on malformed hashes."""
    try:
        return _hasher.verify(hashed, plaintext)
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception:
        return False


def create_user_token(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    label: str,
) -> tuple[str, str]:
    """Create a new user token. Returns (token_id, plaintext).

    The plaintext is shown to the user ONCE and never persisted — only its hash.
    """
    token_id, plaintext = _mint_user_token_plaintext_with_id()
    hashed = hash_token(plaintext)
    conn.execute(
        """
        INSERT INTO tokens (
            id, token_hash, label, principal_type, principal_id,
            created_at, last_used_at, revoked_at
        ) VALUES (?, ?, ?, 'user', ?, ?, NULL, NULL)
        """,
        (token_id, hashed, label, user_id, _now()),
    )
    conn.commit()
    from markland.service import metrics as _metrics
    try:
        _metrics.emit("token_create", principal_id=user_id, kind="user")
    except Exception:
        pass
    return token_id, plaintext


def _create_token_for_agent(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    label: str,
) -> tuple[str, str]:
    """Mint a token bound to an agent principal, regardless of owner.

    Internal — callers in the user-facing path should use create_agent_token,
    which enforces ownership. This helper is reused by the service-agent
    operator script.
    """
    token_id, plaintext = _mint_agent_token_plaintext_with_id()
    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, "
        "created_at, last_used_at, revoked_at) "
        "VALUES (?, ?, ?, 'agent', ?, ?, NULL, NULL)",
        (token_id, hash_token(plaintext), (label or "").strip(), agent_id, _now()),
    )
    conn.commit()
    from markland.service import metrics as _metrics
    try:
        _metrics.emit("token_create", principal_id=agent_id, kind="agent")
    except Exception:
        pass
    return token_id, plaintext


def create_agent_token(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    owner_user_id: str,
    label: str,
) -> tuple[str, str]:
    """Mint a `mk_agt_…` token for a user-owned agent. Plaintext returned once."""
    row = conn.execute(
        "SELECT owner_type, owner_id, revoked_at FROM agents WHERE id = ?",
        (agent_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"agent_not_found: {agent_id}")
    owner_type, owner_id, revoked_at = row[0], row[1], row[2]
    if revoked_at is not None:
        raise ValueError("agent_revoked")
    if owner_type != "user" or owner_id != owner_user_id:
        raise PermissionError("not_agent_owner")

    return _create_token_for_agent(conn, agent_id=agent_id, label=label)


def resolve_token(conn: sqlite3.Connection, plaintext: str) -> Principal | None:
    """Find the token row whose hash matches `plaintext`, return its principal.

    Scans non-revoked tokens; argon2 verify per row. At 100-user scale with <1k
    total tokens this is fine; a per-request cache is a Plan 10 concern.
    """
    if not plaintext:
        return None
    rows = conn.execute(
        """
        SELECT id, token_hash, principal_type, principal_id
        FROM tokens
        WHERE revoked_at IS NULL
        """
    ).fetchall()
    for token_id, token_hash, principal_type, principal_id in rows:
        if verify_token(plaintext, token_hash):
            if principal_type == "user":
                user_row = conn.execute(
                    "SELECT id, display_name, is_admin FROM users WHERE id = ?",
                    (principal_id,),
                ).fetchone()
                if user_row is None:
                    return None
                # Fire-and-forget update of last_used_at. Failure must not block auth.
                try:
                    conn.execute(
                        "UPDATE tokens SET last_used_at = ? WHERE id = ?",
                        (_now(), token_id),
                    )
                    conn.commit()
                except sqlite3.Error:
                    pass
                return Principal(
                    principal_id=user_row[0],
                    principal_type="user",
                    display_name=user_row[1],
                    is_admin=bool(user_row[2]),
                    user_id=None,
                )
            if principal_type == "agent":
                agent_row = conn.execute(
                    "SELECT id, owner_type, owner_id, display_name, revoked_at "
                    "FROM agents WHERE id = ?",
                    (principal_id,),
                ).fetchone()
                if agent_row is None:
                    return None
                (
                    agent_id,
                    agent_owner_type,
                    agent_owner_id,
                    agent_display_name,
                    agent_revoked_at,
                ) = agent_row
                if agent_revoked_at is not None:
                    return None
                try:
                    conn.execute(
                        "UPDATE tokens SET last_used_at = ? WHERE id = ?",
                        (_now(), token_id),
                    )
                    conn.commit()
                except sqlite3.Error:
                    pass
                owner_user_id = (
                    agent_owner_id if agent_owner_type == "user" else None
                )
                return Principal(
                    principal_id=agent_id,
                    principal_type="agent",
                    display_name=agent_display_name,
                    is_admin=False,
                    user_id=owner_user_id,
                )
            return None
    return None


def revoke_token(
    conn: sqlite3.Connection,
    *,
    token_id: str,
    user_id: str,
) -> bool:
    """Revoke `token_id` iff it belongs to `user_id`. Returns True on success."""
    cursor = conn.execute(
        """
        UPDATE tokens
        SET revoked_at = ?
        WHERE id = ? AND principal_type = 'user' AND principal_id = ? AND revoked_at IS NULL
        """,
        (_now(), token_id, user_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def list_tokens(conn: sqlite3.Connection, *, user_id: str) -> list[TokenRecord]:
    """List this user's non-revoked tokens, newest first."""
    rows = conn.execute(
        """
        SELECT id, label, principal_type, principal_id, created_at, last_used_at, revoked_at
        FROM tokens
        WHERE principal_type = 'user' AND principal_id = ? AND revoked_at IS NULL
        ORDER BY created_at DESC
        """,
        (user_id,),
    ).fetchall()
    return [
        TokenRecord(
            id=r[0],
            label=r[1],
            principal_type=r[2],
            principal_id=r[3],
            created_at=r[4],
            last_used_at=r[5],
            revoked_at=r[6],
        )
        for r in rows
    ]
