"""P2-G / markland-ezu: defense-in-depth admin gates.

`docs_svc.feature` and `audit_svc.list_recent` previously trusted the
caller to be an admin. Both now self-gate. These tests assert the gate
fires for non-admins and the happy path still works for admins.
"""

from __future__ import annotations

import pytest

from markland.db import init_db, insert_document
from markland.models import Document
from markland.service import audit as audit_svc
from markland.service import docs as docs_svc
from markland.service.auth import Principal
from markland.service.permissions import PermissionDenied


def _user(uid: str, *, is_admin: bool = False) -> Principal:
    return Principal(
        principal_id=uid,
        principal_type="user",
        display_name=None,
        is_admin=is_admin,
        user_id=uid,
    )


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "t.db")
    yield c
    c.close()


def _seed_doc(conn) -> str:
    doc_id = Document.generate_id()
    insert_document(
        conn,
        doc_id,
        "Title",
        "body",
        Document.generate_share_token(),
        is_public=True,
        owner_id="usr_admin",
    )
    return doc_id


def test_feature_denies_non_admin(conn):
    """P2-G: docs_svc.feature must reject a non-admin caller, even if
    the tool-layer gate above was somehow bypassed."""
    doc_id = _seed_doc(conn)
    with pytest.raises(PermissionDenied):
        docs_svc.feature(conn, _user("usr_bob"), doc_id, True)


def test_feature_admin_succeeds(conn):
    """Regression: admin path still works."""
    doc_id = _seed_doc(conn)
    result = docs_svc.feature(conn, _user("usr_admin", is_admin=True), doc_id, True)
    assert result["is_featured"] is True


def test_audit_list_recent_denies_non_admin(conn):
    """P2-G: audit.list_recent must reject when a non-admin principal is
    explicitly passed (defense-in-depth on top of the route check)."""
    with pytest.raises(PermissionDenied):
        audit_svc.list_recent(conn, principal=_user("usr_bob"))


def test_audit_list_recent_admin_succeeds(conn):
    """Regression: admin path still works."""
    rows = audit_svc.list_recent(conn, principal=_user("usr_admin", is_admin=True))
    assert isinstance(rows, list)


def test_audit_list_recent_no_principal_still_works(conn):
    """Back-compat: existing callers that don't yet pass a principal
    keep working. (The /admin/audit route in app.py was updated to pass
    one, but legacy paginated tests in test_audit_service.py do not.)"""
    rows = audit_svc.list_recent(conn)
    assert isinstance(rows, list)
