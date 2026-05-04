"""Grant CRUD + best-effort email notifications."""

from unittest.mock import MagicMock

import pytest

from markland.db import init_db, upsert_grant
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service.auth import Principal
from markland.service.permissions import PermissionDenied


BASE = "https://markland.test"


def _user(uid: str) -> Principal:
    return Principal(
        principal_id=uid,
        principal_type="user",
        display_name=None,
        is_admin=False,
        user_id=uid,
    )


def _fresh_db(tmp_path):
    return init_db(tmp_path / "t.db")


def _seed_users(conn, email_by_uid: dict[str, str]) -> None:
    for uid, email in email_by_uid.items():
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, '2026-01-01')",
            (uid, email),
        )
    conn.commit()


def _seed(conn, owner: Principal, *, email_by_uid: dict[str, str] | None = None):
    """Seed users and publish one doc owned by `owner`. Returns doc_id."""
    email_by_uid = email_by_uid or {}
    _seed_users(conn, email_by_uid)
    return docs_svc.publish(conn, BASE, owner, "body", title="T")["id"]


def test_grant_by_email_creates_row(tmp_path):
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed(
        conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"}
    )
    email_client = MagicMock()
    result = grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="b@x",
        level="view",
        email_client=email_client,
    )
    assert result["principal_id"] == "usr_bob"
    assert result["principal_type"] == "user"
    assert result["level"] == "view"
    email_client.send.assert_called_once()
    kwargs = email_client.send.call_args.kwargs
    assert kwargs["to"] == "b@x"
    assert "view" in kwargs["subject"].lower() or "view" in kwargs["html"].lower()


def test_grant_unknown_email_silently_creates_invite(tmp_path):
    """P2-E / markland-yi1: granting to an email with no matching user
    no longer raises GrantTargetNotFound — it silently creates an
    invite and returns a grant-shaped response. This prevents the doc
    owner from enumerating which emails belong to Markland accounts."""
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed(conn, alice, email_by_uid={"usr_alice": "a@x"})
    email_client = MagicMock()
    result = grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="nobody@x",
        level="view",
        email_client=email_client,
    )
    # Same shape as a successful grant.
    assert result["doc_id"] == doc_id
    assert result["principal_id"] == "nobody@x"
    assert result["level"] == "view"
    # Invite was actually created (a row in the invites table).
    rows = conn.execute(
        "SELECT id FROM invites WHERE doc_id = ?", (doc_id,)
    ).fetchall()
    assert len(rows) == 1
    # Email was queued.
    email_client.send.assert_called_once()


def test_grant_rejects_non_email_unknown_target(tmp_path):
    """A target that is not email-shaped (no '@') and not an agt_ id
    should still raise GrantTargetNotFound — those are user typos, not
    enumeration probes."""
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed(conn, alice, email_by_uid={"usr_alice": "a@x"})
    with pytest.raises(grants_svc.GrantTargetNotFound):
        grants_svc.grant(
            conn,
            base_url=BASE,
            principal=alice,
            doc_id=doc_id,
            target="not-an-email",
            level="view",
            email_client=MagicMock(),
        )


def test_grant_rejects_unknown_agent_id_with_not_found(tmp_path):
    """Plan 4 allows `agt_…` targets; unknown ones raise NotFound."""
    from markland.service.permissions import NotFound

    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed(conn, alice, email_by_uid={"usr_alice": "a@x"})
    with pytest.raises(NotFound, match="agent_not_found"):
        grants_svc.grant(
            conn,
            base_url=BASE,
            principal=alice,
            doc_id=doc_id,
            target="agt_abc",
            level="edit",
            email_client=MagicMock(),
        )


def test_grant_requires_owner(tmp_path):
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    doc_id = _seed(
        conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"}
    )
    upsert_grant(conn, doc_id, "usr_bob", "user", "edit", "usr_alice")
    with pytest.raises(PermissionDenied):
        grants_svc.grant(
            conn,
            base_url=BASE,
            principal=bob,
            doc_id=doc_id,
            target="b@x",
            level="edit",
            email_client=MagicMock(),
        )


def test_grant_upserts_on_reapply(tmp_path):
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed(
        conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"}
    )
    mc = MagicMock()
    grants_svc.grant(conn, base_url=BASE, principal=alice, doc_id=doc_id,
                    target="b@x", level="view", email_client=mc)
    out = grants_svc.grant(conn, base_url=BASE, principal=alice, doc_id=doc_id,
                           target="b@x", level="edit", email_client=mc)
    assert out["level"] == "edit"
    rows = grants_svc.list_grants(conn, principal=alice, doc_id=doc_id)
    assert len(rows) == 1
    assert rows[0]["level"] == "edit"


