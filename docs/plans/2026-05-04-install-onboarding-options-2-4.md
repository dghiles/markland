# Install / Onboarding — Options 2-4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the CLI-first install path (Phase 1: single-link instruction + RFC 8628 conformance) and add a browser-first onramp that reuses it (Phase 2: dashboard "Connect Claude Code" panel that hands the user one line to paste into Claude Code).

**Architecture:** Two phases sharing the device-flow path. Phase 1 changes one service helper (adds a field to a dataclass), one API handler (propagates the field), and one runbook string. Phase 2 adds a service helper (has-the-user-authorized-any-device-yet?), a template partial, a dismiss endpoint, and a one-line cookie set on the existing `/device/confirm` success redirect. No DB schema changes.

**Tech Stack:** FastAPI, Jinja2 templates, SQLite, pytest. RFC 8628 §3.2 (`verification_uri_complete`).

**Spec:** `docs/specs/2026-05-04-install-onboarding-options-2-4-design.md`.

---

## File Structure

**Phase 1 — modify:**
- `src/markland/service/device_flow.py:66-72` — `DeviceStart` dataclass gains `verification_uri_complete: str` field.
- `src/markland/service/device_flow.py:120-148` — `start()` builds and returns the new field.
- `src/markland/web/device_routes.py:135-160` — `api_device_start` handler propagates the field into the JSON response.
- `src/markland/web/device_routes.py:347-442` — `/setup` runbook string: rewrite step 2 + update step 1's documented response shape.
- `tests/test_device_flow_routes.py` — three new test cases (response shape, runbook step 2 wording, prefill-from-query-param).

**Phase 2 — modify:**
- `src/markland/service/device_flow.py` — append `has_authorized_device(conn, user_id) -> bool` helper.
- `src/markland/web/dashboard.py:45-104` — pass `show_connect_panel: bool` and `csrf_token: str` into the dashboard template context.
- `src/markland/web/templates/dashboard.html` — render the new partial conditionally.
- `src/markland/web/identity_routes.py` — append `POST /api/me/dismiss-connect-claude-code` route.
- `src/markland/web/device_routes.py:255-315` — on successful `/device/confirm`, the `RedirectResponse` to `/device/done` gains a Set-Cookie for `mk_dismiss_connect`.

**Phase 2 — create:**
- `src/markland/web/templates/_connect_claude_code.html` — new partial (single dismissible card).
- `tests/test_dashboard_connect_panel.py` — new test file.

**Test framework:** `uv run pytest tests/ -q`. To run a single file: `uv run pytest tests/test_device_flow_routes.py -q`.

---

# Phase 1 — CLI-first single-link install (RFC 8628 conforming)

## Task 1.1: `DeviceStart` dataclass + `start()` return `verification_uri_complete`

**Files:**
- Modify: `src/markland/service/device_flow.py:66-72` (dataclass)
- Modify: `src/markland/service/device_flow.py:120-148` (`start()` body)
- Test: `tests/test_device_flow_routes.py` (one new test below)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_device_flow_routes.py` (after the existing
`test_device_start_without_body_returns_expected_shape` block):

```python
def test_device_start_includes_verification_uri_complete(client):
    """RFC 8628 §3.2: response carries a single-click URL with the user_code embedded."""
    r = client.post("/api/auth/device-start")
    assert r.status_code == 200
    body = r.json()
    assert "verification_uri_complete" in body, body
    user_code = body["user_code"]
    # The complete URI is verification_uri + ?code=<user_code>.
    expected = f"https://markland.dev/device?code={user_code}"
    assert body["verification_uri_complete"] == expected, body["verification_uri_complete"]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_device_flow_routes.py::test_device_start_includes_verification_uri_complete -v
```

Expected: FAIL with `assert "verification_uri_complete" in body`.

- [ ] **Step 3: Add the field to the `DeviceStart` dataclass**

Edit `src/markland/service/device_flow.py:66-72`. Replace:

```python
@dataclass(frozen=True)
class DeviceStart:
    device_code: str
    user_code: str            # formatted: XXXX-XXXX
    verification_url: str
    poll_interval: int
    expires_in: int
