# Stress Final Gate - 2026-08-21

Scratch-only. No production code modified.

Purpose: stop tuning and decide whether the MNQ-only Stress branch survives as an active hedge/diversifier candidate.

Gate policy:

- 2026 is sanity-only, not a rejection input.
- Test only fixed candidates and fixed scales.
- Test both allowing overlap and blocking Stress when Normal already holds MNQ.
- Required to keep candidate: zero Normal same-symbol opposite overlap after policy, positive 2025, floor cluster stability, and no combined MaxDD worsening.

## floor

| candidate | scale | policy | raw_trades | kept_trades | blocked | stress_net | stress_maxdd | base_maxdd | combined_net | combined_maxdd | maxdd_delta | normal_opp_days | calm_opp_days | clusters | best_cluster | without_best | final4 | cluster_pass | bad20_stress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b4_g2_rr15_x1555 | 5x | allow_overlap | 68 | 68 | 0 | $20,232 | $4,665 | $16,230 | $60,661 | $12,428 | $-3,802 | 28 | 6 | 60 | $4,608 | $15,624 | $2,175 | True | $0 |
| b4_g2_rr15_x1555 | 5x | block_normal_mnq | 68 | 30 | 38 | $11,604 | $2,390 | $16,230 | $52,033 | $16,566 | $335 | 0 | 4 | 29 | $3,459 | $8,145 | $31 | True | $0 |
| b4_g3_rr15_x1555 | 7x | allow_overlap | 50 | 50 | 0 | $23,749 | $4,688 | $16,230 | $64,178 | $13,577 | $-2,653 | 20 | 5 | 45 | $3,677 | $20,072 | $3,045 | True | $0 |
| b4_g3_rr15_x1555 | 7x | block_normal_mnq | 50 | 22 | 28 | $14,336 | $3,346 | $16,230 | $54,765 | $16,796 | $565 | 0 | 3 | 22 | $3,677 | $10,659 | $2,198 | True | $0 |

## vault2025

| candidate | scale | policy | raw_trades | kept_trades | blocked | stress_net | stress_maxdd | base_maxdd | combined_net | combined_maxdd | maxdd_delta | normal_opp_days | calm_opp_days | clusters | best_cluster | without_best | final4 | cluster_pass | bad20_stress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b4_g2_rr15_x1555 | 5x | allow_overlap | 3 | 3 | 0 | $3,236 | $116 | $9,457 | $13,978 | $7,870 | $-1,586 | 2 | 0 | 3 | $1,989 | $1,248 | $3,236 | False | $0 |
| b4_g2_rr15_x1555 | 5x | block_normal_mnq | 3 | 1 | 2 | $-116 | $116 | $9,457 | $10,626 | $9,457 | $0 | 0 | 0 | 1 | $-116 | $0 | $-116 | False | $0 |
| b4_g3_rr15_x1555 | 7x | allow_overlap | 3 | 3 | 0 | $4,531 | $163 | $9,457 | $15,273 | $7,870 | $-1,586 | 2 | 0 | 3 | $2,784 | $1,747 | $4,531 | False | $0 |
| b4_g3_rr15_x1555 | 7x | block_normal_mnq | 3 | 1 | 2 | $-163 | $163 | $9,457 | $10,579 | $9,457 | $0 | 0 | 0 | 1 | $-163 | $0 | $-163 | False | $0 |

## vault2026

| candidate | scale | policy | raw_trades | kept_trades | blocked | stress_net | stress_maxdd | base_maxdd | combined_net | combined_maxdd | maxdd_delta | normal_opp_days | calm_opp_days | clusters | best_cluster | without_best | final4 | cluster_pass | bad20_stress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b4_g2_rr15_x1555 | 5x | allow_overlap | 8 | 8 | 0 | $-2,807 | $2,895 | $16,579 | $1,915 | $16,868 | $290 | 4 | 3 | 8 | $1,164 | $-3,971 | $-1,097 | False | $-1,797 |
| b4_g2_rr15_x1555 | 5x | block_normal_mnq | 8 | 4 | 4 | $-2,355 | $2,442 | $16,579 | $2,367 | $17,462 | $884 | 0 | 3 | 4 | $979 | $-3,334 | $-2,355 | False | $-884 |
| b4_g3_rr15_x1555 | 7x | allow_overlap | 4 | 4 | 0 | $-406 | $2,516 | $16,579 | $4,316 | $16,984 | $406 | 3 | 1 | 4 | $1,629 | $-2,035 | $-406 | False | $-2,516 |
| b4_g3_rr15_x1555 | 7x | block_normal_mnq | 4 | 1 | 3 | $-1,237 | $1,237 | $16,579 | $3,484 | $17,816 | $1,237 | 0 | 1 | 1 | $-1,237 | $0 | $-1,237 | False | $-1,237 |

## Gate Decision

| candidate | scale | policy | floor_cluster_pass | floor_maxdd_delta | 2025_net | 2025_maxdd_delta | 2026_sanity_net | 2026_sanity_maxdd_delta | decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b4_g2_rr15_x1555 | 5x | allow_overlap | True | $-3,802 | $3,236 | $-1,586 | $-2,807 | $290 | fail_overlap |
| b4_g2_rr15_x1555 | 5x | block_normal_mnq | True | $335 | $-116 | $0 | $-2,355 | $884 | fail_2025 |
| b4_g3_rr15_x1555 | 7x | allow_overlap | True | $-2,653 | $4,531 | $-1,586 | $-406 | $406 | fail_overlap |
| b4_g3_rr15_x1555 | 7x | block_normal_mnq | True | $565 | $-163 | $0 | $-1,237 | $1,237 | fail_2025 |

## Verdict

- If both block-normal scenarios fail, reject the independent Stress sleeve for deploy/paper and keep it as research only.
- If a block-normal scenario passes, keep only that exact fixed candidate/policy as a deploy-track research candidate.
- Allow-overlap scenarios cannot be deployed because same-symbol MNQ netting risk remains unresolved.