---
name: project-kit
description: >
  Bootstrap a project's agent-facing context system — structured JSON docs (live status +
  decision records) rendered by a live HTML dashboard, plus the operating rules that keep
  them current, wired into CLAUDE.md. Use when setting up context docs for a new or existing
  project, "set up project docs", "scaffold status/ADRs", or first-time project setup.
  Usage: /project-kit [--minimal | --full] [path]
trigger: /project-kit
user-invocable: true
argument-hint: "[--minimal | --full] [path]"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "AskUserQuestion"]
---

# /project-kit

Bootstrap a project's **agent-facing context system** into any project, on the first
session. It creates a small set of *living* docs as **structured JSON** (so they're machine-
readable and never drift from a separate copy), ships a **live HTML dashboard** to read them
at a glance, and wires the rules that keep them current into `CLAUDE.md`.

The system is layered by how fast things change. The **data is JSON** (the source of truth that
agents read and write); the **dashboard renders it** for humans:

| Layer | File | Role |
|---|---|---|
| Primer (auto-loaded) | `CLAUDE.md` | Always-on orientation + the self-maintaining rule. Points at `status.json`, doesn't duplicate it. |
| Live state | `docs/pm/status.json` | Now / Next / Milestones / Blocked / Shipped. The "where are we" source of truth. |
| Decisions | `docs/pm/decisions/NNNN-*.json` | One ADR (JSON) per direction change. Numbered, fixed once accepted. |
| Field contracts | `docs/pm/schema/*.schema.json` | JSON Schema for each doc — the shape + per-field guidance. Consult before writing. |
| Dashboard | `docs/pm/dashboard/` | Read-only viewer: `serve.py` (stdlib, live-reload) + `index.html`. `python3 docs/pm/dashboard/serve.py`. |
| Thesis & spec *(opt-in)* | `docs/pm/project-summary.json`, `prd.json` | The "why" and the buildable "what". Only with `--full`. |

**Lean by default**: status + ADRs + schemas + dashboard + the `CLAUDE.md` rules. The thesis/spec layer is opt-in.

## Usage

```
/project-kit                 # infer from repo, interview only for gaps, scaffold lean
/project-kit --minimal       # blank templates, no inference, no questions
/project-kit --full          # also scaffold project-summary.json + prd.json
/project-kit <path>          # target a different project root (default: current dir)
/project-kit --help          # print this Usage block and stop
```

If invoked with `--help` / `-h` and no other arguments, print the `## Usage` block
verbatim and stop. Do nothing else.

## What you must do when invoked

The templates live next to this file under `templates/`. The JSON docs and the `CLAUDE.md` block
carry `{{TOKEN}}` placeholders you substitute (mapping below) — **you** (the agent) do the
substitution; the tokens are not a runtime feature. The dashboard (`dashboard/`) and schemas
(`schema/`) are **static tooling copied verbatim**, with no tokens.

### Step 0 — Parse arguments
- `--minimal` → skip Steps 2 & 3 entirely (no inference, no questions); write templates with the
  bracketed `[…]` placeholders left in place for the user to fill.
- `--full` → in Step 4, also scaffold the optional thesis + spec docs (and their two schemas).
- A bare non-flag argument → the **target project root**. Default: the current working directory.
- Resolve the skill's own directory (where `templates/` sits) so you can read the templates —
  e.g. `ls "$(dirname …)"`; if unsure, the templates are at `${CLAUDE_PLUGIN_ROOT}/skills/project-kit/templates/`.

### Step 1 — Detect & protect (always)
Inspect the target root. Use Glob/Read — do **not** assume.
- Is there a `CLAUDE.md`? a `docs/pm/`? `docs/pm/status.json`? `docs/pm/decisions/`? `docs/pm/schema/`? `docs/pm/dashboard/`?
- Build a **create vs. skip** list. **Never overwrite an existing file.** If a target file already
  exists, leave it untouched and report it as *skipped* in Step 6.
- The one exception is the marked block in `CLAUDE.md` (Step 5) and the generated decisions index
  (Step 4a), which are refreshed in place.

