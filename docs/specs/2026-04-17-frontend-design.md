# Markland Frontend — Landing + Explore Design Spec

**Date:** 2026-04-17
**Updated:** 2026-04-18 — Visual Direction refined to **Dark + Outlined + Primary**. Reference: https://io.google/2024/ (specifically the dark-mode content-hub cards — two-up outlined dark tiles with primary-color content)
**Status:** Shipped — retrospectively authoritative
**Author:** Davey Hiles

**Theming history:**
1. 2026-04-17 — MVP shipped with generic system-UI styling
2. 2026-04-18 AM — neubrutalism pass (cream + Archivo Black + hard offset shadows). Superseded. Retrospective: `docs/plans/2026-04-18-neubrutalism-theming.md`
3. 2026-04-18 mid-day — IO24 / gradient pass (warm off-white + rainbow gradients + Figtree + soft shadows). Superseded after design review (too soft, too gradient-heavy, too "indie SaaS"). Retrospective: `docs/plans/2026-04-18-io24-theming.md`
4. 2026-04-18 PM — **Dark-Outlined-Primary** (current authority). Retrospective: `docs/plans/2026-04-18-dark-outlined-primary.md`

## Overview

Add two public web pages to the Markland web viewer: a marketing landing page (`/`) that doubles as a showcase of real agent-authored docs, and an explore gallery (`/explore`) with search and a masonry grid for browsing all public docs. Introduce a two-state visibility model (`unlisted` / `public`) plus a `featured` flag for pinning specific docs to the landing hero. No auth, no accounts, no bylines — this is an MVP showcase, not a multi-tenant platform.

The visual identity is deliberate — see Visual Direction below. Markland's technical moat is thin (MCP server + SQLite + static markdown is not hard to replicate). Aesthetic is a differentiation vector that costs only taste, and taste is exactly what generic clones will lack.

## Goals

- Give first-time visitors a landing page that explains what Markland is and shows real docs as proof.
- Give everyone a public gallery at `/explore` for finding docs with search.
- Preserve the existing private-share default — only opt-in docs become public.
- Let Davey curate which public docs appear on the landing hero.

## Non-Goals

- No user accounts or auth in this phase.
- No per-doc author bylines (single-user MVP).
- No tags, categories, or multi-sort (Recent only).
- No pagination (hard cap at 50 results on `/explore`).
- No VPS deployment (stays local-only; defer to a separate plan).
- No asset pipeline, no bundler, no external CSS framework — all styles inlined.

## Visual Direction

**Aesthetic: Dark + Outlined + Primary.** Near-black canvas, content lives inside dark cards defined by thin white outlines (~22% opacity white stroke). No gradients anywhere. Primary colors — Google red, yellow, blue, green — used as **discrete solid accents**: a single colored dot, a single colored character of punctuation, a colored numeral, a solid-color badge fill. Typography is Figtree throughout (plus Newsreader serif for doc-viewer body), pure white for headlines, off-white `#E8EAED` for body. Modern, cool, colorful — without the "monotone AI slop" feel that bland single-color minimalism produces.

**Reference:** https://io.google/2024/ — specifically the two-up outlined-tile "Join a community group" / "Continue learning" pattern. Dark fills, thin white strokes, pill buttons with white outlines, white display type.

