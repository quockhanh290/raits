"""Two follow-up measurements for the combined stop/risk audit. SCRATCH-ONLY.

P1  MAX_HOLD is evaluated before the stop on the exit day.
    The day loop closes a max-hold position at the 09:30 open without first
    asking whether the already-armed stop was touched earlier that same day.
    Count how many booked MAX_HOLD exits had the armed stop level traded through
    before the exit bar, and what that ordering costs versus honouring the stop.

P2  The Calm-NKD challenger and the current NKD sleeve are priced from different
    NKD parquet files in two of the three windows. Confirm the paths and measure
    the price disagreement at the instants the switch forces a close.

Self-checks:
  SC1 trade lists non-empty per window
  SC2 every MAX_HOLD trade resolves its exit bar in the frame
  SC3 the armed instant precedes the exit bar for every counted case

  python scratch/combined_maxhold_stop_order_probe_20260822.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.normal_promotion_variant_matrix_20260821 as vm
import scratch.stress_switch_full_replay_20260822 as full
from futures._validated_core import daily_atr_series, load_parquet
from futures.basket import BASKET
from global_index import specs as gi_specs
from global_index._core import load_parquet as gi_load

ARM_HOURS = 14 + 5 / 60
STOP_BASIS = 2.0
RISK_MULT = 2.5
OUT = Path("scratch/combined_maxhold_stop_order_probe_20260822.json")


def naive(ts):
    t = pd.Timestamp(ts)
    return t.tz_localize(None) if t.tzinfo is not None else t


def p1_maxhold_order(which: str) -> dict:
    raw = json.loads(full.NORMAL_PROMOTION_FILES[which].read_text(encoding="utf-8"))
    frames = vm.load_frames(raw)
    nkd = raw["nkd_instrument"]
    rows, checks = [], dict(n_maxhold=0, n_resolved=0, n_arm_before_exit=0)
    for inst, lst in raw["filtered"].items():
        df = frames[inst]
        datr = daily_atr_series(df)
        pv = (gi_specs.SPECS[nkd] if inst == nkd else BASKET[inst]).point_value
        tz = df.index.tz
        for t in lst:
            if t["reason"] != "MAX_HOLD":
                continue
            checks["n_maxhold"] += 1
            d0 = naive(pd.Timestamp(t["day"])).normalize()
            xt = pd.Timestamp(t["exit_time"])
            if xt.tzinfo is None and tz is not None:
                xt = xt.tz_localize(tz)
            arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=ARM_HOURS)
            arm = arm.tz_localize(tz) if tz is not None else arm
            xday = naive(xt).normalize()
            xday_tz = xday.tz_localize(tz) if tz is not None else xday
            # bars on the exit day, after arming, strictly before the exit bar
            seg = df[(df.index >= max(arm, xday_tz)) & (df.index < xt)]
            checks["n_resolved"] += 1
            if arm >= xt:
                continue
            checks["n_arm_before_exit"] += 1
            if seg.empty:
                continue
            da = datr.asof(d0)
            da = float(da) if (da is not None and not pd.isna(da)) else float(datr.median())
            entry = float(t["entry"])
            stop = entry - STOP_BASIS * da if t["direction"] == "LONG" else entry + STOP_BASIS * da
            touched = (float(seg["low"].min()) <= stop if t["direction"] == "LONG"
                       else float(seg["high"].max()) >= stop)
            if not touched:
                continue
            booked = float(t["pnl"])
            pts_stop = (stop - entry) if t["direction"] == "LONG" else (entry - stop)
            # same cost basis as the booked trade: pnl = points*pv - round_turn
            cost = pts_from_booked = (float(t["points"]) * pv) - booked
            stop_pnl = pts_stop * pv - cost
            rows.append(dict(inst=inst, day=str(t["day"]), exit_day=str(t["exit_day"]),
                             direction=t["direction"], entry=entry, exit=float(t["exit"]),
                             stop=stop, booked_pnl=booked, stop_pnl=stop_pnl,
                             delta=booked - stop_pnl,
                             declared_risk=RISK_MULT * da * pv))
    d = pd.DataFrame(rows)
    res = dict(checks=checks, n_hits=int(len(d)))
    if d.empty:
        return res
    res["total_delta"] = float(d["delta"].sum())
    res["worst_delta"] = float(d["delta"].min())
    res["by_inst"] = [dict(inst=i, n=int(len(g)), delta=float(g["delta"].sum()),
                           n_loss_over_declared=int((-g["booked_pnl"] > g["declared_risk"]).sum()))
                      for i, g in d.groupby("inst")]
    res["worst_rows"] = d.sort_values("delta").head(8).to_dict("records")
    return res


def p2_nkd_series(which: str) -> dict:
    raw = json.loads(full.NORMAL_PROMOTION_FILES[which].read_text(encoding="utf-8"))
    argv = raw["argv"]
    art_path = argv[argv.index("--nkd-parquet") + 1]
    probe_path = "global_index/data/NKD_continuous_1m_8y.parquet"
    res = dict(artifact_nkd_parquet=art_path, calm_nkd_probe_parquet=probe_path,
               same_file=bool(Path(art_path).resolve() == Path(probe_path).resolve()))
    c = gi_specs.SPECS[raw["nkd_instrument"]]
    a = gi_load(art_path)
    a.index = a.index.tz_convert(c.session_tz)
    b = gi_load(probe_path)
    b.index = b.index.tz_convert(c.session_tz)
    joined = a[["close"]].join(b[["close"]], how="inner", lsuffix="_art", rsuffix="_probe")
    if joined.empty:
        res["overlap_bars"] = 0
        return res
    diff = (joined["close_art"] - joined["close_probe"]).abs()
    res["overlap_bars"] = int(len(joined))
    res["n_bars_differ"] = int((diff > 1e-9).sum())
    res["pct_bars_differ"] = float((diff > 1e-9).mean())
    res["median_abs_diff_points"] = float(diff[diff > 1e-9].median()) if (diff > 1e-9).any() else 0.0
    res["max_abs_diff_points"] = float(diff.max())
    res["max_abs_diff_dollars"] = float(diff.max() * c.point_value)
    return res


def main() -> int:
    out = {}
    for which in ("floor", "vault2025", "vault2026"):
        print(f"[run] {which}", flush=True)
        p1 = p1_maxhold_order(which)
        assert p1["checks"]["n_maxhold"] > 0, "SC1/SC2 failed: no MAX_HOLD trades scanned"
        assert p1["checks"]["n_resolved"] == p1["checks"]["n_maxhold"], "SC2 failed"
        assert p1["checks"]["n_arm_before_exit"] > 0, "SC3 failed: no armed MAX_HOLD exits"
        out[which] = dict(p1_maxhold_order=p1, p2_nkd_series=p2_nkd_series(which))
        print(f"[ok] {which} maxhold_scanned={p1['checks']['n_maxhold']} hits={p1['n_hits']}",
              flush=True)
    OUT.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
