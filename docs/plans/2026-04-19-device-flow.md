# Device Flow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

> **Note:** No git commits during execution — this project is not a git repo at time of writing; the user manages version control manually. Where commit steps would normally appear, a "verification" step is substituted.

**Goal:** Deliver one-paste Claude-Code onboarding via an OAuth-device-flow pattern. After this plan, a user can paste `https://markland.dev/setup` or `https://markland.dev/setup?invite=<token>` into Claude Code and land — in a single flow — with (a) a freshly minted user token, (b) Markland's MCP server installed in their Claude Code config, and (c) (if an invite was present) the invite accepted and its grant attached to their account.

**Architecture:** A new `device_authorizations` table captures the pending state of a device-flow handshake. `service/device_flow.py` owns `start / poll / authorize`. Four new HTTP routes expose the flow to Claude Code and to the browser: `POST /api/auth/device-start`, `POST /api/auth/device-poll`, `POST /api/auth/device-authorize`, plus the `GET /device` consent page and the `GET /setup` runbook. Successful authorization mints a user token via the existing `service.auth.create_user_token` (Plan 2). If the start call carried an `invite_token`, authorization also calls `service.invites.accept_invite` (Plan 5) — best-effort; authorization still completes even if the invite step fails. Rate-limiting is in-process: a per-IP bucket on start, a per-`device_code` `polled_last` timestamp on poll. Codes expire after 10 minutes and are single-use (a `consumed_at` column prevents re-reading a minted token).

**Tech Stack:** Python 3.12, FastAPI, Starlette, SQLite, Jinja2, pytest, FastMCP. All existing — this plan adds no new dependencies.

**Scope excluded (this plan):**
- No QR codes or camera-assisted pairing.
- No browser-push / WebSocket-push auth (poll only).
- No pairing across multiple simultaneous clients for the same `user_code`.
- No alternative-CLI (Cursor, VS Code MCP) runbook automation — documented only.
- No stdio proxy.
- No signup inside `/device` — the user must already have a session (or complete magic-link login in the same tab). Magic-link signup is Plan 2; this plan assumes it exists.

---

## File Structure

**New files:**
- `src/markland/service/device_flow.py` — start/poll/authorize + `user_code` alphabet + `DeviceStart` dataclass.
- `src/markland/web/templates/device.html` — consent page rendered for `GET /device`.
- `src/markland/web/templates/device_done.html` — rendered after the user authorizes a code (confirmation + any invite-accept warning).
- `tests/test_device_flow_codes.py` — unit tests for the reduced-alphabet `user_code` generator.
- `tests/test_device_flow_service.py` — unit tests for `start`, `poll`, `authorize`, single-use, slow_down, expiry.
- `tests/test_device_flow_routes.py` — integration tests for the four HTTP endpoints (including per-IP rate limit on start).
- `tests/test_device_flow_e2e.py` — full happy path (start → browser authorize-as-session → poll returns access_token → whoami with that token) and the invite-piggyback case.

**Modified files:**
- `src/markland/db.py` — add `device_authorizations` table + index to `init_db`.
- `src/markland/web/app.py` — register the four routes and wire them against `db_conn`.

**Unchanged (but read before starting):**
- `src/markland/service/auth.py` — `create_user_token(user_id, label) -> (token_id, plaintext)`.
- `src/markland/service/sessions.py` — cookie helpers; `/api/auth/device-authorize` and `/device` require a logged-in session.
- `src/markland/service/invites.py` — `accept_invite(invite_token, user_id)`.

---

## Task 1: Migration — `device_authorizations` table

**Files:**
- Modify: `src/markland/db.py`

- [x] **Step 1: Write the failing test**

Create `tests/test_device_flow_schema.py`:

```python
"""Schema contract for the device_authorizations table."""

import sqlite3

from markland.db import init_db


def test_device_authorizations_table_exists(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='device_authorizations'"
    )
    assert cur.fetchone() is not None


def test_device_authorizations_columns(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(device_authorizations)")}
    assert cols == {
        "device_code",
        "user_code",
        "status",
        "user_id",
        "invite_token",
        "created_at",
        "expires_at",
        "polled_last",
        "authorized_at",
        "consumed_at",
    }


def test_user_code_is_unique(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO device_authorizations "
        "(device_code, user_code, status, created_at, expires_at) "
        "VALUES ('d1','ABCD1234','pending','2026-04-19T00:00:00Z','2026-04-19T00:10:00Z')"
    )
    with pytest_raises_integrity(conn):
        conn.execute(
            "INSERT INTO device_authorizations "
            "(device_code, user_code, status, created_at, expires_at) "
            "VALUES ('d2','ABCD1234','pending','2026-04-19T00:00:00Z','2026-04-19T00:10:00Z')"
        )


def test_user_code_index_exists(tmp_path):
    conn = init_db(tmp_path / "t.db")
    idx = {row[1] for row in conn.execute("PRAGMA index_list(device_authorizations)")}
    assert "idx_device_user_code" in idx


def pytest_raises_integrity(conn):
    import pytest
    return pytest.raises(sqlite3.IntegrityError)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_device_flow_schema.py -v`
Expected: FAIL — table does not exist.

- [x] **Step 3: Add the DDL to `init_db`**

In `src/markland/db.py`, inside `init_db`, after the existing `CREATE TABLE` statements and before the commit, append:

```python
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_authorizations (
            device_code    TEXT PRIMARY KEY,
            user_code      TEXT NOT NULL UNIQUE,
            status         TEXT NOT NULL CHECK (status IN ('pending','authorized','expired','denied')),
            user_id        TEXT,
            invite_token   TEXT,
            created_at     TEXT NOT NULL,
            expires_at     TEXT NOT NULL,
            polled_last    TEXT,
            authorized_at  TEXT,
            consumed_at    TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_device_user_code "
        "ON device_authorizations (user_code)"
    )
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_device_flow_schema.py -v`
Expected: PASS (4 tests).

- [x] **Step 5: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: no regressions.

---

## Task 2: `user_code` alphabet + generator

**Files:**
- Create: `src/markland/service/device_flow.py` (stub for this task; expanded in later tasks)
- Create: `tests/test_device_flow_codes.py`

- [x] **Step 1: Write the failing tests**

Create `tests/test_device_flow_codes.py`:

