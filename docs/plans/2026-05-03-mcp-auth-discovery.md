# MCP Auth Discovery (markland-2yj) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Markland's `/mcp` endpoint advertise its bearer-token-only auth model so MCP clients that auto-probe for OAuth get a JSON-shaped, legible response instead of falling into Markland's HTML 404 page and crashing on `Unrecognized token '<'`.

**Architecture:** Two server-side surfaces. (1) `PrincipalMiddleware` adds a `WWW-Authenticate: Bearer realm="markland", resource_metadata="<base>/.well-known/oauth-protected-resource"` header to the existing 401 responses on protected paths (per RFC 9728 / MCP authz spec 2025-03-26). (2) Two new public routes serve `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server` as JSON — the protected-resource doc declares the bearer scheme and points at `/settings/tokens`, the authorization-server doc returns a 404 with a JSON body (so SDK probes parse cleanly). Then republish the public Quickstart doc (`3366aa58f6ead5e7`) so the live install instructions match the runbook.

**Tech Stack:** FastAPI + Starlette middleware, pytest + httpx TestClient (existing conventions), checked-in admin scripts under `scripts/admin/` for the production republish step.

**Reference signals (verified 2026-05-03):**

```
$ curl -i -s -X POST https://markland.dev/mcp -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
HTTP/2 401
content-type: application/json
{"error":"unauthenticated"}                  # <-- no WWW-Authenticate header

$ curl -s -o /dev/null -w "%{http_code} %{content_type}\n" \
    https://markland.dev/.well-known/oauth-protected-resource
404 text/html; charset=utf-8                # <-- HTML 404 trips JSON.parse('<')
```

The Claude Code MCP SDK reproduces the bug as:

> `SDK auth failed: HTTP 404: Invalid OAuth error response: SyntaxError: JSON Parse error: Unrecognized token '<'. Raw body: <!DOCTYPE html>...`

---

## File Structure

| File | Responsibility |
|---|---|
| `src/markland/web/principal_middleware.py` | Existing 401 response gains a `WWW-Authenticate` header (single helper, single change site). |
| `src/markland/web/well_known_routes.py` | **New.** Holds the two `/.well-known/*` route handlers and the JSON bodies they return. Pure functions + a `register_well_known_routes(app, *, base_url)` registrar so tests can mount it on a bare FastAPI app. |
| `src/markland/web/app.py` | Adds one call: `register_well_known_routes(app, base_url=base_url)` near the existing public routes (e.g. next to `/robots.txt`). |
| `tests/test_principal_middleware_www_authenticate.py` | **New.** Asserts the header is present on 401 responses and absent on success. |
| `tests/test_well_known_oauth.py` | **New.** Asserts the two `/.well-known/*` endpoints return JSON with the right shape and status codes. |
| `seed-content/admin/07-quickstart-claude-code.md` | Already locally edited (this session) to use `--transport http --scope user --header`. Republish to production at the end. |

We do NOT touch `src/markland/server.py` (the FastMCP instance) — discovery happens at the FastAPI layer that wraps it.

---

## Task 1: WWW-Authenticate header on 401

**Why first:** This is the single change that makes any spec-compliant MCP client (a) stop attempting OAuth entirely if it sees `Bearer` realm-only, or (b) at least know where to look for metadata. Smallest, lowest-risk piece — does not introduce new routes.

**Files:**
- Modify: `src/markland/web/principal_middleware.py:36-55`
- Test: `tests/test_principal_middleware_www_authenticate.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_principal_middleware_www_authenticate.py`:

