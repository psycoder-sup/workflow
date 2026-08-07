#!/usr/bin/env python3
"""orchlog — record + analyze /implement workflow runs.

Subcommands:
  record   append one JSONL line (an `agent` or a `run` record) to the log
  report   aggregate the log into improvement signals (quality + cost)
  tokens   scan this session's transcripts and print token usage by agent type

Log file: $ORCHESTRATE_LOG, default ~/.claude/orchestrate/runs.jsonl

The orchestrator (the /implement skill) calls `record` after each wave (one
`agent` line per implementer) and once at milestone end (one `run` line; token
usage is embedded automatically — pass `--no-auto-tokens` to skip). `report`/`tokens`
are for whoever reviews the harness over time to improve the workflow and the agent
architecture.

Token usage is recovered post-hoc from Claude Code transcripts:
  ~/.claude/projects/<sanitized-cwd>/<session>.jsonl                 (orchestrator)
  ~/.claude/projects/<sanitized-cwd>/<session>/subagents/agent-*.jsonl       (subagents)
  ~/.claude/projects/<sanitized-cwd>/<session>/subagents/agent-*.meta.json   (agent type)
Each message carries a `usage` block, so usage is grouped by type. The agent type is
read from the sibling `.meta.json` (`customAgentType`) first — the authoritative source,
and the only one that identifies async in_process_teammate implementers, which carry no
`attributionAgent` in-transcript — falling back to transcript `attributionAgent`/
`attributionSkill`. The session is auto-detected from the current cwd (newest session),
so no session-id plumbing is needed.
"""
import argparse
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

WORKFLOW_VERSION = "2.1.0"  # bump when the kit's architecture/log schema changes
# 2.1.0: token-heavy verification (e2e/long-log suite triage) delegated out of the orchestrator
#        session to a verifier subagent — orchestrator output share drops on e2e-heavy runs.
# 2.0.0: two-dimension gate (width AND volume V>=5; V<=4 -> direct dispatch, unlogged)
#        + linear-chain collapse rule in partitioning. Expect fewer, larger logged runs.


def log_path():
    p = os.environ.get("ORCHESTRATE_LOG")
    if p:
        return Path(p).expanduser()
    return Path.home() / ".claude" / "orchestrate" / "runs.jsonl"


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---- transcript token scan -------------------------------------------------
def _read_lines(path):
    try:
        return path.read_text(errors="replace").splitlines()
    except OSError:
        return []


def sanitize_cwd(path):
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(path))


def projects_root():
    return Path.home() / ".claude" / "projects"


def project_dir_for_cwd(cwd=None):
    return projects_root() / sanitize_cwd(cwd or os.getcwd())


WORKTREE_MARKER = "--claude-worktrees-"


def candidate_project_dirs(project_dir):
    """The cwd's project dir plus the worktree project dirs related to it.

    EnterWorktree changes cwd mid-session, so a milestone's transcripts can live under a
    *different* project dir than the one derived from the current cwd. For auto-detect we
    consider:
      - the cwd's own project dir,
      - its worktree children  (<name>--claude-worktrees-<slug>), and
      - if the cwd IS a worktree dir, the parent repo's project dir.
    """
    root = projects_root()
    dirs = [project_dir]
    for d in sorted(root.glob(project_dir.name + WORKTREE_MARKER + "*")):
        if d.is_dir() and d not in dirs:
            dirs.append(d)
    if WORKTREE_MARKER in project_dir.name:
        parent = root / project_dir.name.split(WORKTREE_MARKER, 1)[0]
        if parent.is_dir() and parent not in dirs:
            dirs.append(parent)
    return dirs


def pick_session(project_dir, session=None):
    """Explicit session, else the newest session that spawned subagents (else newest transcript).

    Searches the cwd's project dir *and* related worktree dirs, so auto-detect still finds the
    session after EnterWorktree relocated the transcripts (the #1 cause of MISSING token data).
    """
    if session:
        return session
    dirs = candidate_project_dirs(project_dir)
    subs = [p for d in dirs for p in d.glob("*/subagents")]
    if subs:
        return max(subs, key=lambda p: p.stat().st_mtime).parent.name
    files = [p for d in dirs for p in d.glob("*.jsonl")]
    if files:
        return max(files, key=lambda p: p.stat().st_mtime).stem
    return None


