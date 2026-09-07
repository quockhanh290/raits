# Stress Pass 2 - Event And Risk Gate

Scratch-only follow-up. This pass tests whether Stress deserves more work after the first event validation.

## floor

Policy table:

| policy | trades | net | PF | Calmar | MaxDD% |
| --- | ---: | ---: | ---: | ---: | ---: |
| base | 84 | $2,749 | 1.49 | 0.26 | 4.4% |
| crash_liq_only | 61 | $2,588 | 1.60 | 0.28 | 4.0% |
| no_false_chop | 78 | $2,465 | 1.46 | 0.23 | 4.5% |
| no_bear_cont | 67 | $2,871 | 1.64 | 0.31 | 3.9% |
| stop_pct_le_010 | 69 | $2,040 | 1.51 | 0.25 | 3.4% |
| stop_pct_le_012 | 77 | $3,214 | 1.69 | 0.34 | 3.9% |
| wide3 | 61 | $2,588 | 1.60 | 0.28 | 4.0% |
| late_cont | 48 | $1,968 | 1.77 | 0.59 | 1.4% |
| hybrid_crash_wide_else_late | 76 | $1,945 | 1.36 | 0.16 | 5.2% |
| hybrid_crash_base_else_late | 76 | $1,945 | 1.36 | 0.16 | 5.2% |

Cap table for base:

| risk_mode | cap | max_pos | trades | rejected | net | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| stop | 2.5% | 1 | 44 | 40 | $1,807 | 1.55 |
| stop | 2.5% | 2 | 84 | 0 | $2,749 | 1.49 |
| stop | 2.5% | all | 84 | 0 | $2,749 | 1.49 |
| stop | 5.0% | 1 | 44 | 40 | $1,807 | 1.55 |
| stop | 5.0% | 2 | 84 | 0 | $2,749 | 1.49 |
| stop | 5.0% | all | 84 | 0 | $2,749 | 1.49 |
| stop | 7.5% | 1 | 44 | 40 | $1,807 | 1.55 |
| stop | 7.5% | 2 | 84 | 0 | $2,749 | 1.49 |
| stop | 7.5% | all | 84 | 0 | $2,749 | 1.49 |
| stop | 10.0% | 1 | 44 | 40 | $1,807 | 1.55 |
| stop | 10.0% | 2 | 84 | 0 | $2,749 | 1.49 |
| stop | 10.0% | all | 84 | 0 | $2,749 | 1.49 |
| deploy_atr | 2.5% | 1 | 20 | 64 | $119 | 1.09 |
| deploy_atr | 2.5% | 2 | 20 | 64 | $119 | 1.09 |
| deploy_atr | 2.5% | all | 20 | 64 | $119 | 1.09 |
| deploy_atr | 5.0% | 1 | 43 | 41 | $1,589 | 1.49 |
| deploy_atr | 5.0% | 2 | 59 | 25 | $1,086 | 1.24 |
| deploy_atr | 5.0% | all | 59 | 25 | $1,086 | 1.24 |
| deploy_atr | 7.5% | 1 | 44 | 40 | $1,754 | 1.52 |
| deploy_atr | 7.5% | 2 | 76 | 8 | $1,841 | 1.35 |
| deploy_atr | 7.5% | all | 76 | 8 | $1,841 | 1.35 |
| deploy_atr | 10.0% | 1 | 44 | 40 | $1,754 | 1.52 |
| deploy_atr | 10.0% | 2 | 83 | 1 | $2,856 | 1.52 |
| deploy_atr | 10.0% | all | 83 | 1 | $2,856 | 1.52 |

Base by event subtype:

| event_subtype | trades | net | avg | pf |
| --- | --- | --- | --- | --- |
| bear-trend continuation | 17 | -122.53 | -7.21 | 0.89 |
| crash-gap/liquidation | 61 | 2588.01 | 42.43 | 1.60 |
| false stress / chop | 6 | 283.22 | 47.20 | 2.33 |

