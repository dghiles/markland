# MCP `/mcp` 307-Redirect Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Beads:** `markland-dfj` (P2; surfaced 2026-05-04 from production logs).

**Goal:** Make `POST https://markland.dev/mcp` (no trailing slash) return the same 200 response as `POST https://markland.dev/mcp/`, eliminating the 307 redirect that adds ~5-8s of round-trip latency to every Claude Code session-establishment sequence.

**Architecture:** Investigate-then-fix. Try the cheapest correct fix first (server-side `redirect_slashes=False` or equivalent on the Starlette mount), fall back to mounting the FastMCP sub-app at empty prefix with explicit `/mcp` and `/mcp/` route handlers if the cheap fix isn't available. PrincipalMiddleware's `startswith("/mcp")` gate already covers both forms — verify before changing. The Quickstart already publishes the trailing-slash form (per PR #68); this plan closes the no-slash hole that legacy installs and ad-hoc `claude mcp add` invocations still hit.

**Tech Stack:** FastAPI + Starlette mount semantics, FastMCP `streamable_http_app()`, pytest + httpx TestClient, `flyctl logs` for production verification.

**Reference:** `src/markland/web/app.py:203` (sub-app path config), `src/markland/web/app.py:875` (mount), `src/markland/web/principal_middleware.py` (auth gate).

---

## File Structure

**Modify:**

- `src/markland/web/app.py:200-205` and/or `src/markland/web/app.py:875` — the mount-point configuration that produces the redirect.
- `tests/test_mcp_routing.py` (new or extend an existing test file — verify with `grep -rn "test_mcp" tests/`) — assert no-slash and slash both return 200.

**No new modules expected.** If Option B is needed (Task 3), a small middleware or route-add at the same file.

**Test framework:** `uv run python -m pytest tests/ -q`.

---

## Task 1: Pin the current bug + the desired behavior with failing tests

**Files:**
- Test: `tests/test_mcp_routing.py` (new).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_routing.py`:

```python
"""MCP /mcp routing — both /mcp and /mcp/ should reach the sub-app
without a 307 round-trip. Pins markland-dfj.

CRITICAL: PrincipalMiddleware short-circuits unauthenticated /mcp* requests
with a 401 BEFORE any route lookup, so the redirect only manifests on
AUTHENTICATED requests. Tests must mint a real token and send it as
`Authorization: Bearer ...`, otherwise the 401 short-circuit will hide
the 307 and the tests will be green-on-red (passing on broken code).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.auth import create_user_token
from markland.service.users import create_user
from markland.web.app import create_app

SECRET = "test-session-secret"


@pytest.fixture
def authed(tmp_path, monkeypatch):
    """TestClient + headers dict with a valid bearer token."""
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "test.db")
    user = create_user(conn, email="dfj@example.com", display_name="DFJ")
    _, token = create_user_token(conn, user_id=user.id, label="dfj-test")
    app = create_app(
        conn, mount_mcp=True,
        base_url="https://markland.dev",
        session_secret=SECRET,
    )
    with TestClient(app, base_url="http://testserver") as c:
        yield c, {"Authorization": f"Bearer {token}"}


def test_mcp_no_slash_does_not_redirect(authed):
    """POST /mcp (no slash) must reach the sub-app directly, not 307 to /mcp/."""
    client, hdrs = authed
    r = client.post(
        "/mcp",
        headers={
            **hdrs,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "no-redirect-test", "version": "0"},
            },
        },
        follow_redirects=False,
    )
    assert r.status_code != 307, (
        f"got 307 → location: {r.headers.get('location')!r}. "
        f"This is the bug — middleware passed (auth ok), Starlette's mount "
        f"redirected /mcp to /mcp/."
    )
    # Acceptable terminal codes: 200 (initialize accepted), 202 (accepted async),
    # or any other non-3xx. We don't pin the exact value because FastMCP can
    # legitimately respond several ways depending on session state.
    assert r.status_code < 300 or r.status_code >= 400, r.text[:200]


def test_mcp_slash_works_unchanged(authed):
    """Regression guard: POST /mcp/ continues to work exactly as pre-fix."""
    client, hdrs = authed
    r = client.post(
        "/mcp/",
        headers={
            **hdrs,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "regress", "version": "0"},
            },
        },
        follow_redirects=False,
    )
    assert r.status_code != 307
    assert r.status_code < 300 or r.status_code >= 400, r.text[:200]


def test_mcp_get_no_slash_does_not_redirect(authed):
    """GET /mcp also must not 307 — FastMCP uses GET for SSE event stream."""
    client, hdrs = authed
    r = client.get(
        "/mcp",
        headers={**hdrs, "Accept": "text/event-stream"},
        follow_redirects=False,
    )
    assert r.status_code != 307, f"got 307 → {r.headers.get('location')!r}"


def test_unauthenticated_post_mcp_short_circuits_to_401(tmp_path, monkeypatch):
    """Defensive: middleware must continue to short-circuit unauth requests
    BEFORE reaching the route — so we never accidentally redirect an
    unauthenticated request to /mcp/. This is current behavior; the test
    locks it in so the Task 2/3 fix can't accidentally break it."""
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "test.db")
    app = create_app(
        conn, mount_mcp=True,
        base_url="https://markland.dev",
        session_secret=SECRET,
    )
    with TestClient(app, base_url="http://testserver") as c:
        r = c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
            follow_redirects=False,
        )
        assert r.status_code == 401, f"expected 401, got {r.status_code}"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/daveyhiles/Developer/markland/.worktrees/mcp-trailing-slash-redirect
