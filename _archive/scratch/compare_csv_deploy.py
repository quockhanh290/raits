"""
compare_csv_deploy.py — Compare deploy_sim (original vs corrected CSV), side-by-side
======================================================================================
Uses deploy_sim internals (real sizer + ATR risk + 2-tick slippage + stress included),
same config that produced baseline_fit_c.txt: net $52,962 | Calmar 2.75 | MaxDD $2,789.

DOES NOT MODIFY spy_daily.csv.
Run from d:\raits:
    python _archive/scratch/compare_csv_deploy.py
Runtime: ~8-15 min (2× deploy_sim, each ~4-7 min with parquet cache).
"""
from __future__ import annotations
import sys, warnings, os
sys.path.insert(0, "d:/raits")
warnings.filterwarnings("ignore")
from pathlib import Path
import pandas as pd
import numpy as np

# ── Config (must match baseline_fit_c.txt) ───────────────────────────────────
DATA_DIR      = "d:/raits/data/cache/futures"
NKD_PARQUET   = "d:/raits/global_index/data/NKD_continuous_1m_8y.parquet"
CSV_ORIGINAL  = "d:/raits/spy_daily.csv"
CSV_CORRECTED = "d:/raits/_archive/scratch/spy_adjusted_v1_2026-07-06.csv"
ACCOUNT       = 50_000.0
SLIPPAGE      = 2.0          # 2 ticks/side — matches baseline_fit_c.txt
NKD_INST      = "MNKD"
NKD_EMA       = 10
NKD_MULT      = 2.5
ROSKA4_MULT   = 2.5
HMM_TRAIN_END = "2018-01-01"
HMM_FIT_END   = "2024-12-31"
INCLUDE_STRESS = True        # matches baseline — stress trades included
VAULT_START   = "2023-01-01"
OUT_DIR       = Path("d:/raits/_archive/scratch")

# ── Imports ───────────────────────────────────────────────────────────────────
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

# ── Load shared data (no regime labels — shared between both runs) ────────────
print("Loading shared market data...")
dfs = {n: load_parquet(str(Path(DATA_DIR) / data_filename(c))) for n, c in BASKET.items()}
atr = {n: daily_atr_series(df) for n, df in dfs.items()}
pv  = {n: c.point_value for n, c in BASKET.items()}

c_spec = gi_specs.SPECS[NKD_INST]
ndf_raw = gi_load(NKD_PARQUET)
ndf_raw.index = ndf_raw.index.tz_convert(c_spec.session_tz)
natr = daily_atr_series(ndf_raw)
ncost = GIFC(point_value=c_spec.point_value, tick=c_spec.tick,
             commission_rt=c_spec.commission_rt,
             slippage_ticks_per_side=SLIPPAGE)
costs = costs_for_basket(slippage_ticks=SLIPPAGE)
print(f"  Rổ 4 + NKD loaded | slippage={SLIPPAGE} tick/side | stress={INCLUDE_STRESS}")
print()


def real_risk(atr_series, mult, point_value, entry_day, contracts):
    try:
        av = atr_series.asof(pd.Timestamp(entry_day))
    except Exception:
        av = np.nan
    if av is None or pd.isna(av):
        av = float(atr_series.median())
    return contracts * mult * float(av) * point_value


