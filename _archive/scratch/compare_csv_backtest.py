"""
compare_csv_backtest.py — Run combined_system twice (original vs corrected CSV), compare
========================================================================================
Calls combined_system internals directly — no subprocess, structured comparison output.
DOES NOT MODIFY spy_daily.csv.  Both files read-only.

Run from d:\raits:
    python _archive/scratch/compare_csv_backtest.py

Runtime: ~5-10 min (2× backtest, each ~2-4 min with parquet cache).

Outputs:
    _archive/scratch/result_original.txt   — full per-year for original CSV
    _archive/scratch/result_corrected.txt  — full per-year for corrected CSV
    Side-by-side comparison printed to stdout.
"""
from __future__ import annotations
import sys, warnings, os
sys.path.insert(0, "d:/raits")
warnings.filterwarnings("ignore")
from pathlib import Path
import pandas as pd
import numpy as np

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR     = "d:/raits/data/cache/futures"
NKD_PARQUET  = "d:/raits/global_index/data/NKD_continuous_1m_8y.parquet"
CSV_ORIGINAL = "d:/raits/spy_daily.csv"
CSV_CORRECTED = "d:/raits/_archive/scratch/spy_adjusted_v1_2026-07-06.csv"
ACCOUNT      = 50_000.0
RISK_PER_POS = 500.0
HMM_TRAIN_END = "2018-01-01"
HMM_FIT_END   = "2024-12-31"
NKD_EMA      = 10
NKD_MULT     = 2.5
NKD_INST     = "MNKD"
VAULT_START  = "2023-01-01"

OUT_DIR = Path("d:/raits/_archive/scratch")

# ── Imports ───────────────────────────────────────────────────────────────────
from futures._validated_core import load_parquet, benchmark_daily, label_regimes, backtest_swing_tf
from futures.basket import BASKET, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket
from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
from global_index import specs as gi_specs
from global_index.regime import RegimeLabels
from global_index.net_exposure_multi import MultiClusterGuard, Position, entry_priority_key
try:
    from futures.circuit_breaker import CircuitBreaker
except Exception:
    CircuitBreaker = None

from global_index.combined_system import metrics, run_system


# ── Load data once (shared between both runs) ─────────────────────────────────
print("Loading market data (shared)...")
dfs = {n: load_parquet(str(Path(DATA_DIR) / data_filename(c))) for n, c in BASKET.items()}
print(f"  Rổ 4: {list(dfs.keys())}")

c_spec = gi_specs.SPECS[NKD_INST]
ndf_raw = gi_load(NKD_PARQUET)
ndf_raw.index = ndf_raw.index.tz_convert(c_spec.session_tz)
ncost = GIFC(point_value=c_spec.point_value, tick=c_spec.tick,
             commission_rt=c_spec.commission_rt)
costs = costs_for_basket()
print("  NKD + Rổ4 data loaded.")
print()


