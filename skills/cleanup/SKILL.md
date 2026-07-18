---
name: cleanup
description: >
  Ship a completed /implement milestone: open a PR for the worktree branch, poll CI until
  conclusive (never cancel — self-hosted runners can be slow), auto-merge when every check is green
  and the PR is MERGEABLE/CLEAN, then clean up the worktree + branches. In project-kit repos the
  milestone's status.json now->shipped bump rides INSIDE the milestone PR (no direct push to main),
  so parallel sessions never race a shared-doc write. Run AFTER a successful
  /implement when the branch's work is committed and verified. It ships what's there — it never
  writes or fixes code; a red CI or required review ends the skill with a report, not a patch.
trigger: /cleanup
user-invocable: true
argument-hint: "[branch or PR-title override] — usually none; infers the current worktree branch"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "AskUserQuestion"]
# Cleanup is mechanical (PR → poll CI → merge on green → clean up) and never writes/fixes code,
# so it runs on the cost tier. The only judgment-heavy path is shared-doc conflict resolution
# during rebase (status.json / ADR renumber); escalate that manually if it gets hairy.
model: sonnet
---

# /cleanup

The tail end of an `/implement` run, automated: **PR (with the project-kit status.json now→shipped
bump folded in) → poll CI → auto-merge on green → clean up**. You are the orchestrator finishing a milestone whose code
is already written, committed, and locally verified. **You do not write or fix implementation code
here.** If CI goes red or a review is required, you STOP and report — remediation is a fresh
`/implement` or a manual pass.

## When to use
Right after a successful `/implement`: the milestone branch lives in a dedicated worktree, its
build/tests are green locally, and you're ready to ship it to `main`. Not for unverified work.

## Preconditions
- Run from (or knowing) the **milestone worktree branch**. If `git branch --show-current` is
  `main`/`master`, STOP — there's nothing to ship.
