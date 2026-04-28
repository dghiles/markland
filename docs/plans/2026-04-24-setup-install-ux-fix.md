# /setup Install UX + Security Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `/setup` install path actually work end-to-end, and close one security issue exposed during a real install run on 2026-04-24:
1. `POST /mcp` returns `307 → http://…/mcp/` — Fly's proxy strips HTTPS internally and uvicorn isn't told to trust the forwarded scheme, so the redirect Location header downgrades to plain HTTP. A client that follows it would send the bearer token in cleartext. (Critical.)
2. Quickstart teaches `claude mcp add markland {host}/setup` — `claude mcp add` interprets a bare URL as a stdio command and fails silently.
3. The `/setup` runbook shows a `claude mcp add` command missing `--transport http` and using `Authorization=Bearer …` (=) instead of `Authorization: Bearer …` (:). Both are rejected by the actual CLI.
4. `/login?next=/device` does not thread `next` through the magic-link round-trip — users land on `/settings/tokens` after sign-in instead of returning to `/device`, hit a "Create a token" form, and mistakenly enter the device user_code as a token *label*. Token gets created, device flow stays pending forever.
5. Anyone who fetches `/setup` via curl/browser sees a runbook addressed at "Claude Code" with no human-facing breadcrumb explaining where the URL belongs.

**Architecture:** Five independent fixes ordered by severity. Task 1 (security) ships first. Tasks 2-3 fix what the docs teach. Task 4 fixes the post-login dead-end. Task 5 adds the human preamble. Each task is small, self-contained, TDD-driven, and produces a working commit.

**Tech Stack:** FastAPI + Jinja2 templates, uvicorn, pytest, plain Python f-string runbook in `device_routes.py`.

---

## File Structure

