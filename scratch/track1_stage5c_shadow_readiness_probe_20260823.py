"""scratch/track1_stage5c_shadow_readiness_probe_20260823.py — is it safe to start the shadow?

    python scratch/track1_stage5c_shadow_readiness_probe_20260823.py
    python scratch/track1_stage5c_shadow_readiness_probe_20260823.py --json

**READ-ONLY.** This script starts nothing, connects to nothing, and writes nothing outside its
own stdout. It does not create `STOP_TRADING`, does not create the confirmation file, does not
touch the dashboard, and cannot place an order. It exists so the state an operator is about to
act on is measured at the moment of acting, rather than read out of a report written earlier.

Why a probe rather than a paragraph in the runbook
---------------------------------------------------
Every fact here has already gone stale once in this project. The scheduler was running when
Stage 4 began and was gone by Stage 4B; a precondition table written in Stage 4B was wrong by
Stage 4C. A checklist that names numbers goes out of date silently. This re-measures.

The one number that decides the order of operations
----------------------------------------------------
`--track1-shadow` adds Track 1's jobs and removes exactly one of legacy's. Every legacy entry
slot survives, so **starting the scheduler in shadow mode resumes legacy trading** unless
`STOP_TRADING` is already on disk. That is what `stop_trading_present` and
`legacy_entry_slots_under_shadow` are for, and why `safe_to_start_shadow` is false without the
kill switch.
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

ET = ZoneInfo("America/New_York")


def scheduler_processes() -> tuple:
    """`(count, detail)` — and it can say "I do not know".

    Three outcomes, not two. A probe that folds "the query failed" into "nothing is running" is
    how this repo once launched a second scheduler: two of them fought over client id 1 and six
    entry slots were lost. `None` means unknown and must be treated as "maybe".
    """
    ps = (
        "$p = @(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
        "| Where-Object { $_.CommandLine -like '*run_scheduler*' }); "
        "$p.Count"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return None, f"probe failed to run: {exc}"
    if out.returncode != 0:
        return None, f"probe exited {out.returncode}: {out.stderr.strip()[:120]}"
    txt = out.stdout.strip()
    if not txt.isdigit():
        return None, f"probe returned non-numeric output {txt!r}"
    return int(txt), "counted via Win32_Process"


def _exists(p: str) -> bool:
    return Path(p).exists()


def scheduler_shapes() -> dict:
    """Job counts for both configurations. Builds and discards; starts nothing."""
    from global_index import run_scheduler as rs

    logging.disable(logging.CRITICAL)
    try:
        off = {j.id for j in rs.make_scheduler(port=4002, dry_run=True,
                                               track1_shadow=False).get_jobs()}
        on = {j.id for j in rs.make_scheduler(port=4002, dry_run=True,
                                             track1_shadow=True).get_jobs()}
    finally:
        logging.disable(logging.NOTSET)
    entry_off = sorted(i for i in off if i.startswith("live_day"))
    entry_on = sorted(i for i in on if i.startswith("live_day"))
    t1 = sorted(i for i in on if i.startswith("track1_"))
    return {
        "jobs_off": len(off), "jobs_on": len(on),
        "track1_slots": len(t1),
        "track1_calm_slots": len([i for i in t1 if i.startswith("track1_calm_")]),
        "track1_stress_slots": len([i for i in t1 if i.startswith("track1_stress_")]),
        "track1_first": t1[0] if t1 else None, "track1_last": t1[-1] if t1 else None,
        "legacy_entry_slots_off": len(entry_off),
        "legacy_entry_slots_under_shadow": len(entry_on),
        "shadow_removes_legacy_entries": entry_off != entry_on,
        "added_by_shadow": len(on - off), "removed_by_shadow": sorted(off - on),
    }


def checkpoint_state() -> dict:
    from global_index import run_live_day_track1 as entry
    from global_index import track1_bootstrap as boot
    from global_index import track1_normal_r4 as NR
    import pandas as pd

    path = entry.CHECKPOINT_PATH
    if not Path(path).exists():
        return {"path": path, "present": False, "accepted": False, "code": "file_absent"}
    idx = pd.date_range("2026-03-25", periods=10, freq="5min", tz="America/New_York")
    frame = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
                         index=idx)
    res = boot.accepts(path, sleeve="roska4_swing", inst="MES", frame=frame,
                       regime_csv="spy_daily_live.csv",
                       data_path=entry.default_data_paths()["MES"],
                       fill_law=NR.NormalR4Params().fill_law)
    return {"path": path, "present": True, "accepted": bool(res),
            "code": getattr(res, "code", "ok")}


def probe() -> dict:
    from global_index import track1_gates as g

    n_sched, how = scheduler_processes()
    now_et = datetime.now(ET)
    conf, conf_errs = g.load_confirmations()
    coverage = sorted(set(glob.glob("window_coverage_*.jsonl")
                          + glob.glob("**/window_coverage_*.jsonl", recursive=True)))
    stop_present = _exists("STOP_TRADING")
    shapes = scheduler_shapes()

    out = {
        "measured_at_et": now_et.isoformat(timespec="seconds"),
        "et_weekday": now_et.strftime("%A"),
        "scheduler_running": (None if n_sched is None else n_sched > 0),
        "scheduler_process_count": n_sched,
        "scheduler_probe": how,
        "pid_file_present": _exists("runner.pid"),
        "track1_pid_file_present": _exists("runner.track1.pid"),
        "stop_trading_present": stop_present,
        "stop_trading_track1_present": _exists("STOP_TRADING.track1"),
        "confirmation_present": _exists(g.CONFIRMATION_PATH),
        "confirmation_errors": conf_errs,
        "confirmation_flags": dict(conf.flags),
        "orders_env_present": os.environ.get("TRACK1_ORDERS_APPROVED") is not None,
        "track1_blockers": [b.id for b in g.blocking(conf)],
        "gate_self_check": g.self_check(),
        "orders_possible": g.may_enable_orders(conf)[0],
        "live_frame_wiring_released": g.live_frame_wiring()[0],
        "scheduler_shapes": shapes,
        "window_coverage_files": coverage,
        "window_coverage_present": bool(coverage),
        "checkpoint": checkpoint_state(),
        "maxhold_catch_up_would_fire_on_start": not (
            now_et.weekday() >= 5
            or now_et.hour * 60 + now_et.minute < 9 * 60 + 31),
    }

    # Derived, never typed in. One question: would starting right now let legacy take an entry
    # nobody asked for, or collide with a scheduler that is already up?
    reasons = []
    if out["scheduler_running"] is None:
        reasons.append("cannot tell whether a scheduler is already running")
    elif out["scheduler_running"]:
        reasons.append("a scheduler is already running - a second one fights for client id 1")
    if not stop_present:
        reasons.append(f"STOP_TRADING is absent and shadow mode keeps "
                       f"{shapes['legacy_entry_slots_under_shadow']} legacy entry slots")
    if out["orders_possible"]:
        reasons.append("the order gate is open - this probe expects it shut")
    out["safe_to_start_shadow"] = not reasons
    out["blocking_reasons"] = reasons
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Track 1 shadow-start readiness probe (read-only)")
    ap.add_argument("--json", action="store_true", help="emit the raw dict")
    a = ap.parse_args()
    d = probe()
    if a.json:
        print(json.dumps(d, indent=2, ensure_ascii=False))
        return 0

    s = d["scheduler_shapes"]
    print("=" * 74)
    print(f"TRACK 1 SHADOW READINESS - {d['measured_at_et']} ET ({d['et_weekday']})")
    print("=" * 74)
    print(f"  scheduler running        : {d['scheduler_running']}  "
          f"({d['scheduler_process_count']} proc, {d['scheduler_probe']})")
    print(f"  runner.pid               : {d['pid_file_present']}")
    print(f"  STOP_TRADING             : {d['stop_trading_present']}")
    print(f"  STOP_TRADING.track1      : {d['stop_trading_track1_present']}")
    print(f"  confirmation file        : {d['confirmation_present']}")
    print(f"  TRACK1_ORDERS_APPROVED   : {d['orders_env_present']}")
    print(f"  blockers                 : {d['track1_blockers']}")
    print(f"  orders possible          : {d['orders_possible']}")
    print(f"  live-frame wiring        : "
          f"{'released' if d['live_frame_wiring_released'] else 'HELD'}")
    print()
    print(f"  scheduler jobs off / on  : {s['jobs_off']} / {s['jobs_on']}")
    print(f"  Track 1 slots            : {s['track1_slots']} "
          f"({s['track1_first']} .. {s['track1_last']})")
    print(f"  legacy entry slots ON    : {s['legacy_entry_slots_under_shadow']} "
          f"<- these fire unless STOP_TRADING exists")
    print(f"  removed by shadow        : {s['removed_by_shadow']}")
    print()
    print(f"  window coverage files    : {len(d['window_coverage_files'])}")
    print(f"  Track 1 checkpoint       : present={d['checkpoint']['present']} "
          f"accepted={d['checkpoint']['accepted']} ({d['checkpoint']['code']})")
    print(f"  maxhold catch-up on start: {d['maxhold_catch_up_would_fire_on_start']} "
          f"<- true means a start connects to the broker at once")
    print()
    print(f"  SAFE TO START SHADOW     : {d['safe_to_start_shadow']}")
    for r in d["blocking_reasons"]:
        print(f"     - {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
