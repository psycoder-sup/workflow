# workflow

Claude Code plugin: one GitHub-issue-native delivery pipeline.

```
/project-kit          (once per repo: labels, tracker conventions, CONTEXT.md + docs/adr/, CLAUDE.md block)
     │
/spec                 grilling + domain-modeling → parent issue (label `spec`); the issue body IS the spec;
     │                too wide for one PR → split into sibling parents with blocked-by edges
/taskplan <parent>    vertical-slice sub-issues: native --parent + --blocked-by, ready-for-agent by
     │                construction, taskplan metadata block (files_owned / model / method); quiz-gated
/implement <parent>   1 parent = 1 worktree = 1 branch = 1 PR; walks the live graph — parallel waves when
     │                file-disjoint, serial when a chain; one fresh worker per ticket (subagents, or
     │                --orca for Orca terminals); lands `Ticket: #<n>` commits; workers follow implement-core
/cleanup              PR (adopts /implement's) → poll CI → merge on green → close the parent → teardown
```

Inbound raw bugs/ideas enter through **`/triage`** (verify → categorise → grill if murky → agent
brief → `ready-for-agent`), then `/implement <n>` picks them up as standalone builds.

GitHub is the only state store: specs are parent issues, tickets are native sub-issues, dependencies
are native blocked-by edges, progress is the parent's sub-issue summary. The durable outputs of
thinking live in git: `CONTEXT.md` (glossary) + `docs/adr/` (minimal ADRs), maintained by
`domain-modeling` during grilling sessions. Requires `gh` ≥ 2.94.

Label vocabulary and issue/ADR conventions follow
[mattpocock/skills](https://github.com/mattpocock/skills); `/triage`, `grilling`, and
`domain-modeling` are ports of the same.

## Skills

| Skill | Stage | What it does |
|---|---|---|
| `/project-kit` | setup | Create the 8 labels on GitHub, write `docs/agents/{issue-tracker,triage-labels}.md`, seed `CONTEXT.md`, wire the CLAUDE.md block. Migrates the old `docs/pm/` JSON layout (decisions → ADRs) on approval. |
| `/spec` | define | Frontier-round grilling (with `domain-modeling` writing glossary/ADRs as decisions land) → Pocock-template spec → split check → fresh-eyes review → published parent issue. |
| `/taskplan` | plan | Decompose a parent into dependency-linked sub-issues sized for parallel waves; user approves the breakdown before anything is published. The issue graph IS the plan. |
| `/implement` | build | Orchestrate the graph: claim all children, walk in dependency order, fan out file-disjoint unblocked tickets, verify + land each as a `Ticket: #<n>` commit, one PR closing every child. `--orca` swaps subagent workers for Orca terminal sessions. Logs every run (`orchlog.py`). |
| `implement-core` | doctrine | The per-ticket worker contract all `/implement` briefs are built from (brief layout, contract selection, CONTEXT/ADR discipline, method, self-verify, IMPLEMENTER REPORT). §0 fixes the two-block brief layout — a frozen campaign header shared byte-identically across every worker, then the ticket block. Never invoked directly. |
| `/triage` | inbound | State machine for raw issues/PRs: verify the claim, grill if needed, write agent briefs, maintain `.out-of-scope/`. |
| `/cleanup` | ship | Adopt/open the PR, poll CI to conclusive (`pollci.py`), auto-merge on green, close the parent when `completed == total`, tear down the worktree. |
| `grilling` | engine | Relentless design-tree interview in frontier rounds. Used by `/spec` and `/triage`; also directly for ad-hoc stress-testing. |
| `domain-modeling` | engine | Glossary (`CONTEXT.md`) + minimal ADRs (`docs/adr/`), maintained inline as decisions crystallize. |

## Versioning

Two independent version numbers, on purpose:

- **`.claude-plugin/plugin.json` `version`** — the plugin's semver (what `/plugin` installs and updates).
- **`WORKFLOW_VERSION` in `skills/implement/orchlog.py`** — the run-log schema version, stamped into
  every `orchlog` record. It bumps when the orchestration doctrine or log semantics change, so runs
  stay comparable across plugin releases (only compare metrics within the same schema version).

## Install

```
/plugin marketplace add psycoder-sup/workflow
/plugin install workflow@workflow
```
