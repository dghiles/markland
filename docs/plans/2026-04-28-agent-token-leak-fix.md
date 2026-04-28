# Agent Token Query-String Leak Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop leaking newly-minted agent token plaintext through the URL by replacing the `?new_token=...` query-string redirect with a short-TTL signed flash cookie.

**Architecture:** Mirror the existing `URLSafeTimedSerializer` flash-cookie pattern from `src/markland/service/pending_intent.py`. On agent-token POST, sign the plaintext into a `markland_agent_token_flash` cookie (5-min TTL, HttpOnly, SameSite=Lax, Secure when `base_url` is https), redirect to `/settings/agents` with no query string. The GET handler reads the cookie, renders the token once, and clears the cookie on the response so a refresh shows nothing. We pick the signed-cookie path (not a server-side cache key) because the codebase already has the `itsdangerous` dependency, an established sibling pattern (`pending_intent.py`), and a single client-side hop — so a one-shot opaque token + server cache adds storage state without buying us anything.

**Tech Stack:** Python 3, FastAPI, itsdangerous (`URLSafeTimedSerializer`), Jinja2 templates, pytest + `fastapi.testclient.TestClient`.

---

## File Structure

**Create:**
- `src/markland/service/agent_token_flash.py` — issue/read helpers + `InvalidAgentTokenFlash` exception, mirroring `pending_intent.py`.
- `tests/test_service_agent_token_flash.py` — unit tests for the serializer roundtrip.

**Modify:**
- `src/markland/web/routes_agents.py` — change POST `/settings/agents/{agent_id}/tokens/create` (currently lines 205-225) to set a signed cookie and redirect to `/settings/agents` with no query string; change GET `/settings/agents` (currently lines 162-173) to read+clear the cookie instead of `request.query_params.get("new_token")`.
- `tests/test_settings_agents_page.py` — update `test_settings_agents_token_create_surfaces_plaintext` (currently lines 61-71) to assert no query string and a flash cookie; add tests for render-once behaviour and sibling audit.
- `tests/test_routes_agents.py` — add a flash-cookie integration test for the HTML form path (the file currently only exercises `/api/agents*` JSON endpoints).

---

### Task 1: Add the agent_token_flash service module

**Files:**
- Create: `src/markland/service/agent_token_flash.py`
- Test: `tests/test_service_agent_token_flash.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_service_agent_token_flash.py`:

```python
"""Unit tests for the signed flash cookie used to surface a freshly-minted
agent token without leaking it into the URL."""

import time

import pytest

from markland.service.agent_token_flash import (
    AGENT_TOKEN_FLASH_COOKIE_NAME,
    AGENT_TOKEN_FLASH_MAX_AGE_SECONDS,
    InvalidAgentTokenFlash,
    issue_agent_token_flash,
    read_agent_token_flash,
)


SECRET = "test-secret"


def test_cookie_name_constant():
    assert AGENT_TOKEN_FLASH_COOKIE_NAME == "markland_agent_token_flash"


def test_max_age_is_five_minutes():
    assert AGENT_TOKEN_FLASH_MAX_AGE_SECONDS == 5 * 60


def test_roundtrip_returns_plaintext():
    sealed = issue_agent_token_flash(secret=SECRET, plaintext="mk_agt_abc123")
    assert sealed != "mk_agt_abc123"  # signed, not echoed
    assert read_agent_token_flash(sealed, secret=SECRET) == "mk_agt_abc123"


def test_empty_token_is_rejected_on_issue():
    with pytest.raises(ValueError):
        issue_agent_token_flash(secret=SECRET, plaintext="")


def test_empty_secret_is_rejected_on_issue():
    with pytest.raises(ValueError):
        issue_agent_token_flash(secret="", plaintext="mk_agt_abc")


def test_empty_cookie_value_raises_invalid():
    with pytest.raises(InvalidAgentTokenFlash):
        read_agent_token_flash("", secret=SECRET)


def test_tampered_signature_raises_invalid():
    sealed = issue_agent_token_flash(secret=SECRET, plaintext="mk_agt_abc123")
    tampered = sealed[:-1] + ("A" if sealed[-1] != "A" else "B")
    with pytest.raises(InvalidAgentTokenFlash):
        read_agent_token_flash(tampered, secret=SECRET)


def test_wrong_secret_raises_invalid():
    sealed = issue_agent_token_flash(secret=SECRET, plaintext="mk_agt_abc123")
    with pytest.raises(InvalidAgentTokenFlash):
        read_agent_token_flash(sealed, secret="other-secret")


def test_expired_cookie_raises_invalid():
    sealed = issue_agent_token_flash(secret=SECRET, plaintext="mk_agt_abc123")
    # Set max_age to 0 to force expiry; itsdangerous treats now > issued+0 as expired.
    time.sleep(1)
    with pytest.raises(InvalidAgentTokenFlash):
        read_agent_token_flash(sealed, secret=SECRET, max_age_seconds=0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_service_agent_token_flash.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'markland.service.agent_token_flash'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/markland/service/agent_token_flash.py`:

