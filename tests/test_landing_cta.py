"""Landing page hero CTA — must send users into the magic-link flow,
not into a pre-launch waitlist. Pins the conversion fix from
docs/plans/2026-05-29-pre-launch-cleanup.md."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app

SECRET = "test-session-secret"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "test.db")
    app = create_app(
        conn, mount_mcp=False,
        base_url="https://markland.dev",
        session_secret=SECRET,
    )
    with TestClient(app, base_url="http://testserver") as c:
        yield c


def test_landing_hero_primary_cta_routes_to_login(client):
    """The big primary CTA on / should hand the visitor straight into
    magic-link sign-in, not into /api/waitlist."""
    r = client.get("/")
    assert r.status_code == 200
    text = r.text
    # The waitlist form must NOT be the primary CTA in the hero block.
    # We allow waitlist as a secondary/footer affordance for users who
    # really want it — but not as the giant button people land on.
    hero_section = text.split("<section class=\"section\"", 1)[0]
    assert 'action="/api/waitlist"' not in hero_section, (
        "hero still gates conversion on /api/waitlist — see "
        "docs/plans/2026-05-29-pre-launch-cleanup.md Track B"
    )
    # The new primary path: /login (magic link)
    assert "/login" in hero_section


def test_landing_no_pre_launch_messaging(client):
    """Site has been live for 30+ days. 'Pre-launch · we'll email when
    it's ready' contradicts the actual state of the product."""
    r = client.get("/")
    assert "Pre-launch" not in r.text
    assert "we'll email when it's ready" not in r.text
