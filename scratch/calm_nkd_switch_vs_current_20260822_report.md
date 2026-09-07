# Calm-NKD Switch vs Current NKD - 2026-08-22

Scratch-only. Base includes Normal-R4 filtered and Stress-MNQ `mnq_only_g3_q7` cap 10%. This tests Candidate B as replacement and as a switch override of the existing NKD sleeve.

Switch mode: if Calm-NKD is admitted, close any open current MNKD position at the Calm-NKD entry price, enter Calm-NKD, and suppress current NKD entries while Calm-NKD remains open.

## floor

| mode | current_nkd_trades | calm_nkd_trades | R4 taken/rej | Stress taken/rej | NKD taken/rej | calm_closed_current | calm_switch_delta | suppressed_current | suppressed_current_pnl | net | ret | pf | sharpe | calmar | maxdd | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current_nkd | 228 | 0 | 551/192 | 49/1 | 228/0 | 0 | $0 | 0 | $0 | $56,037 | 112.1% | 1.61 | 2.45 | 1.67 | $4,893 | 2 |
| calm_nkd_replacement | 0 | 550 | 551/192 | 49/1 | 550/0 | 0 | $0 | 0 | $0 | $59,295 | 118.6% | 1.73 | 2.07 | 1.27 | $6,691 | 2 |
| current_nkd_plus_calm_switch | 228 | 550 | 551/192 | 49/1 | 758/0 | 45 | $340 | 20 | $-561 | $64,094 | 128.2% | 1.64 | 1.93 | 1.74 | $5,274 | 2 |

## vault2025

| mode | current_nkd_trades | calm_nkd_trades | R4 taken/rej | Stress taken/rej | NKD taken/rej | calm_closed_current | calm_switch_delta | suppressed_current | suppressed_current_pnl | net | ret | pf | sharpe | calmar | maxdd | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current_nkd | 31 | 0 | 55/50 | 3/0 | 31/0 | 0 | $0 | 0 | $0 | $12,370 | 24.7% | 1.99 | 3.23 | 2.80 | $4,792 | 0 |
| calm_nkd_replacement | 0 | 90 | 55/50 | 3/0 | 90/0 | 0 | $0 | 0 | $0 | $12,644 | 25.3% | 2.25 | 2.44 | 3.57 | $3,611 | 0 |
| current_nkd_plus_calm_switch | 31 | 90 | 55/50 | 3/0 | 117/0 | 7 | $30 | 4 | $-1,289 | $16,166 | 32.3% | 2.23 | 2.70 | 4.07 | $4,057 | 0 |

## vault2026

| mode | current_nkd_trades | calm_nkd_trades | R4 taken/rej | Stress taken/rej | NKD taken/rej | calm_closed_current | calm_switch_delta | suppressed_current | suppressed_current_pnl | net | ret | pf | sharpe | calmar | maxdd | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current_nkd | 26 | 0 | 46/35 | 3/1 | 24/2 | 0 | $0 | 0 | $0 | $7,898 | 15.8% | 1.59 | 2.89 | 2.93 | $4,877 | 0 |
| calm_nkd_replacement | 0 | 44 | 46/35 | 3/1 | 43/1 | 0 | $0 | 0 | $0 | $3,573 | 7.1% | 1.33 | 1.39 | 1.60 | $3,656 | 0 |
| current_nkd_plus_calm_switch | 26 | 44 | 46/35 | 3/1 | 62/3 | 5 | $-3,172 | 5 | $-2,518 | $8,926 | 17.9% | 1.65 | 2.58 | 3.37 | $4,342 | 0 |
