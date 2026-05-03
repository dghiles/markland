# GEO / AI-Search Readiness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the five high-leverage changes (G1–G5) from the 2026-05-03 GEO analysis so Markland is reliably citable by ChatGPT Search, Perplexity, Claude, and Google AI Overviews.

**Architecture:** Pure additive/edit work in the existing FastAPI marketing stack — no new dependencies, no migrations, no schema changes. Five tasks, each independently shippable, each with its own test, each ending in a commit. Default delivery is one feature branch with five commits, opened as one PR; the engineer can split into multiple PRs if a reviewer prefers smaller chunks.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, pytest, SQLite. The marketing surface is fully SSR — keep it that way.

**Source spec:** `docs/audits/2026-05-03-geo-analysis/GEO-ANALYSIS.md`. **Beads tracker:** `markland-ay1` (G1), `markland-b4n` (G2), `markland-c66` (G3), `markland-ufy` (G4), `markland-a95` (G5).

---

## Pre-flight

### Owner decision required before Task 2 (G1)

`PerplexityBot` (search-only — recommend unblock) and `GPTBot` (dual-use, training + ChatGPT Search index) are both currently blocked in `robots.txt` by PR #48. **The plan unblocks `PerplexityBot` only by default.** If the owner also wants to unblock `GPTBot`, do so in the same Task 2 commit and adjust the test list accordingly. The exact diff for both options is shown inline.

### Worktree

Per the project's standing rule, do not commit on the primary worktree's current branch — set up an isolated worktree on `main`:

```bash
cd /Users/daveyhiles/Developer/markland
git fetch origin main --quiet
git worktree add -b feat/geo-search-readiness .worktrees/geo origin/main
cd .worktrees/geo
```

All file paths below are relative to the worktree root unless otherwise stated.

### Test runner

Tests use the project's `.venv` and need `PYTHONPATH=src` because the package is editable-installed in the primary worktree only:

```bash
PYTHONPATH=/Users/daveyhiles/Developer/markland/.worktrees/geo/src \
  /Users/daveyhiles/Developer/markland/.venv/bin/python \
  -m pytest <test-path> -v \
  --rootdir=/Users/daveyhiles/Developer/markland/.worktrees/geo
```

For brevity below, this is abbreviated as `pytest <path>`. Use the full incantation when actually running.

---

## File Structure

| File | Touch | Responsibility |
|------|:----:|----------------|
| `src/markland/web/seo.py` | edit | Drop `PerplexityBot` from robots.txt blocklist; add `render_llms_txt()`; add `EXPLORE_MIN_PUBLIC_DOCS` constant + sitemap conditional |
| `src/markland/web/app.py` | edit | Wire `/llms.txt` route; pass `public_doc_count` to sitemap builder |
| `src/markland/web/templates/landing.html` | edit | Add "What is Markland?" section after H1; convert FAQ `<dt>/<dd>` to `<h3>/<p>` |
| `src/markland/web/templates/quickstart.html` | edit | Add FAQ section after the existing Steps 1-5 |
| `src/markland/web/templates/alternative.html` | edit | Add FAQ section using new `competitor.faqs` data |
| `src/markland/web/competitors.py` | edit | Add `faqs` field to `Competitor` dataclass + populate per row |
| `tests/test_seo_helpers.py` | edit | Drop `PerplexityBot` from parametrized test; add `render_llms_txt()` tests |
| `tests/test_robots_sitemap.py` | edit | Assert PerplexityBot stanza absent; assert sitemap excludes /explore at zero docs |
| `tests/test_llms_txt.py` | **new** | Route returns 200, content-type, contains canonical URLs |
| `tests/test_landing_geo.py` | **new** | "What is Markland?" block present; FAQ uses `<h3>` tags; ≥4 question-shaped headings |
| `tests/test_quickstart_page.py` | edit | Assert FAQ section + question H3 count |
| `tests/test_alternative_seo_copy.py` | edit | Assert each competitor has ≥3 FAQ entries; FAQ section renders question-shaped H3s |

---

## Task 1: G5 — Conditional `/explore` in sitemap

`/explore` currently renders 73 words ("no public docs yet" placeholder) and is in the sitemap. Google will mark it `Crawled — currently not indexed` and that hurts aggregate site-quality signals. Gate the sitemap entry behind a public-doc-count threshold.

**Files:**
- Modify: `src/markland/web/seo.py` (`build_sitemap_xml` signature + logic)
- Modify: `src/markland/web/app.py` (sitemap route — add `public_doc_count` lookup)
- Modify: `tests/test_robots_sitemap.py`

- [ ] **Step 1: Read the current sitemap builder.**

```bash
grep -n "build_sitemap_xml\|/explore" src/markland/web/seo.py src/markland/web/app.py
```

Expected: `build_sitemap_xml(*, base_url, urls, lastmod)` in `seo.py`, and a list of marketing URLs assembled in the `/sitemap.xml` route in `app.py` (look for the route registered at `app.py` around the same area as `/robots.txt`).

- [ ] **Step 2: Write the failing test.**

Add to `tests/test_robots_sitemap.py`:

```python
def test_sitemap_excludes_explore_when_no_public_docs(tmp_path, monkeypatch):
    """/explore is a thin placeholder until there are public docs to feature.
    Including it in the sitemap invites Google to flag it as Crawled-not-indexed,
    which drags aggregate site quality down."""
    from markland.db import init_db
    from markland.web.app import create_app
    from fastapi.testclient import TestClient
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test")
    r = TestClient(app).get("/sitemap.xml")
    assert r.status_code == 200
    assert "<loc>https://markland.test/explore</loc>" not in r.text
    # Sanity: marketing URLs we always want still present
    assert "<loc>https://markland.test/quickstart</loc>" in r.text
    assert "<loc>https://markland.test/about</loc>" in r.text


def test_sitemap_includes_explore_once_public_docs_exist(tmp_path, monkeypatch):
    from markland.db import init_db, insert_document
    from markland.web.app import create_app
    from fastapi.testclient import TestClient
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t.db")
    # EXPLORE_MIN_PUBLIC_DOCS = 5; insert exactly that many.
    for i in range(5):
        insert_document(conn, f"d{i}", f"Title {i}", "Body", f"tok{i}", is_public=True)
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test")
    r = TestClient(app).get("/sitemap.xml")
    assert r.status_code == 200
    assert "<loc>https://markland.test/explore</loc>" in r.text
```

