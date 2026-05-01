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


def _render_base(path: str, umami_id: str = "abcd-1234") -> str:
    """Render base.html directly with a mock request, bypassing routing.

    Goes through the Jinja env so the path-exclusion conditional in
    base.html actually executes — unlike calling /admin/* via TestClient,
    where the admin routes either return JSON or use standalone templates
    that don't extend base.html.
    """
    from types import SimpleNamespace

    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader("src/markland/web/templates"),
        autoescape=select_autoescape(["html"]),
    )
    env.globals["umami_website_id"] = umami_id
    env.globals["umami_script_url"] = "https://cloud.umami.is/script.js"
    env.globals["seo"] = {"title": "t", "description": "d", "canonical": "/"}
    env.globals["signed_in_user"] = None
    request = SimpleNamespace(url=SimpleNamespace(path=path))
    tpl = env.get_template("base.html")
    return tpl.render(request=request)


@pytest.mark.parametrize("path", ["/admin", "/admin/", "/admin/audit", "/admin/metrics"])
def test_base_template_omits_umami_on_admin_paths(path):
    html = _render_base(path)
    assert "cloud.umami.is/script.js" not in html
    assert "data-website-id" not in html


@pytest.mark.parametrize("path", ["/", "/explore", "/admin-onboarding", "/security"])
def test_base_template_renders_umami_on_non_admin_paths(path):
    html = _render_base(path)
    assert "cloud.umami.is/script.js" in html
    assert 'data-website-id="abcd-1234"' in html


def test_csp_includes_umami_origin_when_id_set(monkeypatch, tmp_path):
    monkeypatch.setenv("UMAMI_WEBSITE_ID", "abcd-1234")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    client = _make_client(tmp_path)
    r = client.get("/")
    csp = r.headers.get("content-security-policy", "")
    # Umami Cloud serves script.js from cloud.umami.is but routes the beacon
    # to api-gateway.umami.dev — different host. CSP must allow both, plus
    # cover any future umami.is/umami.dev API host moves.
    assert "https://cloud.umami.is" in csp
    assert "script-src 'self' 'unsafe-inline' https://cloud.umami.is" in csp
    # connect-src must allow both the umami.is and umami.dev families so the
    # script can POST to the API regardless of which gateway umami uses.
    assert "https://*.umami.is" in csp.split("connect-src", 1)[1]
    assert "https://*.umami.dev" in csp.split("connect-src", 1)[1]


def test_csp_omits_umami_origin_when_id_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("UMAMI_WEBSITE_ID", raising=False)
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    client = _make_client(tmp_path)
    r = client.get("/")
    csp = r.headers.get("content-security-policy", "")
    assert "cloud.umami.is" not in csp
    assert "script-src 'self' 'unsafe-inline';" in csp
    assert "connect-src 'self';" in csp


def test_csp_uses_custom_script_url_origin(monkeypatch, tmp_path):
    monkeypatch.setenv("UMAMI_WEBSITE_ID", "abcd-1234")
    monkeypatch.setenv("UMAMI_SCRIPT_URL", "https://analytics.markland.dev/script.js")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    client = _make_client(tmp_path)
    r = client.get("/")
    csp = r.headers.get("content-security-policy", "")
    assert "https://analytics.markland.dev" in csp
    assert "cloud.umami.is" not in csp


def test_custom_script_url_overrides_default(monkeypatch, tmp_path):
    monkeypatch.setenv("UMAMI_WEBSITE_ID", "abcd-1234")
    monkeypatch.setenv("UMAMI_SCRIPT_URL", "https://analytics.markland.dev/script.js")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    client = _make_client(tmp_path)
    r = client.get("/")
    assert "https://analytics.markland.dev/script.js" in r.text
    assert "cloud.umami.is" not in r.text
