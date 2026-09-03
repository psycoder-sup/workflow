---
name: implement-orc
description: >
  Build a parent issue's sub-issue graph as an ORCHESTRATOR with workers: 1 parent = 1 worktree =
  1 integration branch = 1 PR. Reads the dependency-linked sub-issues, picks chain mode (one worker
  walks the whole graph) or fan-out mode (one fresh worker per ticket in file-disjoint waves) from
  the graph shape, briefs workers per the implement-core doctrine under a frozen campaign header,
  verifies and lands each slice as a `Ticket: #<n>` commit, and ships one PR that closes every
  child. The orchestrator NEVER writes implementation code. Workers are general-purpose subagents
  briefed with the full doctrine by default; --orca runs each worker as a `claude` session in its
  own Orca terminal.
  Use ONLY when the user explicitly asks for an orchestrated build — the default build skill is
  /implement (the session implements everything itself).
trigger: /implement-orc
user-invocable: true
argument-hint: "<parent issue number, e.g. 42> [--orca] [--dry-run]"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent", "AskUserQuestion", "EnterWorktree", "ExitWorktree", "Skill", "SendMessage"]
---

# /implement-orc

Build a parent issue end-to-end as an **orchestrator**: read the live sub-issue graph from GitHub,
dispatch workers, verify and land each slice as a commit on ONE integration branch, and finish with
ONE PR that closes every child. **You never write the implementation yourself.**

This is the opt-in sibling of [`/implement`](../implement/SKILL.md). `/implement` builds the graph
in the session itself and is the default; this skill exists for when the user explicitly wants
workers — visible Orca panes, a wide graph they want fanned out, or an experiment. Same pipeline
position (after `/taskplan`), same branch shape, same trailers, same PR — a campaign started with
either skill can be resumed with either, because all state lives in GitHub and the branch.

**The shape is fixed: 1 parent = 1 worktree = 1 branch = 1 PR.** Refuse a parent whose own
`blocked-by` (parent-to-parent) edges are still open — its predecessor hasn't shipped.

**Transport**: workers are `general-purpose` subagents by default. With **`--orca`**, each worker is
a `claude` CLI session in its own Orca terminal (visible panes, runtime task/dispatch provenance) —
see Step 4. Neither transport has a worker agent definition: **the brief is the agent definition**,
which is why W-0 puts implement-core and WORKER.md in full at the top of every brief, both transports
alike.

## The roles (keep them separate)

- **Orchestrator (you, this session)** — read the graph, route tiers, compose briefs, run commands
  (build/test/git), integrate, land commits, decide.
- **Worker** — implements per the [`implement-core`](../implement-core/SKILL.md) doctrine (contract
  selection, CONTEXT.md/ADR discipline, the prescribed method, self-verify) plus the worker overlay
  in [`WORKER.md`](./WORKER.md) (brief layout, file boundary, git duties, STOP, IMPLEMENTER REPORT).
  One worker walks the whole graph (chain mode) or one fresh worker builds one ticket (fan-out mode).
- **`verifier` subagent (optional)** — independently reproduces build/tests, read-only.
- **`/code-review`, `/security-review`** — fresh-eyes review of the integrated diff at the end.

## Anti-freelance rule (the one rule that makes this work)

**You do not write or edit implementation code. Ever.** Not for the first ticket, not for a "just
one-line" fix found during verification, not for review findings. All code changes go through a
worker. Your Write/Edit access is for orchestration artifacts only. You *do* run commands: build,
test, and **git** — committing, pushing, and landing verified slices is orchestration, not coding.

**Why the rule exists, so it survives the next redesign:** the orchestrator is the one context that
grades the work without having written it, and composes the PR against the issues rather than
against the transcript that produced the code. That independence is the thing this skill buys over
`/implement`; freelancing spends it. If you don't want that property, you want `/implement`.

**What it costs, so nobody is surprised:** measured on a 7-ticket chain, one worker per ticket ran
2.9× the wall-clock, 2× the cost and 3× the diff of a single context, and lost a spec-level testing
constraint that no worker held. Chain mode, the frozen header and `## Parent constraints` exist to
contain exactly that. Across 22 logged runs the orchestrator was the largest output bucket.

