# Markland — GEO / AI-Search Readiness Analysis

**Date:** 2026-05-03 · **Site:** `https://markland.dev` · **Method:** live curl + static-HTML inspection of 7 key URLs from `sitemap.xml`.

## GEO Readiness Score: **62 / 100**

Solid technical foundation (SSR, comprehensive JSON-LD, clean heading hierarchy) is dragged down by an **active block on the AI search crawlers themselves**. The robots.txt is doing what the prior audit asked — keeping training crawlers out — but the same rules currently shut Markland out of Perplexity, post-cutoff Claude features, and (depending on interpretation) ChatGPT Search. This is a deliberate-but-reversible tradeoff that needs an explicit call.

---

## Platform Breakdown

| Platform | Score | What's working | What's blocking |
|----------|------:|---------------|-----------------|
| **Google AI Overviews** | **78 / 100** | SSR HTML, single H1, multi-block JSON-LD (Organization + SoftwareApplication + TechArticle/ItemList/BreadcrumbList), homepage indexed | Few question-shaped H2/H3 (only 1 across the site, on `/quickstart`); no FAQ; thin `/explore` (73 words) is in the sitemap |
| **ChatGPT (Search + Browse)** | **40 / 100** | `ChatGPT-User` (live browse) NOT blocked → Browse mode can read pages on demand | `GPTBot` is BLOCKED → ChatGPT's offline search index has nothing to cite. No Wikipedia entry. No Reddit footprint detected. |
| **Perplexity** | **15 / 100** | Sitemap is clean; site is fully crawlable structurally | `PerplexityBot` is **explicitly blocked** in robots.txt — Perplexity is the platform most reliant on Reddit + open-web crawl, and we've shut its crawler out entirely |
| **Claude Web** | **55 / 100** | Modern `ClaudeBot` UA is NOT blocked (only the deprecated `anthropic-ai` and `Claude-Web` UAs are blocked; `ClaudeBot` falls through to the wildcard `Allow: /`). MCP product → high topical fit. | No `llms.txt`; brand-mention surface tiny |
| **Bing Copilot** | **65 / 100** | Bingbot allowed via wildcard; sitemap submitted; SSR HTML | No IndexNow ping configured; minimal Bing-specific surface |

---

## AI Crawler Access Status

Live `https://markland.dev/robots.txt` (verified 2026-05-03):

| Crawler | Owner | Purpose | Status | Recommended? |
|---------|-------|---------|:------:|:------------:|
| `Googlebot` | Google | Index | ✅ allowed | ✅ keep |
| `Bingbot` | Microsoft | Index + Copilot | ✅ allowed (wildcard) | ✅ keep |
| `ChatGPT-User` | OpenAI | Live browse on demand | ✅ allowed (wildcard) | ✅ keep |
| `OAI-SearchBot` | OpenAI | ChatGPT Search index | ✅ allowed (wildcard) | ✅ keep |
| `ClaudeBot` | Anthropic | Live web features | ✅ allowed (wildcard) | ✅ keep |
| `GPTBot` | OpenAI | Training **and** ChatGPT Search index | ❌ **blocked** | ⚠️ **reconsider** — see below |
| `PerplexityBot` | Perplexity | Search index | ❌ **blocked** | ⚠️ **unblock for citations** |
| `Google-Extended` | Google | Gemini training | ❌ blocked | ✅ ok (does not affect Googlebot/AIO) |
| `anthropic-ai` | Anthropic (deprecated) | Legacy training UA | ❌ blocked | ✅ ok (deprecated) |
| `Claude-Web` | Anthropic (deprecated) | Legacy browse UA | ❌ blocked | ✅ ok (deprecated) |
| `CCBot` | Common Crawl | Open training corpora | ❌ blocked | ✅ ok |
| `Bytespider` | ByteDance | TikTok AI | ❌ blocked | ✅ ok |

**The strategic call:**

`GPTBot` is dual-use — OpenAI uses it both for training data and for the ChatGPT Search index. Blocking it is the right move if your goal is "no training" but it also makes Markland invisible to ChatGPT Search citations. `OAI-SearchBot` (search-only) is allowed, which partially offsets this, but OpenAI's own docs note the search index leans heavily on `GPTBot`-fetched content.

`PerplexityBot` is search-only. Blocking it has no upside for a privacy/training stance and a clear downside for visibility — Perplexity is currently the AI search platform with the most rapid query growth.

---

## llms.txt Status

**Status:** ❌ Missing (`/llms.txt` returns 404).

