# Stress Intraday 10:15-Close Causal Pass - 2026-08-21

Scope: scratch-only. No production code modified.

Rules use the fully closed 5-minute bar stamped 10:15 and enter at the 10:20
1-minute open. They do not use daily Stress labels.

## vault2025

Candidate table:

| name | trades | days | clusters | net | pf | sharpe | calmar | maxdd | target_rate | stop_rate | signal_after_entry | same_bar_exit | slip2x_net | slip3x_net |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| causal1015_b4_rr2_x1555 | 88 | 45 | 30 | $5,322 | 1.80 | 1.27 | 4.67 | $1,170 | 0.06 | 0.20 | 0 | 0 | $5,167 | $5,011 |
| causal1015_b3_rr2_x1555 | 137 | 75 | 40 | $4,955 | 1.49 | 1.10 | 2.22 | $2,288 | 0.07 | 0.26 | 0 | 0 | $4,705 | $4,456 |
| causal1015_b4_wide3_rr2_x1555 | 38 | 20 | 14 | $4,385 | 2.27 | 1.28 | 4.66 | $1,091 | 0.08 | 0.16 | 0 | 0 | $4,317 | $4,249 |
| causal1015_b4_mnq_rr2_x1555 | 43 | 43 | 30 | $4,008 | 2.05 | 1.53 | 5.38 | $765 | 0.05 | 0.19 | 0 | 0 | $3,965 | $3,922 |
| causal1015_b4_rr15_x1400 | 88 | 45 | 30 | $3,279 | 1.48 | 0.92 | 2.77 | $1,213 | 0.12 | 0.17 | 0 | 0 | $3,123 | $2,968 |

Swing overlap:

| name | held | opposite | conflict_days | opposite_net | opposite_gross |
| --- | --- | --- | --- | --- | --- |
| causal1015_b4_rr2_x1555 | 34 | 20 | 13 | $1,634 | $3,614 |
| causal1015_b3_rr2_x1555 | 55 | 32 | 22 | $1,200 | $5,255 |
| causal1015_b4_wide3_rr2_x1555 | 19 | 10 | 6 | $1,262 | $1,888 |
| causal1015_b4_mnq_rr2_x1555 | 17 | 12 | 12 | $1,531 | $2,623 |
| causal1015_b4_rr15_x1400 | 34 | 20 | 13 | $1,760 | $3,248 |

Calm overlap:

| name | held | opposite | conflict_days | opposite_net | opposite_gross |
| --- | --- | --- | --- | --- | --- |
| causal1015_b4_rr2_x1555 | 7 | 7 | 4 | $131 | $1,285 |
| causal1015_b3_rr2_x1555 | 8 | 8 | 5 | $-35 | $1,451 |
| causal1015_b4_wide3_rr2_x1555 | 1 | 1 | 1 | $-468 | $468 |
| causal1015_b4_mnq_rr2_x1555 | 4 | 4 | 4 | $-43 | $1,046 |
| causal1015_b4_rr15_x1400 | 7 | 7 | 4 | $654 | $1,270 |

Event bootstrap:

| name | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| causal1015_b4_rr2_x1555 | 30 | 0.96 | $410 | $5,174 | $10,599 |
| causal1015_b3_rr2_x1555 | 40 | 0.93 | $-475 | $4,838 | $10,716 |
| causal1015_b4_wide3_rr2_x1555 | 14 | 0.96 | $183 | $4,301 | $8,820 |
| causal1015_b4_mnq_rr2_x1555 | 30 | 0.98 | $745 | $3,914 | $7,533 |
| causal1015_b4_rr15_x1400 | 30 | 0.90 | $-853 | $3,283 | $7,320 |

Chronological event WFO:

