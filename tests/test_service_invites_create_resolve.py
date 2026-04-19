"""service/invites.py: create + resolve with hashed-token round-trip."""

from datetime import datetime, timedelta, timezone

import pytest

from markland.db import init_db
from markland.service.invites import create_invite, resolve_invite


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "t.db")


def _seed_doc(conn, doc_id="doc_a", owner_id="usr_alice"):
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "(?, 't', 'c', ?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 0, 0, ?)",
        (doc_id, f"tok_{doc_id}", owner_id),
    )
    conn.commit()


def test_create_invite_returns_id_and_url(conn):
    _seed_doc(conn)
    result = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    assert result.id.startswith("inv_")
    assert result.url.startswith("https://markland.dev/invite/")
    # URL ends with a prefixed URL-safe token: mk_inv_<urlsafe32>.
    token = result.url.rsplit("/", 1)[1]
    assert token.startswith("mk_inv_")
    assert len(token) >= len("mk_inv_") + 40


def test_create_persists_hashed_token_not_plaintext(conn):
    _seed_doc(conn)
    result = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="edit",
        base_url="https://markland.dev",
    )
    token = result.url.rsplit("/", 1)[1]
    row = conn.execute("SELECT token_hash FROM invites WHERE id = ?", (result.id,)).fetchone()
    assert row is not None
    # Stored value is a hash, not the plaintext.
    assert row[0] != token
    assert len(row[0]) > 50  # argon2id hashes are long encoded strings


def test_resolve_invite_returns_invite_for_valid_token(conn):
    _seed_doc(conn)
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    token = r.url.rsplit("/", 1)[1]
    inv = resolve_invite(conn, token)
    assert inv is not None
    assert inv.id == r.id
    assert inv.doc_id == "doc_a"
    assert inv.level == "view"


def test_resolve_invite_returns_none_for_unknown_token(conn):
    assert resolve_invite(conn, "not_a_real_token_aaaaaaaaaaaaaaaaaaaaaaaaaa") is None


def test_resolve_invite_returns_none_if_expired(conn):
    _seed_doc(conn)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
        expires_at_override=past,
    )
    token = r.url.rsplit("/", 1)[1]
    assert resolve_invite(conn, token) is None


def test_resolve_invite_returns_none_if_revoked(conn):
    _seed_doc(conn)
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    token = r.url.rsplit("/", 1)[1]
    conn.execute(
        "UPDATE invites SET revoked_at = ? WHERE id = ?",
        ("2026-04-19T00:00:00+00:00", r.id),
    )
    conn.commit()
    assert resolve_invite(conn, token) is None


def test_resolve_invite_returns_none_if_no_uses_remaining(conn):
    _seed_doc(conn)
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    token = r.url.rsplit("/", 1)[1]
    conn.execute("UPDATE invites SET uses_remaining = 0 WHERE id = ?", (r.id,))
    conn.commit()
    assert resolve_invite(conn, token) is None


def test_create_rejects_unknown_level(conn):
    _seed_doc(conn)
    with pytest.raises(ValueError):
        create_invite(
            conn,
            doc_id="doc_a",
            created_by_user_id="usr_alice",
            level="admin",
            base_url="https://markland.dev",
        )


def test_create_expires_in_days_sets_expires_at(conn):
    _seed_doc(conn)
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
        expires_in_days=7,
    )
    row = conn.execute("SELECT expires_at FROM invites WHERE id = ?", (r.id,)).fetchone()
    assert row[0] is not None
