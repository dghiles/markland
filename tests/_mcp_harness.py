"""MCP test harness — dual-backend (direct + http) with snapshot baselines.

See docs/specs/2026-04-27-mcp-audit-design.md §4-§11 for design.
"""

from __future__ import annotations

import difflib
import json
import re
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
    _snapshot_update: bool = False

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

    def snapshot(self, tool: str, scenario: str, payload: Any) -> None:
        path = _SNAPSHOT_DIR / f"{tool}.json"
        existing = json.loads(path.read_text()) if path.exists() else {}

        if self._snapshot_update:
            existing[scenario] = payload
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")
            return

        if scenario not in existing:
            raise AssertionError(
                f"Missing snapshot for {tool}/{scenario}. "
                f"Run: pytest --snapshot-update"
            )
        if existing[scenario] != payload:
            raise AssertionError(
                "snapshot mismatch:\n" + _format_snapshot_diff(existing[scenario], payload)
            )


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
            code = data.get("code", "internal_error")
            payload = {k: v for k, v in data.items() if k != "code"}
            return Response(False, None, code, payload, exc)

        # No tool should raise raw exceptions any more — anything that does
        # is a regression. Surface as internal_error to keep tests informative.
        return Response(
            False, None, "internal_error",
            {"raw": repr(exc)}, exc,
        )

    # Successful tool calls always return a dict (or list).
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
    text = contents[0]["text"] if contents and contents[0].get("type") == "text" else None

    if result.get("isError"):
        # FastMCP wraps ToolError messages as "Error executing tool <name>: <msg>".
        # tool_error() puts JSON in <msg>, so strip the prefix and parse.
        decoded = _decode_tool_error_text(text)
        if decoded is not None and "code" in decoded:
            return Response(
                False,
                None,
                decoded["code"],
                {k: v for k, v in decoded.items() if k != "code"},
                resp,
            )
        return Response(False, None, "internal_error", {"raw": text or result}, resp)

    if text is not None:
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = text
    else:
        value = result
    return Response(True, value, None, {}, resp)


def _decode_tool_error_text(text):
    """Pull the JSON payload out of a FastMCP-wrapped ToolError message.

    FastMCP serializes a raised ToolError as
        "Error executing tool <tool_name>: <message>"
    where <message> is whatever the ToolError was constructed with. Our
    `tool_error()` factory uses a JSON dump as that message, so we just need
    to strip the prefix and parse.
    """
    if not isinstance(text, str):
        return None
    # First try parsing the whole thing as JSON.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Then try stripping the FastMCP prefix.
    marker = ": "
    idx = text.find(marker)
    if idx == -1:
        return None
    payload = text[idx + len(marker):]
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


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
                return json.loads(line[len("data: "):])
        return {}
    return resp.json()


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

_SNAPSHOT_DIR = Path(__file__).parent / "fixtures" / "mcp_baseline"


def _format_snapshot_diff(expected: Any, actual: Any) -> str:
    e = json.dumps(expected, indent=2, sort_keys=True).splitlines()
    a = json.dumps(actual, indent=2, sort_keys=True).splitlines()
    diff = difflib.unified_diff(e, a, fromfile="expected", tofile="actual", lineterm="")
    return "\n".join(diff)

_VOLATILE_FIELDS = {
    "id": "<ID>",  # generic — overridden below by id-prefix pattern
    "share_token": "<SHARE_TOKEN>",
    "share_url": "<SHARE_URL>",
    "url": "<INVITE_URL>",
    "created_at": "<TIMESTAMP>",
    "updated_at": "<TIMESTAMP>",
    "expires_at": "<TIMESTAMP>",
    "completed_at": "<TIMESTAMP>",
    "consumed_at": "<TIMESTAMP>",
    "granted_at": "<TIMESTAMP>",
    "revoked_at": "<TIMESTAMP>",
    "window_start_iso": "<TIMESTAMP>",
    "window_end_iso": "<TIMESTAMP>",
    "owner_id": "<USR_ID>",
    "principal_id": "<PRINCIPAL_ID>",
    "agent_id": "<AGT_ID>",
    "user_id": "<USR_ID>",
    "doc_id": "<DOC_ID>",
    "invite_id": "<INVITE_ID>",
}


_STABLE_PRINCIPAL_LITERALS = {"anonymous"}  # Don't mask these with _VOLATILE_FIELDS.


def _placeholder_for_id(value: str) -> str:
    """Map id-shaped strings to their typed placeholders."""
    if not isinstance(value, str):
        return value
    # User / agent / invite IDs have explicit prefixes.
    if re.match(r"^usr_[a-f0-9]+$", value):
        return "<USR_ID>"
    if re.match(r"^agt_[a-f0-9]+$", value):
        return "<AGT_ID>"
    if re.match(r"^inv_[a-f0-9]+$", value):
        return "<INVITE_ID>"
    # Invite token (the secret used in URLs).
    if re.match(r"^mk_inv_[A-Za-z0-9_-]+$", value):
        return "<INVITE_TOKEN>"
    # Document IDs are bare 16-char lowercase hex.
    if re.match(r"^[a-f0-9]{16}$", value):
        return "<DOC_ID>"
    return value


def as_envelope(value: Any) -> Any:
    """Recursively strip volatile fields from a snapshot payload."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                out[k] = as_envelope(v)
            elif isinstance(v, str):
                # Prefer typed id placeholder if value matches a known prefix.
                typed = _placeholder_for_id(v)
                if typed != v:
                    out[k] = typed
                elif v in _STABLE_PRINCIPAL_LITERALS:
                    out[k] = v  # Preserve stable literals over field-name masking.
                elif k in _VOLATILE_FIELDS:
                    out[k] = _VOLATILE_FIELDS[k]
                else:
                    out[k] = v
            elif k in _VOLATILE_FIELDS:
                out[k] = _VOLATILE_FIELDS[k]
            else:
                out[k] = v
        return out
    if isinstance(value, list):
        return [as_envelope(v) for v in value]
    if isinstance(value, str):
        return _placeholder_for_id(value)
    return value
