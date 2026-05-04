"""Tests for service/auth.py — token hashing, creation, resolution."""

import secrets
import sqlite3
from unittest.mock import patch

import pytest

from markland.db import init_db
from markland.service.auth import (
    Principal,
    _format_user_token_plaintext,
    _mint_user_token_plaintext_with_id,
    _parse_token_plaintext,
    create_agent_token,
    create_user_token,
    hash_token,
    list_tokens,
    resolve_token,
    revoke_token,
    verify_token,
)
from markland.service.agents import create_agent
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


# --- Task 1 — token-id prefix format ----------------------------------------


def test_new_user_token_plaintext_embeds_token_id():
    token_id = "tok_a7c3f9d2b8e6014f"
    plaintext = _format_user_token_plaintext(token_id, "secret_part")
    assert plaintext.startswith("mk_usr_a7c3f9d2b8e6014f_")
    assert plaintext.endswith("secret_part")


def test_parse_token_plaintext_extracts_token_id():
    plaintext = "mk_usr_a7c3f9d2b8e6014f_xyz123"
    parsed = _parse_token_plaintext(plaintext)
    assert parsed is not None
    assert parsed.principal_type == "user"
    assert parsed.token_id == "tok_a7c3f9d2b8e6014f"
    assert parsed.secret_part == "xyz123"


def test_parse_agent_token_plaintext_extracts_token_id():
    plaintext = "mk_agt_a7c3f9d2b8e6014f_xyz123"
    parsed = _parse_token_plaintext(plaintext)
    assert parsed is not None
    assert parsed.principal_type == "agent"
    assert parsed.token_id == "tok_a7c3f9d2b8e6014f"


def test_parse_legacy_token_returns_none():
    # Legacy plaintext: no embedded token_id (urlsafe secret can include `-` `_`)
    plaintext = "mk_usr_aGVsbG93b3JsZA"
    parsed = _parse_token_plaintext(plaintext)
    assert parsed is None


def test_parse_empty_or_garbage_returns_none():
    assert _parse_token_plaintext("") is None
    assert _parse_token_plaintext("not-a-token") is None
    assert _parse_token_plaintext("mk_xyz_a7c3f9d2b8e6014f_secret") is None


def test_parse_legacy_token_that_happens_to_match_regex_falls_through():
    """A legacy plaintext whose secret happens to start with 16 lowercase
    hex chars and an underscore would match the new-format regex. The
    parser correctly returns ParsedToken; resolve_token's fast path
    will then PK-miss and MUST fall through to legacy. See Task 2.
    """
    plaintext = "mk_usr_a7c3f9d2b8e6014f_legacysecretpart"
    parsed = _parse_token_plaintext(plaintext)
    # Parser does match — that's correct behavior.
    assert parsed is not None
    assert parsed.token_id == "tok_a7c3f9d2b8e6014f"


def test_mint_user_token_plaintext_with_id_returns_consistent_pair():
    token_id, plaintext = _mint_user_token_plaintext_with_id()
    assert token_id.startswith("tok_")
    parsed = _parse_token_plaintext(plaintext)
    assert parsed is not None
    assert parsed.token_id == token_id
    assert parsed.principal_type == "user"


def test_create_user_token_plaintext_parses_to_returned_token_id(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="Alice")
    token_id, plaintext = create_user_token(conn, user_id=u.id, label="laptop")
    parsed = _parse_token_plaintext(plaintext)
    assert parsed is not None
    assert parsed.token_id == token_id
    assert parsed.principal_type == "user"


# --- Task 2 — fast path + legacy fallback in resolve_token ------------------


def test_resolve_token_uses_id_prefix_for_new_shape(tmp_path):
    """New-shape tokens hit the table by PK and resolve to the right user."""
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="Alice")
    _, plaintext = create_user_token(conn, user_id=u.id, label="x")
    p = resolve_token(conn, plaintext)
    assert p is not None
    assert p.principal_id == u.id
    assert p.principal_type == "user"


def test_resolve_token_returns_none_when_id_prefix_does_not_exist(tmp_path):
    conn = init_db(tmp_path / "t.db")
    # Forge a parser-matching plaintext whose token_id is not in the DB.
    forged = "mk_usr_deadbeefdeadbeef_xxxxxxxxxxxxxxxx"
    assert resolve_token(conn, forged) is None


def test_resolve_token_legacy_format_still_works(tmp_path):
    """Tokens minted before this PR (no embedded token_id) still work."""
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users(id, email, display_name, is_admin, created_at) "
        "VALUES (?, ?, ?, 0, ?)",
        ("usr_bob", "bob@x", "Bob", "2026-01-01T00:00:00+00:00"),
    )
    legacy_plaintext = "mk_usr_" + secrets.token_urlsafe(32)
    legacy_id = "tok_legacy00000000"
    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, "
        "created_at, last_used_at, revoked_at) "
        "VALUES (?, ?, 'legacy', 'user', 'usr_bob', '2026-01-01T00:00:00+00:00', NULL, NULL)",
        (legacy_id, hash_token(legacy_plaintext)),
    )
    conn.commit()
    p = resolve_token(conn, legacy_plaintext)
    assert p is not None
    assert p.principal_id == "usr_bob"


