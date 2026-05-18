"""Signed pending-intent cookies for the logged-out save-to-account resume flow."""

import time

import pytest

from markland.service.pending_intent import (
    PENDING_INTENT_COOKIE_NAME,
    PENDING_INTENT_MAX_AGE_SECONDS,
    InvalidPendingIntent,
    PendingIntent,
    issue_pending_intent,
    read_pending_intent,
)


SECRET = "test-secret"


def test_roundtrip_signed_payload():
    token = issue_pending_intent(
        secret=SECRET,
        action="fork",
        share_token="abc123",
    )
    intent = read_pending_intent(token, secret=SECRET)
    assert intent == PendingIntent(action="fork", share_token="abc123")


def test_read_rejects_tampered_token():
    token = issue_pending_intent(
        secret=SECRET, action="bookmark", share_token="abc123"
    )
    # Mutate a middle char of the signature segment. The last base64url char of
    # an HMAC-SHA1 signature only encodes 4 significant bits (the other 2 are
    # padding), so flipping it lands in the same 4-char equivalence class ~1/16
    # of the time and the token still verifies — making any token[-1] tamper flaky.
    sig_start = token.rfind(".") + 1
    mid = sig_start + (len(token) - sig_start) // 2
    tampered = token[:mid] + ("A" if token[mid] != "A" else "B") + token[mid + 1 :]
    with pytest.raises(InvalidPendingIntent):
        read_pending_intent(tampered, secret=SECRET)


def test_read_rejects_wrong_secret():
    token = issue_pending_intent(secret=SECRET, action="fork", share_token="x")
    with pytest.raises(InvalidPendingIntent):
        read_pending_intent(token, secret="other-secret")


def test_read_rejects_unknown_action():
    with pytest.raises(ValueError):
        issue_pending_intent(secret=SECRET, action="explode", share_token="x")


def test_cookie_name_and_max_age_constants():
    assert PENDING_INTENT_COOKIE_NAME == "markland_pending_intent"
    assert PENDING_INTENT_MAX_AGE_SECONDS == 30 * 60
