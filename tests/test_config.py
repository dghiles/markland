"""Tests for config loading."""

import os

from markland.config import get_config, reset_config


def test_admin_token_loaded_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKLAND_ADMIN_TOKEN", "mk_admin_test_xyz")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    cfg = get_config()
    assert cfg.admin_token == "mk_admin_test_xyz"


def test_admin_token_empty_when_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("MARKLAND_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    cfg = get_config()
    assert cfg.admin_token == ""


def test_sentry_dsn_and_resend_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTRY_DSN", "https://fake@sentry.io/1")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "test@markland.dev")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    cfg = get_config()
    assert cfg.sentry_dsn == "https://fake@sentry.io/1"
    assert cfg.resend_api_key == "re_test"
    assert cfg.resend_from_email == "test@markland.dev"


def test_session_secret_loaded_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", "s3cret_test_value")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    cfg = get_config()
    assert cfg.session_secret == "s3cret_test_value"


def test_session_secret_empty_when_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("MARKLAND_SESSION_SECRET", raising=False)
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    cfg = get_config()
    assert cfg.session_secret == ""


def test_config_reads_umami_website_id(monkeypatch, tmp_path):
    monkeypatch.setenv("UMAMI_WEBSITE_ID", "abcd-1234")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    cfg = get_config()
    assert cfg.umami_website_id == "abcd-1234"


def test_config_umami_website_id_defaults_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("UMAMI_WEBSITE_ID", raising=False)
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    cfg = get_config()
    assert cfg.umami_website_id == ""


def test_config_umami_script_url_default(monkeypatch, tmp_path):
    monkeypatch.delenv("UMAMI_SCRIPT_URL", raising=False)
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    cfg = get_config()
    assert cfg.umami_script_url == "https://cloud.umami.is/script.js"
