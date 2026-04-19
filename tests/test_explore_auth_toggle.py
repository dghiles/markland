"""`/explore` must be session-aware without leaking private docs to anon users."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import docs as docs_svc
from markland.service.auth import Principal, create_user_token
from markland.service.users import create_user
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_USER_PER_MIN", "1000")

    conn = init_db(tmp_path / "e.db")
    alice = create_user(conn, email="a@a", display_name="Alice")
    _, token = create_user_token(conn, user_id=alice.id, label="l")
    alice_p = Principal(
        principal_id=alice.id,
        principal_type="user",
        display_name="Alice",
        is_admin=False,
        user_id=alice.id,
    )
    docs_svc.publish_doc(
        conn, base_url="x", principal=alice_p, title="Public doc", content="p", is_public=True
    )
    docs_svc.publish_doc(
        conn, base_url="x", principal=alice_p, title="Private Mine doc", content="m", is_public=False
    )
    app = create_app(conn, mount_mcp=False, base_url="http://t")
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c


def test_anon_explore_shows_only_public(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")

    conn = init_db(tmp_path / "e2.db")
    alice = create_user(conn, email="a@a", display_name="Alice")
    alice_p = Principal(
        principal_id=alice.id, principal_type="user", display_name="Alice",
        is_admin=False, user_id=alice.id,
    )
    docs_svc.publish_doc(conn, base_url="x", principal=alice_p, title="Public", content="p", is_public=True)
    docs_svc.publish_doc(conn, base_url="x", principal=alice_p, title="SECRETDOC", content="m", is_public=False)

    app = create_app(conn, mount_mcp=False, base_url="http://t")
    with TestClient(app) as c:
        r = c.get("/explore")
    assert r.status_code == 200
    assert "Public" in r.text
    assert "SECRETDOC" not in r.text


def test_authed_default_view_is_public(client):
    r = client.get("/explore")
    assert r.status_code == 200
    assert "Public doc" in r.text
    assert "Private Mine doc" not in r.text


def test_authed_mine_view_shows_owned_docs(client):
    r = client.get("/explore?view=mine")
    assert r.status_code == 200
    assert "Private Mine doc" in r.text
    assert "Public doc" in r.text  # owner sees public too


def test_anon_mine_view_never_leaks(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")

    conn = init_db(tmp_path / "e3.db")
    alice = create_user(conn, email="a@a", display_name="Alice")
    alice_p = Principal(
        principal_id=alice.id, principal_type="user", display_name="Alice",
        is_admin=False, user_id=alice.id,
    )
    docs_svc.publish_doc(conn, base_url="x", principal=alice_p, title="Public", content="p", is_public=True)
    docs_svc.publish_doc(conn, base_url="x", principal=alice_p, title="SECRETDOC", content="m", is_public=False)

    app = create_app(conn, mount_mcp=False, base_url="http://t")
    with TestClient(app) as c:
        r = c.get("/explore?view=mine")
    assert r.status_code in (200, 302)
    assert "SECRETDOC" not in r.text
