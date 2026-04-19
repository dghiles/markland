"""Tests that init_db creates the presence table with the expected columns."""

from markland.db import init_db


def test_presence_table_exists(tmp_path):
    conn = init_db(tmp_path / "t.db")
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='presence'"
    ).fetchall()
    assert len(rows) == 1


def test_presence_columns(tmp_path):
    conn = init_db(tmp_path / "t.db")
    info = conn.execute("PRAGMA table_info(presence)").fetchall()
    names = {row[1] for row in info}
    assert names == {
        "doc_id",
        "principal_id",
        "principal_type",
        "status",
        "note",
        "updated_at",
        "expires_at",
    }


def test_presence_primary_key(tmp_path):
    conn = init_db(tmp_path / "t.db")
    info = conn.execute("PRAGMA table_info(presence)").fetchall()
    pk = {row[1]: row[5] for row in info}
    # Composite PK: doc_id and principal_id each have pk >= 1.
    assert pk["doc_id"] >= 1
    assert pk["principal_id"] >= 1
    assert pk["doc_id"] != pk["principal_id"]


def test_presence_upsert_roundtrip(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        """
        INSERT INTO documents
          (id, title, content, share_token, created_at, updated_at,
           is_public, is_featured, version)
        VALUES ('doc_1', 'T', 'C', 'tok_1',
                '2026-04-19T00:00:00', '2026-04-19T00:00:00', 0, 0, 1)
        """
    )
    conn.commit()
    conn.execute(
        """
        INSERT INTO presence
          (doc_id, principal_id, principal_type, status, note, updated_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "doc_1",
            "usr_alice",
            "user",
            "editing",
            "drafting intro",
            "2026-04-19T10:00:00",
            "2026-04-19T10:10:00",
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT status, note, expires_at FROM presence "
        "WHERE doc_id=? AND principal_id=?",
        ("doc_1", "usr_alice"),
    ).fetchone()
    assert row[0] == "editing"
    assert row[1] == "drafting intro"
    assert row[2] == "2026-04-19T10:10:00"
