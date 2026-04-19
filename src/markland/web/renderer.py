"""Markdown → HTML rendering with Pygments syntax highlighting."""

from markdown_it import MarkdownIt
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound


def _highlight_code(code: str, lang: str, attrs: str) -> str:
    """Highlight fenced code block using Pygments."""
    try:
        lexer = get_lexer_by_name(lang) if lang else TextLexer()
    except ClassNotFound:
        lexer = TextLexer()
    formatter = HtmlFormatter(cssclass="highlight", nowrap=False)
    return highlight(code, lexer, formatter)


def _build_markdown_renderer() -> MarkdownIt:
    md = MarkdownIt(
        "gfm-like",  # includes tables, strikethrough, linkify
        {
            "html": False,  # escape raw HTML for safety
            "linkify": False,  # requires linkify-it-py; skip for MVP
            "typographer": True,
            "highlight": _highlight_code,
        },
    )
    md.use(tasklists_plugin)
    return md


_md = _build_markdown_renderer()


def render_markdown(content: str) -> str:
    """Render a markdown string to HTML."""
    if not content or not content.strip():
        return ""
    return _md.render(content)


import re as _re


def make_excerpt(content: str, length: int = 140) -> str:
    """Strip common markdown syntax and return the first `length` chars."""
    if not content:
        return ""
    # Remove fenced code blocks greedily across lines
    cleaned = _re.sub(r"```.*?```", "", content, flags=_re.DOTALL)
    # Strip heading markers
    cleaned = _re.sub(r"^#+\s*", "", cleaned, flags=_re.MULTILINE)
    # Strip list markers (-, *, +, or numbered)
    cleaned = _re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=_re.MULTILINE)
    cleaned = _re.sub(r"^\s*\d+\.\s+", "", cleaned, flags=_re.MULTILINE)
    # Replace [text](url) with text
    cleaned = _re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)
    # Strip blockquote markers
    cleaned = _re.sub(r"^\s*>\s?", "", cleaned, flags=_re.MULTILINE)
    # Strip emphasis and inline code chars
    cleaned = _re.sub(r"[*_`]", "", cleaned)
    # Collapse whitespace
    cleaned = _re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > length:
        return cleaned[:length].rstrip() + "…"
    return cleaned