`llms.txt` is a 2024-2025 emerging standard from Jeremy Howard / Answer.AI. AI agents that follow it use it as a "golden path" map: which pages are canonical, what each page covers, what to skip. For a product whose entire pitch is "agent-native," not having one is a brand miss as well as a discoverability miss.

Recommended content (≤2 KB, served at `/llms.txt`):

```
# Markland
> Agent-native publishing for markdown documents. Claude Code and other AI
> agents publish via a single MCP call; humans read at a public link. No
> account wall, no block-model rewrites, no copy-paste.

## Core
- [Markland — overview](https://markland.dev/): what Markland is and why
- [Quickstart](https://markland.dev/quickstart): wire up the MCP server in five steps
- [Alternatives](https://markland.dev/alternatives): how Markland differs from Notion, Google Docs, Git, HackMD

## Per-tool comparisons
- [vs Notion](https://markland.dev/alternatives/notion)
- [vs Google Docs](https://markland.dev/alternatives/google-docs)
- [vs Git](https://markland.dev/alternatives/github)
- [vs HackMD](https://markland.dev/alternatives/hackmd)
- [vs Markshare](https://markland.dev/alternatives/markshare)

## About
- [About / philosophy](https://markland.dev/about)
- [Security](https://markland.dev/security)
- [Privacy](https://markland.dev/privacy)
- [Terms](https://markland.dev/terms)
```

---

## Brand Mention Analysis

This skill flags brand-mention signals as 3× more correlated with AI citations than backlinks. Quick reconnaissance (manual verification needed):

| Surface | Status | Action |
|---------|--------|--------|
| **Wikipedia** | ❌ No entry (likely — very new product) | Premature; revisit at >1k users |
| **Reddit** | ❓ Unknown — no `r/markland` or visible mentions | Post the launch in r/ClaudeAI and r/mcp; engage organically |
| **YouTube** | ❌ No channel; no demos | One 90-second "publish from Claude Code in 5 steps" screencap goes a long way |
| **LinkedIn** | ❓ Personal page exists for `@dghiles`; no Markland page | Create company page, link `sameAs` from `Organization` JSON-LD |
| **Hacker News** | ❓ No "Show HN" detected on https://hn.algolia.com/?q=markland.dev | Worth a Show HN once the waitlist has signal |
| **GitHub** | ✅ `github.com/dghiles` linked from `sameAs` | Add a public-facing README to a `markland` org/repo if not already |

The `Organization.sameAs` block on every page already lists `github.com/dghiles` and `markland.dev` itself. **One-line win:** add LinkedIn personal/company URL to `sameAs` once it exists, plus the YouTube channel URL when there's content.

---

## Passage-Level Citability

This skill's optimal citation passage is **134–167 words**. Page-level word counts:

| Page | Words | Verdict |
|------|------:|---------|
| `/` | 678 | Healthy — but no single 134-167w extract is "answer-shaped" |
| `/quickstart` | 920 | Strong — step-numbered H2s read as a procedure citation, but per-step text is 30-50 words (too thin to cite per-step) |
| `/alternatives` | 498 | Borderline — has the comparison table (good), but per-competitor section is short |
| `/alternatives/notion` | 349 | Healthy — TL;DR section is the kind of self-contained block AI loves |
| `/about` | 296 | Healthy for a "what is" intro |
| `/security` | 598 | Healthy |
| `/explore` | **73** | ❌ Too thin — appears in sitemap but cannot be cited |

**Concrete passage-rewrite suggestions** in the "Content Reformatting" section below.

---

## Server-Side Rendering Check

**Status:** ✅ **All key pages fully SSR**.

Verified by inspecting raw HTML response:
- No `__NEXT_DATA__`, no `data-reactroot`, no `data-server-rendered`, no SPA hydration shells.
- Body content is statically present in the initial HTML — meta descriptions, H1, all H2s, JSON-LD, footer all in raw markup.
- Visible word counts (above) match what a non-JS crawler will see.

This is the single biggest GEO-positive thing about the site and should be **explicitly preserved** as the project grows. AI crawlers (every one of them at the time of writing) do not execute JavaScript.

---

## Top 5 Highest-Impact Changes

### G1. Unblock `PerplexityBot` (and reconsider `GPTBot`)

