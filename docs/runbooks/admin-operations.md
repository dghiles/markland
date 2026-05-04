# Admin Operations - Runbook

How to do common admin tasks against the live `markland.dev` instance. Three
surfaces are available depending on context: **MCP tools** (call from Claude
Code or any MCP client with an admin token), **HTTP endpoints** (curl with
`Authorization: Bearer <admin_token>`), and **direct SQL** via `flyctl ssh
console` (last resort, for things no tool exposes).

All MCP and HTTP admin paths gate on `users.is_admin = 1`. A non-admin token
returns `403 forbidden` (HTTP) or a `forbidden` tool error (MCP).

## Admin scripts

Common admin tasks are checked-in scripts under `scripts/admin/`, deployed
to `/app/scripts/admin/` on the Fly image. Run them with the project's
venv-resolved Python:

```bash
flyctl ssh console -a markland -C "/app/.venv/bin/python scripts/admin/<name>.py [args]"
```

The Fly base image does NOT include the `sqlite3` CLI binary, and system
Python doesn't have project deps installed — always use
`/app/.venv/bin/python` with the named scripts below. They import the real
service helpers, so they survive schema/auth-hash changes.

Available scripts:

| Script | Purpose |
|---|---|
| `make_admin.py <email>` | Flip `is_admin=1` on a user. |
| `mint_admin_token.py [label]` | Mint a fresh user-token bound to the first admin. Plaintext printed once. |
| `lookup_user.py <email>` | Show user row + doc/grant/token counts. |
| `list_admin_tokens.py` | List metadata of admin-bound tokens (no plaintexts; revocation cleanup). |

## Becoming an admin

Admin status is a `users.is_admin` boolean. There is no UI to toggle it -
flip it directly the first time, then any further admins can grant
themselves access the same way.

```bash
flyctl ssh console -a markland -C "/app/.venv/bin/python scripts/admin/make_admin.py you@example.com"
```

You must have signed in (via magic link) at least once for the row to
exist. After flipping, your existing tokens already carry admin status on
the next request - `is_admin` is read from the DB at token-resolution
time, not baked into the token itself.

## Minting a test admin token

Tokens are Argon2id-hashed; existing plaintexts are unrecoverable. To get
a working bearer for `curl`-ing the admin endpoints, mint a fresh one and
park it in `.env.local` so subsequent commands don't need to repeat the
ssh dance.

**One-time setup:**

1. Copy the template if you haven't yet: `cp .env.example .env.local`
2. Mint the token:
   ```bash
   flyctl ssh console -a markland -C "/app/.venv/bin/python scripts/admin/mint_admin_token.py runbook-test"
   ```
3. Paste the printed `mk_usr_...` value into `.env.local` as
   `MARKLAND_PROD_ADMIN_TOKEN`.

`.env.local` is gitignored. Revoke at `/settings/tokens` (find the
`runbook-test` label) when you're done — leaving long-lived admin bearers
on disk is a security smell.

## Calling /admin/* endpoints

Once `.env.local` is set, use the helper:

```bash
./scripts/admin/curl-admin /admin/metrics | jq
./scripts/admin/curl-admin "/admin/metrics?window_seconds=86400" | jq
./scripts/admin/curl-admin "/admin/waitlist?limit=10" | jq
```

The helper sources `.env.local`, sets the bearer header, and prefixes
`MARKLAND_PROD_BASE_URL` (default `https://markland.dev`). Pass any extra
`curl` args after the path: `./scripts/admin/curl-admin /admin/metrics -i`
to see headers, etc.

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

**HTTP equivalent (using the helper):**

```bash
./scripts/admin/curl-admin "/admin/metrics?window_seconds=86400" | jq
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
./scripts/admin/curl-admin "/admin/waitlist?limit=50" | jq
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

For users, use the lookup script:

```bash
flyctl ssh console -a markland -C "/app/.venv/bin/python scripts/admin/lookup_user.py alice@example.com"
```

It prints the user row plus doc-owned, grants-received, and active-token
counts in one shot.

For anything not covered by an existing script, see "One-off SQL queries"
below — that's the pattern for ad-hoc reads.

The `documents` table has `id, title, share_token, is_public, is_featured,
owner_id, version, created_at, updated_at`. Use `share_token` (not `id`) to
construct the share URL: `https://markland.dev/d/<share_token>`.

## One-off SQL queries

For ad-hoc reads not worth scripting (forensics, "show me X for one user",
debugging in production), the pattern is `flyctl ssh console` + the
project's venv Python + an inline `python -c`. Use this template:

```bash
flyctl ssh console -a markland -C "/app/.venv/bin/python -c '
import sqlite3
from markland.config import get_config
c = sqlite3.connect(get_config().db_path)
for r in c.execute(\"<YOUR SELECT HERE>\"):
    print(r)
'"
```

Notes:
- Always use `/app/.venv/bin/python` (system Python lacks project deps).
- `get_config().db_path` is the canonical path — don't hard-code
  `/data/markland.db`.
- Wrap multi-line bodies in single quotes; escape inner double quotes with
  `\"`. Use parameterised queries (`?` placeholders + a tuple) for any
  user-supplied value to avoid SQL-injection in your own scripts.
- This is a **read** pattern. For writes, prefer a checked-in script under
  `scripts/admin/` so the change is reviewable and idempotent — see
  `scripts/admin/make_admin.py` as a template.

### Common one-liners

**List all users (most-recent first):**

```bash
flyctl ssh console -a markland -C "/app/.venv/bin/python -c 'import sqlite3; from markland.config import get_config; c=sqlite3.connect(get_config().db_path); [print(r) for r in c.execute(\"SELECT email, display_name, is_admin, created_at FROM users ORDER BY created_at DESC\")]'"
```

