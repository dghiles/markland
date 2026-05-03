"""Tests for per-competitor SEO copy and FAQ content (G3c)."""

import html
import re

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app
from markland.web.competitors import COMPETITORS


@pytest.mark.parametrize("competitor", COMPETITORS, ids=lambda c: c.slug)
def test_competitor_has_at_least_three_faqs(competitor):
    """Every competitor must have ≥3 FAQ entries for AI-search citation
    surface (G3c)."""
    assert hasattr(competitor, "faqs"), f"{competitor.slug} missing faqs field"
    assert len(competitor.faqs) >= 3, (
        f"{competitor.slug} has {len(competitor.faqs)} FAQs; want ≥3"
    )
    for q, a in competitor.faqs:
        assert q.endswith("?"), f"{competitor.slug} FAQ '{q}' must end with '?'"
        assert len(a.split()) >= 25, (
            f"{competitor.slug} answer to '{q}' is {len(a.split())} words; want ≥25"
        )


@pytest.mark.parametrize("competitor", COMPETITORS, ids=lambda c: c.slug)
def test_competitor_page_renders_faq_section(competitor, tmp_path, monkeypatch):
    """The FAQ data must appear in the rendered page as <h3>question</h3>."""
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / f"{competitor.slug}.db")
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test")
    r = TestClient(app).get(f"/alternatives/{competitor.slug}")
    assert r.status_code == 200
    # Unescape HTML entities so apostrophes/quotes match the raw string
    page_text = html.unescape(r.text)
    h3_questions = re.findall(r'<h3[^>]*>[^<]*\?', page_text)
    assert len(h3_questions) >= 3, (
        f"{competitor.slug} renders {len(h3_questions)} question H3s; want ≥3"
    )
    # First FAQ question must be visible verbatim
    first_q = competitor.faqs[0][0]
    assert first_q in page_text, f"{competitor.slug} missing FAQ Q1: {first_q!r}"