| test_cluster | selected | event_subtype | trades | net | pf |
| --- | --- | --- | --- | --- | --- |
| E009 | causal1015_b4_wide3_rr2_x1555 | broad-liquidation | 4 | $-94 | 0.81 |
| E010 | causal1015_b4_wide3_rr2_x1555 | broad-liquidation | 2 | $98 | inf |
| E011 | causal1015_b4_rr2_x1555 | broad-liquidation | 4 | $-94 | 0.81 |
| E012 | causal1015_b3_rr2_x1555 | broad-liquidation | 8 | $-142 | 0.78 |
| E013 | causal1015_b3_rr2_x1555 | broad-liquidation | 2 | $98 | inf |
| E014 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-210 | 0.48 |
| E015 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $301 | 11.02 |
| E016 | causal1015_b3_rr2_x1555 | wide-chop | 3 | $-656 | 0.00 |
| E017 | causal1015_b3_rr2_x1555 | weak | 1 | $-166 | 0.00 |
| E018 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $17 | inf |
| E019 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $86 | inf |
| E020 | causal1015_b3_rr2_x1555 | weak | 2 | $-49 | 0.00 |
| E021 | causal1015_b3_rr2_x1555 | opening-selloff | 5 | $190 | 1.99 |
| E022 | causal1015_b3_rr2_x1555 | weak | 2 | $-357 | 0.00 |
| E023 | causal1015_b3_rr2_x1555 | weak | 2 | $371 | inf |
| E024 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 3 | $584 | inf |
| E025 | causal1015_b3_rr2_x1555 | opening-selloff | 1 | $29 | inf |
| E026 | causal1015_b3_rr2_x1555 | broad-liquidation | 2 | $-668 | 0.00 |
| E027 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-362 | 0.12 |
| E028 | causal1015_b3_rr2_x1555 | weak | 4 | $-287 | 0.20 |
| E029 | causal1015_b3_rr2_x1555 | weak | 2 | $-214 | 0.00 |
| E030 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $-98 | 0.05 |
| E031 | causal1015_b4_rr2_x1555 | no selected trade | 0 | $0 | inf |
| E032 | causal1015_b4_rr2_x1555 | no selected trade | 0 | $0 | inf |
| E033 | causal1015_b4_rr2_x1555 | no selected trade | 0 | $0 | inf |
| E034 | causal1015_b4_rr2_x1555 | no selected trade | 0 | $0 | inf |
| E035 | causal1015_b3_rr2_x1555 | weak | 2 | $-405 | 0.00 |
| E036 | causal1015_b4_rr2_x1555 | no selected trade | 0 | $0 | inf |
| E037 | causal1015_b4_rr2_x1555 | no selected trade | 0 | $0 | inf |
| E038 | causal1015_b4_rr2_x1555 | no selected trade | 0 | $0 | inf |
| E039 | causal1015_b4_rr2_x1555 | no selected trade | 0 | $0 | inf |
| E040 | causal1015_b4_rr2_x1555 | no selected trade | 0 | $0 | inf |

WFO concentration gate:

| total | best | without_best | best_share | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| $-2,029 | $584 | $-2,613 | inf | $0 | 9 | 32 | False |

By year/instrument/subtype for `causal1015_b4_rr2_x1555`:

 year  trades        net       avg       pf
 2025      88 5322.29525 60.480628 1.799192

inst  trades        net      avg       pf
 MES      45 1314.05625 29.20125 1.459483
 MNQ      43 4008.23900 93.21486 2.054874

       event_subtype  trades        net        avg       pf
   broad-liquidation      38 4385.29200 115.402421 2.272054
full-breadth-selloff      50  937.00325  18.740065 1.291703

By year/instrument/subtype for `causal1015_b4_wide3_rr2_x1555`:

 year  trades      net        avg       pf
 2025      38 4385.292 115.402421 2.272054

inst  trades      net        avg       pf
 MES      20 1178.410  58.920500 1.689884
 MNQ      18 3206.882 178.160111 2.843794

    event_subtype  trades      net        avg       pf
broad-liquidation      38 4385.292 115.402421 2.272054

By year/instrument/subtype for `causal1015_b4_rr15_x1400`:

 year  trades      net       avg       pf
 2025      88 3278.883 37.260034 1.475207

inst  trades       net       avg       pf
 MES      45  302.7375  6.727500 1.101155
 MNQ      43 2976.1455 69.212686 1.761729

       event_subtype  trades        net       avg       pf
   broad-liquidation      38 1940.85225 51.075059 1.500160
full-breadth-selloff      50 1338.03075 26.760615 1.443139

By year/instrument/subtype for `causal1015_b4_mnq_rr2_x1555`:

 year  trades      net      avg       pf
 2025      43 4008.239 93.21486 2.054874

inst  trades      net      avg       pf
 MNQ      43 4008.239 93.21486 2.054874

       event_subtype  trades      net        avg       pf
   broad-liquidation      18 3206.882 178.160111 2.843794
