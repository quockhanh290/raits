# Stress New Hypothesis Pass - 2026-08-21

Scratch-only. No production code modified.

These rules do not use daily Stress labels and do not tune around the 10:15/10:20 breadth detector.

## vault2025

Candidate table:

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| late_break_1100_b3_rr2_x1555 | 65 | 38 | 24 | $2,182 | 1.37 | 1.02 | $2,163 | 0 | 0 | $2,052 | $1,922 | 0.74 | $-3,364 |
| failed_stress_reclaim_1130_b3_long_x1555 | 45 | 28 | 19 | $1,171 | 1.37 | 0.71 | $1,659 | 0 | 0 | $1,081 | $991 | 0.71 | $-2,074 |
| late_break_1100_b4_rr2_x1555 | 46 | 26 | 20 | $907 | 1.25 | 0.61 | $1,501 | 0 | 0 | $815 | $723 | 0.64 | $-2,620 |
| midday_expansion_1200_b3_rr2_x1555 | 51 | 31 | 21 | $-187 | 0.96 | -0.10 | $1,958 | 0 | 0 | $-289 | $-391 | 0.47 | $-3,620 |
| late_break_1130_b3_rr2_x1555 | 61 | 38 | 26 | $-3,415 | 0.50 | -0.69 | $5,010 | 0 | 0 | $-3,537 | $-3,659 | 0.09 | $-7,741 |

WFO gate:

| total | best | without_best | best_share | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| $-3,098 | $423 | $-3,521 | inf | $0 | 4 | 25 | False |

By year for best standalone row:

      trades       net        avg
year                             
2025      65  2182.334  33.574369

By instrument/subtype:

            trades       net        avg
instrument                             
MES             37   568.245  15.357973
MNQ             28  1614.089  57.646036

                           trades         net         avg
event_subtype                                            
broad-late-liquidation         30  1767.28625   58.909542
deep-morning-selloff            2   884.73000  442.365000
full-breadth-late-selloff      16  -859.90700  -53.744187
weak                           11  1685.27350  153.206682
wide-midday-chop                6 -1295.04875 -215.841458

## vault2026

Candidate table:

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| failed_stress_reclaim_1130_b3_long_x1555 | 35 | 20 | 15 | $1,093 | 1.43 | 1.89 | $917 | 0 | 0 | $1,023 | $953 | 0.77 | $-1,131 |
| late_break_1130_b3_rr2_x1555 | 29 | 20 | 16 | $383 | 1.15 | 0.40 | $1,535 | 0 | 0 | $325 | $267 | 0.55 | $-2,472 |
| late_break_1100_b3_rr2_x1555 | 37 | 23 | 18 | $-654 | 0.86 | -0.41 | $2,504 | 0 | 0 | $-728 | $-802 | 0.40 | $-4,789 |
| midday_expansion_1200_b3_rr2_x1555 | 44 | 29 | 18 | $-947 | 0.76 | -1.07 | $1,399 | 0 | 0 | $-1,035 | $-1,123 | 0.33 | $-4,309 |
| late_break_1100_b4_rr2_x1555 | 22 | 13 | 11 | $-2,209 | 0.36 | -1.21 | $2,898 | 0 | 0 | $-2,253 | $-2,297 | 0.08 | $-4,943 |

WFO gate:

| total | best | without_best | best_share | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| $-1,328 | $342 | $-1,670 | inf | $-673 | 3 | 16 | False |

By year for best standalone row:

      trades          net        avg
year                                
2026      35  1093.063529  31.230387

By instrument/subtype:

            trades         net        avg
instrument                               
MES             18  369.315551  20.517531
MNQ             17  723.747979  42.573411

                           trades         net         avg
event_subtype                                            
broad-late-liquidation         13  550.061772   42.312444
deep-morning-selloff            2  646.467309  323.233655
full-breadth-late-selloff       7 -997.400025 -142.485718
weak                            6  665.537554  110.922926
wide-midday-chop                7  228.396919   32.628131
