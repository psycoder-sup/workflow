---
name: implement-orca
description: >
  Run a body of work as an orchestrator, exactly like /implement, but the parallel workers are
  Orca-orchestrated `claude` CLI terminals (task-create -> dispatch --inject -> worker_done) instead
  of built-in background subagents. Workers are visible Orca panes with runtime task/dispatch
  provenance. The main session orchestrates and NEVER writes implementation code itself. Every wave
  and run is logged for later analysis. Use for non-trivial multi-file features inside an
  Orca-managed worktree.
trigger: /implement-orca
user-invocable: true
argument-hint: "<work description or path to a plan file>"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent", "AskUserQuestion", "TaskCreate", "TaskUpdate", "Skill"]
---

# /implement-orca

Run a body of work end-to-end as an **orchestrator**: you plan and partition the work, delegate the
actual coding to parallel workers, integrate and verify their output, get it reviewed, and (only on
request) open a PR. **You never write the implementation yourself.** Every run is logged so the
harness can be analyzed and improved over time.

This is the **Orca-dispatch variant of `/implement`**. The management doctrine is identical — same
gate, same partition rules, same briefs, same review loop, same run log. Only the delivery mechanism
differs: instead of built-in `code-implementer` subagents, each worker is a **`claude` CLI session in
its own Orca terminal**, coordinated through `orca orchestration` (task-create → dispatch --inject →
worker_done). That buys visible worker panes, runtime task/dispatch provenance you can audit with
`orca orchestration task-list`, and workers that survive independent of this session.

## Step 0 — load the official `orchestration` skill (source of truth)

Before dispatching anything, **invoke the user-level `orchestration` skill** (Orca's official
coordination skill, installed at `~/.claude/skills/orchestration` and auto-updated with Orca) and
follow it for **all** coordination mechanics: worker terminal creation, `task-create`,
`dispatch --inject`, rolling `check --wait` supervision, `reply` to gates, `worker_done` semantics,
liveness rules, and teardown. If it is not available, **stop and tell the user** — this workflow
requires it.

This document tells you *what* to do at each workflow step, in orchestration vocabulary. The
orchestration skill defines *how*. The few command examples below are illustrative; **if they ever
diverge from the orchestration skill, the orchestration skill wins.**

This workflow is **supervised orchestration, not a full handoff**: you create tracked tasks, inject
dispatch preambles, and wait on `worker_done` — exactly the supervised path the orchestration skill
describes. All its rules on handle addressing, lifecycle authority, auto-completion on `worker_done`,
and provenance checks apply as written there.

## The roles (keep them separate)

- **Orchestrator (you, this session)** — plan, partition, delegate, run commands (build/test/git),
  integrate, decide. You hold all of the work in context.
- **Orca worker** — a `claude` CLI terminal that implements ONE scoped task inside a fixed file
  boundary, self-verifies, and reports back via `worker_done`. Spawned N-at-a-time, in parallel.
- **`verifier` subagent (optional)** — independently reproduces build/tests and checks acceptance
  criteria. Read-only, spawned with the built-in `Agent` tool (it implements nothing, so Orca
  provenance is not needed for it).
- **Review worker** — a dedicated Orca terminal (`claude --model opus --dangerously-skip-permissions`)
  that runs `/code-review` and `/security-review` as real slash commands and reports findings back.
  Not this session: `/code-review` is `disable-model-invocation`, so the `Skill` tool cannot call it
  here. See Step 5.

## Anti-freelance rule (the one rule that makes this work)

**You do not write or edit implementation code. Ever.** Not for the first task, not for a "just
one-line" fix found during verification, not for review findings. All code changes go through an
Orca worker. Your Write/Edit access is only for orchestration artifacts (a plan file, `status.json`)
— never source files. If you catch yourself about to Edit a source file, stop and delegate it
instead. Editing source yourself races the workers and destroys the parallelism guarantees.

## Preconditions

- `orca status --json` shows a running runtime; `orca` is on PATH; the orchestration experimental
  feature is enabled (Settings > Experimental). If any of these fails, stop and report — do not fall
  back to built-in subagents (that would be `/implement`, and it would break the provenance this
  skill promises).
