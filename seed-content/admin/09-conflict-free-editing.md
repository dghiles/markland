# Conflict-free editing with `if_version`: how Markland handles concurrent agent updates

When two agents edit the same document at the same time, what happens?

Most tools either pretend it can't (last-write-wins, silently overwriting) or punt to a human ("hey, can you resolve this merge conflict?"). Both are wrong for agents. Last-write-wins corrupts collaboration; human-mediated merges defeat the point of having agents in the loop.

Markland uses optimistic concurrency. Every doc has a monotonic `version` integer; every update must declare which version it's editing; the server rejects writes against stale versions. The agent retries with the current version. No data loss, no human in the loop, no merge UI.

This is the same pattern HTTP `If-Match` headers, ETags, and database `WHERE version = ?` updates use. It's not novel; it just needs to be exposed at the protocol layer where agents can use it.

## The contract

Every doc has `version`, an integer that starts at 1 on publish and increments by 1 on each successful update.

`markland_get(doc_id)` returns the current `version` along with the content. `markland_update(doc_id, content=..., if_version=N)` succeeds *only* if the doc's current version equals N. If someone else updated since you read, your update fails with a `ConflictError` carrying the current version.

The agent's job: read, compute the new content, write with `if_version`. If write fails: read again, recompute against the new content, retry.

```python
# Pseudo-code; actual MCP calls are similar
doc = markland_get(doc_id)
new_content = transform(doc.content)
try:
    markland_update(doc_id, content=new_content, if_version=doc.version)
except ConflictError as e:
    # Someone else wrote between our read and our write
    # e contains the current version; refetch and retry
    doc = markland_get(doc_id)
    new_content = transform(doc.content)
    markland_update(doc_id, content=new_content, if_version=doc.version)
```

In practice, retry loops are bounded — typically once or twice is enough, because real-world contention is low.

## Why this and not OT or CRDTs

Operational transforms (Google Docs) and CRDTs (Figma, Linear) are the "fancier" options for collaborative editing. Both work brilliantly for human-typing-speed, character-by-character edits where the unit of conflict is a keystroke.

For agents, neither is the right primitive:

**OT requires server-side state.** A central server tracks every operation and transforms incoming ones. The complexity is paid every edit. The benefit — invisible character-level merging — only matters if both editors are typing in real time. Agents don't type; they generate content in bursts. The OT machinery has nothing to merge against.

**CRDTs are merge-free but write-heavy.** Every edit emits a CRDT operation that has to propagate. The data structure grows with edit history. For document editing where most edits are "rewrite this section," the CRDT is solving a problem (per-character merges) the agent doesn't have.

**Optimistic concurrency is the right granularity.** The unit of conflict is "the document at version N." Agents either succeed atomically or retry. The complexity is one integer column and one comparison. No server-side OT engine, no CRDT log, no UI to render mid-merge state.

## What `if_version` rules out

- **Silent overwrites.** Agent A reads version 3, agent B reads version 3, both write. Without `if_version`, the second write wins and the first edit vanishes. With `if_version`, the second write fails — A's edit is preserved, B retries against version 4.
- **Stale-data acting.** An agent that fetched a doc 10 minutes ago and is about to act on its content can use `if_version` as an "is this still current?" check. If the doc has moved on, the agent re-reads before writing.
- **Coordinating across agents.** Two agents that need to take turns can each do `read → compute → write with if_version` and let the conflict-retry loop serialize them. No external lock needed.

## What it doesn't solve

`if_version` protects against *write conflicts*. It does not protect against *semantic conflicts*. Two agents that both compute "rewrite this paragraph" against version 3 will both succeed in turn (with one retry), but the final state has only one of the two rewrites — whichever wrote second.

For semantic conflicts, the answer is the same as it is in code: split the work. If two agents are both editing the same paragraph, they should be editing different documents, or one should be reviewing the other's output. The conflict-resolution model is human/agent judgment, not a merge algorithm.

This is intentional. Trying to merge "agent A's rewrite of paragraph 3" with "agent B's rewrite of paragraph 3" would require either AI-mediated merging (currently unreliable) or character-level merge tooling (the wrong granularity for agent edits). Markland steps back from both.

## What this means for agent design

Three guidelines for agents writing to Markland:

1. **Always pass `if_version` you read in the same logical operation.** Don't cache versions across tool calls — the version you read 30 seconds ago might be stale.

2. **Catch the conflict, refetch, retry once or twice.** Don't infinite-retry. If you keep losing the race, log it and back off — there's likely a human or another agent making concurrent edits, and you should let them finish.

3. **Treat the doc as the source of truth, not your local content variable.** When you retry, recompute the new content from the freshly-fetched version. Don't assume your local copy is current.

For most agent workloads, this looks like:

```
def update_doc(doc_id, transformer, max_retries=3):
    for _ in range(max_retries):
        doc = markland_get(doc_id)
        new_content = transformer(doc.content)
        try:
            return markland_update(doc_id, content=new_content, if_version=doc.version)
        except ConflictError:
            continue
    raise RuntimeError("update_doc: too many conflicts")
```

That's the entire concurrency-handling code. Two retries usually suffice.

## Compared to filesystem editing

For agents that today write to the local filesystem and then commit to Git, the equivalent loop is:

```
git pull
edit_file
git commit
git push  # may fail if remote moved
git pull --rebase
git push  # retry
```

`if_version` collapses this into a one-tool-call loop, with no branch management and no merge resolution. The mental model is the same — read, edit, write with concurrency check — but the surface area is one tool, not five commands.

## Compared to chat-based editing

For agents that today route output through a chat surface ("here's the new version, what do you think?"), there's no concurrency model at all — the human is the merge layer. That works at small scale and breaks the moment you have multiple agents producing output that needs to converge into a single artifact.

`if_version` makes "multiple agents producing output that converges into a single artifact" a thing that works without human mediation.

## In summary

The full set of concurrency primitives Markland exposes:

| Primitive | Purpose |
|---|---|
| `version: int` on every doc | Monotonic update counter |
| `if_version` parameter on `markland_update` | Optimistic concurrency check |
| `ConflictError` with current version | Signal to refetch and retry |
| `markland_revisions(doc_id)` | Pre-update snapshots (forensic, not active concurrency) |

Three of those are exposed at the protocol layer. Agents that want to play nicely with concurrent editors only need to honor `if_version`.

That's the whole pattern. Read, transform, write with version, retry on conflict. It composes cleanly across agents, across sessions, and across humans-and-agents in the same doc.
