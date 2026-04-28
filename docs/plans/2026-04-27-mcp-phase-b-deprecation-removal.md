# MCP Audit — Phase B (Deprecation Removal) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **DO NOT EXECUTE BEFORE 30 DAYS AFTER PLANS 2-6 LAND.** This plan deletes deprecated tools and parameter aliases. Running it earlier breaks any client (Claude Code installs, agent integrations, etc.) that relied on the deprecation window. The first task is a date check that aborts if executed too soon.

**Goal:** Drop the four deprecation shims (`markland_set_visibility`, `markland_feature`, `markland_set_status`, `markland_clear_status`) and the `principal=` kwarg alias on `markland_grant`. Net surface drops from 26 tools to 22 — the v1.0 target from spec §8.0.

**Architecture:** Pure deletion. Each shim definition is removed from `server.py`; the deprecation parity tests in `test_audit_deprecations.py` are removed. The `principal` alias on `markland_grant` is removed from the function signature and dispatch logic. Layer B baseline shrinks by four files.

**Tech Stack:** Python 3.12 only.

**Spec reference:** `docs/specs/2026-04-27-mcp-audit-design.md` §9 (Phase B).

---

## File Structure

**Files removed:**
- Snapshot files for the four shims:
  - `tests/fixtures/mcp_baseline/markland_set_visibility.json`
  - `tests/fixtures/mcp_baseline/markland_feature.json`
  - `tests/fixtures/mcp_baseline/markland_set_status.json`
  - `tests/fixtures/mcp_baseline/markland_clear_status.json`

**Files modified:**
- `src/markland/server.py` — drop the four shims and the `principal` kwarg on `markland_grant`. Drop their docstrings and helpers if no longer referenced.
- `tests/test_audit_deprecations.py` — file deleted entirely (or emptied).
- `tests/test_audit_idempotency.py` — drop the four shim names from `IDEMPOTENT_TOOLS`.
- `tests/test_mcp_baseline.py` — drop the four shim baseline tests.
- `README.md` — drop the four shim rows from the tool table; update the count.

---

## Task 1: Date check (abort if too soon)

**Files:** None — this task gates execution.

- [ ] **Step 1: Verify the plan should run**

Phase B is gated on the deprecation tag laid down at the end of plan 6 (or
manually after axis 5 lands). Plan 6's task 8 must include a final commit:

```bash
git tag -a mcp-audit-axis-5-released -m "axis-5 shipped; Phase B opens at +30d"
git push origin mcp-audit-axis-5-released
```

Then in this plan:

```bash
TAG_DATE=$(git log -1 --format=%cs mcp-audit-axis-5-released 2>/dev/null)
TODAY=$(date +%Y-%m-%d)
if [ -z "$TAG_DATE" ]; then
    echo "Tag mcp-audit-axis-5-released not found; plan 6 not finalized. ABORT."
    exit 1
fi
# Linux: ELAPSED=$(( ($(date -d "$TODAY" +%s) - $(date -d "$TAG_DATE" +%s)) / 86400 ))
ELAPSED=$(( ($(date -j -f "%Y-%m-%d" "$TODAY" +%s) - $(date -j -f "%Y-%m-%d" "$TAG_DATE" +%s)) / 86400 ))
echo "Days since axis-5 release tag: $ELAPSED"
if [ "$ELAPSED" -lt 30 ]; then
    echo "Less than 30 days since axis-5 release. Phase B is too early. ABORT."
    exit 1
fi
echo "Cleared for Phase B."
```

> **Why a tag, not a path-based date:** The plan-doc commit timestamp can drift
> from the implementation commit if plans get rebased, cherry-picked, or
> committed out of order from execution. The tag is laid at the moment the
> last axis-5 work actually lands on `main`, anchoring the window to the real
> release. Plan 6 task 8 already updates README + ROADMAP — adding the tag
> command there closes the loop.

- [ ] **Step 2: Confirm with the user before proceeding**

Pause and ask: "Phase B drops 4 deprecated tools and the `markland_grant` `principal=` alias. Confirm any external integrations have migrated to the new names?"

If unsure, do NOT proceed. Each shim is small; the cost of waiting another sprint is low, the cost of breaking installed clients is high.

---

## Task 2: Drop the four shim tool definitions

**Files:**
- Modify: `src/markland/server.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_naming.py`:

```python
def test_deprecated_shims_removed_in_phase_b(mcp):
    """Phase B: the four folded predecessors no longer exist."""
    assert "markland_set_visibility" not in mcp.markland_handlers
    assert "markland_feature" not in mcp.markland_handlers
    assert "markland_set_status" not in mcp.markland_handlers
    assert "markland_clear_status" not in mcp.markland_handlers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audit_naming.py -v -k phase_b`
Expected: FAIL — shims still present.

- [ ] **Step 3: Delete the shim functions**

In `src/markland/server.py`, delete:
- The `@mcp.tool() def markland_set_visibility(...)` block.
- The `@mcp.tool() def markland_feature(...)` block.
- The `@mcp.tool() def markland_set_status(...)` block.
- The `@mcp.tool() def markland_clear_status(...)` block.

