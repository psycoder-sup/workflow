---
name: implement
description: >
  Run a body of work as an orchestrator: plan -> partition into file-disjoint waves -> delegate to N
  parallel code-implementer subagents -> integrate, verify, review -> (PR on request). The main
  session orchestrates and NEVER writes implementation code itself. Every wave and run is logged for
  later analysis. Use for non-trivial multi-file features run inside a dedicated worktree.
trigger: /implement
user-invocable: true
argument-hint: "<work description or path to a plan file>"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent", "AskUserQuestion", "TaskCreate", "TaskUpdate", "EnterWorktree"]
---

# /implement

Run a body of work end-to-end as an **orchestrator**: you plan and partition the work, delegate the
actual coding to parallel `code-implementer` subagents, integrate and verify their output, get it
reviewed, and (only on request) open a PR. **You never write the implementation yourself.** Every run
is logged so the harness can be analyzed and improved over time.

This is the N-child evolution of the single-child `/tian implement` pattern, built on pure
Claude-Code primitives (worktree + native subagents + skills) — no tian CLI.

## The roles (keep them separate)

- **Orchestrator (you, this session)** — plan, partition, delegate, run commands (build/test/git),
  integrate, decide. You hold all of the work in context.
- **`code-implementer` subagent** — implements ONE scoped task inside a fixed file boundary,
  self-verifies, returns a structured report. Spawned N-at-a-time, in parallel.
- **`verifier` subagent (optional)** — independently reproduces build/tests and checks acceptance
  criteria. Read-only.
- **`/code-review`, `/security-review`** — fresh-eyes review of the integrated diff.

## Anti-freelance rule (the one rule that makes this work)

**You do not write or edit implementation code. Ever.** Not for the first task, not for a "just
one-line" fix found during verification, not for review findings. All code changes go through a
`code-implementer`. Your Write/Edit access is only for orchestration artifacts (a plan file,
`status.json`) — never source files. If you catch yourself about to Edit a source file, stop and
delegate it instead. Editing source yourself races the implementers and destroys the parallelism
guarantees.

## Preconditions

Run this **inside a dedicated worktree**, so all the work is isolated from `main`:

**Branch policy — the branch you're on decides everything.** Run `git branch --show-current` at the
start of step 1, then:

- **On `main`/`master`** (you're NOT in a dedicated worktree) → **create a worktree** with the
  built-in `EnterWorktree` tool: `EnterWorktree({ name: "feat/<slug>" })`. It creates an isolated
  git worktree (under `.claude/worktrees/`) and switches this session into it — so the work
  runs isolated from `main`, exactly like the `claude --worktree` case. **This is the only case
  where you create anything.** Do *not* use `git checkout -b`: that stays in the `main` working tree
  and doesn't isolate the work.
  - **Gotcha — the branch name is sanitized, not literal.** `EnterWorktree({ name: "feat/<slug>" })`
    does NOT produce a `feat/<slug>` branch: it slugifies the name (`/` → `+`) and prefixes it, so
    you land on branch `worktree-feat+<slug>` (dir `feat+<slug>`). That's expected — don't fight it.
  - **Gotcha — do NOT rename this branch.** Leave the `worktree-feat+<slug>` name as-is. Here
    `EnterWorktree` owns the branch's whole lifecycle: `ExitWorktree({ action: "remove" })` deletes
    the *exact* branch it created. A `git branch -m` would desync that — cleanup removes the old
    name and the renamed branch survives, orphaned, needing a manual `git branch -d`. The ugly name
    is the price of clean auto-teardown; accept it.
- **On any other branch** (the normal `claude --worktree` case) → **never create a branch or
  worktree.** That branch already IS the branch for this work. (`EnterWorktree` did not run this
  session, so there's no `ExitWorktree` auto-teardown to desync — renaming here is safe.)
  - Auto-generated placeholder (e.g. `worktree-polymorphic-seeking-riddle`)? Rename it **in place**
    with `git branch -m feat/<slug>` (e.g. `git branch -m feat/inbox-create-modal-properties`). `-m`
    renames the current branch *without* creating a new one or moving HEAD, so worktree isolation is
    fully preserved while the branch gets a readable name.
  - Already a meaningful name? Leave it as-is.

`git branch -m` = rename in place = safe, but **only** in the non-main case above (an
`EnterWorktree`-created branch must keep its name so auto-teardown can delete it). `checkout -b`
while on a non-main branch = a stray branch + a moved HEAD = the footgun that switches the branch
out from under your work. Never do it.

## Workflow

### 1. Plan + partition
- **Get into the worktree first — precondition, not a judgment call.** `/implement` always runs
  off `main`, so establish this before anything that writes a file (a plan, `status.json`) or you'll
  strand it on `main`. Run `git branch --show-current`:
  - **On `main`/`master`** → `EnterWorktree({ name: "feat/<slug>" })`, and **leave the resulting
    `worktree-feat+<slug>` branch name as-is** — renaming it orphans the branch at cleanup (see
    Branch policy).
  - **On any other branch** (the normal `claude --worktree` case) → you're already isolated; never
    create a worktree or branch. Rename an auto-generated placeholder in place with
    `git branch -m feat/<slug>`, or keep it if it's already meaningful (see Branch policy above).
- **Worth orchestrating? (hard gate — width AND volume.)** With the worktree ready, compute two
  numbers from the draft partition: the **parallel width** `W` = the most *independent* tasks
  (disjoint file sets) that could run together in a single wave, and the **volume** `V` = total
  task count *after collapsing linear chains* (step 2's chain rule — a chain counts as one task).
  Apply the rules mechanically; only the last branch continues past this bullet to the run-id line
  below:
  - **`W == 1` → STOP. Do NOT orchestrate — exit the skill *before* you mint a run_id.** This covers
    both a single task *and* work that only runs one-at-a-time (every wave has one agent, i.e.
    `agents == waves` — sequential work in a parallel costume). There is no "orchestrate it anyway
    because I'm already in the worktree" branch. Tell the user the work is serial, then either do it in
    a normal session (`ExitWorktree` to drop the fresh worktree — an unchanged one auto-cleans) or
    dispatch **one** `code-implementer` with no wave machinery, no run record, no review loop.
    - **Fast-path — a single feedback item or bug fix is `W == 1` by default.** "Fix feedback #N",
      "fix the `<X>` bug", one-screen / one-file corrections: this is serial single-file work wearing a
      task costume. Route it straight to one `code-implementer` and skip `/implement` entirely —
      unless you can concretely name **≥2 disjoint-file tasks that run at the same time**. (This exact
      pattern is where the width gate leaked most in practice — see below.)
  - **`W ≥ 2` but `V ≤ 4` → direct dispatch — skip the machinery.** The work is genuinely parallel
    but too small to amortize the orchestration tax (measured below). Spawn the implementers
    directly: parallel `Agent` calls in a single message, each with a full step-3 brief and file
    boundary — the anti-freelance rule stays in force — then integrate and verify yourself (step 4's
    build/test discipline, minus the logging). **No run_id, no orchlog records, no wave bookkeeping,
    no standing review loop** — run `/code-review medium` only if the integrated diff genuinely
    warrants fresh eyes. You keep the parallelism and the boundary safety; you drop the fixed
    ceremony that dwarfs runs this size.
  - **`W ≥ 2` and `V ≥ 5` → orchestrate.** Enough work to bank against the overhead — continue to
    the run-id line below.

  **Why the gate has two dimensions.** Orchestration overhead is roughly fixed per run — planning,
  per-agent briefs, integration passes, reviews, logging — so its cost *relative to the work*
  explodes as runs shrink. Measured across token-attributed runs (schema ≥1.9): the median
  orchestrator/implementer output-token ratio is **4.5× for runs of ≤5 agents** (worst observed: a
  2-agent run at 20×), ~1× at 6–9 agents, ~1.4× at 10–16, and **0.6–0.7× at 17+** — break-even sits
  around 6–7 agents. The width dimension catches serial work; the volume dimension catches
  small-parallel work that passes the width test and still pays a 4–20× tax. Each dimension has an
  after-the-fact mirror in the run log: `peak_width == 1` (violated width — 25% of pre-1.9 runs,
  eliminated once the gate hardened) and a small `agents_total` with a high orchestrator token share
  (violated volume — the leak this gate closes). Do not soften either dimension by planning less to
  shrink the orchestrator's share — planning stays thorough. The only lever is *not running the full
  machinery on work too small to pay for it*.
- Decompose the work into independent **tasks**. If a plan file was passed as the argument,
  start from it; otherwise build the plan with the user (use plan mode for anything non-trivial).
- Build a **file-ownership map**: for each task, the set of files it will create/modify.
- Group tasks into **waves**: tasks with **disjoint** file sets share a wave (they run in parallel);
  tasks that depend on another's output go in a later wave.
- Mint a **run id** now and reuse it for every `orchlog.py` call in this run:
  ```bash
  run_id="<branch>-$(date +%Y%m%d-%H%M%S)"
  ```
- (Optional) `TaskCreate` one task per work-item to track wave progress.

### 2. Partition rules — deciding N
N is **discovered, not forced** — only split work that is genuinely independent.
- Disjoint file sets → parallel (same wave).
- Two tasks share a file → **conflict**. Resolve by (a) one agent owns that file + both pieces, or
  (b) serialize them into different waves, or (c) make that single shared edit as its own tiny
  delegated task between waves (delegate it — don't edit it yourself).
- **Hotspot files** are conflict magnets — never let two agents touch them in parallel: router/route
  tables, DI containers, barrel `index.ts`, schema/migrations, lockfiles, shared types.
- Sequential dependency (task B needs task A's API) → N=1 for that stretch; don't fake parallelism.
- **Collapse linear chains into one brief.** A run of consecutive width-1 tasks (A → B → C, nothing
  running beside them) is **one** implementer task with a multi-step brief, not three waves — every
  width-1 wave costs a full dispatch → report → integrate round trip and banks zero parallelism.
  Measured: ~40% of logged runs carried 2+ single-agent waves, nearly all collapsible chains
  (shapes like `[3,1,1,1]`). Keep a dependent task as its own wave only when something else runs
  *beside* it in that wave, or when the chain's combined scope is too big for one agent's context —
  then split at the narrowest interface. A collapsed chain counts as **one task for the volume gate
  `V`** (step 1) — don't pad the count to clear the gate.
  integration). Give an agent `isolation: worktree` only when its change is large/risky enough to
  want its own checkout. A shared-file conflict is NOT solved by isolation (it just moves to merge
  time) — solve those by serializing / single-owner. **Caveat:** an `isolation: worktree` agent gets
  a *separate checkout*, so it (a) can't see uncommitted changes in this worktree, (b) with the
  default `worktree.baseRef=fresh` branches from `origin/<default-branch>` — it won't even see this
  branch's commits, and (c) its output must be merged back separately. So **never use it for work
  that depends on another wave or on the current state of the work** — reserve it for a
  large/risky standalone task that's fine to run from a clean origin-based checkout.

### 3. Dispatch a wave
Spawn the wave's implementers **in a single message, one `Agent` call each**, so they run in
parallel (`subagent_type: "code-implementer"`). **Choose a model tier per task and pass it
explicitly** as `model:` on each `Agent` call — this overrides the `opus` default pinned in the
agent definition. The model is a per-task decision, **orthogonal to the file partition**: two
implementers in the same wave may run different tiers.

#### Model selection — match the tier to the task
Weigh two axes against the model's scores:
- **Intelligence** — how hard the *logic* is: subtle correctness, tricky edge cases, concurrency,
  algorithms, or a design the brief doesn't fully pin down.
- **Taste** — how much *human-facing design judgment* the output needs: public API/interface shape,
  naming, UX, or code in a widely-read module.

| Model | `model:` | Cost¹ | Int. | Taste | Route here when… |
|---|---|---|---|---|---|
| Fable 5   | `fable`  | 2  | 10 | 10 | *(unavailable for delegation — never route here)* |
| Opus 4.8  | `opus`   | 5  | 8  | 8  | subtle correctness, non-trivial reasoning, or a design the brief doesn't pin down — **top available tier** |
| Sonnet 5  | `sonnet` | 8  | 6  | 6  | standard, well-specified task with a clear pattern + tight criteria — **the workhorse default** |
| Haiku 4.5 | `haiku`  | 10 | 4  | 3  | mechanical / deterministic: renames, moving files, config/JSON, boilerplate copying an obvious template |

¹ **Cost is inverted — a higher number is cheaper.** Haiku (10) is the cheapest, Fable (2) the dearest.

**The rule: pick the cheapest tier whose intelligence *and* taste both clear the task's bar** — don't
overpay for a mechanical edit, don't starve a subtle one.
- Both axes low → **Haiku**.
- Standard, well-specified, pattern-following → **Sonnet** (most delegated work lands here).
- Either axis genuinely high (hard logic *or* real design judgment) → **Opus**.
- **Fable is not available for delegation — treat Opus as the ceiling; never pass `model: "fable"`.**

**Escalate on rework.** If a cheaper-tier agent fails self-verify and you re-delegate it (a
`--rework`), bump the fix one tier (Haiku→Sonnet→Opus): a cheap agent that reworked is a signal the
task's bar was higher than you judged — don't re-run it at the same tier.

Each implementer gets a self-contained brief — implementers share no memory, so front-load everything:

```
## Task
<the one unit of work>
## Acceptance criteria   (checkable — this is the contract)
- [ ] ...
## File ownership   (modify ONLY these; if you need anything outside, STOP and report it)
- src/foo/**, tests/foo/**
## Context & conventions
<pointers to existing code, the pattern to follow, examples>
## Verification
<the exact build / test / lint commands to run for this scope>
## Rules
- If the acceptance criteria leave a real design fork open, STOP and report it as a blocker rather
  than guessing — a re-dispatch with a ruling beats a reworked wrong guess. Note trivial departures
  under deviations.
## Output
Return the IMPLEMENTER REPORT block exactly as your agent definition specifies.
```

Under-specified briefs are the #1 cause of bad delegated code. If you can't write crisp acceptance
criteria and a clean file boundary, the task isn't ready — refine the partition first.

### 4. Integrate + verify + log
- Collect each implementer's IMPLEMENTER REPORT. Read `verdict`, `build`, `tests`, `blockers`.
- A `blockers` entry naming a cross-boundary need means your partition was off — handle it (reassign
  ownership, add a serial step), don't ignore it.
- Run the **full** build + test suite yourself (running commands is orchestration, not coding) —
  **except long-log suites (e2e / UI / integration)**: delegate those to a `verifier` subagent
  (`model: "sonnet"` — it runs commands and reads, never edits). Its brief: run the exact suite
  command, triage any failures to a suspected cause, and report a compact verdict — pass/fail,
  failing case names, suspected cause, ≤20 lines, **never raw logs**. Every token of e2e output that
  lands in this session is re-read on every subsequent turn at orchestrator-tier rates; a triaged
  verdict is orders of magnitude smaller. Fixes still route to a `code-implementer` as usual.
- (Optional) spawn a `verifier` subagent against the acceptance criteria for a second opinion. It
  does read-only acceptance-checking — no code output, no taste — so pass `model: "sonnet"`; reserve
  `model: "opus"` for criteria that hinge on subtle correctness. (The reviews in step 5 pick their
  own models internally; you don't set those.)
- Anything red, or any `needs-attention`/`fail` verdict → **re-delegate a fix** to a fresh
  `code-implementer` (never patch inline). Loop back to step 3 until the wave is green.
- **Log one `agent` record per implementer** (map the report → flags):
  ```bash
  python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py record --type agent --run-id "$run_id" \
    --wave 1 --task "add foo endpoint" --files-owned 3 --files-changed 3 \
    --model sonnet --verdict pass --build pass --tests pass --isolation tree
  # --model <tier> = the model you routed this task to (opus|sonnet|haiku); feeds the model-fit
  #                  signal in `report` (see "Analyzing the harness"). Always record it.
  # flags to add when true: --deviated (deviations!=none)  --blockers (blockers!=none)
  #                         --boundary-stop (STOPped on a cross-boundary need)
  #                         --rework      (re-delegated after the agent's own work failed self-verify)
  #                         --review-fix  (delegated a /code-review or /security-review finding)
  # rework vs review-fix matters: rework is a quality signal (briefs/partition); review-fix is healthy.
  ```

### 5. Review
Both `/code-review` and `/security-review` spawn their OWN subagents internally, and subagents can't
spawn subagents — so **you (the orchestrator) must run each one yourself, directly in this session;
never delegate a review to a `code-implementer`** (it would fail or silently degrade). Invoking them
is an orchestrator action, like running build/test.

**You judge which of the two this change needs, and run each you deem necessary:**
- **`/code-review medium`** — warranted for essentially any run with real code changes; run it
  unless the diff is trivial/non-code (docs-only, pure config). **Always pass `medium`** — the no-arg
  default is `xhigh`, which burns far more tokens than a routine review needs; only go higher
  (high/max/ultra) when the user explicitly asks.
- **`/security-review`** — warranted when the diff touches a security-relevant surface: auth/authz,
  crypto, secrets, user-input handling, file/path/network I/O, deserialization, or SQL. Skip it when
  there's no plausible security impact (docs, pure refactors, test-only).

- Route every finding back to a `code-implementer` as a fix task (anti-freelance still applies); log
  each such fix agent with `--review-fix` — it's healthy follow-up, not `--rework`.
- Re-verify after fixes.

### 6. Finish + run log
- **Only if the user explicitly asks**, publish: `gh pr create ...` (and/or commit). Otherwise leave
  the worktree in place and report what was done and verified — publishing is the user's call.
- If the repo uses `project-kit`, you may reflect **in-progress** state in `docs/pm/status.json` if
  useful (keep the milestone in `now`), but **do not mark it shipped here** — the now→shipped
  transition is folded into the milestone PR by `/cleanup` (step 1), so `main` is only
  ever mutated by a merge. Marking it shipped in both places is the double-write that causes the
  cross-session `main` conflicts this workflow is designed to avoid.
- **Log the run summary** (once per run). Token capture is **automatic** — it scans this
  session's subagent + orchestrator transcripts and embeds usage **by agent type** (session
  auto-detected from cwd; pass `--no-auto-tokens` to skip):
  ```bash
  python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py record --type run --run-id "$run_id" \
    --branch "<branch>" --milestone "<desc>" --waves 2 --agents 5 \
    --outcome success --build-final pass --tests-final pass --review-findings 2
  # add --pr-created if you opened a PR.
  # Do NOT pass --fix-iterations: it is derived automatically from this run's agent records
  #   (the --rework / --review-fix tags you logged per implementer), so it can't drift from
  #   reality. It survives only as a manual override; leave it off.
  # peak_width + wave_widths are ALSO derived automatically from this run's per-wave agent
  #   records — nothing to pass. peak_width==1 flags a run that shouldn't have been orchestrated.
  # Token capture is automatic in a dedicated worktree session (the norm) and now buckets by the
  #   agent's .meta.json customAgentType, so async in_process_teammate implementers land in
  #   `code-implementer` (pre-1.7 they leaked into `review`). If you reuse one session across runs,
  #   also pass --since "<run-start ISO>" to scope the scan.
  ```

## Management principles
- **Self-contained briefs** — every agent gets all the context it needs; no shared memory.
- **Acceptance criteria are the contract** — verify against them, not against vibes.
- **Verification gate** — nothing is "done" until build + tests are green and criteria are met.
- **Bounded autonomy** — agents have a hard file boundary and a STOP-and-report rule; that is what
  lets them run in parallel safely and keeps humans out of the loop until a real decision is needed.
- **Fixes are always re-delegated** — never inline-patch; the fix gets the same boundary + gate.
- **Right-size the model** — each task gets the cheapest tier that clears its intelligence + taste
  bar (step 3's table); escalate a tier on rework.

## Analyzing the harness (closing the loop)
Periodically review accumulated runs to improve this workflow and the agent definitions:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py report --recent 20
```

**Quality signals**: high **boundary_stop** rate → partitioning too coarse or boundaries wrong; high
**avg rework/run** (re-delegations after a failed self-verify, derived from agent tags) → briefs
under-specified or tasks too big; high **deviated** → acceptance criteria not tight enough; the
**verdict** mix shows overall health and parallel utilization. **avg review-fix/run** is derived and
tracked separately as *healthy* (review findings routed to fixes) — it never counts against brief
quality. Both per-run averages come straight from the per-agent `--rework` / `--review-fix` tags, so
they can't be inflated by a stale hand-entered count.

**Parallelism signal**: **avg peak width** and the **serial runs (peak==1)** count expose gate leaks —
any `peak_width == 1` run paid full orchestration overhead and banked no parallelism (it violated the
`W ≥ 2` gate in step 1 and should have been a normal session or a single implementer). Watch this
alongside the cost block: a peak==1 run is pure orchestrator overhead with nothing to amortize it.

**Model-fit signal** (the AGENT block's `model:` + `rework by model:` lines): checks whether the
step-3 routing is calibrated. **Rework clustered in a cheap tier** (e.g. `haiku=2/3`) → you're routing
too aggressively — those tasks' bars were higher than judged; lean harder on the escalation rule or
default them a tier up. **Everything on `opus`** → the routing isn't banking the cost the table
offers; more tasks likely belong on Sonnet/Haiku. Read it next to the COST block — the two together
say whether cheaper models are saving tokens without buying rework.

**Cost signals** (the COST block, captured automatically): **output by type** shows where tokens go —
if `orchestrator` dominates, the orchestration overhead itself is the cost (the fix is to delegate
more coarsely or, for serial/small jobs, not orchestrate at all — see the hard gate in step 1 — **not**
to plan less; thorough planning is a feature, not the leak). Buckets are keyed off each agent's
`.meta.json` `customAgentType` (schema ≥1.7); **pre-1.7 numbers are unreliable** — async
in_process_teammate implementers leaked into `review`, so `code-implementer` read as ~0 and `review`
was inflated (only compare runs at the same schema version). The `review` bucket is the genuine cost of
`/code-review` + `/security-review`; **~rework output** is tokens burned on rework, tying the `rework`
quality signal directly to a dollar-shaped number. For an ad-hoc look at the current session without
logging a run:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py tokens          # output/total by agent type
```

When you change this skill or the agent definitions in response to these signals, bump
`WORKFLOW_VERSION` in `orchlog.py` so before/after runs stay comparable.