```python
"""Signed flash cookie carrying a freshly-minted agent token plaintext.

After a user mints a new agent token via the /settings/agents form, we need
to surface the plaintext exactly once on the next page render. Putting the
plaintext in a query string (the prior implementation) leaks it into browser
history, Referer headers, and access logs. Instead, we sign the plaintext
into a short-TTL HttpOnly cookie, redirect to /settings/agents (no query
string), then read+clear the cookie on the next render.

Cookie name: `markland_agent_token_flash`. Payload: `{"plaintext": str}`,
signed via itsdangerous with the same `session_secret` used for `mk_session`.
TTL: 5 minutes — long enough to survive the redirect hop, short enough that
a forgotten tab can't leak the value indefinitely.
"""

from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

AGENT_TOKEN_FLASH_COOKIE_NAME = "markland_agent_token_flash"
AGENT_TOKEN_FLASH_MAX_AGE_SECONDS = 5 * 60
_SALT = "mk.agent_token_flash.v1"


class InvalidAgentTokenFlash(Exception):
    """Raised when a flash token is missing, tampered, or expired."""


def _serializer(secret: str) -> URLSafeTimedSerializer:
    if not secret:
        raise ValueError("session secret must be non-empty")
    return URLSafeTimedSerializer(secret, salt=_SALT)


def issue_agent_token_flash(*, secret: str, plaintext: str) -> str:
    if not plaintext:
        raise ValueError("plaintext must be non-empty")
    return _serializer(secret).dumps({"plaintext": plaintext})


def read_agent_token_flash(
    sealed: str,
    *,
    secret: str,
    max_age_seconds: int = AGENT_TOKEN_FLASH_MAX_AGE_SECONDS,
) -> str:
    if not sealed:
        raise InvalidAgentTokenFlash("empty cookie")
    try:
        payload = _serializer(secret).loads(sealed, max_age=max_age_seconds)
    except SignatureExpired as e:
        raise InvalidAgentTokenFlash("expired") from e
    except BadSignature as e:
        raise InvalidAgentTokenFlash("bad signature") from e
    if not isinstance(payload, dict):
        raise InvalidAgentTokenFlash("malformed payload")
    plaintext = payload.get("plaintext")
    if not isinstance(plaintext, str) or not plaintext:
        raise InvalidAgentTokenFlash("malformed payload")
    return plaintext
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_service_agent_token_flash.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/agent_token_flash.py tests/test_service_agent_token_flash.py
git commit -m "feat(service): add signed flash cookie for new-agent-token plaintext"
```

---

### Task 2: Update the settings_agents page test to expect cookie-based flash

**Files:**
- Modify: `tests/test_settings_agents_page.py:61-71`

The existing `test_settings_agents_token_create_surfaces_plaintext` asserts that the redirect Location starts with `/settings/agents?new_token=mk_agt_`. That assertion is exactly what we are deleting. Replace it with three tests that pin the new behaviour: (a) redirect URL has no query string, (b) a signed flash cookie is set, (c) GET `/settings/agents` renders the token once then clears it.

