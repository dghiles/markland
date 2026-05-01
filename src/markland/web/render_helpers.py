"""Render helpers that auto-inject the signed-in nav + base.html context.

Every base.html-extending template needs three context kwargs that are
trivial to forget: `signed_in_user` (for the banner partial),
`request` (for the _seo_meta partial's `request.url.path`), and
`canonical_host` (for _seo_meta's og: and JSON-LD URLs). Forgetting any
of them is a silent failure: forgetting `signed_in_user` makes the
banner disappear; forgetting `request`/`canonical_host` raises a
Jinja `UndefinedError` mid-render.

Handlers that render a template with the signed-in nav banner used to
duplicate `signed_in_user = signed_in_user_ctx(...)` plus pass-through
boilerplate at every call site. That triplicated quickly (landing, doc,
explore) and got missed entirely on settings/tokens, settings/agents,
verify_sent, dashboard, and the static-page handlers — so the banner
silently disappeared whenever a signed-in user navigated to those.
PR #34 then added a duplicate `_canonical_host(request)` helper inside
`auth_routes.py` for the same purpose. This wrapper subsumes both.

`render_with_nav` does the lookups once and passes the results alongside
the caller's kwargs. Callers can override any of the three by passing
the kwarg explicitly; explicit wins.
"""

from __future__ import annotations

import sqlite3

from starlette.requests import Request

from markland.web.session_principal import signed_in_user_ctx


def _canonical_host(request: Request, base_url: str) -> str:
    """Return the canonical scheme://host string for this request.

    Prefers `base_url` when configured (immune to Host-header spoofing).
    Falls back to the request URL, honoring `x-forwarded-proto` so reverse-
    proxied HTTPS traffic yields the right scheme. Mirrors `_public_host`
    in `web/app.py` and the `_canonical_host` PR #34 added to auth_routes;
    consolidates both into one place.
    """
    if base_url:
        return base_url.rstrip("/")
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{scheme}://{request.url.netloc}"


def render_with_nav(
    tpl,
    request: Request,
    conn: sqlite3.Connection,
    *,
    base_url: str = "",
    secret: str | None = None,
    **ctx,
) -> str:
    """Render `tpl` with the three base.html context kwargs auto-injected.

    Auto-injects:
        - signed_in_user: dict with `email`, or None (for the banner partial)
        - request: the FastAPI Request itself (for _seo_meta)
        - canonical_host: scheme+host string (for _seo_meta + JSON-LD)

    Caller-provided kwargs win — pass `signed_in_user=None` (etc.) to
    override the auto-resolution. Used today for: admin-impersonation
    previews, tests asserting on a specific banner state, etc.
    """
    # `if "X" not in ctx` (not setdefault) so signed_in_user_ctx is skipped
    # when the caller overrode signed_in_user — saves a SQLite lookup and
    # respects the explicit-wins precedence semantic.
    if "signed_in_user" not in ctx:
        ctx["signed_in_user"] = signed_in_user_ctx(request, conn, secret=secret)
    if "request" not in ctx:
        ctx["request"] = request
    if "canonical_host" not in ctx:
        ctx["canonical_host"] = _canonical_host(request, base_url)
    return tpl.render(**ctx)
