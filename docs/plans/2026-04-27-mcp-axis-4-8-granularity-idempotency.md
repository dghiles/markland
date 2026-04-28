# MCP Audit — Axis 4 (Granularity) + Axis 8 (Idempotency) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land axis 4 (fold `markland_set_visibility` + `markland_feature` → `markland_doc_meta`; fold `markland_set_status` + `markland_clear_status` → `markland_status`) and axis 8 (idempotency-flips on `markland_revoke` and `markland_revoke_invite`; assert idempotency contract for every tool). Old folded tools become deprecation shims.

**Architecture:** Two new tools — `markland_doc_meta(doc_id, public=None, featured=None)` and `markland_status(doc_id, status: str | None)`. The folded predecessors keep working as deprecation shims that delegate to the new tools and emit a deprecation marker in their docstrings. `_revoke` and `_revoke_invite` flip from raising `not_found` to returning success when the target row doesn't exist (idempotent semantics per spec §7).

**Tech Stack:** Python 3.12 only.

**Scope excluded (this plan):**
- No new tools beyond folds (axis 5 → plan 6).
- No removal of old shims — Phase B → plan 7, +30 days.
- No changes to `markland_grant` (already idempotent via upsert, locked in plan 2).

**Spec reference:** `docs/specs/2026-04-27-mcp-audit-design.md` §8.4, §8.8, §9.

---

## File Structure

**New files:**
- `tests/test_audit_granularity.py` — Layer C: new folded tools work; old shims still work and produce parity output.
- `tests/test_audit_idempotency.py` — Layer C: every tool's documented idempotency contract holds.

**Modified files:**
- `src/markland/server.py` — add `markland_doc_meta` and `markland_status`; rewrite the four folded predecessors as shims.
- `src/markland/service/docs.py`, `service/presence.py` — minor: ensure service-layer ops support partial updates (None=leave-as-is).
- `src/markland/server.py` — `_revoke` and `_revoke_invite` no longer raise `not_found` when target is missing.
- `tests/test_audit_deprecations.py` — extend with shim parity for the four folded tools.
- `tests/fixtures/mcp_baseline/*.json` — re-snapshot after idempotency flips and new tools.

---

## Pre-flight checks

- [ ] **Verify plan 4 landed**

Run: `uv run pytest tests/test_audit_pagination.py tests/test_audit_return_envelopes.py -q 2>&1 | tail -3`
Expected: All PASS.

---

## Task 1: New tool — `markland_doc_meta`

**Files:**
- Create: `tests/test_audit_granularity.py`
- Modify: `src/markland/server.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_granularity.py`:

```python
"""Layer C — axis 4: tool folding (granularity)."""

import pytest
from tests._mcp_harness import MCPHarness


def test_doc_meta_set_public(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")

    res = alice.call("markland_doc_meta", doc_id=pub["id"], public=True)
    assert res["is_public"] is True
    assert res["id"] == pub["id"]


def test_doc_meta_set_featured_admin_only(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")

    # Non-admin trying to set featured.
    r = alice.call_raw("markland_doc_meta", doc_id=pub["id"], featured=True)
    r.assert_error("forbidden")

    # Admin can.
    admin = h.as_admin()
    res = admin.call(
        "markland_doc_meta", doc_id=pub["id"], featured=True, public=False,
    )
    assert res["is_featured"] is True


def test_doc_meta_none_leaves_unchanged(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t", public=True)

    # Pass nothing — should be a no-op (idempotent).
    res = alice.call("markland_doc_meta", doc_id=pub["id"])
    assert res["is_public"] is True  # unchanged
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_granularity.py -v -k doc_meta`
Expected: FAIL — tool doesn't exist.

- [ ] **Step 3: Add the new tool**

In `src/markland/server.py`:

