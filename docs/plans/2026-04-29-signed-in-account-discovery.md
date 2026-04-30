# First-Time Invitee Account Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a signed-in browser user able to find their own account and docs from any page they naturally land on, closing the "I don't have an account yet, idk where it saved" gap.

**Context:** While testing the magic-link → invite flow with Noah (`noahpan323@gmail.com`, account `usr_c9442e3056fa47b3`) on 2026-04-29, he completed the entire flow successfully — account created, invite accepted, doc loaded, even bookmarked it twice — then said *"lol I got it. But idk where it saved to. I don't have an account yet."* The Fly logs show his actual journey: he eventually clicked the brand-link "Markland" in the doc-page nav, landed on the public marketing landing (`GET /` returned the marketing page), and gave up. Investigation uncovered two real defects: (a) the doc page and the landing page do not reflect signed-in state — there's no "you're signed in" indicator, no link to "your docs," no sign-out — and (b) `/explore?view=mine` is the right URL for the dashboard, but `request.state.principal` is **only** populated for browser routes when the caller carries a Bearer token, never from the `mk_session` cookie. So for browsers, "your docs" is currently unreachable through any UI path.

**Architecture:** Three layered fixes. (1) A small `web/session_principal.py` helper resolves the `mk_session` cookie to a `Principal` so existing browser handlers (`/explore`, `/`, `/d/...`) can ask "is this caller signed in via a session cookie?" without reaching into `service.sessions` + `service.users` from inside route bodies. (2) A shared `_signed_in_nav.html` Jinja partial renders "Signed in as `<email>` · Your docs · Sign out" when the rendered context contains a `signed_in_user` object; the three large templates (`landing.html`, `document.html`, `explore.html`) `{% include %}` it at the top, mirroring the codebase's existing pattern (`_save_dialog.html`, `_share_dialog.html`). (3) The handlers that render those three templates resolve the session principal once and inject `signed_in_user` into the render context. The `/` handler keeps showing the marketing landing for everyone — the per-user banner sits inside the existing nav region, not as a redirect, per the product call already made.

**Tech Stack:** Python 3.12, FastAPI/Starlette routes, Jinja2 templates, SQLite via existing `markland.service.users.get_user`, `markland.service.sessions.get_session`. No new dependencies.

**Scope excluded:**
- Dashboard tutorial / welcome screen / confetti.
- Settings nav redesign (the existing `/settings/tokens` page works).
- Mobile-specific layouts beyond inheriting whatever the existing pages do.
- Changing the redirect target of `/verify` after first sign-in.
- Auto-promoting `/` to redirect to `/explore?view=mine` for signed-in users (explicitly chosen "show landing + nav banner" instead).
- Sign-out via GET (CSRF risk); `/api/auth/logout` is a POST today and we'll wire the partial's "Sign out" link as a tiny POST form.

---

## File Structure

**New files:**
- `src/markland/web/session_principal.py` — `session_principal(request, conn) -> Principal | None` helper. Reads `mk_session` cookie, looks up the user, returns a `Principal` or `None`. Used by browser route handlers that previously checked `request.state.principal` and silently got None for cookie-auth'd users.
- `src/markland/web/templates/_signed_in_nav.html` — Jinja partial. Renders the "Signed in as `<email>` · Your docs · Sign out" banner when the render context has `signed_in_user`. Renders nothing when absent.
- `tests/test_session_principal.py` — unit tests for the helper.
- `tests/test_signed_in_nav_e2e.py` — end-to-end tests across the three pages: assert the banner shows for signed-in cookie users and is absent for anon users; assert the `/explore?view=mine` link is reachable and works for cookie-auth'd users.

**Modified files:**
- `src/markland/web/app.py` — three route handlers (`landing` at `:454`, `explore` at `:469`, `view_document` at `:526`) gain one line each: resolve `signed_in_user = session_principal(request, db_conn)` and pass it into the template context. The `/explore` `view=mine` branch additionally falls back to the cookie-resolved principal when `request.state.principal` is None.
- `src/markland/web/templates/landing.html` — add `{% include "_signed_in_nav.html" %}` near the top of `<body>` (above the existing brand mark / hero).
- `src/markland/web/templates/document.html` — add `{% include "_signed_in_nav.html" %}` near the top of `<body>`.
- `src/markland/web/templates/explore.html` — add `{% include "_signed_in_nav.html" %}` near the top of `<body>`.

