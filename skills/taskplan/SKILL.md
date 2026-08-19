---
name: taskplan
description: >
  Decompose a parent spec issue into vertical-slice sub-issues on GitHub — native --parent links,
  native blocked-by dependency edges, ready-for-agent by construction — each carrying checkable
  acceptance criteria and an advisory taskplan metadata block (files_owned, model tier, method) that
  /implement uses for file-disjoint waves and model routing. Quizzes the user for approval BEFORE
  publishing anything. The plan stage between /spec and /implement; the issue graph it publishes IS
  the plan — no plan file.
trigger: /taskplan
user-invocable: true
argument-hint: "<parent issue number, e.g. 42>"
allowed-tools: ["Read", "Bash", "Glob", "Grep", "AskUserQuestion", "WebFetch"]
---

# /taskplan

Turn a parent spec issue into a **published, dependency-linked sub-issue graph**. This is the *plan*
stage of the pipeline: `/spec` published the parent (the spec is its body); `/taskplan` decomposes
it into tickets sized and shaped so `/implement`'s walk is nearly free — every ticket already
carries its acceptance criteria, its blocking edges, and its orchestration metadata.

**The output is the issue graph itself.** There is no plan file: a JSON duplicating the graph goes
stale the moment anyone re-triages an issue.

## When to use

- **Use** after `/spec`, on a parent issue carrying the `spec` label, when the work is more than one
  ticket.
- **Skip** for a single obvious ticket — `/implement <n>` takes a standalone issue directly.

## Preconditions

- **`gh` ≥ 2.94** (native `--parent` / `--blocked-by` flags). Check once; older → stop and say so.
- The argument is an open issue. If it doesn't carry the `spec` label, warn (it may be a raw idea
  that should go through `/spec` first) but proceed if the user confirms.
- The repo has the triage labels (`/project-kit` creates them). If the agent-ready label is missing
  (`gh label list`), stop — `gh issue create --label <missing>` fails outright.

## Process

### 1. Read the spec, the domain, the code

- `gh issue view <parent> --comments` — the body is the contract; comments may refine it.
- Read `CONTEXT.md` (or `CONTEXT-MAP.md`) and relevant `docs/adr/*` — ticket vocabulary MUST match
  the glossary, and slices MUST respect ADRs. Absent files → proceed silently.
- Explore the code the spec touches. Look for **prefactoring** opportunities — "make the change
  easy, then make the easy change." Prefactoring becomes the first ticket(s).

### 2. Draft vertical slices

Break the work into **tracer-bullet tickets**:

- Each slice cuts a narrow but COMPLETE path through every layer it touches (schema, API, UI,
  tests) — vertical, NOT a horizontal slice of one layer.
- A completed slice is demoable or verifiable on its own.
- Each slice is sized to fit one fresh context window (roughly ≤ ~150 lines of change; bigger →
  split, trivially tiny → merge into a neighbor).
- Prefactoring first.

Give each ticket its **blocking edges** — the tickets that must land before it can start. No
blockers = startable immediately. Sequence for parallelism where it's real: two slices with disjoint
file sets and no data dependency get **no edge between them**, so `/implement` can fan them out.
Don't fake independence — a false missing edge dispatches work in the wrong order.

**Wide refactors are the exception to vertical slicing.** One mechanical change with codebase-wide
blast radius (rename a column, retype a shared symbol) can't land green as a tracer bullet —
sequence it as **expand–contract**: an *expand* ticket (add the new form beside the old; nothing
breaks), *migrate* tickets in blast-radius-sized batches (each blocked by expand, CI green batch to
batch), and a *contract* ticket (delete the old form, blocked by every migrate batch).

### 3. Attach orchestration metadata per ticket

- **`files_owned`** — the globs/paths the ticket will create or modify. This is what lets
  `/implement` judge file-disjoint fan-out. Include the ticket's own test files. **Hotspot files**
  (routers, DI containers, barrel `index.*`, schema/migrations, lockfiles, shared types) must never
  appear in two unordered tickets — serialize them with an edge or single-owner the file.
