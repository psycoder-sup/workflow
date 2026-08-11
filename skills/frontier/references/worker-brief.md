# Worker brief template

The `--prompt` handed to each ticket's `claude` worker at `ORCA worktree create`.

A worker starts with **no memory of this session** — it has the repo, the issue number, and this
prompt. Front-load everything. Interpolate the ticket's real values; don't send the placeholders.

Keep it to what the worker can't derive. The ticket body is the contract, so paste it verbatim
rather than summarising it — a paraphrase silently drops acceptance criteria.

---

```text
You own GitHub issue #<n> in this repo, start to finish. You are in a dedicated Orca worktree
created for exactly this ticket; nobody else is working in it.

## The ticket

#<n> — <title>

<the issue body verbatim: What to build / Acceptance criteria / Blocked by>

## Before you write anything

Read `docs/agents/domain.md` and follow it. In short: read `CONTEXT.md` (or `CONTEXT-MAP.md` and the
contexts it points at) and any ADRs under `docs/adr/` that touch this area. Name things using the
glossary's vocabulary — if a concept you need isn't in it, that's a signal: either you're inventing
language the project doesn't use, or there's a real gap worth noting. If your approach contradicts an
ADR, say so explicitly rather than quietly overriding it.

If those files don't exist, proceed silently — they're created lazily, and their absence is normal.

## How to build it

This ticket is ONE vertical slice — a narrow but complete path through every layer it touches.

Build it SERIALLY, yourself. Do NOT call /implement or /implement-orca: a single slice decomposes
into a dependency chain, which collapses to width 1, which their gate refuses to orchestrate. The
parallelism in this flow is across tickets, and it already happened — you are one of those workers.

Use /tdd at the seams the spec named — failing test first, then the minimal code to pass, then
refactor. Run typechecking and the relevant test files as you go, and the full suite once at the end.

Stay inside this ticket. If you find work that belongs to another ticket, note it in your report and
leave it alone — don't fix it here.

## Keep the card current

Update the Orca worktree at real checkpoints, so progress is visible without opening the terminal:

  ORCA worktree set --worktree active --comment "<short status>" --json
  ORCA worktree set --worktree active --workspace-status in-progress --json   # then in-review

Meaningful checkpoints only — approach settled, slice green, tests passing, blocked. Not every edit.
(`ORCA` = the executable resolved per the orca-cli rules; inside an Orca terminal it's `orca`.)

## When it's green

Run /cleanup. It opens the PR with `Closes #<n>` — sourced from this worktree's linked issue — polls
CI, and merges when green.

Do NOT close issue #<n> by hand, and do NOT unassign yourself. The merge closes it, which is what
lets the next /frontier run see the tickets this one was blocking.

## If you get stuck

Stop and report rather than guessing. Set the card comment to what blocked you, and leave the issue
assigned so it isn't silently re-dispatched. A blocked ticket that says why is worth more than a
half-built one.

Specifically stop and report if:
- The acceptance criteria leave a real design fork open. A re-dispatch with a ruling beats a
  reworked wrong guess.
- The work turns out to need a change another open ticket owns.
- Your approach contradicts an ADR and you think the ADR should be reopened.
```

---

## Notes for the dispatcher

- **Paste the issue body verbatim.** Every summarisation drops an acceptance criterion.
- **Substitute `ORCA`** with the executable you resolved in step 1 before sending — the worker
  shouldn't have to re-derive it, and on Linux a wrong guess reaches the GNOME screen reader.
- **No file-ownership section.** That's the wave path's safety boundary. Here the worktree *is* the
  boundary, and a ticket legitimately touches every layer — an artificial file list would just make
  the worker stop and ask.
- **No model tier.** One ticket is a whole vertical slice with real design judgment in it; the
  worker runs at session default rather than being routed down a tier.
- If the repo has no `docs/agents/domain.md` (`/setup-matt-pocock-skills` never ran), drop that
  paragraph rather than pointing the worker at a file that isn't there.
