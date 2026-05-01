# Signed-In Banner Coverage and Overflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the signed-in nav banner shipped in PR #28 actually show on every page a signed-in user can land on, and stop it from clipping when the email is long.

**Context:** Live-tested PR #28 in incognito with `daveyhiles+banner-test@gmail.com` on 2026-05-01. The banner works on `/`, `/explore`, and `/d/<token>` as designed. Three real defects surfaced during the test, plus one already-logged FOLLOW-UPS entry covering a fourth: (1) `verify_sent.html` — the page rendered immediately after a user clicks their magic link in a "naked" sign-in flow (no `?next=`) — is a standalone, light-themed template that doesn't include the banner. It's the user's literal first-impression surface and the worst place to skip the banner. (2) `settings/tokens` — the page recommended in `verify_sent.html`'s "Go to your tokens" link — is also standalone and light-themed, and has its own bespoke "Sign out" link. (3) `settings/agents` likely has the same shape (sibling of tokens). (4) Banner overflow: `_signed_in_nav.html` uses `display: inline-flex` with no `min-width: 0`, no `flex-wrap`, and no email truncation, so a 31-char email like `daveyhiles+banner-test@gmail.com` clips "Your docs · Sign out" off the right edge of the viewport. Plus the FOLLOW-UPS entry: `/quickstart`, `/about`, `/security`, `/privacy`, `/terms`, `/alternatives` (and `/alternatives/<slug>`) inherit the include via `base.html` but their handlers don't pass `signed_in_user`, so the banner silently disappears when a signed-in user navigates to those pages.

