# Stress Intraday Static Candidate Audit - 2026-08-21

Scope: scratch-only. No production code modified.

Frozen candidate: `liq_1020_b4_rr2_x1555` from the intraday detector pass.
Critical check: the 5-minute bar stamped 10:20 is not known until 10:25, so this
report measures both the as-measured version and a causal 10:25 entry repair.

## floor

Static candidate audit:

| name | trades | days | clusters | net | pf | sharpe | calmar | maxdd | target_rate | stop_rate | slip2x_net | slip3x_net |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| as_measured | 699 | 358 | 237 | $10,982 | 1.27 | 0.58 | 0.57 | $2,577 | 0.14 | 0.27 | 9747.23 | 8512.73 |
| causal_delay1025 | 692 | 357 | 237 | $3,411 | 1.08 | 0.18 | 0.11 | $4,374 | 0.11 | 0.27 | 2184.65 | 958.65 |

Timing audit:

| name | signal_after_entry | needs_delay | same_bar_exit | outside_exit_bar |
| --- | --- | --- | --- | --- |
| as_measured | 699 | 699 | 0 | 0 |
| causal_delay1025 | 0 | 0 | 0 | 0 |

Swing same-symbol overlap:

| name | held | opposite | conflict_days | opposite_net | opposite_gross |
| --- | --- | --- | --- | --- | --- |
| as_measured | 296 | 171 | 116 | 4325.28 | 26639.04 |
| causal_delay1025 | 291 | 168 | 113 | 1052.50 | 25934.65 |

Calm same-symbol overlap (`on_neg_fade_mod001_010_x1555` saved logs):

| name | held | opposite | conflict_days | opposite_net | opposite_gross |
| --- | --- | --- | --- | --- | --- |
| as_measured | 63 | 63 | 39 | -1369.94 | 5742.06 |
| causal_delay1025 | 63 | 63 | 39 | -2264.24 | 6122.70 |

Event bootstrap:

| name | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| as_measured | 237 | 0.97 | 1297.80 | 10915.15 | 20763.85 |
| causal_delay1025 | 237 | 0.72 | -6140.40 | 3337.92 | 13135.31 |

By instrument/year/subtype for `as_measured`:

inst  trades        net       avg       pf
 MES     357 3429.33375  9.605977 1.200740
 MNQ     342 7552.40100 22.083044 1.322077

 year  trades        net       avg       pf
 2017      36  -43.01000 -1.194722 0.929651
 2018     102 1894.79900 18.576461 1.428899
 2019     112 -533.17525 -4.760493 0.865902
 2020      76 1884.54725 24.796674 1.400473
 2021      76 -578.86375 -7.616628 0.892145
 2022     124 5301.95525 42.757704 1.580280
 2023      78 1335.51600 17.122000 1.358874
 2024      95 1719.96625 18.104908 1.200086

    event_subtype  trades        net       avg       pf
broad-liquidation     215 6712.37425 31.220345 1.382507
  opening-selloff     302 2106.47125  6.975070 1.130232
             weak     182 2162.88925 11.884007 1.317634

By instrument/year/subtype for `causal_delay1025`:

inst  trades       net      avg       pf
 MES     356  622.1650 1.747654 1.033278
 MNQ     336 2788.4865 8.299067 1.109127

 year  trades         net        avg       pf
 2017      36  -287.01000  -7.972500 0.642181
 2018     102  1121.20575  10.992213 1.223406
 2019     112  -707.86325  -6.320208 0.832695
 2020      73  1196.20075  16.386312 1.226923
 2021      76 -2055.44125 -27.045280 0.650252
 2022     121  3501.51475  28.938138 1.359350
 2023      78   242.17850   3.104853 1.056205
 2024      94   399.86625   4.253896 1.044451

    event_subtype  trades         net       avg       pf
broad-liquidation     208  4069.80225 19.566357 1.219417
  opening-selloff     302 -1021.01475 -3.380844 0.943344
             weak     182   361.86400  1.988264 1.047123

## vault2025

Static candidate audit:

| name | trades | days | clusters | net | pf | sharpe | calmar | maxdd | target_rate | stop_rate | slip2x_net | slip3x_net |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| as_measured | 86 | 44 | 31 | $6,952 | 2.14 | 1.67 | 5.38 | $1,357 | 0.15 | 0.26 | 6800.04 | 6648.04 |
| causal_delay1025 | 83 | 43 | 31 | $4,088 | 1.65 | 1.16 | 3.32 | $1,294 | 0.13 | 0.25 | 3940.55 | 3793.05 |

Timing audit:

| name | signal_after_entry | needs_delay | same_bar_exit | outside_exit_bar |
| --- | --- | --- | --- | --- |
| as_measured | 86 | 86 | 0 | 0 |
| causal_delay1025 | 0 | 0 | 0 | 0 |

Swing same-symbol overlap:

| name | held | opposite | conflict_days | opposite_net | opposite_gross |
| --- | --- | --- | --- | --- | --- |
| as_measured | 37 | 25 | 15 | 2104.80 | 4505.14 |
| causal_delay1025 | 34 | 25 | 15 | 2065.44 | 4879.78 |