## Preconditions

- **`gh` ≥ 2.94** — the native sub-issue/dependency flags landed in 2.94. Check once; older → stop.
- The argument resolves to an open GitHub issue: **a parent with sub-issues** → the graph walk; **a
  standalone issue with no sub-issues** → one worker, one ticket, verify, land, PR via `/cleanup`.
- The issue's own `blockedBy` must be all closed. An open blocker on the *parent* means a sibling
  parent hasn't shipped — report and stop.

### Branch policy — the branch you're on decides everything

Run `git branch --show-current` first (with `--orca`, use the Orca worktree resolution in Step 4
instead):

- **On `main`/`master`** → `EnterWorktree({ name: "feat/<slug>" })`. The branch comes out sanitized
  as `worktree-feat+<slug>` — expected; **do not rename it**.
- **On any other branch** → that branch IS the integration branch; never create another. Rename an
  auto-generated placeholder in place with `git branch -m feat/<slug>`; keep a meaningful name as-is.
- Never `git checkout -b`.

## Step 1 — Resolve the graph, resume if a campaign exists

```bash
gh issue list --state all --json number,title,state,labels,assignees,parent,blockedBy,blocking \
  --jq '[.[] | select(.parent.number == <parent>)]'
```

Fetch **all states** — the resume check needs closed children too.

**Hard guards, before anything else:**

- **Never dispatch the parent.** The scope issue itself is a spec, not a ticket.
- **An issue with no acceptance criteria is not a ticket** — no `## Acceptance criteria` section and
  no agent-brief comment means refuse it and say why.
- **Resolve the agent-ready label** from `docs/agents/triage-labels.md`; fall back to
  `ready-for-agent`. Name the label you resolved.
- A child **assigned to someone else** means another session holds part of this parent — stop.

**Resume first — the parent comment is the pointer.** A previous `🛠️ /implement …` or
`🛠️ /implement-orc …` comment names the branch; adopt it and read what landed:

```bash
git log origin/<branch> --format=%B | grep '^Ticket: #' | sort -u
```

Continue from the first unlanded ticket. All campaign state is derivable; a died session costs
nothing but the restart.

**On `--dry-run`:** print the mode (chain or fan-out), walk order, wave structure, and tier routing
(Step 3), then stop. Claim nothing, comment nothing, dispatch nothing.

## Step 2 — Claim the set, announce the campaign, build the header

**Claim every open child up-front** — blocked ones included:

```bash
gh issue edit <n> --add-assignee @me   # once per child
```

Then post one comment on the parent (skip if resuming and it exists):

```bash
gh issue comment <parent> --body "🛠️ /implement-orc is working this parent on branch \`<branch>\` — one integration branch, one PR. Children stay open until it merges."
```

### Build the campaign header — once, here

Assemble block `[A]` of [`WORKER.md` W-0](./WORKER.md) now, before any dispatch: the implement-core
doctrine and WORKER.md, the orientation digest (CONTEXT.md/CONTEXT-MAP.md glossary excerpt, the ADR index for
the area this parent touches, repo conventions, the **exact** build / test / typecheck commands
resolved from CI config or package scripts, and **`## Parent constraints`** — the parent issue's
`Implementation Decisions` and `Testing Decisions` sections pasted verbatim), and the IMPLEMENTER
REPORT format.

Resolve those commands **here, not per worker**. Then **freeze it**: paste the same bytes into every
brief for the rest of the campaign, subagent and Orca alike. On resume, rebuild it the same way from
the same sources. If it genuinely has to change mid-campaign (a new ADR lands), that is a new header
from that point and one accepted cold start — say so in your report.

## Step 3 — Chain or fan-out — the graph decides, once, up front

Each `/taskplan` sub-issue body carries an advisory block:

```
<!-- taskplan: {"files_owned": [...], "model": "opus", "method": "tdd"} -->
```

