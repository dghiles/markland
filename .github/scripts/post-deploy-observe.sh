#!/usr/bin/env bash
# Post-deploy observation for markland. Run by .github/workflows/deploy.yml
# right after `flyctl deploy`; see the comment there for why this only
# observes and never rolls back.
#
# For CHECKS rounds, every INTERVAL_SECONDS:
#   - one GET of HEALTH_URL (a single request: no retries, HEALTH_TIMEOUT cap)
#   - one sample each of Fly's min(fly_instance_cpu_balance) and
#     max(rate(fly_instance_cpu_throttle[1m])) for FLY_APP. Fly reports both
#     in centiseconds; they are printed as CPU-seconds and throttled s/s.
#
# Exit 1: HEALTH_URL failed FAIL_AFTER checks in a row (fails fast). Failures
#         before the first passing check are not counted for the first
#         BOOT_GRACE_SECONDS, so a slow boot is not an outage.
# Exit 0: everything else. Isolated health failures, a CPU balance dip,
#         throttling and metrics-API errors only emit ::warning:: lines. A
#         balance dip is expected right after a deploy: the deploy resets the
#         burst balance and every MCP client reconnects at once.

set -uo pipefail

HEALTH_URL="${HEALTH_URL:-https://markland.dev/health}"
FLY_APP="${FLY_APP:-markland}"
PROM_URL="${PROM_URL:-https://api.fly.io/prometheus/personal/api/v1/query}"
CHECKS="${CHECKS:-30}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-10}"
FAIL_AFTER="${FAIL_AFTER:-3}"
BOOT_GRACE_SECONDS="${BOOT_GRACE_SECONDS:-60}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-5}"
FLY_API_TOKEN="${FLY_API_TOKEN:-}"

RUNBOOK="docs/runbooks/post-deploy-cpu-throttle.md"
if [ -n "${GITHUB_SERVER_URL:-}" ] && [ -n "${GITHUB_REPOSITORY:-}" ] && [ -n "${GITHUB_SHA:-}" ]; then
  RUNBOOK="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/blob/${GITHUB_SHA}/${RUNBOOK}"
fi

# Fly's Prometheus API wants "FlyV1 <macaroon>" for `fly tokens create` /
# fm2_ tokens (it answers 401 to "Bearer fm2_...") and "Bearer <token>" for
# older `flyctl auth token` tokens.
auth_header() {
  case "$FLY_API_TOKEN" in
    "FlyV1 "*) printf 'Authorization: %s' "$FLY_API_TOKEN" ;;
    fm1_* | fm2_*) printf 'Authorization: FlyV1 %s' "$FLY_API_TOKEN" ;;
    *) printf 'Authorization: Bearer %s' "$FLY_API_TOKEN" ;;
  esac
}

lt() { awk -v a="$1" -v b="$2" 'BEGIN { exit !(a < b) }'; }
div100() { awk -v v="$1" -v p="$2" 'BEGIN { printf "%.*f", p, v / 100 }'; }

metrics_err=""
metrics_off=0
[ -n "$FLY_API_TOKEN" ] || { metrics_off=1; metrics_err="FLY_API_TOKEN not set"; }

# Sets PROM_VALUE to the query's scalar result, or "" when unavailable.
prom_query() {
  PROM_VALUE=""
  [ "$metrics_off" -eq 0 ] || return 0
  local resp code
  resp=$(curl -sS --max-time 5 -H "$(auth_header)" --data-urlencode "query=$1" \
    -w '\n%{http_code}' "$PROM_URL" 2>/dev/null)
  code="${resp##*$'\n'}"
  if [ "$code" != "200" ]; then
    if [ -z "$metrics_err" ]; then
      echo "Fly metrics query failed (HTTP $code); continuing with health checks only."
    fi
    metrics_err="HTTP $code"
    case "$code" in 401 | 403) metrics_off=1 ;; esac
    return 0
  fi
  PROM_VALUE=$(printf '%s' "${resp%$'\n'*}" | jq -r '.data.result[0].value[1] // empty' 2>/dev/null)
  case "$PROM_VALUE" in '' | *[!0-9.eE+-]*) PROM_VALUE="" ;; esac # drops NaN/Inf
}

ok=0 failed=0 consec=0 max_consec=0 seen_ok=0 slowest=""
bal_first="" bal_min="" bal_last="" thr_max="" thr_samples=0

