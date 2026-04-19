# Markland Landing Page — Waitlist & Positioning Refresh

**Date:** 2026-04-18
**Status:** Approved, pending plan
**Author:** Davey Hiles
**Related:** `docs/specs/2026-04-17-frontend-design.md` (parent design system — unchanged), `docs/ROADMAP.md` (pre-launch priorities)

## Overview

Evolve the shipped landing page (`/`) to capture pre-launch demand and sharpen positioning. The page currently has no email capture and an abstract tagline. This spec adds a waitlist mechanism (email → SQLite), swaps the hero to a benefit-led tagline, and inserts two new content sections (Before/After framing + How-it-works MCP snippet) between the existing pillars and gallery.

The entire existing **Dark + Outlined + Primary** design system is inherited verbatim from `2026-04-17-frontend-design.md`. Every new component reuses tokens and patterns already declared in `base.html`. No new design primitives are introduced.

Driven by competitive analysis vs markshare.to: they're ahead on marketing surface, Markland is ahead on architecture. The gap to close is marketing, not product.

## Goals

- Capture pre-launch email signups from landing visitors.
- Replace the abstract tagline ("Your agent writes. The world reads.") with a concrete benefit-led tagline ("Your agent publishes. You share the link.").
- Add proof elements that explain the moment of magic: the MCP call → published link.
- Frame the pain (copy-paste from agent to editor) and the fix (one MCP call) using typographic-only before/after — no screenshots, no animation.
- Surface a second conversion point below the fold for readers who scroll past the hero.
- Avoid SaaS-slop waitlist copy. Use "Get started" and "Get early access" framing throughout the UI.

## Non-Goals

- No new visual identity, tokens, or design primitives.
- No email automation, drip sequences, or transactional sending. Emails are stored; outbound comms are handled manually from a CSV export at launch.
- No account system, auth, or per-email state beyond presence in the `waitlist` table.
- No JavaScript framework. Form submission is a plain HTML POST.
- No rewrite of the existing "Why Markland" pillars or the `/explore` page.
- No changes to MCP tools, the document model, or the doc viewer.
- No new Python dependencies.

## Context: Inherited Design System

Per `2026-04-17-frontend-design.md`:

- Canvas: `--bg` `#0A0A0A` near-black.
- Cards: `--surface` fill, 1.5px `--outline` stroke, 28px radius (or 32px `--radius-xl` for the two-up nav-card variant).
- Typography: Figtree (display/body), DM Mono (eyebrows/mono hints), Newsreader (doc viewer body only — not used on landing).
- Accents: Google primaries (`--red` `#EA4335`, `--yellow` `#FBBC04`, `--blue` `#4285F4`, `--green` `#34A853`) used as discrete single-point accents — a dot, a character of punctuation, a numeral. Never on fills, strips, or gradients.
- Primary CTA: one per page — solid white pill with black text (`--bg`).
- Secondary CTAs: ghost pills — transparent fill, 1.5px `--outline` stroke.
- Period-accent headlines: the color-on-text signature, one character per period.
- No gradients, no shadows as primary visual, no keyframe animations.

All of the above is load-bearing and unchanged by this spec.

## Page Structure (New Order)

```
1. Top bar                         (existing, unchanged)
2. Hero                            (MODIFIED — new tagline + email form)
3. Why Markland (pillars)          (existing, unchanged)
4. Before / After                  (NEW)
5. How it works (MCP snippet)      (NEW)
6. Get early access (CTA repeat)   (NEW)
7. Published from agents (gallery) (MODIFIED — cap 8 → 4)
8. Footer                          (existing, unchanged)
```

Narrative flow: *what it does → why it matters → the old way sucks → here's the call → sign up → social proof*.

## Sections

### 2. Hero (MODIFIED)

**Content:**

- Chip: existing — yellow dot + mono `Agent-native publishing · v0.1`. Unchanged.
- Headline: `Your agent publishes<red-period>` / `You share the link<blue-period>` — Figtree 800, `clamp(2.6rem, 7vw, 5.2rem)`, tracking `-0.045em`, line-height 1. The red and blue periods are the only color on the headline.
- Lede: muted Figtree body, ≤2 lines, ~36ch max: "Markdown from your agent, hosted and shareable in one MCP call. No copy-paste, no editor."
- **Email form** (replaces the current `Copy MCP config` CTA): a single row with a pill-shaped email input and a solid-white pill submit button labeled **Get started**.
  - Input: `type="email"`, `required`, pill radius, `--surface` fill, 1.5px `--outline` stroke, mono placeholder `you@company.com` in `--muted`. Focus transitions border to `--text` (full white). Input `name="email"`.
  - Hidden field: `<input type="hidden" name="source" value="hero">`.
  - Submit: the single inverted-primary pill — solid white fill, black text. The page's one primary CTA.
