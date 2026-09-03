# WORKER.md — the worker overlay for `/implement-orc`

Read by `/implement-orc` only, when composing worker briefs. A worker is a `code-implementer`
subagent or an Orca terminal session that implements under an orchestrator. It follows
[`implement-core`](../implement-core/SKILL.md) for *how to build*; this file adds what only a worker
needs: how its brief is laid out, its file boundary, its git duties, how it stops, and how it
reports. A brief is self-contained — workers share no memory with the orchestrator or each other.

## W-0. Brief layout — how the orchestrator assembles a brief

A brief is **two blocks, shared part first**. Never interleaved, never reordered.

```
──── [A] CAMPAIGN HEADER — byte-identical in every brief of this campaign ────
  1. the implement-core doctrine, then this WORKER.md
  2. the campaign orientation digest:
       - CONTEXT.md / CONTEXT-MAP.md glossary excerpt
       - the ADR index for the area this campaign touches
       - repo conventions worth stating once
       - the exact build / test / typecheck commands
       - `## Parent constraints` — the parent spec's Implementation Decisions and
         Testing Decisions sections, verbatim
  3. the IMPLEMENTER REPORT format (W-4)
──── [B] TICKET BLOCK — differs per worker ────
  - the contract verbatim (implement-core §1) and its ticket number
      (chain mode: every ticket's contract, in walk order)
  - `## File ownership` (`files_owned`) — only when fanned out (W-1)
  - `## Landed so far` — fan-out mode, second wave on: the `summary` and
    `files_changed` lines of every previous IMPLEMENTER REPORT
  - the ticket's `method` (implement-core §3)
```

`## Parent constraints` is in `[A]` because it is the same for every worker and because a rule that
lives only in the parent is a rule no worker follows — seven test files a spec had forbidden came out
of one campaign whose workers each saw only their own ticket. `## Landed so far` is in `[B]` because
it grows per wave; it exists so a fresh worker does not spend its first hundred reads re-deriving a
convention a sibling established minutes earlier.

**`[A]` is frozen for the campaign's lifetime, and carries no per-ticket value.** An issue number, a
file list, or a tier name that leaks into `[A]` makes it unique per worker, and the shared prefix
becomes unreachable for everyone. If `[A]` genuinely must change mid-campaign (a new ADR lands),
that is a *new* header from that point on and one accepted cold miss — say so rather than editing it
silently.

**Why the order is load-bearing:** prompt caching is a byte prefix match from position zero.
Identical text placed first is read by every worker at a fraction of its price; the same text placed
after the ticket contract is unreachable, because each brief has already diverged. The digest also
exists so N workers don't each re-derive the same test command and the same glossary — the
orchestrator resolves it once and pastes it unchanged.

## W-1. The file boundary

**Fan-out worker — the brief carries `## File ownership`:** it is a **hard boundary**. Create or
modify only those paths; test files live inside it. Needing anything outside it means the partition
was wrong — **STOP and report the cross-boundary need** (subagent: as a `blockers` entry; Orca
worker: via `ask`). Do not edit it, even for a one-line fix.

**Chain worker — no ownership section:** the branch is the boundary; nothing runs beside you.
implement-core §4 (stay on the ticket) is the whole rule.

## W-2. Git duties

- **Fan-out worker:** **do not commit, push, branch, or open PRs — you only change the working
  tree.** The orchestrator verifies and lands your work as a commit.
- **Chain worker:** the brief transfers landing duty. Commit each ticket as you finish it —
  `<type>: <ticket title> (#<n>)` with a `Ticket: #<n>` trailer — then move to the next. The trailer
  is the orchestrator's resume marker, so never commit a ticket whose criteria aren't all ticked.
  **Still no push, no branch, no PR.**

## W-3. Stopping

implement-core §2 and §5 say to stop on an ADR conflict or a real design fork. For a worker,
"stop and surface it" means: **report it as a `blockers` entry in the IMPLEMENTER REPORT (subagent)
or via `ask` (Orca) and end your turn.** Do not guess and do not continue into work that depends on
the answer — a re-dispatch with a ruling beats a reworked wrong guess. Cross-boundary needs (W-1)
stop the same way.

## W-4. Output — the IMPLEMENTER REPORT

End with EXACTLY this block. An Orca worker puts it in the body of its `worker_done` message and
lists changed paths in the payload's `filesModified`. A chain worker emits one covering the whole
walk, with `files_changed` grouped by ticket.

```
===== IMPLEMENTER REPORT =====
task: <one-line restatement>
files_changed:
  - <path> — <what changed>
summary: <2-4 lines>
build: pass | fail | skipped(<reason>)
tests: pass | fail | skipped(<reason>)
typecheck: pass | fail | skipped(<reason>)
verdict: pass | needs-attention | fail
deviations: <or none>
blockers: <cross-boundary needs / ambiguities, or none>
follow_ups: <or none>
===== END IMPLEMENTER REPORT =====
```

`verdict: pass` means: every acceptance criterion checked, build/tests/typecheck green in this
ticket's scope, no unreported deviations. Anything less is `needs-attention` (say why) or `fail`.
