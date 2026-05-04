"""Signed session cookies via itsdangerous.

Cookie name: `mk_session`. Payload:
``{"user_id": str, "exp": iso8601, "epoch": int}``.
Signed with `MARKLAND_SESSION_SECRET`. 30-day default lifetime.

Two layers of revocation:

1. Rotating ``MARKLAND_SESSION_SECRET`` invalidates all outstanding
   sessions globally (catastrophic / blast-radius unbounded).
2. ``bump_session_epoch(conn, user_id=...)`` invalidates outstanding
   cookies for one user — called from ``/api/auth/logout`` (markland-bul).

Production callers MUST pass ``conn`` to ``read_session`` and
``issue_session``; the ``conn=None`` path exists for unit tests that
don't seed the users table and is equivalent to "no revocation check"
plus ``epoch=0`` at issue time.
"""

from __future__ import annotations

import hmac
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from itsdangerous.serializer import Serializer

SESSION_COOKIE_NAME = "mk_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days
_SALT = "mk.session.v1"


class InvalidSession(Exception):
    """Raised when a session cookie is missing, tampered, expired, or revoked."""


def _signer(secret: str) -> TimestampSigner:
    if not secret:
        raise ValueError("session secret must be non-empty")
    return TimestampSigner(secret, salt=_SALT)


