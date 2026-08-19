---
name: cleanup
description: >
  Ship completed work off a worktree branch — an /implement campaign branch (whose already-open PR
  is adopted, never recreated) or a single-issue build: open a PR for the branch (auto-closing the
  GitHub sub-issues it resolves via Closes lines), poll CI until conclusive (never cancel —
  self-hosted runners can be slow), auto-merge when every check is green and the PR is
  MERGEABLE/CLEAN, then CLOSE THE PARENT ISSUE when its sub-issue summary reads completed == total
  (GitHub never auto-closes parents), and clean up the worktree + branches (UNLESS running inside an
  Orca terminal, which owns the worktree lifecycle — then teardown is skipped). GitHub Issues are
  the only bookkeeping layer — no status.json, no milestones. Run AFTER a successful /implement,
  when the branch's work is committed and verified. It ships what's there — it never writes or
  fixes code; a red CI or required review ends the skill with a report, not a patch.
trigger: /cleanup
user-invocable: true
argument-hint: "[branch or PR-title override] — usually none; infers the current worktree branch"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "AskUserQuestion"]
# Cleanup is mechanical (PR → poll CI → merge on green → close parent → clean up) and never
# writes/fixes code, so it runs on the cost tier.
model: sonnet
---

# /cleanup

The tail end of an `/implement` run, automated: **PR → poll CI → auto-merge on green → close the
parent → clean up**. You are shipping a branch whose code is already written, committed, and locally
verified. **You do not write or fix implementation code here.** If CI goes red or a review is
required, you STOP and report — remediation is a fresh `/implement` pass or a manual one.

## When to use

Right after a successful `/implement`: the branch lives in a dedicated worktree, its build/tests are
green locally, and you're ready to ship it to `main`. Not for unverified work.

**Prefer a fresh (or cleared) session over the tail of a long orchestrator session.** CI polling is
many turns, and every turn re-reads whatever the session carries. Everything this skill needs is on
disk and in GitHub — the branch, the trailers, the issue graph.

## Preconditions

- Run from (or knowing) the **worktree branch being shipped**. If `git branch --show-current` is
  `main`/`master`, STOP — there's nothing to ship.
