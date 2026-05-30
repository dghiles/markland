# Show HN Draft — Markland

**Status:** Drafted 2026-05-29. NOT POSTED. Post when: Track B (homepage CRO) shipped + verified converting + Track C (post #2) live + Tracks E1-E3 (deletion Phase 1, privacy, ToS) shipped.

**Best time to post:** Tuesday-Thursday, 8-10am EST (weekday US morning).

---

## Title (max 80 chars)

Show HN: Markland – Publish markdown from your AI agent with one MCP tool call

## URL

https://markland.dev

## Body (text only — Show HN body is optional but recommended for context)

Hi HN — I built Markland because every time Claude Code wrote me a great
spec or report, I lost ten minutes copying it into Notion and fighting
the formatting. Markland is an MCP server that gives Claude Code (and
any other MCP-compatible agent — Cursor, Codex, Claude Desktop) a
`markland_publish` tool: turn the markdown your agent just wrote into
a shareable URL with one tool call.

The full toolkit is around two dozen MCP tools — publish, grant,
revoke, search, fork, update with version control, invite, list, etc.
— and the reader side is a plain HTTPS link that any browser or agent
can fetch. Documents are private by default; you can grant access to
specific humans (by email) or agents (by agent ID). Auth uses RFC 8628
device flow, same primitive `gh auth login` and `vercel login` use.

It's free during public beta. The technical writeup is on the blog:
https://markland.dev/blog/agent-native-publishing

A few specifics I expect HN to ask about:

- **What's the storage?** SQLite + Litestream backup to R2, hosted on
  Fly.io. Built for one writer plus many readers per doc; not trying
  to compete with Notion at the database-of-everything level.
- **What's the auth model?** Magic-link sign-in for humans (no
  passwords), Argon2id-hashed bearer tokens for agents, append-only
  audit log on every mutation. Pre-release security review filed 18
  findings; all 18 are shipped (P0/P1/P2/P3).
- **What about real-time?** Not yet. v1 is advisory presence (badges,
  no live updates). CRDT collaboration is on the v2 roadmap.
- **What's the business model?** Free during beta. Paid tiers
  (Free / Pro / Team / Enterprise) are designed; spec is on the
  roadmap. Won't charge per-agent — agents are first-class, not
  penalized.

It's operated by one developer (me). The privacy and security pages
are explicit about that and about what we do and don't store:
https://markland.dev/privacy, https://markland.dev/security

Code is open: https://github.com/dghiles/markland

Happy to answer questions.

— davey

---

## Canned reply: "Why not GitHub Gist / Notion / Google Docs?"

(Already covered in https://markland.dev/blog/share-claude-code-output —
quick version: Gist has the GitHub login wall on readers; Notion's
block model loses the markdown source-of-truth; Google Docs has no
agent-facing API surface. Markland's whole point is that the
publishing step is one MCP tool call from the agent that wrote the
doc, with bytes preserved exactly.)

## Canned reply: "How is this different from $X MCP server I just installed?"

(I don't know any direct competitor that combines publish + grants +
agent identities + share tokens behind a single MCP surface. If you
do, please link — I'd genuinely like to compare. The closest thing in
spirit is HackMD/markshare for human-to-human markdown sharing, but
those don't have first-class agent identities or an MCP server.)

## Canned reply: "What if I trust agent A to read but not write?"

Per-grant permissions are scoped: each grant is `view`, `edit`, or
`owner`. An agent gets exactly the permission the human granting
access chose. The recent install/onboarding work also gates the
"flip a doc public" path so an agent can't accidentally make
something public on a casually-worded prompt.

## Canned reply: "What does it cost to run, single-developer-style?"

About $30/month total: Fly.io (~$15), Resend (~free at this volume),
Cloudflare R2 backups (~free at this volume), Umami Cloud analytics
(~free at this volume), domain (~$15/year). Almost everything has a
free tier appropriate to the scale.

## Anti-pattern check

- DON'T link the blog post AND say "I wrote a post about it" — let
  HN find the post organically by clicking through.
- DON'T mention the metrics from the soak-window. The 6-users number
  is honest but will read as low even by Show HN beta standards. The
  HN audience will figure out the scale from looking at the site.
- DON'T post the same week a competing high-profile MCP server
  launches on HN. Check the front page first.
- DON'T post when you can't be at the keyboard for the next 4 hours
  to respond to comments. The first 2 hours of comments determine
  whether the post survives.
