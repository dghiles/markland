"""Schema contract for the device_authorizations table."""

import sqlite3

import pytest

from markland.db import init_db


def test_device_authorizations_table_exists(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='device_authorizations'"
    )
    assert cur.fetchone() is not None


def test_device_authorizations_columns(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(device_authorizations)")}
    assert cols == {
        "device_code",
        "user_code",
        "status",
        "user_id",
        "invite_token",
        "created_at",
        "expires_at",
        "polled_last",
        "authorized_at",
        "consumed_at",
        "failed_confirms",
    }


def test_user_code_is_unique(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO device_authorizations "
        "(device_code, user_code, status, created_at, expires_at) "
        "VALUES ('d1','ABCD1234','pending','2026-04-19T00:00:00Z','2026-04-19T00:10:00Z')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO device_authorizations "
            "(device_code, user_code, status, created_at, expires_at) "
            "VALUES ('d2','ABCD1234','pending','2026-04-19T00:00:00Z','2026-04-19T00:10:00Z')"
        )


def test_user_code_index_exists(tmp_path):
    conn = init_db(tmp_path / "t.db")
    idx = {row[1] for row in conn.execute("PRAGMA index_list(device_authorizations)")}
    assert "idx_device_user_code" in idx