```

with:

```python
@dataclass(frozen=True)
class DeviceStart:
    device_code: str
    user_code: str                     # formatted: XXXX-XXXX
    verification_url: str
    verification_uri_complete: str     # RFC 8628 §3.2: single-link form
    poll_interval: int
    expires_in: int
```

- [ ] **Step 4: Build the field inside `start()`**

Edit `src/markland/service/device_flow.py:140-148`. Replace:

```python
    verification_url = f"{base_url.rstrip('/')}/device" if base_url else "/device"
    return DeviceStart(
        device_code=device_code,
        user_code=format_user_code(raw_user_code),
        verification_url=verification_url,
        poll_interval=POLL_INTERVAL_SECONDS,
        expires_in=DEVICE_CODE_TTL_SECONDS,
    )
```

with:

```python
    formatted_user_code = format_user_code(raw_user_code)
    verification_url = f"{base_url.rstrip('/')}/device" if base_url else "/device"
    # urllib.parse.quote handles the '-' separator harmlessly; explicit so a
    # future user_code alphabet change doesn't silently produce a malformed URL.
    from urllib.parse import quote
    verification_uri_complete = (
        f"{verification_url}?code={quote(formatted_user_code, safe='')}"
    )
    return DeviceStart(
        device_code=device_code,
        user_code=formatted_user_code,
        verification_url=verification_url,
        verification_uri_complete=verification_uri_complete,
        poll_interval=POLL_INTERVAL_SECONDS,
        expires_in=DEVICE_CODE_TTL_SECONDS,
    )
```

(The `from urllib.parse import quote` line goes at the **top of the file** with the other imports — move it there as part of the edit. Don't leave a function-local import.)

- [ ] **Step 5: Propagate the field in the API handler**

Edit `src/markland/web/device_routes.py:148-156`. Replace:

```python
        return JSONResponse({
            "device_code": result.device_code,
            "user_code": result.user_code,
            "verification_url": result.verification_url,
            "poll_interval": result.poll_interval,
            "expires_in": result.expires_in,
        })
```

with:

```python
        return JSONResponse({
            "device_code": result.device_code,
            "user_code": result.user_code,
            "verification_url": result.verification_url,
            "verification_uri_complete": result.verification_uri_complete,
            "poll_interval": result.poll_interval,
            "expires_in": result.expires_in,
        })
```

- [ ] **Step 6: Update the existing shape-pinning test**

Find the existing test at `tests/test_device_flow_routes.py` near
`test_device_start_without_body_returns_expected_shape`. It looks like:

```python
    assert set(body) == {
        "device_code",
        "user_code",
        "verification_url",
        "poll_interval",
        "expires_in",
    }
```

Replace the literal `set(...)` with:

```python
    assert set(body) == {
        "device_code",
        "user_code",
        "verification_url",
        "verification_uri_complete",
        "poll_interval",
        "expires_in",
    }
```

- [ ] **Step 7: Run the new test + the updated shape test to verify pass**

```bash
uv run pytest tests/test_device_flow_routes.py::test_device_start_without_body_returns_expected_shape \
              tests/test_device_flow_routes.py::test_device_start_includes_verification_uri_complete \
              -v
```

Expected: both PASS.

- [ ] **Step 8: Run the full file to catch any regression**

```bash
uv run pytest tests/test_device_flow_routes.py -q
```

Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add src/markland/service/device_flow.py \
        src/markland/web/device_routes.py \
        tests/test_device_flow_routes.py
git commit -m "feat(device-flow): add verification_uri_complete to device-start response (RFC 8628 §3.2)"
```

---

## Task 1.2: `/setup` runbook — single-link instruction in step 2