def run_deploy(label: str, regime_csv: str) -> dict:
    """Run deploy_sim logic with given regime CSV. Returns structured metrics dict."""
    print(f"{'='*65}")
    print(f"Running: {label}")
    print(f"  CSV: {regime_csv}")
    print(f"{'='*65}")

    bench = benchmark_daily(regime_csv)
    labels = label_regimes(bench, HMM_TRAIN_END, 3, HMM_FIT_END)
    n_regimes = pd.Series(labels).value_counts()
    print(f"  Regime dist: {dict(n_regimes)}")

    # Rổ 4 swing + stress
    swing  = SwingTFEngine().backtest_basket(dfs, labels, costs)
    stress = StressMidEngine().backtest_basket(dfs, labels, costs) if INCLUDE_STRESS else {}

    # NKD
    spy = pd.Series(label_regimes(benchmark_daily(regime_csv), HMM_TRAIN_END, 3, HMM_FIT_END))
    idx = pd.DatetimeIndex(spy.index)
    spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    nlab = RegimeLabels(spy.sort_index(), lag_days=1)
    nkd  = backtest_swing_tf(ndf_raw, nlab, ncost, ema_period=NKD_EMA,
                             chandelier_atr_mult=NKD_MULT, max_hold_days=5, gap_fill=True)

    # Assemble trades
    all_tr = []
    for inst, lst in swing.items():
        for t in lst:
            all_tr.append(dict(inst=inst, cluster="roska4_swing",
                               entry=pd.Timestamp(t["day"]),
                               exit=pd.Timestamp(t["exit_day"]),
                               direction=t["direction"], pnl1=t["pnl"],
                               atr=atr[inst], mult=ROSKA4_MULT, pv=pv[inst]))
    for inst, lst in stress.items():
        for t in lst:
            all_tr.append(dict(inst=inst, cluster="roska4_stress",
                               entry=pd.Timestamp(t["day"]),
                               exit=pd.Timestamp(t["exit_day"]),
                               direction=t["direction"], pnl1=t["pnl"],
                               atr=atr[inst], mult=ROSKA4_MULT, pv=pv[inst]))
    for t in nkd:
        ed = pd.Timestamp(t["day"]).tz_localize(None)
        xd = (pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed)
        all_tr.append(dict(inst=NKD_INST, cluster="global_nkd", entry=ed, exit=xd,
                           direction=t["direction"], pnl1=t["pnl"],
                           atr=natr, mult=NKD_MULT, pv=c_spec.point_value))

    for t in all_tr:
        t["_atr_entry"] = pd.Timestamp(t["entry"])

    # Step 1: 1-micro to find MaxDD → sizer
    for t in all_tr:
        t["risk_sized"] = real_risk(t["atr"], t["mult"], t["pv"], t["_atr_entry"], 1)
        t["pnl_sized"]  = t["pnl1"] * 1
    guard0 = MultiClusterGuard(account=ACCOUNT)
    d1, _ = replay(all_tr, ACCOUNT, guard0, {}, CircuitBreaker)
    m1    = metrics(d1)

    base_margin = sum(BASKET[n].est_margin for n in BASKET) + c_spec.est_margin
    n_contracts, sz = size_combined(m1["maxdd"], base_margin, ACCOUNT)

    # Step 2: sized replay
    contracts_by = {n: n_contracts for n in BASKET}
    contracts_by[NKD_INST] = n_contracts
    for t in all_tr:
        t["risk_sized"] = real_risk(t["atr"], t["mult"], t["pv"], t["_atr_entry"], n_contracts)
        t["pnl_sized"]  = t["pnl1"] * n_contracts
    guard = MultiClusterGuard(account=ACCOUNT)
    sized_daily, st = replay(all_tr, ACCOUNT, guard, contracts_by, CircuitBreaker)
    msz = metrics(sized_daily)

    # Vault metrics
    vault = sized_daily[sized_daily.index >= pd.Timestamp(VAULT_START)]
    vmsz  = metrics(vault) if not vault.empty else {}

    per_year = {y: float(g.sum()) for y, g in sized_daily.groupby(sized_daily.index.year)}

    print(f"  Sizer: n_contracts={n_contracts} | binding={sz['binding']} "
          f"| proj_dd={sz['proj_dd_pct']:.1%}")
    print(f"  DEPLOY:  net ${msz['pnl']:>9,.0f} | Calmar {msz['calmar']:.2f} | "
          f"MaxDD ${msz['maxdd']:>7,.0f} | PF {msz['pf']:.2f} | Sharpe {msz['sharpe']:.2f}")
    print(f"  vault:   net ${vmsz.get('pnl',0):>9,.0f} | Calmar {vmsz.get('calmar',0):.2f} | "
          f"MaxDD ${vmsz.get('maxdd',0):>7,.0f}")
    print(f"  taken: {st['taken']}  rejected: {st['rejected']}  halted: {st['halted']}")
    print(f"  Per-year:")
    for yr, net in sorted(per_year.items()):
        print(f"    {yr}  ${net:>9,.0f}")
    print()

    # Save to file
    tag = "original_deploy" if "original" in label.lower() else "corrected_deploy"
    out = OUT_DIR / f"result_{tag}.txt"
    lines = [f"Run: {label}", f"CSV: {regime_csv}",
             f"n_contracts={n_contracts} binding={sz['binding']}",
             f"Regime dist: {dict(n_regimes)}",
             f"DEPLOY: pnl={msz['pnl']:.2f} calmar={msz['calmar']:.3f} "
             f"maxdd={msz['maxdd']:.2f} pf={msz['pf']:.3f} sharpe={msz['sharpe']:.3f}",
             f"vault:  pnl={vmsz.get('pnl',0):.2f} calmar={vmsz.get('calmar',0):.3f} "
             f"maxdd={vmsz.get('maxdd',0):.2f}",
             "per-year:"] + [f"  {yr}  {net:.2f}" for yr, net in sorted(per_year.items())]
    out.write_text("\n".join(lines))
    print(f"  → Saved: {out}")
    print()

    return dict(label=label, regime_csv=regime_csv, n_contracts=n_contracts,
                sz=sz, msz=msz, vmsz=vmsz, per_year=per_year,
                n_regimes=dict(n_regimes), taken=st["taken"],
                rejected=st["rejected"], halted=st["halted"])


# ── Run both ──────────────────────────────────────────────────────────────────
print(f"spy_daily.csv UNCHANGED at {CSV_ORIGINAL}")
print(f"Corrected snapshot:  {CSV_CORRECTED}")
print()

