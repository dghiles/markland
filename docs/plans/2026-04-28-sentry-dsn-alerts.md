# Sentry DSN + Alert Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision a Sentry project, set the `SENTRY_DSN` Fly secret, verify the conditional-init log line on deploy, wire the three Phase-0 alerts (5xx spike, `ConflictError` spike, `EmailSendError` spike), and smoke-test alert delivery via a deliberate transient error.

**Architecture:** Sentry init is already conditional on `config.sentry_dsn` at `src/markland/run_app.py:47-58`. This plan is mostly ops (Sentry dashboard config + Fly secret) with a small TDD addendum: an `exception.type` regression test ensuring `ConflictError` and `EmailSendError` propagate to Sentry with the correct fully-qualified class name (so the alert filters in `docs/runbooks/sentry-setup.md` match). No source code edits to error classes are required, but a smoke-test route is added temporarily then removed.

**Tech Stack:** `sentry-sdk` (Python), Fly.io secrets, Sentry alert rules, `pytest`/`uv`.

---

## File Structure

- Modify (temporary, reverted at end): `src/markland/web/app.py` — add a `/__sentry_smoke` route that raises a `RuntimeError` for smoke-test only, then revert.
- Create: `tests/test_sentry_error_capture.py` — verifies `ConflictError` and `EmailSendError` are seen by `sentry_sdk` with their unqualified class names (which Sentry indexes as `exception.type`).
- Read-only references:
  - `src/markland/run_app.py:47-58` — Sentry-conditional init.
  - `src/markland/config.py:18,42` — `sentry_dsn` config field.
  - `src/markland/service/docs.py:19` — `class ConflictError(Exception)`.
  - `src/markland/service/email.py:13` — `class EmailSendError(RuntimeError)`.
  - `docs/runbooks/sentry-setup.md` — alert specs (5xx, ConflictError, EmailSendError).
  - `tests/test_sentry_init.py` — pattern for reloading `markland.run_app` with patched `sentry_sdk.init`.
  - `tests/test_config.py` — config loading reference.

---

## Task 1: Provision the Sentry project and capture the DSN

**Files:** none (Sentry dashboard work).

- [ ] **Step 1: Check whether a Markland Sentry project already exists**

Run: `open https://sentry.io/organizations/<your-org>/projects/`
Expected: visually confirm whether `markland` project exists.
- If it exists, use that project. Skip to Step 3.
- If it does not exist, proceed to Step 2.

- [ ] **Step 2: Create a new Sentry project named `markland`**

In the Sentry dashboard:
1. Projects -> Create Project.
2. Platform: `Python`.
3. Project name: `markland`.
4. Team: default team.
5. Alert frequency: "Alert me on every new issue" (we will refine via explicit alert rules in Tasks 4-6).

Expected: project created, redirected to onboarding page that shows a DSN like `https://<key>@o<orgid>.ingest.us.sentry.io/<projid>`.

- [ ] **Step 3: Capture the DSN**

In Sentry: Project Settings -> Client Keys (DSN) -> copy the DSN string.
Expected: a string of the form `https://<32-hex-key>@o<digits>.ingest.<region>.sentry.io/<digits>`.
Store it in your password manager under `markland / SENTRY_DSN`. Do NOT paste it into any file in the repo.

- [ ] **Step 4: Capture which project was used (existing vs. new)**

Append a single line to your launch journal (or commit message in Task 3) noting:
- `Sentry project: <existing|new> — slug=<slug>, region=<us|eu>`.

This satisfies the scope requirement to "call out which" project was used. No git commit yet — this metadata rides on the Task 3 verification commit.

---

## Task 2: Set `SENTRY_DSN` as a Fly secret

**Files:** none (Fly.io ops).

- [ ] **Step 1: Confirm current Fly secret state (before)**

Run: `flyctl secrets list -a markland`
Expected: a table of secret names. `SENTRY_DSN` may or may not appear. Capture the output.

- [ ] **Step 2: Set the secret**

