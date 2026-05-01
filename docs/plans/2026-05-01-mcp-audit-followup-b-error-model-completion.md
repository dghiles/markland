# MCP Audit Follow-up B — Error Model Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 5 error-model gaps that the retrospective review found in the merged Plan-3 work — the closed-code-set isn't quite closed, one dead helper is still alive, and one tool surfaces a non-canonical kwarg.

**Architecture:** Each fix is small and local. Common shape: catch a specific exception → re-raise as `tool_error(<canonical-code>, ...)`. The largest item is removing the dead `_feature_requires_admin` helper plus its only consumer (a test file that exists solely to test the helper).

**Tech Stack:** Python 3.12.

**Source of issues:** Retrospective review of merged PR #32 (Plan 3 — axis 3 error model), with one item carried from PR #38 (Plan 6).

**Spec reference:** `docs/specs/2026-04-27-mcp-audit-design.md` §7 (closed code set).

---

## File Structure

**Modified files:**
- `src/markland/server.py` — `_publish` catches `PermissionError`; `_admin_metrics` uses `reason=` instead of `message=`; delete `_feature_requires_admin`.
- `src/markland/service/audit.py` — wrap `int(last_id)` in try/except, re-raise as `ValueError` matching `decode_cursor`'s contract.
- `tests/test_audit_error_model.py` — new tests for each fix.
- `tests/test_whoami_tool.py` — delete the two `_feature_requires_admin` tests (or the whole file if those are its only contents).

**New files:** none.

---

## Pre-flight checks

- [ ] **Verify worktree is clean and tracking origin/main**

Run:
```
git status -sb
git log --oneline -3
```
Expected: branch tracks `origin/main`; HEAD is the latest main commit.

- [ ] **Verify the post-Plan-6 baselines pass**

Run: `uv run pytest tests/test_audit_*.py tests/test_mcp_baseline.py --tb=no -q 2>&1 | tail -3`
Expected: ~140 tests pass cleanly.

---

## Task 1: `_publish` for service-agents → `tool_error("invalid_argument")`

**Files:**
- Modify: `src/markland/server.py:96-101` (`_publish` function body).
- Test: `tests/test_audit_error_model.py` (append).

**Issue:** `docs_svc.publish` at `src/markland/service/docs.py:97` raises `PermissionError("invalid_argument: service_agent_cannot_publish")` when a service-owned agent attempts to publish. `_publish` doesn't catch this — direct-mode surfaces as `internal_error`, HTTP-mode surfaces as malformed wire shape. The `markland_publish` docstring lines 567-571 already promise `Raises: invalid_argument`, so this is also a docstring-vs-behavior mismatch.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_error_model.py`:

```python
def test_publish_service_agent_is_invalid_argument(tmp_path):
    """Plan-B.1: service-owned agents cannot publish; the tool surfaces
    invalid_argument with reason=service_agent_cannot_publish, not the
    raw PermissionError."""
    h = MCPHarness.create(tmp_path, mode="direct")

    # Build a service-owned agent (owner_user_id is None).
    from markland.service.agents import create_service_agent
    from markland.service.auth import Principal, create_agent_token

    agent = create_service_agent(
        h.db, service_id="svc_test", display_name="probe-bot"
    )
    _, token = create_agent_token(
        h.db, agent_id=agent.id, owner_user_id=None, label="harness"
    )
    principal = Principal(
        principal_id=agent.id,
        principal_type="agent",
        display_name=agent.display_name,
        is_admin=False,
        user_id=None,  # service agent has no human owner
    )

    # Wire a Caller manually since the harness as_agent only seeds
    # user-owned agents.
    from tests._mcp_harness import Caller
    caller = Caller(principal=principal, token=token, _harness=h)

    r = caller.call_raw("markland_publish", content="# probe")
    r.assert_error("invalid_argument")
    assert "service_agent_cannot_publish" in r.error_data.get("reason", "")
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/test_audit_error_model.py::test_publish_service_agent_is_invalid_argument -v`
Expected: FAIL — today the response surfaces as `internal_error` because the raw `PermissionError` propagates uncaught.

