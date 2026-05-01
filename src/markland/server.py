"""Markland MCP Server — publish and share markdown documents.

Every tool resolves the current principal from request state (set by Plan 2's
PrincipalMiddleware) and calls into `service/docs.py` / `service/grants.py`.
Errors are surfaced via `markland._mcp_errors.tool_error(code, **data)` (axis
3) — the closed code set is `{unauthenticated, forbidden, not_found, conflict,
invalid_argument, rate_limited, internal_error}`.

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
from markland._mcp_envelopes import doc_envelope, doc_summary, list_envelope
from markland._mcp_errors import tool_error
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
        raise tool_error("unauthenticated")
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
        raw = docs_svc.publish(db_conn, base_url, p, content, title=title, public=public)
        # Re-fetch via get() to ensure all doc_envelope fields are populated.
        full = docs_svc.get(db_conn, p, raw["id"], base_url=base_url)
        return doc_envelope(full)

    def _list(ctx, limit: int = 50, cursor: str | None = None):
        p = _require_principal(ctx)
        rows, next_cursor = docs_svc.list_for_principal_paginated(
            db_conn, p, limit=limit, cursor=cursor,
        )
        items = [doc_summary(r) for r in rows]
        return list_envelope(items=items, next_cursor=next_cursor)

    def _get(ctx, doc_id: str):
        p = _require_principal(ctx)
        try:
            body = docs_svc.get(db_conn, p, doc_id, base_url=base_url)
        except NotFound:
            raise tool_error("not_found")
        except PermissionDenied:
            raise tool_error("forbidden")
        # Embed non-expired presence rows. Principals who lack view access
        # never reach this branch because the check_permission call in
        # docs_svc.get raised above.
        actives = presence_svc.list_active(db_conn, doc_id=doc_id)
        active_principals = [
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
        return doc_envelope(body, active_principals=active_principals)

    def _search(ctx, query: str, limit: int = 50, cursor: str | None = None):
        p = _require_principal(ctx)
        rows, next_cursor = docs_svc.search_paginated(
            db_conn, p, query, limit=limit, cursor=cursor,
        )
        items = [doc_summary(r) for r in rows]
        return list_envelope(items=items, next_cursor=next_cursor)

    def _share(ctx, doc_id: str):
        p = _require_principal(ctx)
        try:
            return docs_svc.share_link(db_conn, base_url, p, doc_id)
        except NotFound:
            raise tool_error("not_found")
        except PermissionDenied:
            raise tool_error("forbidden")

    def _get_by_share_token(ctx, share_token: str):
        # Anonymous-callable — no _require_principal call.
        raw = docs_svc.get_by_share_token(db_conn, share_token)
        if raw is None:
            raise tool_error("not_found")
        raw["share_url"] = f"{base_url}/d/{share_token}"
        return doc_envelope(raw)

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
            raise tool_error("not_found")
        except PermissionDenied:
            raise tool_error("forbidden")
        except ValueError:
            raise tool_error("not_found")
        except docs_svc.ConflictError as exc:
            raise tool_error(
                "conflict",
                current_version=exc.current_version,
                current_content=exc.current_content,
                current_title=exc.current_title,
            )
        full = docs_svc.get(db_conn, p, doc.id, base_url=base_url)
        return doc_envelope(full)

    def _delete(ctx, doc_id: str):
        p = _require_principal(ctx)
        try:
            return docs_svc.delete(db_conn, p, doc_id)
        except NotFound:
            raise tool_error("not_found")
        except PermissionDenied:
            raise tool_error("forbidden")

    def _doc_meta(
        ctx,
        doc_id: str,
        public: bool | None = None,
        featured: bool | None = None,
    ):
        from markland import db as db_module

        p = _require_principal(ctx)

        if featured is not None and not p.is_admin:
            raise tool_error("forbidden")

        # Look up current state so we can skip no-op writes (idempotency)
        # before they hit permission checks.
        current = db_module.get_document(db_conn, doc_id)

        # Owner check is handled inside docs_svc for the public flag. Skip
        # the call entirely when the requested state matches current state.
        if public is not None and (current is None or current.is_public != public):
            try:
                docs_svc.set_visibility(db_conn, base_url, p, doc_id, public)
            except NotFound:
                raise tool_error("not_found")
            except PermissionDenied:
                raise tool_error("forbidden")

        if featured is not None and (current is None or current.is_featured != featured):
            try:
                docs_svc.feature(db_conn, p, doc_id, featured)
            except NotFound:
                raise tool_error("not_found")

        # Return the freshly-loaded doc as a doc_envelope.
        doc = db_module.get_document(db_conn, doc_id)
        if doc is None:
            raise tool_error("not_found")

        # No writes attempted: fall back to the standard view-permission
        # check so we don't leak metadata for unrelated docs.
        wrote = (
            (public is not None and (current is None or current.is_public != public))
            or (featured is not None and (current is None or current.is_featured != featured))
        )
        if not wrote:
            try:
                body = docs_svc.get(db_conn, p, doc_id, base_url=base_url)
            except NotFound:
                raise tool_error("not_found")
            except PermissionDenied:
                raise tool_error("forbidden")
            return doc_envelope(body)

        body = {
            "id": doc.id,
            "title": doc.title,
            "content": doc.content,
            "share_url": f"{base_url}/d/{doc.share_token}",
            "updated_at": doc.updated_at,
            "created_at": doc.created_at,
            "is_public": doc.is_public,
            "is_featured": doc.is_featured,
            "owner_id": doc.owner_id,
            "version": doc.version,
        }
        return doc_envelope(body)

    def _grant(
        ctx,
        doc_id: str,
        target: str | None = None,
        level: str = "view",
        *,
        principal: str | None = None,  # Deprecated alias for `target`.
    ):
        p = _require_principal(ctx)
        chosen_target = target if target is not None else principal
        if chosen_target is None:
            raise tool_error("invalid_argument", reason="target is required")
        try:
            return grants_svc.grant(
                db_conn,
                base_url=base_url,
                principal=p,
                doc_id=doc_id,
                target=chosen_target,
                level=level,
                email_client=email_client,
            )
        except NotFound:
            raise tool_error("not_found")
        except PermissionDenied:
            raise tool_error("forbidden")
        except grants_svc.GrantTargetNotFound:
            raise tool_error("invalid_argument", reason="target_not_found")
        except grants_svc.AgentGrantsNotSupported:
            raise tool_error("invalid_argument", reason="agent_grants_not_supported")
        except grants_svc.InvalidGrantLevel:
            raise tool_error("invalid_argument", reason="invalid_level")

    def _revoke(ctx, doc_id: str, target: str):
        p = _require_principal(ctx)
        pid = target.strip()
        if "@" in pid:
            row = db_conn.execute(
                "SELECT id FROM users WHERE lower(email) = lower(?)", (pid,)
            ).fetchone()
            if row is None:
                # Idempotent: target doesn't exist as a user → return success no-op.
                return {"revoked": False, "doc_id": doc_id, "target": target}
            pid = row[0]

        # Owner check still applies — non-owner shouldn't probe arbitrary docs.
        try:
            check_permission(db_conn, p, doc_id, "owner")
        except NotFound:
            raise tool_error("not_found")
        except PermissionDenied:
            raise tool_error("forbidden")

        try:
            result = grants_svc.revoke(
                db_conn, principal=p, doc_id=doc_id, principal_id=pid,
            )
        except NotFound:
            # Grant didn't exist on this owner-readable doc. Idempotent.
            return {"revoked": False, "doc_id": doc_id, "target": target}
        return result

    def _list_grants(
        ctx, doc_id: str, limit: int = 50, cursor: str | None = None
    ):
        p = _require_principal(ctx)
        try:
            rows, next_cursor = grants_svc.list_grants_paginated(
                db_conn,
                principal=p,
                doc_id=doc_id,
                limit=limit,
                cursor=cursor,
            )
        except NotFound:
            raise tool_error("not_found")
        except PermissionDenied:
            raise tool_error("forbidden")
        return list_envelope(items=rows, next_cursor=next_cursor)

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
            raise tool_error("not_found")
        except PermissionDenied:
            raise tool_error("forbidden")
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
            # Idempotent: invite never existed.
            return {"revoked": True, "invite_id": invite_id}
        try:
            check_permission(db_conn, p, row[0], "owner")
        except NotFound:
            raise tool_error("not_found")
        except PermissionDenied:
            raise tool_error("forbidden")
        invites_svc.revoke_invite(
            db_conn, invite_id=invite_id, owner_user_id=p.principal_id
        )
        return {"revoked": True, "invite_id": invite_id}

    def _status(ctx, doc_id: str, status: str | None, note: str | None = None):
        p = _require_principal(ctx)

        if status is None:
            # Clear path — idempotent.
            presence_svc.clear_status(db_conn, doc_id=doc_id, principal=p)
            return {"doc_id": doc_id, "cleared": True}

        if status not in ("reading", "editing"):
            raise tool_error(
                "invalid_argument",
                reason="status_must_be_reading_or_editing_or_none",
            )

        try:
            check_permission(db_conn, p, doc_id, "view")
        except NotFound:
            raise tool_error("not_found")
        except PermissionDenied:
            raise tool_error("forbidden")

        try:
            return presence_svc.set_status(
                db_conn, doc_id=doc_id, principal=p, status=status, note=note,
            )
        except presence_svc.PresenceError:
            raise tool_error("not_found")

    def _list_my_agents(ctx, limit: int = 50, cursor: str | None = None):
        p = _require_principal(ctx)
        if p.principal_type == "agent":
            # Special-cases: agents always see at most one row (themselves),
            # so pagination is a no-op — always returns next_cursor=None.
            if p.user_id is None:
                return list_envelope(items=[], next_cursor=None)
            row = db_conn.execute(
                "SELECT id, display_name, owner_type, owner_id, created_at "
                "FROM agents WHERE id = ?",
                (p.principal_id,),
            ).fetchone()
            if row is None:
                return list_envelope(items=[], next_cursor=None)
            return list_envelope(
                items=[
                    {
                        "id": row[0],
                        "display_name": row[1],
                        "owner_type": row[2],
                        "owner_id": row[3],
                        "created_at": row[4],
                    }
                ],
                next_cursor=None,
            )
        rows, next_cursor = agents_svc.list_paginated(
            db_conn,
            owner_user_id=p.principal_id,
            limit=limit,
            cursor=cursor,
        )
        return list_envelope(items=rows, next_cursor=next_cursor)

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
        """Return the caller's identity.

        Useful for confirming which principal an MCP token resolves to before
        running other tools. Anonymous callers get back a synthetic
        `principal_id="anonymous"` row instead of an error.

        Args:
            ctx: FastMCP request context. The principal is resolved from
                `ctx.request_context.request.state.principal` (set by
                PrincipalMiddleware) or `ctx.principal` in tests.

        Returns:
            `{principal_id, principal_type, display_name}`. `principal_type`
            is `"user"` or `"agent"`; for anonymous callers `principal_id`
            is `"anonymous"` and `display_name` is `None`.

        Idempotency: Read-only.
        """
        return _whoami(ctx)

    @mcp.tool()
    def markland_publish(
        ctx: Context, content: str, title: str | None = None, public: bool = False
    ) -> dict:
        """Publish a markdown document owned by the current principal.

        Each call creates a fresh document with a new id and share token —
        there is no upsert. Service-owned agents (no `user_id`) cannot
        publish; use a user-owned agent token instead.

        Args:
            content: Raw markdown body. No length limit enforced here.
            title: Optional title. When omitted, the title is extracted from
                the first markdown heading in `content`, falling back to a
                placeholder.
            public: If `True`, the document is listed on /explore. Default
                `False` (unlisted — visible only to grantees and via share
                link).

        Returns:
            `{id, title, share_url, is_public, owner_id}`.

        Raises:
            invalid_argument: When called by a service-owned agent
                (`service_agent_cannot_publish`).

        Idempotency: Not idempotent — each call creates a new document.
        """
        return _publish(ctx, content, title=title, public=public)

    @mcp.tool()
    def markland_list(
        ctx: Context, limit: int = 50, cursor: str | None = None
    ) -> dict:
        """List documents the current principal can view, paginated.

        Returns documents the principal owns plus those reached via a
        `view`/`edit` grant. Public-but-ungranted documents are not
        included — use `markland_search` for discovery.

        Args:
            ctx: FastMCP request context (principal resolved from state).
            limit: Max documents per page (1-200, default 50).
            cursor: Opaque token from a previous response's `next_cursor`.
                Pass to fetch the next page; omit for the first page.

        Returns:
            list_envelope of doc_summary: {items: [doc_summary, ...],
            next_cursor}. `next_cursor` is None when there are no more
            results. Ordering is `(updated_at DESC, id DESC)`.

        Raises:
            unauthenticated: caller has no principal.

        Idempotency: Read-only.
        """
        return _list(ctx, limit=limit, cursor=cursor)

    @mcp.tool()
    def markland_get(ctx: Context, doc_id: str) -> dict:
        """Get a document with embedded active-presence rows.

        The response includes `version: int` — pass this value back as
        `if_version` to `markland_update` so your write is rejected if
        anyone else committed a revision in the meantime.

        Args:
            doc_id: Document id (e.g. `doc_…`).

        Returns:
            Full document dict including `id, title, content, share_url,
            is_public, version, owner_id, updated_at` plus
            `active_principals: list[dict]` — the non-expired presence rows
            for this doc (each `{principal_id, principal_type, display_name,
            status, note, updated_at}`).

        Raises:
            not_found: Document does not exist.
            forbidden: Caller lacks view access.

        Idempotency: Read-only.
        """
        return _get(ctx, doc_id)

    @mcp.tool()
    def markland_search(
        ctx: Context,
        query: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict:
        """Search documents the current principal can view, paginated.

        Searches title and content with a simple LIKE match; only documents
        the principal owns or has a grant on are returned.

        Args:
            query: Free-text query. Empty strings match nothing.
            limit: Max documents per page (1-200, default 50).
            cursor: Opaque token from a previous response's `next_cursor`.
                Pass to fetch the next page; omit for the first page.

        Returns:
            list_envelope of doc_summary: {items: [doc_summary, ...],
            next_cursor}. `next_cursor` is None when there are no more
            results. Ordering is `(updated_at DESC, id DESC)`.

        Idempotency: Read-only.
        """
        return _search(ctx, query, limit=limit, cursor=cursor)

    @mcp.tool()
    def markland_get_by_share_token(ctx: Context, share_token: str) -> dict:
        """Read a public document by its share token, no authentication required.

        Mirrors the anonymous web-viewer flow at `/d/<share_token>`. If the doc
        is unlisted (not public), returns not_found regardless of caller — the
        share token is not a capability for non-public docs.

        Args:
            share_token: The doc's share token (the last URL segment of share_url).

        Returns:
            doc_envelope. `active_principals` is omitted for anonymous callers.

        Raises:
            not_found: doc does not exist or is not public.

        Idempotency: Read-only.
        """
        return _get_by_share_token(ctx, share_token)

    @mcp.tool()
    def markland_share(ctx: Context, doc_id: str) -> dict:
        """Get a document's shareable URL.

        Anyone with the URL who also has view access can open the doc. For
        public docs the URL works without authentication.

        Args:
            doc_id: Document id.

        Returns:
            `{share_url, title}`.

        Raises:
            not_found: Document does not exist.
            forbidden: Caller lacks view access.

        Idempotency: Read-only.
        """
        return _share(ctx, doc_id)

    @mcp.tool()
    def markland_update(
        ctx: Context,
        doc_id: str,
        if_version: int,
        content: str | None = None,
        title: str | None = None,
    ) -> dict:
        """Update a document's content or title with optimistic concurrency.

        Compare-and-swap on `if_version`: if the server's current version
        does not match, the call raises a `conflict` ToolError carrying the
        current state so the caller can re-fetch, merge, and retry.

        Args:
            doc_id: Document id to update.
            if_version: REQUIRED. The version number you last saw from
                `markland_get`. Used as the CAS token.
            content: New markdown body. Omit to leave content unchanged.
            title: New title. Omit to leave title unchanged.

        Returns:
            `{id, title, share_url, updated_at, version}` on success, with
            `version` bumped by 1.

        Raises:
            not_found: Document does not exist (or was deleted).
            forbidden: Caller lacks edit access.
            conflict: ToolError with `data={code, current_version,
                current_content, current_title}` — re-fetch and retry.

        Idempotency: Not idempotent — each successful call increments
            version and writes a revision row.
        """
        return _update(ctx, doc_id, if_version, content=content, title=title)

    @mcp.tool()
    def markland_delete(ctx: Context, doc_id: str) -> dict:
        """Delete a document. Owner only.

        Removes the document, its grants, invites, and revisions. There is
        no undo — re-publish from a backup if the content is needed again.

        Args:
            doc_id: Document id to delete.

        Returns:
            `{deleted: bool, id}`. `deleted` is `False` only if the row had
            already been removed before the call landed.

        Raises:
            not_found: Document does not exist.
            forbidden: Caller is not the owner.

        Idempotency: Not idempotent — first call deletes, second returns
            `not_found`.
        """
        return _delete(ctx, doc_id)

    @mcp.tool()
    def markland_set_visibility(ctx: Context, doc_id: str, public: bool) -> dict:
        """Deprecated. Use markland_doc_meta(doc_id, public=...) instead.

        Removed in the release scheduled 30 days after this one.

        Args:
            doc_id: The document to update.
            public: True for public, False for unlisted.

        Returns:
            doc_envelope.

        Raises:
            not_found: doc does not exist or caller cannot see it.
            forbidden: caller is not the owner.

        Idempotency: Idempotent.
        """
        return _doc_meta(ctx, doc_id, public=public, featured=None)

    @mcp.tool()
    def markland_feature(ctx: Context, doc_id: str, featured: bool = True) -> dict:
        """Deprecated. Use markland_doc_meta(doc_id, featured=...) instead.

        Removed in the release scheduled 30 days after this one.

        Args:
            doc_id: The document to update.
            featured: True to pin, False to unpin.

        Returns:
            doc_envelope.

        Raises:
            not_found: doc does not exist or caller cannot see it.
            forbidden: caller is not an admin.

        Idempotency: Idempotent.
        """
        return _doc_meta(ctx, doc_id, public=None, featured=featured)

    @mcp.tool()
    def markland_doc_meta(
        ctx: Context,
        doc_id: str,
        public: bool | None = None,
        featured: bool | None = None,
    ) -> dict:
        """Update document metadata flags. Owner can set public; admin can set featured.

        Args:
            doc_id: The document to update.
            public: True/False to change public visibility (owner only).
                    None leaves it unchanged.
            featured: True/False to pin/unpin on the landing hero (admin only).
                      None leaves it unchanged.

        Returns:
            doc_envelope.

        Raises:
            not_found: doc does not exist or caller cannot see it.
            forbidden: caller is not the owner (for public) or not admin (for featured).

        Idempotency: Idempotent — calling with arguments matching current state is a no-op.
        """
        return _doc_meta(ctx, doc_id, public=public, featured=featured)

    @mcp.tool()
    def markland_grant(
        ctx: Context,
        doc_id: str,
        target: str | None = None,
        level: str = "view",
        *,
        principal: str | None = None,  # Deprecated alias for `target`.
    ) -> dict:
        """Grant view or edit access to a user or agent. Owner only.

        `target` accepts an email address (resolves to a user, creating
        a placeholder row if needed) or an `agt_…` id (agent grant). A
        best-effort notification email is sent for user grants when an
        EmailClient was wired into `build_mcp`.

        Args:
            doc_id: Document id.
            target: Email address or `agt_…` agent id. Replaces the
                `principal` keyword (deprecated; removed in the release
                scheduled 30 days after this one).
            level: `"view"` or `"edit"`. Defaults to `"view"`.

        Returns:
            Grant row dict `{doc_id, principal_id, principal_type, level,
            granted_by, granted_at}`.

        Raises:
            not_found: Document does not exist.
            forbidden: Caller is not the owner.
            invalid_argument: `target_not_found`, `invalid_level`, or
                `agent_grants_not_supported`.

        Idempotency: Idempotent (upsert) — re-granting the same target is a
            no-op; re-granting at a different level updates the row.
        """
        return _grant(ctx, doc_id, target, level, principal=principal)

    @mcp.tool()
    def markland_revoke(
        ctx: Context,
        doc_id: str,
        target: str | None = None,
        *,
        principal: str | None = None,  # Deprecated alias for `target`.
    ) -> dict:
        """Revoke an existing grant. Owner only.

        `target` accepts the same forms as `markland_grant`: an email
        address (resolved to a user id) or a `usr_…`/`agt_…` id passed
        through directly.

        Args:
            doc_id: Document id.
            target: Email, `usr_…`, or `agt_…` identifier of the grantee
                to remove. Replaces the `principal` keyword (deprecated;
                removed in the release scheduled 30 days after this one).

        Returns:
            `{revoked: bool, doc_id, target}`. `revoked` is `False`
            when no matching grant row existed (idempotent no-op).

        Raises:
            not_found: Document does not exist.
            forbidden: Caller is not the owner.

        Idempotency: Idempotent — calling on a non-existent target/grant
            is a no-op success.
        """
        chosen_target = target if target is not None else principal
        if chosen_target is None:
            raise tool_error("invalid_argument", reason="target is required")
        return _revoke(ctx, doc_id, chosen_target)

    @mcp.tool()
    def markland_list_grants(
        ctx: Context,
        doc_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict:
        """List grants on a document, paginated.

        Visible to the owner and any principal with edit access.

        Args:
            doc_id: Document id.
            limit: Max grants per page (1-200, default 50).
            cursor: Opaque token from a previous response's `next_cursor`.
                Pass to fetch the next page; omit for the first page.

        Returns:
            list_envelope of grant dicts: {items: [{doc_id, principal_id,
            principal_type, level, granted_by, granted_at}, ...],
            next_cursor}. Ordering is `(granted_at DESC, principal_id
            DESC)`.

        Raises:
            not_found: Document does not exist.
            forbidden: Caller lacks edit access.

        Idempotency: Read-only.
        """
        return _list_grants(ctx, doc_id, limit=limit, cursor=cursor)

    @mcp.tool()
    def markland_create_invite(
        ctx: Context,
        doc_id: str,
        level: str,
        single_use: bool = True,
        expires_in_days: int | None = None,
    ) -> dict:
        """Create an invite link with a pre-set access level. Owner only.

        The plaintext invite token is returned only in the URL; only its
        argon2id hash is persisted. Show the URL to the recipient — there
        is no way to recover it later.

        Args:
            doc_id: Document id to invite to.
            level: `"view"` or `"edit"` — access level granted on accept.
            single_use: When `True` (default) the invite consumes itself on
                first accept; when `False` the invite remains usable until
                explicitly revoked.
            expires_in_days: Optional integer — sets `expires_at` to N days
                from now. `None` means no expiry.

        Returns:
            `{invite_id, url, level, expires_at}`. `url` is the only place
            the plaintext token appears.

        Raises:
            not_found: Document does not exist.
            forbidden: Caller is not the owner.

        Idempotency: Not idempotent — each call creates a new invite row
            with a fresh token.
        """
        return _create_invite(
            ctx,
            doc_id,
            level,
            single_use=single_use,
            expires_in_days=expires_in_days,
        )

    @mcp.tool()
    def markland_revoke_invite(ctx: Context, invite_id: str) -> dict:
        """Revoke an outstanding invite. Owner only.

        Sets `revoked_at` on the invite so the URL stops resolving. Already
        revoked invites and non-existent invite ids are both treated as
        successful no-ops.

        Args:
            invite_id: Invite id (e.g. `inv_…`).

        Returns:
            `{revoked: True, invite_id}`.

        Raises:
            not_found: The invite's document does not exist.
            forbidden: Caller is not the document owner.

        Idempotency: Idempotent — calling on a non-existent invite is a
            no-op success.
        """
        return _revoke_invite(ctx, invite_id)

    @mcp.tool()
    def markland_list_my_agents(
        ctx: Context, limit: int = 50, cursor: str | None = None
    ) -> dict:
        """List agents owned by the current user, paginated.

        User tokens see all agents they own. Agent tokens see only
        themselves (service-owned agents — those without a `user_id` —
        return an empty list). Agent callers always get next_cursor=None.

        Args:
            ctx: FastMCP request context (principal resolved from state).
            limit: Max agents per page (1-200, default 50). Ignored for
                agent callers.
            cursor: Opaque token from a previous response's `next_cursor`.
                Pass to fetch the next page; omit for the first page.

        Returns:
            list_envelope of agent dicts: {items: [{id, display_name,
            owner_type, owner_id, created_at}, ...], next_cursor}.
            Ordering is `(created_at DESC, id DESC)`.

        Idempotency: Read-only.
        """
        return _list_my_agents(ctx, limit=limit, cursor=cursor)

    @mcp.tool()
    def markland_status(
        ctx: Context,
        doc_id: str,
        status: str | None = None,
        note: str | None = None,
    ) -> dict:
        """Set or clear your presence on a document.

        Pass status="reading" or status="editing" to announce; pass status=None
        (or omit) to clear. Advisory only — does not lock the document. Set
        entries expire after 10 minutes; re-call every ~5 minutes to remain
        visible (heartbeat).

        Args:
            doc_id: The document.
            status: "reading", "editing", or None to clear.
            note: Optional free-text note (only used when status is set).

        Returns:
            On set: {doc_id, status, expires_at, note}.
            On clear: {doc_id, cleared: true}.

        Raises:
            not_found: doc does not exist or caller cannot see it.
            forbidden: caller does not have view access.
            invalid_argument: status not in {reading, editing, None}.

        Idempotency: Idempotent.
        """
        return _status(ctx, doc_id, status=status, note=note)

    @mcp.tool()
    def markland_set_status(
        ctx: Context,
        doc_id: str,
        status: str,
        note: str | None = None,
    ) -> dict:
        """Deprecated. Use markland_status(doc_id, status=...) instead.

        Removed in the release scheduled 30 days after this one.

        Args:
            doc_id: The document.
            status: "reading" or "editing".
            note: Optional free-text note.

        Returns:
            {doc_id, status, expires_at}.

        Raises:
            not_found: doc does not exist or caller cannot see it.
            forbidden: caller does not have view access.
            invalid_argument: status not in {reading, editing}.

        Idempotency: Idempotent.
        """
        return _status(ctx, doc_id, status=status, note=note)

    def _audit(
        ctx,
        doc_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ):
        p = _require_principal(ctx)
        if not p.is_admin:
            raise tool_error("forbidden")
        from markland.service import audit as audit_svc

        rows, next_cursor = audit_svc.list_recent_paginated(
            db_conn, doc_id=doc_id, limit=int(limit), cursor=cursor,
        )
        return list_envelope(items=rows, next_cursor=next_cursor)

    @mcp.tool()
    def markland_audit(
        ctx: Context,
        doc_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict:
        """Read recent audit-log entries, paginated. Admin only.

        Surfaces the system audit trail — publish, update, delete, grant,
        revoke, invite_create events — for forensic and compliance use.

        Args:
            doc_id: Optional filter — when set, only entries for this
                document are returned. Default `None` (all docs).
            limit: Max rows per page. Clamped to [1, 1000]. Default 100.
            cursor: Opaque token from a previous response's `next_cursor`.
                Pass to fetch the next page; omit for the first page.

        Returns:
            list_envelope of audit row dicts: {items: [{id, doc_id,
            action, principal_id, principal_type, metadata, created_at},
            ...], next_cursor}. Newest first; ordering is `(created_at
            DESC, id DESC)`.

        Raises:
            forbidden: Caller is not an admin.

        Idempotency: Read-only.
        """
        return _audit(ctx, doc_id=doc_id, limit=limit, cursor=cursor)

    @mcp.tool()
    def markland_clear_status(ctx: Context, doc_id: str) -> dict:
        """Deprecated. Use markland_status(doc_id, status=None) instead.

        Removed in the release scheduled 30 days after this one.

        Args:
            doc_id: The document whose presence row should be removed.

        Returns:
            {doc_id, cleared: true}.

        Idempotency: Idempotent — safe to call even if no presence row exists.
        """
        return _status(ctx, doc_id, status=None)

    handlers.update(
        markland_whoami=_whoami,
        markland_publish=_publish,
        markland_list=_list,
        markland_get=_get,
        markland_get_by_share_token=_get_by_share_token,
        markland_search=_search,
        markland_share=_share,
        markland_update=_update,
        markland_delete=_delete,
        markland_set_visibility=lambda ctx, doc_id, public: _doc_meta(
            ctx, doc_id, public=public, featured=None
        ),
        markland_feature=lambda ctx, doc_id, featured=True: _doc_meta(
            ctx, doc_id, public=None, featured=featured
        ),
        markland_doc_meta=_doc_meta,
        markland_grant=_grant,
        markland_revoke=lambda ctx, doc_id, target=None, *, principal=None: _revoke(
            ctx, doc_id, target if target is not None else principal
        ),
        markland_list_grants=_list_grants,
        markland_list_my_agents=_list_my_agents,
        markland_create_invite=_create_invite,
        markland_revoke_invite=_revoke_invite,
        markland_set_status=lambda ctx, doc_id, status, note=None: _status(
            ctx, doc_id, status=status, note=note
        ),
        markland_clear_status=lambda ctx, doc_id: _status(
            ctx, doc_id, status=None
        ),
        markland_status=_status,
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
