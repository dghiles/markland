"""Middleware that resolves Bearer tokens to Principals on protected paths.

Replaces the Plan-1 `AdminBearerMiddleware`. On a request under `protected_prefix`:
  1. Extract `Authorization: Bearer <token>`.
  2. Call `service.auth.resolve_token`.
  3. On success, attach the `Principal` to `request.state.principal`.
  4. On any failure (no header, malformed header, unknown/revoked token) return 401.
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
        protected_prefix: str = "/mcp",
    ) -> None:
        super().__init__(app)
        self._conn = db_conn
        self._prefix = protected_prefix

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(self._prefix):
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
