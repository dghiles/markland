"""Dashboard lists My docs and Shared-with-me."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db, upsert_grant
from markland.service import docs as docs_svc
from markland.service.auth import Principal
from markland.web.app import create_app


BASE = "https://markland.test"


def _seed_users(conn, **email_by_uid: str) -> None:
    for uid, email in email_by_uid.items():
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, display_name, created_at) "
            "VALUES (?, ?, ?, '2026-01-01')",
            (uid, email, email.split("@")[0]),
        )
    conn.commit()


@pytest.fixture
def client(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_users(conn, usr_alice="a@x", usr_bob="b@x")
    alice = Principal(
        principal_id="usr_alice", principal_type="user",
        display_name="a", is_admin=False, user_id="usr_alice",
    )
    bob = Principal(
        principal_id="usr_bob", principal_type="user",
        display_name="b", is_admin=False, user_id="usr_bob",
    )
    app = create_app(
        conn, mount_mcp=False, base_url=BASE, session_secret="t",
        email_client=MagicMock(),
        test_principal_by_token={"alice": alice, "bob": bob},
    )
    return TestClient(app), conn, alice, bob


def test_dashboard_unauthed_redirects_or_401(client):
    c, *_ = client
    r = c.get("/dashboard", follow_redirects=False)
    assert r.status_code in (302, 401)


def test_dashboard_shows_owned_and_shared(client):
    c, conn, alice, bob = client
    docs_svc.publish(conn, BASE, alice, "x", title="OwnedByAlice")
    shared = docs_svc.publish(conn, BASE, bob, "y", title="OwnedByBob")["id"]
    upsert_grant(conn, shared, "usr_alice", "user", "view", "usr_bob")
    docs_svc.publish(conn, BASE, bob, "z", title="NotShared")

    r = c.get("/dashboard", headers={"Authorization": "Bearer alice"})
    assert r.status_code == 200
    body = r.text
    assert "OwnedByAlice" in body
    assert "OwnedByBob" in body
    assert "NotShared" not in body
    assert "Shared with me" in body or "shared-with-me" in body.lower()


def test_dashboard_empty_sections_render(client):
    c, _, alice, _ = client
    r = c.get("/dashboard", headers={"Authorization": "Bearer alice"})
    assert r.status_code == 200
    assert "no documents yet" in r.text.lower() or "nothing here yet" in r.text.lower()
