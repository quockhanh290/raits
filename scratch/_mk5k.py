import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from monitor import ops
st = ops.track1_status()
out = {
 "stage": "5K", "date": "2026-08-23", "kind": "ops startup integration for Track 1 shadow",
 "verdict": "READY_TO_START_TRACK1_SHADOW_VIA_OPS",
 "correction": {
   "what": ("every stage since 5C reported '0 scheduler processes'; the probe filtered "
            "Name='python.exe' while monitor/ops.py launches with pythonw.exe"),
   "truth": {"pid": 36656, "started": "2026-08-20 06:35:53", "age": "3d12h",
             "cmd": "pythonw.exe -m global_index.run_scheduler --port 4002 --shadow-resume",
             "track1_shadow": False},
   "consequences": ["Stage 5H's 'why is the scheduler down' question dissolves - it never was",
                    "legacy has been running normally; a flat book was misread as a stopped system",
                    "that scheduler runs code older than today's edits (run_scheduler.py 18:23)",
                    "the first operator command is `restart`, not `up` - `up` leaves a healthy "
                    "scheduler alone, so --track1-shadow would have done nothing"],
   "found_by": "using ops.scheduler_processes(), the project's own function"},
 "changes": [
   {"file": "monitor/ops.py", "what": "--track1-shadow on `up` and `restart`"},
   {"file": "monitor/ops.py", "what": ("_env(track1_shadow=True) setdefaults "
                                       "RAITS_WINDOW_LEDGER_DIR and RAITS_TELEMETRY_DIR to the "
                                       "durable paths and POPS TRACK1_ORDERS_APPROVED")},
   {"file": "monitor/ops.py", "what": ("track1_shadow_blockers(): fail-closed on a present "
                                       "confirmation file and a missing STOP_TRADING")},
   {"file": "monitor/ops.py", "what": "a no-op --track1-shadow under `up` returns 2"},
   {"file": "monitor/ops.py", "what": ("track1_status()/print_track1_status(); mode read from "
                                       "the running process command line")},
 ],
 "legacy_unchanged": ("the Track 1 flag is the only argv difference; legacy children keep their "
                      "environment including TRACK1_ORDERS_APPROVED if the shell carries it"),
 "operator_flow": ["python monitor/ops.py status",
                   "if (-not (Test-Path STOP_TRADING)) { New-Item -ItemType File STOP_TRADING }",
                   "python monitor/ops.py restart --scheduler --track1-shadow --yes",
                   "python monitor/ops.py status"],
 "safety_invariants": {
   "legacy_frozen_before_start": "ops refuses to start without STOP_TRADING",
   "legacy_exits_still_run": "STOP_TRADING clears entry_candidates only",
   "track1_orders_impossible": ["B1 open", "no confirmation file (refused if present)",
                                "TRACK1_ORDERS_APPROVED removed from the child",
                                "no --allow-orders in scheduler args or slot argv"],
   "evidence_durable": "global_index/track1_runtime/, git-ignored, not scratch",
   "flag_cannot_silently_noop": "a no-op --track1-shadow under `up` returns 2",
 },
 "status_now": st,
 "tests": {"stage5k_new": "17 passed",
           "monitor_ops + 5K0 + 5I": "54 passed",
           "dashboard + scheduler + loghygiene + 5B": "58 passed",
           "dashboard_parity": {"legacy_mode": True, "track1_shadow_mode": True},
           "popen": "faked in every test that reaches a launch; nothing started",
           "not_run": "global_index/test_event_playback.py (known hang)",
           "out_of_scope": "test_no_monitor_or_dashboard_file_mentions_the_module"},
 "no_side_effects": ["no service started or stopped (the running scheduler was not touched)",
                     "no IBKR connection", "no order", "no dashboard runtime write",
                     "no STOP_TRADING", "no STOP_TRADING.track1", "no confirmation file",
                     "no commit", "global_index/track1_runtime does not exist"],
 "operator_decision_outstanding": ("the running scheduler is 3.5 days old and runs pre-Track-1 "
                                   "code; restarting it also picks up every legacy change since "
                                   "2026-08-20 - a legacy decision, not only a Track 1 one"),
 "final": ("Stage 5K complete: READY_TO_START_TRACK1_SHADOW_VIA_OPS. Freeze legacy with "
           "STOP_TRADING, then restart --scheduler --track1-shadow. Shadow only; live orders "
           "remain blocked by B1."),
}
Path("scratch/track1_stage5k_ops_startup_integration_20260823.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("verdict:", out["verdict"])
print("scheduler running:", st["scheduler_running"], "| track1 mode:", st["scheduler_track1_shadow"])
