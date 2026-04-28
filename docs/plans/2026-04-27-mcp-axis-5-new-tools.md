# MCP Audit — Axis 5 (Missing Pieces, 5 New Tools) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the five tools called out in spec §8.5: `markland_get_by_share_token`, `markland_list_invites`, `markland_explore`, `markland_fork`, `markland_revisions`. All ship with the §8.6 docstring template, the §7 error model, and the §8.2 / §8.7 envelopes from the start — no deprecation churn.

**Architecture:** Each new tool wraps existing service-layer functionality that's reachable today via HTTP routes (or, for `markland_revisions`, via direct DB read). No service-layer redesign is needed — the audit's job is to expose them via MCP, consistently.

**Tech Stack:** Python 3.12, SQLite. No new dependencies.

**Scope excluded (this plan):**
- No CRDT, no live updates, no rollback.
- No agent-token CRUD via MCP (deferred — security review needed).
- No comments / threads (separate product surface).

**Spec reference:** `docs/specs/2026-04-27-mcp-audit-design.md` §8.5.

---

## File Structure

**New files:**
- `tests/test_audit_missing.py` — Layer C: each new tool present, returns the expected envelope, error paths consistent.

**Modified files:**
- `src/markland/server.py` — five new `@mcp.tool()` definitions plus their helpers.
- `src/markland/service/docs.py` — add `get_by_share_token(...)`, `fork(...)`, `list_revisions(...)`, `list_public_paginated(...)`. (Some may exist already as HTTP-only helpers; consolidate.)
- `src/markland/service/invites.py` — add `list_for_doc_paginated(...)`.
- `tests/fixtures/mcp_baseline/markland_*.json` — five new snapshot files (created via `--snapshot-update`).
- `tests/test_audit_idempotency.py` — extend the catalog with the five new tools.

---

## Pre-flight checks

- [ ] **Verify plan 5 landed**

Run: `uv run pytest tests/test_audit_granularity.py tests/test_audit_idempotency.py -q 2>&1 | tail -3`
Expected: All PASS.

---

## Task 1: `markland_get_by_share_token`

**Files:**
- Modify: `src/markland/service/docs.py`
- Modify: `src/markland/server.py`
- Create: `tests/test_audit_missing.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_missing.py`:

```python
"""Layer C — axis 5: new tools."""

import pytest
from tests._mcp_harness import MCPHarness


def test_get_by_share_token_public(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# Public", public=True)

    # Fetch share_token from the share_url (last segment).
    share_token = pub["share_url"].rsplit("/", 1)[-1]

    # Anonymous read of public doc by share_token works.
    res = h.anon().call("markland_get_by_share_token", share_token=share_token)
    assert res["id"] == pub["id"]
    assert res["title"] == pub["title"]


def test_get_by_share_token_private_not_found(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# Private", public=False)
    share_token = pub["share_url"].rsplit("/", 1)[-1]

    # Anonymous read of a non-public doc → not_found (deny-as-not-found).
    r = h.anon().call_raw("markland_get_by_share_token", share_token=share_token)
    r.assert_error("not_found")


def test_get_by_share_token_unknown(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    r = h.anon().call_raw(
        "markland_get_by_share_token", share_token="not_a_real_token",
    )
    r.assert_error("not_found")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_missing.py -v -k get_by_share_token`
Expected: FAIL — tool doesn't exist.

- [ ] **Step 3: Add service helper + tool**

In `src/markland/service/docs.py`:

```python
def get_by_share_token(conn, share_token: str) -> dict | None:
    """Return doc dict for a public doc, or None if not found / not public."""
    row = conn.execute(
        "SELECT * FROM documents WHERE share_token = ? AND is_public = 1",
        (share_token,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)
```

In `src/markland/server.py`:

```python
@mcp.tool()
def markland_get_by_share_token(ctx: Context, share_token: str) -> dict:
    """Read a public document by its share token, no authentication required.

    Mirrors the anonymous web-viewer flow at `/d/<share_token>`. If the doc
    is unlisted (not public), returns not_found regardless of caller — the
    share token is not a capability for non-public docs.

    Args:
        share_token: The doc's share token (the last URL segment of share_url).

    Returns:
        doc_envelope. `active_principals` is omitted for anonymous callers.

    Raises:
        not_found: doc does not exist or is not public.

    Idempotency: Read-only.
    """
    raw = docs_svc.get_by_share_token(db_conn, share_token)
    if raw is None:
        raise tool_error("not_found")
    raw["share_url"] = f"{base_url}/d/{share_token}"
    return doc_envelope(raw)
```

