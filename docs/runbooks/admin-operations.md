# Admin Operations - Runbook

How to do common admin tasks against the live `markland.dev` instance. Three
surfaces are available depending on context: **MCP tools** (call from Claude
Code or any MCP client with an admin token), **HTTP endpoints** (curl with
`Authorization: Bearer <admin_token>`), and **direct SQL** via `flyctl ssh
console` (last resort, for things no tool exposes).

All MCP and HTTP admin paths gate on `users.is_admin = 1`. A non-admin token
returns `403 forbidden` (HTTP) or a `forbidden` tool error (MCP).

## Becoming an admin

Admin status is a `users.is_admin` boolean. There is no UI to toggle it - flip
it directly in SQL the first time, then any further admins can grant
themselves access the same way.

```bash
flyctl ssh console -a markland -C "sqlite3 /data/markland.db \"UPDATE users SET is_admin=1 WHERE email='you@example.com'\""
```

Verify:

```bash
flyctl ssh console -a markland -C "sqlite3 /data/markland.db \"SELECT id, email, is_admin FROM users WHERE email='you@example.com'\""
```

After flipping, your existing tokens already carry admin status on the next
request - the flag is read from the DB at token-resolution time, not baked
into the token itself.

## How big is the service right now?

Use `markland_admin_metrics` (MCP) or `GET /admin/metrics` (HTTP). Both
return the same 19-key snapshot.

**MCP (default 7-day window):**

```
markland_admin_metrics()
```

**MCP (custom window, e.g. 24 hours):**

```
markland_admin_metrics(window_seconds=86400)
```

Window is floored at 60 seconds and capped at 30 days (2_592_000).

**HTTP equivalent:**

```bash
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  "https://markland.dev/admin/metrics?window_seconds=86400" | jq
```

**Response shape:**

| Group | Keys |
|---|---|
| Window | `window_seconds`, `window_start_iso`, `window_end_iso` |
| Totals (unwindowed) | `users_total`, `documents_total`, `documents_public_total`, `grants_total`, `invites_total`, `waitlist_total` |
| Windowed | `signups`, `documents_created`, `documents_updated`, `documents_deleted`, `publishes`, `grants_created`, `grants_revoked`, `invites_created`, `invites_accepted` |
| Known gap | `first_mcp_call` (always `null` - event lives in stdout logs only; check `flyctl logs -a markland`) |

**`signups` vs `users_total`:** `users_total` is unwindowed and includes
admin-side seeded users (e.g. grant targets created via email lookup before
the user signs up). `signups` is the windowed `users.created_at` count and
has the same caveat. Visitor counts (anonymous traffic) are NOT in this
tool - check the Umami dashboard at `https://cloud.umami.is/` for those.

## What's in the audit log?

Use `markland_audit` (MCP) or `GET /admin/audit` (HTML page).

**Recent events across all docs (MCP):**

```
markland_audit(limit=100)
```

**Filter to one doc:**

```
markland_audit(doc_id="<doc_id>", limit=100)
```

**Pagination:** the response includes a `next_cursor`; pass it back as
`cursor=` to get the next page. Newest-first ordering.

**HTTP (HTML, last 200 rows):**

```
https://markland.dev/admin/audit
```

Open this in a browser logged in as an admin user (session cookie carries
the principal). Useful for ad-hoc forensic browsing; the MCP tool is better
for programmatic reads.

**Action names you'll see:** `publish`, `update`, `delete`, `grant`,
`revoke`, `invite_create`, `invite_accept`. Each row has `doc_id`,
`principal_id` (the user/agent who performed the action), `principal_type`,
`metadata` (action-specific JSON), and `created_at`.

## Who's on the waitlist?

`GET /admin/waitlist` returns the recent N entries plus a per-day signup
histogram and total count.

```bash
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  "https://markland.dev/admin/waitlist?limit=50" | jq
```

`limit` defaults to 50, capped at 500. Response shape: `{total, by_day:
[{day, count}, ...], recent: [{email, source, created_at}, ...]}`.

## Featuring a document on the landing page

`markland_feature` promotes a public doc to the "featured" slot rendered on
`/` (landing page).

```
markland_feature(doc_id="<doc_id>", featured=true)
```

Set `featured=false` to demote. The doc must already be public
(`is_public=1`) for the change to be visible to anonymous visitors. Check
current state via `markland_get(doc_id)` - the response includes the
`is_featured` flag.

## Looking up a specific user or document

No dedicated admin tool for this; use direct SQL. Common queries:

```bash
# Find a user by email
flyctl ssh console -a markland -C "sqlite3 /data/markland.db \"SELECT id, email, display_name, is_admin, created_at FROM users WHERE email='alice@example.com'\""

# How many docs does a user own?
flyctl ssh console -a markland -C "sqlite3 /data/markland.db \"SELECT COUNT(*) FROM documents WHERE owner_id=(SELECT id FROM users WHERE email='alice@example.com')\""

# Who has access to a specific doc?
flyctl ssh console -a markland -C "sqlite3 /data/markland.db \"SELECT principal_id, principal_type, level FROM grants WHERE doc_id='<doc_id>'\""
```

The `documents` table has `id, title, share_token, is_public, is_featured,
owner_id, version, created_at, updated_at`. Use `share_token` (not `id`) to
construct the share URL: `https://markland.dev/d/<share_token>`.

## Reading metrics from the host

For the `first_mcp_call` event (which is stdout-only, no DB row), tail Fly
logs:

```bash
flyctl logs -a markland | grep first_time
```

For the structured access log (every request):

```bash
flyctl logs -a markland | grep -v 'GET /health'
```

## Common questions

**"How many people are using this?"** → `markland_admin_metrics()` -
`users_total` for total accounts, `signups` for new accounts in the window.
Add the Umami dashboard for anonymous-visitor counts.

**"Are people actually publishing?"** → `markland_admin_metrics()` -
`publishes` and `documents_created` over a 7d window. If `documents_created`
≫ `publishes`, accounts are creating docs but not publicising them.

**"Has anything weird happened recently?"** → `markland_audit(limit=200)` -
scan for unexpected `delete`/`revoke` actions or activity from unfamiliar
`principal_id` values.

**"Why is the funnel quieter than expected?"** → check `waitlist_total`
(landing-page sign-ups still flowing?), then `signups` (waitlist converting
to accounts?), then `publishes` (new accounts publishing?). The drop-off
point tells you which step needs attention.

## Out of scope

- **Editing data via tools.** No admin tool can rewrite a doc's content,
  change ownership, or hard-delete. Use SQL via `flyctl ssh console` if you
  need to.
- **Per-user breakdowns.** The metrics tool returns aggregates only. For
  "top 10 publishers" or "users with most grants," write a one-off SQL
  query.
- **Time-series / charts.** This is a point-in-time snapshot tool. For
  trends, run the same call at different `window_seconds` and compare, or
  build a separate dashboard.

## See also

- `docs/runbooks/first-deploy.md` - bringing the instance up
- `docs/runbooks/phase-0-checklist.md` - launch-gate checklist
- `docs/runbooks/sentry-setup.md` - error monitoring
- `docs/FOLLOW-UPS.md` - `first_mcp_call` event-table follow-up