- Modify: `src/markland/run_app.py` — add `proxy_headers=True, forwarded_allow_ips="*"` to the uvicorn.run call (Task 1)
- Add: `tests/test_proxy_headers.py` — assert `request.url.scheme` reflects `X-Forwarded-Proto` end-to-end (Task 1)
- Modify: `src/markland/web/templates/quickstart.html` — replace step 2 copy block (Task 2)
- Modify: `tests/test_quickstart_page.py` — update the assertion that pinned the broken command (Task 2)
- Modify: `src/markland/web/device_routes.py` — fix the `claude mcp add` line in the runbook + prepend human preamble (Tasks 3 + 5)
- Modify: `tests/test_device_flow_routes.py` — assert correct CLI shape and preamble (Tasks 3 + 5)
- Modify: `src/markland/web/auth_routes.py` — accept `next` on `GET /login`, hand it to the template (Task 4)
- Modify: `src/markland/web/templates/login.html` — pull `next` from the URL and include it as `return_to` in the magic-link fetch (Task 4)
- Modify: `tests/test_auth_routes.py` (or `tests/test_magic_link.py` if that's where the login flow tests live — verify existing structure first) — assert `next` is preserved through to the magic-link `return_to` (Task 4)

No new modules. No new templates. Two new test files at most (proxy headers test if no fitting existing file).

---

## Task 1: Fix HTTPS scheme downgrade in MCP redirect (SECURITY)

When a client `POST`s `https://markland.fly.dev/mcp`, the server returns `307 → http://markland.fly.dev/mcp/`. The downgrade to `http://` happens because Fly's proxy terminates TLS and forwards over HTTP; uvicorn defaults to ignoring `X-Forwarded-Proto`, so Starlette builds the redirect Location from the inner `http` scheme. A client that follows the redirect sends the bearer token in cleartext over Fly's edge → app hop. (Fly's edge → app is internal, but defense-in-depth still applies, and any future deployment behind a different proxy could expose this externally.)

The fix: tell uvicorn to trust the proxy headers. Starlette will then build redirect URLs using the original scheme.

**Files:**
- Modify: `src/markland/run_app.py` (the `uvicorn.run(...)` call near line 88)
- Test: `tests/test_proxy_headers.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_proxy_headers.py`:

```python
"""ProxyHeadersMiddleware integration: redirects must preserve HTTPS.

Background: Fly's proxy terminates TLS and forwards to the app over HTTP.
Without proxy_headers=True on uvicorn, Starlette builds redirect URLs from
the inner scheme, downgrading https → http and exposing bearer tokens to
any client that follows the redirect. This test pins the fix.
"""

from fastapi.testclient import TestClient

from markland.web.app import create_app
from tests.helpers import in_memory_db  # adjust import to match repo helper


def test_mcp_trailing_slash_redirect_preserves_https(tmp_session_secret):
    """POST /mcp should redirect with https Location, not http."""
    with in_memory_db() as conn:
        app = create_app(conn, mount_mcp=True, session_secret=tmp_session_secret)
        client = TestClient(app)
        # Simulate Fly's edge: HTTPS at the edge, HTTP on the wire.
        resp = client.post(
            "/mcp",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "markland.fly.dev",
                "Authorization": "Bearer fake_token_for_redirect_check",
            },
            allow_redirects=False,
        )
        # The exact response is "redirect to /mcp/" — the test is the scheme.
        if resp.status_code in (301, 302, 307, 308):
            location = resp.headers.get("location", "")
            assert location.startswith("https://"), (
                f"Redirect Location must use https, got: {location}"
            )
```

If the helpers/fixtures referenced above don't match what's in `tests/conftest.py`, adapt to the existing pattern instead. The key shape: build an app, POST `/mcp` with `X-Forwarded-Proto: https`, assert redirect Location is HTTPS.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_proxy_headers.py -v`
Expected: FAIL — Location header starts with `http://` because uvicorn's TestClient (and the production app) does not trust forwarded headers by default.

Note: TestClient may differ from production. If TestClient doesn't simulate proxy header trust at all, instead start with a smaller direct test against `ProxyHeadersMiddleware` from `uvicorn.middleware.proxy_headers` to verify the middleware is wired in. Adapt as needed; the goal is a test that fails today and passes after Step 3.

- [ ] **Step 3: Update uvicorn.run call**

In `src/markland/run_app.py`, find the line near 88:

```python
    uvicorn.run(app, host=host, port=config.web_port, log_level="info")
```

Replace with:

```python
    # Fly's proxy terminates TLS and forwards over HTTP. Without
    # proxy_headers=True / forwarded_allow_ips, Starlette builds redirect
    # URLs from the inner http scheme — bearer tokens on those redirects
    # would travel cleartext. Trust the X-Forwarded-* headers so redirects
    # preserve https.
    uvicorn.run(
        app,
        host=host,
        port=config.web_port,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
```

`forwarded_allow_ips="*"` is acceptable here because Fly only routes traffic that has already passed its edge — there is no untrusted-proxy threat at the app boundary. (Document this in the comment so a future reader doesn't tighten it incorrectly.)

- [ ] **Step 4: Run the failing test**

Run: `uv run pytest tests/test_proxy_headers.py -v`
Expected: PASS — Location is `https://…/mcp/`.

- [ ] **Step 5: Production smoke**

After deploy, manually check from a host with `curl`:

```bash
curl -sI -X POST https://markland.fly.dev/mcp -H "Authorization: Bearer ignored"
```

Expected: `location: https://markland.fly.dev/mcp/` (note `https`, not `http`).

- [ ] **Step 6: Commit**

```bash
git add src/markland/run_app.py tests/test_proxy_headers.py
git commit -m "fix(security): trust X-Forwarded-Proto so /mcp redirect preserves https

Without proxy_headers=True, uvicorn ignores Fly's X-Forwarded-Proto
header and Starlette builds redirect URLs from the inner http scheme.
A client that followed POST /mcp's 307 to /mcp/ would send its bearer
token in cleartext over the edge → app hop. Trust the forwarded
headers so redirects keep https.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Fix the quickstart install instruction

The quickstart teaches `claude mcp add markland {host}/setup` — verified broken on 2026-04-24:
- `claude mcp add` treats a bare URL as a stdio command unless `--transport http` is passed.
- `/setup` is a Markdown runbook, not an MCP endpoint.

Frame step 2 as a Claude Code chat directive — the way `/setup`'s runbook is actually meant to be consumed.

**Files:**
- Modify: `src/markland/web/templates/quickstart.html` (lines 96–102 today)
- Test: `tests/test_quickstart_page.py` (`test_quickstart_templates_setup_host` near line 49)

- [ ] **Step 1: Update the failing test first**

In `tests/test_quickstart_page.py`, replace `test_quickstart_templates_setup_host` with:

```python
def test_quickstart_templates_setup_host(client):
    r = client.get("/quickstart")
    # Quickstart must NOT teach the broken `claude mcp add <url>` form —
    # claude mcp add treats a bare URL as a stdio command and fails. The
    # runbook at /setup is consumed by Claude Code as a chat directive.
    assert "claude mcp add markland http://testserver/setup" not in r.text
    # Must still show the canonical host so we don't ship a stale fly.dev URL.
    assert "http://testserver/setup" in r.text
    assert "markland.dev/setup" not in r.text
    # Must frame it as a Claude Code chat instruction, not a terminal command.
    assert "Claude Code" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_quickstart_page.py::test_quickstart_templates_setup_host -v`
Expected: FAIL — current template still has `claude mcp add markland {host}/setup`.

- [ ] **Step 3: Update quickstart.html step 2**

In `src/markland/web/templates/quickstart.html`, replace the block at lines 96–102:

```html
  <h2>2. Wire up the MCP server</h2>
  <p>In a terminal, run:</p>
  <pre>claude mcp add markland {{ canonical_host }}/setup</pre>
  <p>
    Claude Code will prompt you to open a browser, authorize a token, and then store the token in your local
    Claude Code config. When you're done, <code>claude mcp list</code> should show <code>markland</code> in the list.
  </p>
```

with:

```html
  <h2>2. Wire up the MCP server</h2>
  <p>Open Claude Code (CLI or web) and send this message:</p>
  <pre>Install the Markland MCP server from {{ canonical_host }}/setup</pre>
  <p>
    Claude Code fetches the runbook at that URL, walks you through a one-time browser authorization, and then
    runs <code>claude mcp add</code> with the right transport flag and bearer token. When it's done,
    <code>claude mcp list</code> should show <code>markland</code> in the list.
  </p>
```

- [ ] **Step 4: Run the targeted test**

Run: `uv run pytest tests/test_quickstart_page.py -v`
Expected: PASS — all quickstart tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/templates/quickstart.html tests/test_quickstart_page.py
git commit -m "fix(quickstart): instruct users to install via Claude Code chat, not 'claude mcp add <url>'

claude mcp add interprets a bare URL as a stdio command, so the
previous directive failed silently for anyone who pasted it into a
terminal. The /setup runbook is designed to be consumed by Claude
Code as chat input — frame the install step that way.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Fix the `claude mcp add` command shown in the `/setup` runbook

The runbook step 4 today shows:

```
claude mcp add markland {host}/mcp --header "Authorization=Bearer $ACCESS_TOKEN"
```

Three problems verified on 2026-04-24:
- Missing `--transport http` → CLI silently registers a stdio server.
- `Authorization=Bearer …` (=) is rejected; CLI requires `Authorization: Bearer …` (:).
- `{host}/mcp` triggers a `307 → /mcp/` redirect that the MCP client doesn't follow gracefully on `POST`. Use `{host}/mcp/` (trailing slash) directly to avoid the round-trip.

**Files:**
- Modify: `src/markland/web/device_routes.py` (the `runbook` f-string in `page_setup`, around line 358)
- Test: `tests/test_device_flow_routes.py` (Task 10 block near line 266)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_device_flow_routes.py`, after the existing `/setup` tests:

```python
def test_setup_runbook_install_command_is_complete(client):
    """The CLI command in step 4 must be runnable as-is.

    Verified broken on 2026-04-24:
    - missing --transport http → registers as stdio
    - Authorization=Bearer (=) → CLI rejects, expects colon
    - bare /mcp → 307 redirect not followed cleanly on POST
    """
    r = client.get("/setup")
    body = r.text
    # Must specify HTTP transport explicitly.
    assert "--transport http" in body
    # Must use header colon syntax, not equals.
    assert 'Authorization: Bearer' in body
    assert 'Authorization=Bearer' not in body
    # Must use trailing-slash MCP path so the install doesn't depend on
    # following a 307 across a POST.
    assert "/mcp/" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_device_flow_routes.py::test_setup_runbook_install_command_is_complete -v`
Expected: FAIL — runbook today has none of the three required strings.

- [ ] **Step 3: Update the runbook command in device_routes.py**

In `src/markland/web/device_routes.py`, find the `## 4. Install the MCP server` section in the runbook f-string (around line 354–376). Change the CLI block from:

```
claude mcp add markland {host}/mcp --header "Authorization=Bearer $ACCESS_TOKEN"
```

to:

```
claude mcp add --transport http markland {host}/mcp/ --header "Authorization: Bearer $ACCESS_TOKEN"
```

And update the JSON fallback block in the same section. Change `"url": "{host}/mcp"` to `"url": "{host}/mcp/"` so the manual-edit path matches.

Leave the surrounding prose unchanged.

- [ ] **Step 4: Run the failing test**

Run: `uv run pytest tests/test_device_flow_routes.py::test_setup_runbook_install_command_is_complete -v`
Expected: PASS.

- [ ] **Step 5: Run full /setup test surface**

Run: `uv run pytest tests/test_device_flow_routes.py -k setup -v`
Expected: PASS — existing `/setup` tests (markdown content type, device-start/poll/whoami snippets, invite threading) all still pass.

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/device_routes.py tests/test_device_flow_routes.py
git commit -m "fix(setup): make 'claude mcp add' command in runbook actually runnable

Three problems with the previous command, verified during a real
install on 2026-04-24:
- missing --transport http → CLI registers it as a stdio server
- 'Authorization=Bearer …' (=) → CLI rejects, requires colon
- bare /mcp → 307 redirect not followed cleanly on POST

Use --transport http, colon header syntax, and the trailing-slash
URL to give a copy-paste command that works on the first try.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Thread `next=` through `/login` so magic-link returns to `/device`

When a user hits `/device` while signed out, we redirect to `/login?next=/device`. But `login.html` ignores the `next` query param entirely — it doesn't read it from the URL, doesn't include it as `return_to` in the JSON body of `POST /api/auth/magic-link`. The magic link is therefore issued with no `return_to`, the verify page falls back to "/", and the verify-sent template lands users on `/settings/tokens`. From there a user trying to authorize a device flow types the user_code into the "Create a token" form (mistaking the *label* field for a code-entry field), which creates an unrelated bearer token while the device flow stays `pending` forever. Verified live on 2026-04-24.

The fix is small: make `/login` accept `next`, render it into the page, JS reads it and includes `return_to` in the fetch body.

**Files:**
- Modify: `src/markland/web/auth_routes.py` (`login_page`, near line 56)
- Modify: `src/markland/web/templates/login.html`
- Test: `tests/test_auth_routes.py` (or whichever file holds login/magic-link tests — confirm by running `grep -l 'magic_link\|/login' tests/` first)

- [ ] **Step 1: Write the failing test**

In the appropriate auth-routes test file, add:

```python
def test_login_threads_next_param_into_magic_link(client, monkeypatch):
    """When /login has ?next=/device, the issued magic link must return there.

    Background: /device redirects unauth'd users to /login?next=/device.
    If `next` doesn't make it into the magic-link `return_to`, users land
    on /settings/tokens after sign-in and the device flow stays pending.
    """
    captured = {}

    def fake_send_magic_link(*, dispatcher, email, secret, base_url, return_to=None, **_):
        captured["email"] = email
        captured["return_to"] = return_to
        return "fake_token"

    monkeypatch.setattr(
        "markland.web.auth_routes.send_magic_link", fake_send_magic_link
    )

    # The login page must render the `next` value so the JS can include it.
    page = client.get("/login?next=/device")
    assert page.status_code == 200
    assert "/device" in page.text

    # Posting the magic-link request with return_to set must thread through.
    r = client.post(
        "/api/auth/magic-link",
        json={"email": "test@example.com", "return_to": "/device"},
    )
    assert r.status_code == 200
    assert captured["return_to"] == "/device"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest <test-file>::test_login_threads_next_param_into_magic_link -v`
Expected: FAIL — `login_page` does not accept a `next` parameter, the rendered HTML has no `/device` reference.

(The POST half may already pass since `/api/auth/magic-link` reads `return_to` from the body — that's fine, the GET-side assertion is what fails.)

- [ ] **Step 3: Accept `next` on the login route**

In `src/markland/web/auth_routes.py`, change the `login_page` signature and pass `next` to the template:

```python
@router.get("/login", response_class=HTMLResponse)
def login_page(next: str | None = None) -> HTMLResponse:
    # Validate `next` with the same allowlist as magic-link return_to so a
    # crafted /login?next=//evil.example can't ride to the magic-link form.
    safe_next = safe_return_to(next)
    return HTMLResponse(login_tpl.render(next=safe_next))
```

Make sure `login_tpl` resolves to the existing `login.html` Jinja template; if `login_page` currently returns raw HTML directly (no template render), introduce `login_tpl = env.get_template("login.html")` once at module/factory scope using the same pattern other templates in the file use. Mirror the surrounding code rather than inventing a new pattern.

- [ ] **Step 4: Update login.html to forward `next` as `return_to`**

In `src/markland/web/templates/login.html`:

```html
<form id="f">
  <label for="email">Email</label>
  <input type="email" id="email" name="email" required>
  <input type="hidden" id="next" value="{{ next | default('/', true) }}">
  <button type="submit">Send magic link</button>
</form>
```

And update the JS submit handler:

```html
<script>
  document.getElementById('f').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('email').value.trim();
    const next = document.getElementById('next').value || '/';
    const msg = document.getElementById('msg');
    msg.className = '';
    msg.textContent = 'Sending...';
    const r = await fetch('/api/auth/magic-link', {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({email, return_to: next}),
    });
    if (r.ok) {
      msg.className = 'msg';
      msg.textContent = 'Check your email for the sign-in link.';
    } else {
      msg.className = 'err';
      msg.textContent = 'Something went wrong. Check the email and try again.';
    }
  });
</script>
```

- [ ] **Step 5: Run the failing test**

Run: `uv run pytest <test-file>::test_login_threads_next_param_into_magic_link -v`
Expected: PASS.

- [ ] **Step 6: Run the full auth-route test surface**

Run: `uv run pytest tests/ -k 'login or magic_link or verify' -v`
Expected: PASS — no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/markland/web/auth_routes.py src/markland/web/templates/login.html <test-file>
git commit -m "fix(auth): thread ?next= through /login → magic-link → verify

/device redirects unauth'd users to /login?next=/device, but the login
form was discarding `next`. Magic links were issued with no return_to,
verify landed on '/', and the verify-sent template pointed users to
/settings/tokens — where they would mistakenly type the device user_code
into the 'Create a token' label field and leave the device flow pending
forever.

Read `next` on GET /login (validated through safe_return_to to avoid
open redirects), render it into the form, send it as return_to with
the magic-link request.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Add a `**For humans:**` preamble to the `/setup` runbook

Anyone who reaches `/setup` via curl, a browser, or by pasting the URL into something that isn't a Claude Code chat needs a one-glance signal explaining where the URL belongs. Put the human preamble at the top of the runbook, then a horizontal rule, then the existing `You are Claude Code…` role prompt — so an LLM consumer still receives a clear directive after the preamble.

**Files:**
- Modify: `src/markland/web/device_routes.py` (the runbook f-string in `page_setup`, top — around line 301)
- Test: `tests/test_device_flow_routes.py` (Task 10 block near line 266)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_device_flow_routes.py`:

```python
def test_setup_runbook_has_human_preamble(client):
    r = client.get("/setup")
    body = r.text
    # Humans landing on /setup via curl/browser need to know this URL is
    # meant to be pasted into a Claude Code chat, not run in a terminal.
    assert "**For humans:**" in body
    assert "Install the Markland MCP server from" in body
    # The agent-facing role prompt must still appear after the preamble so
    # an LLM consumer of the runbook still gets a clear directive.
    assert "You are Claude Code" in body
    # Order matters — preamble first, role prompt second.
    assert body.index("**For humans:**") < body.index("You are Claude Code")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_device_flow_routes.py::test_setup_runbook_has_human_preamble -v`
Expected: FAIL.

- [ ] **Step 3: Add the preamble**

In `src/markland/web/device_routes.py`, change the start of the `runbook` f-string from:

```python
        runbook = f"""# Markland setup

You are Claude Code. A user pasted this URL to install the Markland MCP server.
Execute the steps below end-to-end. Do not ask the user for input beyond what
step 2 instructs.
```

to:

```python
        runbook = f"""# Markland setup

**For humans:** This URL is the install runbook for the Markland MCP server.
It is meant to be read by Claude Code, not run in a terminal. To install,
open Claude Code (CLI or web) and send this message:

> Install the Markland MCP server from {host}/setup

Claude Code will fetch this page, walk you through a one-time browser
authorization, and finish the install.

---

You are Claude Code. A user pasted this URL to install the Markland MCP server.
Execute the steps below end-to-end. Do not ask the user for input beyond what
step 2 instructs.
```

- [ ] **Step 4: Run the targeted test**

Run: `uv run pytest tests/test_device_flow_routes.py::test_setup_runbook_has_human_preamble -v`
Expected: PASS.

- [ ] **Step 5: Run all `/setup` tests**

Run: `uv run pytest tests/test_device_flow_routes.py -k setup -v`
Expected: PASS.

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/markland/web/device_routes.py tests/test_device_flow_routes.py
git commit -m "feat(setup): add 'For humans' preamble to /setup runbook

Anyone who fetches /setup via curl or a browser needs a one-glance
signal that the URL belongs in a Claude Code chat, not a terminal.
Put the human preamble first, separated by a horizontal rule from
the existing 'You are Claude Code...' role prompt so an LLM reading
the page top-down still gets a clear directive.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Out of scope for this plan

- Eliminating the `/mcp` → `/mcp/` 307 entirely (e.g., by serving the streamable-HTTP app at `/mcp` without trailing-slash). Task 1 closes the security side; Task 3 routes around the redirect entirely by documenting `/mcp/` as the canonical install URL. Eliminating the redirect is a bigger refactor and not required to ship a working install today.
- A stdio launcher (`npx @markland/install` or similar) that would let `claude mcp add markland <launcher>` work without chat context.
- Buying / verifying `markland.dev` and switching `RESEND_FROM_EMAIL` away from `onboarding@resend.dev`. Tracked in `docs/FOLLOW-UPS.md`.
- A deploy-time guard that fails if `RESEND_API_KEY` is empty in a prod-flagged env. Worth filing separately so a future deploy doesn't quietly disable email.
- Auditing other places (READMEs, marketing copy) that may still show the old `claude mcp add <url>` form. Cheap to grep as part of Task 2's review.
