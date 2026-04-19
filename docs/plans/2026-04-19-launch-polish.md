# Launch Polish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Note:** No git commits during execution — this project is not a git repo at time of writing; the user manages version control manually. Where commit steps would normally appear, a "verification" step is substituted.

**Goal:** Close out Plans 1–9 with the launch-gate bundle: per-principal rate limiting, an audit log wired into every mutating service call, an admin audit page + MCP tool, a `/quickstart` onboarding page, a session-aware `/explore` toggle, a Sentry runbook, an activation-funnel metrics emitter, a Phase 0 dogfooding checklist, and a rewritten README. Ends when the spec §14 success-criteria end-to-end test passes — that test is the launch gate.

**Architecture:** Two middlewares compose inside `create_app` in order: `PrincipalMiddleware` (from Plan 2) resolves the bearer token onto `request.state.principal`, then `RateLimitMiddleware` reads that principal (or the `X-Forwarded-For` IP for anonymous requests) to pick a tier and consult an in-process async token bucket. `service/audit.py` is a best-effort recorder called from `service/docs.py`, `service/grants.py`, and `service/invites.py` — it never raises. `service/metrics.py` writes JSON-line events to stdout for scraping by Fly's log pipeline. No new persistent dependencies, no Redis, no Prometheus.

**Tech Stack:** Python 3.12, FastAPI, FastMCP, Starlette middleware, SQLite (existing, new `audit_log` table via inline `CREATE TABLE IF NOT EXISTS` in `db.py`), stdlib `logging` with a JSON formatter, Jinja2 for the two new HTML pages.

**Scope excluded (this plan):** Distributed rate limiting, persistent metrics store, Prometheus/OpenTelemetry exporters, a real admin UI beyond the one read-only page, audit-log pagination beyond `limit`, a "forgot my token" flow, Phase 1/Phase 2 rollout work. Anything beyond spec §14 success criteria is Plan 11+ (which does not exist yet — this is the final plan of 10).

---

## File Structure

**New files:**
- `src/markland/service/rate_limit.py` — async token-bucket with LRU eviction
- `src/markland/service/audit.py` — best-effort `record()` + `list_recent()`
- `src/markland/service/metrics.py` — `emit()` + `emit_first_time()` JSON-line writers
- `src/markland/web/rate_limit_middleware.py` — `RateLimitMiddleware` (Starlette BaseHTTPMiddleware)
- `src/markland/web/templates/quickstart.html` — five-step onboarding page
- `src/markland/web/templates/admin_audit.html` — admin-only audit log viewer
- `tests/test_rate_limit.py` — token-bucket unit tests + middleware integration
- `tests/test_audit_service.py` — unit tests for `audit.record` / `list_recent`
- `tests/test_audit_integration.py` — end-to-end: service calls write audit rows
- `tests/test_metrics.py` — stdout JSON + first-time-only emission
- `tests/test_metrics_funnel.py` — six-event activation funnel
- `tests/test_explore_auth_toggle.py` — session-aware `/explore`
- `tests/test_quickstart_page.py` — `/quickstart` renders 200
- `tests/test_admin_audit.py` — `/admin/audit` HTML + `markland_audit` tool, admin-only
- `tests/test_launch_e2e.py` — spec §14 end-to-end launch gate
- `docs/runbooks/sentry-setup.md` — alert configuration runbook
- `docs/runbooks/phase-0-checklist.md` — operator launch-gate checklist

**Modified files:**
- `src/markland/db.py` — add `audit_log` table + `record_audit` row helper
- `src/markland/service/docs.py` — call `audit.record` in publish/update/delete
- `src/markland/service/grants.py` — call `audit.record` in grant/revoke
- `src/markland/service/invites.py` — call `audit.record` in create/accept
- `src/markland/service/auth.py` — `metrics.emit` on signup + token_create
- `src/markland/server.py` — register `markland_audit` MCP tool (admin-only)
- `src/markland/web/app.py` — add `RateLimitMiddleware`, `/quickstart`, `/admin/audit`, `/explore` auth toggle
- `src/markland/run_app.py` — JSON log formatter
- `pyproject.toml` — no new deps (kept lean)
- `README.md` — full rewrite (hosted-first, drops stdio-only setup as primary path)
- `.env.example` — add three optional rate-limit overrides

---

## Task 1: `audit_log` table + db helper

**Files:**
- Modify: `src/markland/db.py`
- Create: `tests/test_audit_service.py` (scaffold only — fleshed out in Task 2)

- [ ] **Step 1: Write the failing schema test**

Create `tests/test_audit_service.py`:

```python
"""Tests for the audit-log table and service."""

import json
import sqlite3

import pytest

from markland.db import init_db


@pytest.fixture
def conn(tmp_path) -> sqlite3.Connection:
    return init_db(tmp_path / "test.db")


def test_audit_log_table_exists(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'"
    ).fetchone()
    assert row is not None


def test_audit_log_columns(conn: sqlite3.Connection) -> None:
    cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
    assert cols["id"].upper() == "INTEGER"
    assert cols["doc_id"].upper() == "TEXT"
    assert cols["action"].upper() == "TEXT"
    assert cols["principal_id"].upper() == "TEXT"
    assert cols["principal_type"].upper() == "TEXT"
    assert cols["metadata"].upper() == "TEXT"
    assert cols["created_at"].upper() == "TEXT"


def test_record_audit_inserts_row(conn: sqlite3.Connection) -> None:
    from markland.db import record_audit

    record_audit(
        conn,
        doc_id="doc_1",
        action="publish",
        principal_id="usr_abc",
        principal_type="user",
        metadata={"title": "hello"},
    )
    row = conn.execute(
        "SELECT doc_id, action, principal_id, principal_type, metadata FROM audit_log"
    ).fetchone()
    assert row[0] == "doc_1"
    assert row[1] == "publish"
    assert row[2] == "usr_abc"
    assert row[3] == "user"
    assert json.loads(row[4]) == {"title": "hello"}


def test_record_audit_allows_null_doc_id(conn: sqlite3.Connection) -> None:
    from markland.db import record_audit

    record_audit(
        conn,
        doc_id=None,
        action="invite_accept",
        principal_id="usr_xyz",
        principal_type="user",
        metadata=None,
    )
    row = conn.execute("SELECT doc_id, metadata FROM audit_log").fetchone()
    assert row[0] is None
    assert row[1] == "{}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_service.py -v`
Expected: FAIL — `audit_log` table does not exist; `record_audit` not importable.

- [ ] **Step 3: Add `audit_log` schema and helper to `src/markland/db.py`**

Inside the existing `init_db` function, append this block after the last existing `CREATE TABLE IF NOT EXISTS` (keep the existing `_add_column_if_missing` pattern for any later schema extensions):

```python
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT,
            action TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            principal_type TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log (created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_doc_id ON audit_log (doc_id)"
    )
    conn.commit()
```

Then add the helper at module scope (bottom of `db.py`):

```python
def record_audit(
    conn: sqlite3.Connection,
    *,
    doc_id: str | None,
    action: str,
    principal_id: str,
    principal_type: str,
    metadata: dict | None = None,
) -> None:
    """Insert one audit row. Commits. Callers should treat raises as fatal — the
    audit *service* wrapper in service/audit.py is what swallows exceptions."""
    import json as _json

    conn.execute(
        """
        INSERT INTO audit_log (doc_id, action, principal_id, principal_type, metadata)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            doc_id,
            action,
            principal_id,
            principal_type,
            _json.dumps(metadata or {}, separators=(",", ":"), sort_keys=True),
        ),
    )
    conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit_service.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Verification — full suite still green**

Run: `uv run pytest tests/ -v`
Expected: every previously-passing test still passes (the new table is additive).

---

## Task 2: `service/audit.py` — best-effort recorder + list_recent

**Files:**
- Create: `src/markland/service/audit.py`
- Modify: `tests/test_audit_service.py`

- [ ] **Step 1: Extend the failing tests**

Append to `tests/test_audit_service.py`:

```python
from markland.service.auth import Principal


def _principal(kind: str = "user") -> Principal:
    return Principal(
        principal_id="usr_a" if kind == "user" else "agt_a",
        principal_type=kind,  # type: ignore[arg-type]
        display_name="Alice",
        is_admin=False,
        user_id="usr_a" if kind == "user" else None,
    )


def test_service_record_writes_row(conn: sqlite3.Connection) -> None:
    from markland.service import audit

    audit.record(
        conn,
        action="publish",
        principal=_principal(),
        doc_id="doc_1",
        metadata={"title": "hi"},
    )
    row = conn.execute(
        "SELECT action, principal_id, principal_type FROM audit_log"
    ).fetchone()
    assert row == ("publish", "usr_a", "user")


def test_service_record_swallows_exceptions(conn: sqlite3.Connection, caplog) -> None:
    from markland.service import audit

    conn.close()  # force any write to raise
    # Must not raise; must log.
    audit.record(
        conn,
        action="publish",
        principal=_principal(),
        doc_id="doc_1",
    )
    assert any("audit" in r.message.lower() for r in caplog.records)


def test_service_list_recent_orders_by_created_at_desc(conn: sqlite3.Connection) -> None:
    from markland.service import audit

    for i in range(3):
        audit.record(
            conn,
            action="publish",
            principal=_principal(),
            doc_id=f"doc_{i}",
            metadata={"i": i},
        )
    rows = audit.list_recent(conn, limit=10)
    assert [r["doc_id"] for r in rows] == ["doc_2", "doc_1", "doc_0"]
    assert rows[0]["metadata"] == {"i": 2}


