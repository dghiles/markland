"""Tests for markdown-to-HTML rendering."""

from markland.web.renderer import render_markdown


def test_renders_heading():
    html = render_markdown("# Hello World")
    assert "<h1>" in html
    assert "Hello World" in html


def test_renders_paragraph():
    html = render_markdown("Just a paragraph.")
    assert "<p>" in html
    assert "Just a paragraph." in html


def test_renders_inline_code():
    html = render_markdown("Use `pip install` to install.")
    assert "<code>" in html
    assert "pip install" in html


def test_renders_fenced_code_block():
    md = '```python\nprint("hello")\n```'
    html = render_markdown(md)
    assert "<pre" in html or "<code" in html
    assert "hello" in html


def test_renders_code_with_syntax_highlighting():
    md = '```python\ndef foo():\n    return 1\n```'
    html = render_markdown(md)
    # Pygments highlighting produces span tags with CSS classes
    assert 'class="highlight"' in html or "<span" in html


def test_renders_link():
    html = render_markdown("[click here](https://example.com)")
    assert 'href="https://example.com"' in html


def test_renders_unordered_list():
    html = render_markdown("- item 1\n- item 2\n- item 3")
    assert "<ul>" in html
    assert "<li>" in html


def test_renders_ordered_list():
    html = render_markdown("1. first\n2. second")
    assert "<ol>" in html


def test_renders_table():
    md = "| A | B |\n|---|---|\n| 1 | 2 |"
    html = render_markdown(md)
    assert "<table>" in html


def test_renders_blockquote():
    html = render_markdown("> a quote")
    assert "<blockquote>" in html


def test_empty_content_returns_empty():
    assert render_markdown("") == ""
    assert render_markdown("   ").strip() == ""


def test_escapes_raw_html():
    html = render_markdown("<script>alert('xss')</script>")
    # markdown-it with html=False should escape the tag
    assert "<script>" not in html


def test_excerpt_short_content():
    from markland.web.renderer import make_excerpt
    assert make_excerpt("Hello world.") == "Hello world."


def test_excerpt_strips_heading_markers():
    from markland.web.renderer import make_excerpt
    result = make_excerpt("# Title\n\nBody text here.")
    assert result.startswith("Title Body text here.")


def test_excerpt_strips_list_markers():
    from markland.web.renderer import make_excerpt
    result = make_excerpt("- item one\n- item two")
    assert "-" not in result
    assert "item one" in result
    assert "item two" in result


def test_excerpt_strips_link_syntax_keeps_text():
    from markland.web.renderer import make_excerpt
    result = make_excerpt("See [the docs](https://example.com) for more.")
    assert "the docs" in result
    assert "example.com" not in result


def test_excerpt_strips_code_fences():
    from markland.web.renderer import make_excerpt
    content = "Intro text.\n\n```python\ndef foo():\n    pass\n```\n\nAfter code."
    result = make_excerpt(content)
    assert "def foo" not in result
    assert "Intro text" in result
    assert "After code" in result


def test_excerpt_truncates_long_content():
    from markland.web.renderer import make_excerpt
    long_text = "word " * 100
    result = make_excerpt(long_text, length=50)
    assert len(result) <= 51  # 50 + ellipsis
    assert result.endswith("…")


def test_excerpt_no_ellipsis_when_short():
    from markland.web.renderer import make_excerpt
    result = make_excerpt("Short text.", length=50)
    assert "…" not in result
