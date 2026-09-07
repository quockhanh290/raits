# Stress Open Search - 2026-08-21

Scratch-only broad candidate excavation. No production code modified.

Search rules:

- no same-day daily Stress regime label;
- every setup bar is treated as known only five minutes after its timestamp;
- families include continuation shorts, gap-continuation shorts, VWAP-reject shorts, and reclaim longs;
- instruments are searched as `MNQ`, `MES`, and `MNQ/MES` fixed variants;
- ranking penalizes single-cluster concentration, negative 3x slippage, negative OOS, zero OOS trades, and fill/timing failures.

Rules searched: 36

## Top Robustness-Ranked Floor Candidates With OOS

| name | family | dir | inst | trades | days | clusters | net | pf | calmar | maxdd | slip3 | boot_p5 | best_share | oos25 | oos25_trades | oos26 | oos26_trades |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gap_cont_short_10:30_b4_mnqmes_rr20_x1555 | cont_short | SHORT | MNQ/MES | 144 | 79 | 68 | $5,054 | 1.64 | 0.39 | $1,630 | $4,478 | $91 | 0.32 | $1,160 | 6 | $-773 | 17 |
| cont_short_10:30_b3_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 302 | 302 | 201 | $6,636 | 1.28 | 0.43 | $1,947 | $5,428 | $733 | 0.18 | $-253 | 41 | $-455 | 25 |
| gap_cont_short_10:30_b4_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 68 | 68 | 60 | $3,759 | 1.95 | 0.50 | $933 | $3,487 | $809 | 0.25 | $647 | 3 | $-561 | 8 |
| cont_short_10:30_b4_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 247 | 247 | 179 | $5,174 | 1.27 | 0.34 | $1,891 | $4,186 | $-722 | 0.19 | $266 | 32 | $-921 | 21 |
| cont_short_10:30_b4_mnqmes_rr20_x1555 | cont_short | SHORT | MNQ/MES | 519 | 281 | 193 | $6,411 | 1.19 | 0.27 | $2,935 | $4,335 | $-2,729 | 0.26 | $415 | 65 | $-1,662 | 41 |
| cont_short_10:30_b3_mnqmes_rr20_x1555 | cont_short | SHORT | MNQ/MES | 659 | 375 | 230 | $8,103 | 1.19 | 0.34 | $2,995 | $5,467 | $-1,433 | 0.21 | $-651 | 85 | $-1,514 | 50 |
| reclaim_long_11:30_b3_mnq_rr20_x1555 | reclaim_long | LONG | MNQ | 38 | 38 | 34 | $1,320 | 1.68 | 0.33 | $495 | $1,168 | $-590 | 0.63 | $564 | 5 | $-218 | 2 |
| reclaim_long_11:30_b3_mnqmes_rr20_x1555 | reclaim_long | LONG | MNQ/MES | 98 | 73 | 64 | $1,318 | 1.32 | 0.20 | $822 | $926 | $-1,903 | 0.94 | $909 | 13 | $-230 | 6 |
| gap_cont_short_13:00_b4_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 43 | 43 | 39 | $548 | 1.27 | 0.09 | $730 | $376 | $-1,026 | 0.58 | $353 | 2 | $-85 | 5 |
| gap_cont_short_10:30_b3_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 90 | 90 | 79 | $2,468 | 1.38 | 0.18 | $1,671 | $2,108 | $-1,043 | 0.39 | $-275 | 7 | $-561 | 8 |
| gap_cont_short_13:00_b4_mnqmes_rr20_x1555 | cont_short | SHORT | MNQ/MES | 92 | 54 | 46 | $793 | 1.21 | 0.08 | $1,318 | $425 | $-1,863 | 0.70 | $596 | 6 | $-85 | 11 |
| gap_cont_short_11:30_b4_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 60 | 60 | 57 | $1,539 | 1.58 | 0.19 | $1,014 | $1,299 | $-574 | 0.32 | $-1,883 | 6 | $1,286 | 4 |
| reclaim_long_10:30_b3_mnq_rr20_x1555 | reclaim_long | LONG | MNQ | 56 | 56 | 53 | $1,983 | 1.60 | 0.35 | $705 | $1,759 | $-512 | 0.36 | $-818 | 7 | $-616 | 3 |
| gap_cont_short_11:30_b4_mnqmes_rr20_x1555 | cont_short | SHORT | MNQ/MES | 129 | 72 | 67 | $2,184 | 1.39 | 0.17 | $1,635 | $1,668 | $-1,435 | 0.40 | $-2,977 | 14 | $1,939 | 9 |
| cont_short_11:30_b4_mnqmes_rr20_x1555 | cont_short | SHORT | MNQ/MES | 419 | 239 | 173 | $3,249 | 1.16 | 0.13 | $3,017 | $1,573 | $-3,389 | 0.52 | $-1,589 | 79 | $119 | 25 |
| reclaim_long_10:30_b3_mnqmes_rr20_x1555 | reclaim_long | LONG | MNQ/MES | 128 | 91 | 80 | $2,421 | 1.36 | 0.22 | $1,369 | $1,909 | $-1,404 | 0.38 | $-1,440 | 17 | $-427 | 9 |
| cont_short_13:00_b3_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 160 | 160 | 120 | $1,622 | 1.20 | 0.21 | $988 | $982 | $-1,523 | 0.37 | $-1,089 | 26 | $-429 | 17 |
| gap_cont_short_10:30_b3_mnqmes_rr20_x1555 | cont_short | SHORT | MNQ/MES | 196 | 115 | 98 | $3,188 | 1.25 | 0.15 | $2,593 | $2,404 | $-2,786 | 0.50 | $-418 | 14 | $-1,045 | 18 |
| cont_short_11:30_b4_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 193 | 193 | 147 | $1,744 | 1.16 | 0.09 | $2,312 | $972 | $-2,357 | 0.60 | $-799 | 37 | $-54 | 11 |

