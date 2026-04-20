"""Dashboard '/dashboard' surfaces a 'Saved' section for bookmarks."""

from fastapi.testclient import TestClient

from markland.db import init_db, insert_document, upsert_bookmark
from markland.models import Document
from markland.service.sessions import issue_session
from markland.service.users import upsert_user_by_email
from markland.web.app import create_app

SECRET = "test-secret"


def _build(tmp_path):
    conn = init_db(tmp_path / "m.db")
    app = create_app(db_conn=conn, session_secret=SECRET, base_url="http://t")
    return app, conn


def _seed(conn, *, owner_id, is_public=True, title="T") -> Document:
    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(conn, doc_id, title, "c", share, is_public=is_public, owner_id=owner_id)
    return Document(
        id=doc_id, title=title, content="c", share_token=share,
        created_at=Document.now(), updated_at=Document.now(),
        is_public=is_public, is_featured=False, owner_id=owner_id,
        version=1, forked_from_doc_id=None,
    )


def test_dashboard_shows_saved_section_with_public_bookmarks(tmp_path):
    app, conn = _build(tmp_path)
    alice = upsert_user_by_email(conn, "alice@x.com").id
    bob = upsert_user_by_email(conn, "bob@x.com").id
    d1 = _seed(conn, owner_id=alice, title="Doc One")
    d2 = _seed(conn, owner_id=alice, title="Doc Two")
    upsert_bookmark(conn, user_id=bob, doc_id=d1.id)
    upsert_bookmark(conn, user_id=bob, doc_id=d2.id)

    client = TestClient(app)
    r = client.get("/dashboard", cookies={"mk_session": issue_session(bob, secret=SECRET)})
    assert r.status_code == 200
    assert "Saved" in r.text
    assert "Doc One" in r.text
    assert "Doc Two" in r.text


def test_dashboard_filters_out_bookmarks_that_became_private(tmp_path):
    app, conn = _build(tmp_path)
    alice = upsert_user_by_email(conn, "alice@x.com").id
    bob = upsert_user_by_email(conn, "bob@x.com").id
    public_doc = _seed(conn, owner_id=alice, is_public=True, title="Still Public")
    private_doc = _seed(conn, owner_id=alice, is_public=False, title="Gone Private")
    upsert_bookmark(conn, user_id=bob, doc_id=public_doc.id)
    upsert_bookmark(conn, user_id=bob, doc_id=private_doc.id)

    client = TestClient(app)
    r = client.get("/dashboard", cookies={"mk_session": issue_session(bob, secret=SECRET)})
    assert "Still Public" in r.text
    assert "Gone Private" not in r.text


def test_dashboard_has_no_saved_section_when_no_bookmarks(tmp_path):
    app, conn = _build(tmp_path)
    bob = upsert_user_by_email(conn, "bob@x.com").id

    client = TestClient(app)
    r = client.get("/dashboard", cookies={"mk_session": issue_session(bob, secret=SECRET)})
    # The literal "Saved" header must not be present when there are no bookmarks.
    assert ">Saved<" not in r.text