- Secondary link below the form: muted `See a sample doc →`, points to `/explore` (or a curated featured doc if one exists).
- Hint: DM Mono, muted — `Pre-launch · we'll email when it's ready`.

**Signup-state chips** (above the form, inside the hero, render only when `?signup=` is present):

| Query value | Chip | Copy |
|---|---|---|
| `ok` | outlined pill with leading `--green` dot, mono text | `You're on the list. We'll be in touch.` |
| `invalid` | outlined pill with leading `--red` dot, mono text | `That doesn't look like a valid email.` |

Both chips reuse the existing outlined-pill + leading-dot component. No new CSS.

### 3. Why Markland (UNCHANGED)

Existing three-pillar section stays as-is. Deferred to a later positioning pass; the roadmap's shared-memory framing (`humans and agents as equal editors`) is not part of this spec.

### 4. Before / After (NEW)

**Eyebrow:** leading `--blue` dot, DM Mono uppercase — `THE OLD WAY VS. MARKLAND`.
**Section title:** Figtree 700 — `Stop copy-pasting your agent's work.`

**Two-up nav-card pattern** (reusing the existing "Get started" nav-card component — 32px radius, 1.5px outline, min-height 320px, 2.2rem padding, ghost-pill at bottom-left).

| Card | Numeral | Body | Meta | CTA |
|---|---|---|---|---|
| **Before** | `01` in `--red` | Your agent writes markdown. / You copy it out. / You open Notion or Docs. / You paste. / You fix the formatting. / You share the link. | `~2 min of manual work` (DM Mono muted) | none |
| **After** | `02` in `--green` | Your agent writes markdown. / Your agent publishes it. / You get a shareable link. | `~3 seconds` (DM Mono muted) | ghost pill: `See the MCP call →`, anchor `#how-it-works` |

The line-count asymmetry (6 vs 3) is the visual argument — no images or screenshots.

Hover on each card: outline brightens from `--outline` to `--text`, 3px translateY. Identical to the existing nav-card interaction.

### 5. How it works (MCP snippet) (NEW)

**Anchor:** `id="how-it-works"` (target of the Before/After After-card CTA).
**Eyebrow:** leading `--green` dot, DM Mono uppercase — `HOW IT WORKS`.
**Section title:** Figtree 700 — `One MCP call. One link.`

**Split code/result card** — single dark outlined card, 28px radius, 1.5px `--outline` stroke, internally divided into two columns via a hairline vertical separator (`--outline-hairline`).

- **Left column** — pure-black `#000` fill (matching the existing doc-viewer code-block styling), 1.5px inner `--outline`, 20px radius. Two code blocks separated by a muted mono comment:
  ```
  # In your MCP client config:
  {
    "markland": {
      "command": "uvx",
      "args": ["--with", "mcp[cli]", "mcp", "run", "markland"]
    }
  }

  # Then your agent just:
  markland_publish(content)
  ```
  Pygments tokens rebound to Google primaries exactly as the doc-viewer code blocks already do: keywords `--red`, strings `--green`, numbers `--yellow`, names/functions `--blue`, comments muted italic. No new Pygments configuration — the existing token rebinding applies.
- **Right column** — `--surface` fill (no inner outline). The "result" state:
  - A small solid `--green` dot + Figtree 700 `Published`. (Dot, not a check glyph — no glyphs are used elsewhere in the design system.)
  - A muted Figtree line: `Your architecture notes · 2,340 words · 3m read`.
  - A pill-shaped mono link row: `mkl.to/a7f2-x` with a ghost-pill `Copy link →` to the right. Static — this is an illustrative mock, not a live action; the button is visual only (`type="button"`, no handler in v1).

Responsive: stacks vertically below ~720px (code above, result below) with the hairline separator becoming horizontal.

### 6. Get early access (CTA repeat) (NEW)

Centered block, no card container — whitespace is the framing.

- **Eyebrow:** leading `--red` dot, DM Mono uppercase — `GET EARLY ACCESS`.
- **Section title:** Figtree 700 — `Be the first to publish.`
- **Subtext:** muted Figtree, max ~50ch: `We'll email you when hosted Markland is live, with install instructions and your early access link.`
- **Email form:** identical to the hero form — same input, same solid-white `Get started` pill, same hidden `source` field (value `cta-section`), same `POST /api/waitlist` target.
- **Hint below form:** DM Mono muted — `No spam · we'll email when it's ready`.

