# Stress Sleeve Event Validation

Scratch-only report. No production code change is implied.

Candidate under review: Stress-only confirmed 10:20 liquidation SHORT, full 10:15-10:19 5m signal, MNQ/MES, stop = 09:45-10:15 swing high * 1.001, target 2R, exit by 14:00, 2 ticks/side.

## floor

| name | trades | net | pf | sharpe | calmar | maxdd_pct | target_rate | stop_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 84 | $2,155 | 1.36 | 2.02 | 0.18 | 4.9% | 0.25 | 0.38 |
| wide3_mnq_mes | 61 | $2,164 | 1.48 | 2.61 | 0.21 | 4.4% | 0.21 | 0.38 |
| breadth3_all4 | 160 | $2,499 | 1.28 | 1.65 | 0.13 | 8.2% | 0.23 | 0.37 |
| breadth3_mnq | 41 | $1,878 | 1.59 | 3.01 | 0.34 | 2.3% | 0.24 | 0.37 |
| breadth3_mes | 43 | $277 | 1.10 | 0.64 | 0.04 | 2.8% | 0.26 | 0.40 |
| rr15 | 84 | $1,455 | 1.25 | 1.51 | 0.13 | 4.8% | 0.35 | 0.37 |
| rr25 | 84 | $3,103 | 1.52 | 2.70 | 0.28 | 4.7% | 0.19 | 0.38 |
| exit1200 | 84 | $1,273 | 1.28 | 1.55 | 0.11 | 4.9% | 0.15 | 0.21 |
| exit1555 | 84 | $2,685 | 1.42 | 2.25 | 0.19 | 6.0% | 0.32 | 0.45 |
| delay1025 | 82 | $2,212 | 1.38 | 2.19 | 0.23 | 4.0% | 0.28 | 0.38 |
| late_cont_break | 48 | $1,632 | 1.60 | 3.04 | 0.43 | 1.6% | 0.15 | 0.33 |
| partial1r_run25 | 84 | $1,258 | 1.22 | 1.34 | 0.12 | 4.2% | 0.00 | 0.00 |

Fill/timing audit for base:

- outside_exit_bar=0
- signal_after_entry=0
- same_bar_exit=0

Base by event subtype:

| event_subtype | trades | net | avg | pf |
| --- | --- | --- | --- | --- |
| bear-trend continuation | 17 | -244.53 | -14.38 | 0.80 |
| crash-gap/liquidation | 61 | 2164.01 | 35.48 | 1.48 |
| false stress / chop | 6 | 235.22 | 39.20 | 2.01 |

Base by instrument:

| inst | trades | net | avg | pf |
| --- | --- | --- | --- | --- |
| MES | 43 | 276.95 | 6.44 | 1.10 |
| MNQ | 41 | 1877.75 | 45.80 | 1.59 |

Chronological held-out event-cluster WFO:

| test_cluster | event_subtype | selected | trades | net | pf |
| --- | --- | --- | --- | --- | --- |
| E004 | crash-gap/liquidation | late_cont_break | 6 | $-666 | 0.00 |
| E005 | crash-gap/liquidation | late_cont_break | 1 | $96 | inf |
| E006 | crash-gap/liquidation | late_cont_break | 3 | $-113 | 0.31 |
| E007 | crash-gap/liquidation | late_cont_break | 1 | $257 | inf |
| E009 | crash-gap/liquidation | late_cont_break | 8 | $666 | 2.86 |
| E010 | bear-trend continuation | wide3_mnq_mes | 4 | $310 | 1.50 |
| E011 | crash-gap/liquidation | late_cont_break | 2 | $125 | inf |
| E012 | false stress / chop | late_cont_break | 0 | $0 | inf |
| E013 | crash-gap/liquidation | late_cont_break | 2 | $645 | inf |
| E014 | crash-gap/liquidation | late_cont_break | 2 | $12 | 2.23 |
| E015 | crash-gap/liquidation | wide3_mnq_mes | 8 | $-372 | 0.45 |
| E016 | bear-trend continuation | wide3_mnq_mes | 0 | $0 | inf |
| E017 | false stress / chop | rr25 | 4 | $546 | 19.36 |

Held-out event total: $1,506; positive folds: 8/13.

## vault2025

| name | trades | net | pf | sharpe | calmar | maxdd_pct | target_rate | stop_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 19 | $3,959 | 6.59 | 10.18 | 50.16 | 1.4% | 0.21 | 0.16 |
| wide3_mnq_mes | 15 | $3,514 | 9.82 | 11.05 | 83.27 | 0.8% | 0.27 | 0.13 |
| breadth3_all4 | 34 | $4,556 | 4.21 | 8.75 | 40.73 | 1.9% | 0.18 | 0.26 |
| breadth3_mnq | 9 | $2,452 | 7.93 | 11.05 | 60.30 | 0.7% | 0.22 | 0.11 |
| breadth3_mes | 10 | $1,507 | 5.24 | 9.75 | 39.39 | 0.7% | 0.20 | 0.20 |
| rr15 | 19 | $4,070 | 6.74 | 11.14 | 51.57 | 1.4% | 0.32 | 0.16 |
| rr25 | 19 | $4,264 | 7.01 | 9.42 | 54.02 | 1.4% | 0.16 | 0.16 |
| exit1200 | 19 | $2,075 | 3.52 | 7.47 | 28.58 | 1.3% | 0.05 | 0.11 |
| exit1555 | 19 | $4,739 | 6.98 | 10.25 | 80.28 | 1.0% | 0.37 | 0.21 |
| delay1025 | 18 | $2,897 | 5.39 | 9.57 | 40.49 | 1.2% | 0.22 | 0.17 |
| late_cont_break | 14 | $493 | 1.35 | 1.90 | 4.56 | 1.9% | 0.21 | 0.36 |
| partial1r_run25 | 19 | $3,344 | 5.72 | 9.70 | 42.36 | 1.4% | 0.00 | 0.00 |

Fill/timing audit for base:

- outside_exit_bar=0
- signal_after_entry=0
- same_bar_exit=0

Base by event subtype:

| event_subtype | trades | net | avg | pf |
| --- | --- | --- | --- | --- |
| bear-trend continuation | 2 | 756.02 | 378.01 | inf |
| crash-gap/liquidation | 15 | 3513.78 | 234.25 | 9.82 |
| false stress / chop | 2 | -310.51 | -155.25 | 0.00 |

Base by instrument:

| inst | trades | net | avg | pf |
| --- | --- | --- | --- | --- |
| MES | 10 | 1506.91 | 150.69 | 5.24 |
| MNQ | 9 | 2452.38 | 272.49 | 7.93 |

## Verdict

Keep Stress as hedge only, not standalone alpha.

Deploy-level hedge candidate to carry forward, conditionally: `breadth3_mnq_mes`, confirmed 10:20 SHORT, MNQ/MES, 2R target, 14:00 exit, stop at 09:45-10:15 swing high * 1.001, with a coarse Stress cap review around 7.5%-10%. The 2.5% cap is not a fair test because it suppresses the candidate in OOS; 5% is still marginal in the standalone cap proxy.

Do not promote live until basket-level timing and broker mechanics are solved: the live signal must have the full 10:15-10:19 5m bar before entry, Stress needs explicit same-day exit/stop ownership, and same-symbol Normal/Calm/Stress netting risk must be handled.

Reject as standalone robust alpha because 2018/2019/2020 carry is negative, event-cluster folds are not consistently positive, 2023-2024/2026 have no contribution, and the edge is a sparse crisis payoff rather than a smooth return stream.

Account assumption for cap/DD display: $50,000.