Same-day stress overlap proxy: {'same_day_pairs': 40, 'two_inst_days': 40, 'mnq_mes_opposite_risk': 40}

## vault2025

Policy table:

| policy | trades | net | PF | Calmar | MaxDD% |
| --- | ---: | ---: | ---: | ---: | ---: |
| base | 19 | $4,095 | 7.10 | 54.09 | 1.3% |
| crash_liq_only | 15 | $3,622 | 10.67 | 89.15 | 0.7% |
| no_false_chop | 17 | $4,392 | 12.73 | 105.53 | 0.7% |
| no_bear_cont | 17 | $3,325 | 5.96 | 44.99 | 1.3% |
| stop_pct_le_010 | 13 | $985 | 2.47 | 13.01 | 1.3% |
| stop_pct_le_012 | 16 | $2,559 | 4.81 | 33.80 | 1.3% |
| wide3 | 15 | $3,622 | 10.67 | 89.15 | 0.7% |
| late_cont | 14 | $597 | 1.44 | 5.67 | 1.8% |
| hybrid_crash_wide_else_late | 19 | $3,711 | 6.12 | 45.32 | 1.4% |
| hybrid_crash_base_else_late | 19 | $3,711 | 6.12 | 45.32 | 1.4% |

Cap table for base:

| risk_mode | cap | max_pos | trades | rejected | net | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| stop | 2.5% | 1 | 10 | 9 | $2,645 | 8.65 |
| stop | 2.5% | 2 | 19 | 0 | $4,095 | 7.10 |
| stop | 2.5% | all | 19 | 0 | $4,095 | 7.10 |
| stop | 5.0% | 1 | 10 | 9 | $2,645 | 8.65 |
| stop | 5.0% | 2 | 19 | 0 | $4,095 | 7.10 |
| stop | 5.0% | all | 19 | 0 | $4,095 | 7.10 |
| stop | 7.5% | 1 | 10 | 9 | $2,645 | 8.65 |
| stop | 7.5% | 2 | 19 | 0 | $4,095 | 7.10 |
| stop | 7.5% | all | 19 | 0 | $4,095 | 7.10 |
| stop | 10.0% | 1 | 10 | 9 | $2,645 | 8.65 |
| stop | 10.0% | 2 | 19 | 0 | $4,095 | 7.10 |
| stop | 10.0% | all | 19 | 0 | $4,095 | 7.10 |
| deploy_atr | 2.5% | 1 | 0 | 19 | $0 | inf |
| deploy_atr | 2.5% | 2 | 0 | 19 | $0 | inf |
| deploy_atr | 2.5% | all | 0 | 19 | $0 | inf |
| deploy_atr | 5.0% | 1 | 4 | 15 | $593 | 48.44 |
| deploy_atr | 5.0% | 2 | 4 | 15 | $593 | 48.44 |
| deploy_atr | 5.0% | all | 4 | 15 | $593 | 48.44 |
| deploy_atr | 7.5% | 1 | 10 | 9 | $2,070 | 7.62 |
| deploy_atr | 7.5% | 2 | 10 | 9 | $2,070 | 7.62 |
| deploy_atr | 7.5% | all | 10 | 9 | $2,070 | 7.62 |
| deploy_atr | 10.0% | 1 | 10 | 9 | $2,070 | 7.62 |
| deploy_atr | 10.0% | 2 | 12 | 7 | $2,317 | 8.12 |
| deploy_atr | 10.0% | all | 12 | 7 | $2,317 | 8.12 |

Base by event subtype:

| event_subtype | trades | net | avg | pf |
| --- | --- | --- | --- | --- |
| bear-trend continuation | 2 | 770.02 | 385.01 | inf |
| crash-gap/liquidation | 15 | 3621.78 | 241.45 | 10.67 |
| false stress / chop | 2 | -296.51 | -148.25 | 0.00 |

Same-day stress overlap proxy: {'same_day_pairs': 9, 'two_inst_days': 9, 'mnq_mes_opposite_risk': 9}

