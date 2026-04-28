"""MCP test harness — dual-backend (direct + http) with snapshot baselines.

See docs/specs/2026-04-27-mcp-audit-design.md §4-§11 for design.
"""

from __future__ import annotations

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
