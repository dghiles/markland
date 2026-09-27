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

import hashlib
import re
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
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


# --- Resolved-token cache ----------------------------------------------------
#
# Every authenticated request resolves its bearer token, and every resolve
# costs Argon2id verifies (~0.1 CPU-s each): one for a new-shape token, one
# per non-revoked row for a legacy-shape token. On 2026-09-26 a post-deploy
# reconnect burst paid that on every request until the Fly shared-cpu burst
# balance ran out. So successful resolutions are cached in-process:
#
# - A hit costs no SQL and no Argon2. It also skips the ``last_used_at``
#   write, so that column is touched at most once per TTL per token.
# - Key: SHA-256 of the plaintext. The plaintext is never stored.
# - Expiry is fixed when the resolve starts, before its DB reads (hits do
#   not extend it), so a result is served for at most TOKEN_CACHE_TTL_S after
#   the DB state it reflects — even when a throttled legacy scan runs long.
# - Only successes are cached. An unknown or revoked token pays the full
#   resolve on every request.
# - Every in-process write that revokes or changes a token, user or agent
#   MUST evict the affected principal with evict_cached_principal(), in a
#   ``finally`` around the write: unconditionally, never gated on rowcount or
#   on commit() succeeding, since neither is trustworthy under concurrency.
#   Eviction is scoped to that principal, so a caller revoking their own
#   tokens (or re-revoking one) cannot flush anyone else's cached resolution
#   back onto the Argon2 scan. Current callers: revoke_token (below),
#   service.agents.revoke_agent, and the agent-token DELETE route in
#   web/routes_agents.py. There is no in-process user deletion or is_admin
#   change today; add an eviction if one appears.
# - Out-of-process writes (scripts/admin/* run over `flyctl ssh console`,
#   e.g. make_admin.py flipping is_admin, or a raw SQL revoke) cannot reach
#   this process's cache. They take effect within TOKEN_CACHE_TTL_S.

TOKEN_CACHE_TTL_S = 60.0
_TOKEN_CACHE_MAX_ENTRIES = 1024


