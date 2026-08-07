#!/usr/bin/env python3
"""Poll a GitHub PR's checks until conclusive, for /cleanup.

Usage:
    pollci.py <pr_number> <target_sha_prefix> [max_polls=40] [interval_sec=30]

Waits until the PR head == target SHA prefix AND every status check has concluded
(nothing PENDING/IN_PROGRESS/QUEUED). Run in the background (run_in_background: true)
so the harness notifies you on exit. Prints a final RESULT_* block.

Exit codes: 0 = conclusive (read RESULT_* lines), 2 = timed out still pending.

Design notes (learned the hard way):
- Right after a push, GitHub briefly returns a stale head / mergeable=UNKNOWN — keep polling.
- Self-hosted runners can sit in_progress for many minutes. That is NOT a hang; do not cancel.
- A paths-filtered PR (e.g. docs-only) may have ZERO checks; treat "head matches + no checks
  after a short grace" as conclusive so the caller can gate on mergeable/CLEAN instead.
"""
import json
import subprocess
import sys
import time

PENDING = {None, "", "PENDING", "IN_PROGRESS", "QUEUED", "EXPECTED", "REQUESTED", "WAITING"}


def main():
    if len(sys.argv) < 3:
        print("usage: pollci.py <pr_number> <target_sha_prefix> [max_polls] [interval_sec]")
        sys.exit(64)
    pr = sys.argv[1]
    target = sys.argv[2]
    max_polls = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    interval = int(sys.argv[4]) if len(sys.argv) > 4 else 30

    first_match = None  # first poll where the head matched; anchors the zero-checks grace window
    for i in range(max_polls):
        try:
            out = subprocess.run(
                ["gh", "pr", "view", pr, "--json",
                 "headRefOid,mergeable,mergeStateStatus,statusCheckRollup"],
                capture_output=True, text=True, timeout=30,
            ).stdout
            d = json.loads(out)
        except Exception as e:  # noqa: BLE001 - transient gh/network hiccup; keep polling
            print(f"poll {i}: err {e}", flush=True)
            time.sleep(interval)
            continue

        head = d.get("headRefOid", "")[:len(target)]
        roll = d.get("statusCheckRollup") or []
        concl = [(c.get("conclusion") or c.get("state") or "PENDING") for c in roll]
        pending = any(x in PENDING for x in concl)
        print(f"poll {i}: head={head} mergeable={d.get('mergeable')} "
              f"state={d.get('mergeStateStatus')} checks={concl}", flush=True)

        if head == target and not pending:
            if first_match is None:
                first_match = i
            # No checks yet? Give GitHub a couple of polls after the head first matched to
            # register any, before deciding this is a genuinely check-less (paths-filtered) PR.
            if not roll and i - first_match < 2:
                time.sleep(interval)
                continue
            print("=== CI CONCLUSIVE ===", flush=True)
            print("RESULT_CHECKS=" + (",".join(concl) if concl
                                      else "(none — likely paths-filtered)"), flush=True)
            print(f"RESULT_MERGEABLE={d.get('mergeable')} "
                  f"RESULT_STATE={d.get('mergeStateStatus')}", flush=True)
            sys.exit(0)

        time.sleep(interval)

    print("=== poll timed out (still pending) — do NOT cancel; re-poll or investigate ===",
          flush=True)
    sys.exit(2)


if __name__ == "__main__":
    main()