**Unchanged:**
- `src/markland/web/principal_middleware.py` — keep `/mcp`-only scope. We deliberately don't widen middleware to all paths; cookie-auth is its own concern and the helper is the right granularity.
- `src/markland/web/rate_limit_middleware.py` — keep Bearer-only resolution. Rate-limit tiering for cookie users isn't worse than the current state and changing it is out of scope.
- `src/markland/service/auth.py`, `service/sessions.py`, `service/users.py` — already provide everything we need.

---

## Task 1: Session-cookie principal resolver helper (TDD)

**Files:**
- Create: `src/markland/web/session_principal.py`
- Test: `tests/test_session_principal.py`

Goal: a single function browser handlers can call to resolve `request.cookies["mk_session"]` to a `Principal` (the same dataclass `PrincipalMiddleware` returns), or `None` if no/invalid session.

- [ ] **Step 1.1: Write the failing tests**

Create `/Users/daveyhiles/Developer/markland/tests/test_session_principal.py`:

```python
"""Unit tests for web.session_principal."""

from __future__ import annotations

from starlette.requests import Request

from markland.db import init_db
from markland.service.auth import Principal
from markland.service.sessions import SESSION_COOKIE_NAME, issue_session
from markland.service.users import create_user
from markland.web.session_principal import session_principal


SECRET = "test-session-secret"


def _make_request(*, cookies: dict[str, str] | None = None) -> Request:
    """Build a Starlette Request with given cookies and no body."""
    cookie_header = "; ".join(f"{k}={v}" for k, v in (cookies or {}).items())
    headers: list[tuple[bytes, bytes]] = []
    if cookie_header:
        headers.append((b"cookie", cookie_header.encode("ascii")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "query_string": b"",
    }
    return Request(scope)


def test_returns_none_when_no_cookie(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    req = _make_request()
    assert session_principal(req, conn) is None


def test_returns_none_when_cookie_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    req = _make_request(cookies={SESSION_COOKIE_NAME: "garbage"})
    assert session_principal(req, conn) is None


def test_returns_none_when_user_missing(tmp_path, monkeypatch):
    """Cookie is valid but user has been deleted between requests."""
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    cookie = issue_session("usr_nonexistent", secret=SECRET)
    req = _make_request(cookies={SESSION_COOKIE_NAME: cookie})
    assert session_principal(req, conn) is None


def test_returns_principal_for_valid_session(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    user = create_user(conn, email="alice@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    req = _make_request(cookies={SESSION_COOKIE_NAME: cookie})

    p = session_principal(req, conn)
    assert isinstance(p, Principal)
    assert p.principal_id == user.id
    assert p.principal_type == "user"
    assert p.is_admin is False


def test_principal_carries_admin_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    user = create_user(conn, email="root@example.com")
    conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user.id,))
    conn.commit()
    cookie = issue_session(user.id, secret=SECRET)
    req = _make_request(cookies={SESSION_COOKIE_NAME: cookie})

    p = session_principal(req, conn)
    assert p is not None
    assert p.is_admin is True
```

- [ ] **Step 1.2: Run the tests to verify they fail**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_session_principal.py -x -v
```

**Expected:** `ModuleNotFoundError: No module named 'markland.web.session_principal'` — file doesn't exist yet.

- [ ] **Step 1.3: Implement the helper**

Create `/Users/daveyhiles/Developer/markland/src/markland/web/session_principal.py`:

```python
"""Resolve `mk_session` cookies to `Principal` for non-/mcp browser routes.

Background: `PrincipalMiddleware` only runs for `/mcp` paths; the rate-limit
middleware fallback only resolves Bearer tokens. Cookie-auth'd browser
sessions never get `request.state.principal` populated. This helper closes
that gap so handlers like `/explore?view=mine` can recognize signed-in
browser users.

Returns None on any failure — missing cookie, bad signature, expired
session, or user deleted between requests.
"""

