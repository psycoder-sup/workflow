---
name: frontier
description: >
  Dispatch the takeable GitHub tickets — open, `ready-for-agent`, unblocked, unassigned — to parallel
  Orca worktrees, one `claude` worker per ticket. The parallel unit is the TICKET, not sub-tasks
  within one: each worker builds its vertical slice serially in its own checkout, then ships it with
  /cleanup. Use after /to-tickets has published a dependency-linked ticket set to GitHub Issues.
trigger: /frontier
user-invocable: true
argument-hint: "[issue numbers to force-dispatch, e.g. 42 43] [--dry-run]"
allowed-tools: ["Read", "Bash", "Glob", "Grep", "AskUserQuestion", "TaskCreate", "TaskUpdate"]
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
re-running `/frontier` after PRs merge — the next query returns the newly-unblocked tickets.

## Preconditions

- `gh` authenticated, and the cwd inside a clone whose remote `gh` can resolve.
- The repo registered with Orca (`ORCA repo list --json`; add with `ORCA repo add --path /abs/repo`).
- The triage labels **exist** in the repo. `/setup-matt-pocock-skills` writes only a *mapping* table
  — it never runs `gh label create`, and `gh issue create --label <missing>` fails outright. If
  `ready-for-agent` is missing, say so and stop; don't silently fall back to an unlabelled query.

---

## Step 1 — Resolve the Orca CLI

Choose the executable **once** and reuse it for every later command:

- `ORCA_CLI_COMMAND` set → use its value.
- Else a dev checkout exposing `ORCA_DEV_REPO_ROOT` → `orca-dev`.
- Else Linux outside an Orca-managed terminal → `orca-ide`. **Never bare `orca` there** — it
  resolves to the GNOME screen reader and starts speech on the user's machine.
- Else → `orca`.

Below, `ORCA` is a placeholder — substitute the resolved executable; don't run `ORCA` literally.
Confirm the app is up with `ORCA status --json`, and `ORCA open --json` if it isn't. If the chosen
executable can't run, report its exact error and stop — never fall through to another one.

Don't guess Orca subcommands or flags. `~/.claude/skills/orca-cli/SKILL.md` is a discovery stub on
purpose; the version-matched surface comes from `ORCA skills get orca-cli`. Load it if anything below
is rejected by this binary.

## Step 2 — Compute the frontier

**Takeable** = open **and** labelled `ready-for-agent` **and** zero open blockers **and** unassigned.

Start with the label + assignee filter:

```bash
gh issue list --state open --label ready-for-agent \
  --json number,title,body,labels,assignees \
  --jq '[.[] | select(.assignees | length == 0)]'
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

If arguments named explicit issue numbers, skip discovery and use those — but still run the blocked
and assignee checks, and refuse any that fail unless the user overrides in the same breath.

## Step 3 — Present, and get approval

Print one line per candidate: number, title, and the one-line "What it delivers". Then list what was
**excluded and why** — blocked (by which open issues), already assigned (to whom), or not
`ready-for-agent`. The exclusions matter more than the inclusions; a ticket silently missing from the
frontier looks identical to a ticket that doesn't exist.

Ask before dispatching. Claiming writes to the tracker and spawning workers spends tokens; neither is
something to infer. On `--dry-run`, stop here.

## Step 4 — Claim, then dispatch

**Claim first, before any work**, so a concurrent run skips the ticket. The assignee *is* the lock:

```bash
gh issue edit <n> --add-assignee @me
```

Then one worktree per ticket, **agent-first** — `create --agent` puts `claude` in the worktree's
first terminal. Creating a bare worktree and then opening an agent in it is an anti-pattern that
leaves a stray fallback shell:

```bash
ORCA worktree create \
  --repo id:<repoId> \
  --name ticket-<n>-<slug> \
  --issue <n> \
  --no-parent \
  --agent claude \
  --prompt "<worker brief>" \
  --json
```

- **`--issue <n>` is load-bearing.** It links the GitHub issue to the worktree, which is how the
  selector `issue:<n>` resolves later and how `/cleanup` builds `Closes #<n>` without a plan file.
  Never omit it.
- **`--no-parent`** — tickets are independent top-level work. Omit `--base-branch` so Orca uses the
  repo default base. Never base a ticket on another feature branch unless its `blocked_by` genuinely
  requires stacking and the user asked for it.
- Read the agent handle from `result.agentTerminalHandle`; older runtimes return only
  `result.startupTerminal.handle`. If a handle later reports `terminal_handle_stale`, re-list with
  `ORCA terminal list --worktree <selector> --json` — never dual-send to old and new handles.
- Build each worker's prompt from [references/worker-brief.md](references/worker-brief.md).

**Dispatch all approved tickets in one pass**, then stop issuing commands — they run concurrently
and independently.

## Step 5 — Report, then stop

Print a table: ticket → worktree id → agent handle → claimed ✓. Repeat the exclusion list. Then tell
the user plainly:

> Workers are running independently. Each will open its own PR via `/cleanup`. Re-run `/frontier`
> once those merge to pick up the newly-unblocked tickets.

**Do not poll, wait, or supervise.** No `terminal wait`, no `check --wait`, no re-querying in a loop.
If the user wants supervision, that's a different flow (`/implement-orca`).

---

## Rules

- **Claim before dispatch, always.** An unclaimed ticket is a race with every other session.
- **Never dispatch a blocked ticket.** The `blocked_by` count is the gate, not your judgment about
  whether the blocker "really" matters.
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
- You're about to run `orca orchestration ...` → wrong flow. This is a handoff; re-read the section
  above.
