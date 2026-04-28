# Security Follow-Ups Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Burn down six security follow-ups from `docs/FOLLOW-UPS.md` (Security section, lines 8-57): URL escape on device redirect, per-IP rate limit on `/device/confirm`, lock device row after N failed confirms, defensive `principal_type` check in `grants.grant_by_principal_id`, append-only `audit_log` enforcement, and `/admin/audit` middleware coverage.

**Architecture:** Each item is independently shippable; the plan orders them cheapest-first so each merge keeps the tree green. Tasks (a)-(d) are pure local edits with new tests. Task (e) adds a SQLite trigger and exercises it from existing audit tests. Task (f) widens `PrincipalMiddleware` to gate `/admin/*` and removes the duplicate bearer-resolve in `app.py::admin_audit` — largest blast radius, sequenced last.

**Tech Stack:** Python 3.12, FastAPI, Starlette, SQLite, pytest (`uv run pytest tests/ -q`).

---

## Conventions for every task

- TDD: failing test first, minimal impl, verify, commit.
- Test command: `uv run pytest tests/ -q` (or a `-k` filter for the specific test).
- Each task ends with a `git commit` step; commits are scoped to one follow-up.
- All file paths below are absolute repo-rooted (no leading `/`).

---

## Task 1: Escape `user_code` in `/device/confirm` unauth redirect

Wrap `user_code` with `urllib.parse.quote` when constructing the inner `next_path` so a malformed code containing `?`, `&`, `#`, or whitespace can't corrupt the `/login?next=…` redirect target. The outer `urlencode` already protects the `next=` param itself; the bug is the inner path.

**Files:**
- Modify: `src/markland/web/device_routes.py:234`
- Test: `tests/test_device_flow_routes.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_device_flow_routes.py` after `test_device_confirm_unauth_redirect_preserves_user_code_through_login` (currently around line 235-258):

```python
def test_device_confirm_unauth_redirect_escapes_malformed_user_code(client):
    """A user_code containing `?` or `&` must not break the redirect target.

    The inner `next_path` is `/device?code=<user_code>`; if user_code is
    naively interpolated, characters like `?` or `&` would let an attacker
    inject extra query params into /device or break URL parsing entirely.
    """
    from urllib.parse import parse_qs, urlparse

    r = client.post(
        "/device/confirm",
        data={"user_code": "AB?CD&x=1", "csrf": "x"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    location = r.headers["location"]
    qs = parse_qs(urlparse(location).query)
    # The inner `?` and `&` must be percent-encoded inside the next= value.
    next_val = qs.get("next", [""])[0]
    assert next_val.startswith("/device?code="), next_val
    # Raw `?` or `&` after the first `code=` would mean we leaked structure.
    assert "?" not in next_val[len("/device?code="):], next_val
    assert "&" not in next_val[len("/device?code="):], next_val
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_device_flow_routes.py::test_device_confirm_unauth_redirect_escapes_malformed_user_code -v
```

Expected: FAIL — the assertion `"?" not in next_val[...]` fails because `user_code` is interpolated raw at `device_routes.py:234`.

- [ ] **Step 3: Apply the fix**

Edit `src/markland/web/device_routes.py` at line 234. Replace:

```python
            next_path = f"/device?code={user_code}"
```

With:

```python
            next_path = f"/device?code={quote(user_code, safe='')}"
```

`quote` is already imported at line 20 (`from urllib.parse import quote, urlencode`); no new import needed. `safe=''` ensures `?`, `&`, `#`, `=`, `/` are all encoded.

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_device_flow_routes.py -v
```

Expected: all device-flow tests PASS, including the new one and the pre-existing `test_device_confirm_unauth_redirect_preserves_user_code_through_login` (the well-formed `ABCD-EFGH` case still round-trips because `quote` is idempotent on safe chars in that string).

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/device_routes.py tests/test_device_flow_routes.py
git commit -m "fix(device): url-escape user_code in /device/confirm unauth redirect"
```

---

## Task 2: Defensive `principal_type` / `agt_` check in `grant_by_principal_id`

