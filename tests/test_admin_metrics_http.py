"""HTTP endpoint tests for GET /admin/metrics."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.auth import create_user_token
from markland.service.users import create_user
from markland.web.app import create_app


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

    app = create_app(conn, mount_mcp=False, base_url="http://t")
    return {
        "client": TestClient(app),
        "admin_token": admin_token,
        "user_token": user_token,
    }


def test_admin_metrics_unauthenticated_401(ctx):
    r = ctx["client"].get("/admin/metrics")
    assert r.status_code == 401


def test_admin_metrics_non_admin_403(ctx):
    r = ctx["client"].get(
        "/admin/metrics",
        headers={"Authorization": f"Bearer {ctx['user_token']}"},
    )
    assert r.status_code == 403


def test_admin_metrics_admin_returns_summary(ctx):
    r = ctx["client"].get(
        "/admin/metrics?window_seconds=86400",
        headers={"Authorization": f"Bearer {ctx['admin_token']}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["window_seconds"] == 86400
    assert "signups" in body
    assert "publishes" in body
    assert "grants_created" in body
    assert "invites_accepted" in body
    assert "waitlist_total" in body
    assert "users_total" in body
    assert "documents_total" in body
    assert "documents_public_total" in body
    assert "documents_created" in body
    assert "documents_updated" in body
    assert "documents_deleted" in body
    assert "grants_total" in body
    assert "grants_revoked" in body
    assert "invites_total" in body
    assert "invites_created" in body
    assert body["first_mcp_call"] is None


def test_admin_metrics_default_window_is_7d(ctx):
    r = ctx["client"].get(
        "/admin/metrics",
        headers={"Authorization": f"Bearer {ctx['admin_token']}"},
    )
    assert r.status_code == 200
    assert r.json()["window_seconds"] == 604800  # 7 days
