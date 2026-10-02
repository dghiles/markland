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


# --- (a) digest path ------------------------------------------------------------


def test_minted_tokens_resolve_by_digest_with_no_argon2(conn, argon2_verifies):
    u = create_user(conn, email="a@x", display_name="A")
    _, user_plaintext = create_user_token(conn, user_id=u.id, label="t")
    agent = create_agent(conn, u.id, "scribe")
    _, agent_plaintext = create_agent_token(
        conn, agent_id=agent.id, owner_user_id=u.id, label="t"
    )

    p = resolve_token(conn, user_plaintext)
    assert p is not None and p.principal_id == u.id
    a = resolve_token(conn, agent_plaintext)
    assert a is not None and a.principal_type == "agent" and a.user_id == u.id
    assert argon2_verifies.call_count == 0


def test_digest_lookup_is_served_by_the_unique_index(conn):
    plan = conn.execute(
        "EXPLAIN QUERY PLAN " + auth._DIGEST_LOOKUP_SQL, ("0" * 64,)
    ).fetchall()
    details = [row[3] for row in plan]
    assert any("SEARCH" in d and "idx_tokens_digest" in d for d in details), details


def test_digest_resolve_never_scans_the_tokens_table(conn):
    """The constant being indexed is not enough: the statements a digest-hit
    resolve actually runs must not scan tokens (the trace callback passes
    expanded SQL, so each can be EXPLAINed as-is)."""
    u = create_user(conn, email="a@x", display_name="A")
    _, plaintext = create_user_token(conn, user_id=u.id, label="t")
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        assert resolve_token(conn, plaintext) is not None
    finally:
        conn.set_trace_callback(None)
    selects = [
        s for s in statements
        if s.lstrip().upper().startswith("SELECT") and "tokens" in s
    ]
    assert selects
    for s in selects:
        details = [r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + s)]
        assert not any(d.startswith("SCAN") for d in details), (s, details)


def test_revoked_minted_token_costs_no_argon2(conn, argon2_verifies):
    u = create_user(conn, email="a@x", display_name="A")
    create_user_token(conn, user_id=u.id, label="other")  # live, has a digest
    token_id, plaintext = create_user_token(conn, user_id=u.id, label="t")
    assert auth.revoke_token(conn, token_id=token_id, user_id=u.id)
    assert resolve_token(conn, plaintext) is None
    assert argon2_verifies.call_count == 0


# --- (b)/(c) fallbacks backfill the digest ---------------------------------------


def test_rollback_window_token_resolves_and_backfills(conn, argon2_verifies):
    """A new-shape token minted by the pre-digest release during a rollback
    (post-cutoff, no digest) must keep working after the roll-forward."""
    u = create_user(conn, email="a@x", display_name="A")
    token_id, plaintext = auth._mint_user_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=plaintext,
        principal_type="user", principal_id=u.id, created_at=POST_CUTOFF,
    )

    assert resolve_token(conn, plaintext).principal_id == u.id
    assert argon2_verifies.call_count == 1  # (b): one verify
    assert _digest_of(conn, token_id) == token_digest(plaintext)

    auth.invalidate_token_cache()
    assert resolve_token(conn, plaintext).principal_id == u.id
    assert argon2_verifies.call_count == 1  # now a digest hit


def test_rollback_window_agent_token_resolves_and_backfills(conn, argon2_verifies):
    u = create_user(conn, email="a@x", display_name="A")
    agent = create_agent(conn, u.id, "scribe")
    token_id, plaintext = auth._mint_agent_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=plaintext,
        principal_type="agent", principal_id=agent.id, created_at=POST_CUTOFF,
    )

    p = resolve_token(conn, plaintext)
    assert p is not None and p.principal_id == agent.id
    assert _digest_of(conn, token_id) == token_digest(plaintext)

    auth.invalidate_token_cache()
    assert resolve_token(conn, plaintext) == p
    assert argon2_verifies.call_count == 1


