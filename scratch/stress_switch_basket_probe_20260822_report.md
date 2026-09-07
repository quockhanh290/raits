# Stress Switch Basket Probe - 2026-08-22

Scratch-only. No production code modified.

Question: what if Stress trades the whole R4 basket instead of MNQ only?

Policy: close existing same-symbol Normal/Calm position at Stress entry timestamp, then allow Stress on that symbol.

Scenarios:

- `mnq_only_g3_q7`: MNQ only, qty 7.
- `r4_basket_g3_q1each`: MES/MNQ/MYM/M2K, qty 1 each.
- `r4_basket_g3_q2each`: MES/MNQ/MYM/M2K, qty 2 each.

## floor

| scenario | legs | trade_days | qty_each | margin_est | switched_existing | switch_delta | stress_net | base_maxdd | switched_base_maxdd | combined_net | combined_maxdd | maxdd_delta | bad20_stress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_only_g3_q7 | 50 | 50 | 7 | $15,400 | 28 | $836 | $23,749 | $16,230 | $15,474 | $65,014 | $12,299 | $-3,931 | $0 |
| r4_basket_g3_q1each | 202 | 61 | 1 | $5,300 | 86 | $1,313 | $6,088 | $16,230 | $16,160 | $47,829 | $14,537 | $-1,693 | $0 |
| r4_basket_g3_q2each | 202 | 61 | 2 | $10,600 | 86 | $1,313 | $12,176 | $16,230 | $16,160 | $53,918 | $13,855 | $-2,376 | $0 |

## vault2025

| scenario | legs | trade_days | qty_each | margin_est | switched_existing | switch_delta | stress_net | base_maxdd | switched_base_maxdd | combined_net | combined_maxdd | maxdd_delta | bad20_stress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_only_g3_q7 | 3 | 3 | 7 | $15,400 | 2 | $1,285 | $4,531 | $9,457 | $8,413 | $16,558 | $7,870 | $-1,586 | $0 |
| r4_basket_g3_q1each | 15 | 6 | 1 | $5,300 | 9 | $428 | $1,614 | $9,457 | $7,703 | $12,784 | $8,138 | $-1,319 | $0 |
| r4_basket_g3_q2each | 15 | 6 | 2 | $10,600 | 9 | $428 | $3,228 | $9,457 | $7,703 | $14,399 | $8,573 | $-884 | $0 |

## vault2026

| scenario | legs | trade_days | qty_each | margin_est | switched_existing | switch_delta | stress_net | base_maxdd | switched_base_maxdd | combined_net | combined_maxdd | maxdd_delta | bad20_stress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_only_g3_q7 | 4 | 4 | 7 | $15,400 | 4 | $2,012 | $-406 | $16,579 | $14,566 | $6,328 | $14,972 | $-1,606 | $-2,516 |
| r4_basket_g3_q1each | 16 | 4 | 1 | $5,300 | 16 | $4,122 | $121 | $16,579 | $12,457 | $8,964 | $12,336 | $-4,243 | $-428 |
| r4_basket_g3_q2each | 16 | 4 | 2 | $10,600 | 16 | $4,122 | $242 | $16,579 | $12,457 | $9,085 | $12,215 | $-4,364 | $-856 |

## Verdict

- Basket Stress is only interesting if it improves combined MaxDD and OOS without requiring unrealistic margin or excessive switching.
- Compare against MNQ-only 7x, which is the current switch-policy benchmark.