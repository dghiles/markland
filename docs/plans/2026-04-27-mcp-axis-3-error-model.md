# MCP Audit — Axis 3 (Error Model) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Converge every tool on a closed set of seven error codes (`unauthenticated`, `forbidden`, `not_found`, `conflict`, `invalid_argument`, `rate_limited`, `internal_error`) with a single wire format (`ToolError` with `err.data = {"code": ..., **error_data}`). Behavior shifts intentionally; baseline snapshots get updated.

**Architecture:** Today, tool errors come back via four mechanisms — `{"error": "..."}` dicts, raised `PermissionError`, raised `ValueError`, and a single `ToolError` ("conflict"). This plan unifies them: every error path raises `ToolError` with the canonical `code` in `err.data`. The harness's normalization table from plan 1 collapses to one branch (parse `err.data['code']`). Anonymous calls go from "internal_error from raised AttributeError" to a clean `unauthenticated`. The Layer B baseline gets re-snapshotted with the new error shapes.

**Tech Stack:** Python 3.12 only.

**Scope excluded (this plan):**
- No naming changes (axis 1 done in plan 2).
- No fold/return-shape changes (axes 2 + 4 deferred to plans 4-5).
- No new tools (plan 6).
- No idempotency-flips (those land in plan 5 with axis 8 — the cases where today's `not_found` becomes idempotent success).

**Spec reference:** `docs/specs/2026-04-27-mcp-audit-design.md` §6.3, §7, §8.3.

---

## File Structure

**New files:**
- `src/markland/_mcp_errors.py` — central `ToolError` factory: `tool_error(code: str, **data)` returning a properly-shaped `ToolError`.
- `tests/test_audit_error_model.py` — Layer C: drives every tool into every relevant error code, asserts shape.

**Modified files:**
- `src/markland/server.py` — every error path replaced with `raise tool_error(...)`. The `{"error": ...}` return convention disappears. The local `_require_principal` raises `tool_error("unauthenticated")` instead of `RuntimeError`.
- `tests/_mcp_harness.py` — `_normalize_direct` simplified to a one-branch handler (parse `ToolError.data['code']`).
- `tests/fixtures/mcp_baseline/*.json` — re-snapshotted via `--snapshot-update`. The diff is the "error: not_found" → `code: not_found` shape change.

---

## Pre-flight checks

- [ ] **Verify plan 2 landed cleanly**

Run: `uv run pytest tests/test_audit_naming.py tests/test_audit_docstrings.py tests/test_audit_deprecations.py -q 2>&1 | tail -3`
Expected: All PASS.

---

## Task 1: Central `tool_error` factory

**Files:**
- Create: `src/markland/_mcp_errors.py`
- Create: `tests/test_audit_error_model.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_error_model.py`:

```python
"""Layer C — axis 3: error-model contract."""

import pytest
from markland._mcp_errors import tool_error, ERROR_CODES


def test_error_codes_are_a_closed_set():
    assert ERROR_CODES == {
        "unauthenticated",
        "forbidden",
        "not_found",
        "conflict",
        "invalid_argument",
        "rate_limited",
        "internal_error",
    }


def test_tool_error_carries_code_and_data():
    err = tool_error("conflict", current_version=3)
    assert err.data == {"code": "conflict", "current_version": 3}


def test_tool_error_rejects_unknown_code():
    with pytest.raises(ValueError, match="not in ERROR_CODES"):
        tool_error("teapot")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_error_model.py -v -k "tool_error or codes_are"`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write the factory**

Create `src/markland/_mcp_errors.py`:

```python
"""Canonical MCP error factory. See spec §7 for the closed code set."""

from __future__ import annotations

from mcp.server.fastmcp.exceptions import ToolError

ERROR_CODES: frozenset[str] = frozenset({
    "unauthenticated",
    "forbidden",
    "not_found",
    "conflict",
    "invalid_argument",
    "rate_limited",
    "internal_error",
})


def tool_error(code: str, **data) -> ToolError:
    """Build a ToolError with `data = {"code": code, **data}`.

    Use this everywhere a tool needs to surface an error to the MCP client.
    The harness's Response wrapper normalizes against the same shape.
    """
    if code not in ERROR_CODES:
        raise ValueError(f"{code!r} not in ERROR_CODES")
    msg = code.replace("_", " ")
    err = ToolError(msg)
    err.data = {"code": code, **data}
    return err
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit_error_model.py -v -k "tool_error or codes_are"`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/markland/_mcp_errors.py tests/test_audit_error_model.py
git commit -m "feat(mcp): central tool_error factory (axis 3)"
```

---

## Task 2: Replace `_require_principal` to raise `unauthenticated`

**Files:**
- Modify: `src/markland/server.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_error_model.py`:

```python
from tests._mcp_harness import MCPHarness


def test_anon_publish_is_unauthenticated(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    r = h.anon().call_raw("markland_publish", content="x")
    r.assert_error("unauthenticated")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audit_error_model.py::test_anon_publish_is_unauthenticated -v`
Expected: FAIL — today this surfaces as `internal_error` (per plan 1's normalization).

- [ ] **Step 3: Update `_require_principal`**

In `src/markland/server.py`, replace the existing `_require_principal`:

```python
from markland._mcp_errors import tool_error

def _require_principal(ctx) -> Principal:
    p = _principal_from_ctx(ctx)
    if p is None:
        raise tool_error("unauthenticated")
    return p
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_audit_error_model.py::test_anon_publish_is_unauthenticated -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/markland/server.py tests/test_audit_error_model.py
git commit -m "feat(mcp): _require_principal raises tool_error(unauthenticated) (axis 3)"
```

---

## Task 3: Convert `{"error": ...}` returns to `tool_error`

**Files:**
- Modify: `src/markland/server.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_audit_error_model.py`:

```python
def test_get_not_found_error_shape(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    r = alice.call_raw("markland_get", doc_id="doc_does_not_exist")
    r.assert_error("not_found")
    # The wrapper extracts data from ToolError.data, with code stripped.
    assert "code" not in r.error_data


def test_grant_invalid_argument_carries_reason(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    r = alice.call_raw(
        "markland_grant", doc_id=pub["id"],
        target="not-an-email-or-agent", level="view",
    )
    r.assert_error("invalid_argument")
    assert "reason" in r.error_data


def test_feature_non_admin_is_forbidden(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    r = alice.call_raw("markland_feature", doc_id=pub["id"], featured=True)
    r.assert_error("forbidden")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_error_model.py -v`
Expected: At least one FAIL — today's tools return `{"error": "not_found"}` etc., which the harness normalizes to `error_code="not_found"` but with the old data shape.

- [ ] **Step 3: Convert each error-returning helper to raise `tool_error`**

In `src/markland/server.py`, every helper (`_get`, `_share`, `_update`, `_delete`, `_set_visibility`, `_feature`, `_grant`, `_revoke`, `_list_grants`, `_create_invite`, `_revoke_invite`, `_set_status`, `_audit`) replaces dict returns with raises:

```python
# BEFORE:
def _get(ctx, doc_id: str):
    p = _require_principal(ctx)
    try:
        body = docs_svc.get(...)
    except NotFound:
        return {"error": "not_found"}
    except PermissionDenied:
        return {"error": "forbidden"}
    ...

# AFTER:
def _get(ctx, doc_id: str):
    p = _require_principal(ctx)
    try:
        body = docs_svc.get(...)
    except NotFound:
        raise tool_error("not_found")
    except PermissionDenied:
        raise tool_error("forbidden")
    ...
```

For `_grant`'s nuanced cases:

```python
except grants_svc.GrantTargetNotFound:
    raise tool_error("invalid_argument", reason="target_not_found")
except grants_svc.AgentGrantsNotSupported:
    raise tool_error("invalid_argument", reason="agent_grants_not_supported")
except grants_svc.InvalidGrantLevel:
    raise tool_error("invalid_argument", reason="invalid_level")
```

For `_feature`:

```python
def _feature(ctx, doc_id: str, featured: bool = True):
    p = _require_principal(ctx)
    if not p.is_admin:
        raise tool_error("forbidden")
    try:
        return docs_svc.feature(db_conn, p, doc_id, featured)
    except NotFound:
        raise tool_error("not_found")
```

For `_update` (the conflict path is already a `ToolError`, but normalize the shape):

```python
except docs_svc.ConflictError as exc:
    raise tool_error(
        "conflict",
        current_version=exc.current_version,
        current_content=exc.current_content,
        current_title=exc.current_title,
    )
```

For `_set_status` (the `ValueError` for bad status):

```python
def _set_status(ctx, doc_id: str, status: str, note: str | None = None):
    p = _require_principal(ctx)
    if status not in ("reading", "editing"):
        raise tool_error("invalid_argument", reason="status_must_be_reading_or_editing")
    ...
```

For `_audit` (the `PermissionError`):

```python
def _audit(ctx, doc_id: str | None = None, limit: int = 100):
    p = _require_principal(ctx)
    if not p.is_admin:
        raise tool_error("forbidden")
    ...
```

For `markland_update`'s tool wrapper that already wraps a conflict — delete the dict-checking branch; the `tool_error` already raised in the helper propagates correctly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit_error_model.py -v`
Expected: All PASS.

- [ ] **Step 5: Run full suite to find anything that broke**

Run: `uv run pytest tests/ -q 2>&1 | tail -10`
Expected: Many FAILS — pre-audit tests assert against `{"error": "not_found"}` returns. We fix the snapshots in Task 4.

- [ ] **Step 6: Commit**

```bash
git add src/markland/server.py tests/test_audit_error_model.py
git commit -m "feat(mcp): every tool raises tool_error instead of returning error dicts (axis 3)"
```

---

## Task 4: Simplify the harness normalizer

**Files:**
- Modify: `tests/_mcp_harness.py`

- [ ] **Step 1: Update `_normalize_direct`**

Replace the body with the simplified one:

```python
def _normalize_direct(value: Any, exc: BaseException | None) -> Response:
    if exc is not None:
        from mcp.server.fastmcp.exceptions import ToolError

        if isinstance(exc, ToolError):
            data = getattr(exc, "data", None) or {}
            code = data.get("code", "internal_error")
            payload = {k: v for k, v in data.items() if k != "code"}
            return Response(False, None, code, payload, exc)

        # No tool should raise raw exceptions any more — anything that does
        # is a regression. Surface as internal_error to keep tests informative.
        return Response(
            False, None, "internal_error",
            {"raw": repr(exc)}, exc,
        )

    # Successful tool calls always return a dict (or list).
    return Response(True, value, None, {}, value)
```

> **Note:** The dict-with-"error"-key branch is gone — no tool returns that shape any more. If a regression sneaks in, the assertion in any error test will catch it because the wrapper will say `ok=True, value={"error": ...}` instead of routing to the error path.

- [ ] **Step 2: Add `_normalize_http` simplification**

In `_http_call`, the JSON-RPC error branch already extracts `error.data['code']` correctly per plan 1. Verify the path: the `tools/call` response's `result.isError=True` branch extracts `code` from `data`. If the spec changes the wire format meaningfully here, update; otherwise plan 1's HTTP normalizer is already aligned.

- [ ] **Step 3: Run the harness tests**

Run: `uv run pytest tests/test_mcp_harness.py -v`
Expected: All PASS. (Plan 1's tests were written against `error_code` strings — they don't care how the normalization happens.)

- [ ] **Step 4: Commit**

```bash
git add tests/_mcp_harness.py
git commit -m "test(mcp): collapse harness error-normalization to one branch (axis 3)"
```

---

## Task 5: Update Layer B baseline snapshots

**Files:**
- Modify: `tests/fixtures/mcp_baseline/*.json` (via `--snapshot-update`)

- [ ] **Step 1: Run baseline with --snapshot-update**

Run: `uv run pytest tests/test_mcp_baseline.py --snapshot-update -q 2>&1 | tail -3`
Expected: All PASS, snapshot files mutated.

- [ ] **Step 2: Eyeball the diff**

Run: `git diff tests/fixtures/mcp_baseline/markland_get.json | head -40`
Expected: Error scenarios changed from old dict shape to `kind: error, code: not_found, data: {}` etc. No `kind: ok` scenarios should change.

- [ ] **Step 3: Sanity-check that error scenarios use the seven canonical codes**

Run: `grep -h '"code"' tests/fixtures/mcp_baseline/*.json | sort -u`
Expected: Each line shows one of: `unauthenticated`, `forbidden`, `not_found`, `conflict`, `invalid_argument`, `rate_limited`, `internal_error`. Anything else is a bug.

- [ ] **Step 4: Re-run without --snapshot-update**

Run: `uv run pytest tests/test_mcp_baseline.py -q 2>&1 | tail -3`
Expected: All PASS.

- [ ] **Step 5: Run full suite**

Run: `uv run pytest tests/ -q 2>&1 | tail -10`
Expected: Pre-audit tests that assert against `{"error": "not_found"}` returns will fail. **For each failing test, decide:**
- If the test is in the audit infrastructure (`test_mcp_harness.py`, `test_mcp_baseline.py`, `test_audit_*.py`), it should already be aligned — fix it.
- If the test is pre-existing (e.g., `test_mcp_grants.py`, `test_mcp_invite_tools.py`, `test_mcp_update_conflict.py`), update each one to assert via the harness or via `ToolError.data["code"]` directly. Each fix is a one-line change.

> **Implementer note:** This is the painful part. Pre-existing tests like `test_mcp_grants.py` likely assert `result == {"error": "not_found"}`. Replace with either:
> - `with pytest.raises(ToolError) as exc: ...; assert exc.value.data["code"] == "not_found"`, or
> - migrate the test to use the harness fixture and `r.assert_error("not_found")`.

Group the fixes by test file; each file is its own commit.

- [ ] **Step 6: Commit baseline updates**

```bash
git add tests/fixtures/mcp_baseline/
git commit -m "test(mcp): re-snapshot baseline with new error shapes (axis 3)"
```

---

## Task 6: Update pre-existing tests to new error shape

**Files:**
- Modify: `tests/test_mcp_grants.py`, `tests/test_mcp_invite_tools.py`, `tests/test_mcp_update_conflict.py`, `tests/test_presence_mcp.py`, `tests/test_list_my_agents_tool.py`, and any other pre-existing MCP test.

- [ ] **Step 1: Find affected files**

Run: `grep -lE '"error":\s*"' tests/*.py`
Expected: A list of ~5 files.

- [ ] **Step 2: For each file, migrate assertions**

For each:
- Replace `assert result == {"error": "X"}` with `assert exc.value.data["code"] == "X"` inside a `with pytest.raises(ToolError):` block.
- Or refactor to use the harness; this is generally cleaner but more code churn.
- Run the file's tests in isolation: `uv run pytest tests/test_mcp_grants.py -v` etc.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest tests/ -q 2>&1 | tail -3`
Expected: All PASS.

- [ ] **Step 4: Commit per-file**

For each migrated file, one commit:

```bash
git add tests/test_mcp_grants.py
git commit -m "test(mcp): migrate test_mcp_grants to ToolError shape (axis 3)"
```

---

## Self-review checklist

- [ ] `markland._mcp_errors` exists and is the only place `ToolError` is constructed (other than the harness, which only consumes them).
- [ ] Every error path in `server.py` raises via `tool_error(...)`. No `{"error": "..."}` dicts returned.
- [ ] `tests/test_audit_error_model.py` covers each of the seven codes via at least one tool call.
- [ ] Layer B snapshots use `kind: error, code: <one of seven>` shape across every error scenario.
- [ ] Pre-existing tests migrated; full suite green.
