# Schema.org Audit — Markland Marketing Site

**Date:** 2026-04-24
**Target:** https://markland.fly.dev/
**Scope:** 13 marketing URLs, all served via shared `_seo_meta.html` partial.

## 1. Detected Schema (all pages — verified via homepage, /quickstart, /alternatives/notion)

Three JSON-LD blocks, identical across every page:

| Type | @id | Validity |
|------|-----|----------|
| `Organization` | `#organization` | Pass (minimal) |
| `WebSite` | `#website` | Pass |
| `SoftwareApplication` | `#software` | Pass (missing rich-result fields) |

Format: JSON-LD, `@context: https://schema.org`, absolute URLs, no placeholders, no deprecated types. Cross-refs via `@id` resolve correctly.

## 2. Validation Per Type

### Organization — PASS, incomplete
Required (`name`, `url`): present. Missing recommended: `logo` (required for Google knowledge panel eligibility), `sameAs` (social/GitHub profiles), `foundingDate`, `contactPoint`.

### WebSite — PASS, incomplete
Valid. Missing `potentialAction` → `SearchAction` (sitelinks search box eligibility, since `/explore` exists).

### SoftwareApplication — PASS, thin
Has `applicationCategory`, `operatingSystem`, `featureList`. Missing the three fields Google requires for the Software App rich result: `offers` (with `price`/`priceCurrency`), `aggregateRating`, and `review`. Without any of these, no rich snippet eligibility — block is currently decorative only.

## 3. Gaps & Opportunities

### Critical (unlocks rich results)
1. **`SoftwareApplication.offers`** — Add `Offer` with `price: "0"`, `priceCurrency: "USD"`, `availability: https://schema.org/InStock`. Required for the Software App rich card. Effort: 15 min (static values in partial).
2. **`Organization.logo`** — Add ImageObject pointing to the Markland wordmark SVG/PNG. Required for knowledge panel. Effort: 30 min (needs a raster logo asset at min 112x112).

### High
3. **`BreadcrumbList` on `/alternatives/{slug}`** (6 pages) — Worth it. Google renders breadcrumbs in SERP for comparison pages, replacing the URL. Visual hierarchy (`Home › Alternatives › Notion`) already rendered in `.cmp-crumbs`, so this is pure markup work. Effort: 20 min (one template block, crumbs exist in data).
4. **`Organization.sameAs`** — Add GitHub org URL (and X/LinkedIn when live). Trivial but meaningful for entity disambiguation. Effort: 5 min.
5. **`WebSite.potentialAction` (SearchAction)** — `/explore` is a browse surface, not full-text search, so only add this if/when a real `?q=` search endpoint exists. Defer.

### Medium
6. **`TechArticle` on `/quickstart`** — Worth it. `/quickstart` is a developer onboarding article with code samples; `TechArticle` (not `Article`) is the correct subtype and not deprecated. Adds `headline`, `datePublished`, `dateModified`, `author` (Organization ref), `proficiencyLevel: "Beginner"`. No rich result, but improves topical relevance and agent parsing. **Do NOT use `HowTo`** — deprecated Sep 2023. Effort: 30 min.
7. **`ItemList` on `/alternatives` hub** — Worth it for listing the 5 comparison pages as an ordered list of `WebPage` items. No `ComparisonTable` type exists in Schema.org — don't invent one. `ItemList` is the correct choice. Effort: 20 min.
8. **`WebPage` wrapper with `about`/`mainEntity`** on each `/alternatives/{slug}` — links the page to the compared product as an entity. Low marginal value; defer.

### Low / Do Not Add
- **`FAQPage`** — Rich result restricted Aug 2023 to government/health authorities. Markland does not qualify. Even if Q&A content is added later, rich-result eligibility is effectively zero. Skip.
- **`Product`** on comparison pages — Incorrect; `SoftwareApplication` is already the canonical type and is a `Product` subclass. Duplicating would confuse entity graph.
- **`Review` / `AggregateRating`** on alternatives pages — Do not fabricate ratings; only add once real review data (e.g. Product Hunt, G2) exists. Fabricated ratings are a manual-action risk.

## 4. Recommended Implementation Order

1. Add `offers` to `SoftwareApplication` (Critical, 15 min).
2. Add `sameAs` to `Organization` (High, 5 min).
3. Add `BreadcrumbList` to alternatives template (High, 20 min).
4. Add `logo` to `Organization` once asset exists (Critical, 30 min).
5. Add `TechArticle` to `/quickstart` (Medium, 30 min).
6. Add `ItemList` to `/alternatives` hub (Medium, 20 min).

Total effort for items 1–3: ~40 min. Items 1–6: ~2 hours.

## 5. Sample JSON-LD — SoftwareApplication with `offers`

```json
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "@id": "https://markland.fly.dev/#software",
  "name": "Markland",
  "url": "https://markland.fly.dev/",
  "applicationCategory": "BusinessApplication",
  "applicationSubCategory": "DocumentManagement",
  "operatingSystem": "Web, macOS, Linux, Windows",
  "offers": {
    "@type": "Offer",
    "price": "0",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock"
  },
  "publisher": { "@id": "https://markland.fly.dev/#organization" }
}
```

## 6. Sample JSON-LD — BreadcrumbList (per alternatives/{slug} page)

```json
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://markland.fly.dev/" },
    { "@type": "ListItem", "position": 2, "name": "Alternatives", "item": "https://markland.fly.dev/alternatives" },
    { "@type": "ListItem", "position": 3, "name": "Notion", "item": "https://markland.fly.dev/alternatives/notion" }
  ]
}
```
