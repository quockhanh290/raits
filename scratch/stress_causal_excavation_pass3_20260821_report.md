# Stress Causal Excavation Pass 3 - 2026-08-21

Scope: scratch-only. Production code was not modified.

This pass intentionally does not tune on lag-0 Stress labels. All candidates
use lag-1 regime labels and only features available at or before the tested entry.

Acceptance gate, declared before reading this pass:

- held-out event-WFO total must stay positive after removing the single best cluster;
- no single cluster may contribute more than 50% of held-out net;
- final four folds must not be negative after selection converges;
- promoted primary must be selected by its own folds, not by another strategy family.

## floor

Top causal lag-1 candidates by standalone net:

| name | trades | days | clusters | net | pf | sharpe_calendar | calmar_calendar | maxdd | target_rate | stop_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exit1555__no_bear | 63 | 33 | 12 | $2,695 | 1.59 | 0.44 | 0.33 | $1,730 | 0.29 | 0.43 |
| rr25__no_bear | 63 | 33 | 12 | $2,522 | 1.59 | 0.43 | 0.28 | $1,871 | 0.16 | 0.37 |
| exit1555__crash_only | 57 | 29 | 10 | $2,440 | 1.57 | 0.41 | 0.34 | $1,516 | 0.28 | 0.44 |
| exit1555__range_ge_100bp | 33 | 17 | 7 | $2,175 | 1.95 | 0.49 | 0.71 | $812 | 0.24 | 0.39 |
| rr25__crash_only | 57 | 29 | 10 | $2,124 | 1.53 | 0.38 | 0.27 | $1,658 | 0.14 | 0.37 |
| rr25__range_ge_100bp | 33 | 17 | 7 | $1,932 | 1.96 | 0.48 | 0.54 | $954 | 0.09 | 0.27 |
| breadth3_mnq_mes__no_bear | 63 | 33 | 12 | $1,822 | 1.43 | 0.34 | 0.20 | $1,871 | 0.21 | 0.37 |
| breadth3_mnq_mes__range_ge_100bp | 33 | 17 | 7 | $1,705 | 1.85 | 0.45 | 0.47 | $954 | 0.15 | 0.27 |
| wide3_mnq_mes__range_ge_100bp | 33 | 17 | 7 | $1,705 | 1.85 | 0.45 | 0.47 | $954 | 0.15 | 0.27 |
| wide3_mnq_mes__stop_le_125bp | 53 | 29 | 10 | $1,678 | 1.49 | 0.37 | 0.29 | $1,256 | 0.21 | 0.36 |
| rr25__stop_le_125bp | 74 | 41 | 12 | $1,677 | 1.34 | 0.30 | 0.21 | $1,663 | 0.16 | 0.41 |
| wide3_mnq_mes | 57 | 29 | 10 | $1,538 | 1.38 | 0.30 | 0.20 | $1,658 | 0.19 | 0.37 |
| breadth3_mnq_mes__crash_only | 57 | 29 | 10 | $1,538 | 1.38 | 0.30 | 0.20 | $1,658 | 0.19 | 0.37 |
| wide3_mnq_mes__crash_only | 57 | 29 | 10 | $1,538 | 1.38 | 0.30 | 0.20 | $1,658 | 0.19 | 0.37 |
| wide3_mnq_mes__no_bear | 57 | 29 | 10 | $1,538 | 1.38 | 0.30 | 0.20 | $1,658 | 0.19 | 0.37 |
| rr25 | 78 | 41 | 12 | $1,538 | 1.28 | 0.25 | 0.16 | $2,064 | 0.15 | 0.41 |
| exit1555 | 78 | 41 | 12 | $1,503 | 1.25 | 0.23 | 0.16 | $1,923 | 0.26 | 0.49 |
| rr15__no_bear | 63 | 33 | 12 | $1,480 | 1.35 | 0.30 | 0.17 | $1,871 | 0.30 | 0.37 |
| delay1025__no_bear | 61 | 33 | 12 | $1,465 | 1.36 | 0.31 | 0.18 | $1,754 | 0.25 | 0.38 |
| delay1025__range_ge_100bp | 31 | 17 | 7 | $1,451 | 1.76 | 0.43 | 0.47 | $810 | 0.19 | 0.29 |
| exit1555__stop_le_125bp | 74 | 41 | 12 | $1,386 | 1.26 | 0.24 | 0.17 | $1,757 | 0.27 | 0.49 |
| delay1025__crash_only | 55 | 29 | 10 | $1,375 | 1.36 | 0.30 | 0.19 | $1,535 | 0.24 | 0.38 |
| mnq_only__no_bear | 31 | 31 | 11 | $1,359 | 1.58 | 0.42 | 0.26 | $1,082 | 0.19 | 0.35 |
| rr15__range_ge_100bp | 33 | 17 | 7 | $1,353 | 1.67 | 0.39 | 0.38 | $954 | 0.24 | 0.27 |
| rr15__crash_only | 57 | 29 | 10 | $1,312 | 1.33 | 0.28 | 0.17 | $1,658 | 0.30 | 0.37 |
| mnq_only__range_ge_100bp | 17 | 17 | 7 | $1,190 | 2.05 | 0.51 | 0.49 | $645 | 0.12 | 0.29 |
| late_cont_break | 37 | 22 | 10 | $1,133 | 1.50 | 0.32 | 0.34 | $696 | 0.11 | 0.38 |
| mnq_only__crash_only | 29 | 29 | 10 | $1,097 | 1.47 | 0.35 | 0.22 | $1,082 | 0.17 | 0.38 |
| delay1025__stop_le_125bp | 74 | 41 | 12 | $1,078 | 1.22 | 0.22 | 0.16 | $1,442 | 0.24 | 0.41 |
| wide3_mnq_mes__below4 | 48 | 24 | 10 | $1,064 | 1.31 | 0.23 | 0.16 | $1,395 | 0.23 | 0.33 |
| exit1555__wide4 | 37 | 19 | 8 | $1,049 | 1.37 | 0.23 | 0.18 | $1,275 | 0.22 | 0.43 |
| rr25__stop_le_100bp | 67 | 39 | 12 | $1,027 | 1.24 | 0.23 | 0.16 | $1,336 | 0.16 | 0.43 |
| breadth3_mnq_mes__stop_le_125bp | 74 | 41 | 12 | $915 | 1.19 | 0.18 | 0.12 | $1,663 | 0.20 | 0.41 |
| mnq_only__stop_le_125bp | 35 | 35 | 12 | $845 | 1.34 | 0.28 | 0.23 | $786 | 0.20 | 0.37 |
| wide3_mnq_mes__stop_le_100bp | 47 | 27 | 10 | $844 | 1.27 | 0.23 | 0.17 | $1,054 | 0.21 | 0.40 |
| rr25__below4 | 58 | 29 | 11 | $827 | 1.18 | 0.15 | 0.11 | $1,588 | 0.17 | 0.41 |
| exit1200__crash_only | 57 | 29 | 10 | $811 | 1.25 | 0.21 | 0.11 | $1,511 | 0.11 | 0.26 |
| breadth3_mnq_mes | 78 | 41 | 12 | $776 | 1.14 | 0.14 | 0.08 | $2,064 | 0.19 | 0.41 |
| exit1200__range_ge_100bp | 33 | 17 | 7 | $757 | 1.43 | 0.26 | 0.25 | $808 | 0.03 | 0.21 |
| mnq_only | 38 | 38 | 12 | $705 | 1.23 | 0.21 | 0.12 | $1,187 | 0.18 | 0.39 |

