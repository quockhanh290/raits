# Stress Gap-Shock Sleeve Rebuild - 2026-08-21

Scratch-only. No production code modified.

Protocol frozen before reading this pass:

- no daily Stress label;
- event trigger is overnight gap-down in at least 3/4 R4 instruments plus 4/4 below open and VWAP at the 10:30 5-minute bar;
- the 10:30 bar is treated as known at 10:35;
- entries are allowed only from 10:40 onward;
- SHORT only, stop at setup high * 1.001, target 2R, exit 15:55;
- candidates are limited to MNQ/MES break, MNQ-only break, and MNQ/MES retest-fail.

## vault2025

Candidate table:

| name | trades | days | clusters | net | pf | calmar | maxdd | target_rate | stop_rate | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gapshock_full_breadth_break_1040_mnq_mes_rr2 | 6 | 3 | 3 | $1,160 | 50.91 | inf | $0 | 0.00 | 0.00 | 0 | 0 | $1,148 | $1,136 | 1.00 | $496 |
| gapshock_full_breadth_break_1040_mnq_only_rr2 | 3 | 3 | 3 | $647 | 28.85 | 28.02 | $23 | 0.00 | 0.00 | 0 | 0 | $641 | $635 | 0.97 | $226 |
| gapshock_full_breadth_retestfail_1040_mnq_mes_rr2 | 0 | 0 | 0 | $0 | inf | 0.00 | $0 | 0.00 | 0.00 | 0 | 0 | $0 | $0 | 0.00 | $0 |

WFO gate:

| total | best | without_best | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- |
| $0 | $0 | $0 | $0 | 0 | 0 | False |

Best split for `gapshock_full_breadth_break_1040_mnq_mes_rr2`:

      trades      net         avg
year                             
2025       6  1159.81  193.301667

            trades     net         avg
instrument                            
MES              3  512.53  170.843333
MNQ              3  647.28  215.760000

## vault2026

Candidate table:

| name | trades | days | clusters | net | pf | calmar | maxdd | target_rate | stop_rate | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gapshock_full_breadth_break_1040_mnq_mes_rr2 | 8 | 4 | 4 | $20 | 1.04 | 0.06 | $534 | 0.00 | 0.00 | 0 | 0 | $4 | $-12 | 0.60 | $-1,053 |
| gapshock_full_breadth_retestfail_1040_mnq_mes_rr2 | 3 | 2 | 2 | $-56 | 0.69 | -0.49 | $183 | 0.00 | 0.00 | 0 | 0 | $-62 | $-68 | 0.28 | $-365 |
| gapshock_full_breadth_break_1040_mnq_only_rr2 | 4 | 4 | 4 | $-58 | 0.84 | -0.26 | $359 | 0.00 | 0.00 | 0 | 0 | $-66 | $-74 | 0.42 | $-713 |

WFO gate:

| total | best | without_best | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- |
| $0 | $0 | $0 | $0 | 0 | 0 | False |

Best split for `gapshock_full_breadth_break_1040_mnq_mes_rr2`:

      trades    net     avg
year                       
2026       8  19.58  2.4475

            trades    net     avg
instrument                       
MES              4  77.54  19.385
MNQ              4 -57.96 -14.490
