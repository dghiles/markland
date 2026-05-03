# Admin Metrics — Tool/Usage Analytics Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `markland_admin_metrics` (and `GET /admin/metrics`) so an admin can answer "how big is the service right now and what's actually getting used?" in one call — total users, total documents, document-creation rate, share/grant/invite activity, and per-action audit-event totals.

**Architecture:** Pure additive aggregation in `src/markland/service/admin_metrics.py::summary()`. Add unwindowed totals (`users_total`, `documents_total`, `documents_public_total`, `grants_total`, `invites_total`) and windowed counts (`documents_created`, `documents_updated`, `documents_deleted`, `grants_revoked`, `invites_created`). Existing keys (`signups`, `publishes`, `grants_created`, `invites_accepted`, `waitlist_total`, `first_mcp_call`) are preserved verbatim — no breaking changes for existing callers. Tests, snapshots, and docstrings get the new keys.

**Tech Stack:** SQLite, FastAPI, FastMCP. No new tables, no new dependencies. All counts derived from existing `users`, `documents`, `grants`, `invites`, `audit_log`, `waitlist` tables.

---

## File Structure

**Modified:**

- `src/markland/service/admin_metrics.py` — extend `summary()` with new keys; keep flat-dict shape.
- `src/markland/server.py` — update `markland_admin_metrics` docstring's `Returns` section to enumerate new keys; update the `/admin/metrics` endpoint docstring if present.
- `src/markland/web/app.py` — no logic change; the endpoint just passes through `summary()` output. Verify nothing hardcodes the response shape.
- `tests/test_admin_metrics_service.py` — new unit tests for each added key.
- `tests/test_admin_metrics_http.py` — assert new keys appear in HTTP response.
- `tests/test_admin_metrics_mcp.py` — assert new keys appear in MCP tool response.
- `tests/fixtures/mcp_baseline/markland_admin_metrics.json` — regenerate snapshot to include new keys.
- `docs/FOLLOW-UPS.md` — drop the `first_mcp_call` line if it gets resolved here (it does NOT — see Out of Scope).

**Created:** none.

---

## Out of Scope

- **`first_mcp_call`** stays `None`. It requires a `metrics_events` table; tracked separately in `docs/FOLLOW-UPS.md`. Do not attempt to resolve here.
- **Per-user breakdowns** ("top 10 publishers"). Single-tool call, single flat dict. No nesting.
- **Charts / time-series.** This is a point-in-time snapshot tool; trends are a separate analytics surface.
- **Document size / content stats.** Word count, byte size, etc. — not requested.
- **Umami Cloud anonymous-visitor counts.** Those live in the Umami dashboard, not in our DB.

---

## New Return Shape

After this plan, `summary()` returns a flat dict with these keys (existing keys marked `(existing)`):

```
# Window metadata
window_seconds              (existing)
window_start_iso            (existing)
window_end_iso              (existing)

# All-time totals (unwindowed)
users_total                 NEW   COUNT(*) FROM users
documents_total             NEW   COUNT(*) FROM documents
documents_public_total      NEW   COUNT(*) FROM documents WHERE is_public = 1
grants_total                NEW   COUNT(*) FROM grants  (active grants on the books)
invites_total               NEW   COUNT(*) FROM invites WHERE revoked_at IS NULL
waitlist_total              (existing) — already unwindowed

# Windowed counts (signups/publishes/grants_created/invites_accepted are existing)
signups                     (existing)   created_at ∈ [start, end) on users
publishes                   (existing)   audit action='publish'
grants_created              (existing)   audit action='grant'
invites_accepted            (existing)   audit action='invite_accept'

documents_created           NEW          COUNT(*) FROM documents WHERE created_at ∈ window
documents_updated           NEW          audit action='update'
documents_deleted           NEW          audit action='delete'
grants_revoked              NEW          audit action='revoke'
invites_created             NEW          audit action='invite_create'

# Known gap (existing)
first_mcp_call              (existing) → null
```