Full candidate-set chronological event WFO:

| test_cluster | event_subtype | selected | trades | net | pf |
| --- | --- | --- | --- | --- | --- |
| E005 | crash-gap/liquidation | rr25__stop_le_75bp | 3 | $-347 | 0.00 |
| E006 | crash-gap/liquidation | delay1025__stop_le_100bp | 10 | $-480 | 0.24 |
| E007 | crash-gap/liquidation | exit1200__stop_le_75bp | 3 | $59 | 1.31 |
| E009 | crash-gap/liquidation | rr25__no_bear | 6 | $1,912 | inf |
| E010 | crash-gap/liquidation | exit1555__no_bear | 4 | $269 | 1.40 |
| E012 | false stress / chop | exit1555__no_bear | 5 | $-499 | 0.00 |
| E013 | false stress / chop | exit1555__crash_only | 0 | $0 | inf |
| E014 | crash-gap/liquidation | exit1555__crash_only | 10 | $-296 | 0.58 |
| E016 | false stress / chop | exit1555__crash_only | 0 | $0 | inf |

Full candidate-set concentration gate:

| total | best | without_best | best_share | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 617.54 | 1911.56 | -1294.02 | 3.10 | -794.65 | 3 | 9 | False |

Restricted predeclared-family chronological event WFO:

