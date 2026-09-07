"""Stage 5M-0 — reconstruct the two scheduler state files from log evidence. DRY-RUN BY DEFAULT.

    python scratch/track1_stage5m0_state_repair_20260823.py            # show, write nothing
    python scratch/track1_stage5m0_state_repair_20260823.py --apply    # write (operator only)

What this repairs, and what it refuses to
-----------------------------------------
`global_index/preflight_state.json` and `global_index/maxhold_state.json` were overwritten on
2026-08-23 by a probe that fired the two job bodies with the subprocess runner patched out.
Patching the runner stops the child process; it does not stop the job's success path from
writing its own state file. Both files were reduced to a single key for a Sunday — a day
neither job runs.

These files are FAIL-CLOSED EVIDENCE. `true` for a day means "the update ran and succeeded on
that day", and a slot is allowed to trade because of it. So the one thing this script must
never do is put a `true` next to a day it cannot point at a log line for.

The rule it follows:

    A day is written ONLY if a scheduler log contains an explicit success line for it.
    A day whose run failed, or whose run has no outcome line at all, is NOT written.
    Every existing key with no such line — including the bogus Sunday — is DROPPED.

That last clause is why 2026-08-13's max-hold does not appear in the output: it launched twice
that day (the two-scheduler incident) and neither launch produced a completion line. "It
probably ran" is exactly the inference this file exists to refuse.

Pruning matches the writer
--------------------------
`run_scheduler._save_preflight_state` keeps the newest 7 entries by sorted key. The
reconstruction applies the same rule, so the repaired file is the file the scheduler itself
would have written, not a longer one that happens to contain it.

Clocks
------
Scheduler log lines are stamped in MACHINE-LOCAL time (Calgary). The keys in these files are ET
session dates. A 09:31 ET job logs at 07:31 local, and a late-evening local line can already be
the next ET day — so every timestamp is converted rather than sliced.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import re
import zoneinfo
from pathlib import Path

LOCAL = zoneinfo.ZoneInfo("America/Edmonton")
ET = zoneinfo.ZoneInfo("America/New_York")

PREFLIGHT_PATH = Path("global_index/preflight_state.json")
MAXHOLD_PATH = Path("global_index/maxhold_state.json")
KEEP = 7                      # run_scheduler._PREFLIGHT_KEEP

_PF_START = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})\s+\w+\s+run_scheduler — "
    r"\[PRE-FLIGHT\] Starting: update_ibkr_daily -> update_spy_csv \((\d{4}-\d{2}-\d{2})\)")
_PF_OK = re.compile(r"\[PRE-FLIGHT\] OK")
_PF_FAIL = re.compile(r"\[PRE-FLIGHT\].*FAILED")

_MH_LAUNCH = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})\s+INFO\s+run_scheduler — "
    r"\[(MAX_HOLD_EXIT(?:_CATCHUP)?)\] .*run_maxhold_exit")
_MH_OK = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+INFO\s+run_scheduler — "
    r"\[MAX_HOLD_EXIT(?:_CATCHUP)?\] completed OK")


def _et_day(date_s: str, time_s: str) -> str:
    """A machine-local log stamp as an ET session date."""
    loc = dt.datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL)
    return loc.astimezone(ET).date().isoformat()


def _logs(pattern: str = "scheduler*.log") -> list:
    return sorted(glob.glob(pattern))


def scan_preflight(pattern: str = "scheduler*.log") -> list:
    """Every pre-flight run found, each paired with its own outcome line.

    The ET day comes from the job's OWN message — it prints the date it is recording — rather
    than from the log stamp. One less conversion to get wrong.
    """
    runs = []
    for path in _logs(pattern):
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        for i, ln in enumerate(lines):
            m = _PF_START.match(ln)
            if not m:
                continue
            verdict, ev = "no_outcome_line", None
            for j in range(i + 1, min(i + 60, len(lines))):
                if _PF_START.match(lines[j]):
                    break
                if _PF_OK.search(lines[j]):
                    verdict, ev = "ok", lines[j].strip(); break
                if _PF_FAIL.search(lines[j]):
                    verdict, ev = "failed", lines[j].strip(); break
            runs.append({"day": m.group(3), "log": path, "launched_local": f"{m.group(1)} "
                         f"{m.group(2)}", "verdict": verdict, "evidence": ev})
    return runs


def scan_maxhold(pattern: str = "scheduler*.log") -> list:
    runs = []
    for path in _logs(pattern):
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        for i, ln in enumerate(lines):
            m = _MH_LAUNCH.match(ln)
            if not m:
                continue
            verdict, ev = "no_outcome_line", None
            for j in range(i + 1, min(i + 200, len(lines))):
                if _MH_LAUNCH.match(lines[j]):
                    break
                if _MH_OK.match(lines[j]):
                    verdict, ev = "ok", lines[j].strip(); break
                if "exited with code" in lines[j] and "MAX_HOLD" in lines[j]:
                    verdict, ev = "failed", lines[j].strip(); break
            runs.append({"day": _et_day(m.group(1), m.group(2)), "log": path,
                         "launched_local": f"{m.group(1)} {m.group(2)}",
                         "label": m.group(3), "verdict": verdict, "evidence": ev})
    return runs


def reconstruct(runs: list, *, record_failures: bool) -> dict:
    """Attested days only, pruned exactly the way the scheduler's own writer prunes.

    `record_failures` is the one difference between the two files. The pre-flight writer
    records False on a failure, so a failed day IS part of the record. The max-hold writer only
    ever records True, so a failed day is simply absent — writing False there would invent a
    key the scheduler has no code to produce.
    """
    out: dict = {}
    for r in runs:
        if r["verdict"] == "ok":
            out[r["day"]] = True
        elif r["verdict"] == "failed" and record_failures:
            out[r["day"]] = False
    return dict(sorted(out.items())[-KEEP:])


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def diff(current: dict, proposed: dict) -> dict:
    return {
        "dropped_unattested": sorted(k for k in current if k not in proposed),
        "restored": sorted(k for k in proposed if k not in current),
        "unchanged": sorted(k for k in proposed if current.get(k) == proposed[k]),
        "value_changed": sorted(k for k in proposed
                                if k in current and current[k] != proposed[k]),
    }


def _write_atomic(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="WRITE the repaired files. Without this nothing is written.")
    ap.add_argument("--logs", default="scheduler*.log")
    ap.add_argument("--preflight-path", default=str(PREFLIGHT_PATH))
    ap.add_argument("--maxhold-path", default=str(MAXHOLD_PATH))
    ap.add_argument("--expect-current", default=None,
                    help="JSON the target files must currently hold; refuse to write if they "
                         "do not. Stops a repair from clobbering a file that already healed.")
    a = ap.parse_args(argv)

    pf_runs, mh_runs = scan_preflight(a.logs), scan_maxhold(a.logs)
    pf_new = reconstruct(pf_runs, record_failures=True)
    mh_new = reconstruct(mh_runs, record_failures=False)

    targets = [(Path(a.preflight_path), pf_new, pf_runs, "pre-flight"),
               (Path(a.maxhold_path), mh_new, mh_runs, "max-hold")]

    for path, proposed, runs, label in targets:
        cur = _read(path)
        d = diff(cur, proposed)
        print(f"\n=== {label} — {path} ===")
        print(f"  runs found      : {len(runs)}  "
              f"(ok={sum(1 for r in runs if r['verdict'] == 'ok')}, "
              f"failed={sum(1 for r in runs if r['verdict'] == 'failed')}, "
              f"no outcome={sum(1 for r in runs if r['verdict'] == 'no_outcome_line')})")
        print(f"  current         : {json.dumps(cur)}")
        print(f"  proposed        : {json.dumps(proposed)}")
        print(f"  dropped         : {d['dropped_unattested']}")
        print(f"  restored        : {d['restored']}")
        skipped = sorted({r["day"] for r in runs
                          if r["verdict"] != "ok" and r["day"] not in proposed})
        if skipped:
            print(f"  NOT written (no success line): {skipped}")

    if not a.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to write.")
        return 0

    if a.expect_current is not None:
        want = json.loads(a.expect_current)
        for path, *_ in targets:
            if _read(path) != want:
                print(f"\nREFUSED: {path} does not hold the expected content; it has changed "
                      f"since this repair was planned. Re-plan rather than overwrite.")
                return 2

    for path, proposed, _runs, label in targets:
        _write_atomic(path, proposed)
        print(f"WROTE {path}: {json.dumps(proposed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
