# Hosted Infrastructure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Note:** No git commits during execution — this project is not a git repo at time of writing; the user manages version control manually. Where commit steps would normally appear, a "verification" step is substituted.

**Goal:** Make the existing Markland app reachable at `https://markland.dev/mcp` and `https://markland.dev/` as a single deployable Fly.io service, behind a single hardcoded admin bearer token. No user accounts, no grants, no ownership logic — that's all later plans. This plan ends with the current local stdio behavior replicated over HTTP, from a production host, with Litestream-backed SQLite durability, Sentry error capture, a Resend client stub, and a GitHub Actions deploy pipeline.

**Architecture:** One FastAPI app mounts FastMCP's `streamable-http` ASGI app at `/mcp` and keeps existing web routes (`/`, `/explore`, `/d/<token>`, `/health`). An auth middleware gates `/mcp` behind `Authorization: Bearer <MARKLAND_ADMIN_TOKEN>`. A single uvicorn process serves everything. Fly.io runs the container with a persistent volume at `/data` for SQLite, Litestream replicates the DB to Cloudflare R2 continuously, and a GitHub Actions workflow deploys on push to `main`.

**Tech Stack:** Python 3.12, FastAPI, FastMCP, uvicorn, SQLite (WAL), Litestream, Sentry SDK, Resend SDK, Fly.io, Cloudflare R2, Cloudflare DNS, GitHub Actions.

**Scope excluded (this plan):** Users, agents, grants, invites, device flow, conflict handling, presence, email notifications (client stub only, no triggers), rate limits beyond a token bucket, migration from local DBs, admin UI.

---

## File Structure

**New files:**
- `src/markland/run_app.py` — unified HTTP entrypoint (web + MCP + auth + Sentry init)
- `src/markland/service/__init__.py` — new service layer
- `src/markland/service/email.py` — Resend client wrapper, no triggers yet
- `src/markland/web/auth_middleware.py` — bearer-token gate for `/mcp` path prefix
- `Dockerfile` — container image
- `scripts/start.sh` — container entrypoint; runs `litestream restore` then exec-runs uvicorn under `litestream replicate`
- `litestream.yml` — replication config for `/data/markland.db` → R2
- `fly.toml` — Fly app config
- `.github/workflows/deploy.yml` — CI deploy to Fly on push to main
- `docs/runbooks/first-deploy.md` — manual operator steps for the one-time Fly launch + DNS + secrets
- `tests/test_http_mcp.py` — integration tests: MCP calls via HTTP with auth
- `tests/test_auth_middleware.py` — unit tests for bearer-token gating
- `tests/test_email_service.py` — unit tests for Resend wrapper (mocked)
- `tests/test_sentry_init.py` — unit test for Sentry init conditional

**Modified files:**
- `pyproject.toml` — add `sentry-sdk`, `resend` dependencies
- `.env.example` — add `MARKLAND_ADMIN_TOKEN`, `SENTRY_DSN`, `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `LITESTREAM_*` vars
- `src/markland/config.py` — add `admin_token`, `sentry_dsn`, `resend_api_key`, `resend_from_email` fields
- `README.md` — append a "Running Hosted (Fly.io)" section with runbook link

**Unchanged:** `server.py` (stdio MCP still works for local dev), `run_web.py` (deprecated but not deleted), all existing DB/tool/template code.

---

## Task 1: Add admin token to config

**Files:**
- Modify: `src/markland/config.py`
- Modify: `.env.example`
- Modify: `tests/test_documents.py` (context; may need reset_config call)

- [x] **Step 1: Write the failing test**

Create new test file `tests/test_config.py`:

```python
"""Tests for config loading."""

import os

from markland.config import get_config, reset_config


def test_admin_token_loaded_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKLAND_ADMIN_TOKEN", "mk_admin_test_xyz")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    cfg = get_config()
    assert cfg.admin_token == "mk_admin_test_xyz"