from __future__ import annotations

import sqlite3

from starlette.requests import Request

from markland.service.auth import Principal
from markland.service.sessions import get_session
from markland.service.users import get_user


def session_principal(
    request: Request,
    conn: sqlite3.Connection,
) -> Principal | None:
    """Return a Principal for the request's session cookie, or None."""
    info = get_session(request)
    if info is None:
        return None
    user = get_user(conn, info.user_id)
    if user is None:
        return None
    return Principal(
        principal_id=user.id,
        principal_type="user",
        display_name=user.display_name,
        is_admin=user.is_admin,
        user_id=None,
    )
```

- [ ] **Step 1.4: Verify the `SessionInfo` shape matches**

The helper assumes `get_session()` returns an object with `.user_id`. Confirm by reading the source:

```bash
cd /Users/daveyhiles/Developer/markland && grep -n "class SessionInfo\|@dataclass" src/markland/service/sessions.py | head
```

**Expected output:** lines showing a `SessionInfo` dataclass with at least `user_id: str`. If `get_session` returns a dict instead (older code path), change the helper's `info.user_id` to `info["user_id"]`.

- [ ] **Step 1.5: Run the tests to verify they pass**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_session_principal.py -x -v
```

**Expected:** all 5 tests pass.

- [ ] **Step 1.6: Commit**

