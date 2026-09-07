# Stress Switch Full Cap/Breaker Replay - 2026-08-22

Scratch-only. No production code modified.

Base book: `normal_promotion_trades_*_20260821.json`, bucket `filtered`, R4 only (MES/MNQ/MYM/M2K), NKD excluded.

Switch semantics measured here:

- if Stress is rejected by cap/breaker, existing Normal is left alone;
- if Stress is admissible, same-symbol Normal is closed at Stress entry open and Stress enters;
- if Normal later tries to enter a symbol while Stress is still open on that symbol, that Normal entry is suppressed;
- replay is intraday for entry/exit/switch order, while cap math uses the existing `MultiClusterGuard` and account breaker.

Caveat: this is still a scratch harness around captured Normal trades, not a production patch.

## floor

Base Normal-R4 filtered replay: trades attempted 752, taken 546, rejected 206, net $29,046, ret 58.1%, PF 1.49, Sharpe 2.25, Calmar 0.68, MaxDD $6,209.

| scenario | stress_cap | stress_legs | stress_taken | stress_rej | normal_taken | normal_rej | closed | blocked_late_normal | net | ret | pf | sharpe | calmar | maxdd | dd_delta | switch_delta | removed_normal | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_only_g3_q7 | 2.5% | 50 | 6 | 44 | 546 | 206 | 2 | 0 | $32,579 | 65.2% | 1.55 | 2.48 | 0.77 | $6,209 | $0 | $441 | $0 | 0 |
| mnq_only_g3_q7 | 5.0% | 50 | 32 | 18 | 549 | 197 | 8 | 4 | $46,189 | 92.4% | 1.74 | 2.99 | 1.31 | $5,151 | $-1,058 | $2,277 | $2,690 | 2 |
| mnq_only_g3_q7 | 7.5% | 50 | 47 | 3 | 551 | 192 | 11 | 7 | $49,724 | 99.4% | 1.72 | 2.85 | 1.09 | $6,646 | $437 | $1,279 | $1,723 | 2 |
| mnq_only_g3_q7 | 10.0% | 50 | 49 | 1 | 551 | 192 | 11 | 7 | $52,139 | 104.3% | 1.75 | 2.97 | 1.15 | $6,646 | $437 | $1,279 | $1,723 | 2 |
| r4_basket_g3_q1each | 2.5% | 202 | 201 | 1 | 536 | 192 | 42 | 24 | $33,085 | 66.2% | 1.56 | 2.49 | 0.75 | $6,459 | $250 | $2,286 | $2,106 | 0 |
| r4_basket_g3_q1each | 5.0% | 202 | 202 | 0 | 536 | 192 | 42 | 24 | $32,740 | 65.5% | 1.55 | 2.46 | 0.74 | $6,459 | $250 | $2,286 | $2,106 | 0 |
| r4_basket_g3_q1each | 7.5% | 202 | 202 | 0 | 536 | 192 | 42 | 24 | $32,740 | 65.5% | 1.55 | 2.46 | 0.74 | $6,459 | $250 | $2,286 | $2,106 | 0 |
| r4_basket_g3_q1each | 10.0% | 202 | 202 | 0 | 536 | 192 | 42 | 24 | $32,740 | 65.5% | 1.55 | 2.46 | 0.74 | $6,459 | $250 | $2,286 | $2,106 | 0 |
| r4_basket_g3_q2each | 2.5% | 202 | 153 | 49 | 542 | 193 | 32 | 17 | $35,066 | 70.1% | 1.53 | 2.42 | 0.95 | $5,425 | $-784 | $1,674 | $3,241 | 0 |
| r4_basket_g3_q2each | 5.0% | 202 | 201 | 1 | 536 | 192 | 42 | 24 | $39,518 | 79.0% | 1.60 | 2.63 | 0.75 | $7,709 | $1,500 | $2,286 | $2,106 | 0 |
| r4_basket_g3_q2each | 7.5% | 202 | 202 | 0 | 536 | 192 | 42 | 24 | $38,828 | 77.7% | 1.58 | 2.58 | 0.74 | $7,709 | $1,500 | $2,286 | $2,106 | 0 |
| r4_basket_g3_q2each | 10.0% | 202 | 202 | 0 | 536 | 192 | 42 | 24 | $38,828 | 77.7% | 1.58 | 2.58 | 0.74 | $7,709 | $1,500 | $2,286 | $2,106 | 0 |

## vault2025

Base Normal-R4 filtered replay: trades attempted 105, taken 55, rejected 50, net $5,395, ret 10.8%, PF 1.58, Sharpe 1.94, Calmar 1.56, MaxDD $3,768.

