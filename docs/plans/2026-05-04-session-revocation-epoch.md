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
the bulk of this work; keep the old `read_session(token, *, secret)`
signature working for tests that don't care about revocation (they
pass `conn=None`, which skips the epoch check). Production callsites
MUST pass `conn`; tests don't have to.

**Connection-acquisition pattern:** routes in `auth_routes.py` and
peers don't use FastAPI `Depends(get_conn)`. They capture `db_conn`
from the route-factory closure (see `verify` and `verify_page` in
`auth_routes.py:139,169`). All examples in this plan use closure
`db_conn`, not `Depends`. Don't introduce a new pattern.

**Atomicity warning:** Task 4 (logout bumps the epoch) and Task 5
(issuance embeds the user's current epoch) **MUST land in a single
deploy**. Between Task 4 shipping and Task 5 shipping, a user's first
logout would bump the column to 1, but new sign-ins would still
issue cookies with `epoch=0` — locking the user out until secret
rotation. Tasks 4 and 5 are presented as separate sections for
clarity, but commit them together (or rebase before opening the PR
so the PR has a single "feat: logout invalidates outstanding cookies"
commit covering both).

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

def _read_user_epoch(conn: sqlite3.Connection, user_id: str) -> int | None:
    """Return the user's current session_epoch, or None if user does not exist.

    Callers decide what missing-user means:
    - `read_session`: missing user → InvalidSession (cookie references a
      deleted account; revoke).
    - `issue_session`: missing user → epoch=0 (test fixtures issue
      sessions for synthetic user_ids that aren't in the DB; this keeps
      those tests working without forcing them to seed the users table).
    """
    row = conn.execute(
        "SELECT session_epoch FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if row is None:
        return None
    return int(row[0])

def bump_session_epoch(conn: sqlite3.Connection, *, user_id: str) -> int:
    """Increment the user's session_epoch and return the new value.

    Called from /api/auth/logout (and from a future
    /api/auth/revoke-all-sessions endpoint). All cookies whose embedded
    epoch < new epoch will be rejected by read_session on the next
    request.

    Definition appears below in this same task — see the RETURNING-based
    version. (Don't duplicate the function.)
    """

def issue_session(
    user_id: str,
    *,
    secret: str,
    max_age_seconds: int = SESSION_MAX_AGE_SECONDS,
    conn: sqlite3.Connection | None = None,
) -> str:
    """Return a signed cookie value for `user_id`.

    If `conn` is provided, the user's current session_epoch is embedded
    in the payload. If omitted, embeds epoch=0 — equivalent to "fresh
    user," matched by any conn-aware reader on a never-logged-out
    account. Production callers MUST pass conn; the conn=None path
    exists for unit tests that don't seed the users table.

    Unknown user_id (no row in users): embeds epoch=0 (does NOT raise).
    Tests issue sessions for synthetic ids; rejecting them here would
    force every test that issues a session to seed a users row first.
    """
    if not secret:
        raise ValueError("session secret must be non-empty")
    if conn is not None:
        e = _read_user_epoch(conn, user_id)
        epoch = e if e is not None else 0
    else:
        epoch = 0
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
        if current is None:
            # Cookie references a deleted account — revoke.
            raise InvalidSession("user not found")
        if cookie_epoch < current:
            raise InvalidSession("session revoked")
    return payload
```

Also strengthen `bump_session_epoch` to use SQLite's `RETURNING`
clause (≥ 3.35; we're on a modern Python build) so the bump is a
single atomic statement instead of `UPDATE` + `SELECT`:

```python
def bump_session_epoch(conn: sqlite3.Connection, *, user_id: str) -> int:
    """Increment the user's session_epoch and return the new value.

    Atomic via RETURNING — no read-after-write race with another
    concurrent bump.
    """
    row = conn.execute(
        "UPDATE users SET session_epoch = session_epoch + 1 "
        "WHERE id = ? RETURNING session_epoch",
        (user_id,),
    ).fetchone()
    if row is None:
        raise InvalidSession("user not found")
    conn.commit()
    return int(row[0])
```

- [ ] **Step 4: Update the module docstring**

The current top-of-module docstring in `service/sessions.py` says:

> Cookie name: `mk_session`. Payload: `{"user_id": str, "exp": iso8601}`.
> Signed with `MARKLAND_SESSION_SECRET`. 30-day default lifetime.
> Rotating the secret invalidates all outstanding sessions.

Update to reflect:
- Payload now `{"user_id": str, "exp": iso8601, "epoch": int}`.
- `bump_session_epoch(conn, user_id=...)` invalidates outstanding
  cookies for one user; secret rotation still invalidates all
  globally.
- Production callers MUST pass `conn` to `read_session` and
  `issue_session`; the `conn=None` path is for unit tests that don't
  seed users.

- [ ] **Step 5: Run tests to verify passing**

Run: `.venv/bin/pytest tests/test_service_sessions.py -v`
Expected: PASS — including the `_without_conn_skips_revocation_check`
backwards-compat test.

- [ ] **Step 6: Commit**

```bash
git add src/markland/service/sessions.py tests/test_service_sessions.py
git commit -m "feat(sessions): embed and verify session_epoch (markland-bul)"
```

---

## Task 3 — Wire `conn` through every `read_session` caller

**Files:**
- Modify: every file in `src/markland/web/` that calls `read_session` (13 sites — see Pre-work). Each route handler is wired through a `create_*_router(db_conn=…)` factory in `web/app.py`; the `db_conn` is captured by the handler closure, **not** injected via `Depends(get_conn)`.
- Modify: `src/markland/service/sessions.py:get_session` — already takes a `request`; extend to accept an optional `conn` kwarg and forward it to `read_session`.
- Tests: existing route tests should continue to pass.

The current pattern in routes is:

```python
def create_foo_router(*, db_conn, session_secret, ...):
    router = APIRouter()

    @router.get("/foo")
    def some_route(request: Request):
        cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
        try:
            payload = read_session(cookie, secret=session_secret)
        except InvalidSession:
            ...
    return router
```

`db_conn` is already available in every handler's closure (every
factory takes it). The fix is mechanical: pass `conn=db_conn` to
`read_session`. Do NOT introduce `Depends(get_conn)` — that's not
how this codebase wires DB access.

- [ ] **Step 1: Locate the 13 callsites.**

Run: `grep -rn "read_session" src/markland/web/`

You should see roughly:
- `auth_routes.py` (logout — touched in Task 4)
- `dashboard.py`
- `device_routes.py`
- `identity_routes.py` (2 sites)
- `invite_routes.py` (2 sites)
- `presence_api.py`
- `routes_agents.py` (2 sites)
- `save_routes.py`
- … plus internal helpers in the same files

- [ ] **Step 2: Update each callsite to pass `conn=db_conn` to `read_session`.**

Example diff for `dashboard.py`:

```diff
-payload = read_session(cookie, secret=session_secret)
+payload = read_session(cookie, secret=session_secret, conn=db_conn)
```

The variable name in scope is `db_conn` (closure), not `conn` —
mirror what's already there.

- [ ] **Step 3: Update `service/sessions.py:get_session`** — it currently
  reads a `request`, calls `read_session`, returns `SessionInfo`. Add
  an optional `conn: sqlite3.Connection | None = None` parameter and
  forward it. Update callers via `grep -rn "get_session" src/` — only
  a handful, each with closure access to `db_conn`.

- [ ] **Step 4: Run full suite**

Run: `.venv/bin/pytest -q --tb=short`
Expected: full pass. Pre-existing flake on
`test_pending_intent.py::test_read_rejects_tampered_token` may
require a single retry.

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/ src/markland/service/sessions.py
git commit -m "feat(web): pass db_conn to read_session for revocation checks (markland-bul)"
```

**Note on test callsites:** Tests that call `read_session(cookie, secret=...)`
without `conn` continue to work — the conn=None branch skips the
epoch check. **No test files need updating in this task.** Only
production code in `src/markland/web/` is in scope.

---

## Task 4 — Logout bumps + issuance embeds (atomic; ship together)

**⚠ Atomicity:** This task covers both the logout-side bump AND the
issuance-side epoch read. They MUST land in a single commit (or PR).
A deploy that ships only the bump would lock users out: their first
logout sets epoch=1, but the issuance path still hardcodes epoch=0,
so every subsequent sign-in is born stale and rejected.

**Files:**
- Modify: `src/markland/web/auth_routes.py` — three handlers:
  - `verify` (JSON `/api/auth/verify`, ~line 139): calls `issue_session`.
  - `verify_page` (GET `/verify`, ~line 169): calls `issue_session`.
  - `logout` (POST `/api/auth/logout`, ~line 195): currently only
    deletes the cookie.
- Test: `tests/test_auth_routes.py`

**Test helper to add first** (used by both tests in this task):

```python
# tests/test_auth_routes.py — add near other helpers
def _last_magic_link_token(db_conn) -> str:
    """Read the most recently issued magic-link token from the DB.

    Magic-link tokens are persisted hashed in `magic_link_consumed`
    (PR #59) but the un-consumed token is held in the email payload —
    we synthesize it via the same code path the email dispatcher uses.

    NOTE FOR IMPLEMENTER: read how existing tests
    (`tests/test_auth_routes.py`, `tests/test_service_magic_link.py`)
    obtain the issued token and adapt. Most likely you can just call
    `make_magic_link_token(email, secret=session_secret)` directly —
    this helper exists in `service/magic_link.py`. If so, the helper
    above can be replaced inline at each callsite.
    """
    raise NotImplementedError("Replace with the codebase's actual pattern.")
```

(The implementer should substitute the actual mechanism used in
existing tests — most likely calling `make_magic_link_token` directly
rather than fishing for an enqueued email. Just naming the helper
here so the test bodies below can reference it.)

- [ ] **Step 1: Write the failing tests**

```python
def test_logout_invalidates_outstanding_cookie(db_conn):
    """A signed-in user logs out; the *previously issued* cookie no longer
    works on a subsequent request from a different tab."""
    client = TestClient(app)
    # Seed the user.
    db_conn.execute(
        "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
        ("usr_alice", "alice@test", "2026-01-01T00:00:00+00:00"),
    )
    db_conn.commit()
    # Issue a session directly (bypassing magic-link UI for test simplicity).
    cookie_value = issue_session("usr_alice", secret=session_secret, conn=db_conn)
    # 1. Cookie works.
    r = client.get("/api/me", cookies={SESSION_COOKIE_NAME: cookie_value})
    assert r.status_code == 200
    # 2. Logout from "another tab" with the same cookie.
    client.post("/api/auth/logout", cookies={SESSION_COOKIE_NAME: cookie_value})
    # 3. Old cookie no longer works.
    r = client.get("/api/me", cookies={SESSION_COOKIE_NAME: cookie_value})
    assert r.status_code == 401


def test_new_cookie_after_logout_carries_current_epoch(db_conn):
    """Sign in (epoch 0). Logout (bump to 1). Sign in again — new cookie works."""
    client = TestClient(app)
    db_conn.execute(
        "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
        ("usr_bob", "bob@test", "2026-01-01T00:00:00+00:00"),
    )
    db_conn.commit()
    cookie1 = issue_session("usr_bob", secret=session_secret, conn=db_conn)
    client.post("/api/auth/logout", cookies={SESSION_COOKIE_NAME: cookie1})
    cookie2 = issue_session("usr_bob", secret=session_secret, conn=db_conn)
    # Old cookie dead, new cookie alive.
    r = client.get("/api/me", cookies={SESSION_COOKIE_NAME: cookie1})
    assert r.status_code == 401
    r = client.get("/api/me", cookies={SESSION_COOKIE_NAME: cookie2})
    assert r.status_code == 200
```

(Issuing the session directly via `issue_session()` rather than
walking the full magic-link flow keeps these tests crisp. The
end-to-end magic-link flow is already covered by existing tests in
this file; we don't need to re-prove it here.)

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/pytest tests/test_auth_routes.py -v -k "logout_invalidates or new_cookie_after_logout"`
Expected: BOTH FAIL — old cookie still works on logout test;
post-logout sign-in cookie hits epoch mismatch.

- [ ] **Step 3: Update logout, verify, and verify_page handlers**

In `auth_routes.py`:

```python
from markland.service.sessions import bump_session_epoch  # add to imports

# Inside create_auth_router(*, db_conn, session_secret, ...):

@router.post("/api/auth/verify")
def verify(...):
    ...
-   cookie = issue_session(user.id, secret=session_secret)
+   cookie = issue_session(user.id, secret=session_secret, conn=db_conn)
    ...

@router.get("/verify")
def verify_page(...):
    ...
-   cookie = issue_session(user.id, secret=session_secret)
+   cookie = issue_session(user.id, secret=session_secret, conn=db_conn)
    ...

@router.post("/api/auth/logout")
def logout(request: Request):
    cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
    if cookie:
        try:
            payload = read_session(cookie, secret=session_secret, conn=db_conn)
            bump_session_epoch(db_conn, user_id=payload["user_id"])
        except InvalidSession:
            # Cookie is already invalid (expired, revoked, tampered, or
            # references a deleted user) — nothing to bump. The legitimate
            # user can't be locked out by an attacker hitting logout with
            # a stolen cookie because that bump kills the attacker too.
            pass
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response
```

Use closure `db_conn`, NOT `Depends(get_conn)` — that's not the
pattern in this codebase.

- [ ] **Step 4: Run tests to verify passing**

Run: `.venv/bin/pytest tests/test_auth_routes.py -v -k "logout_invalidates or new_cookie_after_logout"`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/pytest -q --tb=short`
Expected: full pass (mod the known flake).

- [ ] **Step 6: Commit (single commit covering both halves)**

```bash
git add src/markland/web/auth_routes.py tests/test_auth_routes.py
git commit -m "feat(auth): logout invalidates outstanding cookies via session_epoch (markland-bul)"
```

**One commit, both halves.** Don't split this — see atomicity warning
at top of task.

---

## Task 5 — `/api/auth/revoke-all-sessions` (optional follow-up)

**Rationale:** `bump_session_epoch` is already exported. A
`/api/auth/revoke-all-sessions` endpoint is the "I think my session
was leaked" UX, distinct from the "I'm signing out" UX that logout
covers. Different button in settings, same primitive.

This is **explicitly optional** for the bead-bul PR. Add it if scope
feels easy; defer to a follow-up bead if not. The current cookie does
NOT need to be re-issued by this endpoint — calling tabs can refresh
and re-authenticate via magic link, which is what we want when
"my session was compromised" anyway.

If you do it:

- [ ] **Step 1: Write the failing test** that issues a session,
  POSTs `/api/auth/revoke-all-sessions`, then asserts the original
  cookie is now 401.
- [ ] **Step 2: Add the route** — same logic as logout but no
  RedirectResponse (return 200/204 with empty body or `{"ok": true}`).
- [ ] **Step 3: Run tests, commit.**

If skipping, file a follow-up bead `revoke-all-sessions endpoint`
and reference it in the PR body.

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

## Rollback

If a bug surfaces post-deploy, revert the deploy (or the merge commit).
The `users.session_epoch` column stays — it's harmless on rollback
because:
- Old code never reads it.
- New cookies issued during the broken window have an `epoch` field;
  old code ignores unknown payload fields.
- The column will pick up where it left off on the next forward
  deploy.

No migration to undo. No data to back out.

## CSRF tokens are NOT epoch-bound (deliberate)

`make_csrf_token` / `verify_csrf_token` (signed by the same secret
but separate salt, 1-hour lifetime) are not coupled to the epoch.
After a logout, an attacker holding a stolen CSRF token has up to 1
hour of validity remaining — but they no longer have a valid session
cookie either, so any state-changing route still rejects them on
session check first. Acceptable for v1.

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
