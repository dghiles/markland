"""PrincipalMiddleware should gate /admin/* identically to /mcp."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.auth import create_user_token
from markland.service.users import create_user
from markland.web.app import create_app


@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_USER_PER_MIN", "1000")
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")

    conn = init_db(tmp_path / "t.db")
    admin = create_user(conn, email="admin@m.dev", display_name="Admin")
    conn.execute("UPDATE users SET is_admin=1 WHERE id = ?", (admin.id,))
    conn.commit()
    _, admin_token = create_user_token(conn, user_id=admin.id, label="t")

    # mount_mcp=False — after Task 6 Step 5, PrincipalMiddleware is always
    # installed regardless of MCP, so /admin/* gating is exercised either way.
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test")
    client = TestClient(app)
    client.admin_token = admin_token
    return client


def test_admin_audit_without_bearer_returns_401(admin_client):
    """/admin/audit must 401 when no Bearer token is present.

    Same contract as /mcp: PrincipalMiddleware short-circuits before the
    handler ever runs.
    """
    r = admin_client.get("/admin/audit")
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}


def test_admin_audit_with_bad_bearer_returns_401(admin_client):
    r = admin_client.get(
        "/admin/audit", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert r.status_code == 401


def test_admin_audit_with_valid_admin_bearer_succeeds(admin_client):
    """Once gated by middleware, the handler still serves admins."""
    r = admin_client.get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {admin_client.admin_token}"},
    )
    assert r.status_code == 200
