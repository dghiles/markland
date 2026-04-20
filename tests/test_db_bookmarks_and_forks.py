"""Migrations + bookmarks CRUD for the save-to-account feature."""

from pathlib import Path

from markland.db import init_db


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