## Top Floor Net Candidates

| name | family | dir | inst | trades | days | clusters | net | pf | calmar | maxdd | slip3 | boot_p5 | best_share | oos25 | oos25_trades | oos26 | oos26_trades |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cont_short_10:30_b3_mnqmes_rr20_x1555 | cont_short | SHORT | MNQ/MES | 659 | 375 | 230 | $8,103 | 1.19 | 0.34 | $2,995 | $5,467 | $-1,433 | 0.21 | $-651 | 85 | $-1,514 | 50 |
| cont_short_10:30_b3_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 302 | 302 | 201 | $6,636 | 1.28 | 0.43 | $1,947 | $5,428 | $733 | 0.18 | $-253 | 41 | $-455 | 25 |
| cont_short_10:30_b4_mnqmes_rr20_x1555 | cont_short | SHORT | MNQ/MES | 519 | 281 | 193 | $6,411 | 1.19 | 0.27 | $2,935 | $4,335 | $-2,729 | 0.26 | $415 | 65 | $-1,662 | 41 |
| cont_short_10:30_b4_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 247 | 247 | 179 | $5,174 | 1.27 | 0.34 | $1,891 | $4,186 | $-722 | 0.19 | $266 | 32 | $-921 | 21 |
| gap_cont_short_10:30_b4_mnqmes_rr20_x1555 | cont_short | SHORT | MNQ/MES | 144 | 79 | 68 | $5,054 | 1.64 | 0.39 | $1,630 | $4,478 | $91 | 0.32 | $1,160 | 6 | $-773 | 17 |
| gap_cont_short_10:30_b4_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 68 | 68 | 60 | $3,759 | 1.95 | 0.50 | $933 | $3,487 | $809 | 0.25 | $647 | 3 | $-561 | 8 |
| cont_short_11:30_b4_mnqmes_rr20_x1555 | cont_short | SHORT | MNQ/MES | 419 | 239 | 173 | $3,249 | 1.16 | 0.13 | $3,017 | $1,573 | $-3,389 | 0.52 | $-1,589 | 79 | $119 | 25 |
| gap_cont_short_10:30_b3_mnqmes_rr20_x1555 | cont_short | SHORT | MNQ/MES | 196 | 115 | 98 | $3,188 | 1.25 | 0.15 | $2,593 | $2,404 | $-2,786 | 0.50 | $-418 | 14 | $-1,045 | 18 |
| gap_cont_short_10:30_b3_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 90 | 90 | 79 | $2,468 | 1.38 | 0.18 | $1,671 | $2,108 | $-1,043 | 0.39 | $-275 | 7 | $-561 | 8 |
| reclaim_long_10:30_b3_mnqmes_rr20_x1555 | reclaim_long | LONG | MNQ/MES | 128 | 91 | 80 | $2,421 | 1.36 | 0.22 | $1,369 | $1,909 | $-1,404 | 0.38 | $-1,440 | 17 | $-427 | 9 |
| gap_cont_short_11:30_b4_mnqmes_rr20_x1555 | cont_short | SHORT | MNQ/MES | 129 | 72 | 67 | $2,184 | 1.39 | 0.17 | $1,635 | $1,668 | $-1,435 | 0.40 | $-2,977 | 14 | $1,939 | 9 |
| cont_short_13:00_b3_mnqmes_rr20_x1555 | cont_short | SHORT | MNQ/MES | 380 | 235 | 159 | $2,030 | 1.12 | 0.12 | $2,197 | $510 | $-3,133 | 0.49 | $-1,832 | 60 | $-682 | 44 |
| reclaim_long_10:30_b3_mnq_rr20_x1555 | reclaim_long | LONG | MNQ | 56 | 56 | 53 | $1,983 | 1.60 | 0.35 | $705 | $1,759 | $-512 | 0.36 | $-818 | 7 | $-616 | 3 |
| cont_short_11:30_b4_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 193 | 193 | 147 | $1,744 | 1.16 | 0.09 | $2,312 | $972 | $-2,357 | 0.60 | $-799 | 37 | $-54 | 11 |
| cont_short_13:00_b3_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 160 | 160 | 120 | $1,622 | 1.20 | 0.21 | $988 | $982 | $-1,523 | 0.37 | $-1,089 | 26 | $-429 | 17 |
| gap_cont_short_11:30_b4_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 60 | 60 | 57 | $1,539 | 1.58 | 0.19 | $1,014 | $1,299 | $-574 | 0.32 | $-1,883 | 6 | $1,286 | 4 |
| cont_short_13:00_b4_mnqmes_rr20_x1555 | cont_short | SHORT | MNQ/MES | 290 | 175 | 126 | $1,450 | 1.11 | 0.10 | $1,902 | $290 | $-3,435 | 0.69 | $-2,378 | 53 | $-917 | 31 |
| reclaim_long_11:30_b3_mnq_rr20_x1555 | reclaim_long | LONG | MNQ | 38 | 38 | 34 | $1,320 | 1.68 | 0.33 | $495 | $1,168 | $-590 | 0.63 | $564 | 5 | $-218 | 2 |
| reclaim_long_11:30_b3_mnqmes_rr20_x1555 | reclaim_long | LONG | MNQ/MES | 98 | 73 | 64 | $1,318 | 1.32 | 0.20 | $822 | $926 | $-1,903 | 0.94 | $909 | 13 | $-230 | 6 |
| cont_short_13:00_b4_mnq_rr20_x1555 | cont_short | SHORT | MNQ | 125 | 125 | 98 | $794 | 1.12 | 0.10 | $952 | $294 | $-1,954 | 0.75 | $-1,288 | 23 | $-401 | 11 |

## Best Candidate Autopsy: `gap_cont_short_10:30_b4_mnqmes_rr20_x1555`

      trades         net        avg
year                               
2018       8  -545.27750 -68.159687
2019      21   416.51925  19.834250
2020      23  1052.06325  45.741880
2021       9   542.34000  60.260000
2022      40  3638.63500  90.965875
2023      26  -471.04800 -18.117231
2024      17   420.48475  24.734397

By instrument:

            trades         net        avg
instrument                               
MES             76  1295.17625  17.041793
MNQ             68  3758.54050  55.272654

By exit reason:

             trades         net         avg
exit_reason                                
stop             24 -4889.55325 -203.731385
target            3  1148.35000  382.783333
time            117  8794.92000   75.170256

Interpretation:

- This is a discovery table, not a promotion table. The selected candidate must be rerun in a narrower follow-up with event-WFO and overlap/insurance scoring.
- If the top row is LONG, it is a Stress-regime/reversal strategy rather than a crash hedge; do not compare it directly with short hedge sleeves.