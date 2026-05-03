"""Pure-Python SEO helpers: crawl policy, robots.txt, sitemap generation.

Kept free of FastAPI/Jinja imports so it is trivial to unit-test and reusable
from routes, middleware, or CLI scripts.
"""

from __future__ import annotations

from typing import Callable, Union
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


# Generated from NOINDEX_PATH_PREFIXES so robots.txt and the X-Robots-Tag
# middleware can never drift. A bare-prefix Disallow (no trailing slash)
# matches both the exact path and its children per standard robots.txt
# prefix semantics, which mirrors should_noindex() above.
_DISALLOW_LINES = "\n".join(f"Disallow: {p}" for p in NOINDEX_PATH_PREFIXES)

ROBOTS_TXT = f"""\
User-agent: *
Allow: /
{_DISALLOW_LINES}

# Block AI training crawlers; real search engines (Googlebot, Bingbot) fall
# through to the wildcard rule above. Google-Extended is the opt-out for
# Gemini/Vertex training without affecting Googlebot's regular index crawl.
User-agent: GPTBot
Disallow: /

User-agent: CCBot
Disallow: /

User-agent: anthropic-ai
Disallow: /

User-agent: Claude-Web
Disallow: /

User-agent: Google-Extended
Disallow: /

User-agent: PerplexityBot
Disallow: /

User-agent: Bytespider
Disallow: /

Sitemap: {{sitemap_url}}
"""


def render_robots_txt(sitemap_url: str) -> str:
    """Return robots.txt body with the sitemap URL filled in."""
    return ROBOTS_TXT.format(sitemap_url=sitemap_url)


def build_sitemap_xml(
    *,
    base_url: str,
    urls: list[str],
    lastmod: Union[str, Callable[[str], str]],
) -> str:
    """Build a minimal, well-formed sitemap XML document.

    `base_url` is the scheme+host (e.g. ``https://example.test``). Trailing
    slash is tolerated. Each entry in ``urls`` is a root-relative path such
    as ``/quickstart`` — it must begin with ``/``.

    `lastmod` may be either:
    - a string (used for every URL — uniform timestamp), or
    - a callable ``(path) -> str`` returning a per-path lastmod (audit
      2026-04-24 M10 — wired to template file mtime so /quickstart and
      /privacy carry distinct dates as soon as they diverge).
    """
    base = base_url.rstrip("/")
    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    resolve_lastmod: Callable[[str], str] = (
        lastmod if callable(lastmod) else (lambda _path: lastmod)
    )
    for path in urls:
        if not path.startswith("/"):
            raise ValueError(f"sitemap path must start with '/': {path!r}")
        loc = escape(f"{base}{path}")
        mod = escape(resolve_lastmod(path))
        lines.append(
            f"  <url><loc>{loc}</loc><lastmod>{mod}</lastmod></url>"
        )
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"