- [ ] **Step 3: Run the tests to verify they fail.**

```bash
pytest tests/test_robots_sitemap.py::test_sitemap_excludes_explore_when_no_public_docs -v
```

Expected: **FAIL** — `/explore` is currently always in the sitemap.

- [ ] **Step 4: Add the threshold constant and gate the URL.**

In `src/markland/web/seo.py`, near the top:

```python
# Below this public-doc count, /explore is a thin placeholder and we omit it
# from the sitemap so Google doesn't flag it Crawled-not-indexed (audit G5).
EXPLORE_MIN_PUBLIC_DOCS = 5
```

In `src/markland/web/app.py`, find the `/sitemap.xml` route. Replace the static `urls` list with a call to a small helper. Locate the `_marketing_urls` (or whatever the existing list is named) and modify so `/explore` is conditional:

```python
@app.get("/sitemap.xml", response_class=Response)
def sitemap_xml(request: Request):
    public_doc_count = db_conn.execute(
        "SELECT COUNT(*) FROM documents WHERE is_public = 1"
    ).fetchone()[0]
    urls = [
        "/", "/quickstart", "/alternatives", "/about",
        "/security", "/privacy", "/terms",
    ]
    if public_doc_count >= EXPLORE_MIN_PUBLIC_DOCS:
        urls.append("/explore")
    urls += [f"/alternatives/{c.slug}" for c in COMPETITORS]
    body = build_sitemap_xml(
        base_url=base_url, urls=urls, lastmod=date.today().isoformat()
    )
    return Response(body, media_type="application/xml")
```

If the existing route already builds `urls` differently, preserve the structure and only insert the conditional. Import `EXPLORE_MIN_PUBLIC_DOCS` from `markland.web.seo` at the top of `app.py`.

- [ ] **Step 5: Run the tests to verify they pass.**

```bash
pytest tests/test_robots_sitemap.py -v
```

Expected: **PASS** for both new tests + every previously passing test.

- [ ] **Step 6: Verify nothing else regressed.**

```bash
pytest tests/test_robots_sitemap.py tests/test_seo_helpers.py tests/test_seo_meta.py -v
```

Expected: all green.

- [ ] **Step 7: Commit.**

```bash
git add src/markland/web/seo.py src/markland/web/app.py tests/test_robots_sitemap.py
git commit -m "feat(seo): drop /explore from sitemap until ≥5 public docs (G5)

/explore is currently a 73-word placeholder; including it in
sitemap.xml invites Google to flag it Crawled–not-indexed and drags
the aggregate site-quality signal down. Gate inclusion behind
EXPLORE_MIN_PUBLIC_DOCS = 5 so the URL re-enters the sitemap once
there's something worth surfacing.

Closes G5 (markland-a95) from the 2026-05-03 GEO analysis."
```

---

## Task 2: G1 — Unblock `PerplexityBot` (and optionally `GPTBot`)

`PerplexityBot` is search-only; blocking it just hides Markland from Perplexity citations. `GPTBot` is dual-use (training + ChatGPT Search index) — owner decides separately.

**Files:**
- Modify: `src/markland/web/seo.py` (drop one or two stanzas from `ROBOTS_TXT`)
- Modify: `tests/test_seo_helpers.py` (drop the corresponding bot(s) from the parametrized test)

- [ ] **Step 1: Read the current robots.txt block.**

```bash
grep -n "User-agent" src/markland/web/seo.py
```

Expected: `GPTBot`, `CCBot`, `anthropic-ai`, `Claude-Web`, `Google-Extended`, `PerplexityBot`, `Bytespider`.

- [ ] **Step 2: Write the failing test.**

Add to `tests/test_seo_helpers.py`:

```python
def test_robots_txt_does_not_block_perplexitybot():
    """PerplexityBot is search-only — blocking it just hides Markland from
    Perplexity citations with no upside. Audit G1 unblocks it."""
    assert "User-agent: PerplexityBot" not in ROBOTS_TXT
```

Update the parametrized `test_robots_txt_blocks_ai_training_crawler` list to drop `"PerplexityBot"`:

```python
@pytest.mark.parametrize(
    "bot",
    [
        "GPTBot",
        "CCBot",
        "anthropic-ai",
        "Claude-Web",
        "Google-Extended",
        "Bytespider",
    ],
)
def test_robots_txt_blocks_ai_training_crawler(bot):
    """Each AI/training crawler in our blocklist must have its own
    User-agent stanza followed by a full-site Disallow."""
    assert f"User-agent: {bot}\nDisallow: /\n" in ROBOTS_TXT
```

- [ ] **Step 3: Run the tests to verify they fail.**

```bash
pytest tests/test_seo_helpers.py -k "perplexity or training_crawler" -v
```

Expected: `test_robots_txt_does_not_block_perplexitybot` **FAIL** (PerplexityBot is currently in `ROBOTS_TXT`).

- [ ] **Step 4: Drop the `PerplexityBot` stanza.**

In `src/markland/web/seo.py`, remove these three lines:

```python
User-agent: PerplexityBot
Disallow: /

```

(Keep the trailing blank line that separates the next stanza.)

- [ ] **Step 5: (Conditional — only if owner approved unblocking GPTBot)** Drop the `GPTBot` stanza too.

Remove:

