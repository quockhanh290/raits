"""AUDIT-ONLY. Read-only measurement of three claims about the Stress 10:20 candidate.

M1  regime-label causality: backtest labels day D from SPY close of day D (16:00 ET),
    but entry is 10:20 ET on day D. Live has SPY only through D-1. Re-run with lag-1.
M2  entry-bar leakage: forward scan starts strictly AFTER the 10:20 bar, so a stop or
    target touched inside 10:20:00-10:20:59 is invisible. Count them.
M3  cap basis: apply_risk_cap() charges daily_atr*2.5*pv (swing chandelier proxy),
    not this sleeve's real stop risk (stop_dist*pv). Compare the two.

No production file is imported for writing. Nothing is modified.
"""
from __future__ import annotations
import sys
from pathlib import Path
if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import numpy as np
import pandas as pd

from futures._validated_core import benchmark_daily, daily_atr_series, label_regimes, load_parquet
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket
from scratch.harness import ARGV
from scratch.stress_sleeve_validation import Variant, build_variant, clip, arg_from

ACCOUNT = 50_000.0
VARIANTS = [Variant("breadth3_mnq_mes"), Variant("wide3_mnq_mes", breadth="wide_range3")]


def lag1(labels: dict) -> dict:
    """label_lagged[D] = label of the last SPY session strictly before D."""
    s = pd.Series(labels).sort_index()
    s.index = pd.DatetimeIndex(s.index).normalize()
    out = {}
    for d in s.index:
        prior = s[s.index < d]
        if len(prior):
            out[d] = prior.iloc[-1]
    return out


def yr(tr: pd.DataFrame) -> str:
    if tr.empty:
        return "  (no trades)"
    g = tr.groupby("year")["pnl"].agg(["size", "sum"])
    return "  " + "  ".join(f"{int(y)}:n={int(r['size'])},${r['sum']:,.0f}" for y, r in g.iterrows())


def pf(tr: pd.DataFrame) -> float:
    if tr.empty:
        return float("nan")
    w = tr[tr.pnl > 0].pnl.sum(); l = -tr[tr.pnl < 0].pnl.sum()
    return w / l if l else float("inf")


def main() -> int:
    which_list = sys.argv[1:] or ["floor", "vault2025"]
    for which in which_list:
        argv = list(ARGV[which])
        data_dir = arg_from(argv, "--data-dir")
        start = arg_from(argv, "--start"); end = arg_from(argv, "--end")
        regime_csv = arg_from(argv, "--regime-csv", "spy_daily_live.csv")
        hmm_fit_end = arg_from(argv, "--hmm-fit-end", "2024-12-31")

        print(f"\n{'='*78}\n{which}: data_dir={data_dir} start={start} end={end} hmm_fit_end={hmm_fit_end}", flush=True)
        dfs = {n: clip(load_parquet(str(Path(data_dir) / data_filename(c))), start, end)
               for n, c in BASKET.items()}
        atrs = {n: daily_atr_series(d) for n, d in dfs.items()}
        costs = costs_for_basket(slippage_ticks=2.0)
        lab0 = label_regimes(benchmark_daily(regime_csv), "2018-01-01", 3, hmm_fit_end)
        labL = lag1(lab0)

        # ---- self-checks: a measurement that cannot go red proves nothing ----
        assert lab0, "SC1 FAIL: label set empty"
        assert labL, "SC2 FAIL: lagged label set empty"
        s0 = {d for d, v in lab0.items() if v == "Stress"}
        sL = {d for d, v in labL.items() if v == "Stress"}
        assert s0 != sL, "SC3 FAIL: lag changed nothing -> lag not applied"
        print(f"  [SC] labels={len(lab0)} stress_lag0={len(s0)} stress_lag1={len(sL)} "
              f"moved={len(s0 ^ sL)}", flush=True)

        for v in VARIANTS:
            t0, a0 = build_variant(dfs, lab0, costs, atrs, v)
            tL, aL = build_variant(dfs, labL, costs, atrs, v)
            print(f"\n-- {v.name} --")
            print(f"  lag0 (as validated) n={len(t0):>3} net=${t0.pnl.sum() if not t0.empty else 0:>8,.0f} pf={pf(t0):.2f}")
            print(yr(t0))
            print(f"  lag1 (live-causal)  n={len(tL):>3} net=${tL.pnl.sum() if not tL.empty else 0:>8,.0f} pf={pf(tL):.2f}")
            print(yr(tL))
            if not t0.empty:
                d0 = set(zip(t0.day, t0.inst)); dL = set(zip(tL.day, tL.inst)) if not tL.empty else set()
                print(f"  overlap={len(d0 & dL)}  lost_by_lag={len(d0 - dL)}  gained_by_lag={len(dL - d0)}")

            if v.name != "breadth3_mnq_mes" or t0.empty:
                continue

            # ---- M2 entry-bar leakage ----
            hit_stop = hit_tgt = 0
            for _, r in t0.iterrows():
                day_1m = dfs[r["inst"]]
                bar = day_1m[day_1m.index == r["entry_time"]]
                if bar.empty:
                    continue
                if float(bar.iloc[0]["high"]) >= r["stop"]:
                    hit_stop += 1
                if float(bar.iloc[0]["low"]) <= r["target"]:
                    hit_tgt += 1
            print(f"  [M2] entry-bar(10:20) high>=stop: {hit_stop}/{len(t0)}   low<=target: {hit_tgt}/{len(t0)}")

            # ---- M2b exits all same session? ----
            same = int((pd.DatetimeIndex(t0.exit_time).normalize() ==
                        pd.DatetimeIndex(t0.day).normalize()).sum())
            print(f"  [M2b] exit_time on entry date: {same}/{len(t0)}  "
                  f"latest_exit={pd.DatetimeIndex(t0.exit_time).time.max()}")

            # ---- M3 cap basis ----
            atr_risk = t0.daily_atr * 2.5 * t0.inst.map(lambda i: BASKET[i].point_value)
            stop_risk = t0.stop_dist * t0.inst.map(lambda i: BASKET[i].point_value)
            print(f"  [M3] ATR-proxy risk/trade  med=${atr_risk.median():,.0f}  max=${atr_risk.max():,.0f}"
                  f"  ({atr_risk.median()/ACCOUNT:.2%} of {ACCOUNT:,.0f})")
            print(f"  [M3] TRUE stop risk/trade  med=${stop_risk.median():,.0f}  max=${stop_risk.max():,.0f}"
                  f"  ({stop_risk.median()/ACCOUNT:.2%})")
            print(f"  [M3] ratio ATRproxy/true   med={float((atr_risk/stop_risk).median()):.2f}x")
            dayrisk = pd.DataFrame({"day": t0.day, "a": atr_risk, "s": stop_risk}).groupby("day").sum()
            print(f"  [M3] per-DAY (both legs) ATR-proxy max=${dayrisk.a.max():,.0f} ({dayrisk.a.max()/ACCOUNT:.1%})"
                  f" | TRUE max=${dayrisk.s.max():,.0f} ({dayrisk.s.max()/ACCOUNT:.1%})")
            print(f"  [M3] worst single trade=${t0.pnl.min():,.0f}  stop_dist_pct med={t0.stop_dist_pct.median():.3%}"
                  f" max={t0.stop_dist_pct.max():.3%}")
            print(f"  [M3] concurrent legs/day: {t0.groupby('day').size().value_counts().to_dict()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
