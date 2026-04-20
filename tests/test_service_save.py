"""fork_document + toggle_bookmark service helpers."""

import pytest

from markland.db import (
    init_db,
    insert_document,
    get_document,
    upsert_grant,
)
from markland.models import Document, Grant
from markland.service.save import (
    fork_document,
    toggle_bookmark,
)


def _seed(conn, *, owner_id="user_owner", is_public=True) -> Document:
    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(
        conn, doc_id, "Original Title", "Original content.", share,
        is_public=is_public, owner_id=owner_id,
    )
    doc = get_document(conn, doc_id)
    assert doc is not None
    return doc


def test_fork_creates_new_doc_owned_by_new_user_with_pointer(tmp_path):
    conn = init_db(tmp_path / "m.db")
    source = _seed(conn, owner_id="alice", is_public=True)

    fork = fork_document(conn, source=source, new_owner_id="bob")

    assert fork.id != source.id
    assert fork.share_token != source.share_token
    assert fork.title == source.title
    assert fork.content == source.content
    assert fork.owner_id == "bob"
    assert fork.is_public is False
    assert fork.forked_from_doc_id == source.id

    n = conn.execute(
        "SELECT COUNT(*) FROM revisions WHERE doc_id = ?", (fork.id,)
    ).fetchone()[0]
    assert n == 1


def test_fork_rejects_owner_forking_own_doc(tmp_path):
    conn = init_db(tmp_path / "m.db")
    source = _seed(conn, owner_id="alice", is_public=True)

    with pytest.raises(ValueError):
        fork_document(conn, source=source, new_owner_id="alice")


def test_fork_rejects_private_doc_without_grant(tmp_path):
    conn = init_db(tmp_path / "m.db")
    source = _seed(conn, owner_id="alice", is_public=False)

    with pytest.raises(PermissionError):
        fork_document(conn, source=source, new_owner_id="bob")


def test_fork_allows_private_doc_with_view_grant(tmp_path):
    conn = init_db(tmp_path / "m.db")
    source = _seed(conn, owner_id="alice", is_public=False)
    upsert_grant(
        conn,
        doc_id=source.id,
        principal_id="bob",
        principal_type="user",
        level="view",
        granted_by="alice",
    )

    fork = fork_document(conn, source=source, new_owner_id="bob")
    assert fork.owner_id == "bob"


def test_toggle_bookmark_insert_then_remove(tmp_path):
    conn = init_db(tmp_path / "m.db")
    source = _seed(conn, owner_id="alice", is_public=True)

    toggle_bookmark(conn, user_id="bob", doc_id=source.id, bookmarked=True)
    toggle_bookmark(conn, user_id="bob", doc_id=source.id, bookmarked=True)

    rows = conn.execute("SELECT user_id FROM bookmarks").fetchall()
    assert rows == [("bob",)]

    toggle_bookmark(conn, user_id="bob", doc_id=source.id, bookmarked=False)
    rows = conn.execute("SELECT user_id FROM bookmarks").fetchall()
    assert rows == []
