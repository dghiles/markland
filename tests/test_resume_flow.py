"""Logged-out save-to-account: magic link → /resume → action complete."""

from fastapi.testclient import TestClient

from markland.db import init_db, insert_document
from markland.models import Document
from markland.service.pending_intent import (
    PENDING_INTENT_COOKIE_NAME,
    issue_pending_intent,
)
from markland.service.magic_link import issue_magic_link_token
from markland.service.users import upsert_user_by_email
from markland.web.app import create_app

SECRET = "test-secret"


def _build(tmp_path):
    conn = init_db(tmp_path / "m.db")
    app = create_app(db_conn=conn, session_secret=SECRET, base_url="http://test")
    return app, conn


def _seed_public(conn, *, owner_id="alice") -> Document:
    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(conn, doc_id, "T", "b", share, is_public=True, owner_id=owner_id)
    return Document(
        id=doc_id, title="T", content="b", share_token=share,
        created_at=Document.now(), updated_at=Document.now(),
        is_public=True, is_featured=False, owner_id=owner_id,
        version=1, forked_from_doc_id=None,
    )


def test_verify_page_with_pending_intent_redirects_to_resume(tmp_path):
    app, conn = _build(tmp_path)
    doc = _seed_public(conn, owner_id=upsert_user_by_email(conn, "alice@x.com").id)

    intent = issue_pending_intent(
        secret=SECRET, action="fork", share_token=doc.share_token
    )
    magic = issue_magic_link_token("bob@example.com", secret=SECRET)

    client = TestClient(app)
    r = client.get(
        f"/verify?token={magic}",
        cookies={PENDING_INTENT_COOKIE_NAME: intent},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert r.headers["location"] == "/resume"
    assert "mk_session" in r.cookies


def test_resume_fork_creates_doc_and_clears_cookie(tmp_path):
    from markland.service.sessions import issue_session

    app, conn = _build(tmp_path)
    alice = upsert_user_by_email(conn, "alice@x.com").id
    bob = upsert_user_by_email(conn, "bob@x.com").id
    doc = _seed_public(conn, owner_id=alice)

    intent = issue_pending_intent(
        secret=SECRET, action="fork", share_token=doc.share_token
    )
    session = issue_session(bob, secret=SECRET)
    client = TestClient(app)

    r = client.get(
        "/resume",
        cookies={"mk_session": session, PENDING_INTENT_COOKIE_NAME: intent},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert r.headers["location"].startswith("/d/")
    set_cookies = r.headers.get("set-cookie", "")
    assert PENDING_INTENT_COOKIE_NAME in set_cookies

    new_token = r.headers["location"].rsplit("/", 1)[-1]
    forked = conn.execute(
        "SELECT owner_id, forked_from_doc_id FROM documents WHERE share_token = ?",
        (new_token,),
    ).fetchone()
    assert forked[0] == bob
    assert forked[1] == doc.id


def test_resume_bookmark_inserts_and_clears_cookie(tmp_path):
    from markland.service.sessions import issue_session

    app, conn = _build(tmp_path)
    bob = upsert_user_by_email(conn, "bob@x.com").id
    doc = _seed_public(conn, owner_id=upsert_user_by_email(conn, "alice@x.com").id)

    intent = issue_pending_intent(
        secret=SECRET, action="bookmark", share_token=doc.share_token
    )
    session = issue_session(bob, secret=SECRET)
    client = TestClient(app)

    r = client.get(
        "/resume",
        cookies={"mk_session": session, PENDING_INTENT_COOKIE_NAME: intent},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/d/{doc.share_token}"
    rows = conn.execute(
        "SELECT user_id FROM bookmarks WHERE user_id = ? AND doc_id = ?", (bob, doc.id)
    ).fetchall()
    assert len(rows) == 1


def test_resume_without_cookie_redirects_to_dashboard(tmp_path):
    from markland.service.sessions import issue_session

    app, conn = _build(tmp_path)
    bob = upsert_user_by_email(conn, "bob@x.com").id
    session = issue_session(bob, secret=SECRET)
    client = TestClient(app)

    r = client.get(
        "/resume",
        cookies={"mk_session": session},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"


def test_resume_requires_login(tmp_path):
    app, conn = _build(tmp_path)
    client = TestClient(app)

    r = client.get("/resume", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/login" in r.headers["location"]
