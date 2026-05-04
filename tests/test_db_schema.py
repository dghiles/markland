"""Schema-level smoke tests — confirm tables and indexes exist after init_db."""

from markland.db import init_db


def test_magic_link_consumed_table_exists(tmp_path):
    conn = init_db(tmp_path / "t.db")
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='magic_link_consumed'"
    ).fetchall()
    assert len(rows) == 1, "magic_link_consumed table missing"


def test_magic_link_consumed_columns(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(magic_link_consumed)").fetchall()}
    assert cols == {"jti", "email", "consumed_at"}, f"unexpected columns: {cols}"


def test_magic_link_consumed_jti_is_primary_key(tmp_path):
    conn = init_db(tmp_path / "t.db")
    info = conn.execute("PRAGMA table_info(magic_link_consumed)").fetchall()
    pk_cols = [row[1] for row in info if row[5] > 0]  # row[5] is `pk`
    assert pk_cols == ["jti"], f"expected jti as PK, got {pk_cols}"


def test_magic_link_consumed_at_index_exists(tmp_path):
    conn = init_db(tmp_path / "t.db")
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='magic_link_consumed'"
    ).fetchall()
    names = {row[0] for row in rows}
    assert "idx_magic_link_consumed_at" in names, f"index missing; got {names}"


def test_users_table_has_session_epoch_column(tmp_path):
    """markland-bul: server-side session revocation requires a per-user
    epoch counter that logout bumps."""
    conn = init_db(tmp_path / "t.db")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    assert "session_epoch" in cols, f"session_epoch column missing; got {cols}"


def test_users_session_epoch_defaults_to_zero(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
        ("usr_test1234567890", "a@b.test", "2026-01-01T00:00:00+00:00"),
    )
    row = conn.execute(
        "SELECT session_epoch FROM users WHERE id = ?",
        ("usr_test1234567890",),
    ).fetchone()
    assert row[0] == 0
