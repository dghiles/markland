"""Tests for optimistic concurrency in service.docs."""

import pytest

from markland.db import (
    count_revisions,
    init_db,
    insert_document,
)
from markland.models import Document


@pytest.fixture
def conn(tmp_path):
    db = init_db(tmp_path / "t.db")
    yield db
    db.close()


def test_new_document_starts_at_version_1(conn):
    doc_id = Document.generate_id()
    token = Document.generate_share_token()
    insert_document(conn, doc_id, "t", "c", token)
    row = conn.execute(
        "SELECT version FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    assert row[0] == 1


def test_revisions_table_exists_and_is_empty_initially(conn):
    doc_id = Document.generate_id()
    token = Document.generate_share_token()
    insert_document(conn, doc_id, "t", "c", token)
    assert count_revisions(conn, doc_id) == 0


def test_conflict_error_carries_current_state():
    from markland.service.docs import ConflictError

    exc = ConflictError(
        current_version=7,
        current_title="Live title",
        current_content="Live body",
    )
    assert exc.current_version == 7
    assert exc.current_title == "Live title"
    assert exc.current_content == "Live body"
    assert "7" in str(exc)


def test_conflict_error_is_an_exception():
    from markland.service.docs import ConflictError

    with pytest.raises(ConflictError):
        raise ConflictError(current_version=1, current_title="t", current_content="c")


# --- Task 3: update() with optimistic locking --------------------------

from markland.service.auth import Principal
from markland.service.docs import ConflictError
from markland.service.docs import get as service_get
from markland.service.docs import update as service_update
from markland.tools.documents import publish_doc


def _Principal(pid: str, ptype: str = "agent") -> Principal:
    return Principal(
        principal_id=pid,
        principal_type=ptype,
        display_name=None,
        is_admin=True,
        user_id=pid if ptype == "user" else None,
    )


def _make_doc(conn) -> str:
    """Create a doc with owner=agent_a so agent_a has owner/edit access."""
    # For tests we publish via service with agent_a as owner so edit
    # permission is granted through ownership.
    p = _Principal("agent_a", ptype="user")
    from markland.service import docs as _svc
    result = _svc.publish(conn, "http://x", p, "Body v1", title="Original", public=False)
    return result["id"]


def test_update_with_matching_version_bumps_version_and_writes_revision(conn):
    doc_id = _make_doc(conn)
    principal = _Principal("agent_a", ptype="user")
    updated = service_update(
        conn,
        doc_id,
        principal,
        content="Body v2",
        title=None,
        if_version=1,
    )
    assert updated.version == 2
    assert updated.content == "Body v2"
    assert updated.title == "Original"
    assert count_revisions(conn, doc_id) == 1
    row = conn.execute(
        "SELECT version, title, content, principal_id, principal_type "
        "FROM revisions WHERE doc_id = ? ORDER BY id DESC LIMIT 1",
        (doc_id,),
    ).fetchone()
    # Revision preserves the PRE-update state, so version == 1 (not 2).
    assert row[0] == 1
    assert row[1] == "Original"
    assert row[2] == "Body v1"
    assert row[3] == "agent_a"
    assert row[4] == "user"


def test_update_with_mismatched_version_raises_conflict(conn):
    doc_id = _make_doc(conn)
    principal = _Principal("agent_a", ptype="user")
    service_update(conn, doc_id, principal, content="v2", if_version=1)
    with pytest.raises(ConflictError) as exc_info:
        service_update(conn, doc_id, principal, content="stale", if_version=1)
    err = exc_info.value
    assert err.current_version == 2
    assert err.current_content == "v2"
    assert err.current_title == "Original"
    after = service_get(conn, doc_id, principal)
    assert after.version == 2
    assert after.content == "v2"


def test_update_against_missing_doc_raises(conn):
    principal = _Principal("agent_a", ptype="user")
    # Missing docs raise NotFound from check_permission (per spec §12.5
    # "doesn't exist" == "no view access" at the edge).
    from markland.service.permissions import NotFound
    with pytest.raises((ValueError, NotFound)):
        service_update(conn, "doesnotexist", principal, content="x", if_version=1)


def test_revision_pruning_caps_at_50(conn):
    doc_id = _make_doc(conn)
    principal = _Principal("agent_a", ptype="user")
    for i in range(55):
        service_update(
            conn,
            doc_id,
            principal,
            content=f"body-{i}",
            if_version=i + 1,
        )
    assert count_revisions(conn, doc_id) == 50
    oldest = conn.execute(
        "SELECT MIN(version) FROM revisions WHERE doc_id = ?", (doc_id,)
    ).fetchone()[0]
    assert oldest == 6


def test_get_returns_version(conn):
    doc_id = _make_doc(conn)
    principal = _Principal("agent_a", ptype="user")
    doc = service_get(conn, doc_id, principal)
    assert doc.version == 1
