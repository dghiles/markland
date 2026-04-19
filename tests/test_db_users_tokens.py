"""Schema tests for users and tokens tables."""

from markland.db import init_db


def _columns(conn, table: str) -> dict[str, str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1]: r[2] for r in rows}


def _indexes(conn, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA index_list({table})").fetchall()
    return {r[1] for r in rows}


def test_users_table_has_expected_columns(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cols = _columns(conn, "users")
    assert set(cols) == {"id", "email", "display_name", "is_admin", "created_at"}
    assert cols["id"] == "TEXT"
    assert cols["email"] == "TEXT"
    assert cols["is_admin"] == "INTEGER"


def test_users_email_is_unique(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) VALUES (?, ?, ?, 0, ?)",
        ("usr_a", "a@example.com", "A", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    import sqlite3
    try:
        conn.execute(
            "INSERT INTO users (id, email, display_name, is_admin, created_at) VALUES (?, ?, ?, 0, ?)",
            ("usr_b", "a@example.com", "B", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
        raise AssertionError("expected UNIQUE violation on users.email")
    except sqlite3.IntegrityError:
        pass


def test_tokens_table_has_expected_columns(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cols = _columns(conn, "tokens")
    assert set(cols) == {
        "id",
        "token_hash",
        "label",
        "principal_type",
        "principal_id",
        "created_at",
        "last_used_at",
        "revoked_at",
    }


def test_tokens_has_token_hash_index(tmp_path):
    conn = init_db(tmp_path / "t.db")
    assert "idx_token_hash" in _indexes(conn, "tokens")


def test_is_admin_defaults_to_zero(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, created_at) VALUES (?, ?, ?, ?)",
        ("usr_x", "x@example.com", "X", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    row = conn.execute("SELECT is_admin FROM users WHERE id = ?", ("usr_x",)).fetchone()
    assert row[0] == 0
