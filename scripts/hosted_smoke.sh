#!/usr/bin/env sh
# Post-deploy smoke test for a hosted Markland instance.
#
# Exercises the full stack as a real MCP client would:
#   - /health returns 200
#   - / (landing) returns 200
#   - /mcp/ returns 401 without a token
#   - /mcp/ returns 200 on `initialize` with a valid user or agent token
#   - `markland_whoami` tool call succeeds and returns the expected principal
#
# Usage:
#   MARKLAND_URL=https://markland.dev \
#   MARKLAND_SMOKE_TOKEN=mk_usr_... \
#   ./scripts/hosted_smoke.sh
#
# MARKLAND_SMOKE_TOKEN is any valid per-user or per-agent API token created
# after sign-in (see /settings or POST /api/tokens). The pre-Plan-2
# MARKLAND_ADMIN_TOKEN is no longer used to gate /mcp.

set -eu

: "${MARKLAND_URL:?set MARKLAND_URL (e.g. https://markland.dev)}"
: "${MARKLAND_SMOKE_TOKEN:?set MARKLAND_SMOKE_TOKEN to a valid mk_usr_ or mk_agt_ token}"

MARKLAND_URL="${MARKLAND_URL%/}"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

echo "==> GET $MARKLAND_URL/health"
curl -fsS "$MARKLAND_URL/health" | tee /dev/stderr
echo

echo "==> GET $MARKLAND_URL/ (landing page, expect 200)"
code=$(curl -s -o /dev/null -w "%{http_code}" "$MARKLAND_URL/")
test "$code" = "200" || fail "landing expected 200, got $code"
echo "ok"

echo "==> POST $MARKLAND_URL/mcp/ without auth (expect 401)"
code=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Accept: application/json, text/event-stream" \
  -X POST "$MARKLAND_URL/mcp/" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}')
test "$code" = "401" || fail "unauth /mcp expected 401, got $code"
echo "ok"

echo "==> POST $MARKLAND_URL/mcp/ initialize with auth (expect 200)"
init_body=$(mktemp)
init_headers=$(mktemp)
trap 'rm -f "$init_body" "$init_headers"' EXIT
code=$(curl -s -o "$init_body" -D "$init_headers" -w "%{http_code}" \
  -H "Authorization: Bearer $MARKLAND_SMOKE_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -X POST "$MARKLAND_URL/mcp/" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}')
test "$code" = "200" || { cat "$init_body" >&2; fail "initialize expected 200, got $code"; }
# MCP streamable HTTP returns Mcp-Session-Id on initialize; subsequent calls
# must echo it back. Header name is case-insensitive per RFC 7230.
session_id=$(awk 'tolower($1) == "mcp-session-id:" { sub(/\r$/, "", $2); print $2; exit }' "$init_headers")
test -n "$session_id" || { cat "$init_headers" >&2; fail "initialize response missing Mcp-Session-Id header"; }
echo "ok (session=$session_id)"

echo "==> POST $MARKLAND_URL/mcp/ tools/call markland_whoami (expect 200 and principal)"
whoami_body=$(mktemp)
trap 'rm -f "$init_body" "$init_headers" "$whoami_body"' EXIT
code=$(curl -s -o "$whoami_body" -w "%{http_code}" \
  -H "Authorization: Bearer $MARKLAND_SMOKE_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $session_id" \
  -X POST "$MARKLAND_URL/mcp/" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"markland_whoami","arguments":{}}}')
test "$code" = "200" || { cat "$whoami_body" >&2; fail "whoami expected 200, got $code"; }
grep -q '"principal_type"' "$whoami_body" || { cat "$whoami_body" >&2; fail "whoami response missing principal_type"; }
echo "ok"

echo
echo "All hosted smoke checks passed."