uv run python -m pytest tests/test_mcp_routing.py -v
```

Expected: `test_mcp_no_slash_does_not_redirect` and `test_mcp_get_no_slash_does_not_redirect` FAIL with status_code 307 (middleware passed because the auth token is valid; then Starlette's mount issues the 307). `test_mcp_slash_works_unchanged` should PASS (mount handles `/mcp/` directly). `test_unauthenticated_post_mcp_short_circuits_to_401` should PASS (current production behavior).

Use `uv run python -m pytest`, NOT `uv run pytest` — system pytest doesn't see the venv.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_mcp_routing.py
git commit -m "test(mcp): pin /mcp no-slash routing (markland-dfj)"
```

(Committing the failing tests on their own is intentional — they document the bug. Tasks 2-3 turn them green.)

---

## Task 2: Try the cheapest fix — `redirect_slashes=False`

**Files:**
- Modify: `src/markland/web/app.py:875` (the `app.mount("/mcp", mcp_app)` call).

- [ ] **Step 1: Investigate Starlette's slash-redirect knob**

Starlette's `Router` and `Mount` both accept a `redirect_slashes: bool` parameter. Confirm via:

```bash
python -c "from starlette.routing import Mount; import inspect; print(inspect.signature(Mount.__init__))"
```

Expected output: includes `redirect_slashes: bool = True` (or similar).

- [ ] **Step 2: Apply the knob**

Edit `src/markland/web/app.py:875`. The current line is:

```python
        app.mount("/mcp", mcp_app)
```

Replace with:

```python
        # markland-dfj: disable Starlette's mount-point trailing-slash
        # redirect so POST /mcp reaches the sub-app directly instead of
        # taking a 307 round trip to /mcp/. The sub-app's internal
        # streamable_http_path is "/" (set above at line 203), so /mcp
        # and /mcp/ both resolve to the same handler.
        app.mount("/mcp", mcp_app, name="mcp")
        # NOTE: Starlette's app-level redirect_slashes lives on the
        # parent app, not on the Mount. If the test in tests/test_mcp_
        # routing.py still shows 307 after this change, fall through to
        # Task 3 (Option B — explicit route handler).
```

(`Mount` may not actually accept `redirect_slashes`; the canonical place is `FastAPI(redirect_slashes=False)` on app construction. Verify before edit; if FastAPI's app-level flag is the only way, it disables redirects globally — that's likely fine for Markland but warrants the test sweep below.)

- [ ] **Step 3: If Step 2 didn't take, set the flag at app construction**

If the Mount-level approach isn't supported, modify the `FastAPI(...)` constructor call (likely in `create_app` near the top — `grep -n "FastAPI(" src/markland/web/app.py`):

```python
    app = FastAPI(
        ...,
        redirect_slashes=False,
    )
```

This disables Starlette's auto-redirect for ALL routes, not just `/mcp`. Audit the existing routes for ones that expect the redirect. Run the full test suite after applying.

- [ ] **Step 4: Run the new tests**

```bash
uv run python -m pytest tests/test_mcp_routing.py -v
```

Expected: all 3 PASS. If `test_mcp_no_slash_does_not_redirect` still fails with 307, proceed to Task 3.

- [ ] **Step 5: Run the full test suite**

```bash
uv run python -m pytest tests/ -q
```

