---
name: cleanup
description: >
  Ship completed work off a worktree branch — an /implement milestone, or a single /frontier ticket:
  open a PR for the branch (auto-closing the GitHub issues it resolves), poll CI until conclusive
  (never cancel — self-hosted runners can be slow), auto-merge when every check is green and the PR
  is MERGEABLE/CLEAN, then close the emptied GitHub milestone and clean up the worktree + branches
  (UNLESS running inside an Orca terminal, which owns the worktree lifecycle — then teardown is
  skipped). In project-kit repos the milestone's status.json now->shipped bump rides INSIDE the PR
  (no direct push to main), so parallel sessions never race a shared-doc write; repos without
  docs/pm/status.json skip that layer entirely and let `Closes #<n>` do the bookkeeping. Run AFTER a
  successful /implement, or at the end of a /frontier worker's ticket, when the branch's work is
  committed and verified. It ships what's there — it never writes or fixes code; a red CI or required
  review ends the skill with a report, not a patch.
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

**Prefer a fresh (or cleared) session over the tail of a long orchestrator session.** The skill
already runs on the cost tier (`model: sonnet` above), but CI polling is many turns, and every turn
re-reads whatever context the session is carrying. Everything this skill needs is on disk and in
git — the branch, the plan, the milestone — so nothing is lost by `/clear`-ing first or running it
in a cheap child terminal.

## Preconditions
- Run from (or knowing) the **worktree branch being shipped** — an `/implement` milestone branch, or
  a `/frontier` ticket worktree (`ticket-<n>-<slug>`). If `git branch --show-current` is
  `main`/`master`, STOP — there's nothing to ship.
- Work is committed and already green locally (that was `/implement`'s or the ticket worker's job).
  If there are uncommitted changes, commit them with a real message first; if you can't tell they're
  finished, STOP and report rather than guessing.
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
- **Auto-close the issues this ship resolves.** In the PR body, add a `Closes #<n>` line for every
  GitHub issue this PR completes, so the merge closes them automatically — no separate
  `gh issue close` call, and the issues link back to the PR. Don't list issues you only partially
  touched; only ones this ship actually finishes.
  **Resolve `<n>` in this order, first hit wins:**
  1. **The worktree's linked issue** (the `/frontier` ticket path — there is no plan file). Orca
     stores it from `worktree create --issue <n>`:
     `ORCA worktree show --worktree active --json` → the linked GitHub issue number. (`ORCA` = the
     executable resolved per the orca-cli rules; inside an Orca terminal it's `orca`. Skip this
     source if the CLI isn't available — don't treat its absence as an error.)
  2. **The branch / worktree name**, when it carries the ticket — `/frontier` names worktrees
     `ticket-<n>-<slug>`, so parse `<n>` out of `git branch --show-current`.
  3. **The plan / the gate's milestone** (the `/taskplan` → `/implement` path).

  If none resolve, **ask** rather than opening a PR that closes nothing — a ticket left open after
  its work merged is invisible breakage: the next `/frontier` run keeps treating it as a live
  blocker, so everything downstream of it stalls.
