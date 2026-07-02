"""
nkd_fit_verify.py — prove NKD reads fit_C labels, not fit_A.
Compares SPY labels NKD receives + trade outcomes between fit_A and fit_C.

Run from d:\\raits:
    python nkd_fit_verify.py
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from futures._validated_core import benchmark_daily, label_regimes, backtest_swing_tf
from futures.basket import REGIME
from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
from global_index import specs as gi_specs
from global_index.regime import RegimeLabels

NKD_PAR    = "global_index/data/NKD_continuous_1m_8y.parquet"
REGIME_CSV = "spy_daily.csv"
VAULT_CUT  = "2023-01-01"   # match reconcile_nkd default

c = gi_specs.SPECS["MNKD"]
ndf = gi_load(NKD_PAR)
ndf.index = ndf.index.tz_convert(c.session_tz)
vs = pd.Timestamp(VAULT_CUT)
if ndf.index.tz:
    vs = vs.tz_localize(ndf.index.tz)
ndf = ndf[ndf.index < vs]
print(f"NKD bars: {len(ndf)}  ({ndf.index[0].date()} → {ndf.index[-1].date()})")

# ── 1. Build SPY label series for fit_A and fit_C ────────────────────────────
print("\nFitting HMM fit_A (2022-12-31)...")
spy_daily = benchmark_daily(REGIME_CSV)
lbl_a = pd.Series(label_regimes(spy_daily, "2018-01-01", 3, "2022-12-31")).sort_index()
print(f"  fit_A labeled {len(lbl_a)} SPY days")

print("Fitting HMM fit_C (2024-12-31)...")
lbl_c = pd.Series(label_regimes(spy_daily, "2018-01-01", 3, REGIME["hmm_fit_end"])).sort_index()
print(f"  fit_C labeled {len(lbl_c)} SPY days  (hmm_fit_end={REGIME['hmm_fit_end']})")

# Strip tz if present
for s in (lbl_a, lbl_c):
    idx = pd.DatetimeIndex(s.index)
    s.index = (idx.tz_localize(None) if idx.tz else idx).normalize()

nlab_a = RegimeLabels(lbl_a, lag_days=1)
nlab_c = RegimeLabels(lbl_c, lag_days=1)

# ── 2. Compare SPY labels NKD RECEIVES (per JST session day) ─────────────────
nkd_days = sorted(ndf.index.normalize().unique())
print(f"\nNKD session days (IS, before {VAULT_CUT}): {len(nkd_days)}")

same = diff = 0
diffs = []
for d in nkd_days:
    ra = nlab_a.get(d)
    rc = nlab_c.get(d)
    if ra == rc:
        same += 1
    else:
        diff += 1
        diffs.append((d, ra, rc))

print(f"Labels same:    {same} ({100*same/len(nkd_days):.1f}%)")
print(f"Labels DIFFER:  {diff} ({100*diff/len(nkd_days):.1f}%)")
if diffs:
    from collections import Counter
    flip_types = Counter(f"{ra}→{rc}" for _, ra, rc in diffs)
    print("  Flip breakdown:")
    for flip, cnt in sorted(flip_types.items(), key=lambda x: -x[1]):
        print(f"    {flip}: {cnt}")
    print(f"  First 5 diff days: {[str(d.date()) for d, _, _ in diffs[:5]]}")
else:
    print("  >>> NO LABEL DIFFS on NKD days — NKD is receiving IDENTICAL labels")
    print("      regardless of fit_A/fit_C. Check hmm_fit_end is truly changing.")

# ── 3. Run NKD backtest with each, compare trades ────────────────────────────
ncost = GIFC(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt,
             slippage_ticks_per_side=1.0)  # matches deploy_sim default

print("\nRunning NKD backtest with fit_A labels...")
trades_a = backtest_swing_tf(ndf, nlab_a, ncost, ema_period=10,
                              chandelier_atr_mult=2.5, max_hold_days=5, gap_fill=True)
pnl_a = sum(t["pnl"] for t in trades_a)

print("Running NKD backtest with fit_C labels...")
trades_c = backtest_swing_tf(ndf, nlab_c, ncost, ema_period=10,
                              chandelier_atr_mult=2.5, max_hold_days=5, gap_fill=True)
pnl_c = sum(t["pnl"] for t in trades_c)

print(f"\n{'='*60}")
print(f"NKD fit_A: {len(trades_a)} trades  pnl=${pnl_a:,.2f}")
print(f"NKD fit_C: {len(trades_c)} trades  pnl=${pnl_c:,.2f}")
print(f"Trade count diff: {len(trades_c) - len(trades_a):+d}")
print(f"PnL diff:         ${pnl_c - pnl_a:+,.2f}")

if len(trades_a) == len(trades_c) and abs(pnl_a - pnl_c) < 0.01:
    if diff == 0:
        print("\nCONCLUSION: Labels identical on NKD days AND trades identical.")
        print("  → fit_C delivers same regime map to NKD as fit_A for IS NKD days.")
        print("  → NOT a bug: the SPY label flip days don't land on NKD session days.")
    else:
        print(f"\nCONCLUSION: Labels DIFFER on {diff} NKD days but trades are IDENTICAL.")
        print("  → Label flips occur on days where NKD had no entry signal (pos≠None or no signal).")
        print("  → NKD IS reading fit_C labels correctly; flip days just don't trigger new entries.")
elif len(trades_a) != len(trades_c) or abs(pnl_a - pnl_c) > 0.01:
    print(f"\nCONCLUSION: Trades DIFFER → labels DO affect NKD trade selection.")
    print(f"  fit_C gives {len(trades_c)-len(trades_a):+d} trades, ${pnl_c-pnl_a:+,.2f} pnl.")
    # Show which entries differ
    set_a = {(t["day"], t["direction"]) for t in trades_a}
    set_c = {(t["day"], t["direction"]) for t in trades_c}
    only_a = set_a - set_c
    only_c = set_c - set_a
    if only_a:
        print(f"  Entries in fit_A but not fit_C ({len(only_a)}): {sorted(only_a)[:5]}")
    if only_c:
        print(f"  Entries in fit_C but not fit_A ({len(only_c)}): {sorted(only_c)[:5]}")
print('='*60)