```python
"""Reduced-alphabet user_code generator: no ambiguous glyphs, 8 chars, formatted XXXX-XXXX."""

import re

from markland.service.device_flow import (
    USER_CODE_ALPHABET,
    format_user_code,
    generate_user_code,
)


def test_alphabet_excludes_ambiguous_characters():
    # Must not include 0/O, 1/I/L or their lowercase — spec §4.1.
    for ch in "0O1IL":
        assert ch not in USER_CODE_ALPHABET
    # Pick one concrete recommended set; guard against silent shrinkage.
    assert len(USER_CODE_ALPHABET) >= 28


def test_alphabet_has_no_duplicates():
    assert len(set(USER_CODE_ALPHABET)) == len(USER_CODE_ALPHABET)


def test_generate_user_code_is_eight_chars_from_alphabet():
    for _ in range(200):
        code = generate_user_code()
        assert len(code) == 8
        assert all(c in USER_CODE_ALPHABET for c in code)


def test_format_user_code_adds_hyphen():
    assert format_user_code("ABCD1234") == "ABCD-1234"


def test_format_user_code_rejects_wrong_length():
    import pytest
    with pytest.raises(ValueError):
        format_user_code("ABC")


def test_generate_user_code_has_entropy():
    codes = {generate_user_code() for _ in range(500)}
    # With 28^8 ≈ 3.8e11 possibilities, 500 draws should collide ~never.
    assert len(codes) == 500


def test_format_user_code_round_trip_regex():
    code = generate_user_code()
    formatted = format_user_code(code)
    assert re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}", formatted)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_device_flow_codes.py -v`
Expected: FAIL — module does not exist.

- [x] **Step 3: Implement the generator**

Create `src/markland/service/device_flow.py`:

```python
"""Device-authorization flow (Markland §4.1).

Public surface (this task):
    USER_CODE_ALPHABET
    generate_user_code() -> str       # 8 chars from reduced alphabet
    format_user_code(raw) -> str      # "ABCDEFGH" -> "ABCD-EFGH"

Later tasks add start / poll / authorize.
"""

from __future__ import annotations

import secrets

# Reduced alphabet — no ambiguous glyphs (0/O, 1/I/L).
# 28 symbols: 20 consonants + 8 digits (2-9).
USER_CODE_ALPHABET = "BCDFGHJKMNPQRSTVWXYZ23456789"
USER_CODE_LENGTH = 8


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
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_device_flow_codes.py -v`
Expected: PASS (7 tests).

---

## Task 3: `service.device_flow.start`

**Files:**
- Modify: `src/markland/service/device_flow.py`
- Create: `tests/test_device_flow_service.py`

Design: `start` inserts a row in status `pending`, holds `invite_token` verbatim for piggyback, and returns a `DeviceStart` with the `user_code` already formatted for display.

- [x] **Step 1: Write the failing tests**

Create `tests/test_device_flow_service.py`:

```python
"""Unit tests for service/device_flow.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from markland.db import init_db
from markland.service import device_flow


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "t.db")


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
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_device_flow_service.py -v`
Expected: FAIL — `start` does not exist.

- [x] **Step 3: Extend `service/device_flow.py`**

Append to `src/markland/service/device_flow.py`:

```python
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

DEVICE_CODE_ENTROPY_BYTES = 40
DEVICE_CODE_TTL_SECONDS = 600          # 10 minutes
POLL_INTERVAL_SECONDS = 5
SLOW_DOWN_WINDOW_SECONDS = 5           # must match POLL_INTERVAL_SECONDS


@dataclass(frozen=True)
class DeviceStart:
    device_code: str
    user_code: str            # formatted: XXXX-XXXX
    verification_url: str
    poll_interval: int
    expires_in: int


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


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
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_device_flow_service.py -v`
Expected: 4 tests pass (the `start`-related tests).

---

## Task 4: `service.device_flow.poll` — status transitions, slow_down, expiry, single-use

**Files:**
- Modify: `src/markland/service/device_flow.py`
- Modify: `tests/test_device_flow_service.py`

