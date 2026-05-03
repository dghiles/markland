"""Unit tests for pure SEO helpers in markland.web.seo."""

import pytest

from markland.web.seo import (
    NOINDEX_PATH_PREFIXES,
    ROBOTS_TXT,
    build_sitemap_xml,
    render_robots_txt,
    should_noindex,
)


def test_should_noindex_blocks_api_and_auth_paths():
    assert should_noindex("/api/tokens")
    assert should_noindex("/mcp/")
    assert should_noindex("/mcp/anything")
    assert should_noindex("/resume")
    assert should_noindex("/login")
    assert should_noindex("/verify")
    assert should_noindex("/setup")
    assert should_noindex("/device")
    assert should_noindex("/device/done")
    assert should_noindex("/settings")
    assert should_noindex("/settings/tokens")
    assert should_noindex("/dashboard")
    assert should_noindex("/inbox")
    assert should_noindex("/invite/abc")
    assert should_noindex("/admin/audit")
    assert should_noindex("/health")


def test_should_noindex_allows_marketing_paths():
    assert not should_noindex("/")
    assert not should_noindex("/quickstart")
    assert not should_noindex("/explore")
    assert not should_noindex("/alternatives")
    assert not should_noindex("/alternatives/notion")
    assert not should_noindex("/d/abc123token")
    assert not should_noindex("/about")
    assert not should_noindex("/security")


def test_robots_txt_references_sitemap_and_core_disallows():
    assert "Sitemap:" in ROBOTS_TXT
    # Disallow lines are generated from NOINDEX_PATH_PREFIXES — every
    # noindex prefix must show up as its own bare-prefix Disallow entry.
    for prefix in NOINDEX_PATH_PREFIXES:
        assert f"Disallow: {prefix}\n" in ROBOTS_TXT
    # Must allow the marketing prefixes (no explicit disallow on root)
    assert "User-agent: *" in ROBOTS_TXT
    assert "Allow: /\n" in ROBOTS_TXT


@pytest.mark.parametrize(
    "bot",
    [
        "GPTBot",
        "CCBot",
        "anthropic-ai",
        "Claude-Web",
        "Google-Extended",
        "PerplexityBot",
        "Bytespider",
    ],
)
def test_robots_txt_blocks_ai_training_crawler(bot):
    """Each AI/training crawler in our blocklist must have its own
    User-agent stanza followed by a full-site Disallow. Locks in the
    audit's L3 expansion so a future refactor can't quietly drop a bot."""
    assert f"User-agent: {bot}\nDisallow: /\n" in ROBOTS_TXT


def test_build_sitemap_xml_contains_all_urls():
    xml = build_sitemap_xml(
        base_url="https://example.test",
        urls=["/", "/quickstart", "/alternatives/notion"],
        lastmod="2026-04-20",
    )
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<urlset" in xml
    assert "<loc>https://example.test/</loc>" in xml
    assert "<loc>https://example.test/quickstart</loc>" in xml
    assert "<loc>https://example.test/alternatives/notion</loc>" in xml
    assert xml.count("<lastmod>2026-04-20</lastmod>") == 3


def test_build_sitemap_xml_escapes_base_url_trailing_slash():
    xml = build_sitemap_xml(
        base_url="https://example.test/",  # trailing slash
        urls=["/quickstart"],
        lastmod="2026-04-20",
    )
    # No double-slash in the URL
    assert "https://example.test//quickstart" not in xml
    assert "<loc>https://example.test/quickstart</loc>" in xml


def test_render_robots_txt_substitutes_sitemap_url():
    out = render_robots_txt("https://example.test/sitemap.xml")
    assert "Sitemap: https://example.test/sitemap.xml" in out
    assert "{sitemap_url}" not in out


def test_build_sitemap_xml_is_well_formed():
    from xml.etree import ElementTree as ET
    xml = build_sitemap_xml(
        base_url="https://example.test",
        urls=["/", "/quickstart"],
        lastmod="2026-04-20",
    )
    root = ET.fromstring(xml)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    assert root.tag.endswith("urlset")
    assert len(root.findall("s:url", ns)) == 2
