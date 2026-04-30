# First Deploy - Operator Runbook

One-time manual steps to stand up `markland.dev` on Fly.io. After this runbook
completes, `git push origin main` triggers `.github/workflows/deploy.yml` and
every subsequent deploy is automatic.

This runbook unblocks Plan 1 tasks 11-12 of
`docs/plans/2026-04-19-hosted-infra.md` (human-gated Fly deploy).

## Current deploy state (2026-04-20)

The initial deploy ran on 2026-04-20 against the Fly-assigned hostname because
`markland.dev` isn't owned yet. Running this runbook top-to-bottom from a clean
slate is still the right path; the checklist below is what's **already done**
vs. what remains:

| Step | Status |
|------|--------|
| 1. Prerequisites | flyctl installed, `daveyhiles@gmail.com` authenticated |
| 2. Resend domain verify | **pending** — blocked on domain purchase |
| 3. R2 bucket + keys | **pending** |
| 4. Generate secrets | done — `MARKLAND_SESSION_SECRET` set on Fly |
| 5. `flyctl launch` | done — app `markland` exists in org `personal`, region `iad` |
| 6. Volume | done — 1 GB volume `data` at `/data` (note: Fly normalized the name from `markland_data`) |
| 7. Set secrets | only `MARKLAND_SESSION_SECRET` set; Resend + Litestream + Sentry pending |
| 8. First deploy | done — machine `185191df264378`, image `registry.fly.io/markland:deployment-01KPP72Q8GWW5647TAK5HVM2BD` |
| 9. IPs + DNS | shared v4 + dedicated v6 attached; dedicated v4 and Cloudflare DNS **pending** (blocked on domain) |
| 10. TLS cert | **pending** (blocked on DNS) |
| 11. Sign in, mint smoke token | **pending** (blocked on Resend for magic-link email; dev fallback via `flyctl logs` is available) |
| 12. CI deploy token | **pending** |

Current public URL: `https://markland.fly.dev/`. `fly.toml` has
`MARKLAND_BASE_URL = 'https://markland.fly.dev'` — flip back to
`https://markland.dev` and redeploy once DNS + cert land.

---

## Notes before you run this

- **`/mcp` auth model.** Plan 1 gated `/mcp` with a single `MARKLAND_ADMIN_TOKEN`
  bearer. Plan 2 replaced that with `PrincipalMiddleware` — `/mcp` now requires
  any valid per-user or per-agent API token (`mk_usr_*` / `mk_agt_*`) minted
  after sign-in. `MARKLAND_ADMIN_TOKEN` is still read by `config.py` for
  back-compat but is not used in the request path. **Do not rely on it to
  reach `/mcp`.** The verification steps below use `MARKLAND_SMOKE_TOKEN`,
  which is any user token you generated via `/settings/tokens` after signing
  in for the first time.
- **`fly.toml` has no explicit `[processes]` table.** Fly infers an `app`
  process group from the Dockerfile `ENTRYPOINT`, which is what we want.
  If `flyctl launch` complains, add `[processes] app = "/app/start.sh"`.
- **Plan 1 Task 11 vs. older drafts.** `flyctl volumes create ... --size 1`
  is enough for launch (< 100 users, markdown only). Grow later with
  `flyctl volumes extend`.

---

## 1. Prerequisites

Before you start, have the following ready:

| Item | Why |
|------|-----|
| Fly.io account with a payment method on file | Required for volumes + IPs |
| Cloudflare account with `markland.dev` on it | DNS + R2 bucket for Litestream |
| Resend account | Transactional email (magic links, etc.) |
| GitHub repo admin access | To set `FLY_API_TOKEN` secret for CI |
| `flyctl` installed locally | `brew install flyctl` (macOS) or https://fly.io/docs/flyctl/install/ |
| `openssl` available locally | For generating secrets |
| Docker (optional) | Only needed if you want to `docker build` locally before first deploy |

Authenticate once:

