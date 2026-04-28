"""SEO meta tags appear on every marketing page."""

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


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/quickstart",
        "/explore",
        "/alternatives",
    ],
)
def test_pages_have_meta_description(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert '<meta name="description"' in r.text


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/quickstart",
        "/explore",
        "/alternatives",
    ],
)
def test_pages_have_canonical(client, path):
    r = client.get(path)
    text = r.text
    assert '<link rel="canonical"' in text
    assert f'href="http://testserver{path}"' in text


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/quickstart",
        "/alternatives",
    ],
)
def test_pages_have_og_and_twitter_tags(client, path):
    r = client.get(path)
    text = r.text
    assert 'property="og:title"' in text
    assert 'property="og:description"' in text
    assert 'property="og:type"' in text
    assert 'property="og:url"' in text
    assert 'name="twitter:card"' in text


def test_homepage_includes_softwareapplication_jsonld(client):
    r = client.get("/")
    text = r.text
    assert '"@type": "SoftwareApplication"' in text
    assert '"@type": "Organization"' in text
    assert '"@type": "WebSite"' in text


def test_softwareapplication_has_offers_field(client):
    """SoftwareApplication.offers is required for the Software App rich result."""
    r = client.get("/")
    text = r.text
    # Free product, USD, in-stock — minimal Offer satisfying Google's requirement.
    assert '"offers"' in text
    assert '"@type": "Offer"' in text
    assert '"price": "0"' in text
    assert '"priceCurrency": "USD"' in text


def test_organization_has_logo_and_sameas(client):
    """Organization needs logo (knowledge panel) and sameAs (entity disambiguation)."""
    r = client.get("/")
    text = r.text
    assert '"logo"' in text
    assert '"@type": "ImageObject"' in text
    assert '"sameAs"' in text
    assert "github.com/dghiles/markland" in text


def test_alternative_page_emits_breadcrumblist(client):
    """Per-competitor pages emit a BreadcrumbList for SERP breadcrumb rendering."""
    r = client.get("/alternatives/notion")
    text = r.text
    assert '"@type": "BreadcrumbList"' in text
    assert '"@type": "ListItem"' in text
    # Three positions: Home, Alternatives, {competitor}
    assert '"position": 1' in text
    assert '"position": 2' in text
    assert '"position": 3' in text
    assert '"name": "Notion"' in text
    assert "http://testserver/alternatives/notion" in text


def test_alternatives_hub_competitor_names_are_h2(client):
    """Each competitor card on the hub must use <h2> so LLMs and Google can scope passages per competitor."""
    r = client.get("/alternatives")
    text = r.text
    # Every competitor name should appear inside an <h2>...</h2>; div-wrapping was the regression we just fixed.
    # All five COMPETITORS rows must be covered — HackMD's row uses the long compound name from competitors.py.
    for name in (
        "Markshare.to",
        "GitHub",
        "Google Docs",
        "Notion",
        "HackMD / HedgeDoc / Gist / Pastebin",
    ):
        assert f"<h2 class=\"alt-name\">Markland vs {name}</h2>" in text


def test_homepage_h1_has_aria_label(client):
    """Decorative H1 fragments need an aria-label for crawlers/SR users."""
    r = client.get("/")
    assert 'aria-label="Shared documents for you and your agents"' in r.text


def test_homepage_title_includes_mcp_and_claude_code(client):
    r = client.get("/")
    assert "MCP" in r.text.split("<title>")[1].split("</title>")[0]
    assert ("Claude Code" in r.text or "AI agents" in r.text)


def test_homepage_has_specific_meta_description(client):
    r = client.get("/")
    text = r.text
    start = text.index('<meta name="description"')
    end = text.index(">", start)
    tag = text[start:end]
    assert "MCP" in tag
    assert "Claude Code" in tag


def test_alternatives_description_mentions_comparison(client):
    r = client.get("/alternatives")
    text = r.text
    start = text.index('<meta name="description"')
    end = text.index(">", start)
    tag = text[start:end]
    # Substring from the per-page copy; not present in the partial's fallback.
    assert "Google Docs" in tag
    assert "Markshare" in tag
