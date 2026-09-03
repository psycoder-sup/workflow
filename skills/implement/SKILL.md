---
name: implement
description: >
  Build a parent issue's sub-issue graph as an orchestrator: 1 parent = 1 worktree = 1 integration
  branch = 1 PR. Walks the dependency-linked sub-issues in graph order — one worker for the whole
  graph when it is a chain (chain mode), one fresh worker per ticket in parallel waves when tickets
  are file-disjoint (fan-out mode); built-in code-implementer subagents by default, --orca for
  Orca-terminal workers — verifying and landing each slice as a `Ticket: #<n>` commit, then shipping
  one PR that closes every child. Workers follow the implement-core doctrine; the orchestrator NEVER writes
  implementation code. Also takes a single triaged issue (no sub-issues) as a one-worker build.
  Use after /taskplan has published the sub-issues.
trigger: /implement
user-invocable: true
argument-hint: "<parent issue number, e.g. 42> [--orca] [--dry-run]"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent", "AskUserQuestion", "EnterWorktree", "ExitWorktree", "Skill"]
---

# /implement

Build a parent issue end-to-end as an **orchestrator**: read the live sub-issue graph from GitHub,
dispatch one worker for the whole graph when it is a chain or one fresh worker per ticket when it
is wide, verify and land each slice as a commit on ONE integration branch, and finish with ONE PR
that closes every child. **You never write the implementation
yourself.**

This is the build stage of the pipeline: `/spec` published the parent issue (the spec), `/taskplan`
decomposed it into sub-issues with native `blocked-by` edges and per-ticket metadata. **The issue
graph IS the plan** — there is no plan file.

**The shape is fixed: 1 parent = 1 worktree = 1 branch = 1 PR.** If a feature is too wide for one
PR, that was `/spec`'s split decision — it published sibling parents, and cross-parent parallelism
is simply running `/implement` twice in two sessions. Refuse a parent whose own `blocked-by`
(parent-to-parent) edges are still open — its predecessor hasn't shipped.

**Transport**: workers are built-in `code-implementer` subagents by default. With **`--orca`**, each
worker is a `claude` CLI session in its own Orca terminal (visible panes, runtime task/dispatch
provenance) — see the Orca transport section; the doctrine is identical either way.

## The roles (keep them separate)

- **Orchestrator (you, this session)** — read the graph, route tiers, compose briefs, run commands
  (build/test/git), integrate, land commits, decide.
- **Worker** — implements ONE ticket per the [`implement-core`](../implement-core/SKILL.md)
  doctrine: contract selection, CONTEXT.md/ADR discipline, the prescribed method, self-verify, the
  IMPLEMENTER REPORT. One ticket, one fresh worker, always — a worker never crosses into a second
  ticket, though it may be sent back to rework the slice it just built (Step 5.3).
- **`verifier` subagent (optional)** — independently reproduces build/tests, read-only.
- **`/code-review`, `/security-review`** — fresh-eyes review of the integrated diff at the end.

## Anti-freelance rule (the one rule that makes this work)

**You do not write or edit implementation code. Ever.** Not for the first ticket, not for a "just
one-line" fix found during verification, not for review findings. All code changes go through a
worker. Your Write/Edit access is for orchestration artifacts only. You *do* run commands: build,
test, and **git** — committing, pushing, and landing verified slices is orchestration, not coding.

## Preconditions

- **`gh` ≥ 2.94** — the native sub-issue/dependency flags (`--parent`, `--blocked-by`,
  `--json parent,subIssues,blockedBy,blocking`) landed in 2.94. Check `gh --version` once; older →
  stop and say so.
- The argument resolves to an open GitHub issue. Two shapes are valid:
  - **A parent with sub-issues** (the `/taskplan` output) → the full graph walk below.
  - **A standalone issue with no sub-issues** (a `/triage`d bug, a hand-written ticket) → the
    **single-worker path**: one worktree, one worker briefed per implement-core, verify, land, PR
    via `/cleanup`. No claim-all, no walk machinery, no run log. The rest of this document is the
    graph case.
- The issue's own `blockedBy` must be all closed (`gh issue view <n> --json blockedBy`). An open
  blocker on the *parent* means a sibling parent hasn't shipped — report and stop.

### Branch policy — the branch you're on decides everything

Run `git branch --show-current` first (with `--orca`, use the Orca worktree resolution in the
transport section instead):

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

