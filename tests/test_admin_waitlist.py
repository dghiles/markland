"""Admin-only waitlist signals endpoint."""

import pytest
from fastapi.testclient import TestClient

from markland.db import add_waitlist_email, init_db
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

    add_waitlist_email(conn, "a@example.com", source="hero")
    add_waitlist_email(conn, "b@example.com", source="hero")
    add_waitlist_email(conn, "c@example.com", source="cta-section")
    add_waitlist_email(conn, "d@example.com", source=None)

    app = create_app(conn, mount_mcp=False, base_url="http://t")
    return {
        "client": TestClient(app),
        "admin_token": admin_token,
        "user_token": user_token,
    }


def test_admin_waitlist_401_for_anon(ctx):
    r = ctx["client"].get("/admin/waitlist")
    assert r.status_code == 401


def test_admin_waitlist_403_for_non_admin(ctx):
    r = ctx["client"].get(
        "/admin/waitlist",
        headers={"Authorization": f"Bearer {ctx['user_token']}"},
    )
    assert r.status_code == 403


def test_admin_waitlist_returns_total_and_breakdowns(ctx):
    r = ctx["client"].get(
        "/admin/waitlist",
        headers={"Authorization": f"Bearer {ctx['admin_token']}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4

    source_counts = {row["source"]: row["count"] for row in body["by_source"]}
    assert source_counts["hero"] == 2
    assert source_counts["cta-section"] == 1
    assert source_counts[None] == 1

    assert sum(row["count"] for row in body["by_day"]) == 4

    emails = [row["email"] for row in body["recent"]]
    assert emails[0] == "d@example.com"
    assert set(emails) == {"a@example.com", "b@example.com", "c@example.com", "d@example.com"}


def test_admin_waitlist_respects_limit(ctx):
    r = ctx["client"].get(
        "/admin/waitlist?limit=2",
        headers={"Authorization": f"Bearer {ctx['admin_token']}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert len(body["recent"]) == 2