- Work is committed and already green locally (that was `/implement`'s job). If there are
  uncommitted changes, commit them with a real message first; if you can't tell they're finished,
  STOP and report rather than guessing.
- **Everything lands via the PR — no direct pushes to `main`, not even docs.** `main` is protected,
  and (learned the hard way) direct-pushing `status.json` from N parallel sessions turns one file
  into a multi-writer hotspot that conflicts on nearly every concurrent ship — `lastUpdated`,
  `shipped[0]`, and the `trim`-rewritten tail are lines *every* session touches, so git's line merge
  can't reconcile them. The `status.json` now→shipped bump therefore rides **inside the milestone
  PR** (step 1), so `main` is only ever mutated by a merge.

## Workflow

### 1. Rebase, push, open PR — with the status bump *inside* the PR
- `branch=$(git branch --show-current)` — the milestone branch. Abort if it's the default branch.
- Commit anything pending (real message; end with the repo's commit footer convention if it has one).
- **Rebase onto the latest default branch first** — parallel sessions may have advanced it, and this
  is the #1 source of a PR opening as CONFLICTING:
  `git fetch origin main && git rebase origin/main`.
  Resolve conflicts — most often **shared-docs collisions**: two ADRs grabbing the same number, or a
  decisions `README.md` / `status.json` both edited. If your ADR number was taken, renumber to the
  next free one and fix every reference (file name, `"number"`, index row, code comments, status).
  **This rebase is now the *single* reconciliation point for `status.json` too** (see the fold-in
  bullet below) — there is no later direct push to `main` to race.
- Push the code: `git push -u origin "$branch"` (add `--force-with-lease` if you rebased).
- `gh pr create --base main --head "$branch" --title "…" --body-file …` — body = what shipped + how
  it was verified; end with the repo's PR footer convention. **Capture the PR number AND URL.**
- **(project-kit) Fold the `status.json` now→shipped bump into this PR** — do NOT save it for after
  the merge:
  - **Surgically** edit `docs/pm/status.json` (not a full reserialize): remove the milestone from
    `now`; prepend a `shipped` entry — `date`, `link` = the PR URL you just captured, a one-line
    summary + verification, and `commit` = `""` (the merge SHA isn't known yet and is intentionally
    **not** recorded — the PR link is the durable pointer; recording the merge SHA would force a
    post-merge edit, i.e. exactly the direct push we're eliminating); bump `lastUpdated`. **Do NOT
    `trim shipped` here** — trimming rewrites the array tail and is the single biggest cross-session
    collision; leave it to an occasional single-writer chore (step 5). Validate:
    `python3 -c "import json;json.load(open('docs/pm/status.json'))"`.
  - Commit it (`docs(status): ship <milestone>`) and `git push` onto the **same branch** so it rides
    this PR. `main` is now only ever mutated by the eventual merge.
- If a *later* session merges its own `status.json` before yours lands, your PR flips to
  DIRTY/CONFLICTING — step 3 handles it (rebase, resolve, push, re-poll). That resolve is the same
  reconciliation point, just triggered late; there is never a concurrent direct write to `main` to race.

### 2. Poll CI — never cancel
Poll until **every check is conclusive** (no PENDING/IN_PROGRESS/QUEUED) **and** the PR head ==
your **latest** pushed SHA — that's the `status.json` commit if you added one in step 1, not the code
push. Use the bundled poller in the background so you're notified on completion:

```
python3 ${CLAUDE_PLUGIN_ROOT}/skills/cleanup/pollci.py <PR#> <pushed-sha7>
```
(run it with `run_in_background: true`; it exits 0 when conclusive, 2 on timeout.)

- **Slow ≠ hung.** Self-hosted runners can sit `in_progress` for many minutes (slow `setup-node`,
  queueing). Do NOT cancel — cancelling + rerunning just re-hits the same slow step. Let it finish.
- Right after a push, GitHub briefly reports a **stale head / `mergeable=UNKNOWN`** — keep polling
  until `headRefOid` matches your SHA.
- A **paths-filtered** PR (e.g. docs-only) may register **zero checks** — the poller treats
  "head matches + no checks after a short grace" as conclusive.

### 3. Merge when green (automatic)
Merge **iff** every check is `SUCCESS`, `mergeable=MERGEABLE`, and `mergeStateStatus=CLEAN`:
`gh pr merge <PR#> --merge` (match the repo's merge style — this repo uses merge commits).

- **STOP and report, do NOT merge, when:**
  - any check `FAILURE` → link the run + name the failing step;
  - `DIRTY`/`CONFLICTING` → rebase onto `main`, resolve, push, and go back to step 2. The conflict
    is now often in `status.json` (another session shipped first): re-apply your now-removal +
    `shipped` prepend on top of their entries, keep both shipped items, re-validate the JSON;
  - `BLOCKED` (required review/approval) → tell the user; it's their gate.
- **Gotcha:** don't pass `--delete-branch`. From inside a worktree it errors
  (`fatal: 'main' is already used by worktree …`). Delete branches in step 4.

### 4. Clean up worktree + branches
- Do this **from the main repo dir, never from inside the worktree you're removing** — that dir is
  your cwd, and removing it breaks the shell (you'll get "working directory was deleted").
- Sync: `git checkout main` (in the main dir) → `git fetch origin main` → `git merge --ff-only origin/main`.
- Remove the milestone worktree: `git worktree remove --force <path>` → `git worktree prune`.
- Delete the branch: `git push origin --delete "$branch"` (remote) + `git branch -D "$branch"` (local).
- **Only the milestone's worktree/branch.** `git worktree list` will show **other sessions'**
  worktrees — leave those completely alone.
- Clean any throwaway artifacts this milestone created (e.g. purge thrashed CI caches with
  `gh cache delete`, remove scratch containers), but nothing shared.

### 5. (project-kit) status.json — already shipped inside the PR
Nothing to push to `main`. The `status.json` now→shipped bump merged as part of the milestone PR
(step 1) — that's the whole point of folding it in, so N parallel sessions never race a direct write.
- **Confirm it landed:** on the freshly-synced `main` from step 4, `git log -1 --stat` should show
  `docs/pm/status.json` in the merge, and the milestone should read as `shipped`.
- **Housekeeping is a separate single-writer chore, never part of a concurrent ship.** Trimming
  `shipped` to the latest ~3 and tidying `next` rewrites shared array regions — exactly the edits
  that conflict across sessions. Do them deliberately from **one** session when nothing else is
  shipping (a quick `docs(status): trim shipped log` commit + PR, or a direct push at a quiet moment),
  not on every milestone.

## Constraints & lessons (from real runs)
- **Everything lands via the PR — even docs; there is no direct push to `main`.** The `status.json`
  now→shipped bump rides inside the milestone PR (step 1), so `main` is only ever mutated by a merge
  and N parallel sessions never race a direct write. (This replaced an earlier design that pushed the
  bump straight to `main` — it conflicted on `lastUpdated` / `shipped[0]` / the `trim`-rewritten tail
  on nearly every concurrent ship, because git merges those shared lines line-by-line with no idea
  they're JSON.)
- **Parallel sessions churn shared docs** (ADR numbers, decisions README, status.json). Rebase right
  before pushing; resolve number/index collisions; expect to re-rebase if `main` moves again before
  the merge lands. `status.json` is one of those shared docs now — but because it rides the PR, its
  only collision point is that same rebase / DIRTY-resolve, **not** a separate post-merge push.
- **Never `trim shipped` on the concurrent ship path** — rewriting the array tail is the biggest
  cross-session collision. Trim as a deliberate single-writer chore (step 5).
- **Slow ≠ hung** on self-hosted runners — poll, don't cancel.
- **Clean up from the parent dir; never delete sibling worktrees.**
- **Report, don't fix** — a red gate or required review ends the skill with a clear status; fixing is
  a separate pass.
