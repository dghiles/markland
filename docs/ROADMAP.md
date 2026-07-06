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

## Where we are (2026-07-05)

**Reconciliation checkpoint — roadmap audited against the codebase.** Three-agent
sweep (source-claim verification, all-plans status audit, beads/gauntlet/launch
state) run 2026-07-05 against `main` @ `8b197e8`. Every shipped claim in the
previous checkpoints verified true in source — no drift in the Shipped log. New
consolidation layer: `docs/plans/README.md` indexes all 56 plans + 8 specs with
status (49 complete; the only open plan work is MCP Plan 7 [executable now],
self-service deletion Phases 2–3 [deferred], and the trigger-gated plugin
marketplace plan). Suite: 1,254 tests collected (+7 since the 2026-05-30
refresh, from PRs #73–#76). MCP surface: 27 tools, 4 of them Plan 7 deprecation
shims awaiting removal.

**The repo has been dormant ~5 weeks.** Last commits (PRs #75/#76 — e2e
magic-link mint seam + real-browser gauntlet card) landed 2026-05-30, hours
after the last roadmap refresh. Beads activity, gauntlet runs, and the launch
sequence all froze at the same moment. This isn't drift inside the work — it's
a full stop right after the pre-launch bundle landed.

**The launch is parked on one overdue gate.** `markland-3sd` — the post-Track-B
soak-window check that unlocks the Show HN post — was deferred to 2026-06-05
and is now a month overdue. Every other prerequisite shipped; the draft sits
queued at `docs/launch/2026-05-29-show-hn-draft.md`. Upside of the delay: five
weeks of post-CRO funnel data now exist instead of the originally planned noisy
3–5-day sample, so the check will be more conclusive when it runs.

**Reconciliation actions taken (2026-07-05):** closed `markland-d9c` (P1
SameSite verify) — the 2026-05-30 gauntlet run proves it
(`magic-link-cross-site-click: consistent_pass`); filed `markland-2jn` (P2) to
rescue stranded PR #72 (open since 2026-05-10, CI green, now CONFLICTING — its
Atom-autodiscovery `<link>` fix is exactly what the one consistently-failing
gauntlet card `blog-atom-feed-valid` has flagged since 2026-05-09); filed
`markland-15e` (P3) for repo hygiene (2 stale locked agent worktrees + ~20
merged local branches); recorded the dispatcher-observability plan as shipped
(verified live in `service/email_dispatcher.py` — it had never made the
Shipped log); retired three Next-lane entries that were already done
(soak-analytics check, SameSite verify, backup RPO/RTO commitment).

Prior checkpoints (2026-05-30, 2026-05-09) are consolidated into the Shipped
log below.

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

The full plan + spec status index lives at `docs/plans/README.md`
(reconciled 2026-07-05) — that file, not the checkbox state inside a
plan, is the authority on whether a plan shipped.

## Now

Active or imminent. Items here have a plan or a clear next action.

**Working theory (2026-05-29 soak-window):** the funnel isn't starving — it's leaking. 52 visitors / 14d → 0 signups; 91% bounce on `/` (which is 64% of all pageviews). All 5 organic signups happened in the first 2 weeks post-launch; adoption has flatlined since. The bottleneck is **homepage conversion + content velocity**, not the trust-gate items we'd been queueing. Re-ordered Now/Next accordingly.