def find_transcript_files(session):
    """Locate a session's main + subagent transcripts across ALL project dirs.

    A session id is globally unique, but its transcript can be split across project dirs when
    EnterWorktree changes cwd (early planning under the repo dir, later work under the worktree
    dir). Globbing by session id everywhere collects every piece regardless of location.
    Returns (main_transcript_paths, subagent_transcript_paths).
    """
    root = projects_root()
    mains = sorted(root.glob(f"*/{session}.jsonl"))
    subs = sorted(root.glob(f"*/{session}/subagents/agent-*.jsonl"))
    return mains, subs


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sum_usage_file(path, since_dt, until_dt=None):
    out = tot = 0
    for line in _read_lines(path):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if since_dt or until_dt:
            t = parse_ts(o.get("timestamp"))
            if t and since_dt and t < since_dt:
                continue
            if t and until_dt and t > until_dt:
                continue
        m = o.get("message")
        u = m.get("usage") if isinstance(m, dict) else None
        if not u:
            continue
        ot = u.get("output_tokens", 0) or 0
        out += ot
        tot += ((u.get("input_tokens", 0) or 0)
                + (u.get("cache_creation_input_tokens", 0) or 0)
                + (u.get("cache_read_input_tokens", 0) or 0)
                + ot)
    return out, tot


