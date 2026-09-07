import json
from pathlib import Path
inv = json.loads(Path("scratch/_5k0_inv.json").read_text(encoding="utf-8"))
out = {
 "stage": "5K0", "date": "2026-08-23", "kind": "operational evidence path hygiene",
 "verdict": "READY_FOR_5K_OPS_STARTUP_INTEGRATION",
 "problem": ("Stage 5J's runbook exported RAITS_WINDOW_LEDGER_DIR into scratch/track1_ledger and "
             "live-shadow explanations defaulted to scratch/track1_shadow. A multi-day shadow "
             "period would have kept its ONLY copy inside the directory this project sweeps, "
             "and that evidence is not reproducible - nobody can re-observe a closed window."),
 "split": {"scratch/track1_shadow": "replay and test artifacts (reproducible)",
           "global_index/track1_runtime": ("live-shadow operational evidence: window_coverage/, "
                                           "slot_timing/, shadow/explanations/")},
 "why_that_root": ("it sits beside the route runtime state this repo already keeps under "
                   "global_index/ - live_state_data.js, preflight_state.json, "
                   "replay_checkpoint.track1.json - rather than inventing a new top-level dir"),
 "inventory": inv,
 "code_changes": [
   {"file": "global_index/track1_explain.py",
    "what": ("SHADOW_ROOT kept for replay; OPERATIONAL_ROOT added; _resolve_shadow bounds a SET "
             "(APPROVED_ROOTS) instead of one root; the refusal names both")},
   {"file": "global_index/run_live_day_track1.py",
    "what": ("RUNTIME_ROOT / OPERATIONAL_SHADOW_DIR / RECOMMENDED_LEDGER_DIR / "
             "RECOMMENDED_TELEMETRY_DIR added; observe_live_slot out_dir default moved to the "
             "operational root; run_shadow default deliberately left at scratch")},
   {"file": ".gitignore", "what": "a Track 1 route runtime section, six entries"},
   {"file": "docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md", "what": "section 3b, append-only"},
   {"file": "scratch/track1_stage5j_operator_shadow_start_runbook_20260823.md",
    "what": "step 3's ledger path corrected, with the reason, plus the optional telemetry dir"},
 ],
 "left_in_scratch_deliberately": ["run_shadow replay output", "stage reports and test files"],
 "gitignore_added": ["live_positions.track1.json", "runner.track1.pid",
                     "global_index/replay_checkpoint.track1.json", "STOP_TRADING.track1",
                     "track1_go_live_confirmation.json", "global_index/track1_runtime/"],
 "gitignore_verified_both_ways": {"ignored_paths_checked": 8, "not_ignored_checked": 5},
 "tests": {"stage5k0_new": "27 passed",
           "stage5i + explain + wiring + 5z": "204 passed, 1 out-of-scope failure",
           "stage5b + 5k0 + 5i": "68 passed",
           "slot_telemetry + log_hygiene + dashboard": "40 passed",
           "monitor/test_ops.py": "8 passed",
           "5D + 5E + 5F + G1 + 3B": "181 passed, 2 skipped",
           "out_of_scope": ("test_no_monitor_or_dashboard_file_mentions_the_module - a monitor/ "
                            "file from another session; monitor/ not touched"),
           "not_run": "global_index/test_event_playback.py"},
 "no_side_effects": ["no scheduler start/stop", "no IBKR connection", "no order",
                     "no dashboard runtime write", "no STOP_TRADING", "no STOP_TRADING.track1",
                     "no confirmation file", "no commit",
                     "global_index/track1_runtime not created by any test",
                     "real scratch/track1_shadow/explanations not created"],
 "readiness": ("Stage 5J's READY_FOR_MANUAL_SHADOW_START stands, with corrected paths: the "
               "operator exports the ledger into global_index/track1_runtime/window_coverage"),
 "final": ("Stage 5K0 complete: operational evidence no longer defaults to scratch; proceed to "
           "Stage 5K ops/dashboard startup integration."),
}
Path("scratch/track1_stage5k0_operational_paths_20260823.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
Path("scratch/_5k0_inv.json").unlink()
print("verdict:", out["verdict"])