- **[Pre-launch F-gate] Post-B soak-window check — OVERDUE ~30 days; the single item parking the launch** — beads `markland-3sd` (P2, was due 2026-06-05). Run `docs/runbooks/metrics-review.md` now — five weeks of post-Track-B funnel data are available (deploy was 2026-05-30 01:27Z), far better than the originally planned 3–5-day sample. Hypothesis to test: hero CTA flip to `/login` drops bounce on `/` from 91% and unsticks signup velocity (was 0 in the 14d before Track B). If yes, Track F (Show HN post) unlocks. If no, the leak is somewhere else than the hero — re-diagnose before posting.
- **MCP audit Plan 7 — Phase B deprecation/removal — window open since 2026-05-31, executable now** — removes 4 deprecation shims: `markland_set_visibility`, `markland_feature`, `markland_set_status`, `markland_clear_status` (all four verified still registered in `server.py` on 2026-07-05; MCP surface 27→23). Plan: `docs/plans/2026-04-27-mcp-phase-b-deprecation-removal.md`.
- **Rescue stranded PR #72 — `/blog` Atom autodiscovery `<link>`** — beads `markland-2jn` (P2). Open since 2026-05-10 with green CI, now CONFLICTING against main. Fixes the only failing gauntlet card (`blog-atom-feed-valid`, consistent_fail in both the 2026-05-09 and 2026-05-30 run sets). Rebase, merge, re-run the card to confirm the two-month-old failure clears.
- **Monetization strategy review + plan-write** `[spec, plan TBD]` — Spec: `docs/specs/2026-05-03-monetization-strategy-design.md` (4-tier ladder Free/Pro/Team/Enterprise, per-workspace + per-human-seat expansion, agent-operations metered overage as a future lever, $25K MRR / 12 months target). Demoted pending the F-gate soak-window — monetization without a converting funnel optimizes the wrong stage. Next move once funnel is confirmed converting: review spec, decide tier prices + workspace/seat caps, then run `superpowers:writing-plans`.

## Next

Queued. The big security/analytics/MCP-axis batches all landed; what's
left is launch-readiness polish.