The page-level color rotation continues: hero headline uses red+blue periods, Before/After eyebrow is blue, How-it-works eyebrow is green, this CTA eyebrow is red. Each section has a distinct primary accent without ever repeating the same eyebrow color adjacently.

### 7. Published from agents (MODIFIED)

Existing section. Only change:

- `list_featured_and_recent_public(db_conn, limit=8)` → `limit=4`.

Empty-state component, Pinned badge, masonry breakpoints — all unchanged.

### 8. Footer (UNCHANGED)

## Data Model

### Schema Addition

```sql
CREATE TABLE IF NOT EXISTS waitlist (
    email      TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    source     TEXT
);
```

- `email` is the primary key — natural dedup, no surrogate id.
- `created_at` stored as ISO-8601 string, same convention as `documents.created_at`.
- `source` nullable, string literals `'hero'` or `'cta-section'` (or `null` for API-direct submissions).

Runs inside the existing `init_db` idempotent migration block — `CREATE TABLE IF NOT EXISTS` means re-runs are safe and no version tracking is needed.

### New DB Function (in `db.py`)

```python
def add_waitlist_email(conn, email: str, source: str | None = None) -> bool:
    """
    Insert email into waitlist. Returns True if inserted, False if already present.
    Uses INSERT OR IGNORE so duplicate submits are idempotent.
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO waitlist (email, created_at, source) VALUES (?, ?, ?)",
        (email, datetime.utcnow().isoformat(), source),
    )
    conn.commit()
    return cur.rowcount > 0
```

No read/list function is in scope. Viewing the list pre-launch is done via a one-off SQL query or CSV export.

## Route: POST /api/waitlist

```python
import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def _valid_email(email: str) -> bool:
    return 3 <= len(email) <= 254 and bool(_EMAIL_RE.match(email))

@app.post("/api/waitlist")
def join_waitlist(
    email: str = Form(...),
    source: str | None = Form(None),
):
    email = email.strip().lower()
    if not _valid_email(email):
        return RedirectResponse("/?signup=invalid", status_code=303)
    add_waitlist_email(db_conn, email, source)
    return RedirectResponse("/?signup=ok", status_code=303)
```

- Status 303 so the redirected GET is idempotent and the browser back button doesn't re-submit.
- Duplicate email → `add_waitlist_email` returns False, handler still redirects to `signup=ok`. User-facing behavior is identical; no leak of "this email is already on the list."
- Validation is deliberately loose — the purpose is to reject obvious junk (missing @, no dot) without rejecting unusual but valid addresses.
- No rate limiting in this spec. If abuse becomes a problem post-launch, add a simple per-IP in-memory throttle or front the route with Cloudflare.

## Landing Route Update

```python
@app.get("/", response_class=HTMLResponse)
def landing(signup: str | None = None):
    docs = list_featured_and_recent_public(db_conn, limit=4)
    signup_state = signup if signup in ("ok", "invalid") else None
    return HTMLResponse(landing_template.render(docs=docs, signup=signup_state))
```

- Whitelisted `signup` values prevent template rendering arbitrary strings from the query string.
- The `limit=4` change replaces `limit=8`.

## Template Changes

**`landing.html` edits:**

1. **Hero section:** replace the `cta-row` block (currently a single `Copy MCP config` button) with the email form component + secondary link + signup-state chip block.
2. **Remove `copyConfig()` JavaScript** from the hero — still used by the "Publish from your agent" nav card in the Get started section, so the function stays in the file but the hero no longer calls it.
3. **Insert two new sections** between the existing "Why Markland" pillar section and the existing "Published from agents" gallery — Before/After (4) and How it works (5).
4. **Insert the CTA repeat section** between "How it works" and the gallery.
5. **Masonry cap:** no template change needed — the Python handler passes a list of length ≤4 instead of ≤8, and the template iterates the list as-is.

**`base.html`:** no changes. All new components are composed of tokens and patterns already declared.

**`document.html`, `explore.html`:** no changes.

**Inline CSS additions in `landing.html`:** only the two new section layouts (Before/After two-up, How-it-works split card). No new color variables, no new font imports, no new global rules.

## File Changes Summary

