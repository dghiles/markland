"""FastAPI routes for per-doc grants + publish.

Mounted by `create_app`. Depends on a Principal being attached to
request.state.principal (Plan 2's PrincipalMiddleware or test injector).
Falls through to 401 if absent.
"""

from __future__ import annotations

import re
import sqlite3

from fastapi import APIRouter, Body, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service.auth import Principal
from markland.service.docs import ConflictError
from markland.service.email import EmailClient
from markland.service.permissions import NotFound, PermissionDenied


_IF_MATCH_RE = re.compile(r'^(?:W/)?"(\d+)"$')


def _parse_if_match(value: str | None) -> int | None:
    if not value:
        return None
    m = _IF_MATCH_RE.match(value.strip())
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail={"error": "unauthenticated"})
    return principal


def build_router(
    *,
    conn: sqlite3.Connection,
    base_url: str,
    email_client: EmailClient,
) -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.post("/docs")
    def publish(request: Request, body: dict = Body(...)):
        p = _principal(request)
        content = body.get("content", "")
        title = body.get("title")
        public = bool(body.get("public", False))
        return docs_svc.publish(conn, base_url, p, content, title=title, public=public)

    @r.get("/docs/{doc_id}")
    def api_get_doc(doc_id: str, request: Request):
        p = _principal(request)
        try:
            body = docs_svc.get(conn, p, doc_id, base_url=base_url)
        except NotFound:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionDenied:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        return JSONResponse(body, headers={"ETag": f'W/"{body["version"]}"'})

    @r.patch("/docs/{doc_id}")
    async def api_patch_doc(
        doc_id: str,
        request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
    ):
        p = _principal(request)
        parsed = _parse_if_match(if_match)
        if parsed is None:
            return JSONResponse(
                {"error": "precondition_required"}, status_code=428
            )
        payload = await request.json()
        content = payload.get("content")
        title = payload.get("title")
        try:
            doc = docs_svc.update(
                conn,
                doc_id,
                p,
                content=content,
                title=title,
                if_version=parsed,
            )
        except (NotFound, ValueError):
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionDenied:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except ConflictError as exc:
            return JSONResponse(
                {
                    "error": "conflict",
                    "current_version": exc.current_version,
                    "current_content": exc.current_content,
                    "current_title": exc.current_title,
                },
                status_code=409,
            )
        return JSONResponse(
            {
                "id": doc.id,
                "title": doc.title,
                "content": doc.content,
                "updated_at": doc.updated_at,
                "version": doc.version,
            },
            headers={"ETag": f'W/"{doc.version}"'},
        )

    @r.get("/docs/{doc_id}/grants")
    def list_grants(doc_id: str, request: Request):
        p = _principal(request)
        try:
            return grants_svc.list_grants(conn, principal=p, doc_id=doc_id)
        except NotFound:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionDenied:
            # Grants are owner/edit-level restricted — treat as 404 for
            # consistency with the "mask forbidden as not-found" principle.
            raise HTTPException(status_code=404, detail={"error": "not_found"})

    @r.post("/docs/{doc_id}/grants")
    def create_grant(doc_id: str, request: Request, body: dict = Body(...)):
        p = _principal(request)
        target = body.get("principal", "")
        level = body.get("level", "")
        try:
            return grants_svc.grant(
                conn,
                base_url=base_url,
                principal=p,
                doc_id=doc_id,
                target=target,
                level=level,
                email_client=email_client,
            )
        except NotFound:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionDenied:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except (
            grants_svc.GrantTargetNotFound,
            grants_svc.AgentGrantsNotSupported,
            grants_svc.InvalidGrantLevel,
        ) as exc:
            return JSONResponse(
                {"error": "invalid_argument", "reason": exc.__class__.__name__},
                status_code=400,
            )

    @r.delete("/docs/{doc_id}/grants/{principal_id}")
    def delete_grant(doc_id: str, principal_id: str, request: Request):
        p = _principal(request)
        try:
            return grants_svc.revoke(
                conn, principal=p, doc_id=doc_id, principal_id=principal_id
            )
        except NotFound:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionDenied:
            raise HTTPException(status_code=404, detail={"error": "not_found"})

    return r


__all__ = ["build_router"]
