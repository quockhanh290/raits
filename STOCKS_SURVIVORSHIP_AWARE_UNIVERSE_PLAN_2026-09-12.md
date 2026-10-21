# Stocks Survivorship-Aware Universe Plan - 2026-09-12

## Purpose

Build a point-in-time equity universe so the current stocks research path can move beyond the
current-survivor Polygon-62 limitation.

Current state:

- Lead research path is no-ML stocks only.
- Current data is Polygon adjusted 5-minute bars for the current 62-stock universe plus SPY.
- Warmup now starts at the earliest authorized Polygon intraday date, 2016-09-13 in returned bars.
- Current lead remains `B_polygon62_no_intraday_cap40`, but it is `WARN+`, not production PASS.

Main blocker:

- Current universe is a survivor universe. It excludes historical names that disappeared,
  underweights ticker changes, and cannot answer whether the observed edge survives realistic
  historical membership and delisting.

This document is a build plan, not a vendor selection or a trading rule change.

## First Principle

The universe must be selected using only information available as of each trading date.

No row in a signal, feature, liquidity filter, or ticker mapping may depend on knowledge that became
available after that date.

## Required Data Contract

### 1. Security Master

One stable row per security identity, not per ticker spelling.

Required fields:

| field | meaning |
|---|---|
| `security_id` | stable internal id; never reused |
| `company_id` | optional issuer/company id if available |
| `primary_listing_exchange` | exchange at listing or as-of row |
| `security_type` | common stock, ADR, ETF, preferred, warrant, etc. |
| `currency` | trading currency |
| `country` | issuer or listing country |
| `first_trade_date` | first known regular trading date |
| `last_trade_date` | last known regular trading date |
| `delist_date` | delisting date if any |
| `delist_reason` | merger, bankruptcy, acquisition, exchange move, unknown, etc. |
| `is_etf` | explicit ETF/fund flag |
| `is_adr` | explicit ADR flag |

Minimum acceptable scope for this project:

- US-listed common stocks.
- Exclude ETFs/funds, preferreds, warrants, units, rights, and non-common share classes unless
  explicitly whitelisted.
- Keep delisted common stocks.

### 2. Ticker History

Ticker is not identity. The system needs a date-ranged mapping from ticker spellings to
`security_id`.

Required fields:

| field | meaning |
|---|---|
| `security_id` | stable id |
| `ticker` | ticker used for market data calls and signal labels |
| `start_date` | first date ticker is valid |
| `end_date` | last date ticker is valid |
| `source_ticker` | raw vendor ticker if different |
| `canonical_ticker` | current or display ticker |
| `event_type` | rename, share-class change, merger, exchange move, unknown |

Rules:

- Ticker ranges must not overlap for the same `security_id`.
- A ticker may map to different `security_id` values at different date ranges.
- The same date/ticker must not map to multiple active security ids unless the source gives a
  disambiguating listing id.

### 3. Corporate Actions

Required fields:

| field | meaning |
|---|---|
| `security_id` | stable id |
| `ex_date` | action ex-date |
| `action_type` | split, reverse split, dividend, special dividend, spin-off, merger adjustment |
| `split_ratio` | split ratio when applicable |
| `cash_amount` | dividend amount when applicable |
| `adjustment_factor` | cumulative or event factor if vendor supplies it |
| `source_timestamp` | when the event was known if available |

Rules:

- Backtests may use vendor adjusted bars if adjustment policy is documented.
- QA must verify split continuity around major known events.
- If using adjusted bars, all sleeves must use the same adjustment basis.

### 4. Daily Universe Membership

This is the load-bearing table.

Required fields:

| field | meaning |
|---|---|
| `date` | trading date |
| `security_id` | stable id |
| `ticker` | ticker valid on that date |
| `in_base_universe` | raw membership before liquidity filters |
| `eligible_common_stock` | security-type and listing filter |
| `eligible_liquidity` | point-in-time liquidity filter |
| `eligible_price` | point-in-time price filter |
| `eligible_final` | final tradable universe flag |
| `reason_excluded` | concise exclusion reason when final flag is false |

