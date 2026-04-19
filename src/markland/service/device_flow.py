"""Device-authorization flow (Markland §4.1).

Public surface:
    USER_CODE_ALPHABET
    generate_user_code() -> str       # 8 chars from reduced alphabet
    format_user_code(raw) -> str      # "ABCDEFGH" -> "ABCD-EFGH"
    normalize_user_code(raw) -> str   # strip hyphens/whitespace, upper-case
    start(conn, *, invite_token=None, base_url="") -> DeviceStart
    poll(conn, device_code) -> dict
    authorize(conn, code, *, user_id) -> AuthorizeResult

OAuth 2.0 Device Authorization Grant (RFC 8628) pattern: an opaque
`device_code` is polled by the CLI while a human-typeable `user_code`
is entered by the user in the browser. After the browser confirms,
a single subsequent `poll` mints a user token.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from markland.service.auth import create_user_token
from markland.service.invites import accept_invite

# ---------------------------------------------------------------------------
# User-code alphabet
# ---------------------------------------------------------------------------

# Reduced alphabet — no ambiguous glyphs (0/O, 1/I/L).
# 28 symbols: 20 consonants + 8 digits (2-9).
USER_CODE_ALPHABET = "BCDFGHJKMNPQRSTVWXYZ23456789"
USER_CODE_LENGTH = 8

DEVICE_CODE_ENTROPY_BYTES = 40
DEVICE_CODE_TTL_SECONDS = 600          # 10 minutes
POLL_INTERVAL_SECONDS = 5
SLOW_DOWN_WINDOW_SECONDS = 5           # must match POLL_INTERVAL_SECONDS


def generate_user_code() -> str:
    """Return an 8-character code drawn uniformly from USER_CODE_ALPHABET."""
    return "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(USER_CODE_LENGTH))


def format_user_code(raw: str) -> str:
    """Format an 8-char code as XXXX-XXXX."""
    if len(raw) != USER_CODE_LENGTH:
        raise ValueError(f"user_code must be {USER_CODE_LENGTH} chars, got {len(raw)}")
    return f"{raw[:4]}-{raw[4:]}"


def normalize_user_code(presented: str) -> str:
    """Canonicalize a code the browser form submits (strip, upcase, drop hyphens/spaces)."""
    return "".join(ch for ch in presented.upper() if ch != "-" and not ch.isspace())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceStart:
    device_code: str
    user_code: str            # formatted: XXXX-XXXX
    verification_url: str
    poll_interval: int
    expires_in: int


@dataclass(frozen=True)
class AuthorizeResult:
    ok: bool
    device_code: str | None = None
    user_code: str | None = None           # formatted, for display
    invite_token: str | None = None
    invite_accepted: bool = False
    invite_error: str | None = None
    reason: str | None = None              # populated when ok is False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _new_device_code() -> str:
    return secrets.token_urlsafe(DEVICE_CODE_ENTROPY_BYTES)


def _unique_user_code(conn: sqlite3.Connection) -> str:
    """Pick a user_code not currently in use. The 28^8 space makes retries rare."""
    for _ in range(10):
        candidate = generate_user_code()
        row = conn.execute(
            "SELECT 1 FROM device_authorizations WHERE user_code = ?",
            (candidate,),
        ).fetchone()
        if row is None:
            return candidate
    raise RuntimeError("unable to generate a unique user_code after 10 attempts")


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


def start(
    conn: sqlite3.Connection,
    *,
    invite_token: str | None = None,
    base_url: str = "",
) -> DeviceStart:
    """Create a pending device-authorization row and return the device/user codes."""
    device_code = _new_device_code()
    raw_user_code = _unique_user_code(conn)
    now = _utcnow()
    expires = now + timedelta(seconds=DEVICE_CODE_TTL_SECONDS)
    conn.execute(
        """
        INSERT INTO device_authorizations
            (device_code, user_code, status, user_id, invite_token,
             created_at, expires_at, polled_last, authorized_at, consumed_at)
        VALUES (?, ?, 'pending', NULL, ?, ?, ?, NULL, NULL, NULL)
        """,
        (device_code, raw_user_code, invite_token, _iso(now), _iso(expires)),
    )
    conn.commit()
    verification_url = f"{base_url.rstrip('/')}/device" if base_url else "/device"
    return DeviceStart(
        device_code=device_code,
        user_code=format_user_code(raw_user_code),
        verification_url=verification_url,
        poll_interval=POLL_INTERVAL_SECONDS,
        expires_in=DEVICE_CODE_TTL_SECONDS,
    )


# ---------------------------------------------------------------------------
# poll
# ---------------------------------------------------------------------------


def poll(conn: sqlite3.Connection, device_code: str) -> dict:
    """Return the current state for a device_code; mint a token on first authorized poll."""
    row = conn.execute(
        "SELECT status, user_id, invite_token, expires_at, polled_last, consumed_at "
        "FROM device_authorizations WHERE device_code = ?",
        (device_code,),
    ).fetchone()
    if row is None:
        return {"status": "not_found"}

    status, user_id, _invite_token, expires_at, polled_last, consumed_at = row
    now = _utcnow()

    # Rate limit first — a spammer can't burn the row faster than one poll per window.
    if polled_last is not None:
        last = _parse_iso(polled_last)
        if (now - last).total_seconds() < SLOW_DOWN_WINDOW_SECONDS:
            return {"status": "slow_down"}

    # Single-use guard.
    if consumed_at is not None:
        return {"status": "expired"}

    # Natural expiry.
    if now >= _parse_iso(expires_at):
        if status != "expired":
            conn.execute(
                "UPDATE device_authorizations SET status='expired' WHERE device_code=?",
                (device_code,),
            )
            conn.commit()
        return {"status": "expired"}

    if status == "expired":
        return {"status": "expired"}
    if status == "denied":
        return {"status": "denied"}

    if status == "pending":
        conn.execute(
            "UPDATE device_authorizations SET polled_last=? WHERE device_code=?",
            (_iso(now), device_code),
        )
        conn.commit()
        return {"status": "pending"}

    if status == "authorized":
        if user_id is None:
            # Shouldn't happen — defensive.
            return {"status": "expired"}
        _token_id, plaintext = create_user_token(
            conn, user_id=user_id, label=f"Device flow {_iso(now)}"
        )
        conn.execute(
            "UPDATE device_authorizations SET consumed_at=?, polled_last=? "
            "WHERE device_code=?",
            (_iso(now), _iso(now), device_code),
        )
        conn.commit()
        return {"status": "authorized", "access_token": plaintext}

    # Unknown status — defensive.
    return {"status": "expired"}


# ---------------------------------------------------------------------------
# authorize
# ---------------------------------------------------------------------------


def _lookup_by_any_code(conn: sqlite3.Connection, code: str):
    """Find a row by device_code (long) or user_code (short, normalized)."""
    row = conn.execute(
        "SELECT device_code, user_code, status, invite_token, expires_at "
        "FROM device_authorizations WHERE device_code = ?",
        (code,),
    ).fetchone()
    if row is not None:
        return row
    normalized = normalize_user_code(code)
    return conn.execute(
        "SELECT device_code, user_code, status, invite_token, expires_at "
        "FROM device_authorizations WHERE user_code = ?",
        (normalized,),
    ).fetchone()


def authorize(
    conn: sqlite3.Connection,
    code: str,
    *,
    user_id: str,
) -> AuthorizeResult:
    """Bind `user_id` to a pending device-authorization row.

    Accepts either the device_code or the user_code (formatted or raw). Returns
    an AuthorizeResult describing the outcome; the caller renders.
    """
    row = _lookup_by_any_code(conn, code)
    if row is None:
        return AuthorizeResult(ok=False, reason="not_found")

    device_code, raw_user_code, status, invite_token, expires_at = row
    now = _utcnow()

    if now >= _parse_iso(expires_at):
        return AuthorizeResult(
            ok=False, reason="expired", device_code=device_code,
            user_code=format_user_code(raw_user_code),
        )
    if status == "authorized":
        return AuthorizeResult(
            ok=False, reason="already_authorized", device_code=device_code,
            user_code=format_user_code(raw_user_code),
        )
    if status != "pending":
        return AuthorizeResult(
            ok=False, reason=status, device_code=device_code,
            user_code=format_user_code(raw_user_code),
        )

    invite_accepted = False
    invite_error: str | None = None
    if invite_token:
        try:
            result = accept_invite(
                conn, invite_token=invite_token, user_id=user_id
            )
            # Canonical service.invites.accept_invite returns None when the
            # invite couldn't be applied (expired/revoked/used up). Anything
            # truthy means a Grant was returned. Mocks in unit tests may
            # return None — for those paths no invite rows exist, so this
            # branch still reflects reality.
            if result is None:
                invite_error = "invite not acceptable"
            else:
                invite_accepted = True
        except Exception as exc:  # best-effort per spec §4.1
            invite_error = str(exc)

    conn.execute(
        "UPDATE device_authorizations SET status='authorized', user_id=?, authorized_at=? "
        "WHERE device_code=?",
        (user_id, _iso(now), device_code),
    )
    conn.commit()

    return AuthorizeResult(
        ok=True,
        device_code=device_code,
        user_code=format_user_code(raw_user_code),
        invite_token=invite_token,
        invite_accepted=invite_accepted,
        invite_error=invite_error,
    )
