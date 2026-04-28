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


@pytest.mark.parametrize(
    ("path", "min_len", "max_len"),
    [
        # Titles must claim enough SERP real estate (≥40 chars) without
        # exceeding the ~60-char truncation point. Audit 2026-04-24 H5.
        ("/about", 40, 60),
        ("/security", 40, 60),
        ("/privacy", 40, 60),
        ("/terms", 30, 60),  # "Terms of Service — Markland Beta" = 32
    ],
)
def test_trust_page_title_length(client, path, min_len, max_len):
    r = client.get(path)
    text = r.text
    title = text.split("<title>")[1].split("</title>")[0]
    assert min_len <= len(title) <= max_len, (
        f"{path} title is {len(title)} chars: {title!r}"
    )


@pytest.mark.parametrize("path", ["/privacy", "/terms"])
def test_privacy_terms_meta_description_length(client, path):
    """Audit 2026-04-24 H6: privacy/terms descriptions must clear the
    130-char floor where Google rewrites in SERP."""
    r = client.get(path)
    text = r.text
    start = text.index('<meta name="description" content="') + len(
        '<meta name="description" content="'
    )
    end = text.index('"', start)
    desc = text[start:end]
    assert 130 <= len(desc) <= 160, f"{path} description is {len(desc)} chars"


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
