"""Tests for the conditional Umami analytics script tag in base template."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.config import reset_config
from markland.db import init_db
from markland.web.app import create_app


def _make_client(tmp_path) -> TestClient:
    conn = init_db(tmp_path / "t.db")
    app = create_app(
        conn,
        base_url="http://testserver",
        session_secret="test-secret",
    )
    return TestClient(app)


def test_landing_renders_umami_script_when_id_set(monkeypatch, tmp_path):
    monkeypatch.setenv("UMAMI_WEBSITE_ID", "abcd-1234")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    client = _make_client(tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    assert "cloud.umami.is/script.js" in r.text
    assert 'data-website-id="abcd-1234"' in r.text


def test_landing_omits_umami_script_when_id_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("UMAMI_WEBSITE_ID", raising=False)
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    client = _make_client(tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    assert "cloud.umami.is/script.js" not in r.text
    assert "data-website-id" not in r.text


def test_admin_pages_omit_umami_script(monkeypatch, tmp_path):
    monkeypatch.setenv("UMAMI_WEBSITE_ID", "abcd-1234")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    client = _make_client(tmp_path)
    r = client.get("/admin/audit", follow_redirects=False)
    assert "cloud.umami.is/script.js" not in r.text


def test_custom_script_url_overrides_default(monkeypatch, tmp_path):
    monkeypatch.setenv("UMAMI_WEBSITE_ID", "abcd-1234")
    monkeypatch.setenv("UMAMI_SCRIPT_URL", "https://analytics.markland.dev/script.js")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    client = _make_client(tmp_path)
    r = client.get("/")
    assert "https://analytics.markland.dev/script.js" in r.text
    assert "cloud.umami.is" not in r.text