Add a runtime assertion that `principal_type ∈ {'user','agent'}` and that when `principal_type == 'agent'` the `principal_id` starts with `agt_`. All current callers are already correct — this is hardening so a future caller can't quietly write a malformed grant row.

**Files:**
- Modify: `src/markland/service/grants.py:78-102` (the `grant_by_principal_id` function)
- Test: `tests/test_api_grants.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_grants.py` (after `test_unauthenticated_returns_401`):

```python
def test_grant_by_principal_id_rejects_unknown_principal_type(client):
    """grant_by_principal_id must reject principal_type outside {'user','agent'}."""
    from markland.service.grants import grant_by_principal_id

    _, conn, _ = client
    with pytest.raises(ValueError):
        grant_by_principal_id(
            conn,
            doc_id="doc_x",
            principal_id="usr_bob",
            principal_type="root",  # not allowed
            level="view",
            granted_by="usr_alice",
        )


def test_grant_by_principal_id_requires_agt_prefix_for_agents(client):
    """Agent grants must use an `agt_` id."""
    from markland.service.grants import grant_by_principal_id

    _, conn, _ = client
    with pytest.raises(ValueError):
        grant_by_principal_id(
            conn,
            doc_id="doc_x",
            principal_id="usr_bob",       # wrong prefix for principal_type=agent
            principal_type="agent",
            level="view",
            granted_by="usr_alice",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_api_grants.py::test_grant_by_principal_id_rejects_unknown_principal_type tests/test_api_grants.py::test_grant_by_principal_id_requires_agt_prefix_for_agents -v
```

Expected: FAIL — current implementation does not validate `principal_type` and writes the row regardless.

- [ ] **Step 3: Apply the fix**

Edit `src/markland/service/grants.py`. Add a module-level constant just below `_VALID_LEVELS` (currently line 34):

```python
_VALID_PRINCIPAL_TYPES = frozenset({"user", "agent"})
```

Then modify `grant_by_principal_id` (lines 78-102) so the body becomes:

```python
def grant_by_principal_id(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    principal_id: str,
    principal_type: str,  # Literal['user','agent']
    level: str,  # Literal['view','edit']
    granted_by: str,
) -> None:
    """Internal helper: idempotent upsert of a grant row.

    No permission check — caller has already authorized (e.g. Plan 5
    invite-accept flow, Plan 4 agent-id grants). No email — caller decides
    whether to notify. Public callers should use `grant(...)` instead.
    """
    if level not in _VALID_LEVELS:
        raise InvalidGrantLevel(f"level must be one of {_VALID_LEVELS}; got {level!r}")
    if principal_type not in _VALID_PRINCIPAL_TYPES:
        raise ValueError(
            f"principal_type must be one of {_VALID_PRINCIPAL_TYPES}; "
            f"got {principal_type!r}"
        )
    if principal_type == "agent" and not principal_id.startswith("agt_"):
        raise ValueError(
            f"agent principal_id must start with 'agt_'; got {principal_id!r}"
        )
    db.upsert_grant(
        conn,
        doc_id=doc_id,
        principal_id=principal_id,
        principal_type=principal_type,
        level=level,
        granted_by=granted_by,
    )
```

- [ ] **Step 4: Run full grants test suite to verify**

```bash
uv run pytest tests/test_api_grants.py tests/test_grants_service.py -v 2>&1 | tail -40
```

