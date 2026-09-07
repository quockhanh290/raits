# Stress Sleeve Event Validation

Scratch-only report. No production code change is implied.

Candidate under review: Stress-only confirmed 10:20 liquidation SHORT, full 10:15-10:19 5m signal, MNQ/MES, stop = 09:45-10:15 swing high * 1.001, target 2R, exit by 14:00, 2 ticks/side.

## floor

| name | trades | net | pf | sharpe | calmar | maxdd_pct | target_rate | stop_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 84 | $2,452 | 1.42 | 2.30 | 0.22 | 4.6% | 0.25 | 0.38 |
| wide3_mnq_mes | 61 | $2,376 | 1.54 | 2.86 | 0.24 | 4.2% | 0.21 | 0.38 |
| breadth3_all4 | 160 | $2,948 | 1.33 | 1.94 | 0.16 | 7.8% | 0.23 | 0.37 |
| breadth3_mnq | 41 | $1,960 | 1.63 | 3.14 | 0.37 | 2.2% | 0.24 | 0.37 |
| breadth3_mes | 43 | $492 | 1.18 | 1.13 | 0.08 | 2.6% | 0.26 | 0.40 |
| rr15 | 84 | $1,752 | 1.31 | 1.82 | 0.16 | 4.5% | 0.35 | 0.37 |
| rr25 | 84 | $3,400 | 1.59 | 2.95 | 0.32 | 4.4% | 0.19 | 0.38 |
| exit1200 | 84 | $1,570 | 1.37 | 1.91 | 0.14 | 4.7% | 0.15 | 0.21 |
| exit1555 | 84 | $2,982 | 1.48 | 2.49 | 0.22 | 5.8% | 0.32 | 0.45 |
| delay1025 | 82 | $2,505 | 1.44 | 2.48 | 0.28 | 3.7% | 0.28 | 0.38 |
| late_cont_break | 48 | $1,800 | 1.68 | 3.36 | 0.51 | 1.5% | 0.15 | 0.33 |
| partial1r_run25 | 84 | $1,555 | 1.28 | 1.66 | 0.16 | 4.0% | 0.00 | 0.00 |

Fill/timing audit for base:

- outside_exit_bar=0
- signal_after_entry=0
- same_bar_exit=0

Base by event subtype:

| event_subtype | trades | net | avg | pf |
| --- | --- | --- | --- | --- |
| bear-trend continuation | 17 | -183.53 | -10.80 | 0.84 |
| crash-gap/liquidation | 61 | 2376.01 | 38.95 | 1.54 |
| false stress / chop | 6 | 259.22 | 43.20 | 2.16 |

Base by instrument:

| inst | trades | net | avg | pf |
| --- | --- | --- | --- | --- |
| MES | 43 | 491.95 | 11.44 | 1.18 |
| MNQ | 41 | 1959.75 | 47.80 | 1.63 |

Chronological held-out event-cluster WFO:

| test_cluster | event_subtype | selected | trades | net | pf |
| --- | --- | --- | --- | --- | --- |
| E004 | crash-gap/liquidation | late_cont_break | 6 | $-645 | 0.00 |
| E005 | crash-gap/liquidation | late_cont_break | 1 | $98 | inf |
| E006 | crash-gap/liquidation | late_cont_break | 3 | $-101 | 0.34 |
| E007 | crash-gap/liquidation | late_cont_break | 1 | $259 | inf |
| E009 | crash-gap/liquidation | late_cont_break | 8 | $694 | 2.98 |
| E010 | bear-trend continuation | wide3_mnq_mes | 4 | $324 | 1.53 |
| E011 | crash-gap/liquidation | late_cont_break | 2 | $132 | inf |
| E012 | false stress / chop | late_cont_break | 0 | $0 | inf |
| E013 | crash-gap/liquidation | late_cont_break | 2 | $652 | inf |
| E014 | crash-gap/liquidation | late_cont_break | 2 | $19 | 4.86 |
| E015 | crash-gap/liquidation | wide3_mnq_mes | 8 | $-344 | 0.48 |
| E016 | bear-trend continuation | wide3_mnq_mes | 0 | $0 | inf |
| E017 | false stress / chop | rr25 | 4 | $560 | 21.19 |

