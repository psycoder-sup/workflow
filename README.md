# workflow

Claude Code plugin: a spec-driven delivery pipeline.

```
/spec  →  /taskplan  →  /implement  →  /cleanup
(PRD)     (partitioned   (parallel      (PR, CI poll,
           plan JSON)     orchestrated   merge, teardown)
                          build)
```

Plus a second delivery path for deep, coupled work — GitHub tickets executed off their dependency
graph, wide graphs fanned out, linear graphs walked:

```
(mattpocock/skills)                    (this plugin)
/to-spec  →  /to-tickets       →       /frontier  →  /cleanup     (wide graph: N worktrees,
(1 issue)    (N issues +               or                          1 agent + 1 PR per ticket)
              blocked_by edges)        /caravan   →  /cleanup     (linear graph: 1 branch,
                                                                   1 agent per ticket, 1 PR)
```

See [docs/flows/tickets-to-orca.md](docs/flows/tickets-to-orca.md) for when to take which path.

Plus `/project-kit` — scaffolds `docs/pm/` project management (status, decisions, schemas, dashboard) into any repo.

## Skills

| Skill | Stage | What it does |
|---|---|---|
| `/spec` | define | Interview-driven PRD at `docs/spec/<slug>.md` — objective, structure, testing, boundaries — finished by a delegated fresh-eyes review (opus) that revises the doc in place. |
| `/taskplan` | plan | Decompose a spec into atomic tasks with file ownership, model tier, and method; derive parallel waves into `docs/plan/<slug>.json`. |
| `/implement` | build | Orchestrate the plan: file-disjoint waves of parallel `code-implementer` subagents, integrate, verify, review. Logs every run (`orchlog.py`). |
| `/implement-orca` | build | Same orchestration doctrine, but workers are Orca-dispatched `claude` CLI terminals (via the official `orchestration` skill): visible panes + runtime task/dispatch provenance. |
| `/frontier` | build | Ticket-level parallelism: query GitHub for takeable tickets (open, `ready-for-agent`, unblocked, unassigned), claim by assignee, dispatch one Orca worktree + `claude` worker per ticket. Full handoff — no coordinator. |
| `/caravan` | build | Ticket-level serial walk: work a parent's mostly-linear ticket graph on one integration branch, one fresh `code-implementer` per ticket, each verified slice landed as a `Ticket: #<n>` commit — then one PR closing every child. |
| `/caravan-orca` | build | Same campaign doctrine, but each ticket's worker is a `claude` CLI session in its own Orca terminal via supervised `orchestration` (task-create → dispatch --inject → worker_done): visible panes + task/dispatch provenance, one fresh terminal per ticket. |
| `/cleanup` | ship | Open the PR, poll CI to conclusive (`pollci.py`), auto-merge on green, tear down the worktree + branches. |
| `/project-kit` | setup | Scaffold `docs/pm/` (status.json, decisions, schemas, dashboard) and the CLAUDE.md block. |

## Versioning

Two independent version numbers, on purpose:

- **`.claude-plugin/plugin.json` `version`** — the plugin's semver (what `/plugin` installs and updates).
- **`WORKFLOW_VERSION` in `skills/implement/orchlog.py`** — the run-log schema version, stamped into every `orchlog` record. It bumps only when the orchestration doctrine or log semantics change, so runs stay comparable across plugin releases (only compare metrics within the same schema version).

## Install

```
/plugin marketplace add psycoder-sup/workflow
/plugin install workflow@workflow
```