> **If `create_service_agent` doesn't accept `service_id` as a keyword:** grep `src/markland/service/agents.py` for the actual signature and adapt the call. The exception name and message are what matter for this test, not the agent-creation call site.

- [ ] **Step 3: Catch and re-raise in `_publish`**

In `src/markland/server.py`, replace lines 96-101 with:

```python
    def _publish(ctx, content: str, title: str | None = None, public: bool = False):
        p = _require_principal(ctx)
        try:
            raw = docs_svc.publish(db_conn, base_url, p, content, title=title, public=public)
        except PermissionError as exc:
            # docs_svc.publish raises PermissionError with a structured
            # message ("invalid_argument: service_agent_cannot_publish")
            # for service-owned agents. Surface the canonical code so
            # callers get a debuggable reason instead of internal_error.
            msg = str(exc)
            reason = msg.split(": ", 1)[1] if ": " in msg else msg
            raise tool_error("invalid_argument", reason=reason)
        # Re-fetch via get() to ensure all doc_envelope fields are populated.
        full = docs_svc.get(db_conn, p, raw["id"], base_url=base_url)
        return doc_envelope(full)
```

> **Why split on `": "`:** The service-layer message format is `"invalid_argument: <reason>"`. We extract `<reason>` and pass it as the `reason=` kwarg so the wire shape is `{"code": "invalid_argument", "reason": "service_agent_cannot_publish"}`.

- [ ] **Step 4: Run new test, verify pass**

Run: `uv run pytest tests/test_audit_error_model.py::test_publish_service_agent_is_invalid_argument -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `uv run pytest tests/ --tb=no 2>&1 | tail -3`
Expected: all pass (one new test added). No baseline drift expected — this scenario isn't in the baseline.

- [ ] **Step 6: Commit**

```
git add src/markland/server.py tests/test_audit_error_model.py
git commit -m "fix(mcp): _publish service-agent → invalid_argument (axis 3)

docs_svc.publish raises PermissionError for service-owned agents; the
MCP wrapper was letting it propagate uncaught, surfacing as
internal_error instead of the documented invalid_argument. Caught by
the post-merge retrospective review of PR #32."
```

---

## Task 2: Remove dead `_feature_requires_admin` helper

**Files:**
- Modify: `src/markland/server.py:48-50` (delete the helper).
- Modify: `tests/test_whoami_tool.py` (delete the two tests that import it).

**Issue:** `_feature_requires_admin` (`src/markland/server.py:48-50`) raises a bare `PermissionError`. Caught by pre-merge review of Plan 3 (PR #32) but never removed. The only consumer is `tests/test_whoami_tool.py` lines 6, 33, 45 — a test file for a helper that's no longer called by any tool.

- [ ] **Step 1: Verify the helper truly has no callers in `src/`**

Run: `grep -rn "_feature_requires_admin" src/`
Expected output: only `src/markland/server.py:48` (the definition itself).

If grep finds anything else, stop and investigate.

- [ ] **Step 2: Read `tests/test_whoami_tool.py` to confirm what's there**

Run: `cat tests/test_whoami_tool.py`

If the file's *only* tests are `test_feature_requires_admin_allows_admin` and `test_feature_requires_admin_rejects_non_admin` (plus possibly `_whoami_for_principal` import scaffolding), the whole file can be deleted. If there are unrelated `_whoami_for_principal` tests in the same file, keep those and delete only the two `_feature_requires_admin` tests + the import.

- [ ] **Step 3a: If the file is feature-tests-only — delete it**

```
git rm tests/test_whoami_tool.py
```

- [ ] **Step 3b: If there are other tests in the file — surgical edit**

Open `tests/test_whoami_tool.py` and:
1. Remove `_feature_requires_admin` from the `from markland.server import` line.
2. Delete the two test functions `test_feature_requires_admin_allows_admin` and `test_feature_requires_admin_rejects_non_admin`.

- [ ] **Step 4: Delete the helper from `server.py`**

In `src/markland/server.py`, delete lines 48-50:

```python
def _feature_requires_admin(principal: Principal) -> None:
    if not principal.is_admin:
        raise PermissionError("markland_feature requires admin")
