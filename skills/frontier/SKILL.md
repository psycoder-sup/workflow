---
name: frontier
description: >
  Dispatch a parent issue's takeable child tickets — open, agent-ready, unblocked, unassigned — to
  parallel Orca worktrees, one `claude` worker per ticket. The parallel unit is the TICKET, not
  sub-tasks within one: each worker builds its vertical slice serially in its own checkout, then
  ships it with /cleanup. Scoped to one parent by default so it never sweeps the whole repo. Use
  after /to-tickets has published a dependency-linked ticket set to GitHub Issues.
trigger: /frontier
user-invocable: true
argument-hint: "<parent issue number, e.g. 234> [--dry-run]"
allowed-tools: ["Read", "Bash", "Glob", "Grep", "AskUserQuestion", "TaskCreate", "TaskUpdate", "Skill", "Agent"]
---

# /frontier

Find the tickets that are **takeable right now** and hand each one to its own Orca worktree.

This is the execution half of the ticket flow: `/grill-with-docs` → `/to-spec` → `/to-tickets`
publish a dependency-linked ticket set to GitHub Issues; `/frontier` works that set. It is the
**ticket-level** counterpart to `/implement` — where `/implement` parallelises *tasks inside one
body of work*, `/frontier` parallelises *whole tickets*, and each worker builds serially.

## Why ticket-level, not wave-level

A `/to-tickets` ticket is a **vertical slice** — a narrow but complete path through schema, API, UI
and tests, "sized to fit a single fresh context window". Decompose one and you get a dependency
chain (UI needs the API needs the schema), which `/taskplan` step 6 collapses into a single task,
which `/implement`'s `W == 1` gate then refuses to orchestrate. That refusal is correct: `/implement`
measures a **4.5× median orchestrator tax below 6 agents** (worst observed 20× at 2 agents), so
there is nothing to win inside one slice.

The width is **across** tickets, and it is free: `/to-tickets` already emitted the dependency graph
as native GitHub `blocked_by` edges. Two tickets in two worktrees are isolated at the git level,
which is strictly stronger than file-boundary discipline — they may both touch the router, and the
conflict surfaces at merge, where git is the right tool.

**Route work here vs `/implement`:**

| Shape | Route |
| --- | --- |
| Deep + coupled — one feature through every layer | `/to-tickets` → **`/frontier`** → N worktrees, one agent each |
| Broad + shallow — same change × many files (12 endpoints, 30 components) | skip `/to-tickets` → `/taskplan` → `/implement` waves |

## This is a full handoff, not supervised orchestration

Each worker **owns its ticket to completion**. Do **not** use `orca orchestration task-create`,
`dispatch --inject`, or `check --wait` — per the orca-cli guide those are the supervised path, and
`task-create` records coordinator-owned tracking state this flow does not want.

**GitHub is the coordination substrate.** `blocked_by` + assignee + closed-state already encode
everything a task DAG would, and they survive this session dying. Advancing the frontier is just
re-running `/frontier <parent>` after PRs merge — the next query returns the newly-unblocked tickets.

## Preconditions

- `gh` authenticated, and the cwd inside a clone whose remote `gh` can resolve.
- The repo registered with Orca (`ORCA repo list --json`; add with `ORCA repo add --path /abs/repo`).
- The triage labels **exist** in the repo. `/setup-matt-pocock-skills` writes only a *mapping* table
  — it never runs `gh label create`, and `gh issue create --label <missing>` fails outright. If the
  agent-ready label (Step 2 resolves which) is missing, say so and stop; don't silently fall back to
  an unlabelled query.

---

## Step 0 — load the `orca-cli` skill (source of truth)

Before running **any** Orca command, **invoke the user-level `orca-cli` skill** with the `Skill`
tool and follow it for all Orca mechanics: executable resolution, worktree creation, terminal
lifecycle, handles, and comments. If it isn't available, **stop and tell the user** — this workflow
requires it.

That skill is itself a discovery stub; it will point you at

```text
ORCA skills get orca-cli
```

which prints the **version-matched** guide for the exact binary that will run your commands. Read it
before dispatching. The command shapes in this document are **illustrative**; where they diverge
from the version-matched guide, **the guide wins**. Flags move between Orca releases — the two
dispatch paths in Step 4 both depend on flags this binary may or may not have, so confirm rather
than assume.

Two things that skill establishes and this one depends on:

