"""Permission-aware doc CRUD."""

import pytest

from markland.db import init_db, upsert_grant
from markland.service import docs as svc
from markland.service.auth import Principal
from markland.service.permissions import NotFound, PermissionDenied


BASE = "https://markland.test"


def _user(uid: str) -> Principal:
    return Principal(
        principal_id=uid,
        principal_type="user",
        display_name=None,
        is_admin=False,
        user_id=uid,
    )


def test_publish_sets_owner_id_from_principal(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    result = svc.publish(conn, BASE, alice, "# Hello\nbody", title=None, public=False)
    assert result["owner_id"] == "usr_alice"
    assert result["title"] == "Hello"


def test_list_returns_owned_and_granted_docs(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    owned = svc.publish(conn, BASE, alice, "alice-doc", title="A")["id"]
    bobs = svc.publish(conn, BASE, bob, "bob-doc", title="B")["id"]
    shared = svc.publish(conn, BASE, bob, "shared-doc", title="S")["id"]
    upsert_grant(conn, shared, "usr_alice", "user", "view", "usr_bob")
    ids = {d["id"] for d in svc.list_for_principal(conn, alice)}
    assert ids == {owned, shared}
    assert bobs not in ids


def test_get_as_owner(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    doc_id = svc.publish(conn, BASE, alice, "body", title="T")["id"]
    result = svc.get(conn, alice, doc_id)
    assert result["id"] == doc_id
    assert result["content"] == "body"


def test_get_as_view_grantee(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    doc_id = svc.publish(conn, BASE, alice, "body", title="T")["id"]
    upsert_grant(conn, doc_id, "usr_bob", "user", "view", "usr_alice")
    result = svc.get(conn, bob, doc_id)
    assert result["id"] == doc_id


def test_get_denies_stranger_as_not_found(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    eve = _user("usr_eve")
    doc_id = svc.publish(conn, BASE, alice, "body")["id"]
    with pytest.raises(NotFound):
        svc.get(conn, eve, doc_id)


def test_update_requires_edit(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    doc_id = svc.publish(conn, BASE, alice, "body", title="T")["id"]
    upsert_grant(conn, doc_id, "usr_bob", "user", "view", "usr_alice")
    with pytest.raises(PermissionDenied):
        svc.update(conn, doc_id, bob, content="new", if_version=1)

    # Upgrade to edit
    upsert_grant(conn, doc_id, "usr_bob", "user", "edit", "usr_alice")
    updated = svc.update(conn, doc_id, bob, content="new", if_version=1)
    assert updated.id == doc_id


def test_delete_requires_owner(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    doc_id = svc.publish(conn, BASE, alice, "body", title="T")["id"]
    upsert_grant(conn, doc_id, "usr_bob", "user", "edit", "usr_alice")
    with pytest.raises(PermissionDenied):
        svc.delete(conn, bob, doc_id)
    result = svc.delete(conn, alice, doc_id)
    assert result["deleted"] is True


def test_set_visibility_requires_owner(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    doc_id = svc.publish(conn, BASE, alice, "body", title="T")["id"]
    upsert_grant(conn, doc_id, "usr_bob", "user", "edit", "usr_alice")
    with pytest.raises(PermissionDenied):
        svc.set_visibility(conn, BASE, bob, doc_id, True)
    out = svc.set_visibility(conn, BASE, alice, doc_id, True)
    assert out["is_public"] is True


def test_search_scoped_to_visible_docs(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    svc.publish(conn, BASE, alice, "secret alpha", title="Alpha")
    bob_doc = svc.publish(conn, BASE, bob, "secret alpha", title="Bravo")["id"]
    hits = svc.search(conn, alice, "alpha")
    ids = {h["id"] for h in hits}
    assert bob_doc not in ids
    assert len(hits) == 1


def test_shared_with_principal_excludes_own_docs(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    owned = svc.publish(conn, BASE, alice, "a", title="A")["id"]
    shared = svc.publish(conn, BASE, bob, "b", title="B")["id"]
    upsert_grant(conn, shared, "usr_alice", "user", "view", "usr_bob")
    ids = {d["id"] for d in svc.list_shared_with(conn, alice)}
    assert ids == {shared}
    assert owned not in ids
