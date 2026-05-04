# Markland — SEO Strategy

**Date:** 2026-05-03 · **Stage:** Pre-GA public beta, ~13 indexable URLs, single-digit waitlist signups
**Domain:** `https://markland.dev` (cutover ~5 days ago from `markland.fly.dev`)
**Skill source:** `claude-seo:seo-plan` (SaaS template, scaled down for current stage)

---

## TL;DR — the next 90 days

1. **Don't build more SEO surface yet.** You have 13 URLs, all indexed, all quality-floor compliant after today's audit work. Adding more thin pages now would dilute the signal. Focus on **content depth + brand mentions** instead.
2. **The single highest-leverage move is shipping a `/blog` (or `/notes`) feed with 4-6 long-form posts** that target the actual queries your audience types: "agent-native publishing," "MCP document server," "share Claude Code output." Today you have ~13 marketing pages and zero educational content — that's the gap.
3. **Brand mentions outrank backlinks 3× for AI search citations** (per the GEO analysis we just did). Your inbound-link graph is empty; one Show HN, one r/ClaudeAI post, and one YouTube screencap would do more for AI-citation surface than 50 link-building emails.

---

## 1. Discovery (synthesis)

### Product

Markland is an MCP document publishing platform for AI agents. Claude Code, Cursor, Codex, Claude Desktop, and any other MCP-compatible client publishes a markdown document with one tool call (`markland_publish`) and shares it as a public or share-token URL. Readers open the link in any browser — no account, no Notion block model, no Git repo.

### Audience

Three concentric rings, ordered by current addressability:

1. **Inner ring (today):** developers actively using Claude Code (or Cursor / Codex) who already write CLAUDE.md, agent-authored specs, plans, research notes, and want to share them without copy-pasting into Slack/Notion/email.
2. **Middle ring (3–6 months):** developers using any MCP-compatible client to produce markdown output — design docs, RFC drafts, retrospectives, agent transcripts.
3. **Outer ring (6–12 months):** non-developer roles ("agent-curious" PMs, designers, founders) who delegate work to AI agents and need a way to receive/share the output.

The strategy below targets the inner ring almost exclusively for the next 6 months. Don't try to talk to anyone else yet.

### Goals (12-month, realistic)

| Metric | Today (2026-05-03) | 90-day | 6-month | 12-month |
|--------|-------------------:|-------:|--------:|---------:|
| Indexed pages (GSC) | 1 confirmed | 13 | 30 | 80 |
| Branded query rank for "markland" | not in top-100 (town namesake) | top-30 | top-10 | top-3 |
| Non-branded informational rank ("MCP document server", "share markdown agent") | not ranking | top-50 for ≥3 queries | top-20 for ≥5 | top-10 for ≥10 |
| ChatGPT Search citations / mo | 0 (just unblocked GPTBot today) | 5+ | 25+ | 100+ |
| Perplexity citations / mo | 0 (just unblocked) | 5+ | 25+ | 100+ |
| Inbound referring domains | 1 (your GitHub) | 5 | 15 | 40 |
| Waitlist signups / mo | (current) | 2× | 5× | 15× |

The branded-query rank is hard because **Markland is also the name of an actual town** (and other namesakes) — Google has competing intent. Either accept the climb or consider a domain/brand differentiator (e.g., always pair with "MCP" in titles — already doing this).

### Constraints

- One-person team (you), so anything that takes >2 hours/week of marketing-flavored work won't survive
- No paid acquisition budget today; every channel must be organic-or-earned
- Beta software with rapid iteration — strategy must tolerate the product changing under the SEO surface

---

## 2. Competitive Analysis

### Direct competitors (already mapped on `/alternatives`)

| Competitor | Their SEO strength | Where they leave room for Markland |
|------------|-------------------|-----------------------------------|
| **Notion** | Massive (notion.so 92 DR, 100k+ ranking pages) | Block-model rewriting; not agent-native; account wall for readers |
| **Google Docs** | Owned-channel dominant, no need for SEO | Not markdown-first; not MCP-callable; rich-text rendering loses fidelity |
| **GitHub Gists** | gist.github.com indexed broadly | Auth required for private; no MCP server; PR workflow overkill for one-doc shares |
| **HackMD / HedgeDoc** | Niche but technical-developer cred | Live-collab focus, not agent-native publishing |
| **Markshare.to** | Tiny footprint | CLI-only, no MCP, single-user |

### Indirect (queries you'll compete on)