**Conventions:**

- All windowed counts use the same `[start_iso, end_iso)` half-open interval as the existing windowed keys.
- All `*_total` keys are unwindowed (point-in-time snapshot at the time of the call).
- Audit-derived counts use the action names already present in `_ALLOWED_ACTIONS` in `src/markland/service/audit.py:20-30` (`publish`, `update`, `delete`, `grant`, `revoke`, `invite_create`, `invite_accept`).

---

### Task 1: Add `users_total` to `summary()`

**Files:**
- Modify: `src/markland/service/admin_metrics.py`
- Test: `tests/test_admin_metrics_service.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_admin_metrics_service.py`:

```python
def test_summary_includes_users_total_unwindowed(conn):
    # Two users — one inside the window, one outside. Both should be counted.
    _seed_user(conn, "usr_recent", "r@x.com", "2026-04-30T12:00:00Z")
    _seed_user(conn, "usr_old", "o@x.com", "2025-01-01T00:00:00Z")
    result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
    assert result["users_total"] == 2
    assert result["signups"] == 1  # window-bound, unchanged behavior
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_admin_metrics_service.py::test_summary_includes_users_total_unwindowed -v`
Expected: FAIL with `KeyError: 'users_total'`.

- [ ] **Step 3: Add the count to `summary()`**

In `src/markland/service/admin_metrics.py`, inside `summary()` after the `waitlist_total = _count(...)` line (currently line 73), add:

```python
    users_total = _count("SELECT COUNT(*) FROM users", ())
```

Then add `"users_total": users_total,` to the returned dict, immediately above `"waitlist_total": waitlist_total,`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_admin_metrics_service.py -v`
Expected: PASS for new test, plus all existing service tests still passing.

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/admin_metrics.py tests/test_admin_metrics_service.py
git commit -m "feat(admin-metrics): add users_total (unwindowed)"
```

---

### Task 2: Add `documents_total` and `documents_public_total`

**Files:**
- Modify: `src/markland/service/admin_metrics.py`
- Test: `tests/test_admin_metrics_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin_metrics_service.py`:

```python
def _seed_doc(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    is_public: int = 0,
    created_at: str = "2026-05-01T00:00:00Z",
    owner_id: str | None = None,
) -> None:
    # documents has UNIQUE share_token NOT NULL — pass through doc_id as a stand-in.
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, is_public, owner_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (doc_id, "t", "c", f"tok_{doc_id}", created_at, created_at, is_public, owner_id),
    )
    conn.commit()


def test_summary_documents_total_counts_all_docs(conn):
    _seed_doc(conn, "d1", is_public=0)
    _seed_doc(conn, "d2", is_public=1)
    _seed_doc(conn, "d3", is_public=1)
    result = summary(conn, window_seconds=86400, now_iso="2026-05-02T00:00:00Z")
    assert result["documents_total"] == 3
    assert result["documents_public_total"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_admin_metrics_service.py::test_summary_documents_total_counts_all_docs -v`
Expected: FAIL with `KeyError: 'documents_total'`.

- [ ] **Step 3: Add the counts to `summary()`**

In `src/markland/service/admin_metrics.py`, after the `users_total` line added in Task 1, add:

```python
    documents_total = _count("SELECT COUNT(*) FROM documents", ())
    documents_public_total = _count(
        "SELECT COUNT(*) FROM documents WHERE is_public = 1", ()
    )
```

Add `"documents_total": documents_total,` and `"documents_public_total": documents_public_total,` to the returned dict, grouped near `users_total` and `waitlist_total`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_admin_metrics_service.py -v`
Expected: PASS for new test, plus all existing service tests still passing.

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/admin_metrics.py tests/test_admin_metrics_service.py
git commit -m "feat(admin-metrics): add documents_total + documents_public_total"
```

---

