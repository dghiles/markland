"""Signed session cookies via itsdangerous.

Cookie name: `mk_session`. Payload: `{"user_id": str, "exp": iso8601}`.
Signed with `MARKLAND_SESSION_SECRET`. 30-day default lifetime.
Rotating the secret invalidates all outstanding sessions.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from itsdangerous.serializer import Serializer

SESSION_COOKIE_NAME = "mk_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days
_SALT = "mk.session.v1"


class InvalidSession(Exception):
    """Raised when a session cookie is missing, tampered, or expired."""


def _signer(secret: str) -> TimestampSigner:
    if not secret:
        raise ValueError("session secret must be non-empty")
    return TimestampSigner(secret, salt=_SALT)


def issue_session(
    user_id: str,
    *,
    secret: str,
    max_age_seconds: int = SESSION_MAX_AGE_SECONDS,
) -> str:
    """Return a signed cookie value for `user_id`."""
    if not secret:
        raise ValueError("session secret must be non-empty")
    serializer = Serializer(secret, salt=_SALT)
    exp = (datetime.now(timezone.utc) + timedelta(seconds=max_age_seconds)).isoformat()
    raw = serializer.dumps({"user_id": user_id, "exp": exp})
    # Add timestamp signing on top so we can enforce max_age at verify time.
    return _signer(secret).sign(raw.encode("utf-8")).decode("utf-8")


def read_session(
    token: str,
    *,
    secret: str,
    max_age_seconds: int = SESSION_MAX_AGE_SECONDS,
) -> dict:
    """Parse a cookie value. Raises `InvalidSession` on any failure."""
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


def get_session(request, *, secret: str | None = None) -> SessionInfo | None:
    """Read the `mk_session` cookie from `request` and return a SessionInfo or None.

    Returns None on any failure — missing cookie, bad signature, expired session.
    Callers that need to distinguish failure modes should use `read_session` directly.
    """
    cookie = request.cookies.get(SESSION_COOKIE_NAME, "") if hasattr(request, "cookies") else ""
    if not cookie:
        return None
    use_secret = secret if secret is not None else _default_secret()
    if not use_secret:
        return None
    try:
        payload = read_session(cookie, secret=use_secret)
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
    """Sign a short-lived CSRF token bound to `user_id`."""
    use_secret = secret if secret is not None else _default_secret()
    if not use_secret:
        # Sign with a placeholder; verification will still require matching secret.
        use_secret = "dev-placeholder"
    signer = TimestampSigner(use_secret, salt=_CSRF_SALT)
    return signer.sign(user_id.encode("utf-8")).decode("utf-8")


def verify_csrf_token(token: str, user_id: str, *, secret: str | None = None) -> bool:
    """Return True iff `token` is a valid CSRF token for `user_id`."""
    if not token or not user_id:
        return False
    use_secret = secret if secret is not None else _default_secret()
    if not use_secret:
        use_secret = "dev-placeholder"
    signer = TimestampSigner(use_secret, salt=_CSRF_SALT)
    try:
        unsigned = signer.unsign(token, max_age=_CSRF_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return False
    return hmac.compare_digest(unsigned.decode("utf-8"), user_id)