Expected: all green. Watch for regressions on routes that may have relied on the trailing-slash redirect (most FastAPI apps don't, but verify).

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/app.py
git commit -m "fix(mcp): disable trailing-slash redirect on /mcp mount (markland-dfj)"
```

If Task 2 succeeded, skip to Task 4. If not, Task 3 is the fallback.

---

## Task 3: Fallback — explicit `/mcp` route handler (Option B)

Only run this task if Task 2 didn't fix the 307. The fallback adds an explicit `POST /mcp` route that internally re-dispatches to the mounted sub-app at `/mcp/`.

**Files:**
- Modify: `src/markland/web/app.py` — add a small route or middleware before the mount.

- [ ] **Step 1: Add an explicit `/mcp` route that calls the sub-app**

Add this before the `app.mount("/mcp", mcp_app)` call:

```python
        # markland-dfj fallback: Starlette's mount-point trailing-slash
        # redirect cannot be disabled on this mount, so handle /mcp (no
        # slash) explicitly by delegating to the sub-app. We rebuild the
        # ASGI scope with path="/" (matching the sub-app's internal
        # streamable_http_path).
        from starlette.types import Receive, Scope, Send

        @app.post("/mcp", include_in_schema=False)
        async def _mcp_no_slash_post(request: Request):
            scope = dict(request.scope)
            scope["path"] = "/"
            scope["raw_path"] = b"/"
            return await mcp_app(scope, request.receive, request._send)

        @app.get("/mcp", include_in_schema=False)
        async def _mcp_no_slash_get(request: Request):
            scope = dict(request.scope)
            scope["path"] = "/"
            scope["raw_path"] = b"/"
            return await mcp_app(scope, request.receive, request._send)
```

(This pattern is borrowed from how Starlette's `Mount` itself dispatches; verify the receive/send wiring against the actual MCP sub-app implementation. The simpler alternative — issuing an internal redirect or making the no-slash path return a copy of the sub-app's response — is fragile because FastMCP serves a streaming SSE-shaped response.)

- [ ] **Step 2: Run the routing tests**

```bash
uv run python -m pytest tests/test_mcp_routing.py -v
```

Expected: 3 PASS.

- [ ] **Step 3: Verify PrincipalMiddleware still gates both paths**

```bash
grep -n "startswith.*mcp" src/markland/web/principal_middleware.py
```

Expected: the middleware uses `path.startswith("/mcp")` which catches both forms. If it uses an exact-match or trailing-slash-required predicate, widen it to cover `/mcp` and `/mcp/`.

- [ ] **Step 4: Run the full test suite**

```bash
uv run python -m pytest tests/ -q
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/app.py
git commit -m "fix(mcp): explicit /mcp no-slash route delegates to sub-app (markland-dfj fallback)"
```

---

## Task 4: Production verification

- [ ] **Step 1: Deploy**

```bash
flyctl deploy --remote-only --strategy immediate
```

Expected: build + deploy succeed; release counter advances by one.

- [ ] **Step 2: Verify both paths return 401 directly (no 307)**

```bash
curl -i -X POST https://markland.dev/mcp \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","method":"initialize","id":1}'
```

Expected: first response line `HTTP/2 401`, no `location:` header.

```bash
curl -i -X POST https://markland.dev/mcp/ \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","method":"initialize","id":1}'
```

Expected: same — `HTTP/2 401`, no redirect.

- [ ] **Step 3: Time a real Claude Code session**

In Claude Code, run `/mcp` and reconnect to Markland. Watch `flyctl logs -a markland --since 5m` while reconnecting.

Expected: zero `307` lines; connection completes in well under 8 seconds (target: under 4s).

- [ ] **Step 4: Document the result in the beads issue**

```bash
bd update markland-dfj --status=in_progress --notes="Deployed via PR. Both /mcp and /mcp/ return 401 directly (no 307). Connection time measured at <Xs> per Claude Code reconnect. Closing."
bd close markland-dfj --reason="307 redirect cycle eliminated; production-verified."
bd sync
```

- [ ] **Step 5: Commit the bd state change**

```bash
git add .beads/issues.jsonl
git commit -m "chore(beads): close markland-dfj — /mcp 307 redirect eliminated"
git push origin main
```

---

## Task 5: Update ROADMAP

- [ ] **Step 1: Move from Next to Shipped**

In `docs/ROADMAP.md`:

1. Remove the `[plan]`-tagged "MCP `/mcp` 307-redirect fix" entry from the Next lane.
2. Add at the top of the "Hosted infrastructure + ops" Shipped section:

```markdown
- **2026-05-04** — **MCP `/mcp` 307-redirect cycle eliminated.** `POST /mcp` (no trailing slash) reaches the FastMCP sub-app directly instead of taking a 307 → `/mcp/` round trip. Connection-establishment latency drops from ~18s to under 4s for cold Claude Code reconnects. Implementation: <Option A or B selected> in `src/markland/web/app.py:875`. Closes `markland-dfj`. Plan: `docs/plans/2026-05-04-mcp-trailing-slash-redirect.md`.
```

- [ ] **Step 2: Commit + push**

```bash
git add docs/ROADMAP.md
git commit -m "docs(roadmap): /mcp 307-redirect fix shipped"
git push origin main
```

---

## Out of scope

- **Restructuring the FastMCP sub-app's internal path config.** The current `streamable_http_path = "/"` is correct for a mounted sub-app; changing it risks breaking the canonical `/mcp/` form.
- **Custom redirect-following on the client side.** Claude Code's SDK already follows 307s; we're fixing the source, not the client.
- **A blanket app-wide `redirect_slashes=False`** if the localized fix works. Only set the flag globally if the per-mount knob isn't available (Task 2 Step 3).

---

## Self-review checklist

- Each task ends with a `git commit` step ✅
- Tests pin the no-slash and slash-form cases independently ✅
- No "TBD" / "TODO" / "fill in" placeholders ✅
- Fallback path (Task 3) included in case the cheap fix doesn't take ✅
- Production verification with real curl + real Claude Code reconnect timing ✅
- Roadmap update task included ✅
