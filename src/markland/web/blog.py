"""Blog content loading for /blog and /blog/{slug}.

Single source of truth: src/markland/web/content/blog/*.md.

Each post is a markdown file with a YAML-style frontmatter block:

    ---
    title: What is agent-native publishing?
    slug: agent-native-publishing
    published_at: 2026-05-03
    updated_at: 2026-05-03
    description: A 140-160 character meta description used as the OG/Twitter snippet.
    og_image: /assets/og/agent-native-publishing.png   # optional
    draft: false                                       # optional, defaults to false
    ---

    # Body markdown starts here

The frontmatter parser is intentionally minimal — no PyYAML dependency.
Each non-blank line inside the `---` fence is split on the first `:`,
the key is lower-cased, the value is the trimmed remainder. Booleans
parse as true/false (case-insensitive). Dates stay as ISO strings.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

CONTENT_DIR = Path(__file__).parent / "content" / "blog"


@dataclass(frozen=True)
class Post:
    slug: str
    title: str
    description: str
    published_at: str  # ISO date "YYYY-MM-DD"
    updated_at: str
    body_markdown: str
    og_image: str | None = None
    draft: bool = False


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a markdown file into (frontmatter dict, body)."""
    if not text.startswith("---\n"):
        raise ValueError("Post is missing frontmatter (must start with '---')")
    rest = text[4:]
    end = rest.find("\n---\n")
    if end == -1:
        raise ValueError("Post frontmatter is missing closing '---'")
    fm_text = rest[:end]
    body = rest[end + 5 :].lstrip("\n")
    fm: dict[str, str] = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"Frontmatter line missing ':': {line!r}")
        key, _, value = line.partition(":")
        fm[key.strip().lower()] = value.strip()
    return fm, body


def _post_from_path(path: Path) -> Post:
    fm, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    required = ("title", "slug", "published_at", "description")
    for field in required:
        if field not in fm:
            raise ValueError(f"{path.name}: frontmatter missing required '{field}'")
    draft_raw = fm.get("draft", "false").lower()
    return Post(
        slug=fm["slug"],
        title=fm["title"],
        description=fm["description"],
        published_at=fm["published_at"],
        updated_at=fm.get("updated_at", fm["published_at"]),
        body_markdown=body,
        og_image=fm.get("og_image") or None,
        draft=draft_raw in ("true", "yes", "1"),
    )


@functools.lru_cache(maxsize=1)
def _all_posts() -> tuple[Post, ...]:
    """Read every *.md under CONTENT_DIR. Cached for the process lifetime;
    blog content is rebuilt on deploy, not at request time."""
    if not CONTENT_DIR.exists():
        return ()
    posts = [_post_from_path(p) for p in sorted(CONTENT_DIR.glob("*.md"))]
    posts.sort(key=lambda p: p.published_at, reverse=True)
    return tuple(posts)


def list_published_posts() -> tuple[Post, ...]:
    """Posts visible to the public — drafts excluded, newest first."""
    return tuple(p for p in _all_posts() if not p.draft)


def get_post(slug: str) -> Post | None:
    for p in list_published_posts():
        if p.slug == slug:
            return p
    return None


def reset_cache() -> None:
    """Test-only: clear the lru_cache so reloads pick up fresh fixtures."""
    _all_posts.cache_clear()


def render_atom_feed(base_url: str, posts: tuple[Post, ...]) -> str:
    """Atom 1.0 feed for /blog/feed.xml. Atom (not RSS 2.0) because the
    spec is tighter, the date format is unambiguous (RFC 3339), and
    feed-readers handle both."""
    from html import escape
    base = base_url.rstrip("/")
    feed_url = f"{base}/blog/feed.xml"
    blog_url = f"{base}/blog"
    if posts:
        latest = max(p.updated_at for p in posts)
    else:
        latest = "2026-01-01"
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f'  <title>Markland Blog</title>',
        f'  <subtitle>Notes on agent-native publishing, MCP, and the workflow gap between AI agents and the humans they work with.</subtitle>',
        f'  <link href="{escape(blog_url)}" rel="alternate" type="text/html"/>',
        f'  <link href="{escape(feed_url)}" rel="self" type="application/atom+xml"/>',
        f'  <id>{escape(feed_url)}</id>',
        f'  <updated>{escape(latest)}T00:00:00Z</updated>',
        f'  <author><name>@dghiles</name><uri>https://github.com/dghiles</uri></author>',
    ]
    for p in posts:
        post_url = f"{base}/blog/{p.slug}"
        parts.extend([
            '  <entry>',
            f'    <title>{escape(p.title)}</title>',
            f'    <link href="{escape(post_url)}" rel="alternate" type="text/html"/>',
            f'    <id>{escape(post_url)}</id>',
            f'    <published>{escape(p.published_at)}T00:00:00Z</published>',
            f'    <updated>{escape(p.updated_at)}T00:00:00Z</updated>',
            f'    <summary>{escape(p.description)}</summary>',
            '  </entry>',
        ])
    parts.append('</feed>')
    return "\n".join(parts) + "\n"
