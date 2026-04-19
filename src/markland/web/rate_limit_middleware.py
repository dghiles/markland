"""Starlette middleware that rate-limits every request using service/rate_limit.

Ordering: MUST be installed AFTER PrincipalMiddleware so `request.state.principal`
is already populated. In create_app we add PrincipalMiddleware first, then this.

Tier selection:
  - user token  -> 60/min   (key: principal_id)
  - agent token -> 120/min  (key: principal_id)
  - anonymous   -> 20/min   (key: X-Forwarded-For first hop, else client.host)

Env overrides:
  MARKLAND_RATE_LIMIT_USER_PER_MIN
  MARKLAND_RATE_LIMIT_AGENT_PER_MIN
  MARKLAND_RATE_LIMIT_ANON_PER_MIN
"""

from __future__ import annotations

import math
import os
import sqlite3

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from markland.service import metrics
from markland.service.rate_limit import RateLimiter


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        limiter: RateLimiter | None = None,
        db_conn: sqlite3.Connection | None = None,
    ) -> None:
        super().__init__(app)
        if limiter is None:
            limiter = RateLimiter(
                defaults={
                    "user": (_int_env("MARKLAND_RATE_LIMIT_USER_PER_MIN", 60), 60),
                    "agent": (_int_env("MARKLAND_RATE_LIMIT_AGENT_PER_MIN", 120), 60),
                    "anon": (_int_env("MARKLAND_RATE_LIMIT_ANON_PER_MIN", 20), 60),
                },
                max_keys=10_000,
            )
        self._limiter = limiter
        self._conn = db_conn

    def _client_ip(self, request: Request) -> str:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _resolve_principal_lazy(self, request: Request):
        """Fallback principal resolution for non-/mcp paths.

        PrincipalMiddleware only runs for /mcp; on other endpoints we still want
        to identify the caller for rate-limit tiering. Do a best-effort token
        resolve if a Bearer header is present.
        """
        principal = getattr(request.state, "principal", None)
        if principal is not None:
            return principal
        if self._conn is None:
            return None
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return None
        from markland.service.auth import resolve_token

        try:
            principal = resolve_token(self._conn, auth[7:].strip())
        except Exception:
            principal = None
        if principal is not None:
            request.state.principal = principal
        return principal

    async def dispatch(self, request: Request, call_next):
        principal = self._resolve_principal_lazy(request)
        if principal is None:
            tier = "anon"
            key = f"ip:{self._client_ip(request)}"
        else:
            tier = "user" if principal.principal_type == "user" else "agent"
            key = f"{principal.principal_type}:{principal.principal_id}"
            if request.url.path.startswith("/mcp"):
                try:
                    metrics.emit_first_time(
                        "first_mcp_call", principal_id=principal.principal_id
                    )
                except Exception:
                    pass

        decision = await self._limiter.check(key, tier=tier)
        if not decision.allowed:
            retry = max(1, math.ceil(decision.retry_after))
            return JSONResponse(
                {"error": "rate_limited", "retry_after": retry},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
        return await call_next(request)
