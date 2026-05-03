"""Tests for magic-link token issuance + verification + email delivery."""

import time
from unittest.mock import MagicMock

import pytest

from markland.service.magic_link import (
    MAGIC_LINK_MAX_AGE_SECONDS,
    InvalidMagicLink,
    _SALT,
    issue_magic_link_token,
    read_magic_link_token,
    safe_return_to,
    send_magic_link,
)


def test_max_age_is_15_minutes():
    assert MAGIC_LINK_MAX_AGE_SECONDS == 15 * 60


def test_issue_and_read_roundtrip():
    token = issue_magic_link_token("alice@example.com", secret="s")
    email = read_magic_link_token(token, secret="s")
    assert email == "alice@example.com"


def test_read_rejects_wrong_secret():
    token = issue_magic_link_token("alice@example.com", secret="s")
    with pytest.raises(InvalidMagicLink):
        read_magic_link_token(token, secret="other")


def test_read_rejects_expired():
    token = issue_magic_link_token("alice@example.com", secret="s", max_age_seconds=1)
    time.sleep(2)
    with pytest.raises(InvalidMagicLink):
        read_magic_link_token(token, secret="s", max_age_seconds=1)


class _FakeDispatcher:
    def __init__(self):
        self.enqueued: list[dict] = []

    def enqueue(self, to, subject, html, text=None, metadata=None):
        self.enqueued.append({
            "to": to, "subject": subject, "html": html,
            "text": text, "metadata": metadata,
        })


def test_send_magic_link_composes_url_and_enqueues(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_BASE_URL", "https://markland.dev")
    from markland.config import reset_config
    reset_config()

    disp = _FakeDispatcher()
    token = send_magic_link(
        dispatcher=disp,
        email="alice@example.com",
        secret="s",
        base_url="https://markland.dev",
    )
    assert isinstance(token, str) and len(token) > 10
    assert len(disp.enqueued) == 1
    sent = disp.enqueued[0]
    assert sent["to"] == "alice@example.com"
    assert "Markland" in sent["subject"]
    assert "https://markland.dev/verify?token=" in sent["html"]
    assert sent["metadata"]["template"] == "magic_link"
    reset_config()


def test_safe_return_to_allows_same_origin_relative_path():
    # Regression: guard was `raw.startswith("/") or raw.startswith("/")`, so
    # every return_to silently collapsed to "/", breaking the invite anon flow.
    assert safe_return_to("/invite/abc123") == "/invite/abc123"


def test_safe_return_to_rejects_protocol_relative_url():
    assert safe_return_to("//evil.com") == "/"
    assert safe_return_to("//evil.com/path") == "/"


def test_safe_return_to_rejects_absolute_url():
    assert safe_return_to("https://evil.com") == "/"
    assert safe_return_to("http://markland.dev/x") == "/"


def test_safe_return_to_defaults_for_empty():
    assert safe_return_to(None) == "/"
    assert safe_return_to("") == "/"


def test_send_magic_link_normalizes_email(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_BASE_URL", "https://markland.dev")
    from markland.config import reset_config
    reset_config()

    disp = _FakeDispatcher()
    send_magic_link(
        dispatcher=disp,
        email="  Alice@Example.COM  ",
        secret="s",
        base_url="https://markland.dev",
    )
    assert disp.enqueued[0]["to"] == "alice@example.com"
    reset_config()


def test_issue_includes_jti_in_payload():
    from itsdangerous import URLSafeTimedSerializer
    token = issue_magic_link_token("alice@example.com", secret="s")
    s = URLSafeTimedSerializer("s", salt=_SALT)
    payload = s.loads(token)
    assert isinstance(payload, dict), f"expected dict payload, got {type(payload)}"
    assert payload["email"] == "alice@example.com"
    assert isinstance(payload["jti"], str)
    assert len(payload["jti"]) >= 16


def test_two_issuances_have_distinct_jtis():
    t1 = issue_magic_link_token("alice@example.com", secret="s")
    t2 = issue_magic_link_token("alice@example.com", secret="s")
    from itsdangerous import URLSafeTimedSerializer
    s = URLSafeTimedSerializer("s", salt=_SALT)
    p1 = s.loads(t1)
    p2 = s.loads(t2)
    assert p1["jti"] != p2["jti"]
    assert t1 != t2