- [ ] **Step 4: Run + commit**

Run: `uv run pytest tests/test_audit_missing.py -v -k get_by_share_token`
Expected: 3 PASSED.

```bash
git add src/markland/service/docs.py src/markland/server.py tests/test_audit_missing.py
git commit -m "feat(mcp): markland_get_by_share_token — anonymous public read (axis 5)"
```

---

## Task 2: `markland_list_invites`

**Files:**
- Modify: `src/markland/service/invites.py`
- Modify: `src/markland/server.py`
- Modify: `tests/test_audit_missing.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_missing.py`:

```python
def test_list_invites_owner_view(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    inv1 = alice.call(
        "markland_create_invite", doc_id=pub["id"], level="view",
    )
    inv2 = alice.call(
        "markland_create_invite", doc_id=pub["id"], level="edit",
        single_use=False, expires_in_days=7,
    )

    res = alice.call("markland_list_invites", doc_id=pub["id"])
    assert "items" in res
    assert "next_cursor" in res
    assert len(res["items"]) == 2
    ids = {item["invite_id"] for item in res["items"]}
    assert ids == {inv1["invite_id"], inv2["invite_id"]}
    # Must NOT include plaintext token.
    for item in res["items"]:
        assert "url" not in item or "mk_inv_" not in item.get("url", "")


def test_list_invites_non_owner_forbidden(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    bob = h.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# t")
    alice.call("markland_create_invite", doc_id=pub["id"], level="view")

    r = bob.call_raw("markland_list_invites", doc_id=pub["id"])
    r.assert_error("not_found")  # deny-as-not-found
```

- [ ] **Step 2: Run tests to fail**

Run: `uv run pytest tests/test_audit_missing.py -v -k list_invites`
Expected: FAIL.

- [ ] **Step 3: Service helper + tool**

In `src/markland/service/invites.py`:

```python
def list_for_doc_paginated(
    conn, doc_id: str, *, limit: int = 50, cursor: str | None = None
) -> tuple[list[dict], str | None]:
    from markland._mcp_envelopes import encode_cursor, decode_cursor

    limit = min(max(1, int(limit)), 200)
    where = ["doc_id = ?", "revoked_at IS NULL"]
    params: list = [doc_id]
    if cursor:
        last_id, last_created_at = decode_cursor(cursor)
        where.append("(created_at, id) < (?, ?)")
        params.extend([last_created_at, last_id])
    sql = (
        "SELECT id, doc_id, level, uses_remaining, expires_at, created_at "
        "FROM invites "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY created_at DESC, id DESC "
        "LIMIT ?"
    )
    params.append(limit + 1)
    rows = conn.execute(sql, params).fetchall()
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        next_cursor = encode_cursor(
            last_id=page[-1]["id"], last_updated_at=page[-1]["created_at"],
        )
    items = [
        {
            "invite_id": r["id"],
            "level": r["level"],
            "uses_remaining": r["uses_remaining"],
            "expires_at": r["expires_at"],
            "created_at": r["created_at"],
        }
        for r in page
    ]
    return items, next_cursor
```

In `src/markland/server.py`:

```python
@mcp.tool()
def markland_list_invites(
    ctx: Context, doc_id: str, limit: int = 50, cursor: str | None = None,
) -> dict:
    """List outstanding invites for a document. Owner only.

    Plaintext invite tokens are NEVER returned — the original tokens are
    only available at create-time. Use this tool to inspect and revoke
    existing invites.

    Args:
        doc_id: The document.
        limit: Max invites per page (1-200, default 50).
        cursor: Pagination cursor.

    Returns:
        list_envelope of invite summaries:
            {invite_id, level, uses_remaining, expires_at, created_at}

    Raises:
        not_found: doc does not exist or caller cannot see it.
        forbidden: caller is not the owner.

    Idempotency: Read-only.
    """
    p = _require_principal(ctx)
    try:
        check_permission(db_conn, p, doc_id, "owner")
    except NotFound:
        raise tool_error("not_found")
    except PermissionDenied:
        raise tool_error("forbidden")
    items, next_cursor = invites_svc.list_for_doc_paginated(
        db_conn, doc_id, limit=limit, cursor=cursor,
    )
    return list_envelope(items=items, next_cursor=next_cursor)
```

- [ ] **Step 4: Run + commit**

