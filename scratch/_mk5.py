import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from global_index import track1_gates as g

led_disk = json.loads(Path("scratch/track1_blocking_ledger_20260822.json").read_text(encoding="utf-8"))
out = {
 "stage": "5", "date": "2026-08-23", "kind": "read-only pre-switch audit / dry-run",
 "verdict": "READY_FOR_SHADOW_SCHEDULER_ONLY",
 "verdict_reason": ("Two runbook preconditions have no evidence at all (a measured shadow "
                    "period, and a bootstrapped Track 1 checkpoint), one is ambiguous (its "
                    "check reports green while the live source still refuses to produce a "
                    "candidate), and the broker half of 'legacy is flat' is forbidden here. "
                    "Legacy's LOCAL state is already flat and its scheduler is not running, so "
                    "there is nothing to drain today."),
 "not_claimed": ["ready for live orders", "legacy verified flat at the broker",
                 "Track 1 can produce a live decision today"],
 "preconditions": [
  {"n": 1, "text": "Every Track 1 blocker is CLOSED or has its confirmation on file",
   "check": "track1_gates.may_enable_orders(load_confirmations()[0])",
   "read_only_now": True, "result": "False - ['B1_broker_account_or_legacy_retirement']",
   "status": "FAIL_BY_DESIGN",
   "note": "B1 is the decision this whole stage is about; nothing else blocks"},
  {"n": 2, "text": "The four sleeves can produce a live decision",
   "check": "track1_live_sleeves.readiness()['blocked'] == []",
   "read_only_now": True, "result": "blocked=[] - the check reads PASS",
   "status": "AMBIGUOUS",
   "note": ("the check does not measure the claim: load_source('live').candidates() still "
            "raises NotImplementedError, the Stress sleeve's live chain runs through 4 scratch "
            "modules and Calm A's through 1, and the route's own prerequisite list still names "
            "today's regime label, a cost object and Calm A stop-risk sizing as missing")},
  {"n": 3, "text": "Track 1 slots exist in the scheduler and in the dashboard mirror",
   "check": "track1_slots.parity_report()['in_parity']",
   "read_only_now": True, "result": "True with shadow OFF and True with shadow ON",
   "status": "PASS", "note": "construction-level only; no scheduler was started"},
  {"n": 4, "text": "_ENTRY_WINDOWS contains ((10,35),(12,30))",
   "check": "as written: run_scheduler._ENTRY_WINDOWS",
   "read_only_now": False, "result": "the named check CANNOT be run",
   "status": "PASS_BY_EFFECT",
   "note": ("_ENTRY_WINDOWS is a local variable inside make_scheduler, not a module attribute, "
            "so the runbook's check raises AttributeError. Verified by its observable effect "
            "instead: shadow ON drops stop_repair_1220 (10 sweeps vs 11) and "
            "track1_slots.REQUIRED_ENTRY_WINDOW == run_scheduler._TRACK1_STRESS_WINDOW")},
  {"n": 5, "text": "Track 1 has run shadow for a measured period with the window ledger on",
   "check": "window_coverage_*.jsonl shows complete for both windows every trading day",
   "read_only_now": True, "result": "no window_coverage_*.jsonl exists anywhere in the repo",
   "status": "FAIL",
   "note": ("scratch/track1_shadow holds replay outputs for vault2025/vault2026 only. A replay "
            "of a measured window cannot testify that a window was WATCHED on a given day, "
            "which is what this precondition asks for")},
  {"n": 6, "text": "The Track 1 checkpoint is bootstrapped under track1_params",
   "check": "track1_bootstrap.accepts(...) returns Resumed, not a Refusal",
   "read_only_now": True,
   "result": "Refusal(no_entry) - global_index/replay_checkpoint.track1.json does not exist",
   "status": "FAIL"},
  {"n": 7, "text": "Legacy is flat",
   "check": "live_positions.json positions == [] AND IBKR reports no position",
   "read_only_now": "half", "result": "file half PASS: positions == [] (0 rows)",
   "status": "PARTIAL",
   "note": "the broker half is NOT_CHECKED - connecting to IBKR is forbidden in this stage"},
  {"n": 8, "text": "The route can build today's frame, and only through the guard",
   "check": "track1_gates.live_frame_wiring()", "read_only_now": True,
   "result": "released=True - track1_live_source fetches and joins through the guard",
   "status": "PASS"},
 ],
 "gate_state": {
   "confirmation_file_exists": Path(g.CONFIRMATION_PATH).exists(),
   "self_check": g.self_check(),
   "ledger_matches_registry": led_disk == g.as_ledger(),
   "blocking": [b.id for b in g.blocking()],
   "allow_orders_exit_code": 2,
   "allow_orders_named": ["B1_broker_account_or_legacy_retirement",
                          "TRACK1_ORDERS_APPROVED not set to 1"],
   "named_live_frame_blocker": False,
 },
}
Path("scratch/_stage5_part1.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
print("part 1 written; blocking =", out["gate_state"]["blocking"])
