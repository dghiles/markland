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


def test_post_grant_unknown_email_returns_200_with_invite(client):
    """P2-E / markland-yi1: granting to an unknown email silently creates
    an invite and returns 200 — same shape as a successful grant — so
    callers cannot enumerate which emails belong to Markland accounts."""
    c, conn, _ = client
    doc_id = _publish(c, "alice")
    r = c.post(
        f"/api/docs/{doc_id}/grants",
        headers={"Authorization": "Bearer alice"},
        json={"principal": "nobody@x", "level": "view"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["doc_id"] == doc_id
    assert body["level"] == "view"
    # Invite was created.
    rows = conn.execute(
        "SELECT id FROM invites WHERE doc_id = ?", (doc_id,)
    ).fetchall()
    assert len(rows) == 1


def test_post_grant_known_and_unknown_email_have_same_shape(client):
    """P2-E: a grant to a known email and a grant to an unknown email
    must return responses with the same field shape (no field that
    leaks the difference) AND with values shaped indistinguishably —
    no `@` in principal_id, both prefixed `usr_`, granted_at within a
    few seconds of each other (not the invite's ~7-day expiry).
    """
    import datetime

    c, _, _ = client
    doc_id = _publish(c, "alice")
    r_unknown = c.post(
        f"/api/docs/{doc_id}/grants",
        headers={"Authorization": "Bearer alice"},
        json={"principal": "nobody@x", "level": "view"},
    )
    r_known = c.post(
        f"/api/docs/{doc_id}/grants",
        headers={"Authorization": "Bearer alice"},
        json={"principal": "b@x", "level": "view"},
    )
    assert r_known.status_code == r_unknown.status_code == 200
    body_known = r_known.json()
    body_unknown = r_unknown.json()
    assert set(body_known.keys()) == set(body_unknown.keys())

    # Value-level indistinguishability: principal_id must not contain
    # `@` (else a caller can detect the unknown-email branch by string
    # match) and must use the `usr_` prefix in both cases.
    assert "@" not in body_unknown["principal_id"], body_unknown
    assert "@" not in body_known["principal_id"], body_known
    assert body_known["principal_id"].startswith("usr_"), body_known
    assert body_unknown["principal_id"].startswith("usr_"), body_unknown
    # P3 / markland-89b: synthetic id must match the production
    # `usr_<16hex>` shape exactly (length 20, lowercase hex). An
    # earlier fixup used `usr_pending_<16hex>` (length 28) which was
    # distinguishable on length alone, and the `pending_` infix itself
    # was a giveaway. Test fixtures use short ids (`usr_bob`) so we
    # can't assert length 20 on the known side; we instead pin the
    # synthetic shape directly with a regex.
    import re
    assert re.fullmatch(r"usr_[0-9a-f]{16}", body_unknown["principal_id"]), (
        body_unknown
    )
    assert "pending_" not in body_unknown["principal_id"], body_unknown
    assert "pending_" not in body_known["principal_id"], body_known

    # granted_at must be a "now" timestamp in BOTH cases, not the
    # invite's 7-day expiry — a caller diffing the two values must not
    # be able to distinguish.
    def _to_epoch(s: str) -> float:
        # Accept ISO-8601 with trailing `Z` or offset.
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()

    delta = abs(_to_epoch(body_known["granted_at"]) - _to_epoch(body_unknown["granted_at"]))
    assert delta < 5, (body_known["granted_at"], body_unknown["granted_at"])


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
