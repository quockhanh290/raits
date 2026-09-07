from __future__ import annotations

import argparse
import math
import sys
from datetime import time as dtime
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, label_regimes, load_parquet, resample_5m
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket


def vwap(bars: pd.DataFrame) -> float:
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    vol = bars["volume"]
    return float((tp * vol).sum() / vol.sum()) if float(vol.sum()) > 0 else float(bars["close"].iloc[-1])


def exit_short(fwd: pd.DataFrame, stop: float, target: float) -> tuple[float, str, pd.Timestamp]:
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


def sim_day(raw_1m: pd.DataFrame, mode: str) -> dict | None:
    if mode == "current_5m_label1015":
        bars = resample_5m(raw_1m).between_time("09:30", "14:00")
        at = bars[bars.index.time == dtime(10, 15)]
        if at.empty:
            return None
        entry_ts = at.index[-1]
        entry = float(at.iloc[-1]["close"])
        pre = bars[bars.index.time <= dtime(10, 15)]
        open_px = float(bars.iloc[0]["open"])
        swing = bars[(bars.index.time >= dtime(9, 45)) & (bars.index.time <= dtime(10, 15))]
        fwd = bars[(bars.index > entry_ts) & (bars.index.time <= dtime(14, 0))]
    elif mode == "live_1m_exact1015":
        bars = raw_1m.between_time("09:30", "14:00")
        at = bars[bars.index.time == dtime(10, 15)]
        if at.empty:
            return None
        entry_ts = at.index[-1]
        entry = float(at.iloc[-1]["close"])
        pre = bars[bars.index.time <= dtime(10, 15)]
        open_px = float(bars.iloc[0]["open"])
        swing = bars[(bars.index.time >= dtime(9, 45)) & (bars.index.time <= dtime(10, 15))]
        fwd = bars[(bars.index > entry_ts) & (bars.index.time <= dtime(14, 0))]
    elif mode == "confirmed_5m_enter1020":
        bars5 = resample_5m(raw_1m).between_time("09:30", "14:00")
        sig = bars5[bars5.index.time == dtime(10, 15)]
        bars1 = raw_1m.between_time("09:30", "14:00")
        at = bars1[bars1.index.time == dtime(10, 20)]
        if sig.empty or at.empty:
            return None
        entry_ts = at.index[-1]
        entry = float(at.iloc[-1]["open"])
        pre = bars5[bars5.index.time <= dtime(10, 15)]
        open_px = float(bars5.iloc[0]["open"])
        swing = bars5[(bars5.index.time >= dtime(9, 45)) & (bars5.index.time <= dtime(10, 15))]
        fwd = bars1[(bars1.index >= entry_ts) & (bars1.index.time <= dtime(14, 0))]
    else:
        raise ValueError(mode)

    if len(pre) < 5 or fwd.empty:
        return None
    vw = vwap(pre)
    signal_close = float(pre.iloc[-1]["close"])
    if signal_close >= vw or signal_close >= open_px:
        return None
    stop = float(swing["high"].max()) * 1.001
    dist = stop - entry
    if dist <= 0 or dist / entry > 0.015:
        return None
    target = entry - 2.0 * dist
    ex, reason, xt = exit_short(fwd, stop, target)
    return {
        "entry_time": entry_ts,
        "exit_time": xt,
        "entry": entry,
        "exit": ex,
        "reason": reason,
    }


def summarize(df: pd.DataFrame) -> None:
    for mode, s in df.groupby("mode"):
        gw = s.loc[s.pnl > 0, "pnl"].sum()
        gl = -s.loc[s.pnl < 0, "pnl"].sum()
        pf = gw / gl if gl else math.inf
        print(f"{mode:<24} n={len(s):4d} pnl=${s.pnl.sum():>9,.0f} pf={pf:>5.2f} exp=${s.pnl.mean():>7.2f}")
        for yr, y in s.groupby("year"):
            print(f"  {int(yr)} n={len(y):3d} pnl=${y.pnl.sum():>8,.0f} exp=${y.pnl.mean():>7.2f}")


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
    rows = []
    modes = ["current_5m_label1015", "live_1m_exact1015", "confirmed_5m_enter1020"]
    for inst, contract in BASKET.items():
        df = load_parquet(str(Path(args.data_dir) / data_filename(contract)))
        df = df[(df.index >= pd.Timestamp(args.start).tz_localize(df.index.tz)) &
                (df.index <= pd.Timestamp(args.end).tz_localize(df.index.tz))]
        cost = costs[inst].round_turn_cost()
        for day_ts, day in df.groupby(df.index.normalize()):
            key = pd.Timestamp(day_ts).tz_localize(None).normalize()
            if labels.get(key) != "Stress":
                continue
            for mode in modes:
                tr = sim_day(day, mode)
                if not tr:
                    continue
                rows.append({
                    **tr,
                    "inst": inst,
                    "day": key.date().isoformat(),
                    "year": key.year,
                    "mode": mode,
                    "pnl": (tr["entry"] - tr["exit"]) * contract.point_value - cost,
                })
    out = pd.DataFrame(rows)
    out.to_csv("scratch/stress_mid_timing_probe.csv", index=False)
    summarize(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
