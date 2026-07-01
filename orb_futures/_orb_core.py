"""
orb_futures/_orb_core.py — shared helpers for the ORB-family edge tests
=======================================================================
Each strategy (breakout / fade / gap-fill / overnight) is a NEW unvalidated edge
and runs its own Gate-2 test. They share: opening-range computation, walk-to-exit,
metrics, the swing-TF reference stream (for the correlation = diversification test),
and the verdict printer. Per-strategy loops live in their own files (signal logic
differs); this module is the common machinery only.

DISCIPLINE: testing several strategies multiplies the chance one "passes" by luck.
Run them SEQUENTIALLY (stop at the first that passes) or tighten thresholds. Do not
cherry-pick the best PF across all of them — that is p-hacking, not an edge.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from futures._validated_core import (load_parquet, benchmark_daily, label_regimes,
                                     daily_atr_series, backtest_swing_tf)
from futures.basket import BASKET, data_filename
from futures.cost import FuturesCost
from futures.swing_tf import costs_for_basket


def opening_range(d, or_start, or_end, atr=None, day=None,
                  min_atr_mult=0.5, max_atr_mult=5.0):
    """Return (or_high, or_low, valid). valid=False if window thin or range
    outside [min,max]×ATR. `d` is one day's 1-min bars (ET tz-aware)."""
    orb = d.between_time(or_start, or_end)
    if len(orb) < 3:
        return None, None, False
    or_high = float(orb["high"].max()); or_low = float(orb["low"].min())
    if atr is not None and day is not None:
        av = atr.asof(day)
        if av and not pd.isna(av):
            r = or_high - or_low
            if r < min_atr_mult * av or r > max_atr_mult * av:
                return or_high, or_low, False
    return or_high, or_low, True


def walk_exit(bars_after, entry, stop, target, direction):
    """Walk bars after entry; return exit price at first stop/target hit, else
    last bar close (session/EOD exit). bars_after = list of namedtuples."""
    if not bars_after:
        return entry
    exit_px = bars_after[-1].close
    for b in bars_after:
        if direction == "LONG":
            if b.low <= stop:
                return stop
            if b.high >= target:
                return target
        else:
            if b.high >= stop:
                return stop
            if b.low <= target:
                return target
    return exit_px


def metrics(trades):
    if not trades:
        return dict(n=0, pf=0.0, wr=0.0, net=0.0, maxdd=0.0, calmar=0.0)
    pnl = np.array([t["pnl"] for t in trades]); eq = pnl.cumsum()
    dd = float((np.maximum.accumulate(eq) - eq).max())
    w = pnl[pnl > 0].sum(); l = -pnl[pnl < 0].sum()
    s = daily_series(trades)
    span = max((s.index[-1] - s.index[0]).days / 365.25, 0.1) if len(s) else 1
    return dict(n=len(pnl), pf=float(w / l) if l > 0 else float("inf"),
                wr=float((pnl > 0).mean()), net=float(pnl.sum()), maxdd=dd,
                calmar=float((pnl.sum() / span) / dd) if dd > 0 else float("inf"))


def daily_series(trades):
    if not trades:
        return pd.Series(dtype=float)
    s = pd.DataFrame([(pd.Timestamp(t["day"]).normalize(), t["pnl"]) for t in trades],
                     columns=["d", "p"]).groupby("d")["p"].sum().sort_index()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None)
    return s


def by_year(trades):
    y = {}
    for t in trades:
        yr = pd.Timestamp(t["day"]).year
        y[yr] = y.get(yr, 0.0) + t["pnl"]
    return dict(sorted(y.items()))


def swing_ref_daily(df, labels, cost):
    """Validated swing-TF daily P&L for the same instrument (correlation ref)."""
    sw = backtest_swing_tf(df, labels, cost, ema_period=30, chandelier_atr_mult=2.5,
                           max_hold_days=5, gap_fill=True)
    return daily_series(sw)


def setup(data_dir, regime_csv, hmm_train_end="2018-01-01", hmm_fit_end="2022-12-31",
          cost_mult=1.0):
    """Common load: dfs, atrs, labels, costs. Returns dict."""
    bench = benchmark_daily(regime_csv)
    labels = label_regimes(bench, hmm_train_end, 3, hmm_fit_end)
    base = costs_for_basket()
    dfs, atrs, costs = {}, {}, {}
    for n, c in BASKET.items():
        df = load_parquet(str(Path(data_dir) / data_filename(c)))
        dfs[n] = df
        atrs[n] = daily_atr_series(df)
        costs[n] = base[n] if cost_mult == 1 else base[n].stressed(cost_mult)
    return dict(dfs=dfs, atrs=atrs, labels=labels, costs=costs)


def print_verdict(name, pooled_trades, orb_daily_all, swing_daily_all,
                  pf_min=1.0, corr_max=0.3):
    """Shared edge + diversification verdict. Thresholds default to the loose
    single-test bar; tighten (pf_min/corr_max) when running several strategies."""
    pm = metrics(pooled_trades)
    yb = by_year(pooled_trades)
    pf = f"{pm['pf']:.2f}" if np.isfinite(pm['pf']) else "inf"
    cal = f"{pm['calmar']:.2f}" if np.isfinite(pm['calmar']) else "inf"
    print("-" * 72)
    print(f"{'POOL':<6}{pm['n']:>6}{pf:>7}{pm['wr']*100:>6.0f}%{pm['net']:>10,.0f}"
          f"{pm['maxdd']:>9,.0f}{cal:>8}")
    if yb:
        print("\nyear-by-year net$ (QQQ rule):")
        print("  " + "  ".join(f"{y}:{v:,.0f}" for y, v in yb.items()))
    j = pd.DataFrame({"s": orb_daily_all, "sw": swing_daily_all}).fillna(0.0)
    corr = float(j["s"].corr(j["sw"])) if len(j) > 2 else float("nan")
    print("\n" + "-" * 72)
    print(f"cross-stream corr ({name} vs swing TF daily P&L): {corr:+.3f}  "
          f"(threshold |corr|<{corr_max})")
    print("-" * 72)
    all_pos = bool(yb) and all(v > 0 for v in yb.values())
    edge_ok = pm["pf"] > pf_min and all_pos
    div_ok = abs(corr) < corr_max
    print(f"EDGE: {'alive' if edge_ok else 'WEAK/none'} "
          f"(PF {pf} vs >{pf_min}, year-by-year {'all+' if all_pos else 'mixed'})")
    print(f"DIVERSIFY: {'YES — low corr' if div_ok else 'NO — too correlated with swing TF'}")
    if edge_ok and div_ok:
        print(f"→ {name}: both pass → candidate for WFO. Real uncorrelated edge.")
    elif edge_ok and not div_ok:
        print(f"→ {name}: edge but correlated → doubles the swing bet, NOT diversification.")
    else:
        print(f"→ {name}: no edge → NO-GO. Move to the next variant.")
    print()
    return dict(edge_ok=edge_ok, div_ok=div_ok, corr=corr, **pm)
