# Server-side Session Revocation (Epoch) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Bead:** `markland-bul` (P2; deferred from PR #64 P1+P2 batch).

**Goal:** Make `POST /api/auth/logout` invalidate the signed cookie
*server-side* so that a stolen cookie cannot be replayed after the
user has signed out, even though the cookie's signature is still
within the 30-day expiry window.

**Architecture:** Add a `session_epoch` integer column on the `users`
table. Embed the user's current epoch in every issued session
cookie's payload. On every `read_session` call, fetch the user's
current epoch from the DB and reject the cookie if its embedded epoch
is older. Logout bumps the column.

**Tech stack:** SQLite (existing schema, `CREATE TABLE IF NOT EXISTS`
pattern + `ALTER TABLE … ADD COLUMN` for the migration), itsdangerous
(existing session signer), FastAPI/Starlette routes (existing).

---

## Pre-work — read these first

These touch points exist in the current codebase. The implementer
should know them before starting:

- `src/markland/service/sessions.py` — `issue_session`,
  `read_session`, `get_session`, `make_session_cookie_value`. The
  payload today is `{"user_id": str, "exp": iso8601}`. We will add an
  `epoch: int` field.
- `src/markland/service/auth.py` — `Principal` dataclass,
  `resolve_token`. Not directly affected but `read_session` callers
  often live next to `resolve_token` callers.
- `src/markland/web/auth_routes.py` — `/api/auth/verify` (issues
  session post-magic-link), `/verify` (browser variant), `/api/auth/logout`.
  Logout currently only deletes the cookie.
- `src/markland/web/{identity_routes,dashboard,save_routes,device_routes,presence_api,routes_agents,invite_routes}.py`
  — every site that calls `read_session(...)`. There are 13 such
  callsites today (`grep -rn "read_session" src/markland/web/`).
- `src/markland/db.py` — `init_db()` runs all `CREATE TABLE IF NOT
  EXISTS`. Several places use the pattern
  `try: conn.execute("ALTER TABLE … ADD COLUMN …"); except sqlite3.OperationalError: pass`
  for additive migrations. Use that pattern for the new column.

**Important constraint:** `read_session` is currently pure (no DB
access). Adding the epoch check requires plumbing a `conn:
sqlite3.Connection` argument through every caller. That refactor is
the bulk of this work; do it carefully and keep the old
`read_session(token, *, secret)` signature working for tests that
don't care about revocation (they pass `conn=None`, which skips the
epoch check and emits a deprecation warning at module-import time).

---

## Task 1 — Schema migration: `users.session_epoch`

**Files:**
- Modify: `src/markland/db.py`
- Test: `tests/test_db_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_schema.py — add to existing test class
def test_users_table_has_session_epoch_column(self):
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    assert "session_epoch" in cols

def test_users_session_epoch_defaults_to_zero(self):
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
                 ("usr_test1234567890", "a@b.test", "2026-01-01T00:00:00+00:00"))
    row = conn.execute("SELECT session_epoch FROM users WHERE id = ?",
                       ("usr_test1234567890",)).fetchone()
    assert row[0] == 0
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/pytest tests/test_db_schema.py::TestSchema::test_users_table_has_session_epoch_column -v`
Expected: FAIL with KeyError or AssertionError.

- [ ] **Step 3: Add the column to `init_db()`**

In `db.py`, immediately after the `CREATE TABLE IF NOT EXISTS users
(…)` block (or wherever the existing additive ALTERs for `users`
live), append:

```python
# Additive migration: session_epoch (markland-bul, 2026-05-04).
# Bumped on logout to invalidate outstanding signed cookies whose
# embedded epoch < user's current epoch.
try:
    conn.execute(
        "ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0"
    )
except sqlite3.OperationalError:
    # Column already exists (idempotent boot).
    pass
```

- [ ] **Step 4: Run tests to verify passing**

Run: `.venv/bin/pytest tests/test_db_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/markland/db.py tests/test_db_schema.py
git commit -m "feat(db): add users.session_epoch column for session revocation (markland-bul)"
```

