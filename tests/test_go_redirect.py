from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app

SECRET = "test-secret"
BASE = "http://markland.dev"


def _client(tmp_path):
    conn = init_db(tmp_path / "m.db")
    app = create_app(db_conn=conn, session_secret=SECRET, base_url=BASE)
    return TestClient(app, base_url=BASE)


def test_go_twitter_default(tmp_path):
    r = _client(tmp_path).get("/go/twitter", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/?utm_source=twitter&utm_medium=social&utm_campaign=launch"


def test_go_source_is_lowercased(tmp_path):
    r = _client(tmp_path).get("/go/Twitter", follow_redirects=False)
    assert r.status_code == 302
    assert "utm_source=twitter" in r.headers["location"]


def test_go_campaign_override(tmp_path):
    r = _client(tmp_path).get("/go/twitter?c=v1-announce", follow_redirects=False)
    assert r.headers["location"] == "/?utm_source=twitter&utm_medium=social&utm_campaign=v1-announce"


def test_go_variant_adds_utm_content(tmp_path):
    r = _client(tmp_path).get("/go/twitter?v=hook-a", follow_redirects=False)
    assert r.headers["location"].endswith("&utm_content=hook-a")


def test_go_landing_path_override(tmp_path):
    r = _client(tmp_path).get("/go/twitter?to=/blog", follow_redirects=False)
    assert r.headers["location"] == "/blog?utm_source=twitter&utm_medium=social&utm_campaign=launch"


def test_go_landing_with_existing_query_uses_ampersand(tmp_path):
    r = _client(tmp_path).get("/go/twitter?to=/blog%3Ffoo%3Dbar", follow_redirects=False)
    assert r.headers["location"] == "/blog?foo=bar&utm_source=twitter&utm_medium=social&utm_campaign=launch"


def test_go_unknown_source_falls_back_to_root(tmp_path):
    r = _client(tmp_path).get("/go/evilsite", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/"


def test_go_rejects_absolute_landing_url(tmp_path):
    r = _client(tmp_path).get("/go/twitter?to=https://evil.example/steal", follow_redirects=False)
    loc = r.headers["location"]
    assert loc.startswith("/?")
    assert "evil.example" not in loc


def test_go_rejects_protocol_relative_landing(tmp_path):
    r = _client(tmp_path).get("/go/twitter?to=//evil.example", follow_redirects=False)
    loc = r.headers["location"]
    assert loc.startswith("/?")
    assert "evil.example" not in loc