- **Never dispatch the parent.** The scope issue itself is a spec, not a ticket.
- **An issue with no acceptance criteria is not a ticket** — no `## Acceptance criteria` section in
  its body and no agent-brief comment means refuse it and say why.
- **Resolve the agent-ready label** from `docs/agents/triage-labels.md` (the `ready-for-agent` row's
  right-hand column); fall back to the literal `ready-for-agent` if absent. Name the label you
  resolved — an empty graph caused by a label mismatch looks identical to "no work".
- A child **assigned to someone else** means another session holds part of this parent — stop and
  report. This walk cannot share its parent: its blockers clear on the integration branch, which
  the other worker can't see.

**Resume first — the parent comment is the pointer.** Check the parent's comments for a previous
campaign announcement (`🛠️ /implement …`). If one exists, adopt the branch it names, get on it, and
read what already landed:

```bash
git log origin/<branch> --format=%B | grep '^Ticket: #' | sort -u
```

Continue from the first unlanded ticket. All campaign state is derivable — the comment names the
branch, the trailers name the landed tickets, GitHub names the graph. No session-local state exists,
so a died session costs nothing but the restart.

**On `--dry-run`:** print the mode (chain or fan-out), walk order, wave structure, and tier routing
(Step 3), then stop.
Claim nothing, comment nothing, dispatch nothing.

## Step 2 — Claim the set, announce the campaign

**Claim every open child up-front** — blocked ones included; the set travels together:

```bash
gh issue edit <n> --add-assignee @me   # once per child
```

The assignee set is the campaign lock against any concurrent session touching this parent. Then post
one comment on the parent (skip if resuming and it exists):

```bash
gh issue comment <parent> --body "🛠️ /implement is working this parent on branch \`<branch>\` — one integration branch, one PR. Children stay open until it merges."
```

### Build the campaign header — once, here

Assemble block `[A]` of [`implement-core` §0](../implement-core/SKILL.md) now, before any dispatch:
the doctrine, the orientation digest (CONTEXT.md/CONTEXT-MAP.md glossary excerpt, the ADR index for
the area this parent touches, repo conventions, the **exact** build / test / typecheck commands
resolved from CI config or package scripts, and **`## Parent constraints`** — the parent issue's
`Implementation Decisions` and `Testing Decisions` sections pasted verbatim), and the IMPLEMENTER
REPORT format.

Resolve those commands **here, not per worker** — every worker that has to rediscover the test
command spends its own context on a fact you already know. Then **freeze it**: paste the same bytes
into every brief for the rest of the campaign, subagent and Orca alike. On resume, rebuild it the
same way from the same sources. If it genuinely has to change mid-campaign (a new ADR lands), that
is a new header from that point and one accepted cold start — say so in your report.

## Step 3 — Walk the graph

Topologically order the open, unlanded children by their `blockedBy` edges. **A blocker counts as
satisfied when its ticket is landed on the integration branch** (its `Ticket: #<n>` trailer exists)
— not when its issue closes. Children stay open by design until the final PR merges: the branch is
the ledger, the trailers are the entries.

### Per-ticket metadata

Each `/taskplan` sub-issue body carries an advisory block:

```
<!-- taskplan: {"files_owned": [...], "model": "opus", "method": "tdd"} -->
```

Parse it for the file boundary, tier, and method. **Missing block** (hand-written or triaged ticket)
→ judge all three at dispatch time yourself; say you did.

### Chain or fan-out — the graph decides, once, up front

Compute the waves from `blockedBy` + `files_owned` before dispatching anything, then pick the mode
for the whole campaign:

- **Chain mode** — fewer than half the tickets can run in a wave of width ≥ 2. Dispatch **one
  worker for the whole graph**: header `[A]` as usual, ticket block `[B]` holding every contract in
  walk order. Landing duty is transferred — the worker commits each ticket as it finishes with the
  `Ticket: #<n>` trailer (implement-core §5), so resume still works. You verify once, at the end. A
  fresh worker per chained ticket re-reads the code, re-edits the same registries and re-runs the
  suite with nothing overlapping — measured at 2.9× the wall-clock, 2× the cost and 3× the diff of
  one worker on a 7-ticket chain. The frozen header keeps the *prefix* cheap; it cannot give back
  the turns.
