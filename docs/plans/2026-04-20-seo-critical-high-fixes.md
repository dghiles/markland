# SEO Critical + High Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the non-domain Critical + High SEO fixes identified in the 2026-04-20 audit: meta/OG/JSON-LD everywhere, robots.txt, sitemap.xml, security headers, crawl-hygiene `X-Robots-Tag`, retitled homepage with a GEO opener, expanded quickstart, trust-floor stub pages, and self-hosted fonts.

**Architecture:** All SEO metadata is centralized in a Jinja `_seo_meta.html` partial rendered from `base.html`, taking per-page blocks (`seo_title`, `seo_description`, `seo_og_type`). Crawlability (`/robots.txt`, `/sitemap.xml`) is served by dynamic FastAPI routes so the sitemap stays in sync with `competitors.COMPETITORS`. A new `SecurityHeadersMiddleware` (BaseHTTPMiddleware, mirroring the pattern in `rate_limit_middleware.py`) adds HSTS/CSP/XFO/XCTO/Referrer-Policy/Permissions-Policy on every response and a per-path `X-Robots-Tag: noindex, nofollow` for non-marketing prefixes. Fonts are self-hosted as subsetted woff2 files under `src/markland/web/static/fonts/`, preloaded and metric-matched via `size-adjust`. Canonical URL is computed from `request.url` so nothing locks us to a specific hostname — when the canonical domain is bought later, no code change is required.

**Tech Stack:** FastAPI, Starlette middleware, Jinja2, pytest + `fastapi.testclient.TestClient`, SQLite. No new Python dependencies.

**Out of scope for this plan (deferred — requires domain purchase):**
- Hard-coding `markland.dev` in canonical/OG URLs
- 301 redirects from `*.fly.dev` to the canonical domain
- Flipping the HSTS `preload` directive on (wait until DNS is stable)

---

## File Structure

**Templates (`src/markland/web/templates/`)**
- `_seo_meta.html` (new) — partial rendering `<meta description>`, canonical, OG, Twitter, and three JSON-LD blocks. Reads `seo_title`, `seo_description`, `seo_og_type`, `seo_canonical` from the render context.
- `base.html` (modify) — include the partial in `<head>`, add font preload, add `{% block body_class %}`-aware footer with trust links.
- `landing.html` (modify) — retitle, new GEO definitional paragraph under the H1, set `seo_description` via `{% set %}`.
- `quickstart.html` (rewrite) — extend `base.html` (currently a standalone HTML doc), use `{{ request.host_url }}` for the setup URL, expand to 600+ words with H2 step headings.
- `alternatives.html`, `alternative.html`, `explore.html` (modify) — set `seo_description` per-page.
- `about.html`, `security.html`, `privacy.html`, `terms.html` (new — minimal stubs) — extend `base.html`, short trust-floor copy the user can rewrite later.

**Python (`src/markland/web/`)**
- `app.py` (modify) — register two new routes (`/robots.txt`, `/sitemap.xml`, and the four stub pages), add a context processor that passes `request` into every template render so the partial can compute canonical + host, wire the new middleware.
- `security_headers_middleware.py` (new) — Starlette BaseHTTPMiddleware that injects the response headers and applies `X-Robots-Tag` for non-marketing paths.
- `seo.py` (new) — pure-Python helpers: `noindex_path_prefixes()`, `build_sitemap_xml(base_url, urls)`, `ROBOTS_TXT` constant. No I/O, easy to unit test.
- `static/fonts/` (new dir) — self-hosted woff2 files (`figtree-700.woff2`, `figtree-800.woff2`, `dmmono-400.woff2`).
- `static/css/fonts.css` (new) — `@font-face` declarations with `size-adjust` fallback overrides.

**Tests (`tests/`)**
- `test_seo_meta.py` (new)
- `test_robots_sitemap.py` (new)
- `test_security_headers.py` (new)
- `test_quickstart_page.py` (modify — assert new content + H2 count)
- `test_web.py` (modify — assert JSON-LD, meta description, canonical present on `/`)

Each task below is one commit. TDD throughout: test first, verify red, implement, verify green, commit.

---

## Task 1: SEO helpers module

Pure functions, no FastAPI/Jinja dependency. Unit-testable in isolation.

**Files:**
- Create: `src/markland/web/seo.py`
- Test: `tests/test_seo_helpers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_seo_helpers.py`:

```python
"""Unit tests for pure SEO helpers in markland.web.seo."""

from markland.web.seo import (
    NOINDEX_PATH_PREFIXES,
    ROBOTS_TXT,
    build_sitemap_xml,
    should_noindex,
)


def test_should_noindex_blocks_api_and_auth_paths():
    assert should_noindex("/api/tokens")
    assert should_noindex("/mcp/")
    assert should_noindex("/mcp/anything")
    assert should_noindex("/resume")
    assert should_noindex("/login")
    assert should_noindex("/verify")
    assert should_noindex("/setup")
    assert should_noindex("/device")
    assert should_noindex("/device/done")
    assert should_noindex("/settings")
    assert should_noindex("/settings/tokens")
    assert should_noindex("/dashboard")
    assert should_noindex("/inbox")
    assert should_noindex("/invite/abc")
    assert should_noindex("/admin/audit")
    assert should_noindex("/health")


def test_should_noindex_allows_marketing_paths():
    assert not should_noindex("/")
    assert not should_noindex("/quickstart")
    assert not should_noindex("/explore")
    assert not should_noindex("/alternatives")
    assert not should_noindex("/alternatives/notion")
    assert not should_noindex("/d/abc123token")
    assert not should_noindex("/about")
    assert not should_noindex("/security")


def test_robots_txt_references_sitemap_and_core_disallows():
    assert "Sitemap:" in ROBOTS_TXT
    assert "Disallow: /api/" in ROBOTS_TXT
    assert "Disallow: /mcp/" in ROBOTS_TXT
    assert "Disallow: /settings" in ROBOTS_TXT
    # Must allow the marketing prefixes (no explicit disallow on root)
    assert "User-agent: *" in ROBOTS_TXT


def test_build_sitemap_xml_contains_all_urls():
    xml = build_sitemap_xml(
        base_url="https://example.test",
        urls=["/", "/quickstart", "/alternatives/notion"],
        lastmod="2026-04-20",
    )
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<urlset" in xml
    assert "<loc>https://example.test/</loc>" in xml
    assert "<loc>https://example.test/quickstart</loc>" in xml
    assert "<loc>https://example.test/alternatives/notion</loc>" in xml
    assert xml.count("<lastmod>2026-04-20</lastmod>") == 3


def test_build_sitemap_xml_escapes_base_url_trailing_slash():
    xml = build_sitemap_xml(
        base_url="https://example.test/",  # trailing slash
        urls=["/quickstart"],
        lastmod="2026-04-20",
    )
    # No double-slash in the URL
    assert "https://example.test//quickstart" not in xml
    assert "<loc>https://example.test/quickstart</loc>" in xml
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_seo_helpers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'markland.web.seo'`