summary() {
  local total=$((ok + failed)) slow="${slowest:+${slowest}s}"
  echo
  echo "Post-deploy observation summary: $1"
  echo "  health        : $ok ok / $failed failed of $total checks (max $max_consec in a row) at $HEALTH_URL"
  echo "  slowest 200   : ${slow:-n/a}"
  echo "  cpu balance   : first=${bal_first:-n/a} min=${bal_min:-n/a} last=${bal_last:-n/a} CPU-s"
  echo "  cpu throttle  : max=${thr_max:-n/a} throttled s/s (1m rate); throttled in $thr_samples samples"
  [ -z "$metrics_err" ] || echo "  metrics       : $metrics_err"
  [ -n "${GITHUB_STEP_SUMMARY:-}" ] || return 0
  {
    echo "### Post-deploy observation: $1"
    echo
    echo "| Signal | Result |"
    echo "|---|---|"
    echo "| Health \`$HEALTH_URL\` | $ok ok / $failed failed of $total (max $max_consec in a row) |"
    echo "| Slowest 200 | ${slow:-n/a} |"
    echo "| CPU burst balance (CPU-s) | first ${bal_first:-n/a}, min ${bal_min:-n/a}, last ${bal_last:-n/a} |"
    echo "| CPU throttle (s/s, 1m rate) | max ${thr_max:-n/a}, throttled in $thr_samples samples |"
    [ -z "$metrics_err" ] || echo "| Metrics | $metrics_err |"
    echo
    echo "Runbook: $RUNBOOK"
  } >>"$GITHUB_STEP_SUMMARY"
}

echo "Observing $HEALTH_URL and Fly CPU metrics for app=$FLY_APP:"
echo "$CHECKS checks every ${INTERVAL_SECONDS}s; fails after $FAIL_AFTER consecutive health failures; never rolls back."

start=$SECONDS
i=1
while [ "$i" -le "$CHECKS" ]; do
  elapsed=$((SECONDS - start))

  out=$(curl -s -o /dev/null -w '%{http_code} %{time_total}' --max-time "$HEALTH_TIMEOUT" "$HEALTH_URL" 2>/dev/null)
  rc=$?
  code="${out%% *}"
  took="${out#* }"
  [ -n "$code" ] || code="000"
  [ -n "$took" ] || took="0"
  shown="$code"
  [ "$rc" -eq 0 ] || shown="$code (curl exit $rc)"

  if [ "$code" = "200" ]; then
    ok=$((ok + 1)) consec=0 seen_ok=1 note=""
    if [ -z "$slowest" ] || lt "$slowest" "$took"; then slowest="$took"; fi
  else
    failed=$((failed + 1))
    if [ "$seen_ok" -eq 1 ] || [ "$elapsed" -ge "$BOOT_GRACE_SECONDS" ]; then
      consec=$((consec + 1)) note="  FAIL ($consec in a row)"
      [ "$consec" -le "$max_consec" ] || max_consec=$consec
    else
      note="  FAIL (boot grace, not counted)"
    fi
  fi

  prom_query "min(fly_instance_cpu_balance{app=\"$FLY_APP\"})"
  bal=""
  if [ -n "$PROM_VALUE" ]; then
    bal=$(div100 "$PROM_VALUE" 1)
    [ -n "$bal_first" ] || bal_first=$bal
    if [ -z "$bal_min" ] || lt "$bal" "$bal_min"; then bal_min=$bal; fi
    bal_last=$bal
  fi
  prom_query "max(rate(fly_instance_cpu_throttle{app=\"$FLY_APP\"}[1m]))"
  thr=""
  if [ -n "$PROM_VALUE" ]; then
    thr=$(div100 "$PROM_VALUE" 3)
    if [ -z "$thr_max" ] || lt "$thr_max" "$thr"; then thr_max=$thr; fi
    if lt 0 "$PROM_VALUE"; then thr_samples=$((thr_samples + 1)); fi
  fi

  printf '[%2d/%d] +%3ds health=%s %ss | cpu_balance=%s CPU-s throttled=%s s/s%s\n' \
    "$i" "$CHECKS" "$elapsed" "$shown" "$took" "${bal:-n/a}" "${thr:-n/a}" "$note"

  if [ "$consec" -ge "$FAIL_AFTER" ]; then
    summary "FAILED"
    cat <<EOF

================================================================================
PRODUCTION IS FAILING HEALTH CHECKS AFTER THIS DEPLOY
$HEALTH_URL failed $consec checks in a row.

This job did NOT roll back, on purpose. A rollback is another machine update:
it resets Fly's shared-cpu burst balance and makes every MCP client reconnect
at once, which can deepen a CPU-throttle outage. Recovery is an operator
decision; start here (scale the VM class up first):
  $RUNBOOK
================================================================================
EOF
    echo "::error title=Post-deploy health check failed::$HEALTH_URL failed $consec consecutive checks after deploy. Nothing was rolled back. Runbook: $RUNBOOK"
    exit 1
  fi

  i=$((i + 1))
  [ "$i" -gt "$CHECKS" ] || sleep "$INTERVAL_SECONDS"
done

summary "OK"
if [ "$failed" -gt 0 ]; then
  echo "::warning title=Post-deploy health blips::$failed of $((ok + failed)) health checks failed (never $FAIL_AFTER in a row). Runbook: $RUNBOOK"
fi
if [ "$thr_samples" -gt 0 ]; then
  echo "::warning title=Fly CPU throttling after deploy::Fly throttled app=$FLY_APP in $thr_samples samples (max ${thr_max} s/s). Health held, so the job passes; if MCP clients time out or /health starts failing, see $RUNBOOK"
fi
if [ -n "$metrics_err" ]; then
  echo "::warning title=Fly metrics unavailable::CPU balance/throttle were not sampled ($metrics_err). The Prometheus API needs an org or read-only token (fly tokens create readonly)."
fi
exit 0
