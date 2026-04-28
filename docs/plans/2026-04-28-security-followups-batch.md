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

- [ ] **Step 1: Write the failing tests (service-level)**

Append two tests to `tests/test_device_flow.py`. The first verifies the lock-out fires when a pending row receives 5 failed authorize attempts. The second locks in the critical invariant that an already-authorized row must NOT be lockable — otherwise an attacker spamming `/device/confirm` after a legitimate auth could flip the row to `expired` before the legit `poll` mints the token, denying service to the real user.

```python
def test_authorize_locks_pending_row_after_five_failed_confirms(tmp_path):
    """A pending row that fails 5 authorize attempts gets locked to expired.

    Drive 5 TTL-expired hits against a single pending row. Each hit returns
    reason='expired' (natural TTL) and bumps failed_confirms. The 5th attempt
    additionally flips status='pending' -> 'expired' so subsequent polls
    short-circuit even if (somehow) TTL extended.
    """
    from markland.db import init_db
    from markland.service import device_flow

    conn = init_db(tmp_path / "t.db")
    # Manually insert a pending row whose TTL is already in the past — every
    # authorize() call hits the TTL-expired branch and bumps the counter.
    conn.execute(
        "INSERT INTO device_authorizations "
        "(device_code, user_code, status, created_at, expires_at) "
        "VALUES ('dc_test', 'AAAABBBB', 'pending', "
        "'2026-01-01T00:00:00Z', '2026-01-01T00:10:00Z')"
    )
    conn.commit()

    # First 4 fails: reason='expired' (TTL), row still 'pending'.
    for i in range(4):
        r = device_flow.authorize(conn, "AAAA-BBBB", user_id="usr_x")
        assert r.ok is False
        assert r.reason == "expired"
        row = conn.execute(
            "SELECT status, failed_confirms FROM device_authorizations "
            "WHERE device_code='dc_test'"
        ).fetchone()
        assert row[0] == "pending", f"after {i + 1} failures, status should still be pending"
        assert row[1] == i + 1

    # Fifth fail: lock fires, status flipped to 'expired'.
    r = device_flow.authorize(conn, "AAAA-BBBB", user_id="usr_x")
    assert r.ok is False
    assert r.reason == "expired"
    row = conn.execute(
        "SELECT status, failed_confirms FROM device_authorizations "
        "WHERE device_code='dc_test'"
    ).fetchone()
    assert row[0] == "expired"
    assert row[1] == 5


def test_authorize_does_not_lock_authorized_row(tmp_path):
    """An authorized row must NOT be locked by repeated already_authorized hits.

    Otherwise a third party who learned the user_code (e.g. shoulder-surfed
    after the human typed it) could spam /device/confirm post-auth and flip
    the row to 'expired' before the legitimate CLI's next poll, preventing
    token mint.
    """
    from markland.db import init_db
    from markland.service import device_flow
    from markland.service.users import create_user

    conn = init_db(tmp_path / "t.db")
    user = create_user(conn, email="a@x", display_name="A")
    start = device_flow.start(conn, base_url="https://markland.test")

    # Legit auth.
    r = device_flow.authorize(conn, start.user_code, user_id=user.id)
    assert r.ok is True

    # Attacker spams 10 retries — each returns already_authorized.
    for _ in range(10):
        r = device_flow.authorize(conn, start.user_code, user_id=user.id)
        assert r.ok is False
        assert r.reason == "already_authorized"

    # Row must remain 'authorized' so the legit poll can still mint the token.
    row = conn.execute(
        "SELECT status FROM device_authorizations WHERE device_code=?",
        (start.device_code,),
    ).fetchone()
    assert row[0] == "authorized"

    # And the legit poll still mints.
    poll_result = device_flow.poll(conn, start.device_code)
    assert poll_result["status"] == "authorized"
    assert "access_token" in poll_result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_device_flow.py::test_authorize_locks_pending_row_after_five_failed_confirms tests/test_device_flow.py::test_authorize_does_not_lock_authorized_row -v
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

Then modify `authorize` (lines 242-309). The new flow: on every non-OK return path that *found* a row, bump `failed_confirms`; if the bump pushes the count to `MAX_FAILED_CONFIRMS` **and the row is still in `pending` status**, flip status to `'expired'`. The pending-only gate is critical: an `'authorized'` row that's awaiting its first poll must NOT be lockable, because that would let a third party who learned the `user_code` flip the row to `expired` after a legit auth, denying token mint. Replace the function body with:

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
        """Increment failed_confirms; lock the row if it reaches the cap.

        Lock only applies when status is still 'pending' — never overwrite
        'authorized' (would deny token mint to the legitimate poll) or
        'expired'/'denied' (already terminal).
        """
        cur = conn.execute(
            "UPDATE device_authorizations "
            "SET failed_confirms = failed_confirms + 1 "
            "WHERE device_code = ? "
            "RETURNING failed_confirms",
            (device_code,),
        )
        new_count_row = cur.fetchone()
        new_count = new_count_row[0] if new_count_row else 0
        if new_count >= MAX_FAILED_CONFIRMS and status == "pending":
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

**Sequenced last** because changing middleware behavior touches every `/admin/*` route. Verified safe against existing tests:

- `tests/test_admin_audit.py` — fixture mints a real admin user via `create_user_token` and seeds `is_admin=1`; tests already expect 401/403/200. After the widening the middleware does the 401 instead of the handler, but the contract is unchanged.
- `tests/test_admin_waitlist.py` — same pattern (real admin token, expects 401/403/200).
- `tests/test_seo_helpers.py` — exercises `should_noindex("/admin/audit")` as a unit test on the helper, no HTTP involved.

No existing test uses `test_principal_by_token` to hit `/admin/*`, so the Starlette middleware-ordering interaction (`_inject_principal` runs inside `PrincipalMiddleware`) doesn't bite any current test.

**Files:**
- Modify: `src/markland/web/principal_middleware.py` (accept tuple of prefixes)
- Modify: `src/markland/web/app.py:432-452` (drop duplicate resolve), `:691-700` (always install, pass widened prefix set)
- Test: New file `tests/test_principal_middleware_admin.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_principal_middleware_admin.py`. The fixture mints a real admin token via `create_user_token` (mirroring `tests/test_admin_audit.py`) so `PrincipalMiddleware` can resolve it through the real auth path. We do NOT use `test_principal_by_token` here because the injection middleware runs *inside* `PrincipalMiddleware` in the request flow (Starlette reverses add-order), so the gate would see no principal and 401 before injection happens.

```python
"""PrincipalMiddleware should gate /admin/* identically to /mcp."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.auth import create_user_token
from markland.service.users import create_user
from markland.web.app import create_app


@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_USER_PER_MIN", "1000")
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")

    conn = init_db(tmp_path / "t.db")
    admin = create_user(conn, email="admin@m.dev", display_name="Admin")
    conn.execute("UPDATE users SET is_admin=1 WHERE id = ?", (admin.id,))
    conn.commit()
    _, admin_token = create_user_token(conn, user_id=admin.id, label="t")

    # mount_mcp=False — after Task 6 Step 5, PrincipalMiddleware is always
    # installed regardless of MCP, so /admin/* gating is exercised either way.
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test")
    client = TestClient(app)
    client.admin_token = admin_token
    return client


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
        "/admin/audit",
        headers={"Authorization": f"Bearer {admin_client.admin_token}"},
    )
    assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify expected starting state**

```bash
uv run pytest tests/test_principal_middleware_admin.py -v
```

Expected: the two 401 tests pass today (the in-handler resolve in `admin_audit` already enforces this); `test_admin_audit_with_valid_admin_bearer_succeeds` may also pass today since the handler-level resolve handles a valid token. The point of writing them now is to lock the contract before we move the auth out of the handler — if any of them regress during Steps 3-5, we know immediately.

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

**Test-fixture interaction note:** The pre-injected-principal short-circuit above (`getattr(request.state, "principal", None)`) is defensive — Starlette's reversed add-order means `_inject_principal` (added at `src/markland/web/app.py:682-689` for tests using `test_principal_by_token`) actually runs *inside* `PrincipalMiddleware` in the request flow. So the short-circuit doesn't help inject-map tests reach `/admin/*`; those tests would 401 at the gate. This is fine — no current test does that, and Step 1's fixture mints a real token instead.

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

Expected: PASS. Pre-verified (2026-04-28) call-sites:
- `tests/test_principal_middleware_admin.py` — new file, all three tests pass.
- `tests/test_admin_audit.py` (3 HTTP tests at lines 56-77) — already uses real `admin_token` / `user_token` minted via `create_user_token`. 401 anon, 403 non-admin, 200 admin all preserved.
- `tests/test_admin_waitlist.py` (4 HTTP tests at lines 40-82) — same pattern, same expectations preserved.
- `tests/test_seo_helpers.py:27` — unit test on `should_noindex("/admin/audit")` helper, no HTTP, unaffected.
- `grep -rn "/admin/" tests/` returned no other call-sites.

If any test breaks unexpectedly, do NOT reach for a quick fix that re-adds in-handler resolve — investigate whether the failure reflects a real contract change.

- [ ] **Step 7: Commit**

```bash
git add src/markland/web/principal_middleware.py src/markland/web/app.py tests/test_principal_middleware_admin.py
git commit -m "refactor(middleware): gate /admin/* via PrincipalMiddleware, drop duplicate resolve"
```

---

## Task 7: Prune the burned-down items from `docs/FOLLOW-UPS.md`

After Tasks 1-6 land, six entries in the Security section of `docs/FOLLOW-UPS.md` are obsolete and must be removed so the doc continues to reflect *open* follow-ups only. This is a docs-only change; per project convention it can be committed straight to `main` without a PR.

**Files:**
- Modify: `docs/FOLLOW-UPS.md` (Security section, current lines 8-57)

- [ ] **Step 1: Remove the six shipped entries**

Delete from `docs/FOLLOW-UPS.md`:
- "Unescaped `user_code` in device login redirect" bullet (Task 1)
- "Per-IP rate limit on device confirm" bullet (Task 3)
- "Lock / expire device row after N failed confirms" bullet (Task 4)
- "`grant_by_principal_id` defensive check" bullet (Task 2)
- "Append-only audit enforcement" bullet (Task 5)
- "`/admin/audit` duplicates bearer resolution" bullet (Task 6)

The remaining Security items (magic-link single-use, agent-token leak via query string, CSRF on save routes) stay — they are out of scope for this batch.

- [ ] **Step 2: Commit**

```bash
git add docs/FOLLOW-UPS.md
git commit -m "docs(follow-ups): remove security items shipped in 2026-04-28 batch"
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
- Burndown of those entries from `docs/FOLLOW-UPS.md` → Task 7 ✓

Ordering: 1 (smallest, single-line fix) → 2 (pure validation) → 3 (mirrors existing limiter) → 4 (schema migration + service logic) → 5 (DB triggers) → 6 (middleware reshape, largest blast radius) → 7 (docs cleanup). Each task is self-contained: tests added, impl shown, verify command, commit step.

**Placeholder scan:** No "TBD," "TODO," or "implement later." Each step contains the actual code to write or the actual command to run.

**Type consistency:** `PrincipalMiddleware.__init__` takes `protected_prefixes: tuple[str, ...]` in Task 6 and is invoked with `protected_prefixes=("/mcp", "/admin/")`. The old kwarg `protected_prefix` is renamed; Task 6 Step 5 includes a grep + update for all callers. `_VALID_PRINCIPAL_TYPES` in Task 2 is consistently spelled. `failed_confirms` column name matches between schema (Task 4 Step 3) and service queries (Task 4 Step 4). `MAX_FAILED_CONFIRMS` constant is referenced consistently.

**Task 4 lock-out semantics:** The lock fires only on rows with `status == "pending"`. Rows in `'authorized'`, `'expired'`, or `'denied'` status are never overwritten — the failed_confirms counter still increments (defensible signal) but status stays put. This protects the legitimate `poll → mint token` path against a third party who learned the `user_code` and spams `/device/confirm` after a real auth. A dedicated test (`test_authorize_does_not_lock_authorized_row`) locks in this invariant.

**Task 4 line numbers:** The follow-up doc cites `device_routes.py:230` and `:234` for the same line — current actual line is 234. Task 4 (and Task 1) cite live line numbers verified against the file as of 2026-04-28.

**Task 6 verification:** Pre-checked existing `/admin/*` test call-sites (`tests/test_admin_audit.py`, `tests/test_admin_waitlist.py`, `tests/test_seo_helpers.py`). All HTTP-level tests already use real bearer tokens minted via `create_user_token`, so widening `PrincipalMiddleware` to gate `/admin/*` does not require updating any existing test. The new `tests/test_principal_middleware_admin.py` fixture follows the same real-token pattern to stay consistent.
