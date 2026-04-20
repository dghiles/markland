"""Authenticated /dashboard page — My docs + Shared with me + Saved."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from markland.db import (
    list_bookmarks_for_user,
    list_documents_for_owner,
    list_shared_with_principal,
)
from markland.service.auth import Principal
from markland.service.sessions import SESSION_COOKIE_NAME, InvalidSession, read_session


def build_router(*, conn: sqlite3.Connection, session_secret: str) -> APIRouter:
    r = APIRouter()
    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
        autoescape=select_autoescape(["html"]),
    )
    tpl = env.get_template("dashboard.html")

    def _owner_display(owner_id: str | None) -> str:
        if not owner_id:
            return "unknown"
        row = conn.execute(
            "SELECT display_name, email FROM users WHERE id = ?", (owner_id,)
        ).fetchone()
        if row is None:
            return owner_id
        return row[0] or row[1] or owner_id

    @r.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        # Prefer an already-resolved principal (PrincipalMiddleware on /mcp, or
        # test_principal_by_token injection). Fall back to the mk_session cookie
        # so plain web-session visitors can view /dashboard too.
        principal: Principal | None = getattr(request.state, "principal", None)
        user_id: str | None = None
        if principal is not None and principal.principal_type == "user":
            user_id = principal.principal_id
        else:
            cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
            if cookie and session_secret:
                try:
                    payload = read_session(cookie, secret=session_secret)
                    uid = payload.get("user_id")
                    if isinstance(uid, str):
                        user_id = uid
                except InvalidSession:
                    user_id = None

        if user_id is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)

        owned_docs = list_documents_for_owner(conn, user_id)
        shared_docs = list_shared_with_principal(conn, user_id)
        bookmarked_docs = list_bookmarks_for_user(conn, user_id=user_id)

        owned = [
            {
                "title": d.title,
                "share_token": d.share_token,
                "updated_at": d.updated_at,
            }
            for d in owned_docs
        ]
        shared = [
            {
                "title": d.title,
                "share_token": d.share_token,
                "updated_at": d.updated_at,
                "owner_display": _owner_display(d.owner_id),
            }
            for d in shared_docs
        ]
        bookmarks = [
            {
                "title": d.title,
                "share_token": d.share_token,
                "updated_at": d.updated_at,
                "owner_display": _owner_display(d.owner_id),
            }
            for d in bookmarked_docs
        ]
        return HTMLResponse(
            tpl.render(owned=owned, shared=shared, bookmarks=bookmarks)
        )

    return r


__all__ = ["build_router"]