- **Fan-out mode** — the graph is genuinely wide. One fresh worker per ticket. Dispatch each wave in
  a single message, one worker each, **only where `files_owned` are disjoint**; after the wave
  verifies, land each ticket as its own commit in ranked order. Overlapping or unknowable ownership
  within a wave → serialize, ranked by `blocking` count descending, tie-break on issue number.
- **Hotspot files** (routers, DI containers, barrel `index.*`, schema/migrations, lockfiles, shared
  types) are conflict magnets — never in two same-wave boundaries.
- **Never use `isolation: worktree` agents for tickets.** An isolated agent branches from
  `origin/main`, not this integration branch — it can't see any landed slice. Wrong base, silently.

### Model routing — cheapest tier that clears the bar

Route per ticket (the metadata's `model` is `/taskplan`'s recommendation — you may override with a
reason). Pass it explicitly on every dispatch:

| Tier | Route here when… |
|---|---|
| `opus` | **the default** — and always in chain mode, where one worker carries the whole graph |
| `sonnet` | a ticket that touches no hotspot file and follows an existing pattern exactly — one-clause justification |

Sonnet took ~2.7× the turns of opus on shared-file tickets (#103 vs #104 in the measured campaign:
120 vs 367 turns, 16 vs 25 min, $12 vs $20) — the unit-price saving cancels and the clock loses.
**These two tiers are the whole table.** Fable is not available for delegation, and **`haiku` is
retired for ticket work** — across 24 logged haiku agents it reworked at 12.5% against sonnet's
3.2%, so its saving was routinely spent twice over. A ticket that looks mechanical enough for haiku
goes to sonnet. (`/taskplan` may still emit `"model": "haiku"` on older tickets — read it as
`sonnet`.) With only two tiers, **escalation on rework means opus**: a sonnet worker that failed its
own self-verify signals the bar was higher than judged.

**Tier affinity within a wave (advisory).** Caches are model-scoped, so a wave split between sonnet
and opus shares no prefix across the split. On a *genuine* toss-up, prefer the wave's dominant tier —
a lone opus worker in an otherwise-sonnet wave pays full price for a prefix its neighbours are
reading at a tenth. This never justifies under-routing a ticket that needs opus; correctness
outranks the cache.

### The brief

Lay every brief out per [`implement-core` §0](../implement-core/SKILL.md): the **frozen campaign
header from Step 2, pasted unchanged**, then the **ticket block** — the **contract verbatim** (§1's
table decides body vs agent-brief comment — fetch with `--comments`), the ticket's **method**, and
the **file boundary** (only when fanned out; in a serial stretch the branch is the boundary), and —
fan-out mode, second wave on — **`## Landed so far`**: the `summary` and `files_changed` lines of
every previous IMPLEMENTER REPORT, so a fresh worker inherits the conventions its siblings just set
instead of re-reading the registries to infer them.

Everything shared lives in the header and is written once; everything per-ticket lives after it.
Never restate a header fact inside the ticket block, and never let a ticket number, file list or
tier name drift up into the header — either breaks the shared prefix for every worker. Front-load
everything; workers share no memory.

## Step 4 — Dispatch

### Default transport — subagents

Spawn each wave's workers in a single message, one `Agent` call each
(`subagent_type: "code-implementer"`, explicit `model:` per the routing). Dispatching a wave in one
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

Orca workers are top-level claude sessions — the `code-implementer` agent definition does NOT apply,
so the brief must carry the full implement-core doctrine inline (boundary, STOP-via-`ask` rule,
report block). It carries the **same campaign header bytes** as a subagent brief; that is how
`--orca` gets the same shared prefix. The tier lives in the argv, so **escalation means a new
terminal**, not a re-dispatch. Supervise per the orchestration skill: rolling `check --wait` for
`worker_done`/`escalation`; a timeout is a checkpoint, not a failure; answer `ask`s with `reply`;
never kill a working worker.

Close worker terminals at the end of the run, not between waves. An idle same-tier terminal may be
re-targeted for a later ticket, but **you reuse the terminal, never the context**: `/clear` it first,
so the next ticket starts on a fresh session exactly as the one-fresh-worker-per-ticket rule
requires. Be clear-eyed about what that buys — `/clear` discards the session's cache too, so terminal
reuse saves process startup, not tokens. Spawning a new terminal instead is equally correct.

