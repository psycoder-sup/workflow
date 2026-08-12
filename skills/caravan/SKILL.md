---
name: caravan
description: >
  Work a parent issue's dependency-linked child tickets serially on ONE integration branch, one
  fresh code-implementer per ticket, landing each verified slice as a commit — then ship a single
  PR that closes every child. The single-PR counterpart to /frontier: frontier parallelises wide
  graphs into per-ticket worktrees and PRs; caravan walks mostly-linear graphs in one worktree.
  Use after /to-tickets when the graph is a chain, or when tickets are too small for solo PRs.
trigger: /caravan
user-invocable: true
argument-hint: "<parent issue number, e.g. 234> [--dry-run]"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent", "AskUserQuestion", "TaskCreate", "TaskUpdate", "EnterWorktree", "Skill"]
---

# /caravan

Walk a parent issue's ticket set **in dependency order, on one integration branch, toward one PR**.

This is the second execution half of the ticket flow: `/grill-with-docs` → `/to-spec` →
`/to-tickets` publish a dependency-linked ticket set to GitHub Issues; then either `/frontier`
fans it out or **`/caravan` walks it**. Same ticket set, same guards, opposite shape:

| Shape | Route |
| --- | --- |
| Deep + coupled, **wide** graph — 3+ tickets independently unblocked, per-ticket review wanted | `/to-tickets` → `/frontier` → N worktrees, N PRs |
| Deep + coupled, **mostly-linear** graph — width 1–2, or tickets too small for solo PRs | `/to-tickets` → **`/caravan`** → one branch, one PR |
| Broad + shallow — same change × many files (12 endpoints, 30 components) | skip `/to-tickets` → `/taskplan` → `/implement` waves |

The litmus is the graph `/to-tickets` already drew. Frontier's payoff is width; when most of the
graph is width 1–2, its per-ticket ceremony — a worktree, a PR, a merge, and a `/frontier` re-run
per ticket — is pure cost, and a ticket's dependencies clear only at PR-merge speed. Caravan clears
them at commit speed: ticket #4 starts the moment #3's slice lands on the integration branch.

Workers as visible Orca terminal sessions instead of in-process subagents → **`/caravan-orca`**
(same doctrine, Orca transport).

## Why the `W == 1` gate does not stop this skill

`/implement` hard-STOPs on serial work (`W == 1`), and caravan is serial by design — so state the
difference, because it is the difference. `/implement`'s gate exists because its per-*task* overhead
(brief, report, integrate round-trip) dwarfs a small task: a measured **4.5× median orchestrator tax
below 6 agents**. Caravan's unit is the **ticket** — a vertical slice `/to-tickets` sized "to fit a
single fresh context window". One brief, one report, and one integrate pass per *context window of
work* is small overhead, and the thing bought is not parallelism at all: it is **fresh context per
slice plus one PR**.

The alternative — one giant worker building the whole feature — is exactly what `/to-tickets` sliced
to avoid: a feature is several context windows of work, and a single session degrades as it fills.
The chain-collapse rule ("collapse linear chains into one brief") stops at the ticket boundary for
the same reason: a chain of *tasks* fits one context window; a chain of *tickets* by definition does
not.

## Anti-freelance rule (the one rule that makes this work)

**You do not write or edit implementation code. Ever.** Not for the first ticket, not for a "just
one-line" fix found during verification, not for review findings. All code changes go through a
`code-implementer`. Your Write/Edit access is only for orchestration artifacts — never source files.
You *do* run commands: build, test, and **git** — committing, pushing, and landing verified slices
is orchestration, not coding.

## Step 0 — Resolve the scope (same guards as `/frontier`)

**`/caravan` is scoped to one parent issue.** It does not sweep the repo.

- **Argument given** (`/caravan 234`) → that's the parent.
- **No argument** → find candidate parents (open agent-ready issues that other open issues name as
  their `## Parent`) and **ask**. Never default to repo-wide.

Resolve children and takeability exactly as `/frontier` Steps 1–2 do — same commands, same caveats:

- Children = issues whose body carries a `## Parent` section naming the scope issue; prefer native
  sub-issues (`gh api repos/{owner}/{repo}/issues/<parent>/sub_issues`) when present. Say which you
  used.
