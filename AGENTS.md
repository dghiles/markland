# Agent setup

Guidance for Claude Code, Codex, and other agents working in this repo.

## One-time setup

Activate the pre-commit hook (refuses commits on non-main branches in the
primary worktree, see `scripts/git-hooks/pre-commit` for details):

```bash
ln -s ../../scripts/git-hooks/pre-commit .git/hooks/pre-commit
```

## Worktree discipline

The primary worktree at `/Users/daveyhiles/Developer/markland` stays on
`main`. **Do feature work in an isolated worktree:**

```bash
git worktree add .worktrees/<name> -b feat/<name>
cd .worktrees/<name>
# ... commit, push, open PR from here ...
```

**Never** run `git checkout -b feat/<name>` in the primary worktree. Parallel
agent sessions share that worktree; mutating its HEAD causes the next session
to inherit the wrong branch and accidentally commit feature work to whatever
branch happens to be checked out.

If you must commit something on a non-main branch from the primary worktree
(rare — usually means you should have made a worktree), bypass the hook
explicitly: `BYPASS_BRANCH_CHECK=1 git commit ...`.

## Docs-only direct push

For diffs that touch only `docs/` (or other plain markdown), commit on `main`
and `git push origin main` — no PR needed. The PR flow is overhead for
content that doesn't need code review. Code changes still go through the
branch + PR flow.
