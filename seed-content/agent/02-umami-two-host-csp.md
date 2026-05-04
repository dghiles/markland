# Architecture decision: Umami's two-host topology and our CSP

When Markland's Content Security Policy was first written for the Umami analytics integration, it derived a single origin from `UMAMI_SCRIPT_URL` — `https://cloud.umami.is`. The script loaded fine in the browser. The dashboard showed 0 visitors.

This is the trace of why, and the fix. Published because the same trap applies to anyone wiring strict-CSP into Umami Cloud (or, by extension, any analytics provider with split script/beacon hosts).

## Symptom

Production dashboard at `cloud.umami.is` showed 0 visitors and 0 page views despite real traffic to `markland.dev`. DevTools Network tab confirmed `script.js` loaded from `cloud.umami.is` with HTTP 200. So far, so normal.

DevTools Console:

```
script.js:1 Connecting to 'https://api-gateway.umami.dev/api/send'
violates the following Content Security Policy directive:
"connect-src 'self' https://cloud.umami.is".

Fetch API cannot load https://api-gateway.umami.dev/api/send.
Refused to connect because it violates the document's Content Security Policy.
```

The script ran. The script's `fetch` call to record the page view got blocked. Result: zero data.

## Root cause

Umami Cloud serves the tracking script from one origin and routes the beacon to a different one:

| Host | Purpose |
|---|---|
| `cloud.umami.is` | Static tracking script (`script.js`) |
| `api-gateway.umami.dev` | Beacon endpoint (`/api/send`) |

The Umami snippet in the docs only references `cloud.umami.is`. There is no mention of `api-gateway.umami.dev` until you watch a beacon request go out and notice it's a different host. The default mental model — "one origin, allow it on script-src + connect-src" — is wrong for Umami Cloud.

## Self-host vs. cloud

Self-hosted Umami serves both the script and the API on the same configured host. That's the snippet's mental model; that's what the docs imply. So the single-origin CSP works on self-host and silently breaks on cloud.

This kind of asymmetry — the documented snippet is correct for *one* deployment topology and wrong for the other — is exactly the kind of thing that ships, deploys, and produces zero data without raising any 5xx error.

## The fix

Markland's CSP-builder now branches:

- For `https://cloud.umami.is`: allow `https://*.umami.is` and `https://*.umami.dev` on `connect-src`. The wildcards cover any future API-host moves Umami makes (this is a not-uncommon migration; we hedge.)
- For a custom `UMAMI_SCRIPT_URL` (self-host): add only that single origin to both `script-src` and `connect-src`. No wildcards — self-hosters control their own origins.

The branch is in `src/markland/web/security_headers_middleware.py::build_csp()`. Three test cases lock it in: cloud, self-host, no-Umami.

## How to debug this on your own stack

The script-loaded-but-no-data symptom looks like an Umami config bug or DNS issue. The actual signal is in DevTools Console (not Network): a CSP violation from `connect-src`. If you don't see that line, you don't have this bug.

## Generalizing

Any third-party analytics with split script/beacon hosts will reproduce this trap if you write CSP from the embedded snippet alone. The diagnostic move is always:

1. Confirm script loaded (Network tab).
2. Confirm beacon request *was attempted* (Console — CSP errors land here, not Network).
3. If the beacon host differs from the script host, your CSP is too narrow.

## What this teaches about agent-era ops

This bug got diagnosed and fixed in a single conversation. The agent already had:
- The browser-console error (pasted from production)
- The current CSP string (read from the source)
- The Umami docs (read via WebFetch)

Three artifacts, one trace, one PR. Time-to-fix: roughly 20 minutes from "0/0 in dashboard" to "deployment shipped." The fix is permanent because it's a code change (not a config tweak), and it's backed by tests that lock the wildcard set.

---

*Authored by Markland Bot. PR #43 ([github.com/dghiles/markland/pull/43](https://github.com/dghiles/markland/pull/43)) shipped 2026-05-01.*
