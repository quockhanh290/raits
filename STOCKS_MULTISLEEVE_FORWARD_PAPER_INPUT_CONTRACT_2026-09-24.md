# Multi-Sleeve Forward Paper Input Contract

The runner consumes two CSV files. Both paper accounts receive the same target rows.

## Targets

Required columns:

`effective_date,clock,signal_timestamp,source,ticker,source_target_weight`

- `clock` is `0935` or `1555`.
- `source` is `pairs` or `calendar`.
- Pair weights are gross-normalized within the pair sleeve. For example, one active pair is `+0.5/-0.5`.
- Calendar rows contain SPY at source exposure `0.0` or `2.5`.
- Every active source must provide a complete snapshot at its clock. Omitted tickers become zero for that source.
- A source with no active position must provide one `__FLAT__` row with weight `0`; this declares a complete
  empty snapshot and requires no market row.
- `signal_timestamp` must not be later than the corresponding market timestamp.

## Market

Required columns:

`effective_date,clock,timestamp,ticker,price,adv20,borrow_available,asset_type`

- `price` is the exact simulated execution/mark price at the named clock.
- `adv20` is PIT dollar ADV known at that timestamp.
- `borrow_available` is `true` or `false`.
- `asset_type` is `stock` or `etf`.
- Each event must include marks for all current holdings and all requested target tickers.

## Timing

- Pair targets execute at 09:35 ET.
- Calendar targets execute at 15:55 ET. The target builder must supply the position intended after that close;
  the first-five rule is therefore determined from the known exchange session calendar, not future prices.
- Rows are processed chronologically by `timestamp`. Duplicate `(effective_date, clock, ticker)` market rows
  or duplicate `(effective_date, clock, source, ticker)` target rows are rejected.

The runner refuses dates after 2024-12-31 unless `--allow-post-2024` is explicitly supplied. That flag is
the operational acknowledgement that forward/OOS data access has been approved.
