import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from global_index import track1_gates as g

out = {
 "stage": "5D", "date": "2026-08-23",
 "kind": "wiring fix; no scheduler started, no IBKR, no orders, no commit",
 "verdict": "BLOCKED_BY_LIVE_SOURCE",
 "verdict_reason": ("The wiring Stage 5C found missing is now built and proved end to end: the "
                    "Track 1 slots ask for live-shadow instead of replaying vault2026, each "
                    "slot writes its own ledger row, the last slot of a window closes it, and "
                    "the checkpoint is written when - and only when - the window completed. "
                    "What still holds preconditions 5 and 6 shut is precondition 2b: the live "
                    "candidate source raises, so every real slot records "
                    "decided=false / reason=live_source_not_ready and the window closes "
                    "INCOMPLETE. That is deliberate, not a gap in the wiring."),
 "not_claimed": ["Track 1 can trade", "preconditions 5 or 6 can pass today",
                 "the live candidate source is implemented"],

 "task1_confirmed_before_changing_anything": {
   "track1_slot_argv_had_no_source": True,
   "record_window_observation_call_sites_before": 0,
   "bootstrap_write_call_sites_before": 0,
   "ledger_opt_in_via_RAITS_WINDOW_LEDGER_DIR": True,
   "live_source_candidates_raises": True,
   "probe_safe_to_start_shadow": False,
 },

 "changes": [
   {"file": "global_index/run_scheduler.py",
    "what": ("the Track 1 slot argv now carries --source live-shadow --sleeve <s> "
             "--slot-id <id>; still no --allow-orders and no --port"),
    "legacy_impact": "none - 60 jobs off / 84 on, off-on == {stop_repair_1220}, 23 entry slots"},
   {"file": "global_index/run_live_day_track1.py",
    "what": ("new live-shadow path: observe_live_slot() writes one slot's ledger row and "
             "fails closed with a NAMED reason; close_live_window() reads the day back off "
             "disk and counts only slots that DECIDED; write_route_checkpoint() gives "
             "track1_bootstrap.write its first caller; --source gains live-shadow plus "
             "--sleeve and --slot-id")},
   {"file": "global_index/window_ledger.py",
    "what": ("added files() and read_day() so a window can be closed by reading what the "
             "other slot processes wrote; legacy behaviour untouched, still a silent no-op "
             "when the env var is unset")},
   {"file": "docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md",
    "what": ("retracted 'starting is what fixes them' with a named correction, and rewrote "
             "status rows 5 and 6 to say 2b comes first")},
 ],

 "design": {
   "fail_closed_reasons": ["ledger_not_configured", "no_bar_provider",
                           "live_source_not_ready", "gate_refused"],
   "ledger_missing_is_a_refusal_not_a_noop": True,
   "replay_cannot_write_coverage": True,
   "coverage_counts_only_decided_slots": True,
   "why": ("counting an undecidable slot as observed would manufacture the evidence the ledger "
           "exists to withhold, and would let precondition 5 go green on a route that cannot "
           "trade"),
   "checkpoint_written_only_after_a_complete_window": True,
 },

 "precondition_2b_remaining": [
   "today's regime label for the live session",
   "a cost object per instrument",
   "Calm A's true stop-risk sizing (disaster-stop distance, not the ATR proxy)",
   "a bar provider handed to the slot - IBKRBarProvider wrapping the runner's broker",
   "track1_sleeves.load_source('live').candidates() must return instead of raising",
 ],
}
Path("scratch/track1_stage5d_shadow_live_wiring_20260823.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("verdict:", out["verdict"])
