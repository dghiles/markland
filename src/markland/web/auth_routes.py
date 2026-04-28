"""Magic-link auth: /api/auth/magic-link, /api/auth/verify, /api/auth/logout, /login, /verify."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from markland.service.email import EmailClient
from markland.service.magic_link import (
    InvalidMagicLink,
    read_magic_link_token,
    safe_return_to,
    send_magic_link,
)
from markland.service.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    issue_session,
)
from markland.service.users import upsert_user_by_email

_TEMPLATE_DIR = Path(__file__).parent / "templates"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class _MagicLinkRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class _VerifyRequest(BaseModel):
    token: str


def build_auth_router(
    *,
    db_conn: sqlite3.Connection,
    session_secret: str,
    base_url: str,
    email_client: EmailClient,
) -> APIRouter:
    router = APIRouter()
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    login_tpl = env.get_template("login.html")
    verify_sent_tpl = env.get_template("verify_sent.html")

    @router.get("/login", response_class=HTMLResponse)
    def login_page(next: str | None = None) -> HTMLResponse:
        safe_next = safe_return_to(next)
        return HTMLResponse(login_tpl.render(next=safe_next))

    @router.post("/api/auth/magic-link")
    async def magic_link(request: Request):
        if not session_secret:
            raise HTTPException(500, "session secret not configured")
        email: str | None = None
        return_to: str | None = None
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                body = await request.json()
            except Exception:
                body = {}
            if isinstance(body, dict):
                email = body.get("email")
                return_to = body.get("return_to")
        else:
            form = await request.form()
            email = form.get("email")
            return_to = form.get("return_to")
        if not email or not isinstance(email, str):
            raise HTTPException(400, "email required")
        email = email.strip().lower()
        if not _EMAIL_RE.match(email):
            raise HTTPException(400, "invalid email")
        dispatcher = getattr(request.app.state, "email_dispatcher", None)
        if dispatcher is None:
            # Defensive: should not happen (create_app always installs one).
            raise HTTPException(500, "email dispatcher not configured")
        try:
            send_magic_link(
                dispatcher=dispatcher,
                email=email,
                secret=session_secret,
                base_url=base_url,
                return_to=return_to if isinstance(return_to, str) else None,
            )
        except Exception:
            # Best-effort: enqueue shouldn't raise; if something else blows up
            # during URL construction, do not leak it to the caller.
            pass
        return JSONResponse({"ok": True})

    @router.post("/api/auth/verify")
    def verify(body: _VerifyRequest, response: Response) -> JSONResponse:
        if not session_secret:
            raise HTTPException(500, "session secret not configured")
        try:
            email = read_magic_link_token(body.token, secret=session_secret)
        except InvalidMagicLink as e:
            raise HTTPException(400, str(e)) from e
        user = upsert_user_by_email(db_conn, email)
        cookie = issue_session(user.id, secret=session_secret)
        resp = JSONResponse({"ok": True, "user_id": user.id})
        resp.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=cookie,
            max_age=SESSION_MAX_AGE_SECONDS,
            httponly=True,
            secure=base_url.startswith("https://"),
            samesite="lax",
            path="/",
        )
        return resp

    @router.get("/verify")
    def verify_page(request: Request, token: str, return_to: str | None = None):
        if not session_secret:
            raise HTTPException(500, "session secret not configured")
        try:
            email = read_magic_link_token(token, secret=session_secret)
        except InvalidMagicLink:
            return HTMLResponse(
                "<html><body style='font-family:system-ui;padding:2rem;'>"
                "<h1>Link expired or invalid</h1>"
                "<p><a href='/login'>Request a new one</a></p>"
                "</body></html>",
                status_code=400,
            )
        user = upsert_user_by_email(db_conn, email)
        cookie = issue_session(user.id, secret=session_secret)
        target = safe_return_to(return_to)
        pending = request.cookies.get("markland_pending_intent", "")
        if pending:
            target = "/resume"
        if target == "/":
            resp = HTMLResponse(verify_sent_tpl.render())
        else:
            resp = RedirectResponse(target, status_code=303)
        resp.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=cookie,
            max_age=SESSION_MAX_AGE_SECONDS,
            httponly=True,
            secure=base_url.startswith("https://"),
            samesite="lax",
            path="/",
        )
        return resp

    @router.post("/api/auth/logout")
    def logout() -> JSONResponse:
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return resp

    return router
