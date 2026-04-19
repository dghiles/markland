"""Authenticated /dashboard page — My docs + Shared with me."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from markland.db import (
    list_documents_for_owner,
    list_shared_with_principal,
)
from markland.service.auth import Principal


def build_router(*, conn: sqlite3.Connection) -> APIRouter:
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
        principal: Principal | None = getattr(request.state, "principal", None)
        if principal is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)

        owned_docs = list_documents_for_owner(conn, principal.principal_id)
        shared_docs = list_shared_with_principal(conn, principal.principal_id)

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
        return HTMLResponse(tpl.render(owned=owned, shared=shared))

    return r


__all__ = ["build_router"]
