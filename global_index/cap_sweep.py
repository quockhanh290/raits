"""
global_index/cap_sweep.py — choose the Rổ-4 gross exposure cap by data, not taste
=================================================================================
risk_diagnostic showed real 4-long gross ≈ 6.7% but the cap is 4% → ~2 of 4 index
admitted. "Full basket" means raising the cap. This sweeps the Rổ-4 gross cap and
shows, at each level, the deploy MaxDD% / return% / Calmar / reject% — so the
choice is bound by the hard 15% DD cap (and 10% target), not by preference.

Computes engine trades ONCE (slow), then replays each cap (fast). The sizer
re-sizes per cap (higher cap → higher MaxDD → sizer may cut contracts), so the
table reflects the real cap↔size interaction.

Read: pick the highest cap whose MaxDD% stays under target 10% — that's the most
return you can take without crowding the hard cap. If full-basket (≈7%) pushes
MaxDD past ~10-12%, a tighter cap is the smarter point despite lower net.

SLIPPAGE NOTE: cap_sweep defaults to 1-tick slippage (not the canonical 2-tick).
Rationale: the purpose is relative ranking across caps, and cap rank is stable across
slippage levels. Net$ in the output table (e.g. ~$58,602 at 5% gross cap, fit_C) is
therefore HIGHER than the canonical baseline ($52,936 at 2-tick). Do NOT read those
as production P&L — they are comparison-only. Canonical numbers come from deploy_sim
with --slippage-ticks 2.

VERIFIED: cap_sweep fit_C (2024-12-31) confirms 5% gross / 4.4% net as optimal cap
(highest Calmar under 10% DD target). This matches DEFAULT_CLUSTERS in
net_exposure_multi.py (roska4_swing max_gross_pct=0.05, max_net_pct=0.044).

    python -m global_index.cap_sweep --data-dir data\\cache\\futures \
        --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet --regime-csv spy_daily.csv
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
from global_index import specs as gi_specs
from global_index.regime import RegimeLabels
from global_index.net_exposure_multi import MultiClusterGuard, ClusterBudget, Position
from global_index.deploy_sim import replay, size_combined, metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--nkd-parquet", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--include-stress", action="store_true", default=True)
    ap.add_argument("--nkd-instrument", default="MNKD")
    ap.add_argument("--nkd-ema", type=int, default=10)
    ap.add_argument("--nkd-mult", type=float, default=2.5)
    ap.add_argument("--roska4-mult", type=float, default=2.5)
    ap.add_argument("--account", type=float, default=50_000.0)
    ap.add_argument("--slippage-ticks", type=float, default=1.0)
    ap.add_argument("--caps", default="0.04,0.05,0.06,0.07,0.08",
                    help="Rổ-4 gross caps to sweep (net cap = gross × 0.875)")
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end", default="2024-12-31")
    a = ap.parse_args()

    from futures._validated_core import (load_parquet, benchmark_daily, label_regimes,
                                         backtest_swing_tf, daily_atr_series)
    from futures.basket import BASKET, data_filename
    from futures.swing_tf import SwingTFEngine, costs_for_basket
    try:
        from futures.circuit_breaker import CircuitBreaker
    except Exception:
        CircuitBreaker = None

    # ── compute trades ONCE ─────────────────────────────────────────────────
    dfs = {n: load_parquet(str(Path(a.data_dir) / data_filename(c))) for n, c in BASKET.items()}
    atr = {n: daily_atr_series(df) for n, df in dfs.items()}
    pv = {n: c.point_value for n, c in BASKET.items()}
    bench = benchmark_daily(a.regime_csv)
    labels = label_regimes(bench, a.hmm_train_end, 3, a.hmm_fit_end)
    costs = costs_for_basket(slippage_ticks=a.slippage_ticks)
    swing = SwingTFEngine().backtest_basket(dfs, labels, costs)
    stress = None
    if a.include_stress:
        from futures.stress_mid import StressMidEngine
        stress = StressMidEngine().backtest_basket(dfs, labels, costs)

    c = gi_specs.SPECS[a.nkd_instrument]
    spy = pd.Series(label_regimes(benchmark_daily(a.regime_csv), a.hmm_train_end, 3, a.hmm_fit_end))
    idx = pd.DatetimeIndex(spy.index); spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    nlab = RegimeLabels(spy.sort_index(), lag_days=1)
    ndf = gi_load(a.nkd_parquet); ndf.index = ndf.index.tz_convert(c.session_tz)
    natr = daily_atr_series(ndf)
    ncost = GIFC(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt,
                 slippage_ticks_per_side=a.slippage_ticks)
    nkd = backtest_swing_tf(ndf, nlab, ncost, ema_period=a.nkd_ema,
                            chandelier_atr_mult=a.nkd_mult, max_hold_days=5, gap_fill=True)

    def rrisk(atr_series, mult, point_value, entry_day, contracts):
        try:
            av = atr_series.asof(pd.Timestamp(entry_day))
        except Exception:
            av = np.nan
        if av is None or pd.isna(av):
            av = float(atr_series.median())
        return contracts * mult * float(av) * point_value

    base = []
    for inst, lst in swing.items():
        for t in lst:
            base.append(dict(inst=inst, cluster="roska4_swing", entry=pd.Timestamp(t["day"]),
                             exit=pd.Timestamp(t["exit_day"]), direction=t["direction"],
                             pnl1=t["pnl"], atr=atr[inst], mult=a.roska4_mult, pv=pv[inst]))
    if stress:
        for inst, lst in stress.items():
            for t in lst:
                base.append(dict(inst=inst, cluster="roska4_stress", entry=pd.Timestamp(t["day"]),
                                 exit=pd.Timestamp(t["exit_day"]), direction=t["direction"],
                                 pnl1=t["pnl"], atr=atr[inst], mult=a.roska4_mult, pv=pv[inst]))
    for t in nkd:
        ed = pd.Timestamp(t["day"]).tz_localize(None)
        xd = (pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed)
        base.append(dict(inst=a.nkd_instrument, cluster="global_nkd", entry=ed, exit=xd,
                         direction=t["direction"], pnl1=t["pnl"], atr=natr, mult=a.nkd_mult, pv=c.point_value))

    base_margin = sum(BASKET[n].est_margin for n in BASKET) + c.est_margin

    def build_guard(gross):
        cl = {
            "roska4_swing":  ClusterBudget("roska4_swing",  max_gross_pct=gross, max_net_pct=gross*0.875),
            "roska4_stress": ClusterBudget("roska4_stress", max_gross_pct=0.025, max_net_pct=None),
            "global_nkd":    ClusterBudget("global_nkd",    max_gross_pct=0.02,  max_net_pct=0.02),
        }
        return MultiClusterGuard(clusters=cl, account=a.account)

    def run_at(gross):
        # 1-micro MaxDD at this cap → sizer
        for t in base:
            t["risk_sized"] = rrisk(t["atr"], t["mult"], t["pv"], t["entry"], 1)
            t["pnl_sized"] = t["pnl1"]
        d1, _ = replay(base, a.account, build_guard(gross), {}, CircuitBreaker)
        m1 = metrics(d1)
        n_ct, _sz = size_combined(m1["maxdd"], base_margin, a.account)
        # replay at sized contracts
        cbi = {n: n_ct for n in BASKET}; cbi[a.nkd_instrument] = n_ct
        for t in base:
            t["risk_sized"] = rrisk(t["atr"], t["mult"], t["pv"], t["entry"], n_ct)
            t["pnl_sized"] = t["pnl1"] * n_ct
        ds, st = replay(base, a.account, build_guard(gross), cbi, CircuitBreaker)
        m = metrics(ds)
        total = sum(st["taken"].values()) + sum(st["rejected"].values())
        rej_pct = sum(st["rejected"].values()) / total if total else 0
        yrs = max((ds.index[-1] - ds.index[0]).days / 365.25, 0.1) if len(ds) else 1
        return dict(cap=gross, contracts=n_ct, net=m["pnl"], calmar=m["calmar"],
                    maxdd=m["maxdd"], maxdd_pct=m["maxdd"]/a.account,
                    ret_pct=m["pnl"]/a.account/yrs, rej_pct=rej_pct,
                    taken_swing=st["taken"]["roska4_swing"], rej_swing=st["rejected"]["roska4_swing"])

    caps = [float(x) for x in a.caps.split(",")]
    print(f"\n{'='*78}\nCAP SWEEP | Rổ 4 + STRESS + NKD | ${a.account:,.0f} | slippage {a.slippage_ticks:g}t")
    print(f"{'='*78}")
    print(f"{'gross':>6}{'net cap':>9}{'micros':>8}{'net$':>10}{'Calmar':>8}"
          f"{'MaxDD%':>8}{'ret%/yr':>9}{'reject%':>9}")
    print("-"*78)
    rows = [run_at(g) for g in caps]
    for r in rows:
        flag = "  ← >10% target" if r["maxdd_pct"] > 0.10 else ("  ← >15% HARD!" if r["maxdd_pct"] > 0.15 else "")
        print(f"{r['cap']:>6.1%}{r['cap']*0.875:>9.1%}{r['contracts']:>8}{r['net']:>10,.0f}"
              f"{r['calmar']:>8.2f}{r['maxdd_pct']:>8.1%}{r['ret_pct']:>9.1%}{r['rej_pct']:>9.0%}{flag}")
    print("-"*78)
    safe = [r for r in rows if r["maxdd_pct"] <= 0.10]
    if safe:
        best = max(safe, key=lambda r: r["calmar"])
        print(f"Under 10% target: best Calmar {best['calmar']:.2f} at gross cap {best['cap']:.0%} "
              f"({best['contracts']} micro, MaxDD {best['maxdd_pct']:.1%}, ret {best['ret_pct']:.1%}/yr)")
    else:
        print("No cap keeps MaxDD under 10% target — even tightest is too hot; reconsider sizing.")
    print("Pick the highest cap whose MaxDD% stays under your target. Higher net is not "
          "worth crowding the 15% hard cap.\n")


if __name__ == "__main__":
    main()
