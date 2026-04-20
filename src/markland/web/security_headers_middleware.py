"""Starlette middleware that adds security + crawl-hygiene headers.

Mirrors the BaseHTTPMiddleware pattern used by RateLimitMiddleware. Every
response gets HSTS, a conservative CSP, XFO/XCTO/Referrer-Policy/
Permissions-Policy. Non-marketing paths additionally receive
`X-Robots-Tag: noindex, nofollow` — belt-and-suspenders on top of
robots.txt, because 401/405 responses do not themselves prevent indexing.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from markland.web.seo import should_noindex

_CSP = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "script-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

# Do not enable `preload` until the canonical domain is live and stable.
_HSTS = "max-age=31536000; includeSubDomains"

_PERMISSIONS = "geolocation=(), camera=(), microphone=(), payment=()"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("strict-transport-security", _HSTS)
        response.headers.setdefault("content-security-policy", _CSP)
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("x-frame-options", "DENY")
        response.headers.setdefault(
            "referrer-policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault("permissions-policy", _PERMISSIONS)
        if should_noindex(request.url.path):
            response.headers["x-robots-tag"] = "noindex, nofollow"
        return response
