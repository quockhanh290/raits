# Stress Audit Response - 2026-08-21

Scratch-only response to the Claude audit. Production code was not modified.

## floor

Regime labels: lag0 Stress days=126, lag1 Stress days=126, moved=32.

Lag-1 causal variant table, calendar-basis metrics:

| name | trades | days | net | pf | sharpe_calendar | calmar_calendar | maxdd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 78 | 41 | $776 | 1.14 | 0.14 | 0.08 | $2,064 |
| wide3_mnq_mes | 57 | 29 | $1,538 | 1.38 | 0.30 | 0.20 | $1,658 |
| rr25 | 78 | 41 | $1,538 | 1.28 | 0.25 | 0.16 | $2,064 |
| delay1025 | 76 | 41 | $584 | 1.11 | 0.12 | 0.06 | $1,936 |
| late_cont_break | 37 | 22 | $1,133 | 1.50 | 0.32 | 0.34 | $696 |
| partial1r_run25 | 78 | 41 | $301 | 1.06 | 0.06 | 0.03 | $2,064 |

Lag-0 comparison, calendar-basis metrics:

| name | trades | days | net | pf | sharpe_calendar | calmar_calendar | maxdd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 84 | 44 | $2,749 | 1.49 | 0.44 | 0.26 | $2,188 |
| wide3_mnq_mes | 61 | 31 | $2,588 | 1.60 | 0.45 | 0.28 | $2,000 |
| rr25 | 84 | 44 | $3,697 | 1.66 | 0.55 | 0.37 | $2,086 |
| delay1025 | 82 | 44 | $2,798 | 1.51 | 0.48 | 0.34 | $1,727 |
| late_cont_break | 48 | 27 | $1,968 | 1.77 | 0.49 | 0.59 | $697 |
| partial1r_run25 | 84 | 44 | $1,852 | 1.35 | 0.34 | 0.21 | $1,862 |

Fill/timing audit after lag-1 fix for `breadth3_mnq_mes`: outside_exit_bar=0, signal_after_entry=0, same_bar_exit=0.

Lag-1 event-cluster WFO:

Total held-out net=$571; positive folds=4/9; picks={'wide3_mnq_mes': 5, 'rr25': 2, 'delay1025': 2}.
| test_cluster | event_subtype | selected | trades | net | pf |
| --- | --- | --- | --- | --- | --- |
| E005 | crash-gap/liquidation | rr25 | 7 | $100 | 1.29 |
| E006 | crash-gap/liquidation | delay1025 | 11 | $-445 | 0.30 |
| E007 | crash-gap/liquidation | delay1025 | 4 | $170 | 1.57 |
| E009 | crash-gap/liquidation | rr25 | 8 | $1,422 | 3.90 |
| E010 | crash-gap/liquidation | wide3_mnq_mes | 4 | $338 | 1.56 |
| E012 | false stress / chop | wide3_mnq_mes | 4 | $-444 | 0.00 |
| E013 | false stress / chop | wide3_mnq_mes | 0 | $0 | inf |
| E014 | crash-gap/liquidation | wide3_mnq_mes | 10 | $-568 | 0.36 |
| E016 | false stress / chop | wide3_mnq_mes | 0 | $0 | inf |

Same-symbol overlap with existing swing sleeve, using lag-1 Stress trades and current swing labels:

| variant | held | opposite | opposite_pnl | total_pnl |
| --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 59 | 34 | $-48 | 775.85 |
| wide3_mnq_mes | 41 | 27 | $23 | 1538.30 |

True stop-risk basis after lag-1 fix:

| variant | risk_med | risk_max | risk_day_max | atr_med | ratio_med |
| --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | $130 | $398 | $664 | 1316.41 | 10.25 |
| wide3_mnq_mes | $144 | $398 | $664 | 1413.66 | 8.96 |

True stop-risk cap table:

| variant | cap | max_pos | trades | rejected | net | pf |
| --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 2.5% | 1 | 41 | 37 | $471 | 1.14 |
| breadth3_mnq_mes | 2.5% | 2 | 78 | 0 | $776 | 1.14 |
| breadth3_mnq_mes | 5.0% | 1 | 41 | 37 | $471 | 1.14 |
| breadth3_mnq_mes | 5.0% | 2 | 78 | 0 | $776 | 1.14 |
| wide3_mnq_mes | 2.5% | 1 | 29 | 28 | $1,150 | 1.50 |
| wide3_mnq_mes | 2.5% | 2 | 57 | 0 | $1,538 | 1.38 |
| wide3_mnq_mes | 5.0% | 1 | 29 | 28 | $1,150 | 1.50 |
| wide3_mnq_mes | 5.0% | 2 | 57 | 0 | $1,538 | 1.38 |

Lag-1 base by event subtype:

          event_subtype  trades      net        avg       pf
bear-trend continuation      15 -1045.67 -69.711333 0.205303
  crash-gap/liquidation      57  1538.30  26.987719 1.381540
    false stress / chop       6   283.22  47.203333 2.325192