def test_legacy_token_resolves_and_backfills(conn, argon2_verifies):
    u = create_user(conn, email="a@x", display_name="A")
    for i in range(3):
        create_user_token(conn, user_id=u.id, label=f"t{i}")
    legacy = "mk_usr_" + secrets.token_urlsafe(32)
    _insert_as_previous_release(
        conn, token_id="tok_legacy", plaintext=legacy,
        principal_type="user", principal_id=u.id, created_at=PRE_CUTOFF,
    )

    assert resolve_token(conn, legacy).principal_id == u.id
    assert argon2_verifies.call_count == 1  # only the digest-less row is verified
    assert _digest_of(conn, "tok_legacy") == token_digest(legacy)

    auth.invalidate_token_cache()
    assert resolve_token(conn, legacy).principal_id == u.id
    assert argon2_verifies.call_count == 1


def test_known_token_id_with_wrong_secret_cannot_plant_a_digest(conn):
    """Knowing a victim's token_id must not let a caller bind their own
    digest to the victim's row: only a successful Argon2 verify of that
    row may write it."""
    u = create_user(conn, email="victim@x", display_name="V")
    token_id, victim = auth._mint_user_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=victim,
        principal_type="user", principal_id=u.id, created_at=POST_CUTOFF,
    )
    short_id = token_id.removeprefix("tok_")
    attacker = f"mk_usr_{short_id}_{secrets.token_urlsafe(32)}"

    assert resolve_token(conn, attacker) is None
    assert _digest_of(conn, token_id) is None

    assert resolve_token(conn, victim).principal_id == u.id
    assert _digest_of(conn, token_id) == token_digest(victim)
    auth.invalidate_token_cache()
    assert resolve_token(conn, attacker) is None


def test_revoked_digestless_rows_are_never_verified_or_backfilled(
    conn, argon2_verifies
):
    u = create_user(conn, email="a@x", display_name="A")
    legacy = "mk_usr_" + secrets.token_urlsafe(32)
    _insert_as_previous_release(
        conn, token_id="tok_legacy", plaintext=legacy,
        principal_type="user", principal_id=u.id, created_at=PRE_CUTOFF,
    )
    token_id, new_shape = auth._mint_user_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=new_shape,
        principal_type="user", principal_id=u.id, created_at=POST_CUTOFF,
    )
    conn.execute("UPDATE tokens SET revoked_at = ?", (POST_CUTOFF,))
    conn.commit()

    assert resolve_token(conn, legacy) is None
    assert resolve_token(conn, new_shape) is None
    assert argon2_verifies.call_count == 0
    assert _digest_of(conn, "tok_legacy") is None
    assert _digest_of(conn, token_id) is None


def test_revoked_agents_digestless_tokens_cost_no_argon2(conn, argon2_verifies):
    """revoke_agent leaves the agent's token rows unrevoked, and a row with no
    digest can never be backfilled once its agent is revoked (the touch never
    runs). A forgotten client retrying such a token must not pay Argon2 on
    every request, and an unknown bearer must not pay for these rows either."""
    u = create_user(conn, email="a@x", display_name="A")
    agent = create_agent(conn, u.id, "scribe")
    token_id, plaintext = auth._mint_agent_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=plaintext,
        principal_type="agent", principal_id=agent.id, created_at=POST_CUTOFF,
    )
    legacy = "mk_agt_" + secrets.token_urlsafe(32)
    _insert_as_previous_release(
        conn, token_id="tok_legacy_agent", plaintext=legacy,
        principal_type="agent", principal_id=agent.id, created_at=PRE_CUTOFF,
    )
    revoke_agent(conn, agent.id, owner_user_id=u.id)

    for _ in range(2):
        assert resolve_token(conn, plaintext) is None
        assert resolve_token(conn, legacy) is None
        assert resolve_token(conn, "mk_usr_" + secrets.token_urlsafe(32)) is None
    assert argon2_verifies.call_count == 0


class _FailBackfillOnce(sqlite3.Connection):
    """Makes the next touch/backfill statement fail, as a locked DB or the
    shared-connection race (markland-5nk) can."""

    armed = False

    def execute(self, sql, *args):
        if _FailBackfillOnce.armed and "COALESCE(token_digest" in sql:
            _FailBackfillOnce.armed = False
            raise sqlite3.OperationalError("database is locked")
        return super().execute(sql, *args)


