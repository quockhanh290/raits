# Stress New Hypothesis Pass - 2026-08-21

Scratch-only. No production code modified.

These rules do not use daily Stress labels and do not tune around the 10:15/10:20 breadth detector.

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