| test_cluster | event_subtype | selected | trades | net | pf |
| --- | --- | --- | --- | --- | --- |
| E005 | crash-gap/liquidation | mnq_only | 4 | $5 | 1.02 |
| E006 | crash-gap/liquidation | delay1025 | 11 | $-445 | 0.30 |
| E007 | crash-gap/liquidation | delay1025 | 4 | $170 | 1.57 |
| E009 | crash-gap/liquidation | mnq_only__crash_only | 3 | $1,215 | inf |
| E010 | crash-gap/liquidation | wide3_mnq_mes | 4 | $338 | 1.56 |
| E012 | false stress / chop | wide3_mnq_mes | 4 | $-444 | 0.00 |
| E013 | false stress / chop | wide3_mnq_mes | 0 | $0 | inf |
| E014 | crash-gap/liquidation | wide3_mnq_mes | 10 | $-568 | 0.36 |
| E016 | false stress / chop | wide3_mnq_mes | 0 | $0 | inf |

Restricted-family concentration gate:

| total | best | without_best | best_share | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 269.87 | 1215.28 | -945.41 | 4.50 | -1012.95 | 4 | 9 | False |

Bootstrap by event cluster for `breadth3_mnq_mes`:

| candidate | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 12 | 0.65 | -2217.13 | 703.30 | 4188.15 |

By subtype for `breadth3_mnq_mes`:

          event_subtype  trades      net        avg       pf
bear-trend continuation      15 -1045.67 -69.711333 0.205303
  crash-gap/liquidation      57  1538.30  26.987719 1.381540
    false stress / chop       6   283.22  47.203333 2.325192

Bootstrap by event cluster for `wide3_mnq_mes`:

| candidate | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| wide3_mnq_mes | 10 | 0.74 | -1734.65 | 1355.82 | 5652.13 |

By subtype for `wide3_mnq_mes`:

        event_subtype  trades    net       avg      pf
crash-gap/liquidation      57 1538.3 26.987719 1.38154

Bootstrap by event cluster for `mnq_only`:

| candidate | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| mnq_only | 12 | 0.73 | -945.07 | 646.70 | 2651.91 |

By subtype for `mnq_only`:

          event_subtype  trades     net        avg       pf
bear-trend continuation       7 -653.34 -93.334286 0.152574
  crash-gap/liquidation      29 1096.93  37.825172 1.470703
    false stress / chop       2  261.74 130.870000      inf

Bootstrap by event cluster for `breadth3_mnq_mes__crash_only`:

| candidate | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes__crash_only | 10 | 0.74 | -1734.65 | 1355.82 | 5652.13 |

By subtype for `breadth3_mnq_mes__crash_only`:

        event_subtype  trades    net       avg      pf
crash-gap/liquidation      57 1538.3 26.987719 1.38154

Bootstrap by event cluster for `wide3_mnq_mes__crash_only`:

