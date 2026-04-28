"""MCP test harness — dual-backend (direct + http) with snapshot baselines.

See docs/specs/2026-04-27-mcp-audit-design.md §4-§11 for design.
"""

from __future__ import annotations

import difflib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from markland.db import init_db
from markland.server import build_mcp
from markland.service.auth import Principal, create_user_token
from markland.service.users import create_user


class _CapturingEmailClient:
    """In-memory email capture for tests. Mirrors EmailClient.send signature."""

    def __init__(self):
        self.sent: list[dict] = []

    def send(
        self,
        *,
        to: str,
        subject: str,
        html: str | None = None,
        text: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.sent.append(
            {"to": to, "subject": subject, "html": html, "text": text,
             "metadata": metadata}
        )


Mode = Literal["direct", "http"]


@dataclass
class Caller:
    """A test principal with a bound token, calling MCP tools."""

    principal: Principal | None
    token: str | None
    _harness: "MCPHarness" = field(repr=False)
    _http_session_id: str | None = None

    @property
    def principal_id(self) -> str | None:
        return self.principal.principal_id if self.principal else None

    def call_raw(self, tool: str, **kwargs: Any) -> "Response":
        h = self._harness
        if h.mode == "direct":
            return _direct_call(h, self, tool, kwargs)
        elif h.mode == "http":
            return _http_call(h, self, tool, kwargs)
        raise MCPHarnessError(f"unknown mode {h.mode!r}")

    def call(self, tool: str, **kwargs: Any) -> Any:
        r = self.call_raw(tool, **kwargs)
        if not r.ok:
            raise MCPCallError(r, tool, kwargs)
        return r.value


@dataclass
class MCPHarness:
    """Test fixture for driving the Markland MCP. Direct or HTTP backend."""

    mode: Mode
    db: sqlite3.Connection
    base_url: str
    _mcp: Any  # FastMCP instance
    _tmp_path: Path
    _user_cache: dict[str, Caller] = field(default_factory=dict)
    _agent_cache: dict[str, Caller] = field(default_factory=dict)

    @classmethod
    def create(cls, tmp_path: Path, *, mode: Mode = "direct") -> "MCPHarness":
        tmp_path = Path(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        db_path = tmp_path / "harness.db"
        db = init_db(db_path)
        base_url = "https://harness.test"
        email_client = _CapturingEmailClient()
        mcp = build_mcp(db, base_url=base_url, email_client=email_client)

        harness = cls(
            mode=mode,
            db=db,
            base_url=base_url,
            _mcp=mcp,
            _tmp_path=tmp_path,
        )
        harness._email_client = email_client

        if mode == "http":
            # Set rate-limit env vars BEFORE create_app, since the app reads
            # them at build time. Setting after create_app has no effect.
            import os
            os.environ.setdefault("MARKLAND_RATE_LIMIT_USER_PER_MIN", "10000")
            os.environ.setdefault("MARKLAND_RATE_LIMIT_AGENT_PER_MIN", "10000")
            os.environ.setdefault("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "10000")

            from fastapi.testclient import TestClient
            from markland.web.app import create_app

            app = create_app(
                db,
                mount_mcp=True,
                base_url=base_url,
                session_secret="harness-secret",
            )

            client = TestClient(app)
            client.__enter__()  # start lifespan
            harness._http_client = client
            harness._http_app = app

        return harness

    def close(self) -> None:
        """Release resources. Safe to call multiple times."""
        if hasattr(self, "_http_client"):
            try:
                self._http_client.__exit__(None, None, None)
            except Exception:
                pass
        try:
            self.db.close()
        except Exception:
            pass

    def as_user(
        self,
        *,
        email: str,
        is_admin: bool = False,
        fresh: bool = False,
    ) -> Caller:
        key = email.lower()
        cached = self._user_cache.get(key)
        if cached is not None and not fresh:
            return cached

        # Find or create user.
        row = self.db.execute(
            "SELECT id FROM users WHERE lower(email) = lower(?)", (email,)
        ).fetchone()
        if row is None:
            user = create_user(self.db, email=email, display_name=None)
            user_id = user.id
        else:
            user_id = row[0]

        if is_admin:
            self.db.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,)
            )
            self.db.commit()

        # Mint a token.
        _, plaintext = create_user_token(self.db, user_id=user_id, label="harness")

        principal = Principal(
            principal_id=user_id,
            principal_type="user",
            display_name=None,
            is_admin=is_admin,
            user_id=None,
        )
        caller = Caller(principal=principal, token=plaintext, _harness=self)
        if not fresh:
            self._user_cache[key] = caller
        return caller

    def as_admin(self) -> Caller:
        return self.as_user(email="admin@harness.test", is_admin=True)

    def as_agent(
        self,
        *,
        owner_email: str,
        display_name: str = "test-agent",
        fresh: bool = False,
    ) -> Caller:
        cache_key = f"{owner_email.lower()}:{display_name}"
        cached = self._agent_cache.get(cache_key)
        if cached is not None and not fresh:
            return cached

        # Ensure owner exists.
        owner = self.as_user(email=owner_email)

        from markland.service.agents import create_agent

        agent = create_agent(
            self.db,
            owner_user_id=owner.principal_id,
            display_name=display_name,
        )

        from markland.service.auth import create_agent_token

        _, plaintext = create_agent_token(
            self.db,
            agent_id=agent.id,
            owner_user_id=owner.principal_id,
            label="harness",
        )

        principal = Principal(
            principal_id=agent.id,
            principal_type="agent",
            display_name=display_name,
            is_admin=False,
            user_id=owner.principal_id,
        )
        caller = Caller(principal=principal, token=plaintext, _harness=self)
        if not fresh:
            self._agent_cache[cache_key] = caller
        return caller

    def anon(self) -> Caller:
        return Caller(principal=None, token=None, _harness=self)

    def emails_sent_to(self, recipient: str) -> list[dict]:
        return [
            e for e in self._email_client.sent
            if e["to"].lower() == recipient.lower()
        ]


@dataclass
class Response:
    """Wrapper over a tool call result. Normalizes success and error shapes."""

    ok: bool
    value: dict | list | None
    error_code: str | None
    error_data: dict
    raw: Any

    def assert_ok(self) -> None:
        if not self.ok:
            raise AssertionError(
                f"expected ok response, got error_code={self.error_code!r} "
                f"data={self.error_data!r}"
            )

    def assert_error(self, code: str, **expected_data: Any) -> None:
        if self.ok:
            raise AssertionError(
                f"expected error_code={code!r}, got ok response value={self.value!r}"
            )
        if self.error_code != code:
            raise AssertionError(
                f"expected error_code={code!r}, got {self.error_code!r}"
            )
        for key, value in expected_data.items():
            actual = self.error_data.get(key)
            if actual != value:
                raise AssertionError(
                    f"expected error_data[{key!r}]={value!r}, got {actual!r}"
                )


class MCPCallError(Exception):
    """Raised by Caller.call(...) when the call returns an error."""

    def __init__(self, response: Response, tool: str, kwargs: dict):
        self.response = response
        self.tool = tool
        self.kwargs = kwargs
        super().__init__(
            f"{tool}({kwargs!r}) → {response.error_code}: {response.error_data}"
        )


class MCPHarnessError(Exception):
    """Raised by the harness for setup/usage errors (not tool errors)."""


# ---------------------------------------------------------------------------
# Direct-mode call helpers
# ---------------------------------------------------------------------------


def _normalize_direct(value: Any, exc: BaseException | None) -> "Response":
    if exc is not None:
        from mcp.server.fastmcp.exceptions import ToolError

        if isinstance(exc, ToolError):
            data = getattr(exc, "data", None) or {}
            code = data.get("code") if isinstance(data, dict) else None
            if code is None:
                # Today's only ToolError carries "conflict: …" with data fields.
                code = "conflict" if "conflict" in str(exc) else "internal_error"
            return Response(
                ok=False,
                value=None,
                error_code=code,
                error_data={k: v for k, v in (data or {}).items() if k != "code"},
                raw=exc,
            )
        if isinstance(exc, PermissionError):
            return Response(
                ok=False,
                value=None,
                error_code="forbidden",
                error_data={},
                raw=exc,
            )
        if isinstance(exc, ValueError):
            # Today's tools raise ValueError on bad status enum etc.
            return Response(
                ok=False,
                value=None,
                error_code="invalid_argument",
                error_data={"reason": str(exc)},
                raw=exc,
            )
        return Response(
            ok=False,
            value=None,
            error_code="internal_error",
            error_data={"raw": repr(exc)},
            raw=exc,
        )

    # No exception. Inspect the returned value.
    if isinstance(value, dict) and "error" in value:
        err = value["error"]
        if err == "not_found":
            return Response(False, None, "not_found", {}, value)
        if err == "forbidden":
            return Response(False, None, "forbidden", {}, value)
        if err == "invalid_argument":
            reason = value.get("reason", "")
            return Response(False, None, "invalid_argument", {"reason": reason}, value)
        # Unknown error string — surface as-is.
        return Response(False, None, str(err), {}, value)

    return Response(True, value, None, {}, value)


class _Ctx:
    """Minimal stand-in for FastMCP's Context carrying a Principal."""

    def __init__(self, principal: Any):
        self.principal = principal


def _direct_call(
    harness: "MCPHarness", caller: "Caller", tool: str, kwargs: dict
) -> "Response":
    handlers = harness._mcp.markland_handlers
    if tool not in handlers:
        suggestion = difflib.get_close_matches(tool, list(handlers), n=1)
        hint = f" — did you mean {suggestion[0]!r}?" if suggestion else ""
        raise MCPHarnessError(f"no such tool: {tool!r}{hint}")
    handler = handlers[tool]

    # The handlers expect _Ctx as first arg; anon callers pass principal=None.
    ctx = _Ctx(caller.principal)
    try:
        value = handler(ctx, **kwargs)
    except BaseException as exc:  # noqa: BLE001 — we re-wrap deliberately
        return _normalize_direct(None, exc)
    return _normalize_direct(value, None)


def _http_call(
    harness: "MCPHarness", caller: "Caller", tool: str, kwargs: dict
) -> "Response":
    if not hasattr(harness, "_http_client"):
        raise MCPHarnessError(
            "HTTP-mode harness was not initialized with TestClient"
        )

    # Lazy session init.
    if caller._http_session_id is None and caller.token is not None:
        _http_initialize(harness, caller)

    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if caller.token:
        headers["Authorization"] = f"Bearer {caller.token}"
    if caller._http_session_id:
        headers["Mcp-Session-Id"] = caller._http_session_id

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": kwargs},
    }
    resp = harness._http_client.post("/mcp/", headers=headers, json=body)

    if resp.status_code == 401:
        return Response(False, None, "unauthenticated", {}, resp)
    if resp.status_code == 403:
        return Response(False, None, "forbidden", {}, resp)
    if resp.status_code == 429:
        retry = resp.headers.get("Retry-After")
        return Response(False, None, "rate_limited", {"retry_after": retry}, resp)
    if resp.status_code != 200:
        return Response(
            False,
            None,
            "internal_error",
            {"status": resp.status_code, "body": resp.text},
            resp,
        )

    data = _parse_jsonrpc(resp)
    if "error" in data:
        err = data["error"]
        return Response(
            False,
            None,
            err.get("code", "internal_error"),
            err.get("data") or {},
            resp,
        )

    # tools/call success — extract structured content.
    result = data.get("result", {})
    contents = result.get("content", [])
    if contents and contents[0].get("type") == "text":
        import json
        try:
            value = json.loads(contents[0]["text"])
        except (json.JSONDecodeError, KeyError):
            value = contents[0]["text"]
    else:
        value = result

    # tools/call may also flag isError + structured error.
    if result.get("isError"):
        if isinstance(value, dict) and "code" in value:
            return Response(
                False,
                None,
                value["code"],
                {k: v for k, v in value.items() if k != "code"},
                resp,
            )
        return Response(False, None, "internal_error", {"raw": value}, resp)

    return Response(True, value, None, {}, resp)


