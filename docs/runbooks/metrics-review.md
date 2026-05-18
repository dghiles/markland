# Metrics Review — Runbook

How to answer "what's actually happening on markland.dev?" — the soak-window
check, a who's-on-here pass, and the standard funnel snapshot. Run this any
time you want a real picture instead of a vibe.

Three data sources, in order of usefulness:

1. **`/admin/metrics`** — funnel counts derived from the audit log + counts of
   live rows. Cheap, fast, no PII beyond what admin tokens already see.
2. **`scripts/admin/list_users.py`** — who's actually signed up. The "is
   there anyone I don't know personally?" question.
3. **`scripts/admin/umami_summary.py`** — referrers + top pages. Where any
   unexpected arrival came from.

All three require an admin token. Mint one per
[`admin-operations.md`](admin-operations.md#minting-a-test-admin-token) and
revoke it (`/settings/tokens`) when you're done.

## 1. Funnel snapshot

```bash
./scripts/admin/curl-admin "/admin/metrics?window_seconds=1209600" | jq    # 14d
./scripts/admin/curl-admin "/admin/metrics?window_seconds=2592000" | jq    # 30d
```

`window_seconds` is capped at 30d server-side; larger values silently clamp.

**What to look at:**

- Funnel deltas: `signups`, `publishes`, `grants_created`, `invites_accepted`,
  `invites_created`, `documents_*`.
- Cumulative totals: `users_total`, `documents_total`,
  `documents_public_total`, `waitlist_total`, `grants_total`, `invites_total`.
- Soft gauge: `first_mcp_call` (currently always `null` — known gap, no
  `mcp_call` event in the audit log yet; see commit `bcc0fc0`).

**Healthy signal:** non-zero deltas in the 30d window even if 14d is flat.
All-zero across both windows when you _know_ there's been activity = audit-log
action names drifted (regression of PR #35's fix).

## 2. Who's signed up

```bash
flyctl ssh console -a markland -C \
    "/app/.venv/bin/python scripts/admin/list_users.py"
```

Prints one row per user with email, admin flag, created_at, doc counts,
grants received, active tokens, and last-token-use timestamp. Ordered newest
first.

Useful flags:

```bash
# Last 7 days only
flyctl ssh console -a markland -C \
    "/app/.venv/bin/python scripts/admin/list_users.py --since 7"

# Cap output
flyctl ssh console -a markland -C \
    "/app/.venv/bin/python scripts/admin/list_users.py --limit 20"
```

**What to look at:** any email you don't recognise. If everyone's an account
you minted, friend you invited, or known tester, no stranger has signed up.

## 3. Where traffic came from

```bash
flyctl ssh console -a markland -C \
    "/app/.venv/bin/python scripts/admin/umami_summary.py --days 14"
```

`UMAMI_API_KEY` is set as a Fly secret — the script reads it from the prod
env. Never copy it locally; always run via fly ssh.

Output is JSON (pipe through `jq` if you want to slice it). Key sections:

- `stats` — visitors / visits / pageviews / bounce rate for the window.
- `pageviews_by_day` — daily timeseries; spots one-day spikes.
- `top_urls` — which pages are getting traffic (landing vs. shared doc URLs
  vs. `/setup`).
- `top_referrers` — where readers came from. Anything that isn't direct,
  your own posts, or known channels = an outside arrival to investigate.
- `top_browsers`, `top_countries` — sanity checks.

## Cross-reference (sanity check)

If `/admin/metrics` shows N signups in a window and Umami shows ~0 unique
visitors over the same window, something's wrong with one of them
(beacon CSP issue, blocked client, or audit-log gap). When they roughly
agree (visitor count >= signups, usually 10–100x), both pipelines are
healthy.

## When to run this

- **Two weeks post-launch** — first soak-window check
  (beads `markland-fjd`).
- **Before any external announcement** — capture a "before" baseline so you
  can measure lift.
- **After any analytics-touching change** — confirm CSP didn't break the
  beacon and audit-log action names didn't drift.
- **Whenever you wonder "is anything happening?"** — cheaper than guessing.