```bash
flyctl auth login
```

---

## 2. Resend - verify sending domain

1. Sign up / log in at https://resend.com.
2. Domains -> Add domain -> `markland.dev`.
3. Copy the DNS records Resend shows (MX, TXT/SPF, DKIM, return-path) and
   add them in Cloudflare DNS for `markland.dev`. (Cloudflare proxy
   status: DNS only / grey cloud for all mail-related records.)
4. Wait for Resend's verification to go green (usually < 5 min).
5. API Keys -> Create API Key -> scope: "Sending access" for
   `markland.dev` only. Copy the key - you won't see it again.

Record:
- `RESEND_API_KEY=re_...`
- `RESEND_FROM_EMAIL=notifications@markland.dev` (matches `fly.toml`)

---

## 3. Cloudflare R2 - Litestream replica bucket

1. Cloudflare Dashboard -> R2 -> Create bucket.
2. Name: `markland-db`. Location: Automatic. No public access.
3. Note your **Account ID** (top-right of the R2 page, or
   `https://dash.cloudflare.com/<accountid>/...` in the URL).
4. R2 -> Manage R2 API Tokens -> Create API Token.
   - Permission: **Object Read & Write**
   - Specify bucket: **`markland-db` only**
   - TTL: no expiry (rotate manually)
5. Copy the **Access Key ID**, **Secret Access Key**, and note the
   **S3 endpoint** shown (e.g. `https://<accountid>.r2.cloudflarestorage.com`).

Record:
- `LITESTREAM_ACCESS_KEY_ID=<r2 access key id>`
- `LITESTREAM_SECRET_ACCESS_KEY=<r2 secret>`
- `LITESTREAM_REPLICA_URL=s3://markland-db.<accountid>.r2.cloudflarestorage.com/markland`

The URL matches the interpolation template in `litestream.yml`.

---

## 4. Generate app secrets

```bash
# Signs session cookies + magic-link tokens. Required.
MARKLAND_SESSION_SECRET="$(openssl rand -hex 32)"

echo "SESSION_SECRET: $MARKLAND_SESSION_SECRET"
```

Store in your password manager **now**. Rotating the session secret logs out
all users immediately (API tokens remain valid — they use Argon2id hashes,
not this secret).

---

## 5. Register the Fly app (no deploy yet)

From the repo root:

```bash
flyctl launch --copy-config --no-deploy --name markland --region iad
```

