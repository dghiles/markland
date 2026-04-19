"""Stub settings page so the footer 'Manage notifications' link resolves."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn)
    with TestClient(app) as c:
        yield c


def test_settings_notifications_returns_coming_soon(client):
    r = client.get("/settings/notifications")
    assert r.status_code == 200
    assert "coming soon" in r.text.lower()
    assert "notification" in r.text.lower()


def test_settings_notifications_is_html(client):
    r = client.get("/settings/notifications")
    assert r.headers["content-type"].startswith("text/html")
