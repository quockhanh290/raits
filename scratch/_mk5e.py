import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from global_index import track1_gates as g

out = {
 "stage": "5E", "date": "2026-08-23",
 "kind": "live candidate source, offline/provider-injected; no scheduler, no IBKR, no orders",
 "verdict": "BLOCKED_BY_LIVE_SOURCE",
 "verdict_reason": ("Precondition 2b is CLOSED for Calm A and still OPEN for Stress. Only two "
                    "sleeves have a Track 1 slot; Calm A's 10:00 slot now returns candidates "
                    "with a causal D-1 label, an explicit cost object and risk from the actual "
                    "disaster-stop distance, while the Stress window - 24 of the 25 slots - "
                    "refuses by name because its rule lives in scratch. A shadow period cannot "
                    "complete both windows, so precondition 5 stays shut. The binding gap is "
                    "the live source, not the broker: even a perfect provider leaves Stress "
                    "undecidable."),
 "not_claimed": ["a broker provider works - every test injects FrameBarProvider",
                 "the Stress window can decide",
                 "Normal-R4 or NKD are live - neither has a Track 1 slot",
                 "Track 1 can trade"],

 "sleeve_reachability": {
   "roska4_calm": {"slot": "10:00", "live_source": "CLOSED offline", "instruments": ["MES", "MNQ"]},
   "roska4_stress": {"slot": "10:35-12:30 x24", "live_source": "OPEN - rule in scratch",
                     "instruments": ["MNQ"]},
   "roska4_swing": {"slot": None, "live_source": "N/A - no Track 1 slot, decides 14:00-15:55"},
   "global_nkd": {"slot": None, "live_source": "N/A - no Track 1 slot, overnight"},
 },

 "implemented": [
   {"what": "LiveTrack1Source", "where": "global_index/track1_live_source.py",
    "notes": "provider injected; opens no connection; named refusals"},
   {"what": "causal_regime_label", "where": "global_index/track1_live_source.py",
    "notes": "last label STRICTLY BEFORE the day; asof() would take today's own row"},
   {"what": "causal_daily_atr", "where": "global_index/track1_live_source.py",
    "notes": ("last daily ATR strictly before the day; the artifacts use asof(day), which is "
              "lookahead at 10:00, so live risk can differ in the causal direction")},
   {"what": "default_costs", "where": "global_index/track1_live_source.py",
    "notes": "2 ticks/side, the slippage the measured rows were built under; no broker lookup"},
   {"what": "entry_conditions + detect_entry_for_day", "where": "global_index/track1_calm_a.py",
    "notes": ("the entry test extracted so the historical detector and the 10:00 path share ONE "
              "copy of the rule; detect() needs the 15:55 bar and cannot run at a 10:00 slot")},
   {"what": "disaster_stop + stop_risk_dollars", "where": "global_index/track1_calm_a.py",
    "notes": "risk = abs(entry - stop) x point_value x qty, so moving the stop moves the risk"},
   {"what": "_resample", "where": "global_index/run_live_day_track1.py",
    "notes": ("the gate declares 5-minute bars per sleeve and the joined frame is 1-minute; "
              "handing it the raw frame refused every slot with gate_refused")},
   {"what": "live-shadow source registered", "where": "global_index/track1_sleeves.py"},
 ],

 "refusal_vocabulary": ["no_bar_provider", "regime_unavailable", "cost_missing",
                        "stop_risk_unavailable", "sleeve_not_live",
                        "stress_rule_not_in_package", "no_sleeve_at_this_instant"],

 "measured": {
   "calm_candidates_with_stub_provider": 2,
   "risk_basis": "true_stop_distance",
   "risk_scales_with_point_value": True,
   "slot_decided": True,
   "window_outcome": "complete 1/1",
   "checkpoint_written_to_temp_and_accepted": True,
   "repo_route_state_created": False,
 },

 "remaining_for_2b": [
   "the Stress rule promoted out of scratch, or a decision not to run that sleeve on Track 1",
   "a real bar provider (IBKRBarProvider wrapping the runner's broker) - never constructed here",
 ],
}
Path("scratch/track1_stage5e_live_source_20260823.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("verdict:", out["verdict"])