---

## Task 2 — `service/sessions.py`: embed and check epoch

**Files:**
- Modify: `src/markland/service/sessions.py`
- Test: `tests/test_service_sessions.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_service_sessions.py
def test_issue_session_embeds_epoch_zero_when_conn_omitted():
    cookie = issue_session("usr_test", secret="s")
    payload = read_session(cookie, secret="s")
    assert payload.get("epoch") == 0

def test_read_session_rejects_cookie_with_stale_epoch(tmp_path):
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
                 ("usr_t", "a@b", "2026-01-01T00:00:00+00:00"))
    conn.commit()
    cookie = issue_session("usr_t", secret="s", conn=conn)
    bump_session_epoch(conn, user_id="usr_t")
    with pytest.raises(InvalidSession, match="revoked"):
        read_session(cookie, secret="s", conn=conn)

def test_read_session_accepts_cookie_with_current_epoch(tmp_path):
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    conn.execute("INSERT INTO users (id, email, created_at, session_epoch) "
                 "VALUES (?, ?, ?, ?)",
                 ("usr_t", "a@b", "2026-01-01T00:00:00+00:00", 5))
    conn.commit()
    cookie = issue_session("usr_t", secret="s", conn=conn)
    payload = read_session(cookie, secret="s", conn=conn)
    assert payload["user_id"] == "usr_t"
    assert payload["epoch"] == 5

def test_read_session_without_conn_skips_revocation_check():
    # Backwards-compat: callers that don't pass conn get the old behaviour.
    cookie = issue_session("usr_t", secret="s")
    payload = read_session(cookie, secret="s")
    assert payload["user_id"] == "usr_t"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/pytest tests/test_service_sessions.py -v -k "epoch or revoked"`
Expected: FAIL on `bump_session_epoch` (NameError), then on epoch
checks.

- [ ] **Step 3: Implement `bump_session_epoch`, extend `issue_session` and `read_session`**

In `service/sessions.py`:

```python
import sqlite3

def _read_user_epoch(conn: sqlite3.Connection, user_id: str) -> int:
    row = conn.execute(
        "SELECT session_epoch FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if row is None:
        # User was deleted; treat as fully revoked.
        raise InvalidSession("user not found")
    return int(row[0])

def bump_session_epoch(conn: sqlite3.Connection, *, user_id: str) -> int:
    """Increment the user's session_epoch and return the new value.

    Called from /api/auth/logout (and from a future /api/auth/revoke-all-sessions
    endpoint). All cookies whose embedded epoch < new epoch will be rejected
    by read_session on the next request.
    """
    cur = conn.execute(
        "UPDATE users SET session_epoch = session_epoch + 1 WHERE id = ?",
        (user_id,),
    )
    if cur.rowcount == 0:
        raise InvalidSession("user not found")
    conn.commit()
    new = conn.execute(
        "SELECT session_epoch FROM users WHERE id = ?", (user_id,)
    ).fetchone()[0]
    return int(new)

def issue_session(
    user_id: str,
    *,
    secret: str,
    max_age_seconds: int = SESSION_MAX_AGE_SECONDS,
    conn: sqlite3.Connection | None = None,
) -> str:
    """Return a signed cookie value for `user_id`.

    If `conn` is provided, the user's current session_epoch is embedded
    in the payload. If omitted, the cookie is issued with epoch=0 (which
    will fail revocation checks on any user whose epoch has been bumped
    — i.e. the cookie is born stale; this is intentional for tests).
    """
    if not secret:
        raise ValueError("session secret must be non-empty")
    epoch = _read_user_epoch(conn, user_id) if conn is not None else 0
    serializer = Serializer(secret, salt=_SALT)
    exp = (datetime.now(timezone.utc) + timedelta(seconds=max_age_seconds)).isoformat()
    raw = serializer.dumps({"user_id": user_id, "exp": exp, "epoch": epoch})
    return _signer(secret).sign(raw.encode("utf-8")).decode("utf-8")

def read_session(
    token: str,
    *,
    secret: str,
    max_age_seconds: int = SESSION_MAX_AGE_SECONDS,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Parse a cookie value. Raises `InvalidSession` on any failure.

    If `conn` is provided, also verifies the embedded epoch matches the
    user's current session_epoch — i.e. enforces server-side revocation.
    Without `conn`, the epoch check is skipped (backwards-compat for
    tests; production callers MUST pass conn).
    """
    if not token:
        raise InvalidSession("empty session token")
    try:
        unsigned = _signer(secret).unsign(token, max_age=max_age_seconds)
    except SignatureExpired as e:
        raise InvalidSession("session expired") from e
    except BadSignature as e:
        raise InvalidSession("bad signature") from e
    try:
        serializer = Serializer(secret, salt=_SALT)
        payload = serializer.loads(unsigned.decode("utf-8"))
    except BadSignature as e:
        raise InvalidSession("bad payload") from e
    if not isinstance(payload, dict) or "user_id" not in payload:
        raise InvalidSession("malformed payload")
    if conn is not None:
        cookie_epoch = int(payload.get("epoch", 0))
        current = _read_user_epoch(conn, payload["user_id"])
        if cookie_epoch < current:
            raise InvalidSession("session revoked")
    return payload
```

