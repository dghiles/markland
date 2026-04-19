"""HTTP routes for invite creation, revocation, acceptance, and the landing page."""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from jinja2 import Environment
from pydantic import BaseModel, Field

from markland.service import email_templates
from markland.service.email import EmailClient
from markland.service.invites import (
    accept_invite,
    create_invite,
    resolve_invite,
    revoke_invite,
)
from markland.service.sessions import (
    SESSION_COOKIE_NAME,
    InvalidSession,
    read_session,
)

logger = logging.getLogger("markland.invites")


class _CreateInviteBody(BaseModel):
    level: str = Field(pattern="^(view|edit)$")
    single_use: bool = True
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


def build_invite_router(
    *,
    db_conn: sqlite3.Connection,
    base_url: str,
    jinja_env: Environment,
    email_client: EmailClient,
    session_secret: str,
) -> APIRouter:
    """Return a router carrying all invite HTTP + HTML routes."""
    router = APIRouter()
    invite_tpl = jinja_env.get_template("invite.html")

    def _session_user_id(request: Request) -> str:
        cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
        try:
            payload = read_session(cookie, secret=session_secret)
        except InvalidSession as e:
            raise HTTPException(status_code=401, detail="unauthenticated") from e
        return payload["user_id"]

    def _optional_user_id(request: Request) -> str | None:
        cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
        if not cookie:
            return None
        try:
            payload = read_session(cookie, secret=session_secret)
        except InvalidSession:
            return None
        uid = payload.get("user_id")
        if not isinstance(uid, str):
            return None
        # Confirm user still exists.
        row = db_conn.execute("SELECT id FROM users WHERE id = ?", (uid,)).fetchone()
        return row[0] if row else None

    def _require_owner(doc_id: str, user_id: str) -> None:
        row = db_conn.execute(
            "SELECT owner_id FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="not_found")
        if row[0] != user_id:
            raise HTTPException(status_code=404, detail="not_found")

    @router.post("/api/docs/{doc_id}/invites", status_code=201)
    def http_create_invite(
        doc_id: str,
        body: _CreateInviteBody,
        request: Request,
    ):
        user_id = _session_user_id(request)
        _require_owner(doc_id, user_id)
        try:
            result = create_invite(
                db_conn,
                doc_id=doc_id,
                created_by_user_id=user_id,
                level=body.level,
                base_url=base_url,
                single_use=body.single_use,
                expires_in_days=body.expires_in_days,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "id": result.id,
            "url": result.url,
            "level": result.level,
            "expires_at": result.expires_at,
        }

    @router.delete("/api/invites/{invite_id}", status_code=204)
    def http_delete_invite(invite_id: str, request: Request):
        user_id = _session_user_id(request)
        row = db_conn.execute(
            "SELECT created_by FROM invites WHERE id = ?", (invite_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="not_found")
        if row[0] != user_id:
            raise HTTPException(status_code=404, detail="not_found")
        try:
            revoke_invite(db_conn, invite_id=invite_id, owner_user_id=user_id)
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=404, detail="not_found") from exc
        return Response(status_code=204)

    @router.get("/invite/{token}", response_class=HTMLResponse)
    def invite_landing(token: str, request: Request):
        user_id = _optional_user_id(request)
        inv = resolve_invite(db_conn, token)
        if inv is None:
            return HTMLResponse(_render_invite_gone(), status_code=410)

        doc_row = db_conn.execute(
            "SELECT title, share_token FROM documents WHERE id = ?", (inv.doc_id,)
        ).fetchone()
        if doc_row is None:
            return HTMLResponse(_render_invite_gone(), status_code=410)
        inviter_row = db_conn.execute(
            "SELECT display_name, email FROM users WHERE id = ?", (inv.created_by,)
        ).fetchone()
        if inviter_row is None:
            inviter_name = "Someone"
        else:
            inviter_name = inviter_row[0] or inviter_row[1] or "Someone"

        return HTMLResponse(
            invite_tpl.render(
                token=token,
                doc_title=doc_row[0],
                doc_share_token=doc_row[1],
                inviter_name=inviter_name,
                level=inv.level,
                signed_in=(user_id is not None),
            )
        )

    @router.post("/api/invites/{token}/accept")
    def http_accept_invite(token: str, request: Request):
        user_id = _session_user_id(request)
        inv = resolve_invite(db_conn, token)
        if inv is None:
            raise HTTPException(status_code=410, detail="gone")
        grant = accept_invite(db_conn, invite_token=token, user_id=user_id)
        if grant is None:
            raise HTTPException(status_code=410, detail="gone")

        dispatcher = getattr(request.app.state, "email_dispatcher", None)
        _notify_creator(
            db_conn=db_conn,
            email_client=email_client,
            dispatcher=dispatcher,
            invite_created_by=inv.created_by,
            accepter_user_id=user_id,
            doc_id=inv.doc_id,
            base_url=base_url,
        )
        return {"doc_id": grant.doc_id, "level": grant.level}

    return router


def _render_invite_gone() -> str:
    return (
        "<html><body style='font-family:system-ui;padding:2rem;max-width:40rem;'>"
        "<h1>This invite is no longer valid</h1>"
        "<p>It may have been revoked, fully used, or expired. "
        "Ask the person who sent it for a new one.</p>"
        "</body></html>"
    )


def _notify_creator(
    *,
    db_conn: sqlite3.Connection,
    email_client: EmailClient,
    dispatcher,
    invite_created_by: str,
    accepter_user_id: str,
    doc_id: str,
    base_url: str,
) -> None:
    creator = db_conn.execute(
        "SELECT email FROM users WHERE id = ?", (invite_created_by,)
    ).fetchone()
    accepter = db_conn.execute(
        "SELECT display_name, email FROM users WHERE id = ?", (accepter_user_id,)
    ).fetchone()
    doc = db_conn.execute(
        "SELECT title, share_token FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if not creator or not accepter or not doc:
        return
    accepter_name = accepter[0] if accepter[0] else accepter[1]

    rendered = email_templates.invite_accepted(
        accepter_display=accepter_name,
        doc_title=doc[0],
        doc_url=f"{base_url}/d/{doc[1]}",
    )

    # Prefer dispatcher (Plan 7 canonical path). Fall back to direct client send
    # only if no dispatcher is present.
    if dispatcher is not None:
        try:
            dispatcher.enqueue(
                to=creator[0],
                subject=rendered["subject"],
                html=rendered["html"],
                text=rendered.get("text"),
                metadata={"template": "invite_accepted", "doc_id": doc_id},
            )
        except Exception as exc:
            logger.warning("invite accept email enqueue failed: %s", exc)
        return

    try:
        email_client.send(
            to=creator[0],
            subject=rendered["subject"],
            html=rendered["html"],
        )
    except Exception as exc:
        logger.warning("invite accept email failed: %s", exc)


def _h(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


__all__ = ["build_invite_router"]