def test_failed_backfill_write_does_not_block_auth_and_is_retried(
    tmp_path, monkeypatch, argon2_verifies
):
    real_connect = sqlite3.connect
    monkeypatch.setattr(
        sqlite3, "connect",
        lambda *a, **kw: real_connect(*a, **{**kw, "factory": _FailBackfillOnce}),
    )
    _FailBackfillOnce.armed = False
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="a@x", display_name="A")
    token_id, plaintext = auth._mint_user_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=plaintext,
        principal_type="user", principal_id=u.id, created_at=POST_CUTOFF,
    )

    _FailBackfillOnce.armed = True
    assert resolve_token(conn, plaintext).principal_id == u.id  # auth still succeeds
    assert _FailBackfillOnce.armed is False  # the backfill write was attempted
    assert _digest_of(conn, token_id) is None

    auth.invalidate_token_cache()  # stands in for the 60 s TTL expiring
    assert resolve_token(conn, plaintext).principal_id == u.id
    assert _digest_of(conn, token_id) == token_digest(plaintext)
    assert argon2_verifies.call_count == 2  # one verify per uncached resolve until backfilled
    conn.close()


def test_backfill_is_folded_into_the_one_touch_write(conn):
    """The backfill must not add a second write or commit on the shared
    connection (markland-5nk): it rides the existing last_used_at UPDATE."""
    u = create_user(conn, email="a@x", display_name="A")
    token_id, plaintext = auth._mint_user_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=plaintext,
        principal_type="user", principal_id=u.id, created_at=POST_CUTOFF,
    )
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        assert resolve_token(conn, plaintext) is not None
    finally:
        conn.set_trace_callback(None)
    updates = [s for s in statements if s.lstrip().upper().startswith("UPDATE")]
    assert len(updates) == 1, updates
    assert "last_used_at" in updates[0] and "token_digest" in updates[0]
    assert _digest_of(conn, token_id) == token_digest(plaintext)


# --- (c) is bounded by LEGACY_TOKEN_CUTOFF: failed auth is cheap ------------------


def test_legacy_cutoff_is_not_before_the_markland_9dm_deploy():
    """Legacy-shape tokens were minted until #69 (488711b) was live. Its
    deploy run ran 15:37:42-15:38:29Z on 2026-05-04, and the old image
    served legacy mints until the machine update completed. The 16:00
    floor adds margin for boot and clock skew. A cutoff earlier than that
    would silently lock out a legacy token; later is safe."""
    assert auth.LEGACY_TOKEN_CUTOFF >= "2026-05-04T16:00:00+00:00"


def test_legacy_token_minted_just_before_the_floor_still_resolves(conn):
    """Pins the cutoff's behavior, not just the constant: the last possible
    legacy token must still be found by (c) and backfilled."""
    u = create_user(conn, email="a@x", display_name="A")
    legacy = "mk_usr_" + secrets.token_urlsafe(32)
    _insert_as_previous_release(
        conn, token_id="tok_lastlegacy", plaintext=legacy,
        principal_type="user", principal_id=u.id,
        created_at="2026-05-04T15:59:59.999999+00:00",
    )
    assert resolve_token(conn, legacy).principal_id == u.id
    assert _digest_of(conn, "tok_lastlegacy") == token_digest(legacy)


def _insert_dormant_new_shape(conn, user_id: str) -> str:
    """A new-shape token not presented since the digest release."""
    token_id, plaintext = auth._mint_user_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=plaintext,
        principal_type="user", principal_id=user_id, created_at=POST_CUTOFF,
    )
    return token_id


def test_unknown_bearer_verifies_only_pre_cutoff_digestless_rows(conn, argon2_verifies):
    u = create_user(conn, email="a@x", display_name="A")
    create_user_token(conn, user_id=u.id, label="minted")  # has a digest
    for _ in range(3):
        _insert_dormant_new_shape(conn, u.id)
    _insert_as_previous_release(
        conn, token_id="tok_legacy", plaintext="mk_usr_" + secrets.token_urlsafe(32),
        principal_type="user", principal_id=u.id, created_at=PRE_CUTOFF,
    )

    assert resolve_token(conn, "mk_usr_" + secrets.token_urlsafe(32)) is None
    assert argon2_verifies.call_count == 1  # tok_legacy only
    assert _digest_of(conn, "tok_legacy") is None  # a failed verify never writes a digest


