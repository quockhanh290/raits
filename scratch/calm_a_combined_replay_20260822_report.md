# Calm A Combined Replay - 2026-08-22

Scratch-only. Base includes Normal-R4 filtered, Stress-MNQ `mnq_only_g3_q7` cap 10%, and current NKD + Calm-NKD switch challenger. Candidate A is `Calm PCLoc bottom-down not-deep-gap` as `roska4_calm`.

Calm cap uses ATR risk proxy (`daily_ATR * 2.5 * point_value`) because Candidate A has no explicit stop.

## floor

| policy | overlap | calm_cap | slip | Calm attempted | Calm taken/rej | Calm suppressed | Stress closed Calm | NKD taken/rej | net | ret | pf | sharpe | calmar | maxdd | halts | audit_bad |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| skip_cap0.015_slip2 | skip_same_symbol | 1.5% | 2 | 349 | 183/159 | 7 | 2 | 758/0 | $66,886 | 133.8% | 1.64 | 1.94 | 1.94 | $4,923 | 2 | 0 |
| skip_cap0.025_slip2 | skip_same_symbol | 2.5% | 2 | 349 | 255/87 | 7 | 3 | 758/0 | $67,586 | 135.2% | 1.62 | 1.93 | 1.96 | $4,923 | 2 | 0 |
| skip_cap0.05_slip2 | skip_same_symbol | 5.0% | 2 | 349 | 335/7 | 7 | 4 | 758/0 | $72,732 | 145.5% | 1.65 | 2.06 | 2.11 | $4,923 | 2 | 0 |
| stress_override_cap025_slip2 | stress_overrides_calm | 2.5% | 2 | 349 | 255/87 | 7 | 3 | 758/0 | $67,972 | 135.9% | 1.62 | 1.95 | 1.98 | $4,923 | 2 | 0 |
| stack_cap025_slip2 | stack_allowed | 2.5% | 2 | 349 | 259/90 | 0 | 3 | 758/0 | $67,424 | 134.8% | 1.61 | 1.93 | 1.96 | $4,923 | 2 | 0 |
| skip_cap025_slip3 | skip_same_symbol | 2.5% | 3 | 349 | 255/87 | 7 | 3 | 758/0 | $67,164 | 134.3% | 1.61 | 1.92 | 1.95 | $4,923 | 2 | 0 |
| skip_cap025_slip4 | skip_same_symbol | 2.5% | 4 | 349 | 255/87 | 7 | 3 | 758/0 | $66,743 | 133.5% | 1.61 | 1.91 | 1.94 | $4,923 | 2 | 0 |
| skip_cap025_slip6 | skip_same_symbol | 2.5% | 6 | 349 | 255/87 | 7 | 3 | 758/0 | $65,900 | 131.8% | 1.60 | 1.88 | 1.91 | $4,923 | 2 | 0 |

## vault2025

| policy | overlap | calm_cap | slip | Calm attempted | Calm taken/rej | Calm suppressed | Stress closed Calm | NKD taken/rej | net | ret | pf | sharpe | calmar | maxdd | halts | audit_bad |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| skip_cap0.015_slip2 | skip_same_symbol | 1.5% | 2 | 44 | 11/31 | 2 | 0 | 117/0 | $16,483 | 33.0% | 2.25 | 2.73 | 4.15 | $4,057 | 0 | 0 |
| skip_cap0.025_slip2 | skip_same_symbol | 2.5% | 2 | 44 | 25/17 | 2 | 0 | 117/0 | $16,889 | 33.8% | 2.26 | 2.72 | 4.29 | $4,014 | 0 | 0 |
| skip_cap0.05_slip2 | skip_same_symbol | 5.0% | 2 | 44 | 38/4 | 2 | 0 | 117/0 | $17,881 | 35.8% | 2.32 | 2.85 | 4.63 | $3,943 | 0 | 0 |
| stress_override_cap025_slip2 | stress_overrides_calm | 2.5% | 2 | 44 | 25/17 | 2 | 0 | 117/0 | $16,889 | 33.8% | 2.26 | 2.72 | 4.29 | $4,014 | 0 | 0 |
| stack_cap025_slip2 | stack_allowed | 2.5% | 2 | 44 | 25/19 | 0 | 0 | 117/0 | $16,889 | 33.8% | 2.26 | 2.72 | 4.29 | $4,014 | 0 | 0 |
| skip_cap025_slip3 | skip_same_symbol | 2.5% | 3 | 44 | 25/17 | 2 | 0 | 117/0 | $16,831 | 33.7% | 2.25 | 2.72 | 4.27 | $4,019 | 0 | 0 |
| skip_cap025_slip4 | skip_same_symbol | 2.5% | 4 | 44 | 25/17 | 2 | 0 | 117/0 | $16,773 | 33.5% | 2.24 | 2.71 | 4.25 | $4,024 | 0 | 0 |
| skip_cap025_slip6 | skip_same_symbol | 2.5% | 6 | 44 | 25/17 | 2 | 0 | 117/0 | $16,657 | 33.3% | 2.23 | 2.69 | 4.21 | $4,034 | 0 | 0 |

## vault2026

| policy | overlap | calm_cap | slip | Calm attempted | Calm taken/rej | Calm suppressed | Stress closed Calm | NKD taken/rej | net | ret | pf | sharpe | calmar | maxdd | halts | audit_bad |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| skip_cap0.015_slip2 | skip_same_symbol | 1.5% | 2 | 28 | 0/27 | 1 | 0 | 62/3 | $8,926 | 17.9% | 1.65 | 2.58 | 3.37 | $4,342 | 0 | 0 |
| skip_cap0.025_slip2 | skip_same_symbol | 2.5% | 2 | 28 | 12/15 | 1 | 0 | 62/3 | $8,881 | 17.8% | 1.63 | 2.45 | 3.26 | $4,342 | 0 | 0 |
| skip_cap0.05_slip2 | skip_same_symbol | 5.0% | 2 | 28 | 15/12 | 1 | 0 | 62/3 | $10,132 | 20.3% | 1.72 | 2.77 | 3.72 | $4,342 | 0 | 0 |
| stress_override_cap025_slip2 | stress_overrides_calm | 2.5% | 2 | 28 | 12/15 | 1 | 0 | 62/3 | $8,881 | 17.8% | 1.63 | 2.45 | 3.26 | $4,342 | 0 | 0 |
| stack_cap025_slip2 | stack_allowed | 2.5% | 2 | 28 | 13/15 | 0 | 0 | 62/3 | $8,857 | 17.7% | 1.62 | 2.44 | 3.25 | $4,342 | 0 | 0 |
| skip_cap025_slip3 | skip_same_symbol | 2.5% | 3 | 28 | 12/15 | 1 | 0 | 62/3 | $8,851 | 17.7% | 1.62 | 2.44 | 3.25 | $4,342 | 0 | 0 |
| skip_cap025_slip4 | skip_same_symbol | 2.5% | 4 | 28 | 12/15 | 1 | 0 | 62/3 | $8,821 | 17.6% | 1.62 | 2.43 | 3.24 | $4,342 | 0 | 0 |
| skip_cap025_slip6 | skip_same_symbol | 2.5% | 6 | 28 | 12/15 | 1 | 0 | 62/3 | $8,761 | 17.5% | 1.61 | 2.41 | 3.22 | $4,342 | 0 | 0 |
