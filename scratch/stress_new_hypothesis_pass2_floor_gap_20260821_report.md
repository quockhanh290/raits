# Stress New Hypothesis Pass 2 - 2026-08-21

Scratch-only. No production code modified.

## floor

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gapdown_break_1030_b3_rr2_x1555 | 152 | 90 | 80 | $1,776 | 1.17 | 0.09 | $2,607 | 0 | 0 | $1,472 | $1,168 | 0.70 | $-3,051 |
| gapdown_break_1130_b3_rr2_x1555 | 120 | 71 | 64 | $306 | 1.04 | 0.01 | $2,746 | 0 | 0 | $66 | $-174 | 0.56 | $-3,918 |

WFO gate:

| total | best | without_best | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- |
| $-51 | $869 | $-920 | $630 | 30 | 78 | False |

Best split for `gapdown_break_1030_b3_rr2_x1555`:

      trades         net        avg
year                               
2018      12  -529.90775 -44.158979
2019      18   586.23925  32.568847
2020      15  -477.16350 -31.810900
2021      12   -78.43750  -6.536458
2022      51  1475.19975  28.925485
2023      27  -585.66650 -21.691352
2024      17  1385.92000  81.524706

                      trades         net        avg
event_subtype                                      
gapdown                   45 -2115.97300 -47.021622
gapdown-full-breadth     107  3892.15675  36.375297