Run: `uv run pytest tests/test_audit_missing.py -v -k list_invites`
Expected: 2 PASSED.

```bash
git add src/markland/service/invites.py src/markland/server.py tests/test_audit_missing.py
git commit -m "feat(mcp): markland_list_invites — owner-only invite enumeration (axis 5)"
```

---

## Task 3: `markland_explore`

**Files:**
- Modify: `src/markland/service/docs.py`
- Modify: `src/markland/server.py`
- Modify: `tests/test_audit_missing.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_missing.py`:

```python
def test_explore_returns_only_public_docs(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    public_doc = alice.call("markland_publish", content="# Public", public=True)
    alice.call("markland_publish", content="# Private", public=False)

    res = h.anon().call("markland_explore")
    items = res["items"]
    ids = {item["id"] for item in items}
    assert public_doc["id"] in ids
    # Private doc not in the list.
    private_titles = [i["title"] for i in items if "Private" in (i["title"] or "")]
    assert private_titles == []


def test_explore_paginates(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    for i in range(5):
        alice.call("markland_publish", content=f"# Doc {i}", public=True)

    page1 = h.anon().call("markland_explore", limit=2)
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None
```

- [ ] **Step 2: Run tests to fail**

Run: `uv run pytest tests/test_audit_missing.py -v -k explore`
Expected: FAIL.

- [ ] **Step 3: Add service helper + tool**

In `src/markland/service/docs.py`:

```python
def list_public_paginated(
    conn, *, limit: int = 50, cursor: str | None = None,
) -> tuple[list[dict], str | None]:
    from markland._mcp_envelopes import encode_cursor, decode_cursor

    limit = min(max(1, int(limit)), 200)
    where = ["is_public = 1"]
    params: list = []
    if cursor:
        last_id, last_updated_at = decode_cursor(cursor)
        where.append("(updated_at, id) < (?, ?)")
        params.extend([last_updated_at, last_id])
    sql = (
        "SELECT * FROM documents "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY updated_at DESC, id DESC "
        "LIMIT ?"
    )
    params.append(limit + 1)
    rows = conn.execute(sql, params).fetchall()
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor(
            last_id=last["id"], last_updated_at=last["updated_at"],
        )
    return [_row_to_dict(r) for r in page], next_cursor
```

In `src/markland/server.py`:

```python
@mcp.tool()
def markland_explore(
    ctx: Context, limit: int = 50, cursor: str | None = None,
) -> dict:
    """List recently-updated public documents. Anonymous-friendly.

    Mirrors the public `/explore` web feed. No authentication required.

    Args:
        limit: Max documents per page (1-200, default 50).
        cursor: Pagination cursor.

    Returns:
        list_envelope of doc_summary.

    Idempotency: Read-only.
    """
    rows, next_cursor = docs_svc.list_public_paginated(
        db_conn, limit=limit, cursor=cursor,
    )
    items = [doc_summary(r) for r in rows]
    return list_envelope(items=items, next_cursor=next_cursor)
```

- [ ] **Step 4: Run + commit**

Run: `uv run pytest tests/test_audit_missing.py -v -k explore`
Expected: 2 PASSED.

```bash
git add src/markland/service/docs.py src/markland/server.py tests/test_audit_missing.py
git commit -m "feat(mcp): markland_explore — public docs feed (axis 5)"
```

---

## Task 4: `markland_fork`

**Files:**
- Modify: `src/markland/service/docs.py`
- Modify: `src/markland/server.py`
- Modify: `tests/test_audit_missing.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_missing.py`:

```python
def test_fork_creates_owned_copy(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    bob = h.as_user(email="bob@example.com")
    src = alice.call("markland_publish", content="# Original", public=True)

    forked = bob.call("markland_fork", doc_id=src["id"], title="Bob's fork")
    assert forked["owner_id"] == bob.principal_id
    assert forked["id"] != src["id"]
    assert forked["title"] == "Bob's fork"
    assert forked["content"] == src["content"]


def test_fork_inherits_title_when_not_provided(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    bob = h.as_user(email="bob@example.com")
    src = alice.call("markland_publish", content="# Source", public=True)
    forked = bob.call("markland_fork", doc_id=src["id"])
    assert "Source" in forked["title"]


def test_fork_private_doc_not_found_for_stranger(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    bob = h.as_user(email="bob@example.com")
    src = alice.call("markland_publish", content="# Private", public=False)
    r = bob.call_raw("markland_fork", doc_id=src["id"])
    r.assert_error("not_found")
```

