# Markland — Full SEO Audit

**Date:** 2026-04-24
**Target:** https://markland.fly.dev/
**Scope:** 13 marketing URLs (handcrafted, no programmatic pages)
**Business type:** SaaS — MCP document publishing platform for AI agents / Claude Code
**Lifecycle stage:** Pre-launch. Zero traffic, zero backlinks, pre-canonical-domain. Sitemap NOT yet submitted to GSC (intentional — awaits `markland.dev` cutover).

---

## Executive Summary

**SEO Health Score: 77 / 100** (strong technical floor, medium content ceiling)

### Category scores

| Category | Weight | Score | Weighted |
|----------|:------:|:-----:|:--------:|
| Technical SEO | 25% | 9.0 / 10 | 22.5 |
| Content Quality | 25% | 6.0 / 10 | 15.0 |
| On-Page SEO | 20% | 7.0 / 10 | 14.0 |
| Schema / Structured Data | 10% | 7.0 / 10 | 7.0 |
| Performance (Core Web Vitals) | 10% | 9.5 / 10 | 9.5 |
| Images | 5% | 10.0 / 10 | 5.0 |
| AI Search Readiness (GEO) | 5% | 7.0 / 10 | 3.5 |
| **Total** | | | **76.5 → 77** |

### Top 5 Critical / High issues

1. **`/alternatives` hub: competitor sections are `<div>`-wrapped, not `<h2>`-wrapped.** 484-word comparison hub has only 3 headings total. Biggest GEO loss on the site — LLMs cannot find scoped passages per competitor.
2. **404 returns JSON, not HTML.** `/nonexistent-page-xyz` → `{"detail":"Not Found"}`. No branded shell, no navigation back to the sitemap. Breaks discovery for both humans and crawlers.
3. **Trust-floor pages fail E-E-A-T thresholds.** `/about` 98w, `/security` 118w, `/privacy` 101w, `/terms` 95w — all below the 250-word floor. Zero author bylines, zero founder name, zero contact. Known intentional (stubs) but blocks trust signals.
4. **No author/expertise signal anywhere sitewide.** Zero `<meta name="author">`, no bylines, no LinkedIn/GitHub founder link. On a zero-traffic SaaS, the only off-page trust signal is "who built this" — invisible today.
5. **`SoftwareApplication` JSON-LD missing `offers`.** Without `offers` (+`aggregateRating` or `review`) Google will not render the Software App rich result. Current block is decorative only.

### Top 5 Quick Wins (ranked by ROI / effort)

| # | Win | Effort | Impact |
|---|-----|:------:|--------|
| 1 | Wrap `/alternatives` competitor names in `<h2>` | 15 min | Big GEO + on-page lift |
| 2 | Add `offers` to SoftwareApplication JSON-LD | 15 min | Unlocks Software App rich result |
| 3 | Add `sameAs` (GitHub URL) to Organization JSON-LD | 5 min | Entity disambiguation |
| 4 | Add `BreadcrumbList` JSON-LD to `/alternatives/{slug}` | 20 min | SERP breadcrumbs |
| 5 | Extend trust-page titles from 14–19 chars to 40–55 chars | 10 min | Recover wasted SERP real estate |

**Sub-hour quick-win bundle unlocks ~5 points of scoring headroom and one rich-result eligibility.**

---

## Technical SEO (9.0 / 10)

### Pass (verified)
- All 6 security headers land on 2xx AND 4xx/5xx (HSTS, CSP, XFO, XCTO, Referrer-Policy, Permissions-Policy).
- `X-Robots-Tag: noindex, nofollow` lands on all non-marketing paths.
- `<html lang="en">`, viewport meta, self-referential canonicals, single `<h1>` on every page.
- Sitemap: well-formed, sitemap.org schema-valid, 13 URLs all 200 OK, none noindexed or disallowed, `lastmod` ISO 8601.
- Robots.txt: `Sitemap:` line matches; GPTBot + CCBot blocked; every `Disallow:` maps to a real noindex prefix.
- Internal linking: every marketing page links to ≥7 other marketing pages via footer; `/alternatives` fans out to all 5 children.
- Zero `<img>` tags sitewide → no alt-text debt.

### Issues

- **[High] 404 returns JSON, not HTML.** FastAPI default. Fix: exception handler rendering `404.html` when `Accept: text/html`; preserve JSON for API clients.
- **[Medium] Uniform sitemap `lastmod`.** All 13 entries share `2026-04-24`. Acceptable at launch — wire to real file/publish timestamps once pages diverge.
- **[Low] HEAD returns 405.** Cosmetic — Googlebot uses GET. Affects uptime monitors only.

---

## Content Quality / E-E-A-T (6.0 / 10)

