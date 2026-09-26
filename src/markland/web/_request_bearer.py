"""Resolve a request's Bearer token at most once per request.

RateLimitMiddleware (outermost) resolves the bearer on every path for
rate-limit tiering; PrincipalMiddleware (inner, on /mcp and /admin/)
needs the same answer to gate the request. A resolve of an unknown or
legacy-shape token is a full Argon2id scan of the tokens table, so the
outcome is memoized in ``request.state``, which wraps the per-request
``scope["state"]`` dict that every BaseHTTPMiddleware layer shares. The
memo includes an explicit invalid verdict, so a bad token is scanned
once per request instead of twice.

Either middleware may run without the other (RateLimit alone on an
unprotected path, PrincipalMiddleware alone in a bare app); whichever
asks first does the resolve.
"""

from __future__ import annotations

import sqlite3

from starlette.requests import Request

from markland.service.auth import Principal, resolve_token

_STATE_ATTR = "bearer_resolution"


class _ResolvedInvalid:
    """Memo value for "this request's bearer was resolved and is invalid"."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "RESOLVED_INVALID"


RESOLVED_INVALID = _ResolvedInvalid()


def resolve_request_bearer(
    request: Request, conn: sqlite3.Connection
) -> Principal | None:
    """Return the Principal for this request's Bearer token, or None.

    None means no bearer header, or a bearer that did not resolve. An
    exception from ``resolve_token`` propagates and is NOT memoized, so a
    later caller in the same request retries rather than turning a
    transient DB error into a 401.
    """
    memo = getattr(request.state, _STATE_ATTR, None)
    if memo is RESOLVED_INVALID:
        return None
    if memo is not None:
        return memo

    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    principal = resolve_token(conn, header[7:].strip())
    setattr(
        request.state,
        _STATE_ATTR,
        principal if principal is not None else RESOLVED_INVALID,
    )
    return principal
