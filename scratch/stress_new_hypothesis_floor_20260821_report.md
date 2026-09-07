# Stress New Hypothesis Pass - 2026-08-21

Scratch-only. No production code modified.

These rules do not use daily Stress labels and do not tune around the 10:15/10:20 breadth detector.

## floor

Candidate table:

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| late_break_1100_b3_rr2_x1555 | 378 | 231 | 158 | $4,916 | 1.20 | 0.22 | $2,778 | 0 | 0 | $4,160 | $3,404 | 0.85 | $-2,844 |
| midday_expansion_1200_b3_rr2_x1555 | 353 | 219 | 149 | $3,448 | 1.21 | 0.24 | $1,791 | 0 | 0 | $2,742 | $2,036 | 0.83 | $-2,312 |
| late_break_1100_b4_rr2_x1555 | 295 | 177 | 134 | $3,367 | 1.18 | 0.14 | $2,944 | 0 | 0 | $2,777 | $2,187 | 0.78 | $-3,273 |
| failed_stress_reclaim_1130_b3_long_x1555 | 275 | 172 | 129 | $2,016 | 1.13 | 0.15 | $1,682 | 0 | 0 | $1,466 | $916 | 0.72 | $-3,107 |
| late_break_1130_b3_rr2_x1555 | 336 | 207 | 145 | $-109 | 0.99 | -0.00 | $3,302 | 0 | 0 | $-781 | $-1,453 | 0.51 | $-6,241 |

WFO gate:

| total | best | without_best | best_share | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| $-650 | $1,030 | $-1,679 | inf | $0 | 72 | 216 | False |

By year for best standalone row:

      trades         net        avg
year                               
2017       2  -106.98000 -53.490000
2018      45  1972.46150  43.832478
2019      21   618.36675  29.446036
2020      48  2340.72375  48.765078
2021      50  -877.78050 -17.555610
2022      99  3255.06375  32.879432
2023      62  -745.88425 -12.030391
2024      51 -1540.21200 -30.200235

By instrument/subtype:

            trades        net        avg
instrument                              
MES            212  3416.9375  16.117630
MNQ            166  1498.8215   9.029045

                           trades         net        avg
event_subtype                                           
broad-late-liquidation        186  6724.30075  36.152155
deep-morning-selloff           10   -73.15000  -7.315000
full-breadth-late-selloff     109 -3357.02150 -30.798362
weak                           49  1088.38650  22.211969
wide-midday-chop               24   533.24325  22.218469