Live bar-cut probe using lag-1 labels and `entry_signals`:

{'breadth3': {'10:15': {'signal_days': 0, 'signal_legs': 0}, '10:20': {'signal_days': 41, 'signal_legs': 78}, '10:21': {'signal_days': 41, 'signal_legs': 78}}, 'wide_range3': {'10:15': {'signal_days': 0, 'signal_legs': 0}, '10:20': {'signal_days': 29, 'signal_legs': 57}, '10:21': {'signal_days': 29, 'signal_legs': 57}}}

## vault2025

Regime labels: lag0 Stress days=290, lag1 Stress days=290, moved=74.

Lag-1 causal variant table, calendar-basis metrics:

| name | trades | days | net | pf | sharpe_calendar | calmar_calendar | maxdd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 19 | 10 | $3,246 | 5.08 | 4.17 | 43.92 | $658 |
| wide3_mnq_mes | 15 | 8 | $3,680 | 11.17 | 4.83 | 90.58 | $362 |
| rr25 | 19 | 10 | $3,551 | 5.46 | 3.94 | 48.04 | $658 |
| delay1025 | 18 | 10 | $2,217 | 4.51 | 3.98 | 33.24 | $594 |
| late_cont_break | 13 | 8 | $265 | 1.21 | 0.59 | 4.25 | $555 |
| partial1r_run25 | 19 | 10 | $2,728 | 4.43 | 4.01 | 36.91 | $658 |

Lag-0 comparison, calendar-basis metrics:

| name | trades | days | net | pf | sharpe_calendar | calmar_calendar | maxdd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 19 | 10 | $4,095 | 7.10 | 4.96 | 54.09 | $658 |
| wide3_mnq_mes | 15 | 8 | $3,622 | 10.67 | 4.76 | 89.15 | $362 |
| rr25 | 19 | 10 | $4,400 | 7.56 | 4.67 | 58.11 | $658 |
| delay1025 | 18 | 10 | $3,029 | 5.87 | 4.77 | 44.33 | $594 |
| late_cont_break | 14 | 8 | $597 | 1.44 | 1.13 | 5.67 | $916 |
| partial1r_run25 | 19 | 10 | $3,480 | 6.19 | 4.81 | 45.96 | $658 |

Fill/timing audit after lag-1 fix for `breadth3_mnq_mes`: outside_exit_bar=0, signal_after_entry=0, same_bar_exit=0.

Lag-1 event-cluster WFO:

Total held-out net=$771; positive folds=1/1; picks={'wide3_mnq_mes': 1}.
| test_cluster | event_subtype | selected | trades | net | pf |
| --- | --- | --- | --- | --- | --- |
| E004 | crash-gap/liquidation | wide3_mnq_mes | 2 | $771 | inf |

Same-symbol overlap with existing swing sleeve, using lag-1 Stress trades and current swing labels:

| variant | held | opposite | opposite_pnl | total_pnl |
| --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 12 | 8 | $653 | 3246.04 |
| wide3_mnq_mes | 8 | 6 | $790 | 3679.53 |

True stop-risk basis after lag-1 fix:

| variant | risk_med | risk_max | risk_day_max | atr_med | ratio_med |
| --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | $227 | $535 | $858 | 3406.25 | 13.26 |
| wide3_mnq_mes | $248 | $535 | $858 | 3406.25 | 12.50 |

True stop-risk cap table:

| variant | cap | max_pos | trades | rejected | net | pf |
| --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 2.5% | 1 | 10 | 9 | $2,042 | 5.47 |
| breadth3_mnq_mes | 2.5% | 2 | 19 | 0 | $3,246 | 5.08 |
| breadth3_mnq_mes | 5.0% | 1 | 10 | 9 | $2,042 | 5.47 |
| breadth3_mnq_mes | 5.0% | 2 | 19 | 0 | $3,246 | 5.08 |
| wide3_mnq_mes | 2.5% | 1 | 8 | 7 | $2,285 | 11.73 |
| wide3_mnq_mes | 2.5% | 2 | 15 | 0 | $3,680 | 11.17 |
| wide3_mnq_mes | 5.0% | 1 | 8 | 7 | $2,285 | 11.73 |
| wide3_mnq_mes | 5.0% | 2 | 15 | 0 | $3,680 | 11.17 |

Lag-1 base by event subtype:

          event_subtype  trades     net      avg        pf
bear-trend continuation       2 -136.98  -68.490  0.000000
  crash-gap/liquidation      15 3679.53  245.302 11.167256
    false stress / chop       2 -296.51 -148.255  0.000000

Live bar-cut probe using lag-1 labels and `entry_signals`:

{'breadth3': {'10:15': {'signal_days': 0, 'signal_legs': 0}, '10:20': {'signal_days': 10, 'signal_legs': 19}, '10:21': {'signal_days': 10, 'signal_legs': 19}}, 'wide_range3': {'10:15': {'signal_days': 0, 'signal_legs': 0}, '10:20': {'signal_days': 8, 'signal_legs': 15}, '10:21': {'signal_days': 8, 'signal_legs': 15}}}

