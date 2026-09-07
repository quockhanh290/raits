# Stress New Hypothesis Pass 2 - 2026-08-21

Scratch-only. No production code modified.

## vault2025

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gapdown_break_1030_b3_rr2_x1555 | 10 | 5 | 5 | $781 | 1.90 | 0.93 | $845 | 0 | 0 | $761 | $741 | 0.74 | $-1,408 |
| vwap_reject_1200_b3_rr2_x1555 | 0 | 0 | 0 | $0 | inf | 0.00 | $0 | 0 | 0 | $0 | $0 | 0.00 | $0 |
| late_day_break_1400_b3_rr2_x1555 | 9 | 6 | 6 | $-711 | 0.01 | -1.01 | $711 | 0 | 0 | $-729 | $-747 | 0.00 | $-1,241 |
| late_day_break_1400_b4_rr2_x1555 | 9 | 6 | 6 | $-711 | 0.01 | -1.01 | $711 | 0 | 0 | $-729 | $-747 | 0.00 | $-1,241 |
| gapdown_break_1130_b3_rr2_x1555 | 10 | 6 | 6 | $-1,477 | 0.20 | -0.92 | $1,621 | 0 | 0 | $-1,497 | $-1,517 | 0.06 | $-3,158 |

WFO gate:

| total | best | without_best | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- |
| $0 | $0 | $0 | $0 | 0 | 3 | False |

Best split for `gapdown_break_1030_b3_rr2_x1555`:

      trades     net     avg
year                        
2025      10  781.43  78.143

                      trades      net         avg
event_subtype                                    
gapdown                    4  -378.38  -94.595000
gapdown-full-breadth       6  1159.81  193.301667

## vault2026

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gapdown_break_1130_b3_rr2_x1555 | 3 | 2 | 2 | $1,513 | 14.91 | 22.09 | $109 | 0 | 0 | $1,507 | $1,501 | 0.74 | $-217 |
| late_day_break_1400_b3_rr2_x1555 | 8 | 5 | 4 | $257 | 1.96 | 1.52 | $267 | 0 | 0 | $241 | $225 | 0.73 | $-322 |
| late_day_break_1400_b4_rr2_x1555 | 6 | 4 | 3 | $150 | 1.56 | 0.89 | $267 | 0 | 0 | $138 | $126 | 0.73 | $-351 |
| vwap_reject_1200_b3_rr2_x1555 | 0 | 0 | 0 | $0 | inf | 0.00 | $0 | 0 | 0 | $0 | $0 | 0.00 | $0 |
| gapdown_break_1030_b3_rr2_x1555 | 9 | 5 | 5 | $-253 | 0.69 | -0.75 | $534 | 0 | 0 | $-271 | $-289 | 0.39 | $-1,338 |

WFO gate:

| total | best | without_best | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- |
| $0 | $0 | $0 | $0 | 0 | 0 | False |

Best split for `gapdown_break_1130_b3_rr2_x1555`:

      trades      net         avg
year                             
2026       3  1512.53  504.176667

                      trades      net      avg
event_subtype                                 
gapdown                    1  -108.74 -108.740
gapdown-full-breadth       2  1621.27  810.635
