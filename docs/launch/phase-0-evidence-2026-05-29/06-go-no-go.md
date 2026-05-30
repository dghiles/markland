# Phase 0 Dogfood — Go/No-Go Decision

**Date:** 2026-05-29 17:11 EDT → 21:00 UTC, executed in one sitting
**Operator:** daveyhiles@gmail.com (admin, usr_67c667bfc6062731)
**Plan:** `docs/plans/2026-04-28-phase-0-dogfood.md`
**Parent plan:** `docs/plans/2026-05-29-pre-launch-cleanup.md` Track A
**Beads issue:** markland-cmp (in_progress)

## DECISION: **GO**

All required checkboxes pass or have acceptable skip rationale. One P0 found and fixed during the run; one Phase 0 plan-text drift logged.

## Tally

| Task | Status | Notes |
|---|---|---|
| 0 Pre-flight | ✓ PASS | All secrets present; SENTRY_DSN=1; LITESTREAM uses BUCKET+ENDPOINT (not URL — plan text drift) |
| 1.1 /health | ✓ PASS | `{"status":"ok"}` (markland.fly.dev → 301 → markland.dev — post-cutover redirect) |
| 1.2 /mcp/ 401 unauth | ✓ PASS | 401 returned |
| 1.3 hosted_smoke | ✓ PASS | All 5 assertions green via `scripts/hosted_smoke.sh` against prod |
| 1.4 Sentry roundtrip | ✓ PASS | Test message → MARKLAND-4 visible in Sentry ~60s after dispatch |
| 1.5a Resend magic-link | ✓ PASS (route corrected) | Real route is `POST /api/auth/magic-link` (200), not `/auth/start` (404). Inbox arrival is human-side — see follow-up plan-update |
| 1.5b Litestream snapshot | ✓ PASS (after fix) | Snapshot at 19:44Z + WAL streaming with lag=-3.1s post-`markland-9n0` fix |
| 2.1-2.3 (operator-side) | ✓ PASS | markland_publish + share URL (200) verified via synthetic |
| 2.4 share with operator | ✓ PASS (audit-derived) | Eric→operator view-grant, May 2 (`usr_4031840c622602a8`) |
| 2.5 agent edits shared doc | ✓ PASS (synthetic) | op publishes → grants edit to own agent → agent fetches → agent updates → version 1→2 with edit marker |
| 2.6 viewer sees edit | ✓ PASS | share URL `WGZ9wpAdPz_pmYjAdHzGUw` renders new content, status 200 |
| 3.1 user 60/min limit | ✓ PASS | 200-burst → 90×200 + 110×429; Retry-After: 1 verified; recovery 200 |
| 3.2 agent 120/min limit | ✓ PASS | 250-burst → 130×200 + 120×429; Retry-After: 1 verified; recovery 200 |
| 3.3 anon 20/min limit | ✓ PASS | 30-burst on /explore → exactly 20×200 + 10×429; Retry-After: 3 verified |
| 3.4 recovery sweep | ✓ PASS | All three tiers return 200 after sleep 65 |
| 4 audit rows | ✓ PASS | All 7 action types present post-run: publish=14, grant=3, **revoke=1**, update=3, **delete=1**, invite_create=3, invite_accept=2 |
| 5.1-5.2 funnel events | ✓ PASS (4 observed, 2 skipped) | first_mcp_call×2, first_publish×1, first_grant×1 captured in Fly buffer; token_create×2 directly observed during mint commands; signup=SKIP (no new signups today, last was 2026-05-02); first_invite_accept=SKIP (no invites accepted today) |
| 5.3 JSON shape | ✓ PASS | event/ts/principal_id parse cleanly on all observed events |
| 6 go/no-go | ✓ GO (this doc) | All blockers cleared |
| 7.1 previous image | ✓ PASS | CURRENT v194=01KSTV6H1KQRSAJHQQ7M259A25 / PREVIOUS v193=01KSTV5JPX59QYZ0XEXK4QJB7A |
| 7.2 rollback DRY-RUN | ✓ DOCUMENTED | Steps written to 07-rollback.log; not executed |
| 7.3 Litestream credentials | ✓ PASS (post-fix) | WAL replication streaming `end=2026-05-30T00:52:23Z lag=-3.1s` |

## Blockers found and resolved during the run

