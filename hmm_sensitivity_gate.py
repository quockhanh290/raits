"""
hmm_sensitivity_gate.py — HMM fit-window sensitivity measurement (research only)
==================================================================================
Đo độ nhạy HMM với anchored-expanding fit window (không đổi production).

Runs from d:\raits:
    python hmm_sensitivity_gate.py

Measures 1 & 2:
  - Label sensitivity on common window 2019-01-01 → 2022-12-31
  - Stress-day count per fit (collapse check)

Measure 3 (deploy_sim edge) must be run separately — see printed commands at end.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

from futures._validated_core import benchmark_daily, label_regimes

# ── Config ───────────────────────────────────────────────────────────────────
SPY_CSV      = str(ROOT / "spy_daily.csv")
ANCHOR_START = "2018-01-01"   # never fit before this date (preserves 2018 selloff)
TRAIN_END    = "2018-12-31"   # labels start from 2019-01-01 onwards
COMMON_START = "2019-01-01"
COMMON_END   = "2022-12-31"

FIT_SPANS = {
    "A (→2022)": "2022-12-31",   # current production
    "B (→2023)": "2023-12-31",
    "C (→2024)": "2024-12-31",
}

# ── Load & anchor ─────────────────────────────────────────────────────────────
print("Loading SPY daily …")
spy_full = benchmark_daily(SPY_CSV)
spy = spy_full[spy_full.index >= pd.Timestamp(ANCHOR_START)]
print(f"  SPY range after anchor: {spy.index[0].date()} → {spy.index[-1].date()}  "
      f"({len(spy)} days)\n")

# ── Fit all spans ─────────────────────────────────────────────────────────────
labels_all: dict[str, pd.Series] = {}
stress_counts: dict[str, tuple[int, int]] = {}

for name, fit_end in FIT_SPANS.items():
    print(f"[{name}] Fitting HMM on 2018-01-01 → {fit_end} …")
    lbl_dict = label_regimes(spy, TRAIN_END, 3, fit_end)
    lbl = pd.Series(lbl_dict).sort_index()
    labels_all[name] = lbl
    n_stress = int((lbl == "Stress").sum())
    n_total  = len(lbl)
    stress_counts[name] = (n_stress, n_total)
    regime_dist = lbl.value_counts().to_dict()
    print(f"  Labeled {n_total} days  ({lbl.index[0].date()} → {lbl.index[-1].date()})")
    print(f"  Regime dist: { {k: f'{v} ({100*v/n_total:.1f}%)' for k,v in sorted(regime_dist.items())} }")
    print(f"  Stress days: {n_stress} ({100*n_stress/n_total:.1f}%)\n")

# ── Measure 2: Stress-day count (collapse check) ──────────────────────────────
print("=" * 68)
print("MEASURE 2 — STRESS-DAY COUNT (collapse check)")
print("=" * 68)
print(f"{'Fit':<14}  {'Stress':>7}  {'Total':>7}  {'%':>6}  {'Calm':>6}  {'Normal':>7}")
for name, (n_s, n_tot) in stress_counts.items():
    lbl = labels_all[name]
    nc = int((lbl == "Calm").sum())
    nn = int((lbl == "Normal").sum())
    nc4 = int((lbl == "Crisis").sum()) if (lbl == "Crisis").any() else 0
    print(f"{name:<14}  {n_s:>7}  {n_tot:>7}  {100*n_s/n_tot:>5.1f}%  "
          f"{nc:>6}  {nn:>7}" + (f"  Crisis={nc4}" if nc4 else ""))

# ── Measure 1: Label sensitivity on common window ─────────────────────────────
print()
print("=" * 68)
print(f"MEASURE 1 — LABEL SENSITIVITY (common window {COMMON_START} → {COMMON_END})")
print("=" * 68)

def common_slice(s: pd.Series) -> pd.Series:
    return s[(s.index >= COMMON_START) & (s.index <= COMMON_END)]

slices = {name: common_slice(lbl) for name, lbl in labels_all.items()}

PAIRS = [
    ("A (→2022)", "B (→2023)", "A→B"),
    ("B (→2023)", "C (→2024)", "B→C"),
    ("A (→2022)", "C (→2024)", "A→C"),
]

for xa, xb, tag in PAIRS:
    sa, sb = slices[xa], slices[xb]
    idx = sa.index.intersection(sb.index)
    n_diff = int((sa[idx] != sb[idx]).sum())
    pct    = 100.0 * n_diff / len(idx) if len(idx) else 0.0
    print(f"\n{tag}:  {n_diff} / {len(idx)} days differ  ({pct:.2f}%)")
    if n_diff == 0:
        print("  (no label changes on common window)")
    else:
        flips = pd.DataFrame({"from": sa[idx][sa[idx] != sb[idx]],
                               "to":   sb[idx][sa[idx] != sb[idx]]})
        fc = flips.groupby(["from", "to"]).size().rename("count")
        for (fr, to), cnt in fc.items():
            pct_flip = 100.0 * cnt / n_diff
            print(f"  {fr:>7} → {to:<7}: {cnt:>4} days ({pct_flip:.1f}% of diffs)")

# ── Verdict helper ────────────────────────────────────────────────────────────
print()
print("=" * 68)
print("THRESHOLD CHECK")
print("=" * 68)

ac_pct = 100.0 * int((slices["A (→2022)"].reindex(
    slices["A (→2022)"].index.intersection(slices["C (→2024)"].index)) !=
    slices["C (→2024)"].reindex(
    slices["A (→2022)"].index.intersection(slices["C (→2024)"].index))).sum()) / max(
    len(slices["A (→2022)"].index.intersection(slices["C (→2024)"].index)), 1)

stress_A, stress_C = stress_counts["A (→2022)"][0], stress_counts["C (→2024)"][0]
stress_pct_A = 100.0 * stress_A / stress_counts["A (→2022)"][1]
stress_pct_C = 100.0 * stress_C / stress_counts["C (→2024)"][1]
stress_ok = stress_C >= stress_A * 0.7  # not collapsed if within 30%

print(f"  A→C label change:  {ac_pct:.2f}%  (ROBUST if <2%, SENSITIVE if >5%)")
print(f"  Stress A: {stress_A} ({stress_pct_A:.1f}%)  |  C: {stress_C} ({stress_pct_C:.1f}%)")
print(f"  Stress collapse:   {'OK (no collapse)' if stress_ok else 'WARN — Stress count dropped >30%'}")

# ── Measure 3 deploy_sim commands ─────────────────────────────────────────────
print()
print("=" * 68)
print("MEASURE 3 — EDGE STABILITY: run these 3 commands from d:\\raits")
print("=" * 68)
BASE = ("python -m global_index.deploy_sim "
        "--data-dir data\\cache\\futures "
        "--nkd-parquet global_index\\data\\NKD_continuous_1m_8y.parquet "
        "--regime-csv spy_daily.csv "
        "--slippage-ticks 2 "
        "--include-stress ")
for name, fit_end in FIT_SPANS.items():
    print(f"\n# {name}")
    print(f"{BASE}--hmm-fit-end {fit_end}")
print()
print("Baseline (fit-2022): net $47,838 | Calmar 2.38 | MaxDD $2,911")
print("Compare Calmar across fits. ROBUST if spread ≤ 0.1, SENSITIVE if > 0.3")
