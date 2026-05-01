"""Starlette middleware that adds security + crawl-hygiene headers.

Mirrors the BaseHTTPMiddleware pattern used by RateLimitMiddleware. Every
response gets HSTS, a conservative CSP, XFO/XCTO/Referrer-Policy/
Permissions-Policy. Non-marketing paths additionally receive
`X-Robots-Tag: noindex, nofollow` — belt-and-suspenders on top of
robots.txt, because 401/405 responses do not themselves prevent indexing.
"""

from __future__ import annotations

import os
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


def build_csp(umami_script_url: str = "") -> str:
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
    return (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "img-src 'self' data:; "
        f"script-src 'self' 'unsafe-inline'{script_extra}; "
        f"connect-src 'self'{connect_extra}; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


_CSP = build_csp()  # default — overridden per-app via constructor

# Pre-canonical-domain: short HSTS max-age so we can unwind without waiting
# a year if the *.fly.dev deployment changes. Bump to 31536000 once the
# canonical domain is live and stable by setting MARKLAND_HSTS_MAX_AGE.
# Do not enable `preload` until after the canonical domain swap.
_HSTS_MAX_AGE = int(os.environ.get("MARKLAND_HSTS_MAX_AGE", "86400"))
_HSTS = f"max-age={_HSTS_MAX_AGE}; includeSubDomains"

_PERMISSIONS = "geolocation=(), camera=(), microphone=(), payment=()"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, csp: str | None = None):
        super().__init__(app)
        self._csp = csp or _CSP

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("strict-transport-security", _HSTS)
        response.headers.setdefault("content-security-policy", self._csp)
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("x-frame-options", "DENY")
        response.headers.setdefault(
            "referrer-policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault("permissions-policy", _PERMISSIONS)
        if should_noindex(request.url.path):
            response.headers.setdefault("x-robots-tag", "noindex, nofollow")
        return response