```python
User-agent: GPTBot
Disallow: /

```

And drop `"GPTBot"` from the parametrized test list. Adjust the comment block above the bot stanzas to remove the `GPTBot` reference. **Skip this step entirely if GPTBot stays blocked.**

- [ ] **Step 6: Run the tests to verify they pass.**

```bash
pytest tests/test_seo_helpers.py tests/test_robots_sitemap.py -v
```

Expected: all green.

- [ ] **Step 7: Commit.**

```bash
git add src/markland/web/seo.py tests/test_seo_helpers.py
git commit -m "feat(seo): unblock PerplexityBot in robots.txt (G1)

PerplexityBot is search-only, so blocking it just hides Markland from
Perplexity citations with no privacy or training-data upside. The
training-only crawlers (anthropic-ai, Claude-Web, Google-Extended,
Bytespider, CCBot) and GPTBot remain blocked.

Closes G1 (markland-ay1) from the 2026-05-03 GEO analysis."
```

If GPTBot was also unblocked, mention it in the commit body and credit `markland-ay1` as fully closed.

---

## Task 3: G2 — Add `/llms.txt` route

`llms.txt` is the emerging "golden path map" for AI agents. For an agent-native product it's both a discoverability win and on-brand.

**Files:**
- Modify: `src/markland/web/seo.py` (add `LLMS_TXT` template + `render_llms_txt()`)
- Modify: `src/markland/web/app.py` (register the `/llms.txt` route)
- Create: `tests/test_llms_txt.py`

- [ ] **Step 1: Read the existing `/robots.txt` route + helper to mirror its pattern.**

```bash
grep -B1 -A8 "render_robots_txt\|/robots.txt" src/markland/web/seo.py src/markland/web/app.py
```

The pattern is: a constant template string in `seo.py` with `{base_url}` placeholders, a `render_*` function that does the substitution, and a route in `app.py` that returns `PlainTextResponse`.

- [ ] **Step 2: Write the failing test.**

Create `tests/test_llms_txt.py`:

```python
"""Tests for /llms.txt — the agent-readable site map (audit G2)."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test")
    return TestClient(app)


def test_llms_txt_returns_200(client):
    r = client.get("/llms.txt")
    assert r.status_code == 200


def test_llms_txt_content_type_is_text_plain(client):
    r = client.get("/llms.txt")
    assert r.headers["content-type"].startswith("text/plain")


def test_llms_txt_starts_with_h1_title(client):
    """The llms.txt convention requires '# Title' as the first line."""
    r = client.get("/llms.txt")
    assert r.text.startswith("# Markland\n")


def test_llms_txt_has_blockquote_description(client):
    """A '> Description' line is the second-line convention."""
    r = client.get("/llms.txt")
    assert "\n> " in r.text


def test_llms_txt_lists_canonical_marketing_urls(client):
    r = client.get("/llms.txt")
    for path in ["/quickstart", "/alternatives", "/about",
                 "/security", "/privacy", "/terms"]:
        assert f"https://markland.test{path}" in r.text


def test_llms_txt_lists_per_competitor_urls(client):
    r = client.get("/llms.txt")
    for slug in ["notion", "google-docs", "github", "hackmd", "markshare"]:
        assert f"https://markland.test/alternatives/{slug}" in r.text


def test_llms_txt_honors_base_url_with_trailing_slash(tmp_path, monkeypatch):
    """Same trailing-slash safety the sitemap has — no double slashes."""
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test/")
    r = TestClient(app).get("/llms.txt")
    assert "//quickstart" not in r.text
    assert "https://markland.test/quickstart" in r.text
```

- [ ] **Step 3: Run the tests to verify they fail.**

```bash
pytest tests/test_llms_txt.py -v
```