**Grants on a specific document:**

```bash
flyctl ssh console -a markland -C "/app/.venv/bin/python -c 'import sqlite3; from markland.config import get_config; c=sqlite3.connect(get_config().db_path); [print(r) for r in c.execute(\"SELECT principal_id, principal_type, level FROM grants WHERE doc_id=?\", (\"<doc_id>\",))]'"
```

**Documents owned by a user (by email):**

```bash
flyctl ssh console -a markland -C "/app/.venv/bin/python -c 'import sqlite3; from markland.config import get_config; c=sqlite3.connect(get_config().db_path); [print(r) for r in c.execute(\"SELECT id, title, is_public, created_at FROM documents WHERE owner_id=(SELECT id FROM users WHERE email=?)\", (\"alice@example.com\",))]'"
```

**Recent audit rows for a principal:**

```bash
flyctl ssh console -a markland -C "/app/.venv/bin/python -c 'import sqlite3; from markland.config import get_config; c=sqlite3.connect(get_config().db_path); [print(r) for r in c.execute(\"SELECT created_at, action, doc_id, metadata FROM audit_log WHERE principal_id=? ORDER BY id DESC LIMIT 50\", (\"<principal_id>\",))]'"
```

If you find yourself running the same query repeatedly, promote it to a
checked-in script under `scripts/admin/` — same pattern as the existing
ones (see `lookup_user.py` for shape).

### PII reminder

User emails, audit metadata, and document content are all PII. Reads via
this pattern are NOT logged in the audit table — they bypass the
application entirely. Treat these queries the same way you'd treat looking
at someone's inbox: only when there's a concrete operational reason, and
don't paste results into anywhere they'll be retained (chat, screenshots,
public docs).

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

## MCP install troubleshooting

Markland uses **static bearer tokens**, not OAuth. But MCP clients (e.g.
Claude Code's SDK) auto-probe OAuth-discovery paths on every connection
attempt. To avoid the SDK's JSON parser crashing on Markland's HTML 404
page, the server returns JSON 404 for every observed probe path:

| Path | Status | Notes |
|---|---|---|
| `GET /.well-known/oauth-protected-resource` | 200 JSON | RFC 9728 metadata, `authorization_servers: []` |
| `GET /.well-known/oauth-authorization-server` | 404 JSON | Signals "no OAuth server" |
| `GET /.well-known/oauth-protected-resource/` | 404 JSON | trailing-slash variant |
| `GET /.well-known/oauth-protected-resource/mcp` | 404 JSON | `/mcp` suffix variant |
| `GET /.well-known/oauth-authorization-server/mcp` | 404 JSON | `/mcp` suffix variant |
| `GET /.well-known/openid-configuration` | 404 JSON | OIDC fallback |
| `GET /.well-known/openid-configuration/mcp` | 404 JSON | `/mcp` suffix variant |
| `GET/POST /register` | 404 JSON | RFC 7591 dynamic client registration |
| `GET /mcp/.well-known/openid-configuration` | 401 JSON | Behind PrincipalMiddleware (correct) |

If a future MCP client probes a NEW path that returns HTML, add it to
`src/markland/web/well_known_routes.py` (route + test) — the regression
net is `tests/test_well_known_integration.py::test_every_observed_probe_path_returns_json`.
Filed history: markland-2yj (PR #66), markland-6o6 (PR #68).

**`/mcp` URL must end in trailing slash.** FastMCP serves at `/mcp/`; a bare
`/mcp` produces a 307 redirect on every request, adding 5–8s of latency to
client startup. The Quickstart doc and `device_routes.py` both use the
trailing-slash form. Filed: markland-dfj (proper server-side fix to handle
both forms without redirect).

**Symptom: user reports "Auth: not authenticated" or stuck "Authenticating
with markland..." in `/mcp` panel.** Most common cause: their token was
revoked or never made it into `~/.claude.json`. Check from the admin side:

```bash
flyctl ssh console -a markland -C "/app/.venv/bin/python -c 'import sqlite3; from markland.config import get_config; c=sqlite3.connect(get_config().db_path); [print(r) for r in c.execute(\"SELECT id, label, created_at, revoked_at FROM tokens t JOIN users u ON t.principal_id=u.id WHERE u.email=? ORDER BY t.created_at DESC LIMIT 5\", (\"USER_EMAIL\",))]'"
```

Look for `revoked_at IS NULL` rows. If none, ask the user to mint a fresh
token at `/settings/tokens` and re-run `claude mcp add`.

## Republishing the live Quickstart doc

When the install command in the published Quickstart drifts (e.g. after a
client-side change to `claude mcp add` or a new convention like the
trailing-slash URL), use `scripts/admin/republish_doc.py` to push the
local `seed-content/admin/07-quickstart-claude-code.md` to production:

```bash
cat > /tmp/sftp_quickstart.txt << 'EOF'
put seed-content/admin/07-quickstart-claude-code.md /tmp/quickstart.md
EOF
flyctl ssh sftp shell -a markland < /tmp/sftp_quickstart.txt
flyctl ssh console -a markland -C "/app/.venv/bin/python scripts/admin/republish_doc.py \
    --doc-id 3366aa58f6ead5e7 \
    --owner-email daveyhiles@gmail.com \
    --content-path /tmp/quickstart.md"
```

The doc's `id` is stable — `3366aa58f6ead5e7`. Its share URL is
`https://markland.dev/d/ukglp7mO8Dbyx2SbvYOoWg` (featured on the landing
page). Version increments on each republish.

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
- `docs/plans/2026-05-03-mcp-auth-discovery.md` - markland-2yj: original WWW-Authenticate + JSON well-known fix
- `docs/plans/2026-05-04-mcp-oauth-probe-coverage.md` - markland-6o6: extended probe-path coverage