| candidate | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| wide3_mnq_mes__crash_only | 10 | 0.74 | -1734.65 | 1355.82 | 5652.13 |

By subtype for `wide3_mnq_mes__crash_only`:

        event_subtype  trades    net       avg      pf
crash-gap/liquidation      57 1538.3 26.987719 1.38154

## vault2025

Top causal lag-1 candidates by standalone net:

| name | trades | days | clusters | net | pf | sharpe_calendar | calmar_calendar | maxdd | target_rate | stop_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rr15__wide4 | 13 | 7 | 3 | $4,599 | inf | 6.29 | inf | $0 | 0.62 | 0.00 |
| rr15__range_ge_100bp | 11 | 6 | 3 | $4,545 | inf | 6.21 | inf | $0 | 0.73 | 0.00 |
| rr25__wide4 | 13 | 7 | 3 | $4,346 | inf | 5.02 | inf | $0 | 0.23 | 0.00 |
| rr25__range_ge_100bp | 11 | 6 | 3 | $4,292 | inf | 4.95 | inf | $0 | 0.27 | 0.00 |
| rr15__crash_only | 15 | 8 | 3 | $4,237 | 12.71 | 5.63 | 104.30 | $362 | 0.53 | 0.13 |
| breadth3_mnq_mes__wide4 | 13 | 7 | 3 | $4,041 | inf | 5.45 | inf | $0 | 0.31 | 0.00 |
| wide3_mnq_mes__wide4 | 13 | 7 | 3 | $4,041 | inf | 5.45 | inf | $0 | 0.31 | 0.00 |
| rr15__below4 | 12 | 6 | 3 | $4,027 | 12.13 | 5.42 | 101.61 | $362 | 0.67 | 0.17 |
| breadth3_mnq_mes__range_ge_100bp | 11 | 6 | 3 | $3,988 | inf | 5.37 | inf | $0 | 0.36 | 0.00 |
| wide3_mnq_mes__range_ge_100bp | 11 | 6 | 3 | $3,988 | inf | 5.37 | inf | $0 | 0.36 | 0.00 |
| rr25__crash_only | 15 | 8 | 3 | $3,984 | 12.01 | 4.51 | 98.07 | $362 | 0.20 | 0.13 |
| exit1555__wide4 | 13 | 7 | 3 | $3,945 | 16.22 | 4.40 | 1339.97 | $26 | 0.46 | 0.08 |
| rr15__no_bear | 17 | 9 | 3 | $3,941 | 6.98 | 5.14 | 53.32 | $658 | 0.47 | 0.18 |
| exit1555__range_ge_100bp | 11 | 6 | 3 | $3,871 | 15.93 | 4.32 | 1314.57 | $26 | 0.55 | 0.09 |
| rr15 | 19 | 10 | 4 | $3,804 | 5.78 | 4.93 | 51.46 | $658 | 0.42 | 0.16 |
| rr25__below4 | 12 | 6 | 3 | $3,774 | 11.43 | 4.33 | 95.22 | $362 | 0.25 | 0.17 |
| exit1555__below4 | 12 | 6 | 3 | $3,742 | 10.64 | 4.20 | 94.41 | $362 | 0.50 | 0.17 |
| rr25__no_bear | 17 | 9 | 3 | $3,688 | 6.60 | 4.11 | 49.89 | $658 | 0.18 | 0.18 |
| wide3_mnq_mes | 15 | 8 | 3 | $3,680 | 11.17 | 4.83 | 90.58 | $362 | 0.27 | 0.13 |
| breadth3_mnq_mes__crash_only | 15 | 8 | 3 | $3,680 | 11.17 | 4.83 | 90.58 | $362 | 0.27 | 0.13 |
| wide3_mnq_mes__crash_only | 15 | 8 | 3 | $3,680 | 11.17 | 4.83 | 90.58 | $362 | 0.27 | 0.13 |
| wide3_mnq_mes__no_bear | 15 | 8 | 3 | $3,680 | 11.17 | 4.83 | 90.58 | $362 | 0.27 | 0.13 |
| exit1555__crash_only | 15 | 8 | 3 | $3,583 | 6.77 | 3.93 | 88.21 | $362 | 0.40 | 0.20 |
| rr25 | 19 | 10 | 4 | $3,551 | 5.46 | 3.94 | 48.04 | $658 | 0.16 | 0.16 |
| breadth3_mnq_mes__below4 | 12 | 6 | 3 | $3,469 | 10.59 | 4.62 | 87.54 | $362 | 0.33 | 0.17 |
| wide3_mnq_mes__below4 | 12 | 6 | 3 | $3,469 | 10.59 | 4.62 | 87.54 | $362 | 0.33 | 0.17 |
| exit1555__no_bear | 17 | 9 | 3 | $3,460 | 5.41 | 3.78 | 63.50 | $485 | 0.35 | 0.24 |
| breadth3_mnq_mes__no_bear | 17 | 9 | 3 | $3,383 | 6.14 | 4.36 | 45.77 | $658 | 0.24 | 0.18 |
| exit1555__range_ge_125bp | 4 | 2 | 1 | $3,302 | inf | 10.24 | inf | $0 | 1.00 | 0.00 |
| breadth3_mnq_mes | 19 | 10 | 4 | $3,246 | 5.08 | 4.17 | 43.92 | $658 | 0.21 | 0.16 |
| exit1555 | 19 | 10 | 4 | $3,215 | 4.12 | 3.48 | 59.00 | $485 | 0.32 | 0.26 |
| delay1025__wide4 | 12 | 7 | 3 | $2,832 | 379.09 | 5.45 | inf | $0 | 0.33 | 0.00 |
| delay1025__range_ge_100bp | 10 | 6 | 3 | $2,774 | 371.41 | 5.33 | inf | $0 | 0.40 | 0.00 |
| partial1r_run25 | 19 | 10 | 4 | $2,728 | 4.43 | 4.01 | 36.91 | $658 | 0.00 | 0.00 |
| exit1200__range_ge_100bp | 11 | 6 | 3 | $2,662 | inf | 5.33 | inf | $0 | 0.09 | 0.00 |
| delay1025__crash_only | 14 | 8 | 3 | $2,628 | 13.40 | 4.96 | 114.52 | $204 | 0.29 | 0.14 |
| rr25__range_ge_125bp | 4 | 2 | 1 | $2,604 | inf | 8.07 | inf | $0 | 0.50 | 0.00 |
| rr15__range_ge_125bp | 4 | 2 | 1 | $2,472 | inf | 10.24 | inf | $0 | 1.00 | 0.00 |
| delay1025__below4 | 11 | 6 | 3 | $2,466 | 12.64 | 4.71 | 110.18 | $204 | 0.36 | 0.18 |
| exit1200__wide4 | 13 | 7 | 3 | $2,421 | 11.03 | 4.72 | 89.31 | $241 | 0.08 | 0.00 |