# ── Core backtest function ────────────────────────────────────────────────────
def run_one(label: str, regime_csv: str) -> dict:
    """Run full combined_system backtest with a given regime CSV. Returns metrics dict."""
    print(f"{'='*65}")
    print(f"Running: {label}")
    print(f"  CSV: {regime_csv}")
    print(f"{'='*65}")

    bench = benchmark_daily(regime_csv)
    labels = label_regimes(bench, HMM_TRAIN_END, 3, HMM_FIT_END)
    n_regimes = pd.Series(labels).value_counts()
    print(f"  Regime distribution: {dict(n_regimes)}")

    # Rổ 4 backtest
    swing = SwingTFEngine().backtest_basket(dfs, labels, costs)

    # NKD
    spy = pd.Series(label_regimes(benchmark_daily(regime_csv), HMM_TRAIN_END, 3, HMM_FIT_END))
    idx = pd.DatetimeIndex(spy.index)
    spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    nlab = RegimeLabels(spy.sort_index(), lag_days=1)
    nkd = backtest_swing_tf(ndf_raw, nlab, ncost, ema_period=NKD_EMA,
                            chandelier_atr_mult=NKD_MULT, max_hold_days=5, gap_fill=True)

    # Assemble trades
    all_tr = []
    for inst, lst in swing.items():
        for t in lst:
            all_tr.append(dict(inst=inst, cluster="roska4_swing",
                               entry=pd.Timestamp(t["day"]),
                               exit=pd.Timestamp(t["exit_day"]),
                               direction=t["direction"],
                               pnl=t["pnl"], risk=RISK_PER_POS))
    for t in nkd:
        all_tr.append(dict(inst=NKD_INST, cluster="global_nkd",
                           entry=pd.Timestamp(t["day"]).tz_localize(None),
                           exit=(pd.Timestamp(t["exit_day"]).tz_localize(None)
                                 if t.get("exit_day") else pd.Timestamp(t["day"]).tz_localize(None)),
                           direction=t["direction"], pnl=t["pnl"], risk=RISK_PER_POS))

    total_trades = len(all_tr)

    # Naive pooled (no risk layer)
    pooled = (pd.DataFrame([(pd.Timestamp(t["entry"]).normalize(), t["pnl"]) for t in all_tr],
                           columns=["d", "p"])
              .groupby("d")["p"].sum().sort_index())

    # Risk-layered
    guard = MultiClusterGuard(account=ACCOUNT)
    sys_daily, st = run_system(all_tr, ACCOUNT, guard, CircuitBreaker)

    pm = metrics(pooled)
    sm = metrics(sys_daily)

    # Per-year breakdown
    per_year = {y: float(g.sum()) for y, g in sys_daily.groupby(sys_daily.index.year)}

    # Vault-period metrics (2023+)
    vault = sys_daily[sys_daily.index >= pd.Timestamp(VAULT_START)]
    vm = metrics(vault) if not vault.empty else {}

    print(f"  naive pooled: net ${pm['pnl']:>9,.0f} | Calmar {pm['calmar']:>5.2f} | "
          f"MaxDD ${pm['maxdd']:>7,.0f} | PF {pm['pf']:.2f}")
    print(f"  FULL SYSTEM:  net ${sm['pnl']:>9,.0f} | Calmar {sm['calmar']:>5.2f} | "
          f"MaxDD ${sm['maxdd']:>7,.0f} | PF {sm['pf']:.2f}")
    print(f"  vault (2023+): net ${vm.get('pnl',0):>8,.0f} | Calmar {vm.get('calmar',0):>5.2f} | "
          f"MaxDD ${vm.get('maxdd',0):>7,.0f}")
    print(f"  per-cluster taken/rejected: {st['taken']} / {st['rejected']}")
    print(f"  circuit-breaker halts: {st['halted']}")
    print(f"  Per-year:")
    for yr, net in sorted(per_year.items()):
        print(f"    {yr}  ${net:>9,.0f}")
    print()

    # Save full per-year to file
    tag = "original" if "original" in label.lower() else "corrected"
    out = OUT_DIR / f"result_{tag}.txt"
    lines = [
        f"Run: {label}",
        f"CSV: {regime_csv}",
        f"Regime distribution: {dict(n_regimes)}",
        f"naive pooled: pnl={pm['pnl']:.2f} calmar={pm['calmar']:.3f} "
        f"maxdd={pm['maxdd']:.2f} pf={pm['pf']:.3f}",
        f"FULL SYSTEM:  pnl={sm['pnl']:.2f} calmar={sm['calmar']:.3f} "
        f"maxdd={sm['maxdd']:.2f} pf={sm['pf']:.3f}",
        f"vault:        pnl={vm.get('pnl',0):.2f} calmar={vm.get('calmar',0):.3f} "
        f"maxdd={vm.get('maxdd',0):.2f}",
        "per-year:",
    ] + [f"  {yr}  {net:.2f}" for yr, net in sorted(per_year.items())]
    out.write_text("\n".join(lines))
    print(f"  Saved → {out}")
    print()

    return dict(label=label, regime_csv=regime_csv,
                pm=pm, sm=sm, vm=vm, per_year=per_year,
                n_regimes=dict(n_regimes), taken=st["taken"], rejected=st["rejected"],
                halted=st["halted"], total_trades=total_trades)


# ── Run both ──────────────────────────────────────────────────────────────────
print(f"spy_daily.csv production: UNCHANGED at {CSV_ORIGINAL}")
print(f"Corrected snapshot:       {CSV_CORRECTED}")
print()

r_orig = run_one("ORIGINAL (spy_daily.csv frozen 2017)", CSV_ORIGINAL)
r_corr = run_one("CORRECTED (Polygon adjusted snapshot 2026-07-06)", CSV_CORRECTED)


# ── Side-by-side comparison ───────────────────────────────────────────────────
print()
print("=" * 70)
print("SIDE-BY-SIDE COMPARISON")
print("=" * 70)
print(f"{'Metric':<30} {'ORIGINAL':>15} {'CORRECTED':>15} {'Delta':>12} {'Delta%':>8}")
print("-" * 80)

