"""Competitor data for /alternatives pages.

Single source of truth. Update here and both the hub page and per-competitor
pages re-render consistently.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Competitor:
    slug: str
    name: str
    tagline: str
    one_liner: str
    sharing_unit: str
    agent_access: str
    best_for: str
    not_ideal_for: str
    angles: tuple[tuple[str, str], ...]  # (heading, paragraph) pairs


MARKLAND = {
    "name": "Markland",
    "tagline": "Shared documents. For you and your agents.",
    "sharing_unit": "A single doc. Every doc has a share link.",
    "agent_access": "First-class. MCP server, one tool call to publish, share, or edit.",
    "best_for": "Solo developers and small teams whose agents produce markdown they want to share — specs, plans, research notes, CLAUDE.md files.",
    "not_ideal_for": "Large editorial teams with rich-text workflows, binary assets, or strict CRDT-style real-time co-editing requirements.",
}


COMPETITORS: tuple[Competitor, ...] = (
    Competitor(
        slug="markshare",
        name="Markshare.to",
        tagline="Terminal to webpage in three seconds.",
        one_liner="A CLI that uploads markdown files and gives you back a URL.",
        sharing_unit="A single markdown file per upload.",
        agent_access="Indirect. Your agent has to shell out to the CLI — there is no MCP surface.",
        best_for="Developers who want a one-shot 'paste this command, get a URL' flow from their own terminal.",
        not_ideal_for="Multi-agent or multi-human collaboration on the same doc over time.",
        angles=(
            (
                "MCP-native vs CLI",
                "Markshare.to is a CLI that uploads markdown. Your agent has to ask you to run a terminal command, or you have to copy its output into a file it can shell out to upload. Markland is an MCP server your agent already knows how to call. One tool call — `markland_publish` — and the agent hands you back the link. No 'copy this command, run it in your terminal' step.",
            ),
            (
                "Shared surface vs one-shot publish",
                "Markshare.to is a publish-and-share endpoint: the file goes up, the URL comes back, and that is the end of the relationship. Markland is a shared surface. The same doc can be read and edited by multiple agents, multiple humans, and agents working on behalf of other humans — all through the same MCP toolset. Collaboration is three-way: human-to-human, human-to-agent, agent-to-agent.",
            ),
            (
                "Versioning and concurrent edits",
                "Markland's `markland_update` takes an `if_version` argument. Concurrent writers see a conflict instead of silently clobbering each other. Markshare.to's model is 'upload replaces the file' — fine for a one-shot share, unsafe for anything two parties are both editing.",
            ),
            (
                "Fine-grained grants",
                "Markland has per-doc grants for specific principals — emails or agent IDs — plus single-use invite links. Markshare.to's sharing model is 'anyone with the URL.' Good for broadcast; limiting for collaboration.",
            ),
        ),
    ),
    Competitor(
        slug="github",
        name="GitHub",
        tagline="The home of open source code.",
        one_liner="A source-control host whose sharing unit is the repository.",
        sharing_unit="A repository. You grant access to the repo, not the file.",
        agent_access="None via MCP. Agents would need repo write access, auth, and a commit/PR flow.",
        best_for="Engineering teams reviewing code, versioning source, and shipping software.",
        not_ideal_for="Sharing a single private document with a non-engineering colleague or client.",
        angles=(
            (
                "Sharing unit mismatch",
                "GitHub's sharing unit is the repository, not the document. To share one private file, your viewer needs a GitHub account *and* membership of your organization. For a design doc you want a non-engineer teammate to read, that is a dead end. Markland's unit is the doc — one share link, one viewer, no org membership.",
            ),
            (
                "Code-review chrome bounces readers",
                "Even when a markdown file renders on GitHub, it is wrapped in commit history, file tree, blame tabs, and branch selectors. A PM or client opens the link, sees a code-review UI, and bounces. GitHub's viewer is built for engineers reviewing code. Markland's viewer is built for readers reading a doc.",
            ),
            (
                "Agents can't publish",
                "Publishing to GitHub requires auth, repo write access, and a commit. There is no MCP surface. Your agent can't hand you back a shareable URL from a single tool call — it has to ask for credentials and run a multi-step commit/PR dance. Markland is one tool call.",
            ),
            (
                "What GitHub is still better at",
                "If your content is code, or if it lives next to code, GitHub is the right home. Public repos and Gists solve 'share a public file' cleanly. Markland is for the private docs and agent-authored notes that do not belong in a source tree.",
            ),
        ),
    ),
    Competitor(
        slug="google-docs",
        name="Google Docs",
        tagline="The default human-collaboration editor.",
        one_liner="A rich-text editor designed around humans co-editing with cursors and comments.",
        sharing_unit="A doc, shared by link or per-email with Google accounts.",
        agent_access="Bolt-on. API access exists but the UI is built for humans; no MCP surface; content lives inside a Drive UI an agent cannot reason about.",
        best_for="Teams of humans writing together, leaving comments, tracking suggestions, and using rich formatting.",
        not_ideal_for="Agent-first workflows where the content is markdown end-to-end and the agent is an equal editor.",
        angles=(
            (
                "Built for human editors, not agents",
                "Cursors, comments, suggest-mode — every affordance assumes a human at a keyboard. There is no MCP surface and no first-class publish, search, or iterate primitives for agents. When Google adds AI features, the agent is a guest in a human workflow. In Markland the agent is a first-class editor with its own token and the same toolset you use.",
            ),
            (
                "Your information isn't agent-addressable",
                "Docs live inside a Drive UI your agent cannot navigate, organized in folders your agent cannot reason about. Markland docs are addressable by stable IDs, returned directly from every tool call, and searchable through `markland_search`.",
            ),
            (
                "Markdown-native end-to-end",
                "Your agent produces markdown. Google Docs converts it into rich-text blocks, loses structure on export, and re-adds it on re-import. Markland stores the markdown the agent wrote and serves it back verbatim.",
            ),
            (
                "What Google Docs is still better at",
                "If the content is a meeting note with three humans leaving comments in real time, or a contract with a suggestion-mode review cycle, Google Docs is the right tool. Markland does not try to be that.",
            ),
        ),
    ),
    Competitor(
        slug="notion",
        name="Notion",
        tagline="A blocks-based workspace for teams.",
        one_liner="A database-plus-wiki hybrid built around rich content blocks.",
        sharing_unit="A page, optionally shared publicly with an account-wall bias.",
        agent_access="API-based, block-shaped. Lossy for agents producing markdown.",
        best_for="Teams building internal wikis, databases, and structured workflows.",
        not_ideal_for="Anyone whose content is plain markdown and who wants that markdown preserved on disk.",
        angles=(
            (
                "Blocks vs markdown",
                "Notion's unit is the block, not the file. Agents produce markdown. Every round-trip through Notion's block model loses or rewrites structure. Markland keeps markdown as the native format end-to-end — the bytes the agent wrote are the bytes the reader renders.",
            ),
            (
                "Account wall",
                "Notion public pages technically work, but the experience nudges viewers toward sign-up. Markland share links are just URLs. Nothing to sign up for to read.",
            ),
            (
                "Weight",
                "Notion is a full workspace with databases, permissions, templates, and block types. Markland is a narrow surface: docs, share links, grants, presence. Use Markland when you want one of those, not all of them.",
            ),
        ),
    ),
    Competitor(
        slug="hackmd",
        name="HackMD / HedgeDoc / Gist / Pastebin",
        tagline="Paste text, get URL.",
        one_liner="A family of 'drop markdown in a box, get a share link' tools.",
        sharing_unit="A pasted snippet with a share URL.",
        agent_access="None. A human has to paste.",
        best_for="Humans sharing a one-off snippet from their own browser.",
        not_ideal_for="Anything an agent produces — because the paste step is the friction.",
        angles=(
            (
                "The paste step is the friction",
                "These are all 'paste text, get URL' products. Their workflow assumes a human copying content out of somewhere, pasting it into a web form, and clicking submit. For anything an agent produces — specs, plans, research summaries, CLAUDE.md files — the paste step is exactly what you want to eliminate. Markland removes it: the agent writes the doc directly through an MCP tool call.",
            ),
            (
                "No sharing model beyond the URL",
                "These tools have one access control: knowing the URL. Markland adds per-principal grants, agent IDs, and single-use invites, so sharing can match the shape of the team and the agents on it.",
            ),
        ),
    ),
)


def get_competitor(slug: str) -> Competitor | None:
    for c in COMPETITORS:
        if c.slug == slug:
            return c
    return None
