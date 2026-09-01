#!/usr/bin/env python3
"""stats — per-stage token accounting across the pipeline (spec -> taskplan -> implement -> cleanup).

Subcommands:
  record   write one cost row for the stage that just finished, keyed by parent issue
  report   roll a parent issue's stages up into a breakdown, or aggregate across issues

Log file: $WORKFLOW_STATS_LOG, default ~/.claude/orchestrate/stats.jsonl (sibling of runs.jsonl).

WHY EACH STAGE MUST RECORD ITSELF
Transcripts carry an `attributionSkill` field, but it tags only the burst of messages right after a
Skill invocation and then stops — measured at 5 of 119 assistant messages in a real session. Deriving
"which stage spent this" from transcripts after the fact would undercount a stage by ~95%. And
/cleanup is advised to run in a fresh session, so it cannot see the earlier stages either. So every
stage records its own window at its end; /cleanup only rolls the rows up.

A stage that forgets to record is unrecoverable. `report` therefore names the stages it is MISSING
for an issue rather than quietly reporting a low total.

All transcript scanning is reused from orchlog.py — session detection, worktree project dirs, the
.meta.json agent-type fix, and the 3.2.0 four-bucket cache split all live there and are not
duplicated here.
"""
import argparse
import importlib.util
import json
import os
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

STATS_VERSION = "1.0.0"
STAGES = ("spec", "taskplan", "implement", "cleanup")


