# Stress Payoff / Sizing Probe - 2026-08-21

Scratch-only. No production code modified.

Purpose: test whether the best ex-2026 Stress candidates are thin because the signal is weak, or because 1-micro payoff is too small.

Assumptions:

- Synthetic scaling multiplies the same micro fills/PnL by N contracts.
- This is not a liquidity model and not a production sizing rule.
- $50k account, target DD 10% ($5k), hard DD 15% ($7.5k), margin budget 40% ($20k).
- 2026 remains sanity-only per the current Stress gate.

## target_gapcont_10:30_b4_g2_mnq_rr15_x1555

1x instruments: MNQ
1x trades: 68, net $4,046, max single loss $-478, median stop $-232

| scale | floor_net | floor_maxdd | dd_pct | margin | margin_pct | target_ok | hard_ok | 2025 | 2026_sanity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1x | $4,046 | $933 | 1.9% | $2,200 | 4% | True | True | $647 | $-561 |
| 2x | $8,093 | $1,866 | 3.7% | $4,400 | 9% | True | True | $1,295 | $-1,123 |
| 3x | $12,139 | $2,799 | 5.6% | $6,600 | 13% | True | True | $1,942 | $-1,684 |
| 4x | $16,185 | $3,732 | 7.5% | $8,800 | 18% | True | True | $2,589 | $-2,246 |
| 5x | $20,232 | $4,665 | 9.3% | $11,000 | 22% | True | True | $3,236 | $-2,807 |
| 6x | $24,278 | $5,598 | 11.2% | $13,200 | 26% | False | True | $3,884 | $-3,369 |
| 7x | $28,325 | $6,531 | 13.1% | $15,400 | 31% | False | True | $4,531 | $-3,930 |
| 8x | $32,371 | $7,464 | 14.9% | $17,600 | 35% | False | True | $5,178 | $-4,491 |
| 9x | $36,417 | $8,398 | 16.8% | $19,800 | 40% | False | False | $5,826 | $-5,053 |
| 10x | $40,464 | $9,331 | 18.7% | $22,000 | 44% | False | False | $6,473 | $-5,614 |

## target_gapcont_10:30_b4_g3_mnq_rr15_x1555

1x instruments: MNQ
1x trades: 50, net $3,393, max single loss $-478, median stop $-249

| scale | floor_net | floor_maxdd | dd_pct | margin | margin_pct | target_ok | hard_ok | 2025 | 2026_sanity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1x | $3,393 | $670 | 1.3% | $2,200 | 4% | True | True | $647 | $-58 |
| 2x | $6,785 | $1,339 | 2.7% | $4,400 | 9% | True | True | $1,295 | $-116 |
| 3x | $10,178 | $2,009 | 4.0% | $6,600 | 13% | True | True | $1,942 | $-174 |
| 4x | $13,571 | $2,679 | 5.4% | $8,800 | 18% | True | True | $2,589 | $-232 |
| 5x | $16,963 | $3,349 | 6.7% | $11,000 | 22% | True | True | $3,236 | $-290 |
| 6x | $20,356 | $4,018 | 8.0% | $13,200 | 26% | True | True | $3,884 | $-348 |
| 7x | $23,749 | $4,688 | 9.4% | $15,400 | 31% | True | True | $4,531 | $-406 |
| 8x | $27,142 | $5,358 | 10.7% | $17,600 | 35% | False | True | $5,178 | $-464 |
| 9x | $30,534 | $6,027 | 12.1% | $19,800 | 40% | False | True | $5,826 | $-522 |
| 10x | $33,927 | $6,697 | 13.4% | $22,000 | 44% | False | True | $6,473 | $-580 |

## target_gapcont_10:30_b4_g2_mnqmes_rr15_x1555

1x instruments: MNQ, MES
1x trades: 144, net $5,347, max single loss $-478, median stop $-168

| scale | floor_net | floor_maxdd | dd_pct | margin | margin_pct | target_ok | hard_ok | 2025 | 2026_sanity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1x | $5,347 | $1,630 | 3.3% | $3,600 | 7% | True | True | $1,158 | $-773 |
| 2x | $10,694 | $3,260 | 6.5% | $7,200 | 14% | True | True | $2,316 | $-1,545 |
| 3x | $16,041 | $4,889 | 9.8% | $10,800 | 22% | True | True | $3,474 | $-2,318 |
| 4x | $21,388 | $6,519 | 13.0% | $14,400 | 29% | False | True | $4,631 | $-3,090 |
| 5x | $26,735 | $8,149 | 16.3% | $18,000 | 36% | False | False | $5,789 | $-3,863 |
| 6x | $32,082 | $9,779 | 19.6% | $21,600 | 43% | False | False | $6,947 | $-4,635 |
| 7x | $37,429 | $11,409 | 22.8% | $25,200 | 50% | False | False | $8,105 | $-5,408 |
| 8x | $42,776 | $13,039 | 26.1% | $28,800 | 58% | False | False | $9,263 | $-6,180 |
| 9x | $48,123 | $14,668 | 29.3% | $32,400 | 65% | False | False | $10,421 | $-6,953 |
| 10x | $53,471 | $16,298 | 32.6% | $36,000 | 72% | False | False | $11,579 | $-7,725 |

## Read

- If using only the account hard-DD rule, the MNQ/MES candidate can scale to about 4x before floor MaxDD breaches 15%.
- MNQ-only can scale higher because floor MaxDD is lower, but 2025 has only 3 trades and the same signal-sample caveat remains.
- Scaling makes PnL thick enough on paper, but it also scales same-symbol conflict and 2026 sanity loss linearly.
- Therefore payoff/sizing helps the thin-PnL problem only if overlap and insurance-value tests pass.