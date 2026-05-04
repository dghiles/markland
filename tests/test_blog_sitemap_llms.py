"""Sitemap + llms.txt gating for /blog (markland-xgj)."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app
from markland.web.blog import list_published_posts, reset_cache


def _client(tmp_path, monkeypatch, blog_content_dir):
    """Build a TestClient with CONTENT_DIR pointed at a chosen directory."""
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    import markland.web.blog as blog_mod
    monkeypatch.setattr(blog_mod, "CONTENT_DIR", blog_content_dir)
    blog_mod._all_posts.cache_clear()
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test")
    return TestClient(app)


def test_sitemap_excludes_blog_when_no_posts(tmp_path, monkeypatch):
    """No published posts → /blog and /blog/* must not appear in sitemap.
    Same gating principle as /explore (audit G5)."""
    c = _client(tmp_path, monkeypatch, tmp_path / "empty_blog")
    r = c.get("/sitemap.xml")
    assert r.status_code == 200
    assert "<loc>https://markland.test/blog</loc>" not in r.text
    assert "/blog/" not in r.text
    # Sanity: marketing URLs we always want are still present.
    assert "<loc>https://markland.test/quickstart</loc>" in r.text


def test_sitemap_includes_blog_index_when_posts_exist(tmp_path, monkeypatch):
    blog_dir = tmp_path / "blog_with_post"
    blog_dir.mkdir()
    (blog_dir / "test-post.md").write_text(
        "---\n"
        "title: A Test Post\n"
        "slug: test-post\n"
        "published_at: 2026-05-03\n"
        "description: Testing.\n"
        "---\n\n"
        "Body.\n"
    )
    c = _client(tmp_path, monkeypatch, blog_dir)
    r = c.get("/sitemap.xml")
    assert r.status_code == 200
    assert "<loc>https://markland.test/blog</loc>" in r.text
    assert "<loc>https://markland.test/blog/test-post</loc>" in r.text


def test_llms_txt_excludes_blog_when_no_posts(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, tmp_path / "empty_blog")
    r = c.get("/llms.txt")
    assert r.status_code == 200
    assert "## Blog" not in r.text


def test_llms_txt_includes_blog_when_posts_exist(tmp_path, monkeypatch):
    blog_dir = tmp_path / "blog_with_post"
    blog_dir.mkdir()
    (blog_dir / "first-post.md").write_text(
        "---\n"
        "title: First Post Title\n"
        "slug: first-post\n"
        "published_at: 2026-05-03\n"
        "description: First post description.\n"
        "---\n\n"
        "Body.\n"
    )
    c = _client(tmp_path, monkeypatch, blog_dir)
    r = c.get("/llms.txt")
    assert r.status_code == 200
    assert "## Blog" in r.text
    assert "First Post Title" in r.text
    assert "https://markland.test/blog/first-post" in r.text


def test_llms_txt_blog_section_after_about_section(tmp_path, monkeypatch):
    """Layout sanity: the Blog section should come after About in the
    rendered file so the canonical (## Core / ## About) structure stays
    on top."""
    blog_dir = tmp_path / "blog_with_post"
    blog_dir.mkdir()
    (blog_dir / "p.md").write_text(
        "---\ntitle: T\nslug: p\npublished_at: 2026-05-03\ndescription: D.\n---\n\nB.\n"
    )
    c = _client(tmp_path, monkeypatch, blog_dir)
    r = c.get("/llms.txt")
    about_idx = r.text.find("## About")
    blog_idx = r.text.find("## Blog")
    assert about_idx > 0 and blog_idx > 0
    assert blog_idx > about_idx, "Blog section should appear after About"