- **"MCP server" / "MCP document"**: emerging category, very few sites have indexable content yet → **strong opportunity** for a few well-written pages to capture early share
- **"share markdown link"**: dominated by Gist, Pastebin, GitHub raw URLs
- **"Claude Code workflow"**: dominated by Anthropic docs, dev.to posts, YouTube; opportunity in long-tail
- **"agent-native"**: nascent term, very few sites use it; **opportunity to define the term**

### Domain authority gap

Markland today: ~zero (~5-day-old domain). Every direct competitor is 80+ DR. Closing that gap takes years of consistent linking. **Don't try.** Compete on:
- Long-tail queries with specific intent ("publish from Claude Code", "share doc from MCP")
- AI-search citations (training-data + search-time crawls — already configured today)
- Brand mentions in developer communities (HN, Reddit, dev.to, YouTube)

---

## 3. Architecture (current vs. target)

### Today (post 2026-05-03 audit)

```
markland.dev/
├── /                              ← landing (hero + "What is Markland" + FAQ)
├── /quickstart                    ← 5-step MCP setup + FAQ
├── /alternatives                  ← hub
│   ├── /alternatives/notion
│   ├── /alternatives/google-docs
│   ├── /alternatives/github
│   ├── /alternatives/hackmd
│   └── /alternatives/markshare
├── /about
├── /security
├── /privacy
├── /terms
├── /robots.txt
├── /sitemap.xml                   ← 12 URLs (excludes thin /explore)
├── /llms.txt                      ← agent-readable site map
└── /404 (branded HTML)
```

Plus: `/explore` (gated — re-enters sitemap once ≥5 public docs).

### Target (12-month)

Don't aggressively expand the marketing surface. Add only what serves intent:

```
markland.dev/
├── (everything above stays)
├── /docs                          ← MCP tool reference (currently inside /quickstart)
│   ├── /docs/markland-publish
│   ├── /docs/markland-grant
│   └── ... (one page per MCP tool, target "/MCP-tool-name" long-tail)
├── /blog                          ← educational content; the SEO scale-up
│   ├── /blog/agent-native-publishing
│   ├── /blog/sharing-claude-code-output
│   ├── /blog/mcp-explained-for-developers
│   ├── /blog/markdown-vs-block-model
│   └── ... (one solid post / 2 weeks)
├── /alternatives/cursor           ← when Cursor users land
└── /integrations                  ← per-MCP-client pages
    ├── /integrations/claude-code
    ├── /integrations/cursor
    ├── /integrations/codex
    └── /integrations/claude-desktop
```

**Notably absent on purpose:** No pricing page until a paid tier exists. No `/case-studies` until you have 3+ named users with quotable wins. No `/customers` page. Adding empty categorical pages dilutes the site's quality signal — `/explore` was already a near-miss on this.

### Internal linking rule

Every blog post links to:
- The relevant `/alternatives/{slug}` if the post compares with a competitor
- `/quickstart` (single high-intent CTA target)
- One related blog post when 2+ exist

Every `/alternatives/{slug}` already links to `/quickstart` and `/` (waitlist). That's enough — don't add a sidebar nav.

---

## 4. Content Strategy

### The 4-6 anchor blog posts (next 90 days)

Pick 4-6 of these to write before any other marketing work. Each targets a specific search intent and answers a question Anthropic's docs / Cursor's docs / GitHub's docs do not.

| # | Working title | Target query | Why now | Effort |
|---|--------------|--------------|---------|--------|
| 1 | **What is agent-native publishing?** | "agent-native publishing", "agent-native" | Defines the category; AI-citation magnet | 3h |
| 2 | **How to share Claude Code output without copy-pasting** | "share Claude Code output", "publish from Claude Code" | High-intent, low-competition | 2h |
| 3 | **Why markdown round-trips break in Notion (and what to do instead)** | "notion markdown export", "markdown to notion" | Drafts off `/alternatives/notion`; long-tail capture | 2h |
| 4 | **MCP, explained for developers** | "what is MCP", "model context protocol" | Foundational; useful for any agent-curious dev | 3h |
| 5 | **Five things to publish to Markland from Claude Code** | "claude code workflow", "claude code recipes" | Use-case content; converts visits to signups | 2h |
| 6 | **Building a public CLAUDE.md library** | "CLAUDE.md examples", "share CLAUDE.md" | Niche but exact-match intent | 2h |

Total: ~14 hours of writing for 6 posts. At one post / 2 weeks, that's a 12-week run.

