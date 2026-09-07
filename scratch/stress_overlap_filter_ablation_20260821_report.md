# Stress Overlap Filter Ablation - 2026-08-21

Scratch-only. No production code modified.

Purpose: measure whether removing specific overlap classes makes the MNQ-only Stress candidates stronger.

Policies:

- `allow_all`: no overlap filter.
- `drop_normal_mnq`: remove Stress trades overlapping any Normal MNQ position.
- `drop_calm_mnq`: remove Stress trades overlapping any Calm MNQ position.
- `drop_any_mnq`: remove Stress trades overlapping Normal or Calm MNQ.
- `keep_normal_mnq_only`: keep only trades that overlap Normal MNQ, to test whether edge lives in the conflict.
- `keep_no_mnq_overlap_only`: same as `drop_any_mnq`, kept for readability.

## floor

| candidate | scale | policy | raw | kept | blocked | stress_net | stress_maxdd | maxdd_delta | normal_opp_days | calm_opp_days | bad20_stress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b4_g2_rr15_x1555 | 5x | allow_all | 68 | 68 | 0 | $20,232 | $4,665 | $-3,802 | 28 | 6 | $0 |
| b4_g2_rr15_x1555 | 5x | drop_normal_mnq | 68 | 30 | 38 | $11,604 | $2,390 | $335 | 0 | 4 | $0 |
| b4_g2_rr15_x1555 | 5x | drop_calm_mnq | 68 | 62 | 6 | $19,127 | $5,782 | $-3,802 | 26 | 0 | $0 |
| b4_g2_rr15_x1555 | 5x | drop_any_mnq | 68 | 26 | 42 | $10,617 | $2,390 | $335 | 0 | 0 | $0 |
| b4_g2_rr15_x1555 | 5x | keep_normal_mnq_only | 68 | 38 | 30 | $8,628 | $5,244 | $-5,165 | 28 | 2 | $0 |
| b4_g2_rr15_x1555 | 5x | keep_no_mnq_overlap_only | 68 | 26 | 42 | $10,617 | $2,390 | $335 | 0 | 0 | $0 |
| b4_g3_rr15_x1555 | 7x | allow_all | 50 | 50 | 0 | $23,749 | $4,688 | $-2,653 | 20 | 5 | $0 |
| b4_g3_rr15_x1555 | 7x | drop_normal_mnq | 50 | 22 | 28 | $14,336 | $3,346 | $565 | 0 | 3 | $0 |
| b4_g3_rr15_x1555 | 7x | drop_calm_mnq | 50 | 45 | 5 | $21,713 | $6,251 | $-2,653 | 18 | 0 | $0 |
| b4_g3_rr15_x1555 | 7x | drop_any_mnq | 50 | 19 | 31 | $12,465 | $3,346 | $565 | 0 | 0 | $0 |
| b4_g3_rr15_x1555 | 7x | keep_normal_mnq_only | 50 | 28 | 22 | $9,413 | $5,499 | $-3,196 | 20 | 2 | $0 |
| b4_g3_rr15_x1555 | 7x | keep_no_mnq_overlap_only | 50 | 19 | 31 | $12,465 | $3,346 | $565 | 0 | 0 | $0 |

## vault2025

| candidate | scale | policy | raw | kept | blocked | stress_net | stress_maxdd | maxdd_delta | normal_opp_days | calm_opp_days | bad20_stress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b4_g2_rr15_x1555 | 5x | allow_all | 3 | 3 | 0 | $3,236 | $116 | $-1,586 | 2 | 0 | $0 |
| b4_g2_rr15_x1555 | 5x | drop_normal_mnq | 3 | 1 | 2 | $-116 | $116 | $0 | 0 | 0 | $0 |
| b4_g2_rr15_x1555 | 5x | drop_calm_mnq | 3 | 3 | 0 | $3,236 | $116 | $-1,586 | 2 | 0 | $0 |
| b4_g2_rr15_x1555 | 5x | drop_any_mnq | 3 | 1 | 2 | $-116 | $116 | $0 | 0 | 0 | $0 |
| b4_g2_rr15_x1555 | 5x | keep_normal_mnq_only | 3 | 2 | 1 | $3,353 | $0 | $-1,586 | 2 | 0 | $0 |
| b4_g2_rr15_x1555 | 5x | keep_no_mnq_overlap_only | 3 | 1 | 2 | $-116 | $116 | $0 | 0 | 0 | $0 |
| b4_g3_rr15_x1555 | 7x | allow_all | 3 | 3 | 0 | $4,531 | $163 | $-1,586 | 2 | 0 | $0 |
| b4_g3_rr15_x1555 | 7x | drop_normal_mnq | 3 | 1 | 2 | $-163 | $163 | $0 | 0 | 0 | $0 |
| b4_g3_rr15_x1555 | 7x | drop_calm_mnq | 3 | 3 | 0 | $4,531 | $163 | $-1,586 | 2 | 0 | $0 |
| b4_g3_rr15_x1555 | 7x | drop_any_mnq | 3 | 1 | 2 | $-163 | $163 | $0 | 0 | 0 | $0 |
| b4_g3_rr15_x1555 | 7x | keep_normal_mnq_only | 3 | 2 | 1 | $4,694 | $0 | $-1,586 | 2 | 0 | $0 |
| b4_g3_rr15_x1555 | 7x | keep_no_mnq_overlap_only | 3 | 1 | 2 | $-163 | $163 | $0 | 0 | 0 | $0 |

