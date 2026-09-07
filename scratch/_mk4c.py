import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from global_index import track1_gates as g
from global_index import track1_live_source as S

released, detail = g.live_frame_wiring()
out = {
 "stage": "4C",
 "date": "2026-08-23",
 "question": "implement and prove the Track 1 live-frame adapter path",
 "verdict": "A",
 "verdict_meaning": ("LIVE_FRAME_ADAPTER_VERIFICATION is released by measurement and no longer "
                     "blocks orders; B1 is the only blocker left. This means the live-frame "
                     "path is wired and guarded OFFLINE. It does not mean Track 1 is ready to "
                     "trade: no live day has been run and no broker has been connected."),

 "task_a_adapter": {
   "module": "global_index/track1_live_source.py",
   "provider_interface": "BarProvider — fetch_session_bars(inst, *, through) -> naive-ET frame",
   "providers": {
     "FrameBarProvider": "deterministic, offline; used by every test and by shadow",
     "IBKRBarProvider": ("the real boundary; delegates to the runner's IBKRBroker rather than "
                         "opening a connection, and refuses with no_broker when handed none. "
                         "Never instantiated by route code in this stage."),
   },
   "ib_insync_imported_at_module_load": False,
   "every_path_ends_in_the_guard": True,
 },

 "task_b_wiring": {
   "entry": "track1_sleeves.LiveSleeveSource.frames() / .detect()",
   "sleeves_served": list(__import__("global_index.track1_params", fromlist=["x"]).SLEEVE_INSTRUMENTS),
   "shared_instrument_joined_once": True,
   "candidates_still_refuses": True,
   "candidates_refusal_reason": ("today's regime label, a cost object, and Calm A's true "
                                 "stop-risk sizing — inputs a live decision needs that this "
                                 "class must not invent"),
   "order_sending_possible": False,
 },

 "task_c_gate": {
   "measurement": "live_frame_wiring",
   "released": released,
   "detail": detail,
   "blocker_status": g.BLOCKERS["LIVE_FRAME_ADAPTER_VERIFICATION"].status,
   "kept_as_measured_gate_not_closed": True,
   "why": ("a MEASURED_GATE re-runs on every read, so a fetch added later that skips the join "
           "shuts it again; CLOSED would freeze a verdict about code that can change"),
   "blocking_now": [b.id for b in g.blocking()],
   "route_modules_scanned": len(g.ROUTE_MODULES),
   "new_detector_vocabulary": ["fetch_session_bars", "fetch_session_bars_direct"],
 },

 "task_d_correctness": {
   "clock_contract": {
     "frozen_half": "parquet stamps are UTC -> New York; Nikkei -> Asia/Tokyo",
     "live_half": "naive ET, the clock IBKRBroker.fetch_bars already produces",
     "conversion": "localize to America/New_York, then convert to the FROZEN FRAME's zone",
     "target_read_from": "the frozen frame, never a table",
   },
   "offset_is_not_constant": {"summer_hours": 13, "winter_hours": 14,
                              "why": "Japan keeps no summer time; the United States does"},
   "failures_the_join_alone_missed": [
     {"direction": "backwards onto history",
      "caught_by": "overlap price agreement",
      "evidence": "reproduced Nikkei error refused; largest disagreement ~1035-1440 points"},
     {"direction": "forwards past history",
      "caught_by": "no bar may be stamped after the fetch instant",
      "evidence": ("the join accepted the whole shifted tail with code=ok before the check "
                   "was added — found by running it, not by reading it")},
   ],
   "stated_limit": ("a multi-day live half shifted forward by less than its own span is caught "
                    "by neither check; a session fetch is hours and a whole-zone error is 13-14, "
                    "so the realistic case is covered. Pinned by a test that names the limit."),
   "equivalence": ["MES cut/join reconstructs the original frame exactly",
                   "MNKD cut/join reconstructs the original frame exactly",
                   "Normal-R4 decisions identical on MES and on MNKD",
                   "Calm A decisions identical on MES",
                   "Calm A gate passes at 10:00 and refuses before it and on a hole",
                   "prior session's 15:59 bar survives the join byte for byte",
                   "Stress gate passes on 09:30-10:30 and refuses a hole and an unobserved window",
                   "duplicates / out-of-order / wrong tz / column mismatch all refuse"],
 },

 "task_e_command": {
   "command": "python -m global_index.run_live_day_track1 --allow-orders --window vault2026",
   "exit_code": 2,
   "refusals": ["B1_broker_account_or_legacy_retirement", "TRACK1_ORDERS_APPROVED not set"],
   "mentions_live_frame_blocker": False,
   "confirmation_file_created": False,
 },
}
Path("scratch/track1_stage4c_live_frame_adapter_20260823.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("verdict", out["verdict"], "| blocking:", out["task_c_gate"]["blocking_now"])