Full candidate-set chronological event WFO:

| test_cluster | event_subtype | selected | trades | net | pf |
| --- | --- | --- | --- | --- | --- |
| E004 | crash-gap/liquidation | exit1555__wide4 | 2 | $98 | inf |

Full candidate-set concentration gate:

| total | best | without_best | best_share | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 97.52 | 97.52 | 0.00 | 1.00 | 97.52 | 1 | 1 | False |

Restricted predeclared-family chronological event WFO:

| test_cluster | event_subtype | selected | trades | net | pf |
| --- | --- | --- | --- | --- | --- |
| E004 | crash-gap/liquidation | wide3_mnq_mes | 2 | $771 | inf |

Restricted-family concentration gate:

| total | best | without_best | best_share | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 770.77 | 770.77 | 0.00 | 1.00 | 770.77 | 1 | 1 | False |

Bootstrap by event cluster for `breadth3_mnq_mes`:

| candidate | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 4 | 0.98 | 359.83 | 3246.04 | 6767.43 |

By subtype for `breadth3_mnq_mes`:

          event_subtype  trades     net      avg        pf
bear-trend continuation       2 -136.98  -68.490  0.000000
  crash-gap/liquidation      15 3679.53  245.302 11.167256
    false stress / chop       2 -296.51 -148.255  0.000000

