# Stress Sleeve Event Validation

Scratch-only report. No production code change is implied.

Candidate under review: Stress-only confirmed 10:20 liquidation SHORT, full 10:15-10:19 5m signal, MNQ/MES, stop = 09:45-10:15 swing high * 1.001, target 2R, exit by 14:00, 2 ticks/side.

## floor

| name | trades | net | pf | sharpe | calmar | maxdd_pct | target_rate | stop_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 84 | $2,749 | 1.49 | 2.57 | 0.26 | 4.4% | 0.25 | 0.38 |
| wide3_mnq_mes | 61 | $2,588 | 1.60 | 3.12 | 0.28 | 4.0% | 0.21 | 0.38 |
| breadth3_all4 | 160 | $3,397 | 1.40 | 2.24 | 0.19 | 7.4% | 0.23 | 0.37 |
| breadth3_mnq | 41 | $2,042 | 1.66 | 3.28 | 0.40 | 2.2% | 0.24 | 0.37 |
| breadth3_mes | 43 | $707 | 1.28 | 1.62 | 0.12 | 2.4% | 0.26 | 0.40 |
| rr15 | 84 | $2,049 | 1.37 | 2.12 | 0.20 | 4.2% | 0.35 | 0.37 |
| rr25 | 84 | $3,697 | 1.66 | 3.21 | 0.37 | 4.2% | 0.19 | 0.38 |
| exit1200 | 84 | $1,867 | 1.45 | 2.27 | 0.17 | 4.5% | 0.15 | 0.21 |
| exit1555 | 84 | $3,279 | 1.54 | 2.74 | 0.25 | 5.5% | 0.32 | 0.45 |
| delay1025 | 82 | $2,798 | 1.51 | 2.77 | 0.34 | 3.5% | 0.28 | 0.38 |
| late_cont_break | 48 | $1,968 | 1.77 | 3.67 | 0.59 | 1.4% | 0.15 | 0.33 |
| partial1r_run25 | 84 | $1,852 | 1.35 | 1.98 | 0.21 | 3.7% | 0.00 | 0.00 |

Fill/timing audit for base:

- outside_exit_bar=0
- signal_after_entry=0
- same_bar_exit=0

Base by event subtype:

| event_subtype | trades | net | avg | pf |
| --- | --- | --- | --- | --- |
| bear-trend continuation | 17 | -122.53 | -7.21 | 0.89 |
| crash-gap/liquidation | 61 | 2588.01 | 42.43 | 1.60 |
| false stress / chop | 6 | 283.22 | 47.20 | 2.33 |

Base by instrument:

| inst | trades | net | avg | pf |
| --- | --- | --- | --- | --- |
| MES | 43 | 706.95 | 16.44 | 1.28 |
| MNQ | 41 | 2041.75 | 49.80 | 1.66 |

Chronological held-out event-cluster WFO:

| test_cluster | event_subtype | selected | trades | net | pf |
| --- | --- | --- | --- | --- | --- |
| E004 | bear-trend continuation | late_cont_break | 6 | $-624 | 0.00 |
| E005 | crash-gap/liquidation | late_cont_break | 1 | $100 | inf |
| E006 | crash-gap/liquidation | late_cont_break | 3 | $-89 | 0.38 |
| E007 | crash-gap/liquidation | late_cont_break | 1 | $261 | inf |
| E009 | crash-gap/liquidation | late_cont_break | 8 | $722 | 3.10 |
| E010 | crash-gap/liquidation | wide3_mnq_mes | 4 | $338 | 1.56 |
| E011 | crash-gap/liquidation | late_cont_break | 2 | $139 | inf |
| E012 | false stress / chop | late_cont_break | 0 | $0 | inf |
| E013 | crash-gap/liquidation | late_cont_break | 2 | $659 | inf |
| E014 | crash-gap/liquidation | rr25 | 3 | $247 | 3.13 |
| E015 | crash-gap/liquidation | wide3_mnq_mes | 8 | $-316 | 0.50 |
| E016 | bear-trend continuation | rr25 | 2 | $495 | inf |
| E017 | false stress / chop | rr25 | 4 | $574 | 23.30 |

Held-out event total: $2,507; positive folds: 9/13.

## vault2025

