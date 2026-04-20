"""POST /d/{token}/fork, POST /d/{token}/bookmark, DELETE /d/{token}/bookmark."""

from __future__ import annotations

import sqlite3
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from markland.db import get_document_by_token
from markland.service.pending_intent import (
    PENDING_INTENT_COOKIE_NAME,
    PENDING_INTENT_MAX_AGE_SECONDS,
    issue_pending_intent,
)
from markland.service.save import fork_document, toggle_bookmark, user_can_view
from markland.service.sessions import SESSION_COOKIE_NAME, InvalidSession, read_session


def _current_user_id(request: Request, *, session_secret: str) -> str | None:
    """Return the authenticated user_id from the mk_session cookie, or None."""
    # First try request.state.principal (set by PrincipalMiddleware for /mcp routes
    # or by test_principal_by_token injection in tests).
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        if getattr(principal, "principal_type", None) == "user":
            return principal.principal_id

    # Fall back to reading the mk_session cookie directly (web session auth).
    cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
    if not cookie or not session_secret:
        return None
    try:
        payload = read_session(cookie, secret=session_secret)
    except InvalidSession:
        return None
    uid = payload.get("user_id")
    return uid if isinstance(uid, str) else None


def _set_pending_cookie(resp: RedirectResponse, cookie_value: str, *, secure: bool) -> None:
    resp.set_cookie(
        key=PENDING_INTENT_COOKIE_NAME,
        value=cookie_value,
        max_age=PENDING_INTENT_MAX_AGE_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def build_router(
    *,
    conn: sqlite3.Connection,
    session_secret: str,
    base_url: str,
) -> APIRouter:
    r = APIRouter()
    secure_cookie = base_url.startswith("https://")

    def _start_login_with_intent(action: str, share_token: str) -> RedirectResponse:
        cookie_raw = issue_pending_intent(
            secret=session_secret, action=action, share_token=share_token
        )
        resp = RedirectResponse(
            url=f"/login?next={quote('/resume', safe='')}", status_code=303
        )
        _set_pending_cookie(resp, cookie_raw, secure=secure_cookie)
        return resp

    @r.post("/d/{share_token}/fork")
    def fork_doc(share_token: str, request: Request):
        doc = get_document_by_token(conn, share_token)
        if doc is None:
            raise HTTPException(404, "document_not_found")

        user_id = _current_user_id(request, session_secret=session_secret)
        if user_id is None:
            return _start_login_with_intent("fork", share_token)

        try:
            new_doc = fork_document(conn, source=doc, new_owner_id=user_id)
        except ValueError:
            raise HTTPException(400, "cannot_fork_own_doc")
        except PermissionError:
            raise HTTPException(403, "source_not_viewable")

        return RedirectResponse(f"/d/{new_doc.share_token}", status_code=303)

    @r.post("/d/{share_token}/bookmark")
    def add_bookmark(share_token: str, request: Request):
        doc = get_document_by_token(conn, share_token)
        if doc is None:
            raise HTTPException(404, "document_not_found")

        user_id = _current_user_id(request, session_secret=session_secret)
        if user_id is None:
            return _start_login_with_intent("bookmark", share_token)

        if not user_can_view(conn, doc=doc, user_id=user_id):
            raise HTTPException(403, "source_not_viewable")

        toggle_bookmark(conn, user_id=user_id, doc_id=doc.id, bookmarked=True)
        return RedirectResponse(f"/d/{share_token}", status_code=303)

    @r.delete("/d/{share_token}/bookmark")
    def remove_bookmark_route(share_token: str, request: Request):
        user_id = _current_user_id(request, session_secret=session_secret)
        if user_id is None:
            raise HTTPException(401, "login_required")

        doc = get_document_by_token(conn, share_token)
        if doc is None:
            raise HTTPException(404, "document_not_found")

        toggle_bookmark(conn, user_id=user_id, doc_id=doc.id, bookmarked=False)
        return JSONResponse({"bookmarked": False})

    return r
