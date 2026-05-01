# Admin Metrics MCP Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `markland_admin_metrics` MCP tool (and a parallel `GET /admin/metrics` JSON endpoint) so an admin can ask their agent "what does the funnel look like this week?" and get a structured answer aggregated from the existing `users`, `api_tokens`, `audit_log`, and `waitlist` tables.

**Architecture:** A pure aggregation service `service/admin_metrics.py` queries the four existing tables and returns a `MetricsSummary` dict. The MCP tool wraps it with admin-permission check (mirroring `markland_audit`'s pattern); the HTTP endpoint mirrors `/admin/waitlist`'s bearer/admin gate. No new schema, no event-table; the `first_mcp_call` event is acknowledged as a known gap and explicitly returned as `null` (with a note pointing the operator at `flyctl logs`).

**Tech Stack:** SQLite via `sqlite3.Connection`, FastMCP server registration in `src/markland/server.py`, FastAPI endpoint in `src/markland/web/app.py`, existing `Principal` / `is_admin` auth pattern.

---

## File Structure

- Create: `src/markland/service/admin_metrics.py` — `summary(conn, window_seconds)` aggregator
- Modify: `src/markland/server.py` — register `markland_admin_metrics` MCP tool
- Modify: `src/markland/web/app.py` — add `GET /admin/metrics` HTTP endpoint
- Test: `tests/test_admin_metrics_service.py` — unit tests for the aggregator
- Test: `tests/test_admin_metrics_mcp.py` — MCP tool tests (admin-only, returns expected shape)
- Test: `tests/test_admin_metrics_http.py` — HTTP endpoint tests (401/403/200)

---

## Task 1: Service-level aggregator

**Files:**
- Create: `src/markland/service/admin_metrics.py`
- Test: `tests/test_admin_metrics_service.py`

- [ ] **Step 1.1: Inventory the existing schemas**

  ```bash
  grep -nA 3 "CREATE TABLE waitlist\|CREATE TABLE users\|CREATE TABLE api_tokens\|CREATE TABLE audit_log" src/markland/db.py
  ```

  Expected: shows the four schemas. Confirm columns:
  - `users`: `id`, `email`, `created_at` (ISO8601 string)
  - `api_tokens`: `id`, `user_id`, `created_at`
  - `audit_log`: `id`, `principal_id`, `action`, `target_id`, `created_at`, `payload_json`
  - `waitlist`: `id`, `email`, `source`, `created_at`

  If any column name differs, adapt the queries in Step 1.4 accordingly. The plan's queries below assume these names; update them if reality differs.

- [ ] **Step 1.2: Inventory audit-log action names**

  ```bash
  grep -rn "audit\.record\|action=" src/markland/service/ | grep -E "publish|grant|invite|update" | head -20
  ```

  Expected: shows the `action=` strings in current use. Common values:
  - `publish` (from `service/docs.py`)
  - `grant_create` / `grant_revoke` (from `service/grants.py`)
  - `invite_create` / `invite_accept` / `invite_revoke` (from `service/invites.py`)
  - `update` (from `service/docs.py`)

  If the actual strings differ, update the WHERE-clauses in Step 1.4.

- [ ] **Step 1.3: Write failing test**

  Create `tests/test_admin_metrics_service.py`:

  ```python
  import sqlite3
  import time

  import pytest

  from markland.db import init_schema
  from markland.service.admin_metrics import summary


  @pytest.fixture
  def conn():
      c = sqlite3.connect(":memory:")
      init_schema(c)
      return c


  def _seed_user(conn, user_id: str, email: str, created_at: str):
      conn.execute(
          "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
          (user_id, email, created_at),
      )
      conn.commit()


  def _seed_audit(conn, principal_id: str, action: str, target_id: str, created_at: str):
      conn.execute(
          "INSERT INTO audit_log (principal_id, action, target_id, created_at) VALUES (?, ?, ?, ?)",
          (principal_id, action, target_id, created_at),
      )
      conn.commit()


  def test_summary_empty_db(conn):
      result = summary(conn, window_seconds=86400)
      assert result["window_seconds"] == 86400
      assert result["signups"] == 0
      assert result["publishes"] == 0
      assert result["grants_created"] == 0
      assert result["invites_accepted"] == 0
      assert result["waitlist_total"] == 0
      assert result["first_mcp_call"] is None  # known gap, explicit


  def test_summary_counts_signups_in_window(conn):
      now = int(time.time())
      recent = f"2026-04-30T12:00:00Z"  # within 24h
      old = f"2026-04-01T12:00:00Z"  # outside 24h
      _seed_user(conn, "usr_a", "a@x.com", recent)
      _seed_user(conn, "usr_b", "b@x.com", old)
      result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
      assert result["signups"] == 1


  def test_summary_counts_audit_events(conn):
      now = "2026-05-01T00:00:00Z"
      _seed_audit(conn, "usr_a", "publish", "doc_1", "2026-04-30T22:00:00Z")
      _seed_audit(conn, "usr_a", "publish", "doc_2", "2026-04-30T23:00:00Z")
      _seed_audit(conn, "usr_a", "grant_create", "doc_1", "2026-04-30T22:30:00Z")
      _seed_audit(conn, "usr_a", "invite_accept", "inv_1", "2026-04-30T23:30:00Z")
      result = summary(conn, window_seconds=86400, now_iso=now)
      assert result["publishes"] == 2
      assert result["grants_created"] == 1
      assert result["invites_accepted"] == 1


  def test_summary_waitlist_total_unbounded_by_window(conn):
      conn.execute(
          "INSERT INTO waitlist (email, source, created_at) VALUES (?, ?, ?)",
          ("c@x.com", "landing", "2025-01-01T00:00:00Z"),
      )
      conn.commit()
      result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
      assert result["waitlist_total"] == 1  # waitlist is total, not windowed


  def test_summary_includes_window_start_and_end(conn):
      result = summary(conn, window_seconds=86400, now_iso="2026-05-01T00:00:00Z")
      assert result["window_end_iso"] == "2026-05-01T00:00:00Z"
      assert result["window_start_iso"] == "2026-04-30T00:00:00Z"
  ```

- [ ] **Step 1.4: Run test to verify failure**

  ```bash
  uv run pytest tests/test_admin_metrics_service.py -v
  ```

  Expected: `ImportError: cannot import name 'summary' from 'markland.service.admin_metrics'`.

- [ ] **Step 1.5: Implement the aggregator**

  Create `src/markland/service/admin_metrics.py`:

  ```python
  """Admin funnel metrics aggregated from existing tables.

  Pure aggregation: reads users/api_tokens/audit_log/waitlist and returns a
  flat dict. Window is operator-supplied seconds; waitlist_total is unwindowed.

  first_mcp_call is a known gap — emitted to stdout only, not persisted.
  Returned as None until a metrics_events table is added.
  """

  from __future__ import annotations

  import datetime as _dt
  import sqlite3
  from typing import Any


  def _now_iso() -> str:
      return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


  def _shift(iso: str, seconds: int) -> str:
      ts = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
      ts = ts - _dt.timedelta(seconds=seconds)
      return ts.isoformat().replace("+00:00", "Z")


  def summary(
      conn: sqlite3.Connection,
      *,
      window_seconds: int,
      now_iso: str | None = None,
  ) -> dict[str, Any]:
      """Aggregate funnel events over a time window.

      Args:
        conn: SQLite connection.
        window_seconds: window size, e.g. 86400 (24h), 604800 (7d).
        now_iso: override for "now" in tests; defaults to current UTC.

      Returns:
        dict with keys: window_seconds, window_start_iso, window_end_iso,
        signups, publishes, grants_created, invites_accepted, waitlist_total,
        first_mcp_call.
      """
      end_iso = now_iso or _now_iso()
      start_iso = _shift(end_iso, window_seconds)

      def _count(query: str, params: tuple) -> int:
          row = conn.execute(query, params).fetchone()
          return int(row[0]) if row else 0

      signups = _count(
          "SELECT COUNT(*) FROM users WHERE created_at >= ? AND created_at < ?",
          (start_iso, end_iso),
      )
      publishes = _count(
          "SELECT COUNT(*) FROM audit_log WHERE action = 'publish' AND created_at >= ? AND created_at < ?",
          (start_iso, end_iso),
      )
      grants_created = _count(
          "SELECT COUNT(*) FROM audit_log WHERE action = 'grant_create' AND created_at >= ? AND created_at < ?",
          (start_iso, end_iso),
      )
      invites_accepted = _count(
          "SELECT COUNT(*) FROM audit_log WHERE action = 'invite_accept' AND created_at >= ? AND created_at < ?",
          (start_iso, end_iso),
      )
      waitlist_total = _count("SELECT COUNT(*) FROM waitlist", ())

      return {
          "window_seconds": window_seconds,
          "window_start_iso": start_iso,
          "window_end_iso": end_iso,
          "signups": signups,
          "publishes": publishes,
          "grants_created": grants_created,
          "invites_accepted": invites_accepted,
          "waitlist_total": waitlist_total,
          "first_mcp_call": None,  # not persisted; see flyctl logs
      }
  ```

- [ ] **Step 1.6: Run test to verify it passes**

  ```bash
  uv run pytest tests/test_admin_metrics_service.py -v
  ```

  Expected: 5 passed. If the audit-log action names differ from `'publish'` / `'grant_create'` / `'invite_accept'` (Step 1.2 inventory), update both the queries in Step 1.5 and the seed values in the test.

- [ ] **Step 1.7: Commit**

  ```bash
  git add src/markland/service/admin_metrics.py tests/test_admin_metrics_service.py
  git commit -m "feat(metrics): admin_metrics.summary() aggregates funnel from existing tables"
  ```

---

## Task 2: HTTP endpoint /admin/metrics

**Files:**
- Modify: `src/markland/web/app.py`
- Test: `tests/test_admin_metrics_http.py`

- [ ] **Step 2.1: Read the /admin/waitlist handler as the pattern to mirror**

  ```bash
  grep -nA 25 'def admin_waitlist' src/markland/web/app.py | head -40
  ```

  Expected: shows bearer-auth + `is_admin` gate. The new endpoint mirrors this exactly, swapping the body for a `summary(...)` call.

- [ ] **Step 2.2: Write failing tests**

  Create `tests/test_admin_metrics_http.py`:

  ```python
  import pytest
  from fastapi.testclient import TestClient

  from markland.web.app import create_app
  from markland.service import auth


  @pytest.fixture
  def client():
      return TestClient(create_app())


  def test_admin_metrics_unauthenticated_401(client):
      r = client.get("/admin/metrics")
      assert r.status_code == 401


  def test_admin_metrics_non_admin_403(client):
      # Create a non-admin user + token in the test DB. Pattern matches
      # tests/test_admin_waitlist.py — copy its setup helpers verbatim if
      # they exist, else inline a minimal user creation.
      from markland.db import init_schema
      from markland.service.users import create_user
      from markland.service.tokens import create_user_token

      conn = client.app.state.db_conn
      uid, _ = create_user(conn, email="user@x.com", is_admin=False)
      _, plaintext = create_user_token(conn, user_id=uid, label="test")
      r = client.get("/admin/metrics", headers={"Authorization": f"Bearer {plaintext}"})
      assert r.status_code == 403


  def test_admin_metrics_admin_returns_summary(client):
      from markland.service.users import create_user
      from markland.service.tokens import create_user_token

      conn = client.app.state.db_conn
      uid, _ = create_user(conn, email="admin@x.com", is_admin=True)
      _, plaintext = create_user_token(conn, user_id=uid, label="test")
      r = client.get(
          "/admin/metrics?window_seconds=86400",
          headers={"Authorization": f"Bearer {plaintext}"},
      )
      assert r.status_code == 200
      body = r.json()
      assert body["window_seconds"] == 86400
      assert "signups" in body
      assert "publishes" in body
      assert "grants_created" in body
      assert "invites_accepted" in body
      assert "waitlist_total" in body
      assert body["first_mcp_call"] is None


  def test_admin_metrics_default_window_is_7d(client):
      from markland.service.users import create_user
      from markland.service.tokens import create_user_token

      conn = client.app.state.db_conn
      uid, _ = create_user(conn, email="admin@x.com", is_admin=True)
      _, plaintext = create_user_token(conn, user_id=uid, label="test")
      r = client.get(
          "/admin/metrics",
          headers={"Authorization": f"Bearer {plaintext}"},
      )
      assert r.status_code == 200
      assert r.json()["window_seconds"] == 604800  # 7 days
  ```

  Adjust `create_user` / `create_user_token` import paths to match the actual helpers used by `tests/test_admin_waitlist.py` — copy that test file's setup first if needed.

- [ ] **Step 2.3: Run tests to verify failure**

  ```bash
  uv run pytest tests/test_admin_metrics_http.py -v
  ```

  Expected: 4 failures — endpoint doesn't exist yet, returns 404.

- [ ] **Step 2.4: Add the endpoint to app.py**

  In `src/markland/web/app.py`, find the `admin_waitlist` handler. Immediately below it, add:

  ```python
  @app.get("/admin/metrics")
  def admin_metrics(request: Request, window_seconds: int = 604800):
      from markland.service.admin_metrics import summary
      from markland.service.auth import resolve_token

      header = request.headers.get("authorization", "")
      if not header.lower().startswith("bearer "):
          return JSONResponse({"error": "unauthenticated"}, status_code=401)
      plaintext = header[7:].strip()
      principal = resolve_token(db_conn, plaintext)
      if principal is None:
          return JSONResponse({"error": "unauthenticated"}, status_code=401)
      if not principal.is_admin:
          return JSONResponse({"error": "forbidden"}, status_code=403)
      capped = max(60, min(window_seconds, 30 * 86400))  # 1 min to 30 days
      return JSONResponse(summary(db_conn, window_seconds=capped))
  ```

  (Match the surrounding helpers — `db_conn`, `JSONResponse` import — that the existing `admin_waitlist` already uses.)

- [ ] **Step 2.5: Run tests to verify they pass**

  ```bash
  uv run pytest tests/test_admin_metrics_http.py -v
  ```

  Expected: 4 passed.

- [ ] **Step 2.6: Commit**

  ```bash
  git add src/markland/web/app.py tests/test_admin_metrics_http.py
  git commit -m "feat(web): GET /admin/metrics JSON endpoint"
  ```

---

## Task 3: MCP tool markland_admin_metrics

**Files:**
- Modify: `src/markland/server.py`
- Test: `tests/test_admin_metrics_mcp.py`

- [ ] **Step 3.1: Read an existing admin-gated MCP tool as the pattern**

  ```bash
  grep -nA 25 'def markland_audit\|@mcp\.tool.*audit' src/markland/server.py | head -50
  ```

  Expected: shows the `markland_audit` tool registration, its admin-gate, and its return-shape. The new tool mirrors the structure.

- [ ] **Step 3.2: Write failing tests**

  Create `tests/test_admin_metrics_mcp.py`:

  ```python
  import pytest

  from markland.server import build_server


  @pytest.fixture
  def admin_principal():
      from markland.service.principal import Principal
      return Principal(id="usr_admin", type="user", is_admin=True)


  @pytest.fixture
  def user_principal():
      from markland.service.principal import Principal
      return Principal(id="usr_user", type="user", is_admin=False)


  def test_admin_metrics_tool_returns_summary(admin_principal, conn_with_schema):
      server = build_server(conn=conn_with_schema)
      result = server.call_tool(
          "markland_admin_metrics",
          {"window_seconds": 86400},
          principal=admin_principal,
      )
      assert "signups" in result
      assert "publishes" in result
      assert result["window_seconds"] == 86400


  def test_admin_metrics_tool_rejects_non_admin(user_principal, conn_with_schema):
      server = build_server(conn=conn_with_schema)
      with pytest.raises(PermissionError):  # or whatever the existing MCP admin gate raises
          server.call_tool(
              "markland_admin_metrics",
              {"window_seconds": 86400},
              principal=user_principal,
          )


  def test_admin_metrics_tool_default_window(admin_principal, conn_with_schema):
      server = build_server(conn=conn_with_schema)
      result = server.call_tool(
          "markland_admin_metrics",
          {},
          principal=admin_principal,
      )
      assert result["window_seconds"] == 604800
  ```

  Use the existing test-helper fixtures from `conftest.py` (`conn_with_schema`, `build_server`) — adapt names if those fixtures don't exist; check `tests/test_mcp_audit.py` for the actual pattern.

- [ ] **Step 3.3: Run tests to verify failure**

  ```bash
  uv run pytest tests/test_admin_metrics_mcp.py -v
  ```

  Expected: 3 failures — tool not registered.

- [ ] **Step 3.4: Register the MCP tool**

  In `src/markland/server.py`, find the section where `markland_audit` is registered. Add a new tool registration alongside it, mirroring the same structure (admin check, parameter shape, JSON return):

  ```python
  @mcp.tool()
  def markland_admin_metrics(
      window_seconds: int = 604800,
      ctx: Context = None,
  ) -> dict:
      """Funnel metrics summary over a time window. Admin-only.

      Aggregates from users/audit_log/waitlist tables. window_seconds defaults
      to 604800 (7 days), capped at 30 days. first_mcp_call is currently
      null — that event lives in stdout logs only; check `flyctl logs`.
      """
      from markland.service.admin_metrics import summary

      principal = _principal_from_ctx(ctx)
      if not principal.is_admin:
          raise PermissionError("admin required")
      capped = max(60, min(window_seconds, 30 * 86400))
      return summary(_conn(), window_seconds=capped)
  ```

  (Substitute `_principal_from_ctx` and `_conn` for whatever the existing `markland_audit` tool uses to access principal + DB. Read 5-10 lines around the `markland_audit` definition before writing this.)

- [ ] **Step 3.5: Run tests to verify they pass**

  ```bash
  uv run pytest tests/test_admin_metrics_mcp.py -v
  ```

  Expected: 3 passed.

- [ ] **Step 3.6: Update the MCP baseline snapshot**

  ```bash
  uv run pytest tests/test_mcp_harness.py --snapshot-update -v
  ```

  Expected: a new `tests/fixtures/mcp_baseline/markland_admin_metrics.json` is created. Inspect it to confirm the tool shape matches expectations.

- [ ] **Step 3.7: Commit**

  ```bash
  git add src/markland/server.py tests/test_admin_metrics_mcp.py tests/fixtures/mcp_baseline/markland_admin_metrics.json
  git commit -m "feat(mcp): markland_admin_metrics tool"
  ```

---

## Task 4: Final verification + roadmap update

**Files:**
- Modify: `docs/ROADMAP.md`
- Modify: `docs/FOLLOW-UPS.md` — add a tech-debt note about `first_mcp_call` persistence gap

- [ ] **Step 4.1: Run full test suite**

  ```bash
  uv run pytest tests/ -q
  ```

  Expected: previous baseline + 12 new tests (5 service + 4 HTTP + 3 MCP), all passing.

- [ ] **Step 4.2: Smoke against live deploy**

  Once deployed (use the launch-group-bug workaround from `docs/FOLLOW-UPS.md`):

  ```bash
  curl -sS https://markland.dev/admin/metrics?window_seconds=86400 \
    -H "Authorization: Bearer <admin-token>" | jq .
  ```

  Expected: JSON response with the 9 keys, all numbers (or `null` for `first_mcp_call`). If non-zero values appear, post-launch funnel is alive.

- [ ] **Step 4.3: Add ROADMAP "Shipped" entry**

  In `docs/ROADMAP.md`, "Hosted infrastructure + ops" Shipped subsection, add at the top:

  ```markdown
  - **<TODAY-YYYY-MM-DD>** — `markland_admin_metrics` MCP tool + `GET /admin/metrics` JSON endpoint. Aggregates signups, publishes, grants_created, invites_accepted from existing tables over a configurable window (default 7d, cap 30d) plus unwindowed waitlist_total. Admin-only via existing `is_admin` gate. `first_mcp_call` returned as null pending event-table follow-up.
  ```

- [ ] **Step 4.4: Add FOLLOW-UPS gap note**

  In `docs/FOLLOW-UPS.md`, under "Test coverage" or a new "Metrics" section, add:

  ```markdown
  - **`first_mcp_call` event persistence** — `service/metrics.py::emit_first_time` writes to stdout only. The new `markland_admin_metrics` tool returns `first_mcp_call: null` because there's no DB row to count. Either add a `metrics_events (event, principal_id, created_at)` table written alongside stdout, or parse `flyctl logs` from the tool. Cheapest path is the table; one ALTER + one write per emit.
  ```

- [ ] **Step 4.5: Commit and push**

  ```bash
  git add docs/ROADMAP.md docs/FOLLOW-UPS.md
  git commit -m "docs: ship admin-metrics tool + flag first_mcp_call gap"
  git push origin main
  ```

  Expected: push succeeds (docs-only direct-to-main is permitted by the existing settings rule).

---

## Verification matrix

| Check | Command | Expected |
|---|---|---|
| Service aggregator | `uv run pytest tests/test_admin_metrics_service.py -v` | 5 pass |
| HTTP endpoint | `uv run pytest tests/test_admin_metrics_http.py -v` | 4 pass |
| MCP tool | `uv run pytest tests/test_admin_metrics_mcp.py -v` | 3 pass |
| MCP baseline snapshot | `uv run pytest tests/test_mcp_harness.py -v` | passes |
| Full suite | `uv run pytest tests/ -q` | baseline + 12 new, all pass |
| Live HTTP | `curl ... /admin/metrics ...` | 200, JSON with 9 keys |
| Live MCP | agent calls `markland_admin_metrics` | returns same shape |

---

## Self-review

**Spec coverage check:**
- Aggregate signups → Task 1.5 ✓
- Aggregate funnel events from audit_log → Task 1.5 ✓
- Aggregate waitlist total → Task 1.5 ✓
- HTTP endpoint mirroring `/admin/waitlist` → Task 2 ✓
- MCP tool mirroring `markland_audit` → Task 3 ✓
- Admin-only enforcement → Task 2.4 + Task 3.4 ✓
- TDD throughout → Steps 1.3, 2.2, 3.2 (write failing test first) ✓
- Acknowledge `first_mcp_call` gap → returned as null + FOLLOW-UPS note ✓
- Window cap → both endpoints cap at 30d, floor 60s ✓
- ROADMAP reconciliation → Task 4.3 ✓

**Placeholder scan:** No `TBD`/`TODO`/`fill in`. The two `<admin-token>` and one `<TODAY-YYYY-MM-DD>` strings are explicit operator-substitution placeholders.

**Type/name consistency:**
- `summary(conn, window_seconds, now_iso)` signature consistent across service definition (1.5), HTTP caller (2.4), MCP caller (3.4)
- Returned dict keys identical across service and both wrappers: `window_seconds`, `window_start_iso`, `window_end_iso`, `signups`, `publishes`, `grants_created`, `invites_accepted`, `waitlist_total`, `first_mcp_call`
- Test file names: `tests/test_admin_metrics_{service,http,mcp}.py` consistent throughout

**Known limitations called out:**
- `first_mcp_call` is null (logged as gap)
- Audit-log action strings inventoried in 1.2 — if names differ in current code, queries need adjustment
- `_seed_user` / `_seed_audit` test helpers assume specific column names; 1.1 inventory step verifies before implementing