- [ ] **Step 4: Run tests to verify passing**

Run: `.venv/bin/pytest tests/test_service_sessions.py -v`
Expected: PASS — including the `_without_conn_skips_revocation_check`
backwards-compat test.

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/sessions.py tests/test_service_sessions.py
git commit -m "feat(sessions): embed and verify session_epoch (markland-bul)"
```

---

## Task 3 — Wire `conn` through every `read_session` caller

**Files:**
- Modify: every file in `src/markland/web/` that calls `read_session` (13 sites — see Pre-work). For each, ensure a `sqlite3.Connection` is available in scope and passed.
- Tests: existing route tests should continue to pass.

The current pattern in routes is:

```python
def some_route(request: Request):
    cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
    try:
        payload = read_session(cookie, secret=session_secret)
    except InvalidSession:
        ...
```

Most routes already have access to a `conn` via dependency injection
(grep for `conn: sqlite3.Connection = Depends(get_conn)` in adjacent
handlers). For each callsite:

- [ ] **Step 1: For each of the 13 callsites, identify how `conn` is obtained.**

Run: `grep -rn "read_session" src/markland/web/`
For each result, inspect the surrounding handler. If the handler
already takes a `conn` Depends, pass it through. If not, add the
Depends.

- [ ] **Step 2: Update each callsite to pass `conn=conn` to `read_session`.**

Example diff for one site:

```diff
-payload = read_session(cookie, secret=session_secret)
+payload = read_session(cookie, secret=session_secret, conn=conn)
```

- [ ] **Step 3: Update `get_session` in `service/sessions.py`** so it
  too accepts an optional `conn` and passes it through. Update the few
  callers that use `get_session` (search via `grep -rn "get_session" src/`).

- [ ] **Step 4: Run full suite**

Run: `.venv/bin/pytest -q --tb=short`
Expected: full pass. Pre-existing flake on
`test_pending_intent.py::test_read_rejects_tampered_token` may
require a single retry.

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/ src/markland/service/sessions.py
git commit -m "feat(web): pass conn to read_session for revocation checks (markland-bul)"
```

---

## Task 4 — Logout bumps the epoch

**Files:**
- Modify: `src/markland/web/auth_routes.py` (the `/api/auth/logout` handler)
- Test: `tests/test_auth_routes.py`

- [ ] **Step 1: Write the failing test**

