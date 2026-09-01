---
name: stats
description: >
  Per-stage token accounting across the pipeline: what one parent issue cost to take from /spec
  through /taskplan, /implement and /cleanup, and which stage ate the budget. Each stage records one
  cost row at its end (keyed by parent issue); /cleanup rolls them up by default and prints the
  breakdown. Reports the four billed buckets (output / input / cache_write / cache_read), the cache
  hit rate, and an estimated dollar figure. Use directly to revisit a shipped issue's cost, or to
  compare stage costs across issues.
trigger: /stats
user-invocable: true
argument-hint: "[issue number] | --recent N   (no args = aggregate across all recorded issues)"
allowed-tools: ["Bash", "Read"]
# Reading a log and printing a table — no judgment calls, no code written.
model: sonnet
---

# /stats

Answers two questions the pipeline could not answer before:

- **What did this feature cost, end to end?** — `/spec`'s grilling rounds and `/taskplan`'s
  decomposition were entirely unmeasured; only `/implement` logged anything.
- **Which stage ate it?** — so the next round of tuning aims at the expensive stage instead of the
  visible one.

## Usage

```bash
# roll up one parent issue (what /cleanup runs by default)
python3 ${CLAUDE_PLUGIN_ROOT}/skills/stats/stats.py report --issue <parent>

# across every recorded issue: median cost per stage, which issues are incomplete
python3 ${CLAUDE_PLUGIN_ROOT}/skills/stats/stats.py report [--recent N]

# raw rows, for your own analysis
python3 ${CLAUDE_PLUGIN_ROOT}/skills/stats/stats.py report --json
```

A stage records itself at its own end — you never call `record` by hand unless a stage's hook was
skipped and its session is *still open*:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/stats/stats.py record --issue <parent> --stage <spec|taskplan|implement|cleanup>
```

Log: `~/.claude/orchestrate/stats.jsonl` (sibling of `runs.jsonl`), overridable with
`$WORKFLOW_STATS_LOG`. One JSONL row per (issue, stage, session).

## The one rule that makes the data trustworthy

**A stage records once, at its end, before the session is cleared — and a stage that forgets is
unrecoverable.**

Transcripts carry an `attributionSkill` field, but it tags only the burst of messages right after a
Skill invocation and then stops (measured: 5 of 119 assistant messages in a real session). So "which
stage spent this" cannot be reconstructed afterwards — inferring it would undercount by ~95%. There
is no backfill, and any offered backfill would be fabricated.

`report` therefore prints **`MISSING: <stages>`** for an issue whose pipeline is incomplete, and
labels the total a **floor** rather than a cost. A quiet low number would be worse than no number.

## What the report shows

Per stage: `total`, its share of the pipeline, `output`, `cache_read`, the **cache hit rate**
(cache_read as a share of billed input), and an estimated cost. Expect `total` to be dominated by
`cache_read` — that is normal for agent loops, where the same prefix is re-read every turn, and it
is why a single `total` number tells you nothing on its own. A hit rate that *drops* between
comparable issues is the signal worth chasing: it means a prefix that used to be shared no longer is
(see [`implement-core` §0](../implement-core/SKILL.md) on the frozen campaign header).

## Dollar figures are estimates — say so when you quote them

The per-message model is **not** recorded in transcripts, so `stats.py` prices each agent type at an
assumed tier (`RATES` and `TYPE_TIER` at the top of the script): orchestrator and review on opus,
workers and everything else on sonnet. A run that routed differently will be off, and the rate table
itself drifts — it is dated in the source, and nothing in the script can detect that it has gone
stale. Treat the numbers as a ratio between stages first and an absolute cost second.

Records written before workflow 3.2.0 have no cache split; those price as `n/a` rather than
guessing from `total`, which would be wrong by roughly 10×.

## Rules

- **Report, never estimate a missing stage.** Name it as missing and call the total a floor.
- **Never edit `stats.jsonl` to "fix" a gap.** The gap is the finding.
- **Re-recording a stage replaces its row**, so a repeated hook is harmless. (This is the failure
  `runs.jsonl` has: a campaign logged three progressive snapshots and its tokens entered every
  aggregate three times.)
- **Quote the dollar figure as an estimate**, with the tier assumption, or quote tokens instead.

## Red flags

- A pipeline total that looks too cheap → check for `MISSING` stages before drawing any conclusion.
- Two issues with similar shape but very different cache hit rates → a shared prefix broke; that is
  a real regression, not noise.
- `est $` reads `n/a` across the board → the rows predate the 3.2.0 cache split; only newer runs can
  be priced.
- You are about to compare a stage against a stage of a different issue with a different repo size →
  the number is not comparable; compare shares, not absolutes.
