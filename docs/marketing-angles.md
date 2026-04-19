# Markland Marketing Angles

A working file of positioning, differentiation, and copy angles. Source for the landing page, `/alternatives` SEO pages, social posts, and sales collateral.

Ordering: sharpest first. Use the top 2–3 on the landing; the rest feed longer-form pages.

## Core one-liner

**Shared documents. For you and your agents.**

Tagline decision from ROADMAP. Landing hero. Warm, collaboration-forward, names the benefit.

## Wedge (demo-able)

**One MCP call. One shareable link.** Your agent publishes markdown directly. No copy-paste from chat, no editor, no repo.

This is the moment-of-magic. Use it in demos, in the how-it-works section, and as the "what does it actually do" answer when anyone asks.

## The bigger idea (v2+ direction)

**Collaboration is now three-way: H2H, H2M, M2M.** The shared surface where your agents, your teammates, and their agents all edit the same docs via MCP.

Use for longer-form content and About pages. Too abstract for a landing hero.

---

## Differentiation by competitor

### vs GitHub

**Angle 1 — Sharing unit mismatch.**
GitHub's sharing unit is the **repo**, not the doc. To share a single file in a private repo, your viewer needs a GitHub account *and* org membership. For a product-spec or design doc you want a non-engineer teammate to read, that's a dead end.

**Angle 2 — Code-review chrome bounces non-technical viewers.**
Even when the markdown renders, it's wrapped in commit history, file tree, blame tabs, and branch selectors. A PM or client opens the link, sees a code-review UI, and bounces. GitHub's viewer is for engineers reviewing code, not readers reading a doc.

**Angle 3 — Agents can't publish to GitHub.**
Publishing requires auth, repo write access, and a commit flow. No MCP surface. Your agent can't hand you back a shareable URL from a single tool call — it has to ask for credentials and do a multi-step commit/PR dance.

**Caveat to avoid:** don't claim "it's hard to share files from GitHub" — public repo raw URLs and Gists work fine. The real pain is **private content + non-technical viewers + agents**, which is exactly our target.

**Supporting pillar copy (already shipped):**
> Git is overkill — Branches, merges, PRs — made for engineering teams. Overkill for notes, alien to your agents.

### vs Google Docs

**Angle 1 — Built for human editors, not agents.**
Cursors, comments, suggest-mode — every affordance assumes a human at a keyboard. No MCP tools. No first-class publish/search/iterate primitives for agents.

**Angle 2 — Your information isn't agent-addressable.**
Docs live inside a Drive UI your agent can't navigate, organized in folders your agent can't reason about. Even when Google adds AI features, the agent is a guest in a human workflow — not a first-class editor.

**Supporting pillar copy (already shipped):**
> Google Docs isn't agent-native — Current editors built for humans. Your agents and workflows aren't native to your information.

### vs Notion

**Angle 1 — Blocks vs markdown.**
Notion's unit is the block, not the file. That makes it harder for agents (which produce markdown) to publish without lossy conversion. Markland keeps markdown as the native format end-to-end.

**Angle 2 — Account wall.**
Notion pages shared publicly work, but the experience pushes viewers toward sign-up. Markland share links have no wall — they're just URLs.

### vs Markshare.to

**Angle 1 — MCP-native vs CLI.**
Markshare.to is a CLI that uploads markdown. Markland is an MCP server your agent already knows how to call. No "copy this command, run it in your terminal" step.

**Angle 2 — Three-way collaboration vs one-shot publish.**
Markshare.to is a publish-and-share endpoint. Markland is a shared surface — multiple agents, multiple humans, all reading and writing the same docs.

### vs Pastebin / HackMD / HedgeDoc / Gist

These are all "paste text, get URL" products. Markland's differentiation is **the agent writes it directly via MCP** — no copy-paste, no human in the middle. For anything an agent produces (specs, plans, research summaries, CLAUDE.md files), the paste step is the friction.

---

## Pain-led copy (for ad headlines, tweets, section intros)

- Stop copy-pasting from your agent's chat into a doc.
- Your agent's best writing is trapped in a chat log.
- GitHub is for code review. Your spec isn't code.
- Your agent has thoughts. Give it somewhere to put them.
- The doc your agent wrote should have a URL.
- One MCP call. One link. No editor.

## Outcome-led copy (benefit framing)

- Your agent writes markdown. You share the link.
- Let your agents publish like teammates.
- Docs that your agents can actually own.
- A shared surface your whole stack can edit — humans included.

## Category-creation copy (manifesto register)

- Collaboration is now three-way.
- Every agent deserves an edit button.
- Git is overkill. Google Docs isn't agent-native.
- The document layer agent-first builders were missing.

---

## Audience segments & their hook

| Segment | Sharpest hook |
|---|---|
| Solo dev using Claude Code / Cursor | "Your agent's specs deserve a URL, not a chat scrollback." |
| Engineering lead | "Share design docs with non-technical teammates without adding them to GitHub." |
| AI-first startup founder | "Your agents are already producing docs. Give them a publishing surface." |
| Agent framework builder | "MCP-native hosting layer — one tool call to publish and share." |
| PM collaborating with engineers' agents | "Read what their agents write, without a GitHub account." |

---

## Things to NOT claim (kills credibility)

- "It's hard to share files from GitHub." (Public repos + Gists make this false.)
- "Agents can't use Google Docs at all." (They can, clumsily, via API — claim is about first-class vs. bolt-on.)
- "Replaces Notion / Confluence." (We don't — different product shape, narrow wedge.)
- "Solves merge conflicts." (Not in v1. CRDT is scoped tightly per memory.)
- "For teams." (Pre-launch; solo-dev + small-collab is the actual wedge.)

---

## Headline formulas that tested well in the bench

From `tagline-candidates.md`, worth reusing in different contexts:

- **Format: "X is overkill. Y isn't Z."** — Manifesto pillars, about-page hero.
  - *Git is overkill. Google Docs isn't agent-native.*
- **Format: "Shared [noun] for [audience]."** — Category-definition.
  - *Shared documents. For you and your agents.*
- **Format: "[Verb]. [Verb]."** — Wedge demo line.
  - *Your agent publishes. You share the link.*
- **Format: "Every agent gets [affordance]."** — Equal-citizenship framing.
  - *Every agent gets an edit button.*
