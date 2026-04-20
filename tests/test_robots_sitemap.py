"""Routes for /robots.txt and /sitemap.xml."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app
from markland.web.competitors import COMPETITORS


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="http://testserver")
    return TestClient(app)


def test_robots_txt_returns_200_plain_text(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")


def test_robots_txt_content(client):
    r = client.get("/robots.txt")
    body = r.text
    assert "User-agent: *" in body
    assert "Disallow: /api/" in body
    assert "Disallow: /mcp/" in body
    assert "Sitemap:" in body
    assert "/sitemap.xml" in body
    # Sitemap URL must use the actual request host, not a hardcoded domain.
    assert "http://testserver/sitemap.xml" in body