### Step 2 — Infer from the repo (skip if `--minimal`)
Draft the project's identity from what's already there, so the scaffold ships filled, not empty:
- **README** (`README*`), and any existing `CLAUDE.md` → project name, one-liner, purpose.
- **Manifests** — `package.json`, `pyproject.toml`/`setup.py`, `Cargo.toml`, `go.mod`, `*.xcodeproj`/`project.yml`, `pom.xml`, etc. → name, language/stack, scripts.
- **`git log --oneline -20`** and `git config user.name` → recent direction, current focus, owner.
- **Top-level layout** → what kind of project this is and where the work is.

From these, draft: `PROJECT_NAME`, `ONE_LINER`, a first-pass `NOW` / `NEXT`, any obvious
milestones, and a sketch of the `CORE_BET`. Today's date: get it with `date +%F`.

### Step 3 — Interview for gaps only (skip if `--minimal`)
Use **AskUserQuestion** to fill *only* what inference could not resolve confidently. Do not
re-ask what the repo already answered. Typical gaps: the **core bet** (the non-obvious idea),
the **near-term focus** for *Now/Next*, and confirmation of the name/one-liner if ambiguous.
Keep it to 1–3 questions. If everything was inferable, skip this step.

### Step 4 — Fill & write the JSON docs
The templates are **valid JSON**. Substitute scalar tokens, and for array fields replace the
bracketed placeholder entries with real inferred content (or, under `--minimal`, leave the
bracketed placeholder strings intact — the file stays valid JSON either way). Write to the
**target** root:
- `docs/pm/status.json`          ← `templates/status.json`
- `docs/pm/decisions/_template.json`            ← `templates/decisions/_template.json`
- `docs/pm/decisions/0001-initial-direction.json` ← `templates/decisions/0001-initial-direction.json`
- `docs/pm/decisions/README.md` — the decisions index, **generated** (see Step 4a)
- **`--full` only:** `docs/pm/project-summary.json` ← `templates/optional/project-summary.json`,
  and `docs/pm/prd.json` ← `templates/optional/prd.json`.

For any file already present (from Step 1), skip it — never clobber. After writing, the JSON must
parse: each shape is defined in `docs/pm/schema/` (copied in Step 4b) — match it.

**Token map** (scalars; substitute directly):

| Token | Source |
|---|---|
| `{{PROJECT_NAME}}` | inferred / confirmed (Steps 2–3) |
| `{{ONE_LINER}}` | inferred / confirmed |
| `{{CORE_BET}}` | interview (Step 3); under `--minimal` leave the bracketed placeholder |
| `{{NOW}}` / `{{NEXT}}` | inferred / interview — these sit inside the `now` / `next` arrays |
| `{{DATE}}` | `date +%F` |
| `{{OWNER}}` | `git config user.name` (fallback: leave `[name]`) |
| `{{OPTIONAL_LAYOUT_LINES}}` | empty for lean; under `--full`, two bullets for `project-summary.json` + `prd.json` (see Step 5) |

Array fields beyond `now`/`next` (milestones, blocked, shipped, etc.) aren't single tokens — fill
them from inference, or under `--minimal` leave the seeded bracketed placeholder entry. `status.json`
ships with one `shipped` entry recording the bootstrap; keep it.

### Step 4a — Generate the Decisions index (always)
Write `docs/pm/decisions/README.md` — a catalog of the ADRs. **Build it from the JSON files, don't hand-author it:**
1. List every `docs/pm/decisions/NNNN-*.json`, sorted by `number` — **exclude** `_template.json`. (On an existing project this picks up *all* prior ADRs, not just `0001`.)
2. For each: read **`number`**, **`title`**, and **`status`** from the JSON. Link the number to the `.json` file.
3. Mark **supersession** from the structured fields, not prose: a record whose `supersededBy` is set takes status `Superseded (by NNNN)` in the index (zero-pad NNNN). The `supersedes`/`supersededBy` pair is authoritative — no need to read the body.
4. Emit the rows into the `templates/decisions/README.md` layout (keep its marker comment + surrounding prose).

