"""Resolve `mk_session` cookies to `Principal` for non-/mcp browser routes.

Background: `PrincipalMiddleware` only runs for `/mcp` paths; the rate-limit
middleware fallback only resolves Bearer tokens. Cookie-auth'd browser
sessions never get `request.state.principal` populated. This helper closes
that gap so handlers like `/explore?view=mine` can recognize signed-in
browser users.

Returns None on any failure — missing cookie, bad signature, expired
session, or user deleted between requests.
"""

from __future__ import annotations

import sqlite3

from starlette.requests import Request

from markland.service.auth import Principal
from markland.service.sessions import get_session
from markland.service.users import get_user


def session_principal(
    request: Request,
    conn: sqlite3.Connection,
) -> Principal | None:
    """Return a Principal for the request's session cookie, or None."""
    info = get_session(request)
    if info is None:
        return None
    user = get_user(conn, info.user_id)
    if user is None:
        return None
    return Principal(
        principal_id=user.id,
        principal_type="user",
        display_name=user.display_name,
        is_admin=user.is_admin,
        user_id=None,
    )
