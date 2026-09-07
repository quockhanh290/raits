# Stress MNQ Strict Overlap / Insurance Probe - 2026-08-21

Scratch-only. No production code modified.

Purpose: test whether the MNQ-only strict Stress candidates are useful at intended synthetic scale after accounting for same-symbol overlap and payoff on bad Normal+Calm days.

Candidates:

- `mnq_strict_10:30_b4_g2_rr15_x1555` at 5x.
- `mnq_strict_10:30_b4_g3_rr15_x1555` at 7x.

Notes:

- Stress uses no daily regime label.
- 2026 remains sanity-only under the current Stress gate.
- Overlap is same-symbol MNQ interval overlap; opposite means existing sleeve is LONG while Stress is SHORT.

## floor

Summary:

| candidate | scale | stress_net | stress_maxdd | combined_net | combined_maxdd | maxdd_delta | normal_opp_days | normal_opp_legs | calm_opp_days | calm_opp_legs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_strict_10:30_b4_g2_rr15_x1555 | 5x | $20,232 | $4,665 | $60,661 | $12,428 | $-3,802 | 28 | 28 | 6 | 6 |
| mnq_strict_10:30_b4_g3_rr15_x1555 | 7x | $23,749 | $4,688 | $64,178 | $13,577 | $-2,653 | 20 | 20 | 5 | 5 |


### mnq_strict_10:30_b4_g2_rr15_x1555 @ 5x

| candidate | scale | stress_net | stress_maxdd | combined_net | combined_maxdd | maxdd_delta | normal_opp_days | normal_opp_legs | calm_opp_days | calm_opp_legs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_strict_10:30_b4_g2_rr15_x1555 | 5x | $20,232 | $4,665 | $60,661 | $12,428 | $-3,802 | 28 | 28 | 6 | 6 |

Insurance buckets:

| bucket | base_pnl | stress_pnl | stress_positive_days | stress_trade_days |
| --- | --- | --- | --- | --- |
| worst_5_base_days | $-16,446 | $0 | 0 | 0 |
| worst_10_base_days | $-28,832 | $0 | 0 | 0 |
| worst_20_base_days | $-47,883 | $0 | 0 | 0 |
| all_negative_base_days | $-146,671 | $2,677 | 10 | 17 |

### mnq_strict_10:30_b4_g3_rr15_x1555 @ 7x

| candidate | scale | stress_net | stress_maxdd | combined_net | combined_maxdd | maxdd_delta | normal_opp_days | normal_opp_legs | calm_opp_days | calm_opp_legs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_strict_10:30_b4_g3_rr15_x1555 | 7x | $23,749 | $4,688 | $64,178 | $13,577 | $-2,653 | 20 | 20 | 5 | 5 |

Insurance buckets:

| bucket | base_pnl | stress_pnl | stress_positive_days | stress_trade_days |
| --- | --- | --- | --- | --- |
| worst_5_base_days | $-16,446 | $0 | 0 | 0 |
| worst_10_base_days | $-28,832 | $0 | 0 | 0 |
| worst_20_base_days | $-47,883 | $0 | 0 | 0 |
| all_negative_base_days | $-146,671 | $4,065 | 9 | 14 |


## vault2025

Summary:

| candidate | scale | stress_net | stress_maxdd | combined_net | combined_maxdd | maxdd_delta | normal_opp_days | normal_opp_legs | calm_opp_days | calm_opp_legs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_strict_10:30_b4_g2_rr15_x1555 | 5x | $3,236 | $116 | $13,978 | $7,870 | $-1,586 | 2 | 2 | 0 | 0 |
| mnq_strict_10:30_b4_g3_rr15_x1555 | 7x | $4,531 | $163 | $15,273 | $7,870 | $-1,586 | 2 | 2 | 0 | 0 |


### mnq_strict_10:30_b4_g2_rr15_x1555 @ 5x

| candidate | scale | stress_net | stress_maxdd | combined_net | combined_maxdd | maxdd_delta | normal_opp_days | normal_opp_legs | calm_opp_days | calm_opp_legs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_strict_10:30_b4_g2_rr15_x1555 | 5x | $3,236 | $116 | $13,978 | $7,870 | $-1,586 | 2 | 2 | 0 | 0 |

