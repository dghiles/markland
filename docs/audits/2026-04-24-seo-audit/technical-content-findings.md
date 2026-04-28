# Markland Technical + Content SEO Audit

Audit date: 2026-04-24
Scope: `/`, `/quickstart`, `/alternatives`, `/alternatives/notion`, `/alternatives/github`, `/about`, `/security`, `/privacy`, `/terms`
Pre-verified (skipped): security headers, X-Robots-Tag on non-marketing routes, presence of meta/description/canonical/OG/Twitter/JSON-LD, sitemap/robots.txt.

---

## Technical SEO

### Pass (no action)

- `<html lang="en">`, viewport meta, self-referential canonicals, single H1 — all green on every page.
- Title length sweet spot on primary pages: `/` 58, `/quickstart` 59, `/alternatives` 61. Unique across the site.
- Meta description length on primary pages: `/` 160, `/alternatives` 155, `/about` 150. All unique.
- Internal linking: every marketing page links to ≥7 other marketing pages via footer; `/alternatives` hub fans out to all 5 children (15 internal links).
- Zero `<img>` tags sitewide — no alt-text debt.

### Issues

#### High: 404 returns JSON, not an HTML page
- **URL**: `/nonexistent-page-xyz`
- **Symptom**: returns `HTTP 404` with body `{"detail":"Not Found"}` (FastAPI default). No HTML, no branded shell, no navigation back to sitemap, no suggested links.
- **Fix**: add a FastAPI 404 exception handler that renders a branded `404.html` template (reuses base layout + footer) when the request accepts `text/html`. Preserve JSON fallback for API clients.
- **File**: likely `apps/web/app/main.py` (FastAPI exception handler registration).

#### High: Alternatives hub has no headings for the 5 competitor sections
- **URL**: `/alternatives`
- **Symptom**: the page lists Markshare.to, GitHub, Google Docs, Notion, HackMD as styled `<div>`/`<span>` cards. Total heading count on a 484-word comparison hub is **3** (H1 + "Summary" H2 + "See it for yourself" H2). Competitor names are invisible to Google's "Things/entities in content" parse and to LLMs scanning for passage structure.
- **Fix**: wrap each competitor name in an `<h2>` (e.g. "Markshare.to vs Markland", "GitHub vs Markland") inside each card. Keep the styling via class, change only the semantic tag.
- **File**: `apps/web/app/templates/alternatives.html` (the competitor list section).

#### Medium: Trust-page titles are too short, leaving SERP real estate unused
- **Pages / current lengths**:
  - `/about` — "About Markland" (14 chars)
  - `/security` — "Security — Markland" (19)
  - `/privacy` — "Privacy — Markland" (18)
  - `/terms` — "Terms — Markland" (16)
- **Fix**: extend to 40–55 chars with a qualifier, e.g.
  - "About Markland — Agent-native Document Publishing"
  - "Security at Markland — Tokens, Grants & Data Handling"
  - "Privacy at Markland — What We Store and What We Don't"
  - "Terms of Service — Markland Beta"
- **File**: `seo.py` PAGE_META table (or wherever per-route title overrides live).

#### Medium: `/terms` and `/privacy` meta descriptions are very short
- `/terms`: 76 chars. `/privacy`: 90 chars. Below the ~130-char floor where Google is likely to rewrite them in SERPs.
- **Fix**: extend each to 140–155 chars; mention "beta", "no warranty", "data deletion", "US-hosted" as applicable.

#### Medium: `/alternatives/*` titles don't include a keyword cue
- Current: `Markland vs Notion · Markland` (36 chars) — wastes the brand-after-dot tail and doesn't tell a searcher what the page *is*.
- **Fix**: e.g. `Markland vs Notion — Agent-native Markdown Publishing` or `Notion alternative for Claude Code agents · Markland`. Target the `"{competitor} alternative"` and `"Markland vs {competitor}"` dual intent. Each page gets a unique qualifier; keep at 50–60 chars.
- **File**: the per-competitor template's `{% block title %}`.

#### Medium: `/alternatives/{slug}` meta descriptions under-sell
- Notion 126 chars, GitHub 124. Ok-ish but all end with the same canned phrase "MCP-first sharing, per-doc grants, one link." — write a unique benefit-line per competitor (e.g. Notion → "Skip the account wall — share a single markdown link instead of a database row.").

#### Low: `/about` has only an H1 and no H2s
- 98-word page. Add at least two H2s ("Why Markland exists", "Who's behind it") for parse-able structure. Related to the E-E-A-T thinness below.
- Homepage heading sequence `H1,H2,H3,H3,H3,H2,H2,H2,H2,H3,H3,H2` — clean, no skipped levels, no action.

---

## Content / E-E-A-T

### Strengths

- **Definitional sentence is citable.** Homepage: *"Markland is an MCP-based document publishing platform that lets AI agents like Claude Code publish, share, and grant access to markdown documents via a single tool call."* 29 words, SVO, names category + mechanism + target user. Ideal LLM-quotable shape.
- **Strong entity naming.** "Git is overkill. Google Docs isn't agent-native." — memorable, entity-dense (Git, Google Docs, MCP, Claude Code).
- **Per-competitor differentiation is real.** Jaccard word-similarity Notion vs GitHub = **36%**. Unique H3s per page (Notion: "Blocks vs markdown", "Account wall"; GitHub: "Sharing unit mismatch", "Code-review chrome bounces readers") prove distinct angles.
- **CTA consistent.** "Get started" / "Sign up, wire the MCP server..." on `/`, `/alternatives`, `/alternatives/notion`.

