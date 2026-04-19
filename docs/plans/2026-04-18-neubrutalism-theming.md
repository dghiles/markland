# Neubrutalism Theming Pass (Superseded)

**Date:** 2026-04-18 AM
**Status:** **Superseded** — replaced later the same day by IO24 pivot. See `2026-04-18-io24-theming.md`.
**Context:** First theming pass on the MVP. Committed to a raw, loud, brutalist aesthetic. Later the same day, the user pointed to https://io.google/2024/ as the target aesthetic, triggering a full re-theme to soft gradients, Figtree, pills, and rounded cards. This document is retained for historical reference; current visual authority is the IO24 spec.

## Why

The pre-theme pages used generic system-UI fonts, subtle gray borders, and neutral gray/blue palette. Functional but indistinguishable from any other AI SaaS MVP. Given Markland's technical moat is thin (MCP + SQLite + markdown is not hard to replicate), visual identity is a free differentiation vector where clones will reveal themselves as clones.

Commitment to a loud, specific aesthetic is also a filter: the agent-first builder audience respects tools that look hand-built. Polish-theater alienates them; raw confidence attracts them.

## Aesthetic Choice

**Neubrutalism.** Cream paper base with polka-dot grain, high-contrast primary accents, hard 2.5-3px black borders, solid offset drop shadows (no blur), chunky display typography in uppercase, JetBrains Mono for body. The full palette, tokens, and component patterns are documented in the spec:

- See `docs/specs/2026-04-17-frontend-design.md` → "Visual Direction"

## Files Modified

| File | Change |
|------|--------|
| `src/markland/web/templates/base.html` | Full rewrite: design tokens, Google Fonts imports, header/footer theming, polka-dot body background |
| `src/markland/web/templates/landing.html` | Full rewrite: neubrutalist hero with blobs and highlighted lines, colored pillar cards, themed featured grid |
| `src/markland/web/templates/explore.html` | Full rewrite: themed search row, multi-color card cycling, pill result badge |
| `src/markland/web/templates/document.html` | Rewritten styling: Newsreader serif body, Archivo Black headings, paper card on dotted background, yellow blockquotes, dark code blocks with shadow |

No changes to Python code, routes, data model, or tests. Only templates.

## Design Decisions Made During the Pass

### 1. Unified cream base — no dark/light split

The original spec called for a dark-theme landing and light-theme explore. This was rejected in favor of a single cream (`#FFF8E7`) base everywhere. Reasons:

- Splitting themes halved the aesthetic commitment. Neubrutalism is a confidence game — flinching between dark and light undermines the attitude.
- The subtle polka-dot grain overlay ties every page together visually. A dark landing would have needed its own texture system.
- High-saturation accents (coral, electric blue, yellow, mint) pop harder against cream than against black.

The document viewer keeps the same cream base but hosts content inside a white "paper" card for reading contrast.

### 2. Two fonts for the site, three for the doc viewer

- Site-wide: **Archivo Black** (display) + **JetBrains Mono** (body/UI).
- Doc viewer adds: **Newsreader** (variable serif) for body copy.

Optimizing for 5-minute reading is a different problem than optimizing for landing-page impact. The serif is the tell: when the user lands on a doc, the change in body typography signals "read mode" while the rest of the visual identity (cream base, black borders, Archivo Black headings, shadow-offset container) keeps brand continuity.

### 3. Hero headline structure

Original draft wrapped just the words "writes." and "reads." in highlighted spans. This broke the `"Your agent writes" in response.text` test because the text was split across `<span>` tags.

Fix: wrap the whole line in a `<span class="line">`, highlight the entire line rather than individual words. Yields "Your agent writes." and "The world reads." as contiguous highlighted blocks — arguably more brutalist anyway, and the test passes.

### 4. Explore card color cycling

Cards in the explore grid rotate through 6 background colors via `:nth-child(6n+…)`:

```
1: white       2: cream-yellow   3: pale blue
4: white       5: pale green     6: pale pink
```

Makes the masonry read as a sticker collection rather than a data table. Preserves hierarchy (title, excerpt, date) but the color variance adds life without needing imagery.

### 5. Press-down micro-interaction

Every interactive element (nav chip, CTA button, search submit, card) uses the same hover-up / active-press-down transform:

```css
:hover   { transform: translate(-2px, -2px); box-shadow: 7px 7px 0 0 var(--border); }
:active  { transform: translate(3px, 3px);  box-shadow: 0 0 0 0 var(--border); }
```

Single motion primitive across the site. No scroll animations, no loops, no parallax. The interactivity is load-bearing — users immediately feel the brutalist tactility.

### 6. Decorative hero blobs

Yellow circle (top-right) + rotated mint square (bottom-left), absolutely positioned with `overflow: hidden` on the hero card so they appear to peek from behind. Not functional; purely atmospheric. On mobile (< 560px) they're hidden to keep the hero compact.

## Test Impact

- 0 new tests added (theme changes, no behavior changes)
- 1 test temporarily broken during iteration (`test_landing_renders_empty` — fixed by restructuring hero headline HTML to keep the substring "Your agent writes" contiguous)
- Final state: all 68 tests passing

## What's Next (If Pursued Further)

- **Type weight pairings:** current Archivo Black is a single weight (900). A paired condensed or variable display font could add hierarchy depth to the document viewer headings.
- **Custom cursor** for the landing page — classic neubrutalist flourish, low cost.
- **SVG decorations** — hand-drawn arrows, stars, exclamation marks as accent elements. Currently using CSS-only shapes; SVG would give more personality.
- **"Pinned" tape variants** — right now every pinned badge is the same coral. Could cycle through coral/yellow/blue/mint to vary the sticker collection feel.
- **Doc viewer "reading mode" toggle** — button to switch Newsreader serif to JetBrains Mono for users who prefer monospace. Low priority.

None of these are required. The current pass delivers a distinctive, shippable aesthetic.

## Not In Scope

- Design system abstraction (tokens as a separate JSON/JS module)
- Component library extraction
- Multi-theme / theme-switcher
- Dark mode
- Accessibility audit (contrast ratios are good-by-eye but not measured; the dark `pre` blocks especially need verification before a real launch)