- **The executable.** `ORCA_CLI_COMMAND` → `orca-dev` in a dev checkout → `orca-ide` on Linux
  outside an Orca terminal (**never bare `orca` there** — it's the GNOME screen reader and will
  start speech on the user's machine) → otherwise `orca`. Choose once, reuse for every command, and
  if it can't run, report its exact error and stop rather than falling through to another binary.
- **Liveness.** `ORCA status --json`; `ORCA open --json` if the app is down.

Below, `ORCA` is a placeholder — substitute the resolved executable; never run `ORCA` literally.

## Step 1 — Resolve the scope

**`/frontier` is scoped to one parent issue.** It does not sweep the repo.

- **Argument given** (`/frontier 234`) → that's the parent.
- **No argument** → find candidate parents and **ask**. A candidate is an open agent-ready issue
  that other open issues name as their `## Parent`. Never default to repo-wide; a repo accumulates
  agent-ready issues from every past feature, and sweeping them is how unrelated work gets
  dispatched.

Children are the issues whose body carries a `## Parent` section naming the scope issue —
that's the section `/to-tickets` writes:

```bash
gh issue list --state open --json number,title,body,labels,assignees \
  --jq '[.[] | select(.body | test("## Parent[\\s\\S]*#<parent>\\b"))]'
```

If the repo uses **native sub-issues** instead (`gh api repos/{owner}/{repo}/issues/<parent>/sub_issues`),
prefer them — they render the tree in GitHub's own UI. `/to-tickets` doesn't create them by default,
so an empty result means fall back to the `## Parent` parse. Say which you used.

## Step 2 — Compute the frontier

**Takeable** = a child of the scope parent **and** open **and** carrying the agent-ready label
**and** zero open blockers **and** unassigned **and** carrying acceptance criteria.

**Never dispatch the parent.** Exclude the scope issue itself, always. And apply this rule
independently of scoping, because it catches the same class of bug when someone force-dispatches by
number:

> **An issue whose body has no `## Acceptance criteria` section is not a ticket.** Refuse it and say
> why.

A `/to-tickets` ticket always has them; a `/to-spec` spec never does. This matters because `/to-spec`
labels the **spec** `ready-for-agent` too (*"Apply the `ready-for-agent` triage label - no need for
additional triage"*), so the label alone cannot tell a whole feature from one slice of it. Dispatched
by mistake, a spec hands one worker the entire feature — and when it's the only unblocked issue, that
looks exactly like a normal single-ticket wave.

**Resolve the label first — don't assume `ready-for-agent`.** `/setup-matt-pocock-skills` lets a repo
map the five canonical triage roles onto its own vocabulary. Read
`docs/agents/triage-labels.md` and take the right-hand column for the `ready-for-agent` row; a repo
that kept the defaults has an identity table, and a repo that didn't uses something like
`bug:ready`. If the file is absent (setup skipped Section B because `triage` isn't installed), fall
back to the literal `ready-for-agent`. Name the label you resolved in your output — an empty frontier
caused by a label mismatch is otherwise indistinguishable from "no work available".

Then filter the **children from Step 1** by label and assignee — note the `--label` narrows an
already-scoped set, it is not the scope itself:

```bash
gh issue list --state open --label "<resolved-label>" \
  --json number,title,body,labels,assignees \
  --jq '[.[] | select(.assignees | length == 0)
             | select(.body | test("## Parent[\\s\\S]*#<parent>\\b"))
             | select(.body | test("## Acceptance criteria"))]'
```

Then drop anything still blocked. The live gate is GitHub's native issue dependencies, which count
**open** blockers only:

```bash
gh api repos/<owner>/<repo>/issues/<n> \
  --jq '.issue_dependencies_summary'
```

- An object with `blocked_by: 0` → **takeable**.
- `blocked_by: N > 0` → blocked; skip it and name the blockers.
- **`null` → the field exists but this repo has no dependency data** (dependencies not enabled, or
  nothing linked). `gh` returns the key either way, so testing `.issue_dependencies_summary.blocked_by`
  alone gives you `null`, which is *not* `0` — don't let it read as "unblocked". Fall through to the
  body parse.

Fallback: parse the ticket body's `Blocked by:` line and treat a blocker as cleared only when that
issue is closed (`gh issue view <b> --json state`). **Say which method you used** — a silent fallback
that mis-reads the graph dispatches work in the wrong order.

If the user force-dispatched explicit issue numbers, skip discovery and use those — but still run
the blocked, assignee, **and acceptance-criteria** checks, and refuse any that fail unless the user
overrides in the same breath. The acceptance-criteria check is not overridable by silence: a spec
dispatched as a ticket produces one worker attempting a whole feature.

## Step 3 — Present, and get approval

Print one line per candidate: number, title, and the one-line "What it delivers". Then list what was
**excluded and why** — blocked (by which open issues), already assigned (to whom), or not
`ready-for-agent`. The exclusions matter more than the inclusions; a ticket silently missing from the
frontier looks identical to a ticket that doesn't exist.

**Route a model tier per ticket**, and show it in the same table. Cheapest tier whose *intelligence
and taste* both clear the bar — the same rubric `/taskplan` uses:

- **sonnet** — the default. Pattern-following work against an established seam: a UI surface, a
  well-specified API, a parity port of something already shipped.
- **opus** — subtle correctness or real design judgment: invariants that must survive (an ADR's
  behavioural rules, a consume/tombstone contract), security predicates like RLS, or a ticket whose
  design fork the spec left open.
- **haiku** — mechanical and fully specified: config, renames, moving files. Rare for a vertical
  slice, which by definition crosses layers.

Default to **sonnet** and justify each **opus** in one clause. A whole frontier routed to opus means
the routing wasn't done. Tickets differ, so the tier is per ticket, never per wave.

Ask before dispatching. Claiming writes to the tracker and spawning workers spends tokens; neither is
something to infer. On `--dry-run`, stop here.

## Step 4 — Claim, then dispatch

**Claim first, before any work**, so a concurrent run skips the ticket. The assignee *is* the lock:

```bash
gh issue edit <n> --add-assignee @me
```

### First, resolve lineage once

Check whether **this** session is already inside an Orca-managed worktree:

```bash
ORCA worktree current --json
```

- **Inside one** → pass `--parent-worktree active` on every create, so the ticket worktrees nest
  under the one you're driving from and the whole feature reads as a tree in Orca's workspace list
  instead of a flat pile of siblings.
- **Not inside one** (a plain shell, the repo root) → pass `--no-parent`; the tickets are independent
  top-level work.

**Lineage is not the git base.** `--parent-worktree` and `--no-parent` control only Orca's tree.
Whichever you pass, **omit `--base-branch`** so every ticket still branches from the repo default.
Tickets must not stack on each other's branches — their `blocked_by` edges are satisfied by *merges*,
not by inheriting an unmerged parent. Stack only if the user explicitly asks.

Call the resolved flag `<lineage>` below.

### Then one worktree per ticket

**Which path depends on whether the ticket needs a non-default model.**

### Path A — default tier (one command)

`create --agent` puts `claude` in the worktree's first terminal at its default model. Use this
whenever the routed tier *is* the default:

```bash
ORCA worktree create \
  --repo id:<repoId> \
  --name ticket-<n>-<slug> \
  --issue <n> \
  <lineage> \
  --agent claude \
  --prompt "<worker brief>" \
  --json
```

### Path B — pinned tier (four commands)

**`worktree create` has no `--model` flag** — verify against the version-matched guide, but as of
writing it accepts only `--agent`/`--prompt` and launches that agent at its default. To pin a tier,
use the guide's documented custom-model handoff: create the worktree *without* `--agent`, then open
the agent with an explicit command.

```bash
ORCA worktree create --repo id:<repoId> --name ticket-<n>-<slug> \
     --issue <n> <lineage> --json
ORCA terminal create --worktree id:<repoId>::<path> --title ticket-<n> \
     --command 'claude --model <tier>' --json
ORCA terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
ORCA terminal send --terminal <handle> --text "<worker brief>" --enter --json
```

- **`terminal wait --for tui-idle` is not optional** — sending before the TUI is ready loses the
  prompt, and a worker that never received its brief looks identical to one that's thinking.
- **Bare `create` may open a fallback shell** when the repo has no default-terminal config. Close it
  **only** after `terminal list` confirms it's an unused shell — a configured default tab is an
  intentional surface, not disposable.

### Do not reach for `orca orchestration`

`worker-start` accepts `--model`/`--effort` and looks like the obvious answer. It isn't, for two
reasons: it has **no `--issue` flag** (so `/cleanup` loses its primary `Closes #<n>` source), and it
injects a coordinator preamble obliging the worker to send `worker_done`/`heartbeat`. Nobody here is
waiting on those — this is a handoff. Path B gets the model pin without the lifecycle debt.

### Both paths

- **`--issue <n>` is load-bearing.** It links the GitHub issue to the worktree, which is how the
  selector `issue:<n>` resolves later and how `/cleanup` builds `Closes #<n>` without a plan file.
  Never omit it.
- **`<lineage>`** — the flag resolved above (`--parent-worktree active` or `--no-parent`). Orca tree
  only; the git base stays the repo default either way.
- Read the agent handle from `result.agentTerminalHandle`; older runtimes return only
  `result.startupTerminal.handle`. If a handle later reports `terminal_handle_stale`, re-list with
  `ORCA terminal list --worktree <selector> --json` — never dual-send to old and new handles.
- Build each worker's prompt from [references/worker-brief.md](references/worker-brief.md). **Fetch
  the issue with its comments** (`gh issue view <n> --comments`), not just the body: a triaged issue
  carries its specification in an **agent brief comment**, and the body is only context. See the
  brief template for which to send.

**Dispatch all approved tickets in one pass**, then stop issuing commands — they run concurrently
and independently.

### Delegate the execution, keep the judgment

You author the briefs, route the tiers, and decide what gets claimed. **Running the commands is
mechanical — delegate it**, so an expensive orchestrator session isn't spending its context on
`worktree create` output. This also keeps the flow valid when the orchestrator is Fable, which
cannot be a delegation target and so must not be the thing typing commands either.

After approval, hand the whole approved set to **one** `Agent` with an explicit
`model: "opus"` (sonnet is enough for pure execution; never Fable). One agent for all tickets, not
one per ticket — the tickets are independent but the *dispatching* is a single serial errand, and N
dispatcher agents would race on nothing.

Its brief gets everything it needs to run commands without judgment calls:

- The resolved `ORCA` executable and the `repoId`
- Per ticket: number, `ticket-<n>-<slug>` name, **Path A or B**, the tier for B, and the **full
  brief text already written** — it composes nothing
- The claim command to run first for each
- Instruction to return the report table (ticket → worktree id → agent handle → claimed ✓) and to
  **stop and report rather than improvise** if any command is rejected — a rejected flag means this
  binary's surface differs from Step 0's guide, which is your call to make, not its.

## Step 5 — Report, then stop

Print the dispatcher's table: ticket → tier → path (A/B) → worktree id → agent handle → claimed ✓.
Repeat the exclusion list. Then tell the user plainly:

> Workers are running independently. Each will open its own PR via `/cleanup`. Re-run
> `/frontier <parent>` once those merge to pick up the newly-unblocked tickets.

When the scope's children are **all closed**, say so and note the parent is ready to close —
`/to-tickets` deliberately never touches it (*"Do NOT close or modify any parent issue"*), so nothing
else will.

**Do not poll, wait, or supervise.** No `terminal wait`, no `check --wait`, no re-querying in a loop.
If the user wants supervision, that's a different flow (`/implement-orca`).

---

## Rules

- **Scope to a parent, never the repo.** An agent-ready label survives every past feature; a
  repo-wide sweep dispatches work nobody asked for.
- **Never dispatch the parent, or anything without acceptance criteria.** A spec is not a ticket.
- **Claim before dispatch, always.** An unclaimed ticket is a race with every other session.
- **Never dispatch a blocked ticket.** The `blocked_by` count is the gate, not your judgment about
  whether the blocker "really" matters.
- **Route a tier per ticket, and say why for each opus.** Everything-on-opus is unrouted.
- **Delegate the commands, own the briefs.** You decide; a cheaper agent types.
- **Never dispatch an assigned ticket** without the user explicitly overriding — someone else holds
  it.
- **One worker per ticket.** Don't split a ticket across workers; that's the wave path, and the
  `W == 1` gate exists to stop it.
- **You don't implement.** This skill queries, claims, and dispatches. All code belongs to the
  workers, in their own checkouts.
- **Don't close issues here.** The worker's PR closes its issue on merge via `Closes #<n>`.

## Red flags

- `ready-for-agent` returns zero issues but the repo clearly has tickets → the label probably doesn't
  exist. Check `gh label list`; don't broaden the query to compensate.
- Every candidate is blocked → the chain is linear. That's fine and expected for a tightly-coupled
  feature; dispatch the one head ticket rather than forcing width.
- A ticket's body has no acceptance criteria → it didn't come from `/to-tickets`, or triage never
  finished it. Send it back rather than handing a worker a vague brief.
- **The frontier contains the parent you scoped to** → the acceptance-criteria guard didn't run.
  Stop; dispatching it hands one worker the whole feature.
- **The frontier is exactly one issue and it's the biggest one in the set** → likely the same bug
  wearing a normal-looking hat. Check for `## Acceptance criteria` before believing it.
- You're about to run `orca orchestration ...` → wrong flow. This is a handoff; Path B pins the model
  without it.
- A worker never responds to its brief → on Path B you probably skipped `terminal wait --for
  tui-idle` and the prompt was swallowed. Re-check the handle before re-sending; never dual-send.
