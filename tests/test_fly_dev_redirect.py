from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app

SECRET = "test-secret"


def _build_client(tmp_path, base_url: str):
    conn = init_db(tmp_path / "m.db")
    app = create_app(db_conn=conn, session_secret=SECRET, base_url=base_url)
    return TestClient(app, base_url=base_url)


def test_fly_dev_apex_redirects_to_markland_dev(tmp_path):
    client = _build_client(tmp_path, "http://markland.fly.dev")
    r = client.get("/", follow_redirects=False, headers={"host": "markland.fly.dev"})
    assert r.status_code == 301
    assert r.headers["location"] == "https://markland.dev/"


def test_fly_dev_path_preserved(tmp_path):
    client = _build_client(tmp_path, "http://markland.fly.dev")
    r = client.get(
        "/alternatives/markshare?utm=test",
        follow_redirects=False,
        headers={"host": "markland.fly.dev"},
    )
    assert r.status_code == 301
    assert r.headers["location"] == "https://markland.dev/alternatives/markshare?utm=test"


def test_markland_dev_host_does_not_redirect(tmp_path):
    client = _build_client(tmp_path, "http://markland.dev")
    r = client.get("/", follow_redirects=False, headers={"host": "markland.dev"})
    assert r.status_code != 301