- [ ] **Step 3: Implement the module**

Create `src/markland/web/seo.py`:

```python
"""Pure-Python SEO helpers: crawl policy, robots.txt, sitemap generation.

Kept free of FastAPI/Jinja imports so it is trivial to unit-test and reusable
from routes, middleware, or CLI scripts.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

# Path prefixes that must never be indexed. Match both exact paths and
# children (e.g. "/settings" and "/settings/tokens").
NOINDEX_PATH_PREFIXES: tuple[str, ...] = (
    "/api/",
    "/api",
    "/mcp/",
    "/mcp",
    "/admin/",
    "/admin",
    "/settings/",
    "/settings",
    "/dashboard",
    "/inbox",
    "/resume",
    "/login",
    "/verify",
    "/setup",
    "/device",
    "/device/",
    "/invite/",
    "/health",
)


def should_noindex(path: str) -> bool:
    """Return True if this URL path should carry ``X-Robots-Tag: noindex``."""
    for prefix in NOINDEX_PATH_PREFIXES:
        if prefix.endswith("/"):
            if path.startswith(prefix):
                return True
        elif path == prefix or path.startswith(prefix + "/"):
            return True
    return False


ROBOTS_TXT = """\
User-agent: *
Allow: /
Disallow: /api/
Disallow: /mcp/
Disallow: /admin/
Disallow: /settings
Disallow: /dashboard
Disallow: /inbox
Disallow: /resume
Disallow: /login
Disallow: /verify
Disallow: /setup
Disallow: /device
Disallow: /invite/
Disallow: /health

# Block AI training crawlers; real search engines (Googlebot, Bingbot) fall
# through to the wildcard rule above.
User-agent: GPTBot
Disallow: /

User-agent: CCBot
Disallow: /

Sitemap: {sitemap_url}
"""


def render_robots_txt(sitemap_url: str) -> str:
    """Return robots.txt body with the sitemap URL filled in."""
    return ROBOTS_TXT.format(sitemap_url=sitemap_url)


def build_sitemap_xml(
    *,
    base_url: str,
    urls: list[str],
    lastmod: str,
) -> str:
    """Build a minimal, well-formed sitemap XML document.

    `base_url` is the scheme+host (e.g. ``https://example.test``). Trailing
    slash is tolerated. Each entry in ``urls`` is a root-relative path such
    as ``/quickstart`` — it must begin with ``/``.
    """
    base = base_url.rstrip("/")
    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path in urls:
        if not path.startswith("/"):
            raise ValueError(f"sitemap path must start with '/': {path!r}")
        loc = escape(f"{base}{path}")
        lines.append(
            f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>"
        )
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_seo_helpers.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/seo.py tests/test_seo_helpers.py
git commit -m "feat(seo): add pure helpers for robots.txt, sitemap, noindex policy"
```

---

## Task 2: `/robots.txt` route

**Files:**
- Modify: `src/markland/web/app.py` (add route near the `/health` block, line ~197)
- Test: `tests/test_robots_sitemap.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_robots_sitemap.py`:

```python
"""Routes for /robots.txt and /sitemap.xml."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app
from markland.web.competitors import COMPETITORS


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="http://testserver")
    return TestClient(app)


def test_robots_txt_returns_200_plain_text(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")


def test_robots_txt_content(client):
    r = client.get("/robots.txt")
    body = r.text
    assert "User-agent: *" in body
    assert "Disallow: /api/" in body
    assert "Disallow: /mcp/" in body
    assert "Sitemap:" in body
    assert "/sitemap.xml" in body
    # Sitemap URL must use the actual request host, not a hardcoded domain.
    assert "http://testserver/sitemap.xml" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_robots_sitemap.py::test_robots_txt_returns_200_plain_text -v`
Expected: FAIL with 404.

- [ ] **Step 3: Implement the route**

In `src/markland/web/app.py`, near the existing `/health` block (~line 195), add the import and route:

At the top of the file (with the other `fastapi.responses` imports on line 11), change to:

```python
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
```

At the top-level imports (near line 20), add:

```python
from markland.web.seo import build_sitemap_xml, render_robots_txt
```

Inside `create_app`, right after the `/health` route, add:

```python
    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots_txt(request: Request):
        sitemap_url = str(request.url_for("sitemap_xml"))
        return PlainTextResponse(render_robots_txt(sitemap_url))
```

Note: `url_for("sitemap_xml")` will fail until Task 3 adds that route. For this commit, temporarily inline the URL:

```python
    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots_txt(request: Request):
        sitemap_url = f"{request.url.scheme}://{request.url.netloc}/sitemap.xml"
        return PlainTextResponse(render_robots_txt(sitemap_url))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_robots_sitemap.py::test_robots_txt_returns_200_plain_text tests/test_robots_sitemap.py::test_robots_txt_content -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/app.py tests/test_robots_sitemap.py
git commit -m "feat(seo): serve /robots.txt with disallow rules for non-marketing paths"
```

---

## Task 3: `/sitemap.xml` route (dynamic from COMPETITORS)

**Files:**
- Modify: `src/markland/web/app.py`
- Test: `tests/test_robots_sitemap.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_robots_sitemap.py`:

```python
def test_sitemap_xml_returns_200_xml(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")


def test_sitemap_contains_core_marketing_urls(client):
    r = client.get("/sitemap.xml")
    body = r.text
    assert '<?xml version="1.0" encoding="UTF-8"?>' in body
    assert "<loc>http://testserver/</loc>" in body
    assert "<loc>http://testserver/quickstart</loc>" in body
    assert "<loc>http://testserver/explore</loc>" in body
    assert "<loc>http://testserver/alternatives</loc>" in body


def test_sitemap_contains_every_competitor_slug(client):
    r = client.get("/sitemap.xml")
    body = r.text
    for competitor in COMPETITORS:
        assert f"<loc>http://testserver/alternatives/{competitor.slug}</loc>" in body


def test_sitemap_excludes_auth_and_api_paths(client):
    r = client.get("/sitemap.xml")
    body = r.text
    for forbidden in ("/settings", "/dashboard", "/api/", "/mcp/", "/login", "/resume", "/health"):
        assert forbidden not in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_robots_sitemap.py::test_sitemap_xml_returns_200_xml -v`
Expected: FAIL with 404.

- [ ] **Step 3: Implement the route**

In `src/markland/web/app.py`, immediately after the `/robots.txt` route added in Task 2, add:

```python
    @app.get("/sitemap.xml", name="sitemap_xml")
    def sitemap_xml(request: Request):
        base_url = f"{request.url.scheme}://{request.url.netloc}"
        paths = ["/", "/quickstart", "/explore", "/alternatives"]
        paths += [f"/alternatives/{c.slug}" for c in COMPETITORS]
        today = datetime.utcnow().date().isoformat()
        body = build_sitemap_xml(base_url=base_url, urls=paths, lastmod=today)
        return Response(body, media_type="application/xml")
```

