# Sitemap + Robots.txt Findings — Markland

**Audit date:** 2026-04-24
**Target:** https://markland.fly.dev/sitemap.xml
**URLs in sitemap:** 13 (well under 50k limit)

## Verdict per check

| # | Check | Verdict | Notes |
|---|-------|---------|-------|
| 1 | Well-formed XML, sitemap.org schema | PASS | `xmllint` clean; correct `xmlns`; no deprecated `priority`/`changefreq` tags. |
| 2 | Canonical host, absolute URLs, 200 OK | PASS | All 13 URLs use `https://markland.fly.dev`, all absolute, all return 200 on GET. (HEAD returns 405 — cosmetic, Google uses GET.) |
| 3 | No disallowed or noindexed URLs | PASS | None of the 13 sitemap paths match any `Disallow:` prefix. No `<meta name="robots" content="noindex">` nor `X-Robots-Tag` on any sitemap URL. |
| 4 | No missing marketing pages | PASS | Sitemap covers `/`, `/quickstart`, `/explore`, `/alternatives` (+5 children), `/about`, `/security`, `/privacy`, `/terms` = 13 of 13 handcrafted marketing pages. Assets (`/favicon.svg`, `/og.png`, `/robots.txt`) correctly excluded. |
| 5 | `lastmod` is ISO 8601 | PASS | All entries `2026-04-24` (YYYY-MM-DD). See low-severity note below. |
| 6 | Quality-gate thresholds | PASS (N/A) | 5 `/alternatives/*` pages — well below the 30-page warning and 50-page hard-stop thresholds. No location pages. No programmatic doorway risk. |
| 7 | Robots.txt correctness | PASS w/ minor | `Sitemap:` line points to correct URL. GPTBot + CCBot blocked. Googlebot/Bingbot fall through to wildcard `Allow: /`. Every `Disallow:` maps to a real non-public prefix (`/api`, `/mcp`, `/admin`, `/settings`, `/dashboard`, `/inbox`, `/resume`, `/login`, `/verify`, `/setup`, `/device`, `/invite`, `/health`). |

## Observations + recommendations

1. **Uniform `lastmod` (low severity).** Every URL shares `2026-04-24`. Acceptable at launch (site genuinely shipped today), but once pages diverge in update cadence, wire `lastmod` to actual file mtime or last-publish timestamp. Identical dates long-term are ignored by Google and degrade the signal.

2. **HEAD returns 405.** Not a sitemap defect — Googlebot uses GET — but worth noting for uptime monitors. Low priority.

3. **Post-cutover checklist (already tracked in repo):**
   - After `markland.dev` DNS cutover, rewrite `<loc>` hosts and the `Sitemap:` directive to the new canonical.
   - Add 301s from `markland.fly.dev/*` to `markland.dev/*` so link equity (once it exists) transfers cleanly.
   - Then submit `https://markland.dev/sitemap.xml` to GSC.

4. **Consider adding additional AI crawlers** to the blocklist if you want parity with peers: `anthropic-ai`, `Claude-Web`, `Google-Extended`, `PerplexityBot`, `Bytespider`. Optional — current coverage (GPTBot, CCBot) handles the two highest-volume scrapers.

5. **No doorway-page risk.** The 5 `/alternatives/*` pages are handcrafted comparison pages, not programmatic location/industry swaps. No quality gates tripped.

## Summary

Sitemap and robots.txt are clean, schema-valid, and production-ready. No blocking issues. Address the uniform-`lastmod` nit after a few publish cycles, and expand the AI-crawler blocklist if desired.
