"""
orb_futures/edge_test.py — Gate 2: does ORB have an edge on Rổ 4, and is it
                            uncorrelated with swing TF?
===========================================================================
Simplest honest ORB: opening range = first 15 min of RTH (9:31-9:45 ET, skip the
9:30 print). First bar to close beyond OR triggers entry at next bar open. Stop =
opposite OR side; target = 2R; else exit at session close. One entry/day/instrument.

No RVol/VWAP/fakeout filters yet — test the RAW breakout edge first. If raw has no
edge, filters won't save it; if it does, refine later (falsification-first).

Reports per-instrument + pooled edge (PF/WR/year-by-year/cost-stress) AND the
cross-stream correlation of ORB daily P&L vs swing-TF daily P&L — the diversification
verdict. Profitable but high-corr = doubles the bet, not diversification.

    python -m orb_futures.edge_test --data-dir data\\cache\\futures \
        --regime-csv spy_daily.csv [--or-min 15] [--allowed Calm,Normal] [--cost-mult 2]
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from futures._validated_core import (load_parquet, benchmark_daily, label_regimes,
                                     daily_atr_series, backtest_swing_tf)
from futures.cost import FuturesCost
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket


def orb_backtest(df, labels, cost, *, or_start="09:31", or_end="09:45",
                 mon_end="15:55", allowed=("Calm", "Normal"), atr=None,
                 min_atr_mult=0.5, max_atr_mult=5.0, target_rr=2.0):
    """Opening-range breakout, intraday exit. df index ET tz-aware, 1-min bars."""
    trades = []
    day_groups = df.groupby(df.index.normalize())
    for day_raw, d in day_groups:
        if d.empty:
            continue
        day = pd.Timestamp(day_raw).tz_localize(None).normalize()  # match swing TF key
        reg = labels.get(day)
        if reg not in allowed:
            continue
        orb = d.between_time(or_start, or_end)
        if len(orb) < 3:
            continue
        or_high = orb["high"].max(); or_low = orb["low"].min()
        or_range = or_high - or_low
        if atr is not None:
            av = atr.asof(day)
            if av and not pd.isna(av):
                if or_range < min_atr_mult * av or or_range > max_atr_mult * av:
                    continue
        mon = d.between_time("09:46", mon_end)
        if mon.empty:
            continue
        # first bar to close beyond OR
        entry = stop = target = direction = None
        bars = list(mon.itertuples())
        for i, b in enumerate(bars):
            if b.close > or_high:
                direction = "LONG"
            elif b.close < or_low:
                direction = "SHORT"
            else:
                continue
            # fill at next bar open
            if i + 1 >= len(bars):
                break
            entry = bars[i + 1].open
            if direction == "LONG":
                stop = or_low; risk = entry - stop
                if risk <= 0:
                    direction = None; continue
                target = entry + target_rr * risk
            else:
                stop = or_high; risk = stop - entry
                if risk <= 0:
                    direction = None; continue
                target = entry - target_rr * risk
            rest = bars[i + 1:]
            break
        if direction is None or entry is None:
            continue
        # walk to target/stop/EOD
        exit_px = bars[-1].close
        for b in rest:
            if direction == "LONG":
                if b.low <= stop:
                    exit_px = stop; break
                if b.high >= target:
                    exit_px = target; break
            else:
                if b.high >= stop:
                    exit_px = stop; break
                if b.low <= target:
                    exit_px = target; break
        gross = (exit_px - entry) if direction == "LONG" else (entry - exit_px)
        pnl = gross * cost.point_value - cost.round_turn_cost()
        trades.append(dict(day=day, direction=direction, pnl=pnl))
    return trades


def daily_series(trades):
    if not trades:
        return pd.Series(dtype=float)
    s = pd.DataFrame([(pd.Timestamp(t["day"]).normalize(), t["pnl"]) for t in trades],
                     columns=["d", "p"]).groupby("d")["p"].sum().sort_index()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None)
    return s


def metrics(trades):
    if not trades:
        return dict(n=0, pf=0.0, wr=0.0, net=0.0, maxdd=0.0, calmar=0.0)
    pnl = np.array([t["pnl"] for t in trades]); eq = pnl.cumsum()
    dd = float((np.maximum.accumulate(eq) - eq).max())
    w = pnl[pnl > 0].sum(); l = -pnl[pnl < 0].sum()
    s = daily_series(trades); span = max((s.index[-1]-s.index[0]).days/365.25, 0.1) if len(s) else 1
    return dict(n=len(pnl), pf=float(w/l) if l > 0 else float("inf"),
                wr=float((pnl > 0).mean()), net=float(pnl.sum()), maxdd=dd,
                calmar=float((pnl.sum()/span)/dd) if dd > 0 else float("inf"))


def by_year(trades):
    y = {}
    for t in trades:
        yr = pd.Timestamp(t["day"]).year; y[yr] = y.get(yr, 0.0) + t["pnl"]
    return dict(sorted(y.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--or-min", type=int, default=15, help="opening-range minutes")
    ap.add_argument("--allowed", default="Calm,Normal", help="ORB regimes (comma)")
    ap.add_argument("--cost-mult", type=float, default=1.0)
    ap.add_argument("--target-rr", type=float, default=2.0)
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end", default="2024-12-31")
    a = ap.parse_args()

    allowed = tuple(a.allowed.split(","))
    or_end = (pd.Timestamp("09:30") + pd.Timedelta(minutes=a.or_min)).strftime("%H:%M")
    bench = benchmark_daily(a.regime_csv)
    labels = label_regimes(bench, a.hmm_train_end, 3, a.hmm_fit_end)
    costs = costs_for_basket()

    print(f"\n{'='*72}\nORB EDGE TEST (Gate 2) | Rổ 4 | OR 9:31-{or_end} | regimes {allowed} | "
          f"cost×{a.cost_mult:g}\n{'='*72}")
    print(f"{'inst':<6}{'n':>6}{'PF':>7}{'WR':>7}{'net$':>10}{'maxDD$':>9}{'Calmar':>8}")
    print("-"*72)

    orb_daily_all = pd.Series(dtype=float)
    swing_daily_all = pd.Series(dtype=float)
    pooled_orb = []
    for n, c in BASKET.items():
        df = load_parquet(str(Path(a.data_dir) / data_filename(c)))
        atr = daily_atr_series(df)
        cost = costs[n] if a.cost_mult == 1 else costs[n].stressed(a.cost_mult)
        trs = orb_backtest(df, labels, cost, or_end=or_end, allowed=allowed,
                           atr=atr, target_rr=a.target_rr)
        pooled_orb += trs
        m = metrics(trs)
        pf = f"{m['pf']:.2f}" if np.isfinite(m['pf']) else "inf"
        cal = f"{m['calmar']:.2f}" if np.isfinite(m['calmar']) else "inf"
        print(f"{n:<6}{m['n']:>6}{pf:>7}{m['wr']*100:>6.0f}%{m['net']:>10,.0f}{m['maxdd']:>9,.0f}{cal:>8}")
        orb_daily_all = orb_daily_all.add(daily_series(trs), fill_value=0)
        # swing TF for same instrument (correlation reference) — Normal+Stress, validated engine
        sw = backtest_swing_tf(df, labels, cost, ema_period=30, chandelier_atr_mult=2.5,
                               max_hold_days=5, gap_fill=True)
        swing_daily_all = swing_daily_all.add(daily_series(sw), fill_value=0)

    print("-"*72)
    pm = metrics(pooled_orb)
    pf = f"{pm['pf']:.2f}" if np.isfinite(pm['pf']) else "inf"
    cal = f"{pm['calmar']:.2f}" if np.isfinite(pm['calmar']) else "inf"
    print(f"{'POOL':<6}{pm['n']:>6}{pf:>7}{pm['wr']*100:>6.0f}%{pm['net']:>10,.0f}{pm['maxdd']:>9,.0f}{cal:>8}")

    yb = by_year(pooled_orb)
    if yb:
        print("\nyear-by-year net$ (QQQ rule):")
        print("  " + "  ".join(f"{y}:{v:,.0f}" for y, v in yb.items()))

    # diversification verdict
    j = pd.DataFrame({"orb": orb_daily_all, "swing": swing_daily_all}).fillna(0.0)
    corr = float(j["orb"].corr(j["swing"])) if len(j) > 2 else float("nan")
    print("\n" + "-"*72)
    print(f"cross-stream corr (ORB vs swing TF daily P&L): {corr:+.3f}")
    print("-"*72)
    edge_ok = pm["pf"] > 1.0 and (not yb or all(v > 0 for v in yb.values()))
    div_ok = abs(corr) < 0.3
    print(f"EDGE: {'alive' if edge_ok else 'WEAK/none'} (PF {pf}, year-by-year "
          f"{'all+' if yb and all(v>0 for v in yb.values()) else 'mixed'})")
    print(f"DIVERSIFY: {'YES — low corr' if div_ok else 'NO — too correlated with swing TF'}")
    if edge_ok and div_ok:
        print("→ both pass → proceed to WFO. A real second uncorrelated edge.")
    elif edge_ok and not div_ok:
        print("→ edge but correlated → doubles the swing bet, NOT diversification. Reconsider.")
    else:
        print("→ no edge → ORB breakout NO-GO on Rổ 4. Try ORB fade / gap-fill instead.")
    print()


if __name__ == "__main__":
    main()