Run (substituting the DSN captured in Task 1, Step 3):
```
flyctl secrets set SENTRY_DSN='https://<key>@o<orgid>.ingest.us.sentry.io/<projid>' -a markland
```
Expected: Fly prints `Secrets are staged for the next deployment` followed by `Updating existing machines...` and a redeploy progress line. The app will restart automatically.

- [ ] **Step 3: Confirm the secret is set (after)**

Run: `flyctl secrets list -a markland`
Expected: `SENTRY_DSN` row present, with a recent `CREATED AT` / `DIGEST` timestamp. The value itself is never displayed — only the digest.

- [ ] **Step 4: No commit (ops-only)**

This task changes Fly state, not the repo. Capture the `flyctl secrets list` output (with the digest, not the value) into the verification log used in Task 7.

---

## Task 3: Verify `Sentry initialized` log line on the new deploy

**Files:** none (log inspection).

- [ ] **Step 1: Stream Fly logs**

Run: `flyctl logs -a markland | head -200`
Expected: at least one machine restart since Task 2. Look for the JSON log line emitted by `src/markland/run_app.py:56`:
```json
{"level":"INFO","logger":"markland.app","msg":"Sentry initialized","ts":"<recent ISO timestamp>"}
```

- [ ] **Step 2: Confirm no fallback warning is present**

In the same log window, confirm there is NO line of the form:
```json
{"level":"WARNING","logger":"markland.app","msg":"SENTRY_DSN set but sentry-sdk not installed; skipping",...}
```
Expected: absent. If present, `sentry-sdk` is missing from the deployed image — file a separate bug; do not proceed.

- [ ] **Step 3: Confirm the SDK does not log init errors**