- **(project-kit) Fold the `status.json` now→shipped bump into this PR** — do NOT save it for after
  the merge. **Gate this on the file: if `docs/pm/status.json` doesn't exist, skip this bullet
  entirely and say so in one line.** Repos on the `/frontier` ticket flow track state in GitHub
  Issues alone — there's no milestone layer to bump, and the `Closes #<n>` above is the whole
  bookkeeping. Don't scaffold `docs/pm/` to satisfy the step; that's `/project-kit`'s call, not
  a ship-time side effect.
  - **Surgically** edit `docs/pm/status.json` (not a full reserialize): remove the milestone from
    `now`; prepend a `shipped` entry — `date`, `link` = the PR URL you just captured, a one-line
    summary + verification, and `commit` = `""` (the merge SHA isn't known yet and is intentionally
    **not** recorded — the PR link is the durable pointer; recording the merge SHA would force a
    post-merge edit, i.e. exactly the direct push we're eliminating); bump `lastUpdated`. **If this
    ship satisfies a gate's `exitCriteria`, flip that gate's `done: true` here** — a *gate* is a
    `milestones[]` entry carrying the optional `exitCriteria`/`githubMilestone` fields (shape:
    `docs/pm/schema/status.schema.json`); the milestone steps below apply only when those fields are
    present. Its GitHub
    milestone gets closed post-merge (step 5), and the invariant is *a gate is `done` iff its
    `githubMilestone` is closed*, so the two must move together. **Do NOT `trim shipped` here** — trimming rewrites the array tail and is the single biggest cross-session
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
Merge **iff** every check concluded `SUCCESS`, `SKIPPED`, or `NEUTRAL` (paths-filtered repos
routinely skip checks — a skipped check is not a red one), `mergeable=MERGEABLE`, and
`mergeStateStatus=CLEAN`:
`gh pr merge <PR#> --merge` (match the repo's merge style — this repo uses merge commits).

- **STOP and report, do NOT merge, when:**
  - any check `FAILURE`/`ERROR`/`CANCELLED`/`TIMED_OUT` → link the run + name the failing step;
  - `DIRTY`/`CONFLICTING` → rebase onto `main`, resolve, push, and go back to step 2. The conflict
    is now often in `status.json` (another session shipped first): re-apply your now-removal +
    `shipped` prepend on top of their entries, keep both shipped items, re-validate the JSON;
  - `BLOCKED` (required review/approval) → tell the user; it's their gate.
- **Gotcha:** don't pass `--delete-branch`. From inside a worktree it errors
  (`fatal: 'main' is already used by worktree …`). Delete branches in step 4.

### 4. Clean up worktree + branches — SKIP inside an Orca terminal
- **First, the Orca guard.** If `$ORCA_TERMINAL_HANDLE` is set (equivalently `TERM_PROGRAM=Orca`),
  this session is running in an **Orca-managed** terminal/worktree (`ORCA_WORKTREE_ID`). **Orca owns
  the worktree lifecycle — do NOT remove the worktree or delete the local branch here.** Removing it
  out from under Orca breaks the pane. In that case: still delete the **remote** branch
  (`git push origin --delete "$branch"` — it's merged and independent of the local worktree) and clean
  throwaway artifacts, then **report** "worktree + local branch left for Orca to manage" and skip the
  rest of this step. Detect once: `[ -n "$ORCA_TERMINAL_HANDLE" ]`.
- **Otherwise (plain terminal), tear down normally:**
  - Do this **from the main repo dir, never from inside the worktree you're removing** — that dir is
    your cwd, and removing it breaks the shell (you'll get "working directory was deleted").
  - Sync: `git checkout main` (in the main dir) → `git fetch origin main` → `git merge --ff-only origin/main`.
  - Remove the milestone worktree: `git worktree remove --force <path>` → `git worktree prune`.
  - Delete the branch: `git push origin --delete "$branch"` (remote) + `git branch -D "$branch"` (local).
- **Only the milestone's worktree/branch.** `git worktree list` will show **other sessions'**
  worktrees — leave those completely alone.
- Clean any throwaway artifacts this milestone created (e.g. purge thrashed CI caches with
  `gh cache delete`, remove scratch containers), but nothing shared.

### 5. (project-kit) status.json + GitHub milestone — reconcile the two layers
**Skip this whole step when `docs/pm/status.json` doesn't exist** — on the `/frontier` ticket flow
the merge already closed the ticket via `Closes #<n>`, and that's the entire reconciliation. Report
"no project-kit layer — ticket closed by the merge" and you're done.

The `status.json` now→shipped bump merged as part of the milestone PR (step 1) — nothing to push to
`main`. The merge also auto-closed the issues named `Closes #<n>` in the PR body (step 1).
- **Confirm it landed:** on the freshly-synced `main` from step 4, `git log -1 --stat` should show
  `docs/pm/status.json` in the merge, and the milestone should read as `shipped`.
- **(GitHub milestones) Close the milestone when it empties.** After the merge closed this ship's
  issues, check the gate's GitHub milestone:
  `gh api repos/{owner}/{repo}/milestones/<N> --jq '.open_issues'`. If it's `0` and you flipped that
  gate's `done: true` in step 1, close the milestone: `gh api -X PATCH repos/{owner}/{repo}/milestones/<N> -f state=closed`.
  **Enforce the invariant:** a gate is `done` in `status.json` iff its `githubMilestone` is closed —
  if step 1 flipped `done` but open issues remain, that gate is NOT actually done: leave the milestone
  open and report the mismatch rather than force-closing.
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
- **Inside an Orca terminal (`$ORCA_TERMINAL_HANDLE` set), do NOT tear down the worktree/local
  branch** — Orca owns that lifecycle and removing it breaks the pane. Delete only the merged remote
  branch and leave the rest for Orca. Outside Orca, tear down normally.
- **Sync both tracking layers on the ship, and never separately from the merge.** GitHub issues close
  via `Closes #<n>` in the PR body (merge-driven, not a side call); the gate's milestone closes
  post-merge only when it empties; the `status.json` gate `done` flip rides the PR. The invariant —
  a gate is `done` iff its `githubMilestone` is closed — is the reconciliation check, not a suggestion.
- **Report, don't fix** — a red gate or required review ends the skill with a clear status; fixing is
  a separate pass.
