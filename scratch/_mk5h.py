import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from global_index import track1_gates as g
ok, detail = g.live_frame_wiring()
out = {
 "stage": "5H", "date": "2026-08-23", "kind": "B1 / shadow-start preflight — audit only",
 "verdict": "NOT_READY_FOR_SHADOW_START",
 "blocker": {
   "what": ("main()'s live-shadow branch never builds a bar provider and there is no "
            "--bar-provider flag, so track1_live_source.build_bar_provider has no caller on "
            "the scheduler path"),
   "kind": "code, not an operator step",
   "measured": {"cmd": ("python -m global_index.run_live_day_track1 --source live-shadow "
                        "--sleeve roska4_calm --slot-id TRACK1_CALM_1000"),
                "result": "decided=False reason=no_bar_provider",
                "window": "0 of 1 decided -> incomplete",
                "checkpoint": "NOT written",
                "ledger_rows": ["window_open", "slot_observed", "window_closed"]},
   "consequence": ("starting the shadow scheduler today freezes legacy and writes rows that "
                   "record that nothing was collected; preconditions 5 and 6 stay shut"),
 },
 "gate_state": {"live_frame_released": ok, "detail": detail,
                "blocking": [b.id for b in g.blocking()],
                "self_check": g.self_check(),
                "orders_possible": g.may_enable_orders()[0],
                "confirmation_file": Path(g.CONFIRMATION_PATH).exists(),
                "allow_orders_exit": 2},
 "scheduler_preflight": {"started": False, "jobs_off": 60, "jobs_on": 84,
                         "track1_slots": 25, "calm": 1, "stress": 24,
                         "legacy_entry_slots_off": 23, "legacy_entry_slots_on": 23,
                         "removed_by_shadow": ["stop_repair_1220"],
                         "slot_has_allow_orders": False, "slot_has_port": False,
                         "slot_source": "live-shadow", "slot_names_window": False},
 "kill_switch": {"legacy": "STOP_TRADING", "track1": "STOP_TRADING.track1", "distinct": True,
                 "legacy_d5": "clears entry_candidates, exits unaffected",
                 "pre_start_broker_read": ("_catch_up_maxhold runs before sched.start(); on a "
                                           "weekday after 09:31 ET it reads the broker, and "
                                           "STOP_TRADING does not prevent it"),
                 "would_fire_now": False, "et_now": "2026-08-23 Sunday"},
 "ledger": {"unset_refuses_first": "ledger_not_configured",
            "temp_dir_records": ["window_open", "slot_observed", "window_closed"],
            "file_naming_caveat": ("file is named by UTC write date while records carry the ET "
                                   "session day; session 2026-08-24 wrote "
                                   "window_coverage_20260823.jsonl"),
            "freshness_binding_live_modes": True},
 "broker_provider": {"connected": False, "fake_only": True,
                     "none_returns": [None, None],
                     "ibkr_with_fake": "IBKRBarProvider built, connect() called on the fake",
                     "real_libs_imported": False,
                     "unknown_kind": "unknown_bar_provider",
                     "disconnect_expectation": ("factory returns (provider, broker) so a caller "
                                                "can disconnect in a finally; no caller exists "
                                                "yet, so no disconnect path exists either")},
 "runbook": {"seven_points_present": True,
             "correction_appended": ("Stage 5H note under precondition 8: the slot cannot obtain "
                                     "a provider today, with the measured output"),
             "production_behaviour_changed": False},
 "tests": {"stage5ab_g1_5g_5c_5d": "60 passed",
           "stage5e_5f_telemetry_overlap": "91 passed, 1 skipped",
           "stage3b_4c_scheduler_dashboard_loghygiene": "154 passed, 1 skipped",
           "stage5b_runbook": "22 passed",
           "explain_wiring_5z": "185 passed, 1 failed (out of scope)",
           "out_of_scope_failure": ("test_no_monitor_or_dashboard_file_mentions_the_module - "
                                    "monitor/ file from another session; monitor/ not touched"),
           "not_run": "global_index/test_event_playback.py"},
 "no_side_effects": ["no scheduler start/stop", "no IBKR connection", "no order",
                     "no dashboard runtime write", "no STOP_TRADING", "no confirmation file",
                     "TRACK1_ORDERS_APPROVED unset", "no commit"],
 "not_claimed": ["ready for live orders", "a broker provider works", "a live day has been run"],
}
Path("scratch/track1_stage5h_b1_shadow_preflight_20260823.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("verdict:", out["verdict"])
