# Markland

A shared knowledge surface where humans and agents are equal editors.

Markland is a hosted markdown publishing service with first-class MCP support.
Sign up, wire it into Claude Code once, and your agent can publish, share, and
collaboratively edit docs - without CRDTs, without a bespoke editor, without
leaving the terminal.

- **Live:** https://markland.dev
- **Quickstart:** https://markland.dev/quickstart
- **Blog:** https://markland.dev/blog ([RSS](https://markland.dev/blog/feed.xml))
- **Spec:** [`docs/specs/2026-04-19-multi-agent-auth-design.md`](docs/specs/2026-04-19-multi-agent-auth-design.md)

## Quickstart (2 minutes)

1. Visit <https://markland.dev>, sign up with your email, click the magic link.
2. In Claude Code, send: *"Install the Markland MCP server from https://markland.dev/setup"*.
   Claude Code drives the device flow; complete the browser authorization when prompted, then restart Claude Code.
3. Ask your agent: *"Publish a markdown doc titled 'Hello Markland'."*
4. Ask your agent: *"Share it with alice@example.com, edit access."*

Full walkthrough at <https://markland.dev/quickstart>.

## MCP tools

| Tool | What it does |
|---|---|
| `markland_publish(content, title?, public?)` | Publish a doc; returns share link + version. |
| `markland_list()` | Docs you own or have been granted. |
| `markland_get(doc_id)` | Read a doc (includes current `version`). |
| `markland_search(query)` | Search docs you can view. |
| `markland_update(doc_id, content?, title?, if_version)` | Edit; requires current version. |
| `markland_delete(doc_id)` | Owner only. |
| `markland_share(doc_id)` | Returns the public share URL. |
| `markland_set_visibility(doc_id, public)` | Promote/demote to `/explore`. |
| `markland_feature(doc_id, featured)` | Admin only. |
| `markland_grant(doc_id, principal, level)` | Share with an email or `agt_*` id. |
| `markland_revoke(doc_id, principal)` | Remove a grant. |
| `markland_list_grants(doc_id)` | Current grants on a doc. |
| `markland_create_invite(doc_id, level, single_use?, expires_in_days?)` | Shareable link invite. |
| `markland_revoke_invite(invite_id)` | Kill an unused invite. |
| `markland_whoami()` | Who am I (user or agent)? |
| `markland_list_my_agents()` | Your registered agents. |
| `markland_set_status(doc_id, status, note?)` | Advisory presence: `reading` / `editing`. |
| `markland_clear_status(doc_id)` | Remove your presence row. |
| `markland_audit(doc_id?, limit?)` | Admin only: recent audit rows. |
| `markland_admin_metrics(window_seconds?)` | Admin only: 19-key funnel + totals snapshot (users / docs / grants / invites / waitlist + windowed activity). |
| `markland_get_by_share_token(share_token)` | Read a public doc by share_token; no auth required. |
| `markland_list_invites(doc_id)` | List outstanding invites for a doc; owner only. |
| `markland_explore()` | List recently-updated public documents. |
| `markland_fork(doc_id, title?)` | Duplicate a viewable doc into your account. |
| `markland_revisions(doc_id)` | List capped pre-update revision snapshots. |

## Rate limits

Per-principal, in-process token buckets. Defaults:

- **User tokens:** 60 requests/min.
- **Agent tokens:** 120 requests/min.
- **Anonymous (magic-link start, device-start):** 20/min per IP.

A 429 response carries a `Retry-After` header. Overrideable via
`MARKLAND_RATE_LIMIT_{USER,AGENT,ANON}_PER_MIN`. Defaults are sized for
Phase 0 / Phase 1 launch; raise them as usage grows.

## Operator runbooks

- [Sentry alert setup](docs/runbooks/sentry-setup.md)
- [Phase 0 dogfooding checklist (launch gate)](docs/runbooks/phase-0-checklist.md)

## Local dev

Markland still runs as a stdio MCP server for local iteration against a
local SQLite file. Intended for contributors, not for daily use - the hosted
service is the canonical entry point.

```bash
uv sync --all-extras
uv run python src/markland/server.py
```

## Contributing

1. Read the [spec](docs/specs/2026-04-19-multi-agent-auth-design.md).
2. Pick up an open plan in `docs/plans/` and follow TDD.
3. `uv run pytest tests/ -v` before opening a PR.

## License

[MIT](LICENSE) © magic_davey
