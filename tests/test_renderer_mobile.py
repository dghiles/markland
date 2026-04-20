"""Mobile-rendering guarantees: wide tables get a horizontal scroll wrapper."""

from markland.web.renderer import render_markdown


def test_table_is_wrapped_in_scroll_container():
    md = (
        "| A | B | C | D | E |\n"
        "|---|---|---|---|---|\n"
        "| 1 | 2 | 3 | 4 | 5 |\n"
    )
    html = render_markdown(md)
    assert '<div class="table-scroll">' in html
    assert html.count("</div>") == 1
    # Sanity: the wrapper closes before the next block. No nested table-scroll.
    assert html.count('<div class="table-scroll">') == 1
    assert html.count("<table>") == 1


def test_non_table_markdown_has_no_wrapper():
    html = render_markdown("# Heading\n\nA paragraph.")
    assert "table-scroll" not in html
