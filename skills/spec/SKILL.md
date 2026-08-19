---
name: spec
description: >
  Turn a rough feature idea into a published parent spec issue on GitHub. Grills the user in
  frontier rounds (via the plugin's grilling + domain-modeling skills), writing glossary terms to
  CONTEXT.md and ADRs to docs/adr/ as decisions crystallize; synthesizes the spec into the parent
  issue body (Problem Statement / Solution / User Stories / Implementation Decisions / Testing
  Decisions / Out of Scope); splits into sibling parent issues when the work exceeds one PR; runs a
  fresh-eyes review before publishing. The issue body IS the spec. The define stage that feeds
  /taskplan then /implement. Use at the START of a non-trivial feature.
trigger: /spec
user-invocable: true
argument-hint: "<feature description | rough idea | path to notes>"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "AskUserQuestion", "WebFetch", "Agent", "Skill"]
---

# /spec

Write the **spec before the code** — as a **parent issue on GitHub**, not a file. This is the
*define* stage of the pipeline: `/spec` publishes the parent, `/taskplan` hangs sub-issues off it,
`/implement` builds the graph. The parent issue body is the single source of truth for
work-in-flight; the durable outputs of the thinking — glossary terms and architectural decisions —
land in git (`CONTEXT.md`, `docs/adr/`) as the session runs.

## When to use

- **Use** at the start of any non-trivial feature where the "what/why" isn't fully pinned.
- **Skip** for a one-line fix or a mechanical change — file a ticket directly (or `/triage` it) and
  go to `/implement <n>`.

## Preconditions

`/project-kit` has run: the `spec` label and triage labels exist, `docs/agents/issue-tracker.md`
names the tracker. If the `spec` label is missing, stop and point at `/project-kit`.

## Process

### 1. Orient — infer before you ask

Read what the repo already tells you so the grilling is short and never re-asks known facts:

- `CONTEXT.md` (or `CONTEXT-MAP.md`) — the domain glossary; use its vocabulary throughout.
- `docs/adr/*` in the touched area — locked decisions. A request that contradicts one must be
  surfaced in the grilling, not papered over.
- README, CLAUDE.md, and the code the feature touches.
- Open `spec`-labeled issues — the new spec may overlap or depend on one.
- For any external API/library the feature leans on, fetch official docs rather than guessing.

### 2. Grill — frontier rounds, docs as you go

Invoke the plugin's **`grilling`** skill and run it together with **`domain-modeling`**: map the
feature as a design tree, ask each round's full frontier (numbered questions, each with your
recommended answer), dispatch sub-agents for facts, and put every *decision* to the user.

As decisions crystallize, `domain-modeling` discipline applies inline:

- A resolved term → `CONTEXT.md`, immediately, in its format.
- A decision that is hard to reverse + surprising without context + a real trade-off → offer an ADR
  (`docs/adr/NNNN-<slug>.md`, minimal format: title + 1–3 sentences). Sparingly — most decisions
  just live in the spec.

Also settle the **test seams** during grilling: prefer existing seams, the highest and fewest
possible (ideally one). The agreed seams go into Testing Decisions — `/taskplan`'s `tdd` method and
the workers depend on them being named.

The grilling ends when the frontier is empty and the user confirms shared understanding.

### 3. Synthesize the spec

Draft the parent issue body (write it to a scratch file for the review step):

```markdown
## Problem Statement

The problem the user is facing, from the user's perspective.

## Solution

The solution, from the user's perspective.

## User Stories

A LONG, numbered list: "As a/an <actor>, I want <feature>, so that <benefit>." Extensive —
cover all aspects of the feature.

## Implementation Decisions

The decisions the grilling produced: modules built/modified and their interfaces, architectural
decisions (link any ADRs written), schema changes, API contracts, UX/style constraints, specific
interactions. NO file paths or code snippets — they go stale fast. Exception: a prototype-derived
snippet that encodes a decision more precisely than prose (state machine, schema, type shape),
trimmed to the decision-rich parts.

## Testing Decisions

What makes a good test here (external behaviour, not implementation details), the agreed seams,
which modules get tested, prior art in the codebase.

## Out of Scope

What is explicitly NOT in this spec — the most important section for preventing scope creep.

## Further Notes

Anything else worth carrying (open follow-ups, links to the grilling's key facts).
```

### 4. Split check — one parent per PR

**The invariant downstream is 1 parent = 1 worktree = 1 PR.** Before review, test the draft:

- Does the work contain **≥ 2 independently-shippable feature boundaries** (each demoable without
  the other)?
- Or would it project to **more than ~8–10 sub-issues** (beyond that, a single PR stops being
  reviewable)?

If either trips, **propose a split into flat sibling parent issues** — one mini-round: the cut
points, what each part ships, and the ordering. Cut points are product decisions — **the user
approves every split.** Siblings that must ship in order get native `blocked-by` edges between the
parents; the narrative link is a body line ("Part 2 of 3 — follows #41"). No epic grandparent — the
two-level shape (parent → sub-issues) is what every skill consumes.

### 5. Fresh-eyes review — delegated, revises in place

Spawn ONE `general-purpose` subagent with `model: "opus"` to review the draft body file(s) with
fresh eyes. Its prompt: read the draft plus the same repo context step 1 named (`CONTEXT.md`,
relevant ADRs); check for ambiguity an implementer could guess wrong, unfalsifiable requirements,
missing out-of-scope, contradictions with ADRs or the glossary, untestable acceptance; **edit the
file in place**; return only `CHANGELOG:` (one line per edit) and `OPEN ISSUES:` (judgment calls
only the user can settle).

Adjudicate, don't re-review: skim the changelog, revert what you reject, resolve OPEN ISSUES with
the user.

### 6. Publish

For each parent (in dependency order when split):

```bash
gh issue create --title "<feature title>" --body-file <draft> --label spec \
  [--blocked-by <earlier-sibling>]
```

The `spec` label is the queryable identity ("all open specs"). Do NOT add the agent-ready label — a
spec is not a ticket, and nothing may ever dispatch it as one.

### 7. Report + hand off

Print the issue URL(s), the ADRs/glossary terms written during the session, and the next step:
**`/taskplan <parent>`** (per sibling, respecting their ordering).

## Rules

- **The issue body is the spec.** No `docs/spec/*.md` shadow copy — one source of truth.
- **Facts are yours, decisions are the user's** — the grilling discipline, end to end.
- **Durable thinking lands in git as it happens** — glossary and ADRs are written mid-session, not
  batched.
- **Scope discipline** — the spec captures the request, not adjacent features you'd like to add.
- **Verifiable over vague** — every requirement checkable, or it isn't a requirement yet.
- **Don't design the build here** — decomposition, boundaries, and tiers belong to `/taskplan`.
- **Never label a spec agent-ready.**

## Red flags

- You started writing code or file-level task lists → wrong stage; this is define-only.
- The spec has no Out of Scope → scope is unbounded.
- Acceptance is "works well / looks good" → not falsifiable.
- You asked one question at a time → that's the old interview; grilling works in frontier rounds.
- You're about to publish a spec that projects to 15 sub-issues → the split check didn't run.
- You wrote an ADR for an easily-reversed choice → the three-part test failed; delete it.