Now that `sitemap_xml` has a named route, switch the `/robots.txt` handler (Task 2) to use `url_for`:

```python
    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots_txt(request: Request):
        sitemap_url = str(request.url_for("sitemap_xml"))
        return PlainTextResponse(render_robots_txt(sitemap_url))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_robots_sitemap.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/app.py tests/test_robots_sitemap.py
git commit -m "feat(seo): serve dynamic /sitemap.xml sourced from COMPETITORS"
```

---

## Task 4: SEO meta partial — description, canonical, OG, Twitter

**Files:**
- Create: `src/markland/web/templates/_seo_meta.html`
- Modify: `src/markland/web/templates/base.html`
- Modify: `src/markland/web/app.py` (pass `request` to every template render so the partial can read it)
- Test: `tests/test_seo_meta.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_seo_meta.py`:

```python
"""SEO meta tags appear on every marketing page."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="http://testserver")
    return TestClient(app)


@pytest.mark.parametrize("path", ["/", "/quickstart", "/explore", "/alternatives"])
def test_pages_have_meta_description(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert '<meta name="description"' in r.text


@pytest.mark.parametrize("path", ["/", "/quickstart", "/explore", "/alternatives"])
def test_pages_have_canonical(client, path):
    r = client.get(path)
    text = r.text
    assert '<link rel="canonical"' in text
    assert f'href="http://testserver{path}"' in text


@pytest.mark.parametrize("path", ["/", "/quickstart", "/alternatives"])
def test_pages_have_og_and_twitter_tags(client, path):
    r = client.get(path)
    text = r.text
    assert 'property="og:title"' in text
    assert 'property="og:description"' in text
    assert 'property="og:type"' in text
    assert 'property="og:url"' in text
    assert 'name="twitter:card"' in text


def test_homepage_includes_softwareapplication_jsonld(client):
    r = client.get("/")
    text = r.text
    assert '"@type": "SoftwareApplication"' in text
    assert '"@type": "Organization"' in text
    assert '"@type": "WebSite"' in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_seo_meta.py -v`
Expected: FAIL (no meta description, no canonical, no JSON-LD).

- [ ] **Step 3: Create the partial**

Create `src/markland/web/templates/_seo_meta.html`:

```jinja
{#-
  SEO meta partial. Rendered from base.html <head>.

  Required context: request (FastAPI Request).
  Optional context (usually set via {% set %} at the top of the page template):
    seo_title:        page <title>; defaults to the {% block title %}.
    seo_description:  <meta name="description"> content; required per page.
    seo_og_type:      og:type; defaults to "website".
-#}
{%- set _host = request.url.scheme ~ '://' ~ request.url.netloc -%}
{%- set _canonical = _host ~ request.url.path -%}
{%- set _desc = seo_description | default('Markland is an MCP-based document publishing platform. Agents like Claude Code publish, share, and grant access to markdown documents with one tool call.') -%}
{%- set _og_type = seo_og_type | default('website') -%}
<meta name="description" content="{{ _desc }}">
<link rel="canonical" href="{{ _canonical }}">

<meta property="og:title" content="{{ self.title() }}">
<meta property="og:description" content="{{ _desc }}">
<meta property="og:type" content="{{ _og_type }}">
<meta property="og:url" content="{{ _canonical }}">
<meta property="og:site_name" content="Markland">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{{ self.title() }}">
<meta name="twitter:description" content="{{ _desc }}">

<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "@id": "{{ _host }}/#organization",
  "name": "Markland",
  "url": "{{ _host }}/",
  "description": "Agent-native document publishing. Shared documents for you and your agents, via MCP."
}
</script>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "@id": "{{ _host }}/#website",
  "url": "{{ _host }}/",
  "name": "Markland",
  "description": "Agent-native document publishing platform built on MCP.",
  "publisher": { "@id": "{{ _host }}/#organization" },
  "inLanguage": "en"
}
</script>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "@id": "{{ _host }}/#software",
  "name": "Markland",
  "url": "{{ _host }}/",
  "applicationCategory": "BusinessApplication",
  "applicationSubCategory": "DocumentManagement",
  "operatingSystem": "Web, macOS, Linux, Windows",
  "description": "Publish and share agent-authored documents with one MCP call and one link. A collaborative surface between Git and Google Docs.",
  "featureList": [
    "MCP-native publishing",
    "Human-to-agent document sharing",
    "One-link distribution",
    "Fork attribution"
  ],
  "publisher": { "@id": "{{ _host }}/#organization" }
}
</script>
```

- [ ] **Step 4: Include the partial in `base.html`**

In `src/markland/web/templates/base.html`, replace lines 6–9 (the `<title>` and font `<link>` block) with:

```html
    <title>{% block title %}Markland{% endblock %}</title>
    {% include "_seo_meta.html" %}
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700;800;900&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
```

- [ ] **Step 5: Make `request` available to every template render**

The existing routes in `app.py` do not pass `request` into `landing_tpl.render(...)`, etc. Patch each render call site to include `request=request`. In `src/markland/web/app.py`:

Modify the `/` (landing) handler (~line 252) to pass `request`:

```python
    @app.get("/", response_class=HTMLResponse)
    def landing(request: Request, signup: str | None = None):
        docs = list_featured_and_recent_public(db_conn, limit=4)
        cards = [_doc_to_card(d) for d in docs]
        signup_state = signup if signup in ("ok", "invalid") else None
        return HTMLResponse(
            landing_tpl.render(
                request=request,
                docs=cards,
                mcp_config_json=mcp_snippet_json,
                signup=signup_state,
            )
        )
```

Apply the same `request=request` addition to: `/quickstart`, `/alternatives`, `/alternatives/{slug}`, `/explore`, `/d/{share_token}`, `/admin/audit`. The `quickstart()` handler signature must also gain `request: Request`:

```python
    @app.get("/quickstart", response_class=HTMLResponse)
    def quickstart(request: Request):
        return HTMLResponse(quickstart_tpl.render(request=request))
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_seo_meta.py -v`
Expected: PASS (12 parametrized cases)

Run full web test suite: `pytest tests/test_web.py tests/test_quickstart_page.py -v`
Expected: all existing tests still PASS.

- [ ] **Step 7: Commit**

```bash
git add src/markland/web/templates/_seo_meta.html src/markland/web/templates/base.html src/markland/web/app.py tests/test_seo_meta.py
git commit -m "feat(seo): add _seo_meta partial with canonical, OG, Twitter, JSON-LD"
```

---

## Task 5: Per-page meta descriptions + retitle homepage

