"""Unit tests for service/device_flow.py."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from markland.db import init_db
from markland.service import device_flow


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "t.db")


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


def test_start_inserts_pending_row(conn):
    result = device_flow.start(conn)
    row = conn.execute(
        "SELECT device_code, user_code, status, user_id, invite_token, expires_at "
        "FROM device_authorizations WHERE device_code = ?",
        (result.device_code,),
    ).fetchone()
    assert row is not None
    assert row[2] == "pending"
    assert row[3] is None
    assert row[4] is None
    # expires_at is ~10 minutes out.
    expires = datetime.fromisoformat(row[5].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    assert timedelta(minutes=9) < (expires - now) <= timedelta(minutes=10, seconds=2)


def test_start_returns_formatted_user_code_and_poll_interval(conn):
    result = device_flow.start(conn, base_url="https://markland.dev")
    assert "-" in result.user_code
    assert result.poll_interval == 5
    assert result.expires_in == 600
    assert result.verification_url == "https://markland.dev/device"


def test_start_records_invite_token(conn):
    result = device_flow.start(conn, invite_token="inv_abc")
    row = conn.execute(
        "SELECT invite_token FROM device_authorizations WHERE device_code = ?",
        (result.device_code,),
    ).fetchone()
    assert row[0] == "inv_abc"


def test_start_device_code_is_high_entropy(conn):
    codes = {device_flow.start(conn).device_code for _ in range(20)}
    assert len(codes) == 20
    # ≥40 bytes of entropy → urlsafe base64 ≥ 54 chars.
    for c in codes:
        assert len(c) >= 54


# ---------------------------------------------------------------------------
# poll
# ---------------------------------------------------------------------------


def _authorize_directly(conn, device_code, user_id="usr_alice", invite_token=None):
    """Helper: simulate the browser authorize step by flipping status directly."""
    conn.execute(
        "UPDATE device_authorizations SET status='authorized', user_id=?, "
        "authorized_at=?, invite_token=COALESCE(?, invite_token) WHERE device_code=?",
        (user_id, device_flow._iso(device_flow._utcnow()), invite_token, device_code),
    )
    conn.commit()


def test_poll_not_found(conn):
    assert device_flow.poll(conn, "no-such-device-code") == {"status": "not_found"}


def test_poll_pending_updates_polled_last(conn):
    start = device_flow.start(conn)
    r = device_flow.poll(conn, start.device_code)
    assert r == {"status": "pending"}
    row = conn.execute(
        "SELECT polled_last FROM device_authorizations WHERE device_code=?",
        (start.device_code,),
    ).fetchone()
    assert row[0] is not None


def test_poll_slow_down_when_recent(conn):
    start = device_flow.start(conn)
    first = device_flow.poll(conn, start.device_code)
    assert first == {"status": "pending"}
    second = device_flow.poll(conn, start.device_code)
    assert second == {"status": "slow_down"}


def test_poll_slow_down_does_not_move_polled_last(conn):
    start = device_flow.start(conn)
    device_flow.poll(conn, start.device_code)
    polled_after_first = conn.execute(
        "SELECT polled_last FROM device_authorizations WHERE device_code=?",
        (start.device_code,),
    ).fetchone()[0]
    device_flow.poll(conn, start.device_code)  # slow_down
    polled_after_slow = conn.execute(
        "SELECT polled_last FROM device_authorizations WHERE device_code=?",
        (start.device_code,),
    ).fetchone()[0]
    assert polled_after_first == polled_after_slow


def test_poll_expired_row_transitions_status(conn):
    start = device_flow.start(conn)
    # Reach in and backdate expires_at.
    conn.execute(
        "UPDATE device_authorizations SET expires_at=? WHERE device_code=?",
        ("2000-01-01T00:00:00Z", start.device_code),
    )
    conn.commit()
    r = device_flow.poll(conn, start.device_code)
    assert r == {"status": "expired"}
    status = conn.execute(
        "SELECT status FROM device_authorizations WHERE device_code=?",
        (start.device_code,),
    ).fetchone()[0]
    assert status == "expired"


def test_poll_authorized_mints_token_and_returns_plaintext(conn):
    start = device_flow.start(conn)
    _authorize_directly(conn, start.device_code, user_id="usr_alice")

    with patch("markland.service.device_flow.create_user_token") as mint:
        mint.return_value = ("tok_abc", "mk_usr_plaintext_xyz")
        r = device_flow.poll(conn, start.device_code)

    assert r == {"status": "authorized", "access_token": "mk_usr_plaintext_xyz"}
    mint.assert_called_once()
    args, kwargs = mint.call_args
    assert kwargs.get("user_id") == "usr_alice" or (len(args) > 1 and args[1] == "usr_alice")
    # consumed_at is now stamped.
    consumed = conn.execute(
        "SELECT consumed_at FROM device_authorizations WHERE device_code=?",
        (start.device_code,),
    ).fetchone()[0]
    assert consumed is not None


def test_poll_single_use_returns_expired_after_consumption(conn):
    start = device_flow.start(conn)
    _authorize_directly(conn, start.device_code, user_id="usr_alice")
    with patch("markland.service.device_flow.create_user_token",
               return_value=("tok_abc", "mk_usr_plaintext_xyz")):
        first = device_flow.poll(conn, start.device_code)
    assert first["status"] == "authorized"

    # Wait past slow_down window, then poll again.
    time.sleep(device_flow.SLOW_DOWN_WINDOW_SECONDS + 1)
    second = device_flow.poll(conn, start.device_code)
    assert second == {"status": "expired"}


# ---------------------------------------------------------------------------
# authorize
# ---------------------------------------------------------------------------


def test_authorize_by_user_code_flips_status(conn):
    start = device_flow.start(conn)
    raw_user_code = start.user_code.replace("-", "")
    r = device_flow.authorize(conn, raw_user_code, user_id="usr_alice")
    assert r.ok
    assert r.device_code == start.device_code
    assert r.invite_accepted is False
    status, user_id = conn.execute(
        "SELECT status, user_id FROM device_authorizations WHERE device_code=?",
        (start.device_code,),
    ).fetchone()
    assert status == "authorized"
    assert user_id == "usr_alice"


def test_authorize_accepts_hyphenated_input(conn):
    start = device_flow.start(conn)
    r = device_flow.authorize(conn, start.user_code, user_id="usr_alice")
    assert r.ok


def test_authorize_rejects_unknown_code(conn):
    r = device_flow.authorize(conn, "ZZZZZZZZ", user_id="usr_alice")
    assert not r.ok
    assert r.reason == "not_found"


def test_authorize_rejects_expired_code(conn):
    start = device_flow.start(conn)
    conn.execute(
        "UPDATE device_authorizations SET expires_at=? WHERE device_code=?",
        ("2000-01-01T00:00:00Z", start.device_code),
    )
    conn.commit()
    raw = start.user_code.replace("-", "")
    r = device_flow.authorize(conn, raw, user_id="usr_alice")
    assert not r.ok
    assert r.reason == "expired"


def test_authorize_rejects_already_authorized_code(conn):
    start = device_flow.start(conn)
    raw = start.user_code.replace("-", "")
    device_flow.authorize(conn, raw, user_id="usr_alice")
    r = device_flow.authorize(conn, raw, user_id="usr_bob")
    assert not r.ok
    assert r.reason == "already_authorized"


def test_authorize_with_invite_token_accepts_invite(conn):
    """When accept_invite returns a truthy Grant, invite_accepted is True.

    Canonical `service.invites.accept_invite` returns a Grant on success
    and None when the invite can't be applied. Unit test mocks it returning
    a sentinel Grant-like object to represent success.
    """
    start = device_flow.start(conn, invite_token="inv_abc")
    raw = start.user_code.replace("-", "")
    with patch("markland.service.device_flow.accept_invite") as accept:
        # Truthy return → treated as success.
        accept.return_value = object()
        r = device_flow.authorize(conn, raw, user_id="usr_alice")
    assert r.ok
    assert r.invite_accepted is True
    assert r.invite_error is None
    accept.assert_called_once()


def test_authorize_invite_none_return_marks_error_but_still_ok(conn):
    """A None return from accept_invite means the invite was unusable;
    authorization still completes but invite_accepted stays False."""
    start = device_flow.start(conn, invite_token="inv_bad")
    raw = start.user_code.replace("-", "")
    with patch("markland.service.device_flow.accept_invite", return_value=None):
        r = device_flow.authorize(conn, raw, user_id="usr_alice")
    assert r.ok
    assert r.invite_accepted is False
    assert r.invite_error is not None


def test_authorize_still_ok_when_invite_accept_raises(conn):
    start = device_flow.start(conn, invite_token="inv_expired")
    raw = start.user_code.replace("-", "")
    with patch(
        "markland.service.device_flow.accept_invite",
        side_effect=RuntimeError("invite already used"),
    ):
        r = device_flow.authorize(conn, raw, user_id="usr_alice")
    assert r.ok
    assert r.invite_accepted is False
    assert r.invite_error == "invite already used"
    # Authorization still landed.
    status = conn.execute(
        "SELECT status FROM device_authorizations WHERE device_code=?",
        (start.device_code,),
    ).fetchone()[0]
    assert status == "authorized"