```python
"""Tests that PrincipalMiddleware advertises auth scheme via WWW-Authenticate.

Per RFC 9728 + MCP authorization spec (2025-03-26), a 401 from a protected
MCP endpoint should carry a WWW-Authenticate header pointing the client at
the resource-metadata URL. Without this, MCP SDK clients fall through to
speculative OAuth discovery and crash on Markland's HTML 404 page.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.auth import create_user_token
from markland.service.users import create_user
from markland.web.principal_middleware import PrincipalMiddleware


def _app(conn):
    app = FastAPI()
    app.add_middleware(PrincipalMiddleware, db_conn=conn, protected_prefixes=("/mcp",))

    @app.get("/mcp/ping")
    def mcp_ping(request: Request):
        p = request.state.principal
        return JSONResponse({"id": p.principal_id})

    @app.get("/public")
    def public():
        return JSONResponse({"ok": True})

    return app


def test_401_missing_header_advertises_bearer(tmp_path):
    conn = init_db(tmp_path / "t.db")
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping")
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}
    www_auth = r.headers.get("www-authenticate", "")
    assert www_auth.startswith("Bearer "), f"expected Bearer scheme, got {www_auth!r}"
    assert 'realm="markland"' in www_auth
    assert 'resource_metadata=' in www_auth
    assert "/.well-known/oauth-protected-resource" in www_auth


def test_401_unknown_token_advertises_bearer(tmp_path):
    conn = init_db(tmp_path / "t.db")
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping", headers={"Authorization": "Bearer mk_usr_unknown"})
    assert r.status_code == 401
    assert r.headers.get("www-authenticate", "").startswith("Bearer ")


def test_200_does_not_set_www_authenticate(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="a@example.com", display_name="A")
    _, plaintext = create_user_token(conn, user_id=u.id, label="l")
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping", headers={"Authorization": f"Bearer {plaintext}"})
    assert r.status_code == 200
    assert "www-authenticate" not in {k.lower() for k in r.headers.keys()}


def test_unprotected_path_does_not_set_www_authenticate(tmp_path):
    conn = init_db(tmp_path / "t.db")
    client = TestClient(_app(conn))
    r = client.get("/public")
    assert r.status_code == 200
    assert "www-authenticate" not in {k.lower() for k in r.headers.keys()}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_principal_middleware_www_authenticate.py -v
```

Expected: FAIL on `test_401_missing_header_advertises_bearer` and `test_401_unknown_token_advertises_bearer` (no `WWW-Authenticate` header on existing 401 responses). The other two tests should already pass.

- [ ] **Step 3: Add the header to PrincipalMiddleware's 401 responses**

Edit `src/markland/web/principal_middleware.py`. Replace the body of `dispatch` (lines 36-55) with:

```python
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not any(path.startswith(p) for p in self._prefixes):
            return await call_next(request)

        # Honor pre-injected principals (test harness path).
        if getattr(request.state, "principal", None) is not None:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return self._unauthenticated(request)

        plaintext = header[7:].strip()
        principal = resolve_token(self._conn, plaintext)
        if principal is None:
            return self._unauthenticated(request)

        request.state.principal = principal
        return await call_next(request)

    @staticmethod
    def _unauthenticated(request: Request) -> JSONResponse:
        # Per RFC 9728 + MCP authorization spec (2025-03-26), advertise the
        # resource-metadata URL so well-behaved MCP clients can discover that
        # this server uses static bearer tokens (no OAuth) instead of
        # speculatively probing /.well-known paths and tripping over HTML 404s.
        scheme = request.url.scheme
        host = request.headers.get("host", request.url.netloc)
        metadata_url = f"{scheme}://{host}/.well-known/oauth-protected-resource"
        return JSONResponse(
            {"error": "unauthenticated"},
            status_code=401,
            headers={
                "WWW-Authenticate": (
                    f'Bearer realm="markland", resource_metadata="{metadata_url}"'
                ),
            },
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_principal_middleware_www_authenticate.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Re-run the existing principal-middleware suite to confirm no regression**

```bash
uv run pytest tests/test_principal_middleware.py tests/test_principal_middleware_admin.py -v
```

Expected: all green. The new `_unauthenticated` helper preserves the JSON body shape `{"error": "unauthenticated"}` that those tests assert on.

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/principal_middleware.py tests/test_principal_middleware_www_authenticate.py
git commit -m "feat(mcp): advertise bearer auth via WWW-Authenticate on 401 (markland-2yj)"
```

---

## Task 2: `/.well-known/oauth-protected-resource` route

**Why second:** With Task 1 done, clients now know where to look. This task makes that URL return a parseable, spec-compliant JSON body instead of HTML.

**Files:**
- Create: `src/markland/web/well_known_routes.py`
- Modify: `src/markland/web/app.py` (add one call near `/robots.txt` registration)
- Test: `tests/test_well_known_oauth.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_well_known_oauth.py`:

```python
"""Tests for /.well-known/oauth-protected-resource and /.well-known/oauth-authorization-server.

These endpoints exist to give MCP clients a JSON-shaped answer when they
auto-probe for OAuth discovery. They MUST NOT trip clients into a real OAuth
flow — Markland uses static bearer tokens.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from markland.web.well_known_routes import register_well_known_routes


def _app():
    app = FastAPI()
    register_well_known_routes(app, base_url="https://markland.dev")
    return app


def test_protected_resource_returns_json_200(tmp_path):
    client = TestClient(_app())
    r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    # RFC 9728 fields
    assert body["resource"] == "https://markland.dev/mcp"
    assert "Bearer" in body["bearer_methods_supported"]
    # Markland-specific hint pointing humans at the token-mint UI
    assert body["token_mint_url"].endswith("/settings/tokens")
    # Explicitly NO authorization_servers — we don't speak OAuth
    assert body.get("authorization_servers", []) == []


def test_authorization_server_returns_json_404():
    """SDK probes that fall through to /.well-known/oauth-authorization-server
    must get a JSON body with a 404 status — never HTML — so JSON.parse() succeeds.
    """
    client = TestClient(_app())
    r = client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["error"] == "no_oauth_server"
    assert "bearer" in body["error_description"].lower()


def test_protected_resource_path_is_exact():
    """Trailing-slash and case variants should NOT match — keeps the surface tight."""
    client = TestClient(_app())
    assert client.get("/.well-known/oauth-protected-resource/").status_code == 404
    assert client.get("/.WELL-KNOWN/oauth-protected-resource").status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_well_known_oauth.py -v
```

Expected: ImportError / collection failure — `markland.web.well_known_routes` does not yet exist.

- [ ] **Step 3: Create the new module**

Create `src/markland/web/well_known_routes.py`:

```python
"""Public OAuth-discovery routes that exist solely to satisfy MCP client probes.

Markland uses static bearer tokens (mint at /settings/tokens). Clients that
auto-probe for OAuth metadata (per RFC 9728 / MCP authorization spec
2025-03-26) hit these routes and receive JSON — not the styled HTML 404 page,
which would crash JSON.parse() in the client SDK with `Unrecognized token <`.

The protected-resource doc explicitly carries an empty `authorization_servers`
list so spec-aware clients short-circuit and use the static bearer path.
The authorization-server endpoint returns 404 with a JSON body for clients
that don't understand the empty-list signal and probe further.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse


def register_well_known_routes(app: FastAPI, *, base_url: str) -> None:
    """Mount the two /.well-known/* discovery routes on `app`.

    `base_url` is the public origin (e.g. `https://markland.dev`) used to build
    the canonical `resource` field. We do NOT derive this per-request: the
    metadata is meant to describe the server's identity, not the proxy hop.
    """

    resource_url = f"{base_url.rstrip('/')}/mcp"
    token_mint_url = f"{base_url.rstrip('/')}/settings/tokens"

    @app.get("/.well-known/oauth-protected-resource")
    def oauth_protected_resource() -> JSONResponse:
        return JSONResponse(
            {
                "resource": resource_url,
                "authorization_servers": [],
                "bearer_methods_supported": ["Bearer"],
                "resource_documentation": f"{base_url.rstrip('/')}/quickstart",
                # Non-RFC field — practical hint for human/agent eyeballs
                # that read the JSON when an SDK error surfaces it.
                "token_mint_url": token_mint_url,
            },
            status_code=200,
        )

    @app.get("/.well-known/oauth-authorization-server")
    def oauth_authorization_server() -> JSONResponse:
        return JSONResponse(
            {
                "error": "no_oauth_server",
                "error_description": (
                    "Markland does not run an OAuth authorization server. "
                    "Use a static bearer token minted at "
                    f"{token_mint_url}."
                ),
            },
            status_code=404,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_well_known_oauth.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/well_known_routes.py tests/test_well_known_oauth.py
git commit -m "feat(mcp): serve /.well-known/oauth-protected-resource as JSON (markland-2yj)"
```

---

## Task 3: Wire the well-known routes into the main app

**Files:**
- Modify: `src/markland/web/app.py` near line 306 (just before `@app.get("/robots.txt")`).

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_well_known_integration.py`:

```python
"""End-to-end: the discovery routes are reachable on the main FastAPI app
and the WWW-Authenticate header on /mcp 401s points at a URL that actually
returns JSON 200."""

from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import build_app


def test_discovery_url_in_www_authenticate_returns_json(tmp_path):
    conn = init_db(tmp_path / "t.db")
    app = build_app(
        db_conn=conn,
        base_url="http://testserver",
        enable_presence_gc=False,
        mount_mcp=False,  # PrincipalMiddleware still gates /mcp paths even unmounted
    )
    client = TestClient(app)

    r = client.get("/mcp/anything")
    assert r.status_code == 401
    www_auth = r.headers["www-authenticate"]
    # Extract the resource_metadata="..." URL from the header.
    import re
    m = re.search(r'resource_metadata="([^"]+)"', www_auth)
    assert m, f"no resource_metadata in {www_auth!r}"
    metadata_url = m.group(1)

    # Strip scheme+host — TestClient is single-origin.
    from urllib.parse import urlparse
    path = urlparse(metadata_url).path
    r2 = client.get(path)
    assert r2.status_code == 200
    assert r2.headers["content-type"].startswith("application/json")
    assert r2.json()["resource"] == "http://testserver/mcp"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_well_known_integration.py -v
```

Expected: FAIL on the metadata-URL fetch — the routes are defined in `well_known_routes.py` but not yet registered on `build_app`'s `app`.

- [ ] **Step 3: Register the routes in app.py**

Edit `src/markland/web/app.py`. At the top of the file, add the import alongside the existing web imports:

```python
from markland.web.well_known_routes import register_well_known_routes
```

Then, immediately before the `@app.get("/robots.txt", response_class=PlainTextResponse)` block (currently at line 306), add:

```python
    register_well_known_routes(app, base_url=base_url)

```

(One blank line above and below; matches the surrounding spacing style.)

- [ ] **Step 4: Run the integration test**

```bash
uv run pytest tests/test_well_known_integration.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the full test suite to catch any regressions in routing**

```bash
uv run pytest -x
```

Expected: all green. Pay special attention to `test_404_page.py` (the existing 404-handler test) — confirm it still passes unchanged. Our new routes have specific paths and don't intercept the catch-all 404.

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/app.py tests/test_well_known_integration.py
git commit -m "feat(mcp): wire /.well-known/* discovery into main app (markland-2yj)"
```

---

## Task 4: Production verification

**Why:** The bug is "this fails *in production* against markland.dev." We must confirm the deployed surface no longer trips Claude Code's MCP SDK before declaring done.

**Files:** none modified — verification step only.

- [ ] **Step 1: Deploy**

Push the merged PR to main and wait for the Fly deploy. Confirm via:

```bash
flyctl status -a markland
```

Expected: latest release is the one containing all three commits above; status is `running`.

- [ ] **Step 2: Verify the 401 carries the new header in production**

```bash
curl -i -s -X POST https://markland.dev/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | head -20
```

Expected: `HTTP/2 401`, body `{"error":"unauthenticated"}`, AND a `www-authenticate: Bearer realm="markland", resource_metadata="https://markland.dev/.well-known/oauth-protected-resource"` header.

- [ ] **Step 3: Verify the protected-resource doc returns JSON 200**

```bash
curl -s -i https://markland.dev/.well-known/oauth-protected-resource | head -20
```

Expected: `HTTP/2 200`, `content-type: application/json`, body containing `"resource":"https://markland.dev/mcp"` and `"token_mint_url":"https://markland.dev/settings/tokens"`.

- [ ] **Step 4: Verify the authorization-server probe returns JSON 404**

```bash
curl -s -i https://markland.dev/.well-known/oauth-authorization-server | head -20
```

Expected: `HTTP/2 404`, `content-type: application/json`, body containing `"error":"no_oauth_server"`. **Specifically NOT HTML** — `<!DOCTYPE` must not appear in the body.

- [ ] **Step 5: Reproduce the original Claude Code install path with no header**

In a scratch directory, run:

```bash
claude mcp remove markland-test 2>/dev/null
claude mcp add --transport http markland-test https://markland.dev/mcp
claude
# inside Claude Code: open /mcp, look at the markland-test entry
```

Expected: the error surface for `markland-test` no longer contains `JSON Parse error: Unrecognized token '<'`. It should now show either a clean `unauthenticated` failure with a hint that points at the resource-metadata URL, or — for SDKs that respect empty `authorization_servers` — a "no auth configured" message. Cleanup:

```bash
claude mcp remove markland-test
```

- [ ] **Step 6: Commit verification evidence (optional, if anything surprising)**

If any of the curl outputs differ from expected, capture them under `cutover-evidence/markland-2yj/` and commit. Otherwise no commit needed for this step.

---

## Task 5: Republish the public Quickstart doc

**Why:** The published copy on `https://markland.dev/d/ukglp7mO8Dbyx2SbvYOoWg` (doc_id `3366aa58f6ead5e7`, the doc featured on the landing page) still has the old, broken install command:

```bash
claude mcp add markland --token "mk_usr_..." https://markland.dev/mcp
```

The local copy at `seed-content/admin/07-quickstart-claude-code.md` was already corrected earlier in this session (uses `--transport http --scope user --header "Authorization: Bearer ..."`). This task pushes the corrected content to production.

**Files:**
- Create: `scripts/admin/republish_doc.py`
- Modify: none on the web app side (script-only).

- [ ] **Step 1: Write a reusable republish script**

Create `scripts/admin/republish_doc.py`:

```python
"""Replace the content of an existing doc with a markdown file from disk.