def _http_initialize(harness: "MCPHarness", caller: "Caller") -> None:
    """Run the JSON-RPC initialize handshake, capture the session id."""
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {caller.token}",
    }
    body = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "harness", "version": "0"},
        },
    }
    resp = harness._http_client.post("/mcp/", headers=headers, json=body)
    if resp.status_code != 200:
        raise MCPHarnessError(
            f"initialize failed for {caller.principal_id!r}: "
            f"{resp.status_code} {resp.text}"
        )
    session_id = resp.headers.get("Mcp-Session-Id")
    if not session_id:
        raise MCPHarnessError("initialize did not return Mcp-Session-Id header")
    caller._http_session_id = session_id

    # Required `initialized` notification per MCP spec.
    notify = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }
    nh = dict(headers)
    nh["Mcp-Session-Id"] = session_id
    harness._http_client.post("/mcp/", headers=nh, json=notify)


def _parse_jsonrpc(resp) -> dict:
    """FastMCP can return either application/json or text/event-stream.
    Handle both."""
    ct = resp.headers.get("content-type", "")
    if ct.startswith("text/event-stream"):
        for line in resp.text.splitlines():
            if line.startswith("data: "):
                import json
                return json.loads(line[len("data: "):])
        return {}
    import json
    return resp.json()
