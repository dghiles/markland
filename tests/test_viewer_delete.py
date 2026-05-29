"""Viewer (/d/{share_token}) renders a Delete button only for the doc's owner."""

from __future__ import annotations

from fastapi.testclient import TestClient

from markland.db import init_db, insert_document
from markland.models import Document
from markland.service.sessions import issue_session
from markland.service.users import upsert_user_by_email
from markland.web.app import create_app

SECRET = "test-secret"


def _build(tmp_path):
    conn = init_db(tmp_path / "m.db")
    app = create_app(db_conn=conn, session_secret=SECRET, base_url="http://t")
    return app, conn


def _make_user(conn, email: str) -> str:
    return upsert_user_by_email(conn, email).id


def _login_cookie(user_id: str) -> str:
    return issue_session(user_id, secret=SECRET)


def _seed_doc(conn, *, owner_id: str, title: str = "My Doc",
              is_public: bool = True) -> Document:
    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(
        conn, doc_id, title, "c", share, is_public=is_public, owner_id=owner_id
    )
    return Document(
        id=doc_id, title=title, content="c", share_token=share,
        created_at=Document.now(), updated_at=Document.now(),
        is_public=is_public, is_featured=False, owner_id=owner_id,
        version=1, forked_from_doc_id=None,
    )


def test_viewer_shows_delete_button_for_owner(tmp_path):
    app, conn = _build(tmp_path)
    alice = _make_user(conn, "alice@example.com")
    doc = _seed_doc(conn, owner_id=alice, title="My Doc")
    client = TestClient(app)

    r = client.get(
        f"/d/{doc.share_token}",
        cookies={"mk_session": _login_cookie(alice)},
    )
    assert r.status_code == 200
    body = r.text
    assert "data-delete-doc" in body
    assert 'data-delete-title="My Doc"' in body


def test_viewer_hides_delete_button_for_non_owner(tmp_path):
    app, conn = _build(tmp_path)
    alice = _make_user(conn, "alice@example.com")
    bob = _make_user(conn, "bob@example.com")
    doc = _seed_doc(conn, owner_id=alice, title="My Doc")
    client = TestClient(app)

    r = client.get(
        f"/d/{doc.share_token}",
        cookies={"mk_session": _login_cookie(bob)},
    )
    assert r.status_code == 200
    assert "data-delete-doc" not in r.text


def test_viewer_hides_delete_button_for_anonymous(tmp_path):
    app, conn = _build(tmp_path)
    alice = _make_user(conn, "alice@example.com")
    doc = _seed_doc(conn, owner_id=alice, title="My Doc")
    client = TestClient(app)

    r = client.get(f"/d/{doc.share_token}")
    assert r.status_code == 200
    assert "data-delete-doc" not in r.text