Run: `flyctl logs -a markland | grep -i sentry | head -40`
Expected: only the `Sentry initialized` line (and possibly Sentry's own startup INFO line `[sentry] DEBUG: Setting up integrations`). No `ERROR` or `Traceback` entries mentioning `sentry`.

- [ ] **Step 4: Capture verification artifact**

Save the `Sentry initialized` log line (with timestamp) to your launch journal. No git commit — verification only.

---

## Task 4: Wire Alert 1 — 5xx spike

**Files:** none (Sentry dashboard).

- [ ] **Step 1: Open the alert builder**

Sentry -> Alerts -> Create Alert -> Issues.

- [ ] **Step 2: Configure the alert exactly per `docs/runbooks/sentry-setup.md` Alert 1**

- Name: `Markland 5xx spike`
- Environment filter: `production`
- Conditions (all of the following, AND'd):
  - `event.type:error`
  - `level:error OR level:fatal`
  - `http.status_code:[500 TO 599]`
- Threshold: "more than 5 events in 5 minutes".
- Action: Send email to `daveyhiles@gmail.com`. (Skip Slack — not wired at Phase 0.)

- [ ] **Step 3: Save and confirm**

Click Save Rule. Expected: alert appears in Alerts -> Rules with state `Active`.

- [ ] **Step 4: No commit (dashboard config)**

Screenshot or copy the rule URL into the launch journal.

---

## Task 5: Wire Alert 2 — `ConflictError` spike

**Files:** none (Sentry dashboard).

- [ ] **Step 1: Open the alert builder**

Sentry -> Alerts -> Create Alert -> Issues.

- [ ] **Step 2: Configure the alert exactly per `docs/runbooks/sentry-setup.md` Alert 2**

- Name: `Markland ConflictError spike`
- Conditions:
  - `exception.type:ConflictError` (this matches `markland.service.docs.ConflictError` — Sentry indexes by the unqualified class name).
- Threshold: "more than 20 events in 10 minutes".
- Action: Email `daveyhiles@gmail.com` only (no paging).

- [ ] **Step 3: Save and confirm**

Click Save Rule. Expected: rule listed as Active.

- [ ] **Step 4: No commit (dashboard config)**

---

## Task 6: Wire Alert 3 — `EmailSendError` spike

**Files:** none (Sentry dashboard).

- [ ] **Step 1: Open the alert builder**

Sentry -> Alerts -> Create Alert -> Issues.

- [ ] **Step 2: Configure the alert exactly per `docs/runbooks/sentry-setup.md` Alert 3**

- Name: `Markland email send failures`
- Conditions:
  - `exception.type:EmailSendError` (matches `markland.service.email.EmailSendError`).
- Threshold: "more than 3 events in 5 minutes".
- Action: Email `daveyhiles@gmail.com`.

- [ ] **Step 3: Save and confirm**

Click Save Rule. Expected: rule listed as Active.

- [ ] **Step 4: No commit (dashboard config)**

---

## Task 7: TDD — regression test for `exception.type` matching the alert filters

The alerts in Tasks 5 and 6 filter by `exception.type:ConflictError` / `exception.type:EmailSendError`. If a future refactor renames either class, Sentry's `exception.type` index changes silently and the alerts go quiet. This task locks the class names with a unit test.

**Files:**
- Create: `tests/test_sentry_error_capture.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_sentry_error_capture.py`:
```python
"""Sentry alert filters (`exception.type:ConflictError`, `exception.type:EmailSendError`)
match the unqualified class names. If anyone renames these classes, the alerts
configured per docs/runbooks/sentry-setup.md will silently stop firing — this
test catches that.
"""

from markland.service.docs import ConflictError
from markland.service.email import EmailSendError


def test_conflict_error_class_name_matches_sentry_alert_filter():
    assert ConflictError.__name__ == "ConflictError"


def test_email_send_error_class_name_matches_sentry_alert_filter():
    assert EmailSendError.__name__ == "EmailSendError"


def test_conflict_error_is_raisable_exception():
    try:
        raise ConflictError("test")
    except ConflictError as exc:
        assert type(exc).__name__ == "ConflictError"


def test_email_send_error_is_raisable_exception():
    try:
        raise EmailSendError("test")
    except EmailSendError as exc:
        assert type(exc).__name__ == "EmailSendError"
```

- [ ] **Step 2: Run the test to verify it passes immediately (no production code change needed)**

Run: `uv run pytest tests/test_sentry_error_capture.py -q`
Expected: `4 passed`. (All four assertions hold against the current code at `src/markland/service/docs.py:19` and `src/markland/service/email.py:13`.)

If any test fails: do NOT rename the classes to make it pass. Instead, the failure means someone has already renamed a class and the runbook's alert filter is stale — update both the class name in the source and the runbook's `exception.type:` filter together, then re-run.

- [ ] **Step 3: Run the full test suite to confirm no regressions**

Run: `uv run pytest tests/ -q`
Expected: full green; new tests included.

- [ ] **Step 4: Commit**

```
git add tests/test_sentry_error_capture.py
git commit -m "test(sentry): lock ConflictError/EmailSendError class names against alert filters"
```

---

## Task 8: Smoke-test — temporarily add `/__sentry_smoke`, deploy, trigger, verify alert path

This task verifies end-to-end that an exception raised inside the live Fly app reaches Sentry. We add a single transient route that raises a unique error, deploy, hit it, observe the issue in Sentry, then revert.

**Files:**
- Modify (temporary): `src/markland/web/app.py` — add a `/__sentry_smoke` route handler that raises `RuntimeError("sentry smoke test")`.

- [ ] **Step 1: Locate the route registration block in `src/markland/web/app.py`**

Run: `grep -n "Route(" src/markland/web/app.py | head -20`
Expected: a list of existing `Route("/...")` lines. Pick the routes list inside `create_app(...)` — typically near the bottom of the function.

- [ ] **Step 2: Add the smoke route handler**

In `src/markland/web/app.py`, immediately above the routes list inside `create_app`, add:
```python
async def _sentry_smoke(request):  # type: ignore[no-untyped-def]
    """TEMPORARY: deliberate 500 to verify Sentry capture; remove after verification."""
    raise RuntimeError("sentry smoke test 2026-04-28")
```
And add to the routes list:
```python
Route("/__sentry_smoke", _sentry_smoke, methods=["GET"]),
```

- [ ] **Step 3: Run the local test suite to confirm nothing else broke**

Run: `uv run pytest tests/ -q`
Expected: full green.

- [ ] **Step 4: Commit and deploy**

```
git add src/markland/web/app.py
git commit -m "chore(sentry): TEMP /__sentry_smoke route for alert verification"
flyctl deploy -a markland
```
Expected: deploy completes; `flyctl logs -a markland` shows `Sentry initialized` again on the new machine.

- [ ] **Step 5: Trigger the error**

Run: `curl -i https://<markland-prod-host>/__sentry_smoke`
Expected: HTTP 500 response. The `RuntimeError("sentry smoke test 2026-04-28")` is raised inside the request handler.

- [ ] **Step 6: Verify the issue appears in Sentry within ~30 seconds**

Open Sentry -> Issues. Expected: a new issue titled approximately `RuntimeError: sentry smoke test 2026-04-28` with `environment: production`, http status 500, and a Python stack trace pointing to `src/markland/web/app.py`.

- [ ] **Step 7: Verify the 5xx alert fires (after 5 events)**

The 5xx alert threshold is "more than 5 events in 5 minutes". Trigger the route 6 times in quick succession:
```
for i in 1 2 3 4 5 6; do curl -s -o /dev/null -w "%{http_code}\n" https://<markland-prod-host>/__sentry_smoke; done
```
Expected: six `500` lines. Within 1-2 minutes, an email arrives at `daveyhiles@gmail.com` from Sentry with subject containing `Markland 5xx spike`.

If the email does not arrive within 5 minutes:
- Check Sentry -> Alerts -> Rules -> `Markland 5xx spike` -> History — should show a recent firing.
- If the rule fired but no email: check Sentry's email notification settings for the project (Settings -> Notifications -> Issue Alerts).
- If the rule did not fire: re-check the conditions in Task 4 against the actual Sentry issue's tags (`http.status_code` may be missing — Sentry's Python SDK only tags it when the error originates from an HTTP integration; if absent, drop the `http.status_code:[500 TO 599]` clause and rely on `level:error`).

- [ ] **Step 8: Revert the smoke route**

Remove both the `_sentry_smoke` handler and its `Route(...)` line from `src/markland/web/app.py`.

Run: `uv run pytest tests/ -q`
Expected: full green.

- [ ] **Step 9: Commit and redeploy**

```
git add src/markland/web/app.py
git commit -m "chore(sentry): remove TEMP /__sentry_smoke route after verification"
flyctl deploy -a markland
```

- [ ] **Step 10: Final sanity — confirm the route is gone**

Run: `curl -i https://<markland-prod-host>/__sentry_smoke`
Expected: HTTP 404. The smoke route is no longer reachable.

- [ ] **Step 11: Resolve the smoke-test issue in Sentry**

Sentry -> Issues -> the `RuntimeError: sentry smoke test 2026-04-28` issue -> Resolve. Expected: issue moves to the Resolved tab. This prevents the alert from re-firing on the existing issue if Sentry's grouping ever re-opens it.

---

## Self-Review

**Spec coverage:**
- (a) Sentry project provisioned/identified — Task 1.
- (b) `flyctl secrets set SENTRY_DSN=...` — Task 2.
- (c) Verify `Sentry initialized` log line — Task 3.
- (d) Wire 5xx, ConflictError, EmailSendError alerts — Tasks 4, 5, 6.
- (e) Smoke-test deliberate error — Task 8.
- Test mirroring (`tests/test_sentry_init.py`, `tests/test_config.py`) — Task 7 adds a parallel `tests/test_sentry_error_capture.py`.

**Placeholder scan:** No `TBD`, `TODO`, or "implement later" entries. Each ops step has a command + expected output; the one code task (Task 7) is full TDD with the complete test file inline; Task 8's temporary route shows exact code.

**Type consistency:** Class names `ConflictError` (from `markland.service.docs`) and `EmailSendError` (from `markland.service.email`) are referenced consistently. The Fly app name is `markland` throughout. The DSN env var is `SENTRY_DSN` (matching `src/markland/config.py:42`) throughout.
