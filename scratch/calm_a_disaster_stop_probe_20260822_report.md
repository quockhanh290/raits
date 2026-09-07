# Calm A Disaster Stop Probe - 2026-08-22

Scratch-only. Tests explicit disaster stops for Calm A PCLoc bottom-down not-deep-gap. Combined rows use the current strongest base plus Calm A with skip-same-symbol and Calm cap 5%.

Stop fill rule for LONG: if a forward bar trades through the stop, fill at stop unless the bar opens below the stop, in which case fill at the open.

## floor

| stop | standalone_n | standalone_net | standalone_pf | standalone_dd | stop_rate | med_risk | max_risk | Calm taken/rej | combined_net | combined_pf | combined_sharpe | combined_calmar | combined_maxdd | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| no_stop | 349 | $9,718 | 1.67 | $1,720 | 0.0% | $580 | $2,062 | 335/7 | $72,732 | 1.65 | 2.06 | 2.11 | $4,923 | 2 |
| atr05 | 349 | $8,757 | 1.58 | $1,397 | 25.8% | $116 | $412 | 342/0 | $72,794 | 1.65 | 2.07 | 2.12 | $4,923 | 2 |
| atr10 | 349 | $7,957 | 1.49 | $1,912 | 7.7% | $232 | $825 | 342/0 | $71,843 | 1.63 | 2.03 | 2.09 | $4,923 | 2 |
| atr15 | 349 | $9,686 | 1.67 | $1,792 | 0.6% | $348 | $1,237 | 342/0 | $73,599 | 1.66 | 2.08 | 2.14 | $4,923 | 2 |
| atr20 | 349 | $9,718 | 1.67 | $1,720 | 0.0% | $464 | $1,650 | 342/0 | $73,631 | 1.66 | 2.08 | 2.14 | $4,923 | 2 |
| or_low_1tick | 349 | $5,606 | 1.54 | $1,140 | 62.2% | $39 | $314 | 342/0 | $69,622 | 1.64 | 1.99 | 2.01 | $4,951 | 2 |

## vault2025

| stop | standalone_n | standalone_net | standalone_pf | standalone_dd | stop_rate | med_risk | max_risk | Calm taken/rej | combined_net | combined_pf | combined_sharpe | combined_calmar | combined_maxdd | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| no_stop | 44 | $2,050 | 2.69 | $362 | 0.0% | $1,009 | $2,620 | 38/4 | $17,881 | 2.32 | 2.85 | 4.63 | $3,943 | 0 |
| atr05 | 44 | $-151 | 0.95 | $1,015 | 29.5% | $202 | $524 | 42/0 | $15,893 | 2.02 | 2.50 | 4.16 | $3,896 | 0 |
| atr10 | 44 | $1,804 | 2.24 | $571 | 2.3% | $404 | $1,048 | 42/0 | $17,848 | 2.28 | 2.84 | 4.67 | $3,896 | 0 |
| atr15 | 44 | $2,050 | 2.69 | $362 | 0.0% | $605 | $1,572 | 42/0 | $18,093 | 2.33 | 2.88 | 4.74 | $3,896 | 0 |
| atr20 | 44 | $2,050 | 2.69 | $362 | 0.0% | $807 | $2,096 | 41/1 | $18,046 | 2.32 | 2.87 | 4.67 | $3,943 | 0 |
| or_low_1tick | 44 | $18 | 1.01 | $788 | 61.4% | $66 | $377 | 42/0 | $16,165 | 2.12 | 2.58 | 4.22 | $3,912 | 0 |

## vault2026

| stop | standalone_n | standalone_net | standalone_pf | standalone_dd | stop_rate | med_risk | max_risk | Calm taken/rej | combined_net | combined_pf | combined_sharpe | combined_calmar | combined_maxdd | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| no_stop | 28 | $1,185 | 1.61 | $385 | 0.0% | $1,724 | $3,200 | 15/12 | $10,132 | 1.72 | 2.77 | 3.72 | $4,342 | 0 |
| atr05 | 28 | $466 | 1.19 | $757 | 17.9% | $345 | $640 | 27/0 | $9,416 | 1.60 | 2.45 | 3.46 | $4,342 | 0 |
| atr10 | 28 | $1,185 | 1.61 | $385 | 0.0% | $690 | $1,280 | 27/0 | $10,135 | 1.67 | 2.64 | 3.72 | $4,342 | 0 |
| atr15 | 28 | $1,185 | 1.61 | $385 | 0.0% | $1,035 | $1,920 | 26/1 | $9,779 | 1.65 | 2.57 | 3.59 | $4,342 | 0 |
| atr20 | 28 | $1,185 | 1.61 | $385 | 0.0% | $1,379 | $2,560 | 18/9 | $9,861 | 1.66 | 2.61 | 3.62 | $4,342 | 0 |
| or_low_1tick | 28 | $1,079 | 1.80 | $495 | 50.0% | $106 | $2,354 | 26/1 | $10,108 | 1.70 | 2.70 | 3.71 | $4,342 | 0 |