```python
def test_logout_invalidates_outstanding_cookie():
    """A signed-in user logs out; the *previously issued* cookie no longer
    works on a subsequent request from a different tab."""
    client = TestClient(app)
    # 1. Sign in and capture the cookie.
    client.post("/api/auth/magic-link", json={"email": "alice@test"})
    token = _last_magic_link_token()
    r = client.get(f"/verify?token={token}")
    cookie_value = r.cookies.get(SESSION_COOKIE_NAME)
    # 2. Cookie works.
    r = client.get("/api/me", cookies={SESSION_COOKIE_NAME: cookie_value})
    assert r.status_code == 200
    # 3. Logout from another tab.
    client.post("/api/auth/logout", cookies={SESSION_COOKIE_NAME: cookie_value})
    # 4. Old cookie no longer works.
    r = client.get("/api/me", cookies={SESSION_COOKIE_NAME: cookie_value})
    assert r.status_code == 401
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/pytest tests/test_auth_routes.py::test_logout_invalidates_outstanding_cookie -v`
Expected: FAIL — old cookie still works on step 4.

- [ ] **Step 3: Update `/api/auth/logout`**

In `auth_routes.py`:

```python
from markland.service.sessions import bump_session_epoch  # add to imports

@router.post("/api/auth/logout")
def logout(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
    if cookie:
        try:
            payload = read_session(cookie, secret=session_secret, conn=conn)
            bump_session_epoch(conn, user_id=payload["user_id"])
        except InvalidSession:
            # Cookie is already invalid (expired, revoked, tampered) — fine.
            pass
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response
```

- [ ] **Step 4: Run tests to verify passing**

Run: `.venv/bin/pytest tests/test_auth_routes.py::test_logout_invalidates_outstanding_cookie -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/pytest -q --tb=short`
Expected: full pass.

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/auth_routes.py tests/test_auth_routes.py
git commit -m "feat(auth): logout bumps session_epoch to revoke outstanding cookies (markland-bul)"
```

---

## Task 5 — Issue cookies with the user's current epoch

**Files:**
- Modify: `src/markland/web/auth_routes.py` (`/api/auth/verify` and
  `/verify` — both call `issue_session` post-magic-link)
- Test: extend `tests/test_auth_routes.py`

The previous task fixed logout but didn't yet update issuance — every
new cookie is currently issued with `epoch=0`. After Task 4, a user's
first logout bumps the column to 1, and **every cookie issued
afterwards must carry epoch=1 too**, otherwise new sign-ins are
born stale.

- [ ] **Step 1: Write the failing test**

```python
def test_new_cookie_after_logout_carries_current_epoch():
    """Sign in (epoch 0). Logout (bump to 1). Sign in again — new cookie works."""
    client = TestClient(app)
    # First sign-in.
    client.post("/api/auth/magic-link", json={"email": "bob@test"})
    t1 = _last_magic_link_token()
    r1 = client.get(f"/verify?token={t1}")
    cookie1 = r1.cookies.get(SESSION_COOKIE_NAME)
    # Logout.
    client.post("/api/auth/logout", cookies={SESSION_COOKIE_NAME: cookie1})
    # Second sign-in.
    client.post("/api/auth/magic-link", json={"email": "bob@test"})
    t2 = _last_magic_link_token()
    r2 = client.get(f"/verify?token={t2}")
    cookie2 = r2.cookies.get(SESSION_COOKIE_NAME)
    # Old cookie dead, new cookie alive.
    r = client.get("/api/me", cookies={SESSION_COOKIE_NAME: cookie1})
    assert r.status_code == 401
    r = client.get("/api/me", cookies={SESSION_COOKIE_NAME: cookie2})
    assert r.status_code == 200
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_auth_routes.py::test_new_cookie_after_logout_carries_current_epoch -v`
Expected: FAIL — second sign-in's cookie has epoch=0, but user's
current epoch is 1, so `read_session` rejects it.

- [ ] **Step 3: Update issuance sites to pass `conn`**

In `auth_routes.py` — both `/api/auth/verify` (JSON) and `/verify`
(GET) call `issue_session(user.id, secret=session_secret)`. Change
to:

```diff
-cookie = issue_session(user.id, secret=session_secret)
+cookie = issue_session(user.id, secret=session_secret, conn=conn)
```

Also check anywhere else `issue_session` or `make_session_cookie_value`
is called (`grep -rn "issue_session\|make_session_cookie_value" src/`).

- [ ] **Step 4: Run tests to verify passing**

Run: `.venv/bin/pytest tests/test_auth_routes.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/pytest -q --tb=short`

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/auth_routes.py tests/test_auth_routes.py
git commit -m "feat(auth): issue cookies with user's current session_epoch (markland-bul)"
```

