"""`/quickstart` renders 200 and contains all five onboarding steps."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "q.db")
    app = create_app(conn, mount_mcp=False, base_url="http://t")
    return TestClient(app)


def test_quickstart_renders_200(client):
    r = client.get("/quickstart")
    assert r.status_code == 200


def test_quickstart_mentions_all_five_steps(client):
    r = client.get("/quickstart")
    body = r.text.lower()
    assert "sign up" in body
    assert "/setup" in body
    assert "markland_publish" in body
    assert "markland_grant" in body
    assert "view the doc" in body or "view your doc" in body


def test_landing_links_to_quickstart(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "/quickstart" in r.text