**Why this fits Markland.** Agent-first builders recognize the IO24 aesthetic as tech-premium (same visual tribe as Linear, Arc, Raycast, OpenAI's developer surfaces). The dark + outlined move signals serious, technical, intentionally built. The discrete primaries prevent it from becoming another AI-dark-mode-with-one-blue-accent. When the underlying tech has no moat, visual identity is a free differentiation vector — clones will reach for default shadcn gradients or pastel neumorphism and reveal themselves instantly.

**Design tokens (see `base.html`):**

| Token | Value | Purpose |
|-------|-------|---------|
| `--bg` | `#0A0A0A` | Near-black canvas (one step up from absolute black so outlines don't vibrate) |
| `--surface` | `#0F0F12` | Card, input, container fill (one step up from `--bg`) |
| `--surface-2` | `#16171B` | Elevated / inline-code / table-header fill |
| `--text` | `#FFFFFF` | Pure white for headlines, wordmark, primary text |
| `--text-2` | `#E8EAED` | Off-white body copy (reduces eye strain on dark long-form) |
| `--muted` | `#9AA0A6` | Secondary copy, meta, placeholders |
| `--outline` | `rgba(255, 255, 255, 0.22)` | **Default card/input stroke — the single most important visual unit** |
| `--outline-strong` | `rgba(255, 255, 255, 0.45)` | Hover state, active nav, button emphasis |
| `--outline-hairline` | `rgba(255, 255, 255, 0.09)` | Internal separators, meta row rules, table row borders |
| `--blue` | `#4285F4` | Google blue — primary links, one hero period, selection color, explore eyebrow |
| `--red` | `#EA4335` | Google red — wordmark dot, one hero period, pillar 02 numeral, doc brand dot, code keywords |
| `--yellow` | `#FBBC04` | Google yellow — hero chip dot, pillar 03 numeral, "Pinned" badge fill, blockquote left edge |
| `--green` | `#34A853` | Google green — section eyebrow dot (landing), result-count dot (explore), code strings |
| `--radius` / `--radius-lg` / `--radius-xl` / `--radius-pill` | `20px` / `28px` / `32px` / `999px` | Rounded; nav cards use xl |

**There are no gradient tokens.** This is intentional. Every visual edge is a solid color line or a stroke; every fill is a solid color. If a surface needs more than one color, it uses adjacent regions, not blends.

**Shadows are near-absent.** The signature visual unit is the **outline**, not the drop shadow. Hover states brighten the outline from `--outline` (22% white) to `--outline-strong` (45% white) or full `--text`, plus a 1–3px `translateY`. No shadow bloom, no glow.

**Typography:**

| Role | Font | Weights | Use |
|------|------|---------|-----|
| Display & UI | Figtree | 400, 500, 600, 700, 800, 900 | Wordmark, headlines (800), card titles (700), buttons (600), body text |
| Mono | DM Mono | 400, 500 | Eyebrows, metadata timestamps, chip labels, code in body |
| Reading body | Newsreader (variable serif) | 400–600 + italic | Document viewer body only — 1.12rem / 1.75 line-height on dark, `--text-2` off-white color |

Figtree is the open-source Google-Sans analogue. Used throughout: body in 400/500, buttons in 600, card titles in 700, hero headlines in 800. Letter-spacing tightens negatively with size (body 0, H3 -0.02em, hero -0.045em) — tighter than default to match the oversized-display voice of the IO aesthetic.

**Component patterns:**

- **Wordmark** (`base.html`) — solid white "Markland" preceded by a small solid **Google red** dot. No gradient. Same wordmark appears in the doc viewer meta row for brand continuity.
- **Ghost pill (nav chip, secondary button, sort dropdown)** — transparent fill, 1–1.5px `--outline` or `--outline-strong` border, white text, pill radius. Hover: border goes to `--text`.
- **Inverted primary pill (primary CTA, search submit)** — solid white fill, black (`--bg`) text. One per page maximum. Reserved for the single highest-priority action.
- **Dark outlined card (pillars, featured grid, explore grid, nav cards, doc container)** — `--surface` fill, 1.5px `--outline` border, 28px radius (32px for the bigger nav cards). Hover: border to `--outline-strong` or `--text`, translateY(-3px).
- **Hero chip** — outlined pill with a solid **yellow** dot + small mono-typed version text. The yellow dot is the only color on the hero except for the period accents.
- **Period accents in headlines** — the ONLY color-on-text pattern. Landing hero: `writes` period in red, `reads` period in blue. Explore hero: `Public docs,` comma in red. This is the tiniest possible primary-color application — a single character — and it is the signature move.
- **Pillar numerals** — `01` / `02` / `03` rendered in `--blue` / `--red` / `--yellow`. The numerical labels ARE the color in each pillar. Headings and body stay white/muted.
- **Section eyebrow (landing)** — uppercase mono label preceded by a small solid **green** dot. Each page uses a different primary color on the eyebrow dot (landing: green, explore: blue), giving page-level color identity without filling anything.
- **Nav cards** (landing "Get started" section) — the reference-image pattern. Two-up grid, 32px radius, 1.5px outline, min-height 320px, padding 2.2rem. Large display headline + muted body at top, ghost-pill button at bottom-left. Hover outline brightens fully to white.
- **"Pinned" badge** — solid **yellow** pill with black text (inverted on the accent color). Positioned top-right of featured cards. No gradient, no border, no shadow.
- **Result count badge** (explore) — outlined pill with a small **green** leading dot, mono-typed. One of the few deliberate uses of pill-outline pattern outside buttons.
- **Empty states** — dashed 1.5px `--outline` border on `--surface` fill, 28px radius, Figtree 700 headline + muted Figtree body.
- **Doc-viewer blockquote** — dark `--surface-2` fill with hairline outline, 3px solid **yellow** left edge, italic serif body. One primary color per quote, as an edge accent.
- **Doc-viewer code** — `<pre>` pure black fill (`#000`) with 1.5px white outline, 20px radius. Pygments tokens rebound to the four Google primaries: keywords red, strings green, numbers/constants yellow, functions/names blue. Syntax highlighting itself becomes the primary-color showcase.

**Motion patterns (minimal, load-bearing):**
- Card / button hover: border-color transition (`--outline` → `--outline-strong` or `--text`), 0.18s ease, plus 1–3px `translateY(-)`. No shadow animation.
- Input focus: border transition from 22% to 100% white. No colored ring, no glow.
- Link hover in doc body: bottom border opacity 45% → 100%. 0.18s ease.
- **No scroll animations, no parallax, no gradient position loops, no keyframe animations.** Static confidence with tight hover feedback.

**Things to never do in this codebase:**
- **Gradients.** None. Not on text, not on backgrounds, not on strips, not on shadows. The one exception: potential future programmatic `<canvas>` illustrations that are genuinely multi-color wireframe art (deferred; see "What's Next" in the retrospective).
- Inter / Roboto / system-ui sans as primary display/body — use Figtree
- Soft blur shadows > 4px blur as a primary visual. The outline IS the visual; shadows are optional and subtle.
- Solid `#000` backgrounds — use `--bg` (`#0A0A0A`). Absolute black makes outlines visually shake.
- Pure grayscale palettes — without the discrete primaries the page will read as "another AI dark mode." The primaries are load-bearing.
- Filled colored accent strips on cards — if a card needs a color it goes on the numeral, the punctuation, or a badge, not on a colored strip.
- Multiple primary colors adjacent — spread them across the page. One primary per component. Never three in a row.
- Italic outside the doc viewer body

## Routes

| Route | Method | Purpose | New? |
|-------|--------|---------|------|
| `/` | GET | Landing page with marketing + featured/recent public docs | NEW |
| `/explore` | GET | Gallery of public docs with optional `?q=<query>` search | NEW |
| `/d/<share_token>` | GET | Existing doc viewer (unchanged) | existing |
| `/health` | GET | Existing status check (unchanged) | existing |

## Visibility Model

Every document has two new boolean flags stored in SQLite:

- `is_public` — `0` by default (unlisted, current behavior). When `1`, the doc appears in `/explore` and is eligible for the landing page.
- `is_featured` — `0` by default. When `1`, the doc is pinned to the top of the landing hero. Only meaningful when `is_public = 1` (a private featured doc is silently excluded from the landing).

**Landing content logic:** Pinned featured docs first (sorted by `updated_at DESC`), then filled with most recent public docs (also `updated_at DESC`), capped at 8 total.

**Explore content logic:** All public docs sorted by `updated_at DESC`. Search query matches against title and content via SQL `LIKE %query%`. Limited to 50 results; if truncated, a "Showing 50 of N" badge appears.

## Data Model Changes

### Schema Migration (idempotent, runs on every `init_db`)

```sql
ALTER TABLE documents ADD COLUMN is_public INTEGER NOT NULL DEFAULT 0;
ALTER TABLE documents ADD COLUMN is_featured INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_public ON documents(is_public);
CREATE INDEX IF NOT EXISTS idx_featured ON documents(is_featured);
```

Migration runs inside `init_db` using a helper `_add_column_if_missing(conn, table, column, type_and_default)` that checks `PRAGMA table_info(documents)` before attempting `ALTER TABLE ADD COLUMN`. Existing docs auto-migrate to `(is_public=0, is_featured=0)` — preserves current unlisted-by-default behavior for all pre-existing content.

### Document Model

```python
@dataclass
class Document:
    id: str
    title: str
    content: str
    share_token: str
    created_at: str
    updated_at: str
    is_public: bool = False
    is_featured: bool = False
```

`_row_to_doc` in `db.py` maps the two new columns to `bool(row[N])` (SQLite stores as INTEGER 0/1).

### New DB Functions (in `db.py`)

```python
def list_public_documents(conn, query: str | None = None, limit: int = 50) -> list[Document]
def list_featured_and_recent_public(conn, limit: int = 8) -> list[Document]
def set_visibility(conn, doc_id: str, is_public: bool) -> Document | None
def set_featured(conn, doc_id: str, is_featured: bool) -> Document | None
```

`insert_document` gains an optional `is_public: bool = False` parameter. Default preserves current behavior.

## MCP Tool Changes

### Existing tool — modified

```
markland_publish(content: str, title: str | None = None, public: bool = False) -> dict
```

Adds the `public` parameter. Default `False` keeps current behavior for existing agent code. Returns dict unchanged: `{id, title, share_url}`.

### New tools

```
markland_set_visibility(doc_id: str, public: bool) -> dict
```

Promotes a doc to public or demotes back to unlisted. Returns `{id, is_public, share_url}` or `{error}`.

```
markland_feature(doc_id: str, featured: bool = True) -> dict
```

Pins or unpins a doc from the landing hero. Returns `{id, is_featured, is_public}` or `{error}`. Does not auto-promote to public — if `is_public = 0`, the doc simply won't appear on the landing; the error-free response tells the agent it's been flagged but won't render.

## Pages

All pages share the `--bg` near-black canvas. No ambient gradient mesh, no polka-dot grain — the background is uniformly flat `#0A0A0A`. Differentiation between pages is through layout and which primary color appears where.

### Landing (`/`)

Five vertical sections:

1. **Top bar** — Sticky, translucent `rgba(10,10,10,0.7)` with `backdrop-filter: blur(14px)`. Wordmark: red dot + white "Markland" in Figtree 700. Nav: two ghost pills (`Explore`, `Docs`); `Explore` gets the active `--outline-strong` border when on that page.
2. **Hero** (centered, no container) — Hero chip: outlined pill with a solid yellow dot + mono-typed `Agent-native publishing · v0.1`. Headline: "Your agent writes." + line break + "The world reads." in Figtree 800 at `clamp(2.6rem, 7vw, 5.2rem)`, letter-spacing `-0.045em`, line-height 1. The **period after "writes" is red; the period after "reads" is blue** — the only color on the headline. Muted Figtree lede below. Two CTAs: primary is a **solid-white pill with black text** ("Copy MCP config"); secondary is a **ghost outline pill** ("Browse docs"). Mono hint below.
3. **Why Markland** — Section eyebrow: mono uppercase with a leading green dot. Large Figtree 700 section title. Three-column pillar grid: dark outlined cards, numbered `01` / `02` / `03` in **blue / red / yellow** respectively, Figtree 700 heading, muted body. Hover: outline brightens to `--outline-strong`, 3px lift.
4. **Get started** (NEW — modeled on the reference io.google/2024 "Join a community group" / "Continue learning" tile pattern) — Section eyebrow + section title. Two-up outlined nav cards, `--radius-xl` 32px radius, min-height 320px. Card 1: "Browse public docs" → `/explore`. Card 2: "Publish from your agent" → copies the MCP config. Each card contains a short muted paragraph and a ghost-pill `Explore →` / `Copy config →` button at the bottom. Hover: outline goes full-white, 3px lift.
5. **Published from agents** — Section eyebrow + title. Masonry grid (`column-count: 3`) of up to 8 dark outlined cards. Featured docs show a solid-**yellow** pill "Pinned" badge at top-right. Cards are uniform — no per-card color differentiation. Hover: outline brightens, 3px lift.
6. **Footer** — Muted text row with a single underlined link. Hairline top border.

Empty state (zero public docs): dashed-outline card, Figtree 700 "Nothing yet." headline, muted body.

### Explore (`/explore`)

1. **Top bar** — same as landing; `Explore` nav pill in the active state with `--outline-strong` border.
2. **Explore hero** — Eyebrow: mono uppercase `Explore` with a leading blue dot. Headline: Figtree 800 "Public docs, published from agents." — the **comma is red** (same period-as-accent pattern as the landing, applied to a comma this time). Muted sub-lede.
3. **Search + sort row** — Pill-shaped input with dark surface fill and `--outline` border; on `:focus` the border goes full-white. Pill-shaped **solid-white "Search" button** with black text (the primary action on the page, mirrors the landing's "Copy MCP config" pattern). Disabled outlined "Recent" sort dropdown on the right.
4. **Result count** — Outlined pill badge with a leading **green** dot, mono-typed `Showing X of Y docs`. Only renders when the result set is truncated.
5. **Results grid** — CSS masonry, 3 → 2 → 1 responsive. Uniform dark outlined cards — no top strips, no per-card color. The visual rhythm comes from titles + excerpts + hover state.
6. **Empty state** — dashed outlined card. Copy differs for "no docs" vs "no search match".

### Doc viewer (`/d/<token>`) — self-contained

Self-contained HTML file (does not extend `base.html`). Shares the dark-outlined-primary identity but tunes typography for 5-minute reading:

- Same `--bg` near-black canvas.
- Content in a dark `--surface` container, 1.5px `--outline` border, 28px radius, no gradient strip.
- Body copy in **Newsreader** variable serif at 1.12rem / 1.75 line-height, color `--text-2` (`#E8EAED` off-white) — deliberately not pure white for long-form reading comfort.
- Headings in Figtree 700/800 pure white with tight negative letter-spacing — visual continuity with the landing.
- Meta row: mono uppercase, solid **red** brand dot + "Markland" link, mono date on the right. Hairline separator underneath.
- Inline code: DM Mono in `--surface-2` with hairline border, 6px radius, white text.
- Fenced blocks: **pure black** (`#000`) fill, 1.5px `--outline` border, 20px radius. Pygments tokens rebound to Google primaries: `.k` red, `.s` green, `.mi/.mf` yellow, `.nf/.nx` blue, `.c` muted italic. The code block is where the most primary color lives in the doc viewer.
- Tables: outlined 20px-radius container, `--surface-2` header row, hairline row separators.
- Blockquotes: italic serif body in `--surface-2` fill, hairline outline, **3px solid yellow left edge**. One primary-color accent per quote.
- Links: Google blue text with a 1.5px 45%-opacity blue underline; on hover underline opacity goes to 100%.

## Template Structure

```
src/markland/web/templates/
├── base.html             # NEW — header, nav, design tokens, typography imports
├── landing.html          # NEW — extends base
├── explore.html          # NEW — extends base
└── document.html         # EXISTING — themed, remains self-contained
```

**`base.html`** provides:
- `{% block title %}` — page `<title>`
- `{% block body_class %}` — additional body class (reserved; currently unused)
- `{% block head_extra %}` — per-page CSS appended into the shared `<style>` block
- `{% block content %}` — main content area
- `{% block nav_explore %}` — set to `"active"` by `explore.html` to highlight the nav link
- Google Fonts `<link>` for Figtree + DM Mono
- All design tokens declared on `:root` (see Visual Direction) — colors, outlines, radii, font stacks
- Sticky translucent dark header with `backdrop-filter: blur(14px)`; uniform `--bg` body
- `::selection` color tuned to Google blue for consistency
- No decorative helpers (no sparkle class, no blob divs, no gradient vars) — removed in the dark-outlined pass

All CSS is inlined per template. The single JavaScript dependency is the `copyConfig()` function on the landing page (Clipboard API for the MCP config CTAs — both the hero button and the second nav card trigger it). Search form is a plain HTML `<form method="get" action="/explore">` — reloads the page with `?q=`.

**`document.html` fonts:** Loads its own `<link>` to Google Fonts for `Figtree`, `DM Mono`, and `Newsreader` — the serif that's unique to the reading surface.

## Rendering Details

### Excerpt generation

Pure Python, no markdown parsing. Strip common markdown syntax via regex, then take first 140 chars + ellipsis:

```python
def make_excerpt(content: str, length: int = 140) -> str:
    # Remove code fences first (greedy multiline)
    cleaned = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
    # Strip headings, list markers, link syntax, bold/italic, inline code
    cleaned = re.sub(r"^#+\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"[*_`]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:length] + ("…" if len(cleaned) > length else "")
```

Lives in `src/markland/web/renderer.py` as a new function.

### Date formatting

`{{ doc.updated_at[:10] }}` — ISO date prefix (`YYYY-MM-DD`) as shown in existing `document.html`. Same pattern, no new logic.

## FastAPI Route Handlers (in `src/markland/web/app.py`)

```python
@app.get("/", response_class=HTMLResponse)
def landing():
    docs = list_featured_and_recent_public(db_conn, limit=8)
    return HTMLResponse(landing_template.render(docs=docs))

@app.get("/explore", response_class=HTMLResponse)
def explore(q: str | None = None):
    query = (q or "").strip() or None
    docs = list_public_documents(db_conn, query=query, limit=50)
    # For the "Showing 50 of N" badge
    total = len(list_public_documents(db_conn, query=query, limit=10_000))
    return HTMLResponse(explore_template.render(docs=docs, query=query, total=total))
```

Replaces the current minimalist `GET /` handler. Three Jinja `Template` objects loaded at app-create time: landing, explore, document (existing).

## Error Handling

- **Empty public doc set on landing** → Featured section renders with empty-state placeholder.
- **Empty `/explore`** → empty-state copy differs for "no docs" vs "no search match".
- **Invalid search query characters** → parameterized SQL protects from injection; whitespace stripped; overly long queries (>200 chars) truncated silently.
- **Featured a non-public doc** → `set_featured` succeeds (flag flips), but the doc is excluded from landing queries via `WHERE is_public = 1`. Agent gets confirmation from the tool response. No surprise behavior.

## Testing Plan

**New tests (~12 total):**

| Test file | New tests |
|-----------|-----------|
| `tests/test_db.py` | `test_migration_adds_columns`, `test_list_public_filters_unlisted`, `test_set_visibility`, `test_set_featured`, `test_list_featured_and_recent_ordering` |
| `tests/test_documents.py` | `test_publish_public_flag`, `test_set_visibility_tool`, `test_feature_tool` |
| `tests/test_web.py` | `test_landing_renders_with_no_public_docs`, `test_landing_shows_featured_first`, `test_explore_renders_public_docs`, `test_explore_search_filters`, `test_explore_hides_unlisted` |

**Smoke test additions to `scripts/smoke_test.py`:**
- After existing flow: publish a second doc with `public=True`, call `markland_feature` on it, GET `/`, assert title appears, GET `/explore`, assert title appears, GET `/explore?q=<partial-title>`, assert it matches.

**Total suite after changes:** ~53 tests.

## File Changes Summary

| File | Change |
|------|--------|
| `src/markland/models.py` | Add `is_public`, `is_featured` fields to `Document` |
| `src/markland/db.py` | Add migration helper; add 4 new query functions; update `_row_to_doc`; update `insert_document` signature |
| `src/markland/tools/documents.py` | Update `publish_doc`; add `set_visibility_doc`, `feature_doc` |
| `src/markland/server.py` | Add `public` param to `markland_publish`; add `markland_set_visibility`, `markland_feature` tools |
| `src/markland/web/renderer.py` | Add `make_excerpt` function |
| `src/markland/web/app.py` | Add `/` and `/explore` routes with template rendering |
| `src/markland/web/templates/base.html` | NEW — shared header + layout |
| `src/markland/web/templates/landing.html` | NEW — marketing landing |
| `src/markland/web/templates/explore.html` | NEW — gallery |
| `tests/test_db.py` | ~5 new tests (incl. migration on pre-existing schema) |
| `tests/test_documents.py` | ~3 new tests |
| `tests/test_web.py` | ~5 new tests |
| `scripts/smoke_test.py` | Add public/feature/landing/explore assertions |

## Out of Scope (Deferred)

- Authentication, user accounts, multi-tenant
- Author bylines / attribution
- Tags, categories, multi-sort
- Pagination beyond 50 results
- Rich previews (images, embedded code highlighting on cards)
- Paywall, marketplace, payments
- Comment system
- RSS / Atom feed for public docs
- OpenGraph / Twitter card meta tags for shared links
- VPS deployment

These stay on the business plan roadmap for future validation phases.
