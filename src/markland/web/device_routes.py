"""HTTP routes for the OAuth-2.0-device-flow onboarding surface (Plan 6).

Exposes:
    POST /api/auth/device-start       — CLI requests a device_code + user_code
    POST /api/auth/device-poll        — CLI polls for authorization
    POST /api/auth/device-authorize   — session-authed JSON confirmation
    GET  /device                      — consent HTML page
    POST /device/confirm              — HTML form confirmation (redirects)
    GET  /device/done                 — confirmation page
    GET  /setup                       — text/markdown runbook for Claude Code
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections import defaultdict, deque
from typing import Deque
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Body, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from jinja2 import Environment
from pydantic import BaseModel

from markland.service import device_flow
from markland.service.sessions import (
    SESSION_COOKIE_NAME,
    InvalidSession,
    make_csrf_token,
    read_session,
    verify_csrf_token,
)

logger = logging.getLogger("markland.device_flow")


class SlidingWindowRateLimiter:
    """Per-key sliding-window rate limiter with periodic stale-key GC.

    Without GC the backing dict grows unboundedly with distinct keys seen
    over process lifetime. GC drops keys whose most recent hit is older than
    the window; cost is O(N) over distinct keys, amortized across
    `prune_every` calls so steady-state overhead is ~constant.
    """

    def __init__(self, *, limit: int, window: float, prune_every: int = 1000) -> None:
        self.limit = limit
        self.window = window
        self._prune_every = prune_every
        self._hits: dict[str, Deque[float]] = defaultdict(deque)
        self._calls_since_prune = 0

    def check(self, key: str) -> tuple[bool, int]:
        self._calls_since_prune += 1
        if self._calls_since_prune >= self._prune_every:
            self._prune()
            self._calls_since_prune = 0

        now = time.time()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            retry_after = int(self.window - (now - q[0])) + 1
            return False, retry_after
        q.append(now)
        return True, 0

    def _prune(self) -> None:
        now = time.time()
        stale = [k for k, q in self._hits.items() if not q or now - q[-1] > self.window]
        for k in stale:
            del self._hits[k]


class DeviceStartBody(BaseModel):
    invite_token: str | None = None


class DevicePollBody(BaseModel):
    device_code: str


class DeviceAuthorizeBody(BaseModel):
    user_code: str


def build_device_router(
    *,
    db_conn: sqlite3.Connection,
    base_url: str,
    jinja_env: Environment,
    session_secret: str,
) -> APIRouter:
    """Return an APIRouter wiring all device-flow HTTP routes."""
    router = APIRouter()

    device_tpl = jinja_env.get_template("device.html")
    device_done_tpl = jinja_env.get_template("device_done.html")

    # --- Per-IP rate limits (in-process, sliding window with periodic GC) ---

    _device_start_limiter = SlidingWindowRateLimiter(limit=10, window=60)
    _device_confirm_limiter = SlidingWindowRateLimiter(limit=10, window=60)

    def _client_ip(request: Request) -> str:
        # P2-C / markland-91j: only `Fly-Client-IP` is trusted. Reading
        # the first hop of X-Forwarded-For would let an attacker spoof
        # their rate-limit key for /device/start and /device/confirm.
        from markland.web._request_ip import trusted_client_ip
        return trusted_client_ip(request)

    def _rate_limit_device_start(ip: str) -> tuple[bool, int]:
        return _device_start_limiter.check(ip)

    def _rate_limit_device_confirm(ip: str) -> tuple[bool, int]:
        return _device_confirm_limiter.check(ip)

    # --- Session helpers ---

    def _session_user_id(request: Request) -> str | None:
        cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
        if not cookie:
            return None
        try:
            payload = read_session(cookie, secret=session_secret)
        except InvalidSession:
            return None
        uid = payload.get("user_id")
        return uid if isinstance(uid, str) else None

    # -------------------------------------------------------------------
    # POST /api/auth/device-start
    # -------------------------------------------------------------------

    @router.post("/api/auth/device-start")
    def api_device_start(request: Request, body: DeviceStartBody | None = None):
        ip = _client_ip(request)
        ok, retry_after = _rate_limit_device_start(ip)
        if not ok:
            return JSONResponse(
                {"error": "rate_limited", "retry_after": retry_after},
                status_code=429,
            )
        invite_token = body.invite_token if body else None
        result = device_flow.start(
            db_conn, invite_token=invite_token, base_url=base_url,
        )
        return JSONResponse({
            "device_code": result.device_code,
            "user_code": result.user_code,
            "verification_url": result.verification_url,
            "poll_interval": result.poll_interval,
            "expires_in": result.expires_in,
        })

    # -------------------------------------------------------------------
    # POST /api/auth/device-poll
    # -------------------------------------------------------------------

    @router.post("/api/auth/device-poll")
    def api_device_poll(body: DevicePollBody = Body(...)):
        return JSONResponse(device_flow.poll(db_conn, body.device_code))

    # -------------------------------------------------------------------
    # POST /api/auth/device-authorize
    # -------------------------------------------------------------------

    @router.post("/api/auth/device-authorize")
    def api_device_authorize(request: Request, body: DeviceAuthorizeBody = Body(...)):
        user_id = _session_user_id(request)
        if user_id is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)
        result = device_flow.authorize(
            db_conn, body.user_code, user_id=user_id,
        )
        if not result.ok:
            if result.reason == "not_found":
                return JSONResponse({"error": "not_found"}, status_code=404)
            if result.reason == "expired":
                return JSONResponse({"error": "expired"}, status_code=410)
            if result.reason == "already_authorized":
                return JSONResponse({"error": "already_authorized"}, status_code=410)
            return JSONResponse({"error": result.reason or "invalid"}, status_code=400)
        return JSONResponse({
            "ok": True,
            "invite_accepted": result.invite_accepted,
            "invite_error": result.invite_error,
        })

    # -------------------------------------------------------------------
    # GET /device
    # -------------------------------------------------------------------

    def _describe_invite(invite_token: str | None):
        if not invite_token:
            return None
        try:
            from markland.service import invites as invites_mod
            describe = getattr(invites_mod, "describe_invite", None)
            if describe is None:
                return None
            return describe(db_conn, invite_token=invite_token)
        except Exception:  # pragma: no cover — defensive
            return None

    def _lookup_by_user_code(raw_or_formatted: str):
        normalized = device_flow.normalize_user_code(raw_or_formatted)
        return db_conn.execute(
            "SELECT device_code, user_code, invite_token "
            "FROM device_authorizations WHERE user_code = ?",
            (normalized,),
        ).fetchone()

    def _session_obj(user_id: str | None):
        """Minimal session object for template rendering."""
        if user_id is None:
            return None
        row = db_conn.execute(
            "SELECT display_name FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        display_name = row[0] if row else None
        return type("SessionView", (), {
            "user_id": user_id,
            "display_name": display_name,
        })()

    @router.get("/device", response_class=HTMLResponse)
    def page_device(request: Request, code: str | None = None):
        user_id = _session_user_id(request)
        session = _session_obj(user_id)
        invite_token = None
        if code and session is not None:
            row = _lookup_by_user_code(code)
            if row is not None:
                invite_token = row[2]
        csrf = make_csrf_token(user_id, secret=session_secret) if user_id else ""
        return HTMLResponse(
            device_tpl.render(
                session=session,
                code=code,
                csrf=csrf,
                invite_token=invite_token,
                invite_description=_describe_invite(invite_token),
                error=None,
            )
        )

    # -------------------------------------------------------------------
    # POST /device/confirm
    # -------------------------------------------------------------------

    @router.post("/device/confirm")
    def page_device_confirm(
        request: Request,
        user_code: str = Form(...),
        csrf: str = Form(...),
    ):
        ip = _client_ip(request)
        ok, retry_after = _rate_limit_device_confirm(ip)
        if not ok:
            return JSONResponse(
                {"error": "rate_limited", "retry_after": retry_after},
                status_code=429,
            )
        user_id = _session_user_id(request)
        session = _session_obj(user_id)
        if user_id is None:
            # urlencode the inner query so `next=` survives URL parsing — bare
            # `?next=/device?code=…` splits at the second `?` and the browser
            # treats `code=…` as a top-level param on /login, dropping it from
            # the next= value entirely.
            next_path = f"/device?code={quote(user_code, safe='')}"
            return RedirectResponse(
                url=f"/login?{urlencode({'next': next_path})}", status_code=303
            )
        if not verify_csrf_token(csrf, user_id, secret=session_secret):
            return HTMLResponse(
                device_tpl.render(
                    session=session, code=user_code, csrf="",
                    invite_token=None, invite_description=None,
                    error="Your session expired. Reload the page and try again.",
                ),
                status_code=400,
            )
        result = device_flow.authorize(db_conn, user_code, user_id=user_id)
        if not result.ok:
            human = {
                "not_found": "We couldn't find that code. Double-check what your CLI showed you.",
                "expired": "That code has expired. Run the CLI step again to get a new one.",
                "already_authorized": "That code has already been used.",
            }.get(result.reason or "", "Couldn't authorize that code.")
            return HTMLResponse(
                device_tpl.render(
                    session=session,
                    code=user_code,
                    csrf=make_csrf_token(user_id, secret=session_secret),
                    invite_token=None,
                    invite_description=None,
                    error=human,
                ),
                status_code=400,
            )
        # Build redirect URL with optional invite_accepted / invite_error params.
        params = [f"code={result.user_code}"]
        if result.invite_accepted:
            params.append("invite_accepted=1")
        if result.invite_error:
            params.append(f"invite_error={quote(result.invite_error)}")
        return RedirectResponse(
            url=f"/device/done?{'&'.join(params)}",
            status_code=303,
        )

    # -------------------------------------------------------------------
    # GET /device/done
    # -------------------------------------------------------------------

    @router.get("/device/done", response_class=HTMLResponse)
    def page_device_done(
        code: str | None = None,
        invite_accepted: str | None = None,
        invite_error: str | None = None,
    ):
        return HTMLResponse(
            device_done_tpl.render(
                code=code,
                invite_accepted=(invite_accepted == "1"),
                invite_error=invite_error,
            )
        )

    # -------------------------------------------------------------------
    # GET /setup
    # -------------------------------------------------------------------

    @router.get("/setup")
    def page_setup(invite: str | None = None):
        host = base_url.rstrip("/") if base_url else ""
        start_body = (
            f'{{"invite_token": "{invite}"}}'
            if invite
            else "{}"
        )
        runbook = f"""# Markland setup

