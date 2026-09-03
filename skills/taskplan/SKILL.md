---
name: taskplan
description: >
  Decompose a parent spec issue into vertical-slice sub-issues on GitHub — native --parent links,
  native blocked-by dependency edges, ready-for-agent by construction — each carrying checkable
  acceptance criteria and an advisory taskplan metadata block (method; plus files_owned and model
  tier, which only /implement-orc reads). Quizzes the user for approval BEFORE publishing
  anything. The plan stage between /spec and /implement; the issue graph it publishes IS the plan —
  no plan file.
trigger: /taskplan
user-invocable: true
argument-hint: "<parent issue number, e.g. 42>"
allowed-tools: ["Read", "Bash", "Glob", "Grep", "AskUserQuestion", "WebFetch"]
---

# /taskplan

Turn a parent spec issue into a **published, dependency-linked sub-issue graph**. This is the *plan*
stage of the pipeline: `/spec` published the parent (the spec is its body); `/taskplan` decomposes
it into tickets sized and shaped so `/implement`'s walk is nearly free — every ticket already
carries its acceptance criteria, its blocking edges, and its method. By default `/implement` builds
the whole graph in one session (solo mode); a ticket is a **checkpoint** in that walk — a commit, a
review scope, a `Closes` row — not a unit of delegation.

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
- Prefer fewer, larger tickets. Size a slice as a **checkpoint**: the amount of work you'd be
  willing to redo if the session died right after it, and a diff a reviewer can hold in one read.
  Each ticket costs a fixed re-read of its contract and criteria and one commit/verify cycle, so a
  slice smaller than a meaningful checkpoint is pure overhead — merge it into a neighbour. A slice
  that can't land green on its own is too big — split it. Line counts are not the measure.
- Prefactoring first.

Give each ticket its **blocking edges** — the tickets that must land before it can start. No
blockers = startable immediately. Edges are **ordering**, and `/implement` walks them serially in
solo mode. Where two slices have disjoint file sets and no data dependency, give them **no edge** —
that is what lets `/implement-orc` fan them out if the user asks for it. Don't fake independence — a
false missing edge puts work in the wrong order.

**Wide refactors are the exception to vertical slicing.** One mechanical change with codebase-wide
blast radius (rename a column, retype a shared symbol) can't land green as a tracer bullet —
sequence it as **expand–contract**: an *expand* ticket (add the new form beside the old; nothing
breaks), *migrate* tickets in blast-radius-sized batches (each blocked by expand, CI green batch to
batch), and a *contract* ticket (delete the old form, blocked by every migrate batch).

### 3. Attach metadata per ticket

- **`method`** — the one field solo mode reads. `tdd` (test-first at the spec's named seams; the
  default), `source-driven` (every external API grounded in official docs), `incremental` (thinnest
  slice, flags for risky paths). Methods compose; see `implement-core` §3 for the definitions.

The next two are **orchestration metadata** — advisory, read only by `/implement-orc`.
Still fill them in: they cost one line and the user may ask for workers later.

- **`files_owned`** — the globs/paths the ticket will create or modify, including its own test
  files. This is what lets an orchestrator judge file-disjoint fan-out. **Hotspot files** (routers,
  DI containers, barrel `index.*`, schema/migrations, lockfiles, shared types) must never appear in
  two unordered tickets — serialize them with an edge or single-owner the file.
- **`model`** — the worker tier. `opus` is the default. `sonnet` only for a ticket that touches no
  hotspot file and follows an existing pattern exactly — justify it in one clause. Those are the only
  two. Never `fable`, and **never `haiku`** (12.5% rework against sonnet's 3.2% across 24 logged
  agents). Sonnet took ~2.7× the turns of opus on shared-file tickets — the same money and 1.6× the
  wall-clock. In solo mode the session's own model is the tier and this field is ignored.

### 4. Quiz the user — the gate before publishing

Present the breakdown as a numbered list. Per ticket: **Title**, **Blocked by**, **What it
delivers**, **method**. Above the list, print the **shape line** derived from the edges and
`files_owned`:

```
N tickets · walk depth D · max wave width W → /implement (solo) · /implement-orc would run chain | fan-out
```

`chain` when fewer than half the tickets can run in a wave of width ≥ 2, else `fan-out`. Solo is
what `/implement` will do regardless; the orchestrated verdict is there so the user knows what
`/implement-orc` would do before anything is published. **Read `N` as checkpoint count**: many small tickets
mean many re-reads and commits for the same work — if two neighbours would each land in a few
minutes, they are one checkpoint. Then ask:

- Does the granularity feel right? (too coarse / too fine)
- Are the blocking edges correct — does each ticket only depend on what genuinely gates it?
- Should any tickets be merged or split further?

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

<!-- taskplan: {"files_owned": ["src/foo/**", "tests/foo/**"], "model": "opus", "method": "tdd"} -->
```

The visible body stays durable — behaviour and criteria, **no file paths, no code snippets** (they
go stale; exception: a prototype-derived snippet that encodes a decision more precisely than prose).
The machine contract lives in the HTML comment, invisible to humans and advisory to `/implement` —
which falls back to judging `method` itself when it's missing.

**Never close or modify the parent issue** beyond the sub-issue links themselves.

### 6. Report + hand off

Print: the published graph (number → title → blocked-by → method), the walk order `/implement`
will take, the shape line from step 4, and the next step: **`/implement <parent>`** — solo, in one
session. Mention `/implement-orc <parent>` (`--orca` for Orca terminals) only as the opt-in it is;
don't recommend it from a wide graph — that's the user's call. If the graph came out wider
or deeper than the spec implied (≥ ~10 tickets, or ≥ 2 independently-shippable clusters), say so —
that's a signal the parent should have been split at `/spec` time, and it's cheaper to split now
than after half the graph lands.

### Record what this stage cost

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/stats/stats.py record --issue <parent> --stage taskplan
```

**Do this before the session is cleared.** Stage attribution cannot be reconstructed from
transcripts afterwards, so a stage that skips this is unrecoverable and `/cleanup`'s pipeline
rollup will report it as `MISSING`. Re-running it is harmless — the row is replaced, not appended.

## Rules

- **Independence is discovered, not forced** — only omit an edge where slices are genuinely
  independent; don't shard a serial job into fake parallel tickets.
- **Acceptance criteria are the contract** — no ticket without checkable criteria.
- **Vocabulary from `CONTEXT.md`, boundaries from `docs/adr/`** — a ticket that contradicts an ADR
  must say so explicitly, not silently override it.
- **Approval before publication, always.**
- **A ticket is a checkpoint** — sized to what you'd redo after a crash and what a reviewer reads in
  one sitting; not a unit of delegation.
- **Fill in the orchestration fields anyway** (`files_owned`, `model` — opus by default, `sonnet`
  with its one-clause justification). `/implement` ignores them; `/implement-orc` needs them.
- **Don't implement here** — the code belongs to `/implement`.

## Red flags

- A ticket has no acceptance criteria, or "make it work" as its only one → not ready.
- Two neighbouring tickets would each land in minutes → one checkpoint, not two. Merge them.
- A ticket can't land green on its own (its tests need the next ticket's code) → the slice is
  horizontal, not vertical. Re-cut it.
- Two unordered tickets list the same file in `files_owned` → missing edge or wrong ownership
  (matters to `/implement-orc`; harmless but sloppy for `/implement`).
- A hotspot file in two unordered tickets → serialize or single-owner it.
- You're writing a plan file → wrong era; the graph is the plan.