- Work is committed and already green locally (that was `/implement`'s job). Uncommitted changes →
  commit them with a real message if they're clearly finished; if you can't tell, STOP and report.
- **Everything lands via the PR — no direct pushes to `main`, not even docs.** `main` is only ever
  mutated by a merge.

## Workflow

### 1. Rebase, push, open or adopt the PR

- `branch=$(git branch --show-current)`. Abort if it's the default branch.
- **Rebase onto the latest default branch first** — parallel sessions may have advanced it, and this
  is the #1 source of a PR opening as CONFLICTING:
  `git fetch origin main && git rebase origin/main`.
  Resolve conflicts — most often **shared-docs collisions**: two ADRs grabbing the same number, or
  both sides touching `CONTEXT.md`. If your ADR number was taken, renumber to the next free one and
  fix every reference (file name, index rows, code comments).
- Push: `git push -u origin "$branch"` (add `--force-with-lease` if you rebased).
- **Adopt an existing PR if one is already open for this branch** —
  `gh pr list --head "$branch" --state open --json number,url`. A hit means `/implement` already
  composed and opened it (its body carries the per-ticket summary and one `Closes #<n>` per child —
  knowledge this skill can't reconstruct): **skip creation, keep its body untouched**, capture its
  number + URL, and go to step 2. No hit → create it:
- `gh pr create --base main --head "$branch" --title "…" --body-file …` — body = what shipped + how
  it was verified; end with the repo's PR footer convention. **Capture the PR number AND URL.**
- **Auto-close the issues this ship resolves.** Add a `Closes #<n>` line for every issue this PR
  completes. Resolve `<n>` in this order, first hit wins:
  1. **The Orca worktree's linked issue** (`ORCA worktree show --worktree active --json` — skip this
     source silently if the CLI isn't available).
  2. **The branch's `Ticket: #<n>` trailers**: `git log origin/main..HEAD --format=%B | grep '^Ticket: #' | sort -u`
     — one `Closes` line per distinct ticket.
  3. **The branch / worktree name**, when it carries an issue number.

  If none resolve, **ask** rather than opening a PR that closes nothing — an issue left open after
  its work merged is invisible breakage: it stays a live blocker for everything downstream of it.
- **Never `Closes #<parent>`.** The parent closes in step 5, after the merge proves the children
  closed.

### 2. Poll CI — never cancel

Poll until **every check is conclusive** (no PENDING/IN_PROGRESS/QUEUED) **and** the PR head ==
your latest pushed SHA. Use the bundled poller in the background so you're notified on completion:

```
python3 ${CLAUDE_PLUGIN_ROOT}/skills/cleanup/pollci.py <PR#> <pushed-sha7>
```

(run with `run_in_background: true`; it exits 0 when conclusive, 2 on timeout.)

- **Slow ≠ hung.** Self-hosted runners can sit `in_progress` for many minutes. Do NOT cancel —
  cancelling + rerunning just re-hits the same slow step.
- Right after a push, GitHub briefly reports a **stale head / `mergeable=UNKNOWN`** — keep polling
  until `headRefOid` matches your SHA.
- A **paths-filtered** PR (e.g. docs-only) may register **zero checks** — the poller treats "head
  matches + no checks after a short grace" as conclusive.

### 3. Merge when green (automatic)

Merge **iff** every check concluded `SUCCESS`, `SKIPPED`, or `NEUTRAL` (a skipped check is not a red
one), `mergeable=MERGEABLE`, and `mergeStateStatus=CLEAN`:
`gh pr merge <PR#> --merge` (match the repo's merge style).

- **STOP and report, do NOT merge, when:**
  - any check `FAILURE`/`ERROR`/`CANCELLED`/`TIMED_OUT` → link the run + name the failing step;
  - `DIRTY`/`CONFLICTING` → rebase onto `main`, resolve, push, and go back to step 2;
  - `BLOCKED` (required review/approval) → tell the user; it's their gate.
- **Gotcha:** don't pass `--delete-branch`. From inside a worktree it errors
  (`fatal: 'main' is already used by worktree …`). Delete branches in step 4.

### 4. Clean up worktree + branches — SKIP inside an Orca terminal

- **First, the Orca guard.** If `$ORCA_TERMINAL_HANDLE` is set (equivalently `TERM_PROGRAM=Orca`),
  this session runs in an **Orca-managed** terminal/worktree. **Orca owns the worktree lifecycle —
  do NOT remove the worktree or delete the local branch here.** Still delete the **remote** branch
  (`git push origin --delete "$branch"`), then report "worktree + local branch left for Orca to
  manage" and skip the rest of this step.
- **Otherwise, tear down normally:**
  - From the main repo dir, **never from inside the worktree you're removing** (removing your cwd
    breaks the shell).
  - Sync: `git checkout main` → `git fetch origin main` → `git merge --ff-only origin/main`.
  - Remove the worktree: `git worktree remove --force <path>` → `git worktree prune`.
  - Delete the branch: `git push origin --delete "$branch"` + `git branch -D "$branch"`.
- **Only this ship's worktree/branch.** `git worktree list` shows other sessions' worktrees — leave
  them completely alone.

### 5. Close the parent issue — GitHub never does it for you

The merge auto-closed the children named in the `Closes #<n>` lines. Now reconcile the parent:

- Find it: `gh issue view <any-closed-child> --json parent` (or the `Parent: #<n>` line in the PR
  body).
- Check completion: `gh issue view <parent> --json subIssuesSummary` — community reports say the
  summary can lag; when in doubt, list the children (`--json subIssues`) and count open states
  yourself.
- **`completed == total`** → close it with a pointer:
  `gh issue close <parent> --comment "All sub-issues shipped in <PR URL>."`
- **Open children remain** → the parent is NOT done: leave it open and report which children remain
  (they may belong to a later `/implement` resume, or a child was never landed — say which it looks
  like).
- A standalone issue (no parent) → nothing to reconcile; the `Closes` line was the whole
  bookkeeping.

## Constraints & lessons (from real runs)

- **Everything lands via the PR — no direct push to `main`.**
- **Parallel sessions churn shared docs** (`CONTEXT.md`, ADR numbers). Rebase right before pushing;
  resolve number collisions; expect to re-rebase if `main` moves again before the merge lands.
- **Slow ≠ hung** on self-hosted runners — poll, don't cancel.
- **Clean up from the parent dir; never delete sibling worktrees.**
- **Inside an Orca terminal, do NOT tear down the worktree/local branch** — delete only the merged
  remote branch.
- **Children close at merge time via `Closes` lines; the parent closes here, explicitly, after.**
  Never close children by hand, and never close a parent with open children.
- **Report, don't fix** — a red gate or required review ends the skill with a clear status.