def test_failed_auth_costs_no_argon2_once_pre_cutoff_rows_are_backfilled(
    conn, argon2_verifies
):
    u = create_user(conn, email="a@x", display_name="A")
    legacy = "mk_usr_" + secrets.token_urlsafe(32)
    _insert_as_previous_release(
        conn, token_id="tok_legacy", plaintext=legacy,
        principal_type="user", principal_id=u.id, created_at=PRE_CUTOFF,
    )
    assert resolve_token(conn, legacy) is not None  # backfills tok_legacy
    _insert_dormant_new_shape(conn, u.id)
    token_id, _ = create_user_token(conn, user_id=u.id, label="t")
    argon2_verifies.reset_mock()

    bogus = [
        "mk_usr_" + secrets.token_urlsafe(32),                   # unknown legacy-shape
        "mk_agt_" + secrets.token_urlsafe(32),
        "mk_usr_deadbeefdeadbeef_" + secrets.token_urlsafe(32),  # unknown token_id
        f"mk_usr_{token_id.removeprefix('tok_')}_wrong",         # known id, wrong secret
    ]
    for plaintext in bogus:
        assert resolve_token(conn, plaintext) is None
    assert argon2_verifies.call_count == 0


def test_type_mismatch_on_a_digestless_row_skips_argon2(conn, argon2_verifies):
    u = create_user(conn, email="a@x", display_name="A")
    agent = create_agent(conn, u.id, "scribe")
    token_id, agent_plaintext = auth._mint_agent_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=agent_plaintext,
        principal_type="agent", principal_id=agent.id, created_at=POST_CUTOFF,
    )
    secret = _parse_token_plaintext(agent_plaintext).secret_part
    forged = f"mk_usr_{token_id.removeprefix('tok_')}_{secret}"

    assert resolve_token(conn, forged) is None
    assert argon2_verifies.call_count == 0  # type check first; (c) skips post-cutoff
    assert _digest_of(conn, token_id) is None
    assert resolve_token(conn, agent_plaintext) is not None  # the real token still works


# --- operator status ------------------------------------------------------------


def test_token_digest_counts(conn):
    u = create_user(conn, email="a@x", display_name="A")
    create_user_token(conn, user_id=u.id, label="minted")
    _insert_as_previous_release(
        conn, token_id="tok_legacy", plaintext="mk_usr_" + secrets.token_urlsafe(32),
        principal_type="user", principal_id=u.id, created_at=PRE_CUTOFF,
    )
    token_id, plaintext = auth._mint_user_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=plaintext,
        principal_type="user", principal_id=u.id, created_at=POST_CUTOFF,
    )
    _insert_as_previous_release(
        conn, token_id="tok_revoked", plaintext="mk_usr_" + secrets.token_urlsafe(32),
        principal_type="user", principal_id=u.id, created_at=PRE_CUTOFF,
    )
    conn.execute(
        "UPDATE tokens SET revoked_at = ? WHERE id = 'tok_revoked'", (POST_CUTOFF,)
    )
    conn.commit()
    agent = create_agent(conn, u.id, "gone")
    _insert_as_previous_release(
        conn, token_id="tok_deadagent", plaintext="mk_agt_" + secrets.token_urlsafe(32),
        principal_type="agent", principal_id=agent.id, created_at=PRE_CUTOFF,
    )
    revoke_agent(conn, agent.id, owner_user_id=u.id)  # its token can never resolve

    assert auth.token_digest_counts(conn) == {
        "live": 3, "without_digest": 2, "legacy_scan": 1,
    }
    assert resolve_token(conn, plaintext) is not None  # backfills the new-shape row
    assert auth.token_digest_counts(conn) == {
        "live": 3, "without_digest": 1, "legacy_scan": 1,
    }


def test_token_digest_counts_on_an_empty_table(conn):
    assert auth.token_digest_counts(conn) == {
        "live": 0, "without_digest": 0, "legacy_scan": 0,
    }


def test_token_digest_status_script_prints_counts_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    try:
        c = init_db(tmp_path / "markland.db")
        u = create_user(c, email="a@x", display_name="A")
        _, plaintext = create_user_token(c, user_id=u.id, label="t")
        c.close()
        capsys.readouterr()  # drop the token_create metric line
        script = Path(__file__).resolve().parents[1] / "scripts/admin/token_digest_status.py"
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_path(str(script), run_name="__main__")
        assert exit_info.value.code == 0
    finally:
        reset_config()
    out = capsys.readouterr().out
    assert re.search(r"live tokens:\s+1\b", out)
    assert re.search(r"without a digest yet:\s+0\b", out)
    assert re.search(r"scanned by every failed auth:\s+0\b", out)
    assert plaintext not in out
    assert token_digest(plaintext) not in out