Answer prompts:
- "Would you like to copy its configuration?" -> **Yes** (uses the repo's `fly.toml`)
- "Would you like to deploy now?" -> **No**
- Postgres / Redis / Sentry wizard offers -> **No** to all

This creates the Fly app record without running a machine.

---

## 6. Create the persistent volume

```bash
flyctl volumes create markland_data --region iad --size 1
```

The name `markland_data` matches `[[mounts]] source` in `fly.toml`; mount
destination is `/data` (= `MARKLAND_DATA_DIR` in `fly.toml [env]`).

Size 1 GB is enough for Plan 1 (< 100 users, markdown only). Grow with
`flyctl volumes extend` later.

---

## 7. Set secrets on Fly

```bash
flyctl secrets set \
  MARKLAND_SESSION_SECRET="$MARKLAND_SESSION_SECRET" \
  SENTRY_DSN="<paste your sentry dsn, or omit this line to leave unset>" \
  RESEND_API_KEY="$RESEND_API_KEY" \
  LITESTREAM_REPLICA_URL="s3://markland-db.<accountid>.r2.cloudflarestorage.com/markland" \
  LITESTREAM_ACCESS_KEY_ID="$LITESTREAM_ACCESS_KEY_ID" \
  LITESTREAM_SECRET_ACCESS_KEY="$LITESTREAM_SECRET_ACCESS_KEY"
```

Note: `MARKLAND_BASE_URL`, `MARKLAND_DATA_DIR`, `MARKLAND_WEB_PORT`, and
`RESEND_FROM_EMAIL` are already in `fly.toml [env]` (non-secret, visible
in the dashboard) and do **not** need to be set here.

Verify:

```bash
flyctl secrets list
```

Expected: all 6 secret names appear (5 if you skipped `SENTRY_DSN`).

---

## 8. First deploy

```bash
flyctl deploy --strategy immediate
```

`--strategy immediate` is required: as of flyctl 0.4.41, the default
`rolling` strategy hits a launch-group lookup bug on this app and creates
a sibling orphan machine + volume on every run instead of updating the
existing machine in place (deploy log says *"Your app doesn't have any
Fly Launch machines, so we'll create one now"* even when the machine
exists with correct metadata). `immediate` uses a different code path
inside flyctl that finds the existing machine. Tradeoff: it skips per-
instance health-check waits, so a bad image ships as "deploy succeeded"
even when the new machine fails `/health` — there is no automatic
rollback. See `docs/plans/2026-04-29-fix-fly-deploy-launch-group.md` for
the full diagnostic. If a future flyctl release fixes the underlying
bug, revert to `--strategy rolling` to recover automatic stop-on-
unhealthy semantics.

This builds the Dockerfile remotely, pushes the image, and boots one
machine. Watch the build and boot logs:

```bash
flyctl logs
```

Look for:
- `[start] No local DB at /data/markland.db; attempting litestream restore...`
  followed by `Restore failed or no replica exists; continuing with fresh DB`
  (expected on first deploy - replica doesn't exist yet).
- `[start] Starting litestream replicate + uvicorn...`
- A uvicorn line: `Uvicorn running on http://0.0.0.0:8080`
- The health check passing every 30s: `200 OK /health`.

---

## 9. Allocate IPs and configure DNS

Fly assigns a shared IPv4 by default, but `markland.dev` apex needs a
dedicated address (and a v6 for good measure):

```bash
flyctl ips allocate-v4
flyctl ips allocate-v6
flyctl ips list
```

Copy the IPv4 (`v4` row) and IPv6 (`v6` row).

In Cloudflare DNS for `markland.dev`:

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| A | `@` | `<IPv4 from flyctl>` | **DNS only** (grey cloud) |
| AAAA | `@` | `<IPv6 from flyctl>` | **DNS only** (grey cloud) |

Proxy must be grey-cloud - Fly manages TLS at the edge; proxying through
Cloudflare would double-terminate TLS and break MCP streamable-http.

Wait ~60s for Cloudflare to pick up the records (`dig markland.dev` to
confirm).

---

## 10. Add the TLS certificate

```bash
flyctl certs add markland.dev
flyctl certs show markland.dev
```

First call may show `awaiting_configuration` or `awaiting_certificate`.
It progresses to `Issued` once Fly verifies the DNS A/AAAA records
above (usually 1-3 min, sometimes up to 15).

Re-run `flyctl certs show markland.dev` until you see `Issued`.

---

## 11. Sign in, promote the first admin, mint a smoke token

Required. The smoke test in the verification checklist needs a real user
API token.

1. Visit `https://markland.dev/` and follow the sign-in link, or go
   directly to `https://markland.dev/auth/magic-link`.
2. Enter your operator email; receive the magic-link email (check
   Resend dashboard if it doesn't arrive — DNS/SPF/DKIM is the usual
   culprit).
3. Click through to sign in; you'll land on the dashboard.
4. Mint a token at `/settings/tokens` labelled `hosted-smoke`. Copy the
   plaintext value — it's shown once. Export it locally:

   ```bash
   export MARKLAND_SMOKE_TOKEN="mk_usr_..."
   ```

5. SSH into the machine and flip the admin flag in SQLite (only needed
   if you plan to use `/admin/audit` or the `markland_audit` MCP tool):

   ```bash
   flyctl ssh console
   # inside the machine:
   apt-get update && apt-get install -y sqlite3   # one-off, if missing
   sqlite3 /data/markland.db \
     "UPDATE users SET is_admin=1 WHERE email='you@example.com';"
   sqlite3 /data/markland.db \
     "SELECT id, email, is_admin FROM users WHERE email='you@example.com';"
   exit
   ```

   Expected final row: `is_admin = 1`.

---

## 12. Wire CI deploy

1. Generate a Fly deploy token:

   ```bash
   flyctl auth token
   ```

2. GitHub repo -> Settings -> Secrets and variables -> Actions -> New
   repository secret:
   - Name: `FLY_API_TOKEN`
   - Value: paste the token from step 1.

3. Push to `main`:

   ```bash
   git push origin main
   ```

4. Watch the Actions tab - `.github/workflows/deploy.yml` runs
   `flyctl deploy --remote-only --strategy immediate` (see section 8 for
   why `--strategy immediate`). From now on every push to `main`
   auto-deploys. If a CI run produces a sibling orphan machine (visible
   in `flyctl machine list -a markland`), disable the workflow's `push:`
   trigger and reopen `docs/plans/2026-04-29-fix-fly-deploy-launch-
   group.md`.

---

## Required env / secrets reference

| Variable | Source | Set as | Notes |
|----------|--------|--------|-------|
| `MARKLAND_BASE_URL` | `fly.toml [env]` | already set | `https://markland.dev` |
| `MARKLAND_DATA_DIR` | `fly.toml [env]` | already set | `/data` (matches `[[mounts]]`) |
| `MARKLAND_WEB_PORT` | `fly.toml [env]` | already set | `8080` (matches `internal_port`) |
| `RESEND_FROM_EMAIL` | `fly.toml [env]` | already set | `notifications@markland.dev` |
| `MARKLAND_SESSION_SECRET` | runbook section 4 | `flyctl secrets set` | `openssl rand -hex 32`; signs cookies + magic-link tokens |
| `SENTRY_DSN` | Sentry project | `flyctl secrets set` | optional - leave unset to disable |
| `RESEND_API_KEY` | Resend dashboard | `flyctl secrets set` | `re_...` |
| `LITESTREAM_REPLICA_URL` | R2 bucket coords | `flyctl secrets set` | `s3://markland-db.<accountid>.r2.cloudflarestorage.com/markland` |
| `LITESTREAM_ACCESS_KEY_ID` | R2 API token | `flyctl secrets set` | |
| `LITESTREAM_SECRET_ACCESS_KEY` | R2 API token | `flyctl secrets set` | |

Names verified against `src/markland/config.py`, `fly.toml`, and
`litestream.yml`. All of the above are documented in `.env.example`.

---

## Verification checklist

Run after step 10 (cert issued):

```bash
# 1. Public health check - expect {"status":"ok"}
curl -s https://markland.dev/health
```

```bash
# 2. MCP endpoint without auth - expect HTTP 401
curl -sSo /dev/null -w "%{http_code}\n" https://markland.dev/mcp/
```

```bash
# 3. MCP endpoint with auth - expect 200, 405, or a streaming-SSE open.
#    Must NOT be 401. Use a user API token you minted from /settings/tokens
#    (sign in first via magic link, see section 11).
curl -sSo /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer $MARKLAND_SMOKE_TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  https://markland.dev/mcp/
```

```bash
# 4. Landing page - expect HTTP 200 and HTML body.
curl -sSo /dev/null -w "%{http_code}\n" https://markland.dev/
```

```bash
# 5. Litestream is replicating to R2 (run after a few writes).
flyctl ssh console -C "litestream snapshots /data/markland.db"
```

Expected: at least one snapshot row. In the Cloudflare R2 console you
should see objects appearing under the `markland/` prefix of the
`markland-db` bucket.

```bash
# 6. Full end-to-end smoke (exercises initialize + markland_whoami):
MARKLAND_URL=https://markland.dev \
MARKLAND_SMOKE_TOKEN="$MARKLAND_SMOKE_TOKEN" \
./scripts/hosted_smoke.sh
```

Expected: `All hosted smoke checks passed.`

---

## Rollback

### Roll back to a previous release

```bash
# List recent releases with image digests
flyctl releases --image

# Redeploy a specific prior image
flyctl deploy --strategy immediate \
  --image registry.fly.io/markland:deployment-<timestamp>
```

`flyctl releases --image` prints each release's image tag. Grab the one
from the last-known-good deploy. `--strategy immediate` is required for
the same reason as section 8.

Alternative: bypass the deploy command entirely and roll the existing
machine in place via `flyctl machine update`:

```bash
flyctl machine update 185191df264378 \
  --image registry.fly.io/markland:deployment-<timestamp> \
  -a markland --yes
```

This is what the workaround used before `--strategy immediate` was
identified. Both paths produce the same end state; `flyctl deploy
--strategy immediate` is now preferred because it advances the release
counter cleanly and matches what CI does.

### Restore the database from Litestream

If the local volume is corrupted or the deploy wrote bad data:

```bash
# Option A - in-place restore on the running machine
flyctl ssh console
  # inside:
  mv /data/markland.db /data/markland.db.broken
  litestream restore -o /data/markland.db "$LITESTREAM_REPLICA_URL"
  exit

# Option B - restore to your laptop for inspection
export LITESTREAM_ACCESS_KEY_ID=...
export LITESTREAM_SECRET_ACCESS_KEY=...
litestream restore -o /tmp/markland-restored.db \
  "s3://markland-db.<accountid>.r2.cloudflarestorage.com/markland"
sqlite3 /tmp/markland-restored.db "SELECT count(*) FROM documents;"
```

After an in-place restore, `flyctl apps restart markland` to cycle the
process cleanly.

---

## Common issues

**Certificate stuck at `awaiting_configuration`** - DNS records haven't
propagated or the proxy is on. Verify:
`dig +short markland.dev` returns the IPv4 from `flyctl ips list`; if
it returns a Cloudflare IP (`104.*.*.*`), the proxy is still enabled -
switch it to grey cloud.

**Cold-start latency on first request after deploy** - the entrypoint
runs `litestream restore` if `/data/markland.db` is missing. On a
freshly-volume-wiped machine this can take 10-60s for a 100-MB DB.
Mitigate by keeping `min_machines_running = 1` in `fly.toml` (already
set) so the volume stays attached across deploys.

**502 Bad Gateway on `/health`** - the volume didn't mount, so the app
crashed trying to open `/data/markland.db`. Check:
`flyctl volumes list` (volume exists in the same region as the machine?)
and `flyctl logs` for `sqlite3.OperationalError: unable to open database`.
Fix by recreating the volume in the correct region.

**`/mcp/` returns 401 even with the right token** - `/mcp` is gated by
`PrincipalMiddleware`, which requires a valid per-user or per-agent API
token (`mk_usr_*` / `mk_agt_*`). Confirm the token hasn't been revoked in
`/settings/tokens`, check for trailing newlines (use `printf` not `echo`
when pasting), and verify `MARKLAND_SESSION_SECRET` is set on the machine
(`flyctl secrets list`).

**Litestream `SignatureDoesNotMatch` errors in logs** - the R2 access
key / secret pair is wrong, or `LITESTREAM_REPLICA_URL` points at the
wrong bucket. `flyctl secrets set` them again and `flyctl apps restart markland`.

**Resend emails not arriving** - Resend dashboard -> Logs shows whether
the send was accepted. If accepted but undelivered, it's a DNS/SPF/DKIM
problem at Cloudflare, not Markland.

---

## After this runbook

- Subsequent deploys: `git push origin main`.
- Sentry alerting: follow `docs/runbooks/sentry-setup.md`.
- Scale-out considerations: deferred until there's a reason. See
  `docs/specs/2026-04-19-multi-agent-auth-design.md` for the operational
  signals to watch.
