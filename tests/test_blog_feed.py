"""Tests for /blog/feed.xml Atom feed (markland-xgj)."""

import re
import pytest
from xml.etree import ElementTree as ET
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


def test_feed_returns_200(client):
    r = client.get("/blog/feed.xml")
    assert r.status_code == 200


def test_feed_content_type_is_atom(client):
    r = client.get("/blog/feed.xml")
    assert r.headers["content-type"].startswith("application/atom+xml")


def test_feed_is_well_formed_xml(client):
    """Atom feed must parse as XML — feed-readers will reject malformed feeds."""
    r = client.get("/blog/feed.xml")
    # Should not raise.
    root = ET.fromstring(r.text)
    # Root element is {http://www.w3.org/2005/Atom}feed
    assert root.tag.endswith("}feed") or root.tag == "feed"


def test_feed_has_self_link(client):
    """Atom requires a rel=self link pointing back at the feed URL."""
    r = client.get("/blog/feed.xml")
    assert 'rel="self"' in r.text
    assert 'https://markland.test/blog/feed.xml' in r.text


def test_feed_has_alternate_link_to_blog_index(client):
    r = client.get("/blog/feed.xml")
    assert 'rel="alternate"' in r.text
    assert 'https://markland.test/blog' in r.text


def test_feed_includes_each_published_post(client):
    r = client.get("/blog/feed.xml")
    posts = list_published_posts()
    assert len(posts) >= 1
    for p in posts:
        assert p.title in r.text, f"missing post title {p.title!r}"
        assert f"https://markland.test/blog/{p.slug}" in r.text


def test_feed_dates_are_rfc3339(client):
    """Atom requires RFC 3339 datetimes (e.g. 2026-05-03T00:00:00Z)."""
    r = client.get("/blog/feed.xml")
    # At minimum the feed-level <updated> must be present and well-formed.
    m = re.search(r"<updated>([^<]+)</updated>", r.text)
    assert m is not None
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", m.group(1)
    ), f"feed <updated> is not RFC3339: {m.group(1)!r}"


def test_feed_empty_state_still_valid_xml(tmp_path, monkeypatch):
    """When no posts exist, feed must still be valid XML so feed-readers
    don't error on a bad first poll."""
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    reset_cache()
    # Point CONTENT_DIR at an empty directory by monkey-patching.
    import markland.web.blog as blog_mod
    monkeypatch.setattr(blog_mod, "CONTENT_DIR", tmp_path / "empty_blog")
    blog_mod._all_posts.cache_clear()

    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test")
    c = TestClient(app)
    r = c.get("/blog/feed.xml")
    assert r.status_code == 200
    # Should still parse.
    ET.fromstring(r.text)
    assert "<entry>" not in r.text  # but no entries


def test_feed_xml_special_chars_escaped(client):
    """If a future post has '&' or '<' in title/desc, the feed must escape them."""
    r = client.get("/blog/feed.xml")
    # Spot-check: no naked unescaped '&' (every '&' must be '&amp;', '&lt;', etc.)
    bad = re.findall(r"&(?![a-z]+;|#\d+;)", r.text)
    assert not bad, f"feed contains unescaped '&' chars: {bad[:3]}"