full-breadth-selloff      25  801.357  32.054280 1.388924

By year/instrument/subtype for `causal1015_b3_rr2_x1555`:

 year  trades        net       avg       pf
 2025     137 4954.59625 36.164936 1.489778

inst  trades        net       avg       pf
 MES      75 1306.57125 17.420950 1.286059
 MNQ      62 3648.02500 58.839113 1.657477

       event_subtype  trades         net        avg       pf
   broad-liquidation      38  4385.29200 115.402421 2.272054
full-breadth-selloff      50   937.00325  18.740065 1.291703
     opening-selloff       8  1024.39375 128.049219 6.234812
                weak      37 -1059.70150 -28.640581 0.628640
           wide-chop       4  -332.39125 -83.097812 0.183637

## vault2026

Candidate table:

| name | trades | days | clusters | net | pf | sharpe | calmar | maxdd | target_rate | stop_rate | signal_after_entry | same_bar_exit | slip2x_net | slip3x_net |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| causal1015_b4_mnq_rr2_x1555 | 18 | 18 | 15 | $-339 | 0.88 | -0.27 | -0.65 | $897 | 0.00 | 0.28 | 0 | 0 | $-357 | $-375 |
| causal1015_b3_rr2_x1555 | 74 | 41 | 24 | $-1,188 | 0.88 | -0.38 | -0.43 | $4,421 | 0.08 | 0.34 | 0 | 0 | $-1,324 | $-1,459 |
| causal1015_b4_rr2_x1555 | 40 | 22 | 16 | $-1,754 | 0.68 | -0.89 | -1.45 | $2,097 | 0.03 | 0.30 | 0 | 0 | $-1,827 | $-1,900 |
| causal1015_b4_rr15_x1400 | 40 | 22 | 16 | $-3,064 | 0.39 | -1.98 | -1.62 | $3,280 | 0.00 | 0.20 | 0 | 0 | $-3,137 | $-3,210 |
| causal1015_b4_wide3_rr2_x1555 | 20 | 12 | 10 | $-3,201 | 0.34 | -1.99 | -2.08 | $3,065 | 0.00 | 0.50 | 0 | 0 | $-3,239 | $-3,277 |

Swing overlap:

| name | held | opposite | conflict_days | opposite_net | opposite_gross |
| --- | --- | --- | --- | --- | --- |
| causal1015_b4_mnq_rr2_x1555 | 9 | 3 | 3 | $-867 | $867 |
| causal1015_b3_rr2_x1555 | 31 | 17 | 12 | $-730 | $5,570 |
| causal1015_b4_rr2_x1555 | 17 | 7 | 5 | $-1,088 | $1,647 |
| causal1015_b4_rr15_x1400 | 17 | 7 | 5 | $-1,688 | $1,703 |
| causal1015_b4_wide3_rr2_x1555 | 10 | 3 | 2 | $-986 | $986 |

Calm overlap:

| name | held | opposite | conflict_days | opposite_net | opposite_gross |
| --- | --- | --- | --- | --- | --- |
| causal1015_b4_mnq_rr2_x1555 | 1 | 1 | 1 | $195 | $195 |
| causal1015_b3_rr2_x1555 | 5 | 5 | 4 | $-434 | $1,199 |
| causal1015_b4_rr2_x1555 | 2 | 2 | 1 | $310 | $310 |
| causal1015_b4_rr15_x1400 | 2 | 2 | 1 | $267 | $267 |
| causal1015_b4_wide3_rr2_x1555 | 0 | 0 | 0 | $0 | $0 |

Event bootstrap:

| name | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| causal1015_b4_mnq_rr2_x1555 | 15 | 0.42 | $-2,721 | $-301 | $2,160 |
| causal1015_b3_rr2_x1555 | 24 | 0.40 | $-7,710 | $-1,026 | $5,064 |
| causal1015_b4_rr2_x1555 | 16 | 0.23 | $-5,790 | $-1,794 | $2,226 |
| causal1015_b4_rr15_x1400 | 16 | 0.02 | $-5,632 | $-3,070 | $-593 |
| causal1015_b4_wide3_rr2_x1555 | 10 | 0.05 | $-6,356 | $-3,147 | $40 |

Chronological event WFO:

