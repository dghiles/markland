"""MCP tool tests for markland_admin_metrics."""

from __future__ import annotations

import pytest

from markland.db import init_db
from markland.service.auth import Principal
from markland.service.users import create_user


class _Ctx:
    def __init__(self, principal: Principal | None):
        self.principal = principal


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_USER_PER_MIN", "1000")
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")

    conn = init_db(tmp_path / "a.db")
    admin = create_user(conn, email="admin@m.dev", display_name="Admin")
    conn.execute("UPDATE users SET is_admin=1 WHERE id = ?", (admin.id,))
    conn.commit()
    user = create_user(conn, email="user@m.dev", display_name="User")

    admin_p = Principal(
        principal_id=admin.id, principal_type="user", display_name="Admin",
        is_admin=True, user_id=admin.id,
    )
    user_p = Principal(
        principal_id=user.id, principal_type="user", display_name="User",
        is_admin=False, user_id=user.id,
    )
    return {"conn": conn, "admin_p": admin_p, "user_p": user_p}


def test_admin_metrics_tool_returns_summary(ctx):
    from markland.server import build_mcp

    handlers = build_mcp(ctx["conn"], base_url="http://t").markland_handlers
    result = handlers["markland_admin_metrics"](_Ctx(ctx["admin_p"]), window_seconds=86400)
    assert isinstance(result, dict)
    assert "signups" in result
    assert "publishes" in result
    assert "grants_created" in result
    assert "invites_accepted" in result
    assert "waitlist_total" in result
    assert result["window_seconds"] == 86400
    assert result["first_mcp_call"] is None


def test_admin_metrics_tool_rejects_non_admin(ctx):
    from mcp.server.fastmcp.exceptions import ToolError

    from markland.server import build_mcp

    handlers = build_mcp(ctx["conn"], base_url="http://t").markland_handlers
    with pytest.raises(ToolError) as exc_info:
        handlers["markland_admin_metrics"](_Ctx(ctx["user_p"]), window_seconds=86400)
    assert exc_info.value.data["code"] == "forbidden"


def test_admin_metrics_tool_default_window(ctx):
    from markland.server import build_mcp

    handlers = build_mcp(ctx["conn"], base_url="http://t").markland_handlers
    result = handlers["markland_admin_metrics"](_Ctx(ctx["admin_p"]))
    assert result["window_seconds"] == 604800