**For humans:** This URL is the install runbook for the Markland MCP server.
It is meant to be read by Claude Code, not run in a terminal. To install,
open Claude Code (CLI or web) and send this message:

> Install the Markland MCP server from {host}/setup

Claude Code will fetch this page, walk you through a one-time browser
authorization, and finish the install.

---

You are Claude Code. A user pasted this URL to install the Markland MCP server.
Execute the steps below end-to-end. Do not ask the user for input beyond what
step 2 instructs.

## 1. Start a device authorization

```
POST {host}/api/auth/device-start
Content-Type: application/json

{start_body}
```

Parse the JSON response. It has shape:

```
{{
  "device_code":       "<long opaque string>",
  "user_code":         "ABCD-EFGH",
  "verification_url":  "{host}/device",
  "poll_interval":     5,
  "expires_in":        600
}}
```

## 2. Show the user exactly this message

> Visit **{host}/device** and enter the code **ABCD-EFGH**.
> The code expires in 10 minutes.

(Substitute the real `user_code` from step 1.)

## 3. Poll until authorized

Every `poll_interval` seconds (5s), call:

```
POST {host}/api/auth/device-poll
Content-Type: application/json

{{"device_code": "<from step 1>"}}
```

Response statuses:
- `{{"status": "pending"}}`   — keep polling.
- `{{"status": "slow_down"}}` — you polled too fast; wait an extra 5s.
- `{{"status": "expired"}}`   — the code ran out; start over from step 1.
- `{{"status": "authorized", "access_token": "mk_usr_..."}}` — done. Capture the token.

Stop polling after `expires_in` seconds regardless.

## 4. Install the MCP server

Prefer the CLI form:

```
claude mcp add --transport http --scope user markland --header="Authorization: Bearer $ACCESS_TOKEN" {host}/mcp/
```

If `claude mcp add` is unavailable, edit `~/.mcp.json` to include:

```json
{{
  "mcpServers": {{
    "markland": {{
      "type": "http",
      "url": "{host}/mcp/",
      "headers": {{
        "Authorization": "Bearer <paste the access_token from step 3>"
      }}
    }}
  }}
}}
```

## 5. Restart Claude Code and verify

Restart Claude Code, then call the `markland_whoami` tool. Expect a response
like `{{"principal_id": "usr_...", "principal_type": "user", ...}}`.

If `markland_whoami` returns `unauthenticated`, the token wasn't installed —
re-run step 4 and restart again.
"""
        return Response(
            content=runbook,
            media_type="text/markdown; charset=utf-8",
        )

    return router
