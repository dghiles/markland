"""Tests for /blog index and /blog/{slug} post detail (markland-xgj, markland-380)."""

import json
import re
import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app
from markland.web.blog import list_published_posts, reset_cache


JSONLD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def _jsonld_blocks(html: str) -> list[dict]:
    """Extract every JSON-LD block from a page and parse it.

    Catches Jinja-leak bugs: if a template ships `(canonical_host ~ "/x") | tojson`
    outside `{{ }}` delimiters, json.loads() raises and the test fails. GSC saw
    the symptom of this on 2026-05-15 ("Unparsable structured data: Incorrect
    value type") on /blog — string-substring asserts didn't catch it.
    """
    return [json.loads(m.group(1)) for m in JSONLD_RE.finditer(html)]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    reset_cache()
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test")
    return TestClient(app)


def test_blog_index_returns_200(client):
    r = client.get("/blog")
    assert r.status_code == 200
    assert "Markland Blog" in r.text or "Notes from the agent-native side" in r.text


def test_blog_index_has_blog_jsonld(client):
    """Index page must declare itself as @type=Blog so AI search engines
    classify it correctly."""
    r = client.get("/blog")
    assert '"@type": "Blog"' in r.text
    assert '"@id": "https://markland.test/blog"' in r.text


def test_blog_index_lists_published_posts(client):
    """The shipped anchor post should appear on the index."""
    r = client.get("/blog")
    posts = list_published_posts()
    assert len(posts) >= 1, "expected at least the agent-native-publishing anchor post"
    for p in posts:
        assert f'/blog/{p.slug}' in r.text, f"missing link to /blog/{p.slug}"
        assert p.title in r.text, f"missing title {p.title!r}"


def test_blog_index_links_atom_feed(client):
    r = client.get("/blog")
    assert "/blog/feed.xml" in r.text


def test_blog_index_no_indexability_block(client):
    """Blog index must not be noindex (would defeat the SEO goal)."""
    r = client.get("/blog")
    xrt = r.headers.get("x-robots-tag", "").lower()
    assert "noindex" not in xrt, f"unexpected x-robots-tag: {xrt!r}"
    assert '<meta name="robots" content="noindex' not in r.text


def test_blog_post_returns_200(client):
    """The anchor post must render."""
    r = client.get("/blog/agent-native-publishing")
    assert r.status_code == 200


def test_blog_post_has_article_jsonld(client):
    r = client.get("/blog/agent-native-publishing")
    assert '"@type": "Article"' in r.text
    assert '"headline": "What is agent-native publishing?"' in r.text
    assert '"datePublished":' in r.text
    assert '"dateModified":' in r.text


def test_blog_post_has_person_author_jsonld(client):
    """Article must reference a Person author (not a bare string).
    @id-linked so the Person block is the canonical author identity."""
    r = client.get("/blog/agent-native-publishing")
    assert '"@type": "Person"' in r.text
    assert '"@id": "https://markland.test/about/dghiles#person"' in r.text


def test_blog_post_has_breadcrumb_jsonld(client):
    r = client.get("/blog/agent-native-publishing")
    assert '"@type": "BreadcrumbList"' in r.text


def test_blog_post_has_h1(client):
    r = client.get("/blog/agent-native-publishing")
    assert "<h1>What is agent-native publishing?</h1>" in r.text


def test_blog_post_renders_markdown_body(client):
    """Body markdown must render to HTML (not show as raw markdown)."""
    r = client.get("/blog/agent-native-publishing")
    # The post has multiple ## headings — they should be <h2> in output.
    assert "<h2" in r.text
    # No bare markdown heading syntax should leak through.
    assert "\n## " not in r.text


def test_blog_post_definition_block_in_citation_window(client):
    """The 'Agent-native publishing, defined' section is the AI-citation
    target. Word count must stay in the 120-200 sweet spot."""
    r = client.get("/blog/agent-native-publishing")
    body = r.text
    # Find the 'defined' h2, then capture text up to the next h2.
    m = re.search(
        r"<h2[^>]*>Agent-native publishing, defined</h2>(.+?)<h2",
        body,
        re.S,
    )
    assert m is not None, "definition section heading not found"
    block_text = re.sub(r"<[^>]+>", " ", m.group(1))
    block_text = re.sub(r"\s+", " ", block_text).strip()
    word_count = len(block_text.split())
    assert 120 <= word_count <= 200, (
        f"definition block is {word_count} words; want 120-200"
    )


def test_blog_post_meta_description_in_seo_band(client):
    r = client.get("/blog/agent-native-publishing")
    m = re.search(r'<meta name="description" content="([^"]+)"', r.text)
    assert m is not None
    desc = m.group(1)
    assert 130 <= len(desc) <= 165, (
        f"meta description is {len(desc)} chars; want 130-165"
    )


def test_blog_post_canonical_url(client):
    r = client.get("/blog/agent-native-publishing")
    assert (
        '<link rel="canonical" href="https://markland.test/blog/agent-native-publishing">'
        in r.text
    )


def test_blog_post_og_type_article(client):
    """og:type for posts must be 'article', not the default 'website'."""
    r = client.get("/blog/agent-native-publishing")
    assert '<meta property="og:type" content="article">' in r.text


def test_blog_post_unknown_slug_returns_404(client):
    r = client.get("/blog/this-post-does-not-exist")
    assert r.status_code == 404


def test_blog_post_links_back_to_quickstart(client):
    """Footer CTA on every post should drive to /quickstart (single high-intent target)."""
    r = client.get("/blog/agent-native-publishing")
    assert 'href="/quickstart"' in r.text


def test_blog_index_jsonld_is_valid_json(client):
    """Every JSON-LD block on /blog must parse as JSON. Regression test for
    the 2026-05-15 GSC "Unparsable structured data" report — Jinja expressions
    were leaking as literal text because they weren't wrapped in `{{ }}`."""
    r = client.get("/blog")
    blocks = _jsonld_blocks(r.text)
    assert len(blocks) >= 1, "expected at least one JSON-LD block on /blog"
    types = [b.get("@type") for b in blocks]
    assert "Blog" in types, f"missing @type=Blog block; saw {types}"
    blog_block = next(b for b in blocks if b.get("@type") == "Blog")
    assert blog_block["publisher"]["@id"] == "https://markland.test/#organization"


def test_blog_post_jsonld_is_valid_json(client):
    """Every JSON-LD block on a post detail page must parse as JSON. Covers
    Article + Person + BreadcrumbList; would catch any future Jinja leak."""
    r = client.get("/blog/agent-native-publishing")
    blocks = _jsonld_blocks(r.text)
    types = [b.get("@type") for b in blocks]
    assert "Article" in types
    assert "Person" in types
    assert "BreadcrumbList" in types
    article = next(b for b in blocks if b.get("@type") == "Article")
    assert article["publisher"]["@id"] == "https://markland.test/#organization"
    assert article["isPartOf"]["@id"] == "https://markland.test/blog"
    assert article["author"]["@id"] == "https://markland.test/about/dghiles#person"
