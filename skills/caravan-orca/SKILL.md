---
name: caravan-orca
description: >
  Work a parent issue's dependency-linked child tickets serially on ONE integration branch, exactly
  like /caravan, but each ticket's implementer is a `claude` CLI session in its own Orca terminal
  (task-create -> dispatch --inject -> worker_done) instead of a built-in subagent. Workers are
  visible Orca panes with runtime task/dispatch provenance; the orchestrator verifies and lands
  each slice as a `Ticket: #<n>` commit, then ships one PR closing every child. Use after
  /to-tickets on a mostly-linear graph when you want watchable per-ticket sessions.
trigger: /caravan-orca
user-invocable: true
argument-hint: "<parent issue number, e.g. 234> [--dry-run]"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent", "AskUserQuestion", "TaskCreate", "TaskUpdate", "Skill"]
---

# /caravan-orca

Walk a parent issue's ticket set in dependency order on one integration branch, toward one PR —
**with every ticket's implementer running as a `claude` CLI session in its own Orca terminal tab.**

This is the **Orca-dispatch variant of `/caravan`**. The campaign doctrine is identical — same
scope guards, same claim-all campaign lock, same `Ticket: #<n>` trailer ledger, same
fan-out-on-disjoint-files rule, same single PR. Only the delivery mechanism differs: instead of
in-process `code-implementer` subagents, each worker is a **`claude` CLI session in its own Orca
terminal**, coordinated through `orca orchestration` (task-create → dispatch --inject →
worker_done). That buys visible worker panes the user can watch and interrupt, runtime
task/dispatch provenance auditable with `orca orchestration task-list`, and per-ticket sessions
that survive independent of this one.

**This is supervised orchestration, not a handoff** — the same tickets `/frontier` would fan out,
run under the opposite coordination model. Frontier hands each ticket away and refuses
`task-create`/`check --wait` because nobody is waiting; here *you* are the one waiting — you create
tracked tasks, inject dispatch preambles, block on `worker_done`, verify, and land every slice
yourself. Don't mix the two models on one parent.

## Step 0 — load two skills (sources of truth)

Before dispatching anything, invoke both with the `Skill` tool. If either is unavailable, **stop
and tell the user** — this workflow requires them.

