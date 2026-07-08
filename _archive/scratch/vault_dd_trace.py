"""
vault_dd_trace.py — Trace vault MaxDD change: which labels/trades caused $666 drop?
Also tests corrected CSV reproducibility (run twice, compare vault).
"""
from __future__ import annotations
import sys, warnings, json, re
sys.path.insert(0, "d:/raits")
warnings.filterwarnings("ignore")
from pathlib import Path
import pandas as pd
import numpy as np
from collections import Counter

DATA_DIR      = "d:/raits/data/cache/futures"
NKD_PARQUET   = "d:/raits/global_index/data/NKD_continuous_1m_8y.parquet"
CSV_ORIGINAL  = "d:/raits/spy_daily.csv"
CSV_CORRECTED = "d:/raits/_archive/scratch/spy_adjusted_v1_2026-07-06.csv"
ACCOUNT       = 50_000.0
SLIPPAGE      = 2.0
NKD_INST      = "MNKD"
NKD_EMA, NKD_MULT, ROSKA4_MULT = 10, 2.5, 2.5
HMM_TRAIN_END, HMM_FIT_END = "2018-01-01", "2024-12-31"
VAULT_START   = pd.Timestamp("2023-01-01")

from futures._validated_core import (load_parquet, benchmark_daily, label_regimes,
                                      backtest_swing_tf, daily_atr_series)
from futures.basket import BASKET, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket
from futures.stress_mid import StressMidEngine
from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
from global_index import specs as gi_specs
from global_index.regime import RegimeLabels
from global_index.net_exposure_multi import MultiClusterGuard, Position, entry_priority_key
from global_index.deploy_sim import replay, size_combined, metrics
try:
    from futures.circuit_breaker import CircuitBreaker
except Exception:
    CircuitBreaker = None

# ── Load shared data ──────────────────────────────────────────────────────────
print("Loading shared data...")
dfs   = {n: load_parquet(str(Path(DATA_DIR) / data_filename(c))) for n, c in BASKET.items()}
atr   = {n: daily_atr_series(df) for n, df in dfs.items()}
pv    = {n: c.point_value for n, c in BASKET.items()}
c_spec = gi_specs.SPECS[NKD_INST]
ndf_raw = gi_load(NKD_PARQUET); ndf_raw.index = ndf_raw.index.tz_convert(c_spec.session_tz)
natr  = daily_atr_series(ndf_raw)
ncost = GIFC(point_value=c_spec.point_value, tick=c_spec.tick,
             commission_rt=c_spec.commission_rt, slippage_ticks_per_side=SLIPPAGE)
costs = costs_for_basket(slippage_ticks=SLIPPAGE)

def real_risk(atr_series, mult, point_value, entry_day, n):
    try: av = atr_series.asof(pd.Timestamp(entry_day))
    except: av = np.nan
    if av is None or pd.isna(av): av = float(atr_series.median())
    return n * mult * float(av) * point_value

