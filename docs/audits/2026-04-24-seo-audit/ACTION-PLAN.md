# Markland SEO — Action Plan

**Source audit:** `FULL-AUDIT-REPORT.md` (2026-04-24). **Current score:** 77 / 100.
**Ordered by impact × inverse-effort.** File paths use repo root `/Users/daveyhiles/Developer/markland/`.

---

## 🟥 Critical (do before any paid acquisition or GSC submission)

### C1. Wrap `/alternatives` competitor sections in `<h2>`
- **Why:** 484-word comparison hub has only 3 headings total. Biggest GEO loss — LLMs cannot find scoped passages per competitor.
- **Fix:** In the alternatives hub template, wrap each competitor card's name in `<h2>` (e.g. "Markshare.to vs Markland"). Keep the existing visual styling via class; only change the semantic tag.
- **File:** `src/markland/web/templates/alternatives.html`
- **Effort:** 15 min

### C2. Add `offers` to `SoftwareApplication` JSON-LD
- **Why:** Without `offers`, Google cannot render the Software App rich snippet. Block is decorative today.
- **Fix:** Add an `Offer` child to the `SoftwareApplication` JSON-LD block:
  ```json
  "offers": {
    "@type": "Offer",
    "price": "0",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock"
  }
  ```
  Use `|tojson` for the Offer dict (per the partial's documented contract).
- **File:** `src/markland/web/templates/_seo_meta.html`
- **Effort:** 15 min

### C3. Render HTML 404 page instead of JSON
- **Why:** `/nonexistent-page-xyz` returns `{"detail":"Not Found"}`. No branded shell, no navigation back to the sitemap, poor discovery UX for humans + crawlers.
- **Fix:** FastAPI 404 exception handler that renders a new `404.html` (extends `base.html`, has a link to `/` and `/quickstart`) when `Accept: text/html`. Preserve JSON fallback for API clients (`request.url.path.startswith("/api")` or `Accept: application/json`).
- **Files:**
  - `src/markland/web/app.py` (exception handler registration)
  - `src/markland/web/templates/404.html` (new)
- **Effort:** 45 min (template + handler + test)

### C4. Resolve E-E-A-T thinness on trust pages before paid acquisition
- **Why:** `/about` 98w, `/security` 118w, `/privacy` 101w, `/terms` 95w — all below 250-word floor. Zero author/founder/contact signal. Known stub. Fine pre-traffic; blocks trust before any paid push.
- **Fix:** Expand each to 250–300w. `/about` adds founder name, handle, 2-sentence background, contact path. `/security` adds one sub-heading per claim (token lifetime, revocation, at-rest encryption, host region) + "Last updated". `/privacy`+`/terms` add data-retention, deletion process, "Last updated".
- **Files:** `src/markland/web/templates/{about,security,privacy,terms}.html`
- **Effort:** 2–3 hours total (content, not code)

---

## 🟧 High (do within 1 week)

### H1. Add sitewide author/expertise signal
- **Why:** Zero `<meta name="author">`, no byline, no founder link. On a zero-traffic SaaS, the only off-page trust signal is "who built this". Invisible today.
- **Fix:**
  - Footer line: *"Built by {Name} — {one-sentence creds} — {link to GH/LinkedIn}"*.
  - Author block on `/about`.
  - Wire `Organization.founder: Person` into the JSON-LD in `_seo_meta.html`.
- **Files:**
  - `src/markland/web/templates/base.html` (footer)
  - `src/markland/web/templates/about.html`
  - `src/markland/web/templates/_seo_meta.html` (Organization `founder`)
- **Effort:** 45 min (mechanics; content depends on decision re: public-facing founder identity)

### H2. Add `BreadcrumbList` JSON-LD to `/alternatives/{slug}`
- **Why:** SERP renders breadcrumbs replacing the URL. Crumbs already visually rendered in `.cmp-crumbs` so it's pure markup work.
- **Fix:** Add a `{% block extra_jsonld %}` in `alternative.html` that emits a `BreadcrumbList` with positions Home → Alternatives → {competitor.name}. Use `|tojson` on dynamic values.
- **File:** `src/markland/web/templates/alternative.html`
- **Effort:** 20 min

### H3. Add `sameAs` + `logo` to `Organization` JSON-LD
- **Why:** `sameAs` (GitHub URL, later X/LinkedIn) → entity disambiguation. `logo` → required for Google knowledge panel.
- **Fix:** Extend the Organization block in `_seo_meta.html`:
  ```json
  "sameAs": ["https://github.com/dghiles/markland"],
  "logo": {
    "@type": "ImageObject",
    "url": "{{ (canonical_host ~ '/og.png') | tojson }}",
    "width": 1200,
    "height": 630
  }
  ```
  Note: `og.png` may not meet Google's knowledge-panel logo spec (≥112×112 square raster). Ideal fix is a dedicated `logo.png` — but `og.png` is acceptable as an interim.
- **File:** `src/markland/web/templates/_seo_meta.html`
- **Effort:** 15 min (interim) / 45 min (with dedicated logo asset)

### H4. Add a waitlist CTA to `/alternatives/*` above the fold
- **Why:** Biggest conversion leak in the audit — high-intent comparison traffic lands at `y=0`, the only waitlist link is at `y=1962` desktop / `y=3206` mobile.
- **Fix:** Add a "Join the waitlist" inline form (or button linking to `/#hero`) in the TL;DR card at the top of `alternative.html`.
- **File:** `src/markland/web/templates/alternative.html`
- **Effort:** 30 min

### H5. Extend trust-page titles (14–19 chars → 40–55)
- **Why:** Trust pages waste SERP real estate with titles like "Terms — Markland" (16 chars).
- **Fix:** Set `{% block title %}` per page:
  - `/about` → "About Markland — Agent-native Document Publishing"
  - `/security` → "Security at Markland — Tokens, Grants & Data Handling"
  - `/privacy` → "Privacy at Markland — What We Store and What We Don't"
  - `/terms` → "Terms of Service — Markland Beta"
- **Files:** `src/markland/web/templates/{about,security,privacy,terms}.html`
- **Effort:** 10 min

### H6. Lengthen `/privacy` + `/terms` meta descriptions above 130 chars
- **Why:** 76 / 90 chars respectively — below the floor where Google rewrites in SERP.
- **Fix:** Extend each to 140–155 chars; mention "beta", "data deletion", "US-hosted", "no warranty".
- **Files:** `{privacy,terms}.html` `{% set seo_description = ... %}`
- **Effort:** 10 min

---

## 🟨 Medium (do within 1 month)

### M1. Unique `/alternatives/{slug}` titles + meta descriptions
- Each currently uses the same canned tail. Write per-competitor qualifiers (e.g. Notion → "Skip the account wall — share a single markdown link instead of a database row.").
- **File:** `src/markland/web/competitors.py` (add `seo_title`, `seo_description` fields to `Competitor` dataclass) + `alternative.html`
- **Effort:** 45 min

### M2. Add `TechArticle` JSON-LD to `/quickstart`
- Dev-onboarding article with code samples. `TechArticle` is the correct subtype (NOT `HowTo` — deprecated).
- **File:** `src/markland/web/templates/quickstart.html`
- **Effort:** 30 min

### M3. Add `ItemList` JSON-LD to `/alternatives` hub
- Ordered list of the 5 comparison pages as `WebPage` items.
- **File:** `src/markland/web/templates/alternatives.html`
- **Effort:** 20 min

### M4. Add end-of-page CTA to `/quickstart`
- 5 steps then cold end. Add closing "Next steps" H2 linking to `/explore` + waitlist form.
- **File:** `src/markland/web/templates/quickstart.html`
- **Effort:** 20 min

### M5. Add H2s to `/about`
- 98-word page has only H1 currently. Add "Why Markland exists" + "Who's behind it" H2s (compose alongside C4).
- **File:** `about.html`
- **Effort:** included in C4

### M6. Add FAQ block to `/` + `/quickstart`
- 3–5 Q&As ("Is Markland free?", "Does it work with ChatGPT?", "How is it different from Git?"). Plain markup — do **not** add `FAQPage` schema (rich-result restricted). Content alone helps GEO.
- **Files:** `landing.html`, `quickstart.html`
- **Effort:** 60 min (writing + placement)

### M7. Add "Last updated: YYYY-MM-DD" line to every marketing page
- Freshness signal for all three major AI engines.
- **File:** `base.html` footer block or per-page `{% block last_updated %}`
- **Effort:** 30 min

### M8. Fix homepage H1 semantic mushiness
- H1 splits into decorative fragments ("Shared documents." / "For you" / "and your agents.") — renders to crawlers as 4 disjoint text nodes. Not keyword-aligned with the title.
- **Fix:** Add `aria-label` on `<h1>` with the full intended sentence, OR flatten to one node and let CSS handle wrap.
- **File:** `landing.html`
- **Effort:** 10 min

### M9. Resolve `/explore` soft-404 risk
- Empty gallery currently indexed. Either noindex until populated, OR render "Here's what a public doc looks like" with one example.
- **Files:** `explore.html` (+ optional `_seo_meta.html` override to add `noindex` meta)
- **Effort:** 20 min

### M10. Wire sitemap `lastmod` to real timestamps
- All 13 entries share today. Fine at launch; wire to file mtime or per-route last-publish once pages diverge.
- **File:** `src/markland/web/app.py` sitemap handler
- **Effort:** 20 min

---

## 🟦 Low (backlog)

### L1. `size-adjust` / `ascent-override` on fallback `@font-face`
- Zeros out the `/quickstart` desktop 0.04 CLS. Still inside "good". Task 10 (self-host fonts) supersedes this.
- **Effort:** 30 min (standalone) / absorbed into Task 10

### L2. `rel="preconnect"` for `fonts.gstatic.com`
- Shaves ~500 ms font-swap latency. Obsoleted by Task 10 self-hosting.
- **File:** `base.html` `<head>`
- **Effort:** 2 min

### L3. Expand AI-crawler blocklist in robots.txt
- Add `anthropic-ai`, `Claude-Web`, `Google-Extended`, `PerplexityBot`, `Bytespider`. Current coverage (GPTBot, CCBot) already handles the two biggest.
- **File:** `src/markland/web/seo.py`
- **Effort:** 10 min

### L4. Widen `PrincipalMiddleware` protected-prefix set to cover `/admin/*`
- Dedupe bearer resolution (currently both middleware and the `/admin/audit` handler call `resolve_token`). Already tracked in `docs/FOLLOW-UPS.md`.
- **Effort:** tracked separately

### L5. Post-domain-cutover work
- All tracked in `docs/FOLLOW-UPS.md` under "Deploy / operations":
  - Rewrite sitemap `<loc>` hosts after `markland.dev` cutover.
  - Add 301s from `markland.fly.dev/*` → `markland.dev/*`.
  - Submit sitemap to GSC after DNS verify.

---

## Suggested batching

**Batch 1 — "sub-hour quick-win" (~80 min):**
C1 + C2 + H3(sameAs interim) + H2 + H5 + H6 + M8 — unlocks ~5 score points and one rich-result eligibility.

**Batch 2 — "trust floor" (half-day):**
C3 + C4 + H1 + H4 — moves the site from "credible-looking" to "credible".

**Batch 3 — "GEO polish" (half-day):**
M1 + M2 + M3 + M4 + M6 + M7 — specifically targets AI search citations.

**Projected score after Batch 1+2+3:** **92 / 100**. No new traffic strategy required.
