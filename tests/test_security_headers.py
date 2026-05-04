"""Security headers applied to every response; X-Robots-Tag on non-marketing paths."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db, insert_document
from markland.web.app import create_app


def _assert_security_headers(h):
    """Assert all six security headers are present AND load-bearing."""
    assert h.get("strict-transport-security", "").startswith("max-age=")
    csp = h.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "form-action 'self'" in csp
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("x-frame-options") == "DENY"
    assert h.get("referrer-policy") == "strict-origin-when-cross-origin"
    perm = h.get("permissions-policy", "")
    assert "camera=()" in perm
    assert "geolocation=()" in perm


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "s.db")
    insert_document(conn, "doc1", "Test", "# Hi", "tok1")
    app = create_app(conn, mount_mcp=False, base_url="http://testserver")
    return TestClient(app)


@pytest.mark.parametrize("path", ["/", "/quickstart", "/explore", "/robots.txt", "/sitemap.xml"])
def test_security_headers_present(client, path):
    r = client.get(path)
    _assert_security_headers(r.headers)


def test_marketing_paths_allow_indexing(client):
    for path in ["/", "/quickstart", "/explore", "/alternatives", "/d/tok1"]:
        r = client.get(path)
        xrt = r.headers.get("x-robots-tag", "")
        assert "noindex" not in xrt, f"{path} should be indexable"


@pytest.mark.parametrize(
    "path,expected_status",
    [
        ("/health", 200),
        ("/settings", 404),
        ("/dashboard", 401),
        ("/inbox", 404),
    ],
)
def test_noindex_on_private_paths(client, path, expected_status):
    r = client.get(path, follow_redirects=False)
    assert r.status_code == expected_status
    assert "noindex" in r.headers.get("x-robots-tag", "").lower()


def test_csp_uses_nonce_not_unsafe_inline_for_scripts(client):
    """P2-B / markland-yxv: script-src must NOT carry 'unsafe-inline'.
    Each request gets a fresh nonce woven into the CSP header."""
    r = client.get("/")
    csp = r.headers.get("content-security-policy", "")
    # Locate the script-src directive.
    parts = [p.strip() for p in csp.split(";")]
    script_src = next(p for p in parts if p.startswith("script-src"))
    assert "'unsafe-inline'" not in script_src, (
        f"script-src must drop 'unsafe-inline'; got: {script_src!r}"
    )
    assert "'nonce-" in script_src, (
        f"script-src must include a per-request nonce; got: {script_src!r}"
    )


def test_csp_nonce_changes_between_requests(client):
    """Each request gets a fresh nonce — replay protection for any
    attacker who exfiltrates a nonce + injects later."""
    r1 = client.get("/")
    r2 = client.get("/")
    csp1 = r1.headers.get("content-security-policy", "")
    csp2 = r2.headers.get("content-security-policy", "")
    # Extract the nonce values.
    import re
    nonce1 = re.search(r"'nonce-([^']+)'", csp1)
    nonce2 = re.search(r"'nonce-([^']+)'", csp2)
    assert nonce1 and nonce2
    assert nonce1.group(1) != nonce2.group(1), (
        "csp nonces must rotate per request"
    )


def test_inline_scripts_carry_nonce(client):
    """A page rendered via render_with_nav (e.g. landing) must stamp the
    nonce on every inline <script>."""
    r = client.get("/")
    body = r.text
    # Extract the response's CSP nonce.
    import re
    csp = r.headers.get("content-security-policy", "")
    m = re.search(r"'nonce-([^']+)'", csp)
    assert m, "no nonce in CSP — middleware regression"
    nonce = m.group(1)
    # Every inline <script> in the rendered body must carry a nonce
    # that matches the response's CSP nonce. We don't enforce that
    # external (src=…) scripts carry a nonce — they get cleared by
    # script-src 'self' instead.
    inline_pattern = re.compile(
        r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE
    )
    for tag in inline_pattern.findall(body):
        assert f'nonce="{nonce}"' in tag, (
            f"inline <script> missing or wrong nonce: {tag!r}"
        )


def test_security_headers_on_rate_limit_429(tmp_path, monkeypatch):
    """Rate-limit 429 responses must carry security headers too."""
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1")
    conn = init_db(tmp_path / "s.db")
    app = create_app(conn, mount_mcp=False, base_url="http://testserver")
    c = TestClient(app)

    # First request consumes the one-per-minute allowance.
    c.get("/")
    # Second request in the same minute should 429.
    r = c.get("/")
    assert r.status_code == 429
    _assert_security_headers(r.headers)
