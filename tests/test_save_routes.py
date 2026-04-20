"""Integration tests for /d/{token}/fork and /d/{token}/bookmark."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db, insert_document, upsert_grant
from markland.models import Document
from markland.service.pending_intent import (
    PENDING_INTENT_COOKIE_NAME,
    read_pending_intent,
)
from markland.service.sessions import issue_session
from markland.service.users import upsert_user_by_email
from markland.web.app import create_app

SECRET = "test-secret"


def _build_app_and_conn(tmp_path):
    db = tmp_path / "m.db"
    conn = init_db(db)
    app = create_app(db_conn=conn, session_secret=SECRET, base_url="http://test")
    return app, conn


def _seed_public_doc(conn, *, owner_id="alice") -> Document:
    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(conn, doc_id, "T", "body", share, is_public=True, owner_id=owner_id)
    return Document(
        id=doc_id, title="T", content="body", share_token=share,
        created_at=Document.now(), updated_at=Document.now(),
        is_public=True, is_featured=False, owner_id=owner_id,
        version=1, forked_from_doc_id=None,
    )


def _make_user(conn, email: str) -> str:
    return upsert_user_by_email(conn, email).id


def _login_cookie(user_id: str) -> str:
    return issue_session(user_id, secret=SECRET)


def test_anonymous_fork_sets_pending_intent_and_redirects_to_login(tmp_path):
    app, conn = _build_app_and_conn(tmp_path)
    doc = _seed_public_doc(conn)
    client = TestClient(app)

    r = client.post(f"/d/{doc.share_token}/fork", follow_redirects=False)

    assert r.status_code in (302, 303)
    assert "/login" in r.headers["location"]
    assert "next=%2Fresume" in r.headers["location"] or "next=/resume" in r.headers["location"]

    intent_cookie = r.cookies.get(PENDING_INTENT_COOKIE_NAME)
    assert intent_cookie
    intent = read_pending_intent(intent_cookie, secret=SECRET)
    assert intent.action == "fork"
    assert intent.share_token == doc.share_token


def test_logged_in_non_owner_fork_creates_copy_and_redirects(tmp_path):
    app, conn = _build_app_and_conn(tmp_path)
    doc = _seed_public_doc(conn, owner_id=_make_user(conn, "alice@example.com"))
    bob_id = _make_user(conn, "bob@example.com")
    client = TestClient(app)

    r = client.post(
        f"/d/{doc.share_token}/fork",
        cookies={"mk_session": _login_cookie(bob_id)},
        follow_redirects=False,
    )

    assert r.status_code in (302, 303)
    assert r.headers["location"].startswith("/d/")
    new_token = r.headers["location"].rsplit("/", 1)[-1]
    assert new_token != doc.share_token

    new_doc = conn.execute(
        "SELECT owner_id, forked_from_doc_id, is_public FROM documents WHERE share_token = ?",
        (new_token,),
    ).fetchone()
    assert new_doc[0] == bob_id
    assert new_doc[1] == doc.id
    assert new_doc[2] == 0


def test_owner_fork_returns_400(tmp_path):
    app, conn = _build_app_and_conn(tmp_path)
    alice = _make_user(conn, "alice@example.com")
    doc = _seed_public_doc(conn, owner_id=alice)
    client = TestClient(app)

    r = client.post(
        f"/d/{doc.share_token}/fork",
        cookies={"mk_session": _login_cookie(alice)},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_fork_private_doc_without_grant_returns_403(tmp_path):
    app, conn = _build_app_and_conn(tmp_path)
    alice = _make_user(conn, "alice@example.com")
    bob = _make_user(conn, "bob@example.com")

    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(conn, doc_id, "T", "body", share, is_public=False, owner_id=alice)

    client = TestClient(app)
    r = client.post(
        f"/d/{share}/fork",
        cookies={"mk_session": _login_cookie(bob)},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_bookmark_is_idempotent(tmp_path):
    app, conn = _build_app_and_conn(tmp_path)
    bob = _make_user(conn, "bob@example.com")
    doc = _seed_public_doc(conn, owner_id=_make_user(conn, "alice@example.com"))
    client = TestClient(app)
    cookies = {"mk_session": _login_cookie(bob)}

    r1 = client.post(f"/d/{doc.share_token}/bookmark", cookies=cookies, follow_redirects=False)
    r2 = client.post(f"/d/{doc.share_token}/bookmark", cookies=cookies, follow_redirects=False)
    assert r1.status_code in (302, 303)
    assert r2.status_code in (302, 303)

    rows = conn.execute(
        "SELECT user_id FROM bookmarks WHERE user_id = ? AND doc_id = ?", (bob, doc.id)
    ).fetchall()
    assert len(rows) == 1


def test_anonymous_bookmark_sets_pending_intent_and_redirects(tmp_path):
    app, conn = _build_app_and_conn(tmp_path)
    doc = _seed_public_doc(conn)
    client = TestClient(app)

    r = client.post(f"/d/{doc.share_token}/bookmark", follow_redirects=False)
    assert r.status_code in (302, 303)
    intent_cookie = r.cookies.get(PENDING_INTENT_COOKIE_NAME)
    assert intent_cookie
    intent = read_pending_intent(intent_cookie, secret=SECRET)
    assert intent.action == "bookmark"
    assert intent.share_token == doc.share_token


def test_delete_bookmark_removes_row(tmp_path):
    from markland.db import upsert_bookmark

    app, conn = _build_app_and_conn(tmp_path)
    bob = _make_user(conn, "bob@example.com")
    doc = _seed_public_doc(conn, owner_id=_make_user(conn, "alice@example.com"))
    upsert_bookmark(conn, user_id=bob, doc_id=doc.id)
    client = TestClient(app)

    r = client.delete(
        f"/d/{doc.share_token}/bookmark",
        cookies={"mk_session": _login_cookie(bob)},
        follow_redirects=False,
    )
    assert r.status_code in (200, 302, 303)
    rows = conn.execute("SELECT * FROM bookmarks").fetchall()
    assert rows == []


def test_anonymous_delete_bookmark_returns_401(tmp_path):
    app, conn = _build_app_and_conn(tmp_path)
    doc = _seed_public_doc(conn)
    client = TestClient(app)

    r = client.delete(f"/d/{doc.share_token}/bookmark", follow_redirects=False)
    assert r.status_code == 401