def _load_orchlog():
    """Import orchlog.py from the sibling /implement skill by path.

    The two scripts ship in one plugin and are versioned together, so a path import is safe and
    keeps the transcript-scanning logic single-sourced. A copy would drift.
    """
    p = Path(__file__).resolve().parent.parent / "implement" / "orchlog.py"
    if not p.exists():
        raise SystemExit(f"stats: cannot find orchlog.py at {p} — is the plugin installed intact?")
    spec = importlib.util.spec_from_file_location("orchlog", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


O = _load_orchlog()

# ---- pricing ---------------------------------------------------------------
# Rates as of 2026-09-01, USD per 1M tokens. VERIFY against current pricing before trusting a
# dollar figure — these drift, and nothing in this script can detect that they have.
# Cache reads bill ~0.1x base input; cache writes 1.25x (5-minute TTL, what agent loops use).
RATES = {                  # model -> (input, output)
    "opus":   (5.00, 25.00),
    "sonnet": (2.00, 10.00),
    "haiku":  (1.00,  5.00),
}
CACHE_READ_MULT = 0.10
CACHE_WRITE_MULT = 1.25

# Which tier an agent type is assumed to run on. The per-message model is NOT recorded in
# transcripts, so this is an assumption, not a measurement — hence every $ figure is an estimate.
# Orchestrators and reviewers run on the expensive tier; workers are routed per ticket but sonnet
# is the documented workhorse default.
TYPE_TIER = defaultdict(lambda: "sonnet", {
    "orchestrator": "opus",
    "review": "opus",
    "Plan": "opus",
})


def estimate_cost(by_type):
    """Approximate USD for a {type: {output,input,cache_read,cache_creation}} block.

    Returns None when the record predates the cache split (only output/total stored) — a number
    computed from `total` alone would be wrong by ~10x, so refuse rather than mislead.
    """
    total = 0.0
    for t, v in (by_type or {}).items():
        if v.get("cache_read") is None:
            return None
        cin, cout = RATES[TYPE_TIER[t]]
        total += (v.get("input", 0) * cin
                  + v.get("cache_creation", 0) * cin * CACHE_WRITE_MULT
                  + v.get("cache_read", 0) * cin * CACHE_READ_MULT
                  + v.get("output", 0) * cout) / 1_000_000
    return total


def usd(x):
    return "    n/a" if x is None else f"${x:>7,.2f}"


# ---- log -------------------------------------------------------------------
def log_path():
    p = os.environ.get("WORKFLOW_STATS_LOG")
    if p:
        return Path(p).expanduser()
    return O.log_path().parent / "stats.jsonl"


def load(path=None):
    path = path or log_path()
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def session_start(session):
    """Earliest timestamp in a session's transcripts, as the default window start."""
    mains, subs = O.find_transcript_files(session)
    best = None
    for f in list(mains) + list(subs):
        for line in O._read_lines(f):
            line = line.strip()
            if not line:
                continue
            try:
                t = O.parse_ts(json.loads(line).get("timestamp"))
            except json.JSONDecodeError:
                continue
            if t:
                if best is None or t < best:
                    best = t
                break  # first TIMESTAMPED line per file is enough; many lines carry none
    return best.isoformat(timespec="seconds") if best else None


def default_since(session, rows, key=None):
    """Window start = where this session's last recorded stage ended, else session start.

    This is what stops two stages run back-to-back in one session from double-counting each other.
    `key` is the (issue, stage, session) being written; its own prior row is excluded so that
    re-recording a stage recomputes the window it had, rather than chaining off itself into an
    empty one.
    """
    prior = [r for r in rows
             if r.get("session") == session and r.get("until")
             and (key is None or (r.get("issue"), r.get("stage"), r.get("session")) != key)]
    if prior:
        # Advance one second: orchlog's window bounds are inclusive at BOTH ends, so starting
        # exactly at the previous stage's `until` would bill any message on that second to two
        # stages. The earlier stage owns its final second; the next starts after it. Stages are
        # then provably disjoint, and their totals sum to the session total.
        last = O.parse_ts(max(r["until"] for r in prior))
        return (last + timedelta(seconds=1)).isoformat(timespec="seconds")
    return session_start(session)


# ---- record ----------------------------------------------------------------
def resolve_session(a):
    """--session, else THIS session from the environment, else orchlog's heuristic.

    $CLAUDE_CODE_SESSION_ID is the only source that is exactly right. orchlog's pick_session
    prefers "newest session that spawned subagents", which is correct for /implement but actively
    wrong here: a fresh /cleanup session spawns none, so the heuristic would resolve to the
    /implement session that just ran and bill its entire window to the cleanup stage.
    """
    if a.session:
        return a.session
    env = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if env:
        return env
    pdir = Path(a.project_dir).expanduser() if a.project_dir else O.project_dir_for_cwd()
    return O.pick_session(pdir, None)


def cmd_record(a):
    session = resolve_session(a)
    if not session:
        print("stats: no session found (set --session or $CLAUDE_CODE_SESSION_ID) — nothing recorded")
        return 1

    rows = load()
    key = (a.issue, a.stage, session)
    since = a.since or default_since(session, rows, key)
    until = a.until or datetime.now().astimezone().isoformat(timespec="seconds")

    s_dt, u_dt = O.parse_ts(since), O.parse_ts(until)
    if s_dt and u_dt and s_dt > u_dt:
        print(f"stats: empty window for stage {a.stage} — this session's previous stage already ran"
              f" up to {since}, which is after now ({until}). Nothing to record; the earlier stage"
              " owns these tokens.")
        return 1

    tk = O.compute_tokens(session, since, until)
    if not tk or not tk.get("total"):
        print(f"stats: no usage found for session {session} in [{since} .. {until}] — nothing recorded")
        return 1

    rec = {
        "type": "stage",
        "ts": O.now_iso(),
        "issue": a.issue,
        "stage": a.stage,
        "session": session,
        "since": since,
        "until": until,
        "stats_version": STATS_VERSION,
        "workflow_version": O.WORKFLOW_VERSION,
        "by_type": tk["by_type"],
        "total": tk["total"],
    }
    for k in O.USAGE_FIELDS:
        rec[k] = tk[k]
    if a.note:
        rec["note"] = a.note

    # Idempotent: re-recording a stage REPLACES its row. runs.jsonl has campaigns logged three
    # times as progressive snapshots, whose tokens then entered every aggregate three times; this
    # log cannot develop that problem.
    path = log_path()
    kept = [r for r in rows if (r.get("issue"), r.get("stage"), r.get("session")) != key]
    replaced = len(kept) != len(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in kept + [rec]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    cost = estimate_cost(tk["by_type"])
    verb = "replaced" if replaced else "logged"
    print(f"{verb} stage {a.stage} for issue #{a.issue} -> {path}")
    print(f"  window {since} .. {until}")
    print(f"  total={tk['total']:,}  output={tk['output']:,}  cache_read={tk['cache_read']:,}"
          f"  ({O._hit_rate(tk)})  est {usd(cost).strip()}")
    return 0


# ---- report ----------------------------------------------------------------
def _row_line(label, d, pipeline_total):
    share = f"{100 * d['total'] / pipeline_total:5.1f}%" if pipeline_total else "    -"
    return (f"  {label:<10} {d['total']:>13,} {share}  out={d.get('output', 0):>8,} "
            f"c_read={d.get('cache_read', 0):>13,}  {O._hit_pct(d):>6}  {usd(estimate_cost(d.get('by_type')))}")


def report_issue(rows, issue):
    mine = [r for r in rows if str(r.get("issue")) == str(issue)]
    if not mine:
        print(f"no stages recorded for issue #{issue}")
        return
    by_stage = {}
    for r in mine:  # last write wins, though record already dedupes
        by_stage[r["stage"]] = r
    total = sum(r["total"] for r in by_stage.values())
    cost = sum(c for c in (estimate_cost(r.get("by_type")) for r in by_stage.values()) if c is not None)

    print(f"=== issue #{issue} ===")
    print(f"  {'stage':<10} {'total':>13} {'share':>6}  {'output':>12} {'cache_read':>20}  {'hit':>6}  {'est $':>8}")
    for s in STAGES:
        if s in by_stage:
            print(_row_line(s, by_stage[s], total))
    for s in sorted(set(by_stage) - set(STAGES)):  # forward-compat with stages added later
        print(_row_line(s, by_stage[s], total))
    print(f"  {'PIPELINE':<10} {total:>13,} 100.0%{'':>43}  {usd(cost)}")

    missing = [s for s in STAGES if s not in by_stage]
    if missing:
        print(f"\n  MISSING: {', '.join(missing)} — never recorded, so this total is a FLOOR, not the")
        print( "           pipeline cost. A stage that did not record at its end is unrecoverable.")


def report_all(rows, recent=None):
    by_issue = defaultdict(dict)
    for r in rows:
        by_issue[str(r.get("issue"))][r["stage"]] = r
    issues = sorted(by_issue, key=lambda i: max(x["ts"] for x in by_issue[i].values()))
    if recent:
        issues = issues[-recent:]
    if not issues:
        print("stats log is empty")
        return

    print(f"=== stats report ===  issues={len(issues)}  log={log_path()}")
    print(f"  {'issue':>8} {'stages':>7} {'total':>14} {'est $':>9}  complete")
    tot_by_stage = defaultdict(list)
    costs = []
    for i in issues:
        st = by_issue[i]
        t = sum(r["total"] for r in st.values())
        c = sum(x for x in (estimate_cost(r.get("by_type")) for r in st.values()) if x is not None)
        costs.append(c)
        for s, r in st.items():
            tot_by_stage[s].append(r["total"])
        full = "yes" if all(s in st for s in STAGES) else f"no ({len(st)}/{len(STAGES)})"
        print(f"  #{i:>7} {len(st):>7} {t:>14,} {usd(c)}  {full}")

    print("\n  median cost per stage (across issues that recorded it):")
    for s in STAGES:
        v = tot_by_stage.get(s)
        if v:
            print(f"    {s:<10} n={len(v):>3}  median total={statistics.median(v):>13,.0f}")
        else:
            print(f"    {s:<10} n=  0  never recorded")
    if costs:
        print(f"\n  median estimated cost per issue: {usd(statistics.median(costs)).strip()}")
    print("\n  $ figures are ESTIMATES — the per-message model is not recorded, so each agent type"
          "\n  is priced at an assumed tier (see RATES/TYPE_TIER in stats.py). Verify rates before"
          "\n  quoting them.")


def cmd_report(a):
    rows = load()
    if a.issue:
        report_issue(rows, a.issue)
    elif a.json:
        print(json.dumps(rows))
    else:
        report_all(rows, a.recent)
    return 0


# ---- cli -------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(prog="stats", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="write one cost row for the stage that just finished")
    r.add_argument("--issue", required=True, help="parent issue number this stage belongs to")
    r.add_argument("--stage", required=True, choices=STAGES)
    r.add_argument("--session", default=None,
                   help="session id (default: $CLAUDE_CODE_SESSION_ID, else auto-detect from cwd)")
    r.add_argument("--project-dir", default=None)
    r.add_argument("--since", default=None,
                   help="window start ISO (default: end of this session's last recorded stage, "
                        "else session start)")
    r.add_argument("--until", default=None, help="window end ISO (default: now)")
    r.add_argument("--note", default=None)
    r.set_defaults(func=cmd_record)

    p = sub.add_parser("report", help="roll up one issue, or aggregate across issues")
    p.add_argument("--issue", default=None, help="report this parent issue's stage breakdown")
    p.add_argument("--recent", type=int, default=None, help="limit the aggregate to N newest issues")
    p.add_argument("--json", action="store_true", help="dump raw rows")
    p.set_defaults(func=cmd_report)

    a = ap.parse_args()
    raise SystemExit(a.func(a) or 0)


if __name__ == "__main__":
    main()