class _ResolvedTokenCache:
    """Thread-safe map of sha256(plaintext) -> Principal, TTL- and LRU-bounded.

    Sync MCP tools run in the threadpool while middleware runs on the event
    loop, so every access takes the lock.

    Every eviction and clear() advances a sequence number. A resolver
    snapshots it with begin() BEFORE its DB reads and hands it back to put().
    The put is dropped if its principal was evicted, or the cache cleared,
    after that snapshot, so a token revoked mid-resolve cannot be re-cached as
    valid. Evicting one principal never drops another principal's put, so
    revoke calls cannot keep other users' legacy scans from ever caching.
    """

    def __init__(
        self,
        *,
        ttl_s: float,
        max_entries: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[bytes, tuple[float, Principal]] = OrderedDict()
        self._seq = 0
        self._cleared_at = 0
        # principal_id -> seq of its latest eviction. Bounded by the number of
        # principals ever evicted, which is small (users and agents).
        self._evicted_at: dict[str, int] = {}

    @property
    def generation(self) -> int:
        with self._lock:
            return self._seq

    def begin(self) -> tuple[int, float]:
        """Snapshot (generation, now) before a resolve's DB reads; pass both to put()."""
        with self._lock:
            return self._seq, self._clock()

    def get(self, key: bytes) -> Principal | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, principal = entry
            if self._clock() >= expires_at:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return principal

    def put(
        self,
        key: bytes,
        principal: Principal,
        *,
        generation: int,
        read_at: float | None = None,
    ) -> None:
        with self._lock:
            if self._cleared_at > generation:
                return
            if self._evicted_at.get(principal.principal_id, -1) > generation:
                return
            started = self._clock() if read_at is None else read_at
            self._entries[key] = (started + self._ttl_s, principal)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def evict_principal(self, principal_id: str) -> None:
        with self._lock:
            self._seq += 1
            self._evicted_at[principal_id] = self._seq
            stale = [k for k, (_, p) in self._entries.items() if p.principal_id == principal_id]
            for key in stale:
                del self._entries[key]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._seq += 1
            self._cleared_at = self._seq

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_token_cache = _ResolvedTokenCache(
    ttl_s=TOKEN_CACHE_TTL_S, max_entries=_TOKEN_CACHE_MAX_ENTRIES
)


def invalidate_token_cache() -> None:
    """Drop every cached token resolution in this process.

    Call after any write that revokes or changes a token, user or agent.
    """
    _token_cache.clear()


def evict_cached_principal(principal_id: str) -> None:
    """Drop every cached resolution for one principal (a user or an agent).

    Call in a ``finally`` around any write that revokes or changes that
    principal's tokens — whether or not it reported a change, since rowcount
    and commit() are not trustworthy under concurrency.
    """
    _token_cache.evict_principal(principal_id)


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
    """Resolve a Bearer token plaintext to a Principal.

    Fast path (new-shape tokens, post-markland-9dm): parse the embedded
    ``token_id`` prefix, fetch exactly one row by primary key, run a
    single Argon2 verify. O(1) regardless of token-table size.

    Legacy path (old-shape tokens, no embedded token_id): scan all
    non-revoked rows. Bounded by the count of pre-migration tokens,
    which only decreases over time as those tokens are revoked or
    rotated. Removal of the legacy path is filed as a follow-up.

    CRITICAL — fall-through on ANY fast-path miss:
        The new-format parser regex matches new-shape tokens AND any
        legacy plaintext whose secret happens to start with 16 lowercase
        hex chars + ``_``. In that case the PK lookup misses (or argon2
        verify fails on the wrong row, or principal_type cross-check
        fails) and we MUST fall through to the legacy scan — otherwise
        the legacy token silently stops working.

        Probability of natural occurrence is ~2.3e-12 per minted token;
        an attacker with a leaked legacy plaintext could engineer this
        shape, so the fall-through closes both correctness and grief
        vectors.

        See ``test_resolve_token_falls_through_to_legacy_on_pk_miss``
        for the regression guard.

    Caching: a successful result is cached for ``TOKEN_CACHE_TTL_S``; a
    repeat within the TTL skips both paths above (no SQL, no Argon2, no
    ``last_used_at`` write). ``None`` is never cached. See the
    "Resolved-token cache" section for invalidation rules.
    """
    if not plaintext:
        return None

    key = hashlib.sha256(plaintext.encode("utf-8")).digest()
    cached = _token_cache.get(key)
    if cached is not None:
        return cached
    generation, read_at = _token_cache.begin()
    principal = _resolve_uncached(conn, plaintext)
    if principal is not None:
        _token_cache.put(key, principal, generation=generation, read_at=read_at)
    return principal


def _resolve_uncached(
    conn: sqlite3.Connection, plaintext: str
) -> Principal | None:
    """Fast path, then legacy fall-through. See :func:`resolve_token`."""
    parsed = _parse_token_plaintext(plaintext)
    if parsed is not None:
        result = _resolve_by_token_id(conn, parsed, plaintext)
        if result is not None:
            return result
        # Fast path missed (PK absent, type mismatch, or verify mismatch).
        # Fall through to the legacy scan — see CRITICAL note above.

    return _resolve_legacy(conn, plaintext)


def _resolve_by_token_id(
    conn: sqlite3.Connection,
    parsed: ParsedToken,
    plaintext: str,
) -> Principal | None:
    """O(1) lookup by token_id PK, with type cross-check + argon2 verify.

    Returns ``Principal`` on success, ``None`` on PK miss / type mismatch /
    verify mismatch / dangling user or revoked agent.

    Caller MUST treat ``None`` as "fall through to legacy", not "auth
    failed." See :func:`resolve_token` for the rationale.
    """
    row = conn.execute(
        """
        SELECT id, token_hash, principal_type, principal_id
        FROM tokens
        WHERE id = ? AND revoked_at IS NULL
        """,
        (parsed.token_id,),
    ).fetchone()
    if row is None:
        return None
    token_id, token_hash, principal_type, principal_id = row
    # Cross-check type BEFORE running argon2 — saves the expensive verify
    # on a forged-prefix attack against an existing row of the wrong type.
    if principal_type != parsed.principal_type:
        return None
    if not verify_token(plaintext, token_hash):
        return None
    return _build_principal_and_touch(
        conn, token_id, principal_type, principal_id
    )


def _resolve_legacy(
    conn: sqlite3.Connection, plaintext: str
) -> Principal | None:
    """Pre-markland-9dm O(N) scan. Kept for legacy plaintexts only.

    Legacy tokens (issued before the token-id prefix migration) have no
    embedded token_id, so we have no choice but to argon2-verify against
    every non-revoked row until a match is found. New-shape tokens that
    PK-miss in the fast path also fall through here (see
    :func:`resolve_token` docstring).
    """
    rows = conn.execute(
        """
        SELECT id, token_hash, principal_type, principal_id
        FROM tokens
        WHERE revoked_at IS NULL
        """
    ).fetchall()
    for token_id, token_hash, principal_type, principal_id in rows:
        if verify_token(plaintext, token_hash):
            return _build_principal_and_touch(
                conn, token_id, principal_type, principal_id
            )
    return None


def _build_principal_and_touch(
    conn: sqlite3.Connection,
    token_id: str,
    principal_type: str,
    principal_id: str,
) -> Principal | None:
    """Build the Principal, then best-effort update ``tokens.last_used_at``.

    Refactored unchanged from the original ``resolve_token`` body. Failure
    to update ``last_used_at`` must NOT block auth.
    """
    if principal_type == "user":
        user_row = conn.execute(
            "SELECT id, display_name, is_admin FROM users WHERE id = ?",
            (principal_id,),
        ).fetchone()
        if user_row is None:
            return None
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


def revoke_token(
    conn: sqlite3.Connection,
    *,
    token_id: str,
    user_id: str,
) -> bool:
    """Revoke `token_id` iff it belongs to `user_id`. Returns True on success."""
    try:
        cursor = conn.execute(
            """
            UPDATE tokens
            SET revoked_at = ?
            WHERE id = ? AND principal_type = 'user' AND principal_id = ? AND revoked_at IS NULL
            """,
            (_now(), token_id, user_id),
        )
        conn.commit()
    finally:
        # Unconditional and scoped to the caller: see "Resolved-token cache".
        evict_cached_principal(user_id)
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
