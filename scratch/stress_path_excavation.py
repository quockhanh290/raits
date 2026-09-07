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


def exit_short(fwd: pd.DataFrame, stop: float, target: float | None, end_time: dtime) -> tuple[float, str, pd.Timestamp]:
    fwd = fwd[fwd.index.time <= end_time]
    if fwd.empty:
        raise ValueError("empty fwd")
    ex = float(fwd.iloc[-1]["close"])
    reason = "time"
    xt = fwd.index[-1]
    for ts, bar in fwd.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])
        op = float(bar["open"])
        if high >= stop:
            return (stop if low <= stop else op), "stop", ts
        if target is not None and low <= target:
            return (target if high >= target else op), "target", ts
        ex = float(bar["close"])
        xt = ts
    return ex, reason, xt


def day_context(day1: pd.DataFrame) -> dict | None:
    bars5 = resample_5m(day1).between_time("09:30", "14:00")
    sig = bars5[bars5.index.time == dtime(10, 15)]
    enter = day1.between_time("10:20", "10:20")
    if len(bars5) < 10 or sig.empty or enter.empty:
        return None
    pre5 = bars5[bars5.index.time <= dtime(10, 15)]
    swing = bars5[(bars5.index.time >= dtime(9, 45)) & (bars5.index.time <= dtime(10, 15))]
    open_px = float(bars5.iloc[0]["open"])
    sig_close = float(sig.iloc[-1]["close"])
    vw = vwap(pre5)
    rth = day1.between_time("09:30", "16:00")
    prior = day1[day1.index < rth.index[0]] if not rth.empty else pd.DataFrame()
    gap = 0.0
    if not prior.empty and not rth.empty:
        pc = float(prior.iloc[-1]["close"])
        gap = (float(rth.iloc[0]["open"]) - pc) / pc if pc else 0.0
    rng_0930_1020 = float(pre5["high"].max() - pre5["low"].min())
    return {
        "bars5": bars5,
        "sig_ts": sig.index[-1],
        "entry_ts": enter.index[-1],
        "entry": float(enter.iloc[-1]["open"]),
        "sig_close": sig_close,
        "open": open_px,
        "vwap": vw,
        "swing_high": float(swing["high"].max()),
        "swing_low": float(swing["low"].min()),
        "gap": gap,
        "range_pct": rng_0930_1020 / open_px if open_px else 0.0,
    }


def confirmed_short(day1: pd.DataFrame, ctx: dict, rr: float = 2.0, max_stop_pct: float = 0.015) -> dict | None:
    if ctx["sig_close"] >= ctx["vwap"] or ctx["sig_close"] >= ctx["open"]:
        return None
    entry = ctx["entry"]
    stop = ctx["swing_high"] * 1.001
    dist = stop - entry
    if dist <= 0 or dist / entry > max_stop_pct:
        return None
    target = entry - rr * dist
    fwd = day1[(day1.index > ctx["entry_ts"]) & (day1.index.time <= dtime(14, 0))]
    ex, reason, xt = exit_short(fwd, stop, target, dtime(14, 0))
    return dict(direction="SHORT", entry=entry, exit=ex, entry_time=ctx["entry_ts"], exit_time=xt,
                reason=reason, stop=stop, target=target)


def failed_reclaim_short(day1: pd.DataFrame, ctx: dict, rr: float = 1.5) -> dict | None:
    if ctx["sig_close"] >= ctx["vwap"] or ctx["sig_close"] >= ctx["open"]:
        return None
    scan = day1[(day1.index.time >= dtime(10, 20)) & (day1.index.time <= dtime(11, 30))]
    reclaimed = False
    for ts, bar in scan.iterrows():
        close = float(bar["close"])
        if close >= ctx["vwap"]:
            reclaimed = True
        if reclaimed and close < ctx["vwap"] and close < ctx["open"]:
            entry = close
            stop = max(ctx["vwap"], float(scan.loc[:ts, "high"].tail(15).max())) * 1.0005
            dist = stop - entry
            if dist <= 0 or dist / entry > 0.012:
                return None
            target = entry - rr * dist
            fwd = day1[(day1.index > ts) & (day1.index.time <= dtime(14, 0))]
            if fwd.empty:
                return None
            ex, reason, xt = exit_short(fwd, stop, target, dtime(14, 0))
            return dict(direction="SHORT", entry=entry, exit=ex, entry_time=ts, exit_time=xt,
                        reason=reason, stop=stop, target=target)
    return None


