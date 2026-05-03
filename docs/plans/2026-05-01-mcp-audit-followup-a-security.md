# MCP Audit Follow-up A — Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two enumeration oracles in `markland_revoke` and `markland_revoke_invite` that the retrospective review surfaced, and explicitly settle the §12.5 deny-as-NotFound deviation in `markland_doc_meta`.

**Architecture:** Two of the three issues are ordering bugs — checks run in the wrong sequence and leak existence via `kind: ok` vs `kind: error`. Fix is mechanical: do owner-check before existence-lookup and normalize success-shape so it doesn't echo input. Third issue is a deliberate spec deviation that we'll align with §12.5 by switching the admin-gate to deny-as-NotFound.

**Tech Stack:** Python 3.12, no new dependencies.

**Source of issues:** Retrospective review of merged PR #36 (Plan 5 — axis 4+8 — granularity + idempotency).

**Spec reference:** `docs/specs/2026-04-27-mcp-audit-design.md` §8.4, §8.8, §12.5.

---

## File Structure

**Modified files:**
- `src/markland/server.py` — `_revoke`, `_revoke_invite`, `_doc_meta` ordering fixes.
- `tests/test_audit_idempotency.py` — extend with negative-oracle tests.
- `tests/fixtures/mcp_baseline/markland_revoke.json` — re-snap if response shape changes.
- `tests/fixtures/mcp_baseline/markland_revoke_invite.json` — re-snap if response shape changes.
- `tests/fixtures/mcp_baseline/markland_doc_meta.json` — re-snap for non-admin featured-flip path.

**New files:** none.

---

## Pre-flight checks

- [ ] **Verify the working tree is clean and on a fresh worktree off origin/main**

