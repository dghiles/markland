"""FastAPI web viewer for shared Markland documents."""

import contextlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from markland.db import (
    add_waitlist_email,
    get_document_by_token,
    list_featured_and_recent_public,
    list_public_documents,
)
from markland.web.competitors import COMPETITORS, MARKLAND, get_competitor
from markland.web.renderer import make_excerpt, render_markdown
from markland.web.seo import build_sitemap_xml, render_robots_txt

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_email(email: str) -> bool:
    return 3 <= len(email) <= 254 and bool(_EMAIL_RE.match(email))

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_SCRIPTS_DIR = Path(__file__).parent.parent.parent.parent / "scripts"


def _load_mcp_snippet() -> dict:
    """Load the MCP config snippet for the landing-page copy button."""
    snippet_path = _SCRIPTS_DIR / "mcp-config-snippet.json"
    try:
        return json.loads(snippet_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"markland": {"type": "stdio", "command": "uv", "args": ["run", "..."]}}


def _minutes_ago(iso_ts: str) -> int:
    """Coarse 'N minutes ago' for the presence badge. Returns 0 on parse failure."""
    try:
        then = datetime.fromisoformat(iso_ts)
    except ValueError:
        return 0
    delta = datetime.utcnow() - then
    return max(0, int(delta.total_seconds() // 60))


def _doc_to_card(doc) -> dict:
    """Convert a Document into the dict the templates expect (adds excerpt)."""
    return {
        "id": doc.id,
        "title": doc.title,
        "share_token": doc.share_token,
        "updated_at": doc.updated_at,
        "is_public": doc.is_public,
        "is_featured": doc.is_featured,
        "excerpt": make_excerpt(doc.content),
    }


def _public_host(request: Request, base_url: str) -> str:
    """Return the canonical ``scheme://host`` for building public URLs.

    Prefers ``base_url`` when configured (immune to Host-header spoofing); else
    falls back to the request URL, honoring ``x-forwarded-proto`` so reverse-
    proxied HTTPS traffic yields the right scheme.
    """
    if base_url:
        return base_url.rstrip("/")
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{scheme}://{request.url.netloc}"


def _seo_ctx(request: Request, base_url: str) -> dict:
    """Context keys every base-extending template needs for the _seo_meta partial."""
    return {"request": request, "canonical_host": _public_host(request, base_url)}


def create_app(
    db_conn: sqlite3.Connection,
    *,
    mount_mcp: bool = False,
    base_url: str = "",
    session_secret: str = "",
    email_client=None,
    email_dispatcher=None,
    test_principal_by_token: dict | None = None,
    enable_presence_gc: bool = False,
    gc_interval_seconds: float = 60.0,
    **_legacy_kwargs,
) -> FastAPI:
    from markland.service.email import EmailClient
    from markland.web.api_grants import build_router as build_grants_router
    from markland.web.auth_routes import build_auth_router
    from markland.web.identity_routes import build_identity_router

    if email_client is None:
        email_client = EmailClient(api_key="", from_email="notifications@markland.dev")

    # Backwards-compat: if no dispatcher was supplied, wrap email_client in a
    # synchronous inline dispatcher. Callers get the same `enqueue(...)` API
    # without any async machinery. Tests that pre-date Plan 7 (and pass only
    # email_client) continue to work, and their existing assertions on
    # `email_client.send.call_count` still fire synchronously.
    if email_dispatcher is None:
        from markland.service.email_dispatcher import EmailDispatcher  # noqa: F401  (type hint)

        class _InlineDispatcher:
            """Sync dispatcher: calls email_client.send directly, swallows errors."""

            def __init__(self, client):
                self._client = client

            def enqueue(self, to, subject, html, text=None, metadata=None):
                try:
                    self._client.send(
                        to=to,
                        subject=subject,
                        html=html,
                        text=text,
                        metadata=metadata,
                    )
                except TypeError:
                    # Pre-Plan-7 mocks or clients that don't accept text/metadata.
                    try:
                        self._client.send(to=to, subject=subject, html=html)
                    except Exception:
                        pass
                except Exception:
                    # Best-effort: never raise to the caller.
                    pass

            async def start(self):
                return None

            async def stop(self):
                return None

        email_dispatcher = _InlineDispatcher(email_client)

    mcp_app = None
    if mount_mcp:
        from markland.server import build_mcp

        mcp_instance = build_mcp(db_conn, base_url=base_url, email_client=email_client)
        # FastMCP's streamable_http_app serves at `/mcp` by default — re-root it
        # so our mount at `/mcp` doesn't produce `/mcp/mcp`.
        mcp_instance.settings.streamable_http_path = "/"
        # Disable MCP's built-in DNS-rebinding protection — our own middleware
        # gates `/mcp`, and Fly.io's proxy sets arbitrary host headers.
        mcp_instance.settings.transport_security.enable_dns_rebinding_protection = False
        mcp_app = mcp_instance.streamable_http_app()

    # Unified lifespan: start/stop the email dispatcher alongside the MCP
    # sub-app's session manager, plus the presence GC task. TestClient entered
    # as a context manager triggers this, so tests see a running dispatcher.
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        if email_dispatcher is not None:
            await email_dispatcher.start()
            app.state.email_dispatcher = email_dispatcher
        app.state.presence_gc_task = None
        app.state.presence_gc_stop = None
        if enable_presence_gc:
            from markland.web import presence_gc as _presence_gc
            gc_task, gc_stop = _presence_gc.start(
                db_conn, interval_seconds=gc_interval_seconds
            )
            app.state.presence_gc_task = gc_task
            app.state.presence_gc_stop = gc_stop
        try:
            if mcp_app is not None:
                async with mcp_app.router.lifespan_context(app):
                    yield
            else:
                yield
        finally:
            if app.state.presence_gc_task is not None:
                from markland.web import presence_gc as _presence_gc
                await _presence_gc.stop(
                    app.state.presence_gc_task, app.state.presence_gc_stop
                )
            if email_dispatcher is not None:
                await email_dispatcher.stop()

    app = FastAPI(
        title="Markland", docs_url=None, redoc_url=None, lifespan=lifespan,
    )
    # Expose eagerly too — handlers that run before startup (shouldn't happen,
    # but be robust) still see the instance.
    app.state.email_dispatcher = email_dispatcher
    app.state.presence_gc_task = None
    app.state.presence_gc_stop = None
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    landing_tpl = env.get_template("landing.html")
    explore_tpl = env.get_template("explore.html")
    document_tpl = env.get_template("document.html")
    quickstart_tpl = env.get_template("quickstart.html")
    admin_audit_tpl = env.get_template("admin_audit.html")
    alternatives_tpl = env.get_template("alternatives.html")
    alternative_tpl = env.get_template("alternative.html")

    mcp_snippet = _load_mcp_snippet()
    mcp_snippet_json = json.dumps(mcp_snippet)

    @app.get("/health")
    def health():
        return JSONResponse({"status": "ok"})

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots_txt(request: Request):
        sitemap_url = f"{_public_host(request, base_url)}/sitemap.xml"
        return PlainTextResponse(render_robots_txt(sitemap_url))

    @app.get("/sitemap.xml", name="sitemap_xml")
    def sitemap_xml(request: Request):
        host = _public_host(request, base_url)
        paths = ["/", "/quickstart", "/explore", "/alternatives"]
        paths += [f"/alternatives/{c.slug}" for c in COMPETITORS]
        today = datetime.now(timezone.utc).date().isoformat()
        body = build_sitemap_xml(base_url=host, urls=paths, lastmod=today)
        return Response(body, media_type="application/xml")

    @app.get("/quickstart", response_class=HTMLResponse)
    def quickstart(request: Request):
        return HTMLResponse(
            quickstart_tpl.render(
                **_seo_ctx(request, base_url),
            )
        )

    @app.get("/alternatives", response_class=HTMLResponse)
    def alternatives(request: Request):
        return HTMLResponse(
            alternatives_tpl.render(
                **_seo_ctx(request, base_url),
                competitors=COMPETITORS,
                markland=MARKLAND,
            )
        )

    @app.get("/alternatives/{slug}", response_class=HTMLResponse)
    def alternative(slug: str, request: Request):
        competitor = get_competitor(slug)
        if competitor is None:
            return HTMLResponse(
                "<html><body style='font-family:system-ui;padding:2rem;background:#0A0A0A;color:#fff;'>"
                "<h1>Alternative not found</h1>"
                "<p><a href='/alternatives' style='color:#4285F4;'>See all alternatives</a></p>"
                "</body></html>",
                status_code=404,
            )
        return HTMLResponse(
            alternative_tpl.render(
                **_seo_ctx(request, base_url),
                competitor=competitor,
                markland=MARKLAND,
            )
        )

    @app.get("/admin/audit", response_class=HTMLResponse)
    def admin_audit(request: Request):
        # Resolve bearer token here because PrincipalMiddleware only gates /mcp.
        from markland.service.auth import resolve_token

        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return JSONResponse({"error": "unauthenticated"}, status_code=401)
        plaintext = header[7:].strip()
        principal = resolve_token(db_conn, plaintext)
        if principal is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)
        if not principal.is_admin:
            return JSONResponse({"error": "forbidden"}, status_code=403)

        from markland.service import audit as audit_svc

        rows = audit_svc.list_recent(db_conn, limit=200)
        for r in rows:
            r["metadata_json"] = json.dumps(r["metadata"], sort_keys=True)
        return HTMLResponse(
            admin_audit_tpl.render(
                **_seo_ctx(request, base_url),
                rows=rows,
            )
        )

    @app.get("/", response_class=HTMLResponse)
    def landing(request: Request, signup: str | None = None):
        docs = list_featured_and_recent_public(db_conn, limit=4)
        cards = [_doc_to_card(d) for d in docs]
        signup_state = signup if signup in ("ok", "invalid") else None
        return HTMLResponse(
            landing_tpl.render(
                **_seo_ctx(request, base_url),
                docs=cards,
                mcp_config_json=mcp_snippet_json,
                signup=signup_state,
            )
        )

    @app.get("/explore", response_class=HTMLResponse)
    def explore(request: Request, q: str | None = None, view: str | None = None):
        principal = getattr(request.state, "principal", None)
        query = (q or "").strip() or None
        show_mine = view == "mine" and principal is not None

        if show_mine:
            from markland.service import docs as docs_svc_local
            mine = docs_svc_local.list_for_principal(db_conn, principal)
            # Re-fetch full docs so we can render cards consistently.
            from markland.db import get_document
            cards = []
            for summary in mine:
                doc = get_document(db_conn, summary["id"])
                if doc is None:
                    continue
                if query and (
                    query.lower() not in (doc.title or "").lower()
                    and query.lower() not in (doc.content or "").lower()
                ):
                    continue
                cards.append(_doc_to_card(doc))
            return HTMLResponse(
                explore_tpl.render(
                    **_seo_ctx(request, base_url),
                    docs=cards,
                    query=query,
                    total=len(cards),
                    view="mine",
                    authed=True,
                )
            )

        docs = list_public_documents(db_conn, query=query, limit=50)
        total_docs = list_public_documents(db_conn, query=query, limit=10_000)
        cards = [_doc_to_card(d) for d in docs]
        return HTMLResponse(
            explore_tpl.render(
                **_seo_ctx(request, base_url),
                docs=cards,
                query=query,
                total=len(total_docs),
                view="public",
                authed=principal is not None,
            )
        )

    @app.post("/api/waitlist")
    def join_waitlist(
        email: str = Form(...),
        source: str | None = Form(None),
    ):
        normalized = email.strip().lower()
        if not _valid_email(normalized):
            return RedirectResponse("/?signup=invalid", status_code=303)
        add_waitlist_email(db_conn, normalized, source)
        return RedirectResponse("/?signup=ok", status_code=303)

    @app.get("/d/{share_token}", response_class=HTMLResponse)
    def view_document(share_token: str, request: Request):
        doc = get_document_by_token(db_conn, share_token)
        if doc is None:
            return HTMLResponse(
                "<html><body style='font-family:system-ui;padding:2rem;'>"
                "<h1>Document not found</h1>"
                "</body></html>",
                status_code=404,
            )
        principal = getattr(request.state, "principal", None)
        principal_user_id = None
        if principal is not None:
            principal_user_id = (
                getattr(principal, "user_id", None) or principal.principal_id
            )
        is_owner = bool(
            principal_user_id and doc.owner_id and principal_user_id == doc.owner_id
        )
        grants_for_template: list = []
        if is_owner:
            from markland.db import list_grants_for_doc
            grants_for_template = [
                {"principal_id": g.principal_id, "level": g.level}
                for g in list_grants_for_doc(db_conn, doc.id)
            ]
        from markland.service import presence as _presence
        actives = _presence.list_active(db_conn, doc_id=doc.id)
        active_principals = [
            {
                "principal_id": a.principal_id,
                "principal_type": a.principal_type,
                "display_name": a.display_name or a.principal_id,
                "status": a.status,
                "note": a.note,
                "updated_at": a.updated_at,
                "minutes_ago": _minutes_ago(a.updated_at),
            }
            for a in actives
        ]
        forked_from = None
        forked_from_visible = False
        if doc.forked_from_doc_id:
            from markland.db import get_document

            parent = get_document(db_conn, doc.forked_from_doc_id)
            if parent is not None:
                forked_from = parent
                # Visible if public, or owned by viewer, or viewer has a grant.
                if parent.is_public:
                    forked_from_visible = True
                elif principal_user_id and parent.owner_id == principal_user_id:
                    forked_from_visible = True
                elif principal_user_id:
                    grant_row = db_conn.execute(
                        "SELECT 1 FROM grants WHERE doc_id = ? AND principal_id = ?",
                        (parent.id, principal_user_id),
                    ).fetchone()
                    forked_from_visible = grant_row is not None
        content_html = render_markdown(doc.content)
        html = document_tpl.render(
            **_seo_ctx(request, base_url),
            title=doc.title,
            content_html=content_html,
            created_at=doc.created_at,
            is_owner=is_owner,
            grants=grants_for_template,
            doc_id=doc.id,
            share_token=doc.share_token,
            active_principals=active_principals,
            forked_from=forked_from,
            forked_from_visible=forked_from_visible,
        )
        return HTMLResponse(html)

    app.include_router(
        build_auth_router(
            db_conn=db_conn,
            session_secret=session_secret,
            base_url=base_url,
            email_client=email_client,
        )
    )

    app.include_router(
        build_identity_router(
            db_conn=db_conn,
            session_secret=session_secret,
        )
    )

    app.include_router(
        build_grants_router(
            conn=db_conn,
            base_url=base_url,
            email_client=email_client,
        )
    )

    from markland.web.dashboard import build_router as build_dashboard_router
    app.include_router(
        build_dashboard_router(conn=db_conn, session_secret=session_secret)
    )

    from markland.web.save_routes import build_router as build_save_router
    app.include_router(
        build_save_router(
            conn=db_conn,
            session_secret=session_secret,
            base_url=base_url,
        )
    )

    from markland.web.settings import router as settings_router
    app.include_router(settings_router)

    from markland.web.routes_agents import build_agents_router
    agents_api_router, agents_html_router = build_agents_router(
        db_conn, session_secret=session_secret
    )
    app.include_router(agents_api_router)
    app.include_router(agents_html_router)

    from markland.web.invite_routes import build_invite_router
    app.include_router(
        build_invite_router(
            db_conn=db_conn,
            base_url=base_url,
            jinja_env=env,
            email_client=email_client,
            session_secret=session_secret,
        )
    )

    from markland.web.device_routes import build_device_router
    app.include_router(
        build_device_router(
            db_conn=db_conn,
            base_url=base_url,
            jinja_env=env,
            session_secret=session_secret,
        )
    )

    from markland.web.presence_api import build_presence_router
    app.include_router(
        build_presence_router(
            db_conn=db_conn,
            session_secret=session_secret,
        )
    )

    # Test-only principal injection: in production PrincipalMiddleware wires
    # `request.state.principal`; here we accept a header→Principal map so
    # api_grants/dashboard tests can exercise the full stack without tokens.
    if test_principal_by_token:
        @app.middleware("http")
        async def _inject_principal(request, call_next):
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                tok = auth[7:]
                if tok in test_principal_by_token:
                    request.state.principal = test_principal_by_token[tok]
            return await call_next(request)

    if mcp_app is not None:
        from markland.web.principal_middleware import PrincipalMiddleware

        # Middleware gates /mcp before the sub-app sees the request.
        app.add_middleware(
            PrincipalMiddleware,
            db_conn=db_conn,
            protected_prefix="/mcp",
        )
        app.mount("/mcp", mcp_app)

    # Rate-limit every incoming request. Starlette applies middleware in reverse
    # of addition order, so adding this LAST means it runs FIRST on requests —
    # actually wait: starlette wraps add_middleware top-down, so the last-added
    # middleware wraps the outermost handler and runs first on the request. We
    # want RateLimit OUTERMOST so Principal is computed inside if present; the
    # middleware also does its own lazy principal resolution for tiering.
    from markland.web.rate_limit_middleware import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware, db_conn=db_conn)

    return app