- [ ] **Step 1: Write the failing tests**

Replace `test_settings_agents_token_create_surfaces_plaintext` (lines 61-71 of `tests/test_settings_agents_page.py`) and append new tests. Final content from line 61 onward should read:

```python
def test_settings_agents_token_create_redirects_without_query_string(client):
    c, conn = client
    a = agents_svc.create_agent(conn, "usr_alice", "scribe")
    r = c.post(
        f"/settings/agents/{a.id}/tokens/create",
        data={"label": "laptop"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    loc = r.headers["location"]
    assert loc == "/settings/agents", loc
    assert "new_token" not in loc
    assert "mk_agt_" not in loc


def test_settings_agents_token_create_sets_signed_flash_cookie(client):
    from markland.service.agent_token_flash import (
        AGENT_TOKEN_FLASH_COOKIE_NAME,
        read_agent_token_flash,
    )

    c, conn = client
    a = agents_svc.create_agent(conn, "usr_alice", "scribe")
    r = c.post(
        f"/settings/agents/{a.id}/tokens/create",
        data={"label": "laptop"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    set_cookie = r.headers.get("set-cookie", "")
    assert AGENT_TOKEN_FLASH_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie.lower() or "samesite=lax" in set_cookie.lower()

    cookie_value = r.cookies.get(AGENT_TOKEN_FLASH_COOKIE_NAME)
    assert cookie_value, "flash cookie should be set on the redirect response"
    plaintext = read_agent_token_flash(cookie_value, secret=SECRET)
    assert plaintext.startswith("mk_agt_")


def test_settings_agents_renders_flash_token_once_then_clears(client):
    from markland.service.agent_token_flash import AGENT_TOKEN_FLASH_COOKIE_NAME

    c, conn = client
    a = agents_svc.create_agent(conn, "usr_alice", "scribe")
    r = c.post(
        f"/settings/agents/{a.id}/tokens/create",
        data={"label": "laptop"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    # TestClient persists Set-Cookie automatically; the next GET will send it.
    flash_cookie = c.cookies.get(AGENT_TOKEN_FLASH_COOKIE_NAME)
    assert flash_cookie

    # First render: token visible, cookie cleared on response.
    r1 = c.get("/settings/agents")
    assert r1.status_code == 200
    assert "mk_agt_" in r1.text
    # Response should clear the cookie (Set-Cookie with empty value / Max-Age=0).
    set_cookie = r1.headers.get("set-cookie", "")
    assert AGENT_TOKEN_FLASH_COOKIE_NAME in set_cookie
    assert ("Max-Age=0" in set_cookie) or ('=""' in set_cookie) or (f"{AGENT_TOKEN_FLASH_COOKIE_NAME}=;" in set_cookie)

    # Second render (refresh): token gone.
    r2 = c.get("/settings/agents")
    assert r2.status_code == 200
    assert "mk_agt_" not in r2.text


def test_settings_agents_ignores_query_string_new_token(client):
    """Defence-in-depth: even if a stale link with ?new_token=... is bookmarked,
    the page must NOT echo the value (since it is no longer trusted input)."""
    c, _ = client
    r = c.get("/settings/agents?new_token=mk_agt_should_not_render")
    assert r.status_code == 200
    assert "mk_agt_should_not_render" not in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_settings_agents_page.py -q`
