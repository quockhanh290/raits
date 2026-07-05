"""
global_index/hmm_flip_year_trust.py — Trust audit: fit_C A→C flip breakdown by year
======================================================================================
CLAIM (TASK.md: "HMM fit_C upgrade"):
  "A→C label change 17.16% but economically justified (83/101 Normal→Stress
   in 2020+2022 bear)"

SOURCE: hmm_sensitivity_gate.py measures total pct change (committed). But the
per-year flip breakdown ("83 of 101 in 2020+2022") is a manual interpretation
from the session — it is NOT reproduced by any committed script.

RE-MEASURES:
  1. Total A→C % change on common window (2019-2022) — should match 17.16%
  2. Flip type breakdown per year — produces "83/101" from the data
  3. Confirms or corrects "economically justified" claim

Run from D:\\raits:
    python global_index\\hmm_flip_year_trust.py
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

from futures._validated_core import benchmark_daily, label_regimes

# ── Config (mirrors hmm_sensitivity_gate.py) ───────────────────────────────────
SPY_CSV      = str(ROOT / "spy_daily.csv")
ANCHOR_START = "2018-01-01"
TRAIN_END    = "2018-01-01"
COMMON_START = "2019-01-01"
COMMON_END   = "2022-12-31"

FIT_A = "2022-12-31"   # fit_A (old production)
FIT_C = "2024-12-31"   # fit_C (current production)

CLAIMED_PCT_CHANGE = 17.16
CLAIMED_NORMAL_STRESS_TOTAL  = 101    # total Normal→Stress flips on common window
CLAIMED_NORMAL_STRESS_BEAR   = 83     # of those, in 2020 + 2022

# ── Load & fit ─────────────────────────────────────────────────────────────────
print("Loading SPY daily …")
spy_full = benchmark_daily(SPY_CSV)
spy = spy_full[spy_full.index >= pd.Timestamp(ANCHOR_START)]

print("Fitting A (→2022) …")
lbl_a_dict = label_regimes(spy, TRAIN_END, 3, FIT_A)
lbl_a = pd.Series(lbl_a_dict).sort_index()

print("Fitting C (→2024) …")
lbl_c_dict = label_regimes(spy, TRAIN_END, 3, FIT_C)
lbl_c = pd.Series(lbl_c_dict).sort_index()

# ── Common window slice ─────────────────────────────────────────────────────────
def common_slice(s: pd.Series) -> pd.Series:
    return s[(s.index >= COMMON_START) & (s.index <= COMMON_END)]

sa = common_slice(lbl_a)
sc = common_slice(lbl_c)
idx = sa.index.intersection(sc.index)
sa, sc = sa[idx], sc[idx]

# ── STEP 1: Total % change ─────────────────────────────────────────────────────
print("\n" + "=" * 72)
print(f"STEP 1 — Total A→C label change on common window ({COMMON_START} → {COMMON_END})")
print("=" * 72)

diffs = sa != sc
n_diff  = int(diffs.sum())
n_total = len(idx)
pct     = 100.0 * n_diff / n_total

print(f"\n  Total days in common window: {n_total}")
print(f"  Different labels:            {n_diff}")
print(f"  Pct change:                  {pct:.2f}%")
print(f"  CLAIMED:                     {CLAIMED_PCT_CHANGE}%")
print(f"  MATCH: {'YES' if abs(pct - CLAIMED_PCT_CHANGE) < 0.5 else 'NO — delta {:.2f}pp'.format(pct - CLAIMED_PCT_CHANGE)}")

# ── STEP 2: Flip type breakdown total ─────────────────────────────────────────
print("\n" + "=" * 72)
print("STEP 2 — Flip type breakdown (total, all years)")
print("=" * 72)

diff_df = pd.DataFrame({"A": sa[diffs], "C": sc[diffs]}, index=idx[diffs])
flip_counts = diff_df.groupby(["A", "C"]).size().rename("count").reset_index()

print(f"\n  {'A label':<10}  {'C label':<10}  {'Count':>7}  {'%':>7}")
print("-" * 42)
for _, row in flip_counts.sort_values("count", ascending=False).iterrows():
    pct_flip = 100.0 * row["count"] / n_diff
    print(f"  {row['A']:<10}  {row['C']:<10}  {row['count']:>7}  {pct_flip:>6.1f}%")

ns_total = int(diff_df[(diff_df["A"] == "Normal") & (diff_df["C"] == "Stress")].shape[0])
print(f"\n  Normal→Stress total: {ns_total}")
print(f"  CLAIMED total:       {CLAIMED_NORMAL_STRESS_TOTAL}")
print(f"  MATCH: {'YES' if abs(ns_total - CLAIMED_NORMAL_STRESS_TOTAL) <= 5 else 'NO — delta {}'.format(ns_total - CLAIMED_NORMAL_STRESS_TOTAL)}")

# ── STEP 3: Flip breakdown per year ───────────────────────────────────────────
print("\n" + "=" * 72)
print("STEP 3 — Normal→Stress flips per year (key claim: 83 of 101 in 2020+2022)")
print("=" * 72)

ns_df = diff_df[(diff_df["A"] == "Normal") & (diff_df["C"] == "Stress")].copy()
ns_df["year"] = ns_df.index.year

print(f"\n  {'Year':<6}  {'N→S flips':>10}  {'cumulative':>12}")
cum = 0
for y, grp in ns_df.groupby("year"):
    cnt = len(grp)
    cum += cnt
    print(f"  {y:<6}  {cnt:>10}  {cum:>12}")

ns_2020 = int((ns_df["year"] == 2020).sum())
ns_2022 = int((ns_df["year"] == 2022).sum())
ns_bear  = ns_2020 + ns_2022

print(f"\n  Normal→Stress in 2020:       {ns_2020}")
print(f"  Normal→Stress in 2022:       {ns_2022}")
print(f"  Total in bear years (20+22): {ns_bear}")
print(f"  Total Normal→Stress:         {ns_total}")
if ns_total > 0:
    bear_pct = 100.0 * ns_bear / ns_total
    print(f"  Pct in bear years:           {bear_pct:.1f}%")

print(f"\n  CLAIMED: {CLAIMED_NORMAL_STRESS_BEAR} of {CLAIMED_NORMAL_STRESS_TOTAL} in 2020+2022")
print(f"  MEASURED: {ns_bear} of {ns_total} in 2020+2022")
if abs(ns_bear - CLAIMED_NORMAL_STRESS_BEAR) <= 5 and abs(ns_total - CLAIMED_NORMAL_STRESS_TOTAL) <= 5:
    print("  VERDICT: CONFIRMED — per-year flip breakdown matches claim within tolerance.")
else:
    print(f"  VERDICT: DIFFERS — N→S bear {ns_bear} vs claim {CLAIMED_NORMAL_STRESS_BEAR}; "
          f"total {ns_total} vs claim {CLAIMED_NORMAL_STRESS_TOTAL}")

# ── STEP 4: All flip types per year ───────────────────────────────────────────
print("\n" + "=" * 72)
print("STEP 4 — All flip types per year (full breakdown for record)")
print("=" * 72)

diff_df["year"] = diff_df.index.year
for y, grp in diff_df.groupby("year"):
    counts = grp.groupby(["A", "C"]).size()
    parts  = "  ".join(f"{fr}→{to}:{cnt}" for (fr, to), cnt in counts.items())
    print(f"  {y}: total {len(grp)}  [{parts}]")

print("\n" + "=" * 72)
print("SUMMARY")
print("=" * 72)
print(f"  A→C pct change (measured):  {pct:.2f}%     claimed: {CLAIMED_PCT_CHANGE}%")
print(f"  Normal→Stress total:        {ns_total}         claimed: {CLAIMED_NORMAL_STRESS_TOTAL}")
print(f"  Normal→Stress in 2020+2022: {ns_bear}          claimed: {CLAIMED_NORMAL_STRESS_BEAR}")
