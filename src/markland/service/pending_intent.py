"""Signed cookie for 'resume this action after login' on the save-to-account flow.

Cookie name: `markland_pending_intent`. Payload: `{action, share_token}`,
signed via itsdangerous with the same `session_secret` used for `mk_session`.
TTL: 30 minutes — long enough for an email magic link to arrive and be clicked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from itsdangerous import BadSignature, SignatureExpired
from itsdangerous.serializer import Serializer
from itsdangerous import TimestampSigner

PENDING_INTENT_COOKIE_NAME = "markland_pending_intent"
PENDING_INTENT_MAX_AGE_SECONDS = 30 * 60  # 30 minutes
_SALT = "mk.pending_intent.v1"

_VALID_ACTIONS = ("fork", "bookmark")


class InvalidPendingIntent(Exception):
    """Raised when a pending-intent token is missing, tampered, or expired."""


@dataclass(frozen=True)
class PendingIntent:
    action: Literal["fork", "bookmark"]
    share_token: str


def _signer(secret: str) -> TimestampSigner:
    if not secret:
        raise ValueError("session secret must be non-empty")
    return TimestampSigner(secret, salt=_SALT)


def issue_pending_intent(
    *,
    secret: str,
    action: str,
    share_token: str,
) -> str:
    """Return a signed cookie value carrying `{action, share_token}`."""
    if action not in _VALID_ACTIONS:
        raise ValueError(f"invalid action: {action!r}")
    if not share_token:
        raise ValueError("share_token must be non-empty")
    serializer = Serializer(secret, salt=_SALT)
    raw = serializer.dumps({"action": action, "share_token": share_token})
    return _signer(secret).sign(raw.encode("utf-8")).decode("utf-8")


def read_pending_intent(
    token: str,
    *,
    secret: str,
    max_age_seconds: int = PENDING_INTENT_MAX_AGE_SECONDS,
) -> PendingIntent:
    """Parse a cookie. Raises `InvalidPendingIntent` on any failure."""
    if not token:
        raise InvalidPendingIntent("empty token")
    try:
        unsigned = _signer(secret).unsign(token, max_age=max_age_seconds)
    except SignatureExpired as e:
        raise InvalidPendingIntent("expired") from e
    except BadSignature as e:
        raise InvalidPendingIntent("bad signature") from e
    try:
        serializer = Serializer(secret, salt=_SALT)
        payload = serializer.loads(unsigned.decode("utf-8"))
    except BadSignature as e:
        raise InvalidPendingIntent("bad payload") from e
    if not isinstance(payload, dict):
        raise InvalidPendingIntent("malformed payload")
    action = payload.get("action")
    share_token = payload.get("share_token")
    if action not in _VALID_ACTIONS or not isinstance(share_token, str) or not share_token:
        raise InvalidPendingIntent("malformed payload")
    return PendingIntent(action=action, share_token=share_token)
