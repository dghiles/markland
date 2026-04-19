"""Schema + permission tests for Plan 3."""

import pytest

from markland.db import init_db, insert_document, upsert_grant
from markland.models import Document
from markland.service.auth import Principal
from markland.service.permissions import (
    NotFound,
    PermissionDenied,
    check_permission,
)


def test_documents_has_owner_id_column(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cols = [row[1] for row in conn.execute("PRAGMA table_info(documents)").fetchall()]
    assert "owner_id" in cols


def test_grants_table_exists_with_expected_columns(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cols = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(grants)").fetchall()}
    assert set(cols) == {
        "doc_id",
        "principal_id",
        "principal_type",
        "level",
        "granted_by",
        "granted_at",
    }


def test_grants_primary_key_is_doc_and_principal(tmp_path):
    conn = init_db(tmp_path / "t.db")
    rows = conn.execute("PRAGMA table_info(grants)").fetchall()
    pk_cols = sorted(row[1] for row in rows if row[5] > 0)
    assert pk_cols == ["doc_id", "principal_id"]


def test_idx_grants_principal_exists(tmp_path):
    conn = init_db(tmp_path / "t.db")
    idx = conn.execute("PRAGMA index_list(grants)").fetchall()
    names = [row[1] for row in idx]
    assert "idx_grants_principal" in names


def _seed_doc(conn, *, owner_id: str | None = None, is_public: bool = False) -> str:
    doc_id = Document.generate_id()
    insert_document(
        conn,
        doc_id,
        "Title",
        "body",
        Document.generate_share_token(),
        is_public=is_public,
        owner_id=owner_id,
    )
    return doc_id


def _user(uid: str) -> Principal:
    return Principal(
        principal_id=uid,
        principal_type="user",
        display_name=None,
        is_admin=False,
        user_id=uid,
    )


def test_owner_can_do_anything(tmp_path):
    conn = init_db(tmp_path / "t.db")
    doc_id = _seed_doc(conn, owner_id="usr_alice")
    p = _user("usr_alice")
    assert check_permission(conn, p, doc_id, "view") == "owner"
    assert check_permission(conn, p, doc_id, "edit") == "owner"
    assert check_permission(conn, p, doc_id, "owner") == "owner"


def test_direct_view_grant_allows_view_denies_edit(tmp_path):
    conn = init_db(tmp_path / "t.db")
    doc_id = _seed_doc(conn, owner_id="usr_alice")
    upsert_grant(conn, doc_id, "usr_bob", "user", "view", "usr_alice")
    p = _user("usr_bob")
    assert check_permission(conn, p, doc_id, "view") == "view"
    with pytest.raises(PermissionDenied):
        check_permission(conn, p, doc_id, "edit")
    with pytest.raises(PermissionDenied):
        check_permission(conn, p, doc_id, "owner")


def test_direct_edit_grant_allows_view_and_edit_denies_manage(tmp_path):
    conn = init_db(tmp_path / "t.db")
    doc_id = _seed_doc(conn, owner_id="usr_alice")
    upsert_grant(conn, doc_id, "usr_bob", "user", "edit", "usr_alice")
    p = _user("usr_bob")
    assert check_permission(conn, p, doc_id, "view") == "edit"
    assert check_permission(conn, p, doc_id, "edit") == "edit"
    with pytest.raises(PermissionDenied):
        check_permission(conn, p, doc_id, "owner")


def test_public_doc_allows_view_denies_edit(tmp_path):
    conn = init_db(tmp_path / "t.db")
    doc_id = _seed_doc(conn, owner_id="usr_alice", is_public=True)
    p = _user("usr_stranger")
    assert check_permission(conn, p, doc_id, "view") == "public"
    with pytest.raises(PermissionDenied):
        check_permission(conn, p, doc_id, "edit")


def test_no_grant_no_public_denies_with_not_found(tmp_path):
    conn = init_db(tmp_path / "t.db")
    doc_id = _seed_doc(conn, owner_id="usr_alice")
    p = _user("usr_stranger")
    with pytest.raises(NotFound):
        check_permission(conn, p, doc_id, "view")


def test_missing_doc_raises_not_found(tmp_path):
    conn = init_db(tmp_path / "t.db")
    p = _user("usr_alice")
    with pytest.raises(NotFound):
        check_permission(conn, p, "no_such_doc", "view")


def test_agent_inheritance_hook_unreachable_today(tmp_path):
    """Plan 4 will wire owner inheritance for user-owned agents. Today the
    agent code path is unreachable because no agent Principal can be
    constructed from Plan 2's resolve_token. Smoke: supplying an agent-like
    Principal without an agents row still denies cleanly."""
    conn = init_db(tmp_path / "t.db")
    doc_id = _seed_doc(conn, owner_id="usr_alice")
    p = Principal(
        principal_id="agt_future",
        principal_type="agent",
        display_name=None,
        is_admin=False,
        user_id=None,
    )
    with pytest.raises(NotFound):
        check_permission(conn, p, doc_id, "view")
