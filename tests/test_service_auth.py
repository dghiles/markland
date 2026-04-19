"""Tests for service/auth.py — token hashing, creation, resolution."""

import pytest

from markland.db import init_db
from markland.service.auth import (
    Principal,
    create_user_token,
    hash_token,
    list_tokens,
    resolve_token,
    revoke_token,
    verify_token,
)
from markland.service.users import create_user


def test_hash_token_produces_argon2id_encoded_string():
    h = hash_token("mk_usr_abc123")
    assert h.startswith("$argon2id$")
    # Non-deterministic (random salt)
    assert hash_token("mk_usr_abc123") != h


def test_verify_token_accepts_match():
    h = hash_token("mk_usr_abc123")
    assert verify_token("mk_usr_abc123", h) is True


def test_verify_token_rejects_mismatch():
    h = hash_token("mk_usr_abc123")
    assert verify_token("mk_usr_wrong", h) is False


def test_verify_token_rejects_garbage_hash():
    assert verify_token("mk_usr_abc", "not-a-hash") is False


def test_create_user_token_returns_plaintext_with_mk_usr_prefix(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="Alice")
    token_id, plaintext = create_user_token(conn, user_id=u.id, label="laptop")
    assert token_id.startswith("tok_")
    assert plaintext.startswith("mk_usr_")
    assert len(plaintext) >= 30


def test_resolve_token_returns_principal_for_valid_token(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="Alice")
    _, plaintext = create_user_token(conn, user_id=u.id, label="laptop")
    principal = resolve_token(conn, plaintext)
    assert principal is not None
    assert principal.principal_id == u.id
    assert principal.principal_type == "user"
    assert principal.display_name == "Alice"
    assert principal.is_admin is False


def test_resolve_token_returns_none_for_unknown(tmp_path):
    conn = init_db(tmp_path / "t.db")
    assert resolve_token(conn, "mk_usr_does_not_exist") is None


def test_resolve_token_returns_none_for_empty(tmp_path):
    conn = init_db(tmp_path / "t.db")
    assert resolve_token(conn, "") is None


def test_resolve_token_updates_last_used_at(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="Alice")
    token_id, plaintext = create_user_token(conn, user_id=u.id, label="laptop")
    assert conn.execute("SELECT last_used_at FROM tokens WHERE id = ?", (token_id,)).fetchone()[0] is None
    resolve_token(conn, plaintext)
    assert conn.execute("SELECT last_used_at FROM tokens WHERE id = ?", (token_id,)).fetchone()[0] is not None


def test_resolve_token_returns_admin_flag(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="op@example.com", display_name="Op")
    conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (u.id,))
    conn.commit()
    _, plaintext = create_user_token(conn, user_id=u.id, label="ops")
    principal = resolve_token(conn, plaintext)
    assert principal is not None and principal.is_admin is True


def test_revoke_token_succeeds_for_owner(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="Alice")
    token_id, plaintext = create_user_token(conn, user_id=u.id, label="laptop")
    assert revoke_token(conn, token_id=token_id, user_id=u.id) is True
    assert resolve_token(conn, plaintext) is None


def test_revoke_token_refuses_non_owner(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = create_user(conn, email="alice@example.com", display_name="Alice")
    b = create_user(conn, email="bob@example.com", display_name="Bob")
    token_id, plaintext = create_user_token(conn, user_id=a.id, label="laptop")
    assert revoke_token(conn, token_id=token_id, user_id=b.id) is False
    # Alice's token still resolves
    assert resolve_token(conn, plaintext) is not None


def test_revoke_already_revoked_is_false(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="Alice")
    token_id, _ = create_user_token(conn, user_id=u.id, label="l")
    assert revoke_token(conn, token_id=token_id, user_id=u.id) is True
    assert revoke_token(conn, token_id=token_id, user_id=u.id) is False


def test_list_tokens_returns_only_user_tokens(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = create_user(conn, email="alice@example.com", display_name="A")
    b = create_user(conn, email="bob@example.com", display_name="B")
    create_user_token(conn, user_id=a.id, label="a1")
    create_user_token(conn, user_id=a.id, label="a2")
    create_user_token(conn, user_id=b.id, label="b1")
    rows = list_tokens(conn, user_id=a.id)
    labels = {r.label for r in rows}
    assert labels == {"a1", "a2"}


def test_list_tokens_excludes_revoked(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="A")
    tid1, _ = create_user_token(conn, user_id=u.id, label="k1")
    create_user_token(conn, user_id=u.id, label="k2")
    revoke_token(conn, token_id=tid1, user_id=u.id)
    assert {r.label for r in list_tokens(conn, user_id=u.id)} == {"k2"}