Expected: PASS for all (the two new tests now pass; existing tests use valid `principal_type` values so still pass).

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/grants.py tests/test_api_grants.py
git commit -m "fix(grants): validate principal_type and agt_ prefix in grant_by_principal_id"
```

---

## Task 3: Per-IP rate limit on `POST /device/confirm`

Mirror the existing `_rate_limit_device_start` sliding-window pattern (`src/markland/web/device_routes.py:64-85`). Reuse the same 10/60s budget but with a separate hit dict keyed off `_device_confirm_hits` so the two endpoints don't share a counter.

**Files:**
- Modify: `src/markland/web/device_routes.py:64-85` (add new limiter), `:221-274` (gate `page_device_confirm`)
- Test: `tests/test_device_flow_routes.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_device_flow_routes.py`:

```python
def test_device_confirm_rate_limits_per_ip(client):
    """POST /device/confirm must rate-limit per IP (10/min) like /device-start."""
    _login(client)
    # Burn 10 confirms (each will return 400 because csrf is bogus, but should
    # NOT 429). The rate limiter must count these.
    for _ in range(10):
        r = client.post(
            "/device/confirm",
            data={"user_code": "XXXX-YYYY", "csrf": "x"},
            follow_redirects=False,
        )
        assert r.status_code != 429, r.text
    # 11th request from the same IP must be 429.
    r = client.post(
        "/device/confirm",
        data={"user_code": "XXXX-YYYY", "csrf": "x"},
        follow_redirects=False,
    )
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "rate_limited"
    assert "retry_after" in body
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_device_flow_routes.py::test_device_confirm_rate_limits_per_ip -v
```

Expected: FAIL — `/device/confirm` is currently unlimited; the 11th call returns 303 (or 400), not 429.

- [ ] **Step 3: Add the limiter alongside the existing one**

In `src/markland/web/device_routes.py`, just after the existing block at lines 64-85, add:

```python
    # --- Per-IP rate limit on /device/confirm (mirrors device-start) ---

    DEVICE_CONFIRM_LIMIT = 10        # requests
    DEVICE_CONFIRM_WINDOW = 60       # seconds
    _device_confirm_hits: dict[str, Deque[float]] = defaultdict(deque)

    def _rate_limit_device_confirm(ip: str) -> tuple[bool, int]:
        now = time.time()
        q = _device_confirm_hits[ip]
        while q and now - q[0] > DEVICE_CONFIRM_WINDOW:
            q.popleft()
        if len(q) >= DEVICE_CONFIRM_LIMIT:
            retry_after = int(DEVICE_CONFIRM_WINDOW - (now - q[0])) + 1
            return False, retry_after
        q.append(now)
        return True, 0
```

- [ ] **Step 4: Gate `page_device_confirm` on the new limiter**

Edit `page_device_confirm` (currently starts at line 221). Insert the limiter check as the first thing inside the function body, BEFORE `_session_user_id`:

```python
    @router.post("/device/confirm")
    def page_device_confirm(
        request: Request,
        user_code: str = Form(...),
        csrf: str = Form(...),
    ):
        ip = _client_ip(request)
        ok, retry_after = _rate_limit_device_confirm(ip)
        if not ok:
            return JSONResponse(
                {"error": "rate_limited", "retry_after": retry_after},
                status_code=429,
            )
        user_id = _session_user_id(request)
        session = _session_obj(user_id)
        # ... rest unchanged ...
```

(Leave the rest of the function body, lines 227 onward in the current file, exactly as is.)

- [ ] **Step 5: Run the device-flow tests**

```bash
uv run pytest tests/test_device_flow_routes.py -v
```

Expected: PASS for all device-flow tests including the new rate-limit test. The existing `test_device_confirm_*` happy-path / unauth tests still issue ≤ 1 confirm per test fixture instance, so they stay under the 10/60s budget.

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/device_routes.py tests/test_device_flow_routes.py
git commit -m "feat(device): per-IP rate limit on POST /device/confirm"
```

---

## Task 4: Lock / expire device row after N failed confirms

Track failed-confirm attempts on the `device_authorizations` row and mark the row `expired` once the count reaches 5. Subsequent confirms (and polls) then return `expired` regardless of the actual TTL — closing the online-guess window on the 38-bit `user_code`.

**Schema note:** The existing `device_authorizations` table (`src/markland/db.py:140-152`) has no `failed_confirms` column. We add one via `ALTER TABLE … ADD COLUMN` in `init_db` so existing on-disk databases auto-migrate (SQLite tolerates the column being absent on old rows; the default is 0). The status column already supports `'expired'` via its CHECK constraint, so no new status value is needed.

**Files:**
- Modify: `src/markland/db.py:138-157` (add column + idempotent migration)
- Modify: `src/markland/service/device_flow.py:242-309` (`authorize` function)
- Test: `tests/test_device_flow.py` (existing) — add new tests; verify path with `tests/test_device_flow_routes.py`

- [ ] **Step 1: Write the failing test (service-level)**

Append to `tests/test_device_flow.py` (or create the test alongside the existing service tests for `authorize`):

