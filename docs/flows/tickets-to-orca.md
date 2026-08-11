# Ticket flow: GitHub Issues → parallel Orca worktrees

A second delivery path alongside `spec → taskplan → implement`. It borrows the discovery half of
[`mattpocock/skills`](https://github.com/mattpocock/skills) — `/grill-with-docs`, `/wayfinder`,
`/to-spec`, `/to-tickets` — and plugs `/frontier` into it as the execution layer.

Nothing upstream is forked. Matt's skills publish to whatever
`docs/agents/issue-tracker.md` names; `/frontier` reads the same GitHub Issues they wrote.

## The flow

```
/grill-with-docs ──▶ [/wayfinder if foggy] ──▶ /to-spec ──▶ /to-tickets
  CONTEXT.md, ADRs      map + decision issues     1 issue     N issues + blocked_by
                                                                     │
                                             ┌───────────────────────┘
                                             ▼
                                    /frontier <parent>
                    scoped to one parent ─ claim by assignee ─ dispatch
                                             │
             ┌───────────────────────────────┼──────────────────────────┐
             ▼                               ▼                          ▼
  worktree --issue 42             worktree --issue 43          #44 blocked, skipped
  claude builds #42 serially      claude builds #43 serially
  → /cleanup → PR "Closes #42"    → /cleanup → PR "Closes #43"
             │                               │
             └──────── merge closes issue ───┴──▶ re-run /frontier → next wave
```

**Keep steps 1–3 in one unbroken context window** — don't `/clear` or `/compact` until after
`/to-tickets`, so the grilling, the spec, and the tickets all build on the same thinking. Each
worker then starts fresh from its ticket, which is the point of slicing them that way.

## Which path to take

| Work shape | Route | Why |
|---|---|---|
| **Deep + coupled** — one feature through schema, API, UI, tests | `/to-spec` → `/to-tickets` → `/frontier` | Parallelism is *across* tickets. Each slice is one context window of serial work. |
| **Broad + shallow** — the same change across many files (12 endpoints, 30 components) | `/taskplan` → `/implement` | Parallelism is *within* one run. Enough disjoint tasks to clear the orchestration tax. |

The two aren't stylistic alternatives — they're separated by a measured threshold.
`/implement` logs a **4.5× median orchestrator-token tax below 6 agents** (worst observed: 20× on a
2-agent run), falling to 0.6–0.7× at 17+. Break-even is 6–7 agents.

A `/to-tickets` slice can't reach that. It's defined as *"sized to fit in a single fresh context
window"*, and decomposing it yields a dependency chain — UI needs the API needs the schema — which
`/taskplan` step 6 collapses to one task and `/implement`'s `W == 1` gate then refuses. **That
refusal is the system working.** Don't relax the gate to force a slice through the wave machinery;
run it serially in its own worktree, which is what `/frontier` does.

## Why worktrees instead of file boundaries

`/implement` keeps parallel agents safe by giving each a disjoint set of files, and treats router
tables, DI containers, barrel `index.*`, migrations and shared types as hotspots that must never
appear in two boundaries at once.

A vertical slice violates that by construction — it *is* a change to the router plus the schema plus
the UI. So `/frontier` doesn't try: each ticket gets its own checkout, and two tickets touching the
same file is fine because they're on different branches. Conflicts surface at merge, where git is
the right tool and a human is already looking.

That's why `/frontier` briefs carry **no file-ownership section**. Handing a vertical slice an
artificial file list just makes the worker stop and ask.

## Coordination lives in GitHub, not in a task DAG

`/to-tickets` emits blocking edges as **native GitHub issue dependencies**. Combined with the
assignee field and open/closed state, that's a complete coordination substrate:

| Concept | Mechanism |
|---|---|
| Dependency graph | `issue_dependencies_summary.blocked_by` (counts **open** blockers only) |
| Frontier | open + `ready-for-agent` + `blocked_by == 0` + unassigned |
| Claim / lock | `gh issue edit <n> --add-assignee @me`, **before** any work |
| Done | PR merges with `Closes #<n>` → issue closes → unblocks its dependents |

So `/frontier` is a **full handoff**, not supervised orchestration: no
`orca orchestration task-create` / `dispatch --inject` / `check --wait`. Advancing the frontier is
re-running `/frontier`; the next query already reflects what merged. State survives this session
dying, which a coordinator's in-memory DAG does not.

`/implement-orca` remains the supervised path — use it when you want visible panes reporting
`worker_done` back to a coordinator that's holding the whole run in context.

## One-time setup, per repo

This is where the flow silently breaks if skipped.

**1. Install the upstream skills** (not `implement`, `tdd`, or `code-review` — this plugin has
those):

```
skills/engineering/{to-spec,to-tickets,wayfinder,ask-matt,setup-matt-pocock-skills}
skills/engineering/triage          # only if you take external issues
```

**2. Run `/setup-matt-pocock-skills`** in the repo. It writes `docs/agents/issue-tracker.md` and
`docs/agents/domain.md`, and adds an `## Agent skills` block to `CLAUDE.md`.

> It edits `CLAUDE.md` **if it exists**, else `AGENTS.md` — it checks which file is present, not
> which harness is running. `/project-kit` also writes a marked block to `CLAUDE.md`; the two target
> different sections and coexist, but check after the first run.

**3. Create the labels by hand.** `/setup-matt-pocock-skills` writes only a *mapping* table — it
never runs `gh label create` — and `gh issue create --label <missing>` **fails outright** rather than
creating the label:

```bash
gh label create needs-triage      --color d93f0b --description "Maintainer needs to evaluate"
gh label create needs-info        --color fbca04 --description "Waiting on reporter"
gh label create ready-for-agent   --color 0e8a16 --description "Fully specified, ready for an agent"
gh label create ready-for-human   --color 1d76db --description "Requires human implementation"
gh label create wontfix           --color ffffff --description "Will not be actioned"
# only if you use /wayfinder:
gh label create wayfinder:map       --color 5319e7
gh label create wayfinder:research  --color 5319e7
gh label create wayfinder:prototype --color 5319e7
gh label create wayfinder:grilling  --color 5319e7
gh label create wayfinder:task      --color 5319e7
```

**4. Enable GitHub issue dependencies** on the repo. Without them `/to-tickets` falls back to a
`Blocked by: #n` line in the body and `/frontier` has to parse it — workable, but the frontier stops
rendering in GitHub's own UI.

**5. Register the repo with Orca** so `--repo id:<repoId>` resolves:

```bash
orca repo add --path /abs/repo --json
```

## Known sharp edges

- **Nothing closes a ticket except a merged PR.** Matt's `/to-tickets` explicitly won't modify the
  parent issue, and his `/implement` never closes anything. `/cleanup`'s `Closes #<n>` is the only
  closure path — which is why it resolves the issue number from the worktree's `--issue` link and
  **asks** rather than guessing. A ticket left open after its work merged stalls everything
  downstream of it.
- **`/triage` is for issues you didn't create.** Tickets from `/to-tickets` are already
  `ready-for-agent` by construction; running triage over them is wasted work. Install it when other
  people file issues in the repo — without it, incoming reports never reach the agent-ready label and
  `/frontier` will never see them. On a solo repo where every ticket comes from your own
  `/to-spec` → `/to-tickets`, skip it.
- **A triaged ticket's contract is a comment, not its body.** When triage moves an issue to
  agent-ready it posts an **agent brief**; the body stays a raw user report. `/frontier` fetches
  `gh issue view <n> --comments` and sends the brief, because sending the body would hand the worker
  the symptom instead of the work.
- **`/frontier` resolves the agent-ready label from `docs/agents/triage-labels.md`**, falling back to
  the literal `ready-for-agent` when that file is absent. If you remap the triage vocabulary, the
  frontier follows — but note setup only writes that file when `triage` is installed.
- **`/frontier` is scoped to a parent issue, never the repo.** `/to-spec` labels the *spec*
  `ready-for-agent` and `/to-tickets` labels every *ticket* the same, so the label alone can't tell a
  whole feature from one slice. Scoping plus a hard "no acceptance criteria → not a ticket" guard is
  what stops a spec being dispatched as if it were a ticket.
- **`--max-workers N` is a ceiling on concurrent workers, not on one run's dispatch.** It subtracts
  what's already in flight, so repeated runs can't accumulate past `N`. When the frontier exceeds the
  ceiling, tickets are ranked by `blocking` count descending — finishing the ticket that gates three
  others widens the frontier; finishing a leaf doesn't. Deferred tickets are always named, never
  dropped. An assigned ticket whose Orca worktree is gone holds a slot forever and is reported as
  "possibly stale" — `/frontier` never unassigns it, since a dead worker and a live one on another
  machine are indistinguishable from here.
- **Per-ticket model tiers need the four-step dispatch.** `orca worktree create` has no `--model`;
  only `orchestration worker-start` does, and that drags in coordinator lifecycle plus loses
  `--issue`. So `/frontier` pins a tier with `terminal create --command 'claude --model <tier>'`
  instead, staying a handoff.
- **A cleared `/wayfinder` map hands off to `/to-spec`, not straight to `/frontier`.** Skipping the
  collapse throws away the linked decision detail the map spent its whole run accumulating.
