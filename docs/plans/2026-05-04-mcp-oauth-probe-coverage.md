# MCP OAuth Probe Coverage (markland-6o6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the Claude Code MCP SDK from crashing on Markland's HTML 404 page when it probes OAuth-related paths beyond the two we already fixed in `markland-2yj`. Restore the user-visible behavior of "install Markland → tools surface in Claude Code sessions."

**Architecture:** Extend `register_well_known_routes` (existing module from `markland-2yj`) with handlers at every additional probe path observed in production logs. Each returns a uniform JSON 404 envelope so the SDK's JSON parser sees valid JSON, can record "no OAuth server here," and falls back to using the static bearer token from the user's config. Add an integration test that hits every observed probe path and asserts JSON content-type so future SDK versions adding new probe paths surface as test failures.

**Tech Stack:** FastAPI + Starlette, pytest + httpx TestClient, existing `well_known_routes.py` module, `scripts/admin/curl-admin` for production verification.

**Reference signals (verified in production logs 2026-05-04 from real-user IP `24.90.1.142`):**

```
GET /.well-known/oauth-protected-resource/mcp        404 ← HTML  ← needs fix
GET /.well-known/oauth-protected-resource            200 JSON  ✓ already fixed
GET /.well-known/oauth-authorization-server          404 JSON  ✓ already fixed
GET /.well-known/openid-configuration                404 ← HTML  ← needs fix
GET /.well-known/oauth-authorization-server/mcp      404 ← HTML  ← needs fix
GET /.well-known/openid-configuration/mcp            404 ← HTML  ← needs fix
GET /mcp/.well-known/openid-configuration            401         ← see Task 1 note
POST /register                                        404 ← HTML  ← needs fix (load-bearing)
```