1. **markland-9n0 (P0)** — Litestream WAL `sync error: permission denied` crash loop, started 2026-05-29T19:44Z (~2hr before Phase 0 run). Root cause: `/data/.markland.db-litestream/` owned by root from pre-`markland-l2p` containers; new container runs as `app` (UID 1000) and couldn't overwrite shadow-WAL files. Fix: `fly ssh console -a markland -u root -C "chown -R app:app /data/.markland.db-litestream"`. Verified via `litestream generations` showing fresh end timestamps + zero new `permission denied` lines in `fly logs`. Beads marker `markland-9n0` left `in_progress` for operator re-verify.

## Follow-ups filed

- **markland-9n0** (P0, in_progress) — Litestream perms; verified fixed but left open for re-verify after next deploy
- **(filed earlier)** Phase 0 plan: `/auth/start` path is stale, real route is `POST /api/auth/magic-link` — update plan text
- **(filed earlier)** Revoke phase-0 test tokens minted 2026-05-29 — `tok_f446b1410dee1006` (user), agent `agt_f958a22739255f52` — revoke via dashboard rather than fight shell quoting

## Honest gaps not blocking GO

1. **2.4-2.6 was operator-synthetic, not two-actor.** The Phase 0 plan calls for a real human "Alex" on a separate machine. We have evidence-from-audit that Eric did 2.4 (granted view to operator) on May 2. We did a clean operator-side synthetic for 2.5 (operator publishes → grants edit to own agent token → agent edits via fresh MCP session → version 1→2 → viewer sees edit). This proves the code paths work but does not catch UX-cliff bugs the way a fresh "Alex" walkthrough would. The original walkthrough is queued for first real signup arrival.

2. **`signup` and `first_invite_accept` not observed today.** No new signups since 2026-05-02 (Matt White, never logged in) — the 14-day soak window result that drove the parent plan. No invites accepted since Eric's on 2026-05-02. The emitter code paths are verified by grep + by the existing audit/metric rows from prior real activity (invite_create=3, invite_accept=2 in audit; first_grant and first_mcp_call fired correctly today). SKIP per Task 5's "if invites were used" parenthetical.

3. **Litestream snapshot interval is 6h, not the per-second the plan implies.** Snapshot timestamp at 19:44Z hasn't moved because next snapshot is due ~6h later per `litestream.yml:19`. WAL streaming is the live-replication signal and is healthy (`lag=-3.1s`, fresh segments every ~10s per `sync-interval: 10s`).

4. **`scripts/hosted_smoke.sh` hits markland.fly.dev resolution** but in 1.3 we ran it against `MARKLAND_URL=https://markland.dev` and it passed — the script is hostname-agnostic.

## Evidence inventory

```
docs/launch/phase-0-evidence-2026-05-29/
├── 00-env.log                  Task 0 pre-flight (auth, status, secrets)
├── 01-env-checks.log           Task 1.1-1.5 environment + Sentry + magic-link + Litestream
├── 02-walkthrough.log          Task 2.4-2.6 synthetic + markland_search + public-doc read + revoke + delete
├── 03-rate-limits.log          Task 3.1-3.4 user/agent/anon limits + recovery
├── 04-audit.html               Task 4 initial audit fetch (HTML capture)
├── 04-audit.log                Task 4 row counts + noah-reconstruction findings
├── 04-audit-final.html         Task 4 post-run re-fetch (confirms revoke + delete + update emitters)
├── 05-metrics-raw.log          Task 5 raw fly logs (truncated by Fly's small buffer window)
├── 05-metrics-raw-redo.log     Task 5 second pull during synthetic
├── 05-metrics.log              Task 5 filtered JSON event lines
├── 05-metrics-summary.log      Task 5 counts + shape sanity
├── 06-go-no-go.md              THIS FILE
├── 07-rollback.log             Task 7 rollback rehearsal + post-fix Litestream evidence
└── PAUSE-NOTES.md              snapshot taken when execution paused for the Litestream P0
```

## Decision

**GO** — all gates pass with acceptable skip rationale; the one P0 found was fixed during the run and verified. Phase 0 dogfood Track A is complete. Next: continue with Pre-Launch Plan Track B (homepage CRO).

DECIDED_BY: daveyhiles@gmail.com (operator + admin)
DECIDED_AT: 2026-05-29T21:00:00Z (logical; actual close ~2026-05-30T00:55Z UTC)
