"""Session-authed identity endpoints: /api/me, /api/tokens, /settings/tokens.

All routes here read the `mk_session` cookie via `service.sessions.read_session`.
Unlike `/mcp`, these are NOT gated by PrincipalMiddleware — sessions, not bearers.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from markland.service.auth import (
    create_user_token,
    list_tokens,
    revoke_token,
)
from markland.service.sessions import (
    SESSION_COOKIE_NAME,
    InvalidSession,
    read_session,
)
from markland.service.users import User, get_user
from markland.web.render_helpers import render_with_nav

_TEMPLATE_DIR = Path(__file__).parent / "templates"


class _CreateTokenRequest(BaseModel):
    label: str = Field(min_length=1, max_length=200)


def _require_session_user(
    request: Request,
    conn: sqlite3.Connection,
    session_secret: str,
) -> User:
    cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
    try:
        payload = read_session(cookie, secret=session_secret, conn=conn)
    except InvalidSession as e:
        raise HTTPException(401, "unauthenticated") from e
    user = get_user(conn, payload["user_id"])
    if user is None:
        raise HTTPException(401, "unauthenticated")
    return user


def build_identity_router(
    *,
    db_conn: sqlite3.Connection,
    session_secret: str,
    base_url: str = "",
) -> APIRouter:
    router = APIRouter()
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    settings_tpl = env.get_template("settings_tokens.html")

    @router.get("/api/me")
    def me(request: Request) -> JSONResponse:
        user = _require_session_user(request, db_conn, session_secret)
        tokens = list_tokens(db_conn, user_id=user.id)
        return JSONResponse({
            "user_id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "is_admin": user.is_admin,
            "tokens": [
                {
                    "id": t.id,
                    "label": t.label,
                    "created_at": t.created_at,
                    "last_used_at": t.last_used_at,
                }
                for t in tokens
            ],
        })

    @router.post("/api/tokens")
    def create_token(request: Request, body: _CreateTokenRequest) -> JSONResponse:
        user = _require_session_user(request, db_conn, session_secret)
        token_id, plaintext = create_user_token(
            db_conn, user_id=user.id, label=body.label
        )
        return JSONResponse({
            "id": token_id,
            "label": body.label,
            "token": plaintext,
        })

    @router.delete("/api/tokens/{token_id}")
    def delete_token(request: Request, token_id: str) -> JSONResponse:
        user = _require_session_user(request, db_conn, session_secret)
        ok = revoke_token(db_conn, token_id=token_id, user_id=user.id)
        if not ok:
            raise HTTPException(404, "token not found")
        return JSONResponse({"ok": True})

    @router.get("/settings/tokens", response_class=HTMLResponse)
    def settings_tokens(request: Request):
        cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
        try:
            payload = read_session(cookie, secret=session_secret, conn=db_conn)
        except InvalidSession:
            return RedirectResponse("/login", status_code=303)
        user = get_user(db_conn, payload["user_id"])
        if user is None:
            return RedirectResponse("/login", status_code=303)
        tokens = list_tokens(db_conn, user_id=user.id)
        return HTMLResponse(
            render_with_nav(
                settings_tpl, request, db_conn,
                base_url=base_url, secret=session_secret,
                user=user, tokens=tokens,
                signed_in_user={"email": user.email},
            )
        )

    return router