This file is a **generated artifact**, so unlike the source docs it is *regenerated*, not skipped, on re-run — but only when it is absent or carries the `<!-- project-kit:decisions-index -->` marker. If a `README.md` exists in that folder **without** the marker, treat it as the user's own file: leave it and report it skipped.

### Step 4b — Copy the dashboard + schemas (always; static, no tokens)
Copy these **verbatim** (no substitution) into the target — they are tooling, not content:
- `docs/pm/dashboard/index.html` ← `templates/dashboard/index.html`
- `docs/pm/dashboard/serve.py`   ← `templates/dashboard/serve.py`
- `docs/pm/schema/status.schema.json`   ← `templates/schema/status.schema.json`
- `docs/pm/schema/decision.schema.json` ← `templates/schema/decision.schema.json`
- `docs/pm/schema/plan.schema.json`     ← `templates/schema/plan.schema.json` (the shape `/taskplan` writes to `docs/plan/` and `/implement` consumes)
- **`--full` only:** `docs/pm/schema/project-summary.schema.json` and `docs/pm/schema/prd.schema.json`.

These are **skip-if-exists** like the source docs — never clobber a dashboard the user has customized.
(To pick up an updated renderer later, the user deletes the file and re-runs.) Prefer a real file
copy (e.g. `cp`) so bytes are identical; only fall back to Read+Write if needed.

### Step 5 — Merge into `CLAUDE.md` (always)
The block to insert is `templates/CLAUDE.block.md` (with tokens substituted). It is delimited by
`<!-- project-kit:begin … -->` / `<!-- project-kit:end -->`.

- **`--full`:** set `{{OPTIONAL_LAYOUT_LINES}}` to:
  ```
  - `docs/pm/project-summary.json` — the thesis / "why". Read first for full context; changes slowly. Shape: `schema/project-summary.schema.json`.
  - `docs/pm/prd.json` — the current version's buildable requirements. Shape: `schema/prd.schema.json`.
  ```
  Otherwise set it to empty (the line vanishes).
- **No `CLAUDE.md` exists:** create it as `# {{PROJECT_NAME}}`, a blank line, `{{ONE_LINER}}`,
  a blank line, then the substituted block.
- **`CLAUDE.md` exists and already contains `<!-- project-kit:begin -->`:** this is a re-run —
  replace everything between the two markers (inclusive) with the freshly substituted block. Leave
  the rest of the file exactly as-is.
- **`CLAUDE.md` exists with no markers:** append the substituted block at the end of the file. **But**
  if the file already has a `## Status` heading, omit the block's own `## Status` section (keep only
  *Repo layout* + *Keeping the record current*) so you don't create a second Status section — and say
  so in the report.

Never edit any part of an existing `CLAUDE.md` outside the marked region.

### Step 6 — Report
Print a short tree of what was **created** vs. **skipped** (already existed), note how `CLAUDE.md`
was handled (created / block-updated / appended / Status-section-omitted), and end with the next
steps: *"Fill the bracketed placeholders in `docs/pm/status.json` and `decisions/0001-…json`, then
view it live: `python3 docs/pm/dashboard/serve.py`. Commit when ready."*

## Design rules (hold to these)
- **Idempotent / non-destructive.** Safe to re-run. Never overwrite a user's file. The two *generated*
  artifacts — the `CLAUDE.md` marked region and `decisions/README.md` (its index marker) — are refreshed
  in place; everything else (JSON docs, schemas, dashboard) is skip-if-exists.
- **JSON is the source of truth; the dashboard is a view.** Agents read and write the JSON; humans read
  the rendered dashboard. There is no second copy to keep in sync.
- **Generalize, don't copy.** These templates carry the *patterns* (layer split, the self-maintaining
  rule, the ADR skeleton, the dated/falsifiable discipline) — never any one project's domain content.
- **Infer-first, interview-for-gaps.** Ship filled content; ask only what the repo can't tell you.
- **Lean by default.** Status + ADRs + schemas + dashboard + CLAUDE rules; thesis/spec are opt-in via `--full`.
- **Keep entries specific and falsifiable** — the docs you scaffold should model the discipline: cite
  dates, link commits/ADRs, snapshot-not-journal.
