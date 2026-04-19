"""HTTP API for presence at /api/docs/{doc_id}/presence.

All three endpoints require an authenticated principal. The principal is
resolved from:
  - `request.state.principal` (set by PrincipalMiddleware for /mcp callers
    or the test injector), OR
  - the `mk_session` cookie (for the hosted web path).
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Body, HTTPException, Request

from markland.service import docs as docs_svc
from markland.service import presence
from markland.service.auth import Principal
from markland.service.permissions import NotFound, PermissionDenied
from markland.service.sessions import (
    SESSION_COOKIE_NAME,
    InvalidSession,
    read_session,
)
from markland.service.users import get_user


def _principal_from_session(
    request: Request, conn: sqlite3.Connection, session_secret: str
) -> Principal | None:
    if not session_secret:
        return None
    cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
    if not cookie:
        return None
    try:
        payload = read_session(cookie, secret=session_secret)
    except InvalidSession:
        return None
    user = get_user(conn, payload.get("user_id", ""))
    if user is None:
        return None
    return Principal(
        principal_id=user.id,
        principal_type="user",
        display_name=user.display_name,
        is_admin=bool(getattr(user, "is_admin", False)),
        user_id=user.id,
    )


def build_presence_router(
    *,
    db_conn: sqlite3.Connection,
    session_secret: str = "",
) -> APIRouter:
    router = APIRouter(prefix="/api/docs", tags=["presence"])

    def _require_principal(request: Request) -> Principal:
        principal = getattr(request.state, "principal", None)
        if principal is None:
            principal = _principal_from_session(request, db_conn, session_secret)
        if principal is None:
            raise HTTPException(
                status_code=401, detail={"error": "unauthenticated"}
            )
        return principal

    def _check_view(principal: Principal, doc_id: str) -> None:
        try:
            docs_svc.get(db_conn, principal, doc_id, base_url="")
        except NotFound:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionDenied:
            raise HTTPException(status_code=404, detail={"error": "not_found"})

    @router.post("/{doc_id}/presence")
    def set_presence(doc_id: str, request: Request, body: dict = Body(default={})):
        principal = _require_principal(request)
        status = body.get("status")
        note = body.get("note")
        if status not in ("reading", "editing"):
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_status",
                        "reason": "must be 'reading' or 'editing'"},
            )
        if note is not None and (not isinstance(note, str) or len(note) > 500):
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_note"},
            )
        _check_view(principal, doc_id)
        try:
            return presence.set_status(
                db_conn,
                doc_id=doc_id,
                principal=principal,
                status=status,
                note=note,
            )
        except presence.PresenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.delete("/{doc_id}/presence")
    def clear_presence(doc_id: str, request: Request):
        principal = _require_principal(request)
        return presence.clear_status(
            db_conn, doc_id=doc_id, principal=principal
        )

    @router.get("/{doc_id}/presence")
    def list_presence(doc_id: str, request: Request):
        principal = _require_principal(request)
        _check_view(principal, doc_id)
        actives = presence.list_active(db_conn, doc_id=doc_id)
        return [
            {
                "principal_id": a.principal_id,
                "principal_type": a.principal_type,
                "display_name": a.display_name,
                "status": a.status,
                "note": a.note,
                "updated_at": a.updated_at,
            }
            for a in actives
        ]

    return router
