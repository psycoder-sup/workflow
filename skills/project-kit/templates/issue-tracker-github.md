# Issue tracker: GitHub

Issues, specs, and tickets for this repo live as GitHub issues. Use the `gh` CLI (≥ 2.94 — the
native sub-issue and dependency flags landed there) for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc or `--body-file`
  for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments` (a triaged issue carries its contract in an
  agent-brief comment, not the body).
- **List issues**: `gh issue list --state open --json number,title,body,labels,assignees,parent,blockedBy,blocking`
  with `--label` / `--state` filters as needed.
- **Comment**: `gh issue comment <number> --body "..."`
- **Label**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`
- Repo inferred from `git remote -v` — `gh` does this automatically inside a clone.

## Hierarchy and dependencies (the pipeline's substrate)

- **Spec = parent issue**, labeled `spec` (published by `/spec`). The issue body IS the spec.
- **Ticket = sub-issue** of its parent (published by `/taskplan`):
  `gh issue create --parent <parent> ...`; re-parent with `gh issue edit --set-parent`.
  List a parent's children via `--json parent` filtering, or
  `gh api repos/{owner}/{repo}/issues/<parent>/sub_issues`.
- **Blocking edges = native issue dependencies**: `gh issue create --blocked-by <m>` /
  `gh issue edit <n> --add-blocked-by <m>`. Read with `--json blockedBy,blocking`. A ticket is
  unblocked when every blocker is closed (during an `/implement` walk, "landed on the integration
  branch" substitutes — see that skill).
  Sibling parent issues may block each other too (ship ordering from a `/spec` split).
- **Progress**: the parent shows `x of y` sub-issue completion natively
  (`--json subIssues,subIssuesSummary`). Closing all sub-issues does **NOT** auto-close the parent —
  `/cleanup` closes it after the merge.
- **Claim**: `gh issue edit <n> --add-assignee @me` — the assignee is the lock.
- Limits: 100 sub-issues per parent, 50 blocked-by links per issue, one parent per sub-issue.

## Pull requests as a triage surface

**PRs as a request surface: {{PRS_AS_REQUESTS}}.** _(Set to `yes` if this repo treats external PRs
as feature requests; `/triage` reads this flag.)_

When `yes`, PRs run through the same labels and states as issues, using `gh pr` equivalents
(`gh pr view/diff/comment/edit/close`). List external PRs by keeping `authorAssociation` in
(`CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, `NONE`). GitHub shares one number space across issues and
PRs — resolve a bare `#42` with `gh pr view 42`, falling back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.