```python
def _doc_meta(ctx, doc_id: str, public: bool | None = None,
              featured: bool | None = None):
    p = _require_principal(ctx)

    if featured is not None and not p.is_admin:
        raise tool_error("forbidden")

    # Owner check is handled inside docs_svc for the public flag.
    if public is not None:
        try:
            docs_svc.set_visibility(db_conn, base_url, p, doc_id, public)
        except NotFound:
            raise tool_error("not_found")
        except PermissionDenied:
            raise tool_error("forbidden")

    if featured is not None:
        try:
            docs_svc.feature(db_conn, p, doc_id, featured)
        except NotFound:
            raise tool_error("not_found")

    # Return the freshly-loaded doc.
    try:
        body = docs_svc.get(db_conn, p, doc_id, base_url=base_url)
    except NotFound:
        raise tool_error("not_found")
    return doc_envelope(body)


@mcp.tool()
def markland_doc_meta(
    ctx: Context,
    doc_id: str,
    public: bool | None = None,
    featured: bool | None = None,
) -> dict:
    """Update document metadata flags. Owner can set `public`; admin can set `featured`.

    Args:
        doc_id: The document to update.
        public: True/False to change public visibility (owner only).
                None leaves it unchanged.
        featured: True/False to pin/unpin on the landing hero (admin only).
                  None leaves it unchanged.

    Returns:
        doc_envelope.

    Raises:
        not_found: doc does not exist or caller cannot see it.
        forbidden: caller is not the owner (for `public`) or not admin (for `featured`).

    Idempotency: Idempotent — calling with arguments matching current state is a no-op.
    """
    return _doc_meta(ctx, doc_id, public=public, featured=featured)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit_granularity.py -v -k doc_meta`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/markland/server.py tests/test_audit_granularity.py
