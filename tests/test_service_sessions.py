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


def test_make_csrf_token_refuses_empty_secret():
    """P1-C / markland-bfk: signing with an empty secret would accept a
    placeholder fallback and let attackers who know the placeholder forge
    CSRF tokens. Refuse with ValueError instead."""
    from markland.service.sessions import make_csrf_token

    with pytest.raises(ValueError):
        make_csrf_token("usr_abc", secret="")


def test_verify_csrf_token_refuses_empty_secret():
    """P1-C / markland-bfk: verification with an empty secret must also
    raise — silently treating an empty secret as 'placeholder' would let
    a forged token pass verification on a misconfigured deployment."""
    from markland.service.sessions import verify_csrf_token

    with pytest.raises(ValueError):
        verify_csrf_token("any-token", "usr_abc", secret="")


def test_csrf_token_roundtrip():
    """Happy path: a token signed with secret S verifies with secret S."""
    from markland.service.sessions import make_csrf_token, verify_csrf_token

    token = make_csrf_token("usr_abc", secret="topsecret")
    assert verify_csrf_token(token, "usr_abc", secret="topsecret") is True
    # Wrong user_id must fail.
    assert verify_csrf_token(token, "usr_other", secret="topsecret") is False
