"""ProxyHeadersMiddleware integration: redirects must preserve HTTPS.

Background: Fly's proxy terminates TLS and forwards to the app over HTTP.
Without proxy_headers=True on uvicorn, Starlette builds redirect URLs from
the inner scheme, downgrading https -> http and exposing bearer tokens to
any client that follows the redirect. These tests pin the fix.

Two complementary assertions:

1. Behavior: with uvicorn's ProxyHeadersMiddleware wrapping the app, a POST
   /mcp that lands on Starlette's Mount-trailing-slash redirect produces
   an https:// Location header. Without the wrap, it produces http://.

2. Wiring: src/markland/run_app.py's uvicorn.run(...) call passes
   proxy_headers=True and forwarded_allow_ips="*" so production actually
   installs the middleware.

The behavior test is the why; the wiring test is the what.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from markland.config import reset_config
from markland.db import init_db
from markland.service.auth import create_user_token
from markland.service.users import create_user
from markland.web.app import create_app


@pytest.fixture
def app_with_token(tmp_path, monkeypatch):
    """Real app + a real bearer token so we get past auth and hit the
    Mount-level trailing-slash redirect that exhibits the bug."""
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    conn = init_db(tmp_path / "test.db")
    user = create_user(conn, email="proxytest@example.com", display_name="Proxy Test")
    _, plaintext = create_user_token(conn, user_id=user.id, label="proxy-test")
    app = create_app(
        conn,
        mount_mcp=True,
        base_url="http://testserver",
        session_secret="test-secret",
    )
    return app, plaintext


def test_mcp_redirect_downgrades_without_proxy_headers(app_with_token):
    """Sanity check: confirm the bug exists without the middleware.

    If this stops failing-as-described, ProxyHeadersMiddleware behavior or
    Starlette's redirect logic has changed and the fix may no longer be
    needed -- or the test no longer pins what it claims to.
    """
    app, token = app_with_token
    client = TestClient(app)
    resp = client.post(
        "/mcp",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "markland.fly.dev",
            "Authorization": f"Bearer {token}",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (301, 302, 307, 308), (
        f"Expected a redirect from /mcp to /mcp/, got {resp.status_code}"
    )
    location = resp.headers.get("location", "")
    assert location.startswith("http://"), (
        f"Without ProxyHeadersMiddleware, redirect should keep inner http "
        f"scheme; got: {location!r}"
    )


def test_mcp_redirect_preserves_https_with_proxy_headers(app_with_token):
    """With uvicorn's ProxyHeadersMiddleware, POST /mcp's redirect uses https."""
    app, token = app_with_token
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts="*")
    client = TestClient(wrapped)
    resp = client.post(
        "/mcp",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "markland.fly.dev",
            "Authorization": f"Bearer {token}",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (301, 302, 307, 308), (
        f"Expected a redirect from /mcp to /mcp/, got {resp.status_code}"
    )
    location = resp.headers.get("location", "")
    assert location.startswith("https://"), (
        f"Redirect Location must use https, got: {location!r}"
    )


def test_run_app_passes_proxy_headers_to_uvicorn():
    """Pin the fix: run_app.py must pass proxy_headers=True and
    forwarded_allow_ips='*' to uvicorn.run, otherwise production will
    silently regress to http redirects.
    """
    run_app_path = Path(__file__).resolve().parent.parent / "src" / "markland" / "run_app.py"
    source = run_app_path.read_text()
    tree = ast.parse(source)

    uvicorn_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # match uvicorn.run(...)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "run"
                and isinstance(func.value, ast.Name)
                and func.value.id == "uvicorn"
            ):
                uvicorn_calls.append(node)

    assert uvicorn_calls, "Expected at least one uvicorn.run(...) call in run_app.py"

    for call in uvicorn_calls:
        kwargs = {kw.arg: kw.value for kw in call.keywords}
        assert "proxy_headers" in kwargs, (
            "uvicorn.run must pass proxy_headers=True so Fly's "
            "X-Forwarded-Proto is honored on redirects"
        )
        proxy_headers_value = kwargs["proxy_headers"]
        assert isinstance(proxy_headers_value, ast.Constant) and proxy_headers_value.value is True, (
            f"proxy_headers must be the literal True, got {ast.dump(proxy_headers_value)}"
        )
        assert "forwarded_allow_ips" in kwargs, (
            "uvicorn.run must pass forwarded_allow_ips='*'; without it, "
            "uvicorn only trusts forwarded headers from 127.0.0.1 and "
            "Fly's edge IP won't be trusted"
        )
        allow_ips_value = kwargs["forwarded_allow_ips"]
        assert isinstance(allow_ips_value, ast.Constant) and allow_ips_value.value == "*", (
            f"forwarded_allow_ips must be the literal '*' (Fly is the only "
            f"proxy in front of the app), got {ast.dump(allow_ips_value)}"
        )
