"""Tests for the Batch 3 audit items (M1-M10).

Audit source: docs/audits/2026-04-24-seo-audit/ACTION-PLAN.md
"""

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


# ---------------------------------------------------------------------------
# M1 — Per-competitor SEO copy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("competitor", COMPETITORS, ids=lambda c: c.slug)
def test_competitor_has_unique_seo_copy(competitor):
    """Every Competitor row has handcrafted seo_title + seo_description.

    Sanity-checks length bounds (titles ≤60, descriptions 140–160) and
    forbids the canned tail the audit flagged ("MCP-first sharing,
    per-doc grants, one link.").
    """
    assert competitor.seo_title and len(competitor.seo_title) <= 60
    assert 140 <= len(competitor.seo_description) <= 160
    assert "per-doc grants, one link" not in competitor.seo_description, (
        f"{competitor.slug} still uses the canned tail"
    )


def test_alternative_page_uses_per_competitor_seo_copy(client):
    """The /alternatives/{slug} template wires through competitor.seo_*."""
    import html as _html

    r = client.get("/alternatives/notion")
    text = r.text
    notion = next(c for c in COMPETITORS if c.slug == "notion")
    title = text.split("<title>")[1].split("</title>")[0]
    assert title == notion.seo_title
    # Description shows up in <meta content="..."> with HTML-escaped
    # punctuation (e.g. ' → &#39;). Compare unescaped.
    start = text.index('<meta name="description" content="') + len(
        '<meta name="description" content="'
    )
    end = text.index('"', start)
    assert _html.unescape(text[start:end]) == notion.seo_description


def test_per_competitor_descriptions_are_unique():
    descs = [c.seo_description for c in COMPETITORS]
    assert len(descs) == len(set(descs)), "competitor descriptions must be unique"


# ---------------------------------------------------------------------------
# M2 — TechArticle on /quickstart
# ---------------------------------------------------------------------------


def test_quickstart_has_techarticle_jsonld(client):
    r = client.get("/quickstart")
    text = r.text
    assert '"@type": "TechArticle"' in text
    assert '"proficiencyLevel": "Beginner"' in text
    # Proves we're NOT using HowTo (deprecated Sep 2023).
    assert '"@type": "HowTo"' not in text


# ---------------------------------------------------------------------------
# M3 — ItemList on /alternatives hub
# ---------------------------------------------------------------------------


def test_alternatives_hub_has_itemlist_jsonld(client):
    r = client.get("/alternatives")
    text = r.text
    assert '"@type": "ItemList"' in text
    # numberOfItems must match COMPETITORS length.
    assert f'"numberOfItems": {len(COMPETITORS)}' in text
    # Every competitor URL appears as a ListItem.
    for c in COMPETITORS:
        assert f"/alternatives/{c.slug}" in text


# ---------------------------------------------------------------------------
# M4 — End-of-page CTA on /quickstart
# ---------------------------------------------------------------------------


def test_quickstart_has_end_of_page_cta(client):
    r = client.get("/quickstart")
    text = r.text
    # The closing form lives in qs-end-cta and tags signups distinctly
    # from the hero CTA on the landing page.
    assert "qs-end-cta" in text
    assert 'value="quickstart-end"' in text
    assert "Join the waitlist" in text


# ---------------------------------------------------------------------------
# M6 — FAQ blocks on / and /quickstart (plain markup, no FAQPage schema)
# ---------------------------------------------------------------------------


def test_landing_has_faq_section(client):
    r = client.get("/")
    text = r.text
    assert 'id="faq"' in text
    assert "Is Markland free?" in text
    assert "How is this different from Git or GitHub?" in text


def test_quickstart_has_faq_section(client):
    r = client.get("/quickstart")
    text = r.text
    assert "qs-faq" in text
    assert "Do I need an API key?" in text


@pytest.mark.parametrize("path", ["/", "/quickstart"])
def test_no_faqpage_schema(client, path):
    """FAQPage rich-result is restricted to gov/health since Aug 2023.
    Plain markup only — never the schema."""
    r = client.get(path)
    assert '"@type": "FAQPage"' not in r.text


# ---------------------------------------------------------------------------
# M7 — Last updated sitewide (centralized in base.html footer)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/", "/quickstart", "/explore", "/alternatives", "/about", "/security",
     "/privacy", "/terms", "/alternatives/notion"],
)
def test_marketing_page_has_last_updated(client, path):
    """Every base-extending marketing page renders a Last updated line
    in the footer (sourced from the page template's mtime)."""
    r = client.get(path)
    assert "Last updated:" in r.text


def test_last_updated_is_iso_date(client):
    """The rendered date is YYYY-MM-DD, not a timestamp or 'today'."""
    import re as _re

    r = client.get("/")
    m = _re.search(r"Last updated: (\d{4}-\d{2}-\d{2})", r.text)
    assert m, "expected ISO YYYY-MM-DD date"


# ---------------------------------------------------------------------------
# M9 — /explore noindex when truly empty
# ---------------------------------------------------------------------------


def test_explore_empty_emits_noindex(client):
    """No public docs + no query → the page should be noindexed so it
    doesn't enter the index as a soft-404."""
    r = client.get("/explore")
    assert '<meta name="robots" content="noindex' in r.text


def test_explore_with_search_query_does_not_noindex(client):
    """A search query represents an indexable query landing page even
    if it has no results — only the no-content base case noindexes."""
    r = client.get("/explore?q=anything")
    # When there are zero docs AND a query, this is a search-empty
    # state, not a soft-404 of the gallery itself. Still safe to allow
    # indexing because the URL is parametrized.
    assert '<meta name="robots" content="noindex' not in r.text


def test_explore_with_public_docs_does_not_noindex(tmp_path, monkeypatch):
    """As soon as one public doc exists, the page is indexable."""
    from markland.db import init_db, insert_document, set_featured

    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t.db")
    insert_document(conn, "p1", "Public", "Body", "tok", is_public=True)
    set_featured(conn, "p1", is_featured=True)
    app = create_app(conn, mount_mcp=False, base_url="http://testserver")
    c = TestClient(app)
    r = c.get("/explore")
    assert '<meta name="robots" content="noindex' not in r.text


# ---------------------------------------------------------------------------
# M10 — Sitemap real per-page lastmod
# ---------------------------------------------------------------------------


def test_sitemap_per_page_lastmod_is_iso_date(client):
    """Each <lastmod> value is a YYYY-MM-DD string sourced from the
    template file mtime. Not all entries have to differ today, but the
    format must be ISO 8601."""
    import re as _re
    import xml.etree.ElementTree as ET

    r = client.get("/sitemap.xml")
    root = ET.fromstring(r.text)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    lastmods = [
        el.text for el in root.findall("s:url/s:lastmod", ns)
    ]
    assert lastmods, "sitemap is empty"
    iso = _re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for v in lastmods:
        assert iso.match(v or ""), f"non-ISO lastmod: {v!r}"
