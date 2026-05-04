"""P3 / markland-6ld: flipping a doc from public→private rotates its
share_token so anyone who saved the public URL loses view access.

Sibling of P2-F (markland-1e8): same severity class — a previously
shared URL must stop working when access is revoked. For the
private→public and public→public no-op transitions, the share_token
is left alone (the URL IS the public capability).
"""

from __future__ import annotations

import pytest

from markland.db import get_document, get_document_by_token, init_db
from markland.service import docs as docs_svc
from markland.service.auth import Principal


BASE = "http://t"


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
    yield c
    c.close()


def test_public_to_private_rotates_share_token(conn):
    """The motivating case: doc starts public, owner makes it private.
    Anyone holding the old URL must now get a 404."""
    alice = _user("usr_alice")
    raw = docs_svc.publish(conn, BASE, alice, content="hello", title="h", public=True)
    old_token = raw["share_url"].rsplit("/", 1)[1]
    assert get_document_by_token(conn, old_token) is not None  # public URL works

    out = docs_svc.set_visibility(conn, BASE, alice, raw["id"], False)
    assert out["is_public"] is False

    # Old token is dead. (get_document_by_token only returns public docs,
    # so even if we hadn't rotated, this would return None — assert on
    # the underlying row to prove the token actually changed.)
    refreshed = get_document(conn, raw["id"])
    assert refreshed is not None
    assert refreshed.share_token != old_token

    # The returned share_url reflects the rotated token.
    assert out["share_url"].endswith(refreshed.share_token)


def test_private_to_public_does_not_rotate_share_token(conn):
    """Going private→public, the share_token IS the new public capability.
    Rotating would invalidate URLs the owner is about to share."""
    alice = _user("usr_alice")
    raw = docs_svc.publish(conn, BASE, alice, content="hello", title="h", public=False)
    old_token = raw["share_url"].rsplit("/", 1)[1]

    out = docs_svc.set_visibility(conn, BASE, alice, raw["id"], True)
    assert out["is_public"] is True

    refreshed = get_document(conn, raw["id"])
    assert refreshed is not None
    assert refreshed.share_token == old_token


def test_public_to_public_noop_does_not_rotate(conn):
    """No transition → no rotation. set_visibility(True) on an already-public
    doc must be a true no-op for the token."""
    alice = _user("usr_alice")
    raw = docs_svc.publish(conn, BASE, alice, content="hello", title="h", public=True)
    old_token = raw["share_url"].rsplit("/", 1)[1]

    docs_svc.set_visibility(conn, BASE, alice, raw["id"], True)

    refreshed = get_document(conn, raw["id"])
    assert refreshed is not None
    assert refreshed.share_token == old_token


def test_private_to_private_noop_does_not_rotate(conn):
    """Symmetry: set_visibility(False) on an already-private doc is a no-op.
    Rotating here would be a footgun — the owner expects the URL they
    have saved to keep working."""
    alice = _user("usr_alice")
    raw = docs_svc.publish(conn, BASE, alice, content="hello", title="h", public=False)
    old_token = raw["share_url"].rsplit("/", 1)[1]

    docs_svc.set_visibility(conn, BASE, alice, raw["id"], False)

    refreshed = get_document(conn, raw["id"])
    assert refreshed is not None
    assert refreshed.share_token == old_token
