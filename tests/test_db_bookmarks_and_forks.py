"""Migrations + bookmarks CRUD for the save-to-account feature."""

from pathlib import Path

from markland.db import (
    init_db,
    insert_document,
    list_bookmarks_for_user,
    remove_bookmark,
    upsert_bookmark,
)
from markland.models import Document


def _seed_doc(conn, *, owner_id: str = "user_owner", is_public: bool = True) -> Document:
    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(
        conn, doc_id, "T", "C", share, is_public=is_public, owner_id=owner_id,
    )
    return Document(
        id=doc_id, title="T", content="C", share_token=share,
        created_at=Document.now(), updated_at=Document.now(),
        is_public=is_public, is_featured=False, owner_id=owner_id,
        version=1, forked_from_doc_id=None,
    )


def _column_names(conn, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def test_init_db_adds_forked_from_and_bookmarks(tmp_path: Path):
    db = tmp_path / "markland.db"
    conn = init_db(db)

    assert "forked_from_doc_id" in _column_names(conn, "documents")
    assert _table_exists(conn, "bookmarks")

    cols = _column_names(conn, "bookmarks")
    assert cols == ["user_id", "doc_id", "created_at"]


def test_init_db_is_idempotent_on_reinit(tmp_path: Path):
    db = tmp_path / "markland.db"
    conn_a = init_db(db)
    conn_a.close()
    conn_b = init_db(db)  # second run must not raise

    assert "forked_from_doc_id" in _column_names(conn_b, "documents")
    assert _table_exists(conn_b, "bookmarks")


def test_upsert_bookmark_is_idempotent(tmp_path):
    conn = init_db(tmp_path / "m.db")
    doc = _seed_doc(conn)

    upsert_bookmark(conn, user_id="u1", doc_id=doc.id)
    upsert_bookmark(conn, user_id="u1", doc_id=doc.id)

    rows = conn.execute(
        "SELECT user_id, doc_id FROM bookmarks"
    ).fetchall()
    assert rows == [("u1", doc.id)]


def test_remove_bookmark_noop_when_missing(tmp_path):
    conn = init_db(tmp_path / "m.db")
    doc = _seed_doc(conn)
    # Remove without inserting — must not raise, must return False.
    removed = remove_bookmark(conn, user_id="u1", doc_id=doc.id)
    assert removed is False


def test_list_bookmarks_filters_to_visible_public_docs_and_orders_by_created_at_desc(tmp_path):
    conn = init_db(tmp_path / "m.db")
    doc_a = _seed_doc(conn, is_public=True)
    doc_b = _seed_doc(conn, is_public=True)
    doc_priv = _seed_doc(conn, is_public=False)

    # Oldest first in insert order; reverse in return.
    upsert_bookmark(conn, user_id="u1", doc_id=doc_a.id)
    upsert_bookmark(conn, user_id="u1", doc_id=doc_b.id)
    upsert_bookmark(conn, user_id="u1", doc_id=doc_priv.id)

    docs = list_bookmarks_for_user(conn, user_id="u1")
    ids = [d.id for d in docs]
    # Private doc filtered out (u1 has no grant on it).
    assert doc_priv.id not in ids
    # Newest first.
    assert ids == [doc_b.id, doc_a.id]


def test_bookmarks_cascade_on_doc_delete(tmp_path):
    from markland.db import delete_document

    conn = init_db(tmp_path / "m.db")
    doc = _seed_doc(conn)
    upsert_bookmark(conn, user_id="u1", doc_id=doc.id)

    delete_document(conn, doc.id)

    rows = conn.execute("SELECT * FROM bookmarks").fetchall()
    assert rows == []
