# MCP Audit — Axis 2 (Return Shapes) + Axis 7 (Pagination) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land axis 2 (consolidate every tool onto three shared return envelopes — `doc_envelope`, `doc_summary`, `list_envelope`) and axis 7 (add `limit` + `cursor` to every list-returning tool). Layer B snapshots get re-snapped with the new shapes.

**Architecture:** Three TypedDict envelopes live in `src/markland/_mcp_envelopes.py`. Doc-returning tools (`markland_publish`, `markland_get`, `markland_update`) project the existing service-layer dict into `doc_envelope`. List-returning tools (`markland_list`, `markland_search`, `markland_list_grants`, `markland_list_my_agents`, `markland_audit`) accept `limit: int = 50` (cap 200) and `cursor: str | None = None`, return `{items: [...], next_cursor: str | None}`. The cursor is opaque base64-JSON of `{last_id, last_updated_at}`; SQL ORDER BY is `(updated_at DESC, id DESC)` and the WHERE clause is the lexicographic tuple.

**Tech Stack:** Python 3.12, SQLite. No new third-party dependencies.

**Scope excluded (this plan):**
- No tool folds (axis 4 → plan 5).
- No new tools (axis 5 → plan 6).
- No idempotency-flips (axis 8 → plan 5).
- No error-model changes (axis 3 done in plan 3).

**Spec reference:** `docs/specs/2026-04-27-mcp-audit-design.md` §8.2, §8.7.

---

## File Structure

**New files:**
- `src/markland/_mcp_envelopes.py` — `doc_envelope(...)`, `doc_summary(...)`, `list_envelope(items, next_cursor)`, plus `encode_cursor(...)` / `decode_cursor(...)`.
- `tests/test_audit_return_envelopes.py` — Layer C: every doc-returning tool returns `doc_envelope` shape; every list tool returns `list_envelope`.
- `tests/test_audit_pagination.py` — Layer C: limit caps; cursor round-trips; missing cursor returns first page.

**Modified files:**
- `src/markland/server.py` — every doc-returning tool wraps with `doc_envelope(...)`; every list tool accepts `limit`/`cursor` and wraps with `list_envelope(...)`.
- `src/markland/service/docs.py`, `service/grants.py`, `service/agents.py`, `service/audit.py` — pagination-supporting query helpers.
- `tests/fixtures/mcp_baseline/*.json` — re-snapshotted.

---

## Pre-flight checks

- [ ] **Verify plan 3 landed**

Run: `uv run pytest tests/test_audit_error_model.py -q 2>&1 | tail -3`
Expected: All PASS.

---

## Task 1: Envelope helpers

**Files:**
- Create: `src/markland/_mcp_envelopes.py`
- Create: `tests/test_audit_return_envelopes.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_return_envelopes.py`:

```python
"""Layer C — axis 2: return envelopes."""

import pytest
from markland._mcp_envelopes import doc_envelope, doc_summary, list_envelope


def test_doc_envelope_required_fields():
    raw = {
        "id": "doc_a", "title": "T", "content": "x", "version": 1,
        "owner_id": "usr_b", "share_url": "http://x/d/abc",
        "is_public": False, "is_featured": False,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    env = doc_envelope(raw)
    assert set(env) >= {
        "id", "title", "content", "version", "owner_id", "share_url",
        "is_public", "is_featured", "created_at", "updated_at",
    }


def test_doc_envelope_with_active_principals():
    raw = {
        "id": "doc_a", "title": "T", "content": "x", "version": 1,
        "owner_id": "usr_b", "share_url": "http://x/d/abc",
        "is_public": False, "is_featured": False,
        "created_at": "x", "updated_at": "x",
    }
    actives = [{"principal_id": "usr_c", "status": "editing"}]
    env = doc_envelope(raw, active_principals=actives)
    assert env["active_principals"] == actives


def test_doc_summary_excludes_content():
    env = doc_summary({
        "id": "doc_a", "title": "T", "content": "should_not_appear",
        "owner_id": "usr_b", "is_public": False, "is_featured": False,
        "created_at": "x", "updated_at": "x",
    })
    assert "content" not in env
    assert env["title"] == "T"


def test_list_envelope_shape():
    env = list_envelope(items=[{"id": "doc_a"}, {"id": "doc_b"}], next_cursor="abc")
    assert env == {"items": [{"id": "doc_a"}, {"id": "doc_b"}], "next_cursor": "abc"}


def test_list_envelope_no_more_pages():
    env = list_envelope(items=[{"id": "doc_a"}], next_cursor=None)
    assert env["next_cursor"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_return_envelopes.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write the helpers**

Create `src/markland/_mcp_envelopes.py`:

```python
"""Canonical MCP return envelopes. See spec §8.2."""