**Files:**
- Modify: `src/markland/web/templates/landing.html`
- Modify: `src/markland/web/templates/alternatives.html`
- Modify: `src/markland/web/templates/alternative.html`
- Modify: `src/markland/web/templates/explore.html`
- Test: `tests/test_seo_meta.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_seo_meta.py`:

```python
def test_homepage_title_includes_mcp_and_claude_code(client):
    r = client.get("/")
    # Title should hit high-intent keywords — MCP + Claude Code + AI agents.
    assert "MCP" in r.text.split("<title>")[1].split("</title>")[0]
    assert ("Claude Code" in r.text or "AI agents" in r.text)


def test_homepage_has_specific_meta_description(client):
    r = client.get("/")
    # Must not fall through to the default; must mention MCP + Claude Code.
    text = r.text
    start = text.index('<meta name="description"')
    end = text.index(">", start)
    tag = text[start:end]
    assert "MCP" in tag
    assert "Claude Code" in tag


def test_alternatives_description_mentions_comparison(client):
    r = client.get("/alternatives")
    text = r.text
    start = text.index('<meta name="description"')
    end = text.index(">", start)
    tag = text[start:end]
    assert "Markland" in tag
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_seo_meta.py::test_homepage_title_includes_mcp_and_claude_code -v`
Expected: FAIL (current title has no "MCP" or "Claude Code").

- [ ] **Step 3: Retitle + set description on landing.html**

In `src/markland/web/templates/landing.html`, replace line 3:

```jinja
{% block title %}Markland — MCP Document Server for Claude Code & AI Agents{% endblock %}
```

Immediately after `{% extends "base.html" %}` on line 1, add:

```jinja
{% set seo_description = "Markland is an MCP-based document platform for Claude Code and AI agents. Publish markdown, grant access, and share links with one MCP call. Git is overkill; Google Docs isn't agent-native." %}
```

- [ ] **Step 4: Set descriptions on the other marketing templates**

In `src/markland/web/templates/alternatives.html`, after `{% extends "base.html" %}`, add:

```jinja
{% set seo_description = "How Markland compares to Git, Google Docs, Notion, HackMD, and Markshare for sharing documents with AI agents. MCP-first, one-link sharing, per-doc grants." %}
```

In `src/markland/web/templates/alternative.html`, after `{% extends "base.html" %}`, add:

```jinja
{% set seo_description = "Markland vs " ~ competitor.name ~ ": " ~ competitor.one_liner ~ " Compared across agent access, sharing unit, and collaboration model." %}
```

In `src/markland/web/templates/explore.html`, after `{% extends "base.html" %}`, add:

```jinja
{% set seo_description = "Browse public Markland documents — specs, plans, research notes, and CLAUDE.md files published by agents and their humans." %}
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_seo_meta.py -v`
Expected: PASS.

Run: `pytest tests/test_web.py -v`
Expected: all pre-existing landing-page assertions still PASS (the H1 text `Shared documents` is unchanged, only `<title>` and `<meta>` changed).

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/templates/landing.html src/markland/web/templates/alternatives.html src/markland/web/templates/alternative.html src/markland/web/templates/explore.html tests/test_seo_meta.py
git commit -m "feat(seo): per-page meta descriptions; retitle home with MCP + Claude Code keywords"
```

---

## Task 6: GEO definitional paragraph on the homepage

A single sentence above the fold that LLMs can quote verbatim. Placed immediately after the H1 subhead (the `.lede` paragraph).

**Files:**
- Modify: `src/markland/web/templates/landing.html`
- Test: `tests/test_web.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web.py` (near the existing `test_landing_renders_empty`):

```python
def test_landing_has_geo_definitional_paragraph(client):
    r = client.get("/")
    text = r.text
    # LLM-friendly definitional sentence — single declarative statement
    # with the product category + primary use case.
    assert "Markland is an MCP-based document publishing platform" in text
    assert "Claude Code" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web.py::test_landing_has_geo_definitional_paragraph -v`
Expected: FAIL.

- [ ] **Step 3: Add the paragraph**

In `src/markland/web/templates/landing.html`, after line 549 (`<p class="lede">...</p>`), insert:

```jinja
    <p class="lede" style="font-size: 0.98rem; margin-top: -1.4rem;">
      <strong>Markland is an MCP-based document publishing platform</strong> that lets AI agents like Claude Code publish, share, and grant access to markdown documents via a single tool call.
    </p>
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_web.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/templates/landing.html tests/test_web.py
git commit -m "feat(seo): add GEO definitional paragraph for AI Overviews / LLM citation"
```

---

## Task 7: Expand quickstart — extend base, template host, H2 step headings, 600+ words

**Files:**
- Rewrite: `src/markland/web/templates/quickstart.html`
- Modify: `src/markland/web/app.py` (pass `request` — already done in Task 4)
- Test: `tests/test_quickstart_page.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_quickstart_page.py`:

```python
def test_quickstart_uses_base_layout(client):
    # Should inherit the site header/footer from base.html now.
    r = client.get("/quickstart")
    assert 'class="site-header"' in r.text
    assert 'class="site-footer"' in r.text


def test_quickstart_templates_setup_host(client):
    # Must NOT hardcode markland.dev — must use the request host.
    r = client.get("/quickstart")
    # TestClient serves under http://testserver by default.
    assert "claude mcp add markland http://testserver/setup" in r.text
    assert "markland.dev/setup" not in r.text


def test_quickstart_has_h2_step_headings(client):
    r = client.get("/quickstart")
    text = r.text
    # At least five H2 headings (one per step).
    assert text.count("<h2") >= 5


def test_quickstart_content_length_not_thin(client):
    import re as _re
    r = client.get("/quickstart")
    # Strip tags, count visible words. Thin-content floor: 600 words.
    visible = _re.sub(r"<[^>]+>", " ", r.text)
    visible = _re.sub(r"\s+", " ", visible)
    word_count = len(visible.split())
    assert word_count >= 600, f"quickstart is still thin: {word_count} words"


def test_quickstart_has_meta_description(client):
    r = client.get("/quickstart")
    assert '<meta name="description"' in r.text
    assert "MCP" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_quickstart_page.py -v`
Expected: existing 3 tests PASS, new 5 tests FAIL.

- [ ] **Step 3: Rewrite the template**

Replace `src/markland/web/templates/quickstart.html` entirely with:

```jinja
{% extends "base.html" %}
{% set seo_description = "Wire Markland's MCP server into Claude Code in five steps. Publish your first shared markdown doc from your agent in under two minutes." %}

{% block title %}Markland Quickstart — Publish Docs from Claude Code via MCP{% endblock %}

{% block nav_docs %}active{% endblock %}

