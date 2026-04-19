"""Tests for SQLite database operations."""

import pytest

from markland.db import (
    delete_document,
    get_document,
    get_document_by_token,
    init_db,
    insert_document,
    list_documents,
    search_documents,
    update_document,
)


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    yield conn
    conn.close()


def test_insert_and_get(db):
    insert_document(db, "test-id", "Test Title", "# Hello", "share123")
    doc = get_document(db, "test-id")
    assert doc is not None
    assert doc.id == "test-id"
    assert doc.title == "Test Title"
    assert doc.content == "# Hello"
    assert doc.share_token == "share123"


def test_get_by_share_token(db):
    insert_document(db, "test-id", "Test Title", "# Hello", "share123")
    doc = get_document_by_token(db, "share123")
    assert doc is not None
    assert doc.id == "test-id"


def test_get_nonexistent_returns_none(db):
    assert get_document(db, "nonexistent") is None
    assert get_document_by_token(db, "nonexistent") is None


def test_list_documents_ordered_by_updated_at_desc(db):
    insert_document(db, "id1", "First", "content1", "token1")
    insert_document(db, "id2", "Second", "content2", "token2")
    docs = list_documents(db)
    assert len(docs) == 2
    assert docs[0].title == "Second"


def test_search_by_title(db):
    insert_document(db, "id1", "Python Guide", "Learn basics", "token1")
    insert_document(db, "id2", "Rust Guide", "Learn basics", "token2")
    results = search_documents(db, "Python")
    assert len(results) == 1
    assert results[0].id == "id1"


def test_search_by_content(db):
    insert_document(db, "id1", "Guide", "Python is great", "token1")
    insert_document(db, "id2", "Guide", "Rust is great", "token2")
    results = search_documents(db, "Python")
    assert len(results) == 1
    assert results[0].id == "id1"


def test_delete_document(db):
    insert_document(db, "id1", "Title", "content", "token1")
    assert delete_document(db, "id1") is True
    assert get_document(db, "id1") is None


def test_delete_nonexistent(db):
    assert delete_document(db, "nonexistent") is False


def test_update_document_content(db):
    insert_document(db, "id1", "Original", "original content", "token1")
    updated = update_document(db, "id1", content="new content")
    assert updated is not None
    assert updated.content == "new content"
    assert updated.title == "Original"  # unchanged


def test_update_document_title(db):
    insert_document(db, "id1", "Original", "content", "token1")
    updated = update_document(db, "id1", title="New Title")
    assert updated is not None
    assert updated.title == "New Title"
    assert updated.content == "content"  # unchanged


def test_update_nonexistent_returns_none(db):
    assert update_document(db, "nonexistent", content="x") is None


def test_share_token_is_unique_indexed(db):
    insert_document(db, "id1", "T1", "c1", "same-token")
    # Inserting another row with the same token should fail
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        insert_document(db, "id2", "T2", "c2", "same-token")


