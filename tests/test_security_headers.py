"""Security headers applied to every response; X-Robots-Tag on non-marketing paths."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db, insert_document
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "s.db")
    insert_document(conn, "doc1", "Test", "# Hi", "tok1")
    app = create_app(conn, mount_mcp=False, base_url="http://testserver")
    return TestClient(app)


@pytest.mark.parametrize("path", ["/", "/quickstart", "/explore", "/robots.txt", "/sitemap.xml"])
def test_security_headers_present(client, path):
    r = client.get(path)
    h = r.headers
    assert h.get("strict-transport-security", "").startswith("max-age=")
    assert "content-security-policy" in h
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("x-frame-options") == "DENY"
    assert h.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "permissions-policy" in h


def test_marketing_paths_allow_indexing(client):
    for path in ["/", "/quickstart", "/explore", "/alternatives", "/d/tok1"]:
        r = client.get(path)
        xrt = r.headers.get("x-robots-tag", "")
        assert "noindex" not in xrt, f"{path} should be indexable"


@pytest.mark.parametrize(
    "path,expected_status",
    [
        ("/health", 200),
        ("/settings", 401),
        ("/dashboard", 401),
        ("/inbox", 401),
    ],
)
def test_noindex_on_private_paths(client, path, expected_status):
    r = client.get(path, follow_redirects=False)
    assert "noindex" in r.headers.get("x-robots-tag", "").lower()


def test_security_headers_on_rate_limit_429(tmp_path, monkeypatch):
    """Rate-limit 429 responses must carry security headers too."""
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1")
    conn = init_db(tmp_path / "s.db")
    app = create_app(conn, mount_mcp=False, base_url="http://testserver")
    c = TestClient(app)

    # First request consumes the one-per-minute allowance.
    c.get("/")
    # Second request in the same minute should 429.
    r = c.get("/")
    assert r.status_code == 429
    h = r.headers
    assert h.get("strict-transport-security", "").startswith("max-age=")
    assert "content-security-policy" in h
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("x-frame-options") == "DENY"