## vault2026

| candidate | scale | policy | raw | kept | blocked | stress_net | stress_maxdd | maxdd_delta | normal_opp_days | calm_opp_days | bad20_stress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b4_g2_rr15_x1555 | 5x | allow_all | 8 | 8 | 0 | $-2,807 | $2,895 | $290 | 4 | 3 | $-1,797 |
| b4_g2_rr15_x1555 | 5x | drop_normal_mnq | 8 | 4 | 4 | $-2,355 | $2,442 | $884 | 0 | 3 | $-884 |
| b4_g2_rr15_x1555 | 5x | drop_calm_mnq | 8 | 5 | 3 | $526 | $1,046 | $-594 | 4 | 0 | $-914 |
| b4_g2_rr15_x1555 | 5x | drop_any_mnq | 8 | 1 | 7 | $979 | $0 | $0 | 0 | 0 | $0 |
| b4_g2_rr15_x1555 | 5x | keep_normal_mnq_only | 8 | 4 | 4 | $-452 | $1,046 | $-594 | 4 | 0 | $-914 |
| b4_g2_rr15_x1555 | 5x | keep_no_mnq_overlap_only | 8 | 1 | 7 | $979 | $0 | $0 | 0 | 0 | $0 |
| b4_g3_rr15_x1555 | 7x | allow_all | 4 | 4 | 0 | $-406 | $2,516 | $406 | 3 | 1 | $-2,516 |
| b4_g3_rr15_x1555 | 7x | drop_normal_mnq | 4 | 1 | 3 | $-1,237 | $1,237 | $1,237 | 0 | 1 | $-1,237 |
| b4_g3_rr15_x1555 | 7x | drop_calm_mnq | 4 | 3 | 1 | $831 | $1,279 | $-831 | 3 | 0 | $-1,279 |
| b4_g3_rr15_x1555 | 7x | drop_any_mnq | 4 | 0 | 4 | $0 | $0 | $0 | 0 | 0 | $0 |
| b4_g3_rr15_x1555 | 7x | keep_normal_mnq_only | 4 | 3 | 1 | $831 | $1,279 | $-831 | 3 | 0 | $-1,279 |
| b4_g3_rr15_x1555 | 7x | keep_no_mnq_overlap_only | 4 | 0 | 4 | $0 | $0 | $0 | 0 | 0 | $0 |

## Decision View

| candidate | policy | floor_net | floor_maxdd_delta | floor_normal_opp | floor_calm_opp | 2025_net | 2025_maxdd_delta | read |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b4_g2_rr15_x1555 | allow_all | $20,232 | $-3,802 | 28 | 6 | $3,236 | $-1,586 | not_enough |
| b4_g2_rr15_x1555 | drop_normal_mnq | $11,604 | $335 | 0 | 4 | $-116 | $0 | not_enough |
| b4_g2_rr15_x1555 | drop_calm_mnq | $19,127 | $-3,802 | 26 | 0 | $3,236 | $-1,586 | not_enough |
| b4_g2_rr15_x1555 | drop_any_mnq | $10,617 | $335 | 0 | 0 | $-116 | $0 | not_enough |
| b4_g2_rr15_x1555 | keep_normal_mnq_only | $8,628 | $-5,165 | 28 | 2 | $3,353 | $-1,586 | not_enough |
| b4_g2_rr15_x1555 | keep_no_mnq_overlap_only | $10,617 | $335 | 0 | 0 | $-116 | $0 | not_enough |
| b4_g3_rr15_x1555 | allow_all | $23,749 | $-2,653 | 20 | 5 | $4,531 | $-1,586 | not_enough |
| b4_g3_rr15_x1555 | drop_normal_mnq | $14,336 | $565 | 0 | 3 | $-163 | $0 | not_enough |
| b4_g3_rr15_x1555 | drop_calm_mnq | $21,713 | $-2,653 | 18 | 0 | $4,531 | $-1,586 | not_enough |
| b4_g3_rr15_x1555 | drop_any_mnq | $12,465 | $565 | 0 | 0 | $-163 | $0 | not_enough |
| b4_g3_rr15_x1555 | keep_normal_mnq_only | $9,413 | $-3,196 | 20 | 2 | $4,694 | $-1,586 | not_enough |
| b4_g3_rr15_x1555 | keep_no_mnq_overlap_only | $12,465 | $565 | 0 | 0 | $-163 | $0 | not_enough |

## Verdict

- The useful test is whether an overlap removal keeps floor and 2025 positive while removing Normal MNQ conflict.
- If only `allow_all` or `keep_normal_mnq_only` works, the edge is tied to the conflict and should not be deployed.
- If `drop_calm_mnq` improves results, Calm overlap can be dropped cheaply because Calm conflicts are operationally smaller.