"""Tests for /llms.txt — the agent-readable site map (audit G2)."""

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


def test_llms_txt_returns_200(client):
    r = client.get("/llms.txt")
    assert r.status_code == 200


def test_llms_txt_content_type_is_text_plain(client):
    r = client.get("/llms.txt")
    assert r.headers["content-type"].startswith("text/plain")


def test_llms_txt_starts_with_h1_title(client):
    """The llms.txt convention requires '# Title' as the first line."""
    r = client.get("/llms.txt")
    assert r.text.startswith("# Markland\n")


def test_llms_txt_has_blockquote_description(client):
    """A '> Description' line is the second-line convention."""
    r = client.get("/llms.txt")
    assert "\n> " in r.text


def test_llms_txt_lists_canonical_marketing_urls(client):
    r = client.get("/llms.txt")
    for path in ["/quickstart", "/alternatives", "/about",
                 "/security", "/privacy", "/terms"]:
        assert f"https://markland.test{path}" in r.text


def test_llms_txt_lists_per_competitor_urls(client):
    r = client.get("/llms.txt")
    for slug in ["notion", "google-docs", "github", "hackmd", "markshare"]:
        assert f"https://markland.test/alternatives/{slug}" in r.text


def test_llms_txt_honors_base_url_with_trailing_slash(tmp_path, monkeypatch):
    """Same trailing-slash safety the sitemap has — no double slashes."""
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test/")
    r = TestClient(app).get("/llms.txt")
    assert "//quickstart" not in r.text
    assert "https://markland.test/quickstart" in r.text


def test_llms_txt_honors_forwarded_proto(tmp_path, monkeypatch):
    """Without base_url, x-forwarded-proto is used for scheme (dev/preview deploys)."""
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "p.db")
    app = create_app(conn, mount_mcp=False, base_url="")
    r = TestClient(app).get("/llms.txt", headers={"x-forwarded-proto": "https"})
    assert "https://testserver/quickstart" in r.text
    assert "http://testserver" not in r.text


def test_llms_txt_ignores_host_header_when_base_url_set(tmp_path, monkeypatch):
    """If base_url is configured, Host header cannot poison the llms.txt URLs."""
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "h.db")
    app = create_app(conn, mount_mcp=False, base_url="https://canonical.example")
    r = TestClient(app).get("/llms.txt", headers={"host": "evil.example"})
    assert "https://canonical.example/quickstart" in r.text
    assert "evil.example" not in r.text