```

(Keep the surrounding blank lines so the file's spacing stays consistent.)

- [ ] **Step 5: Run the suite**

Run: `uv run pytest tests/ --tb=short 2>&1 | tail -5`
Expected: all pass; if Step 3a was used, the test count drops by 2; if Step 3b was used, drops by 2 (only the two deleted tests).

- [ ] **Step 6: Verify no stragglers**

Run: `grep -rn "_feature_requires_admin" .`
Expected: zero matches in code (matches in `docs/audits/*` or commit messages are fine).

- [ ] **Step 7: Commit**

```
git add src/markland/server.py tests/test_whoami_tool.py
git commit -m "chore(mcp): remove dead _feature_requires_admin helper

Caught by pre-merge review of PR #32 (Plan 3) and confirmed still
present by the post-merge retrospective. The helper had no callers
after the markland_feature inline admin-check landed; only its own
tests in test_whoami_tool.py kept it imported. Both gone now."
```

---

## Task 3: FastMCP wire-prefix regression test

**Files:**
- Modify: `tests/test_mcp_harness.py` (append).

**Issue:** The HTTP fix in PR #32 (Plan 3) hard-codes the assumption that FastMCP wraps `ToolError` messages as `"Error executing tool <name>: <body>"`. If a future FastMCP upgrade drops, changes, or i18ns that prefix, every HTTP-mode tool error will silently become `internal_error{raw: ...}` with no test signal. This task adds a regression test that pins the cross-mode equivalence for one specific error so a FastMCP upgrade fails loudly.

- [ ] **Step 1: Write the regression test**

Append to `tests/test_mcp_harness.py`:

```python
def test_http_mode_preserves_tool_error_code_for_known_error(tmp_path):
    """Plan-B.3: pin the FastMCP wire-format assumption. If FastMCP ever
    changes how it serializes ToolError messages, this test fails loudly
    instead of every HTTP-mode error silently becoming internal_error."""
    h = MCPHarness.create(tmp_path, mode="http")
    try:
        alice = h.as_user(email="alice@example.com")
        # markland_get for a doc that doesn't exist → not_found via tool_error.
        # Direct mode passes this trivially; the test exercises HTTP wire decode.
        r = alice.call_raw("markland_get", doc_id="nonexistent00000")
        r.assert_error("not_found")
        # error_data is empty for not_found per spec §7, but the key fact
        # is that error_code resolved correctly from the FastMCP wire format
        # rather than degrading to internal_error.
        assert r.error_code == "not_found", (
            f"FastMCP wire format may have changed — error_code is "
            f"{r.error_code!r} but should be 'not_found'. Inspect "
            f"_decode_tool_error_text in tests/_mcp_harness.py."
        )
    finally:
        h.close()
```

- [ ] **Step 2: Run, verify it passes against current FastMCP**

Run: `uv run pytest tests/test_mcp_harness.py::test_http_mode_preserves_tool_error_code_for_known_error -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```
git add tests/test_mcp_harness.py
git commit -m "test(mcp): pin FastMCP wire-prefix regression test

Plan 3 (PR #32) introduced _decode_tool_error_text to extract our
JSON payload from FastMCP's 'Error executing tool X: <msg>' wrapping.
That parsing depends on FastMCP not changing its prefix format. Pin
the cross-mode contract so a future FastMCP upgrade that breaks this
fails loudly instead of every HTTP error degrading to internal_error."
```

---

## Task 4: Audit cursor `int(last_id)` → clean ValueError

**Files:**
- Modify: `src/markland/service/audit.py:138`.
- Test: `tests/test_audit_error_model.py` (append).

**Issue:** `audit.list_recent_paginated` casts `int(last_id)` inline. A malformed/tampered cursor whose `last_id` decodes to a non-numeric string raises `ValueError` from `int()` — not the `ValueError("malformed cursor: …")` that `decode_cursor`'s contract documents. The MCP wrapper at `_audit` doesn't catch this. Result: user sees an unhandled exception (surfaces as `internal_error`) instead of a clean `invalid_argument` for a malformed cursor.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_error_model.py`:

```python
def test_audit_malformed_cursor_with_non_numeric_id_is_invalid_argument(tmp_path):
    """Plan-B.4: a tampered audit cursor whose last_id is non-numeric must
    surface as invalid_argument (or at least not as internal_error from
    a raw int() ValueError). Today it leaks the int-cast exception."""
    import base64
    import json

    h = MCPHarness.create(tmp_path, mode="direct")
    admin = h.as_admin()

    # Build a cursor whose last_id is a string that int() rejects.
    payload = json.dumps(
        {"last_id": "not-a-number", "last_updated_at": "2026-05-01T00:00:00Z"},
        sort_keys=True,
    )
    bad_cursor = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")

    r = admin.call_raw("markland_audit", cursor=bad_cursor)
    # Either invalid_argument (preferred) or any clean tool_error code —
    # but NOT internal_error from a raw exception.
    assert r.error_code != "internal_error", (
        f"audit cursor ValueError leaks as internal_error; expected a "
        f"canonical code (invalid_argument). Got data: {r.error_data!r}"
    )
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/test_audit_error_model.py::test_audit_malformed_cursor_with_non_numeric_id_is_invalid_argument -v`
Expected: FAIL — `r.error_code == "internal_error"`.

- [ ] **Step 3: Fix the int-cast to raise the canonical ValueError**

In `src/markland/service/audit.py`, replace lines 135-138 with:

```python
    if cursor:
        last_id, last_created_at = decode_cursor(cursor)
        try:
            last_id_int = int(last_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"malformed cursor: last_id not numeric ({exc})") from exc
        where_clauses.append("(created_at, id) < (?, ?)")
        params.extend([last_created_at, last_id_int])
```

- [ ] **Step 4: Wire `_audit` to catch the ValueError and surface invalid_argument**

In `src/markland/server.py`, find `_audit` (search for `def _audit`). Today it likely calls `audit_svc.list_recent_paginated` directly. Wrap with:

```python
    def _audit(ctx, doc_id: str | None = None, limit: int = 100, cursor: str | None = None):
        p = _require_principal(ctx)
        if not p.is_admin:
            raise tool_error("forbidden")
        from markland.service import audit as audit_svc

        try:
            rows, next_cursor = audit_svc.list_recent_paginated(
                db_conn, doc_id=doc_id, limit=int(limit), cursor=cursor,
            )
        except ValueError as exc:
            # Malformed cursor (decode_cursor raises this; int(last_id)
            # casts it for audit's integer ID column). Surface canonical.
            raise tool_error("invalid_argument", reason=str(exc))
        return list_envelope(items=rows, next_cursor=next_cursor)
```

> **Important:** keep the existing `_audit` body's other concerns intact — admin check, etc. The change is just adding the `try/except ValueError` around the service call. If the existing body already differs from this template, integrate the change while preserving its other logic.

- [ ] **Step 5: Run new test, verify pass**

Run: `uv run pytest tests/test_audit_error_model.py::test_audit_malformed_cursor_with_non_numeric_id_is_invalid_argument -v`
Expected: PASS.

- [ ] **Step 6: Run baseline + suite**

Run: `uv run pytest tests/ --tb=no 2>&1 | tail -3`
Expected: all pass.

- [ ] **Step 7: Commit**

```
git add src/markland/service/audit.py src/markland/server.py tests/test_audit_error_model.py
git commit -m "fix(mcp): audit cursor malformed-id surfaces as invalid_argument

audit.list_recent_paginated did int(last_id) inline; tampered cursors
with non-numeric last_id raised an uncatchable ValueError that the
MCP wrapper surfaced as internal_error. Now the cast raises the same
'malformed cursor: …' shape decode_cursor uses, and _audit catches
ValueError → tool_error('invalid_argument'). Caught by retrospective
review of PR #32 (Plan 3)."
```

---

## Task 5: `_admin_metrics` `message=` → `reason=`

**Files:**
- Modify: `src/markland/server.py:1208-1211`.
- Test: `tests/test_audit_error_model.py` (append).

**Issue:** `_admin_metrics` at `server.py:1208` calls `tool_error("invalid_argument", message="window_seconds must be an integer")` while every other `invalid_argument` site in the file uses `reason=...`. Inconsistent for clients writing error handlers.

- [ ] **Step 1: Verify the inconsistency exists**

Run:
```
grep -n 'tool_error("invalid_argument"' src/markland/server.py
```
Expected: most lines pass `reason=...`; one line passes `message=...`.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_audit_error_model.py`:

```python
def test_admin_metrics_invalid_window_uses_reason_kwarg(tmp_path):
    """Plan-B.5: every invalid_argument across the surface uses
    error_data['reason'], not error_data['message']."""
    h = MCPHarness.create(tmp_path, mode="direct")
    admin = h.as_admin()
    r = admin.call_raw(
        "markland_admin_metrics", window_seconds="not-an-int"
    )
    r.assert_error("invalid_argument")
    assert "reason" in r.error_data, (
        f"invalid_argument data uses non-canonical key: {r.error_data!r}"
    )
```

- [ ] **Step 3: Run, verify it fails**

Run: `uv run pytest tests/test_audit_error_model.py::test_admin_metrics_invalid_window_uses_reason_kwarg -v`
Expected: FAIL — `error_data` has `message` key, not `reason`.

- [ ] **Step 4: Apply the fix**

In `src/markland/server.py`, find the call (currently around line 1208-1211) and change `message=` to `reason=`:

```python
        try:
            ws = int(window_seconds)
        except (TypeError, ValueError):
            raise tool_error(
                "invalid_argument",
                reason="window_seconds must be an integer",
            )
```

- [ ] **Step 5: Verify other sites uniformly use `reason=`**

Run: `grep -n 'tool_error("invalid_argument"' src/markland/server.py | grep -v reason`
Expected: zero output (all sites now use `reason=`).

- [ ] **Step 6: Run new test, verify pass**

Run: `uv run pytest tests/test_audit_error_model.py::test_admin_metrics_invalid_window_uses_reason_kwarg -v`
Expected: PASS.

- [ ] **Step 7: Run full suite**

Run: `uv run pytest tests/ --tb=no 2>&1 | tail -3`
Expected: all pass; if any test depended on `error_data["message"]` for `markland_admin_metrics`, fix it inline (replace with `reason`). Likely none — the kwarg only flowed to clients.

- [ ] **Step 8: Commit**

```
git add src/markland/server.py tests/test_audit_error_model.py
git commit -m "fix(mcp): admin_metrics invalid_argument uses reason kwarg uniformly

Every other invalid_argument site passes reason=...; admin_metrics
was the lone outlier passing message=... Caught by retrospective
review of PR #32 (Plan 3). Clients reading error_data should not
have to know per-tool which key holds the human-readable string."
```

---

## Task 6: Final integration

- [ ] **Step 1: Run full suite**

Run: `uv run pytest tests/ --tb=no 2>&1 | tail -5`
Expected: all pass except the pre-existing flake.

- [ ] **Step 2: Verify canonical codes still hold across all baselines**

Run: `grep -h '"code"' tests/fixtures/mcp_baseline/*.json | sort -u`
Expected: only the seven canonical codes from §7.

- [ ] **Step 3: Verify the dead helper is gone**

Run: `grep -rn "_feature_requires_admin" src/ tests/`
Expected: zero matches.

- [ ] **Step 4: Verify all `invalid_argument` sites use `reason=`**

Run: `grep -n 'tool_error("invalid_argument"' src/markland/server.py | grep -v reason`
Expected: empty.

---

## Self-review checklist

- [ ] `_publish` catches `PermissionError` and re-raises as `tool_error("invalid_argument", reason=...)`.
- [ ] `_feature_requires_admin` deleted from `server.py`; its tests removed from `test_whoami_tool.py`.
- [ ] `tests/test_mcp_harness.py` includes a regression test that fails loudly if FastMCP changes its `ToolError` wire prefix.
- [ ] `audit.list_recent_paginated` raises `ValueError("malformed cursor: …")` for non-numeric `last_id`; `_audit` catches and surfaces `invalid_argument`.
- [ ] `_admin_metrics` uses `reason=` not `message=`.
- [ ] All five Layer C tests pass.
- [ ] Full suite green.