Expected: FAIL — current implementation still redirects to `/settings/agents?new_token=...` and reads from `request.query_params`. The redirect-without-query test, the cookie test, the render-once test, and the ignore-query-string test should all fail.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_settings_agents_page.py
git commit -m "test(web): pin no-query-string + signed-flash-cookie agent token behaviour"
```

---

### Task 3: Switch routes_agents.py to flash-cookie pattern

**Files:**
- Modify: `src/markland/web/routes_agents.py:162-173, 205-225`

- [ ] **Step 1: Update GET handler to read+clear the flash cookie**

In `src/markland/web/routes_agents.py`, replace the GET handler block (current lines 162-173):

```python
    @html_router.get("/settings/agents", response_class=HTMLResponse)
    def settings_agents(request: Request):
        user = _session_user_or_none(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        agents = agents_svc.list_agents(db_conn, owner_user_id=user.id)
        return HTMLResponse(
            settings_tpl.render(
                agents=[a.__dict__ for a in agents],
                new_token=request.query_params.get("new_token"),
            )
        )
```

with the following implementation that reads + clears the signed flash cookie and ignores any query-string `new_token`:

```python
    @html_router.get("/settings/agents", response_class=HTMLResponse)
    def settings_agents(request: Request):
        user = _session_user_or_none(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        agents = agents_svc.list_agents(db_conn, owner_user_id=user.id)

        new_token: str | None = None
        sealed = request.cookies.get(AGENT_TOKEN_FLASH_COOKIE_NAME, "")
        if sealed:
            try:
                new_token = read_agent_token_flash(sealed, secret=session_secret)
            except InvalidAgentTokenFlash:
                new_token = None

        body = settings_tpl.render(
            agents=[a.__dict__ for a in agents],
            new_token=new_token,
        )
        resp = HTMLResponse(body)
        if sealed:
            # Clear the cookie regardless of whether we successfully decoded it,
            # so a tampered/expired cookie cannot stick around.
            resp.delete_cookie(AGENT_TOKEN_FLASH_COOKIE_NAME, path="/")
        return resp
```

- [ ] **Step 2: Update the POST handler to set the cookie and redirect cleanly**

Replace the token-create form handler block (current lines 205-225):

```python
    @html_router.post("/settings/agents/{agent_id}/tokens/create")
    def settings_agents_token_create(
        agent_id: str,
        request: Request,
        label: str = Form(...),
    ):
        user = _session_user_or_none(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        try:
            _, plaintext = auth_svc.create_agent_token(
                db_conn,
                agent_id=agent_id,
                owner_user_id=user.id,
                label=label,
            )
        except (LookupError, PermissionError, ValueError):
            return RedirectResponse("/settings/agents", status_code=303)
        return RedirectResponse(
            f"/settings/agents?new_token={plaintext}", status_code=303,
        )
```

with:

```python
    @html_router.post("/settings/agents/{agent_id}/tokens/create")
    def settings_agents_token_create(
        agent_id: str,
        request: Request,
        label: str = Form(...),
    ):
        user = _session_user_or_none(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        try:
            _, plaintext = auth_svc.create_agent_token(
                db_conn,
                agent_id=agent_id,
                owner_user_id=user.id,
                label=label,
            )
        except (LookupError, PermissionError, ValueError):
            return RedirectResponse("/settings/agents", status_code=303)

        sealed = issue_agent_token_flash(
            secret=session_secret, plaintext=plaintext
        )
        resp = RedirectResponse("/settings/agents", status_code=303)
        resp.set_cookie(
            key=AGENT_TOKEN_FLASH_COOKIE_NAME,
            value=sealed,
            max_age=AGENT_TOKEN_FLASH_MAX_AGE_SECONDS,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path="/",
        )
        return resp
```

- [ ] **Step 3: Add the imports at the top of `src/markland/web/routes_agents.py`**

Just below the existing `from markland.service import auth as auth_svc` line, add:

```python
from markland.service.agent_token_flash import (
    AGENT_TOKEN_FLASH_COOKIE_NAME,
    AGENT_TOKEN_FLASH_MAX_AGE_SECONDS,
    InvalidAgentTokenFlash,
    issue_agent_token_flash,
    read_agent_token_flash,
)
```

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run: `uv run pytest tests/test_settings_agents_page.py tests/test_service_agent_token_flash.py -q`
Expected: PASS (all tests, including the four new behaviours from Task 2 plus the original `test_settings_agents_requires_login`, `test_settings_agents_renders`, `test_settings_agents_create_via_form`).

- [ ] **Step 5: Run the full agent-route test suite to catch regressions**

Run: `uv run pytest tests/test_routes_agents.py tests/test_settings_agents_page.py tests/test_service_agent_token_flash.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/routes_agents.py
git commit -m "fix(web): mint agent tokens via signed flash cookie, drop query-string leak"
```

---

### Task 4: Sibling audit — re-grep for `?new_token=` and `?token=` in web/

**Files:** read-only audit.

Per the unit brief, `src/markland/web/identity_routes.py` returns user-token plaintext in a JSON response body (lines 85-94 per the explore note), which is a separate concern (HTTPS body, not URL). This task is a verification gate to confirm we haven't missed another redirect-style leak.

- [ ] **Step 1: Grep the web layer for residual leak patterns**

Run:

```bash
grep -rn "?new_token=" src/markland/web/ tests/
grep -rn "RedirectResponse.*?token=" src/markland/web/
grep -rn "query_params.get(\"new_token\")\|query_params.get(\"token\")" src/markland/web/
```

Expected: only references in test fixtures or `/verify?token=` magic-link patterns (which are intentional one-shot expiring tokens for the email-link flow, not an analogous leak). No hits inside `src/markland/web/routes_agents.py`.

- [ ] **Step 2: Skim `src/markland/web/identity_routes.py:85-94`**

Confirm it returns `{"plaintext": ...}` in a JSON body (response body over HTTPS, not URL/Referer/log-leaking surface). Add no code; this is a conscious scope-out.

- [ ] **Step 3: Document the audit result**

If steps 1 & 2 are clean, no commit needed for this task — proceed to Task 5. If a new leak is found, STOP and report back; the brainstorm scoped this plan to the agents route only.

---

### Task 5: Final verification — full test suite

**Files:** none.

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: PASS (no regressions in any other route, service, or template test).

- [ ] **Step 2: If any test outside the touched files fails, stop and investigate**

Likely suspects: any test that constructed a URL with `?new_token=` (none should exist outside `tests/test_settings_agents_page.py`, which Task 2 already updated — this is a sanity check).

- [ ] **Step 3: No commit — green run is the verification**

---

## Self-Review

**Spec coverage:**
- (a) Redirect URL has no `new_token` query param → `test_settings_agents_token_create_redirects_without_query_string` (Task 2).
- (b) Signed cookie is set → `test_settings_agents_token_create_sets_signed_flash_cookie` (Task 2).
- (c) Page renders the token once → first half of `test_settings_agents_renders_flash_token_once_then_clears` (Task 2).
- (d) Refreshing clears it → second half of the same test (Task 2).
- Sibling audit → Task 4.
- Pattern mirrors `pending_intent.py` → Task 1's module structure (constants, `_serializer`, issue/read pair, dedicated exception, `_SALT` namespacing).
- TTL choice (5 min) → encoded as `AGENT_TOKEN_FLASH_MAX_AGE_SECONDS = 5 * 60` and tested.
- Defence-in-depth against bookmarked stale `?new_token=` URLs → `test_settings_agents_ignores_query_string_new_token` (Task 2); GET handler in Task 3 simply never reads the query param.

**Placeholder scan:** No "TBD"/"similar to"/"add error handling" — every code block is complete and copy-pasteable.

**Type / name consistency:**
- Module path `markland.service.agent_token_flash` is used identically in the service file, both test files, and the route imports.
- Constants `AGENT_TOKEN_FLASH_COOKIE_NAME`, `AGENT_TOKEN_FLASH_MAX_AGE_SECONDS` and exception `InvalidAgentTokenFlash` and functions `issue_agent_token_flash` / `read_agent_token_flash` are spelled identically across Tasks 1, 2, and 3.
- The cookie's `secure` flag is derived from `request.url.scheme == "https"` (Task 3) — `routes_agents.py` does not currently take a `base_url` parameter (verified at `src/markland/web/app.py:642-647`), so we use the request scheme to mirror what `save_routes.py:42-51` does without changing the router signature.
