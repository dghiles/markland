"""Trust-floor pages (about/security/privacy/terms) render and appear in sitemap/footer."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="http://testserver")
    return TestClient(app)


@pytest.mark.parametrize("path", ["/about", "/security", "/privacy", "/terms"])
def test_trust_page_renders_200(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert '<meta name="description"' in r.text


def test_footer_links_to_trust_pages(client):
    r = client.get("/")
    text = r.text
    for path in ["/about", "/security", "/privacy", "/terms"]:
        assert f'href="{path}"' in text


def test_sitemap_includes_trust_pages(client):
    r = client.get("/sitemap.xml")
    body = r.text
    for path in ["/about", "/security", "/privacy", "/terms"]:
        assert f"<loc>http://testserver{path}</loc>" in body
