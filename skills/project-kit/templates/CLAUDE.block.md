<!-- project-kit:begin -->
## Agent skills

### Issue tracker

Specs and tickets live as GitHub issues — a spec is a parent issue (label `spec`), its tickets are
native sub-issues with native blocked-by edges. See `docs/agents/issue-tracker.md`.

### Triage labels

{{TRIAGE_SUMMARY}}. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: the glossary lives in `CONTEXT.md` at the repo root; architecture decision records
live in `docs/adr/NNNN-<slug>.md` (created lazily). Before working in an area, read `CONTEXT.md` and
the ADRs that touch it; use the glossary's vocabulary; surface (never silently override) any
contradiction with an ADR. If these files don't exist, proceed silently.

### Pipeline

`/spec` (grilled PRD → parent issue) → `/taskplan` (sub-issues + dependencies) →
`/implement <parent>` (one worktree, one branch, one PR, built in this session; `/implement-orc` for orchestrator + workers, only on request) →
`/cleanup` (PR → CI → merge → close parent). Inbound raw bugs/ideas go through `/triage` first.
<!-- project-kit:end -->