r_orig = run_deploy("ORIGINAL (spy_daily.csv frozen 2017)", CSV_ORIGINAL)
r_corr = run_deploy("CORRECTED (Polygon adjusted 2026-07-06)", CSV_CORRECTED)


# ── Side-by-side ──────────────────────────────────────────────────────────────
def row(name, o, c, fmt=",.0f"):
    d = c - o
    pct = d / abs(o) * 100 if abs(o) > 1e-9 else 0.0
    print(f"{name:<32} {o:>14{fmt}} {c:>14{fmt}}  {d:>+12{fmt}}  {pct:>+7.1f}%")

print()
print("=" * 80)
print("SIDE-BY-SIDE: ORIGINAL vs CORRECTED (deploy_sim, slippage=2 tick, stress included)")
print("=" * 80)
print(f"{'Metric':<32} {'ORIGINAL':>14} {'CORRECTED':>14}  {'Delta':>12}  {'Delta%':>7}")
print("-" * 80)

print("FULL SYSTEM (deploy-realistic):")
row("  Net P&L ($)",        r_orig['msz']['pnl'],    r_corr['msz']['pnl'])
row("  Calmar",             r_orig['msz']['calmar'],  r_corr['msz']['calmar'], ".3f")
row("  MaxDD ($)",          r_orig['msz']['maxdd'],   r_corr['msz']['maxdd'])
row("  Sharpe",             r_orig['msz']['sharpe'],  r_corr['msz']['sharpe'], ".3f")
row("  PF",                 r_orig['msz']['pf'],      r_corr['msz']['pf'],     ".3f")

print()
print("VAULT PERIOD (2023+):")
row("  Vault Net P&L ($)",  r_orig['vmsz'].get('pnl',0),    r_corr['vmsz'].get('pnl',0))
row("  Vault Calmar",       r_orig['vmsz'].get('calmar',0),  r_corr['vmsz'].get('calmar',0), ".3f")
row("  Vault MaxDD ($)",    r_orig['vmsz'].get('maxdd',0),   r_corr['vmsz'].get('maxdd',0))

print()
print("REGIME DISTRIBUTION:")
for rg in ["Calm", "Normal", "Stress"]:
    o = r_orig['n_regimes'].get(rg, 0)
    c = r_corr['n_regimes'].get(rg, 0)
    print(f"  {rg:<10} {o:>14d} {c:>14d}  {c-o:>+12d}")

print()
print("SIZER (n_contracts):")
print(f"  original:  {r_orig['n_contracts']}  binding={r_orig['sz']['binding']}")
print(f"  corrected: {r_corr['n_contracts']}  binding={r_corr['sz']['binding']}")

print()
print("PER-YEAR NET P&L:")
all_years = sorted(set(list(r_orig['per_year'].keys()) + list(r_corr['per_year'].keys())))
for yr in all_years:
    o = r_orig['per_year'].get(yr, 0)
    c = r_corr['per_year'].get(yr, 0)
    vflag = " [VAULT]" if yr >= 2023 else ""
    print(f"  {yr}  orig: ${o:>9,.0f}   corr: ${c:>9,.0f}   delta: ${c-o:>+8,.0f}{vflag}")

print()
print("=" * 80)
print("VERDICT")
print("=" * 80)
pnl_delta  = r_corr['msz']['pnl']  - r_orig['msz']['pnl']
pnl_pct    = pnl_delta / abs(r_orig['msz']['pnl']) * 100 if r_orig['msz']['pnl'] else 0
vault_delta = r_corr['vmsz'].get('pnl',0) - r_orig['vmsz'].get('pnl',0)
vault_pct   = vault_delta / abs(r_orig['vmsz'].get('pnl',1)) * 100

print(f"Full system net P&L delta:  ${pnl_delta:>+,.0f}  ({pnl_pct:>+.1f}%)")
print(f"Vault OOS P&L delta:        ${vault_delta:>+,.0f}  ({vault_pct:>+.1f}%)")
print(f"Original baseline check:    ${r_orig['msz']['pnl']:>,.0f}  (expect ~$52,962)")
print()
if abs(pnl_pct) < 5 and abs(vault_pct) < 10:
    verdict = "MINOR: data drift had small P&L impact. Can deploy on corrected CSV, no urgency."
elif abs(pnl_pct) < 15 or abs(vault_pct) < 20:
    verdict = "MODERATE: switch to corrected CSV BEFORE go-live. Vault number changes."
else:
    verdict = "SIGNIFICANT: old $52,962/$7,404 unreliable. Must switch + re-establish baseline."
print(f"FINDING: {verdict}")
print()
print(f"spy_daily.csv:  UNCHANGED  (backup: spy_daily_ORIGINAL_backup.csv)")
print(f"Corrected file: {CSV_CORRECTED}")
print(f"Results: {OUT_DIR}/result_original_deploy.txt + result_corrected_deploy.txt")
