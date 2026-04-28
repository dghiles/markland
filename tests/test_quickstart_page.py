"""`/quickstart` renders 200 and contains all five onboarding steps."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "q.db")
    # Empty base_url forces _public_host's request-URL fallback branch so
    # test_quickstart_templates_setup_host asserts http://testserver/setup.
    app = create_app(conn, mount_mcp=False, base_url="")
    return TestClient(app)


def test_quickstart_renders_200(client):
    r = client.get("/quickstart")
    assert r.status_code == 200


def test_quickstart_mentions_all_five_steps(client):
    r = client.get("/quickstart")
    body = r.text.lower()
    assert "sign up" in body
    assert "/setup" in body
    assert "markland_publish" in body
    assert "markland_grant" in body
    assert "view the doc" in body or "view your doc" in body


def test_landing_links_to_quickstart(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "/quickstart" in r.text


def test_quickstart_uses_base_layout(client):
    r = client.get("/quickstart")
    assert 'class="site-header"' in r.text
    assert 'class="site-footer"' in r.text


def test_quickstart_templates_setup_host(client):
    r = client.get("/quickstart")
    # Quickstart must NOT teach the broken `claude mcp add <url>` form —
    # claude mcp add treats a bare URL as a stdio command and fails. The
    # runbook at /setup is consumed by Claude Code as a chat directive.
    assert "claude mcp add markland http://testserver/setup" not in r.text
    # Must still show the canonical host so we don't ship a stale fly.dev URL.
    assert "http://testserver/setup" in r.text
    assert "markland.dev/setup" not in r.text
    # Must frame it as a Claude Code chat instruction, not a terminal command.
    assert "Claude Code" in r.text


def test_quickstart_has_h2_step_headings(client):
    r = client.get("/quickstart")
    text = r.text
    assert text.count("<h2") >= 5


def test_quickstart_content_length_not_thin(client):
    import re as _re
    r = client.get("/quickstart")
    visible = _re.sub(r"<[^>]+>", " ", r.text)
    visible = _re.sub(r"\s+", " ", visible)
    word_count = len(visible.split())
    assert word_count >= 600, f"quickstart is still thin: {word_count} words"


def test_quickstart_has_meta_description(client):
    r = client.get("/quickstart")
    assert '<meta name="description"' in r.text
    assert "MCP" in r.text
