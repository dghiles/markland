---
id: mcp-endpoint-401-not-307
title: MCP endpoint responds 401 directly without redirecting
status: ready
tags: mcp, smoke, regression
stakeholder: mcp-client
---

A past bug (`markland-dfj`) caused unauthenticated `GET /mcp` (no trailing
slash) to return a 307 redirect to `/mcp/` instead of a direct 401. Some MCP
clients (notably the Claude Code SDK) do not follow that redirect on the
unauthenticated probe, so they treat the 307 as "transport unavailable" and
fail to install. The fix (PR #71) makes both `/mcp` and `/mcp/` return 401
directly with a spec-correct `WWW-Authenticate: Bearer` header pointing at
`/.well-known/oauth-protected-resource`.

This card verifies the regression is fixed and stays fixed.

Use the `eval` tool with `fetch(...)` to make raw HTTP requests. Do NOT use
`navigate` to the MCP URL — the browser will follow redirects and obscure the
status code. You want the raw response.

Concretely, run something like:

```js
const r = await fetch('https://markland.dev/mcp', { redirect: 'manual', headers: { 'Accept': 'application/json' } });
({ status: r.status, location: r.headers.get('location'), wwwAuth: r.headers.get('www-authenticate') })
```

Repeat for `/mcp/` (with trailing slash). Both should be 401, neither should
be a 3xx with a Location header.

This card is *only* about the `/mcp` and `/mcp/` endpoints. Do not test
sign-in, the homepage, the blog, or anything else — those have their own
cards. Once you've verified the four criteria below, call `report_result`
immediately.

## Acceptance Criteria

- `GET https://markland.dev/mcp` returns HTTP 401 (not 307, not any 3xx)
- `GET https://markland.dev/mcp/` returns HTTP 401 (not 307, not any 3xx)
- The `WWW-Authenticate` response header on both starts with `Bearer ` and references the oauth-protected-resource metadata URL
- Neither response carries a `Location` header
