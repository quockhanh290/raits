import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from global_index import track1_gates as g
from global_index import track1_params as tp
from global_index import track1_normal_r4 as NR

delta = json.load(open("scratch/_stage4b_fill_law_delta.json", encoding="utf-8"))
windows = {}
for w, v in delta.items():
    if not isinstance(v, dict) or "per_inst" not in v:
        continue
    a = round(sum(i["pnl_artifact"] for i in v["per_inst"].values()), 2)
    p = round(sum(i["pnl_production"] for i in v["per_inst"].values()), 2)
    windows[w] = {
        "pnl_artifact_law": a, "pnl_production_law": p, "delta": round(p - a, 2),
        "rows": sum(i["n_artifact"] for i in v["per_inst"].values()),
        "rows_differing": {k: i["rows_differing"] for k, i in v["per_inst"].items()
                           if i["rows_differing"]},
    }

released, detail = g.live_frame_wiring()
out = {
  "stage": "4B",
  "date": "2026-08-23",
  "question": "close the two remaining technical caveats, or represent them as order-blocking gates",
  "verdict": "B",
  "verdict_meaning": ("fill-law identity is CLOSED in code and tests; the live-frame caveat is "
                      "NOT closed and is now an order-blocking gate released only by a "
                      "measurement. 'Only B1 remains' is no longer true and is not claimed."),

  "caveat_1_fill_law": {
    "status": "CLOSED",
    "was": ("track1_params declared fill_law='production_gap_after_15min_break' as a "
            "hard-coded literal, while every Track 1 row had been generated with every bar "
            "gap-eligible"),
    "now": ("fill_law is a required keyword argument with no default, validated against "
            "FILL_LAWS, threaded through sleeve_config, sleeve_identity, checkpoint_entries, "
            "accepts and checkpoint_report, and sourced from NormalR4Params rather than "
            "named a second time"),
    "laws": list(tp.FILL_LAWS),
    "law_the_route_runs": NR.NormalR4Params().fill_law,
    "identity_differs_between_laws": True,
    "missing_law_raises": "TypeError",
    "unknown_law_raises": "ValueError",
    "checkpoint_cross_law": "refused with params_mismatch, in BOTH directions",
    "measured_delta": windows,
    "rows_total": 1223,
    "rows_differing_total": 6,
  },

  "caveat_2_live_frame": {
    "status": "ORDER_BLOCKING_GATE",
    "blocker_id": "LIVE_FRAME_ADAPTER_VERIFICATION",
    "gate_status": g.MEASURED_GATE,
    "releasable_by_confirmation_flag": False,
    "measurement": "live_frame_wiring",
    "measured_now": {"released": released, "detail": detail},
    "route_modules_scanned": list(g.ROUTE_MODULES),
    "built": ("global_index/track1_live_frame.py — splice(frozen, live) with refusal codes "
              "not_a_frame, empty_frozen, tz_mismatch, duplicate_timestamps, out_of_order, "
              "column_mismatch, history_mutated; notices overlap_trimmed, nothing_new"),
    "proven_offline": [
      "cut/splice round trip reproduces the original frame exactly",
      "the frozen half is byte-compared after every join and the join fails if it moved",
      "an overlapping live bar is trimmed, never applied over history",
      "the NKD 13-hour clock offset is refused rather than converted",
      "Normal-R4 and Calm A reach identical decisions on the spliced frame",
      "a session cut before its closing bar yields no setup rather than a wrong one",
      "the Calm A and Stress intraday gates behave identically on a spliced frame",
    ],
    "not_proven": [
      "that the join is correct on a real trading day — no live day run, no broker connected",
      "that any live bar has ever reached a Track 1 sleeve — nothing on the route fetches one",
    ],
  },

  "order_gate": {
    "blockers_total": len(g.BLOCKERS),
    "closed": sum(1 for b in g.BLOCKERS.values() if b.status == g.CLOSED),
    "blocking_now": [b.id for b in g.blocking()],
    "signature_alone_is_not_enough": True,
    "cli_allow_orders_exit_code": 2,
    "confirmation_file_created": False,
  },
}
Path("scratch/track1_stage4b_identity_liveframe_20260823.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("json written; verdict", out["verdict"], "| blocking:", out["order_gate"]["blocking_now"])