def test_admin_token_empty_when_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("MARKLAND_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    cfg = get_config()
    assert cfg.admin_token == ""


def test_sentry_dsn_and_resend_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTRY_DSN", "https://fake@sentry.io/1")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "test@markland.dev")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    cfg = get_config()
    assert cfg.sentry_dsn == "https://fake@sentry.io/1"
    assert cfg.resend_api_key == "re_test"
    assert cfg.resend_from_email == "test@markland.dev"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `cfg.admin_token` attribute does not exist yet.

- [x] **Step 3: Update `src/markland/config.py`**

Replace the full file with:

```python
"""Environment-based configuration for Markland."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    base_url: str
    data_dir: Path
    web_port: int
    admin_token: str
    sentry_dsn: str
    resend_api_key: str
    resend_from_email: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "markland.db"


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        data_dir_env = os.getenv("MARKLAND_DATA_DIR", "").strip()
        data_dir = Path(data_dir_env).expanduser() if data_dir_env else Path.home() / ".markland"
        data_dir.mkdir(parents=True, exist_ok=True)
        _config = Config(
            base_url=os.getenv("MARKLAND_BASE_URL", "http://localhost:8950").rstrip("/"),
            data_dir=data_dir,
            web_port=int(os.getenv("MARKLAND_WEB_PORT", "8950")),
            admin_token=os.getenv("MARKLAND_ADMIN_TOKEN", "").strip(),
            sentry_dsn=os.getenv("SENTRY_DSN", "").strip(),
            resend_api_key=os.getenv("RESEND_API_KEY", "").strip(),
            resend_from_email=os.getenv("RESEND_FROM_EMAIL", "notifications@markland.dev").strip(),
        )
    return _config


def reset_config() -> None:
    """Reset cached config (for tests)."""
    global _config
    _config = None
```

- [x] **Step 4: Update `.env.example`**

Replace full file contents with:

```
# Base URL for generating share links (default: http://localhost:8950)
MARKLAND_BASE_URL=http://localhost:8950

# Directory for SQLite database (default: ~/.markland)
MARKLAND_DATA_DIR=

# Port for web viewer / HTTP server (default: 8950)
MARKLAND_WEB_PORT=8950

# Admin bearer token for /mcp in hosted mode. Leave empty in local stdio mode.
# Generate: python -c "import secrets; print('mk_admin_' + secrets.token_urlsafe(32))"
MARKLAND_ADMIN_TOKEN=

# Sentry DSN for error tracking. Leave empty to disable.
SENTRY_DSN=

# Resend API key for transactional email. Leave empty to disable.
RESEND_API_KEY=
RESEND_FROM_EMAIL=notifications@markland.dev
```

- [x] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (3 tests).

- [x] **Step 6: Verify existing tests still pass**

Run: `uv run pytest tests/ -v`
Expected: PASS for the full suite (prior count + 3 new tests).

---

## Task 2: Bearer-token auth middleware for /mcp

**Files:**
- Create: `src/markland/web/auth_middleware.py`
- Create: `tests/test_auth_middleware.py`

- [x] **Step 1: Write the failing tests**

Create `tests/test_auth_middleware.py`:

```python
"""Tests for admin bearer-token middleware."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from markland.web.auth_middleware import AdminBearerMiddleware


def _app(token: str) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AdminBearerMiddleware, admin_token=token, protected_prefix="/mcp")

    @app.get("/mcp/ping")
    def mcp_ping():
        return JSONResponse({"ok": True})

    @app.get("/public")
    def public():
        return JSONResponse({"ok": True})

    return app


def test_unprotected_path_does_not_require_auth():
    client = TestClient(_app("secret"))
    assert client.get("/public").status_code == 200


def test_protected_path_without_auth_returns_401():
    client = TestClient(_app("secret"))
    r = client.get("/mcp/ping")
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}


def test_protected_path_with_wrong_token_returns_401():
    client = TestClient(_app("secret"))
    r = client.get("/mcp/ping", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_protected_path_with_correct_token_returns_200():
    client = TestClient(_app("secret"))
    r = client.get("/mcp/ping", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_malformed_authorization_header_returns_401():
    client = TestClient(_app("secret"))
    r = client.get("/mcp/ping", headers={"Authorization": "secret"})  # missing Bearer
    assert r.status_code == 401


def test_empty_admin_token_rejects_all_requests_to_protected_path():
    # When admin_token is empty (local dev), /mcp should be disabled entirely.
    client = TestClient(_app(""))
    r = client.get("/mcp/ping", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 401
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth_middleware.py -v`
Expected: FAIL — `markland.web.auth_middleware` does not exist.

- [x] **Step 3: Implement the middleware**

Create `src/markland/web/auth_middleware.py`:

```python
"""Bearer-token middleware for gating the /mcp endpoint."""

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class AdminBearerMiddleware(BaseHTTPMiddleware):
    """Require `Authorization: Bearer <admin_token>` on paths under `protected_prefix`.

    When `admin_token` is empty, all requests to the protected prefix are rejected
    (the endpoint is effectively disabled — prevents accidental exposure in local dev).
    """

    def __init__(self, app, *, admin_token: str, protected_prefix: str = "/mcp") -> None:
        super().__init__(app)
        self._admin_token = admin_token
        self._prefix = protected_prefix

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(self._prefix):
            return await call_next(request)

        if not self._admin_token:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)

        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return JSONResponse({"error": "unauthenticated"}, status_code=401)

        presented = header[7:].strip()
        if not hmac.compare_digest(presented, self._admin_token):
            return JSONResponse({"error": "unauthenticated"}, status_code=401)

        return await call_next(request)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth_middleware.py -v`
Expected: PASS (6 tests).

---

## Task 3: HTTP MCP transport mounted on FastAPI

**Files:**
- Modify: `src/markland/web/app.py` (accept an optional MCP app to mount)
- Create: `tests/test_http_mcp.py`

Background: FastMCP exposes `mcp.streamable_http_app()` which returns an ASGI app speaking MCP's HTTP transport. We mount it at `/mcp` on the main FastAPI app. The existing `server.py` stdio entry point stays untouched — it still works for local dev.

- [x] **Step 1: Write the failing test**

Create `tests/test_http_mcp.py`:

```python
"""Integration test: MCP tools reachable over HTTP with bearer auth."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("MARKLAND_ADMIN_TOKEN", "test_admin_token")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    from markland.config import reset_config
    reset_config()
    conn = init_db(db_path)
    app = create_app(conn, mount_mcp=True, admin_token="test_admin_token")
    with TestClient(app) as c:
        yield c


def test_mcp_endpoint_rejects_unauthenticated(client):
    r = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r.status_code == 401


def test_mcp_endpoint_accepts_authenticated_initialize(client):
    r = client.post(
        "/mcp/",
        headers={"Authorization": "Bearer test_admin_token", "Accept": "application/json, text/event-stream"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
    )
    # 200 with JSON-RPC body OR SSE stream opening (200) — either is success.
    assert r.status_code == 200


def test_web_routes_still_public(client):
    # /health, /, /explore should remain reachable without auth.
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/explore").status_code == 200
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_http_mcp.py -v`
Expected: FAIL — `create_app` does not accept `mount_mcp`/`admin_token` kwargs yet.

- [x] **Step 3: Extract MCP app factory**

Modify `src/markland/server.py` — add a factory near the bottom, preserving the stdio `__main__` behavior:

```python
"""Markland MCP Server — publish and share markdown documents."""

import logging

from mcp.server.fastmcp import FastMCP

from markland.config import get_config
from markland.db import init_db
from markland.tools.documents import (
    delete_doc,
    feature_doc,
    get_doc,
    list_docs,
    publish_doc,
    search_docs,
    set_visibility_doc,
    share_doc,
    update_doc,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("markland")


def build_mcp(db_conn, base_url: str) -> FastMCP:
    """Build a FastMCP instance with all Markland tools registered.

    Factored out so the same tool set can run under stdio (this file's __main__)
    or mounted as an ASGI sub-app (see src/markland/web/app.py).
    """
    mcp = FastMCP("markland")

    @mcp.tool()
    def markland_publish(content: str, title: str | None = None, public: bool = False) -> dict:
        """Publish a markdown document and get a shareable link."""
        return publish_doc(db_conn, base_url, title, content, public=public)

    @mcp.tool()
    def markland_list() -> list[dict]:
        """List all published documents, most recent first."""
        return list_docs(db_conn)

    @mcp.tool()
    def markland_get(doc_id: str) -> dict:
        """Get a document's full content by ID."""
        return get_doc(db_conn, doc_id)

    @mcp.tool()
    def markland_search(query: str) -> list[dict]:
        """Search documents by title or content."""
        return search_docs(db_conn, query)

    @mcp.tool()
    def markland_share(doc_id: str) -> dict:
        """Get the shareable link for a document."""
        return share_doc(db_conn, base_url, doc_id)

    @mcp.tool()
    def markland_update(doc_id: str, content: str | None = None, title: str | None = None) -> dict:
        """Update a document's content or title."""
        return update_doc(db_conn, base_url, doc_id, content=content, title=title)

    @mcp.tool()
    def markland_delete(doc_id: str) -> dict:
        """Delete a document."""
        return delete_doc(db_conn, doc_id)

    @mcp.tool()
    def markland_set_visibility(doc_id: str, public: bool) -> dict:
        """Promote a doc to public (appears in /explore) or demote to unlisted."""
        return set_visibility_doc(db_conn, base_url, doc_id, is_public=public)

    @mcp.tool()
    def markland_feature(doc_id: str, featured: bool = True) -> dict:
        """Pin or unpin a doc to the landing page hero."""
        return feature_doc(db_conn, doc_id, is_featured=featured)

    return mcp


if __name__ == "__main__":
    config = get_config()
    db_conn = init_db(config.db_path)
    logger.info("Starting Markland MCP server (stdio, db: %s)", config.db_path)
    mcp_instance = build_mcp(db_conn, config.base_url)
    mcp_instance.run()
```

- [x] **Step 4: Mount MCP on FastAPI**

Modify `src/markland/web/app.py` — change the `create_app` signature and body to optionally mount MCP under `/mcp` with auth. Replace the `create_app` function (keep `_load_mcp_snippet`, `_doc_to_card`, `_TEMPLATE_DIR`, `_SCRIPTS_DIR` unchanged):

```python
def create_app(
    db_conn: sqlite3.Connection,
    *,
    mount_mcp: bool = False,
    admin_token: str = "",
    base_url: str = "",
) -> FastAPI:
    app = FastAPI(title="Markland", docs_url=None, redoc_url=None)
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    landing_tpl = env.get_template("landing.html")
    explore_tpl = env.get_template("explore.html")
    document_tpl = env.get_template("document.html")

    mcp_snippet = _load_mcp_snippet()
    mcp_snippet_json = json.dumps(mcp_snippet)

    @app.get("/health")
    def health():
        return JSONResponse({"status": "ok"})

    @app.get("/", response_class=HTMLResponse)
    def landing():
        docs = list_featured_and_recent_public(db_conn, limit=8)
        cards = [_doc_to_card(d) for d in docs]
        return HTMLResponse(
            landing_tpl.render(docs=cards, mcp_config_json=mcp_snippet_json)
        )

    @app.get("/explore", response_class=HTMLResponse)
    def explore(q: str | None = None):
        query = (q or "").strip() or None
        docs = list_public_documents(db_conn, query=query, limit=50)
        total_docs = list_public_documents(db_conn, query=query, limit=10_000)
        cards = [_doc_to_card(d) for d in docs]
        return HTMLResponse(
            explore_tpl.render(docs=cards, query=query, total=len(total_docs))
        )

    @app.get("/d/{share_token}", response_class=HTMLResponse)
    def view_document(share_token: str):
        doc = get_document_by_token(db_conn, share_token)
        if doc is None:
            return HTMLResponse(
                "<html><body style='font-family:system-ui;padding:2rem;'>"
                "<h1>Document not found</h1>"
                "</body></html>",
                status_code=404,
            )
        content_html = render_markdown(doc.content)
        html = document_tpl.render(
            title=doc.title,
            content_html=content_html,
            created_at=doc.created_at,
        )
        return HTMLResponse(html)

    if mount_mcp:
        from markland.server import build_mcp
        from markland.web.auth_middleware import AdminBearerMiddleware

        mcp_instance = build_mcp(db_conn, base_url)
        mcp_app = mcp_instance.streamable_http_app()

        # Middleware gates /mcp before the sub-app sees the request.
        app.add_middleware(
            AdminBearerMiddleware,
            admin_token=admin_token,
            protected_prefix="/mcp",
        )
        app.mount("/mcp", mcp_app)

    return app
```

- [x] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_http_mcp.py -v`
Expected: PASS (3 tests).

- [x] **Step 6: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: all tests pass. Any existing test using `create_app(db_conn)` still works because the new kwargs are optional.

---

## Task 4: Unified HTTP entrypoint `run_app.py`

**Files:**
- Create: `src/markland/run_app.py`

- [x] **Step 1: Write the file**

Create `src/markland/run_app.py`:

```python
"""Unified HTTP entrypoint: web viewer + MCP on /mcp, Sentry init."""

import logging

import uvicorn

from markland.config import get_config
from markland.db import init_db
from markland.web.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("markland.app")

config = get_config()

# Sentry must init before the app is created so uvicorn/fastapi middleware wraps requests.
if config.sentry_dsn:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=config.sentry_dsn,
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
        logger.info("Sentry initialized")
    except ImportError:
        logger.warning("SENTRY_DSN set but sentry-sdk not installed; skipping")

db_conn = init_db(config.db_path)
app = create_app(
    db_conn,
    mount_mcp=True,
    admin_token=config.admin_token,
    base_url=config.base_url,
)


if __name__ == "__main__":
    host = "0.0.0.0" if config.admin_token else "127.0.0.1"
    logger.info(
        "Starting Markland hosted app on %s:%d (db: %s, mcp_enabled=%s)",
        host,
        config.web_port,
        config.db_path,
        bool(config.admin_token),
    )
    uvicorn.run(app, host=host, port=config.web_port, log_level="info")
```

- [x] **Step 2: Verification — run locally and curl**

Run (in one terminal):
```bash
MARKLAND_ADMIN_TOKEN=local_test uv run python src/markland/run_app.py
```
Expected: log line "Starting Markland hosted app on 0.0.0.0:8950 ... mcp_enabled=True".

In another terminal:
```bash
curl -s http://127.0.0.1:8950/health
curl -sSo /dev/null -w "%{http_code}\n" http://127.0.0.1:8950/mcp/
curl -sSo /dev/null -w "%{http_code}\n" -H "Authorization: Bearer local_test" http://127.0.0.1:8950/mcp/
```
Expected: `{"status":"ok"}`, then `401`, then `200` (or a streaming response opening).

Stop the server (Ctrl-C).

---

## Task 5: Sentry init is conditional and safe

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/test_sentry_init.py`

- [x] **Step 1: Add sentry-sdk to dependencies**

Modify `pyproject.toml`'s `dependencies` list — insert after the `jinja2` line:

```toml
    "jinja2>=3.1.0",
    "sentry-sdk>=2.15.0",
    "resend>=2.5.0",
```

- [x] **Step 2: Install**

Run: `uv sync --all-extras`
Expected: resolves and installs without error.

- [x] **Step 3: Write the failing test**

Create `tests/test_sentry_init.py`:

```python
"""Sentry init is conditional on SENTRY_DSN being set."""

from unittest.mock import patch

import pytest


def test_sentry_not_initialized_when_dsn_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_ADMIN_TOKEN", "t")

    from markland.config import reset_config
    reset_config()

    # Importing run_app has side effects; patch sentry_sdk.init first.
    with patch("sentry_sdk.init") as init_mock:
        # Reimport run_app to trigger the module-level init branch.
        import importlib
        import markland.run_app
        importlib.reload(markland.run_app)

    init_mock.assert_not_called()


def test_sentry_initialized_when_dsn_set(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTRY_DSN", "https://fake@sentry.io/1")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_ADMIN_TOKEN", "t")

    from markland.config import reset_config
    reset_config()

    with patch("sentry_sdk.init") as init_mock:
        import importlib
        import markland.run_app
        importlib.reload(markland.run_app)

    init_mock.assert_called_once()
    kwargs = init_mock.call_args.kwargs
    assert kwargs["dsn"] == "https://fake@sentry.io/1"
    assert kwargs.get("send_default_pii") is False
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_sentry_init.py -v`
Expected: PASS (2 tests). `run_app.py` already has the conditional init from Task 4.

---

## Task 6: Resend client service module

**Files:**
- Create: `src/markland/service/__init__.py`
- Create: `src/markland/service/email.py`
- Create: `tests/test_email_service.py`

Rationale: stand up the service module + Resend wrapper now so later plans (email notifications, magic links) have a boring place to plug into.

- [x] **Step 1: Write the failing tests**

Create `tests/test_email_service.py`:

```python
"""Tests for the Resend email wrapper."""

from unittest.mock import MagicMock, patch

import pytest

from markland.service.email import EmailClient, EmailSendError


def test_sends_via_resend_when_api_key_set():
    client = EmailClient(api_key="re_test", from_email="notifications@markland.dev")
    with patch("resend.Emails.send") as send_mock:
        send_mock.return_value = {"id": "email_abc"}
        msg_id = client.send(to="alice@example.com", subject="Hi", html="<p>hi</p>")
    assert msg_id == "email_abc"
    args, kwargs = send_mock.call_args
    sent = args[0] if args else kwargs
    assert sent["to"] == "alice@example.com"
    assert sent["from"] == "notifications@markland.dev"
    assert sent["subject"] == "Hi"
    assert sent["html"] == "<p>hi</p>"


def test_noop_when_api_key_empty(caplog):
    client = EmailClient(api_key="", from_email="n@m.dev")
    with patch("resend.Emails.send") as send_mock:
        msg_id = client.send(to="a@b", subject="x", html="<p>x</p>")
    send_mock.assert_not_called()
    assert msg_id is None


def test_raises_on_resend_failure():
    client = EmailClient(api_key="re_test", from_email="n@m.dev")
    with patch("resend.Emails.send", side_effect=RuntimeError("resend down")):
        with pytest.raises(EmailSendError):
            client.send(to="a@b", subject="x", html="<p>x</p>")
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_email_service.py -v`
Expected: FAIL — `markland.service.email` does not exist.

- [x] **Step 3: Create the service package**

Create `src/markland/service/__init__.py`:

```python
"""Service layer — domain operations shared by HTTP API and MCP tools."""
```

- [x] **Step 4: Implement `EmailClient`**

Create `src/markland/service/email.py`:

```python
"""Thin wrapper around Resend. No-ops safely when no API key is configured."""

from __future__ import annotations

import logging

import resend

logger = logging.getLogger("markland.email")


class EmailSendError(RuntimeError):
    """Raised when Resend returns an error."""


class EmailClient:
    """Stateless-ish wrapper — holds api_key and from_email, calls resend.Emails.send."""

    def __init__(self, *, api_key: str, from_email: str) -> None:
        self._api_key = api_key
        self._from = from_email
        if api_key:
            resend.api_key = api_key

    def send(self, *, to: str, subject: str, html: str) -> str | None:
        """Send an email. Returns Resend's message id, or None if disabled."""
        if not self._api_key:
            logger.info("Email disabled (no RESEND_API_KEY); would have sent to %s: %s", to, subject)
            return None
        try:
            resp = resend.Emails.send({
                "from": self._from,
                "to": to,
                "subject": subject,
                "html": html,
            })
            return resp.get("id") if isinstance(resp, dict) else None
        except Exception as exc:  # resend raises a variety of exception types
            raise EmailSendError(str(exc)) from exc
```

- [x] **Step 5: Run tests**

Run: `uv run pytest tests/test_email_service.py -v`
Expected: PASS (3 tests).

- [x] **Step 6: Run the full suite to confirm nothing regressed**

Run: `uv run pytest tests/ -v`
Expected: all tests pass.

---

## Task 7: Dockerfile

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [x] **Step 1: Write `.dockerignore`**

Create `.dockerignore`:

```
.venv
.pytest_cache
__pycache__
*.pyc
.env
.env.local
tests/
scripts/smoke_test.py
docs/
.git
.superpowers
.claude
README.md
```

- [x] **Step 2: Write `Dockerfile`**

Create `Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    MARKLAND_DATA_DIR=/data \
    MARKLAND_WEB_PORT=8080

# Install system deps (litestream) + uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Install litestream (pinned version)
ARG LITESTREAM_VERSION=0.3.13
RUN curl -fsSL "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-amd64.tar.gz" \
    | tar -xz -C /usr/local/bin litestream \
    && chmod +x /usr/local/bin/litestream

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.5.6 /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./
COPY src ./src

RUN uv sync --frozen --no-dev

COPY scripts/start.sh /app/start.sh
COPY litestream.yml /etc/litestream.yml
RUN chmod +x /app/start.sh

# Persist SQLite on a volume
VOLUME ["/data"]

EXPOSE 8080

ENTRYPOINT ["/app/start.sh"]
```

- [x] **Step 3: Verification — build locally**

Run:
```bash
docker build -t markland:dev .
```
Expected: image builds successfully. (If Docker is not installed locally, defer this verification; the CI workflow in Task 10 exercises it.)

---

## Task 8: Startup script with Litestream

**Files:**
- Create: `scripts/start.sh`
- Create: `litestream.yml`

- [x] **Step 1: Write `litestream.yml`**

Create `litestream.yml`:

```yaml
# Continuously replicates /data/markland.db to Cloudflare R2.
# Credentials come from env: LITESTREAM_ACCESS_KEY_ID, LITESTREAM_SECRET_ACCESS_KEY.
# Endpoint + bucket come from: LITESTREAM_REPLICA_URL (e.g. s3://markland-db.<acct>.r2.cloudflarestorage.com/markland).

dbs:
  - path: /data/markland.db
    replicas:
      - type: s3
        url: ${LITESTREAM_REPLICA_URL}
        access-key-id: ${LITESTREAM_ACCESS_KEY_ID}
        secret-access-key: ${LITESTREAM_SECRET_ACCESS_KEY}
        sync-interval: 10s
        retention: 72h
        snapshot-interval: 6h
```

- [x] **Step 2: Write `scripts/start.sh`**

Create `scripts/start.sh`:

```bash
#!/usr/bin/env sh
set -e

DB_PATH="${MARKLAND_DATA_DIR:-/data}/markland.db"

# Only attempt restore if we have replica credentials AND the DB doesn't already exist.
if [ -n "${LITESTREAM_REPLICA_URL}" ] && [ ! -f "${DB_PATH}" ]; then
  echo "[start] No local DB at ${DB_PATH}; attempting litestream restore…"
  litestream restore -if-replica-exists -o "${DB_PATH}" "${LITESTREAM_REPLICA_URL}" || {
    echo "[start] Restore failed or no replica exists; continuing with fresh DB"
  }
fi

if [ -n "${LITESTREAM_REPLICA_URL}" ]; then
  echo "[start] Starting litestream replicate + uvicorn…"
  exec litestream replicate -config /etc/litestream.yml -exec \
    "uv run python src/markland/run_app.py"
else
  echo "[start] LITESTREAM_REPLICA_URL not set; starting uvicorn directly (no backups)"
  exec uv run python src/markland/run_app.py
fi
```

- [x] **Step 3: Make it executable locally for sanity**

Run: `chmod +x /Users/daveyhiles/Developer/markland/scripts/start.sh`
Expected: no output; file is executable.

- [x] **Step 4: Verification — dry-run review**

Read the script back and sanity-check:
- DB path matches `MARKLAND_DATA_DIR` default (`/data`)
- Restore is skipped gracefully when no replica exists
- `litestream replicate -exec` wraps uvicorn so uvicorn's exit triggers clean shutdown of Litestream

No test command — this is exercised end-to-end in Task 11.

---

## Task 9: `fly.toml`

**Files:**
- Create: `fly.toml`

- [x] **Step 1: Write `fly.toml`**

Create `fly.toml`:

```toml
app = "markland"
primary_region = "iad"

[build]

[env]
  MARKLAND_BASE_URL = "https://markland.dev"
  MARKLAND_DATA_DIR = "/data"
  MARKLAND_WEB_PORT = "8080"
  RESEND_FROM_EMAIL = "notifications@markland.dev"

[[mounts]]
  source = "markland_data"
  destination = "/data"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = "off"
  auto_start_machines = true
  min_machines_running = 1
  processes = ["app"]

  [[http_service.checks]]
    grace_period = "10s"
    interval = "30s"
    method = "GET"
    timeout = "5s"
    path = "/health"

[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 1024
```

- [x] **Step 2: Verification — config validation**

Run (requires `flyctl` installed; see runbook if not):
```bash
flyctl config validate
```
Expected: "Configuration is valid." If flyctl isn't installed locally, skip; CI in Task 10 does this.

---

## Task 10: GitHub Actions deploy workflow

**Files:**
- Create: `.github/workflows/deploy.yml`
- Create: `.github/workflows/test.yml`

- [x] **Step 1: Write the test workflow**

Create `.github/workflows/test.yml`:

```yaml
name: Test

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          version: "0.5.6"
      - name: Set up Python
        run: uv python install 3.12
      - name: Install deps
        run: uv sync --all-extras
      - name: Run tests
        run: uv run pytest tests/ -v
```

- [x] **Step 2: Write the deploy workflow**

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy to Fly

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  deploy:
    runs-on: ubuntu-latest
    concurrency: deploy-main
    needs: [] # Intentionally independent; tests run in parallel.
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@v1
      - name: Deploy
        run: flyctl deploy --remote-only
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

- [x] **Step 3: Verification — YAML lint**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml')); yaml.safe_load(open('.github/workflows/test.yml'))" \
  && echo "OK"
```
Expected: `OK`. (PyYAML is a transitive dep; if missing, `pip install pyyaml` locally or skip — GitHub will validate on push.)

---

## Task 11: Operator runbook — first deploy

**Files:**
- Create: `docs/runbooks/first-deploy.md`
- Modify: `README.md`

This task is documentation, not code. It enumerates the manual one-time operator steps: buying a domain, standing up R2, running `fly launch`, setting secrets, pointing DNS.

- [ ] **Step 1: Write the runbook**

Create `docs/runbooks/first-deploy.md`:

```markdown
# First Deploy — Operator Runbook

One-time manual steps to stand up `markland.dev` on Fly.io. Everything after this is automated by the `deploy.yml` GitHub Actions workflow.

## Prerequisites
- A Cloudflare account (for DNS + R2)
- A Fly.io account with a payment method
- `flyctl` installed locally: `brew install flyctl` (macOS) or see https://fly.io/docs/flyctl/install/
- The `markland.dev` domain registered (or your chosen domain — substitute throughout)

## 1. Cloudflare R2 bucket for SQLite backups

1. Log into Cloudflare → R2 → Create bucket.
2. Name: `markland-db`. Location: Automatic.
3. Manage R2 API Tokens → Create API Token → Permissions: "Object Read & Write", scope: just this bucket.
4. Copy the **Access Key ID**, **Secret Access Key**, and the **S3-compatible endpoint URL** (looks like `https://<accountid>.r2.cloudflarestorage.com`).

You'll use `LITESTREAM_REPLICA_URL = s3://markland-db.<accountid>.r2.cloudflarestorage.com/markland` in step 3.

## 2. Resend

1. Sign up at https://resend.com.
2. Add domain `markland.dev`, add the DNS records Resend shows to Cloudflare (MX, TXT, DKIM).
3. Create an API key scoped to sending-only. Copy it.

## 3. Fly app + volume + secrets

From the project root:

```bash
# First-time app create (answers Y to "copy fly.toml" and "deploy now: N")
flyctl launch --copy-config --no-deploy --name markland --region iad

# Create the persistent volume (3 GB in iad, one per machine)
flyctl volumes create markland_data --region iad --size 3

# Generate an admin token
ADMIN_TOKEN="mk_admin_$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
echo "Admin token (save it): $ADMIN_TOKEN"

# Set secrets (fly encrypts at rest, injects as env vars)
flyctl secrets set \
  MARKLAND_ADMIN_TOKEN="$ADMIN_TOKEN" \
  SENTRY_DSN="<your sentry dsn or empty>" \
  RESEND_API_KEY="<your resend key>" \
  LITESTREAM_REPLICA_URL="s3://markland-db.<accountid>.r2.cloudflarestorage.com/markland" \
  LITESTREAM_ACCESS_KEY_ID="<r2 access key>" \
  LITESTREAM_SECRET_ACCESS_KEY="<r2 secret key>"

# Deploy
flyctl deploy
```

After deploy, sanity-check:
```bash
curl -s https://markland.fly.dev/health
curl -sSo /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $ADMIN_TOKEN" https://markland.fly.dev/mcp/
```
Expected: `{"status":"ok"}`, then `200` for authed MCP, `401` without.

## 4. Custom domain

```bash
flyctl certs add markland.dev
flyctl certs show markland.dev    # shows the DNS records to add
```

In Cloudflare DNS for `markland.dev`:
- Add an A record pointing to the IPv4 shown by `flyctl ips list`
- Add an AAAA record pointing to the IPv6
- Proxy status: **DNS only** (grey cloud). Fly manages TLS; proxying through Cloudflare causes double-TLS issues.

Wait until `flyctl certs show markland.dev` shows "Issued". Then:
```bash
curl -s https://markland.dev/health
```
Expected: `{"status":"ok"}`.

## 5. CI deploy

Add `FLY_API_TOKEN` to the GitHub repository secrets (`flyctl auth token | pbcopy`, paste into https://github.com/<org>/markland/settings/secrets/actions).

From now on, `git push origin main` triggers `deploy.yml`.

## 6. Verify Litestream backups

After a few writes to the hosted app:
```bash
flyctl ssh console -C "litestream snapshots /data/markland.db"
```
Expected: at least one snapshot row, confirming replication to R2 is healthy.

Simulate disaster recovery:
```bash
# In R2 console: verify objects exist under `markland/` prefix.
# Restore locally:
litestream restore -o /tmp/restored.db \
  -config litestream.yml \
  /data/markland.db
sqlite3 /tmp/restored.db "SELECT count(*) FROM documents;"
```

## 7. Monitoring

- Fly dashboard: https://fly.io/apps/markland
- Sentry: issues filtered to this project
- Resend: email send logs

No further setup needed for ~100 users. Re-read `docs/specs/2026-04-19-multi-agent-auth-design.md` §11 "Operational signals to watch" before upgrading anything.
```

- [ ] **Step 2: Add a section to `README.md`**

Append to `README.md`:

```markdown

## Running Hosted (Fly.io)

Markland is deployable as a hosted service with SQLite + Litestream backups. Full one-time setup walkthrough: [`docs/runbooks/first-deploy.md`](docs/runbooks/first-deploy.md).

Day-to-day: `git push origin main` → GitHub Actions → `flyctl deploy`.
```

- [ ] **Step 3: Verification**

Read the runbook back end-to-end. Confirm the commands are copy-pasteable and do not reference undefined variables.

---

## Task 12: End-to-end smoke against a running hosted instance

**Files:**
- Create: `scripts/hosted_smoke.sh`

This is a manual post-deploy verification — not unit tests. It exercises the full stack as a real MCP client would.

- [ ] **Step 1: Write the smoke script**

Create `scripts/hosted_smoke.sh`:

```bash
#!/usr/bin/env sh
set -eu

# Usage: MARKLAND_URL=https://markland.dev MARKLAND_ADMIN_TOKEN=... ./scripts/hosted_smoke.sh

: "${MARKLAND_URL:?set MARKLAND_URL (e.g. https://markland.dev)}"
: "${MARKLAND_ADMIN_TOKEN:?set MARKLAND_ADMIN_TOKEN}"

echo "==> /health"
curl -fsS "$MARKLAND_URL/health" | tee /dev/stderr
echo

echo "==> /mcp without auth (expect 401)"
code=$(curl -s -o /dev/null -w "%{http_code}" "$MARKLAND_URL/mcp/")
test "$code" = "401" || { echo "expected 401, got $code"; exit 1; }
echo "ok"

echo "==> /mcp with auth (expect 200 or SSE open)"
code=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $MARKLAND_ADMIN_TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -X POST "$MARKLAND_URL/mcp/" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}')
test "$code" = "200" || { echo "expected 200, got $code"; exit 1; }
echo "ok"

echo "==> / (landing page, expect 200)"
code=$(curl -s -o /dev/null -w "%{http_code}" "$MARKLAND_URL/")
test "$code" = "200" || { echo "expected 200, got $code"; exit 1; }
echo "ok"

echo "All hosted smoke checks passed."
```

- [ ] **Step 2: Make executable**

Run: `chmod +x /Users/daveyhiles/Developer/markland/scripts/hosted_smoke.sh`
Expected: no output.

- [ ] **Step 3: Verification**

Once the runbook (Task 11) has been completed and the app is deployed, run:

```bash
MARKLAND_URL=https://markland.dev \
MARKLAND_ADMIN_TOKEN=<the admin token you saved> \
./scripts/hosted_smoke.sh
```
Expected: all checks pass.

Defer this step until a real deploy exists; unit tests cover the logic locally.

---

## Completion criteria

- `uv run pytest tests/ -v` passes with the new test files (test_config.py, test_auth_middleware.py, test_http_mcp.py, test_sentry_init.py, test_email_service.py).
- `MARKLAND_ADMIN_TOKEN=t uv run python src/markland/run_app.py` starts the unified app locally; `/health`, `/`, `/explore` respond 200; `/mcp/` responds 401 without auth and 200 with.
- `Dockerfile`, `fly.toml`, `scripts/start.sh`, `litestream.yml`, `.github/workflows/{test,deploy}.yml`, and `docs/runbooks/first-deploy.md` exist and are internally consistent.
- A fresh `flyctl deploy` from the runbook produces a reachable `https://markland.dev/health` and a 401-gated `/mcp/`.
- `scripts/hosted_smoke.sh` passes against the deployed instance.

## What this plan does NOT deliver

Per the spec §17, users/tokens, grants, agents, invites, device flow, email triggers, conflict handling, presence, and launch polish all arrive in later plans. This plan is purely "existing functionality, now hosted, gated by a single admin token, with backups and error tracking wired up."