def _read_user_epoch(conn: sqlite3.Connection, user_id: str) -> int | None:
    """Return the user's current session_epoch, or None if user does not exist.

    Callers decide what missing-user means:

    - ``read_session``: missing user → ``InvalidSession`` (cookie
      references a deleted account; revoke).
    - ``issue_session``: missing user → ``epoch=0`` (test fixtures issue
      sessions for synthetic ``user_id`` values that aren't in the DB;
      this keeps those tests working without forcing them to seed the
      users table).
    """
    row = conn.execute(
        "SELECT session_epoch FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if row is None:
        return None
    return int(row[0])


def bump_session_epoch(conn: sqlite3.Connection, *, user_id: str) -> int:
    """Increment the user's ``session_epoch`` and return the new value.

    Called from ``/api/auth/logout`` (and from a future
    ``/api/auth/revoke-all-sessions`` endpoint). All cookies whose
    embedded epoch < the new epoch will be rejected by ``read_session``
    on the next request.

    Atomic via SQLite ``RETURNING`` (≥ 3.35) — no read-after-write race
    with another concurrent bump.

    Raises ``InvalidSession`` if the user does not exist.
    """
    row = conn.execute(
        "UPDATE users SET session_epoch = session_epoch + 1 "
        "WHERE id = ? RETURNING session_epoch",
        (user_id,),
    ).fetchone()
    if row is None:
        raise InvalidSession("user not found")
    conn.commit()
    return int(row[0])


def issue_session(
    user_id: str,
    *,
    secret: str,
    max_age_seconds: int = SESSION_MAX_AGE_SECONDS,
    conn: sqlite3.Connection | None = None,
) -> str:
    """Return a signed cookie value for ``user_id``.

    If ``conn`` is provided, the user's current ``session_epoch`` is
    embedded in the payload. If omitted, embeds ``epoch=0`` — equivalent
    to "fresh user," matched by any ``conn``-aware reader on a
    never-logged-out account. Production callers MUST pass ``conn``;
    the ``conn=None`` path exists for unit tests that don't seed the
    users table.

    Unknown ``user_id`` (no row in users): embeds ``epoch=0`` (does NOT
    raise). Tests issue sessions for synthetic ids; rejecting them here
    would force every test that issues a session to seed a users row
    first.
    """
    if not secret:
        raise ValueError("session secret must be non-empty")
    if conn is not None:
        e = _read_user_epoch(conn, user_id)
        epoch = e if e is not None else 0
    else:
        epoch = 0
    serializer = Serializer(secret, salt=_SALT)
    exp = (datetime.now(timezone.utc) + timedelta(seconds=max_age_seconds)).isoformat()
    raw = serializer.dumps({"user_id": user_id, "exp": exp, "epoch": epoch})
    # Add timestamp signing on top so we can enforce max_age at verify time.
    return _signer(secret).sign(raw.encode("utf-8")).decode("utf-8")


def read_session(
    token: str,
    *,
    secret: str,
    max_age_seconds: int = SESSION_MAX_AGE_SECONDS,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Parse a cookie value. Raises ``InvalidSession`` on any failure.

    If ``conn`` is provided, also verifies the embedded epoch matches the
    user's current ``session_epoch`` — i.e. enforces server-side
    revocation. Without ``conn``, the epoch check is skipped
    (backwards-compat for tests; production callers MUST pass ``conn``).
    """
    if not token:
        raise InvalidSession("empty session token")
    try:
        unsigned = _signer(secret).unsign(token, max_age=max_age_seconds)
    except SignatureExpired as e:
        raise InvalidSession("session expired") from e
    except BadSignature as e:
        raise InvalidSession("bad signature") from e
    try:
        serializer = Serializer(secret, salt=_SALT)
        payload = serializer.loads(unsigned.decode("utf-8"))
    except BadSignature as e:
        raise InvalidSession("bad payload") from e
    if not isinstance(payload, dict) or "user_id" not in payload:
        raise InvalidSession("malformed payload")
    if conn is not None:
        # Cookies issued before markland-bul have no `epoch` field; treat
        # missing-epoch as 0 so they remain valid until the user's first
        # logout (which bumps the column to 1, killing the old cookie).
        cookie_epoch = int(payload.get("epoch", 0))
        current = _read_user_epoch(conn, payload["user_id"])
        if current is None:
            # Cookie references a deleted account — revoke.
            raise InvalidSession("user not found")
        if cookie_epoch < current:
            raise InvalidSession("session revoked")
    return payload


# ---------------------------------------------------------------------------
# Request-scoped convenience helpers (Plan 6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionInfo:
    """Lightweight session object returned from `get_session`."""

    user_id: str
    display_name: str | None = None


def _default_secret() -> str:
    """Resolve the session secret from env when callers don't pass one."""
    return os.environ.get("MARKLAND_SESSION_SECRET", "")


def get_session(
    request,
    *,
    secret: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> SessionInfo | None:
    """Read the `mk_session` cookie from `request` and return a SessionInfo or None.

    Returns None on any failure — missing cookie, bad signature, expired
    session, or (when ``conn`` is provided) revoked session.
    Callers that need to distinguish failure modes should use
    ``read_session`` directly.
    """
    cookie = request.cookies.get(SESSION_COOKIE_NAME, "") if hasattr(request, "cookies") else ""
    if not cookie:
        return None
    use_secret = secret if secret is not None else _default_secret()
    if not use_secret:
        return None
    try:
        payload = read_session(cookie, secret=use_secret, conn=conn)
    except InvalidSession:
        return None
    uid = payload.get("user_id")
    if not isinstance(uid, str):
        return None
    return SessionInfo(user_id=uid, display_name=None)


def make_session_cookie_value(user_id: str, *, secret: str | None = None) -> str:
    """Convenience wrapper around `issue_session` that reads the secret from env."""
    use_secret = secret if secret is not None else _default_secret()
    return issue_session(user_id, secret=use_secret)


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


_CSRF_SALT = "mk.csrf.v1"
_CSRF_MAX_AGE_SECONDS = 60 * 60  # 1 hour


def make_csrf_token(user_id: str, *, secret: str | None = None) -> str:
    """Sign a short-lived CSRF token bound to `user_id`.

    Raises ValueError if the session secret is empty — refusing to sign
    with a placeholder mirrors `_signer()`'s behaviour and prevents
    accidentally accepting forged CSRF tokens in deployments that
    forgot to configure MARKLAND_SESSION_SECRET (markland-bfk / P1-C).
    """
    use_secret = secret if secret is not None else _default_secret()
    if not use_secret:
        raise ValueError("session secret must be non-empty")
    signer = TimestampSigner(use_secret, salt=_CSRF_SALT)
    return signer.sign(user_id.encode("utf-8")).decode("utf-8")


def verify_csrf_token(token: str, user_id: str, *, secret: str | None = None) -> bool:
    """Return True iff `token` is a valid CSRF token for `user_id`.

    Raises ValueError if the session secret is empty (markland-bfk /
    P1-C). Accepting a placeholder secret here would allow an attacker
    who knew about the placeholder fallback to forge CSRF tokens that
    `verify_csrf_token` would happily accept on a misconfigured prod.
    """
    if not token or not user_id:
        return False
    use_secret = secret if secret is not None else _default_secret()
    if not use_secret:
        raise ValueError("session secret must be non-empty")
    signer = TimestampSigner(use_secret, salt=_CSRF_SALT)
    try:
        unsigned = signer.unsign(token, max_age=_CSRF_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return False
    return hmac.compare_digest(unsigned.decode("utf-8"), user_id)
