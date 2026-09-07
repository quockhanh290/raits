# Stress MNQ-Only Strict Deep Dive - 2026-08-21

Scratch-only. No production code modified.

Purpose: investigate the cleaner MNQ-only strict Stress direction under the ex-2026 gate.

Search space:

- no daily Stress regime label;
- setup `10:00`, `10:30`, `11:00`, known five minutes later;
- 4/4 basket below open/VWAP;
- gap-down count 2/4, 3/4, or 4/4;
- MNQ only;
- SHORT low-break continuation;
- RR 1.0, 1.25, 1.5, 1.75, 2.0;
- exit 14:00 or 15:55;
- 2026 is sanity-only.

Rules searched: 90

## Ranked Fixed Candidates

| name | trades | clusters | net | pf | calmar | maxdd | slip3 | boot_p5 | best_share | 2025 | 2025_trades | 2026_sanity | 2026_trades |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_strict_10:30_b4_g2_rr175_x1555 | 68 | 60 | $4,049 | 2.03 | 0.54 | $933 | $3,777 | $1,088 | 0.24 | $647 | 3 | $-561 | 8 |
| mnq_strict_10:30_b4_g2_rr15_x1555 | 68 | 60 | $4,046 | 2.03 | 0.54 | $933 | $3,774 | $1,058 | 0.23 | $647 | 3 | $-561 | 8 |
| mnq_strict_10:30_b4_g3_rr175_x1555 | 50 | 45 | $3,549 | 2.37 | 0.66 | $670 | $3,349 | $1,169 | 0.15 | $647 | 3 | $-58 | 4 |
| mnq_strict_10:30_b4_g2_rr125_x1555 | 68 | 60 | $3,929 | 2.00 | 0.53 | $933 | $3,657 | $1,029 | 0.21 | $647 | 3 | $-561 | 8 |
| mnq_strict_10:30_b4_g4_rr175_x1555 | 37 | 34 | $3,318 | 2.99 | 0.71 | $587 | $3,170 | $1,337 | 0.16 | $250 | 2 | $125 | 3 |
| mnq_strict_10:30_b4_g3_rr125_x1555 | 50 | 45 | $3,507 | 2.36 | 0.66 | $670 | $3,307 | $1,136 | 0.18 | $647 | 3 | $-58 | 4 |
| mnq_strict_10:30_b4_g4_rr125_x1555 | 37 | 34 | $3,276 | 2.96 | 0.70 | $587 | $3,128 | $1,316 | 0.20 | $250 | 2 | $125 | 3 |
| mnq_strict_10:30_b4_g3_rr15_x1555 | 50 | 45 | $3,393 | 2.31 | 0.63 | $670 | $3,193 | $1,040 | 0.15 | $647 | 3 | $-58 | 4 |
| mnq_strict_11:00_b4_g4_rr175_x1555 | 43 | 40 | $2,555 | 2.50 | 0.93 | $345 | $2,383 | $649 | 0.21 | $1,202 | 3 | $-704 | 3 |
| mnq_strict_10:30_b4_g2_rr20_x1555 | 68 | 60 | $3,759 | 1.95 | 0.50 | $933 | $3,487 | $809 | 0.25 | $647 | 3 | $-561 | 8 |
| mnq_strict_10:30_b4_g4_rr15_x1555 | 37 | 34 | $3,162 | 2.89 | 0.67 | $587 | $3,014 | $1,237 | 0.17 | $250 | 2 | $125 | 3 |
| mnq_strict_10:30_b4_g3_rr20_x1555 | 50 | 45 | $3,258 | 2.26 | 0.61 | $670 | $3,058 | $863 | 0.16 | $647 | 3 | $-58 | 4 |
| mnq_strict_10:30_b4_g3_rr10_x1555 | 50 | 45 | $3,119 | 2.21 | 0.55 | $704 | $2,919 | $838 | 0.16 | $741 | 3 | $-58 | 4 |
| mnq_strict_10:30_b4_g4_rr20_x1555 | 37 | 34 | $3,027 | 2.81 | 0.64 | $587 | $2,879 | $1,082 | 0.18 | $250 | 2 | $125 | 3 |
| mnq_strict_10:30_b4_g2_rr10_x1555 | 68 | 60 | $3,460 | 1.88 | 0.45 | $968 | $3,188 | $689 | 0.20 | $741 | 3 | $-369 | 8 |
| mnq_strict_11:00_b4_g2_rr175_x1555 | 67 | 62 | $3,321 | 2.08 | 0.79 | $524 | $3,053 | $827 | 0.19 | $459 | 7 | $-2,051 | 6 |
| mnq_strict_11:00_b4_g4_rr125_x1555 | 43 | 40 | $2,483 | 2.46 | 0.90 | $345 | $2,311 | $606 | 0.15 | $872 | 3 | $-704 | 3 |
| mnq_strict_10:30_b4_g4_rr10_x1555 | 37 | 34 | $2,918 | 2.75 | 0.62 | $587 | $2,770 | $1,102 | 0.18 | $250 | 2 | $125 | 3 |
| mnq_strict_11:00_b4_g4_rr10_x1555 | 43 | 40 | $2,416 | 2.42 | 0.88 | $345 | $2,244 | $606 | 0.15 | $708 | 3 | $-704 | 3 |
| mnq_strict_11:00_b4_g4_rr20_x1555 | 43 | 40 | $2,694 | 2.59 | 0.98 | $345 | $2,522 | $728 | 0.23 | $226 | 3 | $-704 | 3 |