The SDK probes these in sequence. Currently `POST /register` is what produces the HTML body shown in the user's `/mcp` panel error (`<link rel="canonical" href="https://markland.dev/register">`). The `/mcp/.well-known/openid-configuration` path returns 401 because it's gated by `PrincipalMiddleware` — see Task 1 note for handling.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/markland/web/well_known_routes.py` | Existing module gains 5 additional route handlers + a shared "not_found JSON envelope" helper. |
| `tests/test_well_known_oauth.py` | Existing test file gains assertions for each new path (status code + content-type + body shape). |
| `tests/test_well_known_integration.py` | Existing integration test file gains a parametrized test that hits every probe path through the real `create_app` and asserts JSON content-type — so a new probe path the SDK adds in the future fails fast. |

We do NOT create a new module. The existing `well_known_routes.py` module's responsibility ("OAuth-discovery probe handlers that return JSON instead of HTML 404") is exactly what these new routes are; lumping them together keeps related code together. We do NOT touch `principal_middleware.py` — the `WWW-Authenticate` header it emits already points at `/.well-known/oauth-protected-resource`, which is correct.

We do NOT touch `app.py` — the existing `register_well_known_routes(app, base_url=base_url)` call still wires the registrar in, and the registrar gains new routes inside its own body.

---

## Task 1: Add JSON 404 helper + handlers for the four GET probe paths

**Why first:** All four GETs share the same response shape, are independent of `POST /register` (which has subtly different semantics — see Task 2), and are pure-add (no behavior changes for any existing path).

**Note on `GET /mcp/.well-known/openid-configuration`:** This path is currently 401 because `/mcp/*` is protected by `PrincipalMiddleware`. We will NOT add a route for this — middleware sits in front of routes, so a route here would never be reached. The 401 is already JSON (`{"error": "unauthenticated"}` from `principal_middleware.py:58-61`), which is fine: the SDK gets a JSON response and can parse it. This is Task 1's first observation worth verifying with a regression test (see Step 0 below).

**Files:**
- Modify: `src/markland/web/well_known_routes.py` (extend `register_well_known_routes`)
- Test: `tests/test_well_known_oauth.py` (add new tests)

- [ ] **Step 0: Verify the `/mcp/...` probe is already JSON via the existing middleware (no code change needed)**

```bash
cd /Users/daveyhiles/Developer/markland
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" https://markland.dev/mcp/.well-known/openid-configuration
```

Expected output: `401 application/json`

If the content-type is NOT `application/json`, stop and investigate — `principal_middleware.py:58-61` should be returning JSON. If it's already JSON, this path needs no fix and the integration test in Task 3 will assert it stays that way.

- [ ] **Step 1: Write the failing tests for the four new GET routes**

Open `tests/test_well_known_oauth.py`. Append these tests at the bottom of the file (after `test_discovery_responses_do_not_set_cookies`). Do NOT remove or alter the existing tests.

```python
def test_oauth_protected_resource_with_mcp_suffix_returns_json_404():
    """SDK probes /.well-known/oauth-protected-resource/mcp before the
    suffix-less variant. We must return JSON, not HTML, so JSON.parse()
    in the SDK doesn't crash on '<'.
    """
    client = TestClient(_app())
    r = client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["error"] == "not_found"
    # Body should hint at the static-bearer model so a human reading the
    # SDK's surfaced error has somewhere to go.
    assert "bearer" in body["error_description"].lower()


def test_oauth_authorization_server_with_mcp_suffix_returns_json_404():
    client = TestClient(_app())
    r = client.get("/.well-known/oauth-authorization-server/mcp")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["error"] == "not_found"


def test_openid_configuration_returns_json_404():
    """Some MCP SDKs probe OpenID Connect discovery as a fallback.
    We don't speak OIDC; respond with JSON so the parser doesn't crash.
    """
    client = TestClient(_app())
    r = client.get("/.well-known/openid-configuration")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["error"] == "not_found"


def test_openid_configuration_with_mcp_suffix_returns_json_404():
    client = TestClient(_app())
    r = client.get("/.well-known/openid-configuration/mcp")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["error"] == "not_found"
```

- [ ] **Step 2: Run the new tests, expect failures**

```bash
cd /Users/daveyhiles/Developer/markland/.worktrees/mcp-oauth-probe-coverage
uv run python -m pytest tests/test_well_known_oauth.py -v
```

Expected: 4 NEW failures (each new test gets a 404 from FastAPI's catch-all but with `text/plain` or no body at all — the assertion on `application/json` content-type fails). Existing tests still pass.

- [ ] **Step 3: Add the helper + four GET routes to `well_known_routes.py`**

Open `src/markland/web/well_known_routes.py`. INSIDE `register_well_known_routes`, AFTER the existing `oauth_protected_resource_trailing_slash` handler, add a small helper closure and four new routes. The complete additions to put inside the function body (after the existing trailing-slash handler):

```python
    # Shared "no OAuth here" 404 envelope. Used by every additional probe
    # path the SDK is observed to hit (see tests/test_well_known_oauth.py
    # and the markland-6o6 plan for the full list). Body is intentionally
    # uniform so the SDK can't distinguish probe paths and assume one of
    # them is OAuth-capable.
    _not_found_envelope = {
        "error": "not_found",
        "error_description": (
            "Markland does not run an OAuth authorization server or OIDC "
            "provider. Use a static bearer token minted at "
            f"{token_mint_url}."
        ),
    }

    @app.get("/.well-known/oauth-protected-resource/mcp")
    def oauth_protected_resource_mcp_suffix() -> JSONResponse:
        return JSONResponse(_not_found_envelope, status_code=404)

    @app.get("/.well-known/oauth-authorization-server/mcp")
    def oauth_authorization_server_mcp_suffix() -> JSONResponse:
        return JSONResponse(_not_found_envelope, status_code=404)

    @app.get("/.well-known/openid-configuration")
    def openid_configuration() -> JSONResponse:
        return JSONResponse(_not_found_envelope, status_code=404)

    @app.get("/.well-known/openid-configuration/mcp")
    def openid_configuration_mcp_suffix() -> JSONResponse:
        return JSONResponse(_not_found_envelope, status_code=404)
```

Note: the existing `oauth_protected_resource_trailing_slash` handler returns `{"error": "not_found"}` with no description. That's a pre-existing inconsistency from `markland-2yj`. Leave it alone in this task — Task 4 will normalize it after the new code lands cleanly.

- [ ] **Step 4: Run the new tests, expect them to pass**

```bash
cd /Users/daveyhiles/Developer/markland/.worktrees/mcp-oauth-probe-coverage
uv run python -m pytest tests/test_well_known_oauth.py -v
```

Expected: all tests pass (the 4 originals + 1 cookie test from `markland-2yj` + 4 new = 9 passed).

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/well_known_routes.py tests/test_well_known_oauth.py
git commit -m "feat(mcp): JSON 404 for additional OAuth/OIDC probe paths (markland-6o6)"
```

---

## Task 2: Handle `POST /register` (RFC 7591 dynamic client registration)

**Why separate from Task 1:** This is a `POST`, not a `GET`. It's the path the SDK hits AFTER it gives up on discovery and tries dynamic client registration on the resource origin. It's the load-bearing path in the user's reproduction — the HTML body in their `/mcp` panel came from this exact endpoint. Different verb means a separate handler; isolating the commit also makes the deploy diff legible.

**Files:**
- Modify: `src/markland/web/well_known_routes.py`
- Test: `tests/test_well_known_oauth.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_well_known_oauth.py` after the tests from Task 1:

```python
def test_post_register_returns_json_404():
    """RFC 7591 dynamic-client-registration endpoint. Markland doesn't
    speak OAuth, so a POST here must return JSON so the SDK doesn't
    crash JSON.parse on '<' from the styled HTML 404 page.

    This is the load-bearing path: in production logs the SDK falls
    through to POST /register after `authorization_servers: []` in the
    protected-resource doc, and the HTML response was what surfaced as
    the user-visible 'Auth: not authenticated' error in /mcp.
    """
    client = TestClient(_app())
    # Empty body is fine — we're 404-ing regardless. Match the SDK's
    # actual probe shape (Content-Type: application/json, JSON body).
    r = client.post(
        "/register",
        json={"client_name": "claude-code-test"},
    )
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["error"] == "not_found"
    assert "bearer" in body["error_description"].lower()


def test_get_register_also_returns_json_404():
    """Defensive: SDKs that probe via GET (or curl-debugging humans)
    should also see JSON, not HTML. Same envelope.
    """
    client = TestClient(_app())
    r = client.get("/register")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["error"] == "not_found"
```

- [ ] **Step 2: Run the new tests, expect failures**

```bash
cd /Users/daveyhiles/Developer/markland/.worktrees/mcp-oauth-probe-coverage
uv run python -m pytest tests/test_well_known_oauth.py::test_post_register_returns_json_404 tests/test_well_known_oauth.py::test_get_register_also_returns_json_404 -v
```

Expected: both fail (FastAPI's catch-all 404 returns no JSON body for `/register`).

- [ ] **Step 3: Add the `/register` route**

In `src/markland/web/well_known_routes.py`, INSIDE `register_well_known_routes`, AFTER the four GET handlers added in Task 1, add:

```python
    # RFC 7591 dynamic client registration. SDKs that don't honor an empty
    # `authorization_servers` list fall through to POSTing here on the
    # resource origin. Markland is bearer-only, so 404 with the same JSON
    # envelope as the GET probes. We register both GET and POST so a
    # human curl-debugging the path also sees JSON.
    @app.api_route("/register", methods=["GET", "POST"])
    def register_endpoint() -> JSONResponse:
        return JSONResponse(_not_found_envelope, status_code=404)
```

`@app.api_route` accepts a `methods` list, mounting one handler for both verbs. This avoids two handlers with the same body — DRY.

- [ ] **Step 4: Run the new tests, expect green**

```bash
cd /Users/daveyhiles/Developer/markland/.worktrees/mcp-oauth-probe-coverage
uv run python -m pytest tests/test_well_known_oauth.py -v
```

Expected: 11 passed (9 from before + 2 new).

- [ ] **Step 5: Manual sanity check — confirm we don't shadow any existing `/register` route**

```bash
cd /Users/daveyhiles/Developer/markland/.worktrees/mcp-oauth-probe-coverage
grep -rn '"/register"' src/markland/ --include="*.py"
```

Expected: only matches inside `well_known_routes.py` (and possibly markdown/comments). If anything else in `src/markland/web/*.py` declares a `/register` route, STOP and investigate before continuing — adding a second handler at the same path is order-dependent and could break the existing one. (None expected; the project doesn't currently expose a registration endpoint, but verify.)

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/well_known_routes.py tests/test_well_known_oauth.py
git commit -m "feat(mcp): JSON 404 for /register dynamic-client-registration probe (markland-6o6)"
```

---

## Task 3: Integration test — every probe path through the real app

**Why:** Per-route unit tests can drift from the live app's behavior (e.g. middleware ordering, mount path, redirect_slashes interaction). One parametrized integration test that hits every probe path through `create_app` is the regression net for "did we actually wire everything?" and "did a future SDK version add a path we don't cover?"

**Files:**
- Modify: `tests/test_well_known_integration.py` (add new test; keep existing 2 tests intact)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_well_known_integration.py`:

```python
import pytest


@pytest.mark.parametrize("method,path", [
    # Already-fixed paths (from markland-2yj). Listed here so the regression
    # net catches a future change that breaks them.
    ("GET", "/.well-known/oauth-protected-resource"),
    ("GET", "/.well-known/oauth-authorization-server"),
    ("GET", "/.well-known/oauth-protected-resource/"),
    # New paths fixed in markland-6o6.
    ("GET", "/.well-known/oauth-protected-resource/mcp"),
    ("GET", "/.well-known/oauth-authorization-server/mcp"),
    ("GET", "/.well-known/openid-configuration"),
    ("GET", "/.well-known/openid-configuration/mcp"),
    ("GET", "/register"),
    ("POST", "/register"),
    # Middleware-protected /mcp/* probe — middleware returns JSON 401, which
    # is also fine for the SDK's parser. We assert JSON to lock that in.
    ("GET", "/mcp/.well-known/openid-configuration"),
])
def test_every_observed_probe_path_returns_json(tmp_path, method, path):
    """Every path the Claude Code MCP SDK was observed to probe in production
    logs (2026-05-04, daveyhiles@gmail.com's install) must return JSON, not
    HTML. The exact status code varies by path (200, 401, 404), but the
    content-type MUST be application/json — anything else crashes the SDK's
    JSON.parse with `Unrecognized token <` and breaks the install.
    """
    conn = init_db(tmp_path / "t.db")
    app = build_app_for_test(conn)
    client = TestClient(app)
    r = client.request(method, path)
    assert r.headers["content-type"].startswith("application/json"), (
        f"{method} {path} returned content-type "
        f"{r.headers['content-type']!r} (status {r.status_code}); "
        f"body starts with {r.text[:80]!r}"
    )
```

The test references a `build_app_for_test(conn)` helper. The existing two tests in this file each call `create_app(conn, base_url="http://testserver", enable_presence_gc=False, mount_mcp=False)` directly — duplicating that across 10 parametrize cases would be noisy. Add the helper at the top of the file (right after the imports):

```python
def build_app_for_test(conn):
    """Single source of truth for test-app construction. Mirrors the kwargs
    that the existing two integration tests use; centralising lets the
    parametrized test below stay tight.
    """
    return create_app(
        conn,
        base_url="http://testserver",
        enable_presence_gc=False,
        mount_mcp=False,
    )
```

Optionally also refactor the existing two tests to use this helper. That's a YAGNI judgment call — if doing so is one tiny edit per test, do it; if not, leave them alone and accept one helper used by one test for now.

- [ ] **Step 2: Run the test, expect partial green**

```bash
cd /Users/daveyhiles/Developer/markland/.worktrees/mcp-oauth-probe-coverage
uv run python -m pytest tests/test_well_known_integration.py -v
```

Expected: the 6 paths fixed in Tasks 1 + 2 PASS. The pre-existing `markland-2yj` paths (3) PASS. The `/mcp/.well-known/openid-configuration` parametrize case should also PASS because `principal_middleware.py:58-61` returns `JSONResponse({"error": "unauthenticated"})` which has `content-type: application/json`. So expected: 12 passed (2 existing + 10 parametrize cases).

If `/mcp/.well-known/openid-configuration` FAILS the JSON content-type assertion, it means the middleware's response isn't actually `application/json` — investigate before continuing. The middleware uses `JSONResponse` so it should be fine, but trust the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_well_known_integration.py
git commit -m "test(mcp): regression net — every observed probe path returns JSON (markland-6o6)"
```

---

## Task 4: Normalize the trailing-slash 404 envelope

**Why:** The existing `oauth_protected_resource_trailing_slash` handler from `markland-2yj` returns `{"error": "not_found"}` with no `error_description`. After Task 1 every other "not found" route returns the richer envelope with the bearer-token hint. Cosmetic but worth doing while we're here — keeps the SDK's surfaced error legible no matter which path tripped it.

**Files:**
- Modify: `src/markland/web/well_known_routes.py`
- Test: `tests/test_well_known_oauth.py`

- [ ] **Step 1: Update the existing test to match the new envelope**

Open `tests/test_well_known_oauth.py`. Find the existing `test_protected_resource_path_is_exact` test (it asserts trailing-slash and uppercase-path return 404). Update only the trailing-slash assertion to also check the body shape. Replace:

```python
def test_protected_resource_path_is_exact():
    """Trailing-slash and case variants should NOT match — keeps the surface tight."""
    client = TestClient(_app())
    assert client.get("/.well-known/oauth-protected-resource/").status_code == 404
    assert client.get("/.WELL-KNOWN/oauth-protected-resource").status_code == 404
```

with:

```python
def test_protected_resource_path_is_exact():
    """Trailing-slash and case variants should NOT match — keeps the surface tight.

    Trailing slash is explicitly handled by our own route (returns JSON with
    the standard not_found envelope). The uppercase variant falls through to
    FastAPI's catch-all and 404s.
    """
    client = TestClient(_app())
    r_slash = client.get("/.well-known/oauth-protected-resource/")
    assert r_slash.status_code == 404
    assert r_slash.headers["content-type"].startswith("application/json")
    body = r_slash.json()
    assert body["error"] == "not_found"
    assert "bearer" in body["error_description"].lower()

    assert client.get("/.WELL-KNOWN/oauth-protected-resource").status_code == 404
```

- [ ] **Step 2: Run the test, expect the body assertion to fail**

```bash
cd /Users/daveyhiles/Developer/markland/.worktrees/mcp-oauth-probe-coverage
uv run python -m pytest tests/test_well_known_oauth.py::test_protected_resource_path_is_exact -v
```

Expected: FAIL. Body is `{"error": "not_found"}` with no `error_description` field.

- [ ] **Step 3: Update the trailing-slash handler to use the shared envelope**

In `src/markland/web/well_known_routes.py`, find the existing handler:

```python
    @app.get("/.well-known/oauth-protected-resource/")
    def oauth_protected_resource_trailing_slash() -> JSONResponse:
        return JSONResponse({"error": "not_found"}, status_code=404)
```

Replace its body to use the shared envelope (which is now in scope from Task 1):

```python
    @app.get("/.well-known/oauth-protected-resource/")
    def oauth_protected_resource_trailing_slash() -> JSONResponse:
        return JSONResponse(_not_found_envelope, status_code=404)
```

- [ ] **Step 4: Run the test, expect green**

```bash
cd /Users/daveyhiles/Developer/markland/.worktrees/mcp-oauth-probe-coverage
uv run python -m pytest tests/test_well_known_oauth.py -v
```

Expected: 11 passed (no regressions).

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/well_known_routes.py tests/test_well_known_oauth.py
git commit -m "refactor(mcp): unify trailing-slash 404 envelope with new probe paths (markland-6o6)"
```

---

## Task 5: Full-suite regression check + push + PR

**Why:** Every per-task run is partial. Before opening a PR, confirm the entire suite still passes — no test elsewhere depended on `/.well-known/openid-configuration` returning HTML, no integration test broke from the trailing-slash envelope change, etc.

**Files:** none modified — verification + push + PR only.

- [ ] **Step 1: Run the full suite**

```bash
cd /Users/daveyhiles/Developer/markland/.worktrees/mcp-oauth-probe-coverage
uv run python -m pytest -q
```

Expected: at least 1025 passed (the baseline from `markland-2yj`'s ship), 0 failed. Some new tests added by this plan increase the count slightly. If anything FAILS, investigate before pushing.

- [ ] **Step 2: Push the branch**

```bash
cd /Users/daveyhiles/Developer/markland/.worktrees/mcp-oauth-probe-coverage
git push -u origin feat/mcp-oauth-probe-coverage
```

- [ ] **Step 3: Open the PR**

```bash
gh pr create --title "feat(mcp): cover all observed OAuth/OIDC probe paths to unblock Claude Code install (markland-6o6)" --body "$(cat <<'EOF'
## Summary

Follow-up to PR #66 / markland-2yj. The first fix made `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server` return JSON. But Claude Code's MCP SDK probes additional OAuth paths, all still returning Markland's HTML 404 page, which crashed the SDK's JSON parser and prevented the MCP `initialize` handshake from completing — so no `mcp__markland__*` tools surfaced in user sessions.

This PR extends `register_well_known_routes` to cover every probe path observed in production logs:

- `GET /.well-known/oauth-protected-resource/mcp`
- `GET /.well-known/oauth-authorization-server/mcp`
- `GET /.well-known/openid-configuration`
- `GET /.well-known/openid-configuration/mcp`
- `GET /register` and `POST /register` (RFC 7591 dynamic client registration)

All return a uniform JSON 404 envelope with a hint pointing the user at `/settings/tokens`. Plus a parametrized integration test that hits every observed probe path and asserts JSON content-type — so a future SDK version adding a new probe path fails fast in CI instead of silently breaking installs.

Closes markland-6o6.

## Test plan

- [x] Unit: 4 new tests for the GET probe paths
- [x] Unit: 2 new tests for `/register` (GET + POST)
- [x] Integration: parametrized test covering all 10 observed probe paths
- [x] Refactor: trailing-slash 404 now uses the same JSON envelope as the new paths
- [x] Full suite: 1025+ passed, 0 failed
- [ ] Post-deploy: curl every probe path against `https://markland.dev`; confirm JSON content-type
- [ ] Post-deploy: Claude Code install path produces working `markland_*` tools (the user-visible regression that motivated this)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Capture the PR URL printed by `gh`.

- [ ] **Step 4: Wait for CI to pass**

```bash
gh pr checks <PR_NUMBER>
```

Expected: `test: SUCCESS`. If anything fails, investigate before merging.

---

## Task 6: Merge + deploy

**Files:** none modified — production rollout only.

- [ ] **Step 1: Squash-merge**

```bash
gh pr merge <PR_NUMBER> --squash --delete-branch --admin
```

Note: the `--admin` flag bypasses local-sync errors when the primary worktree has main checked out (this happens routinely in this repo). The remote merge will succeed; only the post-merge local update may fail and we handle that next.

- [ ] **Step 2: Sync the primary worktree's `main`**

```bash
cd /Users/daveyhiles/Developer/markland
git pull --ff-only origin main
```

Expected: fast-forward to the squash-merged commit. If it errors, the primary is on a non-main branch — `git -C /Users/daveyhiles/Developer/markland branch --show-current` to check, then switch to main first.

- [ ] **Step 3: Deploy to Fly**

```bash
cd /Users/daveyhiles/Developer/markland
flyctl deploy -a markland --strategy immediate
```

Expected: deploy completes with exit 0. The `--strategy immediate` flag is established convention in this repo (the launch-group bug forces it).

- [ ] **Step 4: Verify every probe path returns JSON in production**

```bash
for path in \
    "/.well-known/oauth-protected-resource" \
    "/.well-known/oauth-authorization-server" \
    "/.well-known/oauth-protected-resource/" \
    "/.well-known/oauth-protected-resource/mcp" \
    "/.well-known/oauth-authorization-server/mcp" \
    "/.well-known/openid-configuration" \
    "/.well-known/openid-configuration/mcp" \
    "/register"; do
  printf "%-60s " "GET $path"
  curl -s -o /dev/null -w "%{http_code} %{content_type}\n" "https://markland.dev$path"
done
printf "%-60s " "POST /register"
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" -X POST -H "Content-Type: application/json" -d '{}' https://markland.dev/register
printf "%-60s " "GET /mcp/.well-known/openid-configuration"
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" https://markland.dev/mcp/.well-known/openid-configuration
```

Expected output: every line ends with `application/json` (status codes vary: 200 for the protected-resource doc, 401 for the `/mcp/*` middleware path, 404 for everything else). Specifically NO `text/html` anywhere.

If any line shows `text/html`, that path's route registration didn't deploy correctly. Investigate before declaring done.

- [ ] **Step 5: User-facing smoke test**

In a clean shell on the operator's laptop (NOT pasted into chat — token-hygiene per markland-2yj session):

```bash
claude mcp list
```

Expected: `markland: https://markland.dev/mcp (HTTP) - ✓ Connected` (it already shows this; the bug was deeper).

Restart Claude Code (`Ctrl-C` and re-launch). Open `/mcp` in the panel.

Expected: `Status: ✓ connected`, `Auth: ✓ authenticated`, **no `JSON Parse error`** anywhere.

In a session, ask Claude:

> Run `markland_whoami()`

Expected: a real response containing `principal_id`, `email: daveyhiles@gmail.com`, `is_admin: true`. If this returns "tool not available" again, the fix is incomplete — capture fresh production logs from the operator's IP at the moment of the panel-open and inspect for any new probe path not in our coverage list.

- [ ] **Step 6: Close the beads issue**

```bash
bd close markland-6o6 --reason="All observed Claude Code MCP SDK probe paths now return JSON 404 instead of HTML. \`markland_whoami()\` works in real Claude Code sessions. Tools surface correctly. Production-verified at https://markland.dev. PR #<N>."
bd sync
git add .beads/issues.jsonl
git commit -m "chore(beads): close markland-6o6 after deploy + verify"
git push origin main
```

- [ ] **Step 7: Tear down the worktree**

```bash
cd /Users/daveyhiles/Developer/markland
git worktree remove .worktrees/mcp-oauth-probe-coverage
git branch -d feat/mcp-oauth-probe-coverage
```

---

## Self-review

**1. Spec coverage:**
- "JSON 404 for `POST /register`" → Task 2 ✓
- "JSON 404 for `/.well-known/openid-configuration` and `/mcp` suffix" → Task 1 ✓
- "JSON 404 for `oauth-authorization-server/mcp` and `oauth-protected-resource/mcp`" → Task 1 ✓
- "Integration test that hits every probe path" → Task 3 ✓
- "Deploy and verify install path lets Claude Code complete `initialize` and surface tools" → Task 6 (steps 4 + 5) ✓

**2. Placeholder scan:** No "TBD," "implement later," or unspecified behavior. Each step has either a code block, an exact command, or both. The `<PR_NUMBER>` placeholder in Task 6 is intentional — captured from `gh pr create` output in Task 5 step 3. The `<N>` in the bd close reason is the same.

**3. Type / name consistency:**
- `_not_found_envelope` introduced in Task 1, reused in Tasks 2 and 4 ✓
- `register_well_known_routes(app, *, base_url)` signature unchanged from markland-2yj ✓
- `build_app_for_test` helper introduced in Task 3, only referenced inside that test file ✓
- The integration test's parametrize list includes every path tested in the unit tests + the middleware-gated `/mcp/*` path ✓
- Trailing-slash test in Task 4 updates the same test that already exists in the file (not a new test with a parallel name)

**4. One known unknown deliberately not solved here:** the `/mcp/.well-known/openid-configuration` probe gets a 401 from `PrincipalMiddleware`, not a 404. That's actually the right answer for the SDK (JSON content-type, parse-clean) but it might confuse a spec reader. If a future user reports that the middleware's 401-on-OAuth-probe is misleading, file a separate beads issue to special-case probe paths inside the middleware. Not blocking for this fix.

---

## Out of scope (deliberately deferred)

- Filing the upstream Claude Code SDK bug. The SDK ignoring `authorization_servers: []` and probing DCR anyway is a real spec violation; we should report it, but a fix to their SDK would take weeks while this server-side patch unblocks users today.
- Adding rate limiting to `/register`. SDKs probe it once on startup; rate-limiting the JSON 404 isn't worth the surface area unless we see abuse signals.
- Refactoring `_not_found_envelope` into a module-level constant. It depends on `token_mint_url` (computed from `base_url`), so it can't be module-level without restructuring the registrar's signature. Cosmetic.
