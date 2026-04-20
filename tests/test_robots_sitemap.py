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
    app = create_app(conn, mount_mcp=False, base_url="")
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


def test_robots_txt_ignores_host_header_when_base_url_set(tmp_path, monkeypatch):
    """If base_url is configured, Host header cannot poison the sitemap URL."""
    from markland.db import init_db
    from markland.web.app import create_app
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "h.db")
    app = create_app(conn, mount_mcp=False, base_url="https://canonical.example")
    c = TestClient(app)
    r = c.get("/robots.txt", headers={"host": "evil.example"})
    assert "Sitemap: https://canonical.example/sitemap.xml" in r.text
    assert "evil.example" not in r.text


def test_robots_txt_honors_forwarded_proto(tmp_path, monkeypatch):
    """Without base_url, x-forwarded-proto overrides request.url.scheme."""
    from markland.db import init_db
    from markland.web.app import create_app
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "p.db")
    app = create_app(conn, mount_mcp=False, base_url="")
    c = TestClient(app)
    r = c.get("/robots.txt", headers={"x-forwarded-proto": "https"})
    assert "Sitemap: https://testserver/sitemap.xml" in r.text
