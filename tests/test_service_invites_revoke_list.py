"""service/invites.py: revoke + list."""

import pytest

from markland.db import init_db
from markland.service.invites import (
    create_invite,
    list_invites,
    resolve_invite,
    revoke_invite,
)


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


def test_revoke_invite_sets_revoked_at(conn):
    _seed_doc(conn)
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    revoke_invite(conn, invite_id=r.id, owner_user_id="usr_alice")
    row = conn.execute(
        "SELECT revoked_at FROM invites WHERE id = ?", (r.id,)
    ).fetchone()
    assert row[0] is not None


def test_revoke_invite_rejects_non_owner(conn):
    _seed_doc(conn)
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    with pytest.raises(PermissionError):
        revoke_invite(conn, invite_id=r.id, owner_user_id="usr_mallory")


def test_revoke_invite_unknown_id_raises(conn):
    with pytest.raises(ValueError):
        revoke_invite(conn, invite_id="inv_does_not_exist", owner_user_id="usr_alice")


def test_revoked_invite_is_unresolvable(conn):
    _seed_doc(conn)
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    token = r.url.rsplit("/", 1)[1]
    assert resolve_invite(conn, token) is not None
    revoke_invite(conn, invite_id=r.id, owner_user_id="usr_alice")
    assert resolve_invite(conn, token) is None


def test_list_invites_returns_only_the_docs_invites(conn):
    _seed_doc(conn, doc_id="doc_a")
    _seed_doc(conn, doc_id="doc_b")
    create_invite(conn, doc_id="doc_a", created_by_user_id="usr_alice", level="view",
                  base_url="https://markland.dev")
    create_invite(conn, doc_id="doc_a", created_by_user_id="usr_alice", level="edit",
                  base_url="https://markland.dev")
    create_invite(conn, doc_id="doc_b", created_by_user_id="usr_alice", level="view",
                  base_url="https://markland.dev")

    invites = list_invites(conn, doc_id="doc_a")
    assert len(invites) == 2
    assert {i.level for i in invites} == {"view", "edit"}


def test_list_invites_excludes_revoked_by_default(conn):
    _seed_doc(conn)
    r1 = create_invite(conn, doc_id="doc_a", created_by_user_id="usr_alice", level="view",
                       base_url="https://markland.dev")
    r2 = create_invite(conn, doc_id="doc_a", created_by_user_id="usr_alice", level="edit",
                       base_url="https://markland.dev")
    revoke_invite(conn, invite_id=r1.id, owner_user_id="usr_alice")
    active = list_invites(conn, doc_id="doc_a")
    ids = {i.id for i in active}
    assert r2.id in ids
    assert r1.id not in ids


def test_list_invites_include_revoked_true_returns_all(conn):
    _seed_doc(conn)
    r1 = create_invite(conn, doc_id="doc_a", created_by_user_id="usr_alice", level="view",
                       base_url="https://markland.dev")
    revoke_invite(conn, invite_id=r1.id, owner_user_id="usr_alice")
    all_invites = list_invites(conn, doc_id="doc_a", include_revoked=True)
    assert len(all_invites) == 1
    assert all_invites[0].revoked_at is not None