Usage (run on the Fly machine):
    /app/.venv/bin/python scripts/admin/republish_doc.py \\
        --doc-id <doc_id> \\
        --owner-email <email> \\
        --content-path <path-to-md>

The script uses `service.docs.update` so it goes through the same audit /
version path as a real MCP `markland_update` call. The token is resolved from
the owner's first active token; this script is admin-only and assumes you've
already minted one (see scripts/admin/mint_admin_token.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from markland.config import get_config
from markland.db import init_db
from markland.service import docs as docs_svc
from markland.service.auth import resolve_token
from markland.service.users import get_user_by_email


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--doc-id", required=True)
    p.add_argument("--owner-email", required=True)
    p.add_argument("--content-path", required=True)
    args = p.parse_args()

    cfg = get_config()
    conn = init_db(cfg.db_path)

    owner = get_user_by_email(conn, args.owner_email)
    if owner is None:
        print(f"error: no user with email={args.owner_email}", file=sys.stderr)
        return 1

    # Find any active (non-revoked) token for this user.
    row = conn.execute(
        "SELECT id FROM tokens WHERE principal_id=? AND principal_type='user' "
        "AND revoked_at IS NULL ORDER BY created_at DESC LIMIT 1",
        (owner.id,),
    ).fetchone()
    if row is None:
        print(
            f"error: {args.owner_email} has no active token. "
            f"Mint one with mint_admin_token.py first.",
            file=sys.stderr,
        )
        return 1

    # We can't recover the plaintext, so we directly construct a Principal
    # without resolve_token. Use docs_svc.get + update with the user object.
    content = Path(args.content_path).read_text(encoding="utf-8")
    current = docs_svc.get(conn, doc_id=args.doc_id)
    if current is None:
        print(f"error: doc {args.doc_id} not found", file=sys.stderr)
        return 1

    from markland.models import Principal
    principal = Principal(
        principal_id=owner.id,
        principal_type="user",
        is_admin=bool(owner.is_admin),
    )

    updated = docs_svc.update(
        conn,
        doc_id=args.doc_id,
        content=content,
        principal=principal,
        if_version=current.version,
        base_url=cfg.base_url,
    )
    print(f"updated doc {updated.id} → version={updated.version} title={updated.title!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> **Note:** Cross-check the actual `docs_svc.update` and `Principal` signatures before running — if the field names differ (`User.is_admin` vs `Principal.is_admin`, `update`'s `principal` vs `actor` param), adjust the call site in this script. Don't change the service signatures themselves.

- [ ] **Step 2: Verify the script's imports resolve locally**

```bash
uv run python -c "import scripts.admin.republish_doc"
```

Expected: no error. If `scripts` isn't a package, run instead:

```bash
uv run python scripts/admin/republish_doc.py --help
```

Expected: argparse usage banner with the three flags.

- [ ] **Step 3: Verify the content file exists and is the corrected version**

```bash
grep -n "claude mcp add" seed-content/admin/07-quickstart-claude-code.md
```

Expected: matches a line containing `--transport http --scope user --header "Authorization: Bearer`. If it shows the old `--token` form, re-apply the local edits before continuing.

- [ ] **Step 4: Commit the script (Dockerfile already copies scripts/)**

```bash
git add scripts/admin/republish_doc.py
git commit -m "feat(admin): scripts/admin/republish_doc.py — overwrite doc content from a file (markland-2yj)"
```

- [ ] **Step 5: Wait for the deploy of Tasks 1-3 + 5 to land**

Same Fly deploy as Task 4. Confirm:

```bash
flyctl ssh console -a markland -C "ls /app/scripts/admin/republish_doc.py"
```

Expected: the path is listed (single line, no error). If it errors with "no such file," the Dockerfile didn't pick up the new script — verify `Dockerfile` still has `COPY scripts /app/scripts` before re-deploying.

- [ ] **Step 6: Republish the Quickstart doc on production**

```bash
flyctl ssh sftp shell -a markland <<'EOF'
put seed-content/admin/07-quickstart-claude-code.md /tmp/quickstart.md
EOF

flyctl ssh console -a markland -C "/app/.venv/bin/python scripts/admin/republish_doc.py \
  --doc-id 3366aa58f6ead5e7 \
  --owner-email daveyhiles@gmail.com \
  --content-path /tmp/quickstart.md"
```

Expected output: `updated doc 3366aa58f6ead5e7 → version=N title='Quickstart: install Markland MCP in Claude Code'` where N is the previous version + 1.

- [ ] **Step 7: Verify the live page**

```bash
curl -s https://markland.dev/d/ukglp7mO8Dbyx2SbvYOoWg | grep -o 'claude mcp add[^<]*' | head -3
```

Expected: includes `--transport http --scope user --header`. Specifically NOT `--token`.

- [ ] **Step 8: Update beads**

```bash
bd close markland-2yj --reason="Server advertises bearer auth via WWW-Authenticate + /.well-known/oauth-protected-resource. Quickstart doc republished with correct --header install command."
bd sync
```

---

## Self-review

**Spec coverage:**
- "Add WWW-Authenticate header on 401" → Task 1 ✓
- "Serve /.well-known/oauth-protected-resource as RFC 9728 JSON" → Task 2 ✓ (and Task 3 wires it to the live app)
- "Republish public docs (Quickstart at doc_id 3366aa58f6ead5e7) to push the corrected --header install command live" → Task 5 ✓
- Implied: production verification of the bug fix → Task 4 ✓

**Placeholder scan:** No "TBD," "implement later," or "similar to Task N" — every step has explicit code, paths, or commands. The one judgment call is in Task 5 Step 1's note about adjusting `docs_svc.update`'s param names if they differ; that's flagged as a verification step, not a placeholder.

**Type/name consistency:**
- `register_well_known_routes(app, *, base_url)` is defined in Task 2 and called the same way in Task 3 ✓
- `_unauthenticated` helper introduced in Task 1 and not referenced elsewhere ✓
- The `WWW-Authenticate` header value uses the same exact format in the implementation (Task 1 Step 3) and the assertions (Task 1 Step 1: `'realm="markland"'` and `'resource_metadata='`) ✓
- `tests/test_principal_middleware.py` (existing) asserts `r.json() == {"error": "unauthenticated"}` — Task 1's helper preserves that body ✓
- `Principal` field names in Task 5's republish script need verification at write time (flagged in Step 1 note); won't break the plan, but the engineer should not change service signatures to match the script.

**Risks called out for the engineer:**
- Task 1's `_unauthenticated` builds the metadata URL from `request.url.scheme` and `Host` header. Behind Fly.io's proxy, `request.url.scheme` may be `http` even though the public URL is `https`. If production verification (Task 4 Step 2) shows `http://` in the header, switch to using `base_url` (passed into the middleware constructor) instead of deriving from the request. The middleware doesn't currently take `base_url` — adding that param is a one-line change in `src/markland/web/app.py:768-779` where `PrincipalMiddleware` is registered.
- Task 5's republish script bypasses MCP. It runs on the Fly machine using a server-side `Principal` constructed from a User row. This is only safe because the script runs under SSH access (already an admin trust boundary). Don't expose this script as an HTTP endpoint.

---

## Out of scope (deliberately deferred)

- Implementing a real OAuth authorization server. Markland is bearer-only; clients that don't respect empty `authorization_servers` lists will still see the 404 (now JSON, at least). If we later want broader client compatibility, that's a separate plan.
- Updating the runbook (`docs/runbooks/admin-operations.md`). It already mentions `--header`; only the published Quickstart doc was stale. If we add the `republish_doc.py` script, a one-line addition to the runbook's "Admin scripts" table would be welcome but is a docs-only follow-up — file as a beads issue if you want it tracked.