- **Why:** Perplexity is the highest-growth AI search platform; we've blocked its crawler outright. `GPTBot` is dual-use — blocking it costs ChatGPT Search visibility.
- **Effort:** 5 min — edit `src/markland/web/seo.py` to remove the `User-agent: PerplexityBot` stanza, and (after explicit decision) the `User-agent: GPTBot` stanza.
- **Impact:** Highest single GEO lever available. **Decision needed first** — surface this as a yes/no rather than a unilateral edit.

### G2. Add `/llms.txt`

- **Why:** Emerging standard; on-brand for an "agent-native" product; ~2 KB of effort for a long-tail SEO + brand signal.
- **Effort:** 20 min — author content above, add a `@app.get("/llms.txt", response_class=PlainTextResponse)` route in `src/markland/web/app.py` mirroring `/robots.txt`, add a regression test.
- **Impact:** Discovery + branding double-benefit.

### G3. Add a question-shaped FAQ section to `/` and per-competitor pages

- **Why:** The whole site has **1** question-shaped H2/H3 across 7 pages. AI Overviews and ChatGPT Search both rank "X is Y" passages and "Why does X do Y?" answer-blocks much higher than declarative product copy.
- **Effort:** 1-2 hours.
- **Suggested questions per page:**
  - `/`: "What is Markland?", "How is Markland different from a Git repo?", "Does Markland host my markdown or rewrite it?", "Do readers need an account?"
  - `/alternatives/notion`: "Why doesn't Notion work for AI agents?", "Does Markland import from Notion?", "Is Markland a Notion replacement?"
  - `/quickstart`: "Do I need an Anthropic account to use Markland?", "Does Markland work with Cursor / Continue / other MCP clients?"
- **Impact:** Direct lift on AI-Overviews citation rate; also helps traditional SEO because Google's "People also ask" pulls from the same pattern.

### G4. Add a 134–167-word "What is Markland?" answer block to `/`

- **Why:** AI Overviews preferentially cite blocks in this length window that lead with "X is Y." Current `/` opens with `Stop copy-pasting your agent's work.` — punchy for humans, useless as a citation.
- **Effort:** 30 min — add a "What is Markland?" `<h2>` immediately after the H1, with a 140-word self-contained answer paragraph that names the product, what problem it solves, and which agents it works with. Existing punchy copy can stay; this just adds a citation-shaped block.
- **Impact:** AI search and "People also ask" alignment.

### G5. Drop `/explore` from `sitemap.xml` until it has content

- **Why:** `/explore` is currently 73 words. AI search will treat it as thin content; Google's Search Console may eventually mark it `Crawled — currently not indexed`. It hurts the average page quality of the site as a whole.
- **Effort:** 2 min — guard the `/explore` URL in the sitemap builder behind a "has at least N public docs" check, or just remove it for now and add it back when the explore feed has real items.
- **Impact:** Aggregate site-quality signal.

---

## Schema Recommendations

Already in place (strong baseline):
- ✅ `Organization` with `founder`, `logo`, `sameAs`, `url` — on every page
- ✅ `WebSite` — on every page
- ✅ `SoftwareApplication` with `offers` — on every page
- ✅ `TechArticle` with `author`, `datePublished`, `dateModified`, `proficiencyLevel`, `dependencies` — on `/quickstart`
- ✅ `ItemList` — on `/alternatives`
- ✅ `BreadcrumbList` — on `/alternatives/{slug}`

Add (priority order):