def test_migration_adds_columns(tmp_path):
    """Initialize a DB with the old schema, then re-init — new columns must appear."""
    import sqlite3
    db_path = tmp_path / "legacy.db"

    # Create "old" schema WITHOUT is_public / is_featured
    old_conn = sqlite3.connect(str(db_path))
    old_conn.execute("""
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            share_token TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    from markland.models import Document as DocModel
    now = DocModel.now()
    old_conn.execute(
        "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?)",
        ("legacy-id", "Legacy Doc", "# Old", "legacy-token", now, now),
    )
    old_conn.commit()
    old_conn.close()

    # Run init_db — it should migrate the old schema
    from markland.db import init_db, get_document
    conn = init_db(db_path)

    # New columns should exist and default to 0 for the legacy row
    doc = get_document(conn, "legacy-id")
    assert doc is not None
    assert doc.is_public is False
    assert doc.is_featured is False
    conn.close()


def test_insert_sets_is_public_flag(db):
    from markland.db import insert_document, get_document
    insert_document(db, "pub-id", "Public", "content", "tok-pub", is_public=True)
    doc = get_document(db, "pub-id")
    assert doc.is_public is True
    assert doc.is_featured is False


def test_list_public_filters_unlisted(db):
    from markland.db import insert_document, list_public_documents
    insert_document(db, "pub", "Public", "content", "tok1", is_public=True)
    insert_document(db, "priv", "Private", "content", "tok2", is_public=False)
    public_docs = list_public_documents(db)
    assert len(public_docs) == 1
    assert public_docs[0].id == "pub"


def test_list_public_applies_search(db):
    from markland.db import insert_document, list_public_documents
    insert_document(db, "p1", "Python guide", "c", "t1", is_public=True)
    insert_document(db, "p2", "Rust guide", "c", "t2", is_public=True)
    results = list_public_documents(db, query="Python")
    assert len(results) == 1
    assert results[0].id == "p1"


def test_set_visibility(db):
    from markland.db import insert_document, set_visibility, get_document
    insert_document(db, "d1", "T", "c", "t1", is_public=False)
    updated = set_visibility(db, "d1", is_public=True)
    assert updated is not None
    assert updated.is_public is True
    assert get_document(db, "d1").is_public is True


def test_set_featured(db):
    from markland.db import insert_document, set_featured
    insert_document(db, "d1", "T", "c", "t1", is_public=True)
    updated = set_featured(db, "d1", is_featured=True)
    assert updated is not None
    assert updated.is_featured is True


def test_list_featured_and_recent_public_orders_featured_first(db):
    import time
    from markland.db import insert_document, set_featured, list_featured_and_recent_public
    # Older doc is featured
    insert_document(db, "old-featured", "Old featured", "c", "t1", is_public=True)
    set_featured(db, "old-featured", is_featured=True)
    time.sleep(0.01)
    # Newer doc is not featured
    insert_document(db, "new-unfeatured", "New unfeatured", "c", "t2", is_public=True)

    docs = list_featured_and_recent_public(db, limit=8)
    assert len(docs) == 2
    assert docs[0].id == "old-featured"  # featured ranks first despite older timestamp
    assert docs[1].id == "new-unfeatured"


def test_list_featured_and_recent_excludes_unlisted_featured(db):
    """A non-public doc marked featured should still be excluded from the landing."""
    from markland.db import insert_document, set_featured, list_featured_and_recent_public
    insert_document(db, "private", "Private but featured", "c", "t1", is_public=False)
    set_featured(db, "private", is_featured=True)
    docs = list_featured_and_recent_public(db)
    assert docs == []


def test_init_db_creates_waitlist_table(db):
    rows = db.execute("PRAGMA table_info(waitlist)").fetchall()
    assert rows, "waitlist table should exist after init_db"
    columns = {row[1] for row in rows}
    assert columns == {"email", "created_at", "source"}


def test_add_waitlist_email_inserts_new_row(db):
    from markland.db import add_waitlist_email

    inserted = add_waitlist_email(db, "ada@example.com", source="hero")
    assert inserted is True

    row = db.execute(
        "SELECT email, source, created_at FROM waitlist WHERE email = ?",
        ("ada@example.com",),
    ).fetchone()
    assert row is not None
    assert row[0] == "ada@example.com"
    assert row[1] == "hero"
    assert row[2]


def test_add_waitlist_email_is_idempotent_on_duplicate(db):
    from markland.db import add_waitlist_email

    first = add_waitlist_email(db, "ada@example.com", source="hero")
    second = add_waitlist_email(db, "ada@example.com", source="cta-section")
    assert first is True
    assert second is False

    count = db.execute("SELECT COUNT(*) FROM waitlist").fetchone()[0]
    assert count == 1

    source = db.execute("SELECT source FROM waitlist WHERE email = ?", ("ada@example.com",)).fetchone()[0]
    assert source == "hero"


def test_add_waitlist_email_accepts_null_source(db):
    from markland.db import add_waitlist_email

    inserted = add_waitlist_email(db, "lovelace@example.com")
    assert inserted is True

    source = db.execute(
        "SELECT source FROM waitlist WHERE email = ?", ("lovelace@example.com",)
    ).fetchone()[0]
    assert source is None
