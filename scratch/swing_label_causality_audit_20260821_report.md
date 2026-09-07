# Swing Regime Label Causality Audit - 2026-08-21

Scope: scratch-only measurement. Production code was not modified.

Question: does the validated R4 swing baseline depend materially on same-day
HMM regime labels that are only known after the 16:00 SPY close, while entries
can occur from 14:00 to 15:55?

Method:

- `lag0` = existing `label_regimes` labels.
- `lag1` = previous available label, applied only to R4 swing.
- NKD remains on its existing `RegimeLabels(..., lag_days=1)` path in combined replay.
- Costs use the harness window settings, usually 2 ticks/side.

## R4 Swing 1-Micro Results

| Window | Basis | Trades | Entry days | Net | PF | Sharpe | Calmar | MaxDD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| floor | lag0 | 2273 | 866 | $34,699 | 1.34 | 0.84 | 0.77 | $6,540 |
| floor | lag1 | 2292 | 871 | $37,785 | 1.38 | 0.91 | 0.83 | $6,574 |
| vault2324 | lag0 | 538 | 201 | $8,122 | 1.32 | 0.74 | 1.26 | $3,251 |
| vault2324 | lag1 | 550 | 203 | $11,589 | 1.46 | 0.99 | 1.83 | $3,216 |
| vault2025 | lag0 | 304 | 116 | $7,060 | 1.33 | 0.59 | 0.87 | $8,367 |
| vault2025 | lag1 | 309 | 112 | $8,536 | 1.38 | 0.66 | 0.96 | $9,250 |
| vault2026 | lag0 | 251 | 91 | $1,699 | 1.10 | 0.32 | 0.61 | $4,896 |
| vault2026 | lag1 | 245 | 89 | $3,560 | 1.24 | 0.71 | 1.56 | $4,069 |

## Combined Deploy Replay

R4 labels are varied. NKD labels are left on the current causal lag-1 path.

| Window | Basis | Net | PF | Sharpe | Calmar | MaxDD | R4 contracts | Swing taken/rejected | NKD taken/rejected |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| floor | lag0 | $42,565 | 1.53 | 1.79 | 1.65 | $3,744 | 1 | 1606/667 | 637/0 |
| floor | lag1 | $45,811 | 1.58 | 1.92 | 1.77 | $3,752 | 1 | 1616/676 | 637/0 |
| vault2324 | lag0 | $10,757 | 1.50 | 1.71 | 2.86 | $1,899 | 1 | 377/161 | 147/0 |
| vault2324 | lag1 | $13,828 | 1.66 | 2.14 | 3.66 | $1,909 | 1 | 379/171 | 147/0 |
| vault2025 | lag0 | $7,448 | 1.56 | 1.78 | 2.58 | $2,968 | 1 | 172/132 | 94/0 |
| vault2025 | lag1 | $7,426 | 1.52 | 1.71 | 2.22 | $3,474 | 1 | 169/140 | 94/0 |
| vault2026 | lag0 | $3,017 | 1.29 | 1.00 | 1.36 | $3,910 | 1 | 136/115 | 62/6 |
| vault2026 | lag1 | $3,108 | 1.31 | 1.14 | 1.51 | $3,642 | 1 | 131/114 | 62/6 |

## Label And Trade-Day Movement

| Window | Comparable label days | Label flips | Lag0-only trade days / PnL | Lag1-only trade days / PnL | Both-days lag0 vs lag1 PnL |
|---|---:|---:|---:|---:|---:|
| floor | 1759 | 147 | 56 / $877 | 61 / $1,316 | $33,821 vs $36,469 |
| vault2324 | 501 | 46 | 22 / $-419 | 24 / $1,172 | $8,541 vs $10,417 |
| vault2025 | 249 | 31 | 14 / $491 | 10 / $-1,181 | $6,569 vs $9,716 |
| vault2026 | 158 | 20 | 11 / $-2,751 | 9 / $170 | $4,450 vs $3,390 |

## By Instrument Net

### floor

| Instrument | Lag0 | Lag1 | Delta |
|---|---:|---:|---:|
| M2K | $3,706 | $4,223 | $518 |
| MES | $7,348 | $7,856 | $507 |
| MNQ | $17,244 | $19,026 | $1,782 |
| MYM | $6,400 | $6,680 | $280 |

### vault2324

| Instrument | Lag0 | Lag1 | Delta |
|---|---:|---:|---:|
| M2K | $1,242 | $1,268 | $27 |
| MES | $2,311 | $3,237 | $926 |
| MNQ | $5,367 | $7,496 | $2,128 |
| MYM | $-798 | $-412 | $386 |

### vault2025

| Instrument | Lag0 | Lag1 | Delta |
|---|---:|---:|---:|
| M2K | $921 | $1,193 | $272 |
| MES | $705 | $1,336 | $631 |
| MNQ | $4,245 | $4,346 | $102 |
| MYM | $1,190 | $1,661 | $471 |

### vault2026

| Instrument | Lag0 | Lag1 | Delta |
|---|---:|---:|---:|
| M2K | $-895 | $-666 | $230 |
| MES | $-1,147 | $220 | $1,367 |
| MNQ | $2,820 | $3,986 | $1,166 |
| MYM | $920 | $19 | $-901 |

## By Exit Year Net

### floor

| Year | Lag0 | Lag1 | Delta |
|---|---:|---:|---:|
| 2018 | $4,964 | $4,473 | $-491 |
| 2019 | $1,815 | $911 | $-904 |
| 2020 | $13,381 | $15,226 | $1,846 |
| 2021 | $4,627 | $3,351 | $-1,276 |
| 2022 | $-413 | $64 | $477 |
| 2023 | $6,516 | $6,815 | $299 |
| 2024 | $3,809 | $6,945 | $3,137 |

### vault2324

| Year | Lag0 | Lag1 | Delta |
|---|---:|---:|---:|
| 2023 | $4,314 | $4,643 | $330 |
| 2024 | $3,809 | $6,945 | $3,137 |

### vault2025

| Year | Lag0 | Lag1 | Delta |
|---|---:|---:|---:|
| 2025 | $7,060 | $8,536 | $1,476 |

### vault2026

| Year | Lag0 | Lag1 | Delta |
|---|---:|---:|---:|
| 2026 | $1,699 | $3,560 | $1,862 |

## Verdict

The lag-1 repair does not reject the R4 swing baseline. Floor and most OOS
metrics improve under causal labels, and combined deploy replay remains intact.

This is still not a harmless no-op: label flips move dozens of trade days, and
2025 combined Calmar falls because MaxDD rises. Treat the lag-0 R4 convention as
quantified measurement debt. Before the next baseline refresh or paper gate,
decide explicitly whether R4 should follow NKD and use prior-available regime
labels in both research and live paths.
