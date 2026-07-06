"""
debug_vault_labels.py — why did Gate 5 produce 0 trades?
Distinguishes: (A) genuinely no Stress days labeled in the vault window,
vs (B) a date-alignment bug between SPY labels and instrument days.
Read-only.

    python debug_vault_labels.py --parquet NQ_8y.parquet --regime-csv spy_daily.csv \
        --hmm-train-end 2018-01-01 --hmm-fit-end 2024-12-31 --vault-start 2023-01-01
"""
import argparse, sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path.cwd()))

ap = argparse.ArgumentParser()
ap.add_argument("--parquet", required=True)
ap.add_argument("--regime-csv", required=True)
ap.add_argument("--hmm-train-end", default="2018-01-01")
ap.add_argument("--hmm-fit-end", default="2024-12-31")
ap.add_argument("--vault-start", default="2023-01-01")
ap.add_argument("--hmm-components", type=int, default=3)
a = ap.parse_args()

import gate2_edge_harness as G

df = G.load_parquet(a.parquet)
daily = G.benchmark_daily(a.regime_csv)
labels = G.label_regimes(daily, a.hmm_train_end, a.hmm_components, a.hmm_fit_end)
vstart = pd.Timestamp(a.vault_start)

# 1. label distribution in the vault window (from SPY labeling)
vault_labels = {k: v for k, v in labels.items() if k >= vstart}
dist = pd.Series(list(vault_labels.values())).value_counts()
print(f"\n[A-check] SPY labels in vault ({vstart.date()}+): {len(vault_labels)} labelled days")
print(dist.to_string())
print(f"  → Stress days in vault: {dist.get('Stress', 0)}")

# 2. date-alignment check: how many NQ trading days in vault have a label
nq_days = sorted({pd.Timestamp(d).tz_localize(None).normalize()
                  for d in df.index.normalize() if pd.Timestamp(d).tz_localize(None) >= vstart})
matched = sum(1 for d in nq_days if d in labels)
print(f"\n[B-check] NQ vault trading days: {len(nq_days)} | with a matching SPY label: {matched}")
if nq_days:
    print(f"  sample NQ days:  {[str(d.date()) for d in nq_days[:3]]}")
    lbl_days = sorted(vault_labels.keys())
    print(f"  sample label days: {[str(d.date()) for d in lbl_days[:3]]}")
    nq_stress = [d for d in nq_days if labels.get(d) == 'Stress']
    print(f"  NQ vault days labelled Stress: {len(nq_stress)}  {[str(x.date()) for x in nq_stress[:8]]}")

print("\nVERDICT:")
if matched < len(nq_days) * 0.8:
    print("  [B] DATE MISALIGNMENT — labels not matching NQ days. Bug in date keys.")
elif dist.get('Stress', 0) == 0:
    print("  [A] NO BUG — zero Stress days labelled in 2023-2024 under this HMM fit.")
    print("      2023-24 simply wasn't stressful by 2017-2022 standards. STRESS_MID")
    print("      correctly had nothing to trade. Vault can't judge it → need a vault")
    print("      window that contains stress, OR accept it's a conditional edge.")
else:
    print(f"  Stress days exist ({dist.get('Stress',0)}) and dates align — 0 trades is a")
    print("      STRESS_MID signal-logic issue (entry filter), investigate run_day.")
