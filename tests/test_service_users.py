"""Tests for the users service layer."""

from markland.db import init_db
from markland.service.users import (
    User,
    create_user,
    get_user,
    get_user_by_email,
    upsert_user_by_email,
)


def test_create_user_roundtrip(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="Alice")
    assert u.id.startswith("usr_")
    assert u.email == "alice@example.com"
    assert u.display_name == "Alice"
    assert u.is_admin is False
    fetched = get_user(conn, u.id)
    assert fetched == u


def test_get_user_by_email_case_insensitive(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="Bob@Example.com", display_name="Bob")
    assert get_user_by_email(conn, "bob@example.com") == u
    assert get_user_by_email(conn, "BOB@EXAMPLE.COM") == u


def test_get_user_returns_none_for_missing(tmp_path):
    conn = init_db(tmp_path / "t.db")
    assert get_user(conn, "usr_missing") is None
    assert get_user_by_email(conn, "none@example.com") is None


def test_upsert_user_by_email_creates_when_absent(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = upsert_user_by_email(conn, "new@example.com")
    assert u.email == "new@example.com"
    assert get_user_by_email(conn, "new@example.com") == u


def test_upsert_user_by_email_returns_existing(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = create_user(conn, email="carol@example.com", display_name="Carol")
    b = upsert_user_by_email(conn, "CAROL@example.com")
    assert b.id == a.id
