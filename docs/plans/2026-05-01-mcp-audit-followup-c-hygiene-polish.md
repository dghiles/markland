# MCP Audit Follow-up C — Hygiene & Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address the 10 Minor items the retrospective review surfaced across all 6 merged MCP audit PRs. Each item is small and independent; this plan can be cherry-picked piecemeal if a full sweep isn't appealing.

**Architecture:** Eight tasks. Each follows the same shape — single-file change, small targeted test (or no test where the change is documentation-only), one commit. No cross-task dependencies; tasks can land in any order.

**Tech Stack:** Python 3.12.

**Source of issues:** Retrospective review of merged PRs #27, #30, #32, #33, #36, #38.

---

## File Structure

**Modified files (across all tasks):**
- `tests/_mcp_harness.py` — env-var hygiene, anon-HTTP guard, `_VOLATILE_FIELDS` cleanup, list-of-non-dict recursion.
- `tests/conftest.py` — accept `monkeypatch` in `mcp_http` fixture.
- `src/markland/_mcp_envelopes.py` — strict mode option for `doc_envelope`; rename `last_updated_at` cursor kwarg.
- `src/markland/service/{docs,invites,grants,agents,audit}.py` — adopt the renamed cursor kwarg.
- `src/markland/server.py` — `set_status` shim rejects `None`; `clear_status` shim returns legacy `{ok: true}` shape.
- `tests/test_audit_*.py` — small additions to lock contracts.
- `tests/fixtures/mcp_baseline/*.json` — re-snap as needed.

**New files:** none.

---

## Pre-flight checks

- [ ] **Verify clean worktree off origin/main**

Run: `git status -sb && git log --oneline -3`
Expected: branch tracks origin/main; HEAD is post-Plan-6 main.

- [ ] **Verify all post-Plan-6 tests pass**

Run: `uv run pytest tests/ --tb=no 2>&1 | tail -3`
Expected: ~870 tests pass cleanly (modulo the known flake).

---

## Task 1: Harness env-vars via `monkeypatch`

**Files:**
- Modify: `tests/_mcp_harness.py:107-112`.
- Modify: `tests/conftest.py` (`mcp_http` fixture).

**Issue:** `MCPHarness.create` does `os.environ.setdefault("MARKLAND_RATE_LIMIT_…", "10000")`. This mutates process-wide env, leaks across the session, and `setdefault` means only the first test wins — a future rate-limit-coverage test would silently get 10000 instead of the production default. Rest of the codebase uses `monkeypatch.setenv`.

- [ ] **Step 1: Update `MCPHarness.create` to accept an optional monkeypatch**

In `tests/_mcp_harness.py`, find the section that does `os.environ.setdefault(...)` (around lines 107-112) and replace with:

```python
        # Env vars must be set BEFORE create_app() since the app reads
        # them at build time. The fixture (conftest.py) passes
        # monkeypatch so values are scoped to the test, not the session.
        if monkeypatch is not None:
            monkeypatch.setenv("MARKLAND_RATE_LIMIT_USER_PER_MIN", "10000")
            monkeypatch.setenv("MARKLAND_RATE_LIMIT_AGENT_PER_MIN", "10000")
            monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "10000")
        else:
            # Fallback for direct callers (e.g., test_mode_equivalence
            # builds harnesses without a fixture). setdefault keeps the
            # same first-wins semantics the old code had.
            import os
            os.environ.setdefault("MARKLAND_RATE_LIMIT_USER_PER_MIN", "10000")
            os.environ.setdefault("MARKLAND_RATE_LIMIT_AGENT_PER_MIN", "10000")
            os.environ.setdefault("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "10000")
```

Update the `MCPHarness.create` signature to accept `monkeypatch`:

```python
    @classmethod
    def create(
        cls,
        tmp_path,
        *,
        mode: Mode = "direct",
        monkeypatch=None,
    ) -> "MCPHarness":
```

- [ ] **Step 2: Thread `monkeypatch` through the `mcp_http` fixture**