### Issues

#### Critical: Trust-floor pages fail E-E-A-T thresholds
- `/about` 98w, `/security` 118w, `/privacy` 101w, `/terms` 95w. All below the ~250-word thin-content floor.
- `/about`: no byline, no founder, no "who built this / why", no contact. **Fix**: 200–300 words — founder name/handle, background, origin story, contact email once domain lands.
- `/security`: names claims ("per-doc grants", "scoped bearer tokens") but doesn't quantify (token lifetime? revocation? at-rest encryption? host region?). **Fix**: 300+ words, one sub-heading per claim, add "Last updated" timestamp.
- `/privacy` + `/terms`: stubs by design. Add "Last updated" + data-retention + deletion process to clear GDPR-adjacent floor.
- Confirmed intentional for now; priority goes to **High** once real users arrive, **Critical** before paid acquisition.

#### High: No author/expertise signal anywhere on the site
- Zero `<meta name="author">`, no byline on any page, no LinkedIn or GitHub link to the founder, no photo. On a zero-traffic, zero-backlink SaaS, the *only* off-page trust signal Google and LLMs have is whoever is behind it. Currently invisible.
- **Fix**: add a footer line ("Built by {Name} — {one-sentence creds} — {link to GH/LinkedIn}") and a short author block on `/about`. Wire `Organization.founder` into the existing JSON-LD Organization schema with a `Person` subtype.
- **File**: footer template + `seo.py` JSON-LD builder for Organization.

#### Medium: Homepage above-fold clarity = 7/10
- Definitional sentence is clear. But the H1 splits into decorative fragments ("Shared documents." / "For you" / "and your agents.") rendering as `Shared documents . For you and your agents .` to crawlers — cute but semantically mushy and not keyword-aligned with the title ("MCP Document Server for Claude Code & AI Agents").
- **Fix**: add `aria-label` on `<h1>` with the full intended sentence, or flatten the visible text to one clean line and let CSS handle wrap.

#### Medium: Readability split
- `/quickstart` Flesch **68.1** (grade 8, fine for devs). `/alternatives/notion` **50.9** (college level). If the target reader is a non-technical PM, loosen 2–3 paragraphs — syllable density ("infrastructure", "bidirectional") is the culprit, not sentence length.

#### Medium: `/quickstart` has no end-of-page CTA
- Walks through 5 steps then ends. Zero "Get started" / "waitlist" / "Join" on the page. **Fix**: closing "Next steps" H2 linking to `/explore` and the waitlist form.

#### Low: `/explore` soft-404 risk
- Empty gallery indexed in sitemap.xml risks soft-404 signal. Either noindex until content exists, or render "No public docs yet — here's what one will look like" with a single example.

---

## AI Search Readiness

### Citability assessment

- **Definitional sentence (strong citability)**: homepage has a standalone, subject-verb-object, jargon-explaining sentence that LLMs will quote. This is the single biggest GEO win on the site. Keep it where it is — do not move it below the fold.
- **Entity naming (strong)**: "Claude Code", "MCP", "markdown", "Git", "Google Docs", "Notion", "HackMD" all appear in body copy + headings + meta. This is exactly the entity soup an LLM needs to link Markland into the "agent-native document tools" concept cluster.
- **Schema coverage (strong, pre-verified)**: Organization + WebSite + SoftwareApplication on every page gives Gemini / Perplexity / ChatGPT web search the structured hook to cite Markland when someone asks about "MCP document tools".
- **Passage structure (mixed)**: `/quickstart` is good (5 sequential H2 steps — perfect "how to publish docs from Claude Code" passage shape). `/alternatives` hub is **bad** — the 5 competitor sections have no headings, so an LLM trying to answer "what are alternatives to Markshare.to" won't find a scoped passage to cite.
- **Thin trust pages (weak)**: an LLM evaluating Markland for E-E-A-T has nothing to work with on `/about`. Expect LLMs to hedge citations ("a small project called Markland claims...").

### Recommendations (ranked by AI-search ROI)

1. **Fix `/alternatives` hub headings** — cheapest, biggest GEO win. Per-competitor H2 unlocks 5 citable passages on one page.
2. **Expand `/about` to 250–300 words with a named founder + background** — unblocks citation confidence.
3. **Add an FAQ block to `/` and `/quickstart`** with 3–5 questions ("Is Markland free?", "Does it work with ChatGPT?", "How is it different from Git?"). Add `FAQPage` JSON-LD. Perplexity and AI Overviews disproportionately cite FAQ content.
4. **Add `Last updated: 2026-04-24` to all pages** — freshness is a GEO ranking factor for all three major AI engines.
5. **Add an author byline/signal sitewide** — needed before the domain moves to `markland.dev`; backlinks and citations both key off a named human.

---

## Overall SEO health: **7/10**

Technical foundation is strong (headers, schema, sitemap, canonicals, internal linking, mobile, lang — all pass). Content foundation is solid on `/`, `/quickstart`, and the 5 `/alternatives/*` pages which are genuinely differentiated. The three real drags are: (1) JSON 404, (2) the `/alternatives` hub competitor sections being div-wrapped instead of H2-wrapped, and (3) the E-E-A-T thinness across `/about` and the trust pages with no author/expertise signal anywhere. Fix those three and this goes to 9/10 without any new traffic strategy.
