from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import time as dtime
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, label_regimes, load_parquet
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket

STRESS_RR = 2.0
STRESS_ORB_RR = 1.5
CALM_FADE_THRESHOLD = 0.35
CALM_FADE_STOP = 0.35


@dataclass(frozen=True)
class Variant:
    name: str
    regime: str
    family: str


def vwap(bars: pd.DataFrame) -> float:
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    vol = bars["volume"]
    return float((tp * vol).sum() / vol.sum()) if float(vol.sum()) > 0 else float(bars["close"].iloc[-1])


def first_exit(
    direction: str,
    fwd: pd.DataFrame,
    stop: float,
    target: float,
) -> tuple[float, str, pd.Timestamp]:
    if fwd.empty:
        raise ValueError("empty fwd")
    exit_px = float(fwd.iloc[-1]["close"])
    reason = "TIME"
    exit_ts = fwd.index[-1]
    for ts, bar in fwd.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])
        open_px = float(bar["open"])
        if direction == "LONG":
            if low <= stop:
                return (stop if high >= stop else open_px), "STOP", ts
            if high >= target:
                return (target if low <= target else open_px), "TARGET", ts
        else:
            if high >= stop:
                return (stop if low <= stop else open_px), "STOP", ts
            if low <= target:
                return (target if high >= target else open_px), "TARGET", ts
        exit_px = float(bar["close"])
        exit_ts = ts
    return exit_px, reason, exit_ts


def pnl(direction: str, entry: float, exit_px: float, point_value: float, cost: float) -> float:
    pts = (exit_px - entry) if direction == "LONG" else (entry - exit_px)
    return pts * point_value - cost


def stress_mid(day: pd.DataFrame) -> list[dict]:
    win = day.between_time("09:30", "14:00")
    at = win[win.index.time == dtime(10, 15)]
    if win.empty or at.empty:
        return []
    open_px = float(win.iloc[0]["open"])
    entry = float(at.iloc[-1]["close"])
    pre = win[win.index.time <= dtime(10, 15)]
    vw = vwap(pre)
    if entry >= vw or entry >= open_px:
        return []
    swing = win[(win.index.time >= dtime(9, 45)) & (win.index.time <= dtime(10, 15))]
    stop = float(swing["high"].max()) * 1.001
    dist = stop - entry
    if dist <= 0 or dist / entry > 0.015:
        return []
    target = entry - STRESS_RR * dist
    fwd = win[(win.index > at.index[-1]) & (win.index.time <= dtime(14, 0))]
    if fwd.empty:
        return []
    ex, reason, xt = first_exit("SHORT", fwd, stop, target)
    return [dict(strategy="stress_mid_short", direction="SHORT", entry=entry, exit=ex,
                 stop=stop, target=target, entry_time=at.index[-1], exit_time=xt,
                 reason=reason)]


def stress_orb(day: pd.DataFrame) -> list[dict]:
    win = day.between_time("09:30", "11:30")
    orb = win[(win.index.time >= dtime(9, 30)) & (win.index.time <= dtime(9, 45))]
    sig = win[(win.index.time > dtime(9, 45)) & (win.index.time <= dtime(10, 45))]
    if len(orb) < 3 or sig.empty:
        return []
    lo = float(orb["low"].min())
    hi = float(orb["high"].max())
    rng = hi - lo
    if rng <= 0:
        return []
    out = []
    for ts, bar in sig.iterrows():
        close = float(bar["close"])
        if close < lo:
            entry = close
            stop = hi
            dist = stop - entry
            if dist <= 0 or dist / entry > 0.02:
                return []
            target = entry - STRESS_ORB_RR * dist
            fwd = win[(win.index > ts) & (win.index.time <= dtime(11, 30))]
            if fwd.empty:
                return []
            ex, reason, xt = first_exit("SHORT", fwd, stop, target)
            out.append(dict(strategy="stress_orb_short", direction="SHORT", entry=entry, exit=ex,
                            stop=stop, target=target, entry_time=ts, exit_time=xt,
                            reason=reason))
            break
        if close > hi:
            entry = close
            stop = lo
            dist = entry - stop
            if dist <= 0 or dist / entry > 0.02:
                return []
            target = entry + STRESS_ORB_RR * dist
            fwd = win[(win.index > ts) & (win.index.time <= dtime(11, 30))]
            if fwd.empty:
                return []
            ex, reason, xt = first_exit("LONG", fwd, stop, target)
            out.append(dict(strategy="stress_orb_bidir", direction="LONG", entry=entry, exit=ex,
                            stop=stop, target=target, entry_time=ts, exit_time=xt,
                            reason=reason))
            break
    return out


def calm_vwap_fade(day: pd.DataFrame) -> list[dict]:
    win = day.between_time("10:30", "15:30")
    pre = day.between_time("09:30", "10:30")
    if win.empty or len(pre) < 10:
        return []
    morning_range = float(pre["high"].max() - pre["low"].min())
    if morning_range <= 0:
        return []
    out = []
    for ts, bar in win.iterrows():
        hist = day[(day.index >= day.index[0]) & (day.index <= ts)]
        vw = vwap(hist)
        close = float(bar["close"])
        dist = close - vw
        threshold = CALM_FADE_THRESHOLD * morning_range
        if abs(dist) < threshold:
            continue
        if dist > 0:
            direction = "SHORT"
            entry = close
            stop = entry + CALM_FADE_STOP * morning_range
            target = vw
        else:
            direction = "LONG"
            entry = close
            stop = entry - CALM_FADE_STOP * morning_range
            target = vw
        fwd = day[(day.index > ts) & (day.index.time <= dtime(15, 30))]
        if fwd.empty:
            return []
        ex, reason, xt = first_exit(direction, fwd, stop, target)
        out.append(dict(strategy="calm_vwap_fade", direction=direction, entry=entry, exit=ex,
                        stop=stop, target=target, entry_time=ts, exit_time=xt,
                        reason=reason))
        break
    return out