Held-out event total: $1,648; positive folds: 8/13.

## vault2025

| name | trades | net | pf | sharpe | calmar | maxdd_pct | target_rate | stop_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 19 | $4,027 | 6.84 | 10.36 | 52.09 | 1.3% | 0.21 | 0.16 |
| wide3_mnq_mes | 15 | $3,568 | 10.23 | 11.22 | 86.16 | 0.7% | 0.27 | 0.13 |
| breadth3_all4 | 34 | $4,654 | 4.35 | 8.93 | 42.48 | 1.9% | 0.18 | 0.26 |
| breadth3_mnq | 9 | $2,470 | 8.06 | 11.13 | 61.44 | 0.7% | 0.22 | 0.11 |
| breadth3_mes | 10 | $1,557 | 5.58 | 10.07 | 41.95 | 0.6% | 0.20 | 0.20 |
| rr15 | 19 | $4,138 | 7.00 | 11.33 | 53.52 | 1.3% | 0.32 | 0.16 |
| rr25 | 19 | $4,332 | 7.28 | 9.56 | 56.02 | 1.3% | 0.16 | 0.16 |
| exit1200 | 19 | $2,143 | 3.69 | 7.71 | 30.18 | 1.2% | 0.05 | 0.11 |
| exit1555 | 19 | $4,807 | 7.20 | 10.40 | 83.71 | 1.0% | 0.37 | 0.21 |
| delay1025 | 18 | $2,963 | 5.63 | 9.78 | 42.37 | 1.2% | 0.22 | 0.17 |
| late_cont_break | 14 | $545 | 1.40 | 2.10 | 5.11 | 1.9% | 0.21 | 0.36 |
| partial1r_run25 | 19 | $3,412 | 5.94 | 9.90 | 44.12 | 1.3% | 0.00 | 0.00 |

Fill/timing audit for base:

- outside_exit_bar=0
- signal_after_entry=0
- same_bar_exit=0

Base by event subtype:

| event_subtype | trades | net | avg | pf |
| --- | --- | --- | --- | --- |
| bear-trend continuation | 2 | 763.02 | 381.51 | inf |
| crash-gap/liquidation | 15 | 3567.78 | 237.85 | 10.23 |
| false stress / chop | 2 | -303.51 | -151.75 | 0.00 |

Base by instrument:

| inst | trades | net | avg | pf |
| --- | --- | --- | --- | --- |
| MES | 10 | 1556.91 | 155.69 | 5.58 |
| MNQ | 9 | 2470.38 | 274.49 | 8.06 |

## Verdict

Keep Stress as hedge only, not standalone alpha.

Deploy-level hedge candidate to carry forward, conditionally: `breadth3_mnq_mes`, confirmed 10:20 SHORT, MNQ/MES, 2R target, 14:00 exit, stop at 09:45-10:15 swing high * 1.001, with a coarse Stress cap review around 7.5%-10%. The 2.5% cap is not a fair test because it suppresses the candidate in OOS; 5% is still marginal in the standalone cap proxy.

Do not promote live until basket-level timing and broker mechanics are solved: the live signal must have the full 10:15-10:19 5m bar before entry, Stress needs explicit same-day exit/stop ownership, and same-symbol Normal/Calm/Stress netting risk must be handled.

Reject as standalone robust alpha because 2018/2019/2020 carry is negative, event-cluster folds are not consistently positive, 2023-2024/2026 have no contribution, and the edge is a sparse crisis payoff rather than a smooth return stream.

Account assumption for cap/DD display: $50,000.
