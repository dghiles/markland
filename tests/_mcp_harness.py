"""MCP test harness — dual-backend (direct + http) with snapshot baselines.

See docs/specs/2026-04-27-mcp-audit-design.md §4-§11 for design.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from markland.db import init_db
from markland.server import build_mcp


Mode = Literal["direct", "http"]


@dataclass
class MCPHarness:
    """Test fixture for driving the Markland MCP. Direct or HTTP backend."""

    mode: Mode
    db: sqlite3.Connection
    base_url: str
    _mcp: Any  # FastMCP instance
    _tmp_path: Path

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