- **Work-tree resolution** (replaces `/implement`'s EnterWorktree branch policy):
  - **Session already inside an Orca-managed worktree** (the normal case) → workers are created with
    `--worktree active`; you run build/tests/git right here.
  - **Session in the primary checkout on `main`/`master`** → create an isolated Orca worktree first:
    `orca worktree create --name feat-<slug> --no-parent --json` (no `--agent` — workers come later,
    per wave). Create workers with `--worktree id:<fullWorktreeId>` (the exact id from the create
    response), and run your own build/tests/git against that worktree's filesystem path. `main`
    stays clean.

## Workflow

### 1. Plan + partition
- Resolve the work tree first (see Preconditions) so nothing lands on `main`.
- **Worth orchestrating? (hard gate — width AND volume.)** Compute the **parallel width** `W` = the
  most *independent* tasks (disjoint file sets) that could run together in a single wave, and the
  **volume** `V` = total tasks after collapsing linear chains (step 2's chain rule):
  - **`W == 1` → STOP. Do NOT orchestrate — exit the skill before you mint a run_id.** Serial work
    in a parallel costume pays full orchestration overhead and banks nothing. A single feedback item
    or bug fix is `W == 1` by default. Do it in a normal session, or hand it to one worker without
    wave machinery, run record, or review loop.
  - **`W ≥ 2` but `V ≤ 4` → direct dispatch:** stand up the workers in parallel with full briefs
    (anti-freelance still applies), integrate and verify yourself — but **skip the run record, wave
    bookkeeping, and standing review loop**. Small-parallel work can't amortize the fixed overhead.
  - **`W ≥ 2` and `V ≥ 5` → orchestrate.**
  The after-the-fact mirrors of this gate in the run log: `peak_width == 1` (violated width) and a
  small `agents_total` with a high orchestrator token share (violated volume) — either means this
  skill shouldn't have run. (See `/implement` for the measured cost rationale — break-even sits
  around 6–7 agents there, and Orca workers add terminal-management overhead on top, so if anything
  the bar here is higher.)
- Decompose the work into independent **tasks**. If a plan file was passed as the argument, start
  from it; otherwise build the plan with the user (use plan mode for anything non-trivial).
- Build a **file-ownership map**: for each task, the set of files it will create/modify.
- Group tasks into **waves**: disjoint file sets share a wave; dependent tasks go in later waves.
- Mint a **run id** now and reuse it for every `orchlog.py` call in this run — the `orca-` prefix is
  what distinguishes these runs from `/implement` runs in `report`:
  ```bash
  run_id="orca-<branch>-$(date +%Y%m%d-%H%M%S)"
  ```
- (Optional) `TaskCreate` one task per work-item to track wave progress.

### 2. Partition rules — deciding N
N is **discovered, not forced** — only split work that is genuinely independent.
- Disjoint file sets → parallel (same wave).
- Two tasks share a file → **conflict**. Resolve by (a) one worker owns that file + both pieces, or
  (b) serialize into different waves, or (c) make the shared edit its own tiny delegated task
  between waves (delegate it — don't edit it yourself).
- **Hotspot files** are conflict magnets — never let two workers touch them in parallel:
  router/route tables, DI containers, barrel `index.ts`, schema/migrations, lockfiles, shared types.
- Sequential dependency → N=1 for that stretch; don't fake parallelism.
- **Collapse linear chains into one brief.** Consecutive width-1 tasks (A → B → C, nothing beside
  them) are ONE worker with a multi-step brief — each width-1 wave is a full
  dispatch → worker_done → integrate round trip for zero parallelism. Split only when something
  runs beside a task in its wave or the combined scope would blow one worker's context. A collapsed
  chain counts as one task for the volume gate `V`.
- Default isolation is **same tree**: all workers run in this worktree, partitioned by file, so
  integration is trivial. Reserve a **separate Orca worktree worker** (`orca worktree create`, per
  the orchestration skill's worker-terminal guidance) for a large/risky standalone task only — it
  gets an isolated checkout that can't see this tree's uncommitted state, and its output must be
  merged back separately. A shared-file conflict is NOT solved by isolation; solve those by
  serializing / single-owner.

### 3. Dispatch a wave
For each task in the wave, stand up one worker and dispatch to it (mechanics per the orchestration
skill):

1. **Create the worker terminal** in the work tree, running the claude CLI at the task's tier:
   `claude --model <tier> --dangerously-skip-permissions`. The tier is fixed at launch — it lives in
   the argv, not the dispatch. (`--dangerously-skip-permissions` is what lets workers run unattended;
   the file boundary in the brief and the isolated worktree are the containment.)
2. **Wait for TUI idle** before dispatching, so the prompt isn't lost.
3. **`task-create`** with the full brief (below) as the spec.
4. **`dispatch --inject`** the task to that worker's handle. The injected preamble teaches the worker
   its lifecycle duties (`worker_done`, `ask`, heartbeat) — your brief doesn't need to restate them.

Illustrative only (orchestration skill is authoritative):
```bash
orca terminal create --worktree active --title <task-slug> \
  --command "claude --model sonnet --dangerously-skip-permissions" --json
orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
orca orchestration task-create --spec "<brief>" --json
orca orchestration dispatch --task <task_id> --to <handle> --inject --json
```

Create and dispatch every worker in the wave back-to-back; they run concurrently.

#### Model selection — match the tier to the task
Same routing table and doctrine as `/implement` step 3, applied to the `--model` argv:

| Tier | argv | Route here when… |
|---|---|---|
| Opus 4.8  | `--model opus`   | subtle correctness, non-trivial reasoning, or a design the brief doesn't pin down — **top tier** |
| Sonnet 5  | `--model sonnet` | standard, well-specified task with a clear pattern + tight criteria — **the workhorse default** |
| Haiku 4.5 | `--model haiku`  | mechanical / deterministic: renames, config, boilerplate copying an obvious template |

Pick the cheapest tier whose intelligence *and* taste both clear the task's bar. **Escalate one tier
on rework** — and since the model is fixed at terminal launch, escalation means a **new worker
terminal**, not a re-dispatch to the old one.

#### The brief (task-create spec)
Orca workers are top-level claude sessions — the `code-implementer` agent definition does NOT apply
to them, so the implementer contract must travel **inside the spec**. Every brief is self-contained:

```
## Task
<the one unit of work>
## Acceptance criteria   (checkable — this is the contract)
- [ ] ...
## File ownership   (create/modify ONLY these; if you need anything outside, STOP and ask the
## coordinator via `ask` — do not edit it)
- src/foo/**, tests/foo/**
## Context & conventions
<pointers to existing code, the pattern to follow, examples>
## Verification
<the exact build / test / lint commands to run for this scope>
## Rules
- Read before you write; follow surrounding conventions; reuse existing utilities.
- On a design fork or anything the acceptance criteria don't pin down, consult the coordinator via
  `ask` BEFORE proceeding — a one-paragraph ruling is far cheaper than a reworked wrong guess.
  Deviate silently only on trivia, and record it under deviations.
- No scope expansion; tempting adjacent improvements go under follow_ups.
- Do not commit, push, branch, or open PRs — you only change the working tree.
- Self-verify before reporting; never claim done on a red build.
## Output
Put EXACTLY this block in the body of your worker_done message (and include changed paths in the
payload's filesModified):
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

Under-specified briefs are the #1 cause of bad delegated code. If you can't write crisp acceptance
criteria and a clean file boundary, the task isn't ready — refine the partition first.

### 4. Supervise + integrate + verify + log
- **Supervise per the orchestration skill**: rolling `check --wait` loops for
  `worker_done` / `escalation` / `decision_gate`; loop once per outstanding worker. Its liveness
  rules apply verbatim — a timeout is a checkpoint, not a failure; answer a worker's `ask` /
  `decision_gate` with `reply` and keep waiting; heartbeats mean alive, not done; never stop or kill
  a worker that is still working.
- Parse each IMPLEMENTER REPORT from the `worker_done` body. Read `verdict`, `build`, `tests`,
  `blockers`. A `blockers` entry naming a cross-boundary need means your partition was off — handle
  it (reassign ownership, add a serial step), don't ignore it.
- Run the **full** build + test suite yourself in the work tree (running commands is orchestration,
  not coding) — **except long-log suites (e2e / UI / integration)**: delegate those to a dedicated
  **e2e worker** (sonnet tier, same terminal mechanics as any worker; reusable across waves). Its
  brief: run the exact suite command, triage any failures to a suspected cause, and report a compact
  verdict — pass/fail, failing case names, suspected cause, ≤20 lines, **never raw logs**. Every
  token of e2e output that lands in this session is re-read on every subsequent turn at
  orchestrator-tier rates; a triaged verdict is orders of magnitude smaller. Fixes still route to a
  **code** worker as usual (the e2e worker never fixes).
- (Optional) spawn a `verifier` subagent (built-in `Agent` tool, `model: "sonnet"`) against the
  acceptance criteria for a second opinion — read-only, so it needs no Orca provenance.
- Anything red, or any `needs-attention`/`fail` verdict → **re-delegate a fix** (never patch
  inline): same tier → re-dispatch a new task to the now-idle worker terminal; escalated tier → new
  worker terminal. Loop back to step 3 until the wave is green.
- **Log one `agent` record per worker** (map the report → flags):
  ```bash
  python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py record --type agent --run-id "$run_id" \
    --wave 1 --task "add foo endpoint" --files-owned 3 --files-changed 3 \
    --model sonnet --verdict pass --build pass --tests pass --isolation tree
  # flags when true: --deviated --blockers --boundary-stop --rework --review-fix
  # --isolation worktree for a separate-Orca-worktree worker.
  # rework vs review-fix matters: rework is a quality signal (briefs/partition); review-fix is healthy.
  ```

### 5. Review
`/code-review` and `/security-review` are `disable-model-invocation` — the `Skill` tool rejects them
in **this** session. Do not substitute a home-grown reviewer subagent; the user wants the real slash
commands. Run them in one **dedicated review worker** instead:
1. Stand up a fresh Orca worker terminal for review — **opus** tier, since review judgment is worth
   the top model: `claude --model opus --dangerously-skip-permissions`. Wait for TUI idle.
2. In that **same** worker session, send the slash commands directly as terminal input (not via
   `task-create`/`dispatch` — these are user slash commands, not delegated implementation tasks):
   - **`/code-review medium`** — for any run with real code changes (always pass `medium`; the
     no-arg default burns far more tokens than a routine review needs).
   - **`/security-review`** — afterward, in the **same** session, when the diff touches
     auth/authz, crypto, secrets, user input, file/path/network I/O, deserialization, or SQL. Skip
     when there's no plausible security impact.

   Illustrative only (orchestration skill's terminal mechanics are authoritative):
   ```bash
   orca terminal create --worktree active --title code-review \
     --command "claude --model opus --dangerously-skip-permissions" --json
   orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
   orca terminal send --terminal <handle> --text "/code-review medium" --enter
   # poll/wait for the report, then in the same session:
   orca terminal send --terminal <handle> --text "/security-review" --enter
   ```
   Both commands run their own background subagents inside that one worker session — no need for a
   second terminal per command.
3. Poll the terminal output until each report completes, then read the findings back into this
   orchestrator session — that's the "report back to parent" step; the review worker never acts on
   its own findings.
4. Route every finding back to a **code** worker as a fix task (anti-freelance still applies — the
   review worker only reviews, it never fixes); log each such fix with `--review-fix`. Re-verify
   after fixes.
5. Close the review worker terminal with the rest of teardown (Step 6) once the run is done.

### 6. Finish + run log
- **Teardown**: close worker terminals when the run is done (idle workers may be reused across waves
  when the tier matches — close them at the end, not between waves).
- **Only if the user explicitly asks**, publish: `gh pr create ...` (and/or commit). Otherwise
  report what was done and verified — publishing is the user's call.
- In `project-kit` repos: you may reflect **in-progress** state in `docs/pm/status.json`, but do not
  mark it shipped here — that transition rides in the milestone PR via `/cleanup`.
- **Log the run summary** (once per run). **Always pass `--no-auto-tokens`**: workers are separate
  claude sessions whose transcripts live outside this session, so the auto-scan would report
  `code-implementer ≈ 0` and inflate the other buckets — a known-misleading shape. Worker token
  usage is not captured in this variant.
  ```bash
  python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py record --type run --run-id "$run_id" \
    --branch "<branch>" --milestone "<desc>" --waves 2 --agents 5 \
    --outcome success --build-final pass --tests-final pass --review-findings 2 \
    --no-auto-tokens
  # add --pr-created if you opened a PR. fix_iterations, peak_width, wave_widths are derived
  # automatically from this run's agent records — pass nothing for them.
  ```

## Management principles
- **Self-contained briefs** — every worker gets all the context it needs; no shared memory.
- **Acceptance criteria are the contract** — verify against them, not against vibes.
- **Verification gate** — nothing is "done" until build + tests are green and criteria are met.
- **Bounded autonomy** — workers have a hard file boundary and an ask-first rule; that is what lets
  them run in parallel safely.
- **Fixes are always re-delegated** — never inline-patch.
- **Right-size the model** — cheapest tier that clears the bar; escalate a tier (new terminal) on
  rework.
- **Provenance is real** — before claiming a worker was orchestrated, the task/dispatch must exist
  (`task-list` / `dispatch-show`, per the orchestration skill's tool boundary).

## Analyzing the harness (closing the loop)
Same log, same tooling as `/implement` — Orca runs are the `orca-`-prefixed run_ids:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py report --recent 20
```
All `/implement` quality signals (boundary_stop, rework, deviated, peak_width, model-fit) read the
same here. **Ignore the COST block for `orca-` runs** — worker tokens are uncaptured by design
(`--no-auto-tokens`), so only orchestrator-side numbers would appear; never compare COST across the
two variants. When you change this skill in response to these signals, bump `WORKFLOW_VERSION` in
`orchlog.py` so before/after runs stay comparable.