## Dynamic WFO Across Top MNQ-Strict Set

| total | best | without_best | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- |
| $2,039 | $613 | $1,426 | $-186 | 18 | 55 | False |

WFO selected counts:

                                    folds       net
selected                                           
mnq_strict_10:30_b4_g4_rr175_x1555     17  811.6410
mnq_strict_11:00_b4_g4_rr20_x1555       3  565.5800
mnq_strict_11:00_b4_g2_rr175_x1555     12  325.8200
mnq_strict_10:30_b4_g2_rr15_x1555      11  307.9275
mnq_strict_10:30_b4_g2_rr125_x1555      2  210.7600
mnq_strict_10:30_b4_g2_rr175_x1555      6  -40.6415
mnq_strict_11:00_b4_g4_rr10_x1555       4 -142.2400

## Best Fixed Candidate Autopsy: `mnq_strict_10:30_b4_g2_rr175_x1555`

      trades          net         avg
year                                 
2018       3  -189.940000  -63.313333
2019       9   503.381625   55.931292
2020      11  1021.917000   92.901545
2021       5   262.300000   52.460000
2022      19  2499.252500  131.539605
2023      13  -214.300500  -16.484654
2024       8   166.658500   20.832313

By exit reason:

             trades          net         avg
exit_reason                                 
stop              9 -2286.859500 -254.095500
target            3  1106.068625  368.689542
time             56  5230.060000   93.393929

Sizing sketch:

| scale | floor | maxdd | dd_pct | margin | margin_pct | target_ok | hard_ok | 2025 | 2026_sanity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1x | $4,049 | $933 | 1.9% | $2,200 | 4% | True | True | $647 | $-561 |
| 2x | $8,099 | $1,866 | 3.7% | $4,400 | 9% | True | True | $1,295 | $-1,123 |
| 3x | $12,148 | $2,799 | 5.6% | $6,600 | 13% | True | True | $1,942 | $-1,684 |
| 4x | $16,197 | $3,732 | 7.5% | $8,800 | 18% | True | True | $2,589 | $-2,246 |
| 5x | $20,246 | $4,665 | 9.3% | $11,000 | 22% | True | True | $3,236 | $-2,807 |
| 6x | $24,296 | $5,598 | 11.2% | $13,200 | 26% | False | True | $3,884 | $-3,369 |
| 7x | $28,345 | $6,531 | 13.1% | $15,400 | 31% | False | True | $4,531 | $-3,930 |
| 8x | $32,394 | $7,464 | 14.9% | $17,600 | 35% | False | True | $5,178 | $-4,491 |
| 9x | $36,443 | $8,398 | 16.8% | $19,800 | 40% | False | False | $5,826 | $-5,053 |
| 10x | $40,493 | $9,331 | 18.7% | $22,000 | 44% | False | False | $6,473 | $-5,614 |

## Verdict

- This pass is a research deep dive, not a deploy approval.
- The winner must beat the previous `b4 g3 MNQ rr15` shape without relying on a parameter-only improvement.
- 2026 remains visible but non-gating under the current Stress protocol.