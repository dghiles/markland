"""Magic-link login: itsdangerous-signed single-use tokens, delivered via dispatcher.

Token carries the target email; validity = 15 minutes. "Single-use" is enforced at
the verify route by issuing a session immediately on first success; the token itself
has no server-side state (the 15-minute expiry is the belt-and-braces).
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from urllib.parse import urlencode

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from markland.service import email_templates

logger = logging.getLogger("markland.magic_link")

MAGIC_LINK_MAX_AGE_SECONDS = 15 * 60
_SALT = "mk.magiclink.v1"


class InvalidMagicLink(Exception):
    """Raised when a magic-link token is missing, tampered, or expired."""


def _serializer(secret: str) -> URLSafeTimedSerializer:
    if not secret:
        raise ValueError("session secret must be non-empty")
    return URLSafeTimedSerializer(secret, salt=_SALT)


def safe_return_to(raw: str | None) -> str:
    """Whitelist `return_to` values to avoid open redirects."""
    if not raw:
        return "/"
    if not raw.startswith("/") or raw.startswith("//"):
        return "/"
    return raw


def issue_magic_link_token(
    email: str,
    *,
    secret: str,
    max_age_seconds: int = MAGIC_LINK_MAX_AGE_SECONDS,  # kept for symmetry; serializer ignores
) -> str:
    """Sign a token carrying this email plus a unique JTI.

    The JTI is what makes server-side single-use enforcement possible — it
    gives us a stable per-issuance key to record in `magic_link_consumed`.
    """
    payload = {"email": email.strip().lower(), "jti": uuid.uuid4().hex}
    return _serializer(secret).dumps(payload)


def read_magic_link_token(
    token: str,
    *,
    secret: str,
    max_age_seconds: int = MAGIC_LINK_MAX_AGE_SECONDS,
) -> str:
    """Return the email encoded in `token`. Raises `InvalidMagicLink`.

    NOTE: This decodes without enforcing single-use. Production verify routes
    must use `consume_magic_link_token` instead. This helper is kept for tests
    and debugging.
    """
    try:
        payload = _serializer(secret).loads(token, max_age=max_age_seconds)
    except SignatureExpired as e:
        raise InvalidMagicLink("magic link expired") from e
    except BadSignature as e:
        raise InvalidMagicLink("invalid magic link") from e
    if not isinstance(payload, dict) or "email" not in payload:
        raise InvalidMagicLink("invalid magic link payload")
    email = payload["email"]
    if not isinstance(email, str):
        raise InvalidMagicLink("invalid magic link payload")
    return email


def consume_magic_link_token(
    token: str,
    *,
    conn: sqlite3.Connection,
    secret: str,
    max_age_seconds: int = MAGIC_LINK_MAX_AGE_SECONDS,
) -> str:
    """Verify and atomically consume a magic-link token.

    On success: records the JTI in `magic_link_consumed` and returns the
    email. On replay: raises `InvalidMagicLink("magic link already used")`.
    On bad signature / expiry: raises `InvalidMagicLink` with the
    appropriate message.

    Also opportunistically GCs rows older than `max_age_seconds`. Since the
    signature check rejects tokens older than that anyway, GC'd rows can
    never collide with a valid future consume.
    """
    try:
        payload = _serializer(secret).loads(token, max_age=max_age_seconds)
    except SignatureExpired as e:
        raise InvalidMagicLink("magic link expired") from e
    except BadSignature as e:
        raise InvalidMagicLink("invalid magic link") from e
    if not isinstance(payload, dict):
        raise InvalidMagicLink("invalid magic link payload")
    email = payload.get("email")
    jti = payload.get("jti")
    if not isinstance(email, str) or not isinstance(jti, str):
        raise InvalidMagicLink("invalid magic link payload")

    now = int(time.time())
    cutoff = now - max_age_seconds

    # Opportunistic GC. Cheap (indexed scan, ~one row per consume in the worst case).
    conn.execute(
        "DELETE FROM magic_link_consumed WHERE consumed_at < ?",
        (cutoff,),
    )

    # Atomic single-use: INSERT OR IGNORE returns rowcount=0 if the JTI already exists.
    cur = conn.execute(
        "INSERT OR IGNORE INTO magic_link_consumed (jti, email, consumed_at) "
        "VALUES (?, ?, ?)",
        (jti, email, now),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise InvalidMagicLink("magic link already used")
    return email


def send_magic_link(
    *,
    dispatcher,
    email: str,
    secret: str,
    base_url: str,
    return_to: str | None = None,
    expires_in_minutes: int = 15,
) -> str:
    """Issue a magic-link token, enqueue the email, return the token for testing.

    Synchronous: `dispatcher.enqueue(...)` is a sync non-blocking call that pushes
    the item onto an asyncio.Queue and returns immediately. Plan 2's sync route
    handler continues to call this directly.
    """
    normalized = email.strip().lower()
    token = issue_magic_link_token(normalized, secret=secret)
    params = {"token": token}
    safe_rt = safe_return_to(return_to)
    if safe_rt != "/":
        params["return_to"] = safe_rt
    verify_url = f"{base_url.rstrip('/')}/verify?" + urlencode(params)

    rendered = email_templates.magic_link(
        email=normalized,
        verify_url=verify_url,
        expires_in_minutes=expires_in_minutes,
    )
    try:
        dispatcher.enqueue(
            to=normalized,
            subject=rendered["subject"],
            html=rendered["html"],
            text=rendered.get("text"),
            metadata={"template": "magic_link"},
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("Failed to enqueue magic_link email to %s: %s", normalized, exc)
    else:
        logger.info("Magic-link email enqueued for %s", normalized)
    return token
