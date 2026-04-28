"""Branded HTML 404 for browser callers; JSON for API/Accept callers.

Audit 2026-04-24 item C3: previously every 404 returned
`{"detail": "Not Found"}`, with no branded shell, no nav back to the
sitemap, and no extending of base.html. Browser-shaped 404s now render
a real page; machine clients still get JSON so the API contract is
preserved.
"""

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


def test_browser_404_renders_html(client):
    """Unmatched path with default Accept (browser-shaped) returns HTML 404."""
    r = client.get("/this-page-does-not-exist")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/html")
    assert "<!DOCTYPE html>" in r.text
    assert "404" in r.text
    # Must reuse base.html so footer + sitewide nav are intact.
    assert 'class="site-header"' in r.text
    assert 'class="site-footer"' in r.text
    # Must offer at least one navigation path back into the site.
    assert 'href="/"' in r.text


def test_browser_404_carries_security_headers(client):
    """SecurityHeadersMiddleware is outermost — 404 responses must carry the headers."""
    r = client.get("/this-page-does-not-exist")
    assert r.status_code == 404
    assert r.headers.get("content-security-policy")
    assert r.headers.get("x-frame-options") == "DENY"


def test_api_404_returns_json(client):
    """/api/* paths must always return JSON, never HTML — machine contract."""
    r = client.get("/api/nonexistent")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"detail": "Not Found"}


def test_explicit_json_accept_returns_json(client):
    """Accept: application/json (without text/html) gets JSON regardless of path."""
    r = client.get(
        "/this-page-does-not-exist",
        headers={"accept": "application/json"},
    )
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_browser_accept_with_json_still_renders_html(client):
    """A browser sending Accept: text/html, application/json should get HTML."""
    r = client.get(
        "/this-page-does-not-exist",
        headers={"accept": "text/html,application/json"},
    )
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/html")


def test_alternatives_unknown_slug_renders_branded_404(client):
    """/alternatives/{slug} 404 now renders the same branded page (was inline HTML)."""
    r = client.get("/alternatives/totally-fake")
    assert r.status_code == 404
    assert "<!DOCTYPE html>" in r.text
    # Inherits base.html — no more bespoke per-route 404 markup.
    assert 'class="site-header"' in r.text
    assert 'class="site-footer"' in r.text