def row(name, orig_val, corr_val, fmt=".0f", pct_base=None):
    delta = corr_val - orig_val
    if pct_base and abs(pct_base) > 1e-9:
        dpct = delta / abs(pct_base) * 100
        print(f"{name:<30} {orig_val:>15{fmt}} {corr_val:>15{fmt}} {delta:>+12{fmt}} {dpct:>+7.1f}%")
    else:
        print(f"{name:<30} {orig_val:>15{fmt}} {corr_val:>15{fmt}} {delta:>+12{fmt}}")

print("FULL SYSTEM (risk layer):")
row("  Net P&L ($)", r_orig['sm']['pnl'], r_corr['sm']['pnl'], ",d", r_orig['sm']['pnl'])
row("  Calmar", r_orig['sm']['calmar'], r_corr['sm']['calmar'], ".3f")
row("  MaxDD ($)", r_orig['sm']['maxdd'], r_corr['sm']['maxdd'], ",d")
row("  Sharpe", r_orig['sm']['sharpe'], r_corr['sm']['sharpe'], ".3f")
row("  PF", r_orig['sm']['pf'], r_corr['sm']['pf'], ".3f")

print()
print("VAULT PERIOD (2023-2024):")
row("  Vault Net P&L ($)", r_orig['vm'].get('pnl',0), r_corr['vm'].get('pnl',0),
    ",d", r_orig['vm'].get('pnl',1))
row("  Vault Calmar", r_orig['vm'].get('calmar',0), r_corr['vm'].get('calmar',0), ".3f")
row("  Vault MaxDD ($)", r_orig['vm'].get('maxdd',0), r_corr['vm'].get('maxdd',0), ",d")

print()
print("REGIME DISTRIBUTION:")
for rg in ["Calm", "Normal", "Stress"]:
    orig_n = r_orig['n_regimes'].get(rg, 0)
    corr_n = r_corr['n_regimes'].get(rg, 0)
    print(f"  {rg:<10} {orig_n:>15d} {corr_n:>15d} {corr_n-orig_n:>+12d}")

print()
print("PER-YEAR NET P&L (full system):")
all_years = sorted(set(list(r_orig['per_year'].keys()) + list(r_corr['per_year'].keys())))
for yr in all_years:
    o = r_orig['per_year'].get(yr, 0)
    c = r_corr['per_year'].get(yr, 0)
    d = c - o
    vault_flag = " [VAULT]" if yr >= 2023 else ""
    print(f"  {yr}   orig: ${o:>9,.0f}   corr: ${c:>9,.0f}   delta: ${d:>+8,.0f}{vault_flag}")

print()
print("=" * 70)
print("VERDICT")
print("=" * 70)
pnl_delta = r_corr['sm']['pnl'] - r_orig['sm']['pnl']
pnl_pct = pnl_delta / abs(r_orig['sm']['pnl']) * 100 if r_orig['sm']['pnl'] else 0
vault_delta = r_corr['vm'].get('pnl', 0) - r_orig['vm'].get('pnl', 0)
vault_pct = vault_delta / abs(r_orig['vm'].get('pnl', 1)) * 100

print(f"Full IS+vault net P&L delta: ${pnl_delta:+,.0f} ({pnl_pct:+.1f}%)")
print(f"Vault OOS P&L delta:         ${vault_delta:+,.0f} ({vault_pct:+.1f}%)")
print()
if abs(pnl_pct) < 5 and abs(vault_pct) < 10:
    print("FINDING: CSV adjustment drift had MINOR P&L impact (<5% full, <10% vault).")
    print("  Labels were wrong but P&L direction/magnitude is robust.")
    print("  Still recommended to switch to snapshot for correctness, but not critical-path.")
elif abs(pnl_pct) < 15 or abs(vault_pct) < 20:
    print("FINDING: CSV adjustment drift had MODERATE P&L impact.")
    print("  Switch to corrected snapshot BEFORE go-live. Re-establish baseline.")
    print("  Vault OOS number needs to be recalculated on corrected data.")
else:
    print("FINDING: CSV adjustment drift had SIGNIFICANT P&L impact (>15%).")
    print("  MUST switch to corrected snapshot. Old $52,962/$7,404 numbers unreliable.")
    print("  Re-run vault on corrected data before any live deployment.")

print()
print(f"spy_daily.csv: UNCHANGED (backup at spy_daily_ORIGINAL_backup.csv)")
print(f"Corrected CSV: {CSV_CORRECTED}")
print(f"Results saved: {OUT_DIR}/result_original.txt + result_corrected.txt")
