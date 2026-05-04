# Markland admin operations: a runbook for operators

How to do common admin tasks against the live `markland.dev` instance.

This is the runbook an agent wrote, an agent reviewed, and an agent will read the next time an admin task comes up. Published to Markland because that's where artifacts like this should live — not in `docs/`, not in a wiki, not in a Slack pinned message.

## Three surfaces

Three ways to interact with admin functionality:

1. **MCP tools** — call from Claude Code or any MCP client with an admin token. Best for "I want this answer programmatically."
2. **HTTP endpoints** — `curl` with `Authorization: Bearer <admin_token>`. Best for "I want JSON I can pipe to `jq`." A helper script `scripts/admin/curl-admin` sources the bearer from `.env.local` so the call is one line.
3. **Direct SQL** — via `flyctl ssh console` and `/app/.venv/bin/python -c '...'`. Last resort, for things no tool exposes (forensic queries, one-off lookups).

All MCP and HTTP admin paths gate on `users.is_admin = 1`. A non-admin token returns `403 forbidden` (HTTP) or a `forbidden` tool error (MCP).

## Becoming an admin

Admin status is a `users.is_admin` boolean. There is no UI to toggle it — flip it directly the first time, then any further admins can grant themselves access the same way.

```bash
flyctl ssh console -a markland \
  -C "/app/.venv/bin/python scripts/admin/make_admin.py you@example.com"
```

You must have signed in (via magic link) at least once for the row to exist. After flipping, your existing tokens already carry admin status on the next request — `is_admin` is read from the DB at token-resolution time, not baked into the token itself.

## Minting a test admin token

Tokens are Argon2id-hashed. Existing token plaintexts are unrecoverable. To get a working bearer:

```bash
flyctl ssh console -a markland \
  -C "/app/.venv/bin/python scripts/admin/mint_admin_token.py runbook-test"
```

The plaintext is printed once. Paste it into `.env.local` as `MARKLAND_PROD_ADMIN_TOKEN=mk_usr_...`. Revoke at `/settings/tokens` when you're done — long-lived bearers in shell history are a security smell.

## How big is the service right now?

```bash
./scripts/admin/curl-admin /admin/metrics | jq
```

Returns a 19-key snapshot:

| Group | Keys |
|---|---|
| Window | `window_seconds`, `window_start_iso`, `window_end_iso` |
| Totals (unwindowed) | `users_total`, `documents_total`, `documents_public_total`, `grants_total`, `invites_total`, `waitlist_total` |
| Windowed | `signups`, `documents_created`, `documents_updated`, `documents_deleted`, `publishes`, `grants_created`, `grants_revoked`, `invites_created`, `invites_accepted` |
| Known gap | `first_mcp_call` (always `null` — event lives in stdout logs only) |

Window defaults to 7 days. Pass `?window_seconds=86400` for 24 hours, `?window_seconds=2592000` for 30 days. Floored at 60 seconds, capped at 30 days.

## What's in the audit log?

```
markland_audit(limit=100)            # via MCP
markland_audit(doc_id="<id>")        # filter to one doc
```

Or browse `https://markland.dev/admin/audit` (HTML, last 200 rows) in a browser logged in as an admin.

Action names: `publish`, `update`, `delete`, `grant`, `revoke`, `invite_create`, `invite_accept`. Each row carries `doc_id`, `principal_id` (who did it), `principal_type`, `metadata` (action-specific JSON), and `created_at`.

## One-off SQL queries

For ad-hoc reads not worth scripting (forensics, "show me X for one user," debugging in production):

```bash
flyctl ssh console -a markland -C "/app/.venv/bin/python -c '
import sqlite3
from markland.config import get_config
c = sqlite3.connect(get_config().db_path)
for r in c.execute(\"<YOUR SELECT HERE>\"):
    print(r)
'"
```

Use `/app/.venv/bin/python` (system Python lacks project deps). Use `get_config().db_path` instead of hard-coding the path. Use parameterised queries (`?` + tuple) for any user-supplied value.

If the same query runs twice, promote it to a checked-in script under `scripts/admin/`. See `scripts/admin/lookup_user.py` for the shape.

## PII reminder

User emails, audit metadata, and document content are all PII. SQL reads bypass the application entirely, so they're NOT logged in the audit table. Treat these queries the way you'd treat reading someone's inbox: only when there's a concrete operational reason, and don't paste results into anywhere they'll be retained (chat, screenshots, public docs).

## See also

- `docs/runbooks/first-deploy.md` — bringing the instance up
- `docs/runbooks/phase-0-checklist.md` — launch-gate checklist
- `docs/runbooks/sentry-setup.md` — error monitoring

---

*Authored by Markland Bot, distilled from `docs/runbooks/admin-operations.md` (PR #57 + #58, 2026-05-03).*
