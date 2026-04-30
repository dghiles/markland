"""Resolve `mk_session` cookies to `Principal`/`User` for non-/mcp browser routes.

Background: `PrincipalMiddleware` only runs for `/mcp` paths; the rate-limit
middleware fallback only resolves Bearer tokens. Cookie-auth'd browser
sessions never get `request.state.principal` populated. These helpers close
that gap so handlers like `/explore?view=mine` can recognize signed-in
browser users.

Two helpers, one resolver. Use `session_user` when you need fields that live
on the user record (email, display_name); use `session_principal` when you
specifically need the auth-layer abstraction. Both return None on any failure —
missing cookie, bad signature, expired session, or user deleted between
requests.
"""

from __future__ import annotations

import sqlite3

from starlette.requests import Request

from markland.service.auth import Principal
from markland.service.sessions import get_session
from markland.service.users import User, get_user


def session_user(
    request: Request,
    conn: sqlite3.Connection,
    *,
    secret: str | None = None,
) -> User | None:
    """Return the User for the request's session cookie, or None.

    Pass ``secret`` explicitly when the session secret is not available via
    the ``MARKLAND_SESSION_SECRET`` environment variable (e.g. in tests or
    when the app is started with an in-process secret).
    """
    info = get_session(request, secret=secret)
    if info is None:
        return None
    return get_user(conn, info.user_id)


def session_principal(
    request: Request,
    conn: sqlite3.Connection,
    *,
    secret: str | None = None,
) -> Principal | None:
    """Return a Principal for the request's session cookie, or None.

    Internally calls ``session_user`` and lifts the result into a Principal —
    so handlers that only need email/display_name should call ``session_user``
    directly to avoid a redundant Principal allocation.
    """
    user = session_user(request, conn, secret=secret)
    if user is None:
        return None
    return Principal(
        principal_id=user.id,
        principal_type="user",
        display_name=user.display_name,
        is_admin=user.is_admin,
        user_id=None,
    )