## vault2026

Regime labels: lag0 Stress days=290, lag1 Stress days=290, moved=74.

Lag-1 causal variant table, calendar-basis metrics:

| name | trades | days | net | pf | sharpe_calendar | calmar_calendar | maxdd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 2 | 1 | $-534 | 0.00 | 0.00 | inf | $0 |
| wide3_mnq_mes | 2 | 1 | $-534 | 0.00 | 0.00 | inf | $0 |
| rr25 | 2 | 1 | $-534 | 0.00 | 0.00 | inf | $0 |
| delay1025 | 2 | 1 | $-345 | 0.00 | 0.00 | inf | $0 |
| late_cont_break | 2 | 1 | $-480 | 0.00 | 0.00 | inf | $0 |
| partial1r_run25 | 2 | 1 | $-534 | 0.00 | 0.00 | inf | $0 |

Lag-0 comparison, calendar-basis metrics:

| name | trades | days | net | pf | sharpe_calendar | calmar_calendar | maxdd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 0 | 0 | $0 | inf | 0.00 | inf | $0 |
| wide3_mnq_mes | 0 | 0 | $0 | inf | 0.00 | inf | $0 |
| rr25 | 0 | 0 | $0 | inf | 0.00 | inf | $0 |
| delay1025 | 0 | 0 | $0 | inf | 0.00 | inf | $0 |
| late_cont_break | 0 | 0 | $0 | inf | 0.00 | inf | $0 |
| partial1r_run25 | 0 | 0 | $0 | inf | 0.00 | inf | $0 |

Fill/timing audit after lag-1 fix for `breadth3_mnq_mes`: outside_exit_bar=0, signal_after_entry=0, same_bar_exit=0.

Lag-1 event-cluster WFO:

Insufficient event clusters.

Same-symbol overlap with existing swing sleeve, using lag-1 Stress trades and current swing labels:

| variant | held | opposite | opposite_pnl | total_pnl |
| --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 2 | 0 | $0 | -533.73 |
| wide3_mnq_mes | 2 | 0 | $0 | -533.73 |

True stop-risk basis after lag-1 fix:

| variant | risk_med | risk_max | risk_day_max | atr_med | ratio_med |
| --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | $262 | $355 | $524 | 2425.80 | 9.53 |
| wide3_mnq_mes | $262 | $355 | $524 | 2425.80 | 9.53 |

True stop-risk cap table:

| variant | cap | max_pos | trades | rejected | net | pf |
| --- | --- | --- | --- | --- | --- | --- |
| breadth3_mnq_mes | 2.5% | 1 | 1 | 1 | $-358 | 0.00 |
| breadth3_mnq_mes | 2.5% | 2 | 2 | 0 | $-534 | 0.00 |
| breadth3_mnq_mes | 5.0% | 1 | 1 | 1 | $-358 | 0.00 |
| breadth3_mnq_mes | 5.0% | 2 | 2 | 0 | $-534 | 0.00 |
| wide3_mnq_mes | 2.5% | 1 | 1 | 1 | $-358 | 0.00 |
| wide3_mnq_mes | 2.5% | 2 | 2 | 0 | $-534 | 0.00 |
| wide3_mnq_mes | 5.0% | 1 | 1 | 1 | $-358 | 0.00 |
| wide3_mnq_mes | 5.0% | 2 | 2 | 0 | $-534 | 0.00 |

Lag-1 base by event subtype:

        event_subtype  trades     net      avg  pf
crash-gap/liquidation       2 -533.73 -266.865 0.0

Live bar-cut probe using lag-1 labels and `entry_signals`:

{'breadth3': {'10:15': {'signal_days': 0, 'signal_legs': 0}, '10:20': {'signal_days': 1, 'signal_legs': 2}, '10:21': {'signal_days': 1, 'signal_legs': 2}}, 'wide_range3': {'10:15': {'signal_days': 0, 'signal_legs': 0}, '10:20': {'signal_days': 1, 'signal_legs': 2}, '10:21': {'signal_days': 1, 'signal_legs': 2}}}

## Consolidated Verdict

S1 confirmed. Same-day regime labels materially inflated the primary Stress result. After applying lag-1 causal labels, `breadth3_mnq_mes` is not paper-ready.

S2 confirmed in substance. Same-symbol conflict remains common enough after the lag-1 fix that paper deployment still needs either overlap blocking or separate account/stop ownership.

S3 confirmed for the earlier WFO evidence. The old event WFO did not support the promoted primary. The lag-1 WFO table above is the replacement evidence and should decide any future candidate.

S5 confirmed. The high 7.5%-10% cap narrative came from the wrong ATR risk basis. True stop risk is small enough that 2.5% cap is not the limiting issue; max concurrent and symbol conflict are the actual gates.

S4.1 confirmed by measurement. With bars cut at 10:15, the batch live API produces zero 10:20 signals; bars through 10:20 or later are required.

Updated status: research hedge only. Do not start production deploy plumbing until a lag-1 event-WFO candidate is selected and same-symbol overlap policy is specified.