- **`model`** — cheapest tier whose intelligence *and* taste clear the ticket's bar: `haiku`
  (mechanical, fully specified — rare for a vertical slice), `sonnet` (standard pattern-following —
  the default), `opus` (subtle correctness or real design judgment — justify each). Never `fable`.
- **`method`** — `tdd` (test-first at the spec's named seams; the default), `source-driven` (every
  external API grounded in official docs), `incremental` (thinnest slice, flags for risky paths).
  Methods compose; see `implement-core` for the worker-side definitions.

### 4. Quiz the user — the gate before publishing

Present the breakdown as a numbered list. Per ticket: **Title**, **Blocked by**, **What it
delivers**, **tier**. Then ask:

- Does the granularity feel right? (too coarse / too fine)
- Are the blocking edges correct — does each ticket only depend on what genuinely gates it?
- Should any tickets be merged or split further? Any tier overrides?

Iterate until approved. **Nothing is published before approval** — sub-issue creation is
outward-facing, and deleting wrongly-cut issues and re-linking edges is far worse than one approval
round.

### 5. Publish — one sub-issue per ticket, in dependency order

Create blockers first so their numbers exist for the edges:

```bash
gh issue create --title "<ticket title>" --body-file <tmp> \
  --parent <parent> --label "<agent-ready label>" [--blocked-by <m> ...]
```

(Resolve the agent-ready label from `docs/agents/triage-labels.md`; default `ready-for-agent`.
Edges can also be added after creation: `gh issue edit <n> --add-blocked-by <m>`.)

**Ticket body template:**

```markdown
## What to build

The end-to-end behaviour this ticket makes work, from the user's perspective — not
layer-by-layer implementation.

## Acceptance criteria

- [ ] Criterion 1 (checkable — a test passes, an output matches)
- [ ] Criterion 2

## Blocked by

- #<m> — <why it gates this>, or "None — can start immediately".

<!-- taskplan: {"files_owned": ["src/foo/**", "tests/foo/**"], "model": "sonnet", "method": "tdd"} -->
```

The visible body stays durable — behaviour and criteria, **no file paths, no code snippets** (they
go stale; exception: a prototype-derived snippet that encodes a decision more precisely than prose).
The machine contract lives in the HTML comment, invisible to humans and advisory to orchestrators —
`/implement` falls back to judging at dispatch time when it's missing.

**Never close or modify the parent issue** beyond the sub-issue links themselves.

### 6. Report + hand off

Print: the published graph (number → title → blocked-by → tier), the wave structure it implies
(which tickets are simultaneously unblocked and file-disjoint), and the next step:
**`/implement <parent>`** (add `--orca` for visible terminal workers). If the graph came out wider
or deeper than the spec implied (≥ ~10 tickets, or ≥ 2 independently-shippable clusters), say so —
that's a signal the parent should have been split at `/spec` time, and it's cheaper to split now
than after half the graph lands.

## Rules

- **Independence is discovered, not forced** — only omit an edge where slices are genuinely
  independent; don't shard a serial job into fake parallel tickets.
- **Acceptance criteria are the contract** — no ticket without checkable criteria.
- **Vocabulary from `CONTEXT.md`, boundaries from `docs/adr/`** — a ticket that contradicts an ADR
  must say so explicitly, not silently override it.
- **Approval before publication, always.**
- **Right-size the model** — everything-on-opus means the routing wasn't done.
- **Don't implement here** — the code belongs to `/implement`'s workers.

## Red flags

- A ticket has no acceptance criteria, or "make it work" as its only one → not ready.
- Two unordered tickets list the same file in `files_owned` → missing edge or wrong ownership.
- A hotspot file in two unordered tickets → serialize or single-owner it.
- The graph is one long chain of 10+ tiny tickets → slices too thin; merge neighbors.
- You're writing a plan file → wrong era; the graph is the plan.