**Architecture:** One small helper, one CSS fix, one template-migration pattern. Step 1 introduces `render_with_nav(tpl, request, conn, *, base_url, secret, **ctx)` in a new `web/render_helpers.py` module that wraps `tpl.render(...)` and auto-injects three context kwargs every base.html render needs: `signed_in_user` (from `signed_in_user_ctx`), `request` (FastAPI Request, for `_seo_meta`'s `request.url.path`), and `canonical_host` (scheme+host string, also for `_seo_meta`). PR #34 (login styling, merged 2026-05-01) established that base.html-extending templates need `request` + `canonical_host` — without them, `_seo_meta` raises a Jinja `UndefinedError`. The wrapper bakes these in so handlers in Tasks 3–5 don't have to thread them manually, and so we delete the duplicate `_canonical_host(request)` helper PR #34 added in `auth_routes.py`. Every page that wants the banner — base-extending or standalone-converting-to-base — calls this wrapper instead of the bare `tpl.render(...)`. Step 2 fixes the overflow in `_signed_in_nav.html` with `min-width: 0`, email truncation via `text-overflow: ellipsis` on a `max-width`'d span, and `flex-shrink: 0` on the action links so they survive even if the email overflows. Steps 3–6 migrate the four standalone templates (`verify_sent.html`, `settings_tokens.html`, `settings_agents.html`, `dashboard.html`) to extend `base.html` so they inherit the dark theme and the banner partial; their handlers convert to call `render_with_nav`. Step 7 retrofits the eight base-extending static-page handlers (landing, doc, explore are already done) to use the wrapper too, closing the FOLLOW-UPS coverage gap. Each step ships standalone with a green test suite.

**Tech Stack:** Python 3.12 / FastAPI / Jinja2 / pytest. No new deps. The new helper composes existing helpers (`signed_in_user_ctx`); the CSS edit is plain inline-style adjustment in the partial.

**Scope excluded:**
- Redesigning `settings/tokens`, `verify_sent`, or `settings/agents` (we just convert them to extend `base.html`; bigger redesigns can come later).
- Adding settings-section nav links across pages (e.g. tabs between Tokens / Agents / Account). Out of scope; one banner per page is enough today.
- Touching `device.html`, `device_done.html`, or `magic_link_sent.html`. The first two are CLI device-flow pages where the user may not be signed in; `magic_link_sent.html` is shown to anonymous users (we just sent them mail, they aren't authenticated yet). None of these need the banner.
- Touching `404.html`. The banner is nice-to-have on 404 but the static-pages task adds it for free if the 404 handler ends up using the wrapper; either way it's not load-bearing.
- Adding tests for static-page banner coverage (quickstart/about/etc). Their handlers are tiny, the wrapper is unit-tested in Task 1, and exhaustive E2E for every static page is YAGNI. Smoke-test one per pattern.
- Mobile-specific layouts. The overflow fix uses `min-width: 0` + truncation + `flex-shrink: 0` which is mobile-safe; explicit `@media` breakpoints are out of scope.

---

## File Structure

**New files:**
- `src/markland/web/render_helpers.py` — `render_with_nav(tpl, request, conn, *, base_url, secret, **ctx)` wrapper. Auto-injects `signed_in_user`, `request`, and `canonical_host` into the render context.
- `tests/test_render_helpers.py` — 5 unit tests for the wrapper.

**Modified files:**
- `src/markland/web/templates/_signed_in_nav.html` — overflow CSS fix (truncate email, `flex-shrink: 0` on links).
- `src/markland/web/templates/verify_sent.html` — extend `base.html`, drop the bespoke `<style>`.
- `src/markland/web/templates/settings_tokens.html` — extend `base.html`, drop the bespoke `<style>` and the bespoke "Sign out" link/JS.
- `src/markland/web/templates/settings_agents.html` — same shape as tokens.
- `src/markland/web/templates/dashboard.html` — same shape.
- `src/markland/web/auth_routes.py` — `verify_sent_tpl.render()` becomes `render_with_nav(...)`.
- `src/markland/web/identity_routes.py` — `settings_tpl.render(...)` becomes `render_with_nav(...)`.
- `src/markland/web/routes_agents.py` — same.
- `src/markland/web/dashboard.py` — same.
- `src/markland/web/app.py` — refactor the 11 existing `tpl.render(...)` call sites to use `render_with_nav(...)`. The three handlers already passing `signed_in_user` (landing, explore, view_document) drop their inline build code in favor of the wrapper. The eight static-page handlers (quickstart, about, security, privacy, terms, alternatives, alternatives/<slug>, 404 if reached via handler) gain the banner via the wrapper.
- `tests/test_signed_in_nav_e2e.py` — append tests for `verify_sent`, `settings/tokens`, `/quickstart` banner coverage and the overflow CSS rules. Roughly 4 new test functions.
- `docs/FOLLOW-UPS.md` — strike the "Signed-in nav banner missing on secondary pages" entry and the "settings_tokens.html logout fetch is wasteful" entry (we delete that JS in Task 5).

**Unchanged:**
- `src/markland/web/session_principal.py` — keep `session_user`, `session_principal`, `signed_in_user_ctx` as-is.
- `src/markland/web/templates/_signed_in_nav.html`'s structure (root `<span>`, partial gating). Only the CSS in the inline `style=` attributes changes.
- `magic_link_sent.html`, `device.html`, `device_done.html`, `invite.html`, `404.html`, `login.html`. Out of scope per Architecture.

---

## Task 1: `render_with_nav` wrapper helper (TDD)

**Files:**
- Create: `src/markland/web/render_helpers.py`
- Test: `tests/test_render_helpers.py`

Goal: a single function handlers can call instead of `tpl.render(**ctx)` that injects `signed_in_user` (the existing context dict) automatically. Eliminates the per-handler resolve-and-pass duplication that triggered the FOLLOW-UPS gap in the first place.

- [ ] **Step 1.1: Write the failing tests**

Create `/Users/daveyhiles/Developer/markland/tests/test_render_helpers.py`:

```python
"""Unit tests for web.render_helpers."""

from __future__ import annotations

from starlette.requests import Request

from markland.db import init_db
from markland.service.sessions import SESSION_COOKIE_NAME, issue_session
from markland.service.users import create_user
from markland.web.render_helpers import render_with_nav


SECRET = "test-session-secret"
BASE_URL = "http://testserver"


class _FakeTpl:
    """Stand-in for a Jinja Template that records its render kwargs."""

    def __init__(self):
        self.last_kwargs: dict | None = None

    def render(self, **kwargs):
        self.last_kwargs = kwargs
        return "rendered"


def _make_request(*, cookies: dict[str, str] | None = None, path: str = "/") -> Request:
    cookie_header = "; ".join(f"{k}={v}" for k, v in (cookies or {}).items())
    headers: list[tuple[bytes, bytes]] = []
    if cookie_header:
        headers.append((b"cookie", cookie_header.encode("ascii")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers,
        "query_string": b"",
    }
    return Request(scope)


def test_render_with_nav_injects_anon_context(tmp_path, monkeypatch):
    """All three auto-injected kwargs land for an anonymous request."""
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    tpl = _FakeTpl()
    req = _make_request()

    result = render_with_nav(
        tpl, req, conn, base_url=BASE_URL, secret=SECRET, foo="bar"
    )

    assert result == "rendered"
    assert tpl.last_kwargs == {
        "foo": "bar",
        "signed_in_user": None,
        "request": req,
        "canonical_host": BASE_URL,
    }


def test_render_with_nav_injects_dict_for_signed_in(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    user = create_user(conn, email="alice@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    tpl = _FakeTpl()
    req = _make_request(cookies={SESSION_COOKIE_NAME: cookie})

    render_with_nav(tpl, req, conn, base_url=BASE_URL, secret=SECRET)

    assert tpl.last_kwargs["signed_in_user"] == {"email": "alice@example.com"}
    assert tpl.last_kwargs["request"] is req
    assert tpl.last_kwargs["canonical_host"] == BASE_URL


def test_render_with_nav_caller_kwargs_take_precedence(tmp_path, monkeypatch):
    """Explicit kwargs (signed_in_user, request, canonical_host) override
    the auto-injected ones. Cheaper than building opt-out flags."""
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    user = create_user(conn, email="alice@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    tpl = _FakeTpl()
    req = _make_request(cookies={SESSION_COOKIE_NAME: cookie})

    render_with_nav(
        tpl, req, conn,
        base_url=BASE_URL, secret=SECRET,
        signed_in_user=None,
        canonical_host="https://override.example",
    )

    assert tpl.last_kwargs["signed_in_user"] is None
    assert tpl.last_kwargs["canonical_host"] == "https://override.example"
    assert tpl.last_kwargs["request"] is req  # not overridden


def test_render_with_nav_canonical_host_falls_back_to_request(tmp_path, monkeypatch):
    """When base_url is empty, derive canonical_host from the request URL.
    This mirrors the auth_routes._canonical_host() behavior PR #34 added."""
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    tpl = _FakeTpl()
    req = _make_request()

    render_with_nav(tpl, req, conn, base_url="", secret=SECRET)

    # The Starlette test request scope yields scheme=http, host=testserver
    # by default. Either way, canonical_host should be a non-empty string.
    assert tpl.last_kwargs["canonical_host"]
    assert tpl.last_kwargs["canonical_host"].startswith("http")


def test_render_with_nav_passes_through_other_kwargs(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    tpl = _FakeTpl()
    req = _make_request()

    render_with_nav(
        tpl, req, conn,
        base_url=BASE_URL, secret=SECRET,
        title="Hi", count=3, items=[1, 2],
    )

    assert tpl.last_kwargs["title"] == "Hi"
    assert tpl.last_kwargs["count"] == 3
    assert tpl.last_kwargs["items"] == [1, 2]
    # And the auto-injected ones are still there too.
    assert tpl.last_kwargs["signed_in_user"] is None
    assert tpl.last_kwargs["request"] is req
    assert tpl.last_kwargs["canonical_host"] == BASE_URL
```

- [ ] **Step 1.2: Run the tests to verify they fail**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_render_helpers.py -x -v
```

Expected: `ModuleNotFoundError: No module named 'markland.web.render_helpers'`.

- [ ] **Step 1.3: Implement the helper**

Create `/Users/daveyhiles/Developer/markland/src/markland/web/render_helpers.py`:

```python
"""Render helpers that auto-inject the signed-in nav + base.html context.

Every base.html-extending template needs three context kwargs that are
trivial to forget: `signed_in_user` (for the banner partial),
`request` (for the _seo_meta partial's `request.url.path`), and
`canonical_host` (for _seo_meta's og: and JSON-LD URLs). Forgetting any
of them is a silent failure: forgetting `signed_in_user` makes the
banner disappear; forgetting `request`/`canonical_host` raises a
Jinja `UndefinedError` mid-render.

Handlers that render a template with the signed-in nav banner used to
duplicate `signed_in_user = signed_in_user_ctx(...)` plus pass-through
boilerplate at every call site. That triplicated quickly (landing, doc,
explore) and got missed entirely on settings/tokens, settings/agents,
verify_sent, dashboard, and the static-page handlers — so the banner
silently disappeared whenever a signed-in user navigated to those.
PR #34 then added a duplicate `_canonical_host(request)` helper inside
`auth_routes.py` for the same purpose. This wrapper subsumes both.

`render_with_nav` does the lookups once and passes the results alongside
the caller's kwargs. Callers can override any of the three by passing
the kwarg explicitly; explicit wins.
"""

from __future__ import annotations

import sqlite3

from starlette.requests import Request

from markland.web.session_principal import signed_in_user_ctx


def _canonical_host(request: Request, base_url: str) -> str:
    """Return the canonical scheme://host string for this request.

    Prefers `base_url` when configured (immune to Host-header spoofing).
    Falls back to the request URL, honoring `x-forwarded-proto` so reverse-
    proxied HTTPS traffic yields the right scheme. Mirrors `_public_host`
    in `web/app.py` and the `_canonical_host` PR #34 added to auth_routes;
    consolidates both into one place.
    """
    if base_url:
        return base_url.rstrip("/")
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{scheme}://{request.url.netloc}"


def render_with_nav(
    tpl,
    request: Request,
    conn: sqlite3.Connection,
    *,
    base_url: str = "",
    secret: str | None = None,
    **ctx,
) -> str:
    """Render `tpl` with the three base.html context kwargs auto-injected.

    Auto-injects:
        - signed_in_user: dict with `email`, or None (for the banner partial)
        - request: the FastAPI Request itself (for _seo_meta)
        - canonical_host: scheme+host string (for _seo_meta + JSON-LD)

    Caller-provided kwargs win — pass `signed_in_user=None` (etc.) to
    override the auto-resolution. Used today for: admin-impersonation
    previews, tests asserting on a specific banner state, etc.
    """
    if "signed_in_user" not in ctx:
        ctx["signed_in_user"] = signed_in_user_ctx(request, conn, secret=secret)
    if "request" not in ctx:
        ctx["request"] = request
    if "canonical_host" not in ctx:
        ctx["canonical_host"] = _canonical_host(request, base_url)
    return tpl.render(**ctx)
```

- [ ] **Step 1.4: Run the tests to verify they pass**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_render_helpers.py -x -v
```

Expected: 5 tests pass.

- [ ] **Step 1.5: Commit**

```bash
cd /Users/daveyhiles/Developer/markland && BYPASS_BRANCH_CHECK=1 git add src/markland/web/render_helpers.py tests/test_render_helpers.py && BYPASS_BRANCH_CHECK=1 git commit -m "$(cat <<'EOF'
feat(web): render_with_nav helper for auto-injecting signed_in_user

Three handlers (landing, view_document, explore) used to triplicate the
`signed_in_user = signed_in_user_ctx(...)` resolve-and-pass dance, and
4+ other handlers (verify_sent, settings/tokens, settings/agents,
dashboard, all static pages) just forgot it entirely — banner silently
vanished there. This wrapper does the cookie lookup once; callers that
need to override pass signed_in_user= explicitly.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

(Note: this plan is executed on a feature branch from `main`. The repo's pre-commit hook refuses commits on non-main branches in the primary worktree; `BYPASS_BRANCH_CHECK=1` is the documented escape hatch.)

---

## Task 2: Banner overflow CSS fix

**Files:**
- Modify: `src/markland/web/templates/_signed_in_nav.html`
- Test: `tests/test_signed_in_nav_e2e.py` (append a CSS-presence assertion)

Goal: a long email truncates with ellipsis instead of clipping the action links off the viewport. The page chrome (Markland brand + Explore/Docs links) keeps its position; the email shrinks; "Your docs · Sign out" never disappears.

- [ ] **Step 2.1: Write the failing assertion**

Append to `/Users/daveyhiles/Developer/markland/tests/test_signed_in_nav_e2e.py`:

```python
def test_banner_email_truncates_when_long(harness):
    """Long emails must not push 'Your docs / Sign out' off the viewport.

    The fix is CSS: max-width + text-overflow: ellipsis on the email span,
    plus flex-shrink: 0 on the action links. Asserting CSS in HTML is a
    weak signal but enough to catch a future refactor that strips the
    rules wholesale.
    """
    client, conn = harness
    user = create_user(conn, email="long+banner-test+long-alias@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    client.cookies.set(SESSION_COOKIE_NAME, cookie)

    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    # The email itself appears.
    assert "long+banner-test+long-alias@example.com" in body
    # The truncation rules are present in the partial's inline styles.
    assert "text-overflow:ellipsis" in body or "text-overflow: ellipsis" in body
    assert "flex-shrink:0" in body or "flex-shrink: 0" in body
```

- [ ] **Step 2.2: Run the test to verify it fails**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_signed_in_nav_e2e.py::test_banner_email_truncates_when_long -x -v
```

Expected: `AssertionError` on `text-overflow:ellipsis` or `flex-shrink:0` — neither rule exists in the current partial.

- [ ] **Step 2.3: Update the partial**

Replace the entire file `/Users/daveyhiles/Developer/markland/src/markland/web/templates/_signed_in_nav.html`:

```html
{% if signed_in_user %}
<span class="signed-in-nav" style="display:inline-flex; align-items:center; gap:0.6rem; font-size:0.85rem; color:var(--muted); margin-left:0.5rem; min-width:0; max-width:100%;">
  <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0;">Signed in as <strong style="color:var(--text); font-weight:600;">{{ signed_in_user.email }}</strong></span>
  <a href="/explore?view=mine" style="color:var(--text); text-decoration:underline; text-underline-offset:2px; flex-shrink:0;">Your docs</a>
  <form method="post" action="/api/auth/logout" style="margin:0; display:inline; flex-shrink:0;">
    <button type="submit" style="background:none; border:0; padding:0; font:inherit; color:var(--text); text-decoration:underline; text-underline-offset:2px; cursor:pointer;">Sign out</button>
  </form>
</span>
{% endif %}
```

The substantive changes vs. the current file:
- Outer span gains `min-width:0; max-width:100%;` so it can shrink inside its parent flex container.
- The "Signed in as <email>" inner span gains `overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0;` so the email truncates with ellipsis when wide.
- The "Your docs" link and the form-button container gain `flex-shrink:0` so the action items keep their width even if the email block shrinks.

- [ ] **Step 2.4: Run the new test plus the existing banner suite**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_signed_in_nav_e2e.py -x -v
```

Expected: all tests pass (existing 5 + the new truncation test).

- [ ] **Step 2.5: Commit**

```bash
cd /Users/daveyhiles/Developer/markland && BYPASS_BRANCH_CHECK=1 git add src/markland/web/templates/_signed_in_nav.html tests/test_signed_in_nav_e2e.py && BYPASS_BRANCH_CHECK=1 git commit -m "$(cat <<'EOF'
fix(web): truncate long emails in signed-in nav instead of clipping

The flex container had no min-width:0 / no truncation rule on the email
span, so a 31-char email like "daveyhiles+banner-test@gmail.com" pushed
"Your docs · Sign out" off the right edge of the viewport and out of
view. Add ellipsis truncation on the email and flex-shrink:0 on the
action links so they always stay visible.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Migrate `verify_sent.html` to extend base.html

**Files:**
- Modify: `src/markland/web/templates/verify_sent.html`
- Modify: `src/markland/web/auth_routes.py`
- Test: `tests/test_signed_in_nav_e2e.py` (append a verify-sent banner test)

Goal: the post-magic-link "Signed in" page renders dark-themed, with the banner, in `base.html`'s layout.

- [ ] **Step 3.1: Append failing test**

Append to `/Users/daveyhiles/Developer/markland/tests/test_signed_in_nav_e2e.py`:

```python
def test_verify_sent_page_shows_banner(harness):
    """A naked sign-in (no return_to) lands on the verify_sent page.

    Pre-fix this rendered as a standalone light-themed page with no
    banner — the worst place for that gap, since it's the user's first
    impression after sign-in.
    """
    from markland.service.magic_link import issue_magic_link_token

    client, _ = harness
    token = issue_magic_link_token("alice@example.com", secret=SECRET)
    r = client.get(f"/verify?token={token}", follow_redirects=False)
    assert r.status_code == 200  # naked sign-in renders verify_sent
    body = r.text
    # Banner present
    assert "Signed in as" in body
    assert "alice@example.com" in body
    # Inherits base.html chrome
    assert 'href="/explore"' in body  # site-nav links
```

- [ ] **Step 3.2: Run the test to verify it fails**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_signed_in_nav_e2e.py::test_verify_sent_page_shows_banner -x -v
```

Expected: fails on `"Signed in as" in body` — the standalone template has no banner.

- [ ] **Step 3.3: Replace `verify_sent.html` with a base-extending version**

Replace the entire file `/Users/daveyhiles/Developer/markland/src/markland/web/templates/verify_sent.html`:

```html
{% extends "base.html" %}

{% block title %}Signed in &middot; Markland{% endblock %}

{% block content %}
<section style="max-width: 32rem; margin: 4rem auto; padding: 0 1.5rem;">
  <h1 style="font-size: 1.6rem; margin-bottom: 0.75rem;">Signed in</h1>
  <p>You're signed in. Go to <a href="/settings/tokens" style="color:var(--blue); text-decoration:underline; text-underline-offset:2px;">your tokens</a> to create an API token for your MCP client, or visit <a href="/explore?view=mine" style="color:var(--blue); text-decoration:underline; text-underline-offset:2px;">Your docs</a>.</p>
</section>
{% endblock %}
```

The new template:
- Extends `base.html` → gets dark theme, brand mark, banner partial, site nav.
- Replaces the bare-bones `<h1>Signed in</h1>` + single link with a slightly richer "what's next" copy that points at both Tokens (for MCP setup) and "Your docs" (for human users who want to see Markland working).

- [ ] **Step 3.4: Update the auth_routes handler to use `render_with_nav` and delete the duplicate `_canonical_host` helper**

Edit `/Users/daveyhiles/Developer/markland/src/markland/web/auth_routes.py`. PR #34 added a private `_canonical_host(request)` helper at lines ~60–64 plus a `request + canonical_host` thread through the `/login` handler (lines ~67–75). The wrapper now subsumes both. Make three changes:

(a) Add the import at the top alongside other web imports:

```python
from markland.web.render_helpers import render_with_nav
```

(b) Delete the `_canonical_host(request)` inner helper (the 5-line `def _canonical_host` block PR #34 added).

(c) Update the `/login` handler to use `render_with_nav` and drop the manual `request=`/`canonical_host=` kwargs:

```python
    @router.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next: str | None = None) -> HTMLResponse:
        safe_next = safe_return_to(next)
        return HTMLResponse(
            render_with_nav(
                login_tpl, request, db_conn,
                base_url=base_url, secret=session_secret,
                next=safe_next,
            )
        )
```

(d) Update the `verify_sent` render around line 169 from:

```python
        if target == "/":
            resp = HTMLResponse(verify_sent_tpl.render())
        else:
            resp = RedirectResponse(target, status_code=303)
```

to:

```python
        if target == "/":
            resp = HTMLResponse(
                render_with_nav(
                    verify_sent_tpl, request, db_conn,
                    base_url=base_url, secret=session_secret,
                )
            )
        else:
            resp = RedirectResponse(target, status_code=303)
```

The build_auth_router signature already accepts `db_conn` and `session_secret` and `base_url` — all available in scope. No new constructor changes.

Do NOT touch `magic_link_sent_tpl.render(...)` in the same file — that template is shown to anonymous users (we just sent them mail, they aren't authenticated yet), and it's not on the conversion list per the Architecture's Out-of-scope list.

- [ ] **Step 3.5: Run the targeted test plus the full auth-route suite**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_signed_in_nav_e2e.py tests/test_auth_routes.py -x -v
```

Expected: all pass. The auth-route suite already has `test_verify_page_renders` which checked for status 200/302/303 — that still holds because the naked-signin path still returns 200.

- [ ] **Step 3.6: Commit**

```bash
cd /Users/daveyhiles/Developer/markland && BYPASS_BRANCH_CHECK=1 git add src/markland/web/templates/verify_sent.html src/markland/web/auth_routes.py tests/test_signed_in_nav_e2e.py && BYPASS_BRANCH_CHECK=1 git commit -m "$(cat <<'EOF'
fix(web): verify_sent page extends base.html, gets the signed-in banner

The post-magic-link Signed-in page was a standalone light-themed
template with no banner — the user's first impression after sign-in
on a naked /login flow showed "Signed in" floating on a white page
with no Markland chrome. Convert to extend base.html so it inherits
the dark theme, the site nav, and the signed-in banner partial.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Migrate `settings_tokens.html` to extend base.html, drop bespoke sign-out

**Files:**
- Modify: `src/markland/web/templates/settings_tokens.html`
- Modify: `src/markland/web/identity_routes.py`
- Test: `tests/test_signed_in_nav_e2e.py` (append a settings-tokens banner test)

Goal: `/settings/tokens` renders with the dark theme, the banner, and uses the partial's "Sign out" form instead of the bespoke fetch-based one.

- [ ] **Step 4.1: Read the existing template to know what to preserve**

```bash
cd /Users/daveyhiles/Developer/markland && cat src/markland/web/templates/settings_tokens.html
```

Capture the body content (token list, create form) — these stay; only the wrapper chrome and the trailing "Sign out" link/JS go.

- [ ] **Step 4.2: Append failing test**

Append to `/Users/daveyhiles/Developer/markland/tests/test_signed_in_nav_e2e.py`:

```python
def test_settings_tokens_page_shows_banner_and_drops_bespoke_signout(harness):
    """Settings page should use the shared signed-in banner, not its own
    bespoke 'Sign out' fetch link."""
    client, conn = harness
    user = create_user(conn, email="bob@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    client.cookies.set(SESSION_COOKIE_NAME, cookie)

    r = client.get("/settings/tokens")
    assert r.status_code == 200
    body = r.text
    # Banner present
    assert "Signed in as" in body
    assert "bob@example.com" in body
    # Bespoke sign-out fetch JS removed.
    assert "fetch('/api/auth/logout'" not in body
```

- [ ] **Step 4.3: Run the test to verify it fails**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_signed_in_nav_e2e.py::test_settings_tokens_page_shows_banner_and_drops_bespoke_signout -x -v
```

Expected: fails on `"Signed in as" in body` (no banner) and/or `"fetch('/api/auth/logout'" not in body` (the bespoke fetch is still there).

- [ ] **Step 4.4: Read the current template, then replace with a base-extending version**

Read the current file first to capture the inner content (the token-list table + create-token form), then replace the wrapper:

```bash
cd /Users/daveyhiles/Developer/markland && cat src/markland/web/templates/settings_tokens.html
```

Note any unique elements (revealed-token panel, revoke endpoints, JSON-rendering of new-token, etc.) so they survive the migration. Then write the new template:

```html
{% extends "base.html" %}

{% block title %}Tokens &middot; Markland{% endblock %}

{% block content %}
<section style="max-width: 40rem; margin: 3rem auto; padding: 0 1.5rem;">
  <h1 style="font-size: 1.6rem; margin-bottom: 0.5rem;">API tokens for {{ email }}</h1>
  <p style="color: var(--muted); margin-bottom: 2rem;">Use these tokens in your MCP client's <code style="font-family: var(--font-mono); background: var(--surface-2); border: 1px solid var(--outline-hairline); padding: 0.1rem 0.3rem; border-radius: 4px; font-size: 0.85em;">Authorization: Bearer ...</code> header.</p>

  <h2 style="font-size: 1.15rem; margin-bottom: 0.5rem;">Create a token</h2>
  <form method="post" action="/api/tokens" style="display:flex; gap:0.5rem; align-items:center; margin-bottom: 2rem;">
    <input type="text" name="label" placeholder="e.g. laptop" style="flex:1; padding: 0.5rem 0.75rem; border:1px solid var(--outline); background:var(--surface-2); color:var(--text); border-radius: 6px; font: inherit;" />
    <button type="submit" style="padding: 0.5rem 1rem; background: var(--surface-2); color: var(--text); border:1px solid var(--outline); border-radius: 6px; cursor: pointer; font: inherit;">Create</button>
  </form>

  <h2 style="font-size: 1.15rem; margin-bottom: 0.5rem;">Your tokens</h2>
  {% if tokens %}
  <table style="width:100%; border-collapse: collapse; font-size: 0.92rem;">
    <thead>
      <tr style="text-align:left; color: var(--muted); border-bottom: 1px solid var(--outline-hairline);">
        <th style="padding: 0.5rem 0.4rem;">Label</th>
        <th style="padding: 0.5rem 0.4rem;">Created</th>
        <th style="padding: 0.5rem 0.4rem;">Last used</th>
        <th style="padding: 0.5rem 0.4rem;"></th>
      </tr>
    </thead>
    <tbody>
      {% for t in tokens %}
      <tr style="border-bottom: 1px solid var(--outline-hairline);">
        <td style="padding: 0.5rem 0.4rem;">{{ t.label or "—" }}</td>
        <td style="padding: 0.5rem 0.4rem; color: var(--muted);">{{ t.created_at[:10] }}</td>
        <td style="padding: 0.5rem 0.4rem; color: var(--muted);">{{ t.last_used_at[:10] if t.last_used_at else "—" }}</td>
        <td style="padding: 0.5rem 0.4rem; text-align:right;">
          <form method="post" action="/api/tokens/{{ t.id }}/revoke" style="display:inline; margin:0;">
            <button type="submit" style="background:none; border:0; padding:0; color: var(--red); text-decoration:underline; text-underline-offset:2px; cursor:pointer; font: inherit;">Revoke</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p style="color: var(--muted);">No tokens yet.</p>
  {% endif %}

  {% if new_token %}
  <div style="margin-top: 2rem; padding: 1rem; background: var(--surface-2); border: 1px solid var(--outline); border-radius: 8px;">
    <p style="margin-bottom: 0.5rem;"><strong>New token created.</strong> Copy it now — it won't be shown again.</p>
    <code style="font-family: var(--font-mono); background: #000; color: var(--text); padding: 0.5rem; border-radius: 4px; display:block; overflow-x: auto;">{{ new_token }}</code>
  </div>
  {% endif %}
</section>
{% endblock %}
```

If the existing template's structure differs (e.g. different revoke endpoint, different field names), preserve those — read the file first and adapt the new template to match. The structural change is wrapper-only: extend base, drop bespoke styles, drop bespoke "Sign out" link/JS.

- [ ] **Step 4.5: Update `identity_routes.py` to use `render_with_nav`**

Edit `/Users/daveyhiles/Developer/markland/src/markland/web/identity_routes.py`. Find the `settings_tpl.render(...)` call (around line 62 area) and replace with `render_with_nav(settings_tpl, request, db_conn, base_url=base_url, secret=session_secret, ...)`.

Add the import at the top:

```python
from markland.web.render_helpers import render_with_nav
```

The handler may not currently take `request` as a parameter — if so, add `request: Request` to its signature (FastAPI handles injection automatically). If the handler is wired through a build_router pattern that doesn't have `db_conn` / `session_secret` in scope, hoist them in via the router builder's closure.

- [ ] **Step 4.6: Run the targeted test plus broader auth/identity tests**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_signed_in_nav_e2e.py tests/test_auth_routes.py -x -v
```

Expected: all pass.

- [ ] **Step 4.7: Commit**

```bash
cd /Users/daveyhiles/Developer/markland && BYPASS_BRANCH_CHECK=1 git add src/markland/web/templates/settings_tokens.html src/markland/web/identity_routes.py tests/test_signed_in_nav_e2e.py && BYPASS_BRANCH_CHECK=1 git commit -m "$(cat <<'EOF'
fix(web): settings/tokens extends base.html, banner replaces bespoke signout

/settings/tokens was a standalone light-themed page with its own
fetch-based "Sign out" link (the wasteful one logged in FOLLOW-UPS).
Convert to extend base.html so it inherits the dark theme + the shared
signed-in banner; the partial's <form> sign-out replaces the bespoke
fetch entirely.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Migrate `settings_agents.html` and `dashboard.html`

**Files:**
- Modify: `src/markland/web/templates/settings_agents.html`
- Modify: `src/markland/web/templates/dashboard.html`
- Modify: `src/markland/web/routes_agents.py`
- Modify: `src/markland/web/dashboard.py`

Goal: same migration as Task 4, applied to the two remaining standalone signed-in templates. No new tests — Task 4's pattern is the regression guard, and adding identical tests for two more pages is YAGNI. Smoke-test in the manual verification at the end.

- [ ] **Step 5.1: Read both current templates to capture their inner content**

```bash
cd /Users/daveyhiles/Developer/markland && cat src/markland/web/templates/settings_agents.html src/markland/web/templates/dashboard.html
```

Note the body content (agent list, dashboard widgets, etc.) — these stay; only the wrapper chrome goes.

- [ ] **Step 5.2: Convert `settings_agents.html` to extend base**

Replace the file with a `{% extends "base.html" %}` shell containing the inner content under a `{% block content %}`. Use the same styling tokens as Task 4's settings_tokens conversion (max-width section, h1 + h2 hierarchy, inherited theme variables). Drop any bespoke `<head>`, `<style>`, or "Sign out" link.

If the current template has unique elements not in settings_tokens (e.g. agent-token reveal modal, agent-creation form), preserve those structurally inside the new `{% block content %}`.

- [ ] **Step 5.3: Update `routes_agents.py` to use `render_with_nav`**

Find the `settings_tpl.render(...)` call (around line 150 area). Same edit pattern as Task 4 step 4.5:
- Add `from markland.web.render_helpers import render_with_nav` at the top.
- Replace the bare render call with `render_with_nav(settings_tpl, request, db_conn, base_url=base_url, secret=session_secret, ...)`.
- Ensure `request: Request` is in the handler signature.

- [ ] **Step 5.4: Convert `dashboard.html` to extend base**

Same pattern as steps 5.2.

- [ ] **Step 5.5: Update `dashboard.py` to use `render_with_nav`**

Find the `tpl.render(...)` call (line 27 area). Apply the same wrapper change.

- [ ] **Step 5.6: Run the broader suite to verify no regressions**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/ -x 2>&1 | tail -5
```

Expected: full suite passes. The most likely regression is in `test_settings_agents.py` or `test_routes_agents.py` if either asserts on the literal HTML structure of the old standalone template — if so, update those assertions to match the new structure (preserve behavior assertions, drop layout assertions).

- [ ] **Step 5.7: Commit**

```bash
cd /Users/daveyhiles/Developer/markland && BYPASS_BRANCH_CHECK=1 git add src/markland/web/templates/settings_agents.html src/markland/web/templates/dashboard.html src/markland/web/routes_agents.py src/markland/web/dashboard.py && BYPASS_BRANCH_CHECK=1 git commit -m "$(cat <<'EOF'
fix(web): settings/agents and /dashboard extend base.html, get the banner

Same shape as the settings/tokens conversion: standalone light-themed
templates were silently dropping the signed-in banner and rendering on
white instead of the dark Markland chrome. Convert both to extend
base.html and route through render_with_nav.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Retrofit static-page handlers + the three already-instrumented handlers to use `render_with_nav`

**Files:**
- Modify: `src/markland/web/app.py` — 11 `tpl.render(...)` call sites.
- Test: `tests/test_signed_in_nav_e2e.py` (one smoke test for `/quickstart` covering the static-page pattern).

Goal: every base.html-extending handler routes through `render_with_nav`, so the banner appears on `/quickstart`, `/about`, `/security`, `/privacy`, `/terms`, `/alternatives`, `/alternatives/<slug>`, and `/`, `/explore`, `/d/<token>` for cookie-auth'd users. The three already-fixed handlers (landing, explore, view_document) drop their inline `signed_in_user_ctx(...)` resolve in favor of the wrapper, eliminating the triplication.

- [ ] **Step 6.1: Append failing smoke test**

Append to `/Users/daveyhiles/Developer/markland/tests/test_signed_in_nav_e2e.py`:

```python
def test_signed_in_static_page_shows_banner(harness):
    """Static base.html-extending pages (quickstart/about/etc.) inherit the
    partial via base.html, but their handlers used to forget to pass
    signed_in_user. After the render_with_nav refactor, they all show the
    banner."""
    client, conn = harness
    user = create_user(conn, email="dan@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    client.cookies.set(SESSION_COOKIE_NAME, cookie)

    r = client.get("/quickstart")
    assert r.status_code == 200
    body = r.text
    assert "Signed in as" in body
    assert "dan@example.com" in body
```

- [ ] **Step 6.2: Run the test to verify it fails**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_signed_in_nav_e2e.py::test_signed_in_static_page_shows_banner -x -v
```

Expected: fails on `"Signed in as" in body`.

- [ ] **Step 6.3: Refactor the 11 call sites in `app.py`**

Read the file to confirm all current `*_tpl.render(...)` sites:

```bash
cd /Users/daveyhiles/Developer/markland && grep -n "tpl\.render" src/markland/web/app.py
```

Expected output: roughly 11 lines like `landing_tpl.render`, `quickstart_tpl.render`, `about_tpl.render`, `security_tpl.render`, `privacy_tpl.render`, `terms_tpl.render`, `alternatives_tpl.render`, `alternative_tpl.render`, `explore_tpl.render` (×2 — view=mine and public branches), and `document_tpl.render`.

For each one, change `XXX_tpl.render(**ctx)` to `render_with_nav(XXX_tpl, request, db_conn, base_url=base_url, secret=session_secret, **ctx)`.

For the **landing**, **explore**, **view_document** handlers (already passing `signed_in_user`): drop the inline `signed_in_user = signed_in_user_ctx(...)` line entirely — the wrapper handles it. Specifically:

In `landing` (around line 460):

```python
@app.get("/", response_class=HTMLResponse)
def landing(request: Request, signup: str | None = None):
    docs = list_featured_and_recent_public(db_conn, limit=4)
    cards = [_doc_to_card(d) for d in docs]
    signup_state = signup if signup in ("ok", "invalid") else None
    return HTMLResponse(
        render_with_nav(
            landing_tpl, request, db_conn,
            base_url=base_url, secret=session_secret,
            **_seo_ctx(request, base_url, page_template=landing_tpl),
            docs=cards,
            mcp_config_json=mcp_snippet_json,
            signup=signup_state,
        )
    )
```

(The `signed_in_user_ctx(...)` line is removed.)

In `explore`: keep the cookie-principal fallback (it's needed for `view=mine` reachability, not for the banner), but drop the trailing `signed_in_user = signed_in_user_ctx(...)` assignment and pass-through. Both render calls become `render_with_nav(explore_tpl, request, db_conn, base_url=base_url, secret=session_secret, ...)`.

In `view_document`: drop the trailing `signed_in_user = signed_in_user_ctx(...)` line. The render call becomes `render_with_nav(document_tpl, request, db_conn, base_url=base_url, secret=session_secret, ...)`.

Keep the `from markland.web.session_principal import session_principal, signed_in_user_ctx` import for now — `session_principal` is still used by `explore` for the `view=mine` lookup, and `signed_in_user_ctx` is no longer used directly in `app.py` but importing it is harmless and removing it is bikeshedding. Actually — let me prescribe the cleanup precisely:

After the refactor, only `session_principal` is referenced in `app.py`. Update the import to:

```python
from markland.web.session_principal import session_principal
```

And add the new wrapper import:

```python
from markland.web.render_helpers import render_with_nav
```

The static-page handlers (around `app.py` lines 332–395) all become:

```python
@app.get("/quickstart", response_class=HTMLResponse)
def quickstart(request: Request):
    return HTMLResponse(
        render_with_nav(
            quickstart_tpl, request, db_conn,
            base_url=base_url, secret=session_secret,
            **_seo_ctx(request, base_url, page_template=quickstart_tpl),
        )
    )
```

Each handler currently has `request: Request` already (or just `()` — if empty, add `request: Request`). For handlers with extra route params (e.g. `alternatives/<slug>` takes `slug: str`), preserve those.

- [ ] **Step 6.4: Run the targeted test plus the full suite**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/ -x 2>&1 | tail -10
```

Expected: full suite passes. If a test that previously asserted `signed_in_user not in r.text` now fires (e.g. an old static-page test that assumed no banner), update the assertion to match the new state.

- [ ] **Step 6.5: Commit**

```bash
cd /Users/daveyhiles/Developer/markland && BYPASS_BRANCH_CHECK=1 git add src/markland/web/app.py tests/test_signed_in_nav_e2e.py && BYPASS_BRANCH_CHECK=1 git commit -m "$(cat <<'EOF'
refactor(web): route all base.html renders through render_with_nav

Eleven call sites in app.py used to either (a) triplicate the
signed_in_user_ctx resolve-and-pass dance (landing, explore, view_doc)
or (b) skip it entirely (quickstart, about, security, privacy, terms,
alternatives, alternatives/<slug>) so the banner silently disappeared
when a signed-in user navigated there. All now go through the
render_with_nav wrapper. Closes the FOLLOW-UPS coverage gap.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Strike done items in FOLLOW-UPS

**Files:**
- Modify: `docs/FOLLOW-UPS.md`

Goal: the two FOLLOW-UPS entries this plan resolves are struck (`~~`) and dated. The rest of the file is untouched.

- [ ] **Step 7.1: Find the entries to strike**

```bash
cd /Users/daveyhiles/Developer/markland && grep -nE "Signed-in nav banner missing|settings_tokens.html logout fetch|view_document cookie/Bearer split" docs/FOLLOW-UPS.md
```

Expected output: line numbers for the three entries:
- "Signed-in nav banner missing on secondary pages"
- "settings_tokens.html logout fetch is wasteful"
- "view_document cookie/Bearer split for owner controls" — partially still relevant; we're fixing the banner inconsistency but not the `is_owner` fallback. Read it carefully and only strike if all sub-points are addressed.

- [ ] **Step 7.2: Strike the two fully-addressed entries**

Edit `docs/FOLLOW-UPS.md`. Replace:

```markdown
- **Signed-in nav banner missing on secondary pages** — `_signed_in_nav.html`
  renders on `/`, `/d/<token>`, and `/explore` because those handlers pass
  `signed_in_user_ctx(...)` into the render context. Other base.html-extending
  pages (`/quickstart`, `/about`, `/security`, `/competitors/...`, etc.) inherit
  the include but their handlers don't pass the dict, so the banner silently
  disappears when a signed-in user navigates to them via the top-nav and
  reappears when they come back. Either factor a tiny `_render_with_nav(...)`
  helper that injects `signed_in_user` for every base.html render, or extract a
  middleware that hangs `signed_in_user` off `request.state` so all templates
  can pull from there. Cosmetic but visible.
```

with:

```markdown
- **~~Signed-in nav banner missing on secondary pages~~** — Fixed 2026-05-01.
  Added `markland.web.render_helpers.render_with_nav(tpl, request, conn, *,
  secret, **ctx)` and routed every base.html render through it. Banner now
  shows on `/quickstart`, `/about`, `/security`, `/privacy`, `/terms`,
  `/alternatives`, and `/alternatives/<slug>` in addition to the original
  three pages. Plan: `docs/plans/2026-05-01-signed-in-banner-coverage-and-
  overflow.md`.
```

And replace:

```markdown
- **`settings_tokens.html` logout fetch is wasteful but not broken** —
  `templates/settings_tokens.html:79` calls `fetch('/api/auth/logout',
  {method:'POST'})` with no `Accept` header. After PR #28 the server returns
  a 303 redirect to `/` for non-JSON callers, so fetch transparently follows
  the redirect → fetches `/` → JS discards the body and forces
  `location.href = '/login'`. Cookie deletion happens correctly but the
  browser does an unnecessary GET. Add `headers: {'Accept':
  'application/json'}` (or `redirect: 'manual'`) to the fetch.
```

with:

```markdown
- **~~`settings_tokens.html` logout fetch is wasteful but not broken~~** —
  Fixed 2026-05-01 by deleting the bespoke fetch entirely. The page now
  extends base.html and uses the shared `_signed_in_nav.html` partial's
  form-POST sign-out. Plan: `docs/plans/2026-05-01-signed-in-banner-
  coverage-and-overflow.md`.
```

The `view_document` cookie/Bearer split entry stays as-is — this plan doesn't fix the `is_owner` fallback (separate concern from the banner).

- [ ] **Step 7.3: Commit**

Per the user's saved feedback (`feedback_docs_direct_push.md`), docs-only diffs go direct to main. But this plan's commits are on a feature branch — when this branch merges, the docs change ships with it. Don't direct-push; let the PR carry it.

```bash
cd /Users/daveyhiles/Developer/markland && BYPASS_BRANCH_CHECK=1 git add docs/FOLLOW-UPS.md && BYPASS_BRANCH_CHECK=1 git commit -m "$(cat <<'EOF'
docs(follow-ups): strike banner-coverage and bespoke-signout entries

Both addressed by the render_with_nav refactor + settings_tokens
migration to base.html. Plan: docs/plans/2026-05-01-signed-in-banner-
coverage-and-overflow.md.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Final verification + PR

- [ ] **Step 8.1: Full suite**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/
```

Expected: all tests green. The branch should add roughly 4 (Task 1) + 4 (Task 2/3/4/6) = 8 new test functions, so the count goes from ~794 → ~802.

- [ ] **Step 8.2: Manual smoke (operator verification, post-deploy)**

After merge + auto-deploy, in incognito:

1. `https://markland.dev/login` (or `markland.fly.dev/login` if cutover hasn't happened) → enter `daveyhiles+banner-test-2@gmail.com` → check inbox → click magic link.
2. Land on `/verify_sent` (the post-magic-link page) — confirm dark theme, banner at top with "Signed in as daveyhiles+banner-test-2@gmail.com · Your docs · Sign out". The "your tokens" link should be visible inside the page body.
3. Click "Your docs" — land on `/explore?view=mine`, banner still there.
4. Click "Markland" brand link — land on `/`, banner there.
5. Click "Docs" in the top nav — land on `/quickstart`, banner there. (Pre-fix: it would disappear here.)
6. Visit `/about`, `/security`, `/privacy`, `/terms` — banner stays on each.
7. Click "your tokens" link from the verify_sent page (or visit `/settings/tokens` directly) — confirm dark theme, banner present, no bespoke "Sign out" link below the token table.
8. Resize the window to ~600px wide — confirm the email truncates with `…` instead of clipping "Your docs · Sign out" off-screen.
9. Click the banner's "Sign out" button — confirm 303 redirect to `/` and banner disappears.

- [ ] **Step 8.3: Push and open a PR**

```bash
cd /Users/daveyhiles/Developer/markland && git push -u origin feat/signed-in-banner-coverage
gh pr create --title "feat(web): banner coverage on every signed-in page + overflow fix" --body "$(cat <<'EOF'
## Summary
- Add \`render_with_nav(tpl, request, conn, *, secret, **ctx)\` helper that auto-injects \`signed_in_user\` into the template context. Three handlers used to triplicate the resolve-and-pass dance; ~8 others forgot it entirely so the banner silently disappeared.
- Migrate four standalone, light-themed templates (\`verify_sent\`, \`settings_tokens\`, \`settings_agents\`, \`dashboard\`) to extend \`base.html\` so they inherit the dark theme + the shared signed-in banner. Drop the bespoke \`fetch('/api/auth/logout')\` from \`settings_tokens.html\`; the partial's form-POST replaces it.
- Fix banner overflow: long emails (\`daveyhiles+banner-test@gmail.com\`) used to clip "Your docs · Sign out" off the right edge. Added \`min-width:0\` + ellipsis truncation on the email and \`flex-shrink:0\` on the action links.
- Strike two FOLLOW-UPS entries (banner-coverage gap + wasteful settings-tokens logout fetch).

## Context
Live-tested PR #28 in incognito with \`daveyhiles+banner-test@gmail.com\`. The banner shipped correctly on \`/\`, \`/explore\`, and \`/d/<token>\` but vanished on the post-magic-link \`verify_sent\` page (the user's first impression after sign-in), on \`/settings/tokens\` (the next page recommended to them), and on every static page (\`/quickstart\`, \`/about\`, etc.). The email also clipped the action links off-screen on a not-particularly-narrow viewport. All four issues fixed in one PR because the underlying cause is the same: handlers forgot to thread one context kwarg.

## Test plan
- [x] tests/test_render_helpers.py — 4 unit tests for the wrapper.
- [x] tests/test_signed_in_nav_e2e.py — 4 new E2E tests (verify_sent, settings_tokens, /quickstart, overflow CSS).
- [x] uv run pytest tests/ — full suite green (~802 tests).
- [ ] Post-deploy: walk the manual smoke in docs/plans/2026-05-01-signed-in-banner-coverage-and-overflow.md Task 8.2.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Verification

End-to-end, the plan succeeds when:

1. `uv run pytest tests/` passes with the new tests added.
2. A signed-in user navigating from any normal entry point (login, magic link, brand-link click, top-nav clicks) sees the banner on every page they land on, except the ones explicitly anonymous (login form, magic-link sent, device flow).
3. The banner truncates email-text instead of clipping action links on viewports ≥360px wide.
4. `docs/FOLLOW-UPS.md` no longer carries the banner-coverage or wasteful-logout-fetch entries.
5. CI auto-deploy ships the change without orphaning a machine (the `--strategy immediate` workflow continues to function).

---

## Critical Files for Implementation

- `/Users/daveyhiles/Developer/markland/src/markland/web/render_helpers.py` (new, Task 1)
- `/Users/daveyhiles/Developer/markland/tests/test_render_helpers.py` (new, Task 1)
- `/Users/daveyhiles/Developer/markland/src/markland/web/templates/_signed_in_nav.html` (Task 2)
- `/Users/daveyhiles/Developer/markland/src/markland/web/templates/verify_sent.html` (Task 3)
- `/Users/daveyhiles/Developer/markland/src/markland/web/auth_routes.py` (Task 3)
- `/Users/daveyhiles/Developer/markland/src/markland/web/templates/settings_tokens.html` (Task 4)
- `/Users/daveyhiles/Developer/markland/src/markland/web/identity_routes.py` (Task 4)
- `/Users/daveyhiles/Developer/markland/src/markland/web/templates/settings_agents.html` (Task 5)
- `/Users/daveyhiles/Developer/markland/src/markland/web/routes_agents.py` (Task 5)
- `/Users/daveyhiles/Developer/markland/src/markland/web/templates/dashboard.html` (Task 5)
- `/Users/daveyhiles/Developer/markland/src/markland/web/dashboard.py` (Task 5)
- `/Users/daveyhiles/Developer/markland/src/markland/web/app.py` (Task 6 — 11 render call sites)
- `/Users/daveyhiles/Developer/markland/tests/test_signed_in_nav_e2e.py` (Tasks 2–4, 6)
- `/Users/daveyhiles/Developer/markland/docs/FOLLOW-UPS.md` (Task 7)

**Reference (no edits expected):**
- `/Users/daveyhiles/Developer/markland/src/markland/web/session_principal.py` — `session_user`, `session_principal`, `signed_in_user_ctx` are reused as-is.
- `/Users/daveyhiles/Developer/markland/src/markland/web/templates/base.html` — already includes the partial and is correctly themed.
