# Dark + Outlined + Primary — Theming Pass

**Date:** 2026-04-18 PM
**Status:** Shipped — current visual authority
**Reference:** https://io.google/2024/ — specifically the dark two-up outlined-tile pattern ("Join a community group" / "Continue learning")
**Supersedes:** `2026-04-18-io24-theming.md` (gradient pass)

## Why the Pivot

A design review compared the gradient-IO24 implementation against the actual io.google/2024 page and surfaced a real mismatch. The real IO page is:

- **Dark** (near-black canvas), not warm off-white
- **Exhibition/stage-set in energy**, not editorial
- **Illustration-led** with wireframe + primary-color 3D graphics
- **Primary colors as discrete solid fills**, not gradient stops
- **Outlined tiles**, defined by thin white strokes rather than soft shadows

The gradient IO24 pass I shipped earlier that day was "indie SaaS with gradient accents" — pleasant, but the wrong tribe. User feedback:

- "use of primary colors is good — we don't need as MANY of the graphics"
- "i like the contrast of the white outlines on black"
- "both modern and cool but colorful"
- "we should avoid the AI monotone slop, no gradients"
- "don't worry about the wireframe graphics yet"
- "these vertical boxes linking to the other parts of the site are good style" (pointing to the IO24 two-up outlined-tile pattern)

The pivot: keep the IO reference, ditch the gradients entirely, go dark, lean into the outlined-tile-on-black as the signature visual unit.

## Aesthetic Summary

Near-black canvas (`#0A0A0A`). Every surface that isn't background is a dark card defined by a **thin white outline** (`rgba(255,255,255,0.22)`). Typography is Figtree throughout (plus Newsreader serif for doc-viewer body) in pure white for display, off-white for body. The four Google primaries — red `#EA4335`, yellow `#FBBC04`, blue `#4285F4`, green `#34A853` — appear only as **discrete solid accents**: colored numerals, a single colored period of punctuation, a solid-fill badge, a 3px left edge on a blockquote, syntax-highlighting in code. Never gradients. Never softened. Never adjacent.

The full tokens and component patterns are in the spec:

- See `docs/specs/2026-04-17-frontend-design.md` → "Visual Direction"

## Files Modified

| File | Change |
|------|--------|
| `src/markland/web/templates/base.html` | Full rewrite: dark tokens, outline-as-signature, red wordmark dot, ghost-pill nav. Dropped all gradient vars, removed `.sparkle` helper, removed `--gradient-bg` body mesh. |
| `src/markland/web/templates/landing.html` | Full rewrite: hero with red/blue period accents, primary white-on-black pill CTA + ghost secondary, three outlined pillars with colored numerals (blue/red/yellow), **new** "Get started" two-up outlined nav-card section, featured grid with yellow "Pinned" pill badge. Removed all hero blobs, all card top strips, all sparkle icons. |
| `src/markland/web/templates/explore.html` | Full rewrite: outlined search input with white focus, white-fill primary search button, outlined result-count badge with green dot, uniform outlined card grid. Removed gradient card strips, removed gradient headline text. |
| `src/markland/web/templates/document.html` | Full rewrite: dark reading surface, outlined container (no gradient strip), Newsreader serif body at off-white on dark, Pygments tokens rebound to Google primaries, yellow-left-edge blockquotes. |

No changes to Python, routes, data model, tests, or smoke test. Purely templates.

## Key Design Decisions

### 1. The outline IS the signature

Every card — pillars, featured grid, nav cards, explore grid, doc container, empty states, inputs, badges, buttons — uses the same `1.5px solid rgba(255,255,255,0.22)` stroke as its defining edge. Hover brightens to `0.45` or full `#FFFFFF`. This is a single primitive that scales across the entire system. No `box-shadow`, no gradient strips, no filled accents — the outline carries it.

The hairline variant (`rgba(255,255,255,0.09)`) is used for internal separators: meta-row rules, table row borders, footer top border. Too subtle to be a card edge, exactly right for sub-divisions inside a card.

### 2. Primary colors as punctuation

The signature color move on this pass: **the period after "writes" is red, the period after "reads" is blue**. One character of type — a period — carries a primary color. The headline text is otherwise pure white. Explore hero does the same with a comma. This is primary-color accent taken to the smallest possible unit and is recognizably weird enough to stick.

Other primary applications, ranked by size:
- Code syntax highlighting — most of the primary color on any page lives in the doc viewer's `<pre>` blocks. Keywords red, strings green, numbers yellow, names blue.
- Pillar numerals `01` / `02` / `03` — blue / red / yellow on the landing.
- Solid badge fills — "Pinned" yellow, nothing else.
- Small dots — wordmark red, hero chip yellow, section eyebrow green (landing) / blue (explore), result-count green, blockquote left-edge yellow.

