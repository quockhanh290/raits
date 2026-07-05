"""
global_index/scaling_dd_trust.py — Trust audit: 2-micro scaling threshold re-measurement
===========================================================================================
CLAIM (RAITS_FUTURES_STATUS.md, no committed script):
  "Scale 1→2 micro: chỉ sau equity ~$82k"
CLAIM (user estimate, no script): "2-micro DD ~$9,854"

SOURCE: statements in status doc. No script produced these numbers.

RE-MEASURES:
  1. 1-micro MaxDD of current pipeline (baseline sanity-check vs $2,789 known)
  2. Projected 2-micro MaxDD (forced n=2 replay including cap interaction)
  3. Equity threshold where sizer formula auto-selects n=2
  4. Whether "$82k" is derivable from sizer formula or is a manual buffer

Run from D:\\raits:
    python global_index\\scaling_dd_trust.py
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

import numpy as np
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

CLAIMED_DD_2MICRO    = 9854.0   # user estimate "~$9,854"
CLAIMED_THRESHOLD_82 = 82_000.0

# ── Load data (same as stress_mid_trust / deploy_sim) ─────────────────────────
print("Loading market data …")
dfs   = {n: load_parquet(str(Path(DATA_DIR) / data_filename(c))) for n, c in BASKET.items()}
atrs  = {n: daily_atr_series(df) for n, df in dfs.items()}
pvs   = {n: c.point_value for n, c in BASKET.items()}
costs = costs_for_basket(slippage_ticks=SLIPPAGE)
bench  = benchmark_daily(REGIME_CSV)
labels = label_regimes(bench, "2018-01-01", 3, "2024-12-31")

swing_raw  = SwingTFEngine().backtest_basket(dfs, labels, costs)
stress_raw = StressMidEngine().backtest_basket(dfs, labels, costs)

c_spec  = gi_specs.SPECS[NKD_INST]
spy     = pd.Series(label_regimes(benchmark_daily(REGIME_CSV), "2018-01-01", 3, "2024-12-31"))
idx     = pd.DatetimeIndex(spy.index)
spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
nlab    = RegimeLabels(spy.sort_index(), lag_days=1)
ndf     = gi_load(NKD_PARQUET); ndf.index = ndf.index.tz_convert(c_spec.session_tz)
natr    = daily_atr_series(ndf)
ncost   = GIFC(point_value=c_spec.point_value, tick=c_spec.tick,
               commission_rt=c_spec.commission_rt, slippage_ticks_per_side=SLIPPAGE)
nkd_raw = backtest_swing_tf(ndf, nlab, ncost, ema_period=NKD_EMA,
                             chandelier_atr_mult=NKD_MULT, max_hold_days=5, gap_fill=True)


def real_risk(atr_series, mult, point_value, entry_day, n):
    try:
        av = atr_series.asof(pd.Timestamp(entry_day))
    except Exception:
        av = float("nan")
    if av is None or pd.isna(av):
        av = float(atr_series.median())
    return n * mult * float(av) * point_value


def build_all_trades(n):
    trades = []
    for inst, lst in swing_raw.items():
        for t in lst:
            r = real_risk(atrs[inst], ROSKA4_MULT, pvs[inst], t["day"], n)
            trades.append(dict(inst=inst, cluster="roska4_swing",
                               entry=pd.Timestamp(t["day"]), exit=pd.Timestamp(t["exit_day"]),
                               direction=t["direction"], pnl1=t["pnl"],
                               risk_sized=r, pnl_sized=t["pnl"] * n,
                               atr=atrs[inst], mult=ROSKA4_MULT, pv=pvs[inst],
                               _atr_entry=pd.Timestamp(t["day"])))
    for inst, lst in stress_raw.items():
        for t in lst:
            r = real_risk(atrs[inst], ROSKA4_MULT, pvs[inst], t["day"], n)
            trades.append(dict(inst=inst, cluster="roska4_stress",
                               entry=pd.Timestamp(t["day"]), exit=pd.Timestamp(t["exit_day"]),
                               direction=t["direction"], pnl1=t["pnl"],
                               risk_sized=r, pnl_sized=t["pnl"] * n,
                               atr=atrs[inst], mult=ROSKA4_MULT, pv=pvs[inst],
                               _atr_entry=pd.Timestamp(t["day"])))
    for t in nkd_raw:
        ed = pd.Timestamp(t["day"]).tz_localize(None)
        xd = pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed
        r  = real_risk(natr, NKD_MULT, c_spec.point_value, ed, n)
        trades.append(dict(inst=NKD_INST, cluster="global_nkd",
                           entry=ed, exit=xd,
                           direction=t["direction"], pnl1=t["pnl"],
                           risk_sized=r, pnl_sized=t["pnl"] * n,
                           atr=natr, mult=NKD_MULT, pv=c_spec.point_value,
                           _atr_entry=ed))
    return trades


base_margin = sum(BASKET[inst].est_margin for inst in BASKET) + c_spec.est_margin

# ── STEP 1: 1-micro MaxDD ─────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("STEP 1 — 1-micro MaxDD (baseline check)")
print("=" * 72)

tr1 = build_all_trades(1)
g1 = MultiClusterGuard(account=ACCOUNT)
d1, st1 = replay(tr1, ACCOUNT, g1, {}, CircuitBreaker)
m1 = metrics(d1)

n_sized, sz1 = size_combined(m1["maxdd"], base_margin, ACCOUNT)

print(f"  1-micro MaxDD (replay): ${m1['maxdd']:,.0f}  ({m1['maxdd']/ACCOUNT:.1%} of ${ACCOUNT:,.0f})")
print(f"  Net P&L:                ${m1['pnl']:,.0f}")
print(f"  Calmar:                 {m1['calmar']:.2f}")
print(f"  dd_scale:               {sz1['dd_scale']:.2f}")
print(f"  margin_scale:           {sz1['margin_scale']:.2f}")
print(f"  → Sizer selects:        n={n_sized} micro  (binding: {sz1['binding']})")
print(f"\n  Baseline claim: MaxDD=$2,789 / n=1 / Calmar=2.75")
print(f"  MATCH: {'YES' if abs(m1['maxdd'] - 2789) < 200 else 'CHECK — delta ${:.0f}'.format(m1['maxdd'] - 2789)}")

# ── STEP 2: 2-micro MaxDD (forced n=2) ─────────────────────────────────────────
print("\n" + "=" * 72)
print("STEP 2 — 2-micro MaxDD (forced n=2, cap active)")
print("=" * 72)

tr2 = build_all_trades(2)
g2  = MultiClusterGuard(account=ACCOUNT)
d2, st2 = replay(tr2, ACCOUNT, g2, {}, CircuitBreaker)
m2  = metrics(d2)
contracts_2 = {inst: 2 for inst in BASKET}
contracts_2[NKD_INST] = 2

print(f"  2-micro MaxDD (replay):  ${m2['maxdd']:,.0f}  ({m2['maxdd']/ACCOUNT:.1%} of ${ACCOUNT:,.0f})")
print(f"  Net P&L at 2 micro:      ${m2['pnl']:,.0f}")
print(f"  Calmar at 2 micro:       {m2['calmar']:.2f}")
ratio = m2['maxdd'] / m1['maxdd'] if m1['maxdd'] > 0 else float("nan")
print(f"  Ratio 2-micro/1-micro:   {ratio:.2f}x  (linear would be 2.00x)")
print(f"\n  CLAIMED ~$9,854:  {'CLOSE' if abs(m2['maxdd'] - CLAIMED_DD_2MICRO) < 1500 else 'DIFFERS'} "
      f"(measured ${m2['maxdd']:,.0f}, claimed ${CLAIMED_DD_2MICRO:,.0f}, "
      f"delta ${m2['maxdd']-CLAIMED_DD_2MICRO:+,.0f})")

# ── STEP 3: Equity threshold for sizer to output n=2 ──────────────────────────
print("\n" + "=" * 72)
print("STEP 3 — Equity threshold where sizer auto-selects n=2")
print("=" * 72)

# From size_combined formula with measured 1-micro MaxDD:
# dd_scale = account * 0.10 / maxdd >= 2 → account >= 20 * maxdd
# margin_scale = account * 0.40 / base_margin >= 2 → account >= 5 * base_margin
maxdd_1micro = m1["maxdd"]
threshold_dd     = 20.0 * maxdd_1micro
threshold_margin = 5.0  * base_margin
threshold_n2     = max(threshold_dd, threshold_margin)
binding_factor   = "drawdown" if threshold_dd >= threshold_margin else "margin"

print(f"\n  Base margin (all 5 instruments, 1 micro each):")
for inst in BASKET:
    print(f"    {inst}: ${BASKET[inst].est_margin:,}")
print(f"    {NKD_INST}: ${c_spec.est_margin:,}")
print(f"    Total: ${base_margin:,}")

print(f"\n  Formula thresholds (to satisfy dd_scale>=2 AND margin_scale>=2):")
print(f"    DD threshold:     ${threshold_dd:,.0f}  (20 × ${maxdd_1micro:,.0f} MaxDD)")
print(f"    Margin threshold: ${threshold_margin:,.0f}  (5 × ${base_margin:,} margin)")
print(f"    Binding factor:   {binding_factor}")
print(f"    → Sizer selects n=2 at equity ≥ ${threshold_n2:,.0f}  (binding: {binding_factor})")

# Verify by running size_combined at threshold_n2
n_at_threshold, sz_t = size_combined(maxdd_1micro, base_margin, threshold_n2)
print(f"\n  Verification — size_combined at ${threshold_n2:,.0f}: n={n_at_threshold}")

# ── STEP 4: What is the "$82k" claim? ─────────────────────────────────────────
print("\n" + "=" * 72)
print("STEP 4 — Origin of '$82k' threshold claim")
print("=" * 72)

buffer_pct = (CLAIMED_THRESHOLD_82 - threshold_n2) / threshold_n2 * 100
print(f"\n  Sizer formula threshold (from Step 3): ${threshold_n2:,.0f}")
print(f"  Claimed threshold '$82k':              ${CLAIMED_THRESHOLD_82:,.0f}")
print(f"  Buffer above formula threshold:        ${CLAIMED_THRESHOLD_82 - threshold_n2:,.0f}  "
      f"({buffer_pct:.0f}% above formula minimum)")

# Check if 2-micro MaxDD hits hard 15% cap at $82k
dd_pct_at_82k = m2['maxdd'] / CLAIMED_THRESHOLD_82
print(f"\n  At $82k equity, 2-micro MaxDD ${m2['maxdd']:,.0f} = {dd_pct_at_82k:.1%} of equity")
print(f"  Hard cap is 15% ({0.15 * CLAIMED_THRESHOLD_82:,.0f} at $82k)")

print(f"\n  FINDING:")
if abs(threshold_n2 - CLAIMED_THRESHOLD_82) < 5_000:
    print(f"  MATCH — $82k matches sizer formula threshold (${threshold_n2:,.0f}) within $5k.")
else:
    print(f"  GAP — $82k DOES NOT come from sizer formula (which gives ${threshold_n2:,.0f}).")
    print(f"  The ${buffer_pct:.0f}% buffer ({CLAIMED_THRESHOLD_82 - threshold_n2:,.0f}) was NOT derived from a script.")
    print(f"  It appears to be a manual safety buffer added on top of the formula threshold.")
    print(f"  RECOMMENDATION: use sizer formula threshold (${threshold_n2:,.0f}) as the measurable gate.")

print("\n" + "=" * 72)
print("SUMMARY")
print("=" * 72)
print(f"  1-micro MaxDD (measured):  ${m1['maxdd']:,.0f}   | baseline claim: $2,789")
print(f"  2-micro MaxDD (measured):  ${m2['maxdd']:,.0f}   | estimate claim: $9,854")
print(f"  Scaling DD ratio:          {ratio:.2f}x       | expected (linear): 2.00x")
print(f"  Sizer n=2 threshold:       ${threshold_n2:,.0f}   | status doc claim: $82,000")
print(f"  '$82k' source:             NOT from formula — manual {buffer_pct:.0f}% buffer")
