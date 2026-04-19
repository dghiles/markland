"""service/invites.py: accept_invite end-to-end."""

import pytest

from markland.db import get_grant, init_db
from markland.service.grants import grant_by_principal_id as make_grant
from markland.service.invites import accept_invite, create_invite, resolve_invite


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


def _seed_user(conn, user_id, email):
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES (?, ?, ?, 0, '2026-01-01T00:00:00+00:00')",
        (user_id, email, email.split("@")[0]),
    )
    conn.commit()


def _token_from_url(url: str) -> str:
    return url.rsplit("/", 1)[1]


def test_accept_creates_grant_and_decrements_single_use(conn):
    _seed_doc(conn)
    _seed_user(conn, "usr_bob", "bob@example.com")
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    g = accept_invite(conn, invite_token=_token_from_url(r.url), user_id="usr_bob")
    assert g is not None
    assert g.principal_id == "usr_bob"
    assert g.doc_id == "doc_a"
    assert g.level == "view"

    # Invite fully consumed.
    row = conn.execute("SELECT uses_remaining FROM invites WHERE id = ?", (r.id,)).fetchone()
    assert row[0] == 0


def test_accept_reusable_decrements_but_stays_active(conn):
    _seed_doc(conn)
    _seed_user(conn, "usr_bob", "bob@example.com")
    _seed_user(conn, "usr_carol", "carol@example.com")
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
        single_use=False,
    )
    token = _token_from_url(r.url)
    accept_invite(conn, invite_token=token, user_id="usr_bob")
    accept_invite(conn, invite_token=token, user_id="usr_carol")

    row = conn.execute(
        "SELECT uses_remaining FROM invites WHERE id = ?", (r.id,)
    ).fetchone()
    # Decremented twice from starting pool.
    assert row[0] == 1_000_000 - 2
    # Still resolvable.
    assert resolve_invite(conn, token) is not None


def test_accept_idempotent_does_not_downgrade_higher_grant(conn):
    _seed_doc(conn)
    _seed_user(conn, "usr_bob", "bob@example.com")
    # Bob already has edit on doc_a.
    make_grant(
        conn,
        doc_id="doc_a",
        principal_id="usr_bob",
        principal_type="user",
        level="edit",
        granted_by="usr_alice",
    )
    # Invite only offers view.
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    g = accept_invite(conn, invite_token=_token_from_url(r.url), user_id="usr_bob")
    # Returned grant reflects actual grant row (still edit).
    assert g.level == "edit"
    # Use still decremented.
    row = conn.execute("SELECT uses_remaining FROM invites WHERE id = ?", (r.id,)).fetchone()
    assert row[0] == 0


def test_accept_upgrades_view_to_edit(conn):
    _seed_doc(conn)
    _seed_user(conn, "usr_bob", "bob@example.com")
    # Bob has view.
    make_grant(
        conn,
        doc_id="doc_a",
        principal_id="usr_bob",
        principal_type="user",
        level="view",
        granted_by="usr_alice",
    )
    # Invite offers edit.
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="edit",
        base_url="https://markland.dev",
    )
    g = accept_invite(conn, invite_token=_token_from_url(r.url), user_id="usr_bob")
    assert g.level == "edit"
    actual = get_grant(conn, doc_id="doc_a", principal_id="usr_bob")
    assert actual.level == "edit"


def test_accept_unknown_token_returns_none(conn):
    g = accept_invite(conn, invite_token="not_real_aaaaaaaaaaaaaaaaaaaaaaaa", user_id="usr_bob")
    assert g is None


def test_accept_expired_invite_returns_none(conn):
    _seed_doc(conn)
    _seed_user(conn, "usr_bob", "bob@example.com")
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
        expires_at_override="2020-01-01T00:00:00+00:00",
    )
    assert accept_invite(conn, invite_token=_token_from_url(r.url), user_id="usr_bob") is None


def test_accept_used_up_invite_returns_none(conn):
    _seed_doc(conn)
    _seed_user(conn, "usr_bob", "bob@example.com")
    _seed_user(conn, "usr_carol", "carol@example.com")
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    token = _token_from_url(r.url)
    # First accept consumes it.
    assert accept_invite(conn, invite_token=token, user_id="usr_bob") is not None
    # Second accept gets nothing.
    assert accept_invite(conn, invite_token=token, user_id="usr_carol") is None