## vault2026

Policy table:

| policy | trades | net | PF | Calmar | MaxDD% |
| --- | ---: | ---: | ---: | ---: | ---: |
| base | 0 | $0 | inf | 0.00 | 0.0% |
| crash_liq_only | 0 | $0 | inf | 0.00 | 0.0% |
| no_false_chop | 0 | $0 | inf | 0.00 | 0.0% |
| no_bear_cont | 0 | $0 | inf | 0.00 | 0.0% |
| stop_pct_le_010 | 0 | $0 | inf | 0.00 | 0.0% |
| stop_pct_le_012 | 0 | $0 | inf | 0.00 | 0.0% |
| wide3 | 0 | $0 | inf | 0.00 | 0.0% |
| late_cont | 0 | $0 | inf | 0.00 | 0.0% |
| hybrid_crash_wide_else_late | 0 | $0 | inf | 0.00 | 0.0% |
| hybrid_crash_base_else_late | 0 | $0 | inf | 0.00 | 0.0% |

Cap table for base:

| risk_mode | cap | max_pos | trades | rejected | net | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| stop | 2.5% | 1 | 0 | 0 | $0 | inf |
| stop | 2.5% | 2 | 0 | 0 | $0 | inf |
| stop | 2.5% | all | 0 | 0 | $0 | inf |
| stop | 5.0% | 1 | 0 | 0 | $0 | inf |
| stop | 5.0% | 2 | 0 | 0 | $0 | inf |
| stop | 5.0% | all | 0 | 0 | $0 | inf |
| stop | 7.5% | 1 | 0 | 0 | $0 | inf |
| stop | 7.5% | 2 | 0 | 0 | $0 | inf |
| stop | 7.5% | all | 0 | 0 | $0 | inf |
| stop | 10.0% | 1 | 0 | 0 | $0 | inf |
| stop | 10.0% | 2 | 0 | 0 | $0 | inf |
| stop | 10.0% | all | 0 | 0 | $0 | inf |
| deploy_atr | 2.5% | 1 | 0 | 0 | $0 | inf |
| deploy_atr | 2.5% | 2 | 0 | 0 | $0 | inf |
| deploy_atr | 2.5% | all | 0 | 0 | $0 | inf |
| deploy_atr | 5.0% | 1 | 0 | 0 | $0 | inf |
| deploy_atr | 5.0% | 2 | 0 | 0 | $0 | inf |
| deploy_atr | 5.0% | all | 0 | 0 | $0 | inf |
| deploy_atr | 7.5% | 1 | 0 | 0 | $0 | inf |
| deploy_atr | 7.5% | 2 | 0 | 0 | $0 | inf |
| deploy_atr | 7.5% | all | 0 | 0 | $0 | inf |
| deploy_atr | 10.0% | 1 | 0 | 0 | $0 | inf |
| deploy_atr | 10.0% | 2 | 0 | 0 | $0 | inf |
| deploy_atr | 10.0% | all | 0 | 0 | $0 | inf |

Base by event subtype:

_empty_

Same-day stress overlap proxy: {'same_day_pairs': 0, 'two_inst_days': 0, 'mnq_mes_opposite_risk': 0}

## Verdict

Stop digging broad Stress alpha. Keep exactly one hedge candidate on the board: `breadth3_mnq_mes` or the slightly more conservative `wide3_mnq_mes` if risk review prefers lower chop exposure.

The follow-up did not create a stronger robust standalone Stress sleeve. Filtering to crash/liquidation improves the story but mostly restates where the edge already lives; `late_cont_break` is smoother in IS but too weak in 2025. The two-stage partial gives up too much payoff.

Next action is not more parameter mining. Next action is a deploy feasibility gate: live 10:20 basket confirmation, explicit same-day Stress stop/exit ownership, same-symbol netting resolution, and final cap choice around 7.5%-10% if using deploy-style ATR risk.

Account assumption: $50,000.
