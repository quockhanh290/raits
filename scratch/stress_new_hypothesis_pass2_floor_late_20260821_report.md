# Stress New Hypothesis Pass 2 - 2026-08-21

Scratch-only. No production code modified.

## floor

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| vwap_reject_1200_b3_rr2_x1555 | 17 | 13 | 12 | $161 | 1.40 | 0.08 | $259 | 0 | 0 | $127 | $93 | 0.68 | $-383 |
| late_day_break_1400_b3_rr2_x1555 | 82 | 51 | 48 | $-236 | 0.93 | -0.02 | $1,523 | 0 | 0 | $-400 | $-564 | 0.42 | $-2,514 |
| late_day_break_1400_b4_rr2_x1555 | 60 | 36 | 36 | $-933 | 0.63 | -0.09 | $1,230 | 0 | 0 | $-1,053 | $-1,173 | 0.16 | $-2,438 |

WFO gate:

| total | best | without_best | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- |
| $-703 | $554 | $-1,256 | $-324 | 21 | 59 | False |

Best split for `vwap_reject_1200_b3_rr2_x1555`:

      trades      net     avg
year                         
2018       3 -259.095 -86.365
2019       1   13.760  13.760
2020       3  101.280  33.760
2021       1   23.760  23.760
2022       8  246.080  30.760
2023       1   35.260  35.260

                      trades      net        avg
event_subtype                                   
gapdown                    5 -138.450 -27.690000
gapdown-full-breadth      12  299.495  24.957917
