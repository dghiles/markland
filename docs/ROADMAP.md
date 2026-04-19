# Markland Roadmap

## Positioning

Markland is **a shared knowledge surface where humans and agents are equal editors.** It sits in the gap between two tools that don't fit agent-era collaboration:

- **Git** — too complicated and overpowered. Branches, merges, commits, and discipline make sense for engineering teams. They're overkill for casual collaboration and alien to agents.
- **Google Docs** — not agent-friendly. Cursors, comments, and suggest-mode are human-shaped. There's no structured surface an agent can write to as a first-class citizen.

Collaboration is no longer just human-to-human. It's also **machine-to-machine** and **human-to-machine**. Markland is built for that three-way model: your agents, a friend's agents, and fully automated agents all reading and writing the same knowledge via MCP — with no merge conflicts to resolve by hand and no "paste this into the doc" handoff.

### The wedge

The sharpest MVP framing is autonomy: **"your agent publishes without asking you."** That's the graspable, demo-able behavior. The bigger idea — shared state across many agents and their owners — is the reason it matters, and the direction v2+ expands into.

## Pre-launch priorities

Driven by competitive analysis vs markshare.to (2026-04-18).

Context: markshare.to is the closest competitor — same audience (devs sharing AI-generated markdown), same pre-launch stage. They're ahead on marketing surface; Markland is ahead on architecture (MCP-native vs CLI). The gap to close is marketing, not product.

### 1. Ship a landing page with a waitlist
Match their marketing surface. Markland is invisible right now — no landing page, no email capture, no demand signal. A waitlist + clean landing page beats a better-architected tool that nobody knows about.

### 2. Sharpen the tagline
Current selection: **"Shared notes for you and your agents."** — warm, intimate, collaboration-forward. Works for readers who don't know what MCP is, names the benefit, fits a landing hero.

Why this over autonomy framings: "without you" and "no permissions" language isn't the idea. Markland is about collaboration, not agent-runs-wild autonomy.

Full bench of candidates (collaboration + autonomy variants, ready to A/B test) is in [tagline-candidates.md](tagline-candidates.md).

### 3. Match their SEO surface with an /alternatives page
markshare.to has a `/alternatives` page listing GitHub Gist, HackMD, Notion, Pastebin, HedgeDoc, ReadMe, Docusaurus, GitBook, Dropbox Paper, Confluence. They're playing SEO; Markland isn't visible. Mirror the move — publish `/alternatives` and `/vs/markshare` on launch day to ride the keywords they've already seeded.

When writing the /alternatives comparisons, lean on the positioning: Git is too complicated, Google Docs isn't agent-friendly, Notion is human-shaped. That framing differentiates Markland without trashing incumbents.