{% block head_extra %}
        .qs {
            max-width: 780px;
            margin: 0 auto;
            padding: 3rem 1rem;
        }
        .qs h1 {
            font-family: var(--font-display);
            font-size: clamp(2rem, 5vw, 3.2rem);
            letter-spacing: -0.03em;
            line-height: 1.05;
            margin-bottom: 0.4rem;
        }
        .qs .sub {
            color: var(--muted);
            margin-bottom: 2.6rem;
            font-size: 1.05rem;
        }
        .qs h2 {
            font-family: var(--font-display);
            font-size: 1.35rem;
            letter-spacing: -0.02em;
            margin-top: 2.2rem;
            margin-bottom: 0.6rem;
        }
        .qs p { margin-bottom: 1rem; color: var(--text-2); }
        .qs ul, .qs ol { padding-left: 1.3rem; margin-bottom: 1rem; color: var(--text-2); }
        .qs code {
            font-family: var(--font-mono);
            background: var(--surface-2);
            border: 1px solid var(--outline-hairline);
            padding: 0.12em 0.4em;
            border-radius: 6px;
            font-size: 0.92em;
        }
        .qs pre {
            font-family: var(--font-mono);
            background: var(--surface-2);
            border: 1px solid var(--outline-hairline);
            padding: 1rem 1.1rem;
            border-radius: var(--radius);
            overflow-x: auto;
            margin-bottom: 1rem;
            font-size: 0.88rem;
        }
        .qs blockquote {
            border-left: 2px solid var(--outline);
            padding: 0.3rem 0 0.3rem 1rem;
            color: var(--text);
            margin: 0.8rem 0 1rem;
            font-style: italic;
        }
{% endblock %}

{% block content %}
<article class="qs">
  <h1>Markland Quickstart</h1>
  <p class="sub">Publish a markdown doc with your agent in five steps. Under two minutes, start to share link.</p>

  <p>
    Markland is an <strong>MCP-based document publishing platform</strong>. Your AI agent calls a tool, a doc goes up,
    a share link comes back. This quickstart takes you from zero to your first shared document using
    <a href="https://docs.anthropic.com/claude/docs/claude-code">Claude Code</a>. The same steps work with any other
    MCP-compatible client.
  </p>

  <h2>Before you start</h2>
  <p>You'll need:</p>
  <ul>
    <li>A terminal with <code>claude</code> (the Claude Code CLI) installed and signed in.</li>
    <li>An email address you can receive a magic link on.</li>
    <li>About two minutes.</li>
  </ul>
  <p>
    No credit card. No API keys to copy. Markland issues you a scoped bearer token the first time you connect Claude
    Code, and the CLI stores it for you.
  </p>

  <h2>1. Sign up</h2>
  <p>
    Open the Markland landing page, enter your email, and click the magic link that lands in your inbox. That's the whole
    signup flow &mdash; no password to set, no profile to fill out.
  </p>
  <p>
    Once you're signed in you'll see the <a href="/explore">Explore</a> page. Keep that tab open; you'll come back to it
    in step 5 to see your doc.
  </p>

  <h2>2. Wire up the MCP server</h2>
  <p>In a terminal, run:</p>
  <pre>claude mcp add markland {{ request.url.scheme }}://{{ request.url.netloc }}/setup</pre>
  <p>
    Claude Code will prompt you to open a browser, authorize a token, and then store the token in your local
    Claude Code config. When you're done, <code>claude mcp list</code> should show <code>markland</code> in the list.
  </p>
  <p>
    Under the hood Markland uses the
    <a href="https://modelcontextprotocol.io/">Model Context Protocol</a> &mdash; the tool surface your agent actually
    calls. There is no REST SDK to learn; the tool names are the API.
  </p>

  <h2>3. Publish your first doc</h2>
  <p>Ask Claude:</p>
  <blockquote>Publish a markdown doc titled &ldquo;Hello Markland&rdquo; with some notes about my project.</blockquote>
  <p>
    Your agent calls the <code>markland_publish</code> tool. You'll get back a share URL that looks like
    <code>/d/&lt;share-token&gt;</code>. The doc belongs to you, is private by default, and only you (and any agents you
    authorize on your behalf) can read it.
  </p>
  <p>
    You can ask Claude to publish any markdown &mdash; a spec, a plan, a research note, a <code>CLAUDE.md</code> file, a
    daily standup. Markland isn't opinionated about shape, only about being markdown.
  </p>

  <h2>4. Share it</h2>
  <p>Now grant access to a teammate:</p>
  <blockquote>Grant view access on that doc to friend@example.com.</blockquote>
  <p>
    Your agent calls <code>markland_grant</code>. Your friend receives an email with a link. If they're already signed in
    to Markland they see the doc right away; if not, they click the magic link in the invite email and are dropped onto
    the doc after signing in.
  </p>
  <p>
    Grants are per-doc. You can grant view, comment, or edit. You can also grant to another agent by its agent ID, so an
    agent on a teammate's laptop can read and append to docs on yours.
  </p>

  <h2>5. View the doc</h2>
  <p>
    Open the share link in your browser. You'll see the rendered markdown. Head back to
    <a href="/explore?view=mine">/explore</a> and you'll see the doc listed under <strong>Mine + Shared</strong>.
  </p>

  <h2>Troubleshooting</h2>
  <ul>
    <li>
      <strong><code>claude mcp list</code> doesn't show markland.</strong>
      Run <code>claude mcp add</code> again &mdash; the setup endpoint is idempotent and safe to re-run.
    </li>
    <li>
      <strong>The agent says it doesn't know about <code>markland_publish</code>.</strong>
      Restart Claude Code. New MCP servers are only picked up at session start.
    </li>
    <li>
      <strong>The share link returns 404.</strong>
      The token is case-sensitive and must include every character. Paste the whole thing rather than retyping.
    </li>
    <li>
      <strong>I want to revoke a grant.</strong>
      Ask Claude: <em>&ldquo;Revoke access for friend@example.com on that doc.&rdquo;</em>
      The agent calls <code>markland_revoke</code>.
    </li>
  </ul>

  <h2>What's next</h2>
  <p>
    Browse <a href="/explore">public docs</a> to see how other people are using Markland. Read the
    <a href="/alternatives">alternatives</a> page if you're weighing this against Git, Notion, Google Docs, or HackMD.
    Stuck on anything the troubleshooting list doesn't cover? Reply to the signup email &mdash; a real human reads it.
  </p>
