"""Unarmed-window exposure probe for the Normal-R4 / current-NKD sleeves.

SCRATCH-ONLY.

Those sleeves fill between 14:00 and 15:55 on day D and only arm the stop at
14:05 on the next session. Between the fill and the arm instant there is no stop
resting in the market, so the cluster cap's declared risk cannot bound the loss
over that stretch. This measures how far price actually ran against the position
inside that window, in dollars and as a multiple of declared risk.

Self-checks before any number is read:
  SC1  the trade list is non-empty
  SC2  every trade resolves an arm instant inside its own price frame
  SC3  adverse excursion is >= 0 by construction and finite

  python scratch/combined_unarmed_window_probe_20260822.py --which floor vault2025 vault2026
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.normal_promotion_variant_matrix_20260821 as vm
import scratch.stress_switch_full_replay_20260822 as full
from futures._validated_core import daily_atr_series
from global_index import specs as gi_specs
from futures.basket import BASKET
from scratch.normal_sleeve_fill_audit import _real_risk

ARM_HOURS = 14 + 5 / 60
RISK_MULT = 2.5
STOP_BASIS = 2.0
OUT = Path("scratch/combined_unarmed_window_probe_20260822.json")


def naive(ts):
    t = pd.Timestamp(ts)
    return t.tz_localize(None) if t.tzinfo is not None else t


def run(which: str) -> dict:
    raw = json.loads(full.NORMAL_PROMOTION_FILES[which].read_text(encoding="utf-8"))
    frames = vm.load_frames(raw)
    nkd = raw["nkd_instrument"]
    out_rows, checks = [], {"n_trades": 0, "n_arm_resolved": 0, "n_neg_excursion": 0}
    for inst, lst in raw["filtered"].items():
        df = frames[inst]
        datr = daily_atr_series(df)
        pv = (gi_specs.SPECS[nkd] if inst == nkd else BASKET[inst]).point_value
        for t in lst:
            checks["n_trades"] += 1
            ent = pd.Timestamp(t["entry_time"])
            if ent.tzinfo is None and df.index.tz is not None:
                ent = ent.tz_localize(df.index.tz)
            d0 = naive(pd.Timestamp(t["day"])).normalize()
            arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=ARM_HOURS)
            arm_tz = arm.tz_localize(df.index.tz) if df.index.tz is not None else arm
            xt = pd.Timestamp(t["exit_time"])
            if xt.tzinfo is None and df.index.tz is not None:
                xt = xt.tz_localize(df.index.tz)
            end = min(arm_tz, xt)
            seg = df[(df.index >= ent) & (df.index <= end)]
            if seg.empty:
                continue
            checks["n_arm_resolved"] += 1
            entry = float(t["entry"])
            adverse = ((entry - float(seg["low"].min())) if t["direction"] == "LONG"
                       else (float(seg["high"].max()) - entry))
            if adverse < 0:
                checks["n_neg_excursion"] += 1
            da = datr.asof(d0)
            da = float(da) if (da is not None and not pd.isna(da)) else float(datr.median())
            declared = RISK_MULT * da * pv
            stop_dist = STOP_BASIS * da * pv
            out_rows.append(dict(inst=inst, direction=t["direction"], day=str(t["day"]),
                                 reason=t["reason"],
                                 unarmed_adverse=float(max(adverse, 0.0) * pv),
                                 declared_risk=declared, stop_risk=stop_dist,
                                 hours=float((end - ent).total_seconds() / 3600.0)))
    d = pd.DataFrame(out_rows)
    res = {"checks": checks, "n": int(len(d))}
    if d.empty:
        return res
    d["ratio_declared"] = d["unarmed_adverse"] / d["declared_risk"]
    d["ratio_stop"] = d["unarmed_adverse"] / d["stop_risk"]
    per = []
    for inst, g in d.groupby("inst"):
        per.append(dict(inst=inst, n=int(len(g)),
                        med_hours=float(g["hours"].median()),
                        med_adverse=float(g["unarmed_adverse"].median()),
                        p90_adverse=float(g["unarmed_adverse"].quantile(0.90)),
                        max_adverse=float(g["unarmed_adverse"].max()),
                        med_declared=float(g["declared_risk"].median()),
                        med_ratio_stop=float(g["ratio_stop"].median()),
                        p90_ratio_stop=float(g["ratio_stop"].quantile(0.90)),
                        max_ratio_stop=float(g["ratio_stop"].max()),
                        n_beyond_stop=int((g["ratio_stop"] > 1.0).sum()),
                        pct_beyond_stop=float((g["ratio_stop"] > 1.0).mean()),
                        n_beyond_declared=int((g["ratio_declared"] > 1.0).sum())))
    res["per_instrument"] = per
    res["worst"] = d.sort_values("ratio_stop", ascending=False).head(8).to_dict("records")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    a = ap.parse_args()
    out = {}
    for w in a.which:
        print(f"[run] {w}", flush=True)
        out[w] = run(w)
        c = out[w]["checks"]
        assert c["n_trades"] > 0, "SC1 failed: empty trade list"
        assert c["n_arm_resolved"] == c["n_trades"], (
            f"SC2 failed: {c['n_trades'] - c['n_arm_resolved']} trades had no bars in the unarmed window")
        assert c["n_neg_excursion"] == 0, "SC3 failed: negative adverse excursion"
        print(f"[ok] {w} n={out[w]['n']}", flush=True)
    OUT.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
