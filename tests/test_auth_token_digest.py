"""Indexed digest lookup for bearer tokens (markland-tex).

Every token minted now carries token_digest = SHA-256(plaintext). Rows
written before that get it on their first successful resolve:
- legacy tokens
- new-shape tokens minted before the digest release
- tokens an older release mints during a rollback

Argon2 runs only against rows with no digest.
Spec: docs/specs/2026-09-27-token-digest-lookup-design.md.
"""

from __future__ import annotations

import base64
import hashlib
import re
import runpy
import secrets
import sqlite3
from pathlib import Path

import pytest

from markland.config import reset_config
from markland.db import init_db
from markland.service import auth
from markland.service.agents import create_agent, revoke_agent
from markland.service.auth import (
    _parse_token_plaintext,
    create_agent_token,
    create_user_token,
    hash_token,
    resolve_token,
    token_digest,
    verify_token,
)
from markland.service.users import create_user

PRE_CUTOFF = "2026-01-01T00:00:00+00:00"
POST_CUTOFF = "2026-09-01T00:00:00+00:00"


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "t.db")
    yield c
    c.close()


def _insert_as_previous_release(
    conn, *, token_id: str, plaintext: str, principal_type: str,
    principal_id: str, created_at: str,
) -> None:
    """Write a tokens row exactly as the pre-digest release (627601c) does:
    its explicit column list, no token_digest."""
    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, "
        "created_at, last_used_at, revoked_at) "
        "VALUES (?, ?, 'prev', ?, ?, ?, NULL, NULL)",
        (token_id, hash_token(plaintext), principal_type, principal_id, created_at),
    )
    conn.commit()


def _digest_of(conn, token_id: str) -> str | None:
    return conn.execute(
        "SELECT token_digest FROM tokens WHERE id = ?", (token_id,)
    ).fetchone()[0]


# --- the digest itself --------------------------------------------------------


def test_token_digest_is_sha256_hex_of_the_exact_plaintext():
    plaintext = "mk_usr_0123456789abcdef_" + secrets.token_urlsafe(32)
    expected = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    assert token_digest(plaintext) == expected
    assert re.fullmatch(r"[0-9a-f]{64}", token_digest(plaintext))
    assert token_digest(plaintext) != token_digest(plaintext + " ")


def test_minted_secrets_carry_at_least_256_random_bits():
    """token_digest is a fast hash, sound only for high-entropy secrets.
    If a mint ever shortens its secret, this must fail before the digest
    becomes guessable."""
    for mint in (
        auth._mint_user_token_plaintext_with_id,
        auth._mint_agent_token_plaintext_with_id,
    ):
        _, plaintext = mint()
        secret = _parse_token_plaintext(plaintext).secret_part
        raw = base64.urlsafe_b64decode(secret + "=" * (-len(secret) % 4))
        assert len(raw) >= 32


# --- mint: digest plus Argon2 (rollback safety) ---------------------------------


def _hash_and_digest(conn, token_id: str) -> tuple[str, str | None]:
    return conn.execute(
        "SELECT token_hash, token_digest FROM tokens WHERE id = ?", (token_id,)
    ).fetchone()


def test_user_token_mint_writes_digest_and_argon2_hash(conn):
    u = create_user(conn, email="a@x", display_name="A")
    token_id, plaintext = create_user_token(conn, user_id=u.id, label="t")
    token_hash, digest = _hash_and_digest(conn, token_id)
    assert digest == token_digest(plaintext)
    # What the pre-digest release's resolver needs after a rollback: an
    # Argon2 hash, and the row id embedded in the plaintext.
    assert token_hash.startswith("$argon2id$")
    assert verify_token(plaintext, token_hash)
    assert _parse_token_plaintext(plaintext).token_id == token_id


def test_agent_token_mint_writes_digest_and_argon2_hash(conn):
    u = create_user(conn, email="a@x", display_name="A")
    agent = create_agent(conn, u.id, "scribe")
    token_id, plaintext = create_agent_token(
        conn, agent_id=agent.id, owner_user_id=u.id, label="t"
    )
    token_hash, digest = _hash_and_digest(conn, token_id)
    assert digest == token_digest(plaintext)
    assert token_hash.startswith("$argon2id$")
    assert verify_token(plaintext, token_hash)
    assert _parse_token_plaintext(plaintext).token_id == token_id


def test_previous_release_sql_still_runs_on_the_migrated_schema(conn):
    """After a rollback, the pre-digest release runs these statements
    (auth.py @ 627601c, verbatim) against a DB that has token_digest."""
    u = create_user(conn, email="a@x", display_name="A")
    agent = create_agent(conn, u.id, "scribe")
    conn.execute(
        """
        INSERT INTO tokens (
            id, token_hash, label, principal_type, principal_id,
            created_at, last_used_at, revoked_at
        ) VALUES (?, ?, ?, 'user', ?, ?, NULL, NULL)
        """,
        ("tok_olduser", hash_token("mk_usr_x"), "l", u.id, POST_CUTOFF),
    )
    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, "
        "created_at, last_used_at, revoked_at) "
        "VALUES (?, ?, ?, 'agent', ?, ?, NULL, NULL)",
        ("tok_oldagent", hash_token("mk_agt_x"), "l", agent.id, POST_CUTOFF),
    )
    row = conn.execute(
        """
        SELECT id, token_hash, principal_type, principal_id
        FROM tokens
        WHERE id = ? AND revoked_at IS NULL
        """,
        ("tok_olduser",),
    ).fetchone()
    assert row is not None
    conn.execute(
        "UPDATE tokens SET last_used_at = ? WHERE id = ?", (POST_CUTOFF, "tok_olduser")
    )
    conn.commit()
    assert _digest_of(conn, "tok_olduser") is None
    assert _digest_of(conn, "tok_oldagent") is None
