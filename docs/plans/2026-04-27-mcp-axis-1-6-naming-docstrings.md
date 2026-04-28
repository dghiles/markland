# MCP Audit — Axis 1 (Naming) + Axis 6 (Docstrings) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land axis 1 (parameter naming) and axis 6 (docstring template) of the MCP audit. Touches every tool but introduces zero behavior change. The Layer B baseline from plan 1 catches any accidental drift.

**Architecture:** No structural changes. Each surviving tool (per §8.0 of the spec) gets its docstring rewritten to the §8.6 four-part template. The grant-subject parameter is renamed `principal` → `target` with a deprecation shim that accepts both names for one release. Tool names are not changed in this plan — folds (axis 4) and renames-by-fold are deferred to plan 5. Layer C tests (`tests/test_audit_naming.py`, `tests/test_audit_docstrings.py`) lock the new contracts.

**Tech Stack:** Python 3.12 only. No new dependencies.

**Scope excluded (this plan):**
- No tool removes or folds — those land in plan 5.
- No return-shape changes — those land in plan 4.
- No error-model changes — those land in plan 3.
- No new tools — those land in plan 6.
- No pagination params.
- The `markland_grant`'s `principal` rename ships with a deprecation shim that accepts the old keyword, marked `Deprecated.` in the docstring with the removal-release note.

**Spec reference:** `docs/specs/2026-04-27-mcp-audit-design.md` §8.1, §8.6, §9.

---

## File Structure

**New files:**
- `tests/test_audit_naming.py` — Layer C: parameter-naming invariants for axis 1.
- `tests/test_audit_docstrings.py` — Layer C: docstring template adherence for axis 6.
- `tests/test_audit_deprecations.py` — behavior-parity tests for the `principal`/`target` shim. (Reused by plans 3-5.)

**Modified files:**
- `src/markland/server.py` — every `@mcp.tool()` docstring rewritten to the §8.6 template. `_grant` and the `markland_grant` shim accept both `principal` and `target` kwargs.
- Snapshot files in `tests/fixtures/mcp_baseline/` — none changed; this plan introduces zero behavior change. If a snapshot diff appears it's a regression.

---

## Pre-flight checks

- [ ] **Verify plan 1's harness landed**

Run: `ls tests/_mcp_harness.py tests/test_mcp_baseline.py tests/fixtures/mcp_baseline/`
Expected: Harness module, baseline test, 19 snapshot files.

- [ ] **Verify the baseline passes clean**

Run: `uv run pytest tests/test_mcp_baseline.py -q 2>&1 | tail -3`
Expected: All baseline scenarios pass. If anything fails, stop — plan 1 has a regression to fix first.

---

## Task 1: Author the docstring template helper

**Files:**
- Modify: `src/markland/server.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_docstrings.py`:

```python
"""Layer C — axis 6: docstring template adherence."""

import re
import pytest
from markland.server import build_mcp


@pytest.fixture
def tools(tmp_path):
    from markland.db import init_db
    db = init_db(tmp_path / "t.db")
    mcp = build_mcp(db, base_url="http://x", email_client=None)
    return mcp.markland_handlers, mcp


def test_every_tool_has_args_and_returns_sections(tools):
    handlers, mcp = tools
    # Inspect the wrapped tool functions on the FastMCP instance.
    # FastMCP stores them in mcp._tools or similar — find the canonical accessor.
    for name in handlers:
        tool_obj = mcp._tool_manager.get_tool(name)
        doc = tool_obj.description or ""
        assert "Args:" in doc, f"{name} missing Args: section"
        assert "Returns:" in doc, f"{name} missing Returns: section"
        assert "Idempotency:" in doc, f"{name} missing Idempotency: section"


def test_every_tool_has_one_line_summary(tools):
    handlers, mcp = tools
    for name in handlers:
        tool_obj = mcp._tool_manager.get_tool(name)
        doc = (tool_obj.description or "").strip()
        first_line = doc.split("\n", 1)[0]
        assert len(first_line) <= 100, f"{name} summary too long: {first_line}"
        assert first_line.endswith("."), f"{name} summary not a sentence: {first_line}"
```

> **Implementer note (verified against current FastMCP):** `mcp._tool_manager.get_tool(name)` returns a Pydantic-modeled Tool object with `.description` (str), `.parameters` (JSON schema dict with `properties`), `.name`, and `.fn` (the wrapped handler). The `_tool_manager._tools` dict maps name → Tool. `mcp.list_tools()` is async — don't use it in sync test code without `asyncio.run(...)`. The accessor used in this plan is the cleanest sync path.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_docstrings.py -v`
Expected: FAIL — at least some tools lack `Args:` / `Returns:` / `Idempotency:` sections.

- [ ] **Step 3: Rewrite all 19 tool docstrings**

In `src/markland/server.py`, replace each `@mcp.tool()` decorator's docstring with the §8.6 template. The full set is below. Apply each one verbatim — keeping the structure consistent across tools is the point.

