# workflow

Claude Code plugin: a spec-driven delivery pipeline.

```
/spec  →  /taskplan  →  /implement  →  /cleanup
(PRD)     (partitioned   (parallel      (PR, CI poll,
           plan JSON)     orchestrated   merge, teardown)
                          build)
```

Plus `/project-kit` — scaffolds `docs/pm/` project management (status, decisions, schemas, dashboard) into any repo.

## Skills

| Skill | Stage | What it does |
|---|---|---|
| `/spec` | define | Interview-driven PRD at `docs/spec/<slug>.md` — objective, structure, testing, boundaries. |
| `/taskplan` | plan | Decompose a spec into atomic tasks with file ownership, model tier, and method; derive parallel waves into `docs/plan/<slug>.json`. |
| `/implement` | build | Orchestrate the plan: file-disjoint waves of parallel `code-implementer` subagents, integrate, verify, review. Logs every run (`orchlog.py`). |
| `/implement-orca` | build | Same orchestration doctrine, but workers are Orca-dispatched `claude` CLI terminals (via the official `orchestration` skill): visible panes + runtime task/dispatch provenance. |
| `/cleanup` | ship | Open the PR, poll CI to conclusive (`pollci.py`), auto-merge on green, tear down the worktree + branches. |
| `/project-kit` | setup | Scaffold `docs/pm/` (status.json, decisions, schemas, dashboard) and the CLAUDE.md block. |

## Install

```
/plugin marketplace add psycoder-sup/workflow
/plugin install workflow@workflow
```