- [ ] **Step 2: Run tests to fail**

Run: `uv run pytest tests/test_audit_missing.py -v -k fork`
Expected: FAIL.

- [ ] **Step 3: Add service helper + tool**

In `src/markland/service/docs.py` (or reuse existing fork helper from `service/save.py` if it exists):

```python
def fork(
    conn, *, principal, source_doc_id: str, base_url: str,
    title: str | None = None,
) -> dict:
    """Duplicate a viewable doc into the principal's account."""
    src = get(conn, principal, source_doc_id, base_url=base_url)  # raises NotFound
    new_title = title or f"Fork of {src['title']}"
    return publish(
        conn, base_url, principal, src["content"],
        title=new_title, public=False,
    )
```

> **Implementer note:** If `save.py` already implements fork for the HTTP `/fork` route, prefer wrapping that helper to keep one source of truth (`forked_from_doc_id` column tracking, etc.).

In `src/markland/server.py`:

```python
@mcp.tool()
def markland_fork(
    ctx: Context, doc_id: str, title: str | None = None,
) -> dict:
    """Duplicate a viewable document into your account.

    Creates a private copy you own. The original's `forked_from_doc_id` is
    recorded for attribution on the viewer.

    Args:
        doc_id: The source document. Must be visible to the caller.
        title: Optional title; defaults to "Fork of <original title>".

    Returns:
        doc_envelope of the new document.

    Raises:
        not_found: source doc doesn't exist or caller cannot see it.

    Idempotency: Not idempotent — each call creates a new doc.
    """
    p = _require_principal(ctx)
    try:
        raw = docs_svc.fork(
            db_conn, principal=p, source_doc_id=doc_id,
            base_url=base_url, title=title,
        )
    except NotFound:
        raise tool_error("not_found")
    full = docs_svc.get(db_conn, p, raw["id"], base_url=base_url)
    return doc_envelope(full)
```

- [ ] **Step 4: Run + commit**

Run: `uv run pytest tests/test_audit_missing.py -v -k fork`
Expected: 3 PASSED.

```bash
git add src/markland/service/docs.py src/markland/server.py tests/test_audit_missing.py
git commit -m "feat(mcp): markland_fork — duplicate viewable doc (axis 5)"
```

---

## Task 5: `markland_revisions`

**Files:**
- Modify: `src/markland/service/docs.py`
- Modify: `src/markland/server.py`
- Modify: `tests/test_audit_missing.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_missing.py`:

```python
def test_revisions_returns_pre_update_snapshots(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# v1")
    upd1 = alice.call(
        "markland_update", doc_id=pub["id"],
        if_version=pub["version"], content="# v2",
    )
    alice.call(
        "markland_update", doc_id=pub["id"],
        if_version=upd1["version"], content="# v3",
    )

    res = alice.call("markland_revisions", doc_id=pub["id"])
    items = res["items"]
    # Two updates → two pre-update snapshots.
    assert len(items) == 2
    versions = sorted(item["version"] for item in items)
    assert versions == [1, 2]


def test_revisions_forbidden_for_non_viewer(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    bob = h.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# v1")
    r = bob.call_raw("markland_revisions", doc_id=pub["id"])
    r.assert_error("not_found")
```

- [ ] **Step 2: Run tests to fail**

Run: `uv run pytest tests/test_audit_missing.py -v -k revisions`
Expected: FAIL.

- [ ] **Step 3: Add service helper + tool**

In `src/markland/service/docs.py`:

```python
def list_revisions_paginated(
    conn, doc_id: str, *, limit: int = 50, cursor: str | None = None,
) -> tuple[list[dict], str | None]:
    from markland._mcp_envelopes import encode_cursor, decode_cursor

    limit = min(max(1, int(limit)), 200)
    where = ["doc_id = ?"]
    params: list = [doc_id]
    if cursor:
        last_id, last_created_at = decode_cursor(cursor)
        where.append("(created_at, id) < (?, ?)")
        params.extend([last_created_at, last_id])
    sql = (
        "SELECT id, version, title, content, created_at "
        "FROM revisions "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY created_at DESC, id DESC "
        "LIMIT ?"
    )
    params.append(limit + 1)
    rows = conn.execute(sql, params).fetchall()
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        next_cursor = encode_cursor(
            last_id=str(page[-1]["id"]), last_updated_at=page[-1]["created_at"],
        )
    items = [
        {
            "revision_id": r["id"],
            "version": r["version"],
            "title": r["title"],
            "content": r["content"],
            "created_at": r["created_at"],
        }
        for r in page
    ]
    return items, next_cursor
```

