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


@pytest.mark.parametrize(
    ("path", "min_words"),
    [
        # Audit 2026-04-24 C4: every trust page must clear the 250-word
        # E-E-A-T thin-content floor. Page-specific floors picked above
        # the audit baseline (about 98w, security 118w, privacy 101w,
        # terms 95w) — never let regression silently re-thin them.
        # 2026-05-04: privacy floor bumped to 800 (formal privacy policy);
        # terms floor bumped to 900 (formal Terms of Service).
        ("/about", 250),
        ("/security", 300),
        ("/privacy", 800),
        ("/terms", 900),
    ],
)
def test_trust_page_word_count(client, path, min_words):
    import re as _re

    r = client.get(path)
    # Strip script/style and tags; condense whitespace; count words.
    body = _re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r.text, flags=_re.DOTALL)
    visible = _re.sub(r"<[^>]+>", " ", body)
    visible = _re.sub(r"\s+", " ", visible)
    words = len(visible.split())
    assert words >= min_words, f"{path} now has {words} words (floor {min_words})"


@pytest.mark.parametrize("path", ["/about", "/security", "/privacy", "/terms"])
def test_trust_page_has_last_updated(client, path):
    """Freshness signal — every trust page must carry a 'Last updated' line."""
    r = client.get(path)
    assert "Last updated:" in r.text


@pytest.mark.parametrize("path", ["/", "/quickstart", "/alternatives", "/about"])
def test_footer_has_author_byline(client, path):
    """Audit 2026-04-24 H1: every marketing page footer must carry an
    author/expertise signal — without it the site has no off-page trust
    hook for E-E-A-T or LLM citation hedging."""
    r = client.get(path)
    text = r.text
    assert "@dghiles" in text
    assert 'href="https://github.com/dghiles"' in text
    assert 'rel="author"' in text


def test_organization_jsonld_has_founder(client):
    """Organization.founder Person block ties the entity to a named human."""
    r = client.get("/")
    text = r.text
    assert '"founder"' in text
    assert '"@type": "Person"' in text
    assert '"name": "@dghiles"' in text


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


def test_security_page_discloses_umami(client):
    r = client.get("/security")
    assert r.status_code == 200
    assert "Umami" in r.text
    assert "cookie" in r.text.lower()  # confirms the no-cookie note is present


def test_privacy_has_standard_sections(client):
    """The /privacy page must carry the ten standard sections of a real
    privacy policy. Section presence is asserted via the <h2> heading
    text — order is not enforced here, only completeness."""
    r = client.get("/privacy")
    text = r.text
    required_h2 = [
        "Information we collect",
        "How we use your information",
        "Who we share data with",
        "Data retention",
        "Your rights and choices",
        "International transfers",
        "Security",
        "Children's privacy",
        "Changes to this policy",
        "Contact us",
    ]
    missing = [h for h in required_h2 if h not in text]
    assert not missing, f"/privacy missing sections: {missing}"


def test_terms_has_standard_sections(client):
    """The /terms page must carry the 14 standard sections of a real
    terms-of-service document. Section presence is asserted via the
    <h2> heading text — order is not enforced here, only completeness."""
    r = client.get("/terms")
    text = r.text
    required_h2 = [
        "Introduction and acceptance",
        "Definitions",
        "Your account",
        "Acceptable use",
        "Your content",
        "Our service",
        "Termination",
        "Disclaimers",
        "Limitation of liability",
        "Indemnification",
        "Governing law and disputes",
        "General",
        "Changes to these terms",
        "Contact",
    ]
    missing = [h for h in required_h2 if h not in text]
    assert not missing, f"/terms missing sections: {missing}"
