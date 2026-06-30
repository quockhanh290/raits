"""
global_index/combined.py — DEPLOY-DECISION gate: does NKD improve Rổ 4?
=======================================================================
Standalone NKD PF/Calmar says nothing about whether adding it HELPS the deployed
portfolio. NKD is equity (corr ~0.6-0.85 with Rổ 4), so "more return" may just be
"more correlated drawdown". This pools Rổ 4 + NKD into one equity curve and asks
the only question that matters for deployment:

  combined Calmar  >  Rổ-4-alone Calmar  ?

If yes, NKD's return arrives at different TIMES than Rổ 4's losses (the JST power
hour leads the US power hour by ~13h) → timing-smoothing beats correlated DD →
worth deploying. If no, NKD only piles on correlated risk → just size Rổ 4 up.

Also reports cross-stream correlation (Rổ-4 daily P&L vs NKD daily P&L) — the
honest diversification number (correlation of RETURN STREAMS, not of the assets).

Reuses the validated Rổ-4 engines (futures.swing_tf / stress_mid) and the
validated power-hour engine for NKD (tz-Tokyo). NKD config = gated, ema=10/mult=2.5
(WFO+vault winner under realistic cost).

    python -m global_index.combined --data-dir data\\cache\\futures \
        --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet \
        --regime-csv spy_daily.csv [--include-stress] [--start 2018-01-01] [--end 2024-12-31]
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
    from global_index import specs as gi_specs
    from global_index.regime import RegimeLabels
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
    from global_index import specs as gi_specs
    from global_index.regime import RegimeLabels


def metrics(daily: pd.Series) -> dict:
    if daily.empty:
        return dict(pnl=0.0, pf=0.0, calmar=0.0, sharpe=0.0, maxdd=0.0)
    eq = daily.cumsum(); dd = float((eq.cummax() - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    ann = daily.sum() / span
    w = daily[daily > 0].sum(); l = -daily[daily < 0].sum()
    return dict(pnl=float(daily.sum()), pf=float(w/l) if l > 1e-9 else float("inf"),
                calmar=float(ann/dd) if dd > 1e-9 else float("inf"),
                sharpe=float(daily.mean()/daily.std()*np.sqrt(252)) if daily.std() > 1e-9 else 0.0,
                maxdd=dd)


def trades_to_daily(trades) -> pd.Series:
    rows = [(pd.Timestamp(r["day"]).normalize(), r["pnl"]) for r in trades]
    if not rows:
        return pd.Series(dtype=float)
    s = pd.DataFrame(rows, columns=["day", "pnl"]).groupby("day")["pnl"].sum().sort_index()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None)   # calendar date, tz-naive
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, help="Rổ-4 parquet dir (ES/NQ/YM/RTY)")
    ap.add_argument("--nkd-parquet", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--include-stress", action="store_true", help="add STRESS_MID sleeve to Rổ 4")
    ap.add_argument("--nkd-instrument", default="MNKD", choices=list(gi_specs.SPECS.keys()))
    ap.add_argument("--nkd-tz", default="Asia/Tokyo")
    ap.add_argument("--nkd-ema", type=int, default=10)
    ap.add_argument("--nkd-mult", type=float, default=2.5)
    ap.add_argument("--nkd-regime-lag", type=int, default=1)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end", default="2022-12-31")
    ap.add_argument("--slippage-ticks", type=float, default=1.0)
    a = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from futures._validated_core import load_parquet, benchmark_daily, label_regimes, backtest_swing_tf
    from futures.basket import BASKET, data_filename
    from futures.swing_tf import SwingTFEngine, costs_for_basket

    def clip(df):
        if a.start: df = df[df.index >= pd.Timestamp(a.start).tz_localize(df.index.tz)]
        if a.end:   df = df[df.index <= pd.Timestamp(a.end).tz_localize(df.index.tz)]
        return df

    # ── Rổ 4 (validated engine, ET, SPY-gated) ──────────────────────────────
    dfs = {n: clip(load_parquet(str(Path(a.data_dir) / data_filename(c)))) for n, c in BASKET.items()}
    bench = benchmark_daily(a.regime_csv)
    if a.start: bench = bench[bench.index >= pd.Timestamp(a.start)]
    if a.end:   bench = bench[bench.index <= pd.Timestamp(a.end)]
    labels = label_regimes(bench, a.hmm_train_end, 3, a.hmm_fit_end)
    costs = costs_for_basket(slippage_ticks=a.slippage_ticks)

    tf = SwingTFEngine().backtest_basket(dfs, labels, costs)
    r4 = pd.Series(dtype=float)
    for trs in tf.values():
        r4 = r4.add(trades_to_daily(trs), fill_value=0)
    if a.include_stress:
        from futures.stress_mid import StressMidEngine
        sm = StressMidEngine().backtest_basket(dfs, labels, costs)
        for trs in sm.values():
            r4 = r4.add(trades_to_daily(trs), fill_value=0)
    r4 = r4.sort_index()

    # ── NKD (validated power-hour engine, tz-Tokyo, SPY-gated lookahead-safe) ─
    c = gi_specs.SPECS[a.nkd_instrument]
    spy_reg = pd.Series(label_regimes(benchmark_daily(a.regime_csv), a.hmm_train_end, 3, a.hmm_fit_end))
    idx = pd.DatetimeIndex(spy_reg.index)
    spy_reg.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    nkd_labels = RegimeLabels(spy_reg.sort_index(), lag_days=a.nkd_regime_lag)
    ndf = gi_load(a.nkd_parquet); ndf.index = ndf.index.tz_convert(a.nkd_tz); ndf = clip(ndf)
    ncost = GIFC(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt,
                 slippage_ticks_per_side=a.slippage_ticks)
    nkd_trades = backtest_swing_tf(ndf, nkd_labels, ncost, ema_period=a.nkd_ema,
                                   chandelier_atr_mult=a.nkd_mult, max_hold_days=5, gap_fill=True)
    nkd = trades_to_daily(nkd_trades)

    combined = r4.add(nkd, fill_value=0).sort_index()

    print(f"\n{'='*70}\nDEPLOY GATE: Rổ 4 {'+ STRESS_MID ' if a.include_stress else ''}+ NKD ({a.nkd_instrument})")
    print(f"{'='*70}")
    span = "all data" if not (a.start or a.end) else f"{a.start or 'start'} → {a.end or 'end'}"
    print(f"Span: {span} | NKD gated ema={a.nkd_ema} mult={a.nkd_mult}\n")

    for label, d in (("Rổ 4 alone", r4), ("NKD alone", nkd), ("COMBINED", combined)):
        m = metrics(d)
        print(f"  {label:<12} net ${m['pnl']:>9,.0f} | PF {m['pf']:>4.2f} | "
              f"MaxDD ${m['maxdd']:>7,.0f} | Calmar {m['calmar']:>5.2f} | Sharpe {m['sharpe']:>5.2f}")

    # cross-stream correlation (the honest diversification number)
    j = pd.DataFrame({"r4": r4, "nkd": nkd}).fillna(0.0)
    corr = float(j["r4"].corr(j["nkd"])) if len(j) > 2 else float("nan")

    print(f"\ncross-stream daily-P&L correlation (Rổ 4 vs NKD): {corr:+.3f}")
    print("  (low/negative = returns arrive at different times = real smoothing; "
          "high = correlated DD)")

    print("\nper-year net$ (watch for shared drawdown years — COVID 2020, bear 2022):")
    yrs = sorted(set(combined.index.year))
    print(f"  {'year':<6}{'Rổ 4':>11}{'NKD':>10}{'combined':>11}")
    for y in yrs:
        t = r4[r4.index.year == y].sum() if len(r4) else 0
        s = nkd[nkd.index.year == y].sum() if len(nkd) else 0
        print(f"  {y:<6}{t:>11,.0f}{s:>10,.0f}{t+s:>11,.0f}")

    cm, rm = metrics(combined), metrics(r4)
    print("\n" + "-"*70)
    better = cm["calmar"] > rm["calmar"]
    print(f"Combined Calmar {cm['calmar']:.2f} vs Rổ-4-alone {rm['calmar']:.2f} | "
          f"MaxDD ${cm['maxdd']:,.0f} vs ${rm['maxdd']:,.0f}")
    if better:
        print("VERDICT: NKD IMPROVES risk-adjusted return (combined Calmar > Rổ-4 alone) → "
              "timing-smoothing beats correlated DD → worth deploying alongside Rổ 4.")
    else:
        print("VERDICT: NKD does NOT raise risk-adjusted return (combined Calmar ≤ Rổ-4 alone) → "
              "mostly correlated DD; adding return but not improving risk. Reconsider vs just "
              "sizing Rổ 4 up.")
    print("-"*70 + "\n")


if __name__ == "__main__":
    main()