Insurance buckets:

| bucket | base_pnl | stress_pnl | stress_positive_days | stress_trade_days |
| --- | --- | --- | --- | --- |
| worst_5_base_days | $-10,090 | $0 | 0 | 0 |
| worst_10_base_days | $-16,179 | $0 | 0 | 0 |
| worst_20_base_days | $-22,110 | $0 | 0 | 0 |
| all_negative_base_days | $-25,591 | $0 | 0 | 0 |

### mnq_strict_10:30_b4_g3_rr15_x1555 @ 7x

| candidate | scale | stress_net | stress_maxdd | combined_net | combined_maxdd | maxdd_delta | normal_opp_days | normal_opp_legs | calm_opp_days | calm_opp_legs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_strict_10:30_b4_g3_rr15_x1555 | 7x | $4,531 | $163 | $15,273 | $7,870 | $-1,586 | 2 | 2 | 0 | 0 |

Insurance buckets:

| bucket | base_pnl | stress_pnl | stress_positive_days | stress_trade_days |
| --- | --- | --- | --- | --- |
| worst_5_base_days | $-10,090 | $0 | 0 | 0 |
| worst_10_base_days | $-16,179 | $0 | 0 | 0 |
| worst_20_base_days | $-22,110 | $0 | 0 | 0 |
| all_negative_base_days | $-25,591 | $0 | 0 | 0 |


## vault2026

Summary:

| candidate | scale | stress_net | stress_maxdd | combined_net | combined_maxdd | maxdd_delta | normal_opp_days | normal_opp_legs | calm_opp_days | calm_opp_legs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_strict_10:30_b4_g2_rr15_x1555 | 5x | $-2,807 | $2,895 | $1,915 | $16,868 | $290 | 4 | 4 | 3 | 3 |
| mnq_strict_10:30_b4_g3_rr15_x1555 | 7x | $-406 | $2,516 | $4,316 | $16,984 | $406 | 3 | 3 | 1 | 1 |


### mnq_strict_10:30_b4_g2_rr15_x1555 @ 5x

| candidate | scale | stress_net | stress_maxdd | combined_net | combined_maxdd | maxdd_delta | normal_opp_days | normal_opp_legs | calm_opp_days | calm_opp_legs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_strict_10:30_b4_g2_rr15_x1555 | 5x | $-2,807 | $2,895 | $1,915 | $16,868 | $290 | 4 | 4 | 3 | 3 |

Insurance buckets:

| bucket | base_pnl | stress_pnl | stress_positive_days | stress_trade_days |
| --- | --- | --- | --- | --- |
| worst_5_base_days | $-16,983 | $0 | 0 | 0 |
| worst_10_base_days | $-23,215 | $0 | 0 | 0 |
| worst_20_base_days | $-28,635 | $-1,797 | 0 | 2 |
| all_negative_base_days | $-30,784 | $-1,797 | 0 | 2 |

### mnq_strict_10:30_b4_g3_rr15_x1555 @ 7x

| candidate | scale | stress_net | stress_maxdd | combined_net | combined_maxdd | maxdd_delta | normal_opp_days | normal_opp_legs | calm_opp_days | calm_opp_legs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_strict_10:30_b4_g3_rr15_x1555 | 7x | $-406 | $2,516 | $4,316 | $16,984 | $406 | 3 | 3 | 1 | 1 |

Insurance buckets:

| bucket | base_pnl | stress_pnl | stress_positive_days | stress_trade_days |
| --- | --- | --- | --- | --- |
| worst_5_base_days | $-16,983 | $0 | 0 | 0 |
| worst_10_base_days | $-23,215 | $0 | 0 | 0 |
| worst_20_base_days | $-28,635 | $-2,516 | 0 | 2 |
| all_negative_base_days | $-30,784 | $-2,516 | 0 | 2 |


## Verdict

- A Stress candidate needs to improve bad-day payoff without creating unacceptable same-symbol netting conflicts.
- If scaled MNQ-only improves tail days and has low overlap, it can remain a hedge candidate even with thin 1x PnL.
- If overlap is frequent or combined MaxDD worsens, sizing does not rescue the sleeve.