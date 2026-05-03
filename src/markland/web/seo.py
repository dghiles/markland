"""Pure-Python SEO helpers: crawl policy, robots.txt, sitemap generation.

Kept free of FastAPI/Jinja imports so it is trivial to unit-test and reusable
from routes, middleware, or CLI scripts.
"""

from __future__ import annotations

from typing import Callable, Union
from xml.sax.saxutils import escape

# Path prefixes that must never be indexed. Match both exact paths and
# children (e.g. "/settings" and "/settings/tokens").
# Below this public-doc count, /explore is a thin placeholder and we omit it
# from the sitemap so Google doesn't flag it Crawled-not-indexed (audit G5).
EXPLORE_MIN_PUBLIC_DOCS = 5

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

# Real search engines (Googlebot, Bingbot) fall through to the wildcard
# rule above. AI search/browse crawlers (GPTBot, PerplexityBot, ClaudeBot,
# OAI-SearchBot, ChatGPT-User) are deliberately allowed so Markland is
# citable in ChatGPT Search, Perplexity, and Claude.
#
# Google-Extended is Google's opt-out specifically for Gemini/Vertex
# training; it does NOT affect Googlebot's regular index or AI Overviews,
# so blocking it gives a clean training opt-out with zero visibility cost.
#
# Bytespider is ByteDance's crawler for TikTok/Doubao — kept blocked
# until there's a reason to court the Chinese-market AI surface.
User-agent: Google-Extended
Disallow: /

User-agent: Bytespider
Disallow: /

Sitemap: {{sitemap_url}}
"""


def render_robots_txt(sitemap_url: str) -> str:
    """Return robots.txt body with the sitemap URL filled in."""
    return ROBOTS_TXT.format(sitemap_url=sitemap_url)


LLMS_TXT = """\
# Markland
> Agent-native publishing for markdown documents. Claude Code and other
> MCP-compatible AI agents publish a markdown document with one tool
> call and share it as a link — no Git repo, no Notion block model, no
> account wall for the reader. Markland stores the bytes the agent
> wrote and serves them back unchanged.

## Core
- [Markland — overview]({base}/): what Markland is, who it's for, how it works
- [Quickstart]({base}/quickstart): wire up the MCP server in five steps
- [Alternatives]({base}/alternatives): how Markland differs from Notion, Google Docs, Git/GitHub, HackMD, Markshare

## Per-tool comparisons
- [vs Notion]({base}/alternatives/notion): block model vs raw markdown
- [vs Google Docs]({base}/alternatives/google-docs): rich-text vs markdown-first
- [vs Git/GitHub]({base}/alternatives/github): repo-as-share vs doc-as-share
- [vs HackMD]({base}/alternatives/hackmd): live collab vs MCP-native publishing
- [vs Markshare]({base}/alternatives/markshare): CLI upload vs MCP server

## About
- [About / philosophy]({base}/about): why Markland exists
- [Security]({base}/security): bearer tokens, hashing, hosting region
- [Privacy]({base}/privacy): what's stored, what isn't
- [Terms]({base}/terms): beta-stage software, acceptable use
"""


def render_llms_txt(base_url: str) -> str:
    """Return llms.txt body with base_url substituted into every link.
    Strips a trailing slash from base_url to avoid double slashes."""
    return LLMS_TXT.format(base=base_url.rstrip("/"))


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
