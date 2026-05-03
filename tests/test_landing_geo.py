"""Tests for the landing-page GEO answer block (audit G4)."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test")
    return TestClient(app)


def test_landing_has_what_is_markland_h2(client):
    """AI Overviews and ChatGPT Search preferentially cite passages with a
    leading 'What is X?' heading."""
    r = client.get("/")
    assert r.status_code == 200
    assert "<h2" in r.text
    # The exact heading text — locks regression in case copy drifts
    assert ">What is Markland?<" in r.text


def test_landing_answer_block_contains_required_concepts(client):
    """The answer paragraph must mention all three load-bearing concepts so
    AI engines can cite the block as a definition: 'markdown', 'agent',
    and 'MCP'."""
    r = client.get("/")
    body = r.text
    start = body.find(">What is Markland?<")
    assert start != -1
    end = body.find("</section>", start)
    block = body[start:end]
    for word in ["markdown", "agent", "MCP"]:
        assert word.lower() in block.lower(), f"answer block missing '{word}'"


def test_landing_answer_block_word_count_is_in_citation_window(client):
    """134–167 words is the documented optimal window for AI-overview
    citation. Allow a small buffer (120–180) so a future copy edit doesn't
    silently fall out of band."""
    import re
    r = client.get("/")
    body = r.text
    start = body.find(">What is Markland?<")
    end = body.find("</section>", start)
    block = body[start:end]
    text = re.sub(r"<[^>]+>", " ", block)
    text = re.sub(r"\s+", " ", text).strip()
    words = len(text.split())
    # Subtract the heading itself (3 words) for a fair count
    body_words = words - 3
    assert 120 <= body_words <= 180, (
        f"answer block is {body_words} words; want 120–180 (target 140)"
    )


def test_landing_faq_uses_h3_headings(client):
    """FAQ questions must be in <h3> tags so AI/SEO crawlers see them as
    headings, not definition terms. Audit G3a."""
    import re
    r = client.get("/")
    # Count question-shaped <h3> elements (containing '?')
    h3_questions = re.findall(r'<h3[^>]*>[^<]*\?', r.text)
    assert len(h3_questions) >= 4, (
        f"want ≥4 question-shaped <h3> headings, found {len(h3_questions)}"
    )
    # Specific load-bearing questions must be present
    for q in [
        "Is Markland free?",
        "How is this different from Git or GitHub?",
        "Where does my content live?",
    ]:
        assert re.search(rf"<h3[^>]*>{re.escape(q)}</h3>", r.text), (
            f"missing '{q}' as <h3>"
        )


def test_landing_faq_has_no_legacy_dt_markup(client):
    """Definition-list markup is the legacy form — assert it's gone so a
    future template change doesn't silently re-introduce it."""
    r = client.get("/")
    # The FAQ section markers
    assert 'class="section faq"' in r.text or 'id="faq"' in r.text
    # No <dt> or <dd> tags inside the FAQ section
    faq_start = r.text.find('id="faq"')
    faq_end = r.text.find("</section>", faq_start)
    faq_block = r.text[faq_start:faq_end]
    assert "<dt>" not in faq_block, "FAQ still uses <dt> — should be <h3>"
    assert "<dd>" not in faq_block, "FAQ still uses <dd> — should be <p>"