- **Per-route CSRF tokens (or Origin/Referer check) on form-body session-authed routes** — beads `markland-7ly` (P2). Surfaced during the dispatch-round review (`dee1683 review: honest CSRF posture`). Today's posture relies on `SameSite=Lax` to protect mutating form-body routes; explicit per-route CSRF tokens or Origin/Referer checks are the belt-and-suspenders move. No plan yet.
- **Self-service deletion — Phase 2 + Phase 3 remaining** — Spec: `docs/specs/2026-05-04-self-service-deletion-design.md`. Plan: `docs/plans/2026-05-04-self-service-deletion.md`. **Phase 1 shipped 2026-05-29 as Track E1 of the pre-launch bundle** (PR `80769b5` — doc-delete UI with typed-confirmation modal on `/dashboard` + viewer + shared partial). Phase 2 (account soft-delete + 30-day window with magic-link reverify, frozen-from-the-outside semantics) and Phase 3 (daily cron purge that anonymizes the `users` row to a tombstone) remain deferred. Trigger to ship Phase 2/3: first 25 organic signups, OR an external evaluator flag that "no account delete" is the blocker for adoption.
- **Sharpen agent-to-agent positioning** `[needs brainstorm]` — third-party eval flagged `markland_grant` to another agent ID as the most interesting differentiator; current homepage treats it as a footnote. Add an above-fold or near-fold use-case block: "agent-to-agent coordination — architect agent publishes plan, QA agent appends test report, you read one doc instead of scraping terminal logs." Touches landing copy + possibly a `/explore`-adjacent example.
- **Claude Desktop + Claude.ai (Cowork / Custom Connectors) install paths** `[needs brainstorm]` — today `/quickstart` covers Claude Code via `claude mcp add` and mentions other clients only generically ("Setup differs per client"). Two new client surfaces deserve first-class install recipes: (1) **Claude Desktop** — manual edit of `claude_desktop_config.json` adding `https://markland.dev/mcp/` with bearer header, comparable to `~/.claude.json`; (2) **Claude.ai web** — Anthropic's Custom Connectors / Cowork surface for adding remote MCP servers from the chat UI. Design questions: does each surface support our bearer-token-only auth model (no OAuth, no DCR) without UX friction, or does the SDK UX gap from `markland-vtb` reappear in different shapes? Do we need a per-client `/quickstart#claude-desktop` and `/quickstart#claude-web` deep link section, or separate `/integrations/{client}` pages (the SEO strategy doc §3 sketches `/integrations/{claude-code,cursor,codex,claude-desktop}` as a future surface — this could be the trigger to ship that taxonomy)? Verify auth quirks in each surface before choosing scope. After brainstorm: spec → plan → ship.
- **Visibility-change safety rail** `[needs brainstorm]` — today `markland_publish` accepts `public=true` in one tool call, so a casually-worded prompt can flip a doc public without a human gesture. Rough idea: two-step it (`markland_publish` ignores `public=true`, defaults private; `markland_set_visibility` is the only way to flip) + flash + bold audit-log entry. Needs design pass: backwards-compat for existing tool callers, MCP deprecation path, what the UI flash actually looks like, whether to require interactive confirmation for cross-principal grants. Sourced from 2026-05-03 third-party concerns review.
- **Operational maturity baseline** `[needs brainstorm]` — single-developer reality is structural, but mitigations close most of the gap. Three sub-items that may want decomposing into separate plans: public `/status` page (uptime + last incident — host vs build, data source, incident posting workflow), incident-response runbook in `docs/runbooks/` (severity levels, paging policy when there's no on-call), named contact for security/incidents on `/security` (email alias, encrypted contact, response SLA). Sourced from 2026-05-03 third-party concerns review.

## Later

v2+ direction. No plans yet; this is the strategic horizon.

- **Real-time co-editing** — Plan 9 ships advisory presence (badges, no live updates). v2 grows toward CRDT / OT collaboration so two agents (or human + agent) can co-edit a doc with sub-second visibility into each other's changes.
- **Agent inbox / activity feed** — once multiple agents share a doc, the question becomes "what did everyone do today" — surface activity per doc and per principal.
- **Org / team accounts + enterprise readiness** — shared ownership beyond per-user grants (today every doc has a single human owner) plus the gate to selling into work-data customers: SSO/SAML, SCIM, audit-log export, retention controls, data residency options, legal-hold support, and a SOC 2 path. Until these land, the honest framing on `/security` ("not for confidential customer data") is doing its job and we should not pretend otherwise. Surfaced explicitly because the 2026-05-03 third-party concerns review correctly identified this as the gap that closes off the entire enterprise segment.
- **Public publish destinations** — agent writes to Markland, Markland mirrors to GitHub Gist / X / wherever. Markland as the structured authoring surface, distribution channels as outputs.
- **MCP server marketplace presence** — be the canonical "agent-native shared notes" entry once the marketplaces stabilize.
- **Claude Code plugin marketplace listing** — beads `markland-97r` (P3, trigger-gated). Publish Markland as a Claude Code plugin (`claude plugin marketplace add markland-dev/claude-plugin`) so install reduces from "type the `claude mcp add` command and paste a bearer token" to "click Enable in `/plugins`." Trigger: 50+ active MCP installs (measured via `markland_admin_metrics::users_total`) OR an inbound community-marketplace request. Plan: `docs/plans/2026-05-04-claude-code-plugin-marketplace.md`.

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

- **2026-05-30** — **E2E magic-link mint seam + real-browser gauntlet card** (PRs #75, #76). Test-only `POST /api/test/mint-magic-link` (`web/e2e_routes.py`, mounted only when `MARKLAND_E2E_SECRET` is set; constant-time header compare; 404-on-everything anti-fingerprinting; `@markland.test` emails only) lets a Chrome-driven gauntlet card mint a live verify URL and prove the cross-site email-click → 303 → `mk_session` flow end-to-end — the exact regression class TestClient is blind to. #76 moved the secret to the gitignored `.gauntlet/context/secrets/` fixture-file pattern. Last gauntlet batch (`batch_20260530T171657Z_r43v`, 2026-05-30 17:16Z): 4/5 pass; the one fail is the known `blog-atom-feed-valid` autodiscovery gap → PR #72 / `markland-2jn`.
- **2026-05-30** — **Backup RPO/RTO commitment live on `/security`** (`bcb293a`, bead `markland-ixc` closed). Concrete numbers replace the beta hedge: RPO **10 seconds** (Litestream WAL→R2 interval), RTO **under 5 minutes** (restore itself measured 524ms for a 320KB DB), **30-day rolling retention** with 6-hour point-in-time boundaries. `/privacy` retention section states the same 30-day window.
- **2026-05-30** — **`mk_session` SameSite=Lax fix** (PR #74, `2da6933`). Demoted from `SameSite=Strict` (set by PR #64's security batch) after prod observation that Strict cookies aren't sent on the 303 hop following a cross-site navigation — so magic-link email clicks were silently failing to authenticate. TestClient ignores SameSite, so CI couldn't catch it. Memory entry: `feedback_samesite_test_blindness.md`. **Verified 2026-05-30** by the real-browser gauntlet card (`magic-link-cross-site-click: consistent_pass`); `markland-d9c` closed 2026-07-05.
- **2026-05-29** — **Soak-window analytics check** (bead `markland-fjd`, closed). Full pass: 6 users (4 real + 2 test), 0 signups in 14d, 1 publish in 14d (admin), 52 visitors / 91% bounce / 60% pageview drop WoW, 1 blog view in 14d. Conclusion: funnel leaks at the homepage; trust-gates aren't the bottleneck. Drove the pre-launch clean-up bundle and the `[Pre-launch F-gate]` follow-up in Now.
- **2026-05-29** — **Phase 0 dogfooding complete (markland-emu)**. Operator-only sweep of steps 4-14 of `docs/plans/2026-04-28-phase-0-dogfood.md` against prod, plus audit-derived reconstruction of step 2.4 and synthetic 2.5/2.6 with operator's own agent token. Surfaced and fixed one P0 mid-run (`markland-9n0` — Litestream WAL `permission denied` crash loop from file-ownership drift; `chown -R app:app /data/.markland.db-litestream` restored sync, persists across deploys because `Dockerfile USER app`). Surfaced two P3 follow-ups: `markland-2l8` (revoke phase-0 test tokens) and `markland-axc` (plan refers to stale `/auth/start` path, real route is `POST /api/auth/magic-link`). Evidence at `docs/launch/phase-0-evidence-2026-05-29/`. **GO** decision recorded.
- **2026-05-18** — **Metrics-review runbook + supporting scripts** (`77bccc7`). New `docs/runbooks/metrics-review.md` documents the operator-side soak-window flow: `/admin/metrics` funnel snapshot at 14d/30d, `scripts/admin/list_users.py` for the who's-signed-up question, `scripts/admin/umami_summary.py` for referrer + top-pages data. Companion fix `dc65424` sets a non-default User-Agent on the Umami summary script to dodge Cloudflare 1010 block on the analytics dashboard endpoint. Makes the `markland-fjd` soak-window check (then 3 days overdue) a one-paste operation. Sibling docs landings 2026-05-18: `b5d01c9` (wrap Jinja exprs in `{{ }}` so `/blog` JSON-LD parses — clears the GSC validation flagged in `markland-de2`); `aec90a5` (redesigned `og.png` — tighter M lockup, readable wordmark); `a7b5890` (deflake `test_read_rejects_tampered_token` — `markland-ctx` closed).
- **2026-05-09** — Gauntlet QA scaffolding (`61c0f42`). AI-driven prod smoke tests in `.gauntlet/cards/`, runner at `~/Developer/gauntlet`, ~$0.04/card on Haiku. Initial 4 cards: `blog-atom-feed-valid`, `legal-pages-reachable`, `mcp-endpoint-401-not-307`, `signin-return-path`. First batch run logged at `.gauntlet/run-sets/batch_20260509T165056Z_edhq`. Complements pytest unit tests with against-prod smoke checks that exercise real-network behavior the test client can't (HTTP/2, SSE response shape, CDN edge state). Reference: `~/.claude/projects/-Users-daveyhiles-Developer-markland/memory/reference_gauntlet_qa.md`.
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

- **2026-05-09** — **Server-side session revocation (PR #70 — `markland-bul`)** — `users.session_epoch INTEGER NOT NULL DEFAULT 0` column added; `bump_session_epoch` uses `UPDATE … RETURNING` for atomicity; `issue_session(conn=…)` embeds the user's current epoch in the cookie payload; `read_session(conn=…)` rejects cookies whose epoch < current; `POST /api/auth/logout` bumps the user's epoch (server-side revocation — cookie no longer valid in any other tab). Old cookies (no `epoch` field) treated as 0 and remain valid until first logout post-deploy. Implementation atomic per the plan's deploy-window warning: bump + issuance read landed in one commit. Closure-DI pattern preserved (`db_conn` from route factory, not `Depends(get_conn)`). Plan `docs/plans/2026-05-04-session-revocation-epoch.md`.
- **2026-05-09** — **O(1) Bearer token resolve (PR #69 — `markland-9dm`)** — new plaintext format `mk_usr_<16hex>_<urlsafe32>` (and `mk_agt_…`) embeds the row's primary key as a public, non-secret prefix. `resolve_token` parses the prefix, fetches the row by PK, cross-checks `principal_type` before argon2 verify (short-circuits forged prefixes against wrong-type rows), then runs exactly one verify. Critical fall-through to `_resolve_legacy` on ANY fast-path miss (PK absent, type mismatch, verify fail) preserves correctness for legacy plaintexts whose secret happens to start with 16 hex chars + `_` (~2.3e-12 natural rate). Old `_generate_user_token_plaintext` / `_generate_agent_token_plaintext` retained as `NotImplementedError` stubs. Follow-up `markland-brf` deferred 90d for fallback removal once legacy tokens age out. Plan `docs/plans/2026-05-04-token-id-prefix-o1-lookup.md`.
- **2026-05-04** — **P3 security bundle A (PR #67)** — four follow-ups from PR #64's review: (a) `markland-vrm` extended the defense-in-depth admin gate to `audit.list_recent_paginated`; (b) `markland-6ld` rotates `share_token` on a public→private visibility flip (sibling of PR #64's grant-revoke rotation); (c) `markland-89b` synthetic principal_id for invite-pending grants now matches real `usr_<16hex>` shape (length 20, no `pending_` infix), domain-separated SHA256 keeps idempotency; (d) `markland-vw2` invite dedup by `(doc_id, target_email)` — added `invites.target_email` column + `idx_invites_doc_target_email`, case-insensitive lookup, skips email re-enqueue on dedup. 23 new tests; full suite 1146 → 1163.
- **2026-05-04** — **Pre-release security review executed end-to-end.** Multi-agent review (`fdc1707`) filed 18 findings; **P0 batch shipped (PR #62, 3 findings)** — markdown XSS via `javascript:` link scheme (allowlist `http`/`https`/`mailto`/relative/fragment), JS-context XSS in `invite.html`/`settings_agents.html`/`device.html` (via `tojson`, delegated submit handler, `urlencode`), magic-link tokens scrubbed from logs + Sentry (new `markland.log_scrubbing` module masks `token`/`share_token`/`csrf`/`magic_link` query params, strips `Authorization` header). **P1+P2 batch shipped (PR #64, 11 commits, 10 findings)** — `mk_session` `SameSite=Strict`, agent-action inheritance bounded to view/edit (delete/visibility/feature/grant/revoke require explicit owner-grant on the agent), CSRF secret-fail-loud on empty `MARKLAND_SESSION_SECRET`, Dockerfile non-root `app` uid 1000, presence-strip principal_id/display_name/note for anonymous viewers, CSP `script-src` drops `'unsafe-inline'` via per-request `csp_nonce` woven through `render_with_nav`, `Fly-Client-IP` trust over `X-Forwarded-For`, content size caps (1MB UTF-8 / 500-char title), grant-by-unknown-email folds to silent invite (no email-existence oracle), share-token rotation when revoking grants on private docs, defense-in-depth admin gates on `docs_svc.feature` + `audit_svc.list_recent`. 3 P2 deferred to focused follow-ups (server-side session revocation epoch, O(N) Argon2 verify, logout-only-cookie). 13 P3 follow-ups filed as beads.
- **2026-05-04** — **MCP discovery hardened (PR #66)** — bearer auth advertised on `/mcp` so SDK probes don't crash on HTML 404. `WWW-Authenticate: Bearer realm="markland", resource_metadata="<base>/.well-known/oauth-protected-resource"` header on 401s (RFC 9728 / MCP authz spec 2025-03-26) + JSON-shaped `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server` routes. Closes `markland-2yj`. Plan `docs/plans/2026-05-03-mcp-auth-discovery.md`.
- **2026-05-04** — **MCP probe-path coverage extended (PR #68)** — followup to PR #66 after a real-user install verified the SDK probes more paths than expected. Added JSON 404 to `/.well-known/oauth-protected-resource/mcp`, `/.well-known/oauth-authorization-server/mcp`, `/.well-known/openid-configuration[/mcp]`, `GET/POST /register` (RFC 7591). Parametrized integration test (`tests/test_well_known_integration.py::test_every_observed_probe_path_returns_json`) covers all 10 paths so a future SDK adding a new probe fails fast in CI. Quickstart doc republished with `--scope user` + `https://markland.dev/mcp/` (trailing slash, skips 307 redirect). End-to-end smoke verified with real Claude Code install — 27 tools loaded. Closes `markland-6o6`. Plan `docs/plans/2026-05-04-mcp-oauth-probe-coverage.md`. Open follow-up: `markland-dfj` (server-side accept of `/mcp` without redirect).
- **2026-05-04** — **MCP `/mcp` 307 redirect eliminated (PR #71)** — bare `POST /mcp` (no trailing slash) now hits the FastMCP sub-app directly via an explicit ASGI route registered before the Starlette mount, with `scope["path"]` rewritten to `/`. Production-verified: `POST /mcp` returns HTTP/2 200 `text/event-stream` with `mcp-session-id`, no `Location:` header. Investigation found `FastAPI(redirect_slashes=False)` doesn't work — Starlette's `Mount.handle` issues the 307 independently of the Router-level flag, AND falls through to a 404 when Mount stops redirecting. The explicit-route approach (with `_McpNoSlashASGI` class wrapping so Starlette treats it as raw ASGI not a request-response handler) is the working fix. Cold-reconnect should drop from ~18s to under 4s. Two stale redirect-pinning tests in `tests/test_proxy_headers.py` removed (they pinned the bug; obsolete now). Closes `markland-dfj`. Plan `docs/plans/2026-05-04-mcp-trailing-slash-redirect.md`.
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
- **2026-04-28 (recorded 2026-07-05)** — **EmailDispatcher observability** (plan `docs/plans/2026-04-28-dispatcher-observability.md`). `_classify` transient-vs-permanent error triage driving the retry ladder, `_recipient_hash` (sha256[:12]) so Sentry never sees a raw address, `_safe_sentry_capture` on retry exhaustion and permanent failure. Shipped in the 2026-04-28 era but never recorded in this log; caught and verified in source during the 2026-07-05 reconciliation audit.

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

- **2026-05-30** — **Share form collapsed behind a disclosure button** (PR #73, `fd3f1a9`). The viewer's grant/share form now sits behind a `<details>` disclosure styled to match the Delete button, with a grant-count badge — declutters the doc-viewer chrome for the common read-only case.
- **2026-05-29** — **Pre-launch clean up shipped.** 8-track bundle landed. **Track A** Phase 0 dogfood finish: operator-only sweep + audit-reconstruction of step 2.4 + synthetic 2.5/2.6 via operator's own agent token; one P0 discovered + fixed mid-run (`markland-9n0` Litestream UID drift, `chown -R app:app /data/.markland.db-litestream` restored WAL replication, durable post-fix because Dockerfile `USER app` since `markland-l2p`); evidence at `docs/launch/phase-0-evidence-2026-05-29/`; GO verdict on all 21 task rows. **Track B** homepage CRO: hero primary CTA flipped from `POST /api/waitlist` + "Pre-launch · we'll email when it's ready" copy to `GET /login` magic-link flow with "Sign in & try it"; mid-page CTA flipped to match; waitlist demoted to a footer aside for users who still want to wait; `/login` prefills the hero-typed email. **Track C** Blog post #2 live: ["How to share Claude Code output without copy-pasting"](https://markland.dev/blog/share-claude-code-output) (686 body words, 149-char meta description). **Track D** dashboard welcome / first-publish panel for new accounts (`user_has_owned_docs` service helper + `_welcome_first_publish.html` partial + `POST /api/me/dismiss-welcome` dismiss endpoint with year-long cookie; mirrors the `_connect_claude_code` pattern). **Track E1** self-service deletion Phase 1: `POST /d/{share_token}/delete` owner-only route + Delete button on `/dashboard` + viewer with typed-confirmation modal; Phase 2/3 stay deferred until first 25 organic signups land. **Tracks E2/E3** (formal privacy + ToS) were already shipped 2026-05-04 — agent dispatch confirmed no work outstanding. **Track F** Show HN draft queued at `docs/launch/2026-05-29-show-hn-draft.md` — NOT POSTED; gating language explicit: post only after a follow-up soak-window check confirms the funnel converts. Full suite: 1247 passing. Plan: `docs/plans/2026-05-29-pre-launch-cleanup.md`.
- **2026-05-09** — **Install/onboarding Options 2-4 shipped.** Two-phase build landed in 8 commits on `main`. **Phase 1 (CLI-first)** — `device-start` API response gains `verification_uri_complete` (RFC 8628 §3.2 single-link form: `verification_url + ?code=<user_code>`); standards-aware MCP clients pick up the one-click URL automatically. `/setup` runbook step 2 rewritten from "visit /device and enter the code ABCD-EFGH" to "Click here to authorize: /device?code=ABCD-EFGH"; step 1's documented response shape teaches the new field. Existing prefill behavior on `/device?code=…` pinned by an additional regression test that allocates a real code via `device-start`. **Phase 2 (browser-via-shares)** — new `has_authorized_device(conn, user_id)` service helper gates a new dashboard "Connect Claude Code" panel (`src/markland/web/templates/_connect_claude_code.html`); panel renders iff signed-in AND no authorized device AND no `mk_dismiss_connect=1` cookie. Dismiss button POSTs to new `POST /api/me/dismiss-connect-claude-code` (CSRF-protected, session-required, sets year-long cookie, returns 204). Successful `/device/confirm` redirect now sets the same cookie so the panel auto-dismisses on first device authorization. Footnote in the panel routes non-Claude-Code MCP clients to `/quickstart#other-clients`. Plan: `docs/plans/2026-05-04-install-onboarding-options-2-4.md`. Spec: `docs/specs/2026-05-04-install-onboarding-options-2-4-design.md`. Full suite: 1214 passing.
- **2026-05-04** — **Formal Terms of Service live.** `/terms` promoted from a "working terms summary for the public beta" to a full standard-shaped ToS: introduction & acceptance, definitions (Markland, You, Service, Account, Agent, Content, Public/Private Document), your account (16+ eligibility, agent-token responsibility), acceptable use (10 explicit prohibitions + reporting path), your content (ownership retained, license to operate, public-content disclosure), our service (beta status, availability, changes, pricing), termination (by you, by us, survival, discontinuation with 30-day notice), disclaimers (as-is/as-available), limitation of liability ($100 floor or 12 months paid), indemnification (incl. agent-action coverage), governing law (Delaware, no class actions), general (entire agreement, severability, no waiver, assignment, force majeure, notices), changes (14-day material-change notice), `legal@markland.dev` contact alias. Plan: `docs/plans/2026-05-04-formal-terms-of-service.md`.
- **2026-05-04** — **Formal privacy policy live.** `/privacy` promoted from a "working summary for the public beta" to a full standard-shaped privacy policy: information we collect (3 categories), how we use it, sub-processors (Fly.io, Resend, Cloudflare R2, Umami, Sentry, Anthropic), retention timelines per category, your rights and choices (access / correction / deletion / export / complaint), international transfers, security commitments incl. 72-hour breach notification, children's privacy, 14-day material-change notice on policy updates, `privacy@markland.dev` contact alias. Plan: `docs/plans/2026-05-04-formal-privacy-policy.md`.
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
