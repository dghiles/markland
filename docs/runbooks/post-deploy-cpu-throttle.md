# Post-deploy CPU throttle - Runbook

You are here because the **Deploy to Fly** workflow's "Observe production"
step failed (`/health` failed 3 checks in a row after a deploy) or warned
that Fly throttled the VM. The job did **not** roll anything back. That is
deliberate; see "Why no auto-rollback" below.

## What is probably happening

Pattern from the 2026-09-26 outage (root cause strongly supported, not yet
demonstrated end to end):

1. Any machine update (deploy, rollback, `fly scale`) resets the shared-cpu
   burst balance to about 50 CPU-s and drops every MCP connection.
2. Every MCP client reconnects at once. Authenticated requests were
   expensive: each one resolved its token twice, and legacy-shape tokens (no
   embedded token id) were argon2id-verified against every active token,
   about 1 CPU-s per request in prod. (#90 removed the double resolve and
   cached results; markland-tex, #95, replaced the scan with an indexed
   digest lookup.)
3. The burst (about 80 requests in 80s) drained the balance in about 60s.
   Fly then throttled the VM to its 6.25% shared-cpu baseline for about
   15 minutes, and `/health` timed out.

A plain restart does not refill the balance, and it also drops connections.

## Do not (first 15 minutes)

- **Do not roll back, redeploy or restart as the first move.** Each is
  another machine update: another balance reset and another reconnect storm
  on a VM that is already starved.
- Do not load-test or loop `curl` against `markland.dev`. Use single requests.

## Do

1. **Confirm it is CPU throttling.** Read-only query against Fly's metrics
   (both values are in centiseconds; divide by 100):

   ```bash
   # fm2_ / `fly tokens create` tokens need "FlyV1 <token>", not "Bearer".
   curl -sS -H "Authorization: FlyV1 $FLY_API_TOKEN" \
     --data-urlencode 'query=fly_instance_cpu_balance{app="markland"}' \
     https://api.fly.io/prometheus/personal/api/v1/query | jq '.data.result[].value[1]'
   curl -sS -H "Authorization: FlyV1 $FLY_API_TOKEN" \
     --data-urlencode 'query=rate(fly_instance_cpu_throttle{app="markland"}[1m])' \
     https://api.fly.io/prometheus/personal/api/v1/query | jq '.data.result[].value[1]'
   ```

   Throttling looks like a balance near 0 and a non-zero throttle rate. If
   the balance is healthy and the throttle rate is 0, this is a different
   failure: read `flyctl logs -a markland` and Sentry instead.

2. **Scale the VM class up.** Performance vCPUs have a 100% baseline and no
   burst balance to drain, so the reconnect burst is absorbed. This is still
   a machine update (clients reconnect once more), which is why it comes
   first and a rollback does not:

   ```bash
   flyctl scale vm performance-1x --vm-memory 2048 -a markland
   ```

3. **Make it stick.** `fly.toml` pins `[[vm]] cpu_kind = 'shared'`,
   `cpus = 1`, `memory_mb = 1024`, and a later `flyctl deploy` can apply that
   again. Open a PR changing `[[vm]]` to match what you scaled to before the
   next deploy goes out.

4. **Verify** with one request at a time:
   `curl -s -o /dev/null -w '%{http_code} %{time_total}\n' https://markland.dev/health`,
   and re-run the throttle query until the rate is 0.

5. **Then decide about the code.** Once the VM has headroom, a rollback or
   fix-forward is an ordinary decision. Scale back to shared-cpu only after
   the per-request auth cost is fixed and a deploy has been observed clean.

## Throttle warning, job passed

Health held, so nothing is down. Watch the next few minutes of MCP latency
and Sentry. Repeated warnings on routine deploys mean the VM has no headroom
for the reconnect burst: plan the scale-up in step 2 rather than waiting for
an outage.

## Why no auto-rollback

A rollback is a machine update, so it resets the burst balance and forces
the same reconnect burst that caused the outage. Firing one automatically
during a post-deploy reconnect burst can start or extend an outage. See the
comment on the observe step in `.github/workflows/deploy.yml`.