```python
@mcp.tool()
def markland_whoami(ctx: Context) -> dict:
    """Return the caller's identity.

    Use this to verify which principal (user, agent, or anonymous) the current
    bearer token resolves to. Useful for debugging auth setup, agent-token
    onboarding, and writing tools that branch on principal type.

    Args:
        (none)

    Returns:
        principal_envelope: {principal_id, principal_type, display_name,
                             is_admin, user_id}. For anonymous calls,
                             principal_id is "anonymous".

    Raises:
        (none — anonymous callers receive a special anonymous principal envelope.)

    Idempotency: Read-only.
    """
```

> **Implementer note:** Repeat this pattern for every tool. The full docstring set is reproduced in `docs/specs/2026-04-27-mcp-audit-design.md` §8.6 by template; fill the slots from the per-tool semantics in §8.0 and from reading the existing handler. Keep the **first line** as the one-sentence action summary required by §8.6 and the test in step 1.

For brevity in this plan, the remaining 18 docstrings are summarized as a table; the implementer writes them in full following the same template.

| Tool | One-line summary |
|---|---|
| `markland_publish` | Publish a markdown document owned by the current principal. |
| `markland_list` | List documents the current principal can view. |
| `markland_get` | Get a document with embedded active-presence rows. |
| `markland_search` | Search documents the current principal can view. |
| `markland_share` | Get a document's shareable URL. |
| `markland_update` | Update a document's content or title with optimistic concurrency. |
| `markland_delete` | Delete a document. Owner only. |
| `markland_set_visibility` | Promote or demote a document's public visibility. Owner only. |
| `markland_feature` | Pin or unpin a document on the landing hero. Admin only. |
| `markland_grant` | Grant view or edit access to a user or agent. Owner only. |
| `markland_revoke` | Revoke an existing grant. Owner only. Idempotent. |
| `markland_list_grants` | List all grants on a document. |
| `markland_create_invite` | Create an invite link with a pre-set access level. Owner only. |
| `markland_revoke_invite` | Revoke an outstanding invite. Owner only. Idempotent. |
| `markland_list_my_agents` | List agents owned by the current user. |
| `markland_set_status` | Announce that you are reading or editing a document. |
| `markland_clear_status` | Clear your presence announcement on a document. Idempotent. |
| `markland_audit` | Read recent audit-log entries. Admin only. |

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit_docstrings.py -v`
Expected: All PASS.

- [ ] **Step 5: Re-run baseline to confirm zero behavior drift**

Run: `uv run pytest tests/test_mcp_baseline.py -q 2>&1 | tail -3`
Expected: All baseline tests still PASS. (Docstring rewrites must not change semantics.)

- [ ] **Step 6: Commit**

```bash
git add src/markland/server.py tests/test_audit_docstrings.py
git commit -m "feat(mcp): rewrite all tool docstrings to §8.6 template (axis 6)"
```

---

## Task 2: Rename `markland_grant`'s `principal` param to `target` (with shim)

**Files:**
- Modify: `src/markland/server.py`
- Create: `tests/test_audit_naming.py`
- Create: `tests/test_audit_deprecations.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_naming.py`:

```python
"""Layer C — axis 1: parameter-naming invariants."""

import inspect
import pytest
from markland.server import build_mcp


@pytest.fixture
def mcp(tmp_path):
    from markland.db import init_db
    db = init_db(tmp_path / "t.db")
    return build_mcp(db, base_url="http://x", email_client=None)


def test_grant_uses_target_param(mcp):
    tool = mcp._tool_manager.get_tool("markland_grant")
    sig_params = list(tool.parameters.get("properties", {}).keys())
    assert "target" in sig_params, sig_params
    # `principal` is also accepted as deprecated alias — but not advertised in the schema.
```

Create `tests/test_audit_deprecations.py`:

```python
"""Layer C — deprecation parity tests.

For every renamed/folded tool, both old and new shapes must produce the same
result for the same args. Tests are deleted in Phase B when the deprecation
window closes.
"""

import pytest
from tests._mcp_harness import MCPHarness