In `src/markland/server.py`:

```python
@mcp.tool()
def markland_revisions(
    ctx: Context, doc_id: str, limit: int = 50, cursor: str | None = None,
) -> dict:
    """List capped pre-update snapshots of a document. Read-only.

    The most recent 50 revisions per doc are retained. Newer revisions
    appear first. This is read-only — there is no rollback tool today.

    Args:
        doc_id: The document.
        limit: Max revisions per page (1-200, default 50).
        cursor: Pagination cursor.

    Returns:
        list_envelope of revision summaries:
            {revision_id, version, title, content, created_at}.

    Raises:
        not_found: doc does not exist or caller cannot see it.

    Idempotency: Read-only.
    """
    p = _require_principal(ctx)
    try:
        check_permission(db_conn, p, doc_id, "view")
    except NotFound:
        raise tool_error("not_found")
    except PermissionDenied:
        raise tool_error("forbidden")
    items, next_cursor = docs_svc.list_revisions_paginated(
        db_conn, doc_id, limit=limit, cursor=cursor,
    )
    return list_envelope(items=items, next_cursor=next_cursor)
```

- [ ] **Step 4: Run + commit**

Run: `uv run pytest tests/test_audit_missing.py -v -k revisions`
Expected: 2 PASSED.

```bash
git add src/markland/service/docs.py src/markland/server.py tests/test_audit_missing.py
git commit -m "feat(mcp): markland_revisions — read-only revision listing (axis 5)"
```

---

## Task 6: Extend idempotency catalog

**Files:**
- Modify: `tests/test_audit_idempotency.py`

- [ ] **Step 1: Update the catalog**

In `tests/test_audit_idempotency.py`, extend the constants:

```python
NOT_IDEMPOTENT_TOOLS = {
    "markland_publish",
    "markland_update",
    "markland_delete",
    "markland_create_invite",
    "markland_fork",  # new
}

READ_ONLY_TOOLS = {
    "markland_whoami",
    "markland_list",
    "markland_get",
    "markland_search",
    "markland_share",
    "markland_list_grants",
    "markland_list_my_agents",
    "markland_audit",
    # new:
    "markland_get_by_share_token",
    "markland_list_invites",
    "markland_explore",
    "markland_revisions",
}
```

- [ ] **Step 2: Run + commit**

Run: `uv run pytest tests/test_audit_idempotency.py -v`
Expected: All PASS.

```bash
git add tests/test_audit_idempotency.py
git commit -m "test(mcp): extend idempotency catalog with axis-5 new tools"
```

---

## Task 7: Layer B baseline scenarios for the 5 new tools

**Files:**
- Modify: `tests/test_mcp_baseline.py`

- [ ] **Step 1: Add scenarios**

Append to `tests/test_mcp_baseline.py` — one happy + one error per tool, ten scenarios total:

```python
# markland_get_by_share_token
def test_baseline_get_by_share_token_public(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# Public", public=True)
    token = pub["share_url"].rsplit("/", 1)[-1]
    r = mcp.anon().call_raw("markland_get_by_share_token", share_token=token)
    mcp.snapshot("markland_get_by_share_token", "public", _envelope_of_response(r))


def test_baseline_get_by_share_token_unknown(mcp):
    r = mcp.anon().call_raw(
        "markland_get_by_share_token", share_token="not_real",
    )
    mcp.snapshot("markland_get_by_share_token", "unknown", _envelope_of_response(r))


# markland_list_invites
def test_baseline_list_invites_owner(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    alice.call("markland_create_invite", doc_id=pub["id"], level="view")
    r = alice.call_raw("markland_list_invites", doc_id=pub["id"])
    mcp.snapshot("markland_list_invites", "owner", _envelope_of_response(r))


def test_baseline_list_invites_non_owner(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# t")
    r = bob.call_raw("markland_list_invites", doc_id=pub["id"])
    mcp.snapshot("markland_list_invites", "non_owner_hidden", _envelope_of_response(r))


# markland_explore
def test_baseline_explore_anon(mcp):
    alice = mcp.as_user(email="alice@example.com")
    alice.call("markland_publish", content="# Public", public=True)
    r = mcp.anon().call_raw("markland_explore")
    mcp.snapshot("markland_explore", "anon", _envelope_of_response(r))


def test_baseline_explore_empty(mcp):
    r = mcp.anon().call_raw("markland_explore")
    mcp.snapshot("markland_explore", "empty", _envelope_of_response(r))


# markland_fork
def test_baseline_fork_public_doc(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# original", public=True)
    r = bob.call_raw("markland_fork", doc_id=pub["id"])
    mcp.snapshot("markland_fork", "public_doc", _envelope_of_response(r))


def test_baseline_fork_private_not_found(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# private", public=False)
    r = bob.call_raw("markland_fork", doc_id=pub["id"])
    mcp.snapshot("markland_fork", "private_hidden", _envelope_of_response(r))


# markland_revisions
def test_baseline_revisions_after_update(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# v1")
    alice.call(
        "markland_update", doc_id=pub["id"],
        if_version=pub["version"], content="# v2",
    )
    r = alice.call_raw("markland_revisions", doc_id=pub["id"])
    mcp.snapshot("markland_revisions", "after_one_update", _envelope_of_response(r))


def test_baseline_revisions_no_history(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# fresh")
    r = alice.call_raw("markland_revisions", doc_id=pub["id"])
    mcp.snapshot("markland_revisions", "no_history", _envelope_of_response(r))
```

