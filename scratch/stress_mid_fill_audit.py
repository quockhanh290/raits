from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, label_regimes, load_parquet, resample_5m
from futures.basket import BASKET, data_filename
from futures.stress_mid import StressMidEngine
from futures.swing_tf import costs_for_basket


def corrected_exit_short(fwd: pd.DataFrame, stop: float, target: float) -> tuple[float, str, pd.Timestamp]:
    ex = float(fwd.iloc[-1]["close"])
    reason = "eod"
    xt = fwd.index[-1]
    for ts, bar in fwd.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])
        op = float(bar["open"])
        if high >= stop:
            return (stop if low <= stop else op), "stop", ts
        if low <= target:
            return (target if high >= target else op), "target", ts
        ex = float(bar["close"])
        xt = ts
    return ex, reason, xt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/cache/futures/frozen_sim")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end", default="2022-12-31")
    args = ap.parse_args()

    labels = label_regimes(benchmark_daily(args.regime_csv), args.hmm_train_end, 3, args.hmm_fit_end)
    costs = costs_for_basket(slippage_ticks=2)
    engine = StressMidEngine()
    rows = []
    for inst, contract in BASKET.items():
        df = load_parquet(str(Path(args.data_dir) / data_filename(contract)))
        df = df[(df.index >= pd.Timestamp(args.start).tz_localize(df.index.tz)) &
                (df.index <= pd.Timestamp(args.end).tz_localize(df.index.tz))]
        trades = engine.backtest(df, labels, costs[inst])
        day5 = {pd.Timestamp(d).tz_localize(None).normalize(): resample_5m(g)
                for d, g in df.groupby(df.index.normalize())}
        for t in trades:
            day = pd.Timestamp(t["day"]).normalize()
            b5 = day5[day]
            xt = pd.Timestamp(t["exit_time"])
            bar = b5.loc[xt]
            outside_bar = not (float(bar["low"]) - 1e-9 <= t["exit"] <= float(bar["high"]) + 1e-9)
            pre = b5[b5.index.time <= pd.Timestamp(t["entry_time"]).time()]
            swing = b5[(b5.index.time >= pd.Timestamp("09:45").time()) &
                       (b5.index.time <= pd.Timestamp("10:15").time())]
            stop = float(swing["high"].max()) * (1 + engine.stop_pad)
            dist = stop - float(t["entry"])
            target = float(t["entry"]) - engine.target_rr * dist
            fwd = b5[(b5.index > pd.Timestamp(t["entry_time"])) &
                     (b5.index.time <= pd.Timestamp("14:00").time())]
            cex, creason, cxt = corrected_exit_short(fwd, stop, target)
            old_pnl = float(t["pnl"])
            new_pnl = (float(t["entry"]) - cex) * contract.point_value - costs[inst].round_turn_cost()
            rows.append({
                "inst": inst,
                "day": str(t["day"]),
                "entry_time": t["entry_time"],
                "exit_time": t["exit_time"],
                "exit_reason": t["exit_reason"],
                "entry": t["entry"],
                "exit": t["exit"],
                "bar_low": float(bar["low"]),
                "bar_high": float(bar["high"]),
                "outside_bar": outside_bar,
                "corrected_exit": cex,
                "corrected_reason": creason,
                "corrected_exit_time": cxt,
                "old_pnl": old_pnl,
                "new_pnl": new_pnl,
                "delta": new_pnl - old_pnl,
            })
    out = pd.DataFrame(rows)
    out.to_csv("scratch/stress_mid_fill_audit.csv", index=False)
    print(f"trades={len(out)} old=${out.old_pnl.sum():,.0f} corrected=${out.new_pnl.sum():,.0f} delta=${out.delta.sum():,.0f}")
    print(f"outside_exit_bar={int(out.outside_bar.sum())}")
    changed = out[out.delta.abs() > 1e-9]
    print(f"changed_by_gapthrough={len(changed)} delta=${changed.delta.sum():,.0f}")
    if len(changed):
        print(changed[["inst", "day", "exit_reason", "entry", "exit", "bar_low", "bar_high", "corrected_exit", "old_pnl", "new_pnl", "delta"]].head(20).to_string(index=False))
    for inst, s in out.groupby("inst"):
        print(f"{inst} n={len(s)} old=${s.old_pnl.sum():>8,.0f} corrected=${s.new_pnl.sum():>8,.0f} changed={int((s.delta.abs()>1e-9).sum())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
