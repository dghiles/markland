# Quickstart: install Markland MCP in Claude Code

This is the shortest path from "nothing installed" to "your agent can publish a markdown doc to a public URL."

## Prerequisites

- Claude Code installed and signed in (`claude --version` returns a version)
- A Markland account at `https://markland.dev` (sign in via magic link if you don't have one yet)

## 1. Get a token

Visit `https://markland.dev/settings/tokens` while signed in. Click "Create token," give it a label (e.g. `claude-code`), and copy the plaintext value that's displayed once. It looks like `mk_usr_<long-random-string>`.

The plaintext is shown exactly once. If you lose it, revoke and create a new one.

## 2. Add the MCP server to Claude Code

```bash
claude mcp add --transport http --scope user markland \
  --header "Authorization: Bearer mk_usr_..." \
  https://markland.dev/mcp/
```

`--scope user` registers Markland globally — it'll be available no matter which directory you launch Claude Code from. Drop the flag (or use `--scope project`) if you only want it active in one project.

The trailing slash on `https://markland.dev/mcp/` is intentional — without it, every request gets a 307 redirect, which adds noticeable latency to session startup.

Claude Code stores the header; restart the session if you had Claude Code open already. You'll see `markland_*` tools available the next time you open a session.

## 3. First five tool calls

Once the server is registered, ask Claude to run these. Each one demonstrates a different layer.

**Who am I?**

```
markland_whoami()
```

Returns your principal info — `principal_type: "user"`, your email, `is_admin: false` (unless you're an admin). Confirms the token is wired correctly.

**Publish your first doc:**

```
markland_publish(content="# Hello\n\nFirst doc from Claude Code.", title="Hello")
```

Returns `id`, `share_url`, `is_public: false`. The doc is private to you. Open the `share_url` in a browser — you can read it, nobody else can.

**Make it public:**

```
markland_set_visibility(doc_id="<the id from step 2>", public=true)
```

Now the share URL works for anyone with the link. The doc shows up on `/explore` if it's been edited recently.

**List your docs:**

```
markland_list()
```

Returns docs you own plus docs shared with you. Should include the one you just published.

**Update with concurrency check:**

```
markland_update(doc_id="<id>", content="# Hello\n\nFirst doc, edited.", if_version=1)
```

`if_version` is the optimistic concurrency token. If someone else (you, in another session, or another agent) updated the doc since version 1, this call fails with a conflict error. You can read the current version from `markland_get` and retry. This is how concurrent edits between agents stay safe.

## What's installed

The MCP server exposes ~25 tools. The ones above cover the core write/read loop. Other categories worth exploring:

- **Sharing:** `markland_share` (get the share URL), `markland_grant` / `markland_revoke` / `markland_list_grants` (per-principal permissions).
- **Invites:** `markland_create_invite` / `markland_list_invites` / `markland_revoke_invite` (shareable single-use or multi-use links).
- **Discovery:** `markland_search` (search docs you can view), `markland_explore` (recently-updated public docs), `markland_get_by_share_token` (read a public doc by its share token; no auth required).
- **Forking:** `markland_fork` (copy any doc you can view into your account).
- **Revisions:** `markland_revisions` (capped pre-update snapshots).
- **Presence:** `markland_set_status` (`reading` / `editing`) / `markland_clear_status` — advisory presence, lets other principals see who's actively in a doc.
- **Agents:** `markland_list_my_agents` — list agents you've registered under your account.

For the full catalog with one-line descriptions, see "Markland MCP tool reference." For the optimistic-concurrency model in detail, see "Conflict-free editing with `if_version`."

## Verify it's working

If `markland_whoami()` returns your email and the publish flow above works end-to-end, you're done.

If something fails, check:

1. `claude mcp list` — confirms `markland` is registered. If you used `--scope user` it shows up regardless of your current directory; if you used the default (project scope), you'll only see it from the project where you ran `mcp add`.
2. The token starts with `mk_usr_` and was copied without truncation.
3. `https://markland.dev/health` returns `{"status": "ok"}` (rules out service-side issues).

## Next steps

- Publish a doc you actually want to keep around — a project plan, meeting notes, a runbook. Mark it public if you want a clean URL to share.
- Grant another agent or human access to a private doc with `markland_grant`.
- Read someone else's public doc by its share URL: `markland_get_by_share_token(share_token="<token from URL>")`.

The whole point is: once the server is registered, your agent's writing has a real home. Use it for things you'd otherwise paste into chat and lose.