| scenario | stress_cap | stress_legs | stress_taken | stress_rej | normal_taken | normal_rej | closed | blocked_late_normal | net | ret | pf | sharpe | calmar | maxdd | dd_delta | switch_delta | removed_normal | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_only_g3_q7 | 2.5% | 3 | 0 | 3 | 55 | 50 | 0 | 0 | $5,395 | 10.8% | 1.58 | 1.94 | 1.56 | $3,768 | $0 | $0 | $0 | 0 |
| mnq_only_g3_q7 | 5.0% | 3 | 0 | 3 | 55 | 50 | 0 | 0 | $5,395 | 10.8% | 1.58 | 1.94 | 1.56 | $3,768 | $0 | $0 | $0 | 0 |
| mnq_only_g3_q7 | 7.5% | 3 | 2 | 1 | 55 | 50 | 1 | 0 | $10,329 | 20.7% | 2.42 | 3.59 | 3.17 | $3,540 | $-228 | $241 | $0 | 0 |
| mnq_only_g3_q7 | 10.0% | 3 | 3 | 0 | 55 | 50 | 1 | 0 | $10,167 | 20.3% | 2.37 | 3.49 | 3.12 | $3,540 | $-228 | $241 | $0 | 0 |
| r4_basket_g3_q1each | 2.5% | 15 | 14 | 1 | 55 | 50 | 5 | 0 | $4,488 | 9.0% | 1.67 | 3.04 | 1.23 | $3,975 | $207 | $-2,544 | $0 | 0 |
| r4_basket_g3_q1each | 5.0% | 15 | 15 | 0 | 55 | 50 | 5 | 0 | $4,465 | 8.9% | 1.66 | 3.02 | 1.22 | $3,975 | $207 | $-2,544 | $0 | 0 |
| r4_basket_g3_q1each | 7.5% | 15 | 15 | 0 | 55 | 50 | 5 | 0 | $4,465 | 8.9% | 1.66 | 3.02 | 1.22 | $3,975 | $207 | $-2,544 | $0 | 0 |
| r4_basket_g3_q1each | 10.0% | 15 | 15 | 0 | 55 | 50 | 5 | 0 | $4,465 | 8.9% | 1.66 | 3.02 | 1.22 | $3,975 | $207 | $-2,544 | $0 | 0 |
| r4_basket_g3_q2each | 2.5% | 15 | 10 | 5 | 55 | 50 | 4 | 0 | $8,026 | 16.1% | 1.96 | 3.45 | 1.98 | $4,410 | $642 | $601 | $0 | 0 |
| r4_basket_g3_q2each | 5.0% | 15 | 14 | 1 | 55 | 50 | 5 | 0 | $6,125 | 12.3% | 1.86 | 3.47 | 1.51 | $4,410 | $642 | $-2,544 | $0 | 0 |
| r4_basket_g3_q2each | 7.5% | 15 | 15 | 0 | 55 | 50 | 5 | 0 | $6,079 | 12.2% | 1.85 | 3.45 | 1.50 | $4,410 | $642 | $-2,544 | $0 | 0 |
| r4_basket_g3_q2each | 10.0% | 15 | 15 | 0 | 55 | 50 | 5 | 0 | $6,079 | 12.2% | 1.85 | 3.45 | 1.50 | $4,410 | $642 | $-2,544 | $0 | 0 |

## vault2026

Base Normal-R4 filtered replay: trades attempted 81, taken 46, rejected 35, net $1,059, ret 2.1%, PF 1.16, Sharpe 0.87, Calmar 0.47, MaxDD $4,075.

| scenario | stress_cap | stress_legs | stress_taken | stress_rej | normal_taken | normal_rej | closed | blocked_late_normal | net | ret | pf | sharpe | calmar | maxdd | dd_delta | switch_delta | removed_normal | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_only_g3_q7 | 2.5% | 4 | 0 | 4 | 46 | 35 | 0 | 0 | $1,059 | 2.1% | 1.16 | 0.87 | 0.47 | $4,075 | $0 | $0 | $0 | 0 |
| mnq_only_g3_q7 | 5.0% | 4 | 0 | 4 | 46 | 35 | 0 | 0 | $1,059 | 2.1% | 1.16 | 0.87 | 0.47 | $4,075 | $0 | $0 | $0 | 0 |
| mnq_only_g3_q7 | 7.5% | 4 | 1 | 3 | 46 | 35 | 0 | 0 | $2,688 | 5.4% | 1.40 | 1.97 | 1.33 | $3,656 | $-419 | $0 | $0 | 0 |
| mnq_only_g3_q7 | 10.0% | 4 | 3 | 1 | 46 | 35 | 0 | 0 | $1,890 | 3.8% | 1.24 | 1.21 | 0.93 | $3,656 | $-419 | $0 | $0 | 0 |
| r4_basket_g3_q1each | 2.5% | 16 | 14 | 2 | 47 | 34 | 5 | 0 | $2,153 | 4.3% | 1.41 | 2.00 | 1.31 | $2,980 | $-1,094 | $699 | $0 | 0 |
| r4_basket_g3_q1each | 5.0% | 16 | 16 | 0 | 47 | 34 | 5 | 0 | $1,794 | 3.6% | 1.32 | 1.63 | 0.97 | $3,340 | $-735 | $699 | $0 | 0 |
| r4_basket_g3_q1each | 7.5% | 16 | 16 | 0 | 47 | 34 | 5 | 0 | $1,794 | 3.6% | 1.32 | 1.63 | 0.97 | $3,340 | $-735 | $699 | $0 | 0 |
| r4_basket_g3_q1each | 10.0% | 16 | 16 | 0 | 47 | 34 | 5 | 0 | $1,794 | 3.6% | 1.32 | 1.63 | 0.97 | $3,340 | $-735 | $699 | $0 | 0 |
| r4_basket_g3_q2each | 2.5% | 16 | 7 | 9 | 46 | 35 | 2 | 0 | $2,604 | 5.2% | 1.44 | 2.12 | 1.29 | $3,656 | $-419 | $644 | $0 | 0 |
| r4_basket_g3_q2each | 5.0% | 16 | 14 | 2 | 47 | 34 | 5 | 0 | $2,633 | 5.3% | 1.54 | 2.48 | 1.90 | $2,500 | $-1,575 | $699 | $0 | 0 |
| r4_basket_g3_q2each | 7.5% | 16 | 16 | 0 | 47 | 34 | 5 | 0 | $1,914 | 3.8% | 1.34 | 1.71 | 1.08 | $3,219 | $-856 | $699 | $0 | 0 |
| r4_basket_g3_q2each | 10.0% | 16 | 16 | 0 | 47 | 34 | 5 | 0 | $1,914 | 3.8% | 1.34 | 1.71 | 1.08 | $3,219 | $-856 | $699 | $0 | 0 |