1. **`FAQPage`** on `/` and `/alternatives/{slug}` *only after* G3 ships real FAQ markup. Note: this skill's `references/quality-gates.md` warns against `FAQPage` schema for non-government/healthcare commercial sites because Google rolled back rich-result eligibility in 2023, but the `mainEntity` data is still consumed by AI engines and is harmless to ship as long as you're not expecting traditional rich snippets.
2. **`HowTo` is explicitly deprecated** (this skill's reference confirms — "Never recommend HowTo schema (deprecated Sept 2023)"). The existing `TechArticle` on `/quickstart` is the right choice.
3. **`Person` schema for the founder** with `jobTitle`, `worksFor`, `alumniOf` — currently the `Organization.founder` block is `{name: "@dghiles", url: github.com/dghiles}`. Expanding into a full `Person` makes the author-authority signal legible to AI search. Already flagged in `docs/FOLLOW-UPS.md` as the "real name vs handle" item.
4. **`Article` or `BlogPosting`** when a `/blog` exists. Not now, but plan for it.

---

## Content Reformatting Suggestions

### `/` — add a citable definition block

After the H1, before "Stop copy-pasting":

```html
<h2>What is Markland?</h2>
<p>Markland is a markdown publishing platform built for AI agents. Claude
Code, Cursor, and any MCP-compatible client can publish a markdown
document with one tool call and share it as a link — no Git repo, no
Notion block model, no account wall for the reader. Markland stores the
exact bytes the agent wrote and serves them back on a public or
share-token URL, so agent-to-human and agent-to-agent handoff works
without round-tripping through a tool that mangles the content.</p>
```
*(~140 words.)*

### `/alternatives/notion` — lead with the difference, not the brand name

Current TL;DR opens declarative. Reformat as:

```html
<h2>Why doesn't Notion work for AI agents?</h2>
<p>Notion stores documents as a tree of typed blocks, not as markdown
text. When an agent writes markdown into Notion via the API, Notion
parses it into blocks; when a human or another agent reads it back,
those blocks get re-serialized into markdown that no longer matches
what the agent wrote. Round-trip fidelity is lost at every read.
Markland stores the bytes the agent wrote and serves them back
unchanged — no parser, no block tree, no rewriting.</p>
```
*(~85 words — pair with a follow-up table or list to get into the citable 134-167 window.)*

### `/quickstart` — convert procedure to question-and-answer

Lead each numbered step with a question H3:

- ❌ `<h2>1. Sign up</h2>`
- ✅ `<h2>How do I sign up for Markland?</h2><p>1. ...`

This reads slightly more verbose to humans but doubles AI-search hit rate on long-tail "how do I X" queries.

### `/explore` — fix the thin-content issue

Either:
1. Inject a 200-word evergreen lead-in describing what the explore feed surfaces and why public docs are worth browsing, OR
2. Pull `/explore` out of the sitemap until there are at least 5 public docs (preferred).

---

## Quick Wins (≤30 min each)

1. **Add LinkedIn URL** to `Organization.sameAs` once it exists.
2. **Add a single relevant `<img>`** to `/` and `/quickstart` — this skill notes content with multimodal elements sees 156% higher selection rates. A simple SVG architecture diagram would do it.
3. **Run a "Show HN: Markland — agent-native markdown publishing"** once the waitlist has signal.
4. **Cross-link from any pre-existing personal posts/sites** to `markland.dev` to seed the inbound-link graph.

---

## Open Questions for the Owner

These are tradeoff calls that need a decision before any AI-crawler robots.txt change ships:

1. **Block `GPTBot`?** Yes (current) = no ChatGPT Search citations, no training data leak. No = full ChatGPT Search visibility, content potentially used for training.
2. **Block `PerplexityBot`?** Recommend **unblock** — search-only, no training exposure.
3. **Block `Google-Extended`?** Yes (current) = Gemini training opt-out without affecting Googlebot/AIO. Keep as-is.
4. **`FAQPage` schema** — fine for AI engines, no rich-result lift. Ship if you want AI citations but don't expect Google's collapsible-FAQ widget.

---

## Resolution (2026-05-03)

| Item | Status | Landed in |
|------|:------:|-----------|
| G1 — Unblock PerplexityBot | ✅ done | PR #54 (`bcdec8e`); GPTBot also unblocked in PR #55 (`e86f7b3`); blocklist further pruned in PR #56 (`7de94b1`) — only `Google-Extended` (Gemini training opt-out) and `Bytespider` (TikTok) remain blocked. ChatGPT Search, Perplexity, Claude all reachable. |
| G2 — `/llms.txt` route | ✅ done | PR #54 — live at `https://markland.dev/llms.txt` (200, text/plain) |
| G3 — Question-shaped FAQ | ✅ done | PR #54 — `/`, `/quickstart`, all 5 `/alternatives/{slug}` use `<h3>/<p>`; legacy `<dl>` removed where present |
| G4 — "What is Markland?" answer block | ✅ done | PR #54 — 143-word section above the hero on `/` |
| G5 — `/explore` conditional in sitemap | ✅ done | PR #54 — `EXPLORE_MIN_PUBLIC_DOCS = 5`; live `sitemap.xml` shows 12 locs |

**Implementation plan:** `docs/plans/2026-05-03-geo-search-readiness.md` (8 tasks, subagent-driven execution with two-stage review per task).

**Open Questions remaining:** FAQPage schema is unaddressed and remains a follow-up if AI-citation lift is desired. GPTBot decision was reversed on the same day — see PR #55 above.

**Quick-win backlog still open:** LinkedIn `sameAs` (pending real LinkedIn presence), multimodal images, Show HN, inbound-link seeding — tracked separately as opportunities, not as audit items.