```bash
cd /Users/daveyhiles/Developer/markland && git add src/markland/web/session_principal.py tests/test_session_principal.py && git commit -m "$(cat <<'EOF'
feat(web): add session_principal helper for cookie-auth'd browser routes

PrincipalMiddleware is /mcp-only and the rate-limit middleware only
resolves Bearer tokens, so browser pages had no path from `mk_session`
cookie to a Principal. This helper closes that gap with a small
function the handlers can call directly — keeps the middleware stack
unchanged and lets each route opt in.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Shared signed-in nav partial (TDD)

**Files:**
- Create: `src/markland/web/templates/_signed_in_nav.html`
- Test: `tests/test_signed_in_nav_e2e.py` (started here, expanded in Task 3)

Goal: a Jinja partial that renders a small banner with email + "Your docs" + "Sign out" when the rendering context contains `signed_in_user`. Renders nothing when absent (so unauthenticated requests are unaffected).

- [ ] **Step 2.1: Write the first failing E2E test**

Create `/Users/daveyhiles/Developer/markland/tests/test_signed_in_nav_e2e.py`:

```python
"""End-to-end tests for the signed-in nav banner across landing/doc/explore."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.email import EmailClient
from markland.service.sessions import SESSION_COOKIE_NAME, issue_session
from markland.service.users import create_user
from markland.web.app import create_app


SECRET = "test-session-secret"


class _NoopEmail(EmailClient):
    def __init__(self):
        super().__init__(api_key="", from_email="noreply@test.markland.dev")

    def send(self, *, to, subject, html):
        return "noop"


@pytest.fixture
def harness(tmp_path):
    conn = init_db(tmp_path / "t.db")
    app = create_app(
        conn,
        base_url="http://testserver",
        session_secret=SECRET,
        email_client=_NoopEmail(),
    )
    client = TestClient(app)
    yield client, conn
    client.close()


def _signed_in_client(harness, *, email: str = "alice@example.com"):
    """Return (client, user) where the client carries a valid session cookie."""
    client, conn = harness
    user = create_user(conn, email=email)
    cookie = issue_session(user.id, secret=SECRET)
    client.cookies.set(SESSION_COOKIE_NAME, cookie)
    return client, user


def test_anon_landing_has_no_signed_in_banner(harness):
    client, _ = harness
    r = client.get("/")
    assert r.status_code == 200
    assert "Signed in as" not in r.text


def test_signed_in_landing_shows_email_and_links(harness):
    client, user = _signed_in_client(harness, email="alice@example.com")
    r = client.get("/")
    assert r.status_code == 200
    assert "Signed in as" in r.text
    assert "alice@example.com" in r.text
    assert 'href="/explore?view=mine"' in r.text
    assert 'action="/api/auth/logout"' in r.text
```

- [ ] **Step 2.2: Run the tests to verify they fail**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_signed_in_nav_e2e.py -x -v
```

**Expected:** `test_anon_landing_has_no_signed_in_banner` passes (banner doesn't exist yet so the negative assertion holds). `test_signed_in_landing_shows_email_and_links` fails on the first `assert "Signed in as" in r.text` — banner not implemented.

- [ ] **Step 2.3: Implement the partial**

Create `/Users/daveyhiles/Developer/markland/src/markland/web/templates/_signed_in_nav.html`:

```html
{% if signed_in_user %}
<div class="signed-in-nav" style="display:flex; align-items:center; gap:0.75rem; padding:0.5rem 1rem; background:var(--surface-2,#f6f5f1); border-bottom:1px solid var(--outline-hairline,#e3e1d9); font-family:var(--font-display,system-ui); font-size:0.85rem;">
  <span style="color:var(--muted,#666);">Signed in as <strong style="color:var(--text,#111); font-weight:600;">{{ signed_in_user.email }}</strong></span>
  <a href="/explore?view=mine" style="color:var(--text,#111); text-decoration:underline; text-underline-offset:2px;">Your docs</a>
  <form method="post" action="/api/auth/logout" style="margin:0; display:inline;">
    <button type="submit" style="background:none; border:0; padding:0; font:inherit; color:var(--text,#111); text-decoration:underline; text-underline-offset:2px; cursor:pointer;">Sign out</button>
  </form>
</div>
{% endif %}
```

- [ ] **Step 2.4: Wire the partial into landing.html (one of three templates)**

Add the include directive at the top of `<body>` in `/Users/daveyhiles/Developer/markland/src/markland/web/templates/landing.html`. Read the file first to find the exact location:

```bash
cd /Users/daveyhiles/Developer/markland && grep -n "<body" src/markland/web/templates/landing.html | head -3
```

Then insert `{% include "_signed_in_nav.html" %}` on the line **immediately after** the `<body>` tag. Example diff:

```html
  <body>
+   {% include "_signed_in_nav.html" %}
    <!-- existing landing content -->
```

- [ ] **Step 2.5: Inject `signed_in_user` into the landing handler**

Edit `/Users/daveyhiles/Developer/markland/src/markland/web/app.py` `landing` handler (currently at line 454). Add the import at the top of the file (alongside other web imports):

```python
from markland.web.session_principal import session_principal
from markland.service.users import get_user
```

Then change the handler body to:

```python
    @app.get("/", response_class=HTMLResponse)
    def landing(request: Request, signup: str | None = None):
        docs = list_featured_and_recent_public(db_conn, limit=4)
        cards = [_doc_to_card(d) for d in docs]
        signup_state = signup if signup in ("ok", "invalid") else None
        signed_in_user = None
        principal = session_principal(request, db_conn)
        if principal is not None:
            user = get_user(db_conn, principal.principal_id)
            if user is not None:
                signed_in_user = {"email": user.email}
        return HTMLResponse(
            landing_tpl.render(
                **_seo_ctx(request, base_url, page_template=landing_tpl),
                docs=cards,
                mcp_config_json=mcp_snippet_json,
                signup=signup_state,
                signed_in_user=signed_in_user,
            )
        )
```

Note: we re-fetch the user via `get_user` because the helper returns a `Principal` (no email field). For now we accept the extra DB call; if it shows up in profiling later, the helper can be widened.

- [ ] **Step 2.6: Run the tests to verify they pass**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_signed_in_nav_e2e.py -x -v
```

**Expected:** both tests pass.

- [ ] **Step 2.7: Commit**

```bash
cd /Users/daveyhiles/Developer/markland && git add src/markland/web/templates/_signed_in_nav.html src/markland/web/templates/landing.html src/markland/web/app.py tests/test_signed_in_nav_e2e.py && git commit -m "$(cat <<'EOF'
feat(web): signed-in nav banner on landing page

Adds a small banner ("Signed in as <email> · Your docs · Sign out")
that renders when the request carries a valid mk_session cookie. The
partial lives in templates/_signed_in_nav.html and is included near the
top of body. The landing handler resolves the session principal and
threads `signed_in_user` into the render context.

This is the first of three pages to gain the banner; document.html and
explore.html follow in subsequent commits.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Wire the partial into document.html and explore.html

**Files:**
- Modify: `src/markland/web/templates/document.html`
- Modify: `src/markland/web/templates/explore.html`
- Modify: `src/markland/web/app.py` (handlers `view_document` at `:526`, `explore` at `:469`)
- Modify: `tests/test_signed_in_nav_e2e.py` (add document and explore cases)

Goal: the same banner shows on the doc page and explore page so a user can find their account from any natural landing point.

- [ ] **Step 3.1: Add failing tests for document and explore**

Append to `/Users/daveyhiles/Developer/markland/tests/test_signed_in_nav_e2e.py`:

```python
def test_signed_in_doc_page_shows_banner(harness):
    client, conn = harness
    user = create_user(conn, email="bob@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    client.cookies.set(SESSION_COOKIE_NAME, cookie)

    # Insert a public doc the user can view.
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, "
        "updated_at, is_public, is_featured, owner_id) VALUES "
        "('doc_x', 'Hello', '# hi', 'tok_x', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 1, 0, ?)",
        (user.id,),
    )
    conn.commit()

    r = client.get("/d/tok_x")
    assert r.status_code == 200
    assert "Signed in as" in r.text
    assert "bob@example.com" in r.text


def test_anon_doc_page_has_no_banner(harness):
    client, conn = harness
    user = create_user(conn, email="bob@example.com")
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, "
        "updated_at, is_public, is_featured, owner_id) VALUES "
        "('doc_y', 'Public', '# hi', 'tok_y', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 1, 0, ?)",
        (user.id,),
    )
    conn.commit()

    r = client.get("/d/tok_y")
    assert r.status_code == 200
    assert "Signed in as" not in r.text


def test_signed_in_explore_view_mine_lists_user_docs(harness):
    """The 'Your docs' link must actually work for cookie-auth'd users.

    This is the reachability bug: today /explore?view=mine returns the
    public list because principal is None for cookie users.
    """
    client, conn = harness
    user = create_user(conn, email="carol@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    client.cookies.set(SESSION_COOKIE_NAME, cookie)

    # Carol has one private doc.
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, "
        "updated_at, is_public, is_featured, owner_id) VALUES "
        "('doc_carol', 'Carol Plan', 'secret', 'tok_c', "
        "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 0, 0, ?)",
        (user.id,),
    )
    conn.commit()

    r = client.get("/explore?view=mine")
    assert r.status_code == 200
    assert "Carol Plan" in r.text  # would fail before the fix — view=mine
                                   # returned public list for cookie users
    assert "Signed in as" in r.text
```

- [ ] **Step 3.2: Run the tests to verify they fail**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_signed_in_nav_e2e.py -x -v
```

**Expected:** the two doc-page tests fail on `"Signed in as" in r.text` (banner not yet on document.html). `test_signed_in_explore_view_mine_lists_user_docs` fails on `"Carol Plan" in r.text` because the explore handler doesn't recognize cookie users yet (the underlying reachability bug). `test_anon_doc_page_has_no_banner` passes vacuously because banner doesn't exist on doc page yet.

- [ ] **Step 3.3: Add the include to document.html**

Insert `{% include "_signed_in_nav.html" %}` immediately after `<body>` in `/Users/daveyhiles/Developer/markland/src/markland/web/templates/document.html`. The current line 248 is `<body>`; the include goes between line 248 and 249.

```html
  <body>
+   {% include "_signed_in_nav.html" %}
    <div class="container">
```

- [ ] **Step 3.4: Add the include to explore.html**

Same pattern — read first to find the `<body>` line:

```bash
cd /Users/daveyhiles/Developer/markland && grep -n "<body" src/markland/web/templates/explore.html | head -1
```

Then insert the include directly after the opening body tag.

- [ ] **Step 3.5: Update the document handler to inject `signed_in_user`**

Edit `view_document` in `/Users/daveyhiles/Developer/markland/src/markland/web/app.py` (currently at line 526). Find the render call and add the `signed_in_user` parameter using the same pattern as the landing handler:

```python
    @app.get("/d/{share_token}", response_class=HTMLResponse)
    def view_document(share_token: str, request: Request):
        doc = get_document_by_token(db_conn, share_token)
        if doc is None:
            # ...existing 404 handling...
        # ...existing principal resolution and visibility checks unchanged...

        signed_in_user = None
        sp = session_principal(request, db_conn)
        if sp is not None:
            u = get_user(db_conn, sp.principal_id)
            if u is not None:
                signed_in_user = {"email": u.email}

        # In the existing render call, add signed_in_user=signed_in_user.
```

The exact context-building code in `view_document` is more complex than landing (it computes `is_owner`, `active_principals`, `forked_from`, etc.); the rule is: at the final `document_tpl.render(...)` call, add `signed_in_user=signed_in_user` to the kwargs. Don't change anything else in the handler.

- [ ] **Step 3.6: Update the explore handler — fix the reachability bug AND add banner**

This handler has two changes: it must recognize cookie-auth'd users (so `view=mine` actually works for them), and it must pass `signed_in_user` to the template.

Edit `/Users/daveyhiles/Developer/markland/src/markland/web/app.py` `explore` handler at line 469. Replace:

```python
    @app.get("/explore", response_class=HTMLResponse)
    def explore(request: Request, q: str | None = None, view: str | None = None):
        principal = getattr(request.state, "principal", None)
        query = (q or "").strip() or None
        show_mine = view == "mine" and principal is not None
```

with:

```python
    @app.get("/explore", response_class=HTMLResponse)
    def explore(request: Request, q: str | None = None, view: str | None = None):
        principal = getattr(request.state, "principal", None)
        if principal is None:
            principal = session_principal(request, db_conn)
        query = (q or "").strip() or None
        show_mine = view == "mine" and principal is not None
```

Then in **both** `explore_tpl.render(...)` calls in this handler (the `view=mine` branch around line 491 and the public branch around line 504), add the `signed_in_user` kwarg. Build it once before the branches:

```python
        signed_in_user = None
        if principal is not None:
            u = get_user(db_conn, principal.principal_id)
            if u is not None:
                signed_in_user = {"email": u.email}
```

Place that block immediately after the new `principal = session_principal(...)` fallback. Pass `signed_in_user=signed_in_user` into both `explore_tpl.render(...)` calls.

- [ ] **Step 3.7: Run the tests to verify they pass**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/test_signed_in_nav_e2e.py -x -v
```

**Expected:** all 5 tests pass.

- [ ] **Step 3.8: Run the broader suite to check for regressions**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/ -x
```

**Expected:** all tests green. The most likely place to regress is `tests/test_explore_*.py` — the `view=mine` path now resolves cookie principals where it didn't before. If a test relied on cookie-auth'd users being treated as anonymous on `/explore?view=mine`, it will fail and the failure is the spec change landing as designed; update that test to either use anonymous (no cookie) or assert the new mine-view behavior. Don't suppress.

- [ ] **Step 3.9: Commit**

```bash
cd /Users/daveyhiles/Developer/markland && git add src/markland/web/templates/document.html src/markland/web/templates/explore.html src/markland/web/app.py tests/test_signed_in_nav_e2e.py && git commit -m "$(cat <<'EOF'
feat(web): signed-in banner + reachable view=mine across browser pages

Adds the _signed_in_nav.html partial to document.html and explore.html
and threads signed_in_user through both handlers. Also fixes the
underlying reachability bug: /explore?view=mine now resolves the
mk_session cookie for browser users, so the "Your docs" link in the
banner actually shows the user's docs instead of falling back to the
public list. With this commit, a first-time invitee like Noah can find
their account and docs from any page they naturally land on.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Manual verification + PR

- [ ] **Step 4.1: Full suite**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/
```

**Expected:** all tests green. Note the pre-fix baseline is 690 passes; this branch adds 5 new test functions in `test_session_principal.py` and 5 in `test_signed_in_nav_e2e.py` for a target of 700. If any pre-existing test broke, see Task 3 Step 3.8.

- [ ] **Step 4.2: Manual smoke (operator verification, post-deploy)**

After deploy:
1. Open an incognito browser and visit `https://markland.fly.dev/login`. Submit `daveyhiles+marklandnav@gmail.com`.
2. Open the magic link from the inbox.
3. After verify, click any doc link to land on `/d/...`. Confirm the banner reads *"Signed in as daveyhiles+marklandnav@gmail.com · Your docs · Sign out"* at the very top.
4. Click "Your docs" → should land on `/explore?view=mine` and list zero docs (this user owns none yet).
5. Visit `/` directly → confirm marketing landing renders normally with the banner at top.
6. Click "Sign out" → confirm session cookie cleared and the banner disappears.
7. As a regression: visit `/d/...` for any public doc while signed out — confirm no banner renders and the page works as before.

- [ ] **Step 4.3: Open a PR**

```bash
cd /Users/daveyhiles/Developer/markland && gh pr create --title "feat(web): signed-in nav banner so users can find their account" --body "$(cat <<'EOF'
## Summary
- Adds a small "Signed in as <email> · Your docs · Sign out" banner to the top of /, /d/<token>, and /explore for users with a valid mk_session cookie.
- Fixes the reachability bug behind it: /explore?view=mine now resolves the cookie principal, so cookie-auth'd browser users see their own docs instead of falling back to the public list.
- New helper src/markland/web/session_principal.py — small, opt-in, leaves middleware stack unchanged.

## Context
While testing the magic-link → invite flow, Noah completed sign-up + invite-accept fully (account created, grant landed, doc loaded, even bookmarked it twice), then said "lol I got it. But idk where it saved to. I don't have an account yet." Logs show he eventually clicked the brand-link and landed on the public marketing landing with no indication he was signed in. Investigation surfaced two real defects: (a) no signed-in nav anywhere, and (b) /explore?view=mine — the natural "your docs" route — was unreachable for cookie users because principal was only ever set from Bearer tokens. This PR fixes both.

## Test plan
- [x] tests/test_session_principal.py — 5 new tests for the helper.
- [x] tests/test_signed_in_nav_e2e.py — 5 new tests covering signed-in vs anon for landing/doc/explore plus the reachability case.
- [x] uv run pytest tests/ — full suite green.
- [ ] Post-deploy: walk the manual smoke in docs/plans/2026-04-29-signed-in-account-discovery.md Task 4.2.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Critical Files for Implementation

- `/Users/daveyhiles/Developer/markland/src/markland/web/session_principal.py` (new)
- `/Users/daveyhiles/Developer/markland/src/markland/web/templates/_signed_in_nav.html` (new)
- `/Users/daveyhiles/Developer/markland/src/markland/web/templates/landing.html`
- `/Users/daveyhiles/Developer/markland/src/markland/web/templates/document.html`
- `/Users/daveyhiles/Developer/markland/src/markland/web/templates/explore.html`
- `/Users/daveyhiles/Developer/markland/src/markland/web/app.py` (three handlers: `landing` at `:454`, `explore` at `:469`, `view_document` at `:526`)
- `/Users/daveyhiles/Developer/markland/tests/test_session_principal.py` (new)
- `/Users/daveyhiles/Developer/markland/tests/test_signed_in_nav_e2e.py` (new)

**Existing helpers reused (do not modify):**
- `markland.service.sessions.get_session(request)` — returns `SessionInfo | None` from `mk_session` cookie.
- `markland.service.users.get_user(conn, user_id)` — returns `User` (carries email).
- `markland.service.auth.Principal` — the dataclass we return from the helper.
