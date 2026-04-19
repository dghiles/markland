"""Tests for itsdangerous-backed session cookies."""

import time

import pytest

from markland.service.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    InvalidSession,
    issue_session,
    read_session,
)


def test_cookie_constants():
    assert SESSION_COOKIE_NAME == "mk_session"
    assert SESSION_MAX_AGE_SECONDS == 60 * 60 * 24 * 30  # 30 days


def test_issue_and_read_roundtrip():
    token = issue_session("usr_abc", secret="topsecret")
    payload = read_session(token, secret="topsecret")
    assert payload["user_id"] == "usr_abc"
    assert "exp" in payload


def test_read_rejects_wrong_secret():
    token = issue_session("usr_abc", secret="topsecret")
    with pytest.raises(InvalidSession):
        read_session(token, secret="wrong")


def test_read_rejects_tampered_token():
    token = issue_session("usr_abc", secret="topsecret")
    tampered = token[:-4] + "XXXX" if len(token) > 4 else "bad"
    with pytest.raises(InvalidSession):
        read_session(tampered, secret="topsecret")


def test_read_rejects_expired(monkeypatch):
    token = issue_session("usr_abc", secret="topsecret", max_age_seconds=1)
    time.sleep(2)
    with pytest.raises(InvalidSession):
        read_session(token, secret="topsecret", max_age_seconds=1)


def test_empty_secret_refuses_to_issue():
    with pytest.raises(ValueError):
        issue_session("usr_abc", secret="")
