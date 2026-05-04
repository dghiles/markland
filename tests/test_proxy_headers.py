"""ProxyHeadersMiddleware wiring: pin uvicorn invocation flags.

Background: Fly's proxy terminates TLS and forwards over HTTP. Without
proxy_headers=True on uvicorn, Starlette would build URLs from the inner
scheme, downgrading https -> http. Historically this mattered most for the
/mcp mount-trailing-slash redirect; that redirect was eliminated in
markland-dfj, but proxy_headers=True remains correct defensively for any
future redirects (e.g. trailing-slash on other routes, manually-issued
RedirectResponse).

This file now only verifies the wiring (uvicorn.run kwargs); behavioral
redirect tests previously here were removed when the /mcp redirect itself
was eliminated.
"""

from __future__ import annotations

import ast
from pathlib import Path


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
