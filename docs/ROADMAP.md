# Markland Roadmap

Living document. Strategic frame at the top; tactical lanes (Now / Next /
Later) are the working surface; "Shipped" at the bottom is the historical log
organized by track. Update on every meaningful state change. Tactical detail
that doesn't fit the lane summaries lives in `docs/FOLLOW-UPS.md`.

## Positioning

Markland is **a shared knowledge surface where humans and agents are equal editors.** It sits in the gap between two tools that don't fit agent-era collaboration:

- **Git** — too complicated and overpowered. Branches, merges, commits, and discipline make sense for engineering teams. They're overkill for casual collaboration and alien to agents.
- **Google Docs** — not agent-friendly. Cursors, comments, and suggest-mode are human-shaped. There's no structured surface an agent can write to as a first-class citizen.

Collaboration is no longer just human-to-human. It's also **machine-to-machine** and **human-to-machine**. Markland is built for that three-way model: your agents, a friend's agents, and fully automated agents all reading and writing the same knowledge via MCP — with no merge conflicts to resolve by hand and no "paste this into the doc" handoff.

### The wedge

The sharpest MVP framing is autonomy: **"your agent publishes without asking you."** That's the graspable, demo-able behavior. The bigger idea — shared state across many agents and their owners — is the reason it matters, and the direction v2+ expands into.

### Tagline

Current selection: **"Shared notes for you and your agents."** — collaboration-forward, works for readers who don't know what MCP is. Bench of A/B candidates: [tagline-candidates.md](tagline-candidates.md).

---

## Where we are (2026-05-03 PM)