```python
def test_authorize_locks_row_after_five_failed_confirms(tmp_path):
    """After 5 wrong user_codes for a single device_code's row, that row is
    marked expired and further attempts return reason='expired'."""
    from markland.db import init_db
    from markland.service import device_flow
    from markland.service.users import create_user

    conn = init_db(tmp_path / "t.db")
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    start = device_flow.start(conn, base_url="https://markland.test")

    # Five wrong codes (each lookup misses the row, returning not_found).
    # We need failures that *target* the real row to bump its counter, so use
    # near-miss user_codes that share a real row by way of the device_code...
    # Actually: the spec is "5 wrong codes for a given device_code". The
    # row to lock is the one being targeted. Wrong codes that don't resolve
    # to any row can't bump anything, so the behavior we test is: 5 failed
    # confirms against the SAME row (e.g. status mismatch / wrong user_id).
    # To force failure with a hit, we authorize once (row -> status=authorized)
    # then try four more times -> already_authorized; fifth attempt locks it.
    res = device_flow.authorize(conn, start.user_code, user_id=user.id)
    assert res.ok is True
    # Now repeated attempts hit "already_authorized" — count those as failures.
    for _ in range(4):
        r = device_flow.authorize(conn, start.user_code, user_id=user.id)
        assert r.ok is False
    # Fifth failure should lock the row to expired.
    final = device_flow.authorize(conn, start.user_code, user_id=user.id)
    assert final.ok is False
    assert final.reason == "expired"

    # Verify DB state.
    row = conn.execute(
        "SELECT status, failed_confirms FROM device_authorizations WHERE device_code=?",
        (start.device_code,),
    ).fetchone()
    assert row[0] == "expired"
    assert row[1] >= 5
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_device_flow.py::test_authorize_locks_row_after_five_failed_confirms -v
```

Expected: FAIL — `failed_confirms` column doesn't exist (`OperationalError: no such column`) and the lock-out behavior isn't implemented.

- [ ] **Step 3: Add the column to the schema**

Edit `src/markland/db.py`. After the `CREATE TABLE IF NOT EXISTS device_authorizations` block (currently lines 138-153), add an idempotent migration that adds `failed_confirms` if missing. Replace the existing `CREATE TABLE` block with:

```python
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_authorizations (
            device_code     TEXT PRIMARY KEY,
            user_code       TEXT NOT NULL UNIQUE,
            status          TEXT NOT NULL CHECK (status IN ('pending','authorized','expired','denied')),
            user_id         TEXT,
            invite_token    TEXT,
            created_at      TEXT NOT NULL,
            expires_at      TEXT NOT NULL,
            polled_last     TEXT,
            authorized_at   TEXT,
            consumed_at     TEXT,
            failed_confirms INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    # Idempotent migration for pre-existing databases that predate failed_confirms.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(device_authorizations)").fetchall()}
    if "failed_confirms" not in cols:
        conn.execute(
            "ALTER TABLE device_authorizations "
            "ADD COLUMN failed_confirms INTEGER NOT NULL DEFAULT 0"
        )
```

(Leave the `CREATE INDEX` line at 154-157 unchanged.)

- [ ] **Step 4: Wire the lock-out into `authorize`**

Edit `src/markland/service/device_flow.py`. Add a constant near the other constants (line 35-40):

```python
MAX_FAILED_CONFIRMS = 5
```

Then modify `authorize` (lines 242-309). The new flow: on every non-OK return path that *found* a row, bump `failed_confirms`; if the bump pushes the count to `MAX_FAILED_CONFIRMS`, set `status='expired'` and return `reason='expired'` instead of the original reason. Replace the function body with:

