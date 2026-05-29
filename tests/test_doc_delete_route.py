"""HTTP doc-delete route — owner-only, cascades."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import get_document, init_db, insert_document
from markland.models import Document
from markland.service.sessions import issue_session
from markland.service.users import upsert_user_by_email
from markland.web.app import create_app

SECRET = "test-secret"


def _build_app_and_conn(tmp_path):
    db = tmp_path / "m.db"
    conn = init_db(db)
    app = create_app(db_conn=conn, session_secret=SECRET, base_url="http://test")
    return app, conn


def _make_user(conn, email: str) -> str:
    return upsert_user_by_email(conn, email).id


def _login_cookie(user_id: str) -> str:
    return issue_session(user_id, secret=SECRET)


def _seed_doc(conn, *, owner_id: str, is_public: bool = False) -> Document:
    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(
        conn, doc_id, "T", "body", share, is_public=is_public, owner_id=owner_id
    )
    return Document(
        id=doc_id, title="T", content="body", share_token=share,
        created_at=Document.now(), updated_at=Document.now(),
        is_public=is_public, is_featured=False, owner_id=owner_id,
        version=1, forked_from_doc_id=None,
    )


def test_owner_can_delete_doc(tmp_path):
    """Owner POSTs /d/{share_token}/delete; doc is gone."""
    app, conn = _build_app_and_conn(tmp_path)
    alice = _make_user(conn, "alice@example.com")
    doc = _seed_doc(conn, owner_id=alice)
    client = TestClient(app)

    r = client.post(
        f"/d/{doc.share_token}/delete",
        cookies={"mk_session": _login_cookie(alice)},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    assert r.headers["location"] == "/dashboard"
    assert get_document(conn, doc.id) is None


def test_non_owner_cannot_delete_doc(tmp_path):
    """A signed-in non-owner POST returns 403/404; doc remains."""
    app, conn = _build_app_and_conn(tmp_path)
    alice = _make_user(conn, "alice@example.com")
    bob = _make_user(conn, "bob@example.com")
    doc = _seed_doc(conn, owner_id=alice)
    client = TestClient(app)

    r = client.post(
        f"/d/{doc.share_token}/delete",
        cookies={"mk_session": _login_cookie(bob)},
        follow_redirects=False,
    )
    assert r.status_code in (403, 404), r.text
    assert get_document(conn, doc.id) is not None


def test_anonymous_cannot_delete_doc(tmp_path):
    """Unauthenticated POST returns 401/403; doc remains."""
    app, conn = _build_app_and_conn(tmp_path)
    alice = _make_user(conn, "alice@example.com")
    doc = _seed_doc(conn, owner_id=alice)
    client = TestClient(app)

    r = client.post(f"/d/{doc.share_token}/delete", follow_redirects=False)
    assert r.status_code in (401, 403, 404), r.text
    assert get_document(conn, doc.id) is not None


def test_delete_unknown_share_token_returns_404(tmp_path):
    """A signed-in user trying to delete a doc that doesn't exist gets 404."""
    app, conn = _build_app_and_conn(tmp_path)
    alice = _make_user(conn, "alice@example.com")
    client = TestClient(app)

    r = client.post(
        "/d/nonexistent-token/delete",
        cookies={"mk_session": _login_cookie(alice)},
        follow_redirects=False,
    )
    assert r.status_code == 404
