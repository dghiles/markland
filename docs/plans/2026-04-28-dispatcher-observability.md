# Dispatcher Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the in-process EmailDispatcher exhausts retries, the operator must learn about it. Today the failure is buried in a `WARNING` log line in `flyctl logs`; Sentry never sees it because `_process()` swallows the `EmailSendError`. This plan: (1) classifies Resend errors as transient vs permanent so sandbox-rejection emails fail fast (1 attempt) instead of burning the 4-attempt budget; (2) calls `sentry_sdk.capture_exception` on final drop with template/attempt/failure-kind tags (no PII); (3) attaches structured fields (`template`, `attempts`, `error_class`, `failure_kind`) to the existing drop-warning so Fly log search keys off field names instead of regexing the message; (4) tweaks the magic-link "Check your email" page to set realistic expectations.

**Context:** While debugging an invite-flow UX bug (PR #17, merged 2026-04-28), we observed in production that Resend rejected sends to `hello@ericpaulsen.io` with the sandbox-mode error: *"You can only send testing emails to your own email address (daveyhiles@gmail.com)."* The dispatcher retried 4× with backoff, then dropped the email with a `WARNING` log line — and the user-facing handler returned `200 OK` "Check your email" before any of that ran (correctly: dispatch is async). Net result: the operator had **no Sentry alert**, **no metric**, and the only signal was a buried log line in `flyctl logs`. The runbook at `docs/runbooks/sentry-setup.md` *expects* a Sentry "≥3 EmailSendError in 5 min" alert, but Sentry auto-capture only sees exceptions that bubble out of request handlers — and the dispatcher swallows them all in its retry loop. This plan closes that gap with explicit `capture_exception` calls at the drop site, adds a permanent-vs-transient classifier so we don't waste retry budget on errors that will never succeed, and sets honest user-facing expectations.

**Architecture:** All dispatcher changes are localized to `src/markland/service/email_dispatcher.py`. No queue/worker shape changes. Sentry import stays soft (`try: import sentry_sdk / except ImportError: return`) to mirror `run_app.py:47–58` — we never want a Sentry transport problem to take down the dispatcher worker. A new module-level `_classify(exc)` helper inspects `EmailSendError` message text for known permanent-failure signatures (Resend sandbox rejection, validation errors); permanent failures short-circuit the retry ladder by drop-on-attempt-1. Recipient identity is hashed (sha256, first 12 hex) — never the raw address — for tag values. The drop-warning gains `extra={"action": {...}}`, which the existing `JsonFormatter._STRUCTURED` allow-list already promotes to a top-level JSON field (verified: `run_app.py:23` already lists `"action"`). The user-facing copy change is a single Jinja line edit.

**Tech Stack:** Python 3.12, stdlib `hashlib`, `sentry-sdk>=2.15.0` (already a main dep, init optional), pytest + pytest-asyncio, `caplog`, `monkeypatch`.

**Scope excluded:**
- Verifying a Resend domain in production (ops/Fly env work — not a code task).
- Rewriting the dispatcher to async-await Sentry transport, or batching captures.
- Adding StatsD / OTel metric exporters.
- Refactoring `EmailClient` to attach typed error subclasses (kept for future cleanup; classifier is message-based for now).
- Synchronous email send on the magic-link route (intentionally rejected — couples HTTP latency to Resend).

---

## File Structure

**New files:** none.

**Modified files:**
- `/Users/daveyhiles/Developer/markland/src/markland/service/email_dispatcher.py` — add `_classify`, `_recipient_hash`, `_safe_sentry_capture`; modify `_process` to short-circuit permanent failures and emit structured drop log + Sentry capture.
- `/Users/daveyhiles/Developer/markland/src/markland/web/templates/magic_link_sent.html` — single-line tweak to the `.note` paragraph for honest expectation-setting.
- `/Users/daveyhiles/Developer/markland/tests/test_email_dispatcher.py` — three new tests (classifier short-circuit, Sentry capture call, structured log fields).
- `/Users/daveyhiles/Developer/markland/tests/test_auth_routes.py` — one new test asserting the rendered magic-link-sent body.

**Verification-only (no edit expected):**
- `/Users/daveyhiles/Developer/markland/src/markland/run_app.py:23` — `_STRUCTURED` tuple already contains `"action"`. Confirmed before plan was written. Edit only if branch divergence at execution time has removed it.

---

## Task 1: Permanent-vs-transient classifier (TDD)

**Files:**
- Modify: `src/markland/service/email_dispatcher.py`
- Test: `tests/test_email_dispatcher.py`

Goal: a permanent failure drops on attempt 1, not attempt 4. Transient failures keep current behavior.

- [ ] **Step 1.1: Write the failing test**

Append to `/Users/daveyhiles/Developer/markland/tests/test_email_dispatcher.py`:

```python
@pytest.mark.asyncio
async def test_permanent_failure_drops_on_first_attempt(caplog):
    """Resend sandbox-mode rejection must not waste 4 retries."""
    import logging
    caplog.set_level(logging.WARNING, logger="markland.email_dispatcher")

    class _SandboxClient:
        def __init__(self):
            self.calls: list[dict] = []

        def send(self, **kwargs):
            self.calls.append(kwargs)
            raise EmailSendError(
                "You can only send testing emails to your own email address "
                "(daveyhiles@gmail.com). To send to other recipients, please "
                "verify a domain at resend.com/domains."
            )

    client = _SandboxClient()
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    try:
        disp.enqueue(
            to="stranger@example.com",
            subject="s",
            html="<p>h</p>",
            text="h",
            metadata={"template": "magic_link"},
        )
        await asyncio.sleep(0.1)
        await disp.drain()
    finally:
        await disp.stop()

    assert len(client.calls) == 1, f"expected 1 attempt, got {len(client.calls)}"
    assert any("dropping email" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 1.2: Run the test to verify it fails**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_email_dispatcher.py::test_permanent_failure_drops_on_first_attempt -x -v
```

**Expected:** `AssertionError: expected 1 attempt, got 4` (current code retries unconditionally).

- [ ] **Step 1.3: Implement `_classify` helper**

In `/Users/daveyhiles/Developer/markland/src/markland/service/email_dispatcher.py`, below the `DEFAULT_RETRY_DELAYS` constant (around line 30), add:

```python
# Permanent-failure signatures from Resend. Anything matching here drops
# on attempt 1 instead of burning the retry budget. Refine as we collect
# more rejection shapes — a single helper, message-based, intentionally simple.
_PERMANENT_SIGNATURES: tuple[str, ...] = (
    "you can only send testing emails",  # sandbox mode
    "validation_error",                  # 422 from Resend on bad payload
    "invalid `to` field",                # malformed address
)


def _classify(exc: EmailSendError) -> str:
    """Return 'permanent' or 'transient' for an EmailSendError.

    Permanent failures should not be retried (sandbox rejection, validation).
    Transient failures (5xx, network, rate-limit) get the full retry ladder.
    """
    msg = str(exc).lower()
    for sig in _PERMANENT_SIGNATURES:
        if sig in msg:
            return "permanent"
    return "transient"
```

- [ ] **Step 1.4: Wire the classifier into `_process`**

Replace the `except EmailSendError as exc:` branch in `_process` (currently lines ~140–157) with:

```python
        except EmailSendError as exc:
            failure_kind = _classify(exc)
            is_last_attempt = (
                failure_kind == "permanent"
                or item.attempt >= len(self._retry_delays)
            )
            if is_last_attempt:
                logger.warning(
                    "dropping email to %s after %d attempts: %s",
                    item.to, item.attempt + 1, exc,
                )
                return
            delay = self._retry_delays[item.attempt]
            jitter = delay * self._jitter_frac
            delay = delay + random.uniform(-jitter, jitter)
            delay = max(0.0, delay)
            logger.info(
                "email to %s failed (attempt %d); retrying in %.2fs: %s",
                item.to, item.attempt + 1, delay, exc,
            )
            item.attempt += 1
            asyncio.create_task(self._requeue_after(item, delay))
```

(If the existing branch already differs in retry/jitter wiring, **read the file first** and adapt — preserve the existing retry mechanics. The only behavioral change in this task is the `is_last_attempt` short-circuit.)

- [ ] **Step 1.5: Run the test to verify it passes**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_email_dispatcher.py -x -v
```

**Expected:** all dispatcher tests pass (5 pre-existing + the new permanent-failure test).

- [ ] **Step 1.6: Commit**

```bash
cd /Users/daveyhiles/Developer/markland && git add src/markland/service/email_dispatcher.py tests/test_email_dispatcher.py && git commit -m "$(cat <<'EOF'
classify resend errors as permanent vs transient

Sandbox-mode rejection ("You can only send testing emails…") and
validation errors now drop on first attempt instead of burning the full
4-attempt retry ladder. Network/5xx errors keep current behavior.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Sentry capture + structured drop log (TDD)

**Files:**
- Modify: `src/markland/service/email_dispatcher.py`
- Test: `tests/test_email_dispatcher.py`

Goal: the drop branch fires `sentry_sdk.capture_exception` with template/failure-kind tags (no PII), and the warning log carries structured fields the JSON formatter promotes to top-level JSON.

- [ ] **Step 2.1: Write the failing tests**

Append to `/Users/daveyhiles/Developer/markland/tests/test_email_dispatcher.py`:

```python
@pytest.mark.asyncio
async def test_drop_invokes_sentry_capture(monkeypatch):
    """Final drop must call sentry_sdk.capture_exception once with tags."""
    captured: list[dict] = []

    class _FakeSentry:
        @staticmethod
        def capture_exception(exc, **kwargs):
            captured.append({"exc": exc, "kwargs": kwargs})

        class Scope:
            def __init__(self):
                self.tags: dict[str, str] = {}

            def set_tag(self, k, v):
                self.tags[k] = v

        @staticmethod
        def push_scope():
            import contextlib

            @contextlib.contextmanager
            def _cm():
                scope = _FakeSentry.Scope()
                captured.append({"scope": scope})
                yield scope

            return _cm()

    import sys
    monkeypatch.setitem(sys.modules, "sentry_sdk", _FakeSentry)

    client = _FakeClient(fail_times=99)
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    try:
        disp.enqueue(
            to="a@b",
            subject="s",
            html="<p>h</p>",
            text="h",
            metadata={"template": "magic_link"},
        )
        for _ in range(80):
            await asyncio.sleep(0.02)
            if len(client.calls) >= 4:
                await asyncio.sleep(0.05)
                break
        await disp.drain()
    finally:
        await disp.stop()

    capture_calls = [c for c in captured if "exc" in c]
    scope_calls = [c["scope"] for c in captured if "scope" in c]
    assert len(capture_calls) == 1, f"expected 1 capture, got {len(capture_calls)}"
    assert isinstance(capture_calls[0]["exc"], EmailSendError)
    assert len(scope_calls) == 1
    tags = scope_calls[0].tags
    assert tags["template"] == "magic_link"
    assert tags["failure_kind"] == "transient"
    assert tags["attempts"] == "4"
    assert "recipient_hash" in tags
    # PII guard: raw recipient must not appear in any tag value.
    assert all("a@b" not in v for v in tags.values())


@pytest.mark.asyncio
async def test_drop_log_carries_structured_action_fields(caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="markland.email_dispatcher")

    client = _FakeClient(fail_times=99)
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    try:
        disp.enqueue(
            to="a@b",
            subject="s",
            html="<p>h</p>",
            text="h",
            metadata={"template": "user_grant"},
        )
        for _ in range(80):
            await asyncio.sleep(0.02)
            if len(client.calls) >= 4:
                await asyncio.sleep(0.05)
                break
        await disp.drain()
    finally:
        await disp.stop()

    drop_records = [r for r in caplog.records if "dropping email" in r.message.lower()]
    assert len(drop_records) == 1
    rec = drop_records[0]
    action = rec.__dict__.get("action")
    assert isinstance(action, dict), f"expected dict on record.action, got {type(action)}"
    assert action["template"] == "user_grant"
    assert action["attempts"] == 4
    assert action["error_class"] == "EmailSendError"
    assert action["failure_kind"] == "transient"
    assert "recipient_hash" in action
```

- [ ] **Step 2.2: Run the tests to verify they fail**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_email_dispatcher.py::test_drop_invokes_sentry_capture tests/test_email_dispatcher.py::test_drop_log_carries_structured_action_fields -x -v
```

**Expected:** both fail (no `capture_exception` call yet; `record.action` missing).

- [ ] **Step 2.3: Add `hashlib` import + `_recipient_hash` + `_safe_sentry_capture`**

In `/Users/daveyhiles/Developer/markland/src/markland/service/email_dispatcher.py`, add to the imports block (alongside `import random`):

```python
import hashlib
```

Below `_classify` (added in Task 1), add:

```python
def _recipient_hash(addr: str) -> str:
    """Stable, non-reversible 12-hex-char digest. Suitable for tag values.

    Lets ops correlate "same recipient seeing repeated drops" without leaking
    the raw address into Sentry. sha256 truncated; collisions on 12 hex chars
    are statistically irrelevant at our volume.
    """
    return hashlib.sha256(addr.encode("utf-8")).hexdigest()[:12]


def _safe_sentry_capture(
    exc: BaseException,
    *,
    tags: dict[str, str],
) -> None:
    """Best-effort Sentry capture. No-op if sentry_sdk missing or init failed.

    Mirrors run_app.py's optional-import style — we never want a Sentry
    transport problem to take down the dispatcher worker.
    """
    try:
        import sentry_sdk
    except ImportError:
        return
    try:
        with sentry_sdk.push_scope() as scope:
            for k, v in tags.items():
                scope.set_tag(k, v)
            sentry_sdk.capture_exception(exc)
    except Exception:
        # Sentry transport / init issues must not poison the queue.
        logger.exception("sentry capture failed")
```

- [ ] **Step 2.4: Replace the drop branch with structured-fields + Sentry capture**

Replace the `if is_last_attempt:` body inside `_process` (added in Task 1.4) with:

```python
            if is_last_attempt:
                attempts = item.attempt + 1
                template = (item.metadata or {}).get("template", "unknown")
                rcpt_hash = _recipient_hash(item.to)
                action = {
                    "template": template,
                    "attempts": attempts,
                    "error_class": type(exc).__name__,
                    "failure_kind": failure_kind,
                    "recipient_hash": rcpt_hash,
                }
                logger.warning(
                    "dropping email to %s after %d attempts: %s",
                    item.to, attempts, exc,
                    extra={"action": action},
                )
                _safe_sentry_capture(
                    exc,
                    tags={
                        "template": template,
                        "attempts": str(attempts),
                        "failure_kind": failure_kind,
                        "recipient_hash": rcpt_hash,
                    },
                )
                return
```

- [ ] **Step 2.5: Run the new tests + the integration suite to confirm green**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_email_dispatcher.py tests/test_email_integration.py -x -v
```

**Expected:** all green. The pre-existing `test_grant_succeeds_even_when_client_always_fails` still passes because the drop-log message string is unchanged; only `extra=` was added.

- [ ] **Step 2.6: Verify `_STRUCTURED` already contains `"action"`**

```bash
cd /Users/daveyhiles/Developer/markland && grep -n "_STRUCTURED" src/markland/run_app.py
```

**Expected output:**

```
23:    _STRUCTURED = ("principal_id", "doc_id", "action")
```

If `"action"` is missing for any reason (branch divergence at execution time), edit the tuple to include it. Otherwise no edit.

- [ ] **Step 2.7: Commit**

```bash
cd /Users/daveyhiles/Developer/markland && git add src/markland/service/email_dispatcher.py tests/test_email_dispatcher.py && git commit -m "$(cat <<'EOF'
surface email-drop failures to sentry with structured tags

Final drop now calls sentry_sdk.capture_exception (soft-imported) with
template, failure_kind, attempts, and a sha256 recipient hash — no raw
address leaves the process. Drop log gains a structured `action` dict
that the JSON formatter promotes to a top-level field for Fly log search.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: User-facing copy tweak

**Files:**
- Modify: `src/markland/web/templates/magic_link_sent.html`
- Test: `tests/test_auth_routes.py`

Goal: the "Check your email" page sets honest expectations about delivery latency without claiming the send succeeded.

- [ ] **Step 3.1: Write the failing assertion**

Append to `/Users/daveyhiles/Developer/markland/tests/test_auth_routes.py`:

```python
def test_magic_link_sent_page_sets_honest_expectations(client_and_conn):
    client, _, _ = client_and_conn
    r = client.post(
        "/api/auth/magic-link",
        data={"email": "alice@example.com"},
    )
    assert r.status_code == 200
    body = r.text
    assert "up to a minute" in body, "expected honest delivery-time copy in magic_link_sent"
```

- [ ] **Step 3.2: Run the test to verify it fails**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_auth_routes.py::test_magic_link_sent_page_sets_honest_expectations -x -v
```

**Expected:** `AssertionError: expected honest delivery-time copy in magic_link_sent` (current copy says "in a minute" not "up to a minute").

- [ ] **Step 3.3: Edit the template**

Replace line 17 of `/Users/daveyhiles/Developer/markland/src/markland/web/templates/magic_link_sent.html` (the `.note` paragraph) with:

```html
  <p class="note">It can take up to a minute to arrive. The link expires shortly. If it doesn't show up, check your spam folder, or <a href="/login{% if return_to %}?next={{ return_to|urlencode }}{% endif %}">request a new one</a>.</p>
```

- [ ] **Step 3.4: Run auth-route tests to verify pass**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_auth_routes.py -x -v
```

**Expected:** all auth-route tests green.

- [ ] **Step 3.5: Commit**

```bash
cd /Users/daveyhiles/Developer/markland && git add src/markland/web/templates/magic_link_sent.html tests/test_auth_routes.py && git commit -m "$(cat <<'EOF'
set honest delivery-time expectations on magic-link sent page

The page previously implied delivery within a minute; in practice Resend
sandbox rejection or transient failures can drop the email entirely. New
copy says "up to a minute" and keeps the request-a-new-one fallback
prominent. Async dispatch shape unchanged — coupling HTTP to Resend send
latency is the wrong fix.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Verification

- [ ] **Step 4.1: Full suite**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest -x
```

**Expected:** all green. If a pre-existing test fails on the magic-link-sent body, grep for the asserted substring:

```bash
cd /Users/daveyhiles/Developer/markland && grep -rn "in a minute" tests/
```

Update the asserted substring to `"up to a minute"`.

- [ ] **Step 4.2: Manual smoke (operator verification, post-deploy)**

After deploy:
1. Trigger device flow against an email that is **not** the workspace owner (sandbox will reject).
2. `flyctl logs -a markland --no-tail` and grep for `"action":` — expect a single JSON line with `action.template = "magic_link"`, `action.failure_kind = "permanent"`, `action.attempts = 1`.
3. Sentry → Issues — expect a new `EmailSendError` issue with tags `template:magic_link`, `failure_kind:permanent`, `recipient_hash:<12 hex>`.
4. Confirm the `>= 3 EmailSendError in 5 min` Sentry alert from `docs/runbooks/sentry-setup.md` actually fires when 3+ bad-recipient sends happen within 5 minutes.

This step is operator-side; no code change.

---

## Critical Files for Implementation

- `/Users/daveyhiles/Developer/markland/src/markland/service/email_dispatcher.py`
- `/Users/daveyhiles/Developer/markland/src/markland/web/templates/magic_link_sent.html`
- `/Users/daveyhiles/Developer/markland/tests/test_email_dispatcher.py`
- `/Users/daveyhiles/Developer/markland/tests/test_auth_routes.py`

**Verification-only (no edit expected):**
- `/Users/daveyhiles/Developer/markland/src/markland/run_app.py:23`
