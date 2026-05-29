# CLAUDE.md — Markland

Project memory for Claude Code. Read at every session start.

The multi-agent / multi-tool guidance (Codex, etc.) lives in `AGENTS.md`.
CLAUDE.md is the Claude-Code-specific lens on top of that. When the two
conflict, AGENTS.md is the source of truth for repo-wide setup; CLAUDE.md
is the source of truth for "how Claude Code specifically should operate
in this repo."

---

## TL;DR — the deploy flow

| Change type | Path | Deploy gesture |
|---|---|---|
| Code (`src/`, `tests/`, `pyproject.toml`, `fly.toml`, hooks, templates) | **Worktree → branch → PR → squash-merge** | PR merge auto-deploys via CI |
| Blog posts (`src/markland/web/content/blog/*.md`) | **Worktree → branch → PR → squash-merge** | PR merge auto-deploys (the SEO-contract tests are the review gate) |
| Docs-only (`docs/`, `seed-content/`, `.beads/issues.jsonl`, top-level `README.md`) | **Commit on `main` + `git push origin main`** | Push auto-deploys |

**Code never goes through `main` directly.** The merge IS the deploy
gesture. No `flyctl deploy` from a Claude Code session under normal
operation — CI handles it on push.

Manual deploys are rare and reserved for runbook tasks:
```bash
flyctl deploy --remote-only --strategy immediate
```

---

## Worktree-centric is the rule, not the exception

The primary worktree at `/Users/daveyhiles/Developer/markland` stays on
`main` permanently. Every feature, fix, test, or template change starts
with:

```bash
git worktree add .worktrees/<slug> -b feat/<slug>
cd .worktrees/<slug>
# work, commit, push, open PR from here
gh pr create --fill
# squash-merge from GitHub UI or:
gh pr merge --squash --delete-branch
```

Then back in primary:
```bash
git pull --ff-only
git worktree remove .worktrees/<slug>
```

**Never** run `git checkout -b feat/<slug>` in the primary worktree.
Parallel Claude Code sessions share that worktree; mutating its HEAD
makes the next session inherit the wrong branch.

The pre-commit hook (`scripts/git-hooks/pre-commit`) refuses non-main
commits in primary. The post-checkout hook
(`scripts/git-hooks/post-checkout`) warns when primary's HEAD moves off
main. Install both per `AGENTS.md` § "One-time setup".

Bypass exists for genuine emergencies:
`BYPASS_BRANCH_CHECK=1 git commit ...` — but the right answer when you
hit this is almost always "make a worktree."

---

## Multi-agent dispatch (Agent View)

Open Agent View by pressing `←` on an empty prompt (Claude Code
v2.1.139+). This is how you parallelize tracks.

**One agent per worktree per roadmap track.** The current candidate
batch lives at `docs/plans/2026-05-29-pre-launch-cleanup.md` (8 tracks).
Each track entry in `docs/ROADMAP.md` carries its plan link + dependency
notes.

**Recommended dispatch prompt shape:**

> Execute [Pre-launch X] per `docs/plans/2026-05-29-pre-launch-cleanup.md`
> (Track X). Use `superpowers:subagent-driven-development` to execute
> task by task. Create a new worktree at `.worktrees/pre-launch-X`,
> commit + push + open a PR from there. Do not work in the primary
> worktree.

The dispatched agent should:
1. Verify it's in a worktree before any mutation (`git rev-parse --show-toplevel` should not equal the primary path).
2. Run the plan tasks task-by-task with frequent commits.
3. Open the PR when the plan's Task N (close-out) marks itself done.
4. Leave the worktree on the branch — primary's cleanup is the human's job.

---

## What ships through `main` directly

Only **docs and beads state**:
- `docs/**` — roadmap, plans, specs, audits, runbooks, launch artifacts
- `seed-content/**` — admin-published explainers, agent-published demos
- `.beads/issues.jsonl` — beads sync state
- `README.md` (top-level) — when it's a pure docs update

Everything else — `src/`, `tests/`, `pyproject.toml`, hooks, `fly.toml`,
templates, blog posts — goes through the worktree → PR flow even when
it's "just a one-line change." The cost of consistency is lower than
the cost of "this one was small so I direct-pushed" sliding into "all
of them were small so I direct-pushed."

---

## Session close

Per `AGENTS.md` § "Landing the Plane":
1. `git status` — confirm clean
2. `git pull --rebase` — sync (if anything was pushed during the session)
3. `bd sync` — push beads state
4. `git push` — if anything is committed locally
5. For worktree work: confirm the PR is open and CI is green; the
   merge can happen async, but the PR existing is "shipped" for
   handoff purposes.

**Never** stop before pushing. Stranded local commits are the most
common form of work loss between sessions.

---

## Beads

This repo uses `bd` for follow-ups; prefix `markland-*`. JSONL is
committed (part of the docs-only push path); SQLite is gitignored.

- `bd prime` after compaction or new session — auto-called by hook
- `bd ready` to find unblocked work
- `bd sync` at session end

---

## Reference

- **`AGENTS.md`** — hook install, multi-tool worktree discipline,
  blog-content workflow, Landing-the-Plane checklist
- **`docs/ROADMAP.md`** — current Now/Next/Later (the working surface)
- **`docs/plans/`** — implementation plans (executable, task-by-task)
- **`docs/specs/`** — design specs (input to plans, output of brainstorming)
- **`docs/runbooks/`** — operator procedures (metrics-review, admin-ops,
  first-deploy, etc.)
- **`docs/audits/`** — point-in-time analyses (SEO strategy, GEO,
  security review)
- Auto-memory at
  `~/.claude/projects/-Users-daveyhiles-Developer-markland/memory/`
  — project/user/feedback/reference entries indexed by `MEMORY.md`

---

## Anti-patterns

- ❌ **Committing code on `main` in the primary worktree.** Pre-commit
  hook will reject; that's working as intended. Make a worktree.
- ❌ **Using `BYPASS_BRANCH_CHECK=1` for code changes.** It exists for
  genuine emergencies. If you're using it routinely, the worktree
  pattern wasn't followed; back out and do it right.
- ❌ **Running `flyctl deploy` from a Claude Code session for code
  changes.** CI deploys on merge; manual deploys belong in runbook
  contexts only.
- ❌ **"This is a tiny one-line fix, I'll just push it."** The next
  tiny one-line fix is also tiny. The discipline is the value.
- ❌ **Working in the primary worktree after another session left it
  on a feature branch.** Always check `git branch --show-current` is
  `main` before any commit gesture. The post-checkout hook surfaces
  this on entry; the pre-commit hook catches it on commit.
