---
name: implement
description: >
  Build a parent issue's sub-issue graph in THIS session: 1 parent = 1 worktree = 1 integration
  branch = 1 PR. Walks the dependency-linked sub-issues in graph order and implements each one
  yourself — per the implement-core doctrine — landing every slice as a `Ticket: #<n>` commit and
  finishing with one PR that closes every child. No orchestrator, no workers: a single session holds
  the whole spec, so spec-level constraints survive and nothing is re-derived per ticket; on context
  overflow it lands, pushes and relays to a fresh session. Read-only helpers (verifier, Explore,
  /code-review, /security-review) stay available as context firewalls. Also takes a single triaged
  issue (no sub-issues). Use after /taskplan has published the sub-issues. (An orchestrator/worker
  build is the separate /implement-orc skill, invoked by the user by name.)
trigger: /implement
user-invocable: true
argument-hint: "<parent issue number, e.g. 42> [--dry-run]"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent", "AskUserQuestion", "EnterWorktree", "ExitWorktree", "Skill"]
---

# /implement

Build a parent issue end-to-end **in this session**: read the live sub-issue graph from GitHub,
implement each ticket yourself in dependency order, land each slice as a commit on ONE integration
branch, and finish with ONE PR that closes every child. **You are the implementer.** There is no
orchestrator and there are no workers.

This is the build stage of the pipeline: `/spec` published the parent issue (the spec), `/taskplan`
decomposed it into sub-issues with native `blocked-by` edges and a per-ticket `method`. **The issue
graph IS the plan** — there is no plan file.

**The shape is fixed: 1 parent = 1 worktree = 1 branch = 1 PR.** If a feature is too wide for one
PR, that was `/spec`'s split decision — it published sibling parents, and cross-parent parallelism
is simply running `/implement` twice in two sessions. Refuse a parent whose own `blocked-by`
(parent-to-parent) edges are still open — its predecessor hasn't shipped.

## One session, and what it costs

One context holds the whole spec for the whole walk, so spec-level constraints survive and nothing
is re-derived per ticket. (Measured: splitting a 7-ticket chain across per-ticket contexts ran 2.9×
the clock, 2× the cost, and lost a testing rule that lived only in the parent.)

**The trade:** the context that writes the code also grades it. You pay for that in two places, and
neither is optional: acceptance criteria are **re-read from GitHub** before every landing (Step 3),
and the **reviews in Step 4 are a gate**, not a nicety.

**You never delegate implementation.** A big graph relays (Step 3); it does not spawn workers. If the
user wants workers they invoke a different skill by name — you don't switch on their behalf.

**Helpers that are allowed** — they read a lot and return a little, protecting this session's
context. None of them writes source:

- **`verifier` subagent** (`model: "sonnet"`) — long-log suites (e2e / UI / integration) → a triaged
  ≤20-line verdict, never raw logs into this session.
- **`Explore` subagent** — a broad codebase sweep where you need the conclusion, not the file dumps.
- **`/code-review`, `/security-review`** — fresh-eyes review of the integrated diff at the end.

Anything that edits source under a different context — a `general-purpose` agent with Edit, an
`isolation: worktree` agent — is not part of this skill.

## Preconditions

- **`gh` ≥ 2.94** — the native sub-issue/dependency flags (`--parent`, `--blocked-by`,
  `--json parent,subIssues,blockedBy,blocking`) landed in 2.94. Check `gh --version` once; older →
  stop and say so.
- The argument resolves to an open GitHub issue. Two shapes are valid:
  - **A parent with sub-issues** (the `/taskplan` output) → the graph walk below.
  - **A standalone issue with no sub-issues** (a `/triage`d bug, a hand-written ticket) → the same
    walk with a graph of one: one worktree, one ticket, verify, land, PR via `/cleanup`. No claim-all
    beyond the issue itself, no campaign comment.
- The issue's own `blockedBy` must be all closed (`gh issue view <n> --json blockedBy`). An open
  blocker on the *parent* means a sibling parent hasn't shipped — report and stop.

### Branch policy — the branch you're on decides everything

Run `git branch --show-current` first:

