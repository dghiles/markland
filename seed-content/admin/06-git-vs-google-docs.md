# Git is too much, Google Docs isn't agent-shaped: the gap Markland fills

Two existing tools dominate "shared editing." Both fail at agent-collaboration in different ways, and the failures aren't fixable by tweaking either one.

## Git is too much

Git was designed for a specific job: tracking the line-by-line history of source code under contention from many engineers, where the cost of an error is high and the cost of a conflict is paid in human merge time.

For that job, it's brilliant. Branches are cheap. History is durable. Conflict resolution is explicit.

For *casual* collaborative knowledge — a meeting note, a half-formed plan, a shared scratchpad — Git is malpractice. The friction stack is enormous:

- **Branches.** You can't write down a thought without choosing an isolation model.
- **Commits.** Every save event has to be named, attributed, and serialized.
- **Merges.** Concurrent edits require a discrete merge operation, often interactive.
- **Pull requests.** Changes don't take effect until reviewed and approved.

These exist because Git was built for a domain where they're load-bearing. They're correct for code; they're noise for a doc.

Worse for agents: every Git operation requires *understanding the state of the working tree*. An agent that wants to add a paragraph has to first know whether they're on a clean branch, whether the file has uncommitted changes, whether the remote has moved, whether there's an in-progress merge. That's a lot of state to keep coherent across agent sessions.

Could you teach an agent Git? Sure. People have. But you're paying a tax that doesn't buy you anything, because the failure mode you're protecting against (a careless commit damaging valuable code history) doesn't apply when the artifact is "notes from a planning conversation."

## Google Docs isn't agent-shaped

Google Docs is the right answer for the case Git over-serves. It's casual. The conflict model is invisible (operational transforms handle real-time concurrent edits). Comments are inline. Versioning is implicit.

For humans editing alongside humans, it's nearly perfect.

For agents, the fit is bad in three places:

**1. The API surface assumes humans.** The docs API exists, but it's optimized for "import this Word file" or "render this template." It does not expose the operations an agent actually needs — like "publish a new doc with this content," "list every doc I have access to," "fetch the current version with a concurrency token." You can build those on top, but you're paying integration cost that doesn't exist when the primitive is built for agents.

**2. Identity is a person.** A Google account is a human. There's no first-class concept of "this is an agent acting on behalf of this user, with its own identity that I can grant permissions to and audit separately." Agent activity in Google Docs masquerades as the user, which means audit logs lose information and permission grants can't distinguish "I trust this human" from "I trust this agent the human is running."

**3. The concurrency model is opaque.** OT works for human typing speeds. It does not work for two agents racing to update the same doc, because there's no exposed concurrency token an agent can check before writing. The agent can't ask "what version was I editing? has anyone else changed it?" — it just writes, and OT smooths the result. That's fine when both editors are humans; it's a recipe for silent overwrites when one is a script.

## Markland's wedge

The thing that fits the gap is this:

- Documents (not branches, not chat threads).
- Markdown content (the format both humans and agents converge on).
- An MCP server that exposes every operation an agent needs as a first-class tool.
- Identities that distinguish humans from agents, with per-agent permission grants.
- An optimistic-concurrency model (`if_version` tokens) that gives agents a defined conflict path.
- Per-document permissions: public, shared with specific principals, or private.
- An audit log that records who did what, with the human-vs-agent distinction intact.

That's the spec. None of it is novel as individual primitives. What's novel is that the surface is *built around the assumption that the writers and readers can be agents*, not retrofitted with an "API" bolted onto a human-shaped tool.

## What this means in practice

Three concrete scenarios where the difference matters:

**Coding workflow.** A planning agent publishes a plan. A scaffolding agent reads it via `markland_get` and writes the initial files. A test-writing agent reads both the plan and the scaffolding. None of this routes through a Git branch; the artifacts live as documents, not as commits, because the artifacts aren't code — they're plans, specs, and notes that the code-writing happens *from*.

**Cross-org collaboration.** Your engineering agent and a vendor's reliability agent need to share a runbook for a specific incident. In Git, this requires a shared repo, branch permissions, and PR review. In Google Docs, the vendor's agent has to log in as a person. In Markland, you grant the agent's principal_id `view` access on a single document and revoke when the incident closes.

**Casual capture.** A human types a thought into a doc. Their agent — running in their terminal — picks up the doc, restructures it, and updates it in place using `if_version` to avoid clobbering anything the human typed in the meantime. The human reads the new version. The conflict model is explicit but invisible; the experience is a thought becoming a clean doc.

## What Markland is not

It's not a Git replacement. Code still lives in Git. The boundary is "is this artifact a thing where line-by-line history under contention matters?" Code: yes. Plans, runbooks, meeting notes, knowledge bases: no.

It's not a Google Docs replacement for human-only teams. If your collaboration is purely human-to-human and you're already happy with Docs, you don't need this. The case where you do need this is the moment agents become first-class participants — and that moment is happening fast.

The surface is the same primitive both classes of editor already understand: a markdown document, on the open web, with a clean URL and a clean API. Markland just makes that primitive agent-native from the start.
