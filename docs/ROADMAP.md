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

## Where we are (2026-05-04)

Live at **`https://markland.dev`**. Pre-release security pass essentially
complete: 18 findings filed by a multi-agent review, **P0 batch shipped**
(PR #62 — markdown XSS via `javascript:` scheme, JS-context XSS in
`invite.html`/`settings_agents.html`/`device.html`, magic-link tokens
scrubbed from logs + Sentry), **P1+P2 batch shipped** (PR #64, 11
commits — `mk_session` `SameSite=Strict`, agents no longer inherit
owner-action on owning user's docs, CSRF secret-fail-loud, Dockerfile
non-root, presence-strip for anonymous viewers, CSP `script-src` drops
`'unsafe-inline'` via per-request nonce, `Fly-Client-IP` trust over
`X-Forwarded-For`, content size caps, grant-by-unknown-email folds to
silent invite, share-token rotation on private revoke, `feature` +
audit-list defense-in-depth admin gates). 3 P2 deferred to focused
follow-ups (server-side session revocation epoch, O(N) Argon2 verify
scan, logout-only-cookie). 13 P3 follow-ups filed as beads. **MCP
discovery hardened** (PR #66) — bearer auth advertised so SDK probes
don't crash on HTML 404. **Copy-token UX polished** (PR #65) — Copy
button + 'C' shortcut, agent token row stops disappearing.

`/blog` launched + first anchor post live (PR #63) — `/blog`,
`/blog/{slug}`, and `/blog/feed.xml` (Atom 1.0) all serving 200; the
single-post feed is "[What is agent-native publishing?](https://markland.dev/blog/agent-native-publishing)"
(1,403 words, 155-char meta description, 150-word definition lead in
the AI-citation sweet spot, full Article + Person + BreadcrumbList
JSON-LD). Phase 2 of the SEO strategy — content launch — is genuinely
underway one day after the strategy was written.

**Phase 0 dogfooding partial** — Eric ran steps 1-3 with view-grant
only; environment + Sentry alerts complete; steps 4-14 remain.

**GEO batch G1-G5 shipped** (PR #54, #55, #56) — robots.txt pruned to training-only
blocks (Perplexity + ChatGPT Search + Claude Web all reachable now),
`/llms.txt` live, question-shaped FAQ blocks across `/` + `/quickstart` +
every `/alternatives/{slug}`, 143-word "What is Markland?" answer block
above the hero, `/explore` dropped from sitemap until it has content.
**GEO posture decision: made + executed** — Markland is now optimized
for AI search engines, not blocked from them. **SEO drift baselines
captured** — 12 marketing URLs snapshotted to
`~/.cache/claude-seo/drift/baselines.db`; weekly
`/claude-seo:seo-drift compare` cadence added to the strategy doc.
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

## How this roadmap works

Each Now/Next item is a **topic linked to a plan** (or, for items that
need design first, tagged `[needs brainstorm]`). The workflow:

1. **Topic surfaces** in Now or Next.
2. If the topic isn't yet executable, it's tagged `[needs brainstorm]`
   and run through the `superpowers:brainstorming` skill → produces a
   spec at `docs/specs/<date>-<topic>-design.md`.
3. Spec runs through `superpowers:writing-plans` → produces a plan at
   `docs/plans/<date>-<topic>.md`.
4. Plan is linked from the roadmap entry and is ready for any agent
   (or human) to execute task-by-task.

Items with a `Plan:` link are ready to pick up. Items without a plan
link should either have a `Spec:` link, a `[needs brainstorm]` tag, or
be a small ops/content/beads task that doesn't warrant a full plan.

## Now

Active or imminent. Items here have a plan or a clear next action.

- **Monetization strategy review + plan-write** `[spec, plan TBD]` — Spec: `docs/specs/2026-05-03-monetization-strategy-design.md` (4-tier ladder Free/Pro/Team/Enterprise, per-workspace + per-human-seat expansion, agent-operations metered overage as a future lever, $25K MRR / 12 months target). Next move: review spec, decide tier prices + workspace/seat caps, then run `superpowers:writing-plans` to produce the implementation plan (Stripe wiring, gates, billing UI, marketing pricing page).
- **MCP audit Plan 7 — Phase B deprecation/removal** — opens 30 days after the `mcp-audit-axis-5-released` tag (laid 2026-05-01, so window opens **2026-05-31**). Removes 4 deprecation shims: `markland_set_visibility`, `markland_feature`, `markland_set_status`, `markland_clear_status`. Plan: `docs/plans/2026-04-27-mcp-phase-b-deprecation-removal.md`.
- **Install/onboarding flow simplification — Options 2-4** — Option 1 shipped (PR #12 + #13). Brainstormed 2026-05-04: design at `docs/specs/2026-05-04-install-onboarding-options-2-4-design.md`, plan at `docs/plans/2026-05-04-install-onboarding-options-2-4.md`. Two-phase build: **Phase 1 (CLI-first)** ships Options 2+3 — `/setup` runbook step 2 swaps "visit /device and type the code" for a single clickable `/device?code=…` URL, and `device-start` API gains `verification_uri_complete` (RFC 8628 §3.2 standard) so any standards-aware client picks up the single-link form automatically. **Phase 2 (browser-via-shares)** is Option 4 reframed: post-signup dashboard "Connect Claude Code" panel hands the user one line to paste into Claude Code (`Install the Markland MCP server from /setup`), routing back through Phase 1's path — no parallel install flow, no token-on-screen. Auto-dismisses on first authorized device. Original setup-install-ux-fix plan: `docs/plans/2026-04-24-setup-install-ux-fix.md` (Option 1, all tasks shipped).
- **Phase 2 content cadence** — `/blog` infrastructure shipped (PR #63) and post #1 ("What is agent-native publishing?") is live at `https://markland.dev/blog/agent-native-publishing`. Next post target ~2026-05-17 (one post / 2 weeks per `docs/audits/2026-05-03-seo-strategy/SEO-STRATEGY.md` §4). Working list of next anchor titles: "How to share Claude Code output without copy-pasting", "MCP, explained for developers", "Five things to publish to Markland from Claude Code", "Why markdown round-trips break in Notion", "Building a public CLAUDE.md library". Pick 3-4 of those between now and ~2026-08.
- **Phase 0 dogfooding — finish steps 4-14** — Eric ran 1-3 with view-grant only (`b87f338`). Remaining: edit-grant, grant-revocation, MCP-from-CLI, agent token issuance, public-doc reading, `markland_search` from a fresh client, etc. Per `docs/plans/2026-04-28-phase-0-dogfood.md`.

## Next

Queued. The big security/analytics/MCP-axis batches all landed; what's
left is launch-readiness polish.

- **Soak-window analytics check** — beads `markland-fjd` (2 weeks post-launch): pull Umami stats + `/admin/metrics` 14d funnel snapshot + cross-reference signups vs Umami sessions, post a 1-message summary.
- **Server-side session revocation epoch** — beads `markland-bul` / `markland-ayv` (P2 deferred from PR #64). Today logout is cookie-only; if a session cookie is captured, only secret rotation invalidates it globally. Blast radius is large (13+ `read_session` callers across `web/` need a `conn` argument plumbed through). Mitigations in place: magic-link is single-use, secret rotation works. Plan: `docs/plans/2026-05-04-session-revocation-epoch.md`.
- **O(N) Argon2 verify scan on Bearer auth** — beads `markland-9dm` (P2 deferred from PR #64). Schema change required: token-prefix index or hash-bucket sharding so we don't argon2-verify every row in the user/agent tables on each request. Plan: `docs/plans/2026-05-04-token-id-prefix-o1-lookup.md`.
- **Self-service deletion** `[spec, plan TBD]` — Spec: `docs/specs/2026-05-04-self-service-deletion-design.md`. Two-tier model: documents delete immediately and irreversibly (typed-confirmation), accounts get a 30-day soft-delete window (magic-link reverify, frozen-from-the-outside semantics, daily cron purges past-due accounts and anonymizes the `users` row to a tombstone — preserving the audit-log append-only invariant from PR #49). Three independently-mergeable phases: (1) doc-delete UI on the existing API, (2) account soft-delete + recovery, (3) cron purge. Email reuse permitted post-purge. Plan-write next.
- **Formal privacy policy** — `/privacy` line 11 says "a formal privacy policy will be published before general availability." Today's page is a working summary, which reads as deliberately stub-y to outside evaluators. Promote to a real, standard-shaped policy with the 10 sections external evaluators expect: introduction, information we collect (3 categories), how we use it, sub-processors (Fly.io, Resend, R2, Umami, Sentry, Anthropic), retention per category, your rights & choices, international transfers, security + 72-hour breach notification, children's privacy, 14-day material-change notice, contact alias. Plan: `docs/plans/2026-05-04-formal-privacy-policy.md`.
- **Sharpen agent-to-agent positioning** `[needs brainstorm]` — third-party eval flagged `markland_grant` to another agent ID as the most interesting differentiator; current homepage treats it as a footnote. Add an above-fold or near-fold use-case block: "agent-to-agent coordination — architect agent publishes plan, QA agent appends test report, you read one doc instead of scraping terminal logs." Touches landing copy + possibly a `/explore`-adjacent example.
- **Visibility-change safety rail** `[needs brainstorm]` — today `markland_publish` accepts `public=true` in one tool call, so a casually-worded prompt can flip a doc public without a human gesture. Rough idea: two-step it (`markland_publish` ignores `public=true`, defaults private; `markland_set_visibility` is the only way to flip) + flash + bold audit-log entry. Needs design pass: backwards-compat for existing tool callers, MCP deprecation path, what the UI flash actually looks like, whether to require interactive confirmation for cross-principal grants. Sourced from 2026-05-03 third-party concerns review.
- **Backup RPO/RTO commitment** — `/privacy` line 43 says backup rotation cadence is "still being tuned during beta." Pick numbers (Litestream/R2 backup interval, max RPO, documented RTO), commit to them, replace the hedge in `/privacy` with the real values. Pure ops + docs.
- **Operational maturity baseline** `[needs brainstorm]` — single-developer reality is structural, but mitigations close most of the gap. Three sub-items that may want decomposing into separate plans: public `/status` page (uptime + last incident — host vs build, data source, incident posting workflow), incident-response runbook in `docs/runbooks/` (severity levels, paging policy when there's no on-call), named contact for security/incidents on `/security` (email alias, encrypted contact, response SLA). Sourced from 2026-05-03 third-party concerns review.
- **Formal Terms of Service** — `/terms` says "plain-English beta terms now, legalese later." Promote to a real, standard-shaped ToS with the 14 sections external evaluators expect: introduction & acceptance, definitions, your account, acceptable use, your content (incl. license to operate), our service (beta posture, availability, changes, pricing), termination, disclaimers (as-is), limitation of liability, indemnification, governing law (Delaware, no class actions), general (entire-agreement / severability / etc.), changes (14-day material-change notice), `legal@markland.dev` contact alias. Plan: `docs/plans/2026-05-04-formal-terms-of-service.md`.

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

- **2026-05-04** — **Pre-release security review executed end-to-end.** Multi-agent review (`fdc1707`) filed 18 findings; **P0 batch shipped (PR #62, 3 findings)** — markdown XSS via `javascript:` link scheme (allowlist `http`/`https`/`mailto`/relative/fragment), JS-context XSS in `invite.html`/`settings_agents.html`/`device.html` (via `tojson`, delegated submit handler, `urlencode`), magic-link tokens scrubbed from logs + Sentry (new `markland.log_scrubbing` module masks `token`/`share_token`/`csrf`/`magic_link` query params, strips `Authorization` header). **P1+P2 batch shipped (PR #64, 11 commits, 10 findings)** — `mk_session` `SameSite=Strict`, agent-action inheritance bounded to view/edit (delete/visibility/feature/grant/revoke require explicit owner-grant on the agent), CSRF secret-fail-loud on empty `MARKLAND_SESSION_SECRET`, Dockerfile non-root `app` uid 1000, presence-strip principal_id/display_name/note for anonymous viewers, CSP `script-src` drops `'unsafe-inline'` via per-request `csp_nonce` woven through `render_with_nav`, `Fly-Client-IP` trust over `X-Forwarded-For`, content size caps (1MB UTF-8 / 500-char title), grant-by-unknown-email folds to silent invite (no email-existence oracle), share-token rotation when revoking grants on private docs, defense-in-depth admin gates on `docs_svc.feature` + `audit_svc.list_recent`. 3 P2 deferred to focused follow-ups (server-side session revocation epoch, O(N) Argon2 verify, logout-only-cookie). 13 P3 follow-ups filed as beads.
- **2026-05-04** — **MCP discovery hardened (PR #66)** — bearer auth advertised on `/mcp` so SDK probes don't crash on HTML 404. `WWW-Authenticate: Bearer realm="markland", resource_metadata="<base>/.well-known/oauth-protected-resource"` header on 401s (RFC 9728 / MCP authz spec 2025-03-26) + JSON-shaped `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server` routes. Closes `markland-2yj`. Plan `docs/plans/2026-05-03-mcp-auth-discovery.md`.
- **2026-05-04** — Copy-token UX polished (PR #65 + close `markland-31a`). Copy button + 'C' shortcut on `/settings/agents`; agent token row no longer disappears after first reveal.
- **2026-05-04** — **`/blog` launched (PR #63)** — `/blog`, `/blog/{slug}`, `/blog/feed.xml` (Atom 1.0); first anchor post "[What is agent-native publishing?](https://markland.dev/blog/agent-native-publishing)" (1,403 words, 155-char meta description, 150-word definition lead in the AI-citation sweet spot, full Article + Person + BreadcrumbList JSON-LD). Phase 2 of the SEO strategy underway one day after the strategy was written.
- **2026-05-04** — Sentry DSN provisioned + three alerts wired (5xx spike, `ConflictError` spike, `EmailSendError` spike) — plan `docs/plans/2026-04-28-sentry-dsn-alerts.md`. Operator step from the Next lane.
- **2026-05-03** — **Magic-link single-use enforcement (PR #59)** — closes the 15-min capture-and-replay window flagged in the third-party concerns review and on `/security`'s post-beta hardening list. `magic_links.consumed_at` column + single-use guard on verify; replays rejected with the same generic error to avoid timing oracles. Plan `docs/plans/2026-05-03-magic-link-single-use-enforcement.md`.
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

- **2026-05-03** — **`/blog` infrastructure + anchor post #1 shipped (PR #63)** — three new routes (`/blog`, `/blog/{slug}`, `/blog/feed.xml` Atom 1.0), filesystem-sourced markdown content under `src/markland/web/content/blog/*.md` with hand-rolled YAML-style frontmatter (no PyYAML dep), full Article + Person + BreadcrumbList JSON-LD per post, sitemap + `/llms.txt` auto-extension gated on ≥1 published post (mirrors `EXPLORE_MIN_PUBLIC_DOCS` pattern), Blog link in header nav + footer. First post: "[What is agent-native publishing?](https://markland.dev/blog/agent-native-publishing)" — 1,403 body words, 155-char meta description, 150-word definition lead in the AI-citation 134-167 word sweet spot. 31 new tests; full suite 1046 passing. Closes beads `markland-xgj` + `markland-380`.
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
