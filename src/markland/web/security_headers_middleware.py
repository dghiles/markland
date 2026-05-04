"""Starlette middleware that adds security + crawl-hygiene headers.

Mirrors the BaseHTTPMiddleware pattern used by RateLimitMiddleware. Every
response gets HSTS, a conservative CSP, XFO/XCTO/Referrer-Policy/
Permissions-Policy. Non-marketing paths additionally receive
`X-Robots-Tag: noindex, nofollow` — belt-and-suspenders on top of
robots.txt, because 401/405 responses do not themselves prevent indexing.

P2-B / markland-yxv: each request also gets a per-request CSP nonce on
`request.state.csp_nonce`. The nonce is woven into the
`Content-Security-Policy` header (`script-src 'self' 'nonce-…'`) and
exposed to Jinja via the `csp_nonce()` global so templates can stamp
`<script nonce="{{ csp_nonce() }}">`. `'unsafe-inline'` is dropped from
script-src — only nonce'd inline scripts execute.
"""

from __future__ import annotations

import os
import secrets
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from markland.web.seo import should_noindex


def _origin_of(url: str) -> str:
    """Return scheme://host[:port] of a URL, or '' if unparseable."""
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def build_csp(umami_script_url: str = "", *, nonce: str | None = None) -> str:
    """Assemble the CSP string, allowing the Umami host when configured.

    Umami Cloud is a two-host topology: script.js is served from
    cloud.umami.is, but the beacon POSTs to api-gateway.umami.dev — a
    different origin. Single-origin CSP would block the beacon and produce
    zero pageviews silently. To handle both Cloud and any future Umami
    gateway moves, allow https://*.umami.is and https://*.umami.dev on
    connect-src whenever the (default) cloud script URL is in use. For a
    custom UMAMI_SCRIPT_URL (self-host), add only that single origin to
    both directives — self-hosters typically run script + API at the same
    origin.

    P2-B / markland-yxv: when a per-request `nonce` is supplied, drop
    `'unsafe-inline'` from script-src and add `'nonce-…'`. Without a
    nonce (e.g. tests calling build_csp() directly with no request),
    fall back to the legacy `'unsafe-inline'` behaviour so callers don't
    have to thread a nonce through to test the header shape.
    style-src keeps `'unsafe-inline'` for now: Pygments emits inline
    style attributes in code blocks; nonce'ing styles is separate work.
    """
    umami_origin = _origin_of(umami_script_url)
    if not umami_origin:
        connect_extra = ""
        script_extra = ""
    elif umami_origin in ("https://cloud.umami.is", "http://cloud.umami.is"):
        # Umami Cloud: script on cloud.umami.is, beacon on
        # api-gateway.umami.dev. Wildcard both umami families on connect-src
        # to be resilient to future API host moves.
        script_extra = f" {umami_origin}"
        connect_extra = " https://*.umami.is https://*.umami.dev"
    else:
        # Self-host: script and API on the same configured origin.
        script_extra = f" {umami_origin}"
        connect_extra = f" {umami_origin}"
    if nonce:
        script_directive = f"script-src 'self' 'nonce-{nonce}'{script_extra}"
    else:
        script_directive = f"script-src 'self' 'unsafe-inline'{script_extra}"
    return (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "img-src 'self' data:; "
        f"{script_directive}; "
        f"connect-src 'self'{connect_extra}; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


_CSP = build_csp()  # default — overridden per-app via constructor


def generate_csp_nonce() -> str:
    """Return a fresh URL-safe CSP nonce (16 bytes ≈ 22 chars base64)."""
    return secrets.token_urlsafe(16)

# Pre-canonical-domain: short HSTS max-age so we can unwind without waiting
# a year if the *.fly.dev deployment changes. Bump to 31536000 once the
# canonical domain is live and stable by setting MARKLAND_HSTS_MAX_AGE.
# Do not enable `preload` until after the canonical domain swap.
_HSTS_MAX_AGE = int(os.environ.get("MARKLAND_HSTS_MAX_AGE", "86400"))
_HSTS = f"max-age={_HSTS_MAX_AGE}; includeSubDomains"

_PERMISSIONS = "geolocation=(), camera=(), microphone=(), payment=()"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        csp: str | None = None,
        *,
        umami_script_url: str = "",
    ) -> None:
        super().__init__(app)
        # When `csp` is supplied, the caller has fully assembled the CSP
        # string and does NOT want per-request nonce injection (legacy
        # path). When omitted, we inject a fresh nonce on every request.
        self._static_csp = csp
        self._umami_script_url = umami_script_url

    async def dispatch(self, request: Request, call_next) -> Response:
        # P2-B / markland-yxv: mint a fresh nonce per request and stash
        # it on request.state so templates / handlers can pull it
        # without a thread-local.
        if self._static_csp is None:
            nonce = generate_csp_nonce()
            request.state.csp_nonce = nonce
            csp = build_csp(self._umami_script_url, nonce=nonce)
        else:
            csp = self._static_csp
        response = await call_next(request)
        response.headers.setdefault("strict-transport-security", _HSTS)
        response.headers.setdefault("content-security-policy", csp)
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("x-frame-options", "DENY")
        response.headers.setdefault(
            "referrer-policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault("permissions-policy", _PERMISSIONS)
        if should_noindex(request.url.path):
            response.headers.setdefault("x-robots-tag", "noindex, nofollow")
        return response
