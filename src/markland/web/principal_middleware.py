"""Middleware that resolves Bearer tokens to Principals on protected paths.

Replaces the Plan-1 `AdminBearerMiddleware`. On a request whose path matches
ANY of `protected_prefixes`:
  1. If `request.state.principal` is already set (e.g. by a test injection
     middleware), pass through.
  2. Extract `Authorization: Bearer <token>`.
  3. Call `service.auth.resolve_token`.
  4. On success, attach the `Principal` to `request.state.principal`.
  5. On any failure (no header, malformed header, unknown/revoked token) return 401.
"""

from __future__ import annotations

import sqlite3

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from markland.service.auth import resolve_token


class PrincipalMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        db_conn: sqlite3.Connection,
        protected_prefixes: tuple[str, ...] = ("/mcp",),
    ) -> None:
        super().__init__(app)
        self._conn = db_conn
        self._prefixes = tuple(protected_prefixes)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not any(path.startswith(p) for p in self._prefixes):
            return await call_next(request)

        # Honor pre-injected principals (test harness path).
        if getattr(request.state, "principal", None) is not None:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return JSONResponse({"error": "unauthenticated"}, status_code=401)

        plaintext = header[7:].strip()
        principal = resolve_token(self._conn, plaintext)
        if principal is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)

        request.state.principal = principal
        return await call_next(request)
