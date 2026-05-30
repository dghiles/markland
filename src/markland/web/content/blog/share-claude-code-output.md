---
title: How to share Claude Code output without copy-pasting
slug: share-claude-code-output
published_at: 2026-05-30
description: Claude Code writes great markdown. Use the markland_publish MCP tool to turn it into a shareable URL in one call — no Notion, no Docs, no copy-paste.
---

The most common Claude Code workflow goes like this. You ask Claude for a
plan, a spec, a debugging report, or a "here's what changed today" summary.
Claude writes ~1,500 words of clean, well-structured markdown directly into
the terminal. You read it, like it, and then realize: how do I share this
with someone who isn't sitting at my machine?

The path most people take: copy the output, open Notion or a Google Doc,
paste, fight the formatting, fix the code blocks Notion munged, give the
doc a name, click Share, copy the link, paste it into Slack. Best case
that's three minutes of context-switching. Worst case the code blocks
break, the lists renumber, and you spend ten minutes re-formatting.

There is a better way. Install the Markland MCP server once, and
Claude Code gets a new tool — `markland_publish` — that takes the
markdown your agent just wrote, uploads it to <https://markland.dev>, and
returns a shareable URL. One tool call. No copy, no paste, no format fix.

## The 60-second install

Open Claude Code and send this message:

> Install the Markland MCP server from https://markland.dev/setup

Claude Code fetches the runbook, walks you through a one-click browser
authorization, and writes the MCP server config into `~/.claude.json`.
You'll be back in your terminal with a working `markland_publish` tool
in under a minute.

If you want the long version, the [quickstart](https://markland.dev/quickstart)
covers it step-by-step. Markland's auth uses RFC 8628 device flow —
the same primitive `gh auth login` and `vercel login` use — so you'll
recognize the pattern.

## The new workflow

Once installed, the friction drops to zero. After Claude writes the
spec / report / summary, you say:

> Publish that as a Markland doc and give me the link.

Claude calls `markland_publish` with the markdown you just generated.
Markland returns a `https://markland.dev/d/<token>` URL. You paste the
URL into Slack. Total elapsed time from "ask for the spec" to
"link in Slack": about ten seconds longer than just asking for the
spec.

Documents are private by default. The URL works for anyone you share
it with, but it's a share-token URL, not a public-index entry — search
engines and AI crawlers don't see it. If you do want a public doc, ask
Claude to publish it as public and the URL becomes `markland.dev/d/<slug>`
indexable. Default-private means you can dump a half-formed thought
into Markland and not worry about it leaking before you've polished it.

## When this beats the alternatives

Notion is great if your team lives in Notion. But Notion was built for
humans, and its block model means everything your agent writes gets
translated into Notion blocks — losing the markdown source-of-truth in
the process. If you want to round-trip the same doc through three
different agents, Markland preserves the bytes; Notion munges them.

Google Docs has the same shape: built for humans, not agents. There
is no `gdocs_publish` MCP tool (yet), and the OAuth flow to script
against Drive is non-trivial. Markland's whole point is that the
publishing surface is a single MCP tool call.

GitHub Gist works if your audience is technical and you don't mind
the GitHub login wall on the reader side. Markland docs are reachable
without an account.

## What's in the toolkit

`markland_publish` is the headline tool, but the MCP server exposes a
full set of operations Claude Code can use:

- `markland_publish` — turn markdown into a URL
- `markland_update` — edit an existing doc (with version control)
- `markland_search` — find your past docs by title or content
- `markland_grant` — give another human or agent read/edit access
- `markland_revoke` — remove access
- `markland_fork` — copy someone else's doc to your account
- `markland_list_my_agents` — see what agents have access
- ...and a few more

Full reference on the [quickstart](https://markland.dev/quickstart).

## Try it

The whole thing is free during public beta. Visit
[markland.dev](https://markland.dev), sign in with a magic link, and
the install runbook will walk Claude Code through the rest.

The next time Claude writes you a 1,500-word spec, you're ten seconds
from a shareable link, not three minutes from a fight with Notion.
