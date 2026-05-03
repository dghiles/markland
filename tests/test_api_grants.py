"""HTTP endpoints for grant CRUD."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.auth import Principal
from markland.web.app import create_app


BASE = "https://markland.test"


def _seed_users(conn, **email_by_uid: str) -> None:
    for uid, email in email_by_uid.items():
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, '2026-01-01')",
            (uid, email),
        )
    conn.commit()


@pytest.fixture
def client(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_users(conn, usr_alice="a@x", usr_bob="b@x")
    alice = Principal(
        principal_id="usr_alice",
        principal_type="user",
        display_name=None,
        is_admin=False,
        user_id="usr_alice",
    )
    bob = Principal(
        principal_id="usr_bob",
        principal_type="user",
        display_name=None,
        is_admin=False,
        user_id="usr_bob",
    )
    email_client = MagicMock()
    app = create_app(
        conn,
        mount_mcp=False,
        base_url=BASE,
        session_secret="test",
        email_client=email_client,
        test_principal_by_token={"alice": alice, "bob": bob},
    )
    return TestClient(app), conn, email_client


def _publish(client_, token: str, *, title="T", content="body") -> str:
    r = client_.post(
        "/api/docs",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": title, "content": content},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_post_grants_creates_row_and_emails(client):
    c, _, ec = client
    doc_id = _publish(c, "alice")
    r = c.post(
        f"/api/docs/{doc_id}/grants",
        headers={"Authorization": "Bearer alice"},
        json={"principal": "b@x", "level": "view"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["principal_id"] == "usr_bob"
    assert body["level"] == "view"
    ec.send.assert_called_once()


def test_get_grants_requires_edit_or_owner(client):
    c, _, _ = client
    doc_id = _publish(c, "alice")
    r = c.get(
        f"/api/docs/{doc_id}/grants", headers={"Authorization": "Bearer bob"}
    )
    assert r.status_code == 404

    c.post(
        f"/api/docs/{doc_id}/grants",
        headers={"Authorization": "Bearer alice"},
        json={"principal": "b@x", "level": "edit"},
    )
    r = c.get(
        f"/api/docs/{doc_id}/grants", headers={"Authorization": "Bearer bob"}
    )
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_delete_grant_requires_owner(client):
    c, _, _ = client
    doc_id = _publish(c, "alice")
    c.post(
        f"/api/docs/{doc_id}/grants",
        headers={"Authorization": "Bearer alice"},
        json={"principal": "b@x", "level": "view"},
    )
    r = c.delete(
        f"/api/docs/{doc_id}/grants/usr_bob",
        headers={"Authorization": "Bearer bob"},
    )
    assert r.status_code in (403, 404)
    r = c.delete(
        f"/api/docs/{doc_id}/grants/usr_bob",
        headers={"Authorization": "Bearer alice"},
    )
    assert r.status_code == 200
    assert r.json() == {"revoked": True, "doc_id": doc_id, "principal_id": "usr_bob"}


def test_post_grant_unknown_email_returns_400(client):
    c, _, _ = client
    doc_id = _publish(c, "alice")
    r = c.post(
        f"/api/docs/{doc_id}/grants",
        headers={"Authorization": "Bearer alice"},
        json={"principal": "nobody@x", "level": "view"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_argument"


def test_post_grant_on_foreign_doc_returns_404(client):
    c, conn, _ = client
    doc_id = _publish(c, "alice")
    r = c.post(
        f"/api/docs/{doc_id}/grants",
        headers={"Authorization": "Bearer bob"},
        json={"principal": "b@x", "level": "view"},
    )
    assert r.status_code == 404


def test_unauthenticated_returns_401(client):
    c, _, _ = client
    doc_id = _publish(c, "alice")
    r = c.get(f"/api/docs/{doc_id}/grants")
    assert r.status_code == 401


def test_grant_by_principal_id_rejects_unknown_principal_type(client):
    """grant_by_principal_id must reject principal_type outside {'user','agent'}."""
    from markland.service.grants import grant_by_principal_id

    _, conn, _ = client
    with pytest.raises(ValueError):
        grant_by_principal_id(
            conn,
            doc_id="doc_x",
            principal_id="usr_bob",
            principal_type="root",  # not allowed
            level="view",
            granted_by="usr_alice",
        )


def test_grant_by_principal_id_requires_agt_prefix_for_agents(client):
    """Agent grants must use an `agt_` id."""
    from markland.service.grants import grant_by_principal_id

    _, conn, _ = client
    with pytest.raises(ValueError):
        grant_by_principal_id(
            conn,
            doc_id="doc_x",
            principal_id="usr_bob",       # wrong prefix for principal_type=agent
            principal_type="agent",
            level="view",
            granted_by="usr_alice",
        )
