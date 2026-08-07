---
name: spec
description: >
  Turn a rough feature idea into a written PRD before any code. Interview one question at a time
  (only for gaps inference can't fill), surface assumptions, write docs/spec/<slug>.md covering
  objective, structure, testing, and boundaries, then delegate a fresh-eyes review (opus) that
  revises the doc in place. The define stage that feeds /taskplan then /implement.
  Use at the START of a non-trivial feature, when the "what/why" isn't yet pinned down.
trigger: /spec
user-invocable: true
argument-hint: "<feature description | rough idea | path to notes>"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "AskUserQuestion", "WebFetch", "Agent"]
---

# /spec

Write the **spec before the code**. This is the *define* stage of the spec → taskplan → implement
pipeline: it produces a PRD (`docs/spec/<slug>.md`) that `/taskplan` decomposes into tasks and
`/implement` builds. Benchmarks agent-skills `spec-driven-development` + `interview-me`.

A spec's job is to make the work *unambiguous and verifiable* — not to design the implementation.
Capture what to build, why, and how you'll know it's done; leave the how-to-build to `/taskplan`.

## When to use

- **Use** at the start of any non-trivial feature where the "what/why" isn't fully pinned.
- **Skip** for a one-line fix, a mechanical change, or work whose spec already exists — go straight
  to `/taskplan` or a single implementer.

## Process

### 1. Orient — infer before you ask
Read what the repo already tells you so the interview is short and you don't re-ask known facts:
- The repo's design docs — whatever lives under `docs/` (project brief, data model, protocol/API
  specs, UI docs) plus the README and CLAUDE.md.
- Current state, if the repo uses project-kit: `docs/pm/status.json` (now/next), relevant
  `docs/pm/decisions/*.json` (locked calls).
- If graphify-out/ exists, `graphify query "<feature area>"` to locate the touched code.
- For any external API/library the feature leans on, fetch official docs (context7/WebFetch) rather
  than guessing its surface.

### 2. Surface assumptions
Before interviewing, **state your assumptions explicitly** — what you're taking as given from the
docs and the request. This turns silent guesses into things the user can correct cheaply.

### 3. Interview for gaps only — one question at a time
Use **AskUserQuestion** to fill *only* what inference couldn't resolve. Ask the single highest-value
question, take the answer, then decide the next — don't batch a wall of questions. Stop when you're
~confident you could hand the spec to an implementer without them having to guess intent. Typical
gaps: the core user outcome, scope edges (what's explicitly out), UX/style constraints, how success
is measured.

Manage confusion actively: if the request contradicts a locked decision or an existing doc, **name
the conflict and resolve it** before writing — don't paper over it.

### 4. Write the PRD → `docs/spec/<slug>.md`
Derive `<slug>` as kebab-case from the feature (e.g. `dates-today-view`). Write these sections:

```markdown
# <Feature title>

> Spec — feeds `/taskplan docs/spec/<slug>.md`. Status: draft | ready.

## Objective
The single outcome this delivers, in 1–2 sentences. What the user can do after that they couldn't before.

## Why (context)
The problem/need. What prompted it. Link the driving doc/decision/status item.

## User stories / scenarios
Concrete "As a … I can … so that …" or walkthrough scenarios. The behavior, not the mechanism.

## Structure (what changes, where)
The surfaces touched — modules/files/screens/endpoints — at a *pointing* level, not a design.
Enough for /taskplan to draw a file-ownership map.

## Style / UX constraints
Design-system, naming, accessibility, platform (Mac/iOS), copy constraints that bound the build.

## Testing strategy
How correctness is proven: the key cases, the test levels (unit/integration/UI), what "done" looks like.

## Boundaries / non-goals
What is explicitly OUT of scope. The single most important section for preventing scope creep.

## Open questions
Anything still unresolved. Empty when the spec is `ready`.
```

Keep it falsifiable: concrete cases over adjectives. If a section is genuinely N/A, say so — don't pad.

### 5. Fresh-eyes review — delegated, revises in place
Spawn ONE `general-purpose` subagent with `model: "opus"` to review the draft with fresh eyes. Do
NOT have it return findings for you to apply — that round-trips the whole review through this
session's context and turns you into the editor. Instead, its prompt:

- Read `docs/spec/<slug>.md` plus the same repo context step 1 named (docs/, status.json, relevant
  decisions).
- Check: ambiguity (could an implementer guess wrong?), unfalsifiable requirements, missing
  non-goals, contradictions with repo docs or locked decisions, untestable acceptance.
- **Edit the spec file in place** to fix what is clearly wrong or missing.
- Return ONLY two compact lists — no restatement of the document:
  `CHANGELOG:` each edit as one line (what changed + why);
  `OPEN ISSUES:` judgment calls it deliberately did not decide (conflicts with locked decisions,
  scope questions only the user can settle).

Then **adjudicate, don't re-review**: skim the changelog against the file, revert any change you
reject (Edit is fine — the spec is an orchestration artifact, not source code), and resolve OPEN
ISSUES with the user via AskUserQuestion. The user's manual read of the finished spec remains the
gate for `draft → ready` — this step feeds that gate; it does not replace it.

### 6. Report + hand off
Print the path and the status (draft/ready), the review changelog summary, and the next step:
**`/taskplan docs/spec/<slug>.md`**.

## Rules (inherited from the define discipline)
- **Surface assumptions** before building on them.
- **One question at a time**, gaps only — never re-ask what the repo answered.
- **Scope discipline** — the spec captures the request, not adjacent features you'd like to add.
- **Verifiable over vague** — every requirement must be checkable, or it isn't a requirement yet.
- **Don't design here** — implementation choices belong to `/taskplan` and the implementers.

## Red flags
- You started writing code or file-level design → wrong stage; this is define-only.
- The spec has no non-goals → scope is unbounded; add the boundaries.
- Acceptance is "works well / looks good" → not falsifiable; make it concrete.
- You batched ten questions at once → interview one at a time instead.

## Verification
- [ ] `docs/spec/<slug>.md` exists with every section (N/A explicitly where it applies).
- [ ] Objective is one clear outcome; non-goals are stated.
- [ ] Assumptions were surfaced; open questions are empty if status is `ready`.
- [ ] Fresh-eyes review ran (delegated, opus); changelog adjudicated; OPEN ISSUES resolved or
      carried into Open questions.
- [ ] Reported the path and pointed at `/taskplan docs/spec/<slug>.md`.