Live at **`https://markland.dev`**. Heavy day of shipping since this morning's
refresh. **GEO batch G1-G5 shipped** (PR #54, #55, #56) — robots.txt
pruned to training-only blocks (Perplexity + ChatGPT Search + Claude Web
all reachable now), `/llms.txt` live, question-shaped FAQ blocks across
`/` + `/quickstart` + every `/alternatives/{slug}`, 143-word "What is
Markland?" answer block above the hero, `/explore` dropped from sitemap
until it has content. **GEO posture decision: made + executed** —
Markland is now optimized for AI search engines, not blocked from them.
**Magic-link single-use enforcement shipped** (PR #59) — closes the
15-min capture window flagged in the concerns review and on
`/security`'s post-beta hardening list. **Admin metrics expansion
shipped** (PR #53) — `markland_admin_metrics` now returns a 19-key
funnel + totals snapshot. **Seed content live** (PR #60) — 9 demo docs
(6 admin-published explainers + 3 agent-published from "Markland Bot"),
bulk-publish script, agent-provisioned at deploy. The agent-to-agent
positioning now has a *visible* surface on `/explore` instead of being
abstract. **Admin runbook + helper scripts** (PR #57, #58) productized
the bag of one-off SQL queries used during cutover. **Fresh strategic
input:** two strategy docs landed today.
`docs/specs/2026-05-03-monetization-strategy-design.md` — 4-tier ladder
(Free / Pro / Team / Enterprise) targeting **$25K MRR within 12
months**, per-workspace base + per-human-seat expansion, agent-
operations metered overage as a future lever. Awaiting review before
plan-writing. `docs/audits/2026-05-03-seo-strategy/SEO-STRATEGY.md` —
90-day SEO plan: don't build more SEO surface yet (13 URLs is enough),
ship `/blog` + 4-6 anchor long-form posts, lean on brand mentions over
backlinks for AI-citation surface, drift-monitor weekly. Explicit
non-goals enumerated in the new "Non-goals (current)" section below.

One MCP audit plan left — Plan 7 (Phase B deprecation/removal of 4
shims, window opens 2026-05-31). Code-complete on the v1 build (10
plans, 864 tests).

---

## Now

Active or imminent. Items here have a plan or a clear next action.

- **Monetization strategy review + plan-write** — design spec landed at `docs/specs/2026-05-03-monetization-strategy-design.md`: 4-tier ladder (Free / Pro / Team / Enterprise), per-workspace + per-human-seat expansion, agent-operations metered overage reserved as a future lever, $25K MRR target in 12 months. Next move: review, decide tier prices + workspace/seat caps, then write the implementation plan (Stripe wiring, gates, billing UI, marketing pricing page).
- **Pre-release security review** — beads `markland-06e` (P1). Multi-agent security review across the live build before broader launch. Should bundle remaining hardening items (visibility-change rail, agent-edit grant safety rails) into a single review pass.
- **MCP audit Plan 7 — Phase B deprecation/removal** — opens 30 days after the `mcp-audit-axis-5-released` tag (laid 2026-05-01, so window opens **2026-05-31**). Removes 4 deprecation shims: `markland_set_visibility`, `markland_feature`, `markland_set_status`, `markland_clear_status`. Plan: `docs/plans/2026-04-27-mcp-phase-b-deprecation-removal.md`.
- **Install/onboarding flow simplification** — Option 1 shipped (PR #12 + #13). Remaining: (2) prefill `user_code` via `/device?code=…` (route already supports it — runbook needs to construct the link); (3) single-link install — CLI runbook generates one `/device?code=…` URL so sign-in + code-entry happen on the same page; (4) skip device flow for browser-first users — sign in, hit "Connect Claude Code", copy one-shot token from `/me/tokens` into `claude mcp add`. Plan `docs/plans/2026-04-24-setup-install-ux-fix.md`. Worth a brainstorm pass on (2)-(4) before launch — right answer depends on whether the primary install audience is browser-first humans or CLI-first agents.
- **Agent-edit grant safety rails** — granting `edit` to another agent today carries unsurfaced risk (prompt-injected edits, accidental overwrites, polluted project memory) and the grant UI/MCP surface doesn't show the consequences. Two angles: (a) `/quickstart` + grant UI default-recommend `view` for cross-principal agent grants and require an explicit gesture for `edit`; (b) grant-confirmation copy spells out "this lets that agent rewrite the doc body and revision history." Brainstorm — sourced from the 2026-05-03 third-party concerns review.
- **`/blog` infrastructure + Phase 2 content launch** — SEO strategy at `docs/audits/2026-05-03-seo-strategy/SEO-STRATEGY.md` says the single highest-leverage move is a `/blog` (or `/notes`) feed with 4-6 anchor long-form posts. Recommended starters: "What is agent-native publishing?", "How to share Claude Code output without copy-pasting", "MCP, explained for developers", "Five things to publish to Markland from Claude Code". Cadence: one post / 2 weeks. Prerequisites: `/blog` route + `Article` JSON-LD + `Person` author schema + RSS feed. Plan-pending.

## Next

Queued. The big security/analytics/MCP-axis batches all landed; what's
left is launch-readiness polish.

- **Phase 0 dogfooding walkthrough** against live deploy — plan: `docs/plans/2026-04-28-phase-0-dogfood.md` (operationalizes `docs/runbooks/phase-0-checklist.md`). Resend verified, magic-link tested end-to-end — fully unblocked.
- **CSRF on save routes** — `/d/{t}/fork`, `/d/{t}/bookmark`, `DELETE /d/{t}/bookmark` accept plain form/fetch with `SameSite=Lax`. First user-authored mutating POSTs in the app; ship before any real users. No plan yet — small.
- **Sentry DSN + alert wiring** — plan: `docs/plans/2026-04-28-sentry-dsn-alerts.md`. Code path lives (`config.sentry_dsn` + conditional init in `run_app.py`); operator action is provisioning the DSN secret and wiring the three alerts (5xx spike, ConflictError spike, EmailSendError spike).
- **Soak-window analytics check** — beads `markland-fjd` (2 weeks post-launch): pull Umami stats + `/admin/metrics` 14d funnel snapshot + cross-reference signups vs Umami sessions, post a 1-message summary.
- **Self-service deletion** — `/privacy` line 38 already promises "before GA": doc deletion (doc + revisions + grants) and account deletion (magic-link records + agent tokens). Currently "reply to any email and a human will process." External evaluators read this as a "hold off, beta-only" signal — closing it removes a concrete trust friction. No plan yet.
- **Formal privacy policy** — `/privacy` line 11 says "a formal privacy policy will be published before general availability." Today's page is a working summary, which reads as deliberately stub-y to outside evaluators. Promote to a real policy (data inventory, retention, sub-processors, jurisdiction, contact).
- **Sharpen agent-to-agent positioning** — third-party eval flagged `markland_grant` to another agent ID as the most interesting differentiator; current homepage treats it as a footnote. Add an above-fold or near-fold use-case block: "agent-to-agent coordination — architect agent publishes plan, QA agent appends test report, you read one doc instead of scraping terminal logs." Brainstorm — touches landing copy + possibly a `/explore`-adjacent example.
- **Visibility-change safety rail** — today `markland_publish` accepts `public=true` in one tool call, so a casually-worded prompt can flip a doc public without a human gesture. Two-step it: `markland_publish` ignores `public=true` (defaults private), and a separate `markland_set_visibility` (already exists) is the only way to flip. Surface the visibility change as a flash on next page render + bold audit-log entry. Sourced from 2026-05-03 third-party concerns review.
- **Backup RPO/RTO commitment** — `/privacy` line 43 says backup rotation cadence is "still being tuned during beta." Pick numbers (Litestream/R2 backup interval, max RPO, documented RTO), commit to them, replace the hedge in `/privacy` with the real values. Pure ops + docs.
- **Operational maturity baseline** — single-developer reality is structural, but mitigations close most of the gap: public `/status` page (uptime + last incident), incident-response runbook in `docs/runbooks/`, named contact for security/incidents on `/security`. Sourced from 2026-05-03 third-party concerns review.
- **Formal Terms of Service** — `/terms` says "plain-English beta terms now, legalese later." Promote to a real ToS in parallel with the formal privacy policy work; same deadline (before GA).

## Later

v2+ direction. No plans yet; this is the strategic horizon.

- **Real-time co-editing** — Plan 9 ships advisory presence (badges, no live updates). v2 grows toward CRDT / OT collaboration so two agents (or human + agent) can co-edit a doc with sub-second visibility into each other's changes.
- **Agent inbox / activity feed** — once multiple agents share a doc, the question becomes "what did everyone do today" — surface activity per doc and per principal.
- **Org / team accounts + enterprise readiness** — shared ownership beyond per-user grants (today every doc has a single human owner) plus the gate to selling into work-data customers: SSO/SAML, SCIM, audit-log export, retention controls, data residency options, legal-hold support, and a SOC 2 path. Until these land, the honest framing on `/security` ("not for confidential customer data") is doing its job and we should not pretend otherwise. Surfaced explicitly because the 2026-05-03 third-party concerns review correctly identified this as the gap that closes off the entire enterprise segment.
- **Public publish destinations** — agent writes to Markland, Markland mirrors to GitHub Gist / X / wherever. Markland as the structured authoring surface, distribution channels as outputs.
- **MCP server marketplace presence** — be the canonical "agent-native shared notes" entry once the marketplaces stabilize.

---

## Non-goals (current)

Explicit decisions about what we are **not** doing now, to prevent
otherwise-tempting moves from creeping in. Sourced from
`docs/audits/2026-05-03-seo-strategy/SEO-STRATEGY.md` §3 and
`docs/specs/2026-05-03-monetization-strategy-design.md`.

- **No programmatic SEO.** No template-generated pages at scale
  (location pages, "[X] vs [Y]" matrices, "best tool for [job]"
  factories). With ~13 indexable URLs and a quality-floor surface,
  adding thin pages dilutes the signal. `/explore` was already a
  near-miss on this. Lifts when there's content to fill the templates.
- **No pricing page yet.** Lifts when monetization spec resolves
  (`docs/specs/2026-05-03-monetization-strategy-design.md`) and a paid
  tier ships. Showing prices before plans are shippable creates a
  credibility gap.
- **No `/case-studies` until 3+ named users with quotable wins.**
  Empty categorical pages dilute the quality signal.
- **No `/customers` page** for the same reason. We don't have logos
  yet; pretending we do is worse than not having the page.
- **No paid SEO tools.** Strategy is one-person, ≤2h/week of
  marketing-flavored work. Free + earned only.
- **No link-buying, no PBNs, no link exchanges.** Brand mentions
  outrank backlinks 3× for AI-search citations per the GEO analysis;
  one Show HN + one r/ClaudeAI post + one YouTube screencap beats 50
  link-building emails. Earned links only.
- **No paid acquisition** at this stage. No Google Ads, no Twitter
  promotions, no LinkedIn promoted posts. Lifts when there's a paid
  tier + a measurable CAC/LTV story.

---

## Shipped

Reverse-chronological by track. Each line is one shipped capability with the
date it landed.

### Hosted infrastructure + ops

- **2026-05-03** — Seed content live (PR #60 + Docker fix #61): 9 demo docs (6 admin-published explainers — publish surface, three-way collab, Git-vs-Docs, Claude Code quickstart, MCP tool reference, conflict-free editing — plus 3 agent-published from "Markland Bot" describing shipped-today specifics), bulk-publish script, agent provisioned at deploy. `/explore` now shows agent-authored content visibly instead of being abstract.
- **2026-05-03** — Admin runbook + helper scripts (PR #57, #58 + follow-up runbook commits). `scripts/admin/*` for end-to-end admin token mint/revoke/inspect, `curl-admin` helper sourced from `.env.local`, one-off SQL pattern documented (Fly image has no `sqlite3` CLI — use `python -c` against the volume). Productizes the bag of tricks used during cutover.
- **2026-05-03** — `markland_admin_metrics` expanded from 9 to 19 keys (PR #53). Adds unwindowed totals (`users_total`, `documents_total`, `documents_public_total`, `grants_total`, `invites_total`) + windowed activity (`documents_created/updated/deleted`, `grants_revoked`, `invites_created`). Existing keys preserved verbatim — no breaking change. Plan `docs/plans/2026-05-03-admin-metrics-tool-usage-expansion.md`.
- **2026-05-03** — Rate-limiter memory bound: periodic stale-key GC on the hit-counter dicts so `/device/confirm`'s per-IP limiter can't grow without bound (PR #51, beads `markland-77d`).
- **2026-05-03** — `/admin/*` bearer-resolution dedupe (SEO audit L4): single helper across `/admin/waitlist` + `/admin/metrics` + drops a redundant `last_used_at` write per request (PR #50).
- **2026-05-01** — **Cutover to `markland.dev` complete.** All 12 tasks of `docs/plans/2026-04-29-cutover-to-markland-dev.md` shipped: dedicated Fly IPv4 (149.248.214.141) + IPv6 (2a09:8280:1::107:b98d:0), Porkbun-direct A/AAAA at apex (Porkbun API DNS edits), Fly TLS cert issued, `MARKLAND_BASE_URL` flipped to `https://markland.dev`, machine rolled in place via `flyctl deploy --strategy immediate`, `FlyDevRedirectMiddleware` 301s the old `markland.fly.dev` host (`076a3c2`), Resend DNS records (SPF/DKIM/DMARC) verified end-to-end via real magic-link sign-in from `notifications@markland.dev`, GSC domain property added with TXT verification + sitemap.xml submitted. Hosted_smoke green on cutover-relevant checks; a residual grep-on-escaped-JSON false-positive in the smoke whoami assertion is logged in FOLLOW-UPS for separate fix.
- **2026-05-01** — `markland_admin_metrics` MCP tool + `GET /admin/metrics` JSON endpoint. Aggregates signups, publishes, grants_created, invites_accepted from existing tables over a configurable window (default 7d, cap 30d) plus unwindowed waitlist_total. Admin-only via existing `is_admin` gate. `first_mcp_call` returned as null pending event-table follow-up.
- **2026-04-29** — Domain `markland.dev` registered at Porkbun (registry expires 2027-04-29, locked, contact privacy on, Porkbun nameservers active). Unblocks the cutover sequence.
- **2026-04-28** — Five "Next"-lane plans landed under `docs/plans/2026-04-28-*.md`: Resend domain verify, security follow-ups batch (6 items), Phase 0 dogfood walkthrough, Sentry DSN + alerts, agent token query-string leak fix.
- **2026-04-28** — Repo public on GitHub. Three-phase make-repo-public plan executed: audit, git-filter-repo identity scrub of full history, publish + branch protection ruleset on `main` (no direct push, no force push, signed reviews via PR). Unblocks GitHub Pro APIs and provides marketing/credibility.
- **2026-04-24** — `/admin/waitlist` JSON endpoint for signup signals.
- **2026-04-20** — CI auto-deploy working end-to-end (release v3 from `deploy.yml`).
- **2026-04-20** — First Fly.io deploy (`markland` app, iad, 1 GB volume, shared-cpu-1x). Live at `https://markland.fly.dev/`. `MARKLAND_SESSION_SECRET` set; Resend / R2 / Sentry deferred.
- **2026-04-19** — Plan 1 hosted-infra Tasks 1-10: Dockerfile, Fly config, Litestream config, GH Actions workflows, `run_app.py` entrypoint, Sentry-conditional init, Resend client wrapper.

### Build (v1 plans + post-launch security/MCP)

- **2026-05-03** — **Magic-link single-use enforcement (PR #59)** — closes the 15-min capture-and-replay window flagged in the third-party concerns review and on `/security`'s post-beta hardening list. `magic_links.consumed_at` column + single-use guard on verify; replays rejected with the same generic error to avoid timing oracles. Plan `docs/plans/2026-05-03-magic-link-single-use.md`.
- **2026-05-03** — **Security follow-ups batch (PR #49)** — all 6 items from `docs/plans/2026-04-28-security-followups-batch.md`: `user_code` redirect escape via `urllib.parse.quote`, per-IP rate limit on `POST /device/confirm`, lock-after-N-failed-confirms on the device row, `grant_by_principal_id` defensive `principal_type` check, append-only `audit_log` enforcement (DB trigger), `/admin/audit` middleware coverage widened.
- **2026-05-01** — **Agent token query-string leak fixed (PR #41)** — `routes_agents.py:223-225` no longer redirects with `?new_token=…`. Now writes the token to a signed flash cookie (`URLSafeTimedSerializer`, mirrors `pending_intent.py`) read once on the next page render, then cleared.
- **2026-05-01** — **MCP audit Plan 6 — axis 5 (PR #38)** — five new tools: `markland_get_by_share_token`, `markland_list_invites`, `markland_explore`, `markland_fork`, `markland_revisions`. Layer B baselines + extended idempotency catalog.
- **2026-05-01** — **MCP audit Plan 5 — axis 4/8 (PR #36)** — granularity + idempotency.
- **2026-05-01** — **MCP audit Plan 4 — axis 2/7 (PR #33)** — return shapes + pagination.
- **2026-05-03** — **MCP retrospective Plans A/B/C** — three follow-ups from the audit's own retrospective: Plan A security hardening (PR #45), Plan B error-model completion (PR #46), Plan C hygiene (PR #47).

### Build (v1 plans, all 2026-04-19 unless noted)

- **Plan 10 — Launch polish.** Per-principal token-bucket rate limiting (60/120/20 default per user/agent/anon). `audit_log` table + service + admin UI + `markland_audit` MCP tool. Activation funnel metrics (6 events to stdout JSON). Session-aware `/explore`. `/quickstart` page. JSON log formatter. Rewritten README. End-to-end launch-gate test.
- **Plan 9 — Presence.** `presence` table with 10-min TTL, `service/presence.py`, background GC task, MCP tools (`markland_set_status`, `markland_clear_status`, embedded `active_principals` on `markland_get`), HTTP API, viewer badge.
- **Plan 8 — Conflict handling.** Monotonic `version` column + `revisions` table (50-row prune), `ConflictError`, `BEGIN IMMEDIATE` in `update()`. MCP `if_version` required. HTTP `ETag: W/"<n>"` + `If-Match` (428 / 409 / 200).
- **Plan 7 — Email notifications.** Jinja templates per trigger. `EmailDispatcher` (in-process async queue, jittered retry 1s/3s/10s). `EmailClient` extended with `text=` + `metadata=`. `/settings/notifications` stub.
- **Plan 6 — Device flow.** RFC 8628 device flow at `/device` + `/setup` runbook. `device_authorizations` table, slow_down rate limit, per-IP limiter on `device-start`, invite-token piggyback.
- **Plan 5 — Invite links.** `invites` table (argon2id-hashed tokens), MCP tools `markland_create_invite` / `markland_revoke_invite`, HTTP routes including `GET /invite/{token}`, anon signup-via-magic-link flow with `safe_return_to` open-redirect guard.
- **Plan 4 — Agents.** `agents` table (user-owned + service-owned), `mk_agt_` tokens, agent-inheritance in `check_permission`, `markland_list_my_agents` tool, `/settings/agents` page, `scripts/create_service_agent.py`.
- **Plan 3 — Doc ownership and grants.** `documents.owner_id`, `grants` table, `check_permission` (§12.5 resolution: owner → grant → public+view → deny-as-NotFound). MCP `markland_grant` / `markland_revoke` / `markland_list_grants`. Dashboard with My/Shared sections.
- **Plan 2 — Users and tokens.** Magic-link auth, `mk_session` signed cookie, `mk_usr_` argon2id-hashed API tokens, `PrincipalMiddleware` (replaced `AdminBearerMiddleware`), `markland_whoami` tool.

### Marketing + UX surface

- **2026-05-01** — **Umami Cloud analytics live (PR #37 + CSP fix #43)** — env-gated drop-in (`UMAMI_WEBSITE_ID`, `UMAMI_SCRIPT_URL`), admin paths excluded, `<script defer>` only when configured, two-host topology (`cloud.umami.is` + `api-gateway.umami.dev`) allowed in `connect-src`. Privacy-first, cookieless, no PII; disclosed on `/security`.
- **2026-05-01** — Signed-in banner coverage on every authed page + overflow fix (PR #39); themed login/magic-link/verify pages (PR #40, #34); "Sign in" link in header for signed-out visitors (PR #42).
- **2026-04-28** — Install-flow fixes from 2026-04-24 dogfood run (PR #12 + #13). `?next=` thread-through (`/login` → magic-link → `/verify` preserves intended landing); url-encoded `next=` so a `user_code` containing `&` or `?` survives the `/device/confirm` bounce; "For humans" preamble on `/setup`; runbook fixed to use the `/install` Claude Code command rather than the unsupported `claude mcp add markland <url>`; `claude mcp add` references swept across docs; trust `X-Forwarded-Proto` so the `/mcp` redirect preserves https behind Fly's proxy.
- **2026-04-20** — `/alternatives` hub + per-competitor comparison pages (markshare.to + 4 others).
- **2026-04-20** — Save-to-Markland CTA partial (desktop popover + mobile sheet); `/fork` and `/bookmark` routes with logged-out intent capture; `/resume` + magic-link hook for post-login action resume; signed pending-intent cookie via `URLSafeTimedSerializer`; `bookmarks` table + `forked_from_doc_id` column; "Saved" dashboard section; "Forked from" attribution on viewer.
- **2026-04-19** — Landing page + waitlist (`landing-waitlist-implementation.md`).
- **2026-04-18** — Frontend theming experiments (`dark-outlined-primary`, `io24-theming`, `neubrutalism-theming`).
- **2026-04-17** — Frontend implementation baseline.

### Strategy + specs

- **2026-05-03** — SEO strategy doc landed at `docs/audits/2026-05-03-seo-strategy/SEO-STRATEGY.md` (314 lines). 12-month KPI grid, four-phase implementation roadmap (Foundation done → Content launch weeks 1-12 → Authority months 4-6 → Scale months 7-12), 4-6 anchor blog posts spec'd with target queries + effort estimates, weekly drift-monitor cadence, risk register. Drove the new "Non-goals (current)" section.
- **2026-05-03** — Monetization strategy design landed at `docs/specs/2026-05-03-monetization-strategy-design.md`. 4-tier ladder (Free / Pro / Team / Enterprise), per-workspace base + per-human-seat expansion, agent-operations metered overage as a future lever. **$25K MRR within 12 months** target. Awaiting review before plan-writing.

### SEO foundation

- **2026-05-03** — **GEO / AI-search readiness batch G1-G5 shipped (PR #54, #55, #56).** Robots.txt pruned to training-only blocks (`Google-Extended`, `Bytespider`); `PerplexityBot`, `GPTBot`, and modern `ClaudeBot` all reachable now — Markland is no longer locked out of Perplexity / ChatGPT Search / Claude Web. `/llms.txt` route live at `https://markland.dev/llms.txt`. Question-shaped FAQ blocks across `/`, `/quickstart`, all 5 `/alternatives/{slug}` (legacy `<dl>` removed). 143-word "What is Markland?" answer block above the hero on `/`. `/explore` dropped from `sitemap.xml` until it has content. Plan `docs/plans/2026-05-03-geo-search-readiness.md`.
- **2026-05-03** — GEO / AI-search readiness analysis published at `docs/audits/2026-05-03-geo-analysis/GEO-ANALYSIS.md` (score 62/100). Live curl + static-HTML inspection of 7 sitemap URLs, platform-by-platform breakdown (Google AIO, ChatGPT Search, Perplexity, Claude Web, Bing Copilot), AI-crawler access matrix. Drove the G1-G5 batch above.
- **2026-05-03** — **SEO audit complete** — every C/H/M/L item from `docs/audits/2026-04-24-seo-audit/ACTION-PLAN.md` shipped or marked obsolete. Final landings: C3 branded HTML 404 (`tests/test_404_page.py`), C4 trust pages expanded ≥250 words with E-E-A-T signal (`48dc2df`), L3 robots.txt AI-crawler blocklist expanded (PR #48), L4 `/admin/*` middleware dedupe (PR #50), L5 post-cutover sitemap submitted + GSC verified.
- **2026-04-28** — Self-hosted Figtree, DM Mono, Newsreader (perf/SEO Task 10). Variable woff2 files served from `src/markland/web/assets/fonts/`, `@font-face` declarations in `base.html`, Newsreader italic axis widened to weight 600, `tests/test_self_hosted_fonts.py` verifies presence and font-face declarations.
- **2026-04-27** — SEO batch 1 from 2026-04-24 audit: `/alternatives` competitor cards as `<h2>` (C1), `Offer` on `SoftwareApplication` JSON-LD (C2), `BreadcrumbList` on per-competitor pages (H2), `logo` + `sameAs` on `Organization` (H3), additional H5/H6/M8 quick wins. Audit artifacts committed under `docs/audits/2026-04-24-seo-audit/`. HackMD coverage test added.
- **2026-04-22** — `_seo_meta.html` partial (canonical, OG, Twitter, JSON-LD); per-page meta descriptions; homepage retitle for MCP + Claude Code; GEO definitional paragraph for AI Overviews / LLM citation; expanded `/quickstart` (600+ words, H2 steps, templated host); trust-floor stub pages (`about/security/privacy/terms`) + footer; dynamic `/robots.txt` and `/sitemap.xml` (sourced from `COMPETITORS`); `SecurityHeadersMiddleware` (HSTS, CSP, XFO, XCTO, Referrer-Policy, Permissions-Policy, per-path `X-Robots-Tag`).
