# Security Policy

## Reporting a Vulnerability

If you believe you've found a security issue in Markland, please **do not
open a public GitHub issue**. Send the report privately instead:

- Use GitHub's private "Report a vulnerability" link on this repository
  (Security tab → Report a vulnerability), **or**
- Reply to any email you've received from Markland — those replies reach
  a human.

A dedicated `security@markland.dev` address will be published here and on
[markland.dev/security](https://markland.dev/security) before general
availability.

## What to include

- A description of the issue and the impact you believe it has.
- Steps to reproduce, ideally with a minimal example.
- The affected version (commit SHA or release tag).
- Any suggested mitigation, if you have one.

## What to expect

- Acknowledgement within 72 hours.
- A coordinated-disclosure timeline if the issue is confirmed.
- Credit in the fix's commit message or release notes if you'd like it
  (and a quiet fix if you'd rather stay anonymous).

## Scope

**In scope:**

- The hosted service at [markland.dev](https://markland.dev).
- The MCP server (auth, rate limits, tool surface).
- The web viewer (XSS, CSRF, auth bypass, share-link enumeration).
- Magic-link and bearer-token authentication flows.

**Out of scope:**

- Third-party dependencies — please report those upstream.
- Denial-of-service via rate limits (we have them; do tell us if you can
  bypass them, but generic "I can hit your server hard" reports aren't
  actionable).
- Issues that require physical access to a device with valid Markland
  credentials.