## Step 5 — Integrate, verify, land

**Chain mode:** the worker's per-ticket gate stands. Read its final report, confirm one
`Ticket: #<n>` commit per ticket exists, run the full build + test suite once on the integrated
branch, push, log one agent record. Red → re-dispatch the fix to a fresh `opus` worker. The
per-ticket loop below is fan-out mode.

1. **Read the IMPLEMENTER REPORT** (`verdict`, `build`, `tests`, `blockers`). A `blockers` entry
   naming a cross-boundary need means the partition was off — reassign ownership or serialize;
   don't ignore it.
2. **Verify yourself**: run the full build + test suite (running commands is orchestration). Delegate
   long-log suites (e2e / UI / integration) to a `verifier` subagent (`model: "sonnet"`) that
   returns a triaged ≤20-line verdict — never raw logs into this session.
3. Anything red or `needs-attention`/`fail` → **re-delegate the fix; never patch inline.** Which
   worker depends on the failure:
   - **Same slice, same tier** (a review finding, a failed assertion on work that was otherwise on
     track) → **continue the worker that built it** — subagent: `SendMessage`; Orca: `reply` on its
     task. This is the one place reuse is right: its context is both already warm and actually about
     this ticket. It stays one worker on one ticket, so the rule holds.
   - **Escalating a tier** (the original failed its own self-verify) → **a fresh worker** one tier
     up. A subagent's model is fixed at spawn and an Orca tier lives in the argv, so a new session
     is required either way.
   - **The approach was wrong at root**, or the worker is gone → **a fresh worker** at the same tier;
     a warm context that went down the wrong path is a liability, not an asset.

   Log `--rework` in all three cases.
4. **Land it** — one commit per ticket, committed by you:

   ```
   <type>: <ticket title> (#<n>)

   <one or two lines: what the slice delivers, how it was verified>

   Ticket: #<n>
   ```

   The `Ticket: #<n>` trailer is load-bearing — it is the done-marker resume reads and the record
   the PR body is built from. Then **push the branch** — an unpushed landing is state only this
   session knows.
5. **Log one agent record** per worker:

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py record --type agent --run-id "$run_id" \
     --wave <position> --task "<ticket title>" --files-owned N --files-changed N \
     --model <tier> --verdict pass --build pass --tests pass --isolation tree
   # flags when true: --deviated --blockers --boundary-stop --rework --review-fix
   ```

   Mint the run id once at campaign start: `run_id="<branch>-$(date +%Y%m%d-%H%M%S)"` — prefix
   `orca-` under `--orca`.
6. Move to the tickets this landing unblocked.

**If a worker STOPs** (design fork, cross-ticket need, ADR conflict): everything downstream is
blocked by definition — that's the honest cost of a chain. Surface the ticket number and the
worker's question to the user. Never skip past an unlanded blocker, and never answer a design fork
on the spec's behalf.

## Step 6 — Finish: review, one PR, hand to /cleanup

When every child has landed:

1. **Full suite once more** on the integrated branch — the last wave verified itself, not the whole.
2. **Reviews**: `/code-review` is `disable-model-invocation` — pause and ask the user to type
   **`/code-review medium`** (always `medium`; the no-arg default burns far more). Under `--orca`,
   run it in a dedicated review worker terminal instead (`claude --model opus
   --dangerously-skip-permissions`, send the slash commands as terminal input, read findings back).
   Run **`/security-review`** yourself via the Skill tool when the diff touches auth/authz, crypto,
   secrets, user input, file/path/network I/O, deserialization, or SQL. Route every finding to a
   fresh fix worker (`--review-fix`), land, push.
3. **Compose the PR body yourself** — you hold per-ticket knowledge `/cleanup` can't infer:
   - Title from the parent issue.
   - One summary line per landed ticket, in walk order.
   - **One `Closes #<n>` line per child — all of them**; a child left out stays open forever.
   - A `Parent: #<parent>` reference line. **Never `Closes #<parent>`** — `/cleanup` closes the
     parent after the merge, when `subIssuesSummary.completed == total`.
4. **Ask before publishing.** On approval: rebase onto `origin/main`, push, `gh pr create` with the
   composed body — then invoke **`/cleanup`** via the Skill tool: it adopts the existing PR, polls
   CI, merges on green, closes the parent, and tears down per its own rules.