Never used as: backgrounds, card fills, button fills, text of more than one character, gradient stops, large areas.

### 3. The two-up nav-card section is new

Added to the landing between Why Markland and Featured docs. Directly patterned on the reference image's "Join a community group" / "Continue learning" tiles. `min-height: 320px`, 32px radius (one step larger than other cards to read as "major"), 2-column grid, each contains title + muted paragraph + ghost-pill action button at the bottom.

Content:
- Card 1: "Browse public docs" → `/explore`
- Card 2: "Publish from your agent" → copies MCP config via Clipboard API

Functionally, these replicate the hero CTAs. That's intentional — they're an alternative entry point for visitors who scroll past the hero.

### 4. Deliberately no wireframe illustrations yet

The reference image has custom wireframe-3D illustrations in the corners of each tile (globes, speech bubbles, colorful ribbons). User explicitly said "don't worry about the wireframe graphics yet." Tiles on Markland currently land with no illustration — just typography. That's a clean base for future illustration work. Options deferred: corner SVG illustrations per nav card, or small colored-line decorations.

### 5. Inverted-primary for the single top action per page

One button per page uses the solid-white-pill-with-black-text pattern — the inverted emphasis. Everywhere else is a ghost outline pill.

- Landing: hero "Copy MCP config" is inverted. Hero "Browse docs" and nav-card buttons are ghost. Result: the ONE most-important action is visually louder than the surrounding content.
- Explore: "Search" button is inverted. Sort dropdown is ghost. Same principle.
- No inverted button on the doc viewer — reading surface, no page-level primary action.

### 6. Pygments rebind to Google primaries

Code blocks now show keywords in red, strings in green, numbers in yellow, function/class names in blue, comments in muted-italic. The usual GitHub-style purple-keyword / dark-blue-string palette replaced with the four discrete primaries. This is the most colorful surface in the entire doc viewer, and it earns that — code is the content-form that most benefits from per-token color variance.

### 7. Dark canvas but not pure black

`#0A0A0A` not `#000`. Absolute black causes outlines with low opacity to visually vibrate — they appear to "crawl" against the background. One step up keeps the dark feel but lets the `rgba(255,255,255,0.22)` strokes resolve cleanly.

### 8. Motion is outline-color + translateY only

No shadow animations (there are no shadows). No gradient position loops (no gradients). Hover states animate two properties:

1. `border-color` from `--outline` to `--outline-strong` or `--text`, 0.18s ease
2. `transform: translateY(-1px to -3px)` for buttons / cards

That's it. Static confidence with small tactile feedback.

## What Was Removed From the Previous Pass

- All gradient tokens (`--gradient-rainbow`, `--gradient-cool`, `--gradient-warm`, `--gradient-mint`, `--gradient-bg`)
- All blurred gradient blobs from the hero
- The `.sparkle` CSS helper (SVG-mask icon with gradient fill)
- Sparkle icons in section eyebrows, hero chip, CTAs, search button
- Gradient text animation on the hero headline
- Gradient top strips on pillar and grid cards (5-variant cycling in explore, 3-variant in landing)
- Gradient stripe on the doc container top edge
- Ambient radial-gradient body mesh
- All soft blur-based shadows as card separators
- The warm off-white canvas

## Test Impact

- 0 new tests
- All 68 tests still green
- No behavior changes — only CSS + minor markup simplification (removed decorative spans/divs)

## What's Next (Deferred)

The reference io.google/2024 tiles have custom wireframe-3D illustrations that anchor each card. User deferred these ("don't worry about the wireframe graphics yet") but they'd be the natural next step:

- **Nav-card illustrations** — inline SVG wireframe art in the bottom-right of each of the two "Get started" cards. Something on-theme: a stylized markdown file for "Browse"; a stylized MCP connection graph for "Publish."
- **Pillar illustrations** — smaller inline SVG icons for each pillar numeral (01/02/03), in the same wireframe + primary-color style.
- **Hero decoration** — one or two wireframe shapes drifting in the hero whitespace. Minimal, not blobs.
- **Doc viewer illustrations** — first-letter drop cap treatment, or a small wireframe decoration in the meta row.

The aesthetic is strong enough without illustrations; they'd push it further rather than fix a gap.

Other deferred:
- Dark-mode/light-mode toggle (tokens are dark-first; light-mode tokens would be a separate set, not just inversions)
- Reading-mode toggle in doc viewer (Figtree body alternate for users who prefer sans-serif)
- Accessibility audit — `--text-2` off-white against `--surface` is comfortably AA; `--muted` against `--surface` is lighter and may need tuning for AAA compliance
- OpenGraph / Twitter card images using the dark + primary palette

## Not In Scope

- Component library extraction (everything inlined per-template)
- Design token export (CSS vars only, no JSON/TypeScript tokens module)
- Server-side theme switching
- Icon system beyond the colored-dot motif
