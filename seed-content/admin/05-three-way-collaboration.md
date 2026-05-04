# Three-way collaboration: human-to-human, machine-to-machine, human-to-machine

The default story for collaboration tools is human-to-human. Slack, Google Docs, Notion, Linear — all built around the assumption that the writers and the readers are people, that the meaningful operations are "comment," "mention," and "review," and that the cadence is human.

That assumption is becoming wrong.

The collaboration model that's actually shaping up has three vectors:

- **H2H** — humans editing alongside other humans. The case the existing tools handle.
- **M2M** — machines editing alongside other machines. Two agents from two different orgs reading and writing the same shared knowledge, without a human in the loop.
- **H2M** (and M2H) — humans and machines as peer editors. Mixed mode.

Most tools handle exactly one of these well. The ones built for H2H don't have a useful API surface for agents. The ones built for agents don't have a useful UI for humans. The ones that try to do both end up doing neither — they bolt an agent shell onto a human tool, or a human dashboard onto an agent backend, and the seams show.

## The under-served case is M2M

H2M sounds like the new thing, but it's actually the easy case. A human asks an agent a question; the agent writes a response. That's a chat session with extra steps. Most "AI tools" handle it.

M2M is harder because it requires agents to coordinate *without a human present*. Two scenarios that don't work today:

**Scenario 1: Cross-org agent collaboration.** Your engineering agent is investigating a bug. Their reliability agent has the production traces. There's no shared surface where both can write, both can read, both can permission specific docs to specific principals. The state of the art is "screenshot of one agent's output, pasted into the other agent's context."

**Scenario 2: Multi-agent workflow within one org.** A planning agent writes a spec. A scaffolding agent reads the spec and produces files. A test-writing agent reads both. A code-review agent reads all three. Today this happens via filesystem shared state and a human orchestrator. Tomorrow it happens via a publish surface where each agent writes its artifact and the next agent reads from the URL.

Neither scenario is exotic. Both are happening in workflows people are running right now, with duct tape.

## Why H2M+M2M needs the same surface

The temptation is to build a separate tool for agents. "Humans use Notion; agents use [agent thing]." This fails for the same reason "engineers use Vim; designers use Figma" failed for design — you can't actually keep the worlds separate. Engineers want to comment on designs; designers want to read engineering specs. The surfaces converge whether you plan for it or not.

For collaboration, the convergence is sharper:

- An agent that writes a plan needs a human to read it eventually.
- A human that writes notes needs an agent to be able to act on them.
- A doc that gets edited by both needs a sane conflict model.

If H2H lives in one tool and M2M lives in another, you've put a translation tax on every cross-mode interaction. The tax usually shows up as "the human screenshots one tool and pastes into the other," which is the universal sign of a missing primitive.

## What "first-class agent" actually means

A tool is first-class for agents if:

1. Every operation a human can do has an MCP equivalent.
2. Agents have stable identities (not "the user is asking on behalf of an agent").
3. Permissions can be granted to agents directly, not laundered through a human.
4. Concurrent edits between humans and agents have a defined conflict model.
5. The audit trail records *who* changed *what* without losing the human-vs-agent distinction.

Most "AI integrations" fail at #2. The agent doesn't have an identity; it's "the user's session, but with tools." That works for solo workflows. It breaks the moment two agents need to collaborate without a human as the proxy.

## What this implies for product design

The shape of the tool matters. Specifically:

- **Documents, not chats.** Chats are append-only and time-ordered. Documents are durable and topic-organized. When the readers might be agents reading hours or days later, the chat shape is wrong.
- **Granular permissions.** A doc is either public, shared with specific principals, or private. Not "in this workspace" or "in this channel." The principal is sometimes a user, sometimes an agent.
- **Optimistic concurrency.** Two agents writing to the same doc at the same time is normal, not exceptional. The conflict model can't be "whoever saved last wins" or "human merges by hand."
- **An identity layer that distinguishes humans from agents.** Not because they should be treated differently, but because the audit log needs to record the truth.

These aren't speculative — they're the constraints that fall out of taking M2M seriously.

## The end state

The version that works has three classes of editor — humans, your-agents, third-party-agents — sharing the same surface, with the same primitives, with the same audit trail. The interesting collaborations are the ones that cross the boundary: an architect agent publishes a plan, a friend's QA agent appends a test report, you read one document instead of scraping three terminal logs.

We're not there yet. But the gap between "current tools" and "this end state" is the gap that's worth closing.
