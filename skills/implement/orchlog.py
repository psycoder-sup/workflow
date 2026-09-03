#!/usr/bin/env python3
"""orchlog — record + analyze /implement workflow runs.

Subcommands:
  record   append one JSONL line (an `agent` or a `run` record) to the log
  report   aggregate the log into improvement signals (quality + cost)
  tokens   scan this session's transcripts and print token usage by agent type

Log file: $ORCHESTRATE_LOG, default ~/.claude/orchestrate/runs.jsonl

/implement calls `record` once per ticket (one `agent` line per implementer — in solo
mode the session itself, `--executor session`; under /implement-orc one per worker) and once
at campaign end (one `run` line carrying `--mode solo|chain|fanout`; token usage is
embedded automatically — pass `--no-auto-tokens` to skip). `report`/`tokens`
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

WORKFLOW_VERSION = "4.0.0"  # bump when the kit's architecture/log schema changes
# 4.0.0: solo mode is the default — the /implement session implements every ticket itself; the
#        orchestrator/worker split (chain | fanout) lives in the separate /implement-orc skill.
#        Run records carry `mode` (solo|chain|fanout) and `tickets`; agent records carry
#        `executor` (session|subagent|orca). Solo logs ONE agent record per ticket so per-ticket
#        quality rates stay comparable with the 183-agent orchestrated history. Records without
#        `mode`/`executor` are pre-4.0.0 orchestrated runs. In a solo run the `orchestrator` token
#        bucket IS the implementation, not overhead — compare cost within a mode only.
# 3.3.0: chain mode — a graph where fewer than half the tickets can run at width >= 2 gets ONE
#        worker for the whole walk (measured 2.9x wall-clock / 2x cost / 3x diff for one worker
#        per chained ticket); opus is the default tier; parent constraints ride in the header.
# 3.2.0: token scan splits billed usage into output/input/cache_write/cache_read (a single `total`
#        could not say whether caching worked); haiku retired from the routing table (12.5% rework
#        vs sonnet's 3.2% over 24 agents). Cache-split fields exist only from this version on.
# 3.1.0: brief layout fixed at implement-core §0 — a frozen, byte-identical campaign header shared
#        across every worker, orientation digest resolved once by the orchestrator.
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

    Callers should pass $CLAUDE_CODE_SESSION_ID as `session` when available (see _tokens_from_args);
    the subagent heuristic below is a fallback that assumes an orchestrated run.

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


# The four billed buckets, kept separate because they price very differently:
# cache_read ~0.1x base input, cache_creation 1.25x (5m TTL) / 2x (1h), input 1x, output 5x.
# A run's `total` is dominated by cache_read, so a single `total` says nothing about whether
# caching is working — only the split does. See the COST block in `report`.
USAGE_FIELDS = ("output", "input", "cache_creation", "cache_read")


def _empty_usage():
    return dict.fromkeys(USAGE_FIELDS, 0)


def _sum_usage_file(path, since_dt, until_dt=None):
    acc = _empty_usage()
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
        acc["output"] += u.get("output_tokens", 0) or 0
        acc["input"] += u.get("input_tokens", 0) or 0
        acc["cache_creation"] += u.get("cache_creation_input_tokens", 0) or 0
        acc["cache_read"] += u.get("cache_read_input_tokens", 0) or 0
    return acc


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
    by = {}  # type -> usage dict + n
    mains, subs = find_transcript_files(session)

    def add(kind, f):
        acc = _sum_usage_file(f, since_dt, until_dt)
        if not any(acc.values()):
            return
        r = by.setdefault(kind, dict(_empty_usage(), n=0))
        for k in USAGE_FIELDS:
            r[k] += acc[k]
        r["n"] += 1

    for f in subs:
        add(_agent_type_of(f), f)
    for f in mains:
        add("orchestrator", f)

    for r in by.values():
        r["total"] = sum(r[k] for k in USAGE_FIELDS)
    out = {"session": session, "by_type": by}
    for k in USAGE_FIELDS:
        out[k] = sum(r[k] for r in by.values())
    out["total"] = sum(r["total"] for r in by.values())
    return out


def _tokens_from_args(a):
    pdir = Path(a.project_dir).expanduser() if a.project_dir else project_dir_for_cwd()
    # $CLAUDE_CODE_SESSION_ID is the only exactly-right source. pick_session's "newest session
    # that spawned subagents" heuristic was correct when every /implement run was an orchestrator;
    # a solo run that never used verifier/Explore spawns none and would resolve to an OLDER
    # orchestrated session, billing the wrong window.
    session = pick_session(pdir, a.session or os.environ.get("CLAUDE_CODE_SESSION_ID"))
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
            # executor: who implemented — the /implement session itself (solo), a general-purpose
            # subagent, or an Orca terminal worker. Missing on pre-4.0.0 records (= subagent|orca).
            "executor": a.executor,
            # tickets: how many tickets this one record covers (a chain worker covers the whole
            # graph; solo and fan-out records cover exactly one). None = 1.
            "tickets": a.tickets,
            "model": a.model,  # tier the implementer ran on (opus|sonnet); model-fit signal
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
            "mode": a.mode,                     # solo | chain | fanout; None = pre-4.0.0 orchestrated
            "tickets": a.tickets,               # tickets landed in this run
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
                rec["tokens_input"] = tk["input"]
                rec["tokens_cache_creation"] = tk["cache_creation"]
                rec["tokens_cache_read"] = tk["cache_read"]
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
def _cache_hit(d):
    """Cache-read share of all billed *input* (input + cache_write + cache_read), or None.

    Output is excluded: it is never served from cache, so folding it in dilutes the signal.
    None means the record predates the split (only `output`/`total` were stored).
    """
    read = d.get("cache_read")
    if read is None:
        return None
    billed_in = (d.get("input", 0) or 0) + (d.get("cache_creation", 0) or 0) + read
    return (read / billed_in) if billed_in else None


def _hit_pct(d):
    h = _cache_hit(d)
    return "  n/a" if h is None else f"{100 * h:4.1f}%"


def _hit_rate(d):
    h = _cache_hit(d)
    return "cache split unavailable" if h is None else f"cache hit {100 * h:.1f}% of billed input"


def cmd_tokens(a):
    tk = _tokens_from_args(a)
    if not tk:
        print("no session found under", project_dir_for_cwd())
        return
    if a.json:
        print(json.dumps(tk))
        return
    print(f"=== tokens ===  session={tk['session']}")
    print(f"total: {tk['total']:,}")
    print(f"  output={tk['output']:,}  input={tk['input']:,}  "
          f"cache_write={tk['cache_creation']:,}  cache_read={tk['cache_read']:,}"
          f"   ({_hit_rate(tk)})")
    print(f"  {'type':18} {'total':>13} {'output':>10} {'input':>11} {'c_write':>11} {'c_read':>13}  hit   n")
    for k, v in sorted(tk["by_type"].items(), key=lambda kv: -kv[1]["total"]):
        print(f"  {k:18} {v['total']:>13,} {v['output']:>10,} {v.get('input', 0):>11,} "
              f"{v.get('cache_creation', 0):>11,} {v.get('cache_read', 0):>13,}  "
              f"{_hit_pct(v):>5}  {v['n']}")


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


def _run_mode(r):
    """solo | chain | fanout | legacy — legacy = a pre-4.0.0 record, always orchestrated."""
    return r.get("mode") or "legacy"


def _executor(r):
    """session | subagent | orca | legacy — legacy = a pre-4.0.0 worker record."""
    return r.get("executor") or "legacy"


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
        modes = Counter(_run_mode(r) for r in runs)
        # peak_width == 1 is BY DESIGN in solo (one session); it's a mis-mode only when orchestrated.
        orch_runs = [r for r in runs if _run_mode(r) != "solo"]
        orch_serial = sum(1 for r in orch_runs
                          if (w := wave_widths_for_run(r.get("run_id"), agents)) and max(w) == 1
                          and len(w) > 1)
        print("RUN")
        print("  mode:           " + ", ".join(f"{k}={v}" for k, v in modes.items())
              + "   (legacy = pre-4.0.0 orchestrated; compare metrics within a mode)")
        print("  outcome:        " + ", ".join(f"{k}={v}" for k, v in oc.items()))
        print(f"  avg tickets:    {avg('tickets')}   avg waves: {avg('waves')}   avg agents: {avg('agents_total')}")
        print(f"  avg peak width: {avg_peak:.1f}   orchestrated runs that were really a chain (peak==1, >1 worker): {orch_serial}/{len(orch_runs)}")
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
        exe = Counter(_executor(r) for r in agents)
        print("AGENT")
        print("  executor:       " + ", ".join(f"{k}={v}" for k, v in exe.items())
              + "   (one record per ticket in solo/fan-out; a chain record spans `tickets`)")
        print("  verdict:        " + ", ".join(f"{k}={v}" for k, v in vd.items()))
        print(f"  boundary_stop:  {pct(bstop, n)}   <- high = partition too coarse / boundaries wrong")
        print(f"  rework:         {pct(rework, n)}   <- high = self-verify failures; briefs under-specified / task too big")
        print(f"  review_fix:     {pct(rfix, n)}   (healthy: review findings routed to fix tasks — not a quality signal)")
        print(f"  deviated:       {pct(dev, n)}   <- high = acceptance criteria not tight enough")
        print(f"  had_blockers:   {pct(blk, n)}")
        if len(exe) > 1:
            by_exe = {}
            for r in agents:
                e = _executor(r)
                tot, rwk, dv = by_exe.get(e, (0, 0, 0))
                by_exe[e] = (tot + 1, rwk + (1 if _is_rework(r) else 0), dv + (1 if r.get("deviated") else 0))
            print("  by executor:    " + "; ".join(
                f"{e}: rework {pct(rwk, tot)}, deviated {pct(dv, tot)}" for e, (tot, rwk, dv) in by_exe.items())
                  + "   <- the solo-vs-worker quality comparison")
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
        bt = defaultdict(lambda: defaultdict(int))  # type -> bucket -> tokens (split-era only)
        for r in trun:
            for k, v in (r.get("tokens_by_type") or {}).items():
                bt_out[k] += v.get("output", 0)
                bt_n[k] += v.get("n", 0)
                if v.get("cache_read") is not None:
                    for f in USAGE_FIELDS:
                        bt[k][f] += v.get(f, 0)
        nrun = len(trun)
        print("COST (tokens)")
        if any(_run_mode(r) == "solo" for r in trun):
            print("  note: in solo runs the `orchestrator` bucket is the implementing session itself —"
                  " it is the work, not overhead")
        print(f"  avg output/run: {sum(r['tokens_output'] for r in trun) // nrun:,}")
        print(f"  avg total/run:  {sum(r.get('tokens_total', 0) for r in trun) // nrun:,}   (cache_read dominates total)")
        print("  output by type: " + ", ".join(f"{k}={v:,}" for k, v in sorted(bt_out.items(), key=lambda kv: -kv[1])))

        # --- cache split: the only view that says whether caching is working ---
        split = [r for r in trun if r.get("tokens_cache_read") is not None]
        if split:
            agg = {f: sum(r.get("tokens_" + ("cache_creation" if f == "cache_creation" else f), 0)
                          for r in split) for f in USAGE_FIELDS}
            ns = len(split)
            print(f"  cache split ({ns}/{len(trun)} run(s) carry it):")
            print(f"    avg/run  input={agg['input'] // ns:,}  cache_write={agg['cache_creation'] // ns:,}"
                  f"  cache_read={agg['cache_read'] // ns:,}")
            print(f"    {_hit_rate(agg)}   <- low = workers re-reading a prefix that should be shared;"
                  f" see implement-core §0")
            if bt:
                print("    by type: " + ", ".join(
                    f"{k} {_hit_pct(v).strip()}" for k, v in sorted(bt.items(), key=lambda kv: -kv[1]["total"] if "total" in kv[1] else -sum(kv[1].values()))))
        else:
            print("  cache split: not recorded on any run in this window"
                  "  <- pre-3.2.0 records store only output/total; re-run to capture it")
        # Worker output: pre-2.0 workers were `code-implementer` agents (their own bucket); from 2.0
        # /implement-orc briefs general-purpose agents, which share a bucket with research agents,
        # so the estimate is an upper bound there.
        impl_key = "code-implementer" if bt_out.get("code-implementer") else "general-purpose"
        impl_out, impl_n = bt_out.get(impl_key, 0), bt_n.get(impl_key, 0)
        rework = sum(1 for r in agents if _is_rework(r))
        if impl_n and rework:
            per = impl_out / impl_n
            print(f"  ~rework output: {int(per * rework):,}   (est: avg {impl_key} output {int(per):,} x {rework} rework agents)  <- tokens spent on rework")
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
    r.add_argument("--executor", choices=["session", "subagent", "orca"], default=None,
                   help="who implemented: the /implement session itself (solo mode), a subagent, or an Orca worker")
    r.add_argument("--tickets", type=int, default=None,
                   help="agent: tickets this record covers (chain worker = whole graph; default 1). "
                        "run: tickets landed in the run")
    # haiku/fable stay accepted so historical and hand-corrected records still parse; the routing
    # table in /implement is sonnet|opus only as of 3.2.0.
    r.add_argument("--model", choices=["fable", "opus", "sonnet", "haiku"], default=None,
                   help="model tier this implementer ran on (feeds the model-fit signal in report)")
    r.add_argument("--rework", action="store_true",
                   help="re-delegated because the implementer's own work failed self-verify (quality signal)")
    r.add_argument("--review-fix", action="store_true", dest="review_fix",
                   help="delegated a /code-review or /security-review finding as a fix task (healthy, not rework)")
    r.add_argument("--redelegated", action="store_true",
                   help="DEPRECATED: alias for --rework; prefer --rework or --review-fix")
    # run fields
    r.add_argument("--mode", choices=["solo", "chain", "fanout"], default=None,
                   help="solo (/implement: the session implements) | chain | fanout (/implement-orc)")
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
