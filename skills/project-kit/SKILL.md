---
name: project-kit
description: >
  Bootstrap a repo for the GitHub-issue pipeline: create the triage + spec labels as real GitHub
  labels, write the tracker and label convention docs (docs/agents/), scaffold the domain-doc layout
  (CONTEXT.md glossary + docs/adr/), and wire an Agent skills block into CLAUDE.md. Detects the old
  project-kit JSON layout (docs/pm/) and offers a one-shot migration (decision records -> markdown
  ADRs, the rest deleted). Run once per repo, before /spec, /taskplan, /implement, or /triage.
  Usage: /project-kit [path]
trigger: /project-kit
user-invocable: true
argument-hint: "[path]"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "AskUserQuestion"]
---

# /project-kit

Bootstrap a repo's **agent-facing conventions** for the pipeline: GitHub Issues are the only state
store (specs = parent issues, tickets = sub-issues, dependencies = native blocked-by edges), the
domain model lives in git (`CONTEXT.md` + `docs/adr/`), and CLAUDE.md points agents at both.

| Layer | Where | Role |
|---|---|---|
| Labels | GitHub (real labels) | 5 triage states + 2 categories + `spec` |
| Tracker conventions | `docs/agents/issue-tracker.md` | How skills read/write the tracker |
| Label mapping | `docs/agents/triage-labels.md` | Canonical role → this repo's label strings |
| Glossary | `CONTEXT.md` (repo root) | The ubiquitous language; maintained by `domain-modeling` |
| Decisions | `docs/adr/NNNN-<slug>.md` | Minimal ADRs (title + 1–3 sentences); created lazily |
| Primer | `CLAUDE.md` marked block | Points agents at all of the above + the pipeline |

Templates live next to this file under `templates/`. `{{TOKEN}}`s are substituted by you; there is
no runtime templating.

## Steps

### 1. Detect & protect

Inspect the target root (argument path, default cwd). Never assume — look:

- **Git + GitHub**: a git repo with a GitHub remote (`git remote -v`)? `gh auth status` ok?
  `gh --version` ≥ **2.94** (the sub-issue/dependency flags)? Any of these failing → report what's
  missing and stop; this pipeline is GitHub-native.
- **Existing labels**: `gh label list --json name`.
- **Existing files**: `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md`, `CONTEXT.md`,
  `docs/adr/`, a `<!-- project-kit:begin -->` block in `CLAUDE.md`.
- **The old layout**: `docs/pm/` (status.json, decisions/*.json, dashboard, schemas), `docs/spec/`,
  `docs/plan/` → queue the migration offer (step 5).

Build a create-vs-skip list. **Never overwrite an existing file** — the only refresh-in-place
targets are the marked `CLAUDE.md` block and label descriptions.

### 2. Confirm the little that needs confirming

Infer the project name + one-liner (README, manifests) for the `CONTEXT.md` seed. Ask only what
inference can't resolve — typically nothing, at most: confirm GitHub as the tracker if the remote is
ambiguous, and whether external PRs are a request surface (default **no**; it only matters for
`/triage`). Keep it to 0–2 questions.

### 3. Create the labels

For each label missing from the repo, `gh label create <name> --color <hex> --description "<desc>"`
(skip ones that exist; if `bug`/`enhancement` exist with GitHub's defaults, that counts):

| Label | Color | Description |
|---|---|---|
| `needs-triage` | `fbca04` | Maintainer needs to evaluate this issue |
| `needs-info` | `d876e3` | Waiting on reporter for more information |
| `ready-for-agent` | `0e8a16` | Fully specified, ready for an AFK agent |
| `ready-for-human` | `1d76db` | Requires human implementation |
| `wontfix` | `ffffff` | Will not be actioned |
| `bug` | `d73a4a` | Something is broken |
| `enhancement` | `a2eeef` | New feature or improvement |
| `spec` | `5319e7` | Parent spec issue (from /spec) — not a ticket, never dispatch |

Creating real labels at bootstrap is load-bearing: `gh issue create --label <missing>` fails
outright, so this removes the publish-time failure mode from `/spec` and `/taskplan`.

### 4. Write the convention docs + domain scaffold

- `docs/agents/issue-tracker.md` ← `templates/issue-tracker-github.md`
  (`{{PRS_AS_REQUESTS}}` from step 2; default `no`).
- `docs/agents/triage-labels.md` ← `templates/triage-labels.md` (identity mapping unless the repo
  already uses different label strings — then fill the right-hand column with the real ones instead
  of creating duplicates in step 3).
- `CONTEXT.md` (repo root), only if absent — seed it minimally per `domain-modeling`'s
  CONTEXT-FORMAT: the project name, the one-liner, and an empty `## Language` section. It grows
  during `/spec` grilling sessions, not here.
- `docs/adr/` — created lazily by `domain-modeling` when the first ADR is warranted; don't scaffold
  placeholder files. (If migrating old decision records, step 5 creates it now.)

### 5. Migrate the old layout (only when detected, only with approval)

If `docs/pm/` exists, offer **once**, as a single yes/no:

> Old project-kit layout detected. Migrate: convert `docs/pm/decisions/*.json` → `docs/adr/*.md`,
> then delete `docs/pm/` (status.json, dashboard, schemas — GitHub Issues replace them). Also
> delete `docs/spec/` and `docs/plan/` if present (their successors are parent issues and
> sub-issue graphs)?

On yes:

- Each `docs/pm/decisions/NNNN-*.json` → `docs/adr/NNNN-<slug>.md` in the minimal ADR format: the
  JSON's title as `# <title>`, its context/decision/rationale collapsed to 1–3 sentences, a
  `Status:` line only when the record was superseded/deprecated (note `superseded by ADR-NNNN`).
  Keep the numbering.
- `rm -rf docs/pm/` (and `docs/spec/`, `docs/plan/` if approved). The status/dashboard layer has no
  successor by design — live state now lives in GitHub issues.
- Remove any pre-migration `<!-- project-kit:begin -->` block content in `CLAUDE.md` (step 6
  replaces it).

On no: leave everything, note the old layout coexists, and continue.

### 6. Merge into `CLAUDE.md`

The block is `templates/CLAUDE.block.md` (substitute `{{TRIAGE_SUMMARY}}` — e.g. "Default triage
vocabulary (needs-triage / needs-info / ready-for-agent / ready-for-human / wontfix + bug /
enhancement)"). Delimited by `<!-- project-kit:begin -->` / `<!-- project-kit:end -->`:

- No `CLAUDE.md` → create it: `# <name>`, the one-liner, then the block.
- Markers present → replace between them (re-run safe). Never touch anything outside the markers.
- No markers → append the block at the end.

### 7. Report

Print created vs skipped (labels, files, block handling, migration outcome), then the next step:

> Bootstrap done. Start a feature with `/spec <idea>`; triage inbound issues with `/triage`.

## Design rules

- **Idempotent / non-destructive.** Safe to re-run; skip-if-exists everywhere except the marked
  block. The migration is the one destructive path, and it runs only on explicit approval.
- **GitHub is the only state store.** No status file, no dashboard, no milestone layer — the parent
  issue's sub-issue progress is the status view.
- **Labels are created, not just documented** — a documented-but-missing label is a publish-time
  crash in a downstream skill.
- **The glossary and ADRs belong to `domain-modeling`** — this skill scaffolds the seed and the
  layout, never content.