Applying the Dec 2025 QRG update (E-E-A-T matters for all competitive queries, not just YMYL).

### Strengths
- **Citable definitional sentence** on homepage: *"Markland is an MCP-based document publishing platform that lets AI agents like Claude Code publish, share, and grant access to markdown documents via a single tool call."* 29 words, SVO, names category + mechanism + target user. Ideal LLM-quotable shape. **Keep above fold.**
- **Strong entity naming.** "Git", "Google Docs", "Claude Code", "MCP", "Notion", "HackMD" all appear in body + headings + meta. Exactly the entity soup LLMs need to cluster Markland with "agent-native document tools".
- **Genuinely differentiated `/alternatives/{slug}`.** Notion↔GitHub Jaccard word-similarity = **36%** — these are handcrafted, not programmatic. Unique per-competitor H3s ("Blocks vs markdown", "Sharing unit mismatch", etc.).

### Issues

- **[Critical — acknowledged intentional] Trust-floor pages fail E-E-A-T.** `/about` 98w; `/security` 118w; `/privacy` 101w; `/terms` 95w. Target floor is 250–300w per page. Scope: known stub, escalated from "Critical" to "High" once real users arrive; "Critical" before any paid acquisition.
- **[High] No author/expertise signal anywhere sitewide.** Zero byline, founder, photo, LinkedIn/GitHub link. Fix: footer line + `/about` author block + wire `Organization.founder: Person` into JSON-LD.
- **[Medium] Homepage H1 semantically mushy.** "Shared documents." / "For you" / "and your agents." renders to crawlers as four fragments. Fix: `aria-label` on `<h1>` with the full intended sentence, or flatten and let CSS wrap.
- **[Medium] Readability split.** `/quickstart` Flesch 68.1 (grade 8 — fine for devs). `/alternatives/notion` 50.9 (college — heavy for a non-technical PM). Loosen 2–3 paragraphs if target reader is broader.
- **[Medium] `/quickstart` has no end-of-page CTA.** Walks through 5 steps, ends cold. Add a closing "Next steps" H2 → waitlist.
- **[Low] `/explore` soft-404 risk.** Empty gallery indexed in sitemap. Noindex until content exists, or render a "Here's what a public doc looks like" example.

---

## On-Page SEO (7.0 / 10)

### Title tags

| Page | Length | Verdict |
|------|:------:|---------|
| `/` | 58 | Good |
| `/quickstart` | 59 | Good |
| `/alternatives` | 61 | Good |
| `/alternatives/{slug}` | ~36 | **Too short, wastes tail** — add "alternative" or benefit keyword |
| `/about` | 14 | **Too short** |
| `/security` | 19 | **Too short** |
| `/privacy` | 18 | **Too short** |
| `/terms` | 16 | **Too short** |

### Meta descriptions

- `/`, `/alternatives`, `/about` between 150–160 chars — good, unique.
- `/privacy` 90 chars, `/terms` 76 chars — below the 130-char floor where Google rewrites in SERP.
- `/alternatives/{slug}` descriptions all end with the same canned tail "MCP-first sharing, per-doc grants, one link." — write a unique benefit line per competitor.