def late_cont_short(day1: pd.DataFrame, ctx: dict) -> dict | None:
    if ctx["sig_close"] >= ctx["vwap"] or ctx["sig_close"] >= ctx["open"]:
        return None
    scan = day1[(day1.index.time >= dtime(11, 0)) & (day1.index.time <= dtime(12, 0))]
    if scan.empty:
        return None
    low_so_far = float(day1[day1.index.time <= dtime(10, 20)]["low"].min())
    for ts, bar in scan.iterrows():
        close = float(bar["close"])
        if close < low_so_far:
            entry = close
            stop = max(ctx["vwap"], float(scan.loc[:ts, "high"].max())) * 1.0005
            dist = stop - entry
            if dist <= 0 or dist / entry > 0.014:
                return None
            target = entry - 1.5 * dist
            fwd = day1[(day1.index > ts) & (day1.index.time <= dtime(14, 0))]
            if fwd.empty:
                return None
            ex, reason, xt = exit_short(fwd, stop, target, dtime(14, 0))
            return dict(direction="SHORT", entry=entry, exit=ex, entry_time=ts, exit_time=xt,
                        reason=reason, stop=stop, target=target)
    return None


def summarize(df: pd.DataFrame) -> None:
    if df.empty:
        print("no trades")
        return
    for variant, s in df.groupby("variant"):
        gw = s.loc[s.pnl > 0, "pnl"].sum()
        gl = -s.loc[s.pnl < 0, "pnl"].sum()
        pf = gw / gl if gl else math.inf
        print(f"{variant:<30} n={len(s):4d} pnl=${s.pnl.sum():>9,.0f} pf={pf:>5.2f} exp=${s.pnl.mean():>7.2f}")
        for yr, y in s.groupby("year"):
            print(f"  {int(yr)} n={len(y):3d} pnl=${y.pnl.sum():>8,.0f} exp=${y.pnl.mean():>7.2f}")
    bad = df[(df.exit < df.bar_low - 1e-9) | (df.exit > df.bar_high + 1e-9)]
    print(f"fill_audit outside_exit_bar={len(bad)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/cache/futures/frozen_sim")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end", default="2022-12-31")
    ap.add_argument("--out", default="scratch/stress_path_excavation.csv")
    args = ap.parse_args()

    labels = label_regimes(benchmark_daily(args.regime_csv), args.hmm_train_end, 3, args.hmm_fit_end)
    costs = costs_for_basket(slippage_ticks=2)
    dfs = {}
    contexts: dict[tuple[pd.Timestamp, str], dict] = {}
    day_frames: dict[tuple[pd.Timestamp, str], pd.DataFrame] = {}
    for inst, contract in BASKET.items():
        df = load_parquet(str(Path(args.data_dir) / data_filename(contract)))
        df = df[(df.index >= pd.Timestamp(args.start).tz_localize(df.index.tz)) &
                (df.index <= pd.Timestamp(args.end).tz_localize(df.index.tz))]
        dfs[inst] = df
        for day_ts, day in df.groupby(df.index.normalize()):
            key = pd.Timestamp(day_ts).tz_localize(None).normalize()
            if labels.get(key) != "Stress":
                continue
            ctx = day_context(day)
            if ctx:
                contexts[(key, inst)] = ctx
                day_frames[(key, inst)] = day

    rows = []
    for (day, inst), ctx in contexts.items():
        contract = BASKET[inst]
        cost = costs[inst].round_turn_cost()
        peer = [contexts.get((day, i)) for i in BASKET]
        peer = [p for p in peer if p is not None]
        below_count = sum(1 for p in peer if p["sig_close"] < p["vwap"] and p["sig_close"] < p["open"])
        range_big_count = sum(1 for p in peer if p["range_pct"] >= 0.0075)
        gap_down_count = sum(1 for p in peer if p["gap"] <= -0.0025)
        filters = {
            "base": True,
            "breadth3": below_count >= 3,
            "breadth4": below_count >= 4,
            "wide_range3": below_count >= 3 and range_big_count >= 3,
            "gapdown2": below_count >= 3 and gap_down_count >= 2,
            "no_gapdown": below_count >= 3 and gap_down_count == 0,
        }
        variants = []
        day1 = day_frames[(day, inst)]
        for fname, ok in filters.items():
            if ok:
                variants.append((f"conf1020_{fname}", confirmed_short(day1, ctx)))
                if fname in {"breadth3", "wide_range3"}:
                    variants.append((f"conf1020_{fname}_rr1", confirmed_short(day1, ctx, rr=1.0)))
                    variants.append((f"conf1020_{fname}_rr15", confirmed_short(day1, ctx, rr=1.5)))
        variants.append(("failed_reclaim", failed_reclaim_short(day1, ctx)))
        variants.append(("late_cont_break", late_cont_short(day1, ctx)))
        for variant, tr in variants:
            if not tr:
                continue
            xt = tr["exit_time"]
            bar = day1.loc[xt]
            rows.append({
                **tr,
                "variant": variant,
                "inst": inst,
                "day": day.date().isoformat(),
                "year": day.year,
                "below_count": below_count,
                "range_big_count": range_big_count,
                "gap_down_count": gap_down_count,
                "range_pct": ctx["range_pct"],
                "gap": ctx["gap"],
                "pnl": (tr["entry"] - tr["exit"]) * contract.point_value - cost,
                "bar_low": float(bar["low"]),
                "bar_high": float(bar["high"]),
            })
    out = pd.DataFrame(rows)
    out.to_csv(args.out, index=False)
    print(f"wrote {args.out} rows={len(out)}")
    summarize(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