Parse it for the file boundary, tier, and method. **Missing block** → judge all three at dispatch
time yourself; say you did.

Topologically order the open, unlanded children by `blockedBy`. **A blocker counts as satisfied when
its ticket is landed on the integration branch** (its `Ticket: #<n>` trailer exists) — not when its
issue closes. Compute the waves from `blockedBy` + `files_owned` before dispatching anything, then
pick the mode for the whole campaign:

- **Chain mode** — fewer than half the tickets can run in a wave of width ≥ 2. Dispatch **one
  worker for the whole graph**: header `[A]` as usual, ticket block `[B]` holding every contract in
  walk order. Landing duty is transferred — the worker commits each ticket as it finishes with the
  `Ticket: #<n>` trailer (WORKER.md W-2), so resume still works. You verify once, at the end.
  **A chain worker can overflow too**: if it returns partial, or its report shows it re-deriving
  header facts, re-dispatch a fresh worker from the first unlanded trailer — the resume path.
- **Fan-out mode** — the graph is genuinely wide. One fresh worker per ticket. Dispatch each wave in
  a single message, one worker each, **only where `files_owned` are disjoint**; after the wave
  verifies, land each ticket as its own commit in ranked order. Overlapping or unknowable ownership
  within a wave → serialize, ranked by `blocking` count descending, tie-break on issue number.
- **Hotspot files** (routers, DI containers, barrel `index.*`, schema/migrations, lockfiles, shared
  types) are conflict magnets — never in two same-wave boundaries.
- **Never use `isolation: worktree` agents for tickets.** An isolated agent branches from
  `origin/main`, not this integration branch — it can't see any landed slice. Wrong base, silently.

### Model routing

| Tier | Route here when… |
|---|---|
| `opus` | **the default** — and always in chain mode, where one worker carries the whole graph |
| `sonnet` | a ticket that touches no hotspot file and follows an existing pattern exactly — one-clause justification |

Sonnet took ~2.7× the turns of opus on shared-file tickets (120 vs 367 turns, 16 vs 25 min, $12 vs
$20) — the unit-price saving cancels and the clock loses. **These two tiers are the whole table.**
Fable is not available for delegation, and **`haiku` is retired** — across 24 logged haiku agents it
reworked at 12.5% against sonnet's 3.2%. Older tickets carrying `"model": "haiku"` → read as
`sonnet`. **Escalation on rework means opus.** Caches are model-scoped: on a genuine toss-up within
a wave, prefer the wave's dominant tier; never under-route a ticket that needs opus for the cache.

### The brief

Lay every brief out per WORKER.md W-0: the **frozen header from Step 2, pasted unchanged**, then
the **ticket block** — the **contract verbatim** (implement-core §1's table decides body vs
agent-brief comment — fetch with `--comments`), the ticket's **method**, the **file boundary** (fan-out only; in a chain
the branch is the boundary), and — fan-out, second wave on — **`## Landed so far`**: the `summary`
and `files_changed` lines of every previous IMPLEMENTER REPORT, so a fresh worker inherits the
conventions its siblings just set.

Never restate a header fact inside the ticket block, and never let a ticket number, file list or
tier name drift up into the header — either breaks the shared prefix for every worker. Front-load
everything; workers share no memory.

## Step 4 — Dispatch

### Default transport — subagents

Spawn each wave's workers in a single message, one `Agent` call each
(`subagent_type: "general-purpose"`, explicit `model:` per the routing, the brief as the prompt).
A general-purpose agent knows nothing about tickets until the brief tells it — never send a bare
contract without header `[A]`. Dispatching a wave in one
message also keeps its shared header warm across the wave.

### `--orca` transport — Orca terminal workers

**Step 0 (once):** invoke the user-level **`orchestration`** skill via the Skill tool and follow it
for all coordination mechanics — terminal creation, `task-create`, `dispatch --inject`, rolling
`check --wait`, `reply`, `worker_done`, teardown. Not available → stop and tell the user. Also
verify `orca status --json` shows a running runtime. This is supervised orchestration, not a
handoff. Worktree resolution replaces the branch policy: already inside an Orca worktree → workers
get `--worktree active`; on `main` in the primary checkout → `orca worktree create --name
feat-<slug> --no-parent --json` first and target its id.