| File | Change |
|---|---|
| `src/markland/db.py` | Add `waitlist` table to `init_db`; add `add_waitlist_email()` |
| `src/markland/web/app.py` | Add `POST /api/waitlist` route + `_valid_email` helper; update `GET /` to accept `signup` param and pass `limit=4` |
| `src/markland/web/templates/landing.html` | Hero form swap; Before/After section; How-it-works section; Get-early-access CTA section; signup-state chip block |
| `tests/test_db.py` | ~2 new tests: `test_add_waitlist_email_inserts`, `test_add_waitlist_email_is_idempotent_on_duplicate` |
| `tests/test_web.py` | ~4 new tests: `test_waitlist_post_happy_path`, `test_waitlist_post_duplicate_returns_ok`, `test_waitlist_post_invalid_email`, `test_landing_renders_signup_chip` |
| `scripts/smoke_test.py` | POST to `/api/waitlist` with a test email; GET `/` and assert the signup chip renders |

No new files. No new dependencies.

## Testing Plan

**Unit — `tests/test_db.py`:**

- `test_add_waitlist_email_inserts` — call with a fresh email, assert returns True, assert row exists.
- `test_add_waitlist_email_is_idempotent_on_duplicate` — call twice with the same email, assert second call returns False, assert only one row.

**Integration — `tests/test_web.py`:**

- `test_waitlist_post_happy_path` — POST valid email, assert 303 redirect to `/?signup=ok`, assert row inserted.
- `test_waitlist_post_duplicate_returns_ok` — POST same email twice, assert both redirect to `signup=ok`.
- `test_waitlist_post_invalid_email` — POST garbage, assert 303 redirect to `/?signup=invalid`, assert no row inserted.
- `test_landing_renders_signup_chip` — GET `/?signup=ok`, assert chip copy present; GET `/?signup=xyz`, assert chip absent (whitelist).

**Smoke — `scripts/smoke_test.py`:**

- After the existing publish/gallery flow, POST `test+{timestamp}@example.com` to `/api/waitlist`, assert redirect, GET `/?signup=ok`, assert chip renders, assert the hero form still shows.

## Copy Decisions (Final)

| Location | Copy |
|---|---|
| Hero chip | `Agent-native publishing · v0.1` (existing) |
| Hero headline | `Your agent publishes.` / `You share the link.` |
| Hero lede | `Markdown from your agent, hosted and shareable in one MCP call. No copy-paste, no editor.` |
| Hero submit button | `Get started` |
| Hero secondary link | `See a sample doc →` |
| Hero hint | `Pre-launch · we'll email when it's ready` |
| Signup ok chip | `You're on the list. We'll be in touch.` |
| Signup invalid chip | `That doesn't look like a valid email.` |
| Before/After eyebrow | `THE OLD WAY VS. MARKLAND` |
| Before/After title | `Stop copy-pasting your agent's work.` |
| Before card numeral | `01` (`--red`) |
| Before card body | `Your agent writes markdown.` / `You copy it out.` / `You open Notion or Docs.` / `You paste.` / `You fix the formatting.` / `You share the link.` |
| Before card meta | `~2 min of manual work` |
| After card numeral | `02` (`--green`) |
| After card body | `Your agent writes markdown.` / `Your agent publishes it.` / `You get a shareable link.` |
| After card meta | `~3 seconds` |
| After card CTA | `See the MCP call →` → `#how-it-works` |
| How-it-works eyebrow | `HOW IT WORKS` |
| How-it-works title | `One MCP call. One link.` |
| How-it-works result headline | `Published` |
| How-it-works result meta | `Your architecture notes · 2,340 words · 3m read` |
| How-it-works result CTA | `Copy link →` (illustrative; static) |
| CTA repeat eyebrow | `GET EARLY ACCESS` |
| CTA repeat title | `Be the first to publish.` |
| CTA repeat subtext | `We'll email you when hosted Markland is live, with install instructions and your early access link.` |
| CTA repeat submit | `Get started` |
| CTA repeat hint | `No spam · we'll email when it's ready` |

## Out of Scope (Deferred)

- Rewriting the "Why Markland" pillars around the shared-memory / human-agent framing.
- Power-user track expansion (dedicated MCP power-user section with install snippet, GitHub link, advanced tools list). The How-it-works section serves this audience adequately for v1.
- `/alternatives` SEO page and `/vs/markshare` comparison page — separate brainstorm (Roadmap item 3).
- Email automation, drip sequences, welcome emails, transactional sending.
- Analytics integration (Plausible, Fathom) on form submission.
- Rate limiting or abuse protection on the waitlist route.
- OpenGraph / Twitter-card meta tag tuning for the landing page.
- An admin view for browsing the waitlist in-app.
- Internationalization or alt-language variants.