Bootstrap by event cluster for `wide3_mnq_mes`:

| candidate | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| wide3_mnq_mes | 3 | 1.00 | 1392.33 | 3679.53 | 5966.73 |

By subtype for `wide3_mnq_mes`:

        event_subtype  trades     net     avg        pf
crash-gap/liquidation      15 3679.53 245.302 11.167256

Bootstrap by event cluster for `mnq_only`:

| candidate | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| mnq_only | 4 | 0.98 | 91.04 | 1885.38 | 4223.06 |

By subtype for `mnq_only`:

          event_subtype  trades     net         avg        pf
bear-trend continuation       1 -110.74 -110.740000  0.000000
  crash-gap/liquidation       7 2128.86  304.122857 10.997464
    false stress / chop       1 -132.74 -132.740000  0.000000

Bootstrap by event cluster for `breadth3_mnq_mes__crash_only`:

| candidate | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes__crash_only | 3 | 1.00 | 1392.33 | 3679.53 | 5966.73 |

By subtype for `breadth3_mnq_mes__crash_only`:

        event_subtype  trades     net     avg        pf
crash-gap/liquidation      15 3679.53 245.302 11.167256

Bootstrap by event cluster for `wide3_mnq_mes__crash_only`:

| candidate | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| wide3_mnq_mes__crash_only | 3 | 1.00 | 1392.33 | 3679.53 | 5966.73 |

By subtype for `wide3_mnq_mes__crash_only`:

        event_subtype  trades     net     avg        pf
crash-gap/liquidation      15 3679.53 245.302 11.167256

## vault2026

Top causal lag-1 candidates by standalone net:

| name | trades | days | clusters | net | pf | sharpe_calendar | calmar_calendar | maxdd | target_rate | stop_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes__range_ge_100bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| breadth3_mnq_mes__range_ge_125bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| wide3_mnq_mes__range_ge_100bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| wide3_mnq_mes__range_ge_125bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| mnq_only__range_ge_100bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| mnq_only__range_ge_125bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| rr15__range_ge_100bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| rr15__range_ge_125bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| rr25__range_ge_100bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| rr25__range_ge_125bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| delay1025__range_ge_100bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| delay1025__range_ge_125bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| exit1200__range_ge_100bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| exit1200__range_ge_125bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| exit1555__range_ge_100bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| exit1555__range_ge_125bp | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| mes_only | 1 | 1 | 1 | $-176 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |
| exit1200 | 2 | 1 | 1 | $-180 | 0.00 | 0.00 | inf | $0 | 0.00 | 0.00 |
| exit1200__crash_only | 2 | 1 | 1 | $-180 | 0.00 | 0.00 | inf | $0 | 0.00 | 0.00 |
| exit1200__no_bear | 2 | 1 | 1 | $-180 | 0.00 | 0.00 | inf | $0 | 0.00 | 0.00 |
| exit1200__below4 | 2 | 1 | 1 | $-180 | 0.00 | 0.00 | inf | $0 | 0.00 | 0.00 |
| exit1200__wide4 | 2 | 1 | 1 | $-180 | 0.00 | 0.00 | inf | $0 | 0.00 | 0.00 |
| exit1200__stop_le_75bp | 2 | 1 | 1 | $-180 | 0.00 | 0.00 | inf | $0 | 0.00 | 0.00 |
| exit1200__stop_le_100bp | 2 | 1 | 1 | $-180 | 0.00 | 0.00 | inf | $0 | 0.00 | 0.00 |
| exit1200__stop_le_125bp | 2 | 1 | 1 | $-180 | 0.00 | 0.00 | inf | $0 | 0.00 | 0.00 |
| delay1025 | 2 | 1 | 1 | $-345 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |
| delay1025__crash_only | 2 | 1 | 1 | $-345 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |
| delay1025__no_bear | 2 | 1 | 1 | $-345 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |
| delay1025__below4 | 2 | 1 | 1 | $-345 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |
| delay1025__wide4 | 2 | 1 | 1 | $-345 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |
| delay1025__stop_le_75bp | 2 | 1 | 1 | $-345 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |
| delay1025__stop_le_100bp | 2 | 1 | 1 | $-345 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |
| delay1025__stop_le_125bp | 2 | 1 | 1 | $-345 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |
| mnq_only | 1 | 1 | 1 | $-358 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |
| mnq_only__crash_only | 1 | 1 | 1 | $-358 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |
| mnq_only__no_bear | 1 | 1 | 1 | $-358 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |
| mnq_only__below4 | 1 | 1 | 1 | $-358 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |
| mnq_only__wide4 | 1 | 1 | 1 | $-358 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |
| mnq_only__stop_le_75bp | 1 | 1 | 1 | $-358 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |
| mnq_only__stop_le_100bp | 1 | 1 | 1 | $-358 | 0.00 | 0.00 | inf | $0 | 0.00 | 1.00 |