def run_deploy_daily(regime_csv: str) -> tuple[pd.Series, int, dict, dict]:
    """Returns (sized_daily_pnl, n_contracts, labels_dict, label_series)."""
    bench  = benchmark_daily(regime_csv)
    labels = label_regimes(bench, HMM_TRAIN_END, 3, HMM_FIT_END)
    swing  = SwingTFEngine().backtest_basket(dfs, labels, costs)
    stress = StressMidEngine().backtest_basket(dfs, labels, costs)
    spy = pd.Series(label_regimes(benchmark_daily(regime_csv), HMM_TRAIN_END, 3, HMM_FIT_END))
    idx = pd.DatetimeIndex(spy.index)
    spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    nlab = RegimeLabels(spy.sort_index(), lag_days=1)
    nkd  = backtest_swing_tf(ndf_raw, nlab, ncost, ema_period=NKD_EMA,
                             chandelier_atr_mult=NKD_MULT, max_hold_days=5, gap_fill=True)
    all_tr = []
    for inst, lst in swing.items():
        for t in lst:
            all_tr.append(dict(inst=inst, cluster="roska4_swing",
                               entry=pd.Timestamp(t["day"]), exit=pd.Timestamp(t["exit_day"]),
                               direction=t["direction"], pnl1=t["pnl"],
                               atr=atr[inst], mult=ROSKA4_MULT, pv=pv[inst]))
    for inst, lst in stress.items():
        for t in lst:
            all_tr.append(dict(inst=inst, cluster="roska4_stress",
                               entry=pd.Timestamp(t["day"]), exit=pd.Timestamp(t["exit_day"]),
                               direction=t["direction"], pnl1=t["pnl"],
                               atr=atr[inst], mult=ROSKA4_MULT, pv=pv[inst]))
    for t in nkd:
        ed = pd.Timestamp(t["day"]).tz_localize(None)
        xd = pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed
        all_tr.append(dict(inst=NKD_INST, cluster="global_nkd", entry=ed, exit=xd,
                           direction=t["direction"], pnl1=t["pnl"],
                           atr=natr, mult=NKD_MULT, pv=c_spec.point_value))
    for t in all_tr: t["_atr_entry"] = pd.Timestamp(t["entry"])

    for t in all_tr:
        t["risk_sized"] = real_risk(t["atr"], t["mult"], t["pv"], t["_atr_entry"], 1)
        t["pnl_sized"]  = t["pnl1"]
    d1, _ = replay(all_tr, ACCOUNT, MultiClusterGuard(account=ACCOUNT), {}, CircuitBreaker)
    n, sz = size_combined(metrics(d1)["maxdd"], sum(BASKET[n].est_margin for n in BASKET) + c_spec.est_margin, ACCOUNT)

    contracts_by = {k: n for k in list(BASKET.keys()) + [NKD_INST]}
    for t in all_tr:
        t["risk_sized"] = real_risk(t["atr"], t["mult"], t["pv"], t["_atr_entry"], n)
        t["pnl_sized"]  = t["pnl1"] * n
    sized_daily, st = replay(all_tr, ACCOUNT, MultiClusterGuard(account=ACCOUNT),
                             contracts_by, CircuitBreaker)
    return sized_daily, n, labels, st


def vault_maxdd_date(daily: pd.Series) -> tuple[pd.Timestamp, pd.Timestamp, float]:
    """Return (peak_date, trough_date, maxdd) for vault period."""
    v = daily[daily.index >= VAULT_START]
    eq = v.cumsum()
    peak_idx = eq.cummax()
    dd = peak_idx - eq
    trough_ts = dd.idxmax()
    dd_val = float(dd.max())
    # find peak before trough
    peak_ts = eq[:trough_ts].idxmax()
    return peak_ts, trough_ts, dd_val


# ── Run original ──────────────────────────────────────────────────────────────
print("\nRun 1: ORIGINAL")
daily_orig, n_orig, labels_orig, st_orig = run_deploy_daily(CSV_ORIGINAL)
m_orig = metrics(daily_orig[daily_orig.index >= VAULT_START])
pk_o, tr_o, dd_o = vault_maxdd_date(daily_orig)
print(f"  vault pnl=${m_orig['pnl']:,.0f} calmar={m_orig['calmar']:.2f} maxdd=${dd_o:,.0f}")
print(f"  MaxDD window: peak={pk_o.date()} → trough={tr_o.date()}")

# ── Run corrected (x2 for reproducibility) ───────────────────────────────────
print("\nRun 2a: CORRECTED (first pass)")
daily_corr1, n_corr1, labels_corr1, st_corr1 = run_deploy_daily(CSV_CORRECTED)
m_corr1 = metrics(daily_corr1[daily_corr1.index >= VAULT_START])
pk_c1, tr_c1, dd_c1 = vault_maxdd_date(daily_corr1)
print(f"  vault pnl=${m_corr1['pnl']:,.0f} calmar={m_corr1['calmar']:.2f} maxdd=${dd_c1:,.0f}")
print(f"  MaxDD window: peak={pk_c1.date()} → trough={tr_c1.date()}")

print("\nRun 2b: CORRECTED (second pass — reproducibility)")
daily_corr2, n_corr2, labels_corr2, st_corr2 = run_deploy_daily(CSV_CORRECTED)
m_corr2 = metrics(daily_corr2[daily_corr2.index >= VAULT_START])
pk_c2, tr_c2, dd_c2 = vault_maxdd_date(daily_corr2)
print(f"  vault pnl=${m_corr2['pnl']:,.0f} calmar={m_corr2['calmar']:.2f} maxdd=${dd_c2:,.0f}")
print(f"  MaxDD window: peak={pk_c2.date()} → trough={tr_c2.date()}")

