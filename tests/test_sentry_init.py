"""Sentry init is conditional on SENTRY_DSN being set."""

from unittest.mock import patch

import pytest


def test_sentry_not_initialized_when_dsn_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", "t")

    from markland.config import reset_config
    reset_config()

    # Importing run_app has side effects; patch sentry_sdk.init first.
    with patch("sentry_sdk.init") as init_mock:
        # Reimport run_app to trigger the module-level init branch.
        import importlib
        import markland.run_app
        importlib.reload(markland.run_app)

    init_mock.assert_not_called()


def test_sentry_initialized_when_dsn_set(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTRY_DSN", "https://fake@sentry.io/1")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", "t")

    from markland.config import reset_config
    reset_config()

    with patch("sentry_sdk.init") as init_mock:
        import importlib
        import markland.run_app
        importlib.reload(markland.run_app)

    init_mock.assert_called_once()
    kwargs = init_mock.call_args.kwargs
    assert kwargs["dsn"] == "https://fake@sentry.io/1"
    assert kwargs.get("send_default_pii") is False
    # Magic-link / CSRF / share-token redaction must be wired up.
    from markland.log_scrubbing import scrub_sentry_event
    assert kwargs.get("before_send") is scrub_sentry_event