</article>
{% endblock %}
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_quickstart_page.py -v`
Expected: PASS (8 tests).

Run: `pytest tests/test_seo_meta.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/templates/quickstart.html tests/test_quickstart_page.py
git commit -m "feat(seo): expand quickstart to 600+ words, template host, add H2 step headings"
```

---

## Task 8: SecurityHeadersMiddleware + X-Robots-Tag

**Files:**
- Create: `src/markland/web/security_headers_middleware.py`
- Modify: `src/markland/web/app.py` (register middleware)
- Test: `tests/test_security_headers.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_security_headers.py`:

```python
"""Security headers applied to every response; X-Robots-Tag on non-marketing paths."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db, insert_document
from markland.web.app import create_app


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
    h = r.headers
    assert h.get("strict-transport-security", "").startswith("max-age=")
    assert "content-security-policy" in h
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("x-frame-options") == "DENY"
    assert h.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "permissions-policy" in h


def test_marketing_paths_allow_indexing(client):
    for path in ["/", "/quickstart", "/explore", "/alternatives", "/d/tok1"]:
        r = client.get(path)
        # No X-Robots-Tag at all, or explicitly index,follow — either is fine.
        xrt = r.headers.get("x-robots-tag", "")
        assert "noindex" not in xrt, f"{path} should be indexable"


@pytest.mark.parametrize(
    "path,expected_status",
    [
        ("/health", 200),
        ("/settings", 401),   # auth-gated; still must carry noindex
        ("/dashboard", 401),
        ("/inbox", 401),
    ],
)
def test_noindex_on_private_paths(client, path, expected_status):
    r = client.get(path, follow_redirects=False)
    assert "noindex" in r.headers.get("x-robots-tag", "").lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_security_headers.py -v`
Expected: all FAIL (no headers set).

- [ ] **Step 3: Implement the middleware**

Create `src/markland/web/security_headers_middleware.py`:

```python
"""Starlette middleware that adds security + crawl-hygiene headers.

Mirrors the BaseHTTPMiddleware pattern used by RateLimitMiddleware. Every
response gets HSTS, a conservative CSP, XFO/XCTO/Referrer-Policy/
Permissions-Policy. Non-marketing paths additionally receive
`X-Robots-Tag: noindex, nofollow` — belt-and-suspenders on top of
robots.txt, because 401/405 responses do not themselves prevent indexing.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from markland.web.seo import should_noindex

_CSP = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "script-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

# Do not enable `preload` until the canonical domain is live and stable.
_HSTS = "max-age=31536000; includeSubDomains"