from __future__ import annotations

import base64
import json
from typing import Any


_DOC_ENVELOPE_FIELDS = (
    "id", "title", "content", "version", "owner_id", "share_url",
    "is_public", "is_featured", "created_at", "updated_at",
)

_DOC_SUMMARY_FIELDS = (
    "id", "title", "owner_id", "is_public", "is_featured",
    "created_at", "updated_at", "version",
)


def doc_envelope(
    raw: dict, *, active_principals: list[dict] | None = None
) -> dict:
    """Project a service-layer doc dict into the canonical doc_envelope."""
    env = {k: raw.get(k) for k in _DOC_ENVELOPE_FIELDS}
    if active_principals is not None:
        env["active_principals"] = active_principals
    return env


def doc_summary(raw: dict) -> dict:
    """Project a service-layer doc dict into the canonical doc_summary
    (no content)."""
    return {k: raw.get(k) for k in _DOC_SUMMARY_FIELDS}


def list_envelope(*, items: list[Any], next_cursor: str | None) -> dict:
    """Wrap a paginated result in the canonical list_envelope."""
    return {"items": list(items), "next_cursor": next_cursor}


def encode_cursor(*, last_id: str, last_updated_at: str) -> str:
    """Encode pagination state as opaque base64-JSON.

    The query that consumes this cursor must use ORDER BY
    (updated_at DESC, id DESC) and WHERE (updated_at, id) < (?, ?)
    for stable pagination across rows with equal updated_at."""
    payload = json.dumps(
        {"last_id": last_id, "last_updated_at": last_updated_at},
        sort_keys=True,
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    """Decode an opaque cursor. Returns (last_id, last_updated_at).
    Raises ValueError on malformed input."""
    pad = "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + pad).decode())
        return payload["last_id"], payload["last_updated_at"]
    except (ValueError, KeyError, UnicodeDecodeError) as exc:
        raise ValueError(f"malformed cursor: {exc}") from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit_return_envelopes.py -v`
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/markland/_mcp_envelopes.py tests/test_audit_return_envelopes.py
git commit -m "feat(mcp): doc/list envelope helpers + cursor codec (axes 2 + 7)"
```

---

## Task 2: Cursor codec round-trip test

**Files:**
- Modify: `tests/test_audit_return_envelopes.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_return_envelopes.py`:

```python
from markland._mcp_envelopes import encode_cursor, decode_cursor


def test_cursor_round_trip():
    enc = encode_cursor(last_id="doc_abc", last_updated_at="2026-04-27T03:00:00Z")
    assert decode_cursor(enc) == ("doc_abc", "2026-04-27T03:00:00Z")


def test_decode_malformed_cursor_raises():
    with pytest.raises(ValueError, match="malformed cursor"):
        decode_cursor("@@@@@@")
```

- [ ] **Step 2: Run + commit**

Run: `uv run pytest tests/test_audit_return_envelopes.py -v -k cursor`
Expected: 2 PASSED.

```bash
git add tests/test_audit_return_envelopes.py
git commit -m "test(mcp): cursor codec round-trip"
```

---

## Task 3: Wrap doc-returning tools with `doc_envelope`

**Files:**
- Modify: `src/markland/server.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_return_envelopes.py`:

```python
from tests._mcp_harness import MCPHarness


def test_publish_returns_doc_envelope(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    res = alice.call("markland_publish", content="# Hi")
    assert set(res) >= {
        "id", "title", "content", "version", "owner_id", "share_url",
        "is_public", "is_featured", "created_at", "updated_at",
    }


def test_get_returns_doc_envelope_with_active_principals(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# Hi")
    got = alice.call("markland_get", doc_id=pub["id"])
    assert "active_principals" in got
    assert isinstance(got["active_principals"], list)


def test_update_returns_doc_envelope(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# v1")
    upd = alice.call(
        "markland_update", doc_id=pub["id"], if_version=pub["version"],
        content="# v2",
    )
    assert upd["version"] == pub["version"] + 1
    assert upd["content"] == "# v2"
    assert set(upd) >= {
        "id", "title", "content", "version", "owner_id", "share_url",
        "is_public", "is_featured", "created_at", "updated_at",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_return_envelopes.py -v -k "publish or get_returns or update_returns"`
Expected: FAIL — today's tools omit some fields (`content`, `created_at`).

- [ ] **Step 3: Wrap each helper**

In `src/markland/server.py`:

```python
from markland._mcp_envelopes import doc_envelope, doc_summary, list_envelope, encode_cursor, decode_cursor


def _publish(ctx, content, title=None, public=False):
    p = _require_principal(ctx)
    raw = docs_svc.publish(db_conn, base_url, p, content, title=title, public=public)
    # docs_svc.publish must return enough fields; if not, fetch the full row.
    full = docs_svc.get(db_conn, p, raw["id"], base_url=base_url)
    return doc_envelope(full)


def _get(ctx, doc_id):
    p = _require_principal(ctx)
    try:
        body = docs_svc.get(db_conn, p, doc_id, base_url=base_url)
    except NotFound:
        raise tool_error("not_found")
    except PermissionDenied:
        raise tool_error("forbidden")

    actives = presence_svc.list_active(db_conn, doc_id=doc_id)
    active_principals = [
        {
            "principal_id": a.principal_id,
            "principal_type": a.principal_type,
            "display_name": a.display_name,
            "status": a.status,
            "note": a.note,
            "updated_at": a.updated_at,
        }
        for a in actives
    ]
    return doc_envelope(body, active_principals=active_principals)


def _update(ctx, doc_id, if_version, content=None, title=None):
    p = _require_principal(ctx)
    try:
        doc = docs_svc.update(
            db_conn, doc_id, p, content=content, title=title, if_version=if_version,
        )
    except NotFound:
        raise tool_error("not_found")
    except PermissionDenied:
        raise tool_error("forbidden")
    except ValueError:
        raise tool_error("not_found")
    except docs_svc.ConflictError as exc:
        raise tool_error(
            "conflict",
            current_version=exc.current_version,
            current_content=exc.current_content,
            current_title=exc.current_title,
        )
    full = docs_svc.get(db_conn, p, doc.id, base_url=base_url)
    return doc_envelope(full)
```

> **Implementer note:** If `docs_svc.publish` already returns enough fields, drop the secondary `get` fetch — but verify against `_DOC_ENVELOPE_FIELDS`. Same for `update`. The current service-layer dicts may need extending.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit_return_envelopes.py -v -k "publish or get_returns or update_returns"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/markland/server.py
git commit -m "feat(mcp): doc-returning tools project doc_envelope (axis 2)"
```

---

## Task 4: Add pagination to `markland_list`

**Files:**
- Modify: `src/markland/service/docs.py`
- Modify: `src/markland/server.py`
- Create: `tests/test_audit_pagination.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_pagination.py`:

```python
"""Layer C — axis 7: pagination contract."""

import pytest
from tests._mcp_harness import MCPHarness


def test_list_returns_list_envelope(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    alice.call("markland_publish", content="# 1")
    alice.call("markland_publish", content="# 2")

    res = alice.call("markland_list")
    assert "items" in res
    assert "next_cursor" in res
    assert len(res["items"]) == 2
    assert res["next_cursor"] is None


def test_list_pagination_limit_and_cursor(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    for i in range(5):
        alice.call("markland_publish", content=f"# {i}")

    page1 = alice.call("markland_list", limit=2)
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    page2 = alice.call("markland_list", limit=2, cursor=page1["next_cursor"])
    assert len(page2["items"]) == 2

    page3 = alice.call("markland_list", limit=2, cursor=page2["next_cursor"])
    assert len(page3["items"]) == 1
    assert page3["next_cursor"] is None

    # No overlap.
    seen = {item["id"] for item in page1["items"] + page2["items"] + page3["items"]}
    assert len(seen) == 5


def test_list_limit_capped_at_200(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    res = alice.call("markland_list", limit=99999)
    # No assertion on length (alice has 0 docs); we just exercise the path.
    # The cap is enforced in the service layer.
    assert "items" in res
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_pagination.py -v -k list`
Expected: FAIL — today's `markland_list` returns a bare list.

- [ ] **Step 3: Add pagination to `docs_svc.list_for_principal`**

In `src/markland/service/docs.py`, add a paginated variant. Keep the old function for back-compat (used internally by HTML routes, etc.):

```python
def list_for_principal_paginated(
    conn,
    principal,
    *,
    limit: int = 50,
    cursor: str | None = None,
    cap: int = 200,
) -> tuple[list[dict], str | None]:
    """Paginated list. Returns (rows, next_cursor)."""
    from markland._mcp_envelopes import encode_cursor, decode_cursor

    limit = min(max(1, int(limit)), cap)

    where_clauses = ["(d.owner_id = ? OR d.id IN (SELECT doc_id FROM grants WHERE principal_id = ?))"]
    params: list = [principal.principal_id, principal.principal_id]

    if cursor:
        last_id, last_updated_at = decode_cursor(cursor)
        where_clauses.append("(d.updated_at, d.id) < (?, ?)")
        params.extend([last_updated_at, last_id])

    sql = (
        "SELECT d.* FROM documents d "
        f"WHERE {' AND '.join(where_clauses)} "
        "ORDER BY d.updated_at DESC, d.id DESC "
        "LIMIT ?"
    )
    params.append(limit + 1)  # over-fetch by one to detect more

    rows = conn.execute(sql, params).fetchall()
    has_more = len(rows) > limit
    page = rows[:limit]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor(
            last_id=last["id"], last_updated_at=last["updated_at"]
        )

    return [_row_to_dict(r) for r in page], next_cursor
```

> **Implementer note (verified against current db.py):** `init_db()` does not set `conn.row_factory = sqlite3.Row`, so rows come back as tuples. Two paths: (a) set `conn.row_factory = sqlite3.Row` at the top of `init_db` and use `dict(row)`, which has small risk of breaking existing tuple-indexing call sites — grep for `row[0]` / `row[1]` patterns first; or (b) build a small helper that captures `cursor.description` and zips: `[dict(zip([c[0] for c in cur.description], r)) for r in rows]`. Path (b) is safer for an audit. Match the existing `list_for_principal` projection exactly so the `doc_summary` shape stays consistent.

- [ ] **Step 4: Update `markland_list`**

In `src/markland/server.py`:

```python
def _list(ctx, limit: int = 50, cursor: str | None = None):
    p = _require_principal(ctx)
    rows, next_cursor = docs_svc.list_for_principal_paginated(
        db_conn, p, limit=limit, cursor=cursor,
    )
    items = [doc_summary(r) for r in rows]
    return list_envelope(items=items, next_cursor=next_cursor)


@mcp.tool()
def markland_list(ctx: Context, limit: int = 50, cursor: str | None = None) -> dict:
    """List documents the current principal can view, paginated.

    Args:
        limit: Max documents per page (1-200, default 50).
        cursor: Opaque token from a previous response's `next_cursor`.
                Pass to fetch the next page; omit for the first page.

    Returns:
        list_envelope of doc_summary: {items: [doc_summary, ...], next_cursor}.
        next_cursor is None when there are no more results.

    Idempotency: Read-only.
    """
    return _list(ctx, limit=limit, cursor=cursor)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit_pagination.py -v -k list`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/markland/service/docs.py src/markland/server.py tests/test_audit_pagination.py
git commit -m "feat(mcp): markland_list pagination + list_envelope (axis 7)"
```

---

## Task 5: Pagination for the remaining list tools

**Files:**
- Modify: `src/markland/server.py`
- Modify: `src/markland/service/grants.py`, `service/agents.py`, `service/audit.py`, possibly `service/docs.py` (search).
- Modify: `tests/test_audit_pagination.py`

For each of these tools, follow the **same pattern as Task 4**: service-layer paginated query → tool wrapper accepts `limit`/`cursor` → returns `list_envelope` of the appropriate item shape → test in `test_audit_pagination.py`.

| Tool | Item shape | Service-layer change |
|---|---|---|
| `markland_search` | `doc_summary` | `docs_svc.search_paginated(...)` — same WHERE-tuple pattern |
| `markland_list_grants` | grant row | `grants_svc.list_grants_paginated(...)` — order by `(created_at, principal_id) DESC` |
| `markland_list_my_agents` | agent row | `agents_svc.list_paginated(...)` — order by `(created_at, id) DESC` |
| `markland_audit` | audit row | `audit_svc.list_recent_paginated(...)` — order by `(created_at, id) DESC` |

Per-tool task structure:

- [ ] **Step 1: Write a `test_<tool>_pagination` test in `tests/test_audit_pagination.py`** that mirrors `test_list_pagination_limit_and_cursor` from Task 4 with whatever setup the tool needs.
- [ ] **Step 2: Run, see fail.**
- [ ] **Step 3: Add the `_paginated` service helper.**
- [ ] **Step 4: Update the tool wrapper.**
- [ ] **Step 5: Run, see pass.**
- [ ] **Step 6: Commit, e.g. `feat(mcp): markland_search pagination (axis 7)`.**

> **Implementer note:** `markland_audit` uses `(created_at, id) DESC` because rows are immutable (audit is append-only). For `markland_list_grants`, the cursor's "last_updated_at" can be replaced with "last_created_at" if grants don't have an updated_at column. **Verify the column name before writing the SQL.**

---

## Task 6: Re-snapshot Layer B baseline

- [ ] **Step 1: Run with `--snapshot-update`**

Run: `uv run pytest tests/test_mcp_baseline.py --snapshot-update -q 2>&1 | tail -3`
Expected: All PASS, snapshots mutated.

- [ ] **Step 2: Eyeball the diffs**

Run: `git diff tests/fixtures/mcp_baseline/markland_list.json | head -40`
Expected: `kind: ok` value changed from `[doc, doc]` to `{items: [doc, doc], next_cursor: null}`.

Run: `git diff tests/fixtures/mcp_baseline/markland_publish.json | head -40`
Expected: `kind: ok` value gains `created_at`, `updated_at`, `is_featured` fields if missing before.

- [ ] **Step 3: Re-run without update**

Run: `uv run pytest tests/test_mcp_baseline.py -q 2>&1 | tail -3`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/mcp_baseline/
git commit -m "test(mcp): re-snapshot baseline with envelope + pagination shapes"
```

---

## Task 7: Run full suite

- [ ] **Step 1: Full pytest run**

Run: `uv run pytest tests/ -q 2>&1 | tail -10`
Expected: All PASS. Pre-existing list tests may need migration to assert against `list_envelope` shape; each is a one-line change.

- [ ] **Step 2: Migrate any failing pre-existing test files**

For each failing file, replace `assert isinstance(result, list)` with `assert "items" in result; assert isinstance(result["items"], list)` and `len(result)` with `len(result["items"])`. Commit per file.

---

## Self-review checklist

- [ ] `_mcp_envelopes.py` exports `doc_envelope`, `doc_summary`, `list_envelope`, `encode_cursor`, `decode_cursor`.
- [ ] `markland_publish`, `markland_get`, `markland_update` return `doc_envelope`.
- [ ] All five list tools (`list`, `search`, `list_grants`, `list_my_agents`, `audit`) accept `limit`+`cursor` and return `list_envelope`.
- [ ] Cursor encodes `{last_id, last_updated_at}` (or `last_created_at` for immutable tables); ORDER BY mirrors the WHERE tuple.
- [ ] `limit` is capped at 200 in the service layer.
- [ ] Layer B snapshots updated; full suite green.
