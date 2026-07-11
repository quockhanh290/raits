"""
verify_vault2025_labels.py
--------------------------
Đo: labels 2018-2024 giữa spy_daily.csv (frozen) vs spy_daily_live.csv có giống hệt không?

Usage:
    cd d:\raits
    python verify_vault2025_labels.py
"""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from futures._validated_core import benchmark_daily, label_regimes

FROZEN_CSV   = "spy_daily.csv"
VAULT_CSV    = "spy_daily_live.csv"
HMM_FIT_END  = "2024-12-31"
TRAIN_END    = "2018-01-01"
N_COMPONENTS = 3

print("=" * 60)
print("Label comparison: frozen vs vault2025")
print(f"  frozen : {FROZEN_CSV}")
print(f"  vault  : {VAULT_CSV}")
print(f"  fit_end: {HMM_FIT_END}  (both runs use same fit window)")
print("=" * 60)

print("\n[1] Loading CSVs...")
bench_frozen = benchmark_daily(FROZEN_CSV)
bench_vault  = benchmark_daily(VAULT_CSV)
print(f"  frozen: {len(bench_frozen)} rows, {bench_frozen.index[0].date()} → {bench_frozen.index[-1].date()}")
print(f"  vault : {len(bench_vault)}  rows, {bench_vault.index[0].date()} → {bench_vault.index[-1].date()}")

print(f"\n[2] label_regimes (frozen) ...")
labels_frozen = label_regimes(bench_frozen, TRAIN_END, N_COMPONENTS, HMM_FIT_END)
s_frozen = pd.Series(labels_frozen).sort_index()
print(f"  {len(s_frozen)} labels, last={s_frozen.index[-1].date()}")

print(f"\n[3] label_regimes (vault2025) ...")
labels_vault = label_regimes(bench_vault, TRAIN_END, N_COMPONENTS, HMM_FIT_END)
s_vault = pd.Series(labels_vault).sort_index()
print(f"  {len(s_vault)} labels, last={s_vault.index[-1].date()}")

# Compare only 2018-2024 overlap
cutoff = pd.Timestamp("2024-12-31")
frozen_2024 = s_frozen[s_frozen.index <= cutoff]
vault_2024  = s_vault[s_vault.index <= cutoff]

# Align on common dates
common = frozen_2024.index.intersection(vault_2024.index)
f_aligned = frozen_2024.loc[common]
v_aligned = vault_2024.loc[common]

mismatches = f_aligned[f_aligned != v_aligned]

print(f"\n[4] Comparison 2018-2024:")
print(f"  Common dates : {len(common)}")
print(f"  Matches      : {(f_aligned == v_aligned).sum()}")
print(f"  MISMATCHES   : {len(mismatches)}")

if len(mismatches) == 0:
    print("\n  RESULT: IDENTICAL — labels 2018-2024 không đổi khi thêm 2025-2026 data.")
    print("  Baseline an toàn. vault2025.csv safe cho decode-forward.")
else:
    print(f"\n  RESULT: {len(mismatches)} MISMATCHES — global dependency detected!")
    print(mismatches.head(20).to_string())
    print("  => KHÔNG dùng vault2025 cho live cho tới khi điều tra.")

# Extra: show new 2025-2026 labels from vault
vault_2025plus = s_vault[s_vault.index > cutoff]
print(f"\n[5] New 2025-2026 labels (decode-forward, không carry-forward):")
print(f"  {len(vault_2025plus)} ngày mới có label thật")
if len(vault_2025plus) > 0:
    dist = vault_2025plus.value_counts()
    print(f"  Distribution:\n{dist.to_string()}")
    print(f"\n  5 ngày gần nhất:")
    print(vault_2025plus.tail(5).to_string())