_PERMISSIONS = "geolocation=(), camera=(), microphone=(), payment=()"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("strict-transport-security", _HSTS)
        response.headers.setdefault("content-security-policy", _CSP)
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("x-frame-options", "DENY")
        response.headers.setdefault(
            "referrer-policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault("permissions-policy", _PERMISSIONS)
        if should_noindex(request.url.path):
            response.headers["x-robots-tag"] = "noindex, nofollow"
        return response
```

- [ ] **Step 4: Register the middleware**

In `src/markland/web/app.py`, find the line that registers `RateLimitMiddleware` (~line 503):

```python
    app.add_middleware(RateLimitMiddleware, db_conn=db_conn)
```

Immediately before it (Starlette runs middleware in reverse order of addition — the last added runs first, so we want security headers to wrap everything including the rate-limit 429 responses), add:

```python
    from markland.web.security_headers_middleware import SecurityHeadersMiddleware
    app.add_middleware(SecurityHeadersMiddleware)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_security_headers.py -v`
Expected: PASS.

Run the full suite: `pytest tests/ -x -q`
Expected: all PASS. The CSP allows Google Fonts via `style-src` and `font-src`, so the existing font-loading code still works.

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/security_headers_middleware.py src/markland/web/app.py tests/test_security_headers.py
git commit -m "feat(security): add security headers + X-Robots-Tag middleware"
```

---

## Task 9: Trust-floor stub pages + footer

Minimal real pages for About, Security, Privacy, Terms so the footer can link to them and search engines see a basic E-E-A-T floor. Copy is placeholder; the user will rewrite it.

**Files:**
- Create: `src/markland/web/templates/about.html`
- Create: `src/markland/web/templates/security.html`
- Create: `src/markland/web/templates/privacy.html`
- Create: `src/markland/web/templates/terms.html`
- Modify: `src/markland/web/templates/base.html` (real footer)
- Modify: `src/markland/web/app.py` (routes)
- Modify: `src/markland/web/seo.py` (add stub paths to sitemap list via the seo helper)
- Modify: `src/markland/web/app.py` sitemap route (include new paths)
- Test: `tests/test_trust_pages.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_trust_pages.py`:

```python
"""Trust-floor pages (about/security/privacy/terms) render and appear in sitemap/footer."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="http://testserver")
    return TestClient(app)


@pytest.mark.parametrize("path", ["/about", "/security", "/privacy", "/terms"])
def test_trust_page_renders_200(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert '<meta name="description"' in r.text


def test_footer_links_to_trust_pages(client):
    r = client.get("/")
    text = r.text
    for path in ["/about", "/security", "/privacy", "/terms"]:
        assert f'href="{path}"' in text


def test_sitemap_includes_trust_pages(client):
    r = client.get("/sitemap.xml")
    body = r.text
    for path in ["/about", "/security", "/privacy", "/terms"]:
        assert f"<loc>http://testserver{path}</loc>" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trust_pages.py -v`
Expected: all FAIL (404s).

- [ ] **Step 3: Create the four stub templates**

Each extends `base.html`, sets `seo_description`, renders a single `<article>` with an H1 and two-to-four paragraphs. User will rewrite the copy later.

Create `src/markland/web/templates/about.html`:

```jinja
{% extends "base.html" %}
{% set seo_description = "Markland is an agent-native document publishing platform. Built by a solo developer who thinks Git is overkill and Google Docs isn't agent-native." %}

{% block title %}About Markland{% endblock %}

{% block content %}
<article style="max-width: 720px; margin: 0 auto; padding: 3rem 1rem; color: var(--text-2);">
  <h1 style="font-family: var(--font-display); font-size: clamp(2rem, 5vw, 3rem); letter-spacing: -0.03em; line-height: 1.05; margin-bottom: 1.5rem; color: var(--text);">About Markland</h1>
  <p style="margin-bottom: 1rem;">
    Markland is an MCP-based document publishing platform. It sits between Git (too complex for throwaway collaboration) and Google Docs (not agent-native). The premise: agents and humans should edit the same documents, and the sharing primitive should be a single link.
  </p>
  <p style="margin-bottom: 1rem;">
    The project is built by a solo developer. It's in public beta. Feedback is welcome &mdash; reply to any Markland email and a human reads it.
  </p>
  <p>
    <a href="/quickstart" style="color: var(--blue); border-bottom: 1px solid var(--outline);">Try the quickstart</a> &middot;
    <a href="/explore" style="color: var(--blue); border-bottom: 1px solid var(--outline);">Browse public docs</a>
  </p>
</article>
{% endblock %}
```

Create `src/markland/web/templates/security.html`:

```jinja
{% extends "base.html" %}
{% set seo_description = "How Markland handles tokens, grants, and user data. Per-doc grants, scoped bearer tokens, encrypted transport." %}

{% block title %}Security — Markland{% endblock %}

{% block content %}
<article style="max-width: 720px; margin: 0 auto; padding: 3rem 1rem; color: var(--text-2);">
  <h1 style="font-family: var(--font-display); font-size: clamp(2rem, 5vw, 3rem); letter-spacing: -0.03em; line-height: 1.05; margin-bottom: 1.5rem; color: var(--text);">Security</h1>
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Authentication</h2>
  <p style="margin-bottom: 1rem;">
    Markland uses magic-link email for human sign-in and scoped bearer tokens for MCP clients. Tokens are issued per-user and per-agent; you can revoke them individually from the settings page.
  </p>
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Data handling</h2>
  <p style="margin-bottom: 1rem;">
    Documents are stored in SQLite on the server. Grants are per-document; there is no &ldquo;anyone with the link&rdquo; default. All traffic is HTTPS.
  </p>
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Reporting issues</h2>
  <p>
    Found a security issue? Email <a href="mailto:security@markland.dev" style="color: var(--blue); border-bottom: 1px solid var(--outline);">security@markland.dev</a>. Please allow a reasonable window before public disclosure.
  </p>
</article>
{% endblock %}
```

Create `src/markland/web/templates/privacy.html`:

```jinja
{% extends "base.html" %}
{% set seo_description = "Markland privacy practices: what we store, what we don't, and how to delete your data." %}

{% block title %}Privacy — Markland{% endblock %}

{% block content %}
<article style="max-width: 720px; margin: 0 auto; padding: 3rem 1rem; color: var(--text-2);">
  <h1 style="font-family: var(--font-display); font-size: clamp(2rem, 5vw, 3rem); letter-spacing: -0.03em; line-height: 1.05; margin-bottom: 1.5rem; color: var(--text);">Privacy</h1>
  <p style="margin-bottom: 1rem;">
    This is a placeholder. A full privacy policy will be published before general availability.
  </p>
  <p style="margin-bottom: 1rem;">
    What Markland stores today: your email address, display name, documents you publish, and the grants you create. What Markland does not do: sell your data, share it with advertisers, or train AI models on it.
  </p>
  <p>
    To delete your account and all associated documents, email <a href="mailto:privacy@markland.dev" style="color: var(--blue); border-bottom: 1px solid var(--outline);">privacy@markland.dev</a>.
  </p>
</article>
{% endblock %}
```

Create `src/markland/web/templates/terms.html`:

```jinja
{% extends "base.html" %}
{% set seo_description = "Markland terms of service. Beta software, no warranty, use at your own risk." %}

{% block title %}Terms — Markland{% endblock %}

{% block content %}
<article style="max-width: 720px; margin: 0 auto; padding: 3rem 1rem; color: var(--text-2);">
  <h1 style="font-family: var(--font-display); font-size: clamp(2rem, 5vw, 3rem); letter-spacing: -0.03em; line-height: 1.05; margin-bottom: 1.5rem; color: var(--text);">Terms of Service</h1>
  <p style="margin-bottom: 1rem;">
    This is a placeholder. Full terms will be published before general availability.
  </p>
  <p style="margin-bottom: 1rem;">
    Markland is in public beta. The service is provided as-is with no warranty. Please don't use it for anything you can't afford to lose access to.
  </p>
  <p>
    Don't upload content you don't have the right to publish. Don't use Markland to host illegal content. We reserve the right to remove documents or accounts that violate these guidelines.
  </p>
</article>
{% endblock %}
```

- [ ] **Step 4: Add the four routes**

In `src/markland/web/app.py`, immediately after the `/alternatives/{slug}` route (~line 228), add:

```python
    @app.get("/about", response_class=HTMLResponse)
    def about(request: Request):
        return HTMLResponse(
            _env.get_template("about.html").render(request=request)
        )

    @app.get("/security", response_class=HTMLResponse)
    def security(request: Request):
        return HTMLResponse(
            _env.get_template("security.html").render(request=request)
        )

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy(request: Request):
        return HTMLResponse(
            _env.get_template("privacy.html").render(request=request)
        )

    @app.get("/terms", response_class=HTMLResponse)
    def terms(request: Request):
        return HTMLResponse(
            _env.get_template("terms.html").render(request=request)
        )
```

Note: if the existing code caches templates via module-level variables (e.g., `quickstart_tpl = _env.get_template("quickstart.html")`), follow that pattern instead. Check the surrounding lines to match style — the engineer should grep for `get_template(` to see the established convention.

- [ ] **Step 5: Extend the sitemap**

In the `sitemap_xml` handler (added in Task 3), extend the `paths` list:

```python
        paths = ["/", "/quickstart", "/explore", "/alternatives", "/about", "/security", "/privacy", "/terms"]
        paths += [f"/alternatives/{c.slug}" for c in COMPETITORS]
```

- [ ] **Step 6: Rewrite the footer**

In `src/markland/web/templates/base.html`, replace lines 155–157 (the current footer) with:

```html
    <footer class="site-footer">
        <div style="max-width: var(--max-width); margin: 0 auto; display: flex; flex-wrap: wrap; gap: 1.5rem; justify-content: center; padding-bottom: 1rem;">
            <a href="/about">About</a>
            <a href="/explore">Explore</a>
            <a href="/alternatives">Alternatives</a>
            <a href="/quickstart">Quickstart</a>
            <a href="/security">Security</a>
            <a href="/privacy">Privacy</a>
            <a href="/terms">Terms</a>
        </div>
        <div>Markland &middot; an experiment in agent-native publishing</div>
    </footer>
```

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_trust_pages.py tests/test_robots_sitemap.py tests/test_web.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/markland/web/templates/about.html src/markland/web/templates/security.html src/markland/web/templates/privacy.html src/markland/web/templates/terms.html src/markland/web/templates/base.html src/markland/web/app.py tests/test_trust_pages.py
git commit -m "feat(seo): add trust-floor stub pages (about/security/privacy/terms) + real footer"
```

---

## Task 10: Self-host + subset fonts

Drop the external Google Fonts stylesheet in favor of self-hosted, preloaded, subsetted woff2. Recovers 300–800ms LCP on 4G and eliminates the big-H1 CLS reflow.

**Files:**
- Create: `src/markland/web/static/fonts/figtree-700.woff2`
- Create: `src/markland/web/static/fonts/figtree-800.woff2`
- Create: `src/markland/web/static/fonts/dmmono-400.woff2`
- Create: `src/markland/web/static/css/fonts.css`
- Modify: `src/markland/web/app.py` (mount `/static`)
- Modify: `src/markland/web/templates/base.html` (replace Google Fonts `<link>` with preload + self-hosted CSS)
- Modify: `src/markland/web/security_headers_middleware.py` (tighten CSP — no longer needs fonts.googleapis.com)
- Test: `tests/test_static_fonts.py` (new)

- [ ] **Step 1: Obtain the font files**

Use <https://gwfh.mranftl.com/fonts/figtree?subsets=latin> and <https://gwfh.mranftl.com/fonts/dm-mono?subsets=latin>. Select:
- Figtree weights 700 and 800 only (the two actually used in hero + buttons).
- DM Mono weight 400 only.
- Subsets: latin.
- Format: woff2.

Download, rename to `figtree-700.woff2`, `figtree-800.woff2`, `dmmono-400.woff2`, and save under `src/markland/web/static/fonts/`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_static_fonts.py`:

```python
"""Self-hosted fonts are served under /static/fonts/ and preloaded in base.html."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "f.db")
    app = create_app(conn, mount_mcp=False, base_url="http://testserver")
    return TestClient(app)


@pytest.mark.parametrize("filename", ["figtree-700.woff2", "figtree-800.woff2", "dmmono-400.woff2"])
def test_font_is_served_with_correct_mime(client, filename):
    r = client.get(f"/static/fonts/{filename}")
    assert r.status_code == 200
    assert r.headers["content-type"] in ("font/woff2", "application/font-woff2", "application/octet-stream")


def test_fonts_css_served(client):
    r = client.get("/static/css/fonts.css")
    assert r.status_code == 200
    assert "@font-face" in r.text
    assert "size-adjust" in r.text


def test_landing_preloads_self_hosted_fonts(client):
    r = client.get("/")
    text = r.text
    assert 'rel="preload" as="font"' in text
    assert '/static/fonts/figtree-800.woff2' in text
    # Google Fonts stylesheet should no longer be referenced.
    assert "fonts.googleapis.com/css2" not in text
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_static_fonts.py -v`
Expected: FAIL (no `/static` mount, no fonts.css, Google Fonts still in base.html).

- [ ] **Step 4: Write the fonts CSS**

Create `src/markland/web/static/css/fonts.css`:

```css
/*
 * Self-hosted font declarations.
 *
 * size-adjust / ascent-override / descent-override / line-gap-override values
 * metric-match Figtree to the -apple-system fallback so that font swap is
 * invisible (no CLS on the hero H1). Values taken from the Figtree metrics
 * reported by fonttools on the downloaded woff2 files; regenerate if you
 * swap in new files.
 */

@font-face {
  font-family: 'Figtree';
  font-style: normal;
  font-weight: 700;
  font-display: swap;
  src: url('/static/fonts/figtree-700.woff2') format('woff2');
  size-adjust: 97%;
  ascent-override: 102%;
  descent-override: 27%;
  line-gap-override: 0%;
}

@font-face {
  font-family: 'Figtree';
  font-style: normal;
  font-weight: 800;
  font-display: swap;
  src: url('/static/fonts/figtree-800.woff2') format('woff2');
  size-adjust: 97%;
  ascent-override: 102%;
  descent-override: 27%;
  line-gap-override: 0%;
}

@font-face {
  font-family: 'DM Mono';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url('/static/fonts/dmmono-400.woff2') format('woff2');
}
```

- [ ] **Step 5: Mount `/static` in FastAPI**

In `src/markland/web/app.py`, at the top with the other imports:

```python
from fastapi.staticfiles import StaticFiles
```

Inside `create_app`, immediately after the FastAPI `app = FastAPI(...)` instantiation (grep for `app = FastAPI` to find the exact line), add:

```python
    _STATIC_DIR = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
```

- [ ] **Step 6: Replace Google Fonts in base.html**

In `src/markland/web/templates/base.html`, replace lines 7–9 (the three existing font-related `<link>` tags) with:

```html
    <link rel="preload" href="/static/fonts/figtree-800.woff2" as="font" type="font/woff2" crossorigin>
    <link rel="preload" href="/static/fonts/figtree-700.woff2" as="font" type="font/woff2" crossorigin>
    <link rel="stylesheet" href="/static/css/fonts.css">
```

- [ ] **Step 7: Tighten the CSP**

In `src/markland/web/security_headers_middleware.py`, update `_CSP` to drop the Google Fonts origins:

```python
_CSP = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "img-src 'self' data:; "
    "script-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)
```

- [ ] **Step 8: Run tests**

Run: `pytest tests/test_static_fonts.py -v`
Expected: PASS.

Run the full suite: `pytest tests/ -x -q`
Expected: all PASS.

- [ ] **Step 9: Smoke-test locally**

Run: `uv run uvicorn markland.web.app:create_app --factory --reload` (or the equivalent dev-run command your repo uses — check `README.md` or `pyproject.toml` for the canonical command).

Load `http://localhost:8000/` in a browser. Open DevTools → Network → filter "font" → confirm only the two local woff2 files are fetched, no `fonts.gstatic.com`. DevTools → Console should be free of CSP violations.

- [ ] **Step 10: Commit**

```bash
git add src/markland/web/static src/markland/web/templates/base.html src/markland/web/app.py src/markland/web/security_headers_middleware.py tests/test_static_fonts.py
git commit -m "perf(fonts): self-host + subset Figtree/DM Mono, preload, metric-match fallback"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Each Critical + High from the audit has a task, except the three explicitly deferred domain items.
  - C: canonical tag → Task 4 (host-relative, domain-agnostic)
  - C: robots.txt → Tasks 1, 2
  - C: sitemap.xml → Tasks 1, 3
  - C: meta description, OG/Twitter, JSON-LD → Tasks 4, 5
  - C: E-E-A-T floor pages → Task 9
  - C: thin quickstart → Task 7
  - H: security headers → Task 8
  - H: X-Robots-Tag on auth/api paths → Tasks 1, 8
  - H: retitle homepage → Task 5
  - H: GEO definitional opener → Task 6
  - H: self-host + subset fonts → Task 10
  - Deferred: `markland.dev` hardcoding in quickstart → Task 7 templates the host, so no hardcoding remains; once DNS flips, no code change needed.
  - Deferred (domain-dependent): 301 `*.fly.dev` → `markland.dev`, `preload` flag on HSTS, competitor-pages audit (already inside quality gate).

- [x] **Placeholder scan:** No TBDs, no "handle edge cases", no "similar to Task N" hand-waves. Every code step has the full code. Every test step has the full test body.

- [x] **Type consistency:** `should_noindex` / `build_sitemap_xml` / `render_robots_txt` / `NOINDEX_PATH_PREFIXES` / `ROBOTS_TXT` / `SecurityHeadersMiddleware` all referenced by the exact same names across tasks.

- [x] **Hosting check:** `StaticFiles` mount lives inside `create_app` (Task 10) so it inherits the app's test and middleware stack. The `/static/` path does not collide with any existing route.

---

## Execution notes

- Tasks 1 → 10 are ordered so each one leaves `pytest tests/ -x -q` green. A bisected rollback is safe at any commit.
- Task 10 requires downloading binary font files; it's the only task that isn't purely code. If the engineer can't download the fonts (e.g., restricted environment), they can skip Task 10 and keep Google Fonts — the CSP in Task 8 already permits it. The other SEO wins are independent.
- After all tasks: run `curl -I https://<deployed-host>/` and verify every security header lands in production. Then submit the sitemap in Google Search Console using whatever hostname is live.
