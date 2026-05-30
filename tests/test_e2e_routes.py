"""Tests for the e2e smoke endpoint at /api/test/mint-magic-link."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.magic_link import read_magic_link_token
from markland.web.app import create_app


def _make_client(tmp_path, monkeypatch, *, e2e_secret: str | None):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    if e2e_secret is None:
        monkeypatch.delenv("MARKLAND_E2E_SECRET", raising=False)
    else:
        monkeypatch.setenv("MARKLAND_E2E_SECRET", e2e_secret)
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "t.db")
    email_client = MagicMock()
    email_client.send.return_value = None
    app = create_app(
        conn,
        mount_mcp=False,
        base_url="http://testserver",
        session_secret="test-secret",
        email_client=email_client,
    )
    return TestClient(app), conn


def test_mint_endpoint_404s_when_secret_not_configured(tmp_path, monkeypatch):
    """No MARKLAND_E2E_SECRET → endpoint is not mounted at all."""
    client, _ = _make_client(tmp_path, monkeypatch, e2e_secret=None)
    r = client.post(
        "/api/test/mint-magic-link?email=smoke-a@markland.test",
        headers={"X-Markland-E2E-Secret": "any-value"},
    )
    assert r.status_code == 404


def test_mint_endpoint_404s_on_wrong_secret(tmp_path, monkeypatch):
    """Endpoint mounted, wrong secret → 404 (not 403) for fingerprint denial."""
    client, _ = _make_client(tmp_path, monkeypatch, e2e_secret="real-secret")
    r = client.post(
        "/api/test/mint-magic-link?email=smoke-a@markland.test",
        headers={"X-Markland-E2E-Secret": "wrong-secret"},
    )
    assert r.status_code == 404


def test_mint_endpoint_404s_on_missing_secret_header(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch, e2e_secret="real-secret")
    r = client.post("/api/test/mint-magic-link?email=smoke-a@markland.test")
    assert r.status_code == 404


def test_mint_endpoint_400s_on_non_allowlisted_email(tmp_path, monkeypatch):
    """Even with the right secret, real-user emails are rejected."""
    client, _ = _make_client(tmp_path, monkeypatch, e2e_secret="real-secret")
    r = client.post(
        "/api/test/mint-magic-link?email=victim@gmail.com",
        headers={"X-Markland-E2E-Secret": "real-secret"},
    )
    assert r.status_code == 400
    assert "markland.test" in r.json()["detail"]


def test_mint_endpoint_returns_usable_verify_url(tmp_path, monkeypatch):
    """Happy path: returned URL contains a token that decodes to the
    requested email under the prod session secret."""
    client, _ = _make_client(tmp_path, monkeypatch, e2e_secret="real-secret")
    r = client.post(
        "/api/test/mint-magic-link?email=smoke-a@markland.test",
        headers={"X-Markland-E2E-Secret": "real-secret"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "smoke-a@markland.test"
    assert body["verify_url"].startswith("http://testserver/verify?token=")
    token = body["verify_url"].split("token=", 1)[1]
    decoded_email = read_magic_link_token(token, secret="test-secret")
    assert decoded_email == "smoke-a@markland.test"


def test_mint_endpoint_normalizes_email(tmp_path, monkeypatch):
    """Mixed-case / whitespace gets normalized."""
    client, _ = _make_client(tmp_path, monkeypatch, e2e_secret="real-secret")
    r = client.post(
        "/api/test/mint-magic-link?email=  SMOKE-B@MARKLAND.TEST  ",
        headers={"X-Markland-E2E-Secret": "real-secret"},
    )
    assert r.status_code == 200
    assert r.json()["email"] == "smoke-b@markland.test"
