"""Markland MCP Server — publish and share markdown documents.

Every tool resolves the current principal from request state (set by Plan 2's
PrincipalMiddleware) and calls into `service/docs.py` / `service/grants.py`.
Errors are mapped to MCP-friendly dicts: {"error": "not_found" | "forbidden" |
"invalid_argument", "reason": ...}.

`build_mcp` also exposes `.markland_handlers` — a dict of handler callables —
so unit tests can exercise tool logic without standing up an MCP session.
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import Context, FastMCP

from markland.config import get_config
from markland.db import init_db
from markland.service import agents as agents_svc
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service import invites as invites_svc
from markland.service import presence as presence_svc
from markland.service.auth import Principal
from markland.service.email import EmailClient
from markland.service.permissions import NotFound, PermissionDenied, check_permission

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("markland")


def _whoami_for_principal(principal: Principal) -> dict:
    return {
        "principal_id": principal.principal_id,
        "principal_type": principal.principal_type,
        "display_name": principal.display_name,
    }


def _feature_requires_admin(principal: Principal) -> None:
    if not principal.is_admin:
        raise PermissionError("markland_feature requires admin")


def _principal_from_ctx(ctx) -> Principal | None:
    """Ctx surfaces the Principal.

    Tests pass a stand-in Context with `.principal`; in production FastMCP
    request path sets `ctx.request_context.request.state.principal`.
    """
    if ctx is None:
        return None
    if hasattr(ctx, "principal"):
        return ctx.principal
    req = getattr(ctx, "request_context", None)
    if req is None:
        return None
    request = getattr(req, "request", None)
    if request is None:
        return None
    state = getattr(request, "state", None)
    if state is None:
        return None
    return getattr(state, "principal", None)


def _require_principal(ctx) -> Principal:
    p = _principal_from_ctx(ctx)
    if p is None:
        raise RuntimeError("no principal on context — PrincipalMiddleware missing?")
    return p


def build_mcp(
    db_conn,
    *,
    base_url: str,
    email_client: EmailClient | None = None,
) -> FastMCP:
    """Build a FastMCP with all Markland tools. Same factory serves stdio + HTTP.

    `email_client` is optional — when None, `markland_grant` skips the
    best-effort email send silently.
    """
    mcp = FastMCP("markland")
    handlers: dict = {}

    def _publish(ctx, content: str, title: str | None = None, public: bool = False):
        p = _require_principal(ctx)
        return docs_svc.publish(db_conn, base_url, p, content, title=title, public=public)

    def _list(ctx):
        p = _require_principal(ctx)
        return docs_svc.list_for_principal(db_conn, p)

    def _get(ctx, doc_id: str):
        p = _require_principal(ctx)
        try:
            body = docs_svc.get(db_conn, p, doc_id, base_url=base_url)
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}
        # Embed non-expired presence rows. Principals who lack view access
        # never reach this branch because the check_permission call in
        # docs_svc.get raised above.
        actives = presence_svc.list_active(db_conn, doc_id=doc_id)
        body["active_principals"] = [
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
        return body

    def _search(ctx, query: str):
        p = _require_principal(ctx)
        return docs_svc.search(db_conn, p, query)

    def _share(ctx, doc_id: str):
        p = _require_principal(ctx)
        try:
            return docs_svc.share_link(db_conn, base_url, p, doc_id)
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}

    def _update(
        ctx,
        doc_id: str,
        if_version: int,
        content: str | None = None,
        title: str | None = None,
    ):
        p = _require_principal(ctx)
        try:
            doc = docs_svc.update(
                db_conn, doc_id, p, content=content, title=title, if_version=if_version
            )
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}
        except ValueError:
            return {"error": "not_found"}
        except docs_svc.ConflictError as exc:
            return {
                "error": "conflict",
                "current_version": exc.current_version,
                "current_content": exc.current_content,
                "current_title": exc.current_title,
            }
        return {
            "id": doc.id,
            "title": doc.title,
            "share_url": f"{base_url}/d/{doc.share_token}",
            "updated_at": doc.updated_at,
            "version": doc.version,
        }

    def _delete(ctx, doc_id: str):
        p = _require_principal(ctx)
        try:
            return docs_svc.delete(db_conn, p, doc_id)
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}

    def _set_visibility(ctx, doc_id: str, public: bool):
        p = _require_principal(ctx)
        try:
            return docs_svc.set_visibility(db_conn, base_url, p, doc_id, public)
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}

    def _feature(ctx, doc_id: str, featured: bool = True):
        p = _require_principal(ctx)
        row = db_conn.execute(
            "SELECT is_admin FROM users WHERE id = ?", (p.principal_id,)
        ).fetchone()
        if not row or not row[0]:
            return {"error": "forbidden"}
        try:
            return docs_svc.feature(db_conn, p, doc_id, featured)
        except NotFound:
            return {"error": "not_found"}

    def _grant(ctx, doc_id: str, principal: str, level: str):
        p = _require_principal(ctx)
        try:
            return grants_svc.grant(
                db_conn,
                base_url=base_url,
                principal=p,
                doc_id=doc_id,
                target=principal,
                level=level,
                email_client=email_client,
            )
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}
        except grants_svc.GrantTargetNotFound:
            return {"error": "invalid_argument", "reason": "target_not_found"}
        except grants_svc.AgentGrantsNotSupported:
            return {"error": "invalid_argument", "reason": "agent_grants_not_supported"}
        except grants_svc.InvalidGrantLevel:
            return {"error": "invalid_argument", "reason": "invalid_level"}

    def _revoke(ctx, doc_id: str, principal: str):
        p = _require_principal(ctx)
        pid = principal.strip()
        if "@" in pid:
            row = db_conn.execute(
                "SELECT id FROM users WHERE lower(email) = lower(?)", (pid,)
            ).fetchone()
            if row is None:
                return {"error": "invalid_argument", "reason": "target_not_found"}
            pid = row[0]
        try:
            return grants_svc.revoke(
                db_conn, principal=p, doc_id=doc_id, principal_id=pid
            )
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}

    def _list_grants(ctx, doc_id: str):
        p = _require_principal(ctx)
        try:
            return grants_svc.list_grants(db_conn, principal=p, doc_id=doc_id)
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}

    def _create_invite(
        ctx,
        doc_id: str,
        level: str,
        single_use: bool = True,
        expires_in_days: int | None = None,
    ):
        p = _require_principal(ctx)
        try:
            check_permission(db_conn, p, doc_id, "owner")
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}
        result = invites_svc.create_invite(
            db_conn,
            doc_id=doc_id,
            created_by_user_id=p.principal_id,
            level=level,
            base_url=base_url,
            single_use=single_use,
            expires_in_days=expires_in_days,
        )
        return {
            "invite_id": result.id,
            "url": result.url,
            "level": result.level,
            "expires_at": result.expires_at,
        }

    def _revoke_invite(ctx, invite_id: str):
        p = _require_principal(ctx)
        row = db_conn.execute(
            "SELECT doc_id FROM invites WHERE id = ?", (invite_id,)
        ).fetchone()
        if row is None:
            return {"error": "not_found"}
        try:
            check_permission(db_conn, p, row[0], "owner")
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}
        invites_svc.revoke_invite(
            db_conn, invite_id=invite_id, owner_user_id=p.principal_id
        )
        return {"revoked": True, "invite_id": invite_id}

    def _set_status(ctx, doc_id: str, status: str, note: str | None = None):
        p = _require_principal(ctx)
        if status not in ("reading", "editing"):
            raise ValueError("status must be 'reading' or 'editing'")
        try:
            check_permission(db_conn, p, doc_id, "view")
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}
        try:
            return presence_svc.set_status(
                db_conn,
                doc_id=doc_id,
                principal=p,
                status=status,
                note=note,
            )
        except presence_svc.PresenceError:
            return {"error": "not_found"}

    def _clear_status(ctx, doc_id: str):
        p = _require_principal(ctx)
        return presence_svc.clear_status(db_conn, doc_id=doc_id, principal=p)

    def _list_my_agents(ctx):
        p = _require_principal(ctx)
        if p.principal_type == "agent":
            if p.user_id is None:
                return []  # service-owned agent — no self-lookup exposed
            row = db_conn.execute(
                "SELECT id, display_name, owner_type, owner_id, created_at "
                "FROM agents WHERE id = ?",
                (p.principal_id,),
            ).fetchone()
            if row is None:
                return []
            return [
                {
                    "id": row[0],
                    "display_name": row[1],
                    "owner_type": row[2],
                    "owner_id": row[3],
                    "created_at": row[4],
                }
            ]
        agents = agents_svc.list_agents(db_conn, owner_user_id=p.principal_id)
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

    def _whoami(ctx):
        principal = _principal_from_ctx(ctx)
        if principal is None:
            return {
                "principal_id": "anonymous",
                "principal_type": "user",
                "display_name": None,
            }
        return _whoami_for_principal(principal)

    @mcp.tool()
    def markland_whoami(ctx: Context) -> dict:
        """Return the caller's identity."""
        return _whoami(ctx)

    @mcp.tool()
    def markland_publish(
        ctx: Context, content: str, title: str | None = None, public: bool = False
    ) -> dict:
        """Publish a markdown document owned by the current principal."""
        return _publish(ctx, content, title=title, public=public)

    @mcp.tool()
    def markland_list(ctx: Context) -> list[dict]:
        """List docs where the current principal is owner or has a grant."""
        return _list(ctx)

    @mcp.tool()
    def markland_get(ctx: Context, doc_id: str) -> dict:
        """Get a document. Requires view access.

        Response includes `version: int` — pass this value back as
        `if_version` to markland_update so your update is rejected if
        anyone else wrote in the meantime.
        """
        return _get(ctx, doc_id)

    @mcp.tool()
    def markland_search(ctx: Context, query: str) -> list[dict]:
        """Search docs the current principal can view."""
        return _search(ctx, query)

    @mcp.tool()
    def markland_share(ctx: Context, doc_id: str) -> dict:
        """Get the shareable link for a document. Requires view access."""
        return _share(ctx, doc_id)

    @mcp.tool()
    def markland_update(
        ctx: Context,
        doc_id: str,
        if_version: int,
        content: str | None = None,
        title: str | None = None,
    ) -> dict:
        """Update a document's content or title with optimistic concurrency control.

        Args:
            doc_id: The document ID to update.
            if_version: REQUIRED. The version number you last saw from
                markland_get. If it does not match the server's current
                version, the update is rejected with a `conflict` error
                whose payload includes `current_version`, `current_content`,
                and `current_title`. Re-fetch, merge, and retry with the
                fresh version number.
            content: New markdown content (optional).
            title: New title (optional).
        """
        from mcp.server.fastmcp.exceptions import ToolError

        result = _update(ctx, doc_id, if_version, content=content, title=title)
        if isinstance(result, dict) and result.get("error") == "conflict":
            err = ToolError("conflict: document was modified by another caller")
            err.data = {
                "code": "conflict",
                "current_version": result["current_version"],
                "current_content": result["current_content"],
                "current_title": result["current_title"],
            }
            raise err
        return result

    @mcp.tool()
    def markland_delete(ctx: Context, doc_id: str) -> dict:
        """Delete a document. Owner only."""
        return _delete(ctx, doc_id)

    @mcp.tool()
    def markland_set_visibility(ctx: Context, doc_id: str, public: bool) -> dict:
        """Promote to /explore (public) or demote to unlisted. Owner only."""
        return _set_visibility(ctx, doc_id, public)

    @mcp.tool()
    def markland_feature(ctx: Context, doc_id: str, featured: bool = True) -> dict:
        """Pin or unpin a doc on the landing page hero. Admin only."""
        return _feature(ctx, doc_id, featured)

    @mcp.tool()
    def markland_grant(ctx: Context, doc_id: str, principal: str, level: str) -> dict:
        """Grant view or edit access. Owner only. `principal` is an email."""
        return _grant(ctx, doc_id, principal, level)

    @mcp.tool()
    def markland_revoke(ctx: Context, doc_id: str, principal: str) -> dict:
        """Revoke a grant. Owner only. `principal` may be an email or usr_ id."""
        return _revoke(ctx, doc_id, principal)

    @mcp.tool()
    def markland_list_grants(ctx: Context, doc_id: str) -> list[dict]:
        """List grants on a document. Requires edit or owner."""
        return _list_grants(ctx, doc_id)

    @mcp.tool()
    def markland_create_invite(
        ctx: Context,
        doc_id: str,
        level: str,
        single_use: bool = True,
        expires_in_days: int | None = None,
    ) -> dict:
        """Owner-only. Create an invite link for a doc."""
        return _create_invite(
            ctx,
            doc_id,
            level,
            single_use=single_use,
            expires_in_days=expires_in_days,
        )

    @mcp.tool()
    def markland_revoke_invite(ctx: Context, invite_id: str) -> dict:
        """Owner-only. Revoke an invite so the URL stops working."""
        return _revoke_invite(ctx, invite_id)

    @mcp.tool()
    def markland_list_my_agents(ctx: Context) -> list[dict]:
        """List agents visible to the caller.

        User tokens see all of that user's agents. Agent tokens see only themselves
        (service-owned agents see an empty list).
        """
        return _list_my_agents(ctx)

    @mcp.tool()
    def markland_set_status(
        ctx: Context,
        doc_id: str,
        status: str,
        note: str | None = None,
    ) -> dict:
        """Announce that you are reading or editing a document.

        Advisory — does NOT lock the document. Other principals may still edit.
        The announcement expires after 10 minutes; re-call this tool every ~5
        minutes to remain visible (heartbeat). Valid statuses: 'reading',
        'editing'. To stop announcing, call `markland_clear_status`.

        Returns `{doc_id, status, expires_at}`.
        """
        return _set_status(ctx, doc_id, status, note=note)

    def _audit(ctx, doc_id: str | None = None, limit: int = 100):
        p = _require_principal(ctx)
        if not p.is_admin:
            raise PermissionError("markland_audit requires admin")
        from markland.service import audit as audit_svc

        return audit_svc.list_recent(db_conn, doc_id=doc_id, limit=int(limit))

    @mcp.tool()
    def markland_audit(
        ctx: Context, doc_id: str | None = None, limit: int = 100
    ) -> list[dict]:
        """Admin-only: recent audit entries across the system."""
        return _audit(ctx, doc_id=doc_id, limit=limit)

    @mcp.tool()
    def markland_clear_status(ctx: Context, doc_id: str) -> dict:
        """Remove your presence announcement from a document.

        Idempotent — safe to call even if you hadn't set a status. Equivalent
        to letting the announcement expire naturally after 10 minutes, but
        immediate.
        """
        return _clear_status(ctx, doc_id)

    handlers.update(
        markland_whoami=_whoami,
        markland_publish=_publish,
        markland_list=_list,
        markland_get=_get,
        markland_search=_search,
        markland_share=_share,
        markland_update=_update,
        markland_delete=_delete,
        markland_set_visibility=_set_visibility,
        markland_feature=_feature,
        markland_grant=_grant,
        markland_revoke=_revoke,
        markland_list_grants=_list_grants,
        markland_list_my_agents=_list_my_agents,
        markland_create_invite=_create_invite,
        markland_revoke_invite=_revoke_invite,
        markland_set_status=_set_status,
        markland_clear_status=_clear_status,
        markland_audit=_audit,
    )
    mcp.markland_handlers = handlers  # type: ignore[attr-defined]
    return mcp


if __name__ == "__main__":
    config = get_config()
    db_conn = init_db(config.db_path)
    email_client = EmailClient(
        api_key=getattr(config, "resend_api_key", "") or "",
        from_email=getattr(config, "resend_from_email", "") or "noreply@markland.dev",
    )
    logger.info("Starting Markland MCP server (stdio, db: %s)", config.db_path)
    mcp_instance = build_mcp(
        db_conn, base_url=config.base_url, email_client=email_client
    )
    mcp_instance.run()