### E-E-A-T plan

You already have:
- ✅ Real author byline (`@dghiles`, `rel="author"` on every page)
- ✅ Last-updated dates
- ✅ `Organization.founder` JSON-LD with GitHub link

Add over next 6 months:
- **Personal "About the author" sub-page** with credentials (GitHub, prior work, why you built Markland) — `Person` schema
- **One named external mention** of you/Markland on a third-party site (HN comment, dev.to guest post, podcast, YouTube guest spot)
- **LinkedIn presence** (currently absent), then add to `Organization.sameAs` and the founder `Person.sameAs`

### Content cadence

Realistic for one-person operation: **one new long-form post / 2 weeks**. Stick to that. Eighteen posts in 9 months is meaningful body of work; trying for weekly will collapse by month 2.

---

## 5. Technical Foundation

Mostly in place. Status:

| Layer | Status | Notes |
|-------|--------|-------|
| SSR HTML | ✅ Fully | Single biggest GEO win |
| Schema (Org, WebSite, SoftwareApp, TechArticle, ItemList, BreadcrumbList) | ✅ Comprehensive | Add `Person` (founder) + `Article`/`BlogPosting` when `/blog` ships |
| Sitemap | ✅ Live, 12 URLs | Auto-extends as competitors / blog posts added |
| `/llms.txt` | ✅ Live | Update when `/blog` and `/docs` ship |
| `robots.txt` | ✅ Pruned to training-only blocks | All AI search bots allowed |
| GSC verified | ✅ | Indexing health check tracked in `markland-ejw` (Tue 5/5) |
| Core Web Vitals | ⚠️ Unknown | Run `claude-seo:seo-google` once GSC has 28 days of CrUX data |
| Drift baseline | ✅ Captured today | 12 pages snapshotted to `~/.cache/claude-seo/drift/baselines.db` |
| Mobile-first | ✅ | Static HTML, responsive |
| HTTPS + HSTS | ✅ | Security headers middleware |

**Things to add when content scales:**
- `/blog/{slug}` template with `Article` JSON-LD + `Person` author
- RSS/Atom feed at `/blog/feed.xml` (single line in FastAPI; high-leverage for syndication)
- Open Graph image generator for blog posts (`claude-seo:seo-image-gen` skill — uses Gemini, requires banana extension)

---

## 6. Implementation Roadmap

### Phase 1 — Foundation (already done, today)

✅ Audit work G1-G5, L1-L5 all shipped. Drift baseline captured. GSC verified. Skip ahead.

### Phase 2 — Content launch (weeks 1-12)

**Week 1-2:**
- Pick 4 of the 6 anchor blog posts above (recommend 1, 2, 4, 5).
- Spec the `/blog` route + `Article` JSON-LD + `Person` author schema.
- Ship `/blog` infrastructure (single FastAPI route + Markdown rendering — same stack as `/d/{token}`).

**Week 3-4:** Write + publish post #1 ("agent-native publishing"). Submit to GSC URL Inspection. Cross-post Link to:
- HN as Show HN (only when you have 1-2 unique data points to share)
- r/ClaudeAI
- dev.to (canonical link back to markland.dev)

**Week 5-12:** Ship one post / 2 weeks. After post #2, add /blog to `/llms.txt`.

### Phase 3 — Authority building (months 4-6)

- Submit any post that hits ≥5 inbound links to "Hacker News" (timing matters; weekday morning EST)
- Reach out to 3 podcasts about Claude Code / agent workflows; offer to be interviewed
- Get listed in `awesome-mcp` GitHub list (and similar curation lists)
- Write one guest post for a developer publication (dev.to, freeCodeCamp, daily.dev) with link back

### Phase 4 — Scale (months 7-12)

Reassess. By month 7 you'll have:
- ~12 blog posts published
- Real GSC data showing which queries actually convert
- Either traction or honest signal that the positioning needs a pivot

If traction:
- Expand `/integrations/{slug}` per supported MCP client
- Open `/case-studies` if 3+ named users exist
- Consider `/comparison-page` to a non-MCP tool that emerged as a competitor

If no traction:
- Don't double down on SEO. Reread Phase 0/1 of dogfood plan and re-evaluate positioning.

---

## 7. KPI Targets (revisited)

Already in §1 Discovery — the 12-month grid. Re-check at end of each phase:

