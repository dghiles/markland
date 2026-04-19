"""HTTP ETag/If-Match contract for /api/docs/{id}."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.auth import Principal
from markland.web.app import create_app


BASE = "https://markland.test"


def _seed_users(conn, **email_by_uid: str) -> None:
    for uid, email in email_by_uid.items():
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, '2026-01-01')",
            (uid, email),
        )
    conn.commit()


@pytest.fixture
def env(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_users(conn, usr_alice="a@x")
    alice = Principal(
        principal_id="usr_alice",
        principal_type="user",
        display_name=None,
        is_admin=False,
        user_id="usr_alice",
    )
    email_client = MagicMock()
    app = create_app(
        conn,
        mount_mcp=False,
        base_url=BASE,
        session_secret="test",
        email_client=email_client,
        test_principal_by_token={"alice": alice},
    )
    client = TestClient(app)
    # Create a doc as alice.
    r = client.post(
        "/api/docs",
        headers={"Authorization": "Bearer alice"},
        json={"title": "Hello", "content": "Body v1"},
    )
    assert r.status_code == 200
    doc_id = r.json()["id"]
    auth = {"Authorization": "Bearer alice"}
    return client, doc_id, auth


def test_get_returns_weak_etag_header(env):
    client, doc_id, auth = env
    r = client.get(f"/api/docs/{doc_id}", headers=auth)
    assert r.status_code == 200
    etag = r.headers.get("ETag")
    assert etag is not None
    assert etag == 'W/"1"'


def test_patch_without_if_match_returns_428(env):
    client, doc_id, auth = env
    r = client.patch(
        f"/api/docs/{doc_id}",
        headers=auth,
        json={"content": "Body v2"},
    )
    assert r.status_code == 428
    assert r.json() == {"error": "precondition_required"}


def test_patch_with_stale_if_match_returns_409_and_current_state(env):
    client, doc_id, auth = env
    r1 = client.patch(
        f"/api/docs/{doc_id}",
        headers={**auth, "If-Match": 'W/"1"'},
        json={"content": "Body v2"},
    )
    assert r1.status_code == 200
    r2 = client.patch(
        f"/api/docs/{doc_id}",
        headers={**auth, "If-Match": 'W/"1"'},
        json={"content": "Stale"},
    )
    assert r2.status_code == 409
    body = r2.json()
    assert body["error"] == "conflict"
    assert body["current_version"] == 2
    assert body["current_content"] == "Body v2"
    assert body["current_title"] == "Hello"


def test_patch_with_matching_if_match_succeeds_and_bumps_etag(env):
    client, doc_id, auth = env
    r = client.patch(
        f"/api/docs/{doc_id}",
        headers={**auth, "If-Match": 'W/"1"'},
        json={"content": "Body v2"},
    )
    assert r.status_code == 200
    assert r.headers.get("ETag") == 'W/"2"'
    r2 = client.get(f"/api/docs/{doc_id}", headers=auth)
    assert r2.headers.get("ETag") == 'W/"2"'


def test_patch_accepts_strong_form_of_if_match(env):
    client, doc_id, auth = env
    r = client.patch(
        f"/api/docs/{doc_id}",
        headers={**auth, "If-Match": '"1"'},
        json={"content": "ok"},
    )
    assert r.status_code == 200