def calm_gap_fill(day: pd.DataFrame) -> list[dict]:
    rth = day.between_time("09:30", "13:30")
    if len(rth) < 20:
        return []
    prior = day[day.index < rth.index[0]]
    if prior.empty:
        return []
    prev_close = float(prior.iloc[-1]["close"])
    open_px = float(rth.iloc[0]["open"])
    gap = (open_px - prev_close) / prev_close
    if abs(gap) < 0.0025 or abs(gap) > 0.01:
        return []
    at = rth[rth.index.time == dtime(10, 30)]
    if at.empty:
        return []
    entry = float(at.iloc[-1]["close"])
    pre = rth[rth.index <= at.index[-1]]
    rng = float(pre["high"].max() - pre["low"].min())
    if rng <= 0:
        return []
    if gap < 0:
        direction = "LONG"
        target = prev_close
        stop = float(pre["low"].min()) - 0.25 * rng
        if entry >= target or entry <= stop:
            return []
    else:
        direction = "SHORT"
        target = prev_close
        stop = float(pre["high"].max()) + 0.25 * rng
        if entry <= target or entry >= stop:
            return []
    fwd = rth[(rth.index > at.index[-1]) & (rth.index.time <= dtime(13, 30))]
    if fwd.empty:
        return []
    ex, reason, xt = first_exit(direction, fwd, stop, target)
    return [dict(strategy="calm_gap_fill", direction=direction, entry=entry, exit=ex,
                 stop=stop, target=target, entry_time=at.index[-1], exit_time=xt,
                 reason=reason)]


def summarize(df: pd.DataFrame) -> None:
    if df.empty:
        print("no trades")
        return
    gross_win = df.loc[df.pnl > 0, "pnl"].sum()
    gross_loss = -df.loc[df.pnl < 0, "pnl"].sum()
    pf = gross_win / gross_loss if gross_loss else math.inf
    print(f"ALL n={len(df)} pnl=${df.pnl.sum():,.0f} pf={pf:.2f} exp=${df.pnl.mean():.2f}")
    for strat, s in df.groupby("strategy"):
        gw = s.loc[s.pnl > 0, "pnl"].sum()
        gl = -s.loc[s.pnl < 0, "pnl"].sum()
        spf = gw / gl if gl else math.inf
        print(f"{strat:<18} n={len(s):4d} pnl=${s.pnl.sum():>9,.0f} pf={spf:>5.2f} exp=${s.pnl.mean():>7.2f}")
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
    ap.add_argument("--out", default="scratch/regime_strategy_excavation.csv")
    ap.add_argument("--stress-rr", type=float, default=2.0)
    ap.add_argument("--stress-orb-rr", type=float, default=1.5)
    ap.add_argument("--calm-fade-threshold", type=float, default=0.35)
    ap.add_argument("--calm-fade-stop", type=float, default=0.35)
    args = ap.parse_args()

    global STRESS_RR, STRESS_ORB_RR, CALM_FADE_THRESHOLD, CALM_FADE_STOP
    STRESS_RR = args.stress_rr
    STRESS_ORB_RR = args.stress_orb_rr
    CALM_FADE_THRESHOLD = args.calm_fade_threshold
    CALM_FADE_STOP = args.calm_fade_stop

    bench = benchmark_daily(args.regime_csv)
    labels = label_regimes(bench, args.hmm_train_end, 3, args.hmm_fit_end)
    costs = costs_for_basket(slippage_ticks=2)
    rows = []
    for inst, contract in BASKET.items():
        path = Path(args.data_dir) / data_filename(contract)
        df = load_parquet(str(path))
        df = df[(df.index >= pd.Timestamp(args.start).tz_localize(df.index.tz)) &
                (df.index <= pd.Timestamp(args.end).tz_localize(df.index.tz))]
        cost = costs[inst].round_turn_cost()
        for day_ts, day in df.groupby(df.index.normalize()):
            day_key = pd.Timestamp(day_ts).tz_localize(None).normalize()
            regime = labels.get(day_key)
            if regime == "Stress":
                candidates = stress_mid(day) + stress_orb(day)
            elif regime == "Calm":
                candidates = calm_vwap_fade(day) + calm_gap_fill(day)
            else:
                continue
            for tr in candidates:
                xt = tr["exit_time"]
                bar = day.loc[xt]
                rows.append({
                    **tr,
                    "inst": inst,
                    "day": day_key.date().isoformat(),
                    "year": day_key.year,
                    "regime": regime,
                    "pnl": pnl(tr["direction"], tr["entry"], tr["exit"], contract.point_value, cost),
                    "bar_low": float(bar["low"]),
                    "bar_high": float(bar["high"]),
                })
    out = pd.DataFrame(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"wrote {args.out} rows={len(out)}")
    summarize(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