def _meta_agent_type(path):
    """Authoritative agent type from the `<agent>.meta.json` sidecar, or None.

    Async in_process_teammate implementers (the default fan-out) carry entrypoint=cli and NO
    attributionAgent/attributionSkill in their transcript, so the transcript-only heuristics
    below misfile them as 'review' — the bug that made code-implementer cost read as ~0 while
    'review' absorbed it. Their `.meta.json` records the true `customAgentType`
    (e.g. code-implementer), which we trust over everything else. `agentType` is the per-task
    instance slug (api-backend, macos, …), NOT the type — never bucket by it."""
    meta = path.parent / (path.stem + ".meta.json")
    try:
        d = json.loads(meta.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    t = d.get("customAgentType")
    return t if isinstance(t, str) and t else None


def _agent_type_of(path):
    """Agent type for a subagent transcript, in priority order:

      1. `.meta.json` customAgentType   -- authoritative; the ONLY signal that identifies async
         in_process_teammate implementers (no attribution in-transcript).
      2. attributionSkill code-review/security-review -> 'review'  -- the review fan-out agents
         carry attributionAgent=general-purpose but ARE review cost, so the skill wins over the
         agent here.
      3. attributionAgent               -- Explore / Plan / general-purpose research agents.
      4. attributionSkill (other)       -- labelled skill:<name>.
      5. entrypoint=cli -> 'review'     -- legacy last-resort for un-metadata'd cli review agents.
    """
    mt = _meta_agent_type(path)
    if mt:
        return mt
    askill = entry = attr = None
    for line in _read_lines(path):
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if attr is None:
            a = o.get("attributionAgent")
            if a:
                attr = a if isinstance(a, str) else json.dumps(a)
        if askill is None:
            askill = o.get("attributionSkill")
        if entry is None:
            entry = o.get("entrypoint")
        if attr is not None and askill is not None and entry is not None:
            break
    if askill in ("code-review", "security-review"):
        return "review"
    if attr:
        return attr
    if askill:
        return f"skill:{askill}"
    if entry == "cli":
        return "review"  # /code-review + /security-review internal subagents
    return "unknown"


def compute_tokens(session, since=None, until=None):
    """Return {session, output, total, by_type:{type:{output,total,n}}} for a milestone.

    `since`/`until` (ISO) bound the scan to a milestone window. `since` is only needed when a
    session is reused across milestones; a dedicated worktree session can omit both. `until` is
    used mainly for post-hoc backfill (a live run logs at milestone end, so nothing follows it).

    Transcripts are located globally by session id (see find_transcript_files), so a session
    split across the repo dir and a worktree dir — or logged from the "wrong" cwd — is fully
    accounted for, orchestrator main transcript included.
    """
    since_dt = parse_ts(since) if since else None
    until_dt = parse_ts(until) if until else None
    by = {}  # type -> [output, total, n]
    mains, subs = find_transcript_files(session)
    for f in subs:
        o, t = _sum_usage_file(f, since_dt, until_dt)
        if not (o or t):
            continue
        r = by.setdefault(_agent_type_of(f), [0, 0, 0])
        r[0] += o
        r[1] += t
        r[2] += 1
    for f in mains:
        o, t = _sum_usage_file(f, since_dt, until_dt)
        if not (o or t):
            continue
        r = by.setdefault("orchestrator", [0, 0, 0])
        r[0] += o
        r[1] += t
        r[2] += 1
    return {
        "session": session,
        "output": sum(v[0] for v in by.values()),
        "total": sum(v[1] for v in by.values()),
        "by_type": {k: {"output": v[0], "total": v[1], "n": v[2]} for k, v in by.items()},
    }


def _tokens_from_args(a):
    pdir = Path(a.project_dir).expanduser() if a.project_dir else project_dir_for_cwd()
    session = pick_session(pdir, a.session)
    if not session:
        return None
    return compute_tokens(session, a.since, getattr(a, "until", None))


# ---- record ----------------------------------------------------------------
def cmd_record(a):
    rec = {
        "ts": now_iso(),
        "run_id": a.run_id,
        "type": a.type,
        "workflow_version": a.workflow_version or WORKFLOW_VERSION,
    }
    if a.type == "agent":
        rec.update({
            "wave": a.wave,
            "task": a.task,
            "files_owned": a.files_owned,
            "files_changed": a.files_changed,
            "verdict": a.verdict,
            "build": a.build,
            "tests": a.tests,
            "typecheck": a.typecheck,
            "deviated": a.deviated,
            "had_blockers": a.blockers,
            "boundary_stop": a.boundary_stop,
            "isolation": a.isolation,
            "model": a.model,  # tier ORCH routed this task to (opus|sonnet|haiku); model-fit signal
            # rework = re-delegated because the implementer's own work failed self-verify
            # (a quality signal); review_fix = delegated a review finding (healthy, expected).
            # --redelegated is a deprecated alias that folds into rework.
            "rework": a.rework or a.redelegated,
            "review_fix": a.review_fix,
        })
    else:  # run
        # fix activity + parallel width are DERIVED from this run's already-logged agent records,
        # not trusted from the CLI: the hand-entered count conflated rework with healthy
        # review-fixes. --fix-iterations survives only as an explicit override.
        prior = load(log_path())
        rework_n, rfix_n = fix_counts_for_run(a.run_id, prior)
        fix_iters = a.fix_iterations if a.fix_iterations is not None else rework_n
        widths = wave_widths_for_run(a.run_id, prior)
        rec.update({
            "branch": a.branch,
            "milestone": a.milestone,
            "waves": a.waves,
            "agents_total": a.agents,
            "wave_widths": widths,              # per-wave agent counts (derived)
            "peak_width": max(widths) if widths else None,  # max concurrency; ==1 => serial (W>=2 gate)
            "fix_iterations": fix_iters,        # = rework agents (derived) unless overridden
            "rework_agents": rework_n,          # re-delegations after a failed self-verify
            "review_fix_agents": rfix_n,        # review findings routed to fix tasks (healthy)
            "outcome": a.outcome,
            "build_final": a.build_final,
            "tests_final": a.tests_final,
            "review_findings": a.review_findings,
            "pr_created": a.pr_created,
        })
        manual = a.tokens_output is not None
        if a.auto_tokens and not manual:
            tk = _tokens_from_args(a)
            if tk:
                rec["tokens_output"] = tk["output"]
                rec["tokens_total"] = tk["total"]
                rec["tokens_by_type"] = tk["by_type"]
            else:
                rec["tokens_output"] = None  # session not found; recorded as missing
        elif manual:  # explicit --tokens-output overrides the auto scan
            rec["tokens_output"] = a.tokens_output
            if a.tokens_total is not None:
                rec["tokens_total"] = a.tokens_total
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    extra = ""
    if a.type == "run" and rec.get("tokens_output") is not None:
        extra = f"  (tokens: output={rec['tokens_output']:,} total={rec['tokens_total']:,})"
    print(f"logged {a.type} {a.run_id} -> {path}{extra}")


# ---- tokens ----------------------------------------------------------------
def cmd_tokens(a):
    tk = _tokens_from_args(a)
    if not tk:
        print("no session found under", project_dir_for_cwd())
        return
    if a.json:
        print(json.dumps(tk))
        return
    print(f"=== tokens ===  session={tk['session']}")
    print(f"output: {tk['output']:,}   total: {tk['total']:,}   (cache_read usually dominates total)")
    for k, v in sorted(tk["by_type"].items(), key=lambda kv: -kv[1]["output"]):
        print(f"  {k:18} output={v['output']:>10,}  total={v['total']:>13,}  agents={v['n']}")


# ---- report ----------------------------------------------------------------
def load(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def pct(n, d):
    return f"{(100 * n / d):.0f}%" if d else "—"


def _is_rework(r):
    """True if this agent was a re-delegation caused by a FAILED self-verify (quality signal).

    New (>=1.3) records carry explicit `rework`/`review_fix`. Pre-1.3 records only have
    `redelegated`, which we conservatively count as rework unless tagged `review_fix`."""
    if r.get("rework"):
        return True
    if r.get("review_fix"):
        return False
    return bool(r.get("redelegated"))


def fix_counts_for_run(run_id, records):
    """(rework_agents, review_fix_agents) for a run, derived from its agent records.

    This is the authoritative source for a run's fix activity: it counts the per-agent tags
    logged during the waves, not a hand-entered run-level number (which historically conflated
    rework with healthy review-fixes and was near-uniformly 1)."""
    rework = rfix = 0
    for r in records:
        if r.get("type") != "agent" or r.get("run_id") != run_id:
            continue
        if _is_rework(r):
            rework += 1
        elif r.get("review_fix"):
            rfix += 1
    return rework, rfix


def wave_widths_for_run(run_id, records):
    """Per-wave agent counts for a run, ordered by wave, derived from its agent records.

    peak width = max(widths) = the most agents that ran concurrently in any single wave.
    peak == 1 means the run NEVER had two agents in parallel — it was serial work in a
    parallel costume and should not have used /implement (the W>=2 hard gate). This is the
    honest measure of parallel utilization; the `agents/waves` average hides a lone wide wave
    among many 1-agent ones."""
    by_wave = defaultdict(int)
    for r in records:
        if r.get("type") != "agent" or r.get("run_id") != run_id:
            continue
        w = r.get("wave")
        if w is not None:
            by_wave[w] += 1
    return [by_wave[w] for w in sorted(by_wave)]


def cmd_report(a):
    recs = load(log_path())
    if not recs:
        print("no log records yet")
        return

    last_ts = defaultdict(str)
    branch_of = {}
    for r in recs:
        rid = r.get("run_id", "")
        ts = r.get("ts", "")
        if ts > last_ts[rid]:
            last_ts[rid] = ts
        if r.get("type") == "run":
            branch_of[rid] = r.get("branch", "")

    rids = list(last_ts.keys())
    if a.branch:
        rids = [r for r in rids if a.branch in branch_of.get(r, "")]
    if a.since:
        rids = [r for r in rids if last_ts[r][:10] >= a.since]
    rids.sort(key=lambda r: last_ts[r])
    if a.recent:
        rids = rids[-a.recent:]
    keep = set(rids)

    runs = [r for r in recs if r.get("type") == "run" and r.get("run_id") in keep]
    agents = [r for r in recs if r.get("type") == "agent" and r.get("run_id") in keep]

    print(f"=== orchlog report ===  runs={len(runs)}  agents={len(agents)}  run_ids={len(keep)}")
    if a.branch:
        print(f"filter: branch~{a.branch!r}")
    if a.since:
        print(f"filter: since {a.since}")
    if a.recent:
        print(f"filter: last {a.recent} runs")
    print()

    if runs:
        oc = Counter(r.get("outcome") for r in runs)

        def avg(key):
            vals = [r.get(key) for r in runs
                    if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool)]
            return f"{sum(vals) / len(vals):.1f}" if vals else "—"

        # Fix activity is derived from agent tags (authoritative), grouped by run — never from the
        # legacy hand-entered `fix_iterations`, which conflated rework with healthy review-fixes.
        rework_by_run = defaultdict(int)
        rfix_by_run = defaultdict(int)
        for ar in agents:
            rid = ar.get("run_id")
            if _is_rework(ar):
                rework_by_run[rid] += 1
            elif ar.get("review_fix"):
                rfix_by_run[rid] += 1
        nruns = len(runs)
        avg_rework = sum(rework_by_run[r.get("run_id")] for r in runs) / nruns
        avg_rfix = sum(rfix_by_run[r.get("run_id")] for r in runs) / nruns

        # Parallel width derived from agent wave records (authoritative; works for runs logged
        # before peak_width existed). peak==1 = serial work that should not have been orchestrated.
        peaks = []
        for r in runs:
            w = wave_widths_for_run(r.get("run_id"), agents)
            if w:
                peaks.append(max(w))
        avg_peak = sum(peaks) / len(peaks) if peaks else 0
        serial = sum(1 for p in peaks if p == 1)

        pr = sum(1 for r in runs if r.get("pr_created"))
        bf = sum(1 for r in runs if r.get("build_final") == "pass")
        tf = sum(1 for r in runs if r.get("tests_final") == "pass")
        print("RUN")
        print("  outcome:        " + ", ".join(f"{k}={v}" for k, v in oc.items()))
        print(f"  avg waves:      {avg('waves')}")
        print(f"  avg agents:     {avg('agents_total')}")
        print(f"  avg peak width: {avg_peak:.1f}   serial runs (peak==1, W>=2 gate says don't orchestrate): {serial}/{len(runs)}")
        print(f"  avg rework/run:     {avg_rework:.2f}   <- derived from agent tags; high = self-verify failures, briefs/partition need work")
        print(f"  avg review-fix/run: {avg_rfix:.2f}   (healthy: review findings routed to fix tasks)")
        print(f"  build_final ok: {pct(bf, len(runs))}   tests_final ok: {pct(tf, len(runs))}   pr_created: {pct(pr, len(runs))}")
        print()

    if agents:
        n = len(agents)
        vd = Counter(r.get("verdict") for r in agents)
        iso = Counter(r.get("isolation") for r in agents)
        mdl = Counter(r.get("model") for r in agents if r.get("model"))
        bstop = sum(1 for r in agents if r.get("boundary_stop"))
        rework = sum(1 for r in agents if _is_rework(r))
        rfix = sum(1 for r in agents if r.get("review_fix"))
        dev = sum(1 for r in agents if r.get("deviated"))
        blk = sum(1 for r in agents if r.get("had_blockers"))
        print("AGENT")
        print("  verdict:        " + ", ".join(f"{k}={v}" for k, v in vd.items()))
        print(f"  boundary_stop:  {pct(bstop, n)}   <- high = partition too coarse / boundaries wrong")
        print(f"  rework:         {pct(rework, n)}   <- high = self-verify failures; briefs under-specified / task too big")
        print(f"  review_fix:     {pct(rfix, n)}   (healthy: review findings routed to fix tasks — not a quality signal)")
        print(f"  deviated:       {pct(dev, n)}   <- high = acceptance criteria not tight enough")
        print(f"  had_blockers:   {pct(blk, n)}")
        print("  isolation:      " + ", ".join(f"{k}={v}" for k, v in iso.items()))
        if mdl:
            print("  model:          " + ", ".join(f"{k}={v}" for k, v in mdl.items()))
            rw_by = {}
            for r in agents:
                m = r.get("model")
                if not m:
                    continue
                tot, rwk = rw_by.get(m, (0, 0))
                rw_by[m] = (tot + 1, rwk + (1 if _is_rework(r) else 0))
            print("  rework by model: " + ", ".join(f"{k}={rwk}/{tot}" for k, (tot, rwk) in rw_by.items())
                  + "   <- rework clustered in a cheap tier = routed too aggressive")
        print()

    # ---- cost (tokens) ----
    trun = [r for r in runs if isinstance(r.get("tokens_output"), (int, float))]
    if trun:
        bt_out = defaultdict(int)
        bt_n = defaultdict(int)
        for r in trun:
            for k, v in (r.get("tokens_by_type") or {}).items():
                bt_out[k] += v.get("output", 0)
                bt_n[k] += v.get("n", 0)
        nrun = len(trun)
        print("COST (tokens)")
        print(f"  avg output/run: {sum(r['tokens_output'] for r in trun) // nrun:,}")
        print(f"  avg total/run:  {sum(r.get('tokens_total', 0) for r in trun) // nrun:,}   (cache_read dominates total)")
        print("  output by type: " + ", ".join(f"{k}={v:,}" for k, v in sorted(bt_out.items(), key=lambda kv: -kv[1])))
        impl_out, impl_n = bt_out.get("code-implementer", 0), bt_n.get("code-implementer", 0)
        rework = sum(1 for r in agents if _is_rework(r))
        if impl_n and rework:
            per = impl_out / impl_n
            print(f"  ~rework output: {int(per * rework):,}   (est: avg impl output {int(per):,} x {rework} rework agents)  <- tokens spent on rework")
        if len(trun) < len(runs):
            print(f"  (note: {len(runs) - len(trun)} run(s) logged without token data)")
        print()

    vers = Counter(r.get("workflow_version") for r in (runs + agents))
    if len(vers) > 1:
        print("  versions:       " + ", ".join(f"{k}={v}" for k, v in vers.items()) + "  (compare across schema bumps)")


# ---- cli -------------------------------------------------------------------
def _add_session_args(p):
    p.add_argument("--since", default=None, help="ISO ts; narrow to a milestone window start (reused sessions)")
    p.add_argument("--until", default=None, help="ISO ts; narrow to a milestone window end (post-hoc backfill)")
    p.add_argument("--session", default=None, help="session id (default: newest under cwd's project dir)")
    p.add_argument("--project-dir", dest="project_dir", default=None, help="override the projects/<cwd> dir")


def main():
    p = argparse.ArgumentParser(prog="orchlog", description="record + analyze /implement runs")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="append one JSONL record")
    r.add_argument("--type", required=True, choices=["agent", "run"])
    r.add_argument("--run-id", required=True, dest="run_id")
    r.add_argument("--workflow-version", dest="workflow_version", default=None)
    # agent fields
    r.add_argument("--wave", type=int)
    r.add_argument("--task", default="")
    r.add_argument("--files-owned", type=int, dest="files_owned", default=None)
    r.add_argument("--files-changed", type=int, dest="files_changed", default=None)
    r.add_argument("--verdict", choices=["pass", "needs-attention", "fail"])
    r.add_argument("--build", default=None)
    r.add_argument("--tests", default=None)
    r.add_argument("--typecheck", default=None)
    r.add_argument("--deviated", action="store_true")
    r.add_argument("--blockers", action="store_true", help="had blockers")
    r.add_argument("--boundary-stop", action="store_true", dest="boundary_stop")
    r.add_argument("--isolation", choices=["tree", "worktree"], default="tree")
    r.add_argument("--model", choices=["fable", "opus", "sonnet", "haiku"], default=None,
                   help="model tier this implementer ran on (feeds the model-fit signal in report)")
    r.add_argument("--rework", action="store_true",
                   help="re-delegated because the implementer's own work failed self-verify (quality signal)")
    r.add_argument("--review-fix", action="store_true", dest="review_fix",
                   help="delegated a /code-review or /security-review finding as a fix task (healthy, not rework)")
    r.add_argument("--redelegated", action="store_true",
                   help="DEPRECATED: alias for --rework; prefer --rework or --review-fix")
    # run fields
    r.add_argument("--branch", default="")
    r.add_argument("--milestone", default="")
    r.add_argument("--waves", type=int)
    r.add_argument("--agents", type=int)
    r.add_argument("--fix-iterations", type=int, dest="fix_iterations", default=None,
                   help="DEPRECATED: derived from agent rework tags; pass only to override the derived value")
    r.add_argument("--outcome", choices=["success", "partial", "failed"])
    r.add_argument("--build-final", dest="build_final", default=None)
    r.add_argument("--tests-final", dest="tests_final", default=None)
    r.add_argument("--review-findings", type=int, dest="review_findings", default=None)
    r.add_argument("--pr-created", action="store_true", dest="pr_created")
    # run token capture
    r.add_argument("--auto-tokens", action="store_true", dest="auto_tokens", default=True,
                   help="scan this session's transcripts and embed token usage by type (default: on)")
    r.add_argument("--no-auto-tokens", action="store_false", dest="auto_tokens", default=True,
                   help="disable automatic token capture")
    r.add_argument("--tokens-output", type=int, dest="tokens_output", default=None)
    r.add_argument("--tokens-total", type=int, dest="tokens_total", default=None)
    _add_session_args(r)
    r.set_defaults(func=cmd_record)

    t = sub.add_parser("tokens", help="print this session's token usage by agent type")
    t.add_argument("--json", action="store_true", help="emit JSON")
    _add_session_args(t)
    t.set_defaults(func=cmd_tokens)

    rp = sub.add_parser("report", help="aggregate the log")
    rp.add_argument("--recent", type=int, default=None, help="last N runs")
    rp.add_argument("--branch", default=None, help="filter run_ids whose branch contains SUBSTR")
    rp.add_argument("--since", default=None, help="YYYY-MM-DD")
    rp.set_defaults(func=cmd_report)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
