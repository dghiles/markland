"""Unit tests for the signed flash cookie used to surface a freshly-minted
agent token without leaking it into the URL."""

import time

import pytest

from markland.service.agent_token_flash import (
    AGENT_TOKEN_FLASH_COOKIE_NAME,
    AGENT_TOKEN_FLASH_MAX_AGE_SECONDS,
    InvalidAgentTokenFlash,
    issue_agent_token_flash,
    read_agent_token_flash,
)


SECRET = "test-secret"


def test_cookie_name_constant():
    assert AGENT_TOKEN_FLASH_COOKIE_NAME == "markland_agent_token_flash"


def test_max_age_is_five_minutes():
    assert AGENT_TOKEN_FLASH_MAX_AGE_SECONDS == 5 * 60


def test_roundtrip_returns_plaintext():
    sealed = issue_agent_token_flash(secret=SECRET, plaintext="mk_agt_abc123")
    assert sealed != "mk_agt_abc123"
    assert read_agent_token_flash(sealed, secret=SECRET) == "mk_agt_abc123"


def test_empty_token_is_rejected_on_issue():
    with pytest.raises(ValueError):
        issue_agent_token_flash(secret=SECRET, plaintext="")


def test_empty_secret_is_rejected_on_issue():
    with pytest.raises(ValueError):
        issue_agent_token_flash(secret="", plaintext="mk_agt_abc")


def test_empty_cookie_value_raises_invalid():
    with pytest.raises(InvalidAgentTokenFlash):
        read_agent_token_flash("", secret=SECRET)


def test_tampered_signature_raises_invalid():
    sealed = issue_agent_token_flash(secret=SECRET, plaintext="mk_agt_abc123")
    # Flip the FIRST char of the signature segment, not the last. itsdangerous
    # decodes the signature before HMAC compare, and base64 alignment means
    # the *last* char of a 20-byte HMAC-SHA1 signature carries only 4 bits of
    # actual data — so ~6% of last-char flips ('A'↔'B', etc.) decode to the
    # same bytes and validate, producing a flaky test. The first signature
    # char carries a full 6 bits, so any flip changes the decoded signature.
    head, sig = sealed.rsplit(".", 1)
    tampered_sig = ("A" if sig[0] != "A" else "B") + sig[1:]
    with pytest.raises(InvalidAgentTokenFlash):
        read_agent_token_flash(f"{head}.{tampered_sig}", secret=SECRET)


def test_wrong_secret_raises_invalid():
    sealed = issue_agent_token_flash(secret=SECRET, plaintext="mk_agt_abc123")
    with pytest.raises(InvalidAgentTokenFlash):
        read_agent_token_flash(sealed, secret="other-secret")


def test_expired_cookie_raises_invalid():
    sealed = issue_agent_token_flash(secret=SECRET, plaintext="mk_agt_abc123")
    time.sleep(1)
    with pytest.raises(InvalidAgentTokenFlash):
        read_agent_token_flash(sealed, secret=SECRET, max_age_seconds=0)
