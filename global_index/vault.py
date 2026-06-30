"""
global_index/vault.py — Gate 5 one-shot vault for a global index (NKD)
======================================================================
Final fragility test: frozen param, the UNTOUCHED 2023-2024 region, run ONCE.
The WFO region (2019-2022) may flatter (Abenomics/COVID-recovery/2022 yen rally);
the vault is data the engine never saw during param selection. If Calmar holds
with frozen param here, the edge is robust; if it collapses, the WFO Calmar was
a regime artifact.

ONE-SHOT DISCIPLINE: the vault is sacred. Run it once with the param you
pre-committed from WFO — never tune against vault output. The
--i-understand-one-shot flag is a deliberate speed bump.

Reuses the EXACT validated engine + tz-convert + lookahead-safe regime, identical
to wfo.py. Default regime-mode = agnostic (it beat gated OOS in WFO for NKD).

    python -m global_index.vault --parquet global_index/data/NKD_continuous_1m_8y.parquet \
        --instrument MNKD --tz Asia/Tokyo --regime-mode agnostic \
        --ema-period 10 --mult 2.5 --vault-start 2023-01-01 --i-understand-one-shot
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from global_index._core import load_parquet, FuturesCost
    from global_index import specs
    from global_index.regime import load_spy_regime, RegimeLabels
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from global_index._core import load_parquet, FuturesCost
    from global_index import specs
    from global_index.regime import load_spy_regime, RegimeLabels


class AllNormal:
    def get(self, _d, default=None):
        return "Normal"


def metrics(trades):
    if not trades:
        return dict(n=0, pnl=0.0, calmar=0.0, pf=0.0, maxdd=0.0)
    df = pd.DataFrame([(pd.Timestamp(r["day"]), r["pnl"]) for r in trades], columns=["day", "pnl"])
    daily = df.groupby("day")["pnl"].sum().sort_index()
    eq = daily.cumsum(); dd = float((eq.cummax() - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    w = daily[daily > 0].sum(); l = -daily[daily < 0].sum()
    return dict(n=len(df), pnl=float(df["pnl"].sum()),
                calmar=float((daily.sum()/span)/dd) if dd > 1e-9 else float("inf"),
                pf=float(w/l) if l > 1e-9 else float("inf"), maxdd=dd)


def by_year(trades):
    y = {}
    for t in trades:
        yr = pd.Timestamp(t["day"]).year
        y[yr] = y.get(yr, 0.0) + t["pnl"]
    return dict(sorted(y.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--instrument", default="MNKD", choices=list(specs.SPECS.keys()))
    ap.add_argument("--tz", default="Asia/Tokyo")
    ap.add_argument("--regime-mode", choices=["gated", "agnostic"], default="agnostic")
    ap.add_argument("--regime-csv")
    ap.add_argument("--regime-lag", type=int, default=1)
    ap.add_argument("--hmm-fit-end", default="2022-12-31")
    ap.add_argument("--ema-period", type=int, default=10)
    ap.add_argument("--mult", type=float, default=2.5)
    ap.add_argument("--max-hold-days", type=int, default=5)
    ap.add_argument("--vault-start", default="2023-01-01")
    ap.add_argument("--slippage-ticks", type=float, default=1.0)
    ap.add_argument("--i-understand-one-shot", action="store_true",
                    help="required: vault is sacred, run once with pre-committed param")
    a = ap.parse_args()

    if not a.i_understand_one_shot:
        ap.error("vault is one-shot. Pass --i-understand-one-shot once you've committed "
                 "the param from WFO. Do NOT tune against vault output.")

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from futures._validated_core import backtest_swing_tf

    c = specs.SPECS[a.instrument]
    vault_start = pd.Timestamp(a.vault_start)

    if a.regime_mode == "gated":
        if not a.regime_csv:
            ap.error("--regime-mode gated requires --regime-csv")
        # fit HMM only on pre-vault SPY (never learn from vault era), then label all
        spy = load_spy_regime(a.regime_csv, "2018-01-01", 3, a.hmm_fit_end)
        labels = RegimeLabels(spy, lag_days=a.regime_lag)
    else:
        labels = AllNormal()

    df = load_parquet(a.parquet)
    df.index = df.index.tz_convert(a.tz)
    df = df[df.index >= vault_start.tz_localize(a.tz)]   # VAULT region only (untouched)

    cost1 = FuturesCost(point_value=c.point_value, tick=c.tick,
                        commission_rt=c.commission_rt, slippage_ticks_per_side=a.slippage_ticks)
    cost2 = cost1.stressed(2.0)

    print(f"\n{'='*68}\nNKD GATE-5 VAULT (one-shot) | {a.instrument} | {a.regime_mode} | tz {a.tz}")
    print(f"FROZEN param ema={a.ema_period} mult={a.mult} hold={a.max_hold_days}d "
          f"| vault ≥ {vault_start.date()}\n{'='*68}")
    print(f"vault data {df.index[0].date()} → {df.index[-1].date()}  ({len(df):,} bars)\n")

    tr1 = backtest_swing_tf(df, labels, cost1, ema_period=a.ema_period,
                            chandelier_atr_mult=a.mult, max_hold_days=a.max_hold_days, gap_fill=True)
    tr2 = backtest_swing_tf(df, labels, cost2, ema_period=a.ema_period,
                            chandelier_atr_mult=a.mult, max_hold_days=a.max_hold_days, gap_fill=True)
    m1, m2 = metrics(tr1), metrics(tr2)

    print(f"{'':12}{'n':>5}{'PF':>7}{'net$':>11}{'maxDD$':>10}{'Calmar':>9}")
    print("-" * 54)
    print(f"{'1× cost':12}{m1['n']:>5}{m1['pf']:>7.2f}{m1['pnl']:>11,.0f}{m1['maxdd']:>10,.0f}{m1['calmar']:>9.2f}")
    print(f"{'2× cost':12}{m2['n']:>5}{m2['pf']:>7.2f}{m2['pnl']:>11,.0f}{m2['maxdd']:>10,.0f}{m2['calmar']:>9.2f}")

    yb = by_year(tr1)
    print("\nyear-by-year net$ (both vault years must be positive — like Rổ 4 vault):")
    print("  " + "  ".join(f"{y}:{v:,.0f}" for y, v in yb.items()))

    print("-" * 68)
    allpos = all(v > 0 for v in yb.values()) and len(yb) >= 2
    p = m1["calmar"] >= 1.0 and m2["pnl"] > 0 and allpos
    print(f"VERDICT: {'PASS' if p else 'FAIL'} — vault Calmar {m1['calmar']:.2f} (≥1.0?"
          f"{'Y' if m1['calmar']>=1 else 'N'}), 2× net ${m2['pnl']:,.0f}, "
          f"all years positive?{'Y' if allpos else 'N'}")
    print(f"  Rổ-4 vault anchor was Calmar 3.21. NKD here = {m1['calmar']:.2f}. "
          f"Hold high → robust; collapse → WFO region was flattered.\n")


if __name__ == "__main__":
    main()