Per worker (mechanics per the orchestration skill; illustrative shapes):

```bash
orca terminal create --worktree active --title <ticket-slug> \
  --command "claude --model <tier> --dangerously-skip-permissions" --json
orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json   # not optional
orca orchestration task-create --spec "<brief>" --json
orca orchestration dispatch --task <task_id> --to <handle> --inject --json
```

Orca workers are top-level claude sessions, so — exactly as for subagents — the brief must carry
implement-core and WORKER.md inline in full (boundary, STOP-via-`ask` rule, report block). It carries the **same campaign header bytes** as a subagent brief; that is how
`--orca` gets the same shared prefix. The tier lives in the argv, so **escalation means a new
terminal**, not a re-dispatch. Supervise per the orchestration skill: rolling `check --wait` for
`worker_done`/`escalation`; a timeout is a checkpoint, not a failure; answer `ask`s with `reply`;
never kill a working worker.

Close worker terminals at the end of the run, not between waves. An idle same-tier terminal may be
re-targeted for a later ticket, but **you reuse the terminal, never the context**: `/clear` it first.
`/clear` discards the session's cache too, so terminal reuse saves process startup, not tokens.

## Step 5 — Integrate, verify, land

**Chain mode:** read the worker's final report, confirm one `Ticket: #<n>` commit per ticket exists,
run the full build + test suite once on the integrated branch (bisect by the per-ticket commits if
red), push, log one agent record (`--executor subagent|orca --tickets N`). Red → re-dispatch the fix
to a fresh `opus` worker from the offending trailer.

**Fan-out mode, per ticket:**

1. **Read the IMPLEMENTER REPORT** (`verdict`, `build`, `tests`, `blockers`). A `blockers` entry
   naming a cross-boundary need means the partition was off — reassign ownership or serialize;
   don't ignore it.
2. **Verify yourself**: run the full build + test suite. Delegate long-log suites to a `verifier`
   subagent (`model: "sonnet"`) that returns a triaged ≤20-line verdict — never raw logs into this
   session.
3. Anything red or `needs-attention`/`fail` → **re-delegate the fix; never patch inline.**
   - **Same slice, same tier** (a review finding, a failed assertion on work otherwise on track) →
     **continue the worker that built it** — subagent: `SendMessage`; Orca: `reply` on its task.
   - **Escalating a tier** (the original failed its own self-verify) → **a fresh worker** on opus.
   - **The approach was wrong at root**, or the worker is gone → **a fresh worker** at the same tier;
     a warm context that went down the wrong path is a liability.

   Log `--rework` in all three cases.
4. **Land it** — one commit per ticket, committed by you:

   ```
   <type>: <ticket title> (#<n>)

   <one or two lines: what the slice delivers, how it was verified>

   Ticket: #<n>
   ```

   Then **push the branch** — an unpushed landing is state only this session knows.
5. **Log one agent record** per worker:

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py record --type agent --run-id "$run_id" \
     --executor subagent --wave <position> --task "<ticket title>" --files-owned N --files-changed N \
     --model <tier> --verdict pass --build pass --tests pass --isolation tree
   # --executor orca under --orca. flags when true: --deviated --blockers --boundary-stop --rework --review-fix
   ```

   Mint the run id once at campaign start: `run_id="<branch>-$(date +%Y%m%d-%H%M%S)"` — prefix
   `orca-` under `--orca`.
6. Move to the tickets this landing unblocked.

**If a worker STOPs** (design fork, cross-ticket need, ADR conflict): everything downstream is
blocked by definition. Surface the ticket number and the worker's question to the user. Never skip
past an unlanded blocker, and never answer a design fork on the spec's behalf.

## Step 6 — Finish: review, one PR, hand to /cleanup

When every child has landed:

1. **Full suite once more** on the integrated branch.
2. **Reviews**: `/code-review` is `disable-model-invocation` — pause and ask the user to type
   **`/code-review medium`**. Under `--orca`, run it in a dedicated review worker terminal instead
   (`claude --model opus --dangerously-skip-permissions`, send the slash commands as terminal input,
   read findings back). Run **`/security-review`** yourself via the Skill tool when the diff touches
   auth/authz, crypto, secrets, user input, file/path/network I/O, deserialization, or SQL. Route
   every finding to a fresh fix worker (`--review-fix`), land, push.
3. **Compose the PR body yourself** — title from the parent; one summary line per landed ticket in
   walk order; **one `Closes #<n>` line per child — all of them**; a `Parent: #<parent>` line.
   **Never `Closes #<parent>`** — `/cleanup` closes the parent after the merge.