- **Resolve the agent-ready label** from `docs/agents/triage-labels.md` (the `ready-for-agent` row's
  right-hand column); fall back to the literal `ready-for-agent` if the file is absent. Name the
  label you resolved.
- Blocked-state from `gh api repos/<owner>/<repo>/issues/<n> --jq '.issue_dependencies_summary'` —
  remember **`null` is not `0`**: `null` means no dependency data, so fall through to parsing the
  ticket body's `Blocked by:` line. Say which method you used.

And the two hard refusals, verbatim from frontier because they guard the same failure:

> **Never dispatch the parent.** Exclude the scope issue itself, always.
>
> **An issue whose body has no `## Acceptance criteria` section is not a ticket.** Refuse it and say
> why. A `/to-tickets` ticket always has them; a `/to-spec` spec never does — and `/to-spec` labels
> the spec `ready-for-agent` too, so the label alone cannot tell a whole feature from one slice.

A child that is open, agent-ready, carrying acceptance criteria, and **either unassigned or already
assigned to you** is part of the caravan. A child assigned to *someone else* means another session
holds part of this parent — **stop and report**; a caravan cannot share its parent with another
worker, because its blockers clear on the integration branch, not on GitHub.

**On `--dry-run`:** after computing the walk order and tier routing (Step 2's table), print them and
stop. Claim nothing, comment nothing, dispatch nothing.

## Step 1 — Integration branch + claim (the campaign lock)

### Resume first — the parent comment is the pointer

Check the parent's comments for a previous caravan announcement (`🚂 /caravan …`). If one exists:

- **Adopt the branch it names.** Fetch it, get on it (in a worktree — see branch policy), and read
  what already landed:

  ```bash
  git log origin/<branch> --format=%B | grep '^Ticket: #' | sort -u
  ```

- Continue Step 2 from the first unlanded ticket. All campaign state is derivable — the comment
  names the branch, the branch's trailers name the landed tickets, GitHub names the graph. **No
  session-local state exists anywhere**, so a died session costs nothing but the restart.

### Fresh campaign — branch policy (mirrors `/implement`)

Run `git branch --show-current`:

- **On `main`/`master`** → create the integration worktree:
  `EnterWorktree({ name: "caravan/<parent>-<slug>" })`. The branch comes out sanitized as
  `worktree-caravan+<parent>-<slug>` — that's expected, and **do not rename it**: `EnterWorktree`
  owns the branch's lifecycle, and a `git branch -m` orphans it at cleanup. The ugly name is the
  price of clean auto-teardown; the PR title carries the readable name.
- **On any other branch** (a `claude --worktree` session, or an Orca worktree) → that branch IS the
  integration branch; never create another. Rename an auto-generated placeholder in place with
  `git branch -m caravan/<parent>-<slug>`; keep a meaningful name as-is.

### Claim the whole set, then announce

**Claim every open child up-front** — blocked ones included; the set travels together:

```bash
gh issue edit <n> --add-assignee @me   # once per child
```

The assignee is the lock. It is what keeps a concurrent `/frontier` run (which requires unassigned)
off this parent while the caravan holds tickets whose "done" lives on a branch GitHub can't see.

Then **post one comment on the parent**:

```bash
gh issue comment <parent> --body "🚂 /caravan is working this parent on branch \`<branch>\` — one integration branch, one PR. Children stay open until it merges."
```

That comment is the durable pointer for resume, and the honest signal to any human who wonders why
five assigned tickets show no per-ticket PRs.

## Step 2 — Walk the graph

Topologically order the open, unlanded children by their `blocked_by` edges. **A blocker counts as
satisfied when its ticket is landed on the integration branch** — not when its issue closes.
Children stay open by design until the final PR merges; inside the campaign, the branch is the
ledger and the `Ticket: #<n>` trailers are the entries.

### Route a model tier per ticket

Same table and doctrine as `/implement` step 3, chosen per ticket before dispatch and shown in the
`--dry-run` / kickoff output:

- **sonnet** — the default. Pattern-following work against an established seam.
- **opus** — subtle correctness or real design judgment: invariants that must survive, security
  predicates, a design fork the spec left open. Justify each in one clause.
- **haiku** — mechanical and fully specified. Rare for a vertical slice.
- **Fable is not available for delegation — Opus is the ceiling.** Escalate one tier on rework.

Pass the tier explicitly as `model:` on every `Agent` call.

### Serial default — one implementer per ticket

For each unlanded ticket whose blockers have all landed:

1. **Dispatch one fresh `code-implementer`** (`subagent_type: "code-implementer"`, explicit
   `model:`), brief built from [references/ticket-brief.md](references/ticket-brief.md). Fetch the
   issue **with comments** (`gh issue view <n> --comments`) — a triaged issue carries its contract
   in an agent brief comment, not the body. Paste the contract verbatim; a paraphrase silently
   drops acceptance criteria.
2. **Integrate + verify** (the `/implement` step-4 discipline): read the IMPLEMENTER REPORT —
   `verdict`, `build`, `tests`, `blockers`. Run the **full** build + test suite yourself; delegate
   long-log suites (e2e / UI / integration) to a `verifier` subagent (`model: "sonnet"`) that
   returns a triaged ≤20-line verdict, never raw logs. Anything red or `needs-attention` →
   **re-delegate a fix to a fresh implementer** (never patch inline), one tier up if the original
   failed its own self-verify.
3. **Land it**: commit the verified slice yourself — one commit per ticket:

   ```
   <type>: <ticket title> (#<n>)

   <one or two lines: what the slice delivers, how it was verified>

   Ticket: #<n>
   ```

   The `Ticket: #<n>` trailer is load-bearing — it is the done-marker resume reads and the record
   the final PR body is built from. Then **push the branch**. The push is the durability step; an
   unpushed landing is state only this session knows.
4. Move to the next ticket its landing unblocked.

### Fan-out when width ≥ 2 — only if the files are disjoint

When two or more tickets are simultaneously unblocked, judge their expected file overlap from the
briefs (and the repo):

- **Disjoint file sets** → dispatch them as one same-tree parallel wave — a single message, one
  `Agent` call each, exactly an `/implement` wave. After the wave verifies, land each ticket as its
  own commit (its own trailer), in ranked order.
- **Overlapping or unknowable** → serialize them, ranked by `blocking` count descending, tie-break
  on issue number. A shared-file conflict is NOT solved by isolation — it just moves to merge time
  (`/implement` step 2's rule, and it holds here).
- **Never use `isolation: worktree` agents for tickets.** With the default `worktree.baseRef=fresh`
  an isolated agent branches from `origin/main` — not from the integration branch — so it can't see
  any landed slice. Wrong base, silently.

Vertical slices cross layers, so overlap is the common case — expect to serialize more than you fan
out. That's fine; width was never the point here. **Sustained width ≥ 3 is the tell that this
parent belonged to `/frontier`** — say so rather than grinding a wide graph serially.

### Log the run (orchlog)

Mint once at campaign start, reuse throughout:

```bash
run_id="caravan-<branch>-$(date +%Y%m%d-%H%M%S)"
```

- One `agent` record per implementer (`orchlog.py record --type agent …`), with `--wave` = the
  ticket's position in the walk and the `--rework` / `--review-fix` / `--blockers` flags mapped
  from its report, exactly as `/implement` step 4 specifies.
- One `run` record at the end (`--type run`, auto token capture applies — same session).
- **Reading the report later:** `caravan-` runs are serial **by design** — exclude them from the
  `peak_width == 1` gate-leak signal, which measures `/implement` runs that shouldn't have
  orchestrated. A caravan run at peak width 1 is the skill working as intended.

### If an implementer STOPs

A STOP-and-report (design fork the criteria leave open, a need owned by another ticket, an ADR
conflict) **holds the whole caravan** — everything downstream is blocked by definition; that is the
cost of a chain, and it's the honest cost. Surface the blocker to the user with the ticket number
and the implementer's question. Never skip ahead past an unlanded blocker, and never answer a design
fork on the spec's behalf — a re-dispatch with a ruling beats a reworked wrong guess.

## Step 3 — Finish: review, then one PR

When every child has landed:

1. **Full suite once more** on the integrated branch — the last wave verified itself, not the whole.
2. **Reviews** (the `/implement` step-5 split): `/code-review` is `disable-model-invocation`, so
   **pause and ask the user to type `/code-review medium`** in this session (always `medium` — the
   no-arg default is `xhigh`). Run **`/security-review`** yourself via the Skill tool when the diff
   touches auth/authz, crypto, secrets, user input, file/path/network I/O, deserialization, or SQL.
   Route every finding to a fix implementer (`--review-fix`), land fixes as additional commits
   (trailer of the ticket they belong to, or no trailer for cross-cutting fixes), push.
3. **Compose the PR body yourself** — caravan holds per-ticket knowledge `/cleanup` can't infer:
   - Title from the parent issue.
   - One summary line per landed ticket, in walk order.
   - **One `Closes #<n>` line per child.** All of them — a child left out stays open forever, since
     nothing else in this flow closes issues.
   - A `Parent: #<parent>` reference line. **Never `Closes #<parent>`** — `/to-tickets` deliberately
     never touches the parent, and closing a feature issue deserves a human glance at what shipped.
4. **Ask before publishing.** Opening a PR is outward-facing; interactive approval is the gate. On
   approval: rebase onto `origin/main`, push, `gh pr create` with the composed body — then invoke
   **`/cleanup`** via the Skill tool for the rest: it adopts the existing open PR (it does not
   recreate it or regenerate `Closes` lines), polls CI to conclusive, merges on green, and tears
   down per its own rules.
5. **Report**: the walk table (ticket → tier → verdict → commit), the PR link, and the parent
   declared **ready to close** once the merge lands — closing it stays a human call.

## Rules

- **Scope to a parent, never the repo.** Same as frontier, same reason.
- **Never dispatch the parent, or anything without acceptance criteria.** A spec is not a ticket.
- **Claim all children up-front.** The assignee set is the campaign lock against `/frontier`.
- **One implementer per ticket, fresh each time.** Fresh context per slice is the point; never feed
  two tickets to one implementer, and never let one ticket's implementer "continue" into the next.
- **Landed = `Ticket: #<n>` trailer on the pushed branch. Closed = merged to main.** Never conflate
  them: inside the campaign only the branch is the ledger; on GitHub nothing closes until the PR
  merges.
- **Anti-freelance, always.** The orchestrator commits and pushes; it never writes source.
- **Fan out only on disjoint files, same tree.** Overlap → serialize. Isolated-worktree agents are
  banned here — they branch from the wrong base.
- **Push after every landing.** An unpushed slice dies with the session.
- **Route a tier per ticket; justify each opus.** Escalate one tier on rework.
- **A STOP holds the caravan.** Downstream tickets are blocked by definition; surface, don't skip.
- **Ask before the PR.** `--dry-run` stops before claiming anything at all.
- **Never `Closes #<parent>`.** One `Closes #<n>` per child, parent reported ready to close.

## Red flags

- **The frontier is wide (3+ tickets independently unblocked, sustained)** → this parent belonged to
  `/frontier`. Say so; don't grind a wide graph serially out of momentum.
- **A ticket's body has no acceptance criteria** → it didn't come from `/to-tickets`, or triage never
  finished it. Refuse it — same guard, same reason as frontier.
- **A child is assigned to someone else** → another session holds part of this parent. A caravan
  can't share its parent: its blockers clear on a branch the other worker can't see. Stop and report.
- **You're about to `Edit` a source file** → anti-freelance violation. Delegate it.
- **An implementer report says `blockers: <another ticket's work>`** → the graph's edges are wrong
  or the walk order ignored one. Check the `blocked_by` data before re-dispatching.
- **`git log` shows a landed trailer for a ticket that's still in your queue** → you're resuming
  without having read the branch. Re-run the resume grep before dispatching anything.
- **The branch has commits with no `Ticket:` trailer** (beyond review-fix commits) → someone landed
  work outside the walk. Reconcile before continuing; the trailer ledger is what resume trusts.
- **You're tempted to close a child issue after its slice lands** → that's the other done-marker
  design, deliberately not this one. Closed-before-main lies to the tracker; the `Closes` lines do
  it correctly, at merge time.
- **The final PR body is missing a child's `Closes` line** → that child stays open forever after
  merge. Count them: landed trailers and `Closes` lines must match one-to-one.
