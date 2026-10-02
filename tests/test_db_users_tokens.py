"""Schema tests for users and tokens tables."""

import sqlite3

import pytest

from markland import db
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
    assert set(cols) == {
        "id", "email", "display_name", "is_admin", "created_at",
        "session_epoch",
    }
    assert cols["id"] == "TEXT"
    assert cols["email"] == "TEXT"
    assert cols["is_admin"] == "INTEGER"
    assert cols["session_epoch"] == "INTEGER"


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
        "token_digest",
        "label",
        "principal_type",
        "principal_id",
        "created_at",
        "last_used_at",
        "revoked_at",
    }
    assert cols["token_digest"] == "TEXT"


def test_tokens_has_token_hash_index(tmp_path):
    conn = init_db(tmp_path / "t.db")
    assert "idx_token_hash" in _indexes(conn, "tokens")


def test_tokens_has_unique_digest_index(tmp_path):
    conn = init_db(tmp_path / "t.db")
    unique = {r[1]: r[2] for r in conn.execute("PRAGMA index_list(tokens)")}
    assert unique.get("idx_tokens_digest") == 1
    cols = [r[2] for r in conn.execute("PRAGMA index_info(idx_tokens_digest)")]
    assert cols == ["token_digest"]


def _insert_token_row(conn, token_id: str, digest: str | None) -> None:
    conn.execute(
        "INSERT INTO tokens(id, token_hash, token_digest, label, principal_type, "
        "principal_id, created_at, last_used_at, revoked_at) "
        "VALUES (?, 'h', ?, NULL, 'user', 'usr_x', '2026-09-27T00:00:00+00:00', NULL, NULL)",
        (token_id, digest),
    )


def test_token_digest_allows_many_nulls_but_no_duplicates(tmp_path):
    conn = init_db(tmp_path / "t.db")
    for i in range(3):
        _insert_token_row(conn, f"tok_null{i}", None)
    _insert_token_row(conn, "tok_a", "d" * 64)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_token_row(conn, "tok_b", "d" * 64)


_PRE_DIGEST_TOKENS_DDL = """
    CREATE TABLE tokens (
        id TEXT PRIMARY KEY,
        token_hash TEXT NOT NULL,
        label TEXT,
        principal_type TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_used_at TEXT,
        revoked_at TEXT
    )
"""


def test_init_db_upgrades_a_pre_digest_tokens_table_in_place(tmp_path):
    """Prod's tokens table predates token_digest: init_db must add the
    column and index in place, leave existing rows NULL, and stay
    idempotent across boots."""
    db_path = tmp_path / "old.db"
    old = sqlite3.connect(str(db_path))
    old.execute(_PRE_DIGEST_TOKENS_DDL)
    old.execute(
        "INSERT INTO tokens VALUES ('tok_old', 'h', 'l', 'user', 'usr_x', "
        "'2026-01-01T00:00:00+00:00', NULL, NULL)"
    )
    old.commit()
    old.close()

    init_db(db_path).close()
    conn = init_db(db_path)  # second boot: no-op, must not raise

    assert "token_digest" in _columns(conn, "tokens")
    assert "idx_tokens_digest" in _indexes(conn, "tokens")
    row = conn.execute(
        "SELECT token_hash, token_digest FROM tokens WHERE id = 'tok_old'"
    ).fetchone()
    assert row == ("h", None)


def test_add_column_if_missing_tolerates_losing_a_concurrent_add(tmp_path, monkeypatch):
    """Admin scripts run init_db over `flyctl ssh console`. If one adds a
    column between our PRAGMA check and our ALTER, the boot must not crash."""
    conn = init_db(tmp_path / "t.db")
    monkeypatch.setattr(db, "_column_exists", lambda *args: False)  # lost the race
    db._add_column_if_missing(
        conn, "users", "session_epoch", "INTEGER NOT NULL DEFAULT 0"
    )
    assert "session_epoch" in _columns(conn, "users")


def test_add_column_if_missing_still_raises_other_errors(tmp_path):
    conn = init_db(tmp_path / "t.db")
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        db._add_column_if_missing(conn, "no_such_table", "x", "TEXT")


def test_is_admin_defaults_to_zero(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, created_at) VALUES (?, ?, ?, ?)",
        ("usr_x", "x@example.com", "X", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    row = conn.execute("SELECT is_admin FROM users WHERE id = ?", ("usr_x",)).fetchone()
    assert row[0] == 0
