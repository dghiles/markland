"""Admin-only audit log: HTML page + MCP tool."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import audit
from markland.service.auth import Principal, create_user_token
from markland.service.users import create_user
from markland.web.app import create_app


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

    _, admin_token = create_user_token(conn, user_id=admin.id, label="a")
    _, user_token = create_user_token(conn, user_id=user.id, label="u")

    admin_p = Principal(
        principal_id=admin.id, principal_type="user", display_name="Admin",
        is_admin=True, user_id=admin.id,
    )
    user_p = Principal(
        principal_id=user.id, principal_type="user", display_name="User",
        is_admin=False, user_id=user.id,
    )

    audit.record(conn, action="publish", principal=admin_p, doc_id="doc_x", metadata={"t": "x"})
    audit.record(conn, action="grant", principal=admin_p, doc_id="doc_x", metadata={"t": "g"})

    app = create_app(conn, mount_mcp=False, base_url="http://t")
    return {
        "client": TestClient(app),
        "admin_token": admin_token,
        "user_token": user_token,
        "conn": conn,
        "admin_p": admin_p,
        "user_p": user_p,
    }


def test_admin_audit_page_200_for_admin(ctx):
    r = ctx["client"].get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {ctx['admin_token']}"},
    )
    assert r.status_code == 200
    assert "publish" in r.text
    assert "grant" in r.text
    assert "doc_x" in r.text


def test_admin_audit_page_403_for_non_admin(ctx):
    r = ctx["client"].get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {ctx['user_token']}"},
    )
    assert r.status_code == 403


def test_admin_audit_page_401_for_anon(ctx):
    r = ctx["client"].get("/admin/audit")
    assert r.status_code == 401


def test_markland_audit_tool_admin_allowed(ctx):
    from markland.server import build_mcp

    handlers = build_mcp(ctx["conn"], base_url="http://t").markland_handlers
    rows = handlers["markland_audit"](_Ctx(ctx["admin_p"]), doc_id=None, limit=100)
    actions = [r["action"] for r in rows]
    assert "publish" in actions
    assert "grant" in actions


def test_markland_audit_tool_non_admin_raises(ctx):
    from mcp.server.fastmcp.exceptions import ToolError

    from markland.server import build_mcp

    handlers = build_mcp(ctx["conn"], base_url="http://t").markland_handlers
    with pytest.raises(ToolError) as exc_info:
        handlers["markland_audit"](_Ctx(ctx["user_p"]), doc_id=None, limit=100)
    assert exc_info.value.data["code"] == "forbidden"


def test_markland_audit_tool_filters_by_doc(ctx):
    from markland.server import build_mcp
    from markland.service import audit as a

    a.record(ctx["conn"], action="update", principal=ctx["admin_p"], doc_id="doc_y")
    handlers = build_mcp(ctx["conn"], base_url="http://t").markland_handlers
    rows = handlers["markland_audit"](_Ctx(ctx["admin_p"]), doc_id="doc_y", limit=100)
    assert all(r["doc_id"] == "doc_y" for r in rows)
    assert len(rows) == 1
