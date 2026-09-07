# Stress Gap-Shock Sleeve Rebuild - 2026-08-21

Scratch-only. No production code modified.

Protocol frozen before reading this pass:

- no daily Stress label;
- event trigger is overnight gap-down in at least 3/4 R4 instruments plus 4/4 below open and VWAP at the 10:30 5-minute bar;
- the 10:30 bar is treated as known at 10:35;
- entries are allowed only from 10:40 onward;
- SHORT only, stop at setup high * 1.001, target 2R, exit 15:55;
- candidates are limited to MNQ/MES break, MNQ-only break, and MNQ/MES retest-fail.

## floor

Candidate table:

| name | trades | days | clusters | net | pf | calmar | maxdd | target_rate | stop_rate | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gapshock_full_breadth_break_1040_mnq_mes_rr2 | 101 | 57 | 51 | $3,208 | 1.58 | 0.31 | $1,295 | 0.02 | 0.16 | 0 | 0 | $3,006 | $2,804 | 0.90 | $-842 |
| gapshock_full_breadth_break_1040_mnq_only_rr2 | 46 | 46 | 43 | $2,554 | 1.98 | 0.48 | $670 | 0.02 | 0.11 | 0 | 0 | $2,462 | $2,370 | 0.97 | $369 |
| gapshock_full_breadth_retestfail_1040_mnq_mes_rr2 | 23 | 15 | 15 | $1,138 | 2.86 | 0.58 | $246 | 0.04 | 0.13 | 0 | 0 | $1,092 | $1,046 | 0.95 | $-40 |

WFO gate:

| total | best | without_best | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- |
| $2,053 | $944 | $1,110 | $624 | 22 | 43 | True |

Best split for `gapshock_full_breadth_break_1040_mnq_mes_rr2`:

      trades         net         avg
year                                
2018       6  -211.92375  -35.320625
2019      18   406.42175   22.578986
2020       9   187.47900   20.831000
2021       5   530.30000  106.060000
2022      32  2032.30500   63.509531
2023      18  -419.75900  -23.319944
2024      13   683.13000   52.548462

            trades        net        avg
instrument                              
MES             55   653.5325  11.882409
MNQ             46  2554.4205  55.530880
