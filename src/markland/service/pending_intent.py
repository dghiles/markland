"""Signed cookie for 'resume this action after login' on the save-to-account flow.

Cookie name: `markland_pending_intent`. Payload: `{action, share_token}`,
signed via itsdangerous with the same `session_secret` used for `mk_session`.
TTL: 30 minutes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

PENDING_INTENT_COOKIE_NAME = "markland_pending_intent"
PENDING_INTENT_MAX_AGE_SECONDS = 30 * 60
_SALT = "mk.pending_intent.v1"

_VALID_ACTIONS = ("fork", "bookmark")


class InvalidPendingIntent(Exception):
    """Raised when a pending-intent token is missing, tampered, or expired."""


@dataclass(frozen=True)
class PendingIntent:
    action: Literal["fork", "bookmark"]
    share_token: str


def _serializer(secret: str) -> URLSafeTimedSerializer:
    if not secret:
        raise ValueError("session secret must be non-empty")
    return URLSafeTimedSerializer(secret, salt=_SALT)


def issue_pending_intent(*, secret: str, action: str, share_token: str) -> str:
    if action not in _VALID_ACTIONS:
        raise ValueError(f"invalid action: {action!r}")
    if not share_token:
        raise ValueError("share_token must be non-empty")
    return _serializer(secret).dumps({"action": action, "share_token": share_token})


def read_pending_intent(
    token: str,
    *,
    secret: str,
    max_age_seconds: int = PENDING_INTENT_MAX_AGE_SECONDS,
) -> PendingIntent:
    if not token:
        raise InvalidPendingIntent("empty token")
    try:
        payload = _serializer(secret).loads(token, max_age=max_age_seconds)
    except SignatureExpired as e:
        raise InvalidPendingIntent("expired") from e
    except BadSignature as e:
        raise InvalidPendingIntent("bad signature") from e
    if not isinstance(payload, dict):
        raise InvalidPendingIntent("malformed payload")
    action = payload.get("action")
    share_token = payload.get("share_token")
    if action not in _VALID_ACTIONS or not isinstance(share_token, str) or not share_token:
        raise InvalidPendingIntent("malformed payload")
    return PendingIntent(action=action, share_token=share_token)