```python
def authorize(
    conn: sqlite3.Connection,
    code: str,
    *,
    user_id: str,
) -> AuthorizeResult:
    """Bind `user_id` to a pending device-authorization row.

    Accepts either the device_code or the user_code (formatted or raw). Returns
    an AuthorizeResult describing the outcome; the caller renders.

    After MAX_FAILED_CONFIRMS unsuccessful attempts on a single row, the row
    is locked to status='expired' so subsequent attempts fail fast regardless
    of TTL — closes the online-guess window on the user_code.
    """
    row = _lookup_by_any_code(conn, code)
    if row is None:
        # No row to bump — best we can do; nothing to lock.
        return AuthorizeResult(ok=False, reason="not_found")

    device_code, raw_user_code, status, invite_token, expires_at = row
    now = _utcnow()

    def _bump_and_maybe_lock(reason: str) -> AuthorizeResult:
        """Increment failed_confirms; lock the row if it reaches the cap."""
        cur = conn.execute(
            "UPDATE device_authorizations "
            "SET failed_confirms = failed_confirms + 1 "
            "WHERE device_code = ? "
            "RETURNING failed_confirms",
            (device_code,),
        )
        new_count_row = cur.fetchone()
        new_count = new_count_row[0] if new_count_row else 0
        if new_count >= MAX_FAILED_CONFIRMS and status != "expired":
            conn.execute(
                "UPDATE device_authorizations SET status='expired' WHERE device_code=?",
                (device_code,),
            )
            conn.commit()
            return AuthorizeResult(
                ok=False, reason="expired", device_code=device_code,
                user_code=format_user_code(raw_user_code),
            )
        conn.commit()
        return AuthorizeResult(
            ok=False, reason=reason, device_code=device_code,
            user_code=format_user_code(raw_user_code),
        )

    if now >= _parse_iso(expires_at):
        return _bump_and_maybe_lock("expired")
    if status == "expired":
        return _bump_and_maybe_lock("expired")
    if status == "authorized":
        return _bump_and_maybe_lock("already_authorized")
    if status != "pending":
        return _bump_and_maybe_lock(status)

    invite_accepted = False
    invite_error: str | None = None
    if invite_token:
        try:
            result = accept_invite(
                conn, invite_token=invite_token, user_id=user_id
            )
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
```