5. **Log the run** (once):

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py record --type run --run-id "$run_id" \
     --branch "<branch>" --milestone "<parent title> (#<parent>)" --waves N --agents N \
     --outcome success --build-final pass --tests-final pass --review-findings N
   # add --pr-created if you opened the PR. fix_iterations / peak_width / wave_widths are derived
   # from the agent records — pass nothing. Under --orca ALWAYS add --no-auto-tokens (worker
   # transcripts live outside this session; the auto-scan would report misleading buckets).
   ```

6. **Record the stage cost** — the pipeline-level counterpart to the run log above:

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/stats/stats.py record --issue <parent> --stage implement
   ```

   Do it before the session is cleared; stage attribution cannot be recovered afterwards. Re-running
   is harmless (the row is replaced). This is what lets `/cleanup` show what the whole feature cost.

7. **Report**: the walk table (ticket → tier → verdict → commit), the PR link, and campaign state.

## Rules

- **Scope is one parent.** Never sweep the repo; never dispatch the parent itself.
- **No acceptance criteria → not a ticket.** Refuse it, whatever its label says.
- **Claim all children up-front; announce on the parent.** The assignee set is the campaign lock.
- **The campaign header is built once and frozen.** Byte-identical in every brief, both transports;
  no ticket number, file list or tier name in it.
- **Fan-out: one fresh worker per ticket. Chain: one worker, the whole graph, in walk order.**
  Never mix — a fan-out worker never "continues" into the next ticket. The only continuation allowed is a same-tier rework of the slice
  that worker just built (Step 5.3) — still one worker, still one ticket.
- **Landed = trailer on the pushed branch. Closed = merged to main.** Never close a child by hand.
- **Fan out only on disjoint files, same tree.** Overlap → serialize. Isolated-worktree agents are
  banned (wrong base).
- **Push after every landing** (chain mode: when the worker returns).
- **Opus by default; justify each `sonnet`; a sonnet rework goes to opus.**
- **A STOP holds the walk.** Surface it; don't skip, don't decide the fork yourself.
- **Anti-freelance, always.** You commit and push; you never write source.
- **Ask before the PR.** `--dry-run` stops before claiming anything.

## Red flags

- A ticket's body has no acceptance criteria → it didn't come from `/taskplan` and triage never
  finished it. Refuse it.
- A child is assigned to someone else → another session holds this parent. Stop.
- You're about to `Edit` a source file → anti-freelance violation. Delegate it.
- A report says `blockers: <another ticket's work>` → the graph's edges are wrong or the walk order
  ignored one. Check `blockedBy` before re-dispatching.
- `git log` shows a trailer for a ticket still in your queue → you're resuming without having read
  the branch. Re-run the resume grep.
- Commits with no `Ticket:` trailer beyond review-fix commits → work landed outside the walk;
  reconcile before continuing.
- Two briefs whose headers differ by even one byte → the shared prefix is gone and every worker pays
  full price. Diff them against the Step 2 header.
- A worker's report shows it grepping for the test command or re-reading the glossary → the header
  didn't carry what it should, and every other worker is repeating the same waste.
- The PR body is missing a child's `Closes` line → that child stays open forever. Landed trailers
  and `Closes` lines must match one-to-one.
- The parent appears in your dispatch list → the guards didn't run; a spec is not a ticket.

## Analyzing the harness (closing the loop)

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/implement/orchlog.py report --recent 20
```

**Quality**: high `boundary_stop` → partitioning wrong; high rework → briefs under-specified or
`/taskplan` slices too big; high `deviated` → criteria not tight. **Model fit**: rework clustered in
a cheap tier → route those up. **Cost**: an
orchestrator-dominated run is overhead-heavy — the fix is coarser slices in `/taskplan`, not less
planning. Slice size is the dominant lever generally: each ticket carries a fixed cost (a cold
prefix plus its share of orientation) that no amount of dispatch tuning removes, so halving the
ticket count halves it. Worker reuse is not an alternative — carried context is billed on every
turn, so a worker that keeps a finished ticket's transcript pays for it repeatedly while getting
worse at the next one. A run with `peak_width == 1` and more than one agent record ran a chain in
fan-out mode — it should have been one worker. Ignore the COST block for `orca-` runs (worker tokens uncaptured). When you
change this skill or the agent definitions in response, bump `WORKFLOW_VERSION` in `orchlog.py`.