- **On `main`/`master`** → create the worktree: `EnterWorktree({ name: "feat/<slug>" })`. The branch
  comes out sanitized as `worktree-feat+<slug>` — expected; **do not rename it** (`EnterWorktree`
  owns that branch's lifecycle, and a `git branch -m` orphans it at teardown).
- **On any other branch** (a `claude --worktree` session, an Orca worktree) → that branch IS the
  integration branch; never create another. Rename an auto-generated placeholder in place with
  `git branch -m feat/<slug>`; keep a meaningful name as-is.
- Never `git checkout -b` — it strands work on a moved HEAD.

## Step 1 — Resolve the graph, resume if a campaign exists

**Children** come from the native hierarchy:

```bash
gh issue list --state all --json number,title,state,labels,assignees,parent,blockedBy,blocking \
  --jq '[.[] | select(.parent.number == <parent>)]'
```

(Equivalently `gh api repos/{owner}/{repo}/issues/<parent>/sub_issues`.) Fetch **all states** — the
resume check needs closed children too.

**Hard guards, before anything else:**

- **Never implement the parent.** The scope issue itself is a spec, not a ticket.
- **An issue with no acceptance criteria is not a ticket** — no `## Acceptance criteria` section in
  its body and no agent-brief comment means refuse it and say why.
- **Resolve the agent-ready label** from `docs/agents/triage-labels.md` (the `ready-for-agent` row's
  right-hand column); fall back to the literal `ready-for-agent` if absent. Name the label you
  resolved — an empty graph caused by a label mismatch looks identical to "no work".
- A child **assigned to someone else** means another session holds part of this parent — stop and
  report. This walk cannot share its parent: its blockers clear on the integration branch, which
  the other session can't see.

**Resume first — the parent comment is the pointer.** Check the parent's comments for a previous
campaign announcement (`🛠️ /implement …`). If one exists, adopt the branch it names, get on it, and
read what already landed:

```bash
git log origin/<branch> --format=%B | grep '^Ticket: #' | sort -u
```

Continue from the first unlanded ticket. All campaign state is derivable — the comment names the
branch, the trailers name the landed tickets, GitHub names the graph. No session-local state exists,
so a died, cleared or relayed session costs nothing but the restart. **This is also the overflow
path** (Step 3).

**On `--dry-run`:** print the walk order, then stop. Claim nothing, comment nothing, implement
nothing.

## Step 2 — Claim the set, announce, orient once

**Claim every open child up-front** — blocked ones included; the set travels together:

```bash
gh issue edit <n> --add-assignee @me   # once per child
```

The assignee set is the campaign lock against any concurrent session touching this parent. Then post
one comment on the parent (skip if resuming and it exists):

```bash
gh issue comment <parent> --body "🛠️ /implement is working this parent on branch \`<branch>\` — one integration branch, one PR. Children stay open until it merges."
```

### Orient — once, here, before the first ticket

Read, in this order, and keep them in view for the whole walk:

1. **The parent's `Implementation Decisions` and `Testing Decisions`** — verbatim from the spec body.
   These are the constraints every ticket must satisfy and no ticket restates. The seven forbidden
   test files came from a campaign where nobody re-read this section after the first ticket.
2. **`CONTEXT.md` / `CONTEXT-MAP.md`** glossary and the **ADR index** under `docs/adr/` for the area
   this parent touches. Absent → proceed silently; they're created lazily.
3. **Repo conventions** worth stating once, and the **exact build / test / typecheck commands**,
   resolved from CI config or package scripts. Resolve them now, not per ticket.

This is simply what you know for the rest of the walk — resolve it once, don't rediscover it per
ticket.

## Step 3 — Walk the graph, implement each ticket yourself

Topologically order the open, unlanded children by their `blockedBy` edges. **A blocker counts as
satisfied when its ticket is landed on the integration branch** (its `Ticket: #<n>` trailer exists)
— not when its issue closes. Children stay open by design until the final PR merges: the branch is
the ledger, the trailers are the entries. Where several tickets are unblocked at once, take them in
`blocking` count descending (the one that unblocks the most first), tie-break on issue number.
**Serial is the shape** — there is one of you.

Each `/taskplan` sub-issue body carries an advisory block:

```
<!-- taskplan: {"files_owned": [...], "model": "opus", "method": "tdd"} -->
```

**Only `method` applies to you.** `files_owned` and `model` are planning metadata for other tooling —
the branch is your boundary and you run on the session's model. Missing block → `tdd`
where a test seam exists (implement-core §3), and say which seam you chose.

### Per ticket

1. **Fetch the contract** — `gh issue view <n> --comments`; [`implement-core` §1](../implement-core/SKILL.md)
   decides body vs agent-brief comment. Read it fresh from GitHub, not from memory of the graph.
2. **Implement** per implement-core §2–§5: read the code around the change, follow the glossary and
   ADRs, build by the ticket's `method`, stay on the ticket. Adjacent improvements are follow-ups, not
   scope. Re-check the parent's constraints before you consider the ticket done. implement-core says
   "stop and surface it" on a fork — for you that means ask the user.
3. **Verify against the criteria, one by one** — re-read the `## Acceptance criteria` list from the
   issue and tick each against what you built. Run typecheck + the relevant tests; delegate a long-log
   suite to `verifier`. **Never land on a red build.**
4. **Land it** — one commit per ticket:

   ```
   <type>: <ticket title> (#<n>)

   <what the slice delivers, how it was verified — the criteria you ticked>
   Deviations: <or none>
   Follow-ups: <or none>

   Ticket: #<n>
   ```

   The `Ticket: #<n>` trailer is load-bearing — it is the done-marker resume reads and the record the
   PR body is built from. The body is your report — implement-core §5's deviations and follow-ups
   land here. Then **push** — an unpushed landing is state only this session knows, and the
   relay below depends on it.
5. **Log one agent record** — one per ticket, `--executor session`, so per-ticket quality rates stay
   comparable with the orchestrated history:

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py record --type agent --run-id "$run_id" \
     --executor session --wave <position> --task "<ticket title>" --files-changed N \
     --model <session model> --verdict pass --build pass --tests pass --isolation tree
   # flags when true: --deviated --blockers --rework --review-fix
   ```

   Mint the run id once at campaign start: `run_id="<branch>-$(date +%Y%m%d-%H%M%S)"`.
6. **Move to the tickets this landing unblocked.**

**If a ticket hits a real design fork** (the criteria leave a genuine decision open, or your approach
contradicts an ADR): **STOP the walk and ask the user.** Everything downstream is blocked by
definition — that's the honest cost of a chain. Never decide a fork on the spec's behalf, never skip
past an unlanded blocker to keep moving. Trivia → decide, record under `Deviations:` in the commit.

### Overflow — relay, don't delegate

A long walk will eventually outgrow this context. **Don't try to predict it from ticket bodies** — a
third of tickets turn out materially different from their description (`deviated: 33%` across 183
logged agents), so any up-front estimate is wrong in both directions. React to it instead. Signs:
a compaction notice, or you notice yourself re-deriving a fact you already established (the test
command, a glossary term, a convention set three tickets ago).

When it happens: **finish the ticket you're on, land it, push, stop, and tell the user to start a
fresh session and run `/implement <parent>` again.** Step 1's resume path picks up from the first
unlanded trailer with a fresh context that re-orients from the same sources. This is the *same* path
a died session uses — one mechanism, already trusted. A relay costs one re-orientation and nothing
else.

Never land a half-finished ticket to relay faster. The trailer means done.

## Step 4 — Finish: review, one PR, hand to /cleanup

When every child has landed:

1. **Full suite once more** on the integrated branch — each ticket verified its own scope, not the
   whole. Long logs → `verifier`.
2. **Reviews — a gate, not a nicety.** The writer and the grader have been the same context for the
   whole walk; this is the independent look. `/code-review` is `disable-model-invocation` — pause and
   ask the user to type **`/code-review medium`** (always `medium`; the no-arg default burns far
   more). Run **`/security-review`** yourself via the Skill tool when the diff touches auth/authz,
   crypto, secrets, user input, file/path/network I/O, deserialization, or SQL. Fix every finding
   yourself, land as a `review-fix` commit (no `Ticket:` trailer), log an agent record with
   `--review-fix`, push.
3. **Compose the PR body**:
   - Title from the parent issue.
   - One summary line per landed ticket, in walk order — lift them from the commit bodies.
   - **One `Closes #<n>` line per child — all of them**; a child left out stays open forever.
   - A `Parent: #<parent>` reference line. **Never `Closes #<parent>`** — `/cleanup` closes the
     parent after the merge, when `subIssuesSummary.completed == total`.
4. **Ask before publishing.** On approval: rebase onto `origin/main`, push, `gh pr create` with the
   composed body — then invoke **`/cleanup`** via the Skill tool: it adopts the existing PR, polls
   CI, merges on green, closes the parent, and tears down per its own rules.
5. **Log the run** (once):

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py record --type run --run-id "$run_id" \
     --mode solo --tickets N --branch "<branch>" --milestone "<parent title> (#<parent>)" \
     --waves N --agents N --outcome success --build-final pass --tests-final pass --review-findings N
   # add --pr-created if you opened the PR. In solo mode waves == agents == tickets landed.
   ```

6. **Record the stage cost** — the pipeline-level counterpart to the run log above:

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/stats/stats.py record --issue <parent> --stage implement
   ```

   Do it before the session is cleared; stage attribution cannot be recovered afterwards. Re-running
   is harmless (the row is replaced). This is what lets `/cleanup` show what the whole feature cost.

7. **Report**: the walk table (ticket → verdict → commit), the PR link, and campaign state.

## Rules

- **Scope is one parent.** Never sweep the repo; never implement the parent itself.
- **No acceptance criteria → not a ticket.** Refuse it, whatever its label says.
- **Claim all children up-front; announce on the parent.** The assignee set is the campaign lock.
- **You implement. No workers, ever.**
- **Verify against criteria re-read from GitHub, not from memory.**
- **Reviews are a gate.** The same context wrote and graded every ticket.
- **Landed = trailer on the pushed branch. Closed = merged to main.** Never close a child by hand.
- **Push after every landing.**
- **Overflow → land, push, relay to a fresh session.**
- **A STOP holds the walk.** Surface it; don't skip, don't decide the fork yourself.
- **Ask before the PR.** `--dry-run` stops before claiming anything.

## Red flags

- A ticket's body has no acceptance criteria → it didn't come from `/taskplan` and triage never
  finished it. Refuse it.
- A child is assigned to someone else → another session holds this parent. Stop.
- You're about to spawn an agent to write "just this one ticket" → not this skill. Implement it.
- You're verifying a ticket from memory of its criteria instead of re-reading the issue → fetch it.
- You skipped `/code-review` because "the tests are green" → the tests were written by the same
  context that wrote the code. Run it.
- You're re-grepping for the test command, or re-reading the glossary for a term you used two
  tickets ago → overflow. Land, push, relay.
- `git log` shows a trailer for a ticket still in your queue → you're resuming without having read
  the branch. Re-run the resume grep.
- Commits with no `Ticket:` trailer beyond review-fix commits → work landed outside the walk;
  reconcile before continuing.
- The PR body is missing a child's `Closes` line → that child stays open forever. Landed trailers
  and `Closes` lines must match one-to-one.
- The parent appears in your walk order → the guards didn't run; a spec is not a ticket.

## Analyzing the harness (closing the loop)

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py report --recent 20
```

Records carry `mode` (solo | chain | fanout) and, per agent record, `executor` (session | subagent
| orca) from schema 4.0.0 on; the report splits by both. **Compare within a mode** — a solo run's
`orchestrator` token bucket *is* the implementation, not overhead. Per ticket: high `deviated` →
criteria not tight; high `rework` → the ticket was under-specified or too big for one pass. The cost
levers in solo mode are relay count (sessions per parent) and ticket count — each ticket carries a
fixed re-read of its contract and criteria, so `/taskplan`'s "fewer, larger" advice holds, for
checkpoint size rather than worker cost. When you change this skill in response, bump
`WORKFLOW_VERSION` in `orchlog.py`.