Minimum daily membership logic:

1. Start with all US-listed common stocks active on that date.
2. Exclude funds, ETFs, preferreds, warrants, units, rights, and non-common instruments.
3. Apply point-in-time price and liquidity filters using only prior data.
4. Keep delisted names while they were active historically.

### 5. Market Data Coverage

For each `security_id` and date, track whether usable bars exist.

Required fields:

| field | meaning |
|---|---|
| `date` | trading date |
| `security_id` | stable id |
| `ticker` | ticker used for the request |
| `has_daily_bar` | daily OHLCV exists |
| `has_5m_0930` | 09:30 bar exists |
| `has_5m_0935` | 09:35 bar exists |
| `has_5m_1000` | 10:00 bar exists |
| `has_5m_1555` | 15:55 bar exists |
| `has_5m_1600` | 16:00 bar exists |
| `missing_reason` | halt, early close, no source data, delisted, unknown |

Rules:

- Missing bars must be explicit, not silently dropped.
- Known market-wide halts and early closes should be tagged.
- Delisting periods must not be mistaken for ordinary missing data.

## Proposed Local Files

All new files should be separate from current Polygon-62 outputs.

Suggested cache layout:

```text
raits/data/cache/stocks_survivorship/
  security_master.parquet
  ticker_history.parquet
  corporate_actions.parquet
  daily_universe.parquet
  market_data_coverage.parquet
  manifests/
    source_manifest_YYYYMMDD.json
    qa_manifest_YYYYMMDD.json
```

Suggested derived files:

```text
raits/data/cache/window_debug_5min_STOCKS_PIT_YYYY_YYYY.pkl
raits/data/cache/stocks_clean_daily_features_STOCKS_PIT_YYYY_YYYY.pkl
raits/data/cache/stocks_intraday_0935_features_STOCKS_PIT_YYYY_YYYY.pkl
raits/data/cache/stocks_gap_rvol30_features_STOCKS_PIT_YYYY_YYYY.pkl
```

Suggested report outputs:

```text
STOCKS_PIT_UNIVERSE_QA_SUMMARY_YYYYMMDD.csv
STOCKS_PIT_UNIVERSE_QA_DAILY_COUNTS_YYYYMMDD.csv
STOCKS_PIT_UNIVERSE_QA_TICKER_EVENTS_YYYYMMDD.csv
STOCKS_PIT_UNIVERSE_QA_MISSING_BARS_YYYYMMDD.csv
```

## Build Phases

### Phase 0 - Requirements Freeze

Deliverable:

- This document reviewed and accepted.

Decisions to freeze:

- Universe scope: US common stocks only.
- Minimum start date.
- Whether ADRs are included.
- Whether multiple share classes are included.
- Whether the first PIT run targets all eligible stocks or a liquidity-capped subset.

Recommended initial target:

- US common stocks.
- Include delisted names.
- Exclude ETFs/funds/preferred/warrants/units/rights.
- Include ADRs only if explicitly desired later.
- Start with 2018-2024 scoring plus available warmup, then extend backward only after QA passes.

### Phase 1 - Source Evaluation

Do not write strategy results in this phase.

Tasks:

- Identify a data source that can provide historical constituents or all active/delisted US common
  stocks by date.
- Confirm ticker history and delisting coverage.
- Confirm intraday or daily bar availability for delisted names.
- Confirm adjustment policy for splits/dividends.
- Confirm API terms and historical depth before fetching bulk data.

Pass criteria:

- Source can represent delisted names and ticker changes.
- Source can build a daily universe without current-survivor look-ahead.
- Source can connect security identity to market bars.

### Phase 2 - Security Master and Ticker Map

Tasks:

- Build `security_master.parquet`.
- Build `ticker_history.parquet`.
- Create stable internal `security_id`.
- Add QA for duplicate/overlapping ticker ranges.

QA:

- No duplicate `security_id`.
- No overlapping ticker ranges for the same security.
- Known examples pass manual checks:
  - FB to META.
  - GOOG/GOOGL share classes.
  - mergers/acquisitions with delisting.

### Phase 3 - Daily PIT Universe

