import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
import importlib
probe = importlib.import_module("scratch.track1_stage5c_shadow_readiness_probe_20260823")
d = probe.probe()

out = {
 "stage": "5C", "date": "2026-08-23",
 "kind": "read-only readiness check + operator checklist; nothing started, nothing connected",
 "verdict": "NOT_READY_FOR_SHADOW_START",
 "verdict_reason": ("Starting the Track 1 shadow scheduler cannot produce the evidence it "
                    "would be started to produce. Each Track 1 slot runs "
                    "run_live_day_track1 with only --regime-csv, so it defaults to "
                    "--source replay --window vault2026: it REPLAYS a historical window, 25 "
                    "times a trading day. record_window_observation has ZERO call sites and "
                    "boot.write has ZERO call sites, so no window_coverage_*.jsonl and no "
                    "Track 1 checkpoint can ever be written by that path. Preconditions 5 and "
                    "6 therefore cannot turn green by starting the scheduler."),
 "correction_to_earlier_stages": (
   "Stage 5 concluded, and Stage 5B repeated, that starting the shadow scheduler is what moves "
   "preconditions 5 and 6 - 'starting is what fixes them'. That was reasoned from the runbook's "
   "framing and never measured against the call sites. It is wrong. The wiring gap must be "
   "closed first, and the runbook's section 2 status table says the opposite of what is true."),

 "measured_state": d,

 "task2_sequence_validation": {
   "runbook_says_stop_trading_then_start_then_watch": True,
   "shadow_keeps_legacy_entry_slots": True,
   "legacy_entry_slots_under_shadow": d["scheduler_shapes"]["legacy_entry_slots_under_shadow"],
   "track1_slot_argv": ["python", "-m", "global_index.run_live_day_track1",
                        "--regime-csv", "<csv>"],
   "track1_slot_has_allow_orders": False,
   "track1_slot_has_broker_port": False,
   "orders_possible_now": d["orders_possible"],
   "verified_by_execution": ("ran the slot's exact argv: mode=shadow, source=replay, "
                             "window=vault2026, send_order calls=0, legacy files unchanged by "
                             "md5, no window_coverage produced"),
 },

 "wiring_gaps_blocking_the_collection_gate": [
   {"what": "record_window_observation is never called",
    "where": "global_index/run_live_day_track1.py:257 defines it; no caller anywhere",
    "effect": "no window_coverage_*.jsonl can be written -> precondition 5 unreachable"},
   {"what": "the window ledger is off unless RAITS_WINDOW_LEDGER_DIR is set",
    "where": "global_index/window_ledger.py - 'Unset -> off'",
    "effect": "even once a caller exists, the env var must be set or writes are silently skipped"},
   {"what": "nothing writes the Track 1 checkpoint",
    "where": "track1_bootstrap.write has zero call sites in global_index/",
    "effect": "precondition 6 unreachable by running"},
   {"what": "the scheduler slot passes no --source, so it replays history",
    "where": "global_index/run_scheduler.py _track1_body",
    "effect": ("25 identical replays of vault2026 per trading day; run_shadow itself reports "
               "window_ledger: 'not driven: a replay cannot testify to observation'")},
   {"what": "the live source cannot produce candidates anyway",
    "where": "track1_sleeves.load_source('live').candidates() raises NotImplementedError",
    "effect": "even with --source live wired in, there is nothing behind it yet"},
 ],

 "other_findings": [
   {"what": "Track 1 freshness already refuses for today",
    "measured": ("regime_csv last date 2026-08-20 is before the required 2026-08-21; the D-1 "
                 "13:45 contract fails while the scheduler is down and nothing refreshes it")},
   {"what": "starting the scheduler is not inert",
    "measured": ("_catch_up_maxhold runs before sched.start() and, on a weekday after 09:31 ET, "
                 "immediately runs the max-hold exit which reads the BROKER. Today is Sunday ET "
                 "so it would not fire, but a weekday start connects at once. STOP_TRADING does "
                 "not prevent this - D5 clears entries only, exits keep running, by design")},
 ],

 "constraints_held": [
   "no scheduler started or stopped", "no IBKR connection", "no order",
   "no dashboard runtime write", "STOP_TRADING not created",
   "track1_go_live_confirmation.json not created", "TRACK1_ORDERS_APPROVED not set",
   "no commit", "global_index/test_event_playback.py not run",
 ],
}
Path("scratch/track1_stage5c_shadow_start_readiness_20260823.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("verdict:", out["verdict"])
print("safe_to_start_shadow (probe):", d["safe_to_start_shadow"], d["blocking_reasons"])