def test_revoke_removes_row(tmp_path):
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed(
        conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"}
    )
    grants_svc.grant(conn, base_url=BASE, principal=alice, doc_id=doc_id,
                    target="b@x", level="view", email_client=MagicMock())
    result = grants_svc.revoke(
        conn, principal=alice, doc_id=doc_id, principal_id="usr_bob"
    )
    assert result["revoked"] is True
    assert grants_svc.list_grants(conn, principal=alice, doc_id=doc_id) == []


def test_revoke_requires_owner(tmp_path):
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    doc_id = _seed(
        conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"}
    )
    grants_svc.grant(conn, base_url=BASE, principal=alice, doc_id=doc_id,
                    target="b@x", level="edit", email_client=MagicMock())
    with pytest.raises(PermissionDenied):
        grants_svc.revoke(
            conn, principal=bob, doc_id=doc_id, principal_id="usr_bob"
        )


def test_list_grants_allows_owner_and_edit(tmp_path):
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    eve = _user("usr_eve")
    doc_id = _seed(
        conn, alice,
        email_by_uid={
            "usr_alice": "a@x", "usr_bob": "b@x", "usr_eve": "e@x",
        },
    )
    grants_svc.grant(conn, base_url=BASE, principal=alice, doc_id=doc_id,
                    target="b@x", level="edit", email_client=MagicMock())
    grants_svc.grant(conn, base_url=BASE, principal=alice, doc_id=doc_id,
                    target="e@x", level="view", email_client=MagicMock())

    assert len(grants_svc.list_grants(conn, principal=alice, doc_id=doc_id)) == 2
    assert len(grants_svc.list_grants(conn, principal=bob, doc_id=doc_id)) == 2
    with pytest.raises(PermissionDenied):
        grants_svc.list_grants(conn, principal=eve, doc_id=doc_id)


def test_email_failure_does_not_fail_grant(tmp_path, caplog):
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed(
        conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"}
    )
    mc = MagicMock()
    mc.send.side_effect = RuntimeError("resend exploded")
    out = grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="b@x",
        level="view",
        email_client=mc,
    )
    assert out["principal_id"] == "usr_bob"
    rows = grants_svc.list_grants(conn, principal=alice, doc_id=doc_id)
    assert len(rows) == 1
    assert any("grant email failed" in r.message.lower() for r in caplog.records)


def test_grant_by_principal_id_writes_row_without_permission_check(tmp_path):
    """Internal helper: no owner check, no email — just the upsert."""
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed(conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"})
    grants_svc.grant_by_principal_id(
        conn,
        doc_id=doc_id,
        principal_id="usr_bob",
        principal_type="user",
        level="view",
        granted_by="system",
    )
    rows = grants_svc.list_grants(conn, principal=alice, doc_id=doc_id)
    assert len(rows) == 1
    assert rows[0]["principal_id"] == "usr_bob"
    assert rows[0]["level"] == "view"
    assert rows[0]["granted_by"] == "system"


def test_grant_by_principal_id_is_idempotent_and_upserts_level(tmp_path):
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed(conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"})
    for level in ("view", "view", "edit"):
        grants_svc.grant_by_principal_id(
            conn,
            doc_id=doc_id,
            principal_id="usr_bob",
            principal_type="user",
            level=level,
            granted_by="usr_alice",
        )
    rows = grants_svc.list_grants(conn, principal=alice, doc_id=doc_id)
    assert len(rows) == 1  # still a single row — idempotent upsert
    assert rows[0]["level"] == "edit"  # last write wins


def test_grant_email_body_contains_required_fields(tmp_path):
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed(
        conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"}
    )
    conn.execute(
        "UPDATE users SET display_name = 'Alice' WHERE id = 'usr_alice'"
    )
    conn.commit()
    mc = MagicMock()
    grants_svc.grant(
        conn, base_url=BASE, principal=alice, doc_id=doc_id,
        target="b@x", level="edit", email_client=mc,
    )
    kwargs = mc.send.call_args.kwargs
    assert kwargs["to"] == "b@x"
    assert "Alice" in kwargs["subject"]
    assert "edit" in kwargs["html"]
    assert f"{BASE}/d/" in kwargs["html"]