---

## Task 6 — Add `/api/auth/revoke-all-sessions` (optional but cheap)

**Rationale:** Now that `bump_session_epoch` exists, exposing it as
an explicit endpoint is one route handler. Useful for the
"compromised account" case (forget the device, kill all sessions on
all browsers). Skip if scope feels tight — this is a P3-ish
quality-of-life addition. The bead doesn't require it.

If you do it:

- [ ] **Step 1: Write the failing test** that creates a session,
  POSTs `/api/auth/revoke-all-sessions`, then asserts the original
  cookie is now 401.

- [ ] **Step 2: Add the route** — same shape as logout but doesn't
  delete the cookie locally (the user is signing out other browsers,
  not this one — though the next request from THIS browser will also
  401 because the current cookie is stale; the route should
  re-issue a fresh cookie for the calling tab).

- [ ] **Step 3: Run tests, commit.**

If skipping, document in the PR body that this endpoint is a
follow-up.

---

## Task 7 — Update `service/sessions.py` docstring

**Files:**
- Modify: top-of-module docstring in `src/markland/service/sessions.py`

- [ ] **Step 1: Update the docstring** to reflect the new payload
  shape (`{"user_id", "exp", "epoch"}`) and revocation semantics.
  Current docstring claims "Rotating the secret invalidates all
  outstanding sessions" — that's still true but no longer the only
  way; mention `bump_session_epoch` as the per-user equivalent.

- [ ] **Step 2: Commit (no test needed for a docstring).**

```bash
git add src/markland/service/sessions.py
git commit -m "docs(sessions): document session_epoch revocation (markland-bul)"
```

---

## Self-review checklist

Before opening the PR, walk this list:

- [ ] Every `read_session` callsite passes `conn`. (`grep -rn "read_session" src/markland/web/` should show `conn=conn` on each.)
- [ ] Every `issue_session` callsite passes `conn`.
- [ ] `bump_session_epoch` is called from every place that should kill outstanding sessions: at minimum logout. Optionally a "revoke all" endpoint.
- [ ] The `users.session_epoch` ALTER is wrapped in `try/except sqlite3.OperationalError: pass` and lives next to other additive migrations.
- [ ] No new SQL string interpolation; only `?` placeholders.
- [ ] No tokens, magic-link strings, or session payloads in any new log line.
- [ ] Full test suite green.
- [ ] At least one integration-level test that covers: sign in → logout → old cookie 401, sign in again → new cookie 200.

---

## PR checklist

```bash
git push -u origin feat/session-revocation-epoch
gh pr create --base main --title "feat(auth): server-side session revocation epoch (markland-bul)" --body "$(cat <<'EOF'
## Summary
Closes the cookie-still-valid-after-logout gap. `users.session_epoch`
column is bumped on logout; cookie payload embeds the user's epoch at
issue time; `read_session` rejects cookies whose epoch < current.

Closes markland-bul (P2; deferred from PR #64 batch).

## Test plan
- [x] New integration test: sign-in → logout → old cookie 401.
- [x] New integration test: sign-in → logout → sign-in again → new
  cookie 200 (issuance picks up bumped epoch).
- [x] Unit tests on `bump_session_epoch`, `read_session` with stale
  epoch, `read_session` without conn (backwards compat).
- [x] Full suite green.

## Notes
- Fresh-deploy DBs and existing-deploy DBs both work via the
  `ALTER TABLE … ADD COLUMN … DEFAULT 0` pattern.
- Existing cookies issued before this PR have no `epoch` field;
  `read_session` treats missing-epoch as 0, so they remain valid
  until their first logout (which bumps to 1).

EOF
)"
```

Stop after PR is opened. Do NOT merge.