| name | trades | net | pf | sharpe | calmar | maxdd_pct | target_rate | stop_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 19 | $4,095 | 7.10 | 10.53 | 54.09 | 1.3% | 0.21 | 0.16 |
| wide3_mnq_mes | 15 | $3,622 | 10.67 | 11.39 | 89.15 | 0.7% | 0.27 | 0.13 |
| breadth3_all4 | 34 | $4,752 | 4.50 | 9.11 | 44.30 | 1.9% | 0.18 | 0.26 |
| breadth3_mnq | 9 | $2,488 | 8.20 | 11.22 | 62.60 | 0.7% | 0.22 | 0.11 |
| breadth3_mes | 10 | $1,607 | 5.94 | 10.39 | 44.69 | 0.6% | 0.20 | 0.20 |
| rr15 | 19 | $4,206 | 7.27 | 11.51 | 55.56 | 1.3% | 0.32 | 0.16 |
| rr25 | 19 | $4,400 | 7.56 | 9.71 | 58.11 | 1.3% | 0.16 | 0.16 |
| exit1200 | 19 | $2,211 | 3.87 | 7.96 | 31.86 | 1.2% | 0.05 | 0.11 |
| exit1555 | 19 | $4,875 | 7.43 | 10.54 | 87.35 | 1.0% | 0.37 | 0.21 |
| delay1025 | 18 | $3,029 | 5.87 | 10.00 | 44.33 | 1.2% | 0.22 | 0.17 |
| late_cont_break | 14 | $597 | 1.44 | 2.30 | 5.67 | 1.8% | 0.21 | 0.36 |
| partial1r_run25 | 19 | $3,480 | 6.19 | 10.10 | 45.96 | 1.3% | 0.00 | 0.00 |

Fill/timing audit for base:

- outside_exit_bar=0
- signal_after_entry=0
- same_bar_exit=0

Base by event subtype:

| event_subtype | trades | net | avg | pf |
| --- | --- | --- | --- | --- |
| bear-trend continuation | 2 | 770.02 | 385.01 | inf |
| crash-gap/liquidation | 15 | 3621.78 | 241.45 | 10.67 |
| false stress / chop | 2 | -296.51 | -148.25 | 0.00 |

Base by instrument:

| inst | trades | net | avg | pf |
| --- | --- | --- | --- | --- |
| MES | 10 | 1606.91 | 160.69 | 5.94 |
| MNQ | 9 | 2488.38 | 276.49 | 8.20 |

## vault2026

| name | trades | net | pf | sharpe | calmar | maxdd_pct | target_rate | stop_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 0 | $0 | inf | 0.00 | 0.00 | 0.0% | 0.00 | 0.00 |
| wide3_mnq_mes | 0 | $0 | inf | 0.00 | 0.00 | 0.0% | 0.00 | 0.00 |
| breadth3_all4 | 0 | $0 | inf | 0.00 | 0.00 | 0.0% | 0.00 | 0.00 |
| breadth3_mnq | 0 | $0 | inf | 0.00 | 0.00 | 0.0% | 0.00 | 0.00 |
| breadth3_mes | 0 | $0 | inf | 0.00 | 0.00 | 0.0% | 0.00 | 0.00 |
| rr15 | 0 | $0 | inf | 0.00 | 0.00 | 0.0% | 0.00 | 0.00 |
| rr25 | 0 | $0 | inf | 0.00 | 0.00 | 0.0% | 0.00 | 0.00 |
| exit1200 | 0 | $0 | inf | 0.00 | 0.00 | 0.0% | 0.00 | 0.00 |
| exit1555 | 0 | $0 | inf | 0.00 | 0.00 | 0.0% | 0.00 | 0.00 |
| delay1025 | 0 | $0 | inf | 0.00 | 0.00 | 0.0% | 0.00 | 0.00 |
| late_cont_break | 0 | $0 | inf | 0.00 | 0.00 | 0.0% | 0.00 | 0.00 |
| partial1r_run25 | 0 | $0 | inf | 0.00 | 0.00 | 0.0% | 0.00 | 0.00 |

Fill/timing audit for base:

- outside_exit_bar=0
- signal_after_entry=0
- same_bar_exit=0

## Verdict

Keep Stress as hedge only, not standalone alpha.

Deploy-level hedge candidate to carry forward, conditionally: `breadth3_mnq_mes`, confirmed 10:20 SHORT, MNQ/MES, 2R target, 14:00 exit, stop at 09:45-10:15 swing high * 1.001, with a coarse Stress cap review around 7.5%-10%. The 2.5% cap is not a fair test because it suppresses the candidate in OOS; 5% is still marginal in the standalone cap proxy.

Do not promote live until basket-level timing and broker mechanics are solved: the live signal must have the full 10:15-10:19 5m bar before entry, Stress needs explicit same-day exit/stop ownership, and same-symbol Normal/Calm/Stress netting risk must be handled.

Reject as standalone robust alpha because 2018/2019/2020 carry is negative, event-cluster folds are not consistently positive, 2023-2024/2026 have no contribution, and the edge is a sparse crisis payoff rather than a smooth return stream.

Account assumption for cap/DD display: $50,000.