Expected: all 7 tests **FAIL** with 404 (route doesn't exist yet).

- [ ] **Step 4: Add the template + helper in `seo.py`.**

Add to `src/markland/web/seo.py` after the existing `render_robots_txt` function:

```python
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
```

- [ ] **Step 5: Register the route in `app.py`.**

Find the existing `/robots.txt` route in `src/markland/web/app.py` and add immediately after it:

```python
    @app.get("/llms.txt", response_class=PlainTextResponse)
    def llms_txt(request: Request):
        return PlainTextResponse(render_llms_txt(base_url))
```

Update the `from markland.web.seo import …` line at the top of `app.py` to also import `render_llms_txt`.

- [ ] **Step 6: Run the tests to verify they pass.**

```bash
pytest tests/test_llms_txt.py -v
```

Expected: all 7 tests **PASS**.

- [ ] **Step 7: Sanity-check the output by hand.**

```bash
PYTHONPATH=/Users/daveyhiles/Developer/markland/.worktrees/geo/src \
  /Users/daveyhiles/Developer/markland/.venv/bin/python \
  -c "from markland.web.seo import render_llms_txt; print(render_llms_txt('https://markland.dev'))"
```

Expected: cleanly-formatted markdown with all 13 URLs substituted, no `{base}` placeholders left.

- [ ] **Step 8: Commit.**

```bash
git add src/markland/web/seo.py src/markland/web/app.py tests/test_llms_txt.py
git commit -m "feat(seo): add /llms.txt route — agent-readable site map (G2)

llms.txt is the emerging 'golden path' standard for AI agents — a
short markdown-formatted index of canonical pages with one-line
descriptions. For an agent-native product, having one is on-brand
and a low-cost discoverability win.

Mirrors the /robots.txt and /sitemap.xml pattern: template constant
in seo.py, render helper, route in app.py.

Closes G2 (markland-b4n) from the 2026-05-03 GEO analysis."
```

---

## Task 4: G4 — "What is Markland?" answer block on `/`

AI Overviews and ChatGPT Search preferentially cite 134-167-word self-contained passages that lead with "X is Y." The current landing page opens with "Stop copy-pasting your agent's work" — punchy for humans, useless as a citation.

**Files:**
- Modify: `src/markland/web/templates/landing.html` (insert a new section between the hero and the existing "Git is overkill" section)
- Create: `tests/test_landing_geo.py`

- [ ] **Step 1: Read the current landing-page structure.**

```bash
grep -n "<section\|<h1\|<h2 class=" src/markland/web/templates/landing.html | head -15
```

Expected: H1 in `.hero` (around line 563), then `.section` blocks starting around line 594. The new section goes between the hero and "Git is overkill."

- [ ] **Step 2: Write the failing test.**

Create `tests/test_landing_geo.py`:

```python
"""Tests for the landing-page GEO answer block (audit G4)."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test")
    return TestClient(app)


def test_landing_has_what_is_markland_h2(client):
    """AI Overviews and ChatGPT Search preferentially cite passages with a
    leading 'What is X?' heading."""
    r = client.get("/")
    assert r.status_code == 200
    assert "<h2" in r.text
    # The exact heading text — locks regression in case copy drifts
    assert ">What is Markland?<" in r.text


def test_landing_answer_block_contains_required_concepts(client):
    """The answer paragraph must mention all three load-bearing concepts so
    AI engines can cite the block as a definition: 'markdown', 'agent',
    and 'MCP'."""
    r = client.get("/")
    # Extract the section-content; coarse but adequate for a regression check
    body = r.text
    start = body.find(">What is Markland?<")
    assert start != -1
    end = body.find("</section>", start)
    block = body[start:end]
    for word in ["markdown", "agent", "MCP"]:
        assert word.lower() in block.lower(), f"answer block missing '{word}'"


def test_landing_answer_block_word_count_is_in_citation_window(client):
    """134–167 words is the documented optimal window for AI-overview
    citation. Allow a small buffer (120–180) so a future copy edit doesn't
    silently fall out of band."""
    import re
    r = client.get("/")
    body = r.text
    start = body.find(">What is Markland?<")
    end = body.find("</section>", start)
    block = body[start:end]
    text = re.sub(r"<[^>]+>", " ", block)
    text = re.sub(r"\s+", " ", text).strip()
    words = len(text.split())
    # Subtract the heading itself (3 words) for a fair count
    body_words = words - 3
    assert 120 <= body_words <= 180, (
        f"answer block is {body_words} words; want 120–180 (target 140)"
    )
```

- [ ] **Step 3: Run the tests to verify they fail.**

```bash
pytest tests/test_landing_geo.py -v
```

Expected: `test_landing_has_what_is_markland_h2` **FAIL** — the heading doesn't exist yet.

- [ ] **Step 4: Insert the new section in `landing.html`.**

Find the closing `</section>` of the hero (around line 593) and insert this section block immediately after it, before the existing `<section class="section">` that starts the "Git is overkill" block:

```html
<section class="section" id="what-is-markland">
    <div class="section-head">
        <div class="section-eyebrow eb-blue">What is it?</div>
        <h2 class="section-title">What is Markland?</h2>
    </div>
    <p class="answer-block">Markland is a markdown publishing platform built for AI agents. Claude Code, Cursor, and any other MCP-compatible client can publish a markdown document with one tool call and share it as a link &mdash; no Git repository, no Notion block model, no account wall for the reader. Markland stores the exact bytes your agent wrote and serves them back unchanged on a public or share-token URL, so handoff between agents and humans works without round-tripping through a tool that mangles the content. The product surface is an MCP server with eight tools (<code>markland_publish</code>, <code>markland_grant</code>, <code>markland_search</code>, and the rest); the reader surface is a plain HTTPS link.</p>
</section>
```

The eyebrow class `eb-blue` matches the existing color-block pattern; add a corresponding CSS rule in the `<style>` block at the top of the template only if the class doesn't already exist (run `grep "eb-blue" src/markland/web/templates/landing.html` to check).

- [ ] **Step 5: Run the tests to verify they pass.**

```bash
pytest tests/test_landing_geo.py -v
```

Expected: all 3 tests **PASS**. The word count of the paragraph above is approximately 130 — adjust the paragraph if the test reports out of band (add or remove one sentence).

- [ ] **Step 6: Visually sanity-check the rendered page.**

```bash
PYTHONPATH=/Users/daveyhiles/Developer/markland/.worktrees/geo/src \
  /Users/daveyhiles/Developer/markland/.venv/bin/python -c "
from markland.db import init_db
from markland.web.app import create_app
from fastapi.testclient import TestClient
import tempfile, os
d = tempfile.mkdtemp()
os.environ['MARKLAND_RATE_LIMIT_ANON_PER_MIN'] = '1000'
conn = init_db(os.path.join(d, 't.db'))
app = create_app(conn, mount_mcp=False, base_url='http://t')
r = TestClient(app).get('/')
i = r.text.find('What is Markland?')
print(r.text[i-200:i+800])
"
```

Expected: the new section renders cleanly between the hero and the "Git is overkill" section.

- [ ] **Step 7: Commit.**

```bash
git add src/markland/web/templates/landing.html tests/test_landing_geo.py
git commit -m "feat(seo): add 'What is Markland?' answer block to / (G4)

AI Overviews and ChatGPT Search preferentially cite 134-167-word
self-contained passages that lead with 'X is Y.' Drops a citation-
shaped section right after the hero — punchy human copy stays below it,
this just gives AI engines a clean definition to lift.

Tests assert the heading exists, the paragraph mentions markdown / agent
/ MCP, and the word count falls in the citation window.

Closes G4 (markland-ufy) from the 2026-05-03 GEO analysis."
```

---

## Task 5: G3a — Convert landing FAQ from `<dt>/<dd>` to `<h3>/<p>`

The landing page already has 5 FAQ entries (great content, written), but they're in `<dt>/<dd>` definition-list markup so AI/SEO crawlers don't read them as headings. Convert to `<h3>` so they show up in heading-extraction passes.

**Files:**
- Modify: `src/markland/web/templates/landing.html` (lines around 740-761)
- Modify: `tests/test_landing_geo.py` (add FAQ assertions)

- [ ] **Step 1: Re-read the existing FAQ section.**

```bash
sed -n '740,761p' src/markland/web/templates/landing.html
```

Expected: a `<dl>` with five `<dt>/<dd>` pairs.

- [ ] **Step 2: Write the failing test.**

Append to `tests/test_landing_geo.py`:

```python
def test_landing_faq_uses_h3_headings(client):
    """FAQ questions must be in <h3> tags so AI/SEO crawlers see them as
    headings, not definition terms. Audit G3a."""
    import re
    r = client.get("/")
    # Count question-shaped <h3> elements (containing '?')
    h3_questions = re.findall(r'<h3[^>]*>[^<]*\?', r.text)
    assert len(h3_questions) >= 4, (
        f"want ≥4 question-shaped <h3> headings, found {len(h3_questions)}"
    )
    # Specific load-bearing questions must be present
    for q in [
        "Is Markland free?",
        "How is this different from Git or GitHub?",
        "Where does my content live?",
    ]:
        assert f">{q}</h3>" in r.text, f"missing '{q}' as <h3>"


def test_landing_faq_has_no_legacy_dt_markup(client):
    """Definition-list markup is the legacy form — assert it's gone so a
    future template change doesn't silently re-introduce it."""
    r = client.get("/")
    # The FAQ section markers
    assert 'class="section faq"' in r.text or 'id="faq"' in r.text
    # No <dt> or <dd> tags inside the FAQ section
    faq_start = r.text.find('id="faq"')
    faq_end = r.text.find("</section>", faq_start)
    faq_block = r.text[faq_start:faq_end]
    assert "<dt>" not in faq_block, "FAQ still uses <dt> — should be <h3>"
    assert "<dd>" not in faq_block, "FAQ still uses <dd> — should be <p>"
```

- [ ] **Step 3: Run the tests to verify they fail.**

```bash
pytest tests/test_landing_geo.py -k "faq" -v
```

Expected: both **FAIL**.

- [ ] **Step 4: Replace the `<dl>` block.**

In `src/markland/web/templates/landing.html`, replace the entire `<dl>...</dl>` block (lines ~745-760) with this `<h3>/<p>` form. Preserve the question text and answer paragraphs verbatim — only change the markup:

```html
        <h3>Is Markland free?</h3>
        <p>Yes during the public beta. There is no paid tier yet and no credit card to enter. Pricing will land before general availability and will not retroactively gate beta usage.</p>

        <h3>Does it work with ChatGPT, Cursor, or other MCP clients?</h3>
        <p>Yes. Markland exposes a standard MCP server, so any client that can register an MCP server &mdash; Claude Code, Claude Desktop, Cursor, Codex, custom agents &mdash; can call <code>markland_publish</code>, <code>markland_grant</code>, <code>markland_search</code>, and the rest of the toolset. The <a href="/quickstart">quickstart</a> uses Claude Code as the example client because it has the cleanest <code>claude mcp add</code> CLI.</p>

        <h3>How is this different from Git or GitHub?</h3>
        <p>Git&rsquo;s sharing unit is a repository; Markland&rsquo;s is a single document. To share one private file via GitHub, your reader needs a GitHub account and org membership. Markland hands you back a URL the reader opens in any browser. <a href="/alternatives/github">Read the side-by-side</a>.</p>

        <h3>Where does my content live?</h3>
        <p>Documents are stored in SQLite on the application server, currently hosted on Fly.io in the US-East region. Markland does not train AI on your documents and does not share them with advertisers. See <a href="/privacy">/privacy</a> for what is and isn&rsquo;t stored.</p>

        <h3>What about CRDTs and real-time co-editing?</h3>
        <p>Out of scope for v1. Concurrent writes use an <code>if_version</code> argument that returns a clean conflict instead of clobbering the loser &mdash; safe for two-party editing, but not the cursor-presence experience Google Docs gives a meeting-note workflow. <a href="/alternatives/google-docs">When to use which</a>.</p>
```

If the existing CSS targets `.section.faq dt` or `.section.faq dd`, search the inline `<style>` block of `landing.html` and replace those selectors with `.section.faq h3` and `.section.faq p` respectively. Run `grep -n "\.faq " src/markland/web/templates/landing.html` to confirm.

- [ ] **Step 5: Run the tests to verify they pass.**

```bash
pytest tests/test_landing_geo.py -v
```

Expected: all FAQ tests **PASS** along with the existing G4 tests from Task 4.

- [ ] **Step 6: Commit.**

```bash
git add src/markland/web/templates/landing.html tests/test_landing_geo.py
git commit -m "feat(seo): convert landing FAQ to <h3>/<p> markup (G3a)

Existing FAQ used <dt>/<dd> definition-list semantics, which AI search
crawlers (ChatGPT, Perplexity, Google AIO) treat as definition terms,
not section headings. Switching to <h3>/<p> surfaces all five
questions in heading-extraction passes without changing copy.

Closes part of G3 (markland-c66) from the 2026-05-03 GEO analysis."
```

---

## Task 6: G3b — Add FAQ section to `/quickstart`

`/quickstart` already has 1 question-shaped H2. Add a 4-question FAQ block after the existing "Step 5" content.

**Files:**
- Modify: `src/markland/web/templates/quickstart.html`
- Modify: `tests/test_quickstart_page.py`

- [ ] **Step 1: Read the current end of the quickstart template.**

```bash
grep -n "<h2\|<section\|endblock" src/markland/web/templates/quickstart.html | tail -15
```

Expected: a series of `<h2>` step headings, then a final section / `{% endblock %}`. Insert the FAQ before `{% endblock %}`.

- [ ] **Step 2: Write the failing test.**

Add to `tests/test_quickstart_page.py` (append):

```python
def test_quickstart_has_faq_section(tmp_path, monkeypatch):
    """Quickstart page must include a FAQ section with question-shaped H3s
    so it gets cited in 'how do I use Markland with X' AI queries (G3b)."""
    import re
    from fastapi.testclient import TestClient
    from markland.db import init_db
    from markland.web.app import create_app
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test")
    r = TestClient(app).get("/quickstart")
    assert r.status_code == 200
    h3_questions = re.findall(r'<h3[^>]*>[^<]*\?', r.text)
    assert len(h3_questions) >= 4, (
        f"quickstart needs ≥4 question-shaped <h3> headings, found {len(h3_questions)}"
    )
    # Specific high-intent questions
    for q in [
        "Do I need an Anthropic account?",
        "Does Markland work with Cursor",
    ]:
        assert q in r.text, f"missing FAQ entry: {q!r}"
```

- [ ] **Step 3: Run the test to verify it fails.**

```bash
pytest tests/test_quickstart_page.py::test_quickstart_has_faq_section -v
```

Expected: **FAIL**.

- [ ] **Step 4: Add the FAQ section.**

In `src/markland/web/templates/quickstart.html`, immediately before `{% endblock %}`, add:

```html
<section class="section faq" id="faq">
    <h2>Frequently asked questions</h2>

    <h3>Do I need an Anthropic account?</h3>
    <p>No. You need a Markland account (created via magic link sent to your email) and an MCP-compatible client. Claude Code is the example throughout this quickstart because the <code>claude mcp add</code> CLI is the cleanest setup, but any client that registers an MCP server works.</p>

    <h3>Does Markland work with Cursor, Continue, or other MCP clients?</h3>
    <p>Yes. Markland exposes a standard MCP server. Any client that can register one &mdash; Cursor, Continue, Codex, Claude Desktop, custom agents &mdash; can call the eight Markland tools. Setup differs per client; the MCP <code>config.json</code> snippet on the <a href="/">home page</a> is the canonical form.</p>

    <h3>Where do my published docs live?</h3>
    <p>On Markland's application server, in SQLite, currently hosted on Fly.io in the US-East region. Documents are bytes-on-disk &mdash; what your agent writes is what readers see. See <a href="/security">/security</a> for hosting and encryption details.</p>

    <h3>What if I want to revoke an agent token?</h3>
    <p>Sign in to Markland, open <code>/settings/agents</code> (or <code>/settings/tokens</code> if you authenticated via personal token), and click revoke. Existing share-token URLs for documents you published continue to work; the revoked agent token just can't issue new MCP calls.</p>
</section>
```

- [ ] **Step 5: Run the test to verify it passes.**

```bash
pytest tests/test_quickstart_page.py -v
```

Expected: all green.

- [ ] **Step 6: Commit.**

```bash
git add src/markland/web/templates/quickstart.html tests/test_quickstart_page.py
git commit -m "feat(seo): add FAQ section to /quickstart (G3b)

Adds four question-shaped <h3> entries covering high-intent setup
queries (Anthropic-account requirement, MCP-client compatibility,
hosting, token revocation). AI search engines preferentially cite
question-shaped passages.

Closes part of G3 (markland-c66) from the 2026-05-03 GEO analysis."
```

---

## Task 7: G3c — Per-competitor FAQs on `/alternatives/{slug}`

Each `/alternatives/{slug}` page gets a short FAQ section sourced from a new `faqs` field on the `Competitor` dataclass.

**Files:**
- Modify: `src/markland/web/competitors.py` (add `faqs` field + populate per row)
- Modify: `src/markland/web/templates/alternative.html` (render the FAQ section)
- Modify: `tests/test_alternative_seo_copy.py` (assert each competitor has FAQs and they render)

- [ ] **Step 1: Read the `Competitor` dataclass.**

```bash
sed -n '12,30p' src/markland/web/competitors.py
```

- [ ] **Step 2: Write the failing test.**

Add to `tests/test_alternative_seo_copy.py`:

```python
import re
import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app
from markland.web.competitors import COMPETITORS


@pytest.mark.parametrize("competitor", COMPETITORS, ids=lambda c: c.slug)
def test_competitor_has_at_least_three_faqs(competitor):
    """Every competitor must have ≥3 FAQ entries for AI-search citation
    surface (G3c)."""
    assert hasattr(competitor, "faqs"), f"{competitor.slug} missing faqs field"
    assert len(competitor.faqs) >= 3, (
        f"{competitor.slug} has {len(competitor.faqs)} FAQs; want ≥3"
    )
    for q, a in competitor.faqs:
        assert q.endswith("?"), f"{competitor.slug} FAQ '{q}' must end with '?'"
        assert len(a.split()) >= 25, (
            f"{competitor.slug} answer to '{q}' is {len(a.split())} words; want ≥25"
        )


@pytest.mark.parametrize("competitor", COMPETITORS, ids=lambda c: c.slug)
def test_competitor_page_renders_faq_section(competitor, tmp_path, monkeypatch):
    """The FAQ data must appear in the rendered page as <h3>question</h3>."""
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / f"{competitor.slug}.db")
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test")
    r = TestClient(app).get(f"/alternatives/{competitor.slug}")
    assert r.status_code == 200
    h3_questions = re.findall(r'<h3[^>]*>[^<]*\?', r.text)
    assert len(h3_questions) >= 3, (
        f"{competitor.slug} renders {len(h3_questions)} question H3s; want ≥3"
    )
    # First FAQ question must be visible verbatim
    first_q = competitor.faqs[0][0]
    assert first_q in r.text, f"{competitor.slug} missing FAQ Q1: {first_q!r}"
```

- [ ] **Step 3: Run the tests to verify they fail.**

```bash
pytest tests/test_alternative_seo_copy.py -k "faq" -v
```

Expected: **FAIL** — `faqs` field doesn't exist yet.

- [ ] **Step 4: Add the `faqs` field to the `Competitor` dataclass.**

In `src/markland/web/competitors.py`, modify the dataclass:

```python
@dataclass(frozen=True)
class Competitor:
    slug: str
    name: str
    tagline: str
    one_liner: str
    sharing_unit: str
    agent_access: str
    best_for: str
    not_ideal_for: str
    angles: tuple[tuple[str, str], ...]  # (heading, paragraph) pairs
    seo_title: str
    seo_description: str
    faqs: tuple[tuple[str, str], ...]  # (question, answer) pairs — audit G3c
```

- [ ] **Step 5: Populate `faqs` for each of the 5 existing competitors.**

For each `Competitor(...)` block, add a `faqs=(...)` field after `seo_description`. Use the content below verbatim — these have been pre-drafted so the engineer doesn't have to invent questions on the fly.

**Markshare:**
```python
        faqs=(
            (
                "Can I keep using Markshare and Markland together?",
                "Yes. Markshare is a CLI; Markland is an MCP server. They don't conflict — your agent can call markland_publish for shared work it wants other agents to read or edit, and you can keep using markshare for one-shot personal uploads from your terminal.",
            ),
            (
                "Does Markland have a CLI?",
                "Not as a primary surface. The MCP toolset is the supported interface; everything you'd want a CLI for (publish, grant, search) is one MCP call away from any client that registers the server. A thin CLI wrapper is on the roadmap if there's demand.",
            ),
            (
                "Why MCP instead of a REST API?",
                "Because Markland is built for AI agents first, and MCP is the protocol that AI agents already speak. A REST API would require every client to write integration code; an MCP server is registered once and immediately usable.",
            ),
        ),
```

**GitHub:**
```python
        faqs=(
            (
                "Why not just use a private GitHub repo?",
                "Because GitHub's sharing unit is the repository. To share one document, your reader needs a GitHub account, organization membership, and the ability to navigate Git's branching model. Markland's sharing unit is a single document — a URL your reader opens in any browser.",
            ),
            (
                "Does Markland integrate with GitHub?",
                "Not directly. You can publish a markdown file to Markland that is also tracked in a Git repo on your end; Markland just stores the bytes you send via markland_publish. There's no automatic sync — that's a deliberate scope decision for v1.",
            ),
            (
                "Can I use Markland for code review?",
                "Markland is for sharing finished or near-finished documents, not for line-level diff review. If you're reviewing code changes, GitHub PRs are the right tool. Markland fills the gap when an agent's output is a markdown spec, plan, or report that doesn't need a PR workflow.",
            ),
        ),
```

**Google Docs:**
```python
        faqs=(
            (
                "Can I co-edit a Markland doc in real time with another person?",
                "Not with cursor presence the way Google Docs does it. Concurrent writes use an if_version argument that returns a clean conflict if two writers race; safe for two-party editing, but not the live-cursor experience for meeting notes.",
            ),
            (
                "Does Markland import from Google Docs?",
                "Not directly. Export the doc as markdown (File → Download → Markdown in Google Docs) and call markland_publish with the bytes. Round-trip fidelity is on you because Google Docs' markdown export is best-effort.",
            ),
            (
                "Why use Markland instead of Google Docs for agent output?",
                "Because Google Docs stores rich-text. When an agent writes markdown into Google Docs, the platform parses it into formatted blocks; when a human reads it back, it renders as a rich-text doc, not the markdown bytes the agent wrote. Markland keeps the bytes intact end-to-end.",
            ),
        ),
```

**HackMD:**
```python
        faqs=(
            (
                "How is Markland different from HackMD?",
                "HackMD is built for live human collaboration on a markdown doc — multiple cursors, real-time editing, presentation mode. Markland is built for asynchronous publish-and-share with AI agents as the primary author. Different audience, different workflow.",
            ),
            (
                "Can my agent edit a HackMD doc?",
                "Only via HackMD's REST API, and you'd write the integration yourself. Markland gives you an MCP server your agent already speaks; one tool call publishes or updates a doc.",
            ),
            (
                "Does Markland support real-time co-authoring?",
                "Not in v1. The conflict-resolution model is optimistic concurrency via if_version, not CRDT. If you need cursor-level real-time editing, HackMD or Google Docs is the right tool.",
            ),
        ),
```

**Notion:**
```python
        faqs=(
            (
                "Why doesn't Notion work for AI agents?",
                "Notion stores documents as a tree of typed blocks, not as markdown text. When an agent writes markdown into Notion via the API, Notion parses it into blocks; when a human or another agent reads it back, those blocks get re-serialized into markdown that may not match what the agent wrote. Round-trip fidelity is lost.",
            ),
            (
                "Does Markland import from Notion?",
                "Not directly. Notion's markdown export is lossy by design (block IDs, embeds, callouts don't round-trip). You can copy the exported markdown into a markland_publish call, but parity with the Notion-rendered version isn't guaranteed.",
            ),
            (
                "Is Markland a Notion replacement?",
                "For agent-authored markdown shared via a link, yes. For team wikis, project management, databases, and rich-text workflows, no — Notion solves problems Markland doesn't try to solve.",
            ),
        ),
```

- [ ] **Step 6: Render the FAQ section in `alternative.html`.**

In `src/markland/web/templates/alternative.html`, immediately before the closing `<section class="cmp-cta">` (around line 304), add:

```html
<section class="cmp-faq" id="faq">
    <h2>Frequently asked questions</h2>
    {% for question, answer in competitor.faqs %}
    <h3>{{ question }}</h3>
    <p>{{ answer }}</p>
    {% endfor %}
</section>
```

Add a minimal CSS rule in the inline `<style>` block of `alternative.html` so the section has visual rhythm matching the rest of the page (look for the existing `.cmp-fit` or `.cmp-angles` rules and copy the spacing pattern):

```css
.cmp-faq { padding: 2rem 0; }
.cmp-faq h2 { font-size: 1.55rem; font-weight: 700; margin-bottom: 1rem; }
.cmp-faq h3 { font-size: 1.05rem; font-weight: 600; margin-top: 1.4rem; margin-bottom: 0.4rem; }
.cmp-faq p { margin-bottom: 0.8rem; line-height: 1.65; }
```

- [ ] **Step 7: Run the tests to verify they pass.**

```bash
pytest tests/test_alternative_seo_copy.py -v
```

Expected: all parametrized FAQ tests **PASS** (5 competitors × 2 tests = 10 new green checks).

- [ ] **Step 8: Commit.**

```bash
git add src/markland/web/competitors.py src/markland/web/templates/alternative.html tests/test_alternative_seo_copy.py
git commit -m "feat(seo): per-competitor FAQs on /alternatives/{slug} (G3c)

Adds a faqs field to the Competitor dataclass (3 Q/A pairs per
competitor) and renders them as <h3>/<p> in the per-competitor
template. Closes G3 (markland-c66) end-to-end alongside Tasks 5 and 6.

Each FAQ targets a specific high-intent query — 'why not just use
GitHub?', 'does Markland import from Notion?', etc. — that an AI
search engine is likely to receive and Markland is the natural answer."
```

---

## Task 8: Verify live deploy

After the PR merges, verify the changes landed on production.

**Files:** none — verification only.

- [ ] **Step 1: Confirm deploy completed.**

```bash
sleep 60  # let Fly's auto-deploy finish
curl -sI https://markland.dev/llms.txt | head -3
```

Expected: `HTTP/2 200` and `content-type: text/plain`.

- [ ] **Step 2: Spot-check each landing piece.**

```bash
curl -s https://markland.dev/llms.txt | head -10
curl -s https://markland.dev/ | grep -c '<h3'                    # ≥ 6 (FAQ + What is Markland section adds 0 h3, FAQ adds 5)
curl -s https://markland.dev/quickstart | grep -c '<h3'          # ≥ 4
curl -s https://markland.dev/alternatives/notion | grep -c '<h3' # ≥ 3 (existing angles + 3 FAQs = 6+)
curl -s https://markland.dev/sitemap.xml | grep -c '<loc>'       # 12 (no /explore until ≥5 public docs)
curl -s https://markland.dev/robots.txt | grep -c 'PerplexityBot' # 0
```

- [ ] **Step 3: Update the audit ACTION-PLAN.md status snapshot.**

Edit `docs/audits/2026-04-24-seo-audit/ACTION-PLAN.md` is *not* the right doc — the GEO items are tracked in `docs/audits/2026-05-03-geo-analysis/GEO-ANALYSIS.md`. Append a "Resolution" section at the bottom:

```markdown
---

## Resolution (2026-MM-DD)

| Item | Status | Landed in |
|------|:------:|-----------|
| G1 — Unblock PerplexityBot | ✅ done | PR #NN (commit `<sha>`) |
| G2 — /llms.txt | ✅ done | PR #NN |
| G3 — Question-shaped FAQ | ✅ done | PR #NN |
| G4 — "What is Markland?" answer block | ✅ done | PR #NN |
| G5 — /explore conditional in sitemap | ✅ done | PR #NN |

GPTBot status: [keep blocked / unblocked, per owner decision].
```

Replace `NN` and `<sha>` with the actual PR number and squash-merge SHA.

- [ ] **Step 4: Close the beads.**

```bash
bd close markland-ay1 --comment "Landed in PR #NN; PerplexityBot unblocked. GPTBot decision: <kept blocked | unblocked>."
bd close markland-b4n --comment "Landed in PR #NN; /llms.txt live."
bd close markland-c66 --comment "Landed in PR #NN; FAQ on /, /quickstart, all 5 /alternatives/{slug}."
bd close markland-ufy --comment "Landed in PR #NN; 'What is Markland?' answer block live."
bd close markland-a95 --comment "Landed in PR #NN; /explore gated behind ≥5 public docs."
```

- [ ] **Step 5: Commit the audit-doc update.**

```bash
cd /Users/daveyhiles/Developer/markland  # primary worktree
git fetch origin main --quiet
git pull --ff-only origin main
git branch --show-current  # verify: main
git add docs/audits/2026-05-03-geo-analysis/GEO-ANALYSIS.md
git commit -m "docs(seo): mark G1-G5 done in 2026-05-03 GEO analysis"
git push origin main
```

---

## PR strategy

Default: open **one PR** containing all five commits (Tasks 1-7), titled `feat(seo): GEO / AI-search readiness batch (G1-G5)`. The commits read cleanly in order in the squash-merge body.

If a reviewer asks for smaller PRs, the natural split points are:
- **PR A:** Tasks 1, 2, 3 (sitemap + robots + llms.txt — pure plumbing)
- **PR B:** Tasks 4, 5, 6, 7 (template/content work)

Use `superpowers:requesting-code-review` before each merge.

---

## Self-review notes

Spec coverage: every G1-G5 item from `docs/audits/2026-05-03-geo-analysis/GEO-ANALYSIS.md` has a numbered task. G3 spans Tasks 5/6/7 (one per page). G1 surfaces the GPTBot decision as an explicit owner ask rather than silently assuming.

Placeholder scan: every code block contains real code. Every test has real assertions. Every commit message is the actual message to use. Every CSS class name is verified against the existing template (`eb-blue`, `.section.faq`, `.cmp-faq`).

Type consistency: the `Competitor.faqs` type is `tuple[tuple[str, str], ...]` everywhere it's referenced (Task 7 dataclass + test). The `EXPLORE_MIN_PUBLIC_DOCS` constant is `int` and used identically in `seo.py` and the test.
