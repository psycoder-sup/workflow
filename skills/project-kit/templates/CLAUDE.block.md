<!-- project-kit:begin — managed block. Safe to edit; re-running /project-kit updates only between these markers. -->

## Status

{{ONE_LINER}}

**Live state lives in [`docs/pm/status.json`](docs/pm/status.json) — read it first each session.** It's structured JSON (Now / Next / Milestones / Blocked / Shipped) and the single source of truth; this primer **does not** copy it here, so there's nothing to keep in sync. Humans: launch the live dashboard with `python3 docs/pm/dashboard/serve.py`.

## Repo layout (context docs)

- `docs/pm/status.json` — live project state (now / next / milestones / blocked / shipped). The first thing to read each session — keep it lean. Shape: `docs/pm/schema/status.schema.json`.
- `docs/pm/decisions/` — decision records (ADRs): one JSON per direction change, numbered, fixed once accepted. `NNNN-*.json` are the records (shape: `schema/decision.schema.json`), `_template.json` is the skeleton, `README.md` is the auto-generated index.
- `docs/pm/schema/` — JSON Schemas: the field-by-field contract + guidance for each doc. Consult before writing/updating a JSON file.
- `docs/pm/dashboard/` — the read-only viewer: `serve.py` (stdlib, no installs) serves the docs and live-reloads on change; `index.html` is the dashboard. Run `python3 docs/pm/dashboard/serve.py`.
{{OPTIONAL_LAYOUT_LINES}}
## Keeping the record current (do this without being asked)

`docs/pm/status.json` is the project's live state and the first thing to read each session. It's only useful if it's true, so maintaining it is part of finishing the work — not a separate request. The dashboard renders it live, so updates show up the moment you save. **After completing any meaningful unit of work — a task, a milestone step, a decision, a notable dead-end — update the record before treating the job as done:**

- **`docs/pm/status.json`** — add the finished item to `shipped` (with `date` and `commit`); **reset `now`** — a shipped item *leaves* `now`, it doesn't accumulate; update `next`; add or clear `blocked`; flip a milestone's `done` to `true` if one completed; bump `lastUpdated`. Match `schema/status.schema.json`. **Keep it lean — it's read every session:** `now`/`next` ≤3 items, ≤2 lines each; each entry is one claim + one pointer (link a commit/PR/ADR — never paste deploy run IDs or file-by-file lists). **`shipped` keeps only the newest ~3** (just enough to orient); when it grows past that, older entries simply drop off — `git log` (and the commit links you kept) is the full history, so there's no archive to maintain. Whole-file target ≤ ~150 lines.
- **`CLAUDE.md` → Status** — usually nothing to do: the Status section only points at `status.json`, it doesn't track progress. Touch it only if the project's identity (the one-liner) changes.
- **A decision record** (`docs/pm/decisions/NNNN-*.json`) — only when direction changed: a choice a future session shouldn't silently reverse. Routine progress needs no ADR. When one supersedes an earlier ADR, set `supersedes` on the new record and set `supersededBy` (and `status: "Superseded"`) on the old one. After adding or changing a record, regenerate `docs/pm/decisions/README.md`.

Keep entries specific and falsifiable — cite dates, link commits/ADRs. A stale status is worse than none: if unsure whether something shipped, say so in the file rather than guessing. `status.json` is a snapshot, not a journal — git history is the fine-grained log.

<!-- project-kit:end -->
