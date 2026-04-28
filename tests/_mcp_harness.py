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


Mode = Literal["direct", "http"]


@dataclass
class Caller:
    """A test principal with a bound token, calling MCP tools."""

    principal: Principal | None
    token: str | None
    _harness: "MCPHarness" = field(repr=False)

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
        db_path = tmp_path / "harness.db"
        db = init_db(db_path)
        base_url = "https://harness.test"
        mcp = build_mcp(db, base_url=base_url, email_client=None)
        return cls(
            mode=mode,
            db=db,
            base_url=base_url,
            _mcp=mcp,
            _tmp_path=tmp_path,
        )

    def close(self) -> None:
        """Release resources. Safe to call multiple times."""
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
    raise MCPHarnessError("HTTP mode not yet implemented")
