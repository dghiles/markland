"""CSP nonce coverage regression tests for Jinja templates.

PR #64 removed `'unsafe-inline'` from the `script-src` CSP directive and
added `nonce="{{ csp_nonce }}"` to inline `<script>` blocks. These tests
guard against regressions: every inline `<script>` MUST carry the nonce,
and inline event handlers (onclick=, onload=, etc.) are forbidden because
they don't execute under nonce-based CSP without `'unsafe-hashes'`.
"""

from __future__ import annotations

import pathlib
import re

TEMPLATE_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "markland" / "web" / "templates"


def test_no_nonceless_inline_scripts():
    """Every inline `<script>` opener must carry `nonce="{{ csp_nonce }}"`.

    External scripts (with `src=`) are exempt — they're constrained by
    `script-src 'self'` (or an allowlisted host) instead. JSON-LD blocks
    (`type="application/ld+json"`) are inline scripts in CSP's eyes too.
    """
    bad: list[str] = []
    for path in sorted(TEMPLATE_DIR.rglob("*.html")):
        text = path.read_text()
        for m in re.finditer(r"<script\b([^>]*)>", text):
            attrs = m.group(1)
            if "src=" in attrs:
                continue
            if 'nonce="{{ csp_nonce }}"' not in attrs:
                bad.append(f"{path.relative_to(TEMPLATE_DIR.parent.parent)}: {m.group(0)}")
    assert not bad, "Templates with nonce-less inline <script>:\n" + "\n".join(bad)


def test_no_inline_event_handlers():
    """Inline event handlers (onclick=, onload=, onsubmit=, ...) are blocked
    by nonce-based CSP without `'unsafe-hashes'`. Use addEventListener from
    a nonce'd `<script>` block instead.
    """
    bad: list[str] = []
    for path in sorted(TEMPLATE_DIR.rglob("*.html")):
        text = path.read_text()
        for m in re.finditer(r'\bon[a-z]+\s*=\s*["\']', text):
            bad.append(f"{path.relative_to(TEMPLATE_DIR.parent.parent)}: {m.group(0)}")
    assert not bad, "Templates with inline event handlers:\n" + "\n".join(bad)
