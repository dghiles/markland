"""Tests for Task 10 — self-host + subset fonts.

Confirms marketing pages no longer depend on fonts.googleapis.com /
fonts.gstatic.com, that the in-app font asset route serves woff2 with
the right cache headers, and that CSP no longer whitelists Google.
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


@pytest.mark.parametrize(
    "path",
    ["/", "/quickstart", "/explore", "/alternatives", "/about",
     "/security", "/privacy", "/terms", "/alternatives/notion"],
)
def test_marketing_pages_self_host_fonts(client, path):
    r = client.get(path)
    assert "fonts.googleapis.com" not in r.text, (
        f"{path} still references Google Fonts CDN"
    )
    assert "fonts.gstatic.com" not in r.text, (
        f"{path} still references Google Fonts asset host"
    )
    assert "/assets/fonts/figtree-var.woff2" in r.text, (
        f"{path} is missing the self-hosted Figtree preload"
    )


def test_font_asset_served_with_immutable_cache(client):
    r = client.get("/assets/fonts/figtree-var.woff2")
    assert r.status_code == 200
    assert r.headers["content-type"] == "font/woff2"
    assert "immutable" in r.headers["cache-control"]
    assert "max-age=31536000" in r.headers["cache-control"]
    assert len(r.content) > 1000  # not an empty stub


def test_unknown_font_404s(client):
    assert client.get("/assets/fonts/nope.woff2").status_code == 404


def test_path_traversal_blocked(client):
    # Path-param routing means "../foo" never matches the {name} segment,
    # but assert the safe-name allow-list rejects it explicitly anyway.
    r = client.get("/assets/fonts/..%2F..%2Fapp.py")
    assert r.status_code == 404


def test_csp_no_longer_whitelists_google_fonts(client):
    r = client.get("/")
    csp = r.headers.get("content-security-policy", "")
    assert "fonts.googleapis.com" not in csp
    assert "fonts.gstatic.com" not in csp
    assert "font-src 'self'" in csp


def test_document_template_self_hosts_newsreader(client, tmp_path, monkeypatch):
    """The doc viewer page also needs Newsreader self-hosted."""
    from markland.db import init_db, insert_document

    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t2.db")
    insert_document(conn, "d1", "Title", "Body", "tok", is_public=True)
    app = create_app(conn, mount_mcp=False, base_url="http://testserver")
    c = TestClient(app)
    r = c.get("/d/tok")
    assert r.status_code == 200
    assert "fonts.googleapis.com" not in r.text
    assert "/assets/fonts/newsreader-roman-var.woff2" in r.text


@pytest.mark.parametrize("family", ["Figtree", "DM Mono"])
def test_landing_declares_font_face(client, family):
    """Locks in that base.html still declares @font-face for each family.
    Catches regressions where a future refactor drops a face block but
    leaves the absence-of-Google-Fonts checks passing."""
    r = client.get("/")
    assert f"font-family: '{family}'" in r.text


@pytest.mark.parametrize("family", ["Figtree", "DM Mono", "Newsreader"])
def test_document_declares_font_face(family, tmp_path, monkeypatch):
    from markland.db import init_db, insert_document

    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t3.db")
    insert_document(conn, "d2", "T", "B", "tok2", is_public=True)
    app = create_app(conn, mount_mcp=False, base_url="http://testserver")
    c = TestClient(app)
    r = c.get("/d/tok2")
    assert f"font-family: '{family}'" in r.text
