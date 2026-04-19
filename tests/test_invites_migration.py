"""Invites table is created with correct columns and token_hash index."""

import sqlite3

from markland.db import ensure_invites_schema, init_db


def test_invites_table_has_expected_columns(tmp_path):
    conn = init_db(tmp_path / "t.db")
    ensure_invites_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(invites)")}
    assert cols == {
        "id",
        "token_hash",
        "doc_id",
        "level",
        "single_use",
        "uses_remaining",
        "created_by",
        "created_at",
        "expires_at",
        "revoked_at",
    }


def test_token_hash_is_unique(tmp_path):
    conn = init_db(tmp_path / "t.db")
    ensure_invites_schema(conn)
    conn.execute(
        "INSERT INTO invites (id, token_hash, doc_id, level, single_use, uses_remaining, "
        "created_by, created_at) VALUES (?, ?, ?, 'view', 1, 1, 'usr_x', '2026-04-19T00:00:00+00:00')",
        ("inv_a", "hash1", "doc_a"),
    )
    try:
        conn.execute(
            "INSERT INTO invites (id, token_hash, doc_id, level, single_use, uses_remaining, "
            "created_by, created_at) VALUES (?, ?, ?, 'view', 1, 1, 'usr_x', '2026-04-19T00:00:00+00:00')",
            ("inv_b", "hash1", "doc_a"),
        )
        raise AssertionError("expected UNIQUE violation on token_hash")
    except sqlite3.IntegrityError:
        pass


def test_token_hash_index_exists(tmp_path):
    conn = init_db(tmp_path / "t.db")
    ensure_invites_schema(conn)
    indexes = {
        row[1]
        for row in conn.execute("PRAGMA index_list(invites)")
    }
    assert "idx_invites_token_hash" in indexes


def test_ensure_is_idempotent(tmp_path):
    conn = init_db(tmp_path / "t.db")
    ensure_invites_schema(conn)
    ensure_invites_schema(conn)
    # Second call must not raise.
    rows = conn.execute("SELECT count(*) FROM invites").fetchone()
    assert rows[0] == 0