### Heading structure
- `/` clean: `H1 → H2/H3/H3/H3 → H2/H2/H2/H2 → H3/H3 → H2`.
- **`/alternatives` broken: only 3 headings total on 484 words.** (see Top 5 #1).
- `/about` has only H1, no H2s.

### Other
- Canonicals self-reference correctly across all 13 pages.
- Internal linking strong (footer + hub-and-spoke on `/alternatives`).

---

## Schema / Structured Data (7.0 / 10)

Detected on every page (identical): `Organization`, `WebSite`, `SoftwareApplication` (all valid, `@id` cross-refs resolve).

### Gaps

**Critical (rich-result unlockers)**
- `SoftwareApplication.offers` missing — required for Software App rich result. 15 min static fix in partial.
- `Organization.logo` missing — required for Google knowledge panel. Needs 112×112 minimum raster asset. 30 min.

**High**
- `Organization.sameAs` — add GitHub org URL (later X/LinkedIn). 5 min. Entity disambiguation.
- `BreadcrumbList` on each `/alternatives/{slug}` — SERP renders breadcrumbs instead of URL. Crumbs already rendered in `.cmp-crumbs`, so pure markup work. 20 min.

**Medium**
- `TechArticle` on `/quickstart` (NOT `HowTo` — deprecated Sep 2023). 30 min.
- `ItemList` on `/alternatives` hub. 20 min.

**Do not add**
- `FAQPage` — rich-result restricted to gov/health since Aug 2023. Skip.
- `Product` on comparison pages — duplicative with SoftwareApplication (a Product subclass).
- Fabricated `AggregateRating` / `Review` — manual-action risk. Only add once real ratings exist.

---

## Performance — Core Web Vitals (9.5 / 10)

Playwright cold-load, single nav per viewport. Sample size 1; treat as smoke-test, not field data.

| Page | Viewport | LCP | CLS | FCP | TTFB | INP~ |
|------|----------|----:|----:|----:|-----:|-----:|
| `/` | 1440×900 | 452 ms | 0.0018 | 452 | 51 | 8 |
| `/` | 375×812 | 388 ms | 0.0000 | 388 | 53 | 13 |
| `/quickstart` | 1440×900 | 336 ms | **0.0401** | 336 | 51 | 9 |
| `/quickstart` | 375×812 | 312 ms | 0.0000 | 312 | 50 | 8 |
| `/alternatives/google-docs` | 1440×900 | 408 ms | 0.0019 | 408 | 53 | 9 |
| `/alternatives/google-docs` | 375×812 | 316 ms | 0.0000 | 316 | 51 | 11 |

- **All LCP < 500 ms, all CLS well inside "good" (<0.1).** LCP == FCP everywhere — text-dominant heroes + inline `<style>` in `base.html` = zero render-blocking CSS.
- **One font-swap shift on `/quickstart` desktop (CLS 0.0401).** ~20× higher than the other pages; the large `<h1>` swaps metrics when the custom face replaces the fallback. Still passes. Fix: `size-adjust`/`ascent-override` on fallback `@font-face`, OR self-host with `font-display: optional` (Task 10, deferred). Mobile CLS is 0.0000 everywhere.

### Above-the-fold analysis
- **`/` desktop + mobile**: H1 + sub-head + email field + "Get started" CTA all visible in first viewport. ✅
- **`/quickstart`**: no hero CTA by design (docs page). ✅
- **`/alternatives/google-docs`**: H1 visible, but the page's only waitlist CTA sits at `y=1962` desktop / `y=3206` mobile. **Biggest conversion leak in audit** — high-intent comparison traffic scrolls a full viewport-plus to convert.

---

## Images (10.0 / 10)

No `<img>` tags sitewide. `/favicon.svg` + `/og.png` exist as static assets. No alt-text debt. No oversized-image concern.

---

## AI Search Readiness / GEO (7.0 / 10)

### Strong
- Citable definitional sentence on `/`.
- Entity soup across body + headings + meta.
- Schema coverage gives Gemini / Perplexity / ChatGPT web search the structured hook.
- `/quickstart` passage structure (5 sequential H2 steps) is ideal for "how to publish from Claude Code" citations.

### Weak
- **`/alternatives` hub has no scoped per-competitor passages** (see Top 5 #1). Ask Perplexity "what are alternatives to Markshare.to" today — the page is structurally illegible.
- **Thin trust pages** — an LLM evaluating Markland for E-E-A-T has nothing on `/about`. Expect hedged citations.
- **No FAQ block, no `Last updated: YYYY-MM-DD` freshness signal** anywhere. Perplexity + AI Overviews disproportionately cite FAQ + timestamped content.
- **No named founder** — backlinks and citations both key off a named human.

### Recommendations (ordered by AI-search ROI)
1. Fix `/alternatives` H2 wrapping.
2. Expand `/about` to 250–300 words with named founder + background.
3. Add 3–5 FAQ block to `/` + `/quickstart` (plain markup — skip `FAQPage` schema).
4. Add `Last updated: 2026-04-24` line to every marketing page.
5. Add sitewide author byline (footer + `/about`).

---

## Artifacts in this directory

- `homepage.html`, `quickstart.html`, `alternatives.html`, `alternatives-notion.html`, `alternatives-github.html`, `about.html`, `security.html`, `privacy.html`, `terms.html` — fetched HTML snapshots.
- `sitemap.xml`, `robots.txt` — fetched crawl-policy files.
- `screenshots/` — 12 PNGs (desktop/mobile × above-fold/full × 3 pages).
- `vitals.json`, `af_recheck.json` — raw Playwright telemetry.
- `schema-findings.md`, `sitemap-findings.md`, `visual-findings.md`, `technical-content-findings.md` — per-specialist reports.
- `ACTION-PLAN.md` — prioritized fixes with effort + file paths.

---

## Post-audit context (known & tracked)

- **Domain cutover** — site currently on `markland.fly.dev`; canonical `markland.dev` pending purchase. Sitemap submission to GSC is parked (see `docs/FOLLOW-UPS.md` "Deploy / operations").
- **Task 10 (self-host + subset fonts)** — deferred. Would zero out the `/quickstart` desktop 0.04 CLS and the font-swap latency.
- **CSP `'unsafe-inline'`** — known trade-off pending nonce migration.