git commit -m "feat(mcp): markland_doc_meta — fold set_visibility + feature (axis 4)"
```

---

## Task 2: Deprecation shims for `set_visibility` and `feature`

**Files:**
- Modify: `src/markland/server.py`
- Modify: `tests/test_audit_deprecations.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_deprecations.py`:

```python
def test_set_visibility_shim_delegates_to_doc_meta(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")

    new = alice.call("markland_doc_meta", doc_id=pub["id"], public=True)
    old = alice.call("markland_set_visibility", doc_id=pub["id"], public=False)

    assert new["is_public"] is True
    assert old["is_public"] is False
    # Both return doc_envelope shape.
    assert set(new) == set(old)


def test_feature_shim_delegates_to_doc_meta(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    admin = h.as_admin()
    pub = admin.call("markland_publish", content="# t")

    old = admin.call("markland_feature", doc_id=pub["id"], featured=True)
    assert old["is_featured"] is True


def test_set_visibility_shim_marked_deprecated_in_docstring(tmp_path):
    from markland.db import init_db
    from markland.server import build_mcp
    db = init_db(tmp_path / "t.db")
    mcp = build_mcp(db, base_url="http://x", email_client=None)
    desc = mcp._tool_manager.get_tool("markland_set_visibility").description
    assert "Deprecated" in desc
    assert "markland_doc_meta" in desc


def test_feature_shim_marked_deprecated(tmp_path):
    from markland.db import init_db
    from markland.server import build_mcp
    db = init_db(tmp_path / "t.db")
    mcp = build_mcp(db, base_url="http://x", email_client=None)
    desc = mcp._tool_manager.get_tool("markland_feature").description
    assert "Deprecated" in desc
```

- [ ] **Step 2: Run tests to verify they fail (or shims behave wrong)**

Run: `uv run pytest tests/test_audit_deprecations.py -v -k "set_visibility_shim or feature_shim"`
Expected: At least one FAIL — old tools still return their old shapes.

- [ ] **Step 3: Convert old tools to shims**

In `src/markland/server.py`, replace `markland_set_visibility` and `markland_feature`:

```python
@mcp.tool()
def markland_set_visibility(ctx: Context, doc_id: str, public: bool) -> dict:
    """Deprecated. Use `markland_doc_meta(doc_id, public=...)` instead.
    Removed in the release scheduled 30 days after this one.

    Args:
        doc_id: The document to update.
        public: True for public, False for unlisted.

    Returns:
        doc_envelope.

    Idempotency: Idempotent.
    """
    return _doc_meta(ctx, doc_id, public=public, featured=None)


@mcp.tool()
def markland_feature(ctx: Context, doc_id: str, featured: bool = True) -> dict:
    """Deprecated. Use `markland_doc_meta(doc_id, featured=...)` instead.
    Removed in the release scheduled 30 days after this one.

    Args:
        doc_id: The document to update.
        featured: True to pin, False to unpin.

    Returns:
        doc_envelope.

    Idempotency: Idempotent.
    """
    return _doc_meta(ctx, doc_id, public=None, featured=featured)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit_deprecations.py -v -k "set_visibility_shim or feature_shim"`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/markland/server.py tests/test_audit_deprecations.py
git commit -m "feat(mcp): set_visibility + feature become deprecation shims for doc_meta"
```

---

## Task 3: New tool — `markland_status`

**Files:**
- Modify: `src/markland/server.py`
- Modify: `tests/test_audit_granularity.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_granularity.py`:

```python
def test_status_set_then_clear(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")

    set_res = alice.call(
        "markland_status", doc_id=pub["id"], status="editing", note="wip",
    )
    assert set_res["status"] == "editing"

    cleared = alice.call("markland_status", doc_id=pub["id"], status=None)
    assert cleared["cleared"] is True


def test_status_invalid_value(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")

    r = alice.call_raw(
        "markland_status", doc_id=pub["id"], status="grilling",
    )
    r.assert_error("invalid_argument")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_granularity.py -v -k status`
Expected: FAIL — tool doesn't exist.

- [ ] **Step 3: Add the new tool**

In `src/markland/server.py`:

```python
def _status(ctx, doc_id: str, status: str | None, note: str | None = None):
    p = _require_principal(ctx)

    if status is None:
        # Clear path — idempotent.
        presence_svc.clear_status(db_conn, doc_id=doc_id, principal=p)
        return {"doc_id": doc_id, "cleared": True}

    if status not in ("reading", "editing"):
        raise tool_error(
            "invalid_argument",
            reason="status_must_be_reading_or_editing_or_none",
        )

    try:
        check_permission(db_conn, p, doc_id, "view")
    except NotFound:
        raise tool_error("not_found")
    except PermissionDenied:
        raise tool_error("forbidden")

    return presence_svc.set_status(
        db_conn, doc_id=doc_id, principal=p, status=status, note=note,
    )


@mcp.tool()
def markland_status(
    ctx: Context,
    doc_id: str,
    status: str | None = None,
    note: str | None = None,
) -> dict:
    """Set or clear your presence on a document.

    Pass `status="reading"` or `status="editing"` to announce; pass
    `status=None` (or omit) to clear. Advisory only — does not lock the
    document. Set entries expire after 10 minutes; re-call every ~5 minutes
    to remain visible (heartbeat).

    Args:
        doc_id: The document.
        status: "reading", "editing", or None to clear.
        note: Optional free-text note (only used when status is set).

    Returns:
        On set: {doc_id, status, expires_at, note}.
        On clear: {doc_id, cleared: true}.

    Raises:
        not_found: doc does not exist or caller cannot see it.
        forbidden: caller does not have view access.
        invalid_argument: status not in {reading, editing, None}.

    Idempotency: Idempotent.
    """
    return _status(ctx, doc_id, status=status, note=note)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit_granularity.py -v -k status`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/markland/server.py tests/test_audit_granularity.py
git commit -m "feat(mcp): markland_status — fold set/clear_status (axis 4)"
```

---

## Task 4: Deprecation shims for `set_status` and `clear_status`

**Files:**
- Modify: `src/markland/server.py`
- Modify: `tests/test_audit_deprecations.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_deprecations.py`:

```python
def test_set_status_shim_delegates(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    res = alice.call("markland_set_status", doc_id=pub["id"], status="reading")
    assert res["status"] == "reading"


def test_clear_status_shim_delegates(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    alice.call("markland_set_status", doc_id=pub["id"], status="reading")
    res = alice.call("markland_clear_status", doc_id=pub["id"])
    assert res["cleared"] is True


def test_set_status_marked_deprecated(tmp_path):
    from markland.db import init_db
    from markland.server import build_mcp
    db = init_db(tmp_path / "t.db")
    mcp = build_mcp(db, base_url="http://x", email_client=None)
    desc = mcp._tool_manager.get_tool("markland_set_status").description
    assert "Deprecated" in desc
    assert "markland_status" in desc
```

- [ ] **Step 2: Convert tools to shims**

```python
@mcp.tool()
def markland_set_status(
    ctx: Context,
    doc_id: str,
    status: str,
    note: str | None = None,
) -> dict:
    """Deprecated. Use `markland_status(doc_id, status=...)` instead.
    Removed in the release scheduled 30 days after this one.

    Args/Returns/Raises: see markland_status.

    Idempotency: Idempotent.
    """
    return _status(ctx, doc_id, status=status, note=note)


@mcp.tool()
def markland_clear_status(ctx: Context, doc_id: str) -> dict:
    """Deprecated. Use `markland_status(doc_id, status=None)` instead.
    Removed in the release scheduled 30 days after this one.

    Args/Returns: see markland_status.

    Idempotency: Idempotent.
    """
    return _status(ctx, doc_id, status=None)
```

- [ ] **Step 3: Run + commit**

Run: `uv run pytest tests/test_audit_deprecations.py -v -k "set_status_shim or clear_status_shim or set_status_marked"`
Expected: 3 PASSED.

```bash
git add src/markland/server.py tests/test_audit_deprecations.py
git commit -m "feat(mcp): set_status + clear_status become shims for markland_status"
```

---

## Task 5: Idempotency flip on `markland_revoke`

**Files:**
- Modify: `src/markland/server.py`
- Create: `tests/test_audit_idempotency.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_idempotency.py`:

```python
"""Layer C — axis 8: idempotency contract."""

import pytest
from tests._mcp_harness import MCPHarness


def test_revoke_nonexistent_grant_succeeds(tmp_path):
    """Per spec §8.8: revoke is idempotent — calling on a non-existent grant
    is a no-op success, not not_found."""
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    h.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# t")

    # Revoke a grant that was never made — should succeed.
    res = alice.call("markland_revoke", doc_id=pub["id"], principal="bob@example.com")
    # Don't assert exact shape; just that it didn't raise.
    assert res is not None


def test_revoke_invite_nonexistent_succeeds(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    res = alice.call(
        "markland_revoke_invite", invite_id="inv_does_not_exist",
    )
    assert res["revoked"] is True
    assert res["invite_id"] == "inv_does_not_exist"


def test_grant_called_twice_with_same_args_is_noop(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    h.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# t")

    a = alice.call("markland_grant", doc_id=pub["id"],
                   target="bob@example.com", level="view")
    b = alice.call("markland_grant", doc_id=pub["id"],
                   target="bob@example.com", level="view")
    # Both succeed; final state same.
    assert a["doc_id"] == b["doc_id"]


def test_delete_nonexistent_remains_not_found(tmp_path):
    """Per spec §8.8 exception: delete is NOT idempotent."""
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    r = alice.call_raw("markland_delete", doc_id="doc_does_not_exist")
    r.assert_error("not_found")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_idempotency.py -v -k "revoke_nonexistent or revoke_invite_nonexistent"`
Expected: FAIL — today's `_revoke` raises `not_found` when the grant doesn't exist.

- [ ] **Step 3: Flip the behavior**

In `src/markland/server.py`, modify `_revoke`:

```python
def _revoke(ctx, doc_id: str, target: str):
    p = _require_principal(ctx)
    pid = target.strip()
    if "@" in pid:
        row = db_conn.execute(
            "SELECT id FROM users WHERE lower(email) = lower(?)", (pid,)
        ).fetchone()
        if row is None:
            # Idempotent: target doesn't exist → return success no-op.
            return {"revoked": False, "doc_id": doc_id, "target": target}
        pid = row[0]

    # Owner check still applies — non-owner shouldn't probe arbitrary docs.
    try:
        check_permission(db_conn, p, doc_id, "owner")
    except NotFound:
        raise tool_error("not_found")
    except PermissionDenied:
        raise tool_error("forbidden")

    try:
        result = grants_svc.revoke(
            db_conn, principal=p, doc_id=doc_id, principal_id=pid,
        )
    except NotFound:
        # Grant didn't exist on this owner-readable doc. Idempotent.
        return {"revoked": False, "doc_id": doc_id, "target": target}
    return result
```

And `_revoke_invite`:

```python
def _revoke_invite(ctx, invite_id: str):
    p = _require_principal(ctx)
    row = db_conn.execute(
        "SELECT doc_id FROM invites WHERE id = ?", (invite_id,)
    ).fetchone()
    if row is None:
        # Idempotent: invite never existed.
        return {"revoked": True, "invite_id": invite_id}
    try:
        check_permission(db_conn, p, row[0], "owner")
    except NotFound:
        raise tool_error("not_found")
    except PermissionDenied:
        raise tool_error("forbidden")
    invites_svc.revoke_invite(
        db_conn, invite_id=invite_id, owner_user_id=p.principal_id,
    )
    return {"revoked": True, "invite_id": invite_id}
```

> **Implementer note:** The `revoke` idempotent flag returns `{"revoked": True}` for nonexistent invite (the user's intent is "this invite shouldn't grant access" — already true), but `{"revoked": False}` for nonexistent grant target (different shape because the target identity itself is missing, not the grant). The two cases are subtly different but both qualify as idempotent success.

- [ ] **Step 4: Run idempotency tests**

Run: `uv run pytest tests/test_audit_idempotency.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/markland/server.py tests/test_audit_idempotency.py
git commit -m "feat(mcp): revoke + revoke_invite become idempotent (axis 8)"
```

---

## Task 6: Idempotency catalog test

**Files:**
- Modify: `tests/test_audit_idempotency.py`

- [ ] **Step 1: Add the catalog test**

Append to `tests/test_audit_idempotency.py`:

```python
IDEMPOTENT_TOOLS = {
    "markland_doc_meta",
    "markland_grant",
    "markland_revoke",
    "markland_status",
    "markland_revoke_invite",
    # Deprecated shims still idempotent because they delegate.
    "markland_set_visibility",
    "markland_feature",
    "markland_set_status",
    "markland_clear_status",
}

NOT_IDEMPOTENT_TOOLS = {
    "markland_publish",
    "markland_update",
    "markland_delete",
    "markland_create_invite",
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
}


def test_every_tool_has_idempotency_section_in_docstring(tmp_path):
    from markland.db import init_db
    from markland.server import build_mcp
    db = init_db(tmp_path / "t.db")
    mcp = build_mcp(db, base_url="http://x", email_client=None)
    for name in IDEMPOTENT_TOOLS | NOT_IDEMPOTENT_TOOLS | READ_ONLY_TOOLS:
        desc = mcp._tool_manager.get_tool(name).description or ""
        assert "Idempotency:" in desc, f"{name} missing Idempotency: line"


def test_idempotency_catalog_covers_all_current_tools(tmp_path):
    from markland.db import init_db
    from markland.server import build_mcp
    db = init_db(tmp_path / "t.db")
    mcp = build_mcp(db, base_url="http://x", email_client=None)
    all_known = IDEMPOTENT_TOOLS | NOT_IDEMPOTENT_TOOLS | READ_ONLY_TOOLS
    extras = set(mcp.markland_handlers) - all_known
    # Plan 6 will add 5 new tools; this test should be updated then.
    assert not extras, f"unclassified tools: {extras}"
```

- [ ] **Step 2: Run + commit**

Run: `uv run pytest tests/test_audit_idempotency.py -v`
Expected: All PASS.

```bash
git add tests/test_audit_idempotency.py
git commit -m "test(mcp): idempotency catalog locks docstring + classification"
```

---

## Task 7: Re-snapshot Layer B baseline

- [ ] **Step 1: Run with --snapshot-update**

Run: `uv run pytest tests/test_mcp_baseline.py --snapshot-update -q 2>&1 | tail -3`
Expected: All PASS.

- [ ] **Step 2: Add baseline scenarios for the two new tools**

Append to `tests/test_mcp_baseline.py`:

```python
def test_baseline_markland_doc_meta_set_public(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    r = alice.call_raw("markland_doc_meta", doc_id=pub["id"], public=True)
    mcp.snapshot("markland_doc_meta", "set_public", _envelope_of_response(r))


def test_baseline_markland_doc_meta_no_change(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    r = alice.call_raw("markland_doc_meta", doc_id=pub["id"])  # no flags
    mcp.snapshot("markland_doc_meta", "no_change", _envelope_of_response(r))


def test_baseline_markland_status_set(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    r = alice.call_raw("markland_status", doc_id=pub["id"], status="reading")
    mcp.snapshot("markland_status", "set_reading", _envelope_of_response(r))


def test_baseline_markland_status_clear(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    alice.call("markland_status", doc_id=pub["id"], status="reading")
    r = alice.call_raw("markland_status", doc_id=pub["id"], status=None)
    mcp.snapshot("markland_status", "clear", _envelope_of_response(r))
```

- [ ] **Step 3: Generate snapshots**

Run: `uv run pytest tests/test_mcp_baseline.py --snapshot-update -v -k "doc_meta or status"`
Expected: PASS, two new snapshot files created.

- [ ] **Step 4: Verify the revoke snapshots reflect the idempotency flip**

Run: `git diff tests/fixtures/mcp_baseline/markland_revoke.json`
Expected: The "non-existent grant" scenario flipped from `kind: error, code: not_found` to `kind: ok, value: {revoked: false, ...}`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_mcp_baseline.py tests/fixtures/mcp_baseline/
git commit -m "test(mcp): baseline scenarios for doc_meta + status; revoke idempotency snapshot"
```

---

## Task 8: Run full suite

- [ ] **Step 1: Full pytest run**

Run: `uv run pytest tests/ -q 2>&1 | tail -10`
Expected: All PASS. Pre-existing tests against the four folded tools still work via the shims.

- [ ] **Step 2: Migrate any failing pre-existing test**

Likely candidates: `tests/test_presence_mcp.py` (which calls `set_status` / `clear_status`). The shims should keep them passing without changes — verify.

---

## Self-review checklist

- [ ] `markland_doc_meta` and `markland_status` exist and are tested.
- [ ] `markland_set_visibility`, `markland_feature`, `markland_set_status`, `markland_clear_status` survive as shims with `Deprecated` markers and behavior parity.
- [ ] `markland_revoke` and `markland_revoke_invite` succeed silently when the target doesn't exist.
- [ ] Every tool's docstring has an `Idempotency:` line.
- [ ] Idempotency catalog test covers all 21 tools currently on the surface (19 originals + 2 new).
- [ ] Layer B snapshots updated; full suite green.