def test_resolve_token_argon2_verify_call_count_for_new_shape(tmp_path):
    """Confirms O(1) on the happy path: exactly ONE argon2 verify call when
    a real new-shape token is presented, regardless of #tokens in the DB.

    NOTE: a parser-matching plaintext that PK-misses falls through to legacy
    and does 1 + N verifies — covered separately by
    test_resolve_token_falls_through_to_legacy_on_pk_miss. This test is
    the happy path, where the fast path resolves and no fall-through occurs.
    """
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="carol@x", display_name="Carol")
    plaintexts = []
    for i in range(50):
        _tok_id, plaintext = create_user_token(conn, user_id=u.id, label=f"t{i}")
        plaintexts.append(plaintext)
    from markland.service.auth import verify_token as real_verify
    with patch(
        "markland.service.auth.verify_token", wraps=real_verify
    ) as spy:
        # Resolving an existing new-shape token: one PK hit, one verify.
        p = resolve_token(conn, plaintexts[42])
        assert p is not None
        assert spy.call_count == 1


# CRITICAL — false-positive fall-through


def test_resolve_token_falls_through_to_legacy_on_pk_miss(tmp_path):
    """A legacy plaintext whose secret happens to start with 16-hex-then-_
    will parse as new-format. The PK lookup misses (no row at that id).
    Resolver MUST fall through to the legacy O(N) scan, not return None.

    Without this fall-through, ~2.3e-12 fraction of legacy tokens silently
    stop working; an attacker with a leaked legacy plaintext could also
    forge a parser-matching shape to grief auth.
    """
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users(id, email, display_name, is_admin, created_at) "
        "VALUES (?, ?, ?, 0, ?)",
        ("usr_dan", "dan@x", "Dan", "2026-01-01T00:00:00+00:00"),
    )
    # A legacy plaintext that happens to parse as new-format but whose
    # parsed token_id is not the actual row's PK.
    legacy_plaintext = "mk_usr_a7c3f9d2b8e6014f_legacysecretpart"
    legacy_id = "tok_realdiffer123"
    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, "
        "created_at, last_used_at, revoked_at) "
        "VALUES (?, ?, 'legacy', 'user', 'usr_dan', '2026-01-01T00:00:00+00:00', NULL, NULL)",
        (legacy_id, hash_token(legacy_plaintext)),
    )
    conn.commit()
    p = resolve_token(conn, legacy_plaintext)
    assert p is not None
    assert p.principal_id == "usr_dan"


def test_resolve_token_type_mismatch_returns_none(tmp_path):
    """Forge mk_usr_<id>_<secret> for a token_id whose row is type=agent.

    The type cross-check rejects without running argon2; in any case
    the secret doesn't match so the row would not authenticate. Result
    must be None (no fall-through to legacy here either, since there
    are no legacy tokens to find).
    """
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="eve@x", display_name="Eve")
    agent = create_agent(conn, u.id, "scribe")
    _, agent_plaintext = create_agent_token(
        conn, agent_id=agent.id, owner_user_id=u.id, label="t"
    )
    parsed = _parse_token_plaintext(agent_plaintext)
    assert parsed is not None
    forged = f"mk_usr_{parsed.token_id.removeprefix('tok_')}_garbage"
    assert resolve_token(conn, forged) is None


def test_resolve_token_revoked_row_returns_none_in_fast_path(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="frank@x", display_name="Frank")
    _, plaintext = create_user_token(conn, user_id=u.id, label="t")
    parsed = _parse_token_plaintext(plaintext)
    assert parsed is not None
    conn.execute(
        "UPDATE tokens SET revoked_at = ? WHERE id = ?",
        ("2026-01-01T00:00:00+00:00", parsed.token_id),
    )
    conn.commit()
    assert resolve_token(conn, plaintext) is None


def test_resolve_token_agent_fast_path_happy(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="grace@x", display_name="Grace")
    agent = create_agent(conn, u.id, "scribe")
    _, plaintext = create_agent_token(
        conn, agent_id=agent.id, owner_user_id=u.id, label="t"
    )
    p = resolve_token(conn, plaintext)
    assert p is not None
    assert p.principal_type == "agent"
    assert p.principal_id == agent.id
    assert p.user_id == u.id


def test_resolve_token_fast_path_updates_last_used_at(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="hank@x", display_name="Hank")
    _, plaintext = create_user_token(conn, user_id=u.id, label="t")
    parsed = _parse_token_plaintext(plaintext)
    assert parsed is not None
    before = conn.execute(
        "SELECT last_used_at FROM tokens WHERE id = ?", (parsed.token_id,)
    ).fetchone()[0]
    assert before is None
    resolve_token(conn, plaintext)
    after = conn.execute(
        "SELECT last_used_at FROM tokens WHERE id = ?", (parsed.token_id,)
    ).fetchone()[0]
    assert after is not None
