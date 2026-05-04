"""HTTP routes for agent management under /api/agents."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from markland.service import agents as agents_svc
from markland.service import auth as auth_svc
from markland.service.agent_token_flash import (
    AGENT_TOKEN_FLASH_COOKIE_NAME,
    AGENT_TOKEN_FLASH_MAX_AGE_SECONDS,
    InvalidAgentTokenFlash,
    issue_agent_token_flash,
    read_agent_token_flash,
)
from markland.service.sessions import (
    SESSION_COOKIE_NAME,
    InvalidSession,
    read_session,
)
from markland.service.users import User, get_user
from markland.web.render_helpers import render_with_nav

_TEMPLATE_DIR = Path(__file__).parent / "templates"


class CreateAgentBody(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)


class CreateAgentTokenBody(BaseModel):
    label: str = Field(min_length=1, max_length=200)


def build_agents_router(
    db_conn: sqlite3.Connection,
    *,
    session_secret: str,
    base_url: str = "",
) -> APIRouter:
    router = APIRouter(prefix="/api/agents", tags=["agents"])

    def _session_user(request: Request) -> User:
        cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
        try:
            payload = read_session(cookie, secret=session_secret, conn=db_conn)
        except InvalidSession as e:
            raise HTTPException(status_code=401, detail="unauthenticated") from e
        user = get_user(db_conn, payload["user_id"])
        if user is None:
            raise HTTPException(status_code=401, detail="unauthenticated")
        return user

    @router.get("")
    def list_agents_endpoint(user: User = Depends(_session_user)):
        agents = agents_svc.list_agents(db_conn, owner_user_id=user.id)
        return [
            {
                "id": a.id,
                "display_name": a.display_name,
                "owner_type": a.owner_type,
                "owner_id": a.owner_id,
                "created_at": a.created_at,
            }
            for a in agents
        ]

    @router.post("", status_code=status.HTTP_201_CREATED)
    def create_agent_endpoint(
        body: CreateAgentBody, user: User = Depends(_session_user)
    ):
        try:
            agent = agents_svc.create_agent(
                db_conn,
                owner_user_id=user.id,
                display_name=body.display_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "id": agent.id,
            "display_name": agent.display_name,
            "owner_type": agent.owner_type,
            "owner_id": agent.owner_id,
            "created_at": agent.created_at,
        }

    @router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
    def revoke_agent_endpoint(
        agent_id: str, user: User = Depends(_session_user)
    ):
        try:
            agents_svc.revoke_agent(db_conn, agent_id, owner_user_id=user.id)
        except LookupError:
            raise HTTPException(status_code=404, detail="not_found")
        except PermissionError:
            raise HTTPException(status_code=403, detail="forbidden")
        return None

    @router.post("/{agent_id}/tokens", status_code=status.HTTP_201_CREATED)
    def create_agent_token_endpoint(
        agent_id: str,
        body: CreateAgentTokenBody,
        user: User = Depends(_session_user),
    ):
        try:
            tok_id, plaintext = auth_svc.create_agent_token(
                db_conn,
                agent_id=agent_id,
                owner_user_id=user.id,
                label=body.label,
            )
        except LookupError:
            raise HTTPException(status_code=404, detail="not_found")
        except PermissionError:
            raise HTTPException(status_code=403, detail="forbidden")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": tok_id, "plaintext": plaintext, "label": body.label}

    @router.delete(
        "/{agent_id}/tokens/{token_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def revoke_agent_token_endpoint(
        agent_id: str,
        token_id: str,
        user: User = Depends(_session_user),
    ):
        row = db_conn.execute(
            "SELECT t.id FROM tokens t "
            "JOIN agents a ON a.id = t.principal_id "
            "WHERE t.id = ? AND t.principal_type = 'agent' "
            "  AND a.owner_type = 'user' AND a.owner_id = ? AND a.id = ?",
            (token_id, user.id, agent_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="not_found")
        db_conn.execute(
            "UPDATE tokens SET revoked_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), token_id),
        )
        db_conn.commit()
        return None

    # --- HTML page routes under /settings/agents ---

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    settings_tpl = env.get_template("settings_agents.html")

    html_router = APIRouter()

    def _session_user_or_none(request: Request) -> User | None:
        cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
        try:
            payload = read_session(cookie, secret=session_secret, conn=db_conn)
        except InvalidSession:
            return None
        return get_user(db_conn, payload["user_id"])

    @html_router.get("/settings/agents", response_class=HTMLResponse)
    def settings_agents(request: Request):
        user = _session_user_or_none(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        agents = agents_svc.list_agents(db_conn, owner_user_id=user.id)

        new_token: str | None = None
        sealed = request.cookies.get(AGENT_TOKEN_FLASH_COOKIE_NAME, "")
        if sealed:
            try:
                new_token = read_agent_token_flash(sealed, secret=session_secret)
            except InvalidAgentTokenFlash:
                new_token = None

        body = render_with_nav(
            settings_tpl, request, db_conn,
            base_url=base_url, secret=session_secret,
            agents=[a.__dict__ for a in agents],
            new_token=new_token,
            signed_in_user={"email": user.email},
        )
        resp = HTMLResponse(body)
        if sealed:
            resp.delete_cookie(AGENT_TOKEN_FLASH_COOKIE_NAME, path="/")
        return resp

    @html_router.post("/settings/agents/create")
    def settings_agents_create(
        request: Request, display_name: str = Form(...)
    ):
        user = _session_user_or_none(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        try:
            agents_svc.create_agent(
                db_conn,
                owner_user_id=user.id,
                display_name=display_name,
            )
        except ValueError:
            pass
        return RedirectResponse("/settings/agents", status_code=303)

    @html_router.post("/settings/agents/{agent_id}/delete")
    def settings_agents_delete(agent_id: str, request: Request):
        user = _session_user_or_none(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        try:
            agents_svc.revoke_agent(
                db_conn, agent_id, owner_user_id=user.id
            )
        except (LookupError, PermissionError):
            pass
        return RedirectResponse("/settings/agents", status_code=303)

    @html_router.post("/settings/agents/{agent_id}/tokens/create")
    def settings_agents_token_create(
        agent_id: str,
        request: Request,
        label: str = Form(...),
    ):
        user = _session_user_or_none(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        try:
            _, plaintext = auth_svc.create_agent_token(
                db_conn,
                agent_id=agent_id,
                owner_user_id=user.id,
                label=label,
            )
        except (LookupError, PermissionError, ValueError):
            return RedirectResponse("/settings/agents", status_code=303)

        sealed = issue_agent_token_flash(
            secret=session_secret, plaintext=plaintext
        )
        resp = RedirectResponse("/settings/agents", status_code=303)
        resp.set_cookie(
            key=AGENT_TOKEN_FLASH_COOKIE_NAME,
            value=sealed,
            max_age=AGENT_TOKEN_FLASH_MAX_AGE_SECONDS,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path="/",
        )
        return resp

    return router, html_router
