# Cutover to markland.dev Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Many steps require **OPERATOR ACTION** in external dashboards (Porkbun, Fly, Cloudflare, Google Search Console, Resend) — those are marked explicitly.

**Goal:** Cut the live deploy over from `markland.fly.dev` to `markland.dev`, with magic-link email working, hosted_smoke green at the new origin, a 301 redirect from the old host, and the sitemap submitted to Google Search Console.

**Architecture:** Sequential ops checklist. Most tasks are: run command → wait for external state → verify expected output → save evidence. The only code change is one line in `fly.toml` (`MARKLAND_BASE_URL`) plus an optional in-app 301 redirect (Task 10). Resend domain verify (Task 9) delegates to the already-landed plan at `docs/plans/2026-04-28-resend-domain-verify.md`.

**Tech Stack:** Porkbun (registrar + nameservers as-shipped), Fly.io (hosting + certs), optionally Cloudflare (proxy/CDN/WAF), Resend (email), Google Search Console.

**Decision encoded in Task 2:** Porkbun-direct DNS vs. switch nameservers to Cloudflare. Task 4 has two alternatives; only one runs.

**Pre-existing constraint:** `flyctl deploy` triggers the launch-group bug — it spawns a sibling machine instead of updating in place. Workaround documented in `docs/FOLLOW-UPS.md` Deploy/operations: use `flyctl deploy --build-only` then `flyctl machine update <id> --image <tag>`. CI auto-deploy is currently disabled (PR #26). Tasks 7 and 12 use the workaround, not raw `flyctl deploy`.

---

## File Structure

Code touched (small surface):
- `fly.toml` — flip `MARKLAND_BASE_URL` (Task 6)
- `src/markland/web/app.py` — optional `FlyDevRedirectMiddleware` for 301 (Task 10)
- `tests/test_fly_dev_redirect.py` — new test file for Task 10 (only if 10 is executed in-app)
- `docs/ROADMAP.md`, `docs/FOLLOW-UPS.md` — final reconciliation in Task 12

Evidence capture:
- All commands `tee` to `cutover-evidence/<step>.log` (gitignored — operator artifact, not committed). Task 1 creates the directory and adds it to `.gitignore`.

---

## Task 1: Pre-flight inventory and evidence directory

**Files:**
- Modify: `.gitignore`
- Create: `cutover-evidence/` (gitignored)

- [ ] **Step 1.1: Verify operator access (OPERATOR ACTION)**

  Confirm you can sign in to:
  - Porkbun: https://porkbun.com/account/domainsSpeedy → `markland.dev` row visible
  - Fly: `flyctl auth whoami` → returns `daveyhiles@gmail.com` (or the account that owns the `markland` app)
  - GitHub: `gh auth status` → returns logged in to `dghiles`
  - Resend: https://resend.com/domains (you'll add `markland.dev` in Task 9)
  - Google Search Console: https://search.google.com/search-console (you'll add the property in Task 11)

  If any of these fails, stop and resolve access before continuing.

- [ ] **Step 1.2: Capture baseline state**

  Run from the repo root:

  ```bash
  mkdir -p cutover-evidence
  flyctl ips list -a markland | tee cutover-evidence/01-ips-before.log
  flyctl certs list -a markland | tee cutover-evidence/01-certs-before.log
  flyctl status -a markland | tee cutover-evidence/01-status-before.log
  flyctl secrets list -a markland | tee cutover-evidence/01-secrets-before.log
  grep -n MARKLAND_BASE_URL fly.toml | tee cutover-evidence/01-base-url-before.log
  curl -s -o /dev/null -w "fly.dev landing: %{http_code} %{time_total}s\n" https://markland.fly.dev/ | tee cutover-evidence/01-fly-dev-baseline.log
  curl -s -o /dev/null -w "fly.dev /health: %{http_code}\n" https://markland.fly.dev/health | tee -a cutover-evidence/01-fly-dev-baseline.log
  ```

  Expected:
  - `01-ips-before.log` shows the shared anycast v4 (`66.241.124.x`) and v6 currently in use, no dedicated v4
  - `01-certs-before.log` shows `markland.fly.dev` with `Issued`, no entry for `markland.dev`
  - `01-base-url-before.log` shows `MARKLAND_BASE_URL = 'https://markland.fly.dev'`
  - `01-fly-dev-baseline.log` shows `200` for both endpoints

  Pass criteria: all four files non-empty, baseline `200`s recorded.

- [ ] **Step 1.3: Add evidence directory to .gitignore**

  Edit `.gitignore`. After the existing entries, append:

  ```
  # Cutover evidence (operator artifact, not committed)
  cutover-evidence/
  ```

- [ ] **Step 1.4: Commit the .gitignore change**

  ```bash
  git add .gitignore
  git commit -m "chore: ignore cutover-evidence directory"
  git push origin main
  ```

  Expected: push succeeds (docs-only / gitignore — direct-to-main is allowed by the existing settings rule).

---

## Task 2: DNS strategy decision

This is a decision task, not an executable one. Pick ONE option and record it. Task 4 will branch on the choice.

**Option A — Porkbun-direct DNS (RECOMMENDED for shipping fast)**

- Pros: zero new accounts, fewer moving parts, Porkbun nameservers are already authoritative (`curitiba|fortaleza|maceio|salvador.ns.porkbun.com`), DNSSEC is one click.
- Cons: no proxy/CDN/WAF; if you later want Cloudflare features you migrate then.
- Time-to-cut: ~1h end-to-end.

**Option B — Switch nameservers to Cloudflare**

- Pros: free Cloudflare proxy/CDN, optional WAF, page rules, analytics, and Workers later.
- Cons: extra account + zone setup, NS-change propagation delay (often <1h, occasionally up to 24h), one more dashboard.
- Time-to-cut: 1.5–24h depending on NS propagation.

- [ ] **Step 2.1: Pick the option (OPERATOR DECISION)**

  Decide: `A` (Porkbun-direct) or `B` (Cloudflare).

- [ ] **Step 2.2: Record the decision**

  ```bash
  echo "DNS strategy: Option A (Porkbun-direct)" > cutover-evidence/02-dns-strategy.log
  # or:
  echo "DNS strategy: Option B (Cloudflare)" > cutover-evidence/02-dns-strategy.log
  cat cutover-evidence/02-dns-strategy.log
  ```

  Expected: file contents echo the chosen option.

---

## Task 3: Allocate dedicated Fly IPs

Required regardless of DNS strategy. Fly's shared anycast IPs cannot serve a custom domain — they only resolve `*.fly.dev`. You need a dedicated v4 (~$2/mo) and a free v6.

**Files:** none (all `flyctl` commands).

- [ ] **Step 3.1: Allocate dedicated IPv4**

  ```bash
  flyctl ips allocate-v4 --yes -a markland | tee cutover-evidence/03-ipv4.log
  ```

  Expected output line: `<a.b.c.d>      v4    public    dedicated`. Capture the IP.

- [ ] **Step 3.2: Allocate IPv6**

  ```bash
  flyctl ips allocate-v6 -a markland | tee cutover-evidence/03-ipv6.log
  ```

  Expected output: a `2a09:8280:1::...` style IPv6 address. Capture it.

- [ ] **Step 3.3: Confirm both IPs are assigned**

  ```bash
  flyctl ips list -a markland | tee cutover-evidence/03-ips-after.log
  ```

  Expected: both new IPs listed alongside the existing shared anycast. Compare against `01-ips-before.log` to verify they're new entries.

  Pass criteria: `03-ipv4.log` contains a public IPv4 in 137.66.x.x or similar Fly Anycast block, `03-ipv6.log` contains a `2a09:` IPv6.

---

## Task 4a: Configure DNS via Porkbun-direct (run ONLY if Task 2 chose Option A)

Skip this task if Task 2 chose Option B; jump to Task 4b.

**Files:** none — work happens in Porkbun's panel.

- [ ] **Step 4a.1: Open Porkbun DNS records (OPERATOR ACTION)**

  Navigate: https://porkbun.com/account/domainsSpeedy → `markland.dev` → DNS Records (the pencil icon next to "DNS RECORDS").

- [ ] **Step 4a.2: Delete the default 2 records (OPERATOR ACTION)**

  Porkbun ships every domain with a parked-page `ALIAS` and `CNAME`. Delete both.

- [ ] **Step 4a.3: Add A record at apex pointing to dedicated v4 (OPERATOR ACTION)**

  Click "Add Record":
  - Type: `A`
  - Host: (leave blank, this is the apex)
  - Answer: paste the IPv4 from `cutover-evidence/03-ipv4.log`
  - TTL: `600`

- [ ] **Step 4a.4: Add AAAA record at apex (OPERATOR ACTION)**

  Click "Add Record":
  - Type: `AAAA`
  - Host: (blank)
  - Answer: paste the IPv6 from `cutover-evidence/03-ipv6.log`
  - TTL: `600`

- [ ] **Step 4a.5: (Optional) Add www CNAME (OPERATOR ACTION)**

  If you want `www.markland.dev` to resolve too:
  - Type: `CNAME`
  - Host: `www`
  - Answer: `markland.dev`
  - TTL: `600`

- [ ] **Step 4a.6: Verify DNS resolution**

  Wait 60 seconds for Porkbun to publish, then:

  ```bash
  dig +short A markland.dev | tee cutover-evidence/04a-dig-a.log
  dig +short AAAA markland.dev | tee cutover-evidence/04a-dig-aaaa.log
  ```

  Expected: `04a-dig-a.log` matches the IPv4 from `03-ipv4.log`, `04a-dig-aaaa.log` matches the IPv6 from `03-ipv6.log`.

  If either is empty, wait another 60s and retry. Porkbun publishes within ~1m typically.

  Pass criteria: both `dig` commands return the exact IPs allocated in Task 3.

---

## Task 4b: Configure DNS via Cloudflare (run ONLY if Task 2 chose Option B)

Skip this task if Task 2 chose Option A.

**Files:** none — work happens in Cloudflare and Porkbun panels.

- [ ] **Step 4b.1: Create Cloudflare account and add the zone (OPERATOR ACTION)**

  - Sign up / log in at https://dash.cloudflare.com (free plan is fine).
  - Click "Add a Site" → enter `markland.dev` → choose Free plan.
  - Cloudflare scans for existing records — there should be none meaningful (Porkbun parking only). Delete any auto-imported records you don't want.

- [ ] **Step 4b.2: Capture Cloudflare-assigned nameservers (OPERATOR ACTION)**

  Cloudflare displays two NS hostnames (e.g. `julia.ns.cloudflare.com` + `kahn.ns.cloudflare.com` — the names are randomly assigned per zone). Copy both.

- [ ] **Step 4b.3: Update nameservers at Porkbun (OPERATOR ACTION)**

  - https://porkbun.com/account/domainsSpeedy → `markland.dev` → "NAMESERVERS" pencil icon.
  - Replace the four `*.ns.porkbun.com` entries with the two Cloudflare nameservers.
  - Save.

- [ ] **Step 4b.4: Wait for NS propagation**

  ```bash
  until [ "$(dig +short NS markland.dev | grep -c cloudflare)" -ge 1 ]; do
    echo "$(date): waiting for Cloudflare NS to propagate..."; sleep 60
  done
  dig +short NS markland.dev | tee cutover-evidence/04b-ns.log
  ```

  Expected: `04b-ns.log` shows the two Cloudflare NS hostnames. Typically <1h, can be up to 24h.

  Cloudflare also shows "Pending Nameserver Update" → "Active" in its dashboard once it sees the change. Wait for that too.

- [ ] **Step 4b.5: Add A and AAAA records DNS-only (OPERATOR ACTION)**

  In Cloudflare dashboard → `markland.dev` → DNS → Records → Add record:

  - Type `A`, Name `@`, IPv4 from `03-ipv4.log`, **Proxy status: DNS only (grey cloud)**, TTL Auto.
  - Type `AAAA`, Name `@`, IPv6 from `03-ipv6.log`, **Proxy status: DNS only**, TTL Auto.
  - (Optional) Type `CNAME`, Name `www`, Target `markland.dev`, DNS only.

  **Why DNS-only:** Fly serves TLS itself and won't issue a Let's Encrypt cert if Cloudflare is proxying (the request never reaches Fly). You can flip to proxied (orange cloud) AFTER the Fly cert is Issued in Task 5, but defer that decision — it's a separate change.

- [ ] **Step 4b.6: Verify DNS resolution**

  ```bash
  dig +short A markland.dev | tee cutover-evidence/04b-dig-a.log
  dig +short AAAA markland.dev | tee cutover-evidence/04b-dig-aaaa.log
  ```

  Expected: matches `03-ipv4.log` and `03-ipv6.log` exactly. Proxied records would resolve to `104.x.x.x` Cloudflare IPs instead — if you see those, Step 4b.5 was misconfigured (proxy is on); fix to grey-cloud and re-verify.

  Pass criteria: both `dig` commands return the exact Fly-allocated IPs from Task 3.

---

## Task 5: Add Fly TLS certificate

Fly issues a free Let's Encrypt cert via HTTP-01 challenge once DNS resolves to its IPs.

**Files:** none.

- [ ] **Step 5.1: Add the cert**

  ```bash
  flyctl certs add markland.dev -a markland | tee cutover-evidence/05-cert-add.log
  ```

  Expected: output shows the cert is being provisioned. If output says `DNS Configured: false`, recheck Task 4 — the apex must already resolve to the Fly IPs.

- [ ] **Step 5.2: Poll until Issued**

  ```bash
  until flyctl certs show markland.dev -a markland 2>&1 | grep -q "Status.*Issued\|Issued =.*true"; do
    echo "$(date): cert pending..."; flyctl certs show markland.dev -a markland | grep -E "Status|Type|Hostname" | head -5; sleep 30
  done
  flyctl certs show markland.dev -a markland | tee cutover-evidence/05-cert-show.log
  ```

  Expected: status flips to `Issued` within 1–5 minutes when DNS is correct. If it stays `Awaiting configuration` for >10 minutes, run `flyctl certs check markland.dev -a markland` and follow its diagnostic.

  Pass criteria: `05-cert-show.log` contains `Issued`.

- [ ] **Step 5.3: Verify HTTPS handshake**

  ```bash
  curl -sI https://markland.dev/ | tee cutover-evidence/05-https-head.log
  ```

  Expected: HTTP status line. May be `404 Not Found` because the app still self-redirects on `markland.fly.dev` host (we haven't updated `MARKLAND_BASE_URL` yet) — that's fine. The point is the **TLS handshake succeeds with no cert error**. If `curl` complains about the cert (`SSL certificate problem`), Task 5.2 isn't actually done.

  Pass criteria: `05-https-head.log` contains an `HTTP/` status line, no SSL error.

---

## Task 6: Update fly.toml MARKLAND_BASE_URL

The app reads `MARKLAND_BASE_URL` from `fly.toml` `[env]` to construct magic-link URLs, share-token URLs, and OG/canonical tags.

**Files:**
- Modify: `fly.toml:12`

- [ ] **Step 6.1: Edit fly.toml**

  Open `fly.toml`. Find:

  ```toml
  MARKLAND_BASE_URL = 'https://markland.fly.dev'
  ```

  Change to:

  ```toml
  MARKLAND_BASE_URL = 'https://markland.dev'
  ```

  Save. Verify the diff:

  ```bash
  git diff fly.toml | tee cutover-evidence/06-fly-toml-diff.log
  ```

  Expected: one line removed, one line added, no other changes. If the diff is larger, revert and redo.

- [ ] **Step 6.2: Commit and push**

  ```bash
  git add fly.toml
  git commit -m "config(fly): point MARKLAND_BASE_URL at markland.dev"
  git push origin main
  ```

  Expected: push succeeds. Note that CI auto-deploy is currently disabled (PR #26), so this commit does NOT trigger a deploy. Task 7 deploys manually.

---

## Task 7: Deploy and verify

Use the launch-group-bug workaround (build-only + machine update), per `docs/FOLLOW-UPS.md`.

**Files:** none (deploy is operator-driven).

- [ ] **Step 7.1: Capture current machine ID**

  ```bash
  flyctl machine list -a markland --json | jq -r '.[] | select(.config.metadata.fly_process_group == "app") | .id' | head -1 | tee cutover-evidence/07-machine-id.log
  ```

  Expected: a 14-character hex string (e.g. `185191df264378`). If empty, fall back to `flyctl machine list -a markland` and find the machine in the `app` process group.

- [ ] **Step 7.2: Build and push the image**

  ```bash
  flyctl deploy --build-only -a markland 2>&1 | tee cutover-evidence/07-build.log
  ```

  Expected: ends with `image: registry.fly.io/markland:deployment-<timestamp>`. Capture the full image tag — Step 7.3 needs it.

  ```bash
  IMAGE=$(grep -oE 'registry\.fly\.io/markland:deployment-[0-9A-Z]+' cutover-evidence/07-build.log | tail -1)
  echo "$IMAGE" | tee cutover-evidence/07-image.log
  ```

  Pass: `07-image.log` non-empty, looks like `registry.fly.io/markland:deployment-...`.

- [ ] **Step 7.3: Roll the existing machine to the new image**

  ```bash
  MID=$(cat cutover-evidence/07-machine-id.log)
  IMAGE=$(cat cutover-evidence/07-image.log)
  flyctl machine update "$MID" --image "$IMAGE" -a markland --yes 2>&1 | tee cutover-evidence/07-machine-update.log
  ```

  Expected: `Machine <mid> updated successfully!`. Health checks should pass within ~30s.

- [ ] **Step 7.4: Confirm app is up at new domain**

  ```bash
  curl -s -o /dev/null -w "markland.dev landing: %{http_code} %{time_total}s\n" https://markland.dev/ | tee cutover-evidence/07-new-domain-landing.log
  curl -s -o /dev/null -w "markland.dev /health: %{http_code}\n" https://markland.dev/health | tee -a cutover-evidence/07-new-domain-landing.log
  curl -s -o /dev/null -w "markland.dev /alternatives: %{http_code}\n" https://markland.dev/alternatives | tee -a cutover-evidence/07-new-domain-landing.log
  ```

  Expected: all three return `200`. Pass criteria: zero non-200s in `07-new-domain-landing.log`.

- [ ] **Step 7.5: Confirm canonical / OG URLs use new base**

  ```bash
  curl -s https://markland.dev/ | grep -E '<link rel="canonical"|<meta property="og:url"' | tee cutover-evidence/07-canonical.log
  ```

  Expected: both URLs are `https://markland.dev/` (no `fly.dev`). If they still say `fly.dev`, Step 7.3's deploy didn't actually pick up the new `fly.toml` env — verify by `flyctl config env -a markland | grep MARKLAND_BASE_URL`.

  Pass criteria: `07-canonical.log` shows both `markland.dev` URLs, no `fly.dev` strings.

---

## Task 8: Run hosted_smoke

`scripts/hosted_smoke.sh` exercises the public surface end-to-end: landing, /alternatives, /quickstart, robots.txt, sitemap.xml, security headers, /health.

**Files:** none.

- [ ] **Step 8.1: Run smoke against new domain**

  ```bash
  MARKLAND_URL=https://markland.dev bash scripts/hosted_smoke.sh 2>&1 | tee cutover-evidence/08-smoke.log
  ```

  Expected: script exits 0. Final line should be `OK` or equivalent. If it fails, read the log — most likely cause is a hardcoded `fly.dev` URL in a template (search with `grep -rn 'fly.dev' src/markland/web/templates/`).

- [ ] **Step 8.2: Run smoke against old domain (regression check)**

  ```bash
  MARKLAND_URL=https://markland.fly.dev bash scripts/hosted_smoke.sh 2>&1 | tee cutover-evidence/08-smoke-old.log
  ```

  Expected: PASSES today (the app is still served at fly.dev). After Task 10's 301 lands, this check will start returning redirects; that's expected and Task 10 will document the new expected output.

  Pass criteria: `08-smoke.log` exits 0; `08-smoke-old.log` exits 0 (or, after Task 10, redirects to `markland.dev`).

---

## Task 9: Resend domain verify

This delegates to the already-landed plan at `docs/plans/2026-04-28-resend-domain-verify.md`. That plan was authored before the domain existed; with the zone now live, every step is executable.

**Files:** none (DNS in Porkbun or Cloudflare per Task 2; secret in Fly).

- [ ] **Step 9.1: Open the Resend plan**

  ```bash
  cat docs/plans/2026-04-28-resend-domain-verify.md
  ```

  Read the entire plan before executing. Note: that plan's "DNS records" task assumes a particular DNS host. If Task 2 chose Option B (Cloudflare), substitute Cloudflare's DNS UI for Porkbun's wherever it appears.

- [ ] **Step 9.2: Execute the Resend plan tasks**

  Work through every checkbox in `docs/plans/2026-04-28-resend-domain-verify.md`. Capture its evidence under `cutover-evidence/09-resend/` so it lives alongside the cutover evidence.

  Expected end state:
  - Resend dashboard shows `markland.dev` Verified.
  - `flyctl secrets list -a markland` includes `RESEND_API_KEY` (already set per `01-secrets-before.log`? if so this step is a no-op for the secret itself; the verify portion is what matters).
  - A test magic-link send to a real inbox arrives in <30s.

- [ ] **Step 9.3: Mark the Resend plan complete**

  Once every checkbox in the Resend plan is ticked, return here. `docs/plans/2026-04-28-resend-domain-verify.md` itself does not need to be edited (the plan is the spec; checkboxes are the work artifact). Note completion in `cutover-evidence/09-resend/done.log`:

  ```bash
  echo "Resend plan completed at $(date -u +%Y-%m-%dT%H:%M:%SZ)" > cutover-evidence/09-resend/done.log
  ```

  Pass criteria: `cutover-evidence/09-resend/done.log` exists.

---

## Task 10: Add 301 redirect from markland.fly.dev to markland.dev

Two paths. Pick one based on whether you want a server-side redirect (preserves path, simple) or a Fly-edge / Cloudflare redirect (zero app changes).

**Recommended:** Server-side middleware (10a). Cheap, in-version-control, testable.

**Alternative:** Cloudflare redirect rule (10b) — only viable if Task 2 chose Option B. Skip this option if you went Porkbun-direct.

### Option 10a: Server-side `FlyDevRedirectMiddleware` (RECOMMENDED)

**Files:**
- Modify: `src/markland/web/app.py`
- Create: `tests/test_fly_dev_redirect.py`

- [ ] **Step 10a.1: Write the failing test**

  Create `tests/test_fly_dev_redirect.py`:

  ```python
  from fastapi.testclient import TestClient

  from markland.web.app import create_app


  def _client():
      app = create_app()
      return TestClient(app, base_url="http://markland.fly.dev")


  def test_fly_dev_apex_redirects_to_markland_dev():
      client = _client()
      r = client.get("/", follow_redirects=False, headers={"host": "markland.fly.dev"})
      assert r.status_code == 301
      assert r.headers["location"] == "https://markland.dev/"


  def test_fly_dev_path_preserved():
      client = _client()
      r = client.get(
          "/alternatives/markshare?utm=test",
          follow_redirects=False,
          headers={"host": "markland.fly.dev"},
      )
      assert r.status_code == 301
      assert r.headers["location"] == "https://markland.dev/alternatives/markshare?utm=test"


  def test_markland_dev_host_does_not_redirect():
      client = TestClient(create_app(), base_url="http://markland.dev")
      r = client.get("/", follow_redirects=False, headers={"host": "markland.dev"})
      assert r.status_code != 301
  ```

- [ ] **Step 10a.2: Run the test to verify it fails**

  ```bash
  uv run pytest tests/test_fly_dev_redirect.py -v
  ```

  Expected: 3 failures. Each `assert r.status_code == 301` fails because no redirect middleware exists yet.

- [ ] **Step 10a.3: Add the middleware to app.py**

  In `src/markland/web/app.py`, find the section that adds middleware (search for `app.add_middleware(SecurityHeadersMiddleware`). Add a new middleware class above it and register it last (so it runs first per Starlette's reverse add-order):

  ```python
  from starlette.middleware.base import BaseHTTPMiddleware
  from starlette.responses import RedirectResponse


  class FlyDevRedirectMiddleware(BaseHTTPMiddleware):
      """301-redirect any request whose Host is markland.fly.dev to markland.dev.

      The redirect is unconditional on host match, so it covers both proxied
      Fly traffic (X-Forwarded-Host honored upstream) and direct hits.
      """

      async def dispatch(self, request, call_next):
          host = request.headers.get("host", "").lower()
          if host == "markland.fly.dev":
              target = f"https://markland.dev{request.url.path}"
              if request.url.query:
                  target = f"{target}?{request.url.query}"
              return RedirectResponse(target, status_code=301)
          return await call_next(request)
  ```

  Then in `create_app()` after the existing `app.add_middleware` calls, add:

  ```python
  app.add_middleware(FlyDevRedirectMiddleware)
  ```

  (Add it last in the add-order so it runs first in the request path — Starlette reverses add-order at runtime.)

- [ ] **Step 10a.4: Run the test to verify it passes**

  ```bash
  uv run pytest tests/test_fly_dev_redirect.py -v
  ```

  Expected: 3 passed.

- [ ] **Step 10a.5: Run the full test suite (regression check)**

  ```bash
  uv run pytest tests/ -q 2>&1 | tee cutover-evidence/10a-full-suite.log
  ```

  Expected: 689 passed (686 baseline + 3 new). Zero failures. Capture the count.

- [ ] **Step 10a.6: Commit**

  ```bash
  git add src/markland/web/app.py tests/test_fly_dev_redirect.py
  git commit -m "feat(web): 301 redirect markland.fly.dev → markland.dev"
  git push origin main
  ```

- [ ] **Step 10a.7: Re-deploy with the workaround**

  Repeat Steps 7.2 and 7.3 (build-only + machine update) so the redirect lands in production.

  Capture: `cutover-evidence/10a-redeploy-build.log` and `cutover-evidence/10a-redeploy-update.log`.

- [ ] **Step 10a.8: Verify redirect in production**

  ```bash
  curl -sI https://markland.fly.dev/ | tee cutover-evidence/10a-redirect-curl.log
  curl -sI https://markland.fly.dev/alternatives/markshare | tee -a cutover-evidence/10a-redirect-curl.log
  ```

  Expected: `HTTP/2 301` followed by `location: https://markland.dev/` (and `/alternatives/markshare` for the second). If you see `200 OK` instead of `301`, the deploy didn't take — re-check Step 10a.7.

  Pass criteria: both `curl` calls show `301` and the correct `location` header.

### Option 10b: Cloudflare bulk redirect (Cloudflare zone only)

Run only if Task 2 chose Option B AND you'd rather handle this at the edge. Otherwise skip 10b entirely.

- [ ] **Step 10b.1: Add a redirect rule (OPERATOR ACTION)**

  In Cloudflare dashboard for a Cloudflare-managed zone (this requires `markland.fly.dev` to be a Cloudflare zone too — which it isn't, since Fly owns `*.fly.dev`). **Conclusion: Option 10b is not viable** because you don't control `fly.dev` DNS. Use Option 10a.

  Mark this option N/A:

  ```bash
  echo "Option 10b N/A — fly.dev is owned by Fly, not us. Used 10a instead." > cutover-evidence/10b-na.log
  ```

---

## Task 11: Submit sitemap to Google Search Console

**Files:** none — work happens in GSC.

- [ ] **Step 11.1: Verify the sitemap is reachable at the new origin**

  ```bash
  curl -sI https://markland.dev/sitemap.xml | head -1 | tee cutover-evidence/11-sitemap-head.log
  curl -s https://markland.dev/sitemap.xml | head -20 | tee cutover-evidence/11-sitemap-body.log
  ```

  Expected: status `200`; body starts with `<?xml version="1.0" encoding="UTF-8"?>` and `<urlset ...>`. URLs inside should all be `https://markland.dev/...` (not `fly.dev`).

  If sitemap entries still say `fly.dev`, Task 7 did not flip the env correctly — back to 7.5 to debug.

- [ ] **Step 11.2: Add domain property in GSC (OPERATOR ACTION)**

  - Go to https://search.google.com/search-console
  - "Add property" → "Domain" (not URL prefix) → enter `markland.dev` → Continue.
  - GSC shows a TXT record to add for verification (looks like `google-site-verification=...`).

- [ ] **Step 11.3: Add the TXT record (OPERATOR ACTION)**

  - **If Task 2 = Option A (Porkbun):** Porkbun panel → DNS records → Add Record → Type `TXT`, Host blank, Answer `google-site-verification=<value>`, TTL 600.
  - **If Task 2 = Option B (Cloudflare):** Cloudflare panel → DNS → Add record → Type `TXT`, Name `@`, Content `google-site-verification=<value>`.

  Wait 60s for propagation:

  ```bash
  dig +short TXT markland.dev | tee cutover-evidence/11-txt.log
  ```

  Expected: at least one line containing `google-site-verification=...`.

- [ ] **Step 11.4: Click "Verify" in GSC (OPERATOR ACTION)**

  Back in GSC, click Verify. Expected: green checkmark, "Ownership verified."

- [ ] **Step 11.5: Submit sitemap (OPERATOR ACTION)**

  GSC → Sitemaps (left sidebar) → "Add a new sitemap" → enter `sitemap.xml` (path only, GSC prepends the domain) → Submit.

  Expected: status flips to "Success" within minutes.

- [ ] **Step 11.6: Capture submission confirmation**

  Screenshot or copy the GSC sitemap row showing "Success" and save to `cutover-evidence/11-gsc-sitemap.png` (or `.txt` with the row text).

  Pass criteria: GSC shows the sitemap as Success with a recent "Last read" timestamp.

---

## Task 12: Final verification, ROADMAP/FOLLOW-UPS reconciliation

**Files:**
- Modify: `docs/ROADMAP.md`
- Modify: `docs/FOLLOW-UPS.md`

- [ ] **Step 12.1: Re-run hosted_smoke against the new origin**

  ```bash
  MARKLAND_URL=https://markland.dev bash scripts/hosted_smoke.sh 2>&1 | tee cutover-evidence/12-smoke-final.log
  ```

  Expected: exit 0, all checks pass.

- [ ] **Step 12.2: Spot-check magic-link end-to-end**

  Manually:
  1. Open `https://markland.dev/` in an incognito window.
  2. Sign up with a real inbox.
  3. Email arrives within 30s, From: `notifications@markland.dev`, link points to `https://markland.dev/auth/verify?...`.
  4. Click link → lands signed in on `https://markland.dev/`.

  Capture in `cutover-evidence/12-magic-link.log` with email arrival timestamp and a note "verified clicked-through OK."

  Pass criteria: end-to-end flow works without log diving.

- [ ] **Step 12.3: Update ROADMAP "Where we are"**

  Open `docs/ROADMAP.md`. Find the "Where we are" header and bump the date to today and replace the "Domain registered" stanza with cutover-complete language. Specifically, replace:

  ```markdown
  **Domain registered 2026-04-29:** `markland.dev` bought at Porkbun
  (daveyhiles@gmail.com, registry expires 2027-04-29, locked, contact privacy
  on, Porkbun nameservers active: `curitiba|fortaleza|maceio|salvador.ns.porkbun.com`).
  This unblocks the cutover work that the prior "blocked on user" line gated:
  Fly cert + dedicated IPv4/IPv6, DNS records, Resend domain verify (→ real
  magic-link sign-ins), GSC sitemap submission, 301 redirects from `fly.dev`.
  ```

  With:

  ```markdown
  **Cutover to `markland.dev` complete (<TODAY-YYYY-MM-DD>):** dedicated Fly
  IPv4/IPv6 allocated, DNS pointed via <Porkbun-direct | Cloudflare>, TLS cert
  Issued by Fly, `MARKLAND_BASE_URL` flipped, hosted_smoke green, 301 from
  `markland.fly.dev` live, Resend domain verified, GSC property added and
  sitemap submitted.
  ```

  (Substitute the date and the chosen DNS path. Replace the angle-bracket placeholders verbatim.)

- [ ] **Step 12.4: Move "Cut over" item from Now → Shipped in ROADMAP**

  In `docs/ROADMAP.md`:
  1. Delete the bullet beginning `- **Cut over to `markland.dev`** —` from the Now lane.
  2. Add a new line at the top of the "Hosted infrastructure + ops" Shipped subsection:

  ```markdown
  - **<TODAY-YYYY-MM-DD>** — Cutover to `markland.dev` complete. Dedicated Fly IPv4 + IPv6 allocated, DNS via <Porkbun-direct | Cloudflare>, Fly TLS cert Issued, `MARKLAND_BASE_URL` flipped to `https://markland.dev`, `FlyDevRedirectMiddleware` 301s `markland.fly.dev` → `markland.dev`, hosted_smoke green, Resend domain verified, GSC property added + sitemap submitted.
  ```

- [ ] **Step 12.5: Reconcile FOLLOW-UPS §1**

  In `docs/FOLLOW-UPS.md`, find the bullet starting `- **Cut over to \`markland.dev\`.**` (added 2026-04-29) and replace the entire bullet with:

  ```markdown
  - **~~Cut over to `markland.dev`.~~** Done <TODAY-YYYY-MM-DD>. See ROADMAP
    Shipped. Plan: `docs/plans/2026-04-29-cutover-to-markland-dev.md`.
  ```

  Also strike-through (`~~ ~~`) the GSC sitemap submission bullet later in the same section if it's still listed as pending — it was completed in Task 11.

- [ ] **Step 12.6: Commit and push docs reconciliation**

  ```bash
  git add docs/ROADMAP.md docs/FOLLOW-UPS.md
  git commit -m "docs: cutover to markland.dev complete"
  git push origin main
  ```

  Expected: push succeeds.

- [ ] **Step 12.7: Final summary**

  Capture a one-screen summary:

  ```bash
  {
    echo "=== Cutover summary ==="
    echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "DNS strategy: $(cat cutover-evidence/02-dns-strategy.log)"
    echo "IPv4: $(grep -oE '\b[0-9]{1,3}(\.[0-9]{1,3}){3}\b' cutover-evidence/03-ipv4.log | head -1)"
    echo "IPv6: $(grep -oE '2[a-f0-9:]+' cutover-evidence/03-ipv6.log | head -1)"
    echo "Cert: Issued"
    echo "MARKLAND_BASE_URL: https://markland.dev"
    echo "Redirect: markland.fly.dev → markland.dev (301)"
    echo "Resend: verified"
    echo "GSC: sitemap submitted"
    echo ""
    echo "=== Verification ==="
    curl -sI https://markland.dev/ | head -1
    curl -sI https://markland.fly.dev/ | head -1
    curl -sI https://markland.dev/sitemap.xml | head -1
  } | tee cutover-evidence/12-final.log
  cat cutover-evidence/12-final.log
  ```

  Expected: `markland.dev/` → 200, `markland.fly.dev/` → 301, `markland.dev/sitemap.xml` → 200.

  **CUTOVER COMPLETE.**

---

## Verification matrix

A summary checklist the operator can scan post-cutover to confirm nothing was missed:

| Check | Command | Expected |
|---|---|---|
| Apex DNS | `dig +short A markland.dev` | dedicated Fly IPv4 |
| TLS cert | `flyctl certs show markland.dev -a markland` | Status: Issued |
| App health | `curl -sI https://markland.dev/health` | 200 |
| Canonical URL | `curl -s https://markland.dev/ \| grep canonical` | `markland.dev` |
| Old host redirect | `curl -sI https://markland.fly.dev/` | 301 to `markland.dev/` |
| hosted_smoke | `MARKLAND_URL=https://markland.dev bash scripts/hosted_smoke.sh` | exit 0 |
| Magic-link email | manual signup with real inbox | arrives in <30s, From: `notifications@markland.dev` |
| Sitemap | `curl -s https://markland.dev/sitemap.xml \| head` | XML, all URLs use `markland.dev` |
| GSC | dashboard | sitemap status: Success |

If any row fails, do not mark the cutover complete. Diagnose and re-run the relevant task.

---

## Rollback

If something irrecoverable happens between Task 6 and Task 12 (the app stops serving correctly at either domain), roll back by reverting `fly.toml` and re-deploying:

```bash
git revert <task-6-commit-sha>
git push origin main
flyctl deploy --build-only -a markland
flyctl machine update <mid> --image <reverted-image-tag> -a markland --yes
```

The DNS records, IPs, and cert can stay — they're harmless without the env flip. Resend domain verify can also stay (the records are stable). GSC property can stay; you'll re-submit the sitemap on the next attempt.

The 301 middleware (Task 10) is the only piece that's awkward to roll back without an app code revert; if it's already deployed, an additional revert of that commit is needed.

---

## Self-review

**Spec coverage check:**
- Allocate dedicated Fly IPs → Task 3 ✓
- DNS records (apex A + AAAA) → Task 4a or 4b ✓
- TLS cert provisioning → Task 5 ✓
- `fly.toml` `MARKLAND_BASE_URL` flip → Task 6 ✓
- Deploy via launch-group workaround → Task 7 ✓
- hosted_smoke against new origin → Task 8 + 12.1 ✓
- Resend domain verify → Task 9 (delegates) ✓
- 301 from `fly.dev` → Task 10a ✓
- GSC sitemap submission → Task 11 ✓
- ROADMAP/FOLLOW-UPS reconciliation → Task 12.3–12.6 ✓
- Decision point on DNS strategy → Task 2 ✓
- Evidence capture per step → throughout (`cutover-evidence/`) ✓
- Rollback path → end-of-doc ✓

**Placeholder scan:** No `TBD`, `TODO`, or `fill in` strings. The two `<TODAY-YYYY-MM-DD>` and one `<Porkbun-direct | Cloudflare>` instances in Task 12 are explicit operator-substitution placeholders, not plan failures — they require the date and choice that only the operator knows at execution time.

**Type/name consistency:** Class name `FlyDevRedirectMiddleware` consistent across Task 10a.3 (definition), 10a.4 (test), and Task 12.4 (Shipped entry). Filename `tests/test_fly_dev_redirect.py` consistent across 10a.1 and 10a.6. Evidence-directory path `cutover-evidence/` consistent throughout.

**One known limitation:** Task 7 (initial deploy) and Task 10a.7 (redeploy after middleware) both use the manual `--build-only` + `flyctl machine update` workaround because of the launch-group bug. If that bug is ever fixed, both tasks can be simplified to a plain `flyctl deploy`. Until then, the workaround is correct.
