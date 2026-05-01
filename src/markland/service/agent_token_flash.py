"""Signed flash cookie carrying a freshly-minted agent token plaintext.

After a user mints a new agent token via the /settings/agents form, we need
to surface the plaintext exactly once on the next page render. Putting the
plaintext in a query string (the prior implementation) leaks it into browser
history, Referer headers, and access logs. Instead, we sign the plaintext
into a short-TTL HttpOnly cookie, redirect to /settings/agents (no query
string), then read+clear the cookie on the next render.

Cookie name: `markland_agent_token_flash`. Payload: `{"plaintext": str}`,
signed via itsdangerous with the same `session_secret` used for `mk_session`.
TTL: 5 minutes — long enough to survive the redirect hop, short enough that
a forgotten tab can't leak the value indefinitely.
"""

from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

AGENT_TOKEN_FLASH_COOKIE_NAME = "markland_agent_token_flash"
AGENT_TOKEN_FLASH_MAX_AGE_SECONDS = 5 * 60
_SALT = "mk.agent_token_flash.v1"


class InvalidAgentTokenFlash(Exception):
    """Raised when a flash token is missing, tampered, or expired."""


def _serializer(secret: str) -> URLSafeTimedSerializer:
    if not secret:
        raise ValueError("session secret must be non-empty")
    return URLSafeTimedSerializer(secret, salt=_SALT)


def issue_agent_token_flash(*, secret: str, plaintext: str) -> str:
    if not plaintext:
        raise ValueError("plaintext must be non-empty")
    return _serializer(secret).dumps({"plaintext": plaintext})


def read_agent_token_flash(
    sealed: str,
    *,
    secret: str,
    max_age_seconds: int = AGENT_TOKEN_FLASH_MAX_AGE_SECONDS,
) -> str:
    if not sealed:
        raise InvalidAgentTokenFlash("empty cookie")
    try:
        payload = _serializer(secret).loads(sealed, max_age=max_age_seconds)
    except SignatureExpired as e:
        raise InvalidAgentTokenFlash("expired") from e
    except BadSignature as e:
        raise InvalidAgentTokenFlash("bad signature") from e
    if not isinstance(payload, dict):
        raise InvalidAgentTokenFlash("malformed payload")
    plaintext = payload.get("plaintext")
    if not isinstance(plaintext, str) or not plaintext:
        raise InvalidAgentTokenFlash("malformed payload")
    return plaintext