1. **`orchestration`** (Orca's official coordination skill) — authoritative for **all**
   coordination mechanics: worker terminal creation, `task-create`, `dispatch --inject`, rolling
   `check --wait` supervision, `reply` to asks and gates, `worker_done` semantics, liveness rules,
   and teardown.
2. **`orca-cli`** — authoritative for Orca mechanics: **executable resolution**
   (`ORCA_CLI_COMMAND` → `orca-dev` in a dev checkout → `orca-ide` on Linux outside an Orca
   terminal — **never bare `orca` there**, it's the GNOME screen reader — → otherwise `orca`),
   liveness (`ORCA status --json`), worktree selectors, and terminal handles.

Command shapes below are **illustrative**; where they diverge from those skills' version-matched
guidance, **the skills win**. `ORCA` is a placeholder for the resolved executable — never run it
literally.

## Preconditions

- `ORCA status --json` shows a running runtime; the orchestration experimental feature is enabled
  (Settings → Experimental). If any of this fails, **stop and report — do not fall back to built-in
  subagents** (that would be `/caravan`, and it would silently break the provenance this skill
  promises).
- `gh` authenticated, cwd inside a clone whose remote `gh` can resolve, repo registered with Orca.
- **Work-tree resolution** (replaces `/caravan`'s EnterWorktree branch policy):
  - **Session already inside an Orca-managed worktree** → that worktree IS the integration
    worktree; its branch is the integration branch. Workers are created with `--worktree active`.
  - **Session in the primary checkout on `main`/`master`** → create the integration worktree first:
    `ORCA worktree create --name caravan-<parent>-<slug> --no-parent --json` (no `--agent` —
    workers come per ticket). Create workers with `--worktree id:<fullWorktreeId>` (the exact id
    from the create response), and run your own build/tests/git against that worktree's filesystem
    path. `main` stays clean.

## Doctrine — by reference to `/caravan`

Everything below is `/caravan`'s law, unchanged; read that skill for the full text:

- **Scope & takeability** (`/caravan` Step 0): one parent, children via `## Parent` or native
  sub-issues, label resolved from `docs/agents/triage-labels.md`, blocked-state from
  `issue_dependencies_summary` with the `null` ≠ `0` caveat. The hard refusals hold with no
  override: **never dispatch the parent; an issue without `## Acceptance criteria` is not a
  ticket; a child assigned to someone else stops the campaign.** `--dry-run` prints the walk order
  + tier routing and touches nothing.
- **Campaign lock & announcement** (`/caravan` Step 1): claim **every** open child up-front
  (`gh issue edit <n> --add-assignee @me`), then post the 🚂 comment on the parent naming the
  integration branch.
- **Resume**: the parent's 🚂 comment names the branch; landed tickets are read from
  `git log origin/<branch> --format=%B | grep '^Ticket: #'`. No session-local state exists.
- **Done-markers**: landed = `Ticket: #<n>` trailer on the pushed integration branch; closed =
  the final PR's `Closes #<n>` merging to main. Never conflate them; never close a child early.
- **Anti-freelance**: you never write or edit source. You run commands — build, test, and git;
  committing and pushing each landed slice is orchestration.
- **Model routing**: per ticket, `/implement`'s table — sonnet default, each opus justified in one
  clause, haiku for mechanical, Fable never. The tier is fixed in the worker's argv, so
  **escalation on rework = a new terminal one tier up**.

## Step 2 — Walk the graph, one worker terminal per ticket

Topologically order the open, unlanded children; a blocker is satisfied when its ticket is landed
on the integration branch. Then, for each ticket whose blockers have all landed:

### 1. A NEW terminal per ticket — always

```bash
ORCA terminal create --worktree <selector> --title ticket-<n> \
  --command "claude --model <tier> --dangerously-skip-permissions" --json
ORCA terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
```

**Terminal reuse across tickets is banned here**, even though `/implement-orca` allows reusing
idle workers across waves. Fresh context per slice is caravan's whole point, and a reused `claude`
session *carries the previous ticket's context* into the next one — exactly the degradation
`/to-tickets` sliced the feature to avoid. One ticket, one session, no exceptions.

`terminal wait --for tui-idle` is not optional: dispatching before the TUI is ready loses the
prompt, and a worker that never received its brief looks identical to one that's thinking.

### 2. Create the task, dispatch it

```bash
ORCA orchestration task-create --spec "<ticket brief>" --json
ORCA orchestration dispatch --task <task_id> --to <handle> --inject --json
```

The injected preamble teaches the worker its lifecycle duties (`worker_done`, `ask`, heartbeat) —
the brief doesn't restate them.

**The brief**: build it from `/caravan`'s
[../caravan/references/ticket-brief.md](../caravan/references/ticket-brief.md) — the
which-text-is-the-contract table (fetch the issue **with comments**; `/to-tickets` body verbatim
vs `/triage` agent-brief comment) and the template body apply unchanged, with three Orca deltas.
Workers here are top-level `claude` sessions — the `code-implementer` agent definition does NOT
apply to them — so the implementer contract travels inside the spec:

1. In `## Rules`, replace the STOP-and-report clause with: *"On a design fork or anything the
   acceptance criteria don't pin down, consult the coordinator via `ask` BEFORE proceeding — a
   one-paragraph ruling is far cheaper than a reworked wrong guess. Deviate silently only on
   trivia, and record it under deviations."* The do-not-commit/push/branch/PR rule stays verbatim.
2. Add: *"Self-verify before reporting; never claim done on a red build."*
3. Replace `## Output` with the inline report contract:

   ```
   ## Output
   Put EXACTLY this block in the body of your worker_done message (and include changed paths in
   the payload's filesModified):
   ===== IMPLEMENTER REPORT =====
   task: <one-line restatement>
   files_changed:
     - <path> — <what changed>
   summary: <2-4 lines>
   build: pass | fail | skipped(<reason>)
   tests: pass | fail | skipped(<reason>)
   typecheck: pass | fail | skipped(<reason>)
   verdict: pass | needs-attention | fail
   deviations: <or none>
   blockers: <cross-boundary needs / ambiguities, or none>
   follow_ups: <or none>
   ===== END IMPLEMENTER REPORT =====
   ```

### 3. Supervise

Per the orchestration skill: rolling `check --wait` for `worker_done` / `escalation` /
`decision_gate`. Its liveness rules apply verbatim — a timeout is a checkpoint, not a failure;
heartbeats mean alive, not done; never stop or kill a worker that is still working.

Answer a worker's `ask` with `reply` **only when the ticket's acceptance criteria or the spec
already answer the question.** A genuine design fork still goes to the user — that is `/caravan`'s
STOP-holds-the-caravan rule expressed through the ask/reply channel. Everything downstream is
blocked by definition while it waits; that's the cost of a chain, and it's the honest cost.

### 4. Verify, land, close the tab

- Parse the IMPLEMENTER REPORT from the `worker_done` body: `verdict`, `build`, `tests`,
  `blockers`. A `blockers` entry naming another ticket's work means the graph's edges are wrong —
  check the `blocked_by` data before re-dispatching.
- Run the **full** build + test suite yourself in the work tree. Long-log suites (e2e / UI /
  integration) → delegate to a dedicated **e2e worker** terminal (sonnet, same mechanics,
  reusable across tickets — it accumulates no implementation context) or a `verifier` subagent
  (built-in `Agent` tool, `model: "sonnet"` — read-only, needs no Orca provenance). Triaged
  ≤20-line verdict, never raw logs.
- Red, or `needs-attention`/`fail` → **re-delegate a fix, never patch inline**: same tier → a new
  task dispatched to the same (still-open) worker terminal — the fix is the same ticket, so its
  context is an asset, not contamination; escalated tier → a new terminal.
- Green → **land it yourself**: one commit per ticket with the `Ticket: #<n>` trailer
  (`/caravan` Step 2's format), then **push**. The push is the durability step.
- **Close the worker's terminal once its slice lands.** The report is captured, the commit is the
  record; a serial walk that keeps every pane open ends with one dead tab per ticket. (This
  replaces `/implement-orca`'s close-at-teardown — reuse is banned here, so a landed ticket's
  terminal has no future.)

### Fan-out when width ≥ 2 — `/caravan`'s rule, Orca mechanics

≥2 tickets simultaneously unblocked **and** judged file-disjoint from their briefs → create and
dispatch their worker terminals back-to-back; they run concurrently in the same tree. Verify and
land each with its own commit, in ranked order (`blocking` count desc, then issue number).
Overlapping or unknowable → serialize. Sustained width ≥ 3 → this parent belonged to `/frontier`;
say so.

### Log the run (orchlog)

```bash
run_id="caravan-orca-<branch>-$(date +%Y%m%d-%H%M%S)"
```

One `agent` record per worker (`--wave` = walk position, flags mapped from its report), one `run`
record at the end — **always with `--no-auto-tokens`**: workers are separate claude sessions whose
transcripts live outside this session, so the auto-scan would report misleading buckets. Ignore
the COST block for these runs, and — as with `/caravan` — exclude `caravan-orca-` runs from the
`peak_width == 1` gate-leak signal: serial is by design here.

## Step 3 — Finish: review worker, then one PR

1. **Full suite once more** on the integrated branch.
2. **Reviews run in a dedicated review worker**, not this session (`/code-review` is
   `disable-model-invocation` here, but a worker terminal is a real user session — the same
   mechanism `/implement-orca` Step 5 uses):

   ```bash
   ORCA terminal create --worktree <selector> --title code-review \
     --command "claude --model opus --dangerously-skip-permissions" --json
   ORCA terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
   ORCA terminal send --terminal <handle> --text "/code-review medium" --enter
   # poll/wait for the report, then in the SAME session, when the diff touches a security
   # surface (auth/authz, crypto, secrets, user input, file/path/network I/O, deserialization, SQL):
   ORCA terminal send --terminal <handle> --text "/security-review" --enter
   ```

   Send the slash commands as plain terminal input — not via `task-create`/`dispatch`; they are
   user commands, not delegated implementation. Read the findings back; the review worker never
   acts on them. Route every finding to a fix worker (`--review-fix`), land fixes as additional
   commits, push, close the review terminal.
3. **One PR — `/caravan` Step 3 verbatim**: compose the body yourself (title from the parent, one
   summary line per landed ticket, **one `Closes #<n>` per child — count them against the landed
   trailers, one-to-one**, a `Parent: #<parent>` line, never `Closes #<parent>`). **Ask before
   publishing.** On approval: rebase onto `origin/main`, push, `gh pr create`, then invoke
   `/cleanup` via the Skill tool — it adopts the existing open PR (never recreates it), polls CI,
   merges on green.
4. **Teardown note**: running inside an Orca terminal, `/cleanup` deliberately leaves the worktree
   and local branch "for Orca to manage" (its Orca guard). Nothing in this flow reaps them — report
   that plainly so the worktree doesn't silently linger, and leave removal to the user.
5. **Report**: walk table (ticket → tier → verdict → commit → terminal), PR link, parent declared
   ready to close — closing it stays a human call.

## Rules

All of `/caravan`'s rules apply unchanged. On top, the transport-specific ones:

- **One worker terminal per ticket, never reused across tickets.** A reused session carries the
  previous ticket's context; fresh context is the point. (Same-ticket fix re-dispatch is the one
  sanctioned reuse.)
- **Never fall back to built-in subagents.** If Orca or orchestration is down, stop — the fallback
  is called `/caravan`, and it's the user's choice to make, not a silent degradation.
- **Provenance is real.** Before claiming a worker was orchestrated, the task/dispatch must exist
  (`task-list` / `dispatch-show`, per the orchestration skill's tool boundary).
- **`terminal wait --for tui-idle` before every dispatch.** A swallowed brief looks identical to a
  thinking worker.
- **`reply` answers only what the ticket already decides.** Design forks go to the user; the
  caravan holds.
- **Close a landed ticket's terminal.** The commit is the record; the pane is done.

## Red flags

- **You're reusing an idle worker terminal for the next ticket** → `/implement-orca` habit; banned
  here. New ticket, new terminal.
- **You're about to spawn workers with `/frontier`'s `worktree create --agent` shape** → wrong
  flow: that's the handoff model, one worktree per ticket, no supervision. Here every ticket runs
  in the ONE integration worktree under tracked tasks.
- **A worker never responds to its brief** → you probably skipped `tui-idle`, and the prompt was
  swallowed. Re-check the handle before re-sending; never dual-send.
- **`check --wait` times out repeatedly with heartbeats still arriving** → alive, not done. Keep
  waiting; never kill a working session.
- **You answered a design fork via `reply` to keep things moving** → you just made a spec decision
  the user never saw. That ruling belongs to them; the ticket should have held.
- **The walk is done but N terminals are still open** → landed tickets' tabs weren't closed as you
  went. Close them; only the review/e2e workers may outlive a ticket.
- **You're tempted to run the implementers as `Agent` subagents "just this once"** → that's
  `/caravan`. Switching transports mid-campaign splits provenance across two models; finish in one.
