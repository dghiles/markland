# Magic-Link Single-Use Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make magic-link tokens truly single-use server-side, so a captured link cannot be replayed within its 15-minute window. Closes the documented `/security` gap and the `docs/FOLLOW-UPS.md` "Magic-link single-use enforcement" item.

**Architecture:** Add a unique JTI to each issued magic-link token (payload becomes `{"email": str, "jti": str}` instead of bare email). Add a `magic_link_consumed (jti, email, consumed_at)` table. Replace `read_magic_link_token` with `consume_magic_link_token(token, *, conn, secret)` which (a) verifies signature/expiry, (b) atomically inserts the JTI via `INSERT OR IGNORE`, and (c) treats `rowcount == 0` as replay → `InvalidMagicLink("magic link already used")`. Opportunistic GC of rows older than 15 minutes runs on each consume.

**Tech Stack:** Python 3, FastAPI, SQLite (WAL), itsdangerous, pytest. No new dependencies — `uuid` is stdlib.

---

## File Structure

**Modified:**

- `src/markland/service/magic_link.py` — change token payload to `{email, jti}`; add `consume_magic_link_token(token, *, conn, secret, max_age_seconds)`; deprecate `read_magic_link_token` to a thin wrapper that returns just the email (kept for tests that don't have a conn — see "Backwards Compatibility" below).
- `src/markland/db.py::init_db` — add `CREATE TABLE IF NOT EXISTS magic_link_consumed` and an index on `consumed_at` for GC.
- `src/markland/web/auth_routes.py` — both call sites (`POST /api/auth/verify` and `GET /verify`) switch from `read_magic_link_token` to `consume_magic_link_token` and pass `db_conn`.
- `src/markland/web/templates/security.html` — change wording from "We do not currently track per-token consumption server-side, so a captured link can be used within its 15-minute window" back to a single-use claim ("Each link is single-use server-side: the first successful verify invalidates it").
- `docs/FOLLOW-UPS.md` — drop the "Magic-link single-use enforcement" entry.
- `tests/test_service_magic_link.py` — update existing roundtrip tests for the new payload shape; add unit tests for `consume_magic_link_token`.
- `tests/test_auth_routes.py` — add a route-level replay test (verify same token twice → first 200, second 400).

**Created:** none.

---

## Out of Scope

- **Migrating in-flight magic-link emails on deploy.** Tokens issued under the old payload shape (bare-email string) become unreadable post-deploy. This is acceptable: tokens expire in 15 minutes, beta volume is low, and an affected user just hits "send me a new link." Do not build a dual-read fallback.
- **Storing the consumed-token table on a separate DB.** SQLite WAL handles this fine; the table stays small (~15 min of rows).
- **Rate-limiting magic-link issuance.** Separate concern, separate follow-up.
- **CSRF on save routes.** Listed alongside this in `docs/FOLLOW-UPS.md`; out of scope here.
- **Cleanup of `magic_link_consumed` via a background sweep.** Opportunistic cleanup on insert is sufficient; if it ever isn't, file a follow-up.

---

## Backwards Compatibility

`read_magic_link_token` has external callers in tests (`tests/test_service_magic_link.py`, `tests/test_auth_routes.py` via `issue_magic_link_token` roundtrip). After this change:

- `issue_magic_link_token(email, *, secret)` — signature unchanged externally; payload changes from `email` to `{"email": email, "jti": <uuid>}`. Tests that issue a token and read it back get the new shape automatically.
- `read_magic_link_token(token, *, secret, max_age_seconds=...)` — kept for now, returns the *email only* (extracts from the new payload). No DB needed. **Does not enforce single-use** — that's `consume_magic_link_token`'s job. Mark with a docstring warning.
- `consume_magic_link_token(token, *, conn, secret, max_age_seconds=...)` — new. Returns email on success. Raises `InvalidMagicLink` on bad signature, expiry, or replay.

Production routes use `consume_magic_link_token`. `read_magic_link_token` exists only as a "decode without consuming" helper for tests/debugging.

---

## Task 1: Add the `magic_link_consumed` table

**Files:**
- Modify: `src/markland/db.py` (within `init_db`, after the existing `audit_log` block, before `conn.commit()`)
- Test: `tests/test_db_schema.py` (create if absent — otherwise add to existing schema test)

- [ ] **Step 1: Check whether `tests/test_db_schema.py` exists**

Run: `ls tests/test_db_schema.py 2>&1`

If it exists, append the new test to it. If not, create it with the failing test below.

- [ ] **Step 2: Write the failing schema test**

Create or extend `tests/test_db_schema.py`:

```python
"""Schema-level smoke tests — confirm tables and indexes exist after init_db."""

from markland.db import init_db


def test_magic_link_consumed_table_exists(tmp_path):
    conn = init_db(tmp_path / "t.db")
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='magic_link_consumed'"
    ).fetchall()
    assert len(rows) == 1, "magic_link_consumed table missing"


def test_magic_link_consumed_columns(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(magic_link_consumed)").fetchall()}
    assert cols == {"jti", "email", "consumed_at"}, f"unexpected columns: {cols}"


def test_magic_link_consumed_jti_is_primary_key(tmp_path):
    conn = init_db(tmp_path / "t.db")
    info = conn.execute("PRAGMA table_info(magic_link_consumed)").fetchall()
    pk_cols = [row[1] for row in info if row[5] > 0]  # row[5] is `pk`
    assert pk_cols == ["jti"], f"expected jti as PK, got {pk_cols}"


def test_magic_link_consumed_at_index_exists(tmp_path):
    conn = init_db(tmp_path / "t.db")
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='magic_link_consumed'"
    ).fetchall()
    names = {row[0] for row in rows}
    assert "idx_magic_link_consumed_at" in names, f"index missing; got {names}"
```

- [ ] **Step 3: Run the test and verify it fails**

Run: `pytest tests/test_db_schema.py -v`
Expected: 4 failures, all because the table does not exist yet (`OperationalError: no such table` or empty result sets).

- [ ] **Step 4: Add the table + index to `init_db`**

In `src/markland/db.py`, locate the audit-log index block (around line 219) and add the following block immediately after it, before the final `conn.commit()` at the bottom of `init_db`:

```python
    conn.execute("""
        CREATE TABLE IF NOT EXISTS magic_link_consumed (
            jti         TEXT PRIMARY KEY,
            email       TEXT NOT NULL,
            consumed_at INTEGER NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_magic_link_consumed_at "
        "ON magic_link_consumed (consumed_at)"
    )
```

`consumed_at` is INTEGER (Unix epoch seconds) so we can do efficient `< ?` comparisons during opportunistic GC. Other tables in this file use ISO strings for human-readable timestamps; this table is purely for machine state and never displayed, so integer epoch is fine.

- [ ] **Step 5: Run the test and verify it passes**

Run: `pytest tests/test_db_schema.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/markland/db.py tests/test_db_schema.py
git commit -m "feat(db): add magic_link_consumed table + index

Stores JTIs of redeemed magic-link tokens so we can reject replays.
Columns: jti (PK), email, consumed_at (epoch seconds). Index on
consumed_at supports opportunistic GC of expired rows."
```

---

## Task 2: Add JTI to magic-link token payload

**Files:**
- Modify: `src/markland/service/magic_link.py`
- Test: `tests/test_service_magic_link.py`

- [ ] **Step 1: Write a failing test for JTI presence**

Add to `tests/test_service_magic_link.py`:

```python
def test_issue_includes_jti_in_payload():
    from itsdangerous import URLSafeTimedSerializer
    token = issue_magic_link_token("alice@example.com", secret="s")
    # Decode without verifying just to inspect payload shape.
    s = URLSafeTimedSerializer("s", salt="mk.magiclink.v1")
    payload = s.loads(token)
    assert isinstance(payload, dict), f"expected dict payload, got {type(payload)}"
    assert payload["email"] == "alice@example.com"
    assert isinstance(payload["jti"], str)
    assert len(payload["jti"]) >= 16


def test_two_issuances_have_distinct_jtis():
    t1 = issue_magic_link_token("alice@example.com", secret="s")
    t2 = issue_magic_link_token("alice@example.com", secret="s")
    from itsdangerous import URLSafeTimedSerializer
    s = URLSafeTimedSerializer("s", salt="mk.magiclink.v1")
    p1 = s.loads(t1)
    p2 = s.loads(t2)
    assert p1["jti"] != p2["jti"]
    # Tokens themselves must also differ (regression: old code produced
    # identical tokens for same-email same-second issuance).
    assert t1 != t2
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_service_magic_link.py::test_issue_includes_jti_in_payload tests/test_service_magic_link.py::test_two_issuances_have_distinct_jtis -v`
Expected: both fail — first with `TypeError: string indices must be integers` (payload is still a string), second with the assertion `t1 != t2` failing because itsdangerous produces identical tokens within one second.

- [ ] **Step 3: Update `issue_magic_link_token` to embed a JTI**

In `src/markland/service/magic_link.py`, change `issue_magic_link_token` to:

```python
import uuid


def issue_magic_link_token(
    email: str,
    *,
    secret: str,
    max_age_seconds: int = MAGIC_LINK_MAX_AGE_SECONDS,  # kept for symmetry; serializer ignores
) -> str:
    """Sign a token carrying this email plus a unique JTI.

    The JTI is what makes server-side single-use enforcement possible — it
    gives us a stable per-issuance key to record in `magic_link_consumed`.
    """
    payload = {"email": email.strip().lower(), "jti": uuid.uuid4().hex}
    return _serializer(secret).dumps(payload)
```

Add `import uuid` at the top of the file (alphabetical order in the stdlib block — after `logging`, before `urllib`).

- [ ] **Step 4: Update `read_magic_link_token` to extract email from the dict payload**

In the same file, change `read_magic_link_token` to:

```python
def read_magic_link_token(
    token: str,
    *,
    secret: str,
    max_age_seconds: int = MAGIC_LINK_MAX_AGE_SECONDS,
) -> str:
    """Return the email encoded in `token`. Raises `InvalidMagicLink`.

    NOTE: This decodes without enforcing single-use. Production verify routes
    must use `consume_magic_link_token` instead. This helper is kept for tests
    and debugging.
    """
    try:
        payload = _serializer(secret).loads(token, max_age=max_age_seconds)
    except SignatureExpired as e:
        raise InvalidMagicLink("magic link expired") from e
    except BadSignature as e:
        raise InvalidMagicLink("invalid magic link") from e
    if not isinstance(payload, dict) or "email" not in payload:
        raise InvalidMagicLink("invalid magic link payload")
    email = payload["email"]
    if not isinstance(email, str):
        raise InvalidMagicLink("invalid magic link payload")
    return email
```

- [ ] **Step 5: Run the JTI tests and verify they pass**

Run: `pytest tests/test_service_magic_link.py::test_issue_includes_jti_in_payload tests/test_service_magic_link.py::test_two_issuances_have_distinct_jtis -v`
Expected: both PASS.

- [ ] **Step 6: Run the full magic-link service test file to confirm no regressions**

Run: `pytest tests/test_service_magic_link.py -v`
Expected: all tests PASS, including the existing `test_issue_and_read_roundtrip`, `test_read_rejects_wrong_secret`, `test_read_rejects_expired`.

- [ ] **Step 7: Commit**

```bash
git add src/markland/service/magic_link.py tests/test_service_magic_link.py
git commit -m "feat(magic-link): embed JTI in token payload

Token payload changes from bare email string to {email, jti} dict. The
JTI is a per-issuance UUID4 that will be the single-use key once
consume_magic_link_token lands. read_magic_link_token continues to
return the email; existing call sites are unaffected."
```

---

## Task 3: Implement `consume_magic_link_token` (single-use enforcement)

**Files:**
- Modify: `src/markland/service/magic_link.py`
- Test: `tests/test_service_magic_link.py`

- [ ] **Step 1: Write the failing tests for the new function**

Add to `tests/test_service_magic_link.py`:

```python
import sqlite3 as _sqlite3
from markland.db import init_db


def test_consume_returns_email_on_first_use(tmp_path):
    conn = init_db(tmp_path / "t.db")
    from markland.service.magic_link import consume_magic_link_token
    token = issue_magic_link_token("alice@example.com", secret="s")
    email = consume_magic_link_token(token, conn=conn, secret="s")
    assert email == "alice@example.com"


def test_consume_rejects_replay(tmp_path):
    conn = init_db(tmp_path / "t.db")
    from markland.service.magic_link import consume_magic_link_token
    token = issue_magic_link_token("alice@example.com", secret="s")
    consume_magic_link_token(token, conn=conn, secret="s")  # first use OK
    with pytest.raises(InvalidMagicLink) as ei:
        consume_magic_link_token(token, conn=conn, secret="s")  # second use rejected
    assert "already used" in str(ei.value).lower()


def test_consume_rejects_expired(tmp_path):
    conn = init_db(tmp_path / "t.db")
    from markland.service.magic_link import consume_magic_link_token
    token = issue_magic_link_token("alice@example.com", secret="s", max_age_seconds=1)
    time.sleep(2)
    with pytest.raises(InvalidMagicLink):
        consume_magic_link_token(token, conn=conn, secret="s", max_age_seconds=1)


def test_consume_rejects_wrong_secret(tmp_path):
    conn = init_db(tmp_path / "t.db")
    from markland.service.magic_link import consume_magic_link_token
    token = issue_magic_link_token("alice@example.com", secret="s")
    with pytest.raises(InvalidMagicLink):
        consume_magic_link_token(token, conn=conn, secret="other")


def test_consume_records_row_in_table(tmp_path):
    conn = init_db(tmp_path / "t.db")
    from markland.service.magic_link import consume_magic_link_token
    token = issue_magic_link_token("alice@example.com", secret="s")
    consume_magic_link_token(token, conn=conn, secret="s")
    rows = conn.execute(
        "SELECT email, consumed_at FROM magic_link_consumed"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "alice@example.com"
    assert isinstance(rows[0][1], int) and rows[0][1] > 0


def test_consume_two_distinct_tokens_for_same_email_both_succeed(tmp_path):
    """Each issuance has its own JTI, so two separately-issued tokens for the
    same email are independently consumable."""
    conn = init_db(tmp_path / "t.db")
    from markland.service.magic_link import consume_magic_link_token
    t1 = issue_magic_link_token("alice@example.com", secret="s")
    t2 = issue_magic_link_token("alice@example.com", secret="s")
    assert t1 != t2  # JTI guarantees distinct tokens
    assert consume_magic_link_token(t1, conn=conn, secret="s") == "alice@example.com"
    assert consume_magic_link_token(t2, conn=conn, secret="s") == "alice@example.com"


def test_consume_garbage_collects_old_rows(tmp_path):
    """Rows older than 15 min should be cleaned up opportunistically on consume."""
    conn = init_db(tmp_path / "t.db")
    from markland.service.magic_link import consume_magic_link_token, MAGIC_LINK_MAX_AGE_SECONDS
    # Insert an old row directly.
    old_ts = int(time.time()) - (MAGIC_LINK_MAX_AGE_SECONDS + 60)
    conn.execute(
        "INSERT INTO magic_link_consumed (jti, email, consumed_at) VALUES (?, ?, ?)",
        ("stale-jti", "stale@example.com", old_ts),
    )
    conn.commit()
    # Now consume a fresh token — GC should fire.
    token = issue_magic_link_token("alice@example.com", secret="s")
    consume_magic_link_token(token, conn=conn, secret="s")
    remaining_jtis = {r[0] for r in conn.execute("SELECT jti FROM magic_link_consumed").fetchall()}
    assert "stale-jti" not in remaining_jtis
    # The fresh consumption row should still be present.
    assert len(remaining_jtis) == 1
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_service_magic_link.py -k consume -v`
Expected: all 7 fail with `ImportError: cannot import name 'consume_magic_link_token'`.

- [ ] **Step 3: Implement `consume_magic_link_token`**

Add to `src/markland/service/magic_link.py`, immediately after `read_magic_link_token`:

```python
def consume_magic_link_token(
    token: str,
    *,
    conn,  # sqlite3.Connection — not annotated to avoid the import here
    secret: str,
    max_age_seconds: int = MAGIC_LINK_MAX_AGE_SECONDS,
) -> str:
    """Verify and atomically consume a magic-link token.

    On success: records the JTI in `magic_link_consumed` and returns the
    email. On replay: raises `InvalidMagicLink("magic link already used")`.
    On bad signature / expiry: raises `InvalidMagicLink` with the
    appropriate message.

    Also opportunistically GCs rows older than `max_age_seconds`. Since the
    signature check rejects tokens older than that anyway, GC'd rows can
    never collide with a valid future consume.
    """
    import time as _time

    try:
        payload = _serializer(secret).loads(token, max_age=max_age_seconds)
    except SignatureExpired as e:
        raise InvalidMagicLink("magic link expired") from e
    except BadSignature as e:
        raise InvalidMagicLink("invalid magic link") from e
    if not isinstance(payload, dict):
        raise InvalidMagicLink("invalid magic link payload")
    email = payload.get("email")
    jti = payload.get("jti")
    if not isinstance(email, str) or not isinstance(jti, str):
        raise InvalidMagicLink("invalid magic link payload")

    now = int(_time.time())
    cutoff = now - max_age_seconds

    # Opportunistic GC. Cheap (indexed scan, ~one row per consume in the worst case).
    conn.execute(
        "DELETE FROM magic_link_consumed WHERE consumed_at < ?",
        (cutoff,),
    )

    # Atomic single-use: INSERT OR IGNORE returns rowcount=0 if the JTI already exists.
    cur = conn.execute(
        "INSERT OR IGNORE INTO magic_link_consumed (jti, email, consumed_at) "
        "VALUES (?, ?, ?)",
        (jti, email, now),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise InvalidMagicLink("magic link already used")
    return email
```

- [ ] **Step 4: Run the consume tests and verify they pass**

Run: `pytest tests/test_service_magic_link.py -k consume -v`
Expected: all 7 PASS.

- [ ] **Step 5: Run the entire magic-link test module to confirm no regressions**

Run: `pytest tests/test_service_magic_link.py -v`
Expected: every test PASSES.

- [ ] **Step 6: Commit**

```bash
git add src/markland/service/magic_link.py tests/test_service_magic_link.py
git commit -m "feat(magic-link): add consume_magic_link_token for single-use

INSERT OR IGNORE on the JTI gives atomic single-use enforcement. Opportunistic
GC of rows older than MAGIC_LINK_MAX_AGE_SECONDS keeps the table small —
since the signature check rejects expired tokens anyway, GC'd rows can
never collide with a valid future consume."
```

---

## Task 4: Wire the verify routes to use `consume_magic_link_token`

**Files:**
- Modify: `src/markland/web/auth_routes.py`
- Test: `tests/test_auth_routes.py`

- [ ] **Step 1: Write the failing replay tests at the route level**

Add to `tests/test_auth_routes.py`:

```python
def test_verify_json_rejects_replay(client_and_conn):
    """A magic-link token that has already been redeemed must be rejected on
    a second verify, even within the 15-minute signature window."""
    client, _, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")

    r1 = client.post("/api/auth/verify", json={"token": token})
    assert r1.status_code == 200, r1.text

    r2 = client.post("/api/auth/verify", json={"token": token})
    assert r2.status_code == 400, r2.text
    assert "already used" in r2.text.lower()


def test_verify_get_rejects_replay(client_and_conn):
    """The browser /verify GET path must also enforce single-use."""
    client, _, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")

    r1 = client.get(f"/verify?token={token}", follow_redirects=False)
    # First use: 200 (verify_sent_tpl) or 303 (return_to redirect). Either way, not 400.
    assert r1.status_code in (200, 303), r1.text

    r2 = client.get(f"/verify?token={token}", follow_redirects=False)
    assert r2.status_code == 400, r2.text
    assert "expired" in r2.text.lower() or "invalid" in r2.text.lower() or "used" in r2.text.lower()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_auth_routes.py::test_verify_json_rejects_replay tests/test_auth_routes.py::test_verify_get_rejects_replay -v`
Expected: both fail. The first will return 200 on the second call (no replay protection); the second will return 200 or 303 on the second call.

- [ ] **Step 3: Switch the JSON verify route to `consume_magic_link_token`**

In `src/markland/web/auth_routes.py`, update the import block at the top:

```python
from markland.service.magic_link import (
    InvalidMagicLink,
    consume_magic_link_token,
    safe_return_to,
    send_magic_link,
)
```

(Remove `read_magic_link_token` from the import — it's no longer used by routes.)

Then update the `/api/auth/verify` handler (currently around line 126):

```python
    @router.post("/api/auth/verify")
    def verify(body: _VerifyRequest, response: Response) -> JSONResponse:
        if not session_secret:
            raise HTTPException(500, "session secret not configured")
        try:
            email = consume_magic_link_token(
                body.token, conn=db_conn, secret=session_secret
            )
        except InvalidMagicLink as e:
            raise HTTPException(400, str(e)) from e
        user = upsert_user_by_email(db_conn, email)
        cookie = issue_session(user.id, secret=session_secret)
        resp = JSONResponse({"ok": True, "user_id": user.id})
        resp.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=cookie,
            max_age=SESSION_MAX_AGE_SECONDS,
            httponly=True,
            secure=base_url.startswith("https://"),
            samesite="lax",
            path="/",
        )
        return resp
```

- [ ] **Step 4: Switch the browser verify route to `consume_magic_link_token`**

In the same file, update the `/verify` GET handler (currently around line 148):

```python
    @router.get("/verify")
    def verify_page(request: Request, token: str, return_to: str | None = None):
        if not session_secret:
            raise HTTPException(500, "session secret not configured")
        try:
            email = consume_magic_link_token(
                token, conn=db_conn, secret=session_secret
            )
        except InvalidMagicLink:
            return HTMLResponse(
                "<html><body style='font-family:system-ui;padding:2rem;'>"
                "<h1>Link expired or invalid</h1>"
                "<p><a href='/login'>Request a new one</a></p>"
                "</body></html>",
                status_code=400,
            )
        user = upsert_user_by_email(db_conn, email)
        cookie = issue_session(user.id, secret=session_secret)
        target = safe_return_to(return_to)
        pending = request.cookies.get("markland_pending_intent", "")
        if pending:
            target = "/resume"
        if target == "/":
            resp = HTMLResponse(
                render_with_nav(
                    verify_sent_tpl, request, db_conn,
                    base_url=base_url, secret=session_secret,
                    signed_in_user={"email": user.email},
                )
            )
        else:
            resp = RedirectResponse(target, status_code=303)
        resp.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=cookie,
            max_age=SESSION_MAX_AGE_SECONDS,
            httponly=True,
            secure=base_url.startswith("https://"),
            samesite="lax",
            path="/",
        )
        return resp
```

(Only the `consume_magic_link_token(...)` call differs from the original. The error-page HTML wording stays the same — "Link expired or invalid" covers the new "already used" case from the user's perspective; we don't want to give a replay attacker a confirmation that the link was redeemed.)

- [ ] **Step 5: Run the new replay tests and verify they pass**

Run: `pytest tests/test_auth_routes.py::test_verify_json_rejects_replay tests/test_auth_routes.py::test_verify_get_rejects_replay -v`
Expected: both PASS.

- [ ] **Step 6: Run the full auth route test module to confirm no regressions**

Run: `pytest tests/test_auth_routes.py -v`
Expected: all tests PASS, including the existing `test_verify_with_valid_token_creates_user_and_session`, `test_verify_with_bad_token_returns_400`, etc.

- [ ] **Step 7: Run the complete test suite**

Run: `pytest -x`
Expected: all tests PASS. If anything else breaks, the most likely culprit is a test that called `client.post("/api/auth/verify", ...)` twice with the same token. Such tests need to issue a fresh token for each call.

- [ ] **Step 8: Commit**

```bash
git add src/markland/web/auth_routes.py tests/test_auth_routes.py
git commit -m "feat(auth): enforce magic-link single-use at /verify

Both /api/auth/verify (JSON) and /verify (browser) now call
consume_magic_link_token, which atomically records the JTI and rejects
replays with InvalidMagicLink. The browser path keeps the generic
'expired or invalid' wording so replays don't leak token state."
```

---

## Task 5: Update `/security` page wording + drop the FOLLOW-UPS entry

**Files:**
- Modify: `src/markland/web/templates/security.html` (line 16)
- Modify: `docs/FOLLOW-UPS.md` (lines 10-17)

- [ ] **Step 1: Update the `/security` template wording**

Open `src/markland/web/templates/security.html`. Find the sentence on line 16:

> "Humans sign in with magic-link email — no passwords are stored. Sign-in links are signed with a server secret and expire 15 minutes after issue. The link is sent only to the email address on the request, and the session it creates is bound to a separate signed cookie. (We do not currently track per-token consumption server-side, so a captured link can be used within its 15-minute window before it expires — that gap is on the post-beta hardening list.) AI agents authenticate with scoped bearer tokens..."

Replace the parenthetical with:

> "Each link is single-use server-side: the first successful verify invalidates the token, so a captured link cannot be replayed."

The replacement string should produce this final paragraph:

```html
    Humans sign in with magic-link email &mdash; no passwords are stored. Sign-in links are signed with a server secret and expire 15 minutes after issue. The link is sent only to the email address on the request, and the session it creates is bound to a separate signed cookie. Each link is single-use server-side: the first successful verify invalidates the token, so a captured link cannot be replayed. AI agents authenticate with scoped bearer tokens minted from a logged-in user account. Tokens are hashed at rest; only the bearer plaintext is shown once at mint time. You can revoke any token individually from settings, and all token issuance is recorded in an append-only audit log.
```

- [ ] **Step 2: Drop the magic-link entry from `docs/FOLLOW-UPS.md`**

Open `docs/FOLLOW-UPS.md`. Delete lines 10-17 (the entire "Magic-link single-use enforcement" bullet, from `- **Magic-link single-use enforcement**` through `back to "single-use" once enforced.`).

The "Security" section should now begin directly with the "No CSRF protection on save routes" entry.

- [ ] **Step 3: Run a quick smoke test that `/security` still renders**

Run: `pytest -k security -v` (covers any existing tests for the page).

If no security-page test exists, add this lightweight one to `tests/test_auth_routes.py` (or wherever HTTP routes are smoke-tested):

```python
def test_security_page_renders(client_and_conn):
    client, _, _ = client_and_conn
    r = client.get("/security")
    assert r.status_code == 200
    assert "single-use" in r.text.lower()
    # Regression: the old "captured link can be used" wording must be gone.
    assert "captured link can be used" not in r.text.lower()
```

Run: `pytest tests/test_auth_routes.py::test_security_page_renders -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/markland/web/templates/security.html docs/FOLLOW-UPS.md tests/test_auth_routes.py
git commit -m "docs(security): magic links are now single-use server-side

/security wording updated; the matching FOLLOW-UPS entry is dropped.
Added a smoke test that asserts the new wording is present and the
old 'captured link can be used' caveat is gone."
```

---

## Task 6: Manual verification + push

**Files:** none (operational task).

- [ ] **Step 1: Run the full test suite one more time**

Run: `pytest`
Expected: every test PASSES.

- [ ] **Step 2: Manually verify the login flow against the dev server**

Start the dev server per the project's usual command (check `README.md` or `Makefile`; common patterns: `make dev`, `uvicorn markland.web.app:create_app --factory`, or `python -m markland.run_web`).

Then:
1. Visit `/login`, request a link for a test address.
2. Open the resulting URL from the dev mailbox / log output.
3. Confirm you are signed in (cookie set, `/api/me` returns 200).
4. **Open the same URL in a private window or after logging out.** Confirm you see the "Link expired or invalid" page (status 400). This is the regression we're fixing — before this work, that second click would have signed you back in.
5. Visit `/security` and confirm the wording is updated and reads as "single-use server-side".

If any of those checks fails, do **not** push. Diagnose, fix, retest.

- [ ] **Step 3: Verify the branch state and push**

Run: `git status && git log --oneline -10`
Expected: clean working tree; the 5 commits from Tasks 1-5 are at the tip of `main`.

This is a docs+security change on `main` — per the project's docs-direct-push convention for security follow-ups, push to remote:

Run: `git push`

- [ ] **Step 4: Close the beads issue (if one exists for this work)**

Run: `bd list --status=open | grep -i magic` to find the corresponding issue, then `bd close <id> --reason="shipped via single-use enforcement"`. If none exists, skip.

Run: `bd sync`

---

## Self-Review Notes

**Spec coverage:**
- ✅ JTI in payload → Task 2
- ✅ `magic_link_consumed` table → Task 1
- ✅ Atomic single-use via `INSERT OR IGNORE` → Task 3
- ✅ Both verify routes consume server-side → Task 4
- ✅ `/security` wording updated → Task 5
- ✅ FOLLOW-UPS entry removed → Task 5
- ✅ Manual verify-flow test → Task 6

**Type/name consistency:** `consume_magic_link_token(token, *, conn, secret, max_age_seconds=...)` is referenced identically in Task 3 (definition), Task 4 (both call sites), and the test code in Tasks 3-4. `magic_link_consumed` table name + columns (`jti`, `email`, `consumed_at`) are identical across Tasks 1, 3, and the test code in Task 3. `MAGIC_LINK_MAX_AGE_SECONDS` is the only `max_age` constant.

**No placeholders:** every step contains the actual code or actual command. The only deferred decision is "the project's usual dev-server command" in Task 6 Step 2 — that's a runtime detail, not a code placeholder.