Run:
```
git status -sb
git log --oneline -3
```
Expected: branch tracks `origin/main`; HEAD is the latest main commit (post-PR-#39, banner coverage). If you're on the wrong branch, stop and create a new worktree.

- [ ] **Verify Plan 6's harness + tests pass on this worktree**

Run: `uv run pytest tests/test_audit_*.py tests/test_mcp_baseline.py --tb=no -q 2>&1 | tail -3`
Expected: ~140 tests pass cleanly. Anything red here is pre-existing — fix or stop.

- [ ] **Note the pre-fix snapshots so re-snap diffs make sense.**

Run:
```
grep -A4 '"unknown_target_invalid_argument"\|"existing_grant"' tests/fixtures/mcp_baseline/markland_revoke.json | head -20
grep -A4 '"not_found"\|"existing"' tests/fixtures/mcp_baseline/markland_revoke_invite.json | head -20
```
Expected: shapes today are `{revoked: False, doc_id, target}` (revoke, missing target) and `{revoked: True, invite_id}` (revoke_invite, missing). After the fix, the missing-target/missing-invite shapes change because we owner-check first; non-owners on missing rows now get `not_found` (not `ok`).

---

## Task 1: Fix `_revoke` email-target enumeration oracle

**Files:**
- Modify: `src/markland/server.py:341-368` (`_revoke` function body).
- Test: `tests/test_audit_idempotency.py` (append).

**Issue:** When `target` is an email and the user doesn't exist, `_revoke` returns `{revoked: False}` *before* running the owner-check on `doc_id`. A non-owner can pass any `doc_id` they have no access to and learn whether `target@example.com` is registered: unknown → `ok`, known → `forbidden`.

- [ ] **Step 1: Write the failing oracle test**

Append to `tests/test_audit_idempotency.py`:

```python
def test_revoke_does_not_leak_user_existence_to_non_owner(tmp_path):
    """Plan-A.1: a non-owner cannot use revoke to probe whether an email
    is registered. Both unknown-email and known-email cases on a doc the
    caller does not own must produce the same error shape."""
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    bob = h.as_user(email="bob@example.com")  # registered
    pub = alice.call("markland_publish", content="# alice's doc")

    # bob (non-owner) tries to revoke against alice's doc.
    # Both calls must surface the same error code — neither leaks
    # whether the target email is registered.
    r_unknown = bob.call_raw(
        "markland_revoke", doc_id=pub["id"], target="ghost@example.com"
    )
    r_known = bob.call_raw(
        "markland_revoke", doc_id=pub["id"], target="alice@example.com"
    )

    assert r_unknown.error_code == r_known.error_code, (
        f"existence oracle: unknown={r_unknown.error_code}, "
        f"known={r_known.error_code}"
    )
    # Both should be not_found per spec §12.5 deny-as-NotFound.
    r_unknown.assert_error("not_found")
    r_known.assert_error("not_found")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_audit_idempotency.py::test_revoke_does_not_leak_user_existence_to_non_owner -v`
Expected: FAIL — `r_unknown.error_code` is `None` (success, `revoked=False`); `r_known.error_code` is `not_found`.

- [ ] **Step 3: Reorder `_revoke` so owner-check runs first**

In `src/markland/server.py`, replace lines 341-368 with:

```python
    def _revoke(ctx, doc_id: str, target: str):
        p = _require_principal(ctx)

        # Owner check FIRST — non-owners must not be able to probe
        # arbitrary doc/target pairs to enumerate user existence.
        try:
            check_permission(db_conn, p, doc_id, "owner")
        except NotFound:
            raise tool_error("not_found")
        except PermissionDenied:
            raise tool_error("forbidden")

        pid = target.strip()
        if "@" in pid:
            row = db_conn.execute(
                "SELECT id FROM users WHERE lower(email) = lower(?)", (pid,)
            ).fetchone()
            if row is None:
                # Idempotent: target email is not a user → no-op success.
                # Owner-only path, so this does not leak user existence.
                return {"revoked": False, "doc_id": doc_id}
            pid = row[0]

        try:
            result = grants_svc.revoke(
                db_conn, principal=p, doc_id=doc_id, principal_id=pid,
            )
        except NotFound:
            # Grant didn't exist on this owner-readable doc. Idempotent.
            return {"revoked": False, "doc_id": doc_id}
        return result
```

> **Two changes:** (a) `check_permission` moved above the email lookup. (b) `target` is dropped from the no-op response — echoing it was harmless but unnecessary, and the owner-only path makes the response shape uniform regardless of whether the target was an email or a `usr_…` id.

- [ ] **Step 4: Run the new test to verify it passes**

Run: `uv run pytest tests/test_audit_idempotency.py::test_revoke_does_not_leak_user_existence_to_non_owner -v`
Expected: PASS.

- [ ] **Step 5: Run the existing idempotency tests + revoke baseline**

Run: `uv run pytest tests/test_audit_idempotency.py tests/test_mcp_baseline.py -k revoke --tb=short 2>&1 | tail -10`
Expected: most pass; `test_baseline_markland_revoke_unknown_target_invalid_argument` will likely shift because the response shape lost `target`. Re-snap in step 6.

- [ ] **Step 6: Re-snap the affected baseline**

Run: `uv run pytest tests/test_mcp_baseline.py -k "markland_revoke and not invite" --snapshot-update -q 2>&1 | tail -3`
Verify the diff:
```
git diff tests/fixtures/mcp_baseline/markland_revoke.json
```
Expected: scenario named for unknown-target now drops the `target` field; `existing_grant` and `non_owner_forbidden` unchanged.

- [ ] **Step 7: Re-run baseline replay (no `--snapshot-update`)**

Run: `uv run pytest tests/test_mcp_baseline.py -k "markland_revoke and not invite" -v 2>&1 | tail -3`
Expected: all PASS.

- [ ] **Step 8: Commit**

```
git add src/markland/server.py tests/test_audit_idempotency.py tests/fixtures/mcp_baseline/markland_revoke.json
git commit -m "fix(mcp): _revoke owner-check before email lookup (security)

Closes the user-existence enumeration oracle in markland_revoke
caught by the post-merge retrospective review of PR #36 (Plan 5).

Before this change, a non-owner calling markland_revoke against a
doc they couldn't see learned whether target@example.com was a
registered user: unknown → ok {revoked: False}, known → forbidden.
Now both paths return not_found (deny-as-NotFound per spec §12.5)."
```

---

## Task 2: Fix `_revoke_invite` invite-id enumeration oracle

**Files:**
- Modify: `src/markland/server.py:433-450` (`_revoke_invite` function body).
- Test: `tests/test_audit_idempotency.py` (append).

**Issue:** When `invite_id` doesn't exist, `_revoke_invite` returns `{revoked: True}` *before* any auth check. Existing-but-not-owner returns `forbidden`. Any authenticated user can probe arbitrary invite IDs to distinguish exists-vs-doesn't-exist.

- [ ] **Step 1: Write the failing oracle test**

Append to `tests/test_audit_idempotency.py`:

```python
def test_revoke_invite_does_not_leak_invite_existence_to_non_owner(tmp_path):
    """Plan-A.2: a non-owner cannot use revoke_invite to probe whether
    an invite_id exists. Both nonexistent-invite and existing-but-not-owner
    cases must surface the same error shape."""
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    bob = h.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# alice's doc")
    real_invite = alice.call(
        "markland_create_invite", doc_id=pub["id"], level="view"
    )
    real_invite_id = real_invite["invite_id"]

    # bob is authenticated but is not alice's collaborator.
    r_nonexistent = bob.call_raw(
        "markland_revoke_invite", invite_id="inv_does_not_exist_12345"
    )
    r_existing = bob.call_raw(
        "markland_revoke_invite", invite_id=real_invite_id
    )

    assert r_nonexistent.error_code == r_existing.error_code, (
        f"existence oracle: nonexistent={r_nonexistent.error_code}, "
        f"existing={r_existing.error_code}"
    )
    r_nonexistent.assert_error("not_found")
    r_existing.assert_error("not_found")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_audit_idempotency.py::test_revoke_invite_does_not_leak_invite_existence_to_non_owner -v`
Expected: FAIL — `r_nonexistent.error_code` is `None` (currently returns `ok {revoked: True}`); `r_existing.error_code` is `not_found`.

- [ ] **Step 3: Reorder `_revoke_invite` so existence-on-an-owned-doc is checked, not existence-anywhere**

In `src/markland/server.py`, replace lines 433-450 with:

```python
    def _revoke_invite(ctx, invite_id: str):
        p = _require_principal(ctx)
        # Look up the invite scoped to docs the caller owns. The
        # combined query closes the existence oracle: a non-owner gets
        # zero rows whether the invite is missing or belongs to someone
        # else, and an owner gets the row when it exists.
        row = db_conn.execute(
            """
            SELECT i.doc_id
              FROM invites i
              JOIN documents d ON d.id = i.doc_id
             WHERE i.id = ?
               AND d.owner_id = ?
            """,
            (invite_id, p.principal_id),
        ).fetchone()
        if row is None:
            # Either the invite doesn't exist OR it's on a doc the
            # caller doesn't own. Per §12.5 deny-as-NotFound, surface
            # the same shape regardless. The previous "idempotent
            # success on missing invite" semantics are preserved for
            # the owner — see test_revoke_invite_owner_idempotent_on_missing.
            #
            # If the invite genuinely belongs to the caller and is
            # already revoked, an extra check below restores the
            # idempotent-success contract for owners.
            owned = db_conn.execute(
                """
                SELECT 1 FROM documents WHERE owner_id = ? LIMIT 1
                """,
                (p.principal_id,),
            ).fetchone()
            # Owner-with-no-docs OR not-an-owner: both deny-as-NotFound.
            if owned is None:
                raise tool_error("not_found")
            # Caller owns at least one doc — they're "an owner". The
            # invite either doesn't exist anywhere or isn't theirs.
            # Treat as idempotent success ONLY when invite truly does
            # not exist. Otherwise (invite exists but not on caller's
            # doc) treat as not_found.
            exists_anywhere = db_conn.execute(
                "SELECT 1 FROM invites WHERE id = ? LIMIT 1",
                (invite_id,),
            ).fetchone()
            if exists_anywhere is None:
                return {"revoked": True, "invite_id": invite_id}
            raise tool_error("not_found")

        invites_svc.revoke_invite(
            db_conn, invite_id=invite_id, owner_user_id=p.principal_id
        )
        return {"revoked": True, "invite_id": invite_id}
```

> **Why two queries instead of one:** owner-with-zero-docs is a degenerate state (a fresh user who registered but never published) that should not be treated as "an owner" for idempotency purposes — they get not_found like everyone else. Owner-of-at-least-one-doc gets the idempotent-true contract because they could plausibly have created the invite themselves and revoked it. The cost is one extra `SELECT 1 LIMIT 1` per missing-invite call by a real owner — negligible.

- [ ] **Step 4: Run the new oracle test to verify it passes**

Run: `uv run pytest tests/test_audit_idempotency.py::test_revoke_invite_does_not_leak_invite_existence_to_non_owner -v`
Expected: PASS.

- [ ] **Step 5: Add the owner-idempotency regression test**

Append to `tests/test_audit_idempotency.py`:

```python
def test_revoke_invite_owner_idempotent_on_missing(tmp_path):
    """Plan-A.2: an owner who calls revoke_invite on a nonexistent
    invite_id still gets idempotent success — the security fix must
    not break this contract."""
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    alice.call("markland_publish", content="# alice owns this")  # makes alice "an owner"

    res = alice.call(
        "markland_revoke_invite", invite_id="inv_does_not_exist_67890"
    )
    assert res["revoked"] is True
    assert res["invite_id"] == "inv_does_not_exist_67890"
```

- [ ] **Step 6: Run all three tests + revoke_invite baseline**

Run: `uv run pytest tests/test_audit_idempotency.py -k revoke_invite tests/test_mcp_baseline.py -k revoke_invite --tb=short 2>&1 | tail -10`
Expected: oracle test PASS; owner-idempotent PASS; baseline `not_found` scenario likely needs a re-snap if today it asserts `kind: ok` for an alice-revoking-nonexistent-invite but the tester is now bob.

- [ ] **Step 7: Re-snap the affected baseline if drifted**

Run:
```
uv run pytest tests/test_mcp_baseline.py -k "markland_revoke_invite" --snapshot-update -q 2>&1 | tail -3
git diff tests/fixtures/mcp_baseline/markland_revoke_invite.json
```
Expected diff: `non_owner_forbidden` scenario unchanged (still `not_found`); `not_found` scenario (the alice-with-bogus-id case) — verify it remained `kind: ok` because alice is an owner. If that scenario's setup uses a fresh user without docs, it'll flip to `not_found` — that's the new contract. Either way commit the diff if intentional.

Run: `uv run pytest tests/test_mcp_baseline.py -k "markland_revoke_invite" -v 2>&1 | tail -3`
Expected: all PASS.

- [ ] **Step 8: Commit**

```
git add src/markland/server.py tests/test_audit_idempotency.py tests/fixtures/mcp_baseline/markland_revoke_invite.json
git commit -m "fix(mcp): _revoke_invite scopes existence check to owned docs (security)

Closes the invite-id enumeration oracle in markland_revoke_invite
caught by the post-merge retrospective review of PR #36 (Plan 5).

Before this change, an authenticated non-owner could pass arbitrary
invite IDs and distinguish nonexistent (ok {revoked: True}) from
existing-but-not-owned (forbidden).

Now the existence query is scoped via JOIN to docs the caller owns;
non-owners get not_found regardless of whether the invite exists.
Owner idempotent-success on truly-missing invites is preserved."
```

---

## Task 3: Align `_doc_meta` admin-gate with §12.5 deny-as-NotFound

**Files:**
- Modify: `src/markland/server.py:241-280` (`_doc_meta` body).
- Test: `tests/test_audit_idempotency.py` (append).
- Snapshot: `tests/fixtures/mcp_baseline/markland_doc_meta.json` (re-snap).

**Issue:** Today `_doc_meta` does `if featured is not None and not p.is_admin: raise tool_error("forbidden")` *before* the doc lookup. A non-admin caller passing any `doc_id` (including one that doesn't exist or that they have no view permission for) gets `forbidden`. This deviates from §12.5 deny-as-NotFound. Two retrospective reviewers flagged this; the right fix is to align with §12.5 since `markland_feature` (the predecessor) is being deprecated anyway.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_idempotency.py`:

```python
def test_doc_meta_non_admin_featured_on_invisible_doc_is_not_found(tmp_path):
    """Plan-A.3: per §12.5, a non-admin attempting to set `featured`
    on a doc they cannot see surfaces as not_found — same shape as for
    a doc that does not exist. Today the admin-gate fires first and
    surfaces forbidden, leaking nothing per se but breaking the §12.5
    invariant the rest of the surface honors."""
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    bob = h.as_user(email="bob@example.com")
    private = alice.call("markland_publish", content="# private", public=False)

    # bob (non-admin, cannot see private) attempts to feature it.
    r = bob.call_raw("markland_doc_meta", doc_id=private["id"], featured=True)
    r.assert_error("not_found")  # NOT forbidden

    # And same for a doc that just doesn't exist.
    r2 = bob.call_raw("markland_doc_meta", doc_id="nonexistent00000000", featured=True)
    r2.assert_error("not_found")
```

- [ ] **Step 2: Run, verify it fails**

Run: `uv run pytest tests/test_audit_idempotency.py::test_doc_meta_non_admin_featured_on_invisible_doc_is_not_found -v`
Expected: FAIL — both calls currently return `forbidden`.

- [ ] **Step 3: Move the admin-gate after the doc-visibility check**

In `src/markland/server.py`, replace `_doc_meta`'s body (lines 241-280) with:

```python
    def _doc_meta(
        ctx,
        doc_id: str,
        public: bool | None = None,
        featured: bool | None = None,
    ):
        from markland import db as db_module

        p = _require_principal(ctx)

        # Visibility gate first: callers who can't see the doc get
        # not_found regardless of which flag they were trying to set.
        # This honors §12.5 deny-as-NotFound across the whole tool.
        try:
            check_permission(db_conn, p, doc_id, "view")
        except NotFound:
            raise tool_error("not_found")
        except PermissionDenied:
            raise tool_error("not_found")  # deny-as-NotFound

        # Now the admin gate. We've already established that the
        # caller can see the doc; surfacing forbidden here is the
        # correct shape because non-admins legitimately cannot
        # change the featured flag on docs they CAN see.
        if featured is not None and not p.is_admin:
            raise tool_error("forbidden")

        # Load current state to skip no-op writes (idempotency).
        current = db_module.get_document(db_conn, doc_id)

        if public is not None and (current is None or current.is_public != public):
            try:
                docs_svc.set_visibility(db_conn, base_url, p, doc_id, public)
            except NotFound:
                raise tool_error("not_found")
            except PermissionDenied:
                raise tool_error("forbidden")

        if featured is not None and (current is None or current.is_featured != featured):
            try:
                docs_svc.feature(db_conn, p, doc_id, featured)
            except NotFound:
                raise tool_error("not_found")

        # Return the freshly-loaded doc as a doc_envelope.
        doc = db_module.get_document(db_conn, doc_id)
        if doc is None:
            raise tool_error("not_found")
        body = docs_svc.get(db_conn, p, doc_id, base_url=base_url)
        return doc_envelope(body)
```

> **The key reorder:** `check_permission(..., "view")` is now line one. Both `NotFound` and `PermissionDenied` map to `tool_error("not_found")` — that's the deny-as-NotFound contract. The admin gate now only fires after the caller has proven they can see the doc, so `forbidden` is the correct shape (the caller is a real, view-permitted user who lacks the admin role). The redundant `current is None` checks remain because `get_document` doesn't itself permission-check (it's a low-level DB read).

- [ ] **Step 4: Run the new test, verify pass**

Run: `uv run pytest tests/test_audit_idempotency.py::test_doc_meta_non_admin_featured_on_invisible_doc_is_not_found -v`
Expected: PASS.

- [ ] **Step 5: Run all granularity + baseline tests**

Run: `uv run pytest tests/test_audit_granularity.py tests/test_mcp_baseline.py -k doc_meta --tb=short 2>&1 | tail -10`
Expected: most pass. The granularity test `test_doc_meta_set_featured_admin_only` calls `alice.call_raw(...)` on alice's *own* doc — she has view permission, so the admin-gate still fires and returns `forbidden`. That test should still pass. The baseline scenarios may need re-snap if any of them used a non-admin against a doc they can't see.

- [ ] **Step 6: Re-snap if drifted**

Run:
```
uv run pytest tests/test_mcp_baseline.py -k doc_meta --snapshot-update -q 2>&1 | tail -3
git diff tests/fixtures/mcp_baseline/markland_doc_meta.json
```
Expected: probably no diff (existing baselines test owner-on-own-doc paths). If a diff appears, eyeball it — only `forbidden` → `not_found` flips for invisible-doc scenarios are intended.

- [ ] **Step 7: Confirm replay**

Run: `uv run pytest tests/test_mcp_baseline.py -k doc_meta -v 2>&1 | tail -3`
Expected: PASS.

- [ ] **Step 8: Commit**

```
git add src/markland/server.py tests/test_audit_idempotency.py tests/fixtures/mcp_baseline/markland_doc_meta.json
git commit -m "fix(mcp): _doc_meta visibility-check before admin-gate (§12.5 alignment)

Aligns markland_doc_meta with the deny-as-NotFound contract used
across the rest of the surface. Caught by retrospective review of
PR #36 (Plan 5).

Before: non-admin sees forbidden regardless of doc visibility.
After: non-admin on invisible doc sees not_found (matching
markland_get, markland_share, etc); non-admin on visible doc with
featured=... still sees forbidden (correct: caller is a real
authenticated user lacking the admin role)."
```

---

## Task 4: Final integration run

- [ ] **Step 1: Run the full suite**

Run: `uv run pytest tests/ --tb=no 2>&1 | tail -5`
Expected: all pass except the known-pre-existing flake `test_pending_intent.py::test_read_rejects_tampered_token`. Test count should be ~2-3 higher than before this plan (3 new oracle/regression tests).

- [ ] **Step 2: Verify the canonical-codes invariant still holds**

Run: `grep -h '"code"' tests/fixtures/mcp_baseline/*.json | sort -u`
Expected: only `unauthenticated`, `forbidden`, `not_found`, `conflict`, `invalid_argument`, `rate_limited`, `internal_error`. Anything else is a regression.

- [ ] **Step 3: Verify the idempotency catalog still classifies all tools**

Run: `uv run pytest tests/test_audit_idempotency.py::test_idempotency_catalog_covers_all_current_tools -v`
Expected: PASS.

---

## Self-review checklist

- [ ] `_revoke` owner-checks before the email lookup; non-owners get the same error shape regardless of whether `target` is registered.
- [ ] `_revoke_invite` scopes the existence query to docs the caller owns; non-owners can't probe invite-id existence.
- [ ] `_doc_meta` view-checks before the admin-gate; non-admins on invisible docs get `not_found`.
- [ ] All three new Layer C tests pin the contracts.
- [ ] Baselines updated; canonical codes still hold; idempotency catalog still complete.
- [ ] Full suite green (modulo pre-existing flake).