In `tests/conftest.py`, replace the `mcp_http` fixture:

```python
@pytest.fixture
def mcp_http(tmp_path, monkeypatch, request) -> "MCPHarness":
    h = MCPHarness.create(tmp_path, mode="http", monkeypatch=monkeypatch)
    h._snapshot_update = request.config.getoption("--snapshot-update")
    yield h
    h.close()
```

(`mcp` fixture for direct mode doesn't need monkeypatch — env vars only matter for HTTP backend.)

- [ ] **Step 3: Run all HTTP-mode tests**

Run: `uv run pytest tests/ -k "http" --tb=short 2>&1 | tail -10`
Expected: all pass. If a test fails because `monkeypatch` isn't available in its fixture chain, that's a real regression — fix the fixture, don't suppress.

- [ ] **Step 4: Run full suite**

Run: `uv run pytest tests/ --tb=no 2>&1 | tail -3`
Expected: all pass.

- [ ] **Step 5: Commit**

```
git add tests/_mcp_harness.py tests/conftest.py
git commit -m "test(mcp): mcp_http fixture uses monkeypatch for rate-limit env

The harness was calling os.environ.setdefault directly, leaking
env state across the session and silently letting only the first
test win. The mcp_http fixture now threads monkeypatch through so
env mutations are torn down per-test. Direct construction without
a fixture (e.g., the mode-equivalence test) keeps the old fallback."
```

---

## Task 2: Anon-HTTP explicit-raise guard

**Files:**
- Modify: `tests/_mcp_harness.py` (`_http_call` body).

**Issue:** `_http_call` initializes a session only when `caller.token is not None`. Anon calls work today via the 401 short-circuit, but Plan 6's anon-allowed tools (`markland_get_by_share_token`, `markland_explore`) would in HTTP-mode hit undefined behavior — no session, but the tool actually allows the call. Either finish the path or raise loudly. Given Plan 7's scope hasn't decided, raise loudly.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mcp_harness.py`:

```python
def test_http_anon_to_allowed_tool_raises_harness_error(tmp_path):
    """Plan-C.2: until anon-HTTP support is intentional, calling an
    anon-allowed tool (markland_explore) via HTTP-mode anon should
    raise MCPHarnessError early rather than producing undefined
    behavior in the session-init path."""
    from tests._mcp_harness import MCPHarness, MCPHarnessError
    h = MCPHarness.create(tmp_path, mode="http")
    try:
        with pytest.raises(MCPHarnessError, match="anon"):
            h.anon().call_raw("markland_explore")
    finally:
        h.close()
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/test_mcp_harness.py::test_http_anon_to_allowed_tool_raises_harness_error -v`
Expected: FAIL — today the call probably surfaces 401 unauthenticated or undefined behavior.

> **If today the call returns `unauthenticated` cleanly:** that means the 401 short-circuit happens before our anon-allowed tools dispatch. That's actually fine for the anon-allowed tools that PrincipalMiddleware doesn't gate. Re-check by examining `src/markland/web/principal_middleware.py` — does it 401 anon on `/mcp/*` regardless of tool name? If yes, this whole task is moot and should be dropped (the existing 401 path works for anon-allowed tools too). Verify before implementing the guard.

- [ ] **Step 3a (if anon HTTP works today): drop this task and move on**

If Step 2's test PASSES because anon calls cleanly return `unauthenticated`, that's a Layer-1 issue with the harness's mental model — anon IS supported in HTTP because the middleware lets the call through and the tool's anon-allowed code path runs. Nothing to fix; document the finding:

```
git commit --allow-empty -m "docs(mcp): anon HTTP works for explore/get_by_share_token (no fix needed)"
```

Then skip to Task 3.

- [ ] **Step 3b (if Step 2 fails as expected): add the guard**

In `tests/_mcp_harness.py`, find `_http_call` and at its top add:

```python
def _http_call(harness, caller, tool, kwargs):
    if not hasattr(harness, "_http_client"):
        raise MCPHarnessError(
            "HTTP-mode harness was not initialized with TestClient"
        )
    if caller.token is None:
        raise MCPHarnessError(
            "HTTP-mode anon calls are not yet supported — "
            "use direct mode or seed a principal."
        )
    # ... existing body ...
```

- [ ] **Step 4: Run, verify pass**

Run: `uv run pytest tests/test_mcp_harness.py::test_http_anon_to_allowed_tool_raises_harness_error -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add tests/_mcp_harness.py tests/test_mcp_harness.py
git commit -m "test(mcp): explicit-raise guard for HTTP anon calls

Today's path silently underdefines what happens when an anon
caller hits an anon-allowed tool (Plan 6's explore/share_token).
Until anon-HTTP support is intentional, raise MCPHarnessError so
the limitation is visible at test-write time."
```

---

## Task 3: Cursor field rename — `last_updated_at` → `last_sort_key`

**Files:**
- Modify: `src/markland/_mcp_envelopes.py` (`encode_cursor`, `decode_cursor`).
- Modify: 5 service-layer callers — `src/markland/service/{docs,invites,grants,agents,audit}.py`.
- Test: `tests/test_audit_return_envelopes.py` (extend cursor round-trip test).

**Issue:** `encode_cursor(last_updated_at=...)` is called with `created_at` values in `revisions`, `invites`, `agents`, and `audit` — the parameter name lies about what's stored. Rename to a neutral term.

- [ ] **Step 1: Rename in `_mcp_envelopes.py`**

In `src/markland/_mcp_envelopes.py`, find `encode_cursor` and `decode_cursor`. Add overload-like compat:

```python
def encode_cursor(*, last_id, last_sort_key=None, last_updated_at=None) -> str:
    """Encode an opaque pagination cursor.

    Use `last_sort_key` for the timestamp (or other monotonic value) the
    underlying query orders by — could be updated_at, created_at, or any
    other column you ORDER BY. The legacy `last_updated_at` kwarg is kept
    for backwards compatibility.
    """
    if last_sort_key is None:
        last_sort_key = last_updated_at
    if last_sort_key is None:
        raise ValueError("encode_cursor requires last_sort_key")
    payload = json.dumps(
        {"last_id": last_id, "last_updated_at": last_sort_key},
        sort_keys=True,
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
```

Keep the on-wire JSON key as `last_updated_at` to preserve cursor compatibility — only the Python kwarg is renamed.

`decode_cursor` returns `(last_id, last_sort_key)` — same tuple, the second element name in our docs becomes neutral. Update the docstring:

```python
def decode_cursor(cursor: str) -> tuple[str, str]:
    """Decode an opaque cursor.

    Returns (last_id, last_sort_key) where last_sort_key is the value the
    query orders by (updated_at, created_at, etc.) — caller knows which.
    Raises ValueError on malformed input.
    """
```

- [ ] **Step 2: Update each service-layer caller to pass `last_sort_key=`**

There are 5 sites. For each:

`src/markland/service/docs.py` — `list_for_principal_paginated` and `search_paginated`. Both already use `updated_at`. Change `encode_cursor(last_id=..., last_updated_at=last.updated_at)` to `encode_cursor(last_id=..., last_sort_key=last.updated_at)`.

`src/markland/service/docs.py` — `list_revisions_paginated`. Already passes `created_at`; change to `last_sort_key=...`.

`src/markland/service/docs.py` — `list_public_paginated`. `updated_at` source; rename kwarg.

`src/markland/service/invites.py` — `list_for_doc_paginated`. `created_at` source; rename kwarg.

`src/markland/service/grants.py` — `list_grants_paginated`. Whatever timestamp it uses; rename kwarg.

`src/markland/service/agents.py` — `list_paginated`. `created_at` source; rename kwarg.

`src/markland/service/audit.py` — `list_recent_paginated`. `created_at` source; rename kwarg.

- [ ] **Step 3: Run all pagination tests + replay**

Run: `uv run pytest tests/test_audit_pagination.py tests/test_mcp_baseline.py --tb=no -q 2>&1 | tail -3`
Expected: all pass. Cursor on-wire format didn't change (still base64-JSON of `{last_id, last_updated_at}` in the JSON), so existing snapshots replay clean.

- [ ] **Step 4: Add a focused test for the new kwarg**

Append to `tests/test_audit_return_envelopes.py`:

```python
def test_encode_cursor_accepts_last_sort_key():
    """Plan-C.3: encode_cursor accepts the renamed kwarg; legacy
    last_updated_at kwarg still works for compatibility."""
    new_kw = encode_cursor(last_id="x", last_sort_key="2026-05-01T00:00:00Z")
    legacy_kw = encode_cursor(last_id="x", last_updated_at="2026-05-01T00:00:00Z")
    assert new_kw == legacy_kw  # same on-wire format


def test_encode_cursor_requires_one_kwarg():
    """encode_cursor without either kwarg raises ValueError."""
    with pytest.raises(ValueError, match="last_sort_key"):
        encode_cursor(last_id="x")
```

- [ ] **Step 5: Run, verify pass**

Run: `uv run pytest tests/test_audit_return_envelopes.py -v -k "encode_cursor" 2>&1 | tail -5`
Expected: PASS.

- [ ] **Step 6: Commit**

```
git add src/markland/_mcp_envelopes.py src/markland/service/ tests/test_audit_return_envelopes.py
git commit -m "refactor(mcp): rename cursor kwarg last_updated_at → last_sort_key

Plan 6 review caught that the kwarg lies about its content for
revisions/invites/agents/audit (which use created_at). Wire format
unchanged — only the Python kwarg name. last_updated_at kept as
deprecated alias for back-compat."
```

---

## Task 4: `set_status` shim rejects `status=None`

**Files:**
- Modify: `src/markland/server.py` (find the `markland_set_status` shim, currently around line 1156).
- Test: `tests/test_audit_deprecations.py` (append).

**Issue:** The deprecated `markland_set_status` shim's signature says `status: str` and its docstring promises `Raises: invalid_argument: status not in {reading, editing}`. But the body delegates to `_status` which interprets `None` as a clear. A caller passing `null` gets a silent clear instead of `invalid_argument`. Tighten the shim to match its contract.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_deprecations.py`:

```python
def test_set_status_shim_rejects_none(tmp_path):
    """Plan-C.4: the deprecated set_status shim's signature says
    status: str (not str | None). Passing None should surface as
    invalid_argument matching the docstring contract — not silently
    clear the presence."""
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")

    r = alice.call_raw("markland_set_status", doc_id=pub["id"], status=None)
    r.assert_error("invalid_argument")
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/test_audit_deprecations.py::test_set_status_shim_rejects_none -v`
Expected: FAIL — today's shim happily clears the presence.

- [ ] **Step 3: Tighten the shim**

In `src/markland/server.py`, find `markland_set_status` (the deprecation shim — should be a `@mcp.tool()` decorated function delegating to `_status`). Add a guard at the top:

```python
    @mcp.tool()
    def markland_set_status(
        ctx: Context,
        doc_id: str,
        status: str,
        note: str | None = None,
    ) -> dict:
        """Deprecated. Use markland_status(doc_id, status=...) instead.
        ...
        """
        if status is None:
            raise tool_error(
                "invalid_argument",
                reason="status_must_be_reading_or_editing",
            )
        return _status(ctx, doc_id, status=status, note=note)
```

> **Why a runtime check** even though the type hint says `str`: MCP/JSON-RPC clients can send any JSON value; type hints are advisory. The pre-merge review specifically flagged that JSON `null` flows past the type hint into `_status` which then treats it as a clear.

- [ ] **Step 4: Run new test, verify pass**

Run: `uv run pytest tests/test_audit_deprecations.py::test_set_status_shim_rejects_none -v`
Expected: PASS.

- [ ] **Step 5: Run baseline + suite**

Run: `uv run pytest tests/ --tb=no 2>&1 | tail -3`
Expected: all pass; no baseline drift expected (existing baselines test `status="reading"` and `status="grilling"` paths, neither of which hit the new branch).

- [ ] **Step 6: Commit**

```
git add src/markland/server.py tests/test_audit_deprecations.py
git commit -m "fix(mcp): set_status shim rejects status=None per docstring

Pre-merge review of PR #36 flagged that the deprecated set_status
shim accepted None and silently delegated to clear, contradicting
its own Raises section. Now matches the docstring."
```

---

## Task 5: `clear_status` shim restores legacy `{ok: true}` shape

**Files:**
- Modify: `src/markland/server.py` (find `markland_clear_status` shim).
- Test: `tests/test_audit_deprecations.py` (append).
- Snapshot: `tests/fixtures/mcp_baseline/markland_clear_status.json` (re-snap).

**Issue:** The pre-Plan-5 `markland_clear_status` returned `{ok: true}`. The shim now returns the new `{doc_id, cleared: true}` shape from `_status`. Strict-shape callers using `result["ok"]` break before the 30-day deprecation deadline. The shim should be return-faithful — translate back to legacy on its way out.

- [ ] **Step 1: Write the test pinning the legacy shape**

Append to `tests/test_audit_deprecations.py`:

```python
def test_clear_status_shim_returns_legacy_ok_true_shape(tmp_path):
    """Plan-C.5: the deprecated clear_status shim must preserve its
    pre-deprecation response shape {ok: true} so existing callers
    don't break before the 30-day removal deadline."""
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    alice.call("markland_set_status", doc_id=pub["id"], status="reading")

    res = alice.call("markland_clear_status", doc_id=pub["id"])
    assert res == {"ok": True}, (
        f"shim returned {res!r}; expected legacy {{'ok': True}} until "
        "the deprecation window closes"
    )
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/test_audit_deprecations.py::test_clear_status_shim_returns_legacy_ok_true_shape -v`
Expected: FAIL — today's shim returns `{doc_id, cleared: true}`.

- [ ] **Step 3: Wrap the shim to translate the response**

In `src/markland/server.py`, find `markland_clear_status` and replace its body so the new shape is translated back to legacy:

```python
    @mcp.tool()
    def markland_clear_status(ctx: Context, doc_id: str) -> dict:
        """Deprecated. Use markland_status(doc_id, status=None) instead.
        ...
        """
        _status(ctx, doc_id, status=None)
        # Preserve the pre-deprecation {ok: true} shape so existing
        # callers don't break before the 30-day removal deadline.
        return {"ok": True}
```

- [ ] **Step 4: Run test, verify pass**

Run: `uv run pytest tests/test_audit_deprecations.py::test_clear_status_shim_returns_legacy_ok_true_shape -v`
Expected: PASS.

- [ ] **Step 5: Re-snap the baseline**

Run:
```
uv run pytest tests/test_mcp_baseline.py -k clear_status --snapshot-update -q 2>&1 | tail -3
git diff tests/fixtures/mcp_baseline/markland_clear_status.json
```
Expected diff: shape returns to `{ok: true}` for both scenarios in that file.

- [ ] **Step 6: Replay**

Run: `uv run pytest tests/test_mcp_baseline.py -k clear_status -v 2>&1 | tail -3`
Expected: all PASS.

- [ ] **Step 7: Commit**

```
git add src/markland/server.py tests/test_audit_deprecations.py tests/fixtures/mcp_baseline/markland_clear_status.json
git commit -m "fix(mcp): clear_status shim restores legacy {ok: true} shape

Plan 5 (PR #36) routed the deprecation shim through _status which
returns {doc_id, cleared: true} — a breaking shape change inside
the 30-day deprecation window. The shim now wraps and returns
{ok: true} so existing callers continue working until the shim
itself is removed in Phase B."
```

---

## Task 6: `doc_envelope` strict-mode opt-in

**Files:**
- Modify: `src/markland/_mcp_envelopes.py` (`doc_envelope`).
- Test: `tests/test_audit_return_envelopes.py` (append).

**Issue:** `doc_envelope(raw)` projects via `raw.get(k)` — missing keys silently become `None`. A service-layer regression that drops `share_url` or `version` would surface only as a snapshot diff, not a boundary failure. Add a `strict=True` mode that asserts required fields are present.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_return_envelopes.py`:

```python
def test_doc_envelope_strict_mode_rejects_missing_required_field():
    """Plan-C.6: doc_envelope(raw, strict=True) raises if any required
    field is missing — catches service-layer regressions at the boundary
    instead of via snapshot diff."""
    incomplete = {
        "id": "doc_abc",
        "title": "T",
        # content missing
        "version": 1,
        "owner_id": "usr_x",
        "share_url": "http://x/d/abc",
        "is_public": False,
        "is_featured": False,
        "created_at": "x",
        "updated_at": "x",
    }
    # Default mode tolerates missing fields (today's behavior).
    env = doc_envelope(incomplete)
    assert env["content"] is None  # silent None

    # Strict mode raises.
    with pytest.raises(KeyError, match="content"):
        doc_envelope(incomplete, strict=True)
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/test_audit_return_envelopes.py::test_doc_envelope_strict_mode_rejects_missing_required_field -v`
Expected: FAIL — `strict` kwarg doesn't exist.

- [ ] **Step 3: Add `strict` parameter**

In `src/markland/_mcp_envelopes.py`, replace `doc_envelope`:

```python
def doc_envelope(
    raw: dict,
    *,
    active_principals: list[dict] | None = None,
    strict: bool = False,
) -> dict:
    """Project a service-layer doc dict into the canonical doc_envelope.

    With strict=True, raises KeyError if any of the 10 required fields
    is missing from raw — useful for boundary-layer assertions in tests.
    Default (strict=False) preserves backward compatibility with callers
    that pass partial dicts.
    """
    if strict:
        missing = [k for k in _DOC_ENVELOPE_FIELDS if k not in raw]
        if missing:
            raise KeyError(
                f"doc_envelope(strict=True) missing required fields: {missing}"
            )
    env = {k: raw.get(k) for k in _DOC_ENVELOPE_FIELDS}
    if active_principals is not None:
        env["active_principals"] = active_principals
    return env
```

- [ ] **Step 4: Run test, verify pass**

Run: `uv run pytest tests/test_audit_return_envelopes.py::test_doc_envelope_strict_mode_rejects_missing_required_field -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `uv run pytest tests/ --tb=no 2>&1 | tail -3`
Expected: all pass; no callers affected since strict defaults to False.

- [ ] **Step 6: Commit**

```
git add src/markland/_mcp_envelopes.py tests/test_audit_return_envelopes.py
git commit -m "feat(mcp): doc_envelope strict mode opt-in

Adds strict=True to doc_envelope so boundary callers can assert
all 10 required fields are present. Default behavior unchanged
(silent None on missing). Caught by retrospective review of PR #33."
```

---

## Task 7: `_VOLATILE_FIELDS` — drop blanket `id` mask

**Files:**
- Modify: `tests/_mcp_harness.py` (`_VOLATILE_FIELDS`).
- Test: existing snapshots replay (no new test).

**Issue:** `_VOLATILE_FIELDS["id"] = "<ID>"` blanket-masks any field named `id` regardless of value. The typed-prefix regex matches first when value is id-shaped, but a field named `id` containing a slug, numeric counter, or any non-id string gets silently flattened to `<ID>`. Drop the entry so the typed-regex path is the only mask source.

- [ ] **Step 1: Verify what currently exercises the `id` fallback**

Run:
```
grep -A2 '"id":' tests/fixtures/mcp_baseline/*.json | grep '"<ID>"' | head
```
Expected: zero or near-zero hits. If non-empty, those are the snapshots that will need re-snapping.

- [ ] **Step 2: Drop the entry**

In `tests/_mcp_harness.py`, find `_VOLATILE_FIELDS` (around line 540-560) and remove the line:

```python
"id": "<ID>",  # generic — overridden below by id-prefix pattern
```

Keep all the typed-prefix entries (`owner_id`, `principal_id`, etc.).

- [ ] **Step 3: Run baseline replay**

Run: `uv run pytest tests/test_mcp_baseline.py --tb=no -q 2>&1 | tail -3`
Expected: most pass; any drift is from a scenario that depended on the blanket `id` mask. Re-snap if so:

Run: `uv run pytest tests/test_mcp_baseline.py --snapshot-update -q 2>&1 | tail -3`
Then `git diff tests/fixtures/mcp_baseline/` — only `<ID>` entries should disappear in favor of typed placeholders or actual values.

- [ ] **Step 4: Run replay again to confirm**

Run: `uv run pytest tests/test_mcp_baseline.py --tb=no -q 2>&1 | tail -3`
Expected: all pass.

- [ ] **Step 5: Commit**

```
git add tests/_mcp_harness.py tests/fixtures/mcp_baseline/
git commit -m "test(mcp): drop blanket _VOLATILE_FIELDS['id'] mask

The typed-regex path already handles id-shaped strings under any
key. The blanket 'id' fallback masked legitimate non-id values
(slugs, numeric counters) when they happened to live under a key
named 'id'. Caught by retrospective review of PR #27."
```

---

## Task 8: `as_envelope` recursion into list-of-non-dict

**Files:**
- Modify: `tests/_mcp_harness.py` (`as_envelope`).
- Test: append to existing test.

**Issue:** `as_envelope` recurses into `dict` and `list` but doesn't apply `_placeholder_for_id` to non-dict list elements. So a list of bare-hex doc IDs (`["6d164947bd16f07f", ...]`) wouldn't get their elements masked — only when they're values under a known field name.

- [ ] **Step 1: Verify the issue with a test**

Append to `tests/test_mcp_harness.py`:

```python
def test_as_envelope_masks_id_shaped_strings_inside_lists():
    """Plan-C.8: bare-hex doc IDs inside a list should still be masked."""
    payload = {"doc_ids": ["6d164947bd16f07f", "abcdef0123456789"]}
    out = as_envelope(payload)
    assert out == {"doc_ids": ["<DOC_ID>", "<DOC_ID>"]}
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/test_mcp_harness.py::test_as_envelope_masks_id_shaped_strings_inside_lists -v`
Expected: FAIL — list elements pass through unmasked.

- [ ] **Step 3: Fix the recursion**

In `tests/_mcp_harness.py`, find `as_envelope`. The list branch currently is:

```python
    if isinstance(value, list):
        return [as_envelope(v) for v in value]
```

That's actually correct — it recurses. The issue must be elsewhere. Re-check: `as_envelope` for a string at top level should call `_placeholder_for_id`. Let me check what happens to a bare string:

If `as_envelope` only handles dict/list at the top level and doesn't have a string-fallback, that's the bug. Add:

```python
def as_envelope(value):
    if isinstance(value, dict):
        # ... existing dict logic ...
    if isinstance(value, list):
        return [as_envelope(v) for v in value]
    if isinstance(value, str):
        return _placeholder_for_id(value)
    return value
```

If a `str` branch already exists, the test should pass — re-read `as_envelope` and confirm. If it doesn't, add it. Either way verify the test passes after.

- [ ] **Step 4: Run test, verify pass**

Run: `uv run pytest tests/test_mcp_harness.py::test_as_envelope_masks_id_shaped_strings_inside_lists -v`
Expected: PASS.

- [ ] **Step 5: Run full suite + replay baselines**

Run: `uv run pytest tests/ --tb=no 2>&1 | tail -3`
Expected: all pass. If any baselines drift (unlikely — no current tool returns id lists), re-snap.

- [ ] **Step 6: Commit**

```
git add tests/_mcp_harness.py
git commit -m "test(mcp): as_envelope masks id-shaped strings in lists

Caught by retrospective review of PR #27. The list-of-strings
case bypassed _placeholder_for_id because the recursion's str
branch was elided at the top level."
```

---

## Task 9: Cursor stability under timestamp ties

**Files:**
- Test: `tests/test_audit_pagination.py` (append).

**Issue:** Keyset pagination on `(timestamp, id) DESC` is correct because SQLite supports row-tuple comparison lexicographically — but **no test pins this**. A future migration that changes column order or a "simplified" comparison would silently degrade pagination by skipping or duplicating rows. Defensive test only — no code change.

- [ ] **Step 1: Write the test**

Append to `tests/test_audit_pagination.py`:

```python
def test_list_pagination_stable_across_equal_updated_at(tmp_path):
    """Plan-C.9: keyset pagination must not skip or duplicate rows
    when multiple rows share the same updated_at. SQLite's row-tuple
    comparison handles this natively; this test pins the contract
    so a future query rewrite can't silently break it."""
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")

    # Publish 4 docs and force them to share an updated_at.
    ids = []
    for i in range(4):
        d = alice.call("markland_publish", content=f"# {i}")
        ids.append(d["id"])
    h.db.execute(
        "UPDATE documents SET updated_at = ? WHERE owner_id = ?",
        ("2026-05-01T12:00:00Z", alice.principal_id),
    )
    h.db.commit()

    # Walk the cursor with limit=2; collect all observed IDs.
    seen = []
    cursor = None
    while True:
        page = alice.call("markland_list", limit=2, cursor=cursor)
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        if len(seen) > 100:
            raise AssertionError(
                "pagination loop did not terminate — likely a cursor bug"
            )

    # No duplicates, no skips.
    assert sorted(seen) == sorted(ids), (
        f"pagination skipped or duplicated rows: seen={seen}, expected={ids}"
    )
```

- [ ] **Step 2: Run, verify pass**

Run: `uv run pytest tests/test_audit_pagination.py::test_list_pagination_stable_across_equal_updated_at -v`
Expected: PASS — locks the current contract.

- [ ] **Step 3: Commit**

```
git add tests/test_audit_pagination.py
git commit -m "test(mcp): pin cursor stability across equal timestamps

Defensive regression test for the keyset (timestamp, id) DESC
pagination contract. Caught by retrospective review of PR #33;
no code change today, but locks SQLite's row-tuple comparison
behavior so a future query refactor can't silently degrade it."
```

---

## Task 10: Final integration

- [ ] **Step 1: Run full suite**

Run: `uv run pytest tests/ --tb=no 2>&1 | tail -5`
Expected: all pass except the known flake.

- [ ] **Step 2: Verify canonical codes still hold**

Run: `grep -h '"code"' tests/fixtures/mcp_baseline/*.json | sort -u`
Expected: only the seven canonical codes.

- [ ] **Step 3: Verify env-var hygiene**

Run: `grep -n "os.environ.setdefault\|MARKLAND_RATE_LIMIT" tests/_mcp_harness.py | head`
Expected: env-vars set via `monkeypatch.setenv` (in fixture) plus the documented direct-construction fallback. No direct mutation in the fixture path.

- [ ] **Step 4: Verify cursor kwarg renamed**

Run: `grep -n "last_updated_at=" src/markland/service/`
Expected: zero hits (all callers now use `last_sort_key=`). Decode signature still accepts the wire field as `last_updated_at`.

---

## Self-review checklist

- [ ] `mcp_http` fixture threads `monkeypatch`; harness env is per-test, not session-wide.
- [ ] HTTP-mode anon raises `MCPHarnessError` (or task dropped because middleware handles cleanly).
- [ ] `encode_cursor`'s kwarg is `last_sort_key`; legacy `last_updated_at` still works for compat.
- [ ] `set_status` shim rejects `status=None`.
- [ ] `clear_status` shim returns legacy `{ok: true}` shape until Phase B.
- [ ] `doc_envelope(strict=True)` raises on missing fields.
- [ ] `_VOLATILE_FIELDS` no longer blanket-masks `id`.
- [ ] `as_envelope` recurses into list-of-strings via `_placeholder_for_id`.
- [ ] Cursor stability across equal timestamps pinned by Layer C test.
- [ ] Full suite green.