- [ ] **Step 2: Generate snapshots**

Run: `uv run pytest tests/test_mcp_baseline.py --snapshot-update -v -k "get_by_share_token or list_invites or explore or fork or revisions"`
Expected: 10 PASSED, 5 new snapshot files.

- [ ] **Step 3: Verify replay**

Run: `uv run pytest tests/test_mcp_baseline.py -v -k "get_by_share_token or list_invites or explore or fork or revisions"`
Expected: 10 PASSED.

- [ ] **Step 4: Commit**

```bash
git add tests/test_mcp_baseline.py tests/fixtures/mcp_baseline/markland_get_by_share_token.json tests/fixtures/mcp_baseline/markland_list_invites.json tests/fixtures/mcp_baseline/markland_explore.json tests/fixtures/mcp_baseline/markland_fork.json tests/fixtures/mcp_baseline/markland_revisions.json
git commit -m "test(mcp): baseline scenarios for the 5 axis-5 new tools"
```

---

## Task 8: Update README + ROADMAP

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Add the 5 new rows to the README's MCP tools table**

Append rows to the table in `README.md` for: `markland_get_by_share_token`, `markland_list_invites`, `markland_explore`, `markland_fork`, `markland_revisions`. One-line each, mirroring the existing format.

- [ ] **Step 2: Note in ROADMAP**

Edit the `MCP audit + test harness` "Now" item in `docs/ROADMAP.md` to note the 5 new tools shipped (or mark as advancing through axis 5).

- [ ] **Step 3: Commit**

```bash
git add README.md docs/ROADMAP.md
git commit -m "docs: README + ROADMAP reflect 5 new MCP tools (axis 5)"
```

---

## Task 9: Run full suite

- [ ] **Step 1: Full pytest run**

Run: `uv run pytest tests/ -q 2>&1 | tail -10`
Expected: All PASS. Surface count: 24 tools (19 originals + 4 shims kept + 2 new folded + 5 new) = 21 + 4 deprecated. Through Phase B (plan 7) the deprecated count drops to 0, leaving 22.

> **Implementer note on surface count:** After this plan lands, the
> handler count is **26**, broken down as:
> - 15 unchanged tools (whoami, publish, list, get, search, share, update,
>   delete, grant, revoke, list_grants, create_invite, revoke_invite,
>   list_my_agents, audit).
> - 2 new folded tools from plan 5 (doc_meta, status).
> - 5 new axis-5 tools from this plan (get_by_share_token, list_invites,
>   explore, fork, revisions).
> - 4 deprecation shims still present (set_visibility, feature, set_status,
>   clear_status).
>
> Plan 7 (Phase B) drops the four shims → final v1.0 surface = 22.
> Confirm against `len(mcp.markland_handlers)` after this plan: expect 26.

---

## Self-review checklist

- [ ] Five new tools exist, tested, snapshotted: `markland_get_by_share_token`, `markland_list_invites`, `markland_explore`, `markland_fork`, `markland_revisions`.
- [ ] Each follows the §8.6 docstring template, the §7 error model, and the §8.2 / §8.7 envelopes.
- [ ] README's tool table includes the 5 new rows.
- [ ] Idempotency catalog covers them.
- [ ] Layer B baseline includes 10 new scenarios.
- [ ] Full suite green.
