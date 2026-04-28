# Visual Audit — Markland (2026-04-24)

Playwright/Chromium headless, cold loads. Raw data: `vitals.json`, `af_recheck.json`. Screenshots: `screenshots/*.png` (12: desktop+mobile × above-fold+full × 3 pages).

## Core Web Vitals

`PerformanceObserver` on a single cold nav per viewport. INP is a simulated proxy (focus/mouseover over first 5 interactive elements) — upper-bound on handler cost, not field data.

| Page | Viewport | LCP | CLS | FCP | TTFB | INP~ |
|---|---|---:|---:|---:|---:|---:|
| `/` | 1440×900 | 452 ms | 0.0018 | 452 | 51 | 8 |
| `/` | 375×812 | 388 ms | 0.0000 | 388 | 53 | 13 |
| `/quickstart` | 1440×900 | 336 ms | **0.0401** | 336 | 51 | 9 |
| `/quickstart` | 375×812 | 312 ms | 0.0000 | 312 | 50 | 8 |
| `/alternatives/google-docs` | 1440×900 | 408 ms | 0.0019 | 408 | 53 | 9 |
| `/alternatives/google-docs` | 375×812 | 316 ms | 0.0000 | 316 | 51 | 11 |

All LCP < 500 ms, all CLS well under 0.1 "good". LCP == FCP everywhere — text-dominant heroes + zero render-blocking CSS (inline `<style>` in `base.html`).

### Font-load shift (quantified)

CSS is inline; only shift source is Google Fonts swap-in. One shift fires ~480–600 ms post-nav on desktop:

- `/` desktop: **0.0018** @ 595 ms
- `/quickstart` desktop: **0.0401** @ 483 ms — **worst observed**
- `/alternatives/google-docs` desktop: **0.0019** @ 510 ms
- All mobile loads: **0.0000**

`/quickstart` desktop is still inside "good" but ~20× higher than the others — the large `h1` swaps metrics when the custom face replaces the fallback. `size-adjust`/`ascent-override` on the fallback `@font-face` (or self-hosting with `font-display: optional`) zeros it out.

## Above-the-fold analysis

`scrollY=0` after `document.fonts.ready`. Desktop viewport 900 px, mobile 812 px.

| Page | Viewport | H1 visible | CTA | CTA top | Above fold? |
|---|---|---|---|---:|---|
| `/` | Desktop | Yes (272–438) | "Get started" | 648 | **Yes** |
| `/` | Mobile | Yes (240–406) | "Get started" | 744 | **Yes** (68 px clear) |
| `/quickstart` | Desktop | Yes (170) | — (docs, no hero CTA) | n/a | n/a |
| `/quickstart` | Mobile | Yes (170) | — | n/a | n/a |
| `/alternatives/google-docs` | Desktop | Yes (200–261) | "Join the waitlist" | **1962** | **No** |
| `/alternatives/google-docs` | Mobile | Yes (200–274) | "Join the waitlist" | **3206** | **No** |

1. Homepage: hero, sub-head, email field, and "Get started" all fit first screen on both viewports.
2. `/quickstart`: no hero CTA by design; acceptable for a docs page.
3. **`/alternatives/google-docs` has no CTA above the fold** on either viewport — the only waitlist link sits near page end (~1960 px desktop / ~3206 px mobile). Comparison traffic is high-intent; this is the biggest conversion leak in the audit.

## Rendering bugs

- No horizontal overflow on any viewport (`scrollWidth == viewport` on all mobile loads).
- No overlapping elements, no cut-off text, no FOUC — font swap is metrics-only.
- Nav (logo, Explore, Docs) renders identically at 1440 and 375; no hamburger needed.
- Home "Get started" button ~48 px tall on mobile — meets touch-target minimum.

## Recommendations (ranked)

1. **Add a waitlist CTA in the hero of `/alternatives/*`.** High-intent traffic shouldn't scroll a full viewport-plus to convert.
2. **Fix font metrics** via `size-adjust`/`ascent-override` on the fallback, or self-host with `font-display: optional` — zeros the 0.04 CLS on `/quickstart` desktop. Low urgency; still passes CWV.
3. Add `rel="preconnect"` for `fonts.gstatic.com` if not present — shaves the ~500 ms font-swap latency.
