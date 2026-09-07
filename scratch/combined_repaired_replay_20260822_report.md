# Combined Repaired Replay - 2026-08-22

Scratch-only repair/re-measure after stop/risk audit blockers.

Repairs applied:

- Stress same-symbol override removes both Normal-R4 and Calm A from survivors before admission; no double settlement.
- Normal-R4 is suppressed if same-symbol Calm A or Stress is already open.
- Calm-NKD forced close is repriced onto the current-NKD artifact price scale using measured constant offsets.
- Calm A uses ATR15 disaster-stop trades and true stop-risk.

Still not repaired here: Calm-NKD risk definition. Rows with Calm-NKD switch remain research-only until that sleeve is regenerated with true stop-at-entry risk.

## floor

| policy | family_cap | R4 taken/rej | Calm taken/rej | Stress taken/rej | NKD taken/rej | family_rej | stress_closed_calm | supp_norm | supp_calm | calm_nkd_closes | calm_switch_delta | double_booked | net | pf | sharpe | calmar | maxdd | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| repaired_mechanics_independent_caps | none | 546/187 | 342/0 | 49/1 | 758/0 | 0 | 4 | 17 | 7 | 45 | $1,790 | 0 | $75,288 | 1.68 | 2.14 | 2.17 | $4,973 | 2 |
| repaired_mechanics_family_cap_5_44 | 5.0%/4.4% | 545/190 | 338/4 | 49/1 | 758/0 | 5 | 4 | 15 | 7 | 45 | $1,790 | 0 | $74,410 | 1.67 | 2.12 | 2.14 | $4,973 | 2 |
| repaired_mechanics_family_cap_7p5 | 7.5%/7.5% | 546/187 | 342/0 | 49/1 | 758/0 | 0 | 4 | 17 | 7 | 45 | $1,790 | 0 | $75,288 | 1.68 | 2.14 | 2.17 | $4,973 | 2 |
| risk_clean_no_calm_nkd_family_cap_5_44 | 5.0%/4.4% | 545/190 | 338/4 | 49/1 | 228/0 | 5 | 4 | 15 | 7 | 0 | $0 | 0 | $64,903 | 1.62 | 2.34 | 1.92 | $4,845 | 2 |
| risk_clean_no_calm_nkd_family_cap_7p5 | 7.5%/7.5% | 546/187 | 342/0 | 49/1 | 228/0 | 0 | 4 | 17 | 7 | 0 | $0 | 0 | $65,781 | 1.62 | 2.37 | 1.94 | $4,845 | 2 |

## vault2025

| policy | family_cap | R4 taken/rej | Calm taken/rej | Stress taken/rej | NKD taken/rej | family_rej | stress_closed_calm | supp_norm | supp_calm | calm_nkd_closes | calm_switch_delta | double_booked | net | pf | sharpe | calmar | maxdd | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| repaired_mechanics_independent_caps | none | 55/48 | 42/0 | 3/0 | 117/0 | 0 | 0 | 2 | 2 | 7 | $-5 | 0 | $17,113 | 2.25 | 2.77 | 4.48 | $3,901 | 0 |
| repaired_mechanics_family_cap_5_44 | 5.0%/4.4% | 55/48 | 39/3 | 3/0 | 117/0 | 3 | 0 | 2 | 2 | 7 | $-5 | 0 | $16,997 | 2.26 | 2.76 | 4.45 | $3,901 | 0 |
| repaired_mechanics_family_cap_7p5 | 7.5%/7.5% | 55/48 | 41/1 | 3/0 | 117/0 | 1 | 0 | 2 | 2 | 7 | $-5 | 0 | $16,868 | 2.24 | 2.74 | 4.41 | $3,901 | 0 |
| risk_clean_no_calm_nkd_family_cap_5_44 | 5.0%/4.4% | 55/48 | 39/3 | 3/0 | 31/0 | 3 | 0 | 2 | 2 | 0 | $0 | 0 | $13,236 | 2.00 | 2.96 | 3.09 | $4,632 | 0 |
| risk_clean_no_calm_nkd_family_cap_7p5 | 7.5%/7.5% | 55/48 | 41/1 | 3/0 | 31/0 | 1 | 0 | 2 | 2 | 0 | $0 | 0 | $13,107 | 1.98 | 2.90 | 3.06 | $4,632 | 0 |

## vault2026

| policy | family_cap | R4 taken/rej | Calm taken/rej | Stress taken/rej | NKD taken/rej | family_rej | stress_closed_calm | supp_norm | supp_calm | calm_nkd_closes | calm_switch_delta | double_booked | net | pf | sharpe | calmar | maxdd | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| repaired_mechanics_independent_caps | none | 46/35 | 26/1 | 3/1 | 62/3 | 0 | 0 | 0 | 1 | 5 | $-3,172 | 0 | $9,779 | 1.65 | 2.57 | 3.59 | $4,342 | 0 |
| repaired_mechanics_family_cap_5_44 | 5.0%/4.4% | 45/36 | 19/8 | 3/1 | 62/3 | 10 | 0 | 0 | 1 | 5 | $-3,172 | 0 | $9,288 | 1.62 | 2.47 | 3.41 | $4,342 | 0 |
| repaired_mechanics_family_cap_7p5 | 7.5%/7.5% | 46/35 | 24/3 | 3/1 | 62/3 | 2 | 0 | 0 | 1 | 5 | $-3,172 | 0 | $9,853 | 1.65 | 2.59 | 3.62 | $4,342 | 0 |
| risk_clean_no_calm_nkd_family_cap_5_44 | 5.0%/4.4% | 45/36 | 19/8 | 3/1 | 24/2 | 10 | 0 | 0 | 1 | 0 | $0 | 0 | $8,260 | 1.55 | 2.57 | 2.75 | $4,797 | 0 |
| risk_clean_no_calm_nkd_family_cap_7p5 | 7.5%/7.5% | 46/35 | 24/3 | 3/1 | 24/2 | 2 | 0 | 0 | 1 | 0 | $0 | 0 | $8,825 | 1.58 | 2.69 | 2.93 | $4,797 | 0 |
