"""Tests for itsdangerous-backed session cookies."""

import time

import pytest

from markland.db import init_db
from markland.service.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    InvalidSession,
    bump_session_epoch,
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


# ---------------------------------------------------------------------------
# session_epoch / revocation (markland-bul)
# ---------------------------------------------------------------------------


def _seed_user(conn, user_id="usr_t", email="a@b", epoch=None):
    if epoch is None:
        conn.execute(
            "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
            (user_id, email, "2026-01-01T00:00:00+00:00"),
        )
    else:
        conn.execute(
            "INSERT INTO users (id, email, created_at, session_epoch) "
            "VALUES (?, ?, ?, ?)",
            (user_id, email, "2026-01-01T00:00:00+00:00", epoch),
        )
    conn.commit()


def test_issue_session_embeds_epoch_zero_when_conn_omitted():
    """Backwards-compat: tests that don't seed a users table still get a
    valid cookie with epoch=0. The conn=None branch skips epoch lookup."""
    cookie = issue_session("usr_test", secret="s")
    payload = read_session(cookie, secret="s")
    assert payload.get("epoch") == 0


def test_issue_session_embeds_user_current_epoch_when_conn_provided(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_user(conn, epoch=7)
    cookie = issue_session("usr_t", secret="s", conn=conn)
    payload = read_session(cookie, secret="s")
    assert payload["epoch"] == 7


def test_issue_session_embeds_zero_for_unknown_user(tmp_path):
    """Tests that issue sessions for synthetic ids (no users row) keep
    working — issuance treats missing-user as epoch=0."""
    conn = init_db(tmp_path / "t.db")
    cookie = issue_session("usr_synthetic", secret="s", conn=conn)
    payload = read_session(cookie, secret="s")
    assert payload["epoch"] == 0


def test_read_session_rejects_cookie_with_stale_epoch(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_user(conn)
    cookie = issue_session("usr_t", secret="s", conn=conn)
    bump_session_epoch(conn, user_id="usr_t")
    with pytest.raises(InvalidSession, match="revoked"):
        read_session(cookie, secret="s", conn=conn)


def test_read_session_accepts_cookie_with_current_epoch(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_user(conn, epoch=5)
    cookie = issue_session("usr_t", secret="s", conn=conn)
    payload = read_session(cookie, secret="s", conn=conn)
    assert payload["user_id"] == "usr_t"
    assert payload["epoch"] == 5


def test_read_session_rejects_cookie_for_deleted_user(tmp_path):
    """Cookie references a user_id no longer in the DB — revoke."""
    conn = init_db(tmp_path / "t.db")
    _seed_user(conn)
    cookie = issue_session("usr_t", secret="s", conn=conn)
    conn.execute("DELETE FROM users WHERE id = ?", ("usr_t",))
    conn.commit()
    with pytest.raises(InvalidSession, match="user not found"):
        read_session(cookie, secret="s", conn=conn)


def test_read_session_without_conn_skips_revocation_check():
    """Backwards-compat: callers that don't pass conn get the old behaviour."""
    cookie = issue_session("usr_t", secret="s")
    payload = read_session(cookie, secret="s")
    assert payload["user_id"] == "usr_t"


def test_bump_session_epoch_returns_new_value(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_user(conn)
    assert bump_session_epoch(conn, user_id="usr_t") == 1
    assert bump_session_epoch(conn, user_id="usr_t") == 2
    row = conn.execute(
        "SELECT session_epoch FROM users WHERE id = ?", ("usr_t",)
    ).fetchone()
    assert row[0] == 2


def test_bump_session_epoch_unknown_user_raises(tmp_path):
    conn = init_db(tmp_path / "t.db")
    with pytest.raises(InvalidSession, match="user not found"):
        bump_session_epoch(conn, user_id="usr_missing")