# ── Reproducibility check ─────────────────────────────────────────────────────
print("\n=== REPRODUCIBILITY ===")
pnl_diff = abs(m_corr1['pnl'] - m_corr2['pnl'])
calmar_diff = abs(m_corr1['calmar'] - m_corr2['calmar'])
label_diffs = sum(1 for d in labels_corr1 if labels_corr1.get(d) != labels_corr2.get(d, None))
print(f"Label diffs run 2a vs 2b: {label_diffs}")
print(f"Vault PnL  diff: ${pnl_diff:.2f}  ({'IDENTICAL' if pnl_diff < 1 else 'DIFFERS'})")
print(f"Vault Calmar diff: {calmar_diff:.4f}  ({'IDENTICAL' if calmar_diff < 0.01 else 'DIFFERS'})")
print(f"n_contracts: {n_corr1} vs {n_corr2}  ({'SAME' if n_corr1==n_corr2 else 'DIFFERS'})")

# ── Vault DD trace: original drawdown chain ───────────────────────────────────
print("\n=== VAULT DD TRACE: ORIGINAL ===")
v_orig = daily_orig[daily_orig.index >= VAULT_START]
eq_o = v_orig.cumsum()
dd_chain_start = pk_o
dd_chain_end   = tr_o
print(f"MaxDD window: {dd_chain_start.date()} → {dd_chain_end.date()} = ${dd_o:,.0f}")
print(f"Days in window: {(dd_chain_end - dd_chain_start).days}")
window_pnl = v_orig[dd_chain_start:dd_chain_end]
losers = window_pnl[window_pnl < 0].sort_values()
print(f"Loss days in window: {(window_pnl < 0).sum()}")
print(f"Top-5 loss days (original):")
for d, v in losers.head(5).items():
    print(f"  {d.date()}: ${v:,.2f}")

print("\n=== VAULT DD TRACE: CORRECTED ===")
v_corr = daily_corr1[daily_corr1.index >= VAULT_START]
eq_c = v_corr.cumsum()
print(f"MaxDD window: {pk_c1.date()} → {tr_c1.date()} = ${dd_c1:,.0f}")
print(f"Days in window: {(tr_c1 - pk_c1).days}")
window_pnl_c = v_corr[pk_c1:tr_c1]
losers_c = window_pnl_c[window_pnl_c < 0].sort_values()
print(f"Top-5 loss days (corrected):")
for d, v in losers_c.head(5).items():
    print(f"  {d.date()}: ${v:,.2f}")

# ── Label changes in the original DD window ───────────────────────────────────
print("\n=== LABEL CHANGES IN ORIGINAL DD WINDOW ===")
label_changes_in_window = {}
for d in labels_orig:
    if dd_chain_start <= d <= dd_chain_end:
        lo = labels_orig[d]
        lc = labels_corr1.get(d, lo)
        if lo != lc:
            label_changes_in_window[d] = (lo, lc)

if label_changes_in_window:
    print(f"Label changes inside original DD window ({dd_chain_start.date()}→{dd_chain_end.date()}):")
    for d, (o,c) in sorted(label_changes_in_window.items()):
        orig_pnl = float(v_orig.get(d, 0.0))
        corr_pnl = float(v_corr.get(d, 0.0))
        print(f"  {d.date()}: {o}→{c}  | orig_day_pnl=${orig_pnl:+,.2f}  corr_day_pnl=${corr_pnl:+,.2f}")
else:
    print("  No label changes inside original DD window.")
    print("  → DD window itself is different between original and corrected.")