Design:
- `poll(conn, device_code)` returns a dict `{status: ..., access_token?: ...}` (JSON-safe).
- Status transitions:
  - Row absent → `{"status": "not_found"}`.
  - `polled_last` within the last `SLOW_DOWN_WINDOW_SECONDS` → `{"status": "slow_down"}`; `polled_last` is **not** updated on slow_down (so one slow_down doesn't shift the clock forward).
  - `expires_at` passed → promote status to `expired`, persist, return `{"status": "expired"}`.
  - Already `consumed_at` set → `{"status": "expired"}` (single-use — a second poll after token issuance can't re-read it).
  - `pending` → update `polled_last`, return `{"status": "pending"}`.
  - `authorized` and not consumed → mint a user token via `service.auth.create_user_token`, stamp `consumed_at`, return `{"status": "authorized", "access_token": "<plaintext>"}`.

- [x] **Step 1: Add failing tests**

Append to `tests/test_device_flow_service.py`:

```python
import time
from unittest.mock import patch


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
    assert kwargs.get("user_id") == "usr_alice" or args[1] == "usr_alice"
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
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_device_flow_service.py -v`
Expected: FAIL — `poll` not yet implemented.

- [x] **Step 3: Implement `poll`**

Append to `src/markland/service/device_flow.py`:

```python
from markland.service.auth import create_user_token


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def poll(conn: sqlite3.Connection, device_code: str) -> dict:
    """Return the current state for a device_code; mint a token on first authorized poll.

    Contract:
        {"status": "pending"}
        {"status": "slow_down"}
        {"status": "expired"}
        {"status": "authorized", "access_token": "<plaintext>"}
        {"status": "not_found"}
    """
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
```

Note the `create_user_token` call signature assumes Plan 2's service function is `create_user_token(conn, *, user_id, label) -> (token_id, plaintext)`. If Plan 2's signature is positional (`create_user_token(conn, user_id, label)`), the call still works; the tests patch the function so either form is accepted.

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_device_flow_service.py -v`
Expected: PASS for all poll tests. Total for the file so far: 11 passes.

---

## Task 5: `service.device_flow.authorize` + invite piggyback

**Files:**
- Modify: `src/markland/service/device_flow.py`
- Modify: `tests/test_device_flow_service.py`

Design:
- `authorize(conn, code, user_id)` accepts either the `device_code` or a normalized `user_code` (no hyphen, uppercase). Browser route passes `user_code`; internal admin tooling may pass `device_code`.
- Returns an `AuthorizeResult` with fields `ok: bool`, `device_code: str | None`, `invite_accepted: bool`, `invite_error: str | None`. Callers render the outcome.
- Flips the row to `authorized`, sets `user_id` + `authorized_at`.
- If `invite_token` is non-null, calls `service.invites.accept_invite(conn, invite_token, user_id)`. On success, stamps `invite_accepted=True`. On failure, sets `invite_error=<str(exc)>` and still completes authorization (best-effort per spec).
- Single SQLite transaction; commits exactly once at the end.
- Rejects codes that are already authorized, expired, or not found.

- [x] **Step 1: Add failing tests**

Append to `tests/test_device_flow_service.py`:

```python
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
    start = device_flow.start(conn, invite_token="inv_abc")
    raw = start.user_code.replace("-", "")
    with patch("markland.service.device_flow.accept_invite") as accept:
        accept.return_value = None
        r = device_flow.authorize(conn, raw, user_id="usr_alice")
    assert r.ok
    assert r.invite_accepted is True
    assert r.invite_error is None
    accept.assert_called_once()


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
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_device_flow_service.py -v`
Expected: FAIL — `authorize` not yet implemented.

- [x] **Step 3: Implement `authorize`**

Append to `src/markland/service/device_flow.py`:

```python
from markland.service.invites import accept_invite


@dataclass(frozen=True)
class AuthorizeResult:
    ok: bool
    device_code: str | None = None
    user_code: str | None = None           # formatted, for display on the confirmation page
    invite_token: str | None = None
    invite_accepted: bool = False
    invite_error: str | None = None
    reason: str | None = None              # populated when ok is False


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
            accept_invite(conn, invite_token=invite_token, user_id=user_id)
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
```

Note: `accept_invite`'s exact kwarg names come from Plan 5 (`service/invites.accept_invite(invite_token, user_id)`). If Plan 5 ships with positional args, update the call site — tests patch the function, so unit tests remain green; catch the signature drift in the e2e test (Task 12).

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_device_flow_service.py -v`
Expected: all 18 tests pass.

---

## Task 6: Route `POST /api/auth/device-start` (with per-IP rate limit)

**Files:**
- Modify: `src/markland/web/app.py`
- Create: `tests/test_device_flow_routes.py`

Design:
- `POST /api/auth/device-start` accepts optional JSON body `{"invite_token": "..."}`.
- Returns the shape `{device_code, user_code, verification_url, poll_interval, expires_in}` — `user_code` pre-formatted.
- Per-IP rate limit: simple in-process `dict[str, list[float]]` sliding window. Default 10 starts / minute per IP. Returns 429 `{"error":"rate_limited","retry_after":<secs>}` beyond that. Limit is attached to the app so tests can reset it.

- [x] **Step 1: Write the failing tests**

Create `tests/test_device_flow_routes.py`:

```python
"""HTTP tests for /api/auth/device-*."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_ADMIN_TOKEN", "t")
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "test.db")
    app = create_app(conn, mount_mcp=False, base_url="https://markland.dev")
    with TestClient(app) as c:
        yield c


def test_device_start_without_body_returns_expected_shape(client):
    r = client.post("/api/auth/device-start")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "device_code",
        "user_code",
        "verification_url",
        "poll_interval",
        "expires_in",
    }
    assert len(body["device_code"]) >= 54
    assert "-" in body["user_code"]
    assert body["verification_url"] == "https://markland.dev/device"
    assert body["poll_interval"] == 5
    assert body["expires_in"] == 600


def test_device_start_with_invite_token_persists_it(client):
    r = client.post("/api/auth/device-start", json={"invite_token": "inv_xyz"})
    assert r.status_code == 200
    # We can't query the DB directly from the client, but we can verify the
    # invite piggyback path end-to-end via the e2e test (Task 12).


def test_device_start_rate_limits_per_ip(client):
    # 10/min per IP. Burst 11 requests from the same IP.
    for _ in range(10):
        r = client.post("/api/auth/device-start")
        assert r.status_code == 200, r.text
    r = client.post("/api/auth/device-start")
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "rate_limited"
    assert "retry_after" in body


def test_device_start_rate_limit_is_per_ip(client):
    # Exhaust limit from default IP.
    for _ in range(10):
        client.post("/api/auth/device-start")
    # Different IP — should still work.
    r = client.post(
        "/api/auth/device-start",
        headers={"X-Forwarded-For": "203.0.113.7"},
    )
    assert r.status_code == 200
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_device_flow_routes.py -v`
Expected: FAIL — route does not exist.

- [x] **Step 3: Add the route and rate limiter**

In `src/markland/web/app.py`, add near the other imports:

```python
import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import Request
from pydantic import BaseModel

from markland.service import device_flow
```

Inside `create_app(...)`, after the existing route definitions (but before `return app`), add:

```python
    # --- Device flow --------------------------------------------------------

    DEVICE_START_LIMIT = 10          # requests
    DEVICE_START_WINDOW = 60         # seconds
    _device_start_hits: dict[str, Deque[float]] = defaultdict(deque)

    def _client_ip(request: Request) -> str:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _rate_limit_device_start(ip: str) -> tuple[bool, int]:
        now = time.time()
        q = _device_start_hits[ip]
        while q and now - q[0] > DEVICE_START_WINDOW:
            q.popleft()
        if len(q) >= DEVICE_START_LIMIT:
            retry_after = int(DEVICE_START_WINDOW - (now - q[0])) + 1
            return False, retry_after
        q.append(now)
        return True, 0

    class DeviceStartBody(BaseModel):
        invite_token: str | None = None

    @app.post("/api/auth/device-start")
    def api_device_start(request: Request, body: DeviceStartBody | None = None):
        ip = _client_ip(request)
        ok, retry_after = _rate_limit_device_start(ip)
        if not ok:
            return JSONResponse(
                {"error": "rate_limited", "retry_after": retry_after},
                status_code=429,
            )
        invite_token = body.invite_token if body else None
        result = device_flow.start(
            db_conn, invite_token=invite_token, base_url=base_url,
        )
        return JSONResponse({
            "device_code": result.device_code,
            "user_code": result.user_code,
            "verification_url": result.verification_url,
            "poll_interval": result.poll_interval,
            "expires_in": result.expires_in,
        })
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_device_flow_routes.py -v`
Expected: 4 tests pass (just the device-start ones; poll/authorize tests arrive in later tasks).

---

## Task 7: Route `POST /api/auth/device-poll`

**Files:**
- Modify: `src/markland/web/app.py`
- Modify: `tests/test_device_flow_routes.py`

- [x] **Step 1: Add failing tests**

Append to `tests/test_device_flow_routes.py`:

```python
def test_device_poll_returns_pending(client):
    start = client.post("/api/auth/device-start").json()
    r = client.post("/api/auth/device-poll", json={"device_code": start["device_code"]})
    assert r.status_code == 200
    assert r.json() == {"status": "pending"}


def test_device_poll_slow_down(client):
    start = client.post("/api/auth/device-start").json()
    client.post("/api/auth/device-poll", json={"device_code": start["device_code"]})
    r = client.post("/api/auth/device-poll", json={"device_code": start["device_code"]})
    assert r.status_code == 200
    assert r.json() == {"status": "slow_down"}


def test_device_poll_unknown_device_code(client):
    r = client.post("/api/auth/device-poll", json={"device_code": "nope"})
    assert r.status_code == 200
    assert r.json() == {"status": "not_found"}


def test_device_poll_missing_body_returns_400(client):
    r = client.post("/api/auth/device-poll", json={})
    assert r.status_code == 422  # pydantic validation


def test_device_poll_accepts_content_type_variations(client):
    start = client.post("/api/auth/device-start").json()
    r = client.post(
        "/api/auth/device-poll",
        json={"device_code": start["device_code"]},
        headers={"Accept": "application/json"},
    )
    assert r.status_code == 200
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_device_flow_routes.py -v`
Expected: FAIL — route does not exist.

- [x] **Step 3: Add the route**

In `create_app`, immediately after `api_device_start`, add:

```python
    class DevicePollBody(BaseModel):
        device_code: str

    @app.post("/api/auth/device-poll")
    def api_device_poll(body: DevicePollBody):
        result = device_flow.poll(db_conn, body.device_code)
        return JSONResponse(result)
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_device_flow_routes.py -v`
Expected: all device-start + device-poll tests pass.

---

## Task 8: Route `POST /api/auth/device-authorize`

**Files:**
- Modify: `src/markland/web/app.py`
- Modify: `tests/test_device_flow_routes.py`

Design:
- Requires a logged-in session — reads `user_id` from `service.sessions.get_session(request)` (Plan 2 helper).
- Body: `{"user_code": "ABCD-1234"}` (hyphen optional).
- On success, returns `{ok: true, invite_accepted: bool, invite_error: null|str}`. The browser flow lives under `GET /device` (Task 9); this JSON endpoint is for programmatic use and for the /device page's fetch call.
- 401 if no session. 400/410 if the code is invalid / expired / already-authorized.

- [x] **Step 1: Add failing tests**

Append to `tests/test_device_flow_routes.py`:

```python
from markland.service import sessions as sessions_mod


def _login(client, user_id="usr_alice"):
    """Install a session cookie for `user_id`. Uses the same signer the app uses."""
    cookie = sessions_mod.make_session_cookie_value(user_id)
    client.cookies.set(sessions_mod.SESSION_COOKIE_NAME, cookie)


def test_device_authorize_requires_session(client):
    start = client.post("/api/auth/device-start").json()
    r = client.post(
        "/api/auth/device-authorize",
        json={"user_code": start["user_code"]},
    )
    assert r.status_code == 401


def test_device_authorize_happy_path(client):
    start = client.post("/api/auth/device-start").json()
    _login(client, user_id="usr_alice")
    r = client.post(
        "/api/auth/device-authorize",
        json={"user_code": start["user_code"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["invite_accepted"] is False


def test_device_authorize_accepts_unhyphenated_code(client):
    start = client.post("/api/auth/device-start").json()
    _login(client, user_id="usr_alice")
    r = client.post(
        "/api/auth/device-authorize",
        json={"user_code": start["user_code"].replace("-", "")},
    )
    assert r.status_code == 200


def test_device_authorize_unknown_code_returns_404(client):
    _login(client, user_id="usr_alice")
    r = client.post(
        "/api/auth/device-authorize",
        json={"user_code": "ZZZZZZZZ"},
    )
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


def test_device_authorize_already_authorized_returns_410(client):
    start = client.post("/api/auth/device-start").json()
    _login(client, user_id="usr_alice")
    client.post("/api/auth/device-authorize", json={"user_code": start["user_code"]})
    r = client.post(
        "/api/auth/device-authorize",
        json={"user_code": start["user_code"]},
    )
    assert r.status_code == 410
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_device_flow_routes.py -v`
Expected: FAIL — route does not exist.

- [x] **Step 3: Add the route**

Import at the top of `src/markland/web/app.py`:

```python
from markland.service import sessions as sessions_mod
```

Inside `create_app`, after `api_device_poll`, add:

```python
    class DeviceAuthorizeBody(BaseModel):
        user_code: str

    @app.post("/api/auth/device-authorize")
    def api_device_authorize(request: Request, body: DeviceAuthorizeBody):
        session = sessions_mod.get_session(request)
        if session is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)
        result = device_flow.authorize(
            db_conn, body.user_code, user_id=session.user_id,
        )
        if not result.ok:
            if result.reason == "not_found":
                return JSONResponse({"error": "not_found"}, status_code=404)
            if result.reason == "expired":
                return JSONResponse({"error": "expired"}, status_code=410)
            if result.reason == "already_authorized":
                return JSONResponse({"error": "already_authorized"}, status_code=410)
            return JSONResponse({"error": result.reason or "invalid"}, status_code=400)
        return JSONResponse({
            "ok": True,
            "invite_accepted": result.invite_accepted,
            "invite_error": result.invite_error,
        })
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_device_flow_routes.py -v`
Expected: all device-start + device-poll + device-authorize tests pass.

---

## Task 9: `GET /device` HTML consent page

**Files:**
- Create: `src/markland/web/templates/device.html`
- Create: `src/markland/web/templates/device_done.html`
- Modify: `src/markland/web/app.py`
- Modify: `tests/test_device_flow_routes.py`

Design:
- `GET /device?code=<raw_or_formatted>` (code is optional — the URL Claude Code shows the user is `/device`, and they type the code). Logged-out users see a prompt to sign in first (link to `/login?next=/device?code=<code>`).
- Logged-in users see:
  - "Hi <display_name> — a CLI is requesting access to your Markland account."
  - If the code is bound to an `invite_token`, name the invite: "This will also give you <level> access to *<doc title>* (invite from <granter_display>)." Lookup via `service.invites.describe_invite(conn, invite_token)` — see note below.
  - Primary action: a `<form method="POST" action="/device/confirm">` carrying the code in a hidden input + a visible CSRF token (signed by `sessions.make_csrf_token`).
- `POST /device/confirm` calls `service.device_flow.authorize` directly (server-side form post, not an XHR — simpler, and the page redirects to `/device/done`).
- `GET /device/done?code=<user_code>` renders `device_done.html` with a completion message (and the invite-error string if present — looked up by `user_code` only to render the confirmation).

**Invite describe note:** `service.invites.describe_invite(conn, invite_token) -> {doc_title, granter_display, level}` is not guaranteed by Plan 5. The fallback is to render a generic "This will also accept the attached invite." string when describe is unavailable. Task 9 wires it optimistically and catches `AttributeError` / `ImportError`.

- [x] **Step 1: Write the consent template**

Create `src/markland/web/templates/device.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Authorize device — Markland</title>
  <style>
    body { font-family: ui-sans-serif, system-ui, sans-serif; max-width: 36rem;
           margin: 4rem auto; padding: 0 1rem; line-height: 1.5; color: #111; }
    h1 { font-size: 1.5rem; margin-bottom: 0.5rem; }
    .code-input { font-family: ui-monospace, monospace; font-size: 1.5rem;
                  letter-spacing: 0.2rem; padding: 0.75rem 1rem; width: 100%;
                  box-sizing: border-box; text-transform: uppercase; }
    .invite-note { background: #fffbea; border: 1px solid #f4c430;
                   padding: 0.75rem 1rem; border-radius: 6px; margin: 1rem 0; }
    .btn { background: #111; color: #fff; padding: 0.6rem 1rem; border: none;
           border-radius: 6px; font-size: 1rem; cursor: pointer; }
    .btn.secondary { background: #eee; color: #111; }
    .error { color: #b00020; }
  </style>
</head>
<body>
  <h1>Authorize a device</h1>

  {% if not session %}
    <p>Please <a href="/login?next=/device{% if code %}?code={{ code }}{% endif %}">sign in</a>
       to continue. After you sign in you'll be brought back here to enter the code.</p>
  {% else %}
    <p>Hi {{ session.display_name or session.user_id }} — a CLI is requesting
       access to your Markland account.</p>

    {% if invite_description %}
      <div class="invite-note">
        This will also give you <strong>{{ invite_description.level }}</strong>
        access to <em>{{ invite_description.doc_title }}</em>
        (shared by {{ invite_description.granter_display }}).
      </div>
    {% elif invite_token %}
      <div class="invite-note">
        This will also accept the attached invite.
      </div>
    {% endif %}

    {% if error %}
      <p class="error">{{ error }}</p>
    {% endif %}

    <form method="post" action="/device/confirm" autocomplete="off">
      <input type="hidden" name="csrf" value="{{ csrf }}" />
      <label for="user_code">Enter the code shown in your CLI:</label>
      <input class="code-input" type="text" id="user_code" name="user_code"
             value="{{ code or '' }}" placeholder="ABCD-EFGH" maxlength="9"
             required autofocus />
      <div style="margin-top:1rem;">
        <button class="btn" type="submit">Authorize</button>
        <a class="btn secondary" href="/" role="button" style="text-decoration:none;display:inline-block;">Cancel</a>
      </div>
    </form>
  {% endif %}
</body>
</html>
```

Create `src/markland/web/templates/device_done.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Device authorized — Markland</title>
  <style>
    body { font-family: ui-sans-serif, system-ui, sans-serif; max-width: 36rem;
           margin: 4rem auto; padding: 0 1rem; line-height: 1.5; color: #111; }
    h1 { font-size: 1.5rem; }
    .ok { color: #0a7a2f; }
    .warn { background: #fff3e0; border: 1px solid #e69138; padding: 0.75rem 1rem;
            border-radius: 6px; margin: 1rem 0; }
  </style>
</head>
<body>
  <h1 class="ok">Device authorized</h1>
  <p>You can return to your CLI — the access token has been issued and your
     tool should complete setup automatically within a few seconds.</p>
  {% if invite_accepted %}
    <p>The attached invite was accepted — the shared doc now appears in your library.</p>
  {% elif invite_error %}
    <div class="warn">
      We authorized the device, but couldn't accept the attached invite:
      <strong>{{ invite_error }}</strong>. Ask whoever sent you the link for a new one.
    </div>
  {% endif %}
  <p><a href="/">Return to Markland</a></p>
</body>
</html>
```

- [x] **Step 2: Add failing tests**

Append to `tests/test_device_flow_routes.py`:

```python
def test_device_page_logged_out_prompts_login(client):
    r = client.get("/device")
    assert r.status_code == 200
    assert "sign in" in r.text.lower()


def test_device_page_logged_in_shows_form(client):
    _login(client, user_id="usr_alice")
    r = client.get("/device")
    assert r.status_code == 200
    assert 'name="user_code"' in r.text


def test_device_page_prefills_code_from_query(client):
    _login(client, user_id="usr_alice")
    r = client.get("/device?code=ABCD-EFGH")
    assert r.status_code == 200
    assert 'value="ABCD-EFGH"' in r.text


def test_device_confirm_requires_session(client):
    r = client.post("/device/confirm", data={"user_code": "XXXX-YYYY", "csrf": "x"})
    assert r.status_code in (401, 303)  # 303 back to /login is also acceptable


def test_device_confirm_happy_path_redirects_to_done(client):
    start = client.post("/api/auth/device-start").json()
    _login(client, user_id="usr_alice")
    # Fetch /device to obtain CSRF via cookie-derived helper.
    r = client.get("/device")
    assert r.status_code == 200
    csrf = _extract_csrf(r.text)
    r2 = client.post(
        "/device/confirm",
        data={"user_code": start["user_code"], "csrf": csrf},
        follow_redirects=False,
    )
    assert r2.status_code == 303
    assert "/device/done" in r2.headers["location"]


def test_device_done_page_renders_ok_state(client):
    start = client.post("/api/auth/device-start").json()
    _login(client, user_id="usr_alice")
    r = client.get("/device")
    csrf = _extract_csrf(r.text)
    client.post(
        "/device/confirm",
        data={"user_code": start["user_code"], "csrf": csrf},
        follow_redirects=False,
    )
    done = client.get(f"/device/done?code={start['user_code']}")
    assert done.status_code == 200
    assert "Device authorized" in done.text


def _extract_csrf(html: str) -> str:
    import re
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "no CSRF token in rendered form"
    return m.group(1)
```

- [x] **Step 2b: Run tests to verify they fail**

Run: `uv run pytest tests/test_device_flow_routes.py -v`
Expected: FAIL — routes do not exist.

- [x] **Step 3: Wire the routes**

At the top of `src/markland/web/app.py`, add (next to existing Jinja imports):

```python
from fastapi.responses import RedirectResponse
from fastapi import Form
```

Inside `create_app`, near the other `env.get_template` calls, add:

```python
    device_tpl = env.get_template("device.html")
    device_done_tpl = env.get_template("device_done.html")
```

Then, after `api_device_authorize`, add:

```python
    def _describe_invite(invite_token: str | None):
        if not invite_token:
            return None
        try:
            from markland.service import invites as invites_mod
            describe = getattr(invites_mod, "describe_invite", None)
            if describe is None:
                return None
            return describe(db_conn, invite_token=invite_token)
        except Exception:
            return None

    def _lookup_by_user_code(raw_or_formatted: str):
        normalized = device_flow.normalize_user_code(raw_or_formatted)
        return db_conn.execute(
            "SELECT device_code, user_code, invite_token "
            "FROM device_authorizations WHERE user_code = ?",
            (normalized,),
        ).fetchone()

    @app.get("/device", response_class=HTMLResponse)
    def page_device(request: Request, code: str | None = None):
        session = sessions_mod.get_session(request)
        invite_token = None
        if code and session is not None:
            row = _lookup_by_user_code(code)
            if row is not None:
                invite_token = row[2]
        csrf = sessions_mod.make_csrf_token(session.user_id) if session else ""
        return HTMLResponse(
            device_tpl.render(
                session=session,
                code=code,
                csrf=csrf,
                invite_token=invite_token,
                invite_description=_describe_invite(invite_token),
                error=None,
            )
        )

    @app.post("/device/confirm")
    def page_device_confirm(
        request: Request,
        user_code: str = Form(...),
        csrf: str = Form(...),
    ):
        session = sessions_mod.get_session(request)
        if session is None:
            return RedirectResponse(
                url=f"/login?next=/device?code={user_code}", status_code=303
            )
        if not sessions_mod.verify_csrf_token(csrf, session.user_id):
            return HTMLResponse(
                device_tpl.render(
                    session=session, code=user_code, csrf="",
                    invite_token=None, invite_description=None,
                    error="Your session expired. Reload the page and try again.",
                ),
                status_code=400,
            )
        result = device_flow.authorize(db_conn, user_code, user_id=session.user_id)
        if not result.ok:
            human = {
                "not_found": "We couldn't find that code. Double-check what your CLI showed you.",
                "expired": "That code has expired. Run the CLI step again to get a new one.",
                "already_authorized": "That code has already been used.",
            }.get(result.reason or "", "Couldn't authorize that code.")
            return HTMLResponse(
                device_tpl.render(
                    session=session, code=user_code, csrf=sessions_mod.make_csrf_token(session.user_id),
                    invite_token=None, invite_description=None, error=human,
                ),
                status_code=400,
            )
        return RedirectResponse(
            url=f"/device/done?code={result.user_code}"
                f"{'&invite_accepted=1' if result.invite_accepted else ''}"
                f"{'&invite_error=' + (result.invite_error or '') if result.invite_error else ''}",
            status_code=303,
        )

    @app.get("/device/done", response_class=HTMLResponse)
    def page_device_done(code: str | None = None, invite_accepted: str | None = None,
                         invite_error: str | None = None):
        return HTMLResponse(
            device_done_tpl.render(
                code=code,
                invite_accepted=(invite_accepted == "1"),
                invite_error=invite_error,
            )
        )
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_device_flow_routes.py -v`
Expected: all tests in the file pass.

---

## Task 10: `GET /setup` runbook endpoint

**Files:**
- Modify: `src/markland/web/app.py`
- Modify: `tests/test_device_flow_routes.py`

Design:
- Content-Type `text/markdown; charset=utf-8`.
- Preserves `?invite=<token>` — threads it into the `device-start` body example.
- Completely self-contained — no external references Claude Code needs to resolve.

- [x] **Step 1: Add failing tests**

Append to `tests/test_device_flow_routes.py`:

```python
def test_setup_returns_markdown(client):
    r = client.get("/setup")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "device-start" in r.text
    assert "device-poll" in r.text
    assert "claude mcp add" in r.text


def test_setup_runbook_includes_verification_step(client):
    r = client.get("/setup")
    assert "markland_whoami" in r.text


def test_setup_runbook_threads_invite_token(client):
    r = client.get("/setup?invite=inv_abc")
    # The runbook should reference the invite_token in the device-start body example.
    assert '"invite_token": "inv_abc"' in r.text


def test_setup_runbook_no_invite_param_omits_invite_body(client):
    r = client.get("/setup")
    assert "invite_token" not in r.text or '"invite_token": null' in r.text
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_device_flow_routes.py -v`
Expected: FAIL — route does not exist.

- [x] **Step 3: Add the route**

In `create_app`, after `page_device_done`, add:

```python
    @app.get("/setup")
    def page_setup(invite: str | None = None):
        host = base_url.rstrip("/") if base_url else ""
        start_body = (
            f'{{"invite_token": "{invite}"}}'
            if invite
            else "{}"
        )
        runbook = f"""# Markland setup

You are Claude Code. A user pasted this URL to install the Markland MCP server.
Execute the steps below end-to-end. Do not ask the user for input beyond what
step 2 instructs.

## 1. Start a device authorization

```
POST {host}/api/auth/device-start
Content-Type: application/json

{start_body}
```

Parse the JSON response. It has shape:

```
{{
  "device_code":       "<long opaque string>",
  "user_code":         "ABCD-EFGH",
  "verification_url":  "{host}/device",
  "poll_interval":     5,
  "expires_in":        600
}}
```

## 2. Show the user exactly this message

> Visit **{host}/device** and enter the code **ABCD-EFGH**.
> The code expires in 10 minutes.

(Substitute the real `user_code` from step 1.)

## 3. Poll until authorized

Every `poll_interval` seconds (5s), call:

```
POST {host}/api/auth/device-poll
Content-Type: application/json

{{"device_code": "<from step 1>"}}
```

Response statuses:
- `{{"status": "pending"}}`   — keep polling.
- `{{"status": "slow_down"}}` — you polled too fast; wait an extra 5s.
- `{{"status": "expired"}}`   — the code ran out; start over from step 1.
- `{{"status": "authorized", "access_token": "mk_usr_..."}}` — done. Capture the token.

Stop polling after `expires_in` seconds regardless.

## 4. Install the MCP server

Prefer the CLI form:

```
claude mcp add markland {host}/mcp --header "Authorization=Bearer $ACCESS_TOKEN"
```

If `claude mcp add` is unavailable, edit `~/.mcp.json` to include:

```json
{{
  "mcpServers": {{
    "markland": {{
      "type": "http",
      "url": "{host}/mcp",
      "headers": {{
        "Authorization": "Bearer <paste the access_token from step 3>"
      }}
    }}
  }}
}}
```

## 5. Restart Claude Code and verify

Restart Claude Code, then call the `markland_whoami` tool. Expect a response
like `{{"principal_id": "usr_...", "principal_type": "user", ...}}`.

If `markland_whoami` returns `unauthenticated`, the token wasn't installed —
re-run step 4 and restart again.
"""
        return Response(
            content=runbook,
            media_type="text/markdown; charset=utf-8",
        )
```

Add these imports near the top of `src/markland/web/app.py` if not already present:

```python
from fastapi.responses import Response
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_device_flow_routes.py -v`
Expected: all tests in the file pass (~20).

---

## Task 11: Integration test — full happy path

**Files:**
- Create: `tests/test_device_flow_e2e.py`

Design: simulate Claude Code + browser interleaving against a single `TestClient`. Uses the real `create_user_token` so the resulting token actually authenticates against the `/mcp` surface (and `markland_whoami` specifically).

- [x] **Step 1: Write the test**

Create `tests/test_device_flow_e2e.py`:

```python
"""End-to-end device flow: Claude Code + browser working against a live app.

We do not spin up two processes — a single TestClient plays both roles. The test
verifies the contract that after the flow, the issued access_token authenticates
against the MCP endpoint (whoami) and against /api/me.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import auth as auth_service
from markland.service import sessions as sessions_mod
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_ADMIN_TOKEN", "test_admin")
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "e2e.db")
    # Seed a user that /device/confirm will bind to. Plan 2 provides create_user.
    auth_service.create_user(conn, user_id="usr_alice", email="alice@example.com",
                             display_name="Alice")
    app = create_app(
        conn, mount_mcp=True, admin_token="test_admin",
        base_url="https://markland.dev",
    )
    with TestClient(app) as c:
        yield c


def _extract_csrf(html: str) -> str:
    import re
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m
    return m.group(1)


def test_full_happy_path(client):
    # --- Claude Code: start
    start = client.post("/api/auth/device-start").json()
    assert start["user_code"].count("-") == 1
    device_code = start["device_code"]

    # --- Claude Code: first poll -> pending
    first = client.post("/api/auth/device-poll", json={"device_code": device_code}).json()
    assert first == {"status": "pending"}

    # --- Browser: user logs in, hits /device, confirms.
    client.cookies.set(
        sessions_mod.SESSION_COOKIE_NAME,
        sessions_mod.make_session_cookie_value("usr_alice"),
    )
    page = client.get(f"/device?code={start['user_code']}")
    csrf = _extract_csrf(page.text)
    confirm = client.post(
        "/device/confirm",
        data={"user_code": start["user_code"], "csrf": csrf},
        follow_redirects=False,
    )
    assert confirm.status_code == 303

    # --- Claude Code: drop the browser cookie, poll again (after slow_down window).
    client.cookies.clear()
    time.sleep(6)
    authorized = client.post(
        "/api/auth/device-poll", json={"device_code": device_code}
    ).json()
    assert authorized["status"] == "authorized"
    token = authorized["access_token"]
    assert token.startswith("mk_usr_")

    # --- Claude Code: use the token against the MCP surface.
    r = client.post(
        "/mcp/",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "e2e", "version": "0"},
            },
        },
    )
    assert r.status_code == 200

    # --- Second poll with the same device_code now returns expired (single-use).
    time.sleep(6)
    repeat = client.post(
        "/api/auth/device-poll", json={"device_code": device_code}
    ).json()
    assert repeat["status"] == "expired"
```

- [x] **Step 2: Run the test**

Run: `uv run pytest tests/test_device_flow_e2e.py -v`
Expected: PASS.

---

## Task 12: Integration test — invite piggyback

**Files:**
- Modify: `tests/test_device_flow_e2e.py`

Design: verifies the one-paste-with-invite path. Seeds a second user + a doc + an invite row via Plan 5's `create_invite`, then walks the flow with `?invite=<token>` and asserts the grant landed.

- [x] **Step 1: Add the test**

Append to `tests/test_device_flow_e2e.py`:

```python
from markland.service import grants as grants_service   # Plan 3
from markland.service import invites as invites_service  # Plan 5
from markland.service import docs as docs_service        # Plan 3


def test_invite_piggyback(client, tmp_path):
    # Reach the conn via an init call. The fixture already created a user — we
    # need to re-open the same DB to seed additional rows.
    import sqlite3
    db_path = tmp_path / "e2e.db"
    conn = sqlite3.connect(db_path)

    # Seed Bob + a doc Bob owns + an invite to Alice.
    from markland.service import auth as auth_service
    auth_service.create_user(
        conn, user_id="usr_bob", email="bob@example.com", display_name="Bob"
    )
    doc = docs_service.publish_doc(
        conn, base_url="https://markland.dev", title="Bob's doc",
        content="# hello", owner_id="usr_bob", public=False,
    )
    invite = invites_service.create_invite(
        conn, doc_id=doc["id"], level="edit", created_by="usr_bob",
        single_use=True, expires_in_days=7,
    )
    conn.commit()
    conn.close()

    invite_token = invite["invite_token"]

    # --- Claude Code: start with invite_token
    start = client.post(
        "/api/auth/device-start", json={"invite_token": invite_token}
    ).json()

    # --- Browser: Alice logs in, authorizes the code
    client.cookies.set(
        sessions_mod.SESSION_COOKIE_NAME,
        sessions_mod.make_session_cookie_value("usr_alice"),
    )
    page = client.get(f"/device?code={start['user_code']}")
    # Invite note is shown (description or generic).
    assert "invite" in page.text.lower()
    csrf = _extract_csrf(page.text)
    confirm = client.post(
        "/device/confirm",
        data={"user_code": start["user_code"], "csrf": csrf},
        follow_redirects=False,
    )
    assert confirm.status_code == 303

    # --- Claude Code: poll -> authorized with token
    client.cookies.clear()
    time.sleep(6)
    out = client.post(
        "/api/auth/device-poll", json={"device_code": start["device_code"]}
    ).json()
    assert out["status"] == "authorized"
    assert out["access_token"].startswith("mk_usr_")

    # --- Grant now exists for Alice on Bob's doc.
    conn2 = sqlite3.connect(db_path)
    row = conn2.execute(
        "SELECT level FROM grants WHERE doc_id = ? AND principal_id = ?",
        (doc["id"], "usr_alice"),
    ).fetchone()
    conn2.close()
    assert row is not None
    assert row[0] == "edit"


def test_invite_piggyback_degrades_gracefully_when_invite_expired(client, tmp_path):
    """If the invite accept fails, authorization still completes and the user gets a token."""
    import sqlite3
    db_path = tmp_path / "e2e.db"
    conn = sqlite3.connect(db_path)

    from markland.service import auth as auth_service
    auth_service.create_user(
        conn, user_id="usr_bob", email="bob@example.com", display_name="Bob"
    )
    doc = docs_service.publish_doc(
        conn, base_url="https://markland.dev", title="Bob's doc",
        content="# hello", owner_id="usr_bob", public=False,
    )
    invite = invites_service.create_invite(
        conn, doc_id=doc["id"], level="edit", created_by="usr_bob",
        single_use=True, expires_in_days=7,
    )
    # Force-revoke the invite so accept_invite raises.
    conn.execute(
        "UPDATE invites SET revoked_at = datetime('now') WHERE id = ?",
        (invite["id"],),
    )
    conn.commit()
    conn.close()

    start = client.post(
        "/api/auth/device-start", json={"invite_token": invite["invite_token"]}
    ).json()

    client.cookies.set(
        sessions_mod.SESSION_COOKIE_NAME,
        sessions_mod.make_session_cookie_value("usr_alice"),
    )
    page = client.get(f"/device?code={start['user_code']}")
    csrf = _extract_csrf(page.text)
    confirm = client.post(
        "/device/confirm",
        data={"user_code": start["user_code"], "csrf": csrf},
        follow_redirects=False,
    )
    assert confirm.status_code == 303
    # The redirect URL carries the invite_error — surfaced on /device/done.
    assert "invite_error" in confirm.headers["location"]

    client.cookies.clear()
    time.sleep(6)
    out = client.post(
        "/api/auth/device-poll", json={"device_code": start["device_code"]}
    ).json()
    assert out["status"] == "authorized"
    assert out["access_token"].startswith("mk_usr_")
```

- [x] **Step 2: Run the tests**

Run: `uv run pytest tests/test_device_flow_e2e.py -v`
Expected: 3 tests pass (happy path + 2 invite variants).

- [x] **Step 3: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: everything green; no regressions in Plans 1–5 test files.

---

## Task 13: Manual verification with real Claude Code

This is not a unit test — it exercises the full user story against a deployed instance (or `uv run python src/markland/run_app.py` locally with a magic-link session you create by hand).

- [x] **Step 1: Start the app locally**

```bash
MARKLAND_ADMIN_TOKEN=local_test \
MARKLAND_BASE_URL=http://localhost:8950 \
uv run python src/markland/run_app.py
```

- [x] **Step 2: Create a user via the web flow**

In a browser, visit `http://localhost:8950/login`, request a magic link for `you@yourdomain`, and complete the login (Plan 2 emits the link to the server logs when `RESEND_API_KEY` is unset).

- [x] **Step 3: Paste `/setup` into Claude Code**

In Claude Code, paste:

```
http://localhost:8950/setup
```

Expected: Claude Code fetches the markdown, performs step 1 (device-start), shows you the message from step 2, polls in step 3, and executes step 4 (`claude mcp add`). Claude Code will instruct you to restart — do so.

- [x] **Step 4: Verify `markland_whoami`**

After restart, in Claude Code: "Call `markland_whoami`."
Expected: a response containing your `user_id` and `principal_type: "user"`.

- [x] **Step 5: Repeat with an invite**

Create an invite as another user (or via SQL — Plan 5 tests show the shape). Paste:

```
http://localhost:8950/setup?invite=<invite_token>
```

into Claude Code. Complete the flow signed in as the *recipient* user. After `markland_whoami`, call `markland_list` — the invited doc should appear in the principal's library.

- [x] **Step 6: Expiry sanity check**

Call `POST /api/auth/device-start`, wait 11 minutes without authorizing, then `POST /api/auth/device-poll` with the `device_code`. Expected: `{"status":"expired"}`.

---

## Completion criteria

- `uv run pytest tests/ -v` passes with the new files:
  - `tests/test_device_flow_schema.py` (4)
  - `tests/test_device_flow_codes.py` (7)
  - `tests/test_device_flow_service.py` (18)
  - `tests/test_device_flow_routes.py` (~20)
  - `tests/test_device_flow_e2e.py` (3)
- `POST /api/auth/device-start` returns the documented shape, honors per-IP rate limit (429 after 10 starts / minute), and persists `invite_token` when supplied.
- `POST /api/auth/device-poll` returns `pending` / `slow_down` / `expired` / `authorized` correctly; minted tokens are single-use (second poll returns `expired`).
- `POST /api/auth/device-authorize` requires a session, rejects unknown / expired / already-authorized codes, and piggybacks invite acceptance best-effort.
- `GET /device` renders the consent page (with invite description when present); `POST /device/confirm` + `GET /device/done` work end-to-end.
- `GET /setup` returns `text/markdown; charset=utf-8` with a self-contained runbook; `?invite=<token>` threads into the device-start body in the runbook.
- Real Claude Code paste of `/setup` and `/setup?invite=...` both complete without human-typed JSON or extra instructions.

## What this plan does NOT deliver

- **No QR codes** — user_code is typed by the human, period.
- **No browser-push / WebSocket auth** — Claude Code polls.
- **No multi-client pairing** — one `user_code` binds one device_code binds one future token.
- **No stdio proxy** — the runbook assumes Claude Code's HTTP MCP support.
- **No automated install paths for other CLIs** — Cursor, VS Code MCP, etc. are documented only; launch targets Claude Code's happy path.
- **No signup from `/device`** — the user must already have (or complete in another tab) a magic-link session via Plan 2's `/login` before the consent page can proceed.
- **No rate-limit persistence** — the per-IP start bucket is in-process and resets on redeploy; adequate for ~100 users. Distributed limiting is deferred to Plan 10.
- **No audit log entry yet** — Plan 10 adds `audit_log` rows for device authorizations.