def test_service_list_recent_filters_by_doc_id(conn: sqlite3.Connection) -> None:
    from markland.service import audit

    audit.record(conn, action="publish", principal=_principal(), doc_id="doc_1")
    audit.record(conn, action="publish", principal=_principal(), doc_id="doc_2")
    rows = audit.list_recent(conn, doc_id="doc_1", limit=10)
    assert len(rows) == 1
    assert rows[0]["doc_id"] == "doc_1"


def test_service_list_recent_honors_limit(conn: sqlite3.Connection) -> None:
    from markland.service import audit

    for i in range(5):
        audit.record(conn, action="publish", principal=_principal(), doc_id=f"doc_{i}")
    rows = audit.list_recent(conn, limit=2)
    assert len(rows) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_service.py -v`
Expected: FAIL — `markland.service.audit` does not exist.

- [ ] **Step 3: Implement `service/audit.py`**

Create `src/markland/service/audit.py`:

```python
"""Audit-log service — best-effort recorder. Never raises on write failure.

Callers (service/docs.py, service/grants.py, service/invites.py) can fire-and-forget.
If the DB is down or the row is malformed, we log and move on. Business logic must
never fail because auditing failed.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from markland.db import record_audit
from markland.service.auth import Principal

logger = logging.getLogger("markland.audit")

_ALLOWED_ACTIONS = frozenset(
    {
        "publish",
        "update",
        "delete",
        "grant",
        "revoke",
        "invite_create",
        "invite_accept",
    }
)


def record(
    conn: sqlite3.Connection,
    *,
    action: str,
    principal: Principal,
    doc_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write one audit row. Swallows all exceptions (logs at WARNING)."""
    if action not in _ALLOWED_ACTIONS:
        logger.warning("audit: unknown action %r (still recording)", action)
    try:
        record_audit(
            conn,
            doc_id=doc_id,
            action=action,
            principal_id=principal.principal_id,
            principal_type=principal.principal_type,
            metadata=metadata,
        )
    except Exception as exc:
        logger.warning(
            "audit: failed to record action=%s principal=%s doc=%s err=%s",
            action,
            principal.principal_id,
            doc_id,
            exc,
        )


