"""
global_index/stress_mid_trust.py — Trust audit: STRESS_MID 2022 P&L re-measurement
=====================================================================================
CLAIM (source: _archive/docs/RAITS_MES_Spike_Results_v3.md, no committed script):
  swing TF 2022  = −$232
  STRESS_MID 2022 = +$5,296
  Narrative: "bear year — swing gãy, STRESS_MID cứu"

That report used: fit_A labels (hmm_fit_end=2022-12-31), $500-stub risk$, NO NKD.
This script re-measures using CURRENT pipeline:
  - fit_C labels (hmm_fit_end=2024-12-31)
  - Real ATR-based risk$ (same as deploy_sim)
  - 2-tick slippage

TWO measurements:
  A. Standalone (no cap) per-year P&L — matches original report methodology
  B. Marginal contribution (with cap): full_system_with_stress − full_system_without_stress

Run from D:\\raits:
    python global_index\\stress_mid_trust.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

from futures._validated_core import (load_parquet, benchmark_daily, label_regimes,
                                     backtest_swing_tf, daily_atr_series)
from futures.basket import BASKET, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket
from futures.stress_mid import StressMidEngine
from futures.circuit_breaker import CircuitBreaker
from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
from global_index import specs as gi_specs
from global_index.regime import RegimeLabels
from global_index.net_exposure_multi import MultiClusterGuard
from global_index.deploy_sim import replay, metrics, size_combined

# ── Config ─────────────────────────────────────────────────────────────────────
DATA_DIR    = "data/cache/futures"
NKD_PARQUET = "global_index/data/NKD_continuous_1m_8y.parquet"
REGIME_CSV  = "spy_daily.csv"
SLIPPAGE    = 2.0
NKD_INST    = "MNKD"
NKD_EMA     = 10
NKD_MULT    = 2.5
ROSKA4_MULT = 2.5
ACCOUNT     = 50_000.0

CLAIMED_SWING_2022   = -232.0
CLAIMED_STRESS_2022  = 5296.0

# ── Load data ──────────────────────────────────────────────────────────────────
print("Loading market data …")
dfs  = {n: load_parquet(str(Path(DATA_DIR) / data_filename(c))) for n, c in BASKET.items()}
atrs = {n: daily_atr_series(df) for n, df in dfs.items()}
pvs  = {n: c.point_value for n, c in BASKET.items()}
costs = costs_for_basket(slippage_ticks=SLIPPAGE)
bench = benchmark_daily(REGIME_CSV)
labels = label_regimes(bench, "2018-01-01", 3, "2024-12-31")

print("Running engines …")
swing_raw  = SwingTFEngine().backtest_basket(dfs, labels, costs)
stress_raw = StressMidEngine().backtest_basket(dfs, labels, costs)

# NKD
c_spec = gi_specs.SPECS[NKD_INST]
spy    = pd.Series(label_regimes(benchmark_daily(REGIME_CSV), "2018-01-01", 3, "2024-12-31"))
idx    = pd.DatetimeIndex(spy.index)
spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
nlab   = RegimeLabels(spy.sort_index(), lag_days=1)
ndf    = gi_load(NKD_PARQUET); ndf.index = ndf.index.tz_convert(c_spec.session_tz)
natr   = daily_atr_series(ndf)
ncost  = GIFC(point_value=c_spec.point_value, tick=c_spec.tick,
              commission_rt=c_spec.commission_rt, slippage_ticks_per_side=SLIPPAGE)
nkd_raw = backtest_swing_tf(ndf, nlab, ncost, ema_period=NKD_EMA,
                             chandelier_atr_mult=NKD_MULT, max_hold_days=5, gap_fill=True)


# ── Build trade lists (same pattern as deploy_sim) ─────────────────────────────
def real_risk(atr_series, mult, point_value, entry_day, n):
    import numpy as np
    try:
        av = atr_series.asof(pd.Timestamp(entry_day))
    except Exception:
        av = float("nan")
    if av is None or pd.isna(av):
        av = float(atr_series.median())
    return n * mult * float(av) * point_value


def build_swing_trades(n=1):
    trades = []
    for inst, lst in swing_raw.items():
        for t in lst:
            r = real_risk(atrs[inst], ROSKA4_MULT, pvs[inst], t["day"], n)
            trades.append(dict(inst=inst, cluster="roska4_swing",
                               entry=pd.Timestamp(t["day"]),
                               exit=pd.Timestamp(t["exit_day"]),
                               direction=t["direction"],
                               pnl1=t["pnl"], atr=atrs[inst], mult=ROSKA4_MULT,
                               pv=pvs[inst], risk_sized=r,
                               pnl_sized=t["pnl"] * n,
                               _atr_entry=pd.Timestamp(t["day"])))
    return trades


def build_stress_trades(n=1):
    trades = []
    for inst, lst in stress_raw.items():
        for t in lst:
            r = real_risk(atrs[inst], ROSKA4_MULT, pvs[inst], t["day"], n)
            trades.append(dict(inst=inst, cluster="roska4_stress",
                               entry=pd.Timestamp(t["day"]),
                               exit=pd.Timestamp(t["exit_day"]),
                               direction=t["direction"],
                               pnl1=t["pnl"], atr=atrs[inst], mult=ROSKA4_MULT,
                               pv=pvs[inst], risk_sized=r,
                               pnl_sized=t["pnl"] * n,
                               _atr_entry=pd.Timestamp(t["day"])))
    return trades


def build_nkd_trades(n=1):
    trades = []
    for t in nkd_raw:
        ed = pd.Timestamp(t["day"]).tz_localize(None)
        xd = pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed
        r = real_risk(natr, NKD_MULT, c_spec.point_value, ed, n)
        trades.append(dict(inst=NKD_INST, cluster="global_nkd",
                           entry=ed, exit=xd,
                           direction=t["direction"],
                           pnl1=t["pnl"], atr=natr, mult=NKD_MULT,
                           pv=c_spec.point_value, risk_sized=r,
                           pnl_sized=t["pnl"] * n,
                           _atr_entry=ed))
    return trades


# ── A: STANDALONE per-year (no cap, n=1) ──────────────────────────────────────
print("\n" + "=" * 72)
print("A. STANDALONE per-year P&L (no cap, n=1 — matches original report methodology)")
print("=" * 72)

def standalone_by_year(trades):
    """Sum pnl1 by exit-year, no cap."""
    by_year = {}
    for t in trades:
        yr = t["exit"].year
        by_year[yr] = by_year.get(yr, 0.0) + t["pnl1"]
    return by_year


swing_yr   = standalone_by_year(build_swing_trades())
stress_yr  = standalone_by_year(build_stress_trades())
years_all  = sorted(set(list(swing_yr) + list(stress_yr)))

print(f"\n{'Year':<6}  {'swing TF':>12}  {'STRESS_MID':>12}  {'Combined':>12}")
print("-" * 50)
for y in years_all:
    sw = swing_yr.get(y, 0.0)
    st = stress_yr.get(y, 0.0)
    print(f"  {y}  {sw:>12,.0f}  {st:>12,.0f}  {sw+st:>12,.0f}")

sw_2022 = swing_yr.get(2022, 0.0)
st_2022 = stress_yr.get(2022, 0.0)
print(f"\n2022 MEASURED  swing={sw_2022:>10,.0f}   STRESS_MID={st_2022:>10,.0f}")
print(f"2022 CLAIMED   swing={CLAIMED_SWING_2022:>10,.0f}   STRESS_MID={CLAIMED_STRESS_2022:>10,.0f}")
swing_delta  = sw_2022 - CLAIMED_SWING_2022
stress_delta = st_2022 - CLAIMED_STRESS_2022
print(f"2022 DELTA     swing={swing_delta:>+10,.0f}   STRESS_MID={stress_delta:>+10,.0f}")
print(f"\n  Note: claim used fit_A labels (2022-12-31) + $500-stub risk$.")
print(f"  This run uses fit_C labels (2024-12-31) + real ATR risk$.")
if abs(stress_delta) < 1500:
    print(f"  VERDICT (STRESS_MID 2022): CONFIRMED — within $1,500 of claim.")
elif abs(stress_delta) < 3000:
    print(f"  VERDICT (STRESS_MID 2022): CLOSE — delta {stress_delta:+,.0f}; check label-change impact.")
else:
    print(f"  VERDICT (STRESS_MID 2022): DIVERGES — delta {stress_delta:+,.0f}; STRESS hedge role needs re-evaluation.")

# ── B: MARGINAL contribution (with cap) ───────────────────────────────────────
print("\n" + "=" * 72)
print("B. MARGINAL contribution WITH cap (full-system swing+stress+NKD vs without-stress)")
print("=" * 72)

sw_tr = build_swing_trades(); st_tr = build_stress_trades(); nk_tr = build_nkd_trades()

# 1-micro MaxDD for sizer
all_combined = sw_tr + st_tr + nk_tr
g0 = MultiClusterGuard(account=ACCOUNT)
d_combined1, _ = replay(all_combined, ACCOUNT, g0, {}, CircuitBreaker)
maxdd_1micro = metrics(d_combined1)["maxdd"]
base_margin = sum(BASKET[n].est_margin for n in BASKET) + c_spec.est_margin
n_sized, _ = size_combined(maxdd_1micro, base_margin, ACCOUNT)

def run_scenario(trades, n):
    for t in trades:
        t["risk_sized"] = real_risk(t["atr"], t["mult"], t["pv"], t["_atr_entry"], n)
        t["pnl_sized"]  = t["pnl1"] * n
    g = MultiClusterGuard(account=ACCOUNT)
    d, _ = replay(trades, ACCOUNT, g, {}, CircuitBreaker)
    return d


# Without stress (swing + NKD only)
tr_no_stress = build_swing_trades(n_sized) + build_nkd_trades(n_sized)
d_no_stress  = run_scenario(tr_no_stress, n_sized)

# With stress
tr_with_stress = build_swing_trades(n_sized) + build_stress_trades(n_sized) + build_nkd_trades(n_sized)
d_with_stress  = run_scenario(tr_with_stress, n_sized)

no_stress_yr   = {y: g.sum() for y, g in d_no_stress.groupby(d_no_stress.index.year)}
with_stress_yr = {y: g.sum() for y, g in d_with_stress.groupby(d_with_stress.index.year)}
years_b = sorted(set(list(no_stress_yr) + list(with_stress_yr)))

print(f"\n  Sizer: n={n_sized} micro (1-micro MaxDD ${maxdd_1micro:,.0f})")
print(f"\n{'Year':<6}  {'no-stress':>12}  {'with-stress':>12}  {'STRESS delta':>14}")
print("-" * 50)
for y in years_b:
    ns = no_stress_yr.get(y, 0.0)
    ws = with_stress_yr.get(y, 0.0)
    print(f"  {y}  {ns:>12,.0f}  {ws:>12,.0f}  {ws-ns:>+14,.0f}")

stress_marginal_2022 = with_stress_yr.get(2022, 0.0) - no_stress_yr.get(2022, 0.0)
print(f"\n  STRESS_MID marginal 2022 (with cap): {stress_marginal_2022:+,.0f}")
print(f"  STRESS_MID standalone 2022 (no cap): {st_2022:+,.0f}")

print("\n" + "=" * 72)
m_no  = metrics(d_no_stress)
m_wth = metrics(d_with_stress)
print(f"SUMMARY ({n_sized} micro, slippage {SLIPPAGE}t):")
print(f"  Without stress: net ${m_no['pnl']:,.0f}  Calmar {m_no['calmar']:.2f}  MaxDD ${m_no['maxdd']:,.0f}")
print(f"  With stress:    net ${m_wth['pnl']:,.0f}  Calmar {m_wth['calmar']:.2f}  MaxDD ${m_wth['maxdd']:,.0f}")