Full candidate-set chronological event WFO:

_insufficient folds_

Full candidate-set concentration gate:

| total | best | without_best | best_share | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.00 | 0.00 | 0.00 | inf | 0.00 | 0 | 0 | False |

Restricted predeclared-family chronological event WFO:

_insufficient folds_

Restricted-family concentration gate:

| total | best | without_best | best_share | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.00 | 0.00 | 0.00 | inf | 0.00 | 0 | 0 | False |

Bootstrap by event cluster for `breadth3_mnq_mes`:

| candidate | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 1 | 0.00 | -533.73 | -533.73 | -533.73 |

By subtype for `breadth3_mnq_mes`:

        event_subtype  trades     net      avg  pf
crash-gap/liquidation       2 -533.73 -266.865 0.0

Bootstrap by event cluster for `wide3_mnq_mes`:

| candidate | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| wide3_mnq_mes | 1 | 0.00 | -533.73 | -533.73 | -533.73 |

By subtype for `wide3_mnq_mes`:

        event_subtype  trades     net      avg  pf
crash-gap/liquidation       2 -533.73 -266.865 0.0

Bootstrap by event cluster for `mnq_only`:

| candidate | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| mnq_only | 1 | 0.00 | -357.79 | -357.79 | -357.79 |

By subtype for `mnq_only`:

        event_subtype  trades     net     avg  pf
crash-gap/liquidation       1 -357.79 -357.79 0.0

Bootstrap by event cluster for `breadth3_mnq_mes__crash_only`:

| candidate | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes__crash_only | 1 | 0.00 | -533.73 | -533.73 | -533.73 |

By subtype for `breadth3_mnq_mes__crash_only`:

        event_subtype  trades     net      avg  pf
crash-gap/liquidation       2 -533.73 -266.865 0.0

Bootstrap by event cluster for `wide3_mnq_mes__crash_only`:

| candidate | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| wide3_mnq_mes__crash_only | 1 | 0.00 | -533.73 | -533.73 | -533.73 |

By subtype for `wide3_mnq_mes__crash_only`:

        event_subtype  trades     net      avg  pf
crash-gap/liquidation       2 -533.73 -266.865 0.0

## Consolidated Verdict

No deploy-level Stress candidate was found. The restricted causal family fails the
predeclared floor event-WFO concentration gate, so any attractive standalone row should
be treated as event-cluster mining rather than a robust hedge candidate.

Stress remains research-only unless a future pass with a predeclared intraday Stress detector
passes the event-WFO concentration gate and solves same-symbol position ownership.
