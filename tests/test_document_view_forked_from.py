"""view_document must render 'Forked from X' when forked_from_doc_id is set."""

from fastapi.testclient import TestClient

from markland.db import init_db, insert_document
from markland.models import Document
from markland.web.app import create_app


def _build(tmp_path):
    conn = init_db(tmp_path / "m.db")
    app = create_app(db_conn=conn, session_secret="s", base_url="http://t")
    return app, conn


def _insert_doc(conn, **kw) -> Document:
    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(
        conn, doc_id, kw.get("title", "T"), kw.get("content", "c"), share,
        is_public=kw.get("is_public", True), owner_id=kw.get("owner_id"),
        forked_from_doc_id=kw.get("forked_from_doc_id"),
    )
    doc = Document(
        id=doc_id, title=kw.get("title", "T"), content=kw.get("content", "c"),
        share_token=share, created_at=Document.now(), updated_at=Document.now(),
        is_public=kw.get("is_public", True), is_featured=False,
        owner_id=kw.get("owner_id"), version=1,
        forked_from_doc_id=kw.get("forked_from_doc_id"),
    )
    return doc


def test_fork_with_public_parent_renders_link(tmp_path):
    app, conn = _build(tmp_path)
    parent = _insert_doc(conn, title="Parent Title", owner_id="alice", is_public=True)
    fork = _insert_doc(
        conn, title="Parent Title", owner_id="bob", is_public=True,
        forked_from_doc_id=parent.id,
    )
    client = TestClient(app)

    r = client.get(f"/d/{fork.share_token}")
    assert r.status_code == 200
    body = r.text
    assert "Forked from" in body
    assert f'/d/{parent.share_token}' in body
    assert "Parent Title" in body


def test_fork_with_private_parent_renders_title_without_link(tmp_path):
    app, conn = _build(tmp_path)
    parent = _insert_doc(conn, title="Private Parent", owner_id="alice", is_public=False)
    fork = _insert_doc(
        conn, title="Private Parent", owner_id="bob", is_public=True,
        forked_from_doc_id=parent.id,
    )
    client = TestClient(app)

    r = client.get(f"/d/{fork.share_token}")
    body = r.text
    assert "Forked from" in body
    # Anonymous viewer cannot access the private parent — no link.
    assert f'/d/{parent.share_token}' not in body
    assert "Private Parent" in body


def test_non_fork_has_no_forked_from_line(tmp_path):
    app, conn = _build(tmp_path)
    doc = _insert_doc(conn, owner_id="alice")
    client = TestClient(app)

    r = client.get(f"/d/{doc.share_token}")
    assert "Forked from" not in r.text