### Task 3: Add `documents_created` (windowed)

**Files:**
- Modify: `src/markland/service/admin_metrics.py`
- Test: `tests/test_admin_metrics_service.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_admin_metrics_service.py`:

```python
def test_summary_documents_created_in_window(conn):
    # One inside the 24h window, one outside.
    _seed_doc(conn, "d_recent", created_at="2026-04-30T12:00:00Z")
    _seed_doc(conn, "d_old", created_at="2026-04-01T12:00:00Z")
    result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
    assert result["documents_created"] == 1
    assert result["documents_total"] == 2  # unwindowed sees both
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_admin_metrics_service.py::test_summary_documents_created_in_window -v`
Expected: FAIL with `KeyError: 'documents_created'`.

- [ ] **Step 3: Add the windowed count**

In `src/markland/service/admin_metrics.py`, alongside the existing `signups` count, add:

```python
    documents_created = _count(
        "SELECT COUNT(*) FROM documents WHERE created_at >= ? AND created_at < ?",
        (start_iso, end_iso),
    )
```

Add `"documents_created": documents_created,` to the returned dict, grouped with the other windowed keys (near `signups` and `publishes`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_admin_metrics_service.py -v`
Expected: PASS for new test, plus all existing service tests still passing.

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/admin_metrics.py tests/test_admin_metrics_service.py
git commit -m "feat(admin-metrics): add documents_created (windowed)"
```

---

### Task 4: Add windowed audit-derived counts (`documents_updated`, `documents_deleted`, `grants_revoked`, `invites_created`)

**Files:**
- Modify: `src/markland/service/admin_metrics.py`
- Test: `tests/test_admin_metrics_service.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_admin_metrics_service.py`:

```python
def test_summary_counts_additional_audit_events_in_window(conn):
    now = "2026-05-01T00:00:00Z"
    in_window = "2026-04-30T22:00:00Z"
    out_of_window = "2026-04-01T22:00:00Z"

    # In window — should be counted
    _seed_audit(conn, "usr_a", "update", "doc_1", in_window)
    _seed_audit(conn, "usr_a", "update", "doc_2", in_window)
    _seed_audit(conn, "usr_a", "delete", "doc_3", in_window)
    _seed_audit(conn, "usr_a", "revoke", "doc_1", in_window)
    _seed_audit(conn, "usr_a", "invite_create", "doc_2", in_window)

    # Out of window — should NOT be counted
    _seed_audit(conn, "usr_a", "update", "doc_4", out_of_window)
    _seed_audit(conn, "usr_a", "delete", "doc_5", out_of_window)
    _seed_audit(conn, "usr_a", "revoke", "doc_6", out_of_window)
    _seed_audit(conn, "usr_a", "invite_create", "doc_7", out_of_window)

    result = summary(conn, window_seconds=86400, now_iso=now)
    assert result["documents_updated"] == 2
    assert result["documents_deleted"] == 1
    assert result["grants_revoked"] == 1
    assert result["invites_created"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_admin_metrics_service.py::test_summary_counts_additional_audit_events_in_window -v`
Expected: FAIL with `KeyError: 'documents_updated'`.

- [ ] **Step 3: Add the counts**

In `src/markland/service/admin_metrics.py`, alongside the existing `publishes`/`grants_created`/`invites_accepted` blocks, add:

```python
    documents_updated = _count(
        "SELECT COUNT(*) FROM audit_log WHERE action = 'update' "
        "AND created_at >= ? AND created_at < ?",
        (start_iso, end_iso),
    )
    documents_deleted = _count(
        "SELECT COUNT(*) FROM audit_log WHERE action = 'delete' "
        "AND created_at >= ? AND created_at < ?",
        (start_iso, end_iso),
    )
    grants_revoked = _count(
        "SELECT COUNT(*) FROM audit_log WHERE action = 'revoke' "
        "AND created_at >= ? AND created_at < ?",
        (start_iso, end_iso),
    )
    invites_created = _count(
        "SELECT COUNT(*) FROM audit_log WHERE action = 'invite_create' "
        "AND created_at >= ? AND created_at < ?",
        (start_iso, end_iso),
    )
```

Add the four new keys to the returned dict alongside `publishes`/`grants_created`/`invites_accepted`:

```python
        "documents_updated": documents_updated,
        "documents_deleted": documents_deleted,
        "grants_revoked": grants_revoked,
        "invites_created": invites_created,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_admin_metrics_service.py -v`
Expected: PASS for new test, plus all existing service tests still passing.

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/admin_metrics.py tests/test_admin_metrics_service.py
git commit -m "feat(admin-metrics): add windowed update/delete/revoke/invite_create counts"
```

---

### Task 5: Add `grants_total` (active grants on the books)

**Files:**
- Modify: `src/markland/service/admin_metrics.py`
- Test: `tests/test_admin_metrics_service.py`

**Note:** The `grants` table represents active grants — a `revoke` removes the row (see `src/markland/service/grants.py:279`). So `grants_total` is the current active-share count, not all grants ever made.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_admin_metrics_service.py`:

```python
def test_summary_grants_total_counts_active_rows(conn):
    # Seed two grant rows directly.
    conn.execute(
        "INSERT INTO grants (doc_id, principal_id, principal_type, level, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("doc_1", "usr_b", "user", "view", "2026-04-30T22:00:00Z"),
    )
    conn.execute(
        "INSERT INTO grants (doc_id, principal_id, principal_type, level, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("doc_2", "usr_c", "user", "edit", "2025-01-01T00:00:00Z"),
    )
    conn.commit()
    result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
    assert result["grants_total"] == 2  # unwindowed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_admin_metrics_service.py::test_summary_grants_total_counts_active_rows -v`
Expected: FAIL with `KeyError: 'grants_total'`.

- [ ] **Step 3: Verify the actual grants schema and adjust test if needed**

Run: `uv run --with pytest python -c "import sqlite3; from markland.db import init_db; c = init_db(':memory:'); print([r for r in c.execute('PRAGMA table_info(grants)')])"`

If the schema differs (e.g., a column is non-null and missing from the test seed), adjust the INSERT in the test to satisfy NOT NULL constraints. Re-run Step 2.

- [ ] **Step 4: Add the count**

In `src/markland/service/admin_metrics.py`, alongside `users_total` and `documents_total`, add:

```python
    grants_total = _count("SELECT COUNT(*) FROM grants", ())
```

Add `"grants_total": grants_total,` to the returned dict.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_admin_metrics_service.py -v`
Expected: PASS for new test, plus all existing service tests still passing.

- [ ] **Step 6: Commit**

```bash
git add src/markland/service/admin_metrics.py tests/test_admin_metrics_service.py
git commit -m "feat(admin-metrics): add grants_total (active grants)"
```

---

### Task 6: Add `invites_total` (live invites — unrevoked)

**Files:**
- Modify: `src/markland/service/admin_metrics.py`
- Test: `tests/test_admin_metrics_service.py`

**Note:** The `invites` table is created by `ensure_invites_schema()` in `src/markland/db.py:254-278`. It has `revoked_at TEXT` (nullable). A live invite is one with `revoked_at IS NULL`.

`init_db()` does NOT call `ensure_invites_schema()` — but `summary()` will be called in production where the schema exists. For the test, call `ensure_invites_schema()` explicitly. For the production path, gracefully handle a missing table by returning 0 (using a `try/except sqlite3.OperationalError` around the count) so this works in fresh test DBs that don't run the invites migration.

- [ ] **Step 1: Confirm `ensure_invites_schema()` is the right call**

Run: `grep -n "ensure_invites_schema" src/markland/`
Expected: Defined in `src/markland/db.py`; called from app startup or invites service. Note where it's called so you understand the invariant in production.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_admin_metrics_service.py`:

```python
def test_summary_invites_total_counts_live_invites(conn):
    from markland.db import ensure_invites_schema

    ensure_invites_schema(conn)
    # Two live, one revoked — total should be 2.
    conn.execute(
        "INSERT INTO invites (id, token_hash, doc_id, level, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("inv1", "h1", "d1", "view", "usr_a", "2026-04-30T22:00:00Z"),
    )
    conn.execute(
        "INSERT INTO invites (id, token_hash, doc_id, level, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("inv2", "h2", "d2", "edit", "usr_a", "2026-04-30T23:00:00Z"),
    )
    conn.execute(
        "INSERT INTO invites (id, token_hash, doc_id, level, created_by, created_at, revoked_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("inv3", "h3", "d3", "view", "usr_a", "2026-04-29T22:00:00Z", "2026-04-30T22:00:00Z"),
    )
    conn.commit()
    result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
    assert result["invites_total"] == 2


def test_summary_invites_total_returns_zero_when_table_missing(conn):
    # init_db does not create the invites table; summary should not raise.
    result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
    assert result["invites_total"] == 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_admin_metrics_service.py::test_summary_invites_total_counts_live_invites tests/test_admin_metrics_service.py::test_summary_invites_total_returns_zero_when_table_missing -v`
Expected: Both FAIL with `KeyError: 'invites_total'`.

- [ ] **Step 4: Add the count with graceful-missing-table handling**

In `src/markland/service/admin_metrics.py`, after the existing counts, add:

```python
    try:
        invites_total = _count(
            "SELECT COUNT(*) FROM invites WHERE revoked_at IS NULL", ()
        )
    except sqlite3.OperationalError:
        # invites table created lazily by ensure_invites_schema(); fresh test
        # DBs that don't run that migration shouldn't break the metrics call.
        invites_total = 0
```

Add `"invites_total": invites_total,` to the returned dict.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_admin_metrics_service.py -v`
Expected: PASS for both new tests, plus all existing service tests still passing.

- [ ] **Step 6: Commit**

```bash
git add src/markland/service/admin_metrics.py tests/test_admin_metrics_service.py
git commit -m "feat(admin-metrics): add invites_total (live invites)"
```

---

### Task 7: Update HTTP-endpoint test to assert new keys present

**Files:**
- Modify: `tests/test_admin_metrics_http.py`

- [ ] **Step 1: Add new key assertions**

In `tests/test_admin_metrics_http.py`, in `test_admin_metrics_admin_returns_summary` (after `assert "waitlist_total" in body`), add the assertions for every new key:

```python
    assert "users_total" in body
    assert "documents_total" in body
    assert "documents_public_total" in body
    assert "documents_created" in body
    assert "documents_updated" in body
    assert "documents_deleted" in body
    assert "grants_total" in body
    assert "grants_revoked" in body
    assert "invites_total" in body
    assert "invites_created" in body
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_admin_metrics_http.py -v`
Expected: PASS — implementation already added all these keys in Tasks 1–6.

- [ ] **Step 3: Commit**

```bash
git add tests/test_admin_metrics_http.py
git commit -m "test(admin-metrics-http): assert expanded summary keys"
```

---

### Task 8: Update MCP-tool test to assert new keys present

**Files:**
- Modify: `tests/test_admin_metrics_mcp.py`

- [ ] **Step 1: Add new key assertions**

In `tests/test_admin_metrics_mcp.py`, in `test_admin_metrics_tool_returns_summary` (after `assert "waitlist_total" in result`), add:

```python
    assert "users_total" in result
    assert "documents_total" in result
    assert "documents_public_total" in result
    assert "documents_created" in result
    assert "documents_updated" in result
    assert "documents_deleted" in result
    assert "grants_total" in result
    assert "grants_revoked" in result
    assert "invites_total" in result
    assert "invites_created" in result
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_admin_metrics_mcp.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_admin_metrics_mcp.py
git commit -m "test(admin-metrics-mcp): assert expanded summary keys"
```

---

### Task 9: Update the `markland_admin_metrics` MCP-tool docstring

**Files:**
- Modify: `src/markland/server.py`

- [ ] **Step 1: Read the current docstring**

Open `src/markland/server.py:1310-1337`. Note the current `Returns:` block enumerates `window_seconds, window_start_iso, window_end_iso, signups, publishes, grants_created, invites_accepted, waitlist_total, first_mcp_call`.

- [ ] **Step 2: Replace the docstring with the expanded shape**

Edit the docstring (the body of `markland_admin_metrics`) so the `Returns:` section reads:

```
        Returns:
            Flat dict. Keys are grouped (no nesting):
              Window: window_seconds, window_start_iso, window_end_iso.
              Totals (unwindowed): users_total, documents_total,
                documents_public_total, grants_total, invites_total,
                waitlist_total.
              Windowed: signups, documents_created, documents_updated,
                documents_deleted, publishes, grants_created, grants_revoked,
                invites_created, invites_accepted.
              Known gap: first_mcp_call (currently null — event lives in
                stdout logs only; check `flyctl logs`).
```

The docstring's `Args:`, `Raises:`, and `Idempotency:` sections are unchanged.

- [ ] **Step 3: Run all admin-metrics tests**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_admin_metrics_service.py tests/test_admin_metrics_http.py tests/test_admin_metrics_mcp.py -v`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add src/markland/server.py
git commit -m "docs(mcp): expand markland_admin_metrics Returns docstring"
```

---

### Task 10: Regenerate the MCP baseline snapshot

**Files:**
- Modify: `tests/fixtures/mcp_baseline/markland_admin_metrics.json`

The baseline test (`tests/test_mcp_baseline.py`) snapshots the tool's response shape. After adding keys, the snapshot will diverge. Regenerate it.

- [ ] **Step 1: Run the baseline test to confirm it now diffs**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_mcp_baseline.py -k admin_metrics -v`
Expected: FAIL — actual response now contains the new keys, snapshot doesn't.

- [ ] **Step 2: Inspect the snapshot helper to find the regenerate flag**

Run: `grep -n "snapshot\|MCP_BASELINE\|UPDATE\|regenerate" tests/_mcp_harness.py | head -20`

Most snapshot harnesses honor an env var (commonly `UPDATE_SNAPSHOTS=1` or similar). Find the actual flag in `tests/_mcp_harness.py` and use it.

- [ ] **Step 3: Regenerate**

Using the flag found in Step 2 (substitute `<FLAG>` below):

```bash
<FLAG>=1 uv run --with pytest --with pytest-asyncio python -m pytest tests/test_mcp_baseline.py -k admin_metrics -v
```

If no flag exists, manually edit `tests/fixtures/mcp_baseline/markland_admin_metrics.json` to add the new keys. For an empty test DB, all the new totals are 0 except `users_total` (which is 1 — the seeded admin) and `documents_total`/`documents_public_total` (0). Use `<TIMESTAMP>` for the windowed timestamps as the existing snapshot does.

- [ ] **Step 4: Visually inspect the regenerated JSON**

Run: `cat tests/fixtures/mcp_baseline/markland_admin_metrics.json`

Verify all three scenarios (`admin_default`, `admin_custom_window`, `non_admin_forbidden`) include the new keys for the OK cases (the forbidden case is unchanged).

- [ ] **Step 5: Run the full baseline test**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/test_mcp_baseline.py -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/mcp_baseline/markland_admin_metrics.json
git commit -m "test(mcp-baseline): refresh markland_admin_metrics snapshot for new keys"
```

---

### Task 11: Full-suite regression check

- [ ] **Step 1: Run the full test suite**

Run: `uv run --with pytest --with pytest-asyncio python -m pytest tests/ -x -q`
Expected: All pass. If anything outside the admin-metrics tests fails, investigate — there may be a place that hard-codes the response shape (e.g., a JSON-schema test). Fix in place.

- [ ] **Step 2: If a schema/shape test elsewhere fails, update it**

Likely candidates if they fail:
- `tests/test_mcp_schema.py` (if it exists) — may enumerate response keys.
- `tests/test_mcp_descriptions.py` — may verify docstring content; should still pass since `Args:` is unchanged.

For any failure, update the test to accept the expanded shape. Do not weaken assertions; just add the new keys to whatever set is being checked.

- [ ] **Step 3: Commit any cleanups**

```bash
git add -A
git commit -m "test: align ancillary tests with expanded admin metrics shape"
```

(Skip this commit if Step 1 already passed.)

---

### Task 12: Smoke-test against a fresh app instance

**Files:** none modified — this is a verification task.

- [ ] **Step 1: Start the dev server**

Run: `uv run --with .[dev] python -m markland.web.app` (or whatever the project's standard dev-server invocation is — see `README.md` or `AGENTS.md`).

- [ ] **Step 2: Hit the endpoint as admin**

In a second terminal, with an admin token to hand:

```bash
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" "http://localhost:8000/admin/metrics?window_seconds=86400" | python -m json.tool
```

Expected: JSON containing all the new keys with sane integer values.

- [ ] **Step 3: Hit the MCP tool as admin via the MCP transport**

Use whatever local-MCP test harness this project uses (check `AGENTS.md` or `docs/` for the agreed approach). Confirm the response includes the new keys.

- [ ] **Step 4: Stop the dev server**

No commit — this is verification only. Move on to Task 13.

---

### Task 13: Wrap up — push and clean up

- [ ] **Step 1: Confirm clean working tree and current branch**

Run: `git status && git branch --show-current`
Expected: Clean tree, on the feature branch (or `main` if doing direct-push per project conventions).

- [ ] **Step 2: Push**

If on a feature branch:
```bash
git push -u origin HEAD
gh pr create --title "feat(admin-metrics): expand summary with totals + tool-usage counts" --body "$(cat <<'EOF'
## Summary
- Adds `users_total`, `documents_total`, `documents_public_total`, `grants_total`, `invites_total` (unwindowed totals).
- Adds `documents_created`, `documents_updated`, `documents_deleted`, `grants_revoked`, `invites_created` (windowed audit-event counts).
- Existing keys unchanged — purely additive.
- Tests + MCP baseline snapshot updated.

## Test plan
- [x] `tests/test_admin_metrics_service.py` covers each new key
- [x] HTTP + MCP tests assert new keys appear in responses
- [x] MCP baseline snapshot regenerated
- [x] Full test suite passes

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

If on `main` (direct-push docs-only convention does NOT apply here — this is code, so prefer the PR flow even though the user previously authorized direct push for beads/docs commits).

- [ ] **Step 3: After merge, beads-close any related issue**

If a beads issue tracked this work:
```bash
bd list --status=open | grep -i metrics  # find the id
bd close <id> --reason="shipped: admin metrics expansion"
bd sync
```

---

## Self-Review Checklist (run before handing off)

- [ ] Every new key in the "New Return Shape" section has a Task that adds it.
- [ ] Every new key has both an implementation step and a test step.
- [ ] No placeholder text (`TBD`, `etc`, `similar to above`) — every code block is complete.
- [ ] Method signatures (`summary()` return shape) are consistent across tasks.
- [ ] `users_total` and `signups` are clearly distinguished (unwindowed vs windowed).
- [ ] `grants_total` (current active grants) and `grants_created` / `grants_revoked` (windowed events) are clearly distinguished.
- [ ] `invites_total` graceful-missing-table behavior is tested explicitly.
- [ ] The `first_mcp_call` known gap is preserved, not silently dropped.