def list_recent(
    conn: sqlite3.Connection,
    *,
    doc_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return most recent audit rows, newest first. Optionally filter by doc_id."""
    limit = max(1, min(int(limit), 1000))
    if doc_id is not None:
        cursor = conn.execute(
            """
            SELECT id, doc_id, action, principal_id, principal_type, metadata, created_at
            FROM audit_log
            WHERE doc_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (doc_id, limit),
        )
    else:
        cursor = conn.execute(
            """
            SELECT id, doc_id, action, principal_id, principal_type, metadata, created_at
            FROM audit_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
    rows: list[dict[str, Any]] = []
    for r in cursor.fetchall():
        try:
            meta = json.loads(r[5]) if r[5] else {}
        except json.JSONDecodeError:
            meta = {}
        rows.append(
            {
                "id": r[0],
                "doc_id": r[1],
                "action": r[2],
                "principal_id": r[3],
                "principal_type": r[4],
                "metadata": meta,
                "created_at": r[6],
            }
        )
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit_service.py -v`
Expected: PASS (9 tests total: 4 from Task 1 + 5 new).

- [ ] **Step 5: Verification — full suite**

Run: `uv run pytest tests/ -v`
Expected: all green.

---

## Task 3: Wire audit into `service/docs.py` (publish/update/delete)

**Files:**
- Modify: `src/markland/service/docs.py`
- Create: `tests/test_audit_integration.py` (scaffold; fleshed out in Task 4)

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_audit_integration.py`:

```python
"""Integration: service-layer calls must write audit rows."""

import sqlite3

import pytest

from markland.db import init_db
from markland.service import docs as docs_svc
from markland.service.auth import Principal


@pytest.fixture
def conn(tmp_path) -> sqlite3.Connection:
    return init_db(tmp_path / "test.db")


@pytest.fixture
def alice(conn: sqlite3.Connection) -> Principal:
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice', 0, '2026-04-19T00:00:00Z')"
    )
    conn.commit()
    return Principal(
        principal_id="usr_alice",
        principal_type="user",
        display_name="Alice",
        is_admin=False,
        user_id="usr_alice",
    )


def _audit_rows(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT action, doc_id, principal_id FROM audit_log ORDER BY id"
    ).fetchall()


def test_publish_writes_audit_row(conn, alice):
    result = docs_svc.publish_doc(
        conn,
        base_url="https://markland.dev",
        principal=alice,
        title="Hello",
        content="# Hi",
    )
    rows = _audit_rows(conn)
    assert len(rows) == 1
    assert rows[0][0] == "publish"
    assert rows[0][1] == result["id"]
    assert rows[0][2] == "usr_alice"


def test_update_writes_audit_row(conn, alice):
    result = docs_svc.publish_doc(
        conn, base_url="x", principal=alice, title="t", content="c"
    )
    doc = docs_svc.get_doc(conn, principal=alice, doc_id=result["id"])
    docs_svc.update_doc(
        conn,
        principal=alice,
        doc_id=result["id"],
        content="c2",
        if_version=doc.version,
    )
    rows = _audit_rows(conn)
    assert [r[0] for r in rows] == ["publish", "update"]


def test_delete_writes_audit_row(conn, alice):
    result = docs_svc.publish_doc(
        conn, base_url="x", principal=alice, title="t", content="c"
    )
    docs_svc.delete_doc(conn, principal=alice, doc_id=result["id"])
    rows = _audit_rows(conn)
    assert [r[0] for r in rows] == ["publish", "delete"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_integration.py -v`
Expected: FAIL — no audit rows written by service/docs.

- [ ] **Step 3: Wire `audit.record` into `service/docs.py`**

In `src/markland/service/docs.py`, add at the top of the file (alongside other imports):

```python
from markland.service import audit
```

In `publish_doc`, immediately before the `return` statement at the end of the function, add:

```python
    audit.record(
        conn,
        action="publish",
        principal=principal,
        doc_id=result["id"],
        metadata={"title": result.get("title"), "is_public": bool(result.get("is_public"))},
    )
```

In `update_doc`, immediately before the `return` statement, add (substitute the local variable holding the post-update Document for `updated` if the file names it differently):

```python
    audit.record(
        conn,
        action="update",
        principal=principal,
        doc_id=doc_id,
        metadata={"new_version": updated.version},
    )
```

In `delete_doc`, immediately before the function returns (or at the end if it returns `None`), add:

```python
    audit.record(
        conn,
        action="delete",
        principal=principal,
        doc_id=doc_id,
        metadata={},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit_integration.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Verification — the whole suite still green**

Run: `uv run pytest tests/ -v`
Expected: all green; existing docs tests unaffected because auditing is additive.

---

## Task 4: Wire audit into grants + invites

**Files:**
- Modify: `src/markland/service/grants.py`
- Modify: `src/markland/service/invites.py`
- Modify: `tests/test_audit_integration.py`

- [ ] **Step 1: Extend the failing tests**

Append to `tests/test_audit_integration.py`:

```python
from markland.service import grants as grants_svc
from markland.service import invites as invites_svc
from markland.service.email import EmailClient


class _NoopEmail(EmailClient):
    def __init__(self) -> None:
        super().__init__(api_key="", from_email="test@m.dev")


@pytest.fixture
def bob(conn: sqlite3.Connection) -> Principal:
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_bob', 'bob@example.com', 'Bob', 0, '2026-04-19T00:00:00Z')"
    )
    conn.commit()
    return Principal(
        principal_id="usr_bob",
        principal_type="user",
        display_name="Bob",
        is_admin=False,
        user_id="usr_bob",
    )


def test_grant_writes_audit_row(conn, alice, bob):
    doc = docs_svc.publish_doc(
        conn, base_url="x", principal=alice, title="t", content="c"
    )
    grants_svc.grant(
        conn,
        base_url="x",
        principal=alice,
        doc_id=doc["id"],
        target="bob@example.com",
        level="view",
        email_client=_NoopEmail(),
    )
    actions = [r[0] for r in _audit_rows(conn)]
    assert actions == ["publish", "grant"]


def test_revoke_writes_audit_row(conn, alice, bob):
    doc = docs_svc.publish_doc(
        conn, base_url="x", principal=alice, title="t", content="c"
    )
    grants_svc.grant(
        conn,
        base_url="x",
        principal=alice,
        doc_id=doc["id"],
        target="bob@example.com",
        level="view",
        email_client=_NoopEmail(),
    )
    grants_svc.revoke(
        conn, principal=alice, doc_id=doc["id"], principal_id="usr_bob"
    )
    actions = [r[0] for r in _audit_rows(conn)]
    assert actions == ["publish", "grant", "revoke"]


def test_invite_create_and_accept_write_audit_rows(conn, alice, bob):
    doc = docs_svc.publish_doc(
        conn, base_url="x", principal=alice, title="t", content="c"
    )
    invite_id, _url = invites_svc.create_invite(
        conn,
        doc_id=doc["id"],
        created_by_user_id="usr_alice",
        level="view",
    )
    # Look up the raw invite token. Plan 5 persists it on the invites row or a
    # sibling table; adapt the SELECT to match. The invariant under test is the
    # three-action audit sequence below, not the storage shape.
    token_row = conn.execute(
        "SELECT token FROM invite_tokens WHERE invite_id = ?",
        (invite_id,),
    ).fetchone()
    invites_svc.accept_invite(
        conn, invite_token=token_row[0], user_id="usr_bob"
    )
    actions = [r[0] for r in _audit_rows(conn)]
    assert actions == ["publish", "invite_create", "invite_accept"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_integration.py -v`
Expected: FAIL — grants and invites don't audit yet.

- [ ] **Step 3: Wire `audit.record` into grants and invites**

In `src/markland/service/grants.py`, add:

```python
from markland.service import audit
```

Inside `grant(...)`, immediately before returning, add:

```python
    audit.record(
        conn,
        action="grant",
        principal=principal,
        doc_id=doc_id,
        metadata={"target": target, "level": level},
    )
```

Inside `revoke(...)`, immediately before returning, add:

```python
    audit.record(
        conn,
        action="revoke",
        principal=principal,
        doc_id=doc_id,
        metadata={"target_principal_id": principal_id},
    )
```

In `src/markland/service/invites.py`, add:

```python
from markland.service import audit
from markland.service.auth import Principal
```

Inside `create_invite(...)`, immediately before returning, add:

```python
    audit.record(
        conn,
        action="invite_create",
        principal=Principal(
            principal_id=created_by_user_id,
            principal_type="user",
            display_name="",
            is_admin=False,
            user_id=created_by_user_id,
        ),
        doc_id=doc_id,
        metadata={"invite_id": invite_id, "level": level, "single_use": single_use},
    )
```

Inside `accept_invite(...)`, immediately before returning, add:

```python
    audit.record(
        conn,
        action="invite_accept",
        principal=Principal(
            principal_id=user_id,
            principal_type="user",
            display_name="",
            is_admin=False,
            user_id=user_id,
        ),
        doc_id=getattr(result, "doc_id", None),
        metadata={"invite_id": getattr(result, "invite_id", None)},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit_integration.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Verification — full suite**

Run: `uv run pytest tests/ -v`
Expected: all green.

---

## Task 5: `service/rate_limit.py` — async token bucket with LRU eviction

**Files:**
- Create: `src/markland/service/rate_limit.py`
- Create: `tests/test_rate_limit.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rate_limit.py`:

```python
"""Token-bucket rate limiter unit tests."""

import asyncio

import pytest

from markland.service.rate_limit import RateLimiter


def test_burst_allowed_up_to_limit():
    rl = RateLimiter(defaults={"user": (60, 60)}, max_keys=1000)

    async def run():
        results = []
        for _ in range(60):
            results.append(await rl.check("user:alice", tier="user"))
        return results

    results = asyncio.run(run())
    assert all(r.allowed for r in results)


def test_61st_request_returns_429_with_retry_after():
    rl = RateLimiter(defaults={"user": (60, 60)}, max_keys=1000)

    async def run():
        for _ in range(60):
            await rl.check("user:alice", tier="user")
        return await rl.check("user:alice", tier="user")

    r = asyncio.run(run())
    assert not r.allowed
    assert r.retry_after > 0
    assert r.retry_after <= 60


def test_bucket_refills_over_time(monkeypatch):
    rl = RateLimiter(defaults={"user": (2, 60)}, max_keys=1000)
    now = [1000.0]
    monkeypatch.setattr("markland.service.rate_limit.time.monotonic", lambda: now[0])

    async def run():
        assert (await rl.check("k", tier="user")).allowed
        assert (await rl.check("k", tier="user")).allowed
        assert not (await rl.check("k", tier="user")).allowed
        # Advance 30s → one token refilled (2 tokens / 60s = 1 token / 30s).
        now[0] += 30.0
        assert (await rl.check("k", tier="user")).allowed
        assert not (await rl.check("k", tier="user")).allowed

    asyncio.run(run())


def test_separate_keys_have_independent_buckets():
    rl = RateLimiter(defaults={"user": (1, 60)}, max_keys=1000)

    async def run():
        a = await rl.check("alice", tier="user")
        b = await rl.check("bob", tier="user")
        a2 = await rl.check("alice", tier="user")
        return a.allowed, b.allowed, a2.allowed

    a, b, a2 = asyncio.run(run())
    assert a is True
    assert b is True
    assert a2 is False


def test_tiers_select_correct_limits():
    rl = RateLimiter(
        defaults={"user": (60, 60), "agent": (120, 60), "anon": (20, 60)},
        max_keys=1000,
    )

    async def run():
        user_burst = [await rl.check("u", tier="user") for _ in range(61)]
        agent_burst = [await rl.check("a", tier="agent") for _ in range(121)]
        anon_burst = [await rl.check("n", tier="anon") for _ in range(21)]
        return user_burst, agent_burst, anon_burst

    u, a, n = asyncio.run(run())
    assert u[-1].allowed is False and all(x.allowed for x in u[:60])
    assert a[-1].allowed is False and all(x.allowed for x in a[:120])
    assert n[-1].allowed is False and all(x.allowed for x in n[:20])


def test_lru_eviction_triggers_beyond_max_keys():
    rl = RateLimiter(defaults={"user": (60, 60)}, max_keys=3)

    async def run():
        for k in ["a", "b", "c", "d"]:
            await rl.check(k, tier="user")
        return rl.size()

    size = asyncio.run(run())
    assert size <= 3


def test_unknown_tier_falls_back_to_anon():
    rl = RateLimiter(defaults={"anon": (1, 60)}, max_keys=1000)

    async def run():
        r1 = await rl.check("x", tier="mystery")
        r2 = await rl.check("x", tier="mystery")
        return r1.allowed, r2.allowed

    a, b = asyncio.run(run())
    assert a is True
    assert b is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_rate_limit.py -v`
Expected: FAIL — `RateLimiter` does not exist.

- [ ] **Step 3: Implement `service/rate_limit.py`**

Create `src/markland/service/rate_limit.py`:

```python
"""In-memory async token-bucket rate limiter.

Per-key bucket keyed by caller-supplied string (principal_id for authed requests,
IP for anonymous). Three tiers: user (60/min), agent (120/min), anon (20/min).
Defaults overridable via env in web/rate_limit_middleware.py.

LRU eviction: when the number of tracked keys exceeds max_keys, the least
recently checked key is dropped. Memory footprint is O(max_keys) — each entry
is two floats + a string key.

No persistence. No cross-process sharing. Process restart resets all buckets —
acceptable at ~100-user launch scale. See spec §11.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

Tier = Literal["user", "agent", "anon"]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: float  # seconds until one token is available; 0 if allowed


class RateLimiter:
    """Async-safe token bucket with LRU eviction."""

    def __init__(
        self,
        *,
        defaults: dict[str, tuple[int, int]],
        max_keys: int = 10_000,
    ) -> None:
        # defaults: tier -> (capacity, refill_period_seconds)
        self._defaults = defaults
        self._max = max_keys
        # key -> [tokens: float, last_refill: float, capacity: float, period: float]
        self._buckets: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = asyncio.Lock()

    def size(self) -> int:
        return len(self._buckets)

    async def check(self, key: str, *, tier: str) -> Decision:
        capacity, period = self._defaults.get(tier) or self._defaults.get(
            "anon", (20, 60)
        )
        now = time.monotonic()
        async with self._lock:
            if key in self._buckets:
                tokens, last, cap, per = self._buckets[key]
                elapsed = max(0.0, now - last)
                refill = (elapsed / per) * cap
                tokens = min(float(cap), tokens + refill)
                self._buckets.move_to_end(key)
            else:
                tokens, cap, per = float(capacity), float(capacity), float(period)
                self._buckets[key] = [tokens, now, cap, per]
                while len(self._buckets) > self._max:
                    self._buckets.popitem(last=False)

            if tokens >= 1.0:
                tokens -= 1.0
                self._buckets[key] = [tokens, now, cap, per]
                return Decision(allowed=True, retry_after=0.0)

            needed = 1.0 - tokens
            retry = (needed / cap) * per
            self._buckets[key] = [tokens, now, cap, per]
            return Decision(allowed=False, retry_after=float(retry))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_rate_limit.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Verification — full suite**

Run: `uv run pytest tests/ -v`
Expected: all green.

---

## Task 6: `RateLimitMiddleware` wired inside `create_app`

**Files:**
- Create: `src/markland/web/rate_limit_middleware.py`
- Modify: `src/markland/web/app.py`
- Modify: `.env.example`
- Modify: `tests/test_rate_limit.py` (add an integration test)

- [ ] **Step 1: Write the failing integration test**

Append to `tests/test_rate_limit.py`:

```python
from fastapi.testclient import TestClient


def test_middleware_returns_429_after_user_limit(tmp_path, monkeypatch):
    from markland.db import init_db
    from markland.web.app import create_app

    monkeypatch.setenv("MARKLAND_RATE_LIMIT_USER_PER_MIN", "3")
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "100")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    from markland.config import reset_config
    reset_config()

    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_a', 'a@a.com', 'A', 0, '2026-04-19T00:00:00Z')"
    )
    from markland.service.auth import create_user_token
    raw_token = create_user_token(conn, user_id="usr_a", label="test")
    conn.commit()

    app = create_app(conn, mount_mcp=False, admin_token="", base_url="http://t")
    client = TestClient(app)

    headers = {"Authorization": f"Bearer {raw_token}"}
    codes = [client.get("/health", headers=headers).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert 429 in codes[3:]

    # 429 response must carry Retry-After.
    r = client.get("/health", headers=headers)
    if r.status_code == 429:
        assert "retry-after" in {k.lower() for k in r.headers.keys()}


def test_middleware_unauthed_uses_ip_from_xff(tmp_path, monkeypatch):
    from markland.db import init_db
    from markland.web.app import create_app

    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "2")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    from markland.config import reset_config
    reset_config()

    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, admin_token="", base_url="http://t")
    client = TestClient(app)

    headers = {"X-Forwarded-For": "1.2.3.4"}
    codes = [client.get("/health", headers=headers).status_code for _ in range(4)]
    assert codes[:2] == [200, 200]
    assert 429 in codes[2:]

    r = client.get("/health", headers={"X-Forwarded-For": "5.6.7.8"})
    assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_rate_limit.py -v`
Expected: FAIL — middleware not wired.

- [ ] **Step 3: Implement the middleware**

Create `src/markland/web/rate_limit_middleware.py`:

```python
"""Starlette middleware that rate-limits every request using service/rate_limit.

Ordering: MUST be installed AFTER PrincipalMiddleware so `request.state.principal`
is already populated. In create_app we add PrincipalMiddleware first, then this.

Tier selection:
  - user token  → 60/min   (key: principal_id)
  - agent token → 120/min  (key: principal_id)
  - anonymous   → 20/min   (key: X-Forwarded-For first hop, else client.host)

Env overrides:
  MARKLAND_RATE_LIMIT_USER_PER_MIN
  MARKLAND_RATE_LIMIT_AGENT_PER_MIN
  MARKLAND_RATE_LIMIT_ANON_PER_MIN
"""

from __future__ import annotations

import math
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from markland.service.rate_limit import RateLimiter


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, limiter: RateLimiter | None = None) -> None:
        super().__init__(app)
        if limiter is None:
            limiter = RateLimiter(
                defaults={
                    "user": (_int_env("MARKLAND_RATE_LIMIT_USER_PER_MIN", 60), 60),
                    "agent": (_int_env("MARKLAND_RATE_LIMIT_AGENT_PER_MIN", 120), 60),
                    "anon": (_int_env("MARKLAND_RATE_LIMIT_ANON_PER_MIN", 20), 60),
                },
                max_keys=10_000,
            )
        self._limiter = limiter

    def _client_ip(self, request: Request) -> str:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        principal = getattr(request.state, "principal", None)
        if principal is None:
            tier = "anon"
            key = f"ip:{self._client_ip(request)}"
        else:
            tier = "user" if principal.principal_type == "user" else "agent"
            key = f"{principal.principal_type}:{principal.principal_id}"

        decision = await self._limiter.check(key, tier=tier)
        if not decision.allowed:
            retry = max(1, math.ceil(decision.retry_after))
            return JSONResponse(
                {"error": "rate_limited", "retry_after": retry},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
        return await call_next(request)
```

- [ ] **Step 4: Install the middleware inside `create_app`**

In `src/markland/web/app.py`, find the block where `PrincipalMiddleware` is added (Plan 2 wired this). Immediately after that line, add:

```python
    from markland.web.rate_limit_middleware import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)
```

Note: Starlette applies middleware in reverse of addition order, so adding `RateLimitMiddleware` *after* `PrincipalMiddleware` in code means requests flow Principal → RateLimit → handler. That is the required order.

- [ ] **Step 5: Update `.env.example`**

Append to `.env.example`:

```
# Rate-limit overrides (optional). Defaults: 60 / 120 / 20 per minute.
MARKLAND_RATE_LIMIT_USER_PER_MIN=60
MARKLAND_RATE_LIMIT_AGENT_PER_MIN=120
MARKLAND_RATE_LIMIT_ANON_PER_MIN=20
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_rate_limit.py -v`
Expected: PASS (9 tests).

- [ ] **Step 7: Verification — full suite**

Run: `uv run pytest tests/ -v`
Expected: all green. Existing tests can set high `MARKLAND_RATE_LIMIT_*_PER_MIN` env vars via their `monkeypatch` fixture if the 20/min anon default pressures a busy test module.

---

## Task 7: `service/metrics.py` — funnel emitter

**Files:**
- Create: `src/markland/service/metrics.py`
- Create: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_metrics.py`:

```python
"""Activation-funnel metrics emitter."""

import json

import pytest

from markland.service import metrics


@pytest.fixture(autouse=True)
def _reset_first_time():
    metrics._reset_for_tests()
    yield
    metrics._reset_for_tests()


def test_emit_writes_json_line(capsys):
    metrics.emit("test_event", principal_id="usr_a", foo="bar", n=3)
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["event"] == "test_event"
    assert payload["principal_id"] == "usr_a"
    assert payload["foo"] == "bar"
    assert payload["n"] == 3
    assert "ts" in payload


def test_emit_without_principal_still_emits(capsys):
    metrics.emit("signup_started", source="web")
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["event"] == "signup_started"
    assert payload["principal_id"] is None
    assert payload["source"] == "web"


def test_emit_first_time_emits_once_per_principal(capsys):
    metrics.emit_first_time("first_publish", principal_id="usr_a")
    metrics.emit_first_time("first_publish", principal_id="usr_a")
    metrics.emit_first_time("first_publish", principal_id="usr_a")
    lines = [l for l in capsys.readouterr().out.strip().splitlines() if l]
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "first_publish"


def test_emit_first_time_independent_per_principal(capsys):
    metrics.emit_first_time("first_publish", principal_id="usr_a")
    metrics.emit_first_time("first_publish", principal_id="usr_b")
    lines = [l for l in capsys.readouterr().out.strip().splitlines() if l]
    assert len(lines) == 2
    assert {json.loads(l)["principal_id"] for l in lines} == {"usr_a", "usr_b"}


def test_emit_first_time_independent_per_event(capsys):
    metrics.emit_first_time("first_publish", principal_id="usr_a")
    metrics.emit_first_time("first_grant", principal_id="usr_a")
    lines = [l for l in capsys.readouterr().out.strip().splitlines() if l]
    assert len(lines) == 2
    assert {json.loads(l)["event"] for l in lines} == {"first_publish", "first_grant"}


def test_emit_first_time_requires_principal_id():
    with pytest.raises(ValueError):
        metrics.emit_first_time("first_publish", principal_id=None)  # type: ignore[arg-type]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `service/metrics.py`**

Create `src/markland/service/metrics.py`:

```python
"""Activation-funnel metrics — JSON-line events to stdout.

Intentionally minimal: stdout is captured by Fly's log pipeline; downstream
(Axiom, Grafana, whatever) can parse JSON lines. No Prometheus, no StatsD.

emit()            — always emits
emit_first_time() — emits only the first time a (event, principal_id) pair
                    is seen in this process. Survives only until restart; use
                    it for funnel *firsts*, not for persistent cohort tracking.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from typing import Any

_seen: set[tuple[str, str]] = set()


def _reset_for_tests() -> None:
    _seen.clear()


def emit(event: str, *, principal_id: str | None = None, **fields: Any) -> None:
    payload: dict[str, Any] = {
        "event": event,
        "principal_id": principal_id,
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    for k, v in fields.items():
        payload[k] = v
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
    sys.stdout.flush()


def emit_first_time(event: str, *, principal_id: str) -> None:
    if not principal_id:
        raise ValueError("emit_first_time requires a non-empty principal_id")
    key = (event, principal_id)
    if key in _seen:
        return
    _seen.add(key)
    emit(event, principal_id=principal_id, first_time=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Verification — full suite**

Run: `uv run pytest tests/ -v`
Expected: all green.

---

## Task 8: Wire funnel events

**Files:**
- Modify: `src/markland/service/auth.py`
- Modify: `src/markland/service/docs.py`
- Modify: `src/markland/service/grants.py`
- Modify: `src/markland/service/invites.py`
- Modify: `src/markland/web/rate_limit_middleware.py` (first_mcp_call hook — cheapest location that sees every authed MCP request)
- Create: `tests/test_metrics_funnel.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_metrics_funnel.py`:

```python
"""End-to-end funnel emission — six events should fire across a user's first session."""

import json

import pytest

from markland.db import init_db
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service import invites as invites_svc
from markland.service import metrics
from markland.service.auth import Principal, create_user, create_user_token
from markland.service.email import EmailClient


class _NoopEmail(EmailClient):
    def __init__(self):
        super().__init__(api_key="", from_email="t@t.dev")


@pytest.fixture(autouse=True)
def _reset_metrics():
    metrics._reset_for_tests()
    yield
    metrics._reset_for_tests()


def _events(capsys) -> list[dict]:
    out = capsys.readouterr().out
    return [json.loads(l) for l in out.splitlines() if l.strip().startswith("{")]


def test_full_funnel_emits_six_events(tmp_path, capsys):
    conn = init_db(tmp_path / "f.db")

    # 1. signup
    alice_id = create_user(conn, email="alice@ex.com", display_name="Alice")
    # 2. token_create
    create_user_token(conn, user_id=alice_id, label="laptop")

    alice = Principal(
        principal_id=alice_id,
        principal_type="user",
        display_name="Alice",
        is_admin=False,
        user_id=alice_id,
    )

    # 3. first_mcp_call — middleware emits this in the live path; simulate here.
    metrics.emit_first_time("first_mcp_call", principal_id=alice_id)

    # 4. first_publish
    doc = docs_svc.publish_doc(
        conn, base_url="x", principal=alice, title="t", content="c"
    )
    # 5. first_grant
    bob_id = create_user(conn, email="bob@ex.com", display_name="Bob")
    grants_svc.grant(
        conn,
        base_url="x",
        principal=alice,
        doc_id=doc["id"],
        target="bob@ex.com",
        level="view",
        email_client=_NoopEmail(),
    )
    # 6. first_invite_accept
    invite_id, _url = invites_svc.create_invite(
        conn, doc_id=doc["id"], created_by_user_id=alice_id, level="view"
    )
    token_row = conn.execute(
        "SELECT token FROM invite_tokens WHERE invite_id = ?", (invite_id,)
    ).fetchone()
    invites_svc.accept_invite(conn, invite_token=token_row[0], user_id=bob_id)

    events = _events(capsys)
    names = {e["event"] for e in events}
    assert "signup" in names
    assert "token_create" in names
    assert "first_mcp_call" in names
    assert "first_publish" in names
    assert "first_grant" in names
    assert "first_invite_accept" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metrics_funnel.py -v`
Expected: FAIL — events not emitted.

- [ ] **Step 3: Wire signup + token_create in `service/auth.py`**

In `src/markland/service/auth.py`, add at the top:

```python
from markland.service import metrics
```

Inside `create_user(...)`, immediately before returning the new `user_id`, add:

```python
    metrics.emit("signup", principal_id=user_id, email=email)
```

Inside `create_user_token(...)`, immediately before returning the raw token, add:

```python
    metrics.emit("token_create", principal_id=user_id, kind="user")
```

If `service/agents.py` has a `create_agent_token` function, add an analogous emit with `kind="agent"`:

```python
    metrics.emit("token_create", principal_id=agent_id, kind="agent")
```

- [ ] **Step 4: Wire first_publish, first_grant, first_invite_accept**

Add the import at the top of `src/markland/service/docs.py`:

```python
from markland.service import metrics
```

Inside `publish_doc`, after the existing `audit.record` call, add:

```python
    metrics.emit_first_time("first_publish", principal_id=principal.principal_id)
```

Add the import at the top of `src/markland/service/grants.py`:

```python
from markland.service import metrics
```

Inside `grant(...)`, after the `audit.record` call, add:

```python
    metrics.emit_first_time("first_grant", principal_id=principal.principal_id)
```

Add the import at the top of `src/markland/service/invites.py`:

```python
from markland.service import metrics
```

Inside `accept_invite(...)`, after the `audit.record` call, add:

```python
    metrics.emit_first_time("first_invite_accept", principal_id=user_id)
```

- [ ] **Step 5: Wire first_mcp_call in the rate-limit middleware**

In `src/markland/web/rate_limit_middleware.py`, add at the top:

```python
from markland.service import metrics
```

Inside `dispatch`, after computing `principal` and before the rate-limit check, add:

```python
        if principal is not None and request.url.path.startswith("/mcp"):
            metrics.emit_first_time(
                "first_mcp_call", principal_id=principal.principal_id
            )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_metrics_funnel.py -v`
Expected: PASS (1 test).

- [ ] **Step 7: Verification — full suite**

Run: `uv run pytest tests/ -v`
Expected: all green.

---

## Task 9: `/explore` auth toggle (Mine + Shared for logged-in users)

**Files:**
- Modify: `src/markland/web/app.py`
- Modify: `src/markland/web/templates/explore.html`
- Create: `tests/test_explore_auth_toggle.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_explore_auth_toggle.py`:

```python
"""`/explore` must be session-aware without leaking private docs to anon users."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import docs as docs_svc
from markland.service.auth import Principal, create_user, create_user_token
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_USER_PER_MIN", "1000")
    from markland.config import reset_config
    reset_config()

    conn = init_db(tmp_path / "e.db")
    alice_id = create_user(conn, email="a@a", display_name="Alice")
    token = create_user_token(conn, user_id=alice_id, label="l")
    alice = Principal(
        principal_id=alice_id,
        principal_type="user",
        display_name="Alice",
        is_admin=False,
        user_id=alice_id,
    )
    docs_svc.publish_doc(
        conn, base_url="x", principal=alice, title="Public doc", content="p", is_public=True
    )
    docs_svc.publish_doc(
        conn, base_url="x", principal=alice, title="Private Mine doc", content="m", is_public=False
    )
    app = create_app(conn, mount_mcp=False, admin_token="", base_url="http://t")
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c


def test_anon_explore_shows_only_public(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    from markland.config import reset_config
    reset_config()

    conn = init_db(tmp_path / "e2.db")
    alice_id = create_user(conn, email="a@a", display_name="Alice")
    alice = Principal(
        principal_id=alice_id, principal_type="user", display_name="Alice",
        is_admin=False, user_id=alice_id,
    )
    docs_svc.publish_doc(conn, base_url="x", principal=alice, title="Public", content="p", is_public=True)
    docs_svc.publish_doc(conn, base_url="x", principal=alice, title="SECRET", content="m", is_public=False)

    app = create_app(conn, mount_mcp=False, admin_token="", base_url="http://t")
    with TestClient(app) as c:
        r = c.get("/explore")
    assert r.status_code == 200
    assert "Public" in r.text
    assert "SECRET" not in r.text


def test_authed_default_view_is_public(client):
    r = client.get("/explore")
    assert r.status_code == 200
    assert "Public doc" in r.text
    assert "Private Mine doc" not in r.text


def test_authed_mine_view_shows_owned_docs(client):
    r = client.get("/explore?view=mine")
    assert r.status_code == 200
    assert "Private Mine doc" in r.text
    assert "Public doc" in r.text  # owner sees public too


def test_anon_mine_view_never_leaks(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    from markland.config import reset_config
    reset_config()

    conn = init_db(tmp_path / "e3.db")
    alice_id = create_user(conn, email="a@a", display_name="Alice")
    alice = Principal(
        principal_id=alice_id, principal_type="user", display_name="Alice",
        is_admin=False, user_id=alice_id,
    )
    docs_svc.publish_doc(conn, base_url="x", principal=alice, title="Public", content="p", is_public=True)
    docs_svc.publish_doc(conn, base_url="x", principal=alice, title="SECRET", content="m", is_public=False)

    app = create_app(conn, mount_mcp=False, admin_token="", base_url="http://t")
    with TestClient(app) as c:
        r = c.get("/explore?view=mine")
    assert r.status_code in (200, 302)
    assert "SECRET" not in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_explore_auth_toggle.py -v`
Expected: FAIL — `/explore` ignores `view` param and principal.

- [ ] **Step 3: Update the `/explore` route in `src/markland/web/app.py`**

Replace the existing `explore` handler with:

```python
    @app.get("/explore", response_class=HTMLResponse)
    def explore(request: Request, q: str | None = None, view: str | None = None):
        principal = getattr(request.state, "principal", None)
        query = (q or "").strip() or None
        show_mine = view == "mine" and principal is not None

        if show_mine:
            from markland.service import docs as docs_svc
            mine_docs = docs_svc.list_docs(db_conn, principal=principal)
            cards = [_doc_to_card(d) for d in mine_docs]
            return HTMLResponse(
                explore_tpl.render(
                    docs=cards,
                    query=query,
                    total=len(cards),
                    view="mine",
                    authed=True,
                )
            )

        docs = list_public_documents(db_conn, query=query, limit=50)
        cards = [_doc_to_card(d) for d in docs]
        return HTMLResponse(
            explore_tpl.render(
                docs=cards,
                query=query,
                total=len(cards),
                view="public",
                authed=principal is not None,
            )
        )
```

Ensure `Request` is imported from `fastapi` at the top of the file.

- [ ] **Step 4: Update `explore.html` template**

Near the top of `src/markland/web/templates/explore.html`, add the toggle block (before the doc list):

```html
{% if authed %}
  <nav class="explore-tabs">
    <a href="/explore?view=public"
       class="tab {% if view == 'public' %}active{% endif %}">Public</a>
    <a href="/explore?view=mine"
       class="tab {% if view == 'mine' %}active{% endif %}">Mine + Shared</a>
  </nav>
{% endif %}
```

Add matching `.explore-tabs` and `.tab.active` rules alongside the file's existing styles.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_explore_auth_toggle.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Verification — full suite**

Run: `uv run pytest tests/ -v`
Expected: all green.

---

## Task 10: `/quickstart` onboarding page

**Files:**
- Create: `src/markland/web/templates/quickstart.html`
- Modify: `src/markland/web/app.py`
- Modify: `src/markland/web/templates/landing.html` (add hero link)
- Create: `tests/test_quickstart_page.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_quickstart_page.py`:

```python
"""`/quickstart` renders 200 and contains all five onboarding steps."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "q.db")
    app = create_app(conn, mount_mcp=False, admin_token="", base_url="http://t")
    return TestClient(app)


def test_quickstart_renders_200(client):
    r = client.get("/quickstart")
    assert r.status_code == 200


def test_quickstart_mentions_all_five_steps(client):
    r = client.get("/quickstart")
    body = r.text.lower()
    assert "sign up" in body
    assert "/setup" in body
    assert "markland_publish" in body
    assert "markland_grant" in body
    assert "view the doc" in body or "view your doc" in body


def test_landing_links_to_quickstart(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "/quickstart" in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_quickstart_page.py -v`
Expected: FAIL — route and template do not exist.

- [ ] **Step 3: Create the template**

Create `src/markland/web/templates/quickstart.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Quickstart — Markland</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; color: #111; }
    h1 { font-size: 2rem; margin-bottom: 0.25rem; }
    .sub { color: #555; margin-bottom: 2rem; }
    ol { padding-left: 1.2rem; }
    ol > li { margin-bottom: 1.5rem; }
    code, pre { font-family: "SF Mono", Menlo, monospace; }
    pre { background: #f5f5f5; padding: 0.8rem 1rem; border-radius: 6px; overflow-x: auto; }
    a { color: #0b5bd3; }
    .footer { margin-top: 3rem; color: #888; font-size: 0.9rem; }
  </style>
</head>
<body>
  <h1>Markland Quickstart</h1>
  <p class="sub">Publish a markdown doc with your agent in five steps.</p>

  <ol>
    <li>
      <strong>Sign up.</strong> Head to <a href="/">markland.dev</a>, enter your email,
      click the magic-link you receive, and you're in.
    </li>

    <li>
      <strong>Paste <code>/setup</code> into Claude Code.</strong> In Claude Code, run:
      <pre>claude mcp add markland https://markland.dev/setup</pre>
      Claude Code will walk you through authorizing a token and wiring up the MCP server.
    </li>

    <li>
      <strong>Publish a doc.</strong> Ask Claude:
      <blockquote>Publish a markdown doc titled "Hello Markland" with some notes about my project.</blockquote>
      Your agent calls <code>markland_publish</code>. You get back a share link.
    </li>

    <li>
      <strong>Share it.</strong> Ask Claude:
      <blockquote>Grant view access on that doc to friend@example.com.</blockquote>
      Your agent calls <code>markland_grant</code>. Your friend gets an email.
    </li>

    <li>
      <strong>View the doc.</strong> Open the share link in a browser. You'll see the
      rendered markdown. Your friend signs in and sees it under "Mine + Shared" on
      <a href="/explore?view=mine">/explore</a>.
    </li>
  </ol>

  <p class="footer">
    Stuck? Check the <a href="/">landing page</a> or the README on GitHub.
  </p>
</body>
</html>
```

- [ ] **Step 4: Register the route**

In `src/markland/web/app.py`, near the other routes, add:

```python
    quickstart_tpl = env.get_template("quickstart.html")

    @app.get("/quickstart", response_class=HTMLResponse)
    def quickstart():
        return HTMLResponse(quickstart_tpl.render())
```

- [ ] **Step 5: Add the hero link on `landing.html`**

In `src/markland/web/templates/landing.html`, inside the hero block near the top of the visible content, add:

```html
<p class="hero-cta">
  New here? <a href="/quickstart">Start with the 5-step quickstart &rarr;</a>
</p>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_quickstart_page.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Verification — full suite**

Run: `uv run pytest tests/ -v`
Expected: all green.

---

## Task 11: `/admin/audit` HTML page + `markland_audit` MCP tool (admin-only)

**Files:**
- Create: `src/markland/web/templates/admin_audit.html`
- Modify: `src/markland/web/app.py`
- Modify: `src/markland/server.py`
- Create: `tests/test_admin_audit.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_audit.py`:

```python
"""Admin-only audit log: HTML page + MCP tool."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import audit
from markland.service.auth import Principal, create_user, create_user_token
from markland.web.app import create_app


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_USER_PER_MIN", "1000")
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    from markland.config import reset_config
    reset_config()

    conn = init_db(tmp_path / "a.db")
    admin_id = create_user(conn, email="admin@m.dev", display_name="Admin")
    conn.execute("UPDATE users SET is_admin=1 WHERE id = ?", (admin_id,))
    conn.commit()
    user_id = create_user(conn, email="user@m.dev", display_name="User")

    admin_token = create_user_token(conn, user_id=admin_id, label="a")
    user_token = create_user_token(conn, user_id=user_id, label="u")

    admin_p = Principal(
        principal_id=admin_id, principal_type="user", display_name="Admin",
        is_admin=True, user_id=admin_id,
    )
    user_p = Principal(
        principal_id=user_id, principal_type="user", display_name="User",
        is_admin=False, user_id=user_id,
    )

    audit.record(conn, action="publish", principal=admin_p, doc_id="doc_x", metadata={"t": "x"})
    audit.record(conn, action="grant", principal=admin_p, doc_id="doc_x", metadata={"t": "g"})

    app = create_app(conn, mount_mcp=False, admin_token="", base_url="http://t")
    return {
        "client": TestClient(app),
        "admin_token": admin_token,
        "user_token": user_token,
        "conn": conn,
        "admin_p": admin_p,
        "user_p": user_p,
    }


def test_admin_audit_page_200_for_admin(ctx):
    r = ctx["client"].get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {ctx['admin_token']}"},
    )
    assert r.status_code == 200
    assert "publish" in r.text
    assert "grant" in r.text
    assert "doc_x" in r.text


def test_admin_audit_page_403_for_non_admin(ctx):
    r = ctx["client"].get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {ctx['user_token']}"},
    )
    assert r.status_code == 403


def test_admin_audit_page_401_for_anon(ctx):
    r = ctx["client"].get("/admin/audit")
    assert r.status_code == 401


def test_markland_audit_tool_admin_allowed(ctx):
    from markland.server import build_mcp_tools

    tools = build_mcp_tools(ctx["conn"], base_url="http://t")
    rows = tools["markland_audit"](principal=ctx["admin_p"], doc_id=None, limit=100)
    actions = [r["action"] for r in rows]
    assert "publish" in actions
    assert "grant" in actions


def test_markland_audit_tool_non_admin_raises(ctx):
    from markland.server import build_mcp_tools

    tools = build_mcp_tools(ctx["conn"], base_url="http://t")
    with pytest.raises(PermissionError):
        tools["markland_audit"](principal=ctx["user_p"], doc_id=None, limit=100)


def test_markland_audit_tool_filters_by_doc(ctx):
    from markland.server import build_mcp_tools
    from markland.service import audit as a

    a.record(ctx["conn"], action="update", principal=ctx["admin_p"], doc_id="doc_y")
    tools = build_mcp_tools(ctx["conn"], base_url="http://t")
    rows = tools["markland_audit"](principal=ctx["admin_p"], doc_id="doc_y", limit=100)
    assert all(r["doc_id"] == "doc_y" for r in rows)
    assert len(rows) == 1
```

Note: tests import `build_mcp_tools` — the plain-function tool registry that Plans 3–9 already expose alongside the FastMCP-decorated tools so unit tests can exercise tool logic without standing up a transport. Register `markland_audit` in both surfaces.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_admin_audit.py -v`
Expected: FAIL — route and tool don't exist.

- [ ] **Step 3: Create the admin template**

Create `src/markland/web/templates/admin_audit.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Audit Log — Markland Admin</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 1000px; margin: 2rem auto; padding: 0 1rem; }
    h1 { font-size: 1.4rem; }
    table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    th, td { border-bottom: 1px solid #eee; padding: 0.35rem 0.5rem; text-align: left; vertical-align: top; }
    th { background: #fafafa; }
    code { font-family: ui-monospace, SFMono-Regular, monospace; font-size: 0.85rem; }
    .meta { color: #666; max-width: 360px; overflow-wrap: anywhere; }
  </style>
</head>
<body>
  <h1>Audit Log ({{ rows|length }} most recent)</h1>
  <table>
    <thead>
      <tr>
        <th>When</th>
        <th>Action</th>
        <th>Principal</th>
        <th>Doc</th>
        <th>Metadata</th>
      </tr>
    </thead>
    <tbody>
      {% for r in rows %}
      <tr>
        <td><code>{{ r.created_at }}</code></td>
        <td>{{ r.action }}</td>
        <td><code>{{ r.principal_id }}</code> <small>({{ r.principal_type }})</small></td>
        <td>{% if r.doc_id %}<code>{{ r.doc_id }}</code>{% else %}—{% endif %}</td>
        <td class="meta"><code>{{ r.metadata_json }}</code></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</body>
</html>
```

- [ ] **Step 4: Register the route in `create_app`**

In `src/markland/web/app.py`, add alongside the other routes:

```python
    admin_audit_tpl = env.get_template("admin_audit.html")

    @app.get("/admin/audit", response_class=HTMLResponse)
    def admin_audit(request: Request):
        import json as _json
        principal = getattr(request.state, "principal", None)
        if principal is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)
        if not principal.is_admin:
            return JSONResponse({"error": "forbidden"}, status_code=403)

        from markland.service import audit as audit_svc
        rows = audit_svc.list_recent(db_conn, limit=200)
        for r in rows:
            r["metadata_json"] = _json.dumps(r["metadata"], sort_keys=True)
        return HTMLResponse(admin_audit_tpl.render(rows=rows))
```

- [ ] **Step 5: Add `markland_audit` MCP tool + plain-function registry entry**

In `src/markland/server.py`, inside `build_mcp` (alongside the other tool registrations) AND in the `build_mcp_tools` plain-function registry, add:

```python
    def _markland_audit(*, principal, doc_id: str | None = None, limit: int = 100):
        """Admin-only: read recent audit-log rows."""
        if not principal.is_admin:
            raise PermissionError("markland_audit requires admin")
        from markland.service import audit as audit_svc
        return audit_svc.list_recent(db_conn, doc_id=doc_id, limit=int(limit))

    # FastMCP surface — wraps the inner fn with the usual authenticated-principal resolver:
    @mcp.tool()
    def markland_audit(doc_id: str | None = None, limit: int = 100) -> list[dict]:
        """Admin-only: recent audit entries across the system."""
        from markland.service.auth import get_principal_from_context
        principal = get_principal_from_context()
        return _markland_audit(principal=principal, doc_id=doc_id, limit=limit)

    tools["markland_audit"] = _markland_audit
```

If `server.py` uses a different auth-context helper name, substitute — the invariant is: the MCP wrapper resolves the principal, the inner `_markland_audit` performs the admin check and returns rows.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_admin_audit.py -v`
Expected: PASS (6 tests).

- [ ] **Step 7: Verification — full suite**

Run: `uv run pytest tests/ -v`
Expected: all green.

---

## Task 12: JSON log formatter + Sentry runbook + Phase 0 checklist

**Files:**
- Modify: `src/markland/run_app.py`
- Create: `docs/runbooks/sentry-setup.md`
- Create: `docs/runbooks/phase-0-checklist.md`

- [ ] **Step 1: Add JSON log formatter to `run_app.py`**

Near the top of `src/markland/run_app.py`, replace the existing `logging.basicConfig(...)` call with:

```python
import json as _json
import logging
import sys


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object, stdout-friendly.

    Pulls structured fields (principal_id, doc_id, action) from record.__dict__
    when callers log with `logger.info("msg", extra={"principal_id": ..., ...})`.
    """

    _STRUCTURED = ("principal_id", "doc_id", "action")

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in self._STRUCTURED:
            if key in record.__dict__:
                payload[key] = record.__dict__[key]
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return _json.dumps(payload, separators=(",", ":"), sort_keys=True)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)
logger = logging.getLogger("markland.app")
```

- [ ] **Step 2: Write the Sentry runbook**

Create `docs/runbooks/sentry-setup.md`:

```markdown
# Sentry Alert Setup — Markland

Markland's Sentry DSN is wired in Plan 1 (hosted-infra). This runbook configures
the three alerts that matter at Phase 0 scale.

## Prerequisites

- `SENTRY_DSN` is set as a Fly secret (`flyctl secrets list` to verify).
- You are the admin of the Markland Sentry project.

## Alert 1 — 5xx spike

**Goal:** page when the hosted app starts throwing server errors.

1. Sentry → Alerts → Create Alert → "Issues".
2. Name: `Markland 5xx spike`.
3. Conditions:
   - `event.type:error`
   - `level:error OR level:fatal`
   - `http.status_code:[500 TO 599]`
4. Filter: `environment:production`.
5. Action: email the operator (daveyhiles@gmail.com); if Slack is wired, post to `#markland-alerts`.
6. Threshold: "more than 5 events in 5 minutes".

## Alert 2 — ConflictError rate

**Goal:** detect unusual optimistic-concurrency contention — a signal of a
client-side retry loop gone wrong, or of real multi-agent editing finding a bug.

1. Sentry → Alerts → Create Alert → "Issues".
2. Name: `Markland ConflictError spike`.
3. Conditions:
   - `exception.type:ConflictError` (matches `markland.service.docs.ConflictError`)
   - Threshold: "more than 20 events in 10 minutes".
4. Action: email only (not paging — this is a health signal, not an outage).

## Alert 3 — Email send failures

**Goal:** catch Resend outages early.

1. Sentry → Alerts → Create Alert → "Issues".
2. Name: `Markland email send failures`.
3. Conditions:
   - `exception.type:EmailSendError` (from `markland.service.email`)
   - Threshold: "more than 3 events in 5 minutes".
4. Action: email the operator.

## Structured logging pairing

`run_app.py` installs a JSON log formatter that injects `principal_id`, `doc_id`,
and `action` fields whenever a caller uses `logger.info("msg", extra={...})`.
These fields appear in Fly's log stream verbatim. To surface them in Sentry
breadcrumbs, add `sentry_sdk.set_tag(...)` calls alongside structured log calls
at future milestones — not needed at launch.

## What this runbook does NOT cover

- Sentry performance monitoring / tracing dashboards (defer).
- Custom dashboards — use the default Issues list at Phase 0 scale.
- PagerDuty / on-call rotation — single-operator launch, email is enough.
```

- [ ] **Step 3: Write the Phase 0 checklist**

Create `docs/runbooks/phase-0-checklist.md`:

```markdown
# Phase 0 Dogfooding Checklist — Markland Launch Gate

Run through this list end-to-end before inviting a single beta user. Each item
maps to spec §14 success criteria; if every box checks, Markland is launched.

## Environment

- [ ] `https://markland.dev/health` returns `{"status":"ok"}`.
- [ ] `https://markland.dev/mcp` returns 401 without auth, 200 with a valid user token.
- [ ] Sentry receives a test error from `run_app.py` (trigger once by raising from the `/health` handler temporarily, then revert).
- [ ] Resend sends a magic-link email to the operator's inbox within 10 seconds.
- [ ] Litestream shows at least one snapshot against `/data/markland.db` (`flyctl ssh console -C "litestream snapshots /data/markland.db"`).

## Success criteria (spec §14)

A non-engineer friend ("Alex") can complete this script without instructions
beyond the one-page quickstart:

- [ ] **1. Sign up.** Alex visits `/`, clicks "Sign in", enters their email, clicks the magic link → redirected to the dashboard.
- [ ] **2. Install.** Alex pastes `claude mcp add markland https://markland.dev/setup` into Claude Code, completes the device flow, sees `markland_*` tools.
- [ ] **3. Publish.** Alex asks "publish a markdown doc titled 'Hello' with some notes". Claude calls `markland_publish`. Share link returned.
- [ ] **4. Share.** Alex asks "share this with <operator's email>, edit access". Claude calls `markland_grant`. Operator receives an email notification.
- [ ] **5. Agent edits.** Operator's agent calls `markland_update` with the correct `if_version`. No silent data loss; operator sees the edit at the share URL within 5 seconds of the update returning.
- [ ] **6. Viewer works.** Alex sees the edit rendered at the share URL.

## Rate limiting + audit verification

- [ ] Exceed 60/min on a user token via a tight loop → receive 429 with `Retry-After`.
- [ ] Exceed 120/min on an agent token → 429 with `Retry-After`.
- [ ] Exceed 20/min from an anon IP on `/explore` → 429.
- [ ] After steps 1–6, `/admin/audit` shows rows for: `publish`, `grant`, `invite_create` (if invites were used), `invite_accept` (if used), `update`.

## Metrics funnel sanity

- [ ] `flyctl logs` shows one JSON line each for: `signup`, `token_create`, `first_mcp_call`, `first_publish`, `first_grant`, `first_invite_accept` after the end-to-end walkthrough.

## Go/no-go

If every box is checked, send Phase 1 invites. If anything fails, fix before
inviting anyone — the whole point of Phase 0 is that strangers never see bugs
Alex found.

## Rollback

The launch is reversible: every change lives behind the same Fly app. If
something catastrophic surfaces, `flyctl deploy --image <previous>` restores the
last known-good image; DB state replays from Litestream.
```

- [ ] **Step 4: Verification — run the formatter**

Run:

```bash
MARKLAND_ADMIN_TOKEN=t uv run python -c "import markland.run_app; import logging; logging.getLogger('markland.app').info('test', extra={'principal_id':'usr_x','action':'smoke'})"
```

Expected: one JSON line printed to stdout containing `"principal_id":"usr_x"` and `"action":"smoke"`.

- [ ] **Step 5: Verification — docs present**

Run: `ls docs/runbooks/`
Expected: listing includes `sentry-setup.md` and `phase-0-checklist.md` alongside any runbook files from earlier plans.

- [ ] **Step 6: Full suite**

Run: `uv run pytest tests/ -v`
Expected: all green (no test changes this task).

---

## Task 13: README rewrite + spec §14 end-to-end launch gate

**Files:**
- Modify: `README.md`
- Create: `tests/test_launch_e2e.py`

- [ ] **Step 1: Write the launch-gate test**

Create `tests/test_launch_e2e.py`:

```python
"""Spec §14 end-to-end launch gate.

This is THE test that declares Markland ready for Phase 1 beta. It exercises
the full auth + sharing + conflict + audit surface in one flow:

  1. Alice signs up.
  2. Alice creates a user token; Alice's agent initializes.
  3. Alice publishes a doc.
  4. Alice grants edit to Bob by email.
  5. Bob reads the doc via his own user token.
  6. Bob's user-owned agent updates the doc with the correct if_version.
  7. An invite is created for a third user Carol.
  8. Carol (a brand-new user) accepts the invite.
  9. Carol can read the updated doc.
 10. The audit_log table has >= 7 rows covering publish/grant/update/invite_create/invite_accept.

If this test passes, the success criteria in spec §14 are met end-to-end.
"""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service import invites as invites_svc
from markland.service.auth import Principal, create_user, create_user_token
from markland.service.email import EmailClient
from markland.web.app import create_app


class _NoopEmail(EmailClient):
    def __init__(self):
        super().__init__(api_key="", from_email="t@t.dev")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_USER_PER_MIN", "1000")
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_AGENT_PER_MIN", "1000")
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "e2e.db")
    app = create_app(conn, mount_mcp=False, admin_token="", base_url="http://m")
    return {"conn": conn, "client": TestClient(app), "email": _NoopEmail()}


def _principal(user_id: str, name: str) -> Principal:
    return Principal(
        principal_id=user_id,
        principal_type="user",
        display_name=name,
        is_admin=False,
        user_id=user_id,
    )


def test_launch_gate_end_to_end(env):
    conn = env["conn"]
    email = env["email"]

    # 1. Sign up Alice and Bob. Carol signs up later via invite acceptance.
    alice_id = create_user(conn, email="alice@ex.com", display_name="Alice")
    bob_id = create_user(conn, email="bob@ex.com", display_name="Bob")
    alice = _principal(alice_id, "Alice")
    bob = _principal(bob_id, "Bob")

    # 2. Tokens.
    alice_token = create_user_token(conn, user_id=alice_id, label="alice-laptop")
    bob_token = create_user_token(conn, user_id=bob_id, label="bob-laptop")
    assert alice_token and alice_token != bob_token

    # 3. Alice publishes.
    result = docs_svc.publish_doc(
        conn,
        base_url="http://m",
        principal=alice,
        title="Launch gate doc",
        content="Line 1.",
    )
    doc_id = result["id"]

    # 4. Alice grants edit to Bob.
    grants_svc.grant(
        conn,
        base_url="http://m",
        principal=alice,
        doc_id=doc_id,
        target="bob@ex.com",
        level="edit",
        email_client=email,
    )

    # 5. Bob reads.
    bob_doc = docs_svc.get_doc(conn, principal=bob, doc_id=doc_id)
    assert bob_doc.content == "Line 1."
    original_version = bob_doc.version

    # 6. Bob updates with the correct if_version.
    updated = docs_svc.update_doc(
        conn,
        principal=bob,
        doc_id=doc_id,
        content="Line 1.\nLine 2 from Bob.",
        if_version=original_version,
    )
    assert updated.version == original_version + 1

    # 7. Create an invite. Spec reserves invite creation to the owner; if the
    # service enforces owner-only, route through Alice.
    try:
        invite_id, _url = invites_svc.create_invite(
            conn, doc_id=doc_id, created_by_user_id=bob_id, level="view"
        )
    except PermissionError:
        invite_id, _url = invites_svc.create_invite(
            conn, doc_id=doc_id, created_by_user_id=alice_id, level="view"
        )

    # 8. Carol signs up + accepts the invite.
    carol_id = create_user(conn, email="carol@ex.com", display_name="Carol")
    token_row = conn.execute(
        "SELECT token FROM invite_tokens WHERE invite_id = ?",
        (invite_id,),
    ).fetchone()
    invites_svc.accept_invite(
        conn, invite_token=token_row[0], user_id=carol_id
    )

    # 9. Carol can now view.
    carol = _principal(carol_id, "Carol")
    carol_doc = docs_svc.get_doc(conn, principal=carol, doc_id=doc_id)
    assert "Line 2 from Bob" in carol_doc.content

    # 10. Audit log has >= 7 rows covering the right actions.
    rows = conn.execute("SELECT action FROM audit_log ORDER BY id").fetchall()
    actions = [r[0] for r in rows]
    assert len(actions) >= 7, f"expected >=7 audit rows, got {len(actions)}: {actions}"
    for required in ("publish", "grant", "update", "invite_create", "invite_accept"):
        assert required in actions, f"missing audit action: {required}"
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `uv run pytest tests/test_launch_e2e.py -v`
Expected: PASS (1 test). If it fails, fix the underlying service — this is the launch gate.

- [ ] **Step 3: Rewrite `README.md`**

Overwrite `README.md` with:

```markdown
# Markland

A shared knowledge surface where humans and agents are equal editors.

Markland is a hosted markdown publishing service with first-class MCP support.
Sign up, wire it into Claude Code once, and your agent can publish, share, and
collaboratively edit docs — without CRDTs, without a bespoke editor, without
leaving the terminal.

- **Live:** https://markland.dev
- **Quickstart:** https://markland.dev/quickstart
- **Spec:** [`docs/specs/2026-04-19-multi-agent-auth-design.md`](docs/specs/2026-04-19-multi-agent-auth-design.md)

## Quickstart (2 minutes)

1. Visit <https://markland.dev>, sign up with your email, click the magic link.
2. In Claude Code: `claude mcp add markland https://markland.dev/setup`.
   Complete the device flow in your browser. Restart Claude Code.
3. Ask your agent: *"Publish a markdown doc titled 'Hello Markland'."*
4. Ask your agent: *"Share it with alice@example.com, edit access."*

Full walkthrough at <https://markland.dev/quickstart>.

## MCP tools

| Tool | What it does |
|---|---|
| `markland_publish(content, title?, public?)` | Publish a doc; returns share link + version. |
| `markland_list()` | Docs you own or have been granted. |
| `markland_get(doc_id)` | Read a doc (includes current `version`). |
| `markland_search(query)` | Search docs you can view. |
| `markland_update(doc_id, content?, title?, if_version)` | Edit; requires current version. |
| `markland_delete(doc_id)` | Owner only. |
| `markland_share(doc_id)` | Returns the public share URL. |
| `markland_set_visibility(doc_id, public)` | Promote/demote to `/explore`. |
| `markland_feature(doc_id, featured)` | Admin only. |
| `markland_grant(doc_id, principal, level)` | Share with an email or `agt_*` id. |
| `markland_revoke(doc_id, principal)` | Remove a grant. |
| `markland_list_grants(doc_id)` | Current grants on a doc. |
| `markland_create_invite(doc_id, level, single_use?, expires_in_days?)` | Shareable link invite. |
| `markland_revoke_invite(invite_id)` | Kill an unused invite. |
| `markland_whoami()` | Who am I (user or agent)? |
| `markland_list_my_agents()` | Your registered agents. |
| `markland_set_status(doc_id, status, note?)` | Advisory presence: `reading` / `editing`. |
| `markland_clear_status(doc_id)` | Remove your presence row. |
| `markland_audit(doc_id?, limit?)` | Admin only: recent audit rows. |

## Rate limits

Per-principal, in-process token buckets. Defaults:

- **User tokens:** 60 requests/min.
- **Agent tokens:** 120 requests/min.
- **Anonymous (magic-link start, device-start):** 20/min per IP.

A 429 response carries a `Retry-After` header. Overrideable via
`MARKLAND_RATE_LIMIT_{USER,AGENT,ANON}_PER_MIN`. Defaults are sized for
Phase 0 / Phase 1 launch; raise them as usage grows.

## Operator runbooks

- [First deploy (hosted Fly.io)](docs/runbooks/first-deploy.md)
- [Sentry alert setup](docs/runbooks/sentry-setup.md)
- [Phase 0 dogfooding checklist (launch gate)](docs/runbooks/phase-0-checklist.md)

## Local dev

Markland still runs as a stdio MCP server for local iteration against a
local SQLite file. Intended for contributors, not for daily use — the hosted
service is the canonical entry point.

```bash
uv sync --all-extras
uv run python src/markland/server.py
```

## Contributing

1. Read the [spec](docs/specs/2026-04-19-multi-agent-auth-design.md).
2. Pick up an open plan in `docs/plans/` and follow TDD.
3. `uv run pytest tests/ -v` before opening a PR.

## License

Source-available pending a decision post-launch.
```

- [ ] **Step 4: Verification — run the full suite**

Run: `uv run pytest tests/ -v`
Expected: the full suite passes, including `tests/test_launch_e2e.py`. This is the launch gate.

- [ ] **Step 5: Verification — README renders**

Open `README.md` in your editor preview (or `grip README.md`). Confirm the
MCP-tool table renders, the runbook links resolve to files that exist
(`docs/runbooks/first-deploy.md`, `docs/runbooks/sentry-setup.md`,
`docs/runbooks/phase-0-checklist.md`), and the quickstart section is readable.

---

## Completion criteria

- `uv run pytest tests/ -v` passes, including the new test files: `test_rate_limit.py`, `test_audit_service.py`, `test_audit_integration.py`, `test_metrics.py`, `test_metrics_funnel.py`, `test_explore_auth_toggle.py`, `test_quickstart_page.py`, `test_admin_audit.py`, `test_launch_e2e.py`.
- `MARKLAND_ADMIN_TOKEN=t uv run python src/markland/run_app.py` starts the app; logs are JSON-line; 61st user-token request to any route returns 429 with `Retry-After`.
- Hitting `/admin/audit` with an admin token renders a row table; with a non-admin token returns 403; without auth returns 401.
- Hitting `/quickstart` renders a 200 page listing five steps.
- Hitting `/explore?view=mine` as a logged-in user shows their owned + granted docs; as anon shows only public.
- `docs/runbooks/sentry-setup.md` and `docs/runbooks/phase-0-checklist.md` exist and are internally consistent; running through the Phase 0 checklist against the deployed instance leaves every box checked.
- `README.md` leads with hosted usage, mentions rate limits, and links to the three operator runbooks.
- `tests/test_launch_e2e.py` — the spec §14 launch gate — passes.

## What this plan does NOT deliver

- Distributed or persistent rate limiting (Redis, shared counters) — deferred until a second region exists.
- Audit-log pagination beyond `limit`, search, or export — the admin page is read-only by design.
- A real admin UI beyond the single audit page — promotions/demotions remain a direct-SQL operator task per spec §3.
- Prometheus / OpenTelemetry / external metrics — the JSON-line stdout emitter is enough for Phase 0.
- Phase 1 / Phase 2 rollout automation — those phases advance by inviting people, not by code, per spec §13.
- CRDT, WYSIWYG, activity feeds, or any of the §15 explicit non-goals.

This is plan 10 of 10. When the completion criteria above are satisfied, Markland is cleared to invite Phase 1 users per spec §13.