Also delete from the `handlers.update(...)` block at the bottom of `build_mcp` — these helpers' entries.

- [ ] **Step 4: Run + commit**

Run: `uv run pytest tests/test_audit_naming.py -v -k phase_b`
Expected: PASS.

```bash
git add src/markland/server.py tests/test_audit_naming.py
git commit -m "feat(mcp): Phase B — drop set_visibility/feature/set_status/clear_status shims"
```

---

## Task 3: Drop the `principal` kwarg alias on `markland_grant`

**Files:**
- Modify: `src/markland/server.py`
- Modify: `tests/test_audit_deprecations.py` (delete the parity test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_naming.py`:

```python
def test_grant_no_longer_accepts_principal_kwarg(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    h.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# t")

    # `target` works (canonical).
    alice.call("markland_grant", doc_id=pub["id"],
               target="bob@example.com", level="view")

    # `principal` no longer works — should produce a TypeError or invalid_argument.
    with pytest.raises((TypeError, Exception)):
        alice.call("markland_grant", doc_id=pub["id"],
                   principal="bob@example.com", level="view")
```

- [ ] **Step 2: Modify `markland_grant` to drop the alias**

In `src/markland/server.py`:

```python
@mcp.tool()
def markland_grant(
    ctx: Context, doc_id: str, target: str, level: str = "view",
) -> dict:
    """Grant view or edit access to a user or agent. Owner only.

    Args:
        doc_id: The document to share.
        target: An email address (creates the user if missing) or an `agt_…` id.
        level: `view` or `edit`.

    Returns:
        grant_envelope: {doc_id, principal_id, level, created_at, owner_id}.

    Raises:
        not_found: doc does not exist or caller cannot see it.
        forbidden: caller is not the owner.
        invalid_argument: target not found, agent grants not supported, or
                          level not in {view, edit}.

    Idempotency: Idempotent (upsert).
    """
    return _grant(ctx, doc_id, target, level)
```

(The `principal` keyword and the conditional dispatch are gone.)

- [ ] **Step 3: Delete the parity test**

```bash
rm tests/test_audit_deprecations.py
```

- [ ] **Step 4: Run + commit**

Run: `uv run pytest tests/test_audit_naming.py -v -k "phase_b or principal_kwarg"`
Expected: PASS.

Run: `uv run pytest tests/ -q 2>&1 | tail -3`
Expected: All PASS. Anything still using `principal=` as a kwarg gets caught here — fix per call site.

```bash
git add src/markland/server.py tests/test_audit_naming.py
git rm tests/test_audit_deprecations.py
git commit -m "feat(mcp): Phase B — drop markland_grant principal= alias"
```

---

## Task 4: Drop deprecated baseline snapshots and tests

**Files:**
- Delete: 4 snapshot files
- Modify: `tests/test_mcp_baseline.py`

- [ ] **Step 1: Delete shim baseline files**

```bash
rm tests/fixtures/mcp_baseline/markland_set_visibility.json
rm tests/fixtures/mcp_baseline/markland_feature.json
rm tests/fixtures/mcp_baseline/markland_set_status.json
rm tests/fixtures/mcp_baseline/markland_clear_status.json
```

- [ ] **Step 2: Drop the corresponding `test_baseline_*` functions**

In `tests/test_mcp_baseline.py`, find and delete every test function whose name contains `set_visibility`, `feature`, `set_status`, `clear_status`.

- [ ] **Step 3: Run + commit**

Run: `uv run pytest tests/test_mcp_baseline.py -q 2>&1 | tail -3`
Expected: PASS.

```bash
git add tests/test_mcp_baseline.py
git rm tests/fixtures/mcp_baseline/markland_set_visibility.json tests/fixtures/mcp_baseline/markland_feature.json tests/fixtures/mcp_baseline/markland_set_status.json tests/fixtures/mcp_baseline/markland_clear_status.json
git commit -m "test(mcp): Phase B — drop shim baseline tests + snapshots"
```

---

## Task 5: Update idempotency catalog

**Files:**
- Modify: `tests/test_audit_idempotency.py`

- [ ] **Step 1: Drop shim names from `IDEMPOTENT_TOOLS`**

```python
IDEMPOTENT_TOOLS = {
    "markland_doc_meta",
    "markland_grant",
    "markland_revoke",
    "markland_status",
    "markland_revoke_invite",
    # Phase B: shims removed.
}
```

- [ ] **Step 2: Run + commit**

Run: `uv run pytest tests/test_audit_idempotency.py -v`
Expected: PASS.

```bash
git add tests/test_audit_idempotency.py
git commit -m "test(mcp): Phase B — drop shims from idempotency catalog"
```

---

## Task 6: Update README + ROADMAP

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: README — drop shim rows**

In `README.md`, delete the four shim rows from the tool table. Update the surface description to reflect 22 tools.

- [ ] **Step 2: ROADMAP — move MCP audit from Now to Shipped**

In `docs/ROADMAP.md`:
- Remove the "MCP audit + test harness" entry from the **Now** section.
- Add a "MCP audit complete" line under **Shipped** > **Build (audit)**:
  ```
  - **2026-MM-DD** — MCP audit complete. Surface consolidated to 22 tools (5
    new, 4 deprecated shims removed). doc/list envelopes, closed-set error
    model, pagination, idempotency contract documented per tool.
    See `docs/specs/2026-04-27-mcp-audit-design.md` and `docs/plans/2026-04-27-mcp-*.md`.
  ```

- [ ] **Step 3: Commit**

```bash
git add README.md docs/ROADMAP.md
git commit -m "docs: Phase B — surface is now 22 tools; mark MCP audit shipped"
```

---

## Task 7: Final integration check

- [ ] **Step 1: Run the full suite**

Run: `uv run pytest tests/ -q 2>&1 | tail -10`
Expected: All PASS.

- [ ] **Step 2: Verify the surface count**

Run:
```bash
uv run python -c "
import tempfile, pathlib
from markland.db import init_db
from markland.server import build_mcp
db = init_db(pathlib.Path(tempfile.mkdtemp()) / 't.db')
mcp = build_mcp(db, base_url='http://x', email_client=None)
tools = sorted(mcp.markland_handlers)
print(f'Tool count: {len(tools)}')
for t in tools:
    print(f'  - {t}')
"
```

Expected output: **22 tools.** Sorted list:
- markland_audit
- markland_create_invite
- markland_delete
- markland_doc_meta
- markland_explore
- markland_fork
- markland_get
- markland_get_by_share_token
- markland_grant
- markland_list
- markland_list_grants
- markland_list_invites
- markland_list_my_agents
- markland_publish
- markland_revisions
- markland_revoke
- markland_revoke_invite
- markland_search
- markland_share
- markland_status
- markland_update
- markland_whoami

If the count is not 22, hunt the discrepancy — extra tools weren't supposed to land in this audit.

- [ ] **Step 3: Verify §14 acceptance criteria**

Walk through `docs/specs/2026-04-27-mcp-audit-design.md` §14:

1. ✅ All 19 existing tools landed their disposition (table in §8.0).
2. ✅ 5 new tools exist (axis 5).
3. ✅ doc-returning tools use `doc_envelope`; list tools use `list_envelope`.
4. ✅ Every error path uses one of seven codes (assert grep: see Task 8 below).
5. ✅ Every list-returning tool supports `limit` + `cursor`.
6. ✅ Every tool's docstring follows the §8.6 template (asserted by `test_audit_docstrings.py`).
7. ✅ Every mutating tool's idempotency contract is documented and tested.
8. ✅ Layer A, B, C tests pass.
9. ✅ Phase B deprecations removed (this plan).
10. ✅ README's tool table reflects the new surface.

- [ ] **Step 4: Final commit (none expected — this is a verification task)**

```bash
git status
# If clean, audit is complete.
```

---

## Task 8: Closed-error-set assertion (acceptance criterion #4)

**Files:**
- Modify: `tests/test_audit_error_model.py`

- [ ] **Step 1: Write the assertion**

Append to `tests/test_audit_error_model.py`:

```python
import json
import pathlib


def test_every_error_snapshot_uses_closed_code_set():
    """Walk every snapshot file; every kind: error scenario carries one of
    the seven canonical codes."""
    base = pathlib.Path("tests/fixtures/mcp_baseline")
    allowed = {
        "unauthenticated", "forbidden", "not_found", "conflict",
        "invalid_argument", "rate_limited", "internal_error",
    }
    for snapshot_file in base.glob("*.json"):
        data = json.loads(snapshot_file.read_text())
        for scenario, payload in data.items():
            if payload.get("kind") == "error":
                assert payload["code"] in allowed, (
                    f"{snapshot_file.name}::{scenario} uses unknown code "
                    f"{payload['code']!r}"
                )
```

- [ ] **Step 2: Run + commit**

Run: `uv run pytest tests/test_audit_error_model.py::test_every_error_snapshot_uses_closed_code_set -v`
Expected: PASS.

```bash
git add tests/test_audit_error_model.py
git commit -m "test(mcp): assert every error snapshot uses the closed code set"
```

---

## Self-review checklist

- [ ] Date check confirmed at least 30 days have passed.
- [ ] Four deprecated tools removed from `server.py`.
- [ ] `markland_grant` no longer accepts `principal=`.
- [ ] Four snapshot files deleted.
- [ ] `tests/test_audit_deprecations.py` deleted.
- [ ] Idempotency catalog updated.
- [ ] README + ROADMAP updated.
- [ ] Surface count is 22.
- [ ] Every snapshot's error scenarios use one of the seven canonical codes.
- [ ] Full suite green.

---

## Rollback

If this plan goes sideways and the deletion needs to be reverted, every removed shim is recoverable from git:

```bash
# Find the last commit containing markland_set_visibility:
git log --diff-filter=D -p --follow -- src/markland/server.py \
  | grep -B5 'markland_set_visibility' | head -20

# Revert the specific commit:
git revert <hash>
```

But: rollback should be *rare*. The deprecation window existed precisely to make this deletion safe.