- **End of Phase 2 (week 12):** indexed pages 25+, ChatGPT/Perplexity citations >0/mo (any volume), inbound domains ≥3.
- **End of Phase 3 (month 6):** non-branded query rank top-20 for ≥5 queries, citations 25+/mo, ≥1 podcast/guest-post inbound.
- **End of Phase 4 (month 12):** see grid in §1.

---

## 8. Tracking and review cadence

- **Weekly (5 min):** `/claude-seo:seo-drift compare https://markland.dev/` — catches accidental regressions from product changes.
- **Bi-weekly (15 min):** GSC Performance tab review — top queries, top pages, CTR trend.
- **Monthly (30 min):** Full `bd ready` sweep + check `markland-ejw`-style follow-ups; re-baseline the drift db; check Umami top-pages report.
- **Quarterly (1h):** Re-read this strategy doc; cross out items shipped; update KPIs against actuals; decide if a re-plan is warranted.

---

## 9. Risk register

| Risk | Likelihood | Impact | Mitigation |
|------|:---------:|:------:|------------|
| Markland-the-town outranks Markland-the-product on branded queries | High | Med | Always pair "Markland" with "MCP" in title/description; build branded-search volume via blog posts that say "Markland" |
| MCP standard fragments or gets superseded | Med | High | Position as "agent-native publishing" first, "MCP server" second (the value prop is the publishing flow, not the protocol) |
| Anthropic ships a competing first-party feature | Med | High | Lean into the multi-client story (Cursor, Codex, custom agents); be clearly client-agnostic |
| Single-author E-E-A-T cap | Med | Med | Get a second contributor named on at least one post within 6 months |
| Personal-name bias (`@dghiles`) on `Organization.founder` reduces rich-card fitness | Low | Low | Already noted in `docs/FOLLOW-UPS.md`; switch to real name when ready to publish it |

---

## 10. What this strategy explicitly does NOT do

- No "publish 50 location pages" play (irrelevant — software, not local)
- No keyword stuffing or content farming
- No paid SEO tools (DataForSEO etc.) until there's revenue to justify; the free tier of GSC + the `claude-seo` skill collection is enough for now
- No backlink-buying, no PBNs, no link exchanges
- No product launches gated on SEO readiness (ship the product, the SEO follows)

---

## Appendix A — How this connects to existing audits

| Doc | What it covers | Relationship to this strategy |
|-----|---------------|-------------------------------|
| `docs/audits/2026-04-24-seo-audit/ACTION-PLAN.md` | C/H/M/L items from initial audit | All ✅/❌ closed as of today |
| `docs/audits/2026-05-03-geo-analysis/GEO-ANALYSIS.md` | AI-search readiness (G1-G5) | All ✅ shipped via PR #54-56 |
| `docs/plans/2026-05-03-geo-search-readiness.md` | Implementation plan for G1-G5 | Closed |
| **`docs/audits/2026-05-03-seo-strategy/SEO-STRATEGY.md`** | This doc — forward-looking 12-month plan | Active |

## Appendix B — Open follow-up beads

- `markland-ejw` (defer 2026-05-05) — GSC indexing health check
- `markland-fjd` + 4 children (defer 2026-05-15) — 14-day soak window
- `markland-n8v` (P4) — fix stale docstring
- (Open question, no bead) — FAQPage schema decision

## Appendix C — What to file as new beads after reading this

1. **`/blog` infrastructure spec** (Phase 2 week 1-2) — FastAPI route + Article JSON-LD + Person author + RSS feed. P3.
   ✅ filed as `markland-xgj`, **shipped same day in PR #63 (`c9a6c16`)**.
2. **Anchor blog post #1: "What is agent-native publishing?"** — P3, blocked by #1.
   ✅ filed as `markland-380`, **shipped in same PR #63 — live at https://markland.dev/blog/agent-native-publishing**.
3. **Author "About" page with Person schema** — P4, do alongside post #1.
   ✅ filed as `markland-0yy` (still open). Inline `Person` schema is embedded on each blog post pending the dedicated `/about/dghiles` page; canonical `@id` already established.
4. **LinkedIn presence + add to Organization.sameAs** — P4, no urgency.
   ✅ filed as `markland-xfc` (still open).

**Phase 2 progress as of 2026-05-04:** the first blog post is live one day after this strategy was written. Cadence target is one post / 2 weeks; next post (~2026-05-17) should be #2 from §4 ("How to share Claude Code output without copy-pasting") or #4 ("MCP, explained for developers") depending on which lands the better hook.