def test_grant_principal_kw_still_works_as_target_alias(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    h.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# share")

    new_call = alice.call(
        "markland_grant", doc_id=pub["id"], target="bob@example.com", level="view"
    )

    # Re-issue with old kwarg name.
    pub2 = alice.call("markland_publish", content="# share-2")
    old_call = alice.call(
        "markland_grant", doc_id=pub2["id"], principal="bob@example.com", level="view"
    )

    assert new_call["doc_id"] == pub["id"]
    assert old_call["doc_id"] == pub2["id"]
    # Both succeed with same shape.
    assert set(new_call) == set(old_call)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_naming.py tests/test_audit_deprecations.py -v`
Expected: At least one FAIL — the schema currently shows `principal`, not `target`.

- [ ] **Step 3: Rename the kwarg with a shim**

In `src/markland/server.py`, modify the `_grant` helper and the `markland_grant` tool:

```python
def _grant(ctx, doc_id: str, target: str, level: str):
    p = _require_principal(ctx)
    # ... existing body, with `principal` parameter renamed to `target` ...
    return grants_svc.grant(
        db_conn,
        base_url=base_url,
        principal=p,
        doc_id=doc_id,
        target=target,
        level=level,
        email_client=email_client,
    )

@mcp.tool()
def markland_grant(
    ctx: Context,
    doc_id: str,
    target: str | None = None,
    level: str = "view",
    *,
    principal: str | None = None,  # Deprecated alias.
) -> dict:
    """Grant view or edit access to a user or agent. Owner only.

    Args:
        doc_id: The document to share.
        target: An email address (creates the user if missing) or an `agt_…` id.
                Replaces the `principal` keyword (now deprecated; removed in
                the release scheduled 30 days after this one).
        level: `view` or `edit`.

    Returns:
        grant_envelope: {doc_id, principal_id, level, created_at, owner_id}.

    Raises:
        not_found: doc does not exist or caller cannot see it.
        forbidden: caller is not the owner.
        invalid_argument: target not found, agent grants not supported, or
                          level not in {view, edit}.

    Idempotency: Idempotent (upsert — calling with same args is a no-op).
    """
    chosen_target = target if target is not None else principal
    if chosen_target is None:
        return {
            "error": "invalid_argument",
            "reason": "target is required",
        }
    return _grant(ctx, doc_id, chosen_target, level)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit_naming.py tests/test_audit_deprecations.py -v`
Expected: All PASS.

- [ ] **Step 5: Re-run baseline**

Run: `uv run pytest tests/test_mcp_baseline.py -q 2>&1 | tail -3`
Expected: One snapshot may have shifted (the `markland_grant` schema in any tool that snapshots schemas — likely none today, so should be 0 changes). If a `markland_grant` snapshot drifts, run with `--snapshot-update` and inspect the diff: it should only be the parameter name in any embedded schema, never the call result.

- [ ] **Step 6: Commit**

```bash
git add src/markland/server.py tests/test_audit_naming.py tests/test_audit_deprecations.py
git commit -m "feat(mcp): rename markland_grant principal → target (axis 1, with shim)"
```

---

## Task 3: Boolean-input naming convention sweep

**Files:**
- Modify: `tests/test_audit_naming.py`
- Modify: `src/markland/server.py` (only if drift found)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_naming.py`:

```python
def test_boolean_inputs_drop_is_prefix(mcp):
    """Per §8.1: boolean inputs use bare names (public, featured, single_use);
    boolean outputs keep is_ prefix (is_public, is_featured)."""
    forbidden_input_names = {"is_public", "is_featured", "is_single_use"}

    for name in mcp.markland_handlers:
        tool = mcp._tool_manager.get_tool(name)
        params = tool.parameters.get("properties", {})
        for pname in params:
            assert pname not in forbidden_input_names, (
                f"{name} uses {pname} as input; per §8.1 use bare name."
            )
```

- [ ] **Step 2: Run test to verify it passes (or fails if drift exists)**

Run: `uv run pytest tests/test_audit_naming.py::test_boolean_inputs_drop_is_prefix -v`

Today's surface uses `public`, `featured`, `single_use` (no `is_` prefix on inputs) — so this test should PASS as a contract lock-in. If it fails, find the offender and rename without an alias (these are not used by anyone outside the tool surface).

- [ ] **Step 3: Commit (test only)**

```bash
git add tests/test_audit_naming.py
git commit -m "test(mcp): lock boolean-input naming convention (axis 1)"
```

---

## Task 4: Final sweep + audit cycle complete

- [ ] **Step 1: Run all Layer C tests**

Run: `uv run pytest tests/test_audit_naming.py tests/test_audit_docstrings.py tests/test_audit_deprecations.py -v`
Expected: All PASS.

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest tests/ -q 2>&1 | tail -5`
Expected: All PASS. No baseline regressions.

- [ ] **Step 3: Verify deprecation marker is in the docstring**

Run: `uv run python -c "
from markland.db import init_db
from markland.server import build_mcp
import tempfile, pathlib
db = init_db(pathlib.Path(tempfile.mkdtemp()) / 't.db')
mcp = build_mcp(db, base_url='http://x', email_client=None)
print(mcp._tool_manager.get_tool('markland_grant').description[:600])
" | grep -i deprecated`
Expected: At least one match — the `principal` alias is documented as deprecated.

---

## Self-review checklist

- [ ] Every surviving tool's docstring follows §8.6 (Args, Returns, Raises, Idempotency).
- [ ] `markland_grant` accepts both `target` (canonical) and `principal` (deprecated).
- [ ] Layer B baseline passes unchanged.
- [ ] Layer C tests for axis 1 + axis 6 pass.
- [ ] Deprecation marker is present and removal-release note is in the docstring.