**Files:**
- Modify: `src/markland/web/device_routes.py:347-442` (the f-string at `GET /setup`)
- Test: `tests/test_device_flow_routes.py` (one new test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_device_flow_routes.py`:

```python
def test_setup_runbook_uses_single_link_form(client):
    """Step 2 should hand the user a single clickable URL, not a code-to-type."""
    r = client.get("/setup")
    assert r.status_code == 200
    body = r.text
    # Must contain the single-link URL form so any reader (Claude Code or a
    # human eyeballing the page) sees one URL.
    assert "/device?code=" in body, "runbook missing single-link form"
    # Must NOT contain the legacy two-step phrasing.
    assert "and enter the code" not in body, "runbook still tells user to type the code"
    # And step 1's documented response shape teaches the new field.
    assert "verification_uri_complete" in body, "step 1 shape missing the new field"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_device_flow_routes.py::test_setup_runbook_uses_single_link_form -v
```

Expected: FAIL on the first assertion (`/device?code=` not in body).

- [ ] **Step 3: Rewrite step 1's documented response shape in the runbook**

Edit `src/markland/web/device_routes.py:373-383`. Replace:

```python
Parse the JSON response. It has shape:

```
{{
  "device_code":       "<long opaque string>",
  "user_code":         "ABCD-EFGH",
  "verification_url":  "{host}/device",
  "poll_interval":     5,
  "expires_in":        600
}}
```
```

with:

```python
Parse the JSON response. It has shape:

```
{{
  "device_code":               "<long opaque string>",
  "user_code":                 "ABCD-EFGH",
  "verification_url":          "{host}/device",
  "verification_uri_complete": "{host}/device?code=ABCD-EFGH",
  "poll_interval":             5,
  "expires_in":                600
}}
```

If your client library implements RFC 8628 §3.2 it will surface
`verification_uri_complete` directly to the user; otherwise build the URL
yourself (it is `verification_url + "?code=" + user_code`).
```

- [ ] **Step 4: Rewrite step 2's user-facing message**

Edit `src/markland/web/device_routes.py:385-391`. Replace:

```python
## 2. Show the user exactly this message

> Visit **{host}/device** and enter the code **ABCD-EFGH**.
> The code expires in 10 minutes.

(Substitute the real `user_code` from step 1.)
```

with:

```python
## 2. Show the user exactly this message

> Click here to authorize: **{host}/device?code=ABCD-EFGH**
> The link expires in 10 minutes.

(Substitute the real `user_code` from step 1, or just paste
`verification_uri_complete` straight from step 1's response.)
```

- [ ] **Step 5: Run the new test to verify it passes**

```bash
uv run pytest tests/test_device_flow_routes.py::test_setup_runbook_uses_single_link_form -v
```

Expected: PASS.

- [ ] **Step 6: Run the full file**

```bash
uv run pytest tests/test_device_flow_routes.py -q
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/markland/web/device_routes.py tests/test_device_flow_routes.py
git commit -m "feat(setup): runbook step 2 — single-link install instruction"
```

---

## Task 1.3: Pin that `/device?code=…` prefills the form

This behavior already exists in production (the route accepts
`code: str | None = None` at `device_routes.py:230` and renders it into
the form). Add a regression test so Phase 2's panel work doesn't
accidentally break it.

**Files:**
- Test: `tests/test_device_flow_routes.py` (one new test)

- [ ] **Step 1: Write the failing-or-passing test**

Append to `tests/test_device_flow_routes.py`:

```python
def test_device_query_param_prefills_form(client):
    """GET /device?code=ABCD-EFGH renders a form with that code prefilled."""
    _login(client)
    # Allocate a real user_code first so the lookup in page_device works.
    start = client.post("/api/auth/device-start").json()
    user_code = start["user_code"]
    r = client.get(f"/device?code={user_code}")
    assert r.status_code == 200
    # The hidden/visible input should carry the user_code attribute.
    assert f'value="{user_code}"' in r.text, r.text[:1500]
```

- [ ] **Step 2: Run the test to verify it passes today**

```bash
uv run pytest tests/test_device_flow_routes.py::test_device_query_param_prefills_form -v
```

Expected: PASS (the route already does this — we are pinning, not
implementing).

If it fails: the route or template changed unexpectedly; investigate
`device_routes.py:230-249` and the `device.html` template before
proceeding.

- [ ] **Step 3: Commit**

```bash
git add tests/test_device_flow_routes.py
git commit -m "test(device-flow): pin that /device?code= prefills the form"
```

---

# Phase 2 — Browser-via-shares onramp

## Task 2.1: `has_authorized_device(conn, user_id)` service helper

**Files:**
- Modify: `src/markland/service/device_flow.py` (append helper at end of file before `__all__` if present, otherwise just at the bottom)
- Test: `tests/test_service_device_flow.py` (existing file — append two tests)

- [ ] **Step 1: Verify the test file exists**

```bash
ls tests/test_service_device_flow.py
```

If absent, create it with the standard fixture stub (the test below will
work either way; `pytest` happily creates a new file).

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_service_device_flow.py` (creating the file with the
imports if needed):

```python
import pytest

from markland.db import init_db
from markland.service import device_flow
from markland.service.users import create_user


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


def test_has_authorized_device_false_when_no_device_authorizations(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    assert device_flow.has_authorized_device(conn, user.id) is False


def test_has_authorized_device_true_after_authorize(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    start = device_flow.start(conn, base_url="https://markland.dev")
    result = device_flow.authorize(conn, start.user_code, user_id=user.id)
    assert result.ok is True
    assert device_flow.has_authorized_device(conn, user.id) is True


def test_has_authorized_device_false_for_pending_only(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    device_flow.start(conn, base_url="https://markland.dev")
    # No authorize() call — row is pending, not authorized.
    assert device_flow.has_authorized_device(conn, user.id) is False
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
uv run pytest tests/test_service_device_flow.py -v
```

Expected: FAIL with `AttributeError: module 'markland.service.device_flow' has no attribute 'has_authorized_device'`.

- [ ] **Step 4: Implement the helper**

Append to `src/markland/service/device_flow.py` (after the existing
`authorize()` function, before the module's `__all__` if present):

```python
# ---------------------------------------------------------------------------
# has_authorized_device — Phase 2 dashboard panel gating
# ---------------------------------------------------------------------------


def has_authorized_device(conn: sqlite3.Connection, user_id: str) -> bool:
    """True if `user_id` has at least one row in device_authorizations
    with status='authorized'. Used by the dashboard "Connect Claude Code"
    panel to decide whether to show the prompt."""
    row = conn.execute(
        "SELECT 1 FROM device_authorizations "
        "WHERE user_id = ? AND status = 'authorized' LIMIT 1",
        (user_id,),
    ).fetchone()
    return row is not None
```

If the file has an `__all__` list, add `"has_authorized_device"` to it.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/test_service_device_flow.py -v
```

Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/markland/service/device_flow.py tests/test_service_device_flow.py
git commit -m "feat(device-flow): has_authorized_device service helper for dashboard panel"
```

---

## Task 2.2: `_connect_claude_code.html` partial + dashboard render-conditional

**Files:**
- Create: `src/markland/web/templates/_connect_claude_code.html`
- Modify: `src/markland/web/dashboard.py:45-104` (pass `show_connect_panel` + `csrf_token` into context)
- Modify: `src/markland/web/templates/dashboard.html` (include the partial conditionally)
- Test: `tests/test_dashboard_connect_panel.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dashboard_connect_panel.py`:

```python
"""Connect Claude Code dashboard panel — visibility logic.

The panel renders iff: signed in AND no authorized device AND no dismiss
cookie. Three negatives (anonymous / authorized / dismissed) and one
positive — four cases.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import sessions as sessions_mod
from markland.service import device_flow
from markland.service.users import create_user
from markland.web.app import create_app

SECRET = "test-session-secret"
PANEL_MARKER = 'aria-label="Connect Claude Code"'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "test.db")
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    app = create_app(
        conn, mount_mcp=False,
        base_url="https://markland.dev",
        session_secret=SECRET,
    )
    with TestClient(app, base_url="http://testserver") as c:
        c.state_alice_id = user.id
        c.state_conn = conn
        yield c


def _login(client, user_id=None):
    uid = user_id or client.state_alice_id
    cookie = sessions_mod.make_session_cookie_value(uid, secret=SECRET)
    client.cookies.set(sessions_mod.SESSION_COOKIE_NAME, cookie)


def test_panel_absent_when_anonymous(client):
    r = client.get("/dashboard")
    # Anonymous returns 401 today; even if that changed, the panel must not
    # leak into an anonymous response.
    assert PANEL_MARKER not in r.text


def test_panel_present_when_signed_in_with_no_authorized_device(client):
    _login(client)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert PANEL_MARKER in r.text


def test_panel_absent_when_signed_in_with_authorized_device(client):
    _login(client)
    start = device_flow.start(client.state_conn, base_url="https://markland.dev")
    device_flow.authorize(client.state_conn, start.user_code, user_id=client.state_alice_id)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert PANEL_MARKER not in r.text


def test_panel_absent_when_dismiss_cookie_set(client):
    _login(client)
    client.cookies.set("mk_dismiss_connect", "1")
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert PANEL_MARKER not in r.text
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_dashboard_connect_panel.py -v
```

Expected: 3 FAIL (panel never rendered — partial doesn't exist yet).
The first test (`test_panel_absent_when_anonymous`) may pass
incidentally, but the other three should fail.

- [ ] **Step 3: Create the partial template**

Create `src/markland/web/templates/_connect_claude_code.html`:

```html
{# Connect Claude Code — dashboard onramp for browser-first signups.
   Visible iff the viewer has no authorized device and has not dismissed.
   Auto-dismisses on successful /device/confirm via Set-Cookie. #}
<aside class="connect-claude-code"
       aria-label="Connect Claude Code"
       data-csrf="{{ csrf_token }}">
  <header>
    <h2>Connect Claude Code</h2>
    <button class="dismiss" type="button"
            data-dismiss-connect aria-label="Dismiss">×</button>
  </header>
  <p>In Claude Code, paste this message:</p>
  <div class="connect-cli-instruction">
    <code id="connect-instr">Install the Markland MCP server from {{ canonical_host }}/setup</code>
    <button class="copy" type="button" data-copy-target="connect-instr">Copy</button>
  </div>
  <p class="fineprint">
    Claude Code will walk you through a one-click browser authorization.
    The access token stays inside Claude Code's local config — it never
    leaves your machine.
  </p>
</aside>

<style>
  .connect-claude-code {
    max-width: 48rem;
    margin: 2rem auto;
    padding: 1.25rem 1.5rem;
    border: 1px solid var(--outline);
    border-radius: 8px;
    background: var(--surface);
  }
  .connect-claude-code header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 0.5rem;
  }
  .connect-claude-code header h2 { font-size: 1.1rem; margin: 0; }
  .connect-claude-code .dismiss {
    background: none; border: none; font-size: 1.5rem; line-height: 1;
    cursor: pointer; color: var(--muted); padding: 0 0.25rem;
  }
  .connect-claude-code .connect-cli-instruction {
    display: flex; align-items: center; gap: 0.5rem;
    background: var(--surface-2);
    border: 1px solid var(--outline-hairline);
    border-radius: 6px;
    padding: 0.5rem 0.75rem;
    margin: 0.5rem 0;
    font-family: var(--font-mono); font-size: 0.85rem;
  }
  .connect-claude-code .connect-cli-instruction code {
    flex: 1; background: none; border: none; padding: 0;
  }
  .connect-claude-code .connect-cli-instruction .copy {
    font: inherit; padding: 0.25rem 0.6rem;
    background: var(--surface); color: var(--text);
    border: 1px solid var(--outline); border-radius: 4px;
    cursor: pointer; font-size: 0.8rem;
  }
  .connect-claude-code .fineprint {
    color: var(--muted); font-size: 0.85rem; margin: 0.5rem 0 0;
  }
</style>

<script nonce="{{ csp_nonce }}">
(function () {
  var panel = document.querySelector('.connect-claude-code');
  if (!panel) return;

  // Copy button.
  var copyBtn = panel.querySelector('[data-copy-target]');
  if (copyBtn) {
    copyBtn.addEventListener('click', function () {
      var target = document.getElementById(copyBtn.getAttribute('data-copy-target'));
      if (!target) return;
      navigator.clipboard.writeText(target.textContent.trim()).then(function () {
        var original = copyBtn.textContent;
        copyBtn.textContent = 'Copied';
        setTimeout(function () { copyBtn.textContent = original; }, 1500);
      });
    });
  }

  // Dismiss button — POST to dismiss endpoint, then remove from DOM.
  var dismissBtn = panel.querySelector('[data-dismiss-connect]');
  if (dismissBtn) {
    dismissBtn.addEventListener('click', function () {
      var csrf = panel.getAttribute('data-csrf') || '';
      fetch('/api/me/dismiss-connect-claude-code', {
        method: 'POST',
        headers: { 'X-CSRF-Token': csrf },
        credentials: 'same-origin',
      }).then(function () {
        panel.remove();
      });
    });
  }
})();
</script>
```

- [ ] **Step 4: Wire the partial into `dashboard.html`**

Edit `src/markland/web/templates/dashboard.html`. Find the
`<section class="dashboard-section">` opening (line 17) and insert the
include block **immediately after** the opening `<section>` tag,
**before** the `<h1>Your documents</h1>`:

```html
{% if show_connect_panel %}
  {% include "_connect_claude_code.html" %}
{% endif %}
```

- [ ] **Step 5: Pass the gating context from the dashboard handler**

Edit `src/markland/web/dashboard.py`. The handler at line 45 currently
reads `user_id`, fetches docs, and calls `render_with_nav`. Add the
gating logic between the user-id resolution (line 65) and the doc
fetches.

After line 66 (`return JSONResponse({"error": "unauthenticated"}, status_code=401)`)
and before line 68 (`owned_docs = list_documents_for_owner(...)`), add:

```python
        # Phase 2: Connect Claude Code panel — show iff no authorized device
        # AND no dismiss cookie. Imported locally to keep the top-level import
        # block focused.
        from markland.service.device_flow import has_authorized_device
        from markland.service.sessions import make_csrf_token
        dismissed = request.cookies.get("mk_dismiss_connect") == "1"
        show_connect_panel = (
            not dismissed and not has_authorized_device(conn, user_id)
        )
        csrf_token = make_csrf_token(user_id, secret=session_secret)
```

Then change the `render_with_nav` call at line 99-103 from:

```python
        return HTMLResponse(
            render_with_nav(
                tpl, request, conn,
                base_url=base_url, secret=session_secret,
                owned=owned, shared=shared, bookmarks=bookmarks,
            )
        )
```

to:

```python
        return HTMLResponse(
            render_with_nav(
                tpl, request, conn,
                base_url=base_url, secret=session_secret,
                owned=owned, shared=shared, bookmarks=bookmarks,
                show_connect_panel=show_connect_panel,
                csrf_token=csrf_token,
            )
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest tests/test_dashboard_connect_panel.py -v
```

Expected: 4 PASS.

- [ ] **Step 7: Run the broader dashboard suite to catch regressions**

```bash
uv run pytest tests/test_dashboard_shared.py tests/test_dashboard_bookmarks.py tests/test_dashboard_connect_panel.py -q
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/markland/web/dashboard.py \
        src/markland/web/templates/dashboard.html \
        src/markland/web/templates/_connect_claude_code.html \
        tests/test_dashboard_connect_panel.py
git commit -m "feat(dashboard): Connect Claude Code panel + visibility gating"
```

---

## Task 2.3: `POST /api/me/dismiss-connect-claude-code` endpoint

**Files:**
- Modify: `src/markland/web/identity_routes.py` (append a new route)
- Test: `tests/test_identity_routes.py` (verified to exist; append three tests there)

- [ ] **Step 1: Confirm the test file exists**

```bash
ls tests/test_identity_routes.py
```

Expected: file exists. If it doesn't (someone moved it), grep for
`/api/tokens` to find the new home and use that instead — but as of
this plan's authoring, `tests/test_identity_routes.py` is the right
target.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_identity_routes.py`:

```python
def test_dismiss_endpoint_requires_auth(client):
    """Anonymous callers get 401, no cookie set."""
    r = client.post("/api/me/dismiss-connect-claude-code")
    assert r.status_code == 401
    assert "mk_dismiss_connect" not in r.cookies


def test_dismiss_endpoint_requires_csrf(client):
    """Signed-in but missing CSRF header → 403."""
    _login(client)
    r = client.post("/api/me/dismiss-connect-claude-code")
    assert r.status_code == 403


def test_dismiss_endpoint_sets_cookie(client):
    """Signed-in + valid CSRF → 204 and Set-Cookie."""
    _login(client)
    # Mint a CSRF token the same way the dashboard handler does.
    from markland.service.sessions import make_csrf_token
    csrf = make_csrf_token(client.state_alice_id, secret=SECRET)
    r = client.post(
        "/api/me/dismiss-connect-claude-code",
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 204
    assert r.cookies.get("mk_dismiss_connect") == "1"
```

(`_login` and `SECRET` come from the existing fixture in that file —
match its style. If creating a new test file, copy the fixture from
`tests/test_device_flow_routes.py:18-49`.)

- [ ] **Step 3: Run the tests to verify they fail**

```bash
uv run pytest tests/test_identity_routes.py -v -k dismiss
```

Expected: FAIL with 404 (route doesn't exist).

- [ ] **Step 4: Add the route**

Append to `src/markland/web/identity_routes.py` (inside the
`build_router` factory function, after the existing `/api/tokens`
routes):

```python
    @router.post("/api/me/dismiss-connect-claude-code")
    def api_dismiss_connect_claude_code(request: Request):
        """Dismiss the dashboard Connect Claude Code panel.
        Sets a year-long cookie. CSRF-required, session-required.
        Mirrors the agent-action policy in /api/tokens.
        """
        user_id = _session_user_id(request)
        if user_id is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)
        csrf = request.headers.get("X-CSRF-Token", "")
        if not verify_csrf_token(csrf, user_id, secret=session_secret):
            return JSONResponse({"error": "csrf"}, status_code=403)
        resp = Response(status_code=204)
        resp.set_cookie(
            key="mk_dismiss_connect",
            value="1",
            max_age=31_536_000,  # 1 year
            path="/",
            samesite="strict",
            secure=True,
            # HttpOnly intentionally False — JS reads this for fallback render
            # decisions; the cookie carries no PII or auth material.
            httponly=False,
        )
        return resp
```

If `Response` and `verify_csrf_token` are not already imported at the
top of `identity_routes.py`, add them:

```python
from fastapi import Response
from markland.service.sessions import verify_csrf_token
```

(Check the top of the file first — `_session_user_id` is already used,
so `Request` is imported. `verify_csrf_token` may be too.)

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/test_identity_routes.py -v -k dismiss
```

Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/identity_routes.py tests/test_identity_routes.py
git commit -m "feat(api): /api/me/dismiss-connect-claude-code dismiss endpoint"
```

---

## Task 2.4: `/device/confirm` success sets dismiss cookie

**Files:**
- Modify: `src/markland/web/device_routes.py:306-315` (the success-path `RedirectResponse`)
- Test: `tests/test_device_flow_routes.py` (one new test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_device_flow_routes.py`:

```python
def test_device_confirm_sets_dismiss_cookie(client):
    """A successful /device/confirm dismisses the dashboard panel for the user."""
    _login(client)
    start = client.post("/api/auth/device-start").json()
    user_code = start["user_code"]
    # Render /device once to grab a CSRF token.
    page = client.get(f"/device?code={user_code}")
    csrf = _extract_csrf(page.text)
    r = client.post(
        "/device/confirm",
        data={"user_code": user_code, "csrf": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    set_cookie = r.headers.get("set-cookie", "")
    assert "mk_dismiss_connect=1" in set_cookie, set_cookie
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_device_flow_routes.py::test_device_confirm_sets_dismiss_cookie -v
```

Expected: FAIL on the `mk_dismiss_connect=1` assertion.

- [ ] **Step 3: Set the cookie on the success redirect**

Edit `src/markland/web/device_routes.py:306-315`. Replace:

```python
        # Build redirect URL with optional invite_accepted / invite_error params.
        params = [f"code={result.user_code}"]
        if result.invite_accepted:
            params.append("invite_accepted=1")
        if result.invite_error:
            params.append(f"invite_error={quote(result.invite_error)}")
        return RedirectResponse(
            url=f"/device/done?{'&'.join(params)}",
            status_code=303,
        )
```

with:

```python
        # Build redirect URL with optional invite_accepted / invite_error params.
        params = [f"code={result.user_code}"]
        if result.invite_accepted:
            params.append("invite_accepted=1")
        if result.invite_error:
            params.append(f"invite_error={quote(result.invite_error)}")
        redirect = RedirectResponse(
            url=f"/device/done?{'&'.join(params)}",
            status_code=303,
        )
        # Phase 2: dismiss the dashboard "Connect Claude Code" panel
        # automatically — this user just authorized a device, so the panel
        # has done its job.
        redirect.set_cookie(
            key="mk_dismiss_connect",
            value="1",
            max_age=31_536_000,
            path="/",
            samesite="strict",
            secure=True,
            httponly=False,
        )
        return redirect
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/test_device_flow_routes.py::test_device_confirm_sets_dismiss_cookie -v
```

Expected: PASS.

- [ ] **Step 5: Run the full file**

```bash
uv run pytest tests/test_device_flow_routes.py -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/device_routes.py tests/test_device_flow_routes.py
git commit -m "feat(device-flow): auto-dismiss Connect Claude Code panel on confirm success"
```

---

## Task 2.5: Final integration sweep

- [ ] **Step 1: Run the entire test suite**

```bash
uv run pytest tests/ -q
```

Expected: all green. Two-phase change touched four files; if anything
unrelated turned red, investigate before continuing.

- [ ] **Step 2: Manual smoke (post-deploy, optional but recommended)**

After this plan deploys to production:

1. Open Claude Code. Paste:
   `Install the Markland MCP server from https://markland.dev/setup`
   Verify Claude Code shows ONE clickable URL of the form
   `https://markland.dev/device?code=ABCD-EFGH`.
2. Click it. Verify:
   - If signed in, the form is prefilled — one click to authorize.
   - If signed out, magic-link flow threads the code through and
     returns to the prefilled form.
3. Sign out, sign in fresh as a new user (or use a fresh email).
   Land on `/dashboard`. Verify the "Connect Claude Code" panel is
   visible.
4. Click `×` to dismiss. Reload `/dashboard`. Verify the panel stays
   gone (cookie set).
5. Clear `mk_dismiss_connect` cookie. Reload. Verify the panel returns.
6. Run the device-flow round trip end-to-end. Reload `/dashboard`.
   Verify the panel is gone (auto-dismissed by the success redirect's
   Set-Cookie).

- [ ] **Step 3: Update ROADMAP**

Roadmap entry for "Install/onboarding flow simplification" should
reflect: Options 2 + 3 shipped (Phase 1), Option 4 shipped via Phase 2
(panel-as-onramp instead of token-on-screen). Move the item from "Now"
to the Shipped log under "Marketing + UX surface."

This is a docs-only change to `docs/ROADMAP.md`; commit with message
`docs(roadmap): install/onboarding Options 2-4 shipped`.

---

## Out of scope (do not implement here)

- **Updating telemetry / metrics_events.** When that table lands
  separately, add events `connect_panel_shown`,
  `connect_panel_dismissed`, `device_confirm_from_panel`. Not this PR.
- **Adding `verification_uri_complete` to the device-flow tests'
  shape-pinning assertion in `tests/test_service_device_flow.py`** — the
  service-level tests pin the dataclass shape implicitly via attribute
  access; if you find a service-level test that does
  `set(asdict(result).keys()) == {...}`, update it. Otherwise leave it.
- **Refactoring the `/setup` runbook into a Jinja template** — it's an
  f-string today and that's fine; rewriting it is a separate concern.
- **Building a `/connect` standalone page** — explicitly rejected in
  the spec.

---

## Self-review checklist (run before declaring this plan done)

- Each task ends with a `git commit` step ✅
- Every code step shows the actual code, not a description ✅
- Every test step shows the assert, not "test it works" ✅
- No "TBD" / "TODO" / "fill in" placeholders ✅
- Type names consistent across tasks: `DeviceStart` (not
  `DeviceStartResult`), `has_authorized_device` (not
  `user_has_device`), `mk_dismiss_connect` cookie key in three
  places — Task 2.3 endpoint, Task 2.4 redirect, Task 2.2 panel
  conditional ✅
- Phase 1 + Phase 2 commits are independently revertable ✅