Calm same-symbol overlap (`on_neg_fade_mod001_010_x1555` saved logs):

| name | held | opposite | conflict_days | opposite_net | opposite_gross |
| --- | --- | --- | --- | --- | --- |
| as_measured | 8 | 8 | 5 | -335.63 | 1751.19 |
| causal_delay1025 | 8 | 8 | 5 | -543.13 | 1731.21 |

Event bootstrap:

| name | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| as_measured | 31 | 1.00 | 2654.92 | 7003.74 | 11424.28 |
| causal_delay1025 | 31 | 0.94 | -93.10 | 4097.02 | 8373.40 |

By instrument/year/subtype for `as_measured`:

inst  trades      net        avg       pf
 MES      44 2160.085  49.092841 1.841059
 MNQ      42 4791.958 114.094238 2.365649

 year  trades      net       avg       pf
 2025      86 6952.043 80.837709 2.143952

    event_subtype  trades        net        avg       pf
broad-liquidation      34 4060.35700 119.422265 2.218399
  opening-selloff      26 3065.63875 117.909183 4.857065
             weak      26 -173.95275  -6.690490 0.910788

By instrument/year/subtype for `causal_delay1025`:

inst  trades       net       avg       pf
 MES      43  759.3050 17.658256 1.264264
 MNQ      40 3328.7455 83.218638 1.982673

 year  trades       net      avg       pf
 2025      83 4088.0505 49.25362 1.652968

    event_subtype  trades        net        avg       pf
broad-liquidation      31 1912.47050  61.692597 1.632994
  opening-selloff      26 2578.53275  99.174337 4.210959
             weak      26 -402.95275 -15.498183 0.834609

## vault2026

Static candidate audit:

| name | trades | days | clusters | net | pf | sharpe | calmar | maxdd | target_rate | stop_rate | slip2x_net | slip3x_net |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| as_measured | 51 | 27 | 19 | $2,776 | 1.57 | 1.12 | 3.36 | $1,439 | 0.16 | 0.22 | 2684.02 | 2592.52 |
| causal_delay1025 | 48 | 27 | 19 | $1,743 | 1.31 | 0.67 | 1.93 | $1,572 | 0.10 | 0.25 | 1654.29 | 1565.79 |

Timing audit:

| name | signal_after_entry | needs_delay | same_bar_exit | outside_exit_bar |
| --- | --- | --- | --- | --- |
| as_measured | 51 | 51 | 0 | 0 |
| causal_delay1025 | 0 | 0 | 0 | 0 |

Swing same-symbol overlap:

| name | held | opposite | conflict_days | opposite_net | opposite_gross |
| --- | --- | --- | --- | --- | --- |
| as_measured | 23 | 12 | 8 | -236.26 | 3651.57 |
| causal_delay1025 | 23 | 12 | 8 | -795.54 | 3913.29 |

Calm same-symbol overlap (`on_neg_fade_mod001_010_x1555` saved logs):

| name | held | opposite | conflict_days | opposite_net | opposite_gross |
| --- | --- | --- | --- | --- | --- |
| as_measured | 3 | 3 | 2 | 627.84 | 627.84 |
| causal_delay1025 | 3 | 3 | 2 | 447.56 | 734.87 |

Event bootstrap:

| name | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| as_measured | 19 | 0.82 | -2209.41 | 2818.00 | 7637.64 |
| causal_delay1025 | 19 | 0.69 | -3820.54 | 1745.77 | 7131.40 |

By instrument/year/subtype for `as_measured`:

inst  trades       net        avg       pf
 MES      27  237.1425   8.783056 1.110925
 MNQ      24 2538.3815 105.765896 1.919337

 year  trades      net       avg       pf
 2026      51 2775.524 54.422039 1.566552

    event_subtype  trades        net        avg       pf
broad-liquidation      27 -879.17975 -32.562213 0.765196
  opening-selloff      14 3356.81275 239.772339 7.190946
             weak      10  297.89100  29.789100 1.486393

By instrument/year/subtype for `causal_delay1025`:

inst  trades        net        avg       pf
 MES      27 -465.31375 -17.233843 0.819314
 MNQ      21 2208.10150 105.147690 1.718171

 year  trades        net       avg       pf
 2026      48 1742.78775 36.308078 1.308465

    event_subtype  trades         net        avg       pf
broad-liquidation      24 -1657.45975 -69.060823 0.594437
  opening-selloff      14  3222.38650 230.170464 4.898212
             weak      10   177.86100  17.786100 1.241515

## Verdict

The as-measured headline must be discarded: every trade uses the 10:20 5-minute
bar before that bar is complete.

The causal 10:25 repair stays positive in 2025 and 2026, but floor edge is thin
(+$3,411, PF 1.08), 3x slippage leaves only about +$959, and same-symbol conflict
is large against both swing and Calm. Reject `liq_1020_b4_rr2_x1555` as a
paper/deploy candidate. Keep it only as evidence that cross-index intraday
liquidation breadth is worth studying with a cleaner causal entry design.