| test_cluster | selected | event_subtype | trades | net | pf |
| --- | --- | --- | --- | --- | --- |
| E009 | causal1015_b3_rr2_x1555 | broad-liquidation | 7 | $-338 | 0.67 |
| E010 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $1,275 | inf |
| E011 | causal1015_b3_rr2_x1555 | broad-liquidation | 2 | $537 | inf |
| E012 | causal1015_b3_rr2_x1555 | broad-liquidation | 4 | $-796 | 0.06 |
| E013 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $-476 | 0.00 |
| E014 | causal1015_b3_rr2_x1555 | weak | 1 | $-29 | 0.00 |
| E015 | causal1015_b3_rr2_x1555 | opening-selloff | 4 | $-1,586 | 0.00 |
| E016 | causal1015_b3_rr2_x1555 | opening-selloff | 1 | $752 | inf |
| E017 | causal1015_b3_rr2_x1555 | weak | 2 | $855 | inf |
| E018 | causal1015_b3_rr2_x1555 | broad-liquidation | 1 | $-365 | 0.00 |
| E019 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-801 | 0.00 |
| E020 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-264 | 0.54 |
| E021 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $502 | inf |
| E022 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 7 | $-2,212 | 0.10 |
| E023 | causal1015_b4_mnq_rr2_x1555 | no selected trade | 0 | $0 | inf |
| E024 | causal1015_b4_mnq_rr2_x1555 | no selected trade | 0 | $0 | inf |

WFO concentration gate:

| total | best | without_best | best_share | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| $-2,948 | $1,275 | $-4,223 | inf | $-1,710 | 5 | 16 | False |

By year/instrument/subtype for `causal1015_b4_rr2_x1555`:

 year  trades        net        avg       pf
 2026      40 -1754.0885 -43.852212 0.676714

inst  trades        net        avg       pf
 MES      22 -1415.4650 -64.339318 0.457174
 MNQ      18  -338.6235 -18.812417 0.879845

       event_subtype  trades         net         avg       pf
   broad-liquidation      20 -3200.56525 -160.028262 0.335276
full-breadth-selloff      20  1446.47675   72.323838 3.367651

By year/instrument/subtype for `causal1015_b4_wide3_rr2_x1555`:

 year  trades         net         avg       pf
 2026      20 -3200.56525 -160.028262 0.335276

inst  trades         net         avg       pf
 MES      12 -1841.88375 -153.490312 0.223461
 MNQ       8 -1358.68150 -169.835187 0.443838

    event_subtype  trades         net         avg       pf
broad-liquidation      20 -3200.56525 -160.028262 0.335276

By year/instrument/subtype for `causal1015_b4_rr15_x1400`:

 year  trades         net        avg       pf
 2026      40 -3064.49175 -76.612294 0.390805

inst  trades         net        avg       pf
 MES      22 -1677.61375 -76.255170 0.262650
 MNQ      18 -1386.87800 -77.048778 0.496632

       event_subtype  trades         net         avg       pf
   broad-liquidation      20 -2827.68850 -141.384425 0.261073
full-breadth-selloff      20  -236.80325  -11.840162 0.803261

By year/instrument/subtype for `causal1015_b4_mnq_rr2_x1555`:

 year  trades       net        avg       pf
 2026      18 -338.6235 -18.812417 0.879845

inst  trades       net        avg       pf
 MNQ      18 -338.6235 -18.812417 0.879845

       event_subtype  trades        net         avg       pf
   broad-liquidation       8 -1358.6815 -169.835187 0.443838
full-breadth-selloff      10  1020.0580  102.005800 3.718256

By year/instrument/subtype for `causal1015_b3_rr2_x1555`:

 year  trades         net       avg     pf
 2026      74 -1188.49775 -16.06078 0.8817

inst  trades        net        avg       pf
 MES      41 -422.53125 -10.305640 0.891929
 MNQ      33 -765.96650 -23.211106 0.875183

       event_subtype  trades         net         avg       pf
   broad-liquidation      20 -3200.56525 -160.028262 0.335276
full-breadth-selloff      20  1446.47675   72.323838 3.367651
     opening-selloff      12   297.08925   24.757437 1.137979
                weak      22   268.50150   12.204614 1.108815

## Verdict

Read the floor WFO gate plus OOS/slippage/overlap together. A standalone
positive row is not enough for this branch.