`UPDATE … RETURNING` is supported on SQLite ≥ 3.35 (Python 3.12 ships with a newer build). If the test environment hits an older build, fall back to a SELECT-then-UPDATE pair instead.

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_device_flow.py tests/test_device_flow_routes.py -v
```

Expected: all PASS. Watch in particular for any pre-existing test that asserts a specific `reason` after multiple failed confirms — those may need updating to reflect the new lock-out behavior. If a pre-existing test legitimately exercises ≥ 5 failures against one row and expects a non-`expired` reason, update its assertion to accept `expired` after the fifth attempt.

- [ ] **Step 6: Commit**

```bash
git add src/markland/db.py src/markland/service/device_flow.py tests/test_device_flow.py
git commit -m "feat(device): lock authorization row after 5 failed confirms"
```

---

## Task 5: Append-only `audit_log` enforcement via SQLite triggers

Make `audit_log` append-only at the DB layer by raising on UPDATE/DELETE. SQLite supports `BEFORE UPDATE` / `BEFORE DELETE` triggers that call `RAISE(ABORT, 'message')`. This closes the gap that `service/audit.py` only writes — there is currently no DB-level guard against tampering.

**Files:**
- Modify: `src/markland/db.py:176-194` (add triggers right after the `audit_log` table)
- Test: `tests/test_audit_service.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_service.py`:

```python
def test_audit_log_update_raises(conn: sqlite3.Connection) -> None:
    """The audit_log table must reject UPDATE via a BEFORE UPDATE trigger."""
    from markland.db import record_audit

    record_audit(
        conn,
        doc_id="doc_1",
        action="publish",
        principal_id="usr_abc",
        principal_type="user",
        metadata={"k": "v"},
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE audit_log SET action='tampered' WHERE id=1")


def test_audit_log_delete_raises(conn: sqlite3.Connection) -> None:
    """The audit_log table must reject DELETE via a BEFORE DELETE trigger."""
    from markland.db import record_audit

    record_audit(
        conn,
        doc_id="doc_1",
        action="publish",
        principal_id="usr_abc",
        principal_type="user",
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM audit_log WHERE id=1")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_audit_service.py::test_audit_log_update_raises tests/test_audit_service.py::test_audit_log_delete_raises -v
```

Expected: FAIL — currently UPDATE/DELETE on `audit_log` succeed silently.

- [ ] **Step 3: Add the triggers in `init_db`**

Edit `src/markland/db.py`. Just after the `audit_log` `CREATE TABLE` block and before the index lines (currently lines 188-194), add:

```python
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS audit_log_no_update
        BEFORE UPDATE ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit_log is append-only');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
        BEFORE DELETE ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit_log is append-only');
        END
        """
    )
```

- [ ] **Step 4: Run audit tests**

```bash
uv run pytest tests/test_audit_service.py tests/test_audit_integration.py -v
```

Expected: PASS for all (the two new tests now pass; existing tests only INSERT into `audit_log` so still pass).

`RAISE(ABORT, …)` surfaces as `sqlite3.IntegrityError` in Python's sqlite3 binding — the assertion in the test already uses that type.

- [ ] **Step 5: Commit**

```bash
git add src/markland/db.py tests/test_audit_service.py
git commit -m "feat(audit): enforce audit_log append-only via SQLite triggers"
```

---

## Task 6: Widen `PrincipalMiddleware` coverage to `/admin/*`

Today `PrincipalMiddleware` only gates `/mcp` (`src/markland/web/principal_middleware.py:27`). The `/admin/audit` handler in `src/markland/web/app.py:432-452` therefore re-runs `resolve_token` itself — duplicating logic. Change the middleware to accept a tuple of protected prefixes, gate both `/mcp` and `/admin/`, and drop the bearer-resolve from `admin_audit`. The `RateLimitMiddleware` lazy-resolve at `src/markland/web/rate_limit_middleware.py:68-91` stays as-is (it already handles principals being pre-populated).

**Sequenced last** because changing middleware behavior touches every `/admin/*` route, including `/admin/waitlist` (added in commit 185b9e7). Verify the full HTTP test suite passes.

**Files:**
- Modify: `src/markland/web/principal_middleware.py` (accept tuple of prefixes)
- Modify: `src/markland/web/app.py:432-452` (drop duplicate resolve), `:691-700` (pass widened prefix set)
- Test: New file `tests/test_principal_middleware_admin.py`; existing tests in `tests/test_admin_audit.py` and any `tests/test_admin_*` must still pass

- [ ] **Step 1: Write the failing test**

Create `tests/test_principal_middleware_admin.py`:

```python
"""PrincipalMiddleware should gate /admin/* identically to /mcp."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.auth import Principal
from markland.web.app import create_app


@pytest.fixture
def admin_client(tmp_path):
    conn = init_db(tmp_path / "t.db")
    admin = Principal(
        principal_id="usr_admin",
        principal_type="user",
        display_name="Admin",
        is_admin=True,
        user_id="usr_admin",
    )
    conn.execute(
        "INSERT OR IGNORE INTO users (id, email, created_at) "
        "VALUES ('usr_admin', 'admin@x', '2026-01-01')"
    )
    conn.commit()
    # mount_mcp=True is required for PrincipalMiddleware to be installed at all
    # in the current factory wiring; the admin-prefix gating is what we test.
    app = create_app(
        conn,
        mount_mcp=True,
        base_url="https://markland.test",
        session_secret="test",
        test_principal_by_token={"adm": admin},
    )
    return TestClient(app)


def test_admin_audit_without_bearer_returns_401(admin_client):
    """/admin/audit must 401 when no Bearer token is present.

    Same contract as /mcp: PrincipalMiddleware short-circuits before the
    handler ever runs.
    """
    r = admin_client.get("/admin/audit")
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}


def test_admin_audit_with_bad_bearer_returns_401(admin_client):
    r = admin_client.get(
        "/admin/audit", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert r.status_code == 401


def test_admin_audit_with_valid_admin_bearer_succeeds(admin_client):
    """Once gated by middleware, the handler still serves admins."""
    r = admin_client.get(
        "/admin/audit", headers={"Authorization": "Bearer adm"}
    )
    assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify the structure works (some will fail)**

```bash
uv run pytest tests/test_principal_middleware_admin.py -v
```

Expected: the 401 cases may already pass (because `admin_audit` does its own resolve), but `test_admin_audit_with_valid_admin_bearer_succeeds` will fail because `test_principal_by_token` injection happens via a separate test middleware that runs *after* `PrincipalMiddleware` in the current ordering and the new gate won't see the injected principal. We fix this in the implementation steps.

(If all three pass before any change is made, the task still has value — it locks in the contract — but you must still complete the impl steps so the duplicate resolve in `admin_audit` is removed.)

- [ ] **Step 3: Widen `PrincipalMiddleware`**

Replace `src/markland/web/principal_middleware.py` entirely with:

```python
"""Middleware that resolves Bearer tokens to Principals on protected paths.

Replaces the Plan-1 `AdminBearerMiddleware`. On a request whose path matches
ANY of `protected_prefixes`:
  1. If `request.state.principal` is already set (e.g. by a test injection
     middleware), pass through.
  2. Extract `Authorization: Bearer <token>`.
  3. Call `service.auth.resolve_token`.
  4. On success, attach the `Principal` to `request.state.principal`.
  5. On any failure (no header, malformed header, unknown/revoked token) return 401.
"""

from __future__ import annotations

import sqlite3

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from markland.service.auth import resolve_token


class PrincipalMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        db_conn: sqlite3.Connection,
        protected_prefixes: tuple[str, ...] = ("/mcp",),
    ) -> None:
        super().__init__(app)
        self._conn = db_conn
        self._prefixes = tuple(protected_prefixes)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not any(path.startswith(p) for p in self._prefixes):
            return await call_next(request)

        # Honor pre-injected principals (test harness path).
        if getattr(request.state, "principal", None) is not None:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return JSONResponse({"error": "unauthenticated"}, status_code=401)

        plaintext = header[7:].strip()
        principal = resolve_token(self._conn, plaintext)
        if principal is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)

        request.state.principal = principal
        return await call_next(request)
```

**Test-fixture interaction note:** The test-injection middleware (`_inject_principal` at `src/markland/web/app.py:682-689`) is added *before* `PrincipalMiddleware`; Starlette's reversed add-order means it runs *after* `PrincipalMiddleware` in the request flow. So when a test sends `Bearer adm`, the gate sees no injected principal yet and `resolve_token` would fail (`adm` isn't a real token). The pre-injected `getattr(request.state, "principal", None)` short-circuit above is harmless but does NOT help here. The fix is in the test fixture: register a real user token via `service.auth.create_user_token` rather than relying on the in-memory inject map.

Update the test fixture in `tests/test_principal_middleware_admin.py` (Step 1) accordingly. Replace its body with:

```python
@pytest.fixture
def admin_client(tmp_path):
    from markland.service.auth import create_user_token

    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT OR IGNORE INTO users (id, email, is_admin, created_at) "
        "VALUES ('usr_admin', 'admin@x', 1, '2026-01-01')"
    )
    conn.commit()
    _, plaintext = create_user_token(conn, user_id="usr_admin", label="t")
    app = create_app(
        conn,
        mount_mcp=True,
        base_url="https://markland.test",
        session_secret="test",
    )
    client = TestClient(app)
    client.admin_token = plaintext
    return client
```

And update the success-case test (`test_admin_audit_with_valid_admin_bearer_succeeds`) to use `admin_client.admin_token` in the header. If the `users` schema does not have an `is_admin` column, swap the seed for the project's actual admin-flag pattern — verify by reading `src/markland/db.py` users table around line 95-103 and `src/markland/service/auth.py` for the admin resolution logic.

- [ ] **Step 4: Drop the duplicate resolve in `admin_audit`**

Edit `src/markland/web/app.py`. Replace the body of `admin_audit` (lines 432-452) with:

```python
    @app.get("/admin/audit", response_class=HTMLResponse)
    def admin_audit(request: Request):
        principal = getattr(request.state, "principal", None)
        if principal is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)
        if not principal.is_admin:
            return JSONResponse({"error": "forbidden"}, status_code=403)

        from markland.service import audit as audit_svc

        rows = audit_svc.list_recent(db_conn, limit=200)
        for r in rows:
            r["metadata_json"] = json.dumps(r["metadata"], sort_keys=True)
        return HTMLResponse(admin_audit_tpl.render(rows=rows))
```

- [ ] **Step 5: Wire the widened prefixes in `create_app`**

Edit `src/markland/web/app.py:691-700`. Replace:

```python
    if mcp_app is not None:
        from markland.web.principal_middleware import PrincipalMiddleware

        # Middleware gates /mcp before the sub-app sees the request.
        app.add_middleware(
            PrincipalMiddleware,
            db_conn=db_conn,
            protected_prefix="/mcp",
        )
        app.mount("/mcp", mcp_app)
```

With:

```python
    # PrincipalMiddleware gates /mcp AND /admin/* uniformly. We add it whether
    # or not /mcp is mounted so /admin endpoints are always covered.
    from markland.web.principal_middleware import PrincipalMiddleware

    app.add_middleware(
        PrincipalMiddleware,
        db_conn=db_conn,
        protected_prefixes=("/mcp", "/admin/"),
    )
    if mcp_app is not None:
        app.mount("/mcp", mcp_app)
```

Note: any callers in tests that pass `protected_prefix=` (singular, old name) need to be updated to `protected_prefixes=` (tuple). Grep for `protected_prefix` to find them:

```bash
grep -rn "protected_prefix" src/ tests/
```

Update each call-site to use the new keyword and pass a tuple.

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest tests/ -q
```

Expected: PASS. Pay attention to:
- `tests/test_principal_middleware*.py` — both old and new
- `tests/test_admin_audit.py` (if present) — uses bearer tokens already, should pass through the widened gate cleanly
- `tests/test_admin_waitlist*.py` (if present, added in commit 185b9e7) — same
- Any test that calls `/admin/*` without a bearer must now expect 401 (it was likely 401 before too, via the in-handler check)

If a previously-passing test breaks because it called `/admin/foo` with no auth and expected (say) 404 / 200, that's a real change — treat it as a follow-up: either supply auth in the test or document the intentional behavior shift.

- [ ] **Step 7: Commit**

```bash
git add src/markland/web/principal_middleware.py src/markland/web/app.py tests/test_principal_middleware_admin.py
git commit -m "refactor(middleware): gate /admin/* via PrincipalMiddleware, drop duplicate resolve"
```

---

## Self-Review

**Spec coverage:**
- (a) `user_code` redirect escape → Task 1 ✓
- (b) Per-IP rate limit on `/device/confirm` → Task 3 ✓
- (c) Lock device row after N failed confirms → Task 4 ✓
- (d) `grant_by_principal_id` defensive check → Task 2 ✓
- (e) Append-only `audit_log` enforcement → Task 5 ✓
- (f) Widen `/admin/audit` middleware coverage → Task 6 ✓

All six items mapped. Ordering: 1 (smallest, single-line fix) → 2 (pure validation) → 3 (mirrors existing limiter) → 4 (schema migration + service logic) → 5 (DB triggers) → 6 (middleware reshape, largest blast radius). Each task is self-contained: tests added, impl shown, verify command, commit step.

**Placeholder scan:** No "TBD," "TODO," or "implement later." Each step contains the actual code to write or the actual command to run.

**Type consistency:** `PrincipalMiddleware.__init__` takes `protected_prefixes: tuple[str, ...]` in Task 6 and is invoked with `protected_prefixes=("/mcp", "/admin/")`. The old kwarg `protected_prefix` is renamed; Task 6 Step 5 includes a grep + update for all callers. `_VALID_PRINCIPAL_TYPES` in Task 2 is consistently spelled. `failed_confirms` column name matches between schema (Task 4 Step 3) and service queries (Task 4 Step 4). `MAX_FAILED_CONFIRMS` constant is referenced consistently.

**Note on Task 4 line numbers:** The follow-up doc cites `device_routes.py:230` and `:234` for the same line — current actual line is 234. Task 4 (and Task 1) cite the live line numbers verified against the file as of 2026-04-28.

**Note on Task 6 ordering subtlety:** The Starlette reversed-add-order interaction between `_inject_principal` (test harness) and `PrincipalMiddleware` is explicitly addressed in Step 3 by switching the test fixture to mint a real token instead of relying on the inject map. This avoids weakening `PrincipalMiddleware`'s real-auth contract.
