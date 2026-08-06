---
name: taskplan
description: >
  Decompose a spec into atomic, independent tasks with checkable acceptance criteria, an explicit
  file boundary, a model tier, and an implementation method — then derive parallel waves and write
  docs/plan/<slug>.json. The output is consumed directly by /implement (its step 1 accepts a
  plan-file path). Use after /spec, before /implement, for multi-task work.
trigger: /taskplan
user-invocable: true
argument-hint: "<path to docs/spec/<slug>.md | feature description>"
allowed-tools: ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "AskUserQuestion"]
---

# /taskplan

Turn a spec into a **buildable, partitioned plan**. This is the *plan* stage of the
spec → taskplan → implement pipeline. It benchmarks agent-skills `planning-and-task-breakdown` and
folds in `/implement`'s partition rules (steps 1–2) so the plan it emits is something
`/implement` can consume with zero re-planning.

**The key seam:** `/implement` already accepts a plan-file path as its argument ("If a plan file
was passed as the argument, start from it"). So this skill's whole job is to produce a plan file in
the shape that makes `/implement`'s partition nearly free — every task already carries its
`files_owned`, `depends_on`, model tier, and method.

## When to use

- **Use** after `/spec` (or with a clear feature description) when the work is more than one task.
- **Skip** for a single obvious task — dispatch one implementer directly; a plan buys nothing.
- Output feeds `/implement docs/plan/<slug>.json`.

## Process

### 1. Read the source
If the argument is a path to `docs/spec/<slug>.md`, read it — it's the contract. Otherwise build a
quick spec sketch in your head from the description (and consider running `/spec` first if the
"what" is fuzzy). Reuse `<slug>` from the spec.

### 2. Decompose into atomic tasks
Break the work into the smallest **independent** units:
- **Size** — aim ~100 lines of change per task. Bigger → split; trivially tiny → merge.
- **Acceptance criteria** — each task gets a checkable contract (a test passes, an output matches).
  If you can't write crisp criteria, the task isn't understood yet — refine it.
- **File ownership** — for each task, the exact globs/paths it will create or modify. This is the
  boundary that makes parallelism safe.

### 3. Partition — draw the file-ownership map (/implement rules)
- **Disjoint file sets → can run in parallel** (same wave).
- **Two tasks share a file → CONFLICT.** Resolve by (a) one task owns that file + both pieces, or
  (b) serialize them via `depends_on`, or (c) split the shared edit into its own tiny task.
- **Hotspot files are conflict magnets — never in two tasks' boundaries at once:** router/route
  tables, DI containers, barrel `index.*`, schema/migrations, lockfiles, shared types.
- **Sequential dependency** (task B needs task A's API) → set `depends_on: ["A"]`; don't fake
  parallelism.

### 4. Route a model tier per task (/implement step-3 table)
Pick the cheapest tier that clears both the task's *intelligence* and *taste* bar:
- **haiku** — mechanical/deterministic: renames, moving files, config/JSON, boilerplate.
- **sonnet** — standard, well-specified, pattern-following (the workhorse default; most tasks).
- **opus** — subtle correctness, tricky edge cases, or real human-facing design judgment.
- Fable is **not** available for delegation — never route there.

### 5. Attach the method (the implement-stage benchmark)
Every task inherits `defaultMethod` unless it overrides. The default encodes tdd + source-driven +
incremental, and `/implement` injects it into each code-implementer brief's `## Method` section:
- **tdd** — "Write the failing test first (red), then the minimal code to pass (green), then
  refactor. Test files must sit inside this task's files_owned."
- **sourceDriven** — "Ground every API/library decision in official docs (context7/WebFetch); cite
  the source. Do not guess an API surface."
- **incremental** — "Ship the thinnest vertical slice that meets the criteria; gate risky/incomplete
  paths behind a feature flag with a safe default."

Override per task only when warranted (e.g. a docs-only task relaxes `tdd`).

> Method placement note: keep each task's `files_owned` inclusive of its own test files, or the tdd
> rule collides with the boundary. Shared test fixtures/harnesses are hotspots — treat them like any
> other shared file in step 3.

### 6. Derive waves + parallel width
Topologically order tasks: a task lands in the earliest wave after all its `depends_on` are in
earlier waves AND its `files_owned` are disjoint from every other task already placed in that wave.
**Collapse linear chains first**: consecutive tasks that would each sit alone in their wave (A → B
→ C with nothing beside them) merge into one task with a multi-step brief — width-1 waves are pure
dispatch overhead in `/implement`. Then compute **`parallelWidth W`** = the size of the widest
wave, and **`V`** = the task count after collapsing.
- **`W >= 2` and `V >= 5`** → real parallel work at real volume; `/implement` is justified.
- **`W >= 2` but `V <= 4`** → parallel but small. Record it, and **note**: "Small-parallel work —
  `/implement`'s volume gate will route this to direct dispatch (parallel implementers, no run
  machinery)." Don't pad the task count to clear the gate.
- **`W == 1`** → the work is serial (every wave has one task). Record it, and **warn**: "Serial work
  — `/implement`'s W>=2 gate will reject this; route to a single `code-implementer` or a normal
  session instead." Don't invent fake parallelism to dodge the gate.

### 7. Write `docs/plan/<slug>.json`
Conform to `docs/pm/schema/plan.schema.json` (if the repo has it — project-kit repos do). Include
`slug`, `spec` (path or ""), `createdWith`,
`defaultMethod`, `tasks[]`, `waves[]`, `parallelWidth`. Then validate it parses and matches the
schema (`python3 -c "import json,sys; json.load(open(sys.argv[1]))" docs/plan/<slug>.json`; if
`jsonschema` is installed, check against the schema too).

### 8. Report + hand off
Print: task count, the wave layout (which tasks in which wave), `W`, and schema-valid ✓. Then the
next step: **`/implement docs/plan/<slug>.json`** (or, if `W == 1`, the single-implementer route;
if `V <= 4`, note that `/implement` will take its direct-dispatch path).

## Rules
- **Independence is discovered, not forced** — only split what's genuinely independent; don't shard a
  serial job into fake parallel tasks.
- **Acceptance criteria are the contract** — no task without checkable criteria.
- **File ownership is the safety boundary** — disjoint or it's not parallel.
- **Right-size the model** — cheapest tier that clears the bar; don't default everything to opus.
- **Don't implement here** — /taskplan produces the plan; the code belongs to the implementers.

## Red flags
- A task has no acceptance criteria, or "make it work" as its only one → not ready.
- Two tasks in the same wave list the same file → partition is wrong; re-do step 3.
- Every wave has one task (`W == 1`) but you still recommend orchestrating → stop; it's serial.
- A hotspot file appears in two boundaries → serialize or single-owner it.
- Everything routed to `opus` → you're not banking the tier savings; recheck step 4.

## Verification
- [ ] `docs/plan/<slug>.json` exists, is valid JSON, and matches `plan.schema.json`.
- [ ] Every task has criteria, a disjoint-within-wave `files_owned`, a model tier, and a method.
- [ ] `waves` are consistent with `files_owned` (disjoint per wave) and `depends_on` (deps earlier).
- [ ] `parallelWidth` equals the widest wave; if `W == 1`, the serial warning was surfaced.
- [ ] Reported the layout and pointed at `/implement docs/plan/<slug>.json`.