4. **Ask before publishing.** On approval: rebase onto `origin/main`, push, `gh pr create` — then
   invoke **`/cleanup`** via the Skill tool.
5. **Log the run** (once):

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py record --type run --run-id "$run_id" \
     --mode chain|fanout --tickets N --branch "<branch>" --milestone "<parent title> (#<parent>)" \
     --waves N --agents N --outcome success --build-final pass --tests-final pass --review-findings N
   # add --pr-created if you opened the PR. Under --orca ALWAYS add --no-auto-tokens (worker
   # transcripts live outside this session; the auto-scan would report misleading buckets).
   ```

6. **Record the stage cost**:

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/stats/stats.py record --issue <parent> --stage implement
   ```

7. **Report**: the walk table (ticket → tier → verdict → commit), the PR link, and campaign state.

## Rules

- **Scope is one parent.** Never sweep the repo; never dispatch the parent itself.
- **No acceptance criteria → not a ticket.**
- **Claim all children up-front; announce on the parent.**
- **The campaign header is built once and frozen.** Byte-identical in every brief, both transports;
  no ticket number, file list or tier name in it.
- **Chain: one worker, the whole graph, in walk order. Fan-out: one fresh worker per ticket, disjoint
  files only, same tree.** Never mix within a campaign. The only continuation allowed is a same-tier
  rework of the slice that worker just built.
- **Landed = trailer on the pushed branch. Closed = merged to main.** Never close a child by hand.
- **Push after every landing** (chain mode: when the worker returns).
- **Opus by default; justify each `sonnet`; a sonnet rework goes to opus.**
- **A STOP holds the walk.**
- **Anti-freelance, always.** You commit and push; you never write source.
- **Ask before the PR.** `--dry-run` stops before claiming anything.

## Red flags

- You're about to `Edit` a source file → anti-freelance violation. Delegate it.
- Two briefs whose headers differ by even one byte → the shared prefix is gone. Diff them against
  the Step 2 header.
- A worker's report shows it grepping for the test command or re-reading the glossary → the header
  didn't carry what it should.
- A report says `blockers: <another ticket's work>` → the graph's edges are wrong or the walk order
  ignored one.
- A run with `peak_width == 1` and more than one agent record → a chain run in fan-out mode; it
  should have been one worker.
- `git log` shows a trailer for a ticket still in your queue → re-run the resume grep.
- The PR body is missing a child's `Closes` line → that child stays open forever.
- The parent appears in your dispatch list → a spec is not a ticket.
- You're reaching for this skill because the graph "looks big" → size is not the trigger; the
  user's request is. `/implement` relays on overflow.

## Analyzing the harness

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py report --recent 20
```

Filter mentally to `mode=chain|fanout` (plus `legacy`, which is all pre-4.0.0 orchestrated runs).
**Quality**: high `boundary_stop` → partitioning wrong; high rework → briefs under-specified or
slices too big; high `deviated` → criteria not tight. **Model fit**: rework clustered in a cheap
tier → route those up. **Cost**: an orchestrator-dominated run is overhead-heavy — coarser slices
in `/taskplan`, not less planning. Worker reuse is not an alternative — carried context is billed on
every turn. Ignore the COST block for `orca-` runs (worker tokens uncaptured). When you change this
skill or the agent definitions in response, bump `WORKFLOW_VERSION` in `orchlog.py`.
