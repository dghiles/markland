"""Tests for /blog index and /blog/{slug} post detail (markland-xgj, markland-380)."""

import re
import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app
from markland.web.blog import list_published_posts, reset_cache


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