# ── Daily delta in vault: where do they differ most? ─────────────────────────
print("\n=== TOP DAILY DELTA (VAULT): where corrected diverges from original ===")
common_idx = v_orig.index.intersection(v_corr.index)
delta = (v_corr.reindex(common_idx) - v_orig.reindex(common_idx)).fillna(0)
big_delta = delta[delta.abs() > 50].sort_values()
print(f"Days with |delta| > $50 in vault: {len(big_delta)}")
if len(big_delta) > 0:
    print("Largest negative deltas (corrected WORSE than original):")
    for d, v in big_delta.head(5).items():
        lo = labels_orig.get(d, "?")
        lc = labels_corr1.get(d, "?")
        change = f"{lo}→{lc}" if lo != lc else "same"
        print(f"  {d.date()}: delta=${v:+,.2f}  label:{change}")
    print("Largest positive deltas (corrected BETTER than original):")
    for d, v in big_delta.tail(5).items():
        lo = labels_orig.get(d, "?")
        lc = labels_corr1.get(d, "?")
        change = f"{lo}→{lc}" if lo != lc else "same"
        print(f"  {d.date()}: delta=${v:+,.2f}  label:{change}")

# ── All 21 vault label changes: P&L delta ────────────────────────────────────
print("\n=== ALL 21 VAULT LABEL CHANGES: P&L DELTA ===")
vault_label_changes = {}
for d in labels_orig:
    if d >= VAULT_START:
        lo = labels_orig[d]
        lc = labels_corr1.get(d, lo)
        if lo != lc:
            vault_label_changes[d] = (lo, lc)

print(f"Vault label changes: {len(vault_label_changes)}")
print(f"{'Date':<14} {'Change':<18} {'Orig PnL':>10} {'Corr PnL':>10} {'Delta':>10}")
print("-"*65)
net_delta_from_changes = 0.0
for d in sorted(vault_label_changes):
    lo, lc = vault_label_changes[d]
    op = float(v_orig.get(d, 0.0))
    cp = float(v_corr.get(d, 0.0))
    delt = cp - op
    net_delta_from_changes += delt
    print(f"{str(d.date()):<14} {lo}→{lc:<14} {op:>10,.2f} {cp:>10,.2f} {delt:>+10,.2f}")
print(f"{'Net delta from label-change days':>47} {net_delta_from_changes:>+10,.2f}")
print()

# ── Final verdict ─────────────────────────────────────────────────────────────
print("="*65)
print("VERDICT")
print("="*65)
print(f"\n1. VAULT DD SOURCE:")
if len(label_changes_in_window) > 0:
    print(f"   {len(label_changes_in_window)} label changes INSIDE original DD window")
    print(f"   These directly shifted the drawdown trajectory")
else:
    print(f"   Original DD window {dd_chain_start.date()}→{tr_o.date()}")
    print(f"   Corrected DD window {pk_c1.date()}→{tr_c1.date()}")
    if dd_chain_start != pk_c1 or tr_o != tr_c1:
        print(f"   DD windows differ → corrected regime changed WHICH trades formed the DD")
    else:
        print(f"   Same DD window — corrected regime changed trades WITHIN the window")

print(f"\n2. TRUSTWORTHINESS:")
print(f"   Vault = 2yr window (~500 trading days), MaxDD = ${dd_o:,.0f} orig / ${dd_c1:,.0f} corr")
print(f"   $666 difference from regime label changes = real sensitivity")
print(f"   Neither Calmar (3.22 or 4.75) is a stable point estimate at 2yr scale")
print(f"   Both are data-correct — corrected CSV is closer to truth, but fragile either way")

print(f"\n3. REPRODUCIBILITY:")
if label_diffs == 0 and pnl_diff < 1:
    print(f"   CONFIRMED: corrected runs 2a/2b identical (label_diffs={label_diffs})")
    print(f"   HMM is deterministic (RANDOM_SEED=42 holds for this CSV)")
else:
    print(f"   WARNING: {label_diffs} label diffs between runs 2a/2b → non-deterministic!")
    print(f"   PnL diff=${pnl_diff:.2f} — vault numbers are NOT reproducible")

print(f"\n4. VAULT AS GATE:")
print(f"   Vault Calmar range: {m_orig['calmar']:.2f}–{m_corr1['calmar']:.2f} from a")
print(f"   single data correction (not even a bad year). 47% swing.")
print(f"   Recommendation: use vault as DIRECTIONAL SIGNAL only.")
print(f"   Gate threshold should use FULL IS+vault Calmar (more stable),")
print(f"   not vault-only. Vault-only Calmar is too sensitive to 20-label HMM shifts.")
