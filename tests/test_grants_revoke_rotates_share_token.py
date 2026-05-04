"""P2-F / markland-1e8: revoking a grant on a private doc rotates its
share_token so the old URL becomes a 404.

For public docs, the share_token IS the capability (anyone-with-link)
and is left alone — rotating it would break the public URL.
"""

from __future__ import annotations

import pytest

from markland.db import get_document, get_document_by_token, init_db
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service.auth import Principal


def _user(uid: str = "usr_alice") -> Principal:
    return Principal(
        principal_id=uid,
        principal_type="user",
        display_name=None,
        is_admin=False,
        user_id=uid,
    )


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "t.db")
    c.execute(
        "INSERT INTO users(id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'a@x', 'A', 0, '2026-04-19T00:00:00+00:00')"
    )
    c.execute(
        "INSERT INTO users(id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_bob', 'b@x', 'B', 0, '2026-04-19T00:00:00+00:00')"
    )
    c.commit()
    yield c
    c.close()


def test_revoke_on_private_doc_rotates_share_token(conn):
    """P2-F: revoking the only grant on a private doc rotates the
    share_token. The old URL is no longer resolvable."""
    raw = docs_svc.publish(
        conn, "http://t", _user("usr_alice"), content="secret", title="s",
        public=False,
    )
    grants_svc.grant(
        conn,
        base_url="http://t",
        principal=_user("usr_alice"),
        doc_id=raw["id"],
        target="b@x",
        level="view",
        email_client=None,
    )
    # Capture the URL Bob bookmarked.
    old_token = raw["share_url"].rsplit("/", 1)[1]

    grants_svc.revoke(
        conn,
        principal=_user("usr_alice"),
        doc_id=raw["id"],
        principal_id="usr_bob",
    )

    # Old token must no longer resolve.
    assert get_document_by_token(conn, old_token) is None
    # New token must work for the owner.
    refreshed = get_document(conn, raw["id"])
    assert refreshed is not None
    assert refreshed.share_token != old_token
    assert get_document_by_token(conn, refreshed.share_token) is not None


def test_revoke_on_public_doc_does_not_rotate_share_token(conn):
    """For public docs the share token is the public URL; revoking a
    grant must NOT rotate it (would break the public link)."""
    raw = docs_svc.publish(
        conn, "http://t", _user("usr_alice"), content="hello", title="h",
        public=True,
    )
    grants_svc.grant(
        conn,
        base_url="http://t",
        principal=_user("usr_alice"),
        doc_id=raw["id"],
        target="b@x",
        level="view",
        email_client=None,
    )
    old_token = raw["share_url"].rsplit("/", 1)[1]

    grants_svc.revoke(
        conn,
        principal=_user("usr_alice"),
        doc_id=raw["id"],
        principal_id="usr_bob",
    )

    refreshed = get_document(conn, raw["id"])
    assert refreshed is not None
    assert refreshed.share_token == old_token
    assert get_document_by_token(conn, old_token) is not None
