"""Pure-Python SEO helpers: crawl policy, robots.txt, sitemap generation.

Kept free of FastAPI/Jinja imports so it is trivial to unit-test and reusable
from routes, middleware, or CLI scripts.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

# Path prefixes that must never be indexed. Match both exact paths and
# children (e.g. "/settings" and "/settings/tokens").
NOINDEX_PATH_PREFIXES: tuple[str, ...] = (
    "/api",
    "/mcp",
    "/admin",
    "/settings",
    "/dashboard",
    "/inbox",
    "/resume",
    "/login",
    "/verify",
    "/setup",
    "/device",
    "/invite",
    "/health",
)


def should_noindex(path: str) -> bool:
    """Return True if this URL path should carry ``X-Robots-Tag: noindex``."""
    for prefix in NOINDEX_PATH_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
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
        mod = escape(lastmod)
        lines.append(
            f"  <url><loc>{loc}</loc><lastmod>{mod}</lastmod></url>"
        )
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"