Tasks:

- Generate one row per eligible security per trading date.
- Apply point-in-time filters.
- Write `daily_universe.parquet`.

Initial filters:

- Active on date.
- Common stock.
- Price above threshold using prior close or same-day open only where causally allowed.
- ADV/liquidity using prior rolling window only.

QA:

- Daily universe count time series.
- Entry/exit reason counts.
- No future delisting knowledge used before delist event.
- Random date samples manually inspectable.

### Phase 4 - Market Data Binding

Tasks:

- Fetch or bind daily and 5-minute bars using the ticker valid on each date.
- Preserve `security_id` in all feature and signal rows.
- Keep ticker as display/request field, not identity.

QA:

- Daily coverage by year.
- 5-minute keybar coverage by year.
- Missing keybar reason table.
- Corporate-action continuity checks around large split events.

### Phase 5 - Feature Pipeline Integration

Tasks:

- Update feature builders to accept `security_id` plus date-valid ticker.
- Generate daily, 09:35, and gap/rvol features from PIT market data.
- Keep current Polygon-62 pipeline untouched.

QA:

- No duplicate `(date, security_id)` features.
- Warmup rows are available before scoring rows.
- Feature rolling windows use only past rows for the same `security_id`.

### Phase 6 - Sleeve Regeneration

Tasks:

- Rebuild broad, local, and YDAY sleeves on PIT universe.
- Keep current sleeve configs fixed.
- Do not optimize parameters on the PIT run.

QA:

- Signal counts by year/sleeve.
- Names entering/leaving versus current-survivor Polygon-62.
- PnL attribution by security status: active today vs delisted later.

### Phase 7 - One-Engine Replay

Tasks:

- Run the same no-ML one-engine portfolio on PIT signals.
- Compare against current-survivor Polygon-62.

Required comparison:

| metric | current-survivor | PIT universe | delta |
|---|---:|---:|---:|
| PnL | | | |
| CAGR | | | |
| DD | | | |
| Sharpe | | | |
| trades | | | |
| 2018 | | | |
| 2022 | | | |
| top 10 ticker PnL share | | | |

Interpretation rule:

- If PIT performance collapses, current lead cannot be promoted.
- If PIT performance survives but concentration remains high, keep `WARN+`.
- Production PASS still requires operational feasibility and proper OOS handling.

## Required QA Gates

### Gate A - Identity Integrity

Pass if:

- All signal rows have `security_id`.
- No signal row uses ticker alone as identity.
- Ticker on a row is valid for that `security_id` on that date.

### Gate B - PIT Integrity

Pass if:

- Universe membership on date `d` does not depend on events after `d`.
- Liquidity filters use prior rolling windows only.
- Delisted names are present before delist and absent after delist.

### Gate C - Market Data Integrity

Pass if:

- Missing bars are counted and explained.
- Known splits have continuous adjusted prices.
- Ticker changes bridge correctly.

### Gate D - Strategy Reproducibility

Pass if:

- Current configs reproduce without manual CSV edits.
- All PIT outputs have retained scripts.
- Summary can be recomputed from equity/trades.

### Gate E - Research Hygiene

Pass if:

- No 2025-2026 OOS is opened.
- Current-survivor and PIT results are labeled separately.
- No production verdict is upgraded without independent audit.

## Open Decisions

1. Should ADRs be included?
2. Should multiple share classes be included separately?
3. What minimum price threshold is acceptable?
4. What minimum ADV threshold should define tradability?
5. Should the first PIT version use all eligible names or a capped top-liquidity universe?
6. Which source provides delisted intraday bars with reliable ticker history?
7. How far back should PIT history go before the sealed OOS process?

## Recommended Next Step

Before selecting a vendor or fetching data, build a small local prototype schema with 5-10 known
securities:

- one stable survivor;
- one ticker rename, e.g. FB/META;
- one major split name;
- one delisted/acquired name;
- one multiple-share-class issuer.

The prototype should prove that the pipeline can carry `security_id` from universe membership to
features, signals, trades, and concentration reports.

Only after that prototype passes should bulk data acquisition begin.

