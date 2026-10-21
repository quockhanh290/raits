# Stocks Research Handoff - 2026-09-11

This handoff is for starting a fresh Codex/Claude session in `D:\raits`.

## Hard Constraints

- Work only on stocks/equity.
- Do not read, run, or edit these off-limits paths:
  - `global_index/**`
  - `monitor/**`
  - `futures/**`
  - `orb_futures/**`
  - `nonequity/**`
  - `tier2/**`
  - `xsect/**`
  - `docs/futures/**`
  - `scratch/**`
- Do not delete parquet/cache files.
- Do not open 2025-2026 OOS unless explicitly approved later.
- Do not commit unless explicitly asked.
- Main report: `STOCKS_CODEX_REVIEW_2026-09-07.md`.

## Current Pipeline State

Current top-level verdict as of report section `6.142`:

```text
The Polygon-62 / broad-PIT stock branch is NOT a money printer yet.
It is a research lead / diagnostic family.
Full broad PIT fails, restricted-62 is strong but universe/curation WARN, and
profile62 is useful diagnostic evidence but not production-ready.
```

If returning later, read `STOCKS_CODEX_REVIEW_2026-09-07.md` sections `6.142` and `6.143` first, then
sections `6.136` through `6.141` for the detailed broad-PIT/restricted-62 investigation.

The current clean research path is no-ML stocks only.

Current clean chain:

```text
Polygon 5m adjusted bars, 2018-2024, current 62-stock universe + SPY
  -> window_debug_5min_POLYGON_2018_2024_62.pkl
  -> Polygon62 feature caches
  -> 3 no-intraday sleeves
  -> one-engine MTM portfolio
```

Current lead excludes:

- ML sleeve: headline FAIL / research-only.
- `intraday_ex10`: FAIL in Polygon-62 2018-2024 one-engine.

Current lead includes:

- `broad_adv10_g2_dd85`
- `local_xs_full_s10`
- `yday_ex6_actual`

The current one-engine sizing is causal:

```text
target_notional = equity_open * sleeve_gross / hold / len(group)
```

Ticker cap and gross cap are applied before orders.

## Data State

Polygon fetch completed for current 62-name universe, 2018-01-01 through 2024-12-31.

Important files:

- `raits/research/stocks_polygon_5min_fetch_2018_2024.py`
- `raits/research/stocks_polygon_5min_bridge_qa.py`
- `raits/research/stocks_polygon_2018_2024_no_ml_pipeline.py`
- `raits/data/cache/polygon_5min_2018_2024_62/`
- `raits/data/cache/window_debug_5min_POLYGON_2018_2024_62.pkl`

Bridge QA summary from previous work:

- 63 symbols including SPY.
- 8,728,437 bars.
- 5m adjusted Polygon data.
- Overlap vs legacy local 5m: 61/62 tickers match essentially exactly.
- META legacy corruption is fixed by Polygon; META is the expected break.
- Known missing keybars:
  - broad-market open halts on 2020-03-09 and 2020-03-16;
  - early closes;
  - small unexpected sparse single-name keybar gaps.

This is still a survivor universe, not survivorship-aware.

## Current Candidate Ledger

Latest old-style candidate ledger is documented in:

- `STOCKS_CODEX_REVIEW_2026-09-07.md`, section `### 6.122 Current full candidate ledger after warmup, audit and PIT checkpoint`.

The older `6.101` ledger is pre-warmup and is no longer the latest candidate snapshot.

However, the current broad-PIT investigation after 6.122 changes the interpretation:

- `B_polygon62_no_intraday_cap40` remains the old lead only under the 62-stock universe.
- It is **not** a production PASS.
- The current checkpoint verdict is section `6.142`, not the 6.122 ledger.

Current primary table, using 2016-09 warmup and 2018-2024 scoring:

| Status | Candidate | Sleeves / Rule | PnL | CAGR | DD | Sharpe | avgGross | maxGross | Trades | 2018 | 2022 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Lead / WARN+ | `B_polygon62_no_intraday_cap40` | broad + local hold20 + yday | `$107.082k` | 17.8% | `-$14.216k` | 1.193 | 0.603x | 0.681x | 32,767 | `-$2.409k` | `-$2.327k` |
| Higher-gross reference / WARN | `A_polygon62_no_intraday_cap40` | broad + local hold20 + yday | `$132.295k` | 20.3% | `-$17.863k` | 1.189 | 0.688x | 0.777x | 32,767 | `-$2.776k` | `-$3.263k` |
| Audit-pending excluded | `B_polygon62_all_cap40` | broad + local + yday + intraday_ex10 | `$136.172k` | 20.7% | `-$17.207k` | 1.266 | 0.602x | 0.754x | 33,222 | `-$2.409k` | `$3.217k` |
| Audit-pending excluded | `A_polygon62_all_cap40` | broad + local + yday + intraday_ex10 | `$170.800k` | 23.7% | `-$23.012k` | 1.257 | 0.687x | 0.876x | 33,222 | `-$2.776k` | `$3.702k` |

Current old-ledger verdict:

- Official research lead remains `B_polygon62_no_intraday_cap40`, but only `WARN+`.
- A is a higher-gross reference.
- Hold5/hold10-vol variants are research-only/risk-shaping diagnostics, not promoted.
- Pyramid variants are rejected.
- Intraday-inclusive variants are attractive in the warmup rerun but excluded pending separate audit.
- Production PASS is not available yet.

Updated verdict from sections 6.136-6.142:

| Branch | Result | Current interpretation |
|---|---:|---|
| Full broad PIT nowarmup B | `$29.361k`, CAGR 7.1%, DD `-$23.691k`, Sharpe 0.271 | FAIL / research-only |
| Historical S&P 500 universe | `$31.570k`, CAGR 7.5%, DD `-$21.579k`, Sharpe 0.367 | FAIL as rescue path |
| Historical Nasdaq-100 universe | `$24.244k`, CAGR 6.0%, DD `-$24.782k`, Sharpe 0.282 | FAIL as rescue path |
| Restricted-to-62 PIT nowarmup B | `$91.363k`, CAGR 16.6%, DD `-$13.834k`, Sharpe 1.141 | strong diagnostic, universe/curation WARN |
| Polygon-62 PIT warmup B | `$107.082k`, CAGR 17.8%, DD `-$14.216k`, Sharpe 1.193 | old lead, still WARN+ |
| `profile62_score_top100` | `$55.055k`, CAGR 11.6%, DD `-$11.184k`, Sharpe 0.860 | diagnostic improvement, not enough |
| `profile62_train_q25` + frozen yday rules | `$59.118k`, CAGR 12.2%, DD `-$13.854k`, Sharpe 1.041 | partial path recovery, still WARN |

Plain-language summary:

- The old 62-stock universe is a large part of the result.
- Full broad PIT does not reproduce the edge.
- Reverse-profile filters prove the 62-stock universe acted like a quality/large-cap/index-like filter,
  but local proxy fields cannot recreate the exact old selection path.
- Historical S&P 500/Nasdaq-100 membership does not rescue the strategy.
- Local is mostly recoverable; yday exact ticker-day path is the main unrecovered blocker.
- The branch is not a "money printer" yet.

## Why Hold5-Vol20 Was Not Promoted

The high-vol challenger looked attractive at first:

```text
B base:              PnL $107.082k, DD -$14.216k, Sharpe 1.193
B hold5 engine size: PnL $114.431k, DD -$15.451k, Sharpe 1.219
```

But fair-sizing showed the improvement is mostly from larger local notional:

| B Variant | PnL | DD | Sharpe | maxGross | 2022 |
|---|---:|---:|---:|---:|---:|
| Base hold20 | `$107.082k` | `-$14.216k` | 1.193 | 0.681x | `-$2.327k` |
| Hold5 + engine sizing | `$114.431k` | `-$15.451k` | 1.219 | 0.828x | `$0.352k` |
| Hold5 + fixed hold20 sizing | `$103.511k` | `-$12.767k` | 1.209 | 0.681x | `-$1.176k` |
| Hold10 + engine sizing | `$110.079k` | `-$14.265k` | 1.200 | 0.761x | `-$1.205k` |
| Hold10 + fixed hold20 sizing | `$104.960k` | `-$13.137k` | 1.204 | 0.681x | `-$1.431k` |

Interpretation:

- Shorter exit alone improves DD/Sharpe but does not beat base PnL.
- The attractive hold5 result depends on `sleeve_gross / hold`, which raises local daily budget when hold drops from 20 to 5.
- Keep this as a tactical research idea, not the official lead.

## Important Recent Report Sections

Read these in order if picking up the thread:

- `6.91` Polygon 5m fetch/bridge QA.
- `6.92` Polygon-62 2018-2024 regenerated no-ML pipeline.
- `6.93` No-intraday robustness stress.
- `6.94` Why 2018 and 2022 are negative.
- `6.95` Independent audit of 6.93.
- `6.96` Causal SPY regime overlay probe.
- `6.97` Refined 2022 fix.
- `6.98` Canonical A/B runner for hold5-vol20.
- `6.99` Independent audit of hold5-vol20.
- `6.100` Fair-sizing check.
- `6.101` Old pre-warmup candidate ledger.
- `6.122` Latest consolidated candidate ledger after warmup/audit/PIT checkpoint.
- `6.123` Current PIT build status before full-daily scale.

## Key Scripts Created/Used Recently

Polygon data:

- `raits/research/stocks_polygon_5min_fetch_2018_2024.py`
- `raits/research/stocks_polygon_5min_bridge_qa.py`
- `raits/research/stocks_polygon_2018_2024_no_ml_pipeline.py`

Current base/stress:

- `raits/research/stocks_polygon62_no_intraday_robustness.py`
- `raits/research/stocks_polygon62_negative_year_diagnostics.py`

Regime/hold experiments:

- `raits/research/stocks_polygon62_regime_overlay_sweep.py`
- `raits/research/stocks_polygon62_regime_refine_sweep.py`
- `raits/research/stocks_polygon62_local_hold5_vol20_candidate.py`
- `raits/research/stocks_polygon62_local_hold_vol20_fair_sizing.py`

Original engine:

- `raits/research/stocks_one_engine_mtm_portfolio.py`

## Known Open Blockers

Before production PASS:

1. Survivor universe, not survivorship-aware.
2. 2023-2024 already opened in earlier research.
3. Warmup is improved but not complete back to 2016-01 because Polygon authorization starts around 2016-09.
4. Concentration remains high: top 10 names carry a large share of PnL.
5. Need pre-registered OOS volatility episodes before trusting hold5-vol20.
6. Need live broker/margin feasibility if using variants with higher intraday exposure.

## Recommended Next Work

### Current PIT universe status as of 2026-09-12

The survivorship-aware/PIT workstream has progressed beyond the original warmup task.

Key current state:

- Main report is current through section `6.143`.
- Limited full-daily transition QA is DONE:
  - FB/META and RLGY/HOUS ticker-change carry-over PASS.
  - TWTR is eligible through 2022-10-27 and excluded on 2022-10-28 by `no_current_daily_bar`.
- Important bugfix:
  - `raits/research/stocks_pit_polygon_liquidity_filter.py` now requires
    `has_current_daily_bar` for `eligible_final`.
  - Prior close/ADV20 still use strictly prior bars only.
- New resumable full-daily builder:
  - `raits/research/stocks_pit_polygon_daily_universe_resumable.py`
  - Use `--mode fetch` to populate per-date cache and `resumable_status.csv`.
  - Use `--mode assemble` only after all target dates are complete.
- Full-daily PIT universe is DONE:
  - tag: `daily_20180102_20241231_resumable`
  - status file:
    `raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20180102_20241231_resumable/resumable_status.csv`
  - 1,826/1,826 dates OK, 0 errors, 0 incomplete.
  - covered dates: 2018-01-02 through 2024-12-31.
  - assembled `daily_universe.parquet`: 9,325,051 rows, 9,491 unique tickers,
    10,382 unique `security_id` values.
  - duplicate identity dropped rows: 740.
- Full-daily liquidity filter is DONE, but use the corrected unadjusted-bars artifact:
  - output directory:
    `raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20180102_20241231_resumable/liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/`
  - final eligible rows: 3,414,774.
  - final eligible rows/day: 0 min, 1,888.5 median, 2,435 max.
  - QA PASS for no future bars, security ids, price filter, liquidity filter and grouped-bar load.
  - QA WARN for ambiguous ticker/security histories: 2,986 rows, 1,420 tickers.
  - QA WARN for ticker fallback used: 1,603,642 rows.
  - 65 business-calendar dates have zero current grouped bars and are excluded by
    `has_current_daily_bar`.
- Superseded artifact:
  - `liquidity_filter_daily_20180102_20241231_px5_adv10m/` used split-adjusted grouped bars.
  - Do not use that artifact for historical price-floor/tradability checks.
- PIT-gated Polygon-62 replay is DONE:
  - script: `raits/research/stocks_polygon62_pit_replay_2016warmup.py`.
  - output prefix: `STOCKS_POLYGON62_PIT_REPLAY_2016WARMUP_2018_2024`.
  - gate QA removed 0 entries after security-id alias matching.
  - security alias rows: 166 broad, 206 local, 2 yday; this handles FB/META historical spelling.
  - lead B PIT replay: PnL $107.082k, CAGR 17.8%, DD -$14.216k, Sharpe 1.193, trades 32,767.
  - This reproduces the Polygon-62 baseline to rounding precision because it only gates the existing
    62-ticker signal cache.
- Broad PIT 5-minute fetch and coverage audit are DONE:
  - plan files:
    `STOCKS_PIT_FULL_5MIN_FETCH_SYMBOLS_2026-09-13.csv`,
    `STOCKS_PIT_FULL_5MIN_FETCH_CHUNKS_2026-09-13.csv`,
    `STOCKS_PIT_FULL_5MIN_FETCH_MANIFEST_2026-09-13.json`.
  - planned symbols: 5,097.
  - raw planned rows: 176,260.
  - runtime symbol/month chunks after union de-dup: 176,028.
  - output directory: `raits/data/cache/polygon_5min_pit_full_2018_2024/`.
  - status file: `raits/data/cache/polygon_5min_pit_full_2018_2024/status.csv`.
  - final dry-run: DONE 176,028, PENDING 0.
  - parquet files: 176,028, about 10.672 GiB after overlap repairs.
  - status latest rows: 151,495 OK, 0 EMPTY, 0 latest ERROR. Status rows are fewer than parquet
    files because one pre-patch concurrent batch wrote parquet before status append; resume checks
    existing non-empty parquet files too.
  - `stocks_pit_full_5min_fetch.py` was patched to union duplicate symbol/month plan rows,
    support `--force-keys-file`, use thread-specific temp parquet names, and continue on worker
    exceptions.
  - overlap repair: 231/231 duplicate symbol/month keys refetched from
    `STOCKS_PIT_FULL_5MIN_DUPLICATE_MONTHS_2026-09-13.csv`.
  - coverage audit script: `raits/research/stocks_pit_full_5min_coverage_audit.py`.
  - audit outputs prefix: `STOCKS_PIT_FULL_5MIN_COVERAGE_AUDIT_2026-09-13`.
  - audit PASS: 176,028/176,028 files exist and are readable; 0 duplicate timestamps; 0 off-RTH rows;
    0 off-month rows; 0 file failures.
  - audit WARN: 34 eligible symbol-days missing 5m bars after force-refetch, concentrated in
    `WTM` 31 days, `MMM.WD` 1, `NWLI` 1, `TOP` 1. This is 0.0010% of 3,414,774 eligible
    symbol-days and must be reported/skipped explicitly in broad replay.
- Broad PIT no-intraday NOWARMUP replay is DONE:
  - scripts:
    `raits/research/stocks_pit_full_feature_cache_builder.py`,
    `raits/research/stocks_pit_full_no_intraday_replay_nowarmup.py`.
  - feature outputs:
    `raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl`,
    `raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl`,
    `raits/data/cache/stocks_gap_rvol30_features_PIT_FULL_2018_2024_NOWARMUP.pkl`.
  - feature part cache is resumable:
    `raits/data/cache/pit_full_feature_parts_2018_2024_nowarmup/`.
  - feature totals: 278,880,450 5m bars -> 3,158,217 clean daily rows,
    3,083,524 09:35 rows, 3,045,071 gap30 rows.
  - replay outputs prefix: `STOCKS_PIT_FULL_NO_INTRADAY_NOWARMUP_2018_2024`.
  - B nowarmup: PnL $29.361k, CAGR 7.1%, DD -$23.691k, Sharpe 0.271,
    avgGross 0.757x, maxGross 0.962x, trades 46,102.
  - A nowarmup: PnL $30.952k, CAGR 7.4%, DD -$27.503k, Sharpe 0.252,
    avgGross 0.866x, maxGross 1.117x, trades 46,102.
  - B sleeve PnL: broad $16.540k, local $27.111k, yday -$14.290k.
  - PIT gate missing_from_pit is 0 for all sleeves; removals are price/liquidity filters.
  - This is not apples-to-apples with section 6.122 because broad 5m starts in 2018 and lacks
    2016-2017 warmup; first engine date is 2018-03-29.
- Broad PIT yday quality audit and yday-only filtered reruns are DONE:
  - scripts:
    `raits/research/stocks_pit_full_quality_audit_nowarmup.py`,
    `raits/research/stocks_pit_full_yday_quality_variants_nowarmup.py`.
  - outputs prefix:
    `STOCKS_PIT_FULL_QUALITY_AUDIT_NOWARMUP_2026-09-13`,
    `STOCKS_PIT_FULL_YDAY_QUALITY_VARIANTS_NOWARMUP_2026-09-13`.
  - diagnostic: yday all was -$14.290k over 270 trades; `prior_close >= 10` kept 193 trades and
    improved yday to -$3.855k; `vol20 <= 6%` kept 152 trades and improved yday to -$4.888k.
  - actual B portfolio reruns with only yday filtered:
    - base: PnL $29.361k, CAGR 7.1%, DD -$23.691k, Sharpe 0.271.
    - yday price >= 10: PnL $46.127k, CAGR 10.2%, DD -$24.700k, Sharpe 0.416.
    - yday price >= 15: PnL $44.949k, CAGR 10.0%, DD -$24.402k, Sharpe 0.423.
    - yday vol20 <= 6%: PnL $37.031k, CAGR 8.5%, DD -$23.129k, Sharpe 0.403.
  - interpretation: missing quality control is a material part of broad PIT weakness, especially
    yday. Keep `yday prior_close >= 10` and `yday vol20 <= 6%` as broad-PIT challenger variants.
    Do not promote them before warmup-matched replay and ticker fallback audit.
- Broad PIT return-gap attribution is DONE:
  - script: `raits/research/stocks_pit_full_gap_attribution_nowarmup.py`.
  - outputs prefix: `STOCKS_PIT_FULL_GAP_ATTRIBUTION_NOWARMUP_2026-09-13`.
  - B Polygon62 warmup vs broad PIT nowarmup gap is -$77.720k.
  - by sleeve: broad -$14.891k, local -$9.404k, yday -$53.426k.
  - yday alone explains about two-thirds of the collapse.
  - not mainly a missing-Jan-Mar-2018 or missing-full-2016 issue: Polygon62 entries from
    2018-03-29 onward are slightly better than full 2018-2024 ($108.589k vs $107.082k).
  - broad PIT yday is almost entirely new names outside Polygon62: 269/270 trades, -$14.335k.
  - interactive no-yday probe: B PnL $47.950k, CAGR 10.5%, DD -$36.379k, Sharpe 0.496. PnL/Sharpe
    improve, but drawdown worsens badly, so `yday price >= 10` is the cleaner first repair.
- Broad PIT yday redesign sweep is DONE:
  - script: `raits/research/stocks_pit_full_yday_redesign_variants_nowarmup.py`.
  - outputs prefix: `STOCKS_PIT_FULL_YDAY_REDESIGN_VARIANTS_NOWARMUP_2026-09-13`.
  - script is resumable/incremental and skips completed `(variant, portfolio config)` rows.
  - B base: PnL $29.361k, CAGR 7.1%, DD -$23.691k, Sharpe 0.271.
  - B `ret60 <= -20%`: PnL $95.952k, CAGR 17.2%, DD -$35.372k, Sharpe 0.632.
  - B `ret60 <= -20% and price 10-100`: PnL $94.939k, CAGR 17.1%, DD -$42.141k, Sharpe 0.683.
  - B `ret60 <= -20% and price 15-100`: PnL $74.897k, CAGR 14.5%, DD -$29.705k, Sharpe 0.635.
  - B `price 15-100`: PnL $54.052k, CAGR 11.5%, DD -$26.634k, Sharpe 0.485.
  - conclusion: broad PIT yday is better framed as severe selloff/panic bounce (`ret60 <= -20%`),
    not generic gapdown bounce. This is in-sample redesign, not promoted.
- Broad PIT ticker-fallback impact audit is DONE:
  - script: `raits/research/stocks_pit_full_ticker_fallback_impact_nowarmup.py`.
  - outputs prefix: `STOCKS_PIT_FULL_TICKER_FALLBACK_IMPACT_NOWARMUP_2026-09-13`.
  - important distinction: most affected rows still have `pit_gate_mode=exact_ticker`; the problem is
    `liquidity_metric_source=ticker_fallback`, meaning PIT liquidity/prior-close used ticker-level
    fallback rather than clean security-id history.
  - yday fallback exposure:
    - base: 63/270 yday signals.
    - price 15-100: 28/134.
    - ret60 <= -20%: 28/101.
    - ret60 <= -20% and price 15-100: 10/40.
  - B fallback-stripped results:
    - base all rows $29.361k; drop any fallback $29.900k.
    - price 15-100 all rows $54.052k; drop any fallback $33.630k.
    - ret60 <= -20% all rows $95.952k; drop any fallback $72.650k.
    - ret60 <= -20% and price 15-100 all rows $74.897k; drop any fallback $50.182k.
  - conclusion: fallback is not fatal for base, but it materially inflates the attractive yday
    redesign variants. Do not promote them. Prefer fallback-excluded stats or rebuild cleaner
    identity/liquidity for fallback names.
- Yearly attribution and drawdown-by-year filter check is DONE:
  - script: `raits/research/stocks_pit_full_yearly_attribution_nowarmup.py`.
  - outputs prefix: `STOCKS_PIT_FULL_YEARLY_ATTRIBUTION_NOWARMUP_2026-09-13`.
  - `price 15-100, drop fallback` is the cleanest yearly DD reducer but return is weak:
    PnL $33.630k, CAGR 7.9%, DD -$20.828k, Sharpe 0.378.
  - `ret60 <= -20%, drop fallback` is the strongest return repair but worsens yearly DD in several
    years: PnL $72.650k, CAGR 14.2%, DD -$31.592k, Sharpe 0.565.
  - `ret60 <= -20%, price 15-100, drop fallback` is the best balance: PnL $50.182k, CAGR 10.8%,
    DD -$24.761k, Sharpe 0.528, but still not production-quality.
  - 2022 is mostly a broad/local drawdown problem; yday filtering alone cannot fix it.
  - Next cheap check should focus on 2020 crash and 2022 broad/local drawdown, not more yday
    micro-filtering.
- Market-regime overlay for 2020/2022 broad-local drawdown is DONE:
  - script: `raits/research/stocks_pit_full_regime_overlay_nowarmup.py`.
  - outputs prefix: `STOCKS_PIT_FULL_REGIME_OVERLAY_NOWARMUP_2026-09-13`.
  - 2022 base max-DD period 2022-03-29 to 2022-06-16 lined up with SPY proxy -10.3% and broad
    universe equal-weight proxy -12.1%.
  - Balanced yday baseline (`ret60 <= -20%, price 15-100`, drop fallback): PnL $50.182k,
    CAGR 10.8%, DD -$24.761k, Sharpe 0.528.
  - Best tested overlay: skip broad+local entries when broad-universe 20-session return `univ20 < -8%`:
    PnL $42.588k, CAGR 9.5%, DD -$19.490k, Sharpe 0.520.
  - Best specific-sleeve overlay: skip local only when `univ20 < -8%`:
    PnL $46.007k, CAGR 10.1%, DD -$20.568k, Sharpe 0.531.
  - Any-risk-off overlay reduces DD more but cuts too much return.
  - conclusion: regime overlay helps DD but is a return haircut; still not production-quality.

Remaining PIT data steps:

1. Stop broad-PIT micro-optimization unless explicitly requested. The current broad PIT family remains
   WARN/research-only and not production-quality.
2. If continuing this family, pre-register only a tiny set for later warmup replay:
   - balanced yday fallback-excluded;
   - balanced yday fallback-excluded + `univ20 < -8%` broad/local overlay.
3. Later fetch/build 2016-2017 broad warmup only if the user accepts the long runtime.
4. Keep current Polygon-62 candidate numbers labelled as Polygon-62 until broad PIT warmup/replay is resolved.

Best next step:

### Continue broad PIT replay analysis

Use the corrected PIT-filtered universe as the tradability/membership gate:

- `filtered_daily_universe.parquet`
- `eligible_final == true`
- `date`, `ticker`, `security_id`
- Keep joins point-in-time; do not open 2025-2026 OOS.
- Do not use the adjusted-bars liquidity artifact for price-floor checks.
- Do not promote the NOWARMUP broad replay as final candidate stats; it is an important warning
  result, not a warmup-matched replacement for 6.122.

Current fetch resume/check command:

```powershell
python raits\research\stocks_pit_full_5min_fetch.py --dry-run
```

Current coverage audit command:

```powershell
python raits\research\stocks_pit_full_5min_coverage_audit.py --workers 30 --progress-every 20000
```

Keep the candidate family stable until broad PIT replay is ready:

- Lead: `B_polygon62_no_intraday_cap40`.
- Higher-gross ref: `A_polygon62_no_intraday_cap40`.
- Hold5/hold10-vol variants: research-only/risk-shaping.
- Pyramid variants: rejected.
- Intraday-inclusive variants: excluded pending separate audit.
- ML: excluded.

## Prompt For New Session

```text
Bạn đang ở repo D:\raits.

Chỉ làm hướng CỔ PHIẾU. KHÔNG đọc/chạy/sửa các thư mục off-limits:
global_index/**, monitor/**, futures/**, orb_futures/**, nonequity/**, tier2/**, xsect/**, docs/futures/**, scratch/**.
Không delete parquet/cache. Không mở 2025-2026 OOS. Không commit nếu chưa được yêu cầu.

Đọc handoff trước:
STOCKS_HANDOFF_NEXT_SESSION_2026-09-11.md

Report chính:
STOCKS_CODEX_REVIEW_2026-09-07.md

Các mục cần đọc kỹ:
6.101, 6.103, 6.104-6.109, 6.120-6.135.

Current status:
- Latest consolidated candidate ledger is section 6.122, not old 6.101.
- Official research lead: B_polygon62_no_intraday_cap40
  PnL $107.082k, CAGR 17.8%, DD -$14.216k, Sharpe 1.193, maxGross 0.681x, trades 32,767, 2018 -$2.409k, 2022 -$2.327k.
- Higher-gross reference: A_polygon62_no_intraday_cap40
  PnL $132.295k, CAGR 20.3%, DD -$17.863k, Sharpe 1.189, maxGross 0.777x.
- Hold5/hold10-vol variants are research-only/risk-shaping.
- Pyramid variants are rejected.
- ML is headline FAIL/research-only.
- Intraday-inclusive variants look attractive in the warmup rerun but remain excluded pending separate audit.
- PIT data step is complete through full daily universe + corrected unadjusted liquidity filter:
  - tag daily_20180102_20241231_resumable, 1,826/1,826 dates OK through 2024-12-31.
  - daily_universe.parquet has 9,325,051 rows.
  - liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted final eligible rows: 3,414,774.
  - QA PASS on no-future-bars/security-id/price/liquidity/grouped-bars.
  - QA WARN on ambiguous ticker map and ticker fallback usage.
- PIT-gated Polygon-62 replay is done:
  - STOCKS_POLYGON62_PIT_REPLAY_2016WARMUP_2018_2024_SUMMARY.csv.
  - Gate removed 0 entries after security_id alias matching.
  - Lead B result reproduces section 6.122 to rounding precision.
  - This is not a broad survivorship replay; it only proves PIT gate wiring on the existing 62-ticker cache.
- Broad PIT 5m fetch is complete:
  - runtime de-duplicated plan has 176,028 symbol/month chunks across 5,097 symbols.
  - final dry-run says DONE 176,028, PENDING 0.
  - parquet files present: 176,028, about 10.672 GiB.
  - status file raits/data/cache/polygon_5min_pit_full_2018_2024/status.csv has 151,495 latest OK rows, 0 EMPTY, 0 latest ERROR.
  - status rows are fewer than parquet files because one pre-patch concurrent batch wrote parquet files before a Windows file-lock stopped status append; resume treats existing non-empty parquet files as done.
  - fetch script was patched to union duplicate symbol/month rows, support force-key refetch, use thread-specific temp parquet names, and continue on worker exceptions.
- Broad PIT 5m coverage audit is complete:
  - audit outputs prefix: STOCKS_PIT_FULL_5MIN_COVERAGE_AUDIT_2026-09-13.
  - 176,028/176,028 parquet files exist/read OK.
  - total 5m rows: 278,880,450.
  - 0 duplicate timestamps, 0 off-RTH rows, 0 off-month rows, 0 file failures.
  - 34 missing eligible symbol-days remain after force-refetch: WTM 31, MMM.WD 1, NWLI 1, TOP 1.
  - Replay must explicitly skip/report these missing 5m symbol-days.
- Broad PIT no-intraday NOWARMUP replay is complete:
  - outputs prefix: STOCKS_PIT_FULL_NO_INTRADAY_NOWARMUP_2018_2024.
  - B nowarmup: PnL $29.361k, CAGR 7.1%, DD -$23.691k, Sharpe 0.271.
  - A nowarmup: PnL $30.952k, CAGR 7.4%, DD -$27.503k, Sharpe 0.252.
  - B sleeve PnL: broad $16.540k, local $27.111k, yday -$14.290k.
  - Gate missing_from_pit is 0; broad/local/yday removals are due to price/liquidity filters.
  - Not apples-to-apples with 6.122 because no 2016-2017 broad warmup; first engine date is 2018-03-29.
- Broad PIT yday quality audit and yday-only filtered reruns are complete:
  - outputs prefix: STOCKS_PIT_FULL_QUALITY_AUDIT_NOWARMUP_2026-09-13 and STOCKS_PIT_FULL_YDAY_QUALITY_VARIANTS_NOWARMUP_2026-09-13.
  - B base nowarmup: PnL $29.361k, CAGR 7.1%, DD -$23.691k, Sharpe 0.271.
  - B yday price >= 10: PnL $46.127k, CAGR 10.2%, DD -$24.700k, Sharpe 0.416.
  - B yday vol20 <= 6%: PnL $37.031k, CAGR 8.5%, DD -$23.129k, Sharpe 0.403.
  - Keep yday price >= 10 and yday vol20 <= 6% as challenger variants, not promoted candidates.
- Broad PIT return-gap attribution is complete:
  - outputs prefix: STOCKS_PIT_FULL_GAP_ATTRIBUTION_NOWARMUP_2026-09-13.
  - total B gap vs Polygon62 warmup is -$77.720k.
  - sleeve deltas: broad -$14.891k, local -$9.404k, yday -$53.426k.
  - yday is the main collapse; not mainly missing full-year 2016.
  - Polygon62 entries from 2018-03-29 onward are slightly better than full 2018-2024, so no-warmup/start-date does not explain the low broad PIT return.
  - broad PIT yday is 269/270 trades outside Polygon62 and loses -$14.335k.
- Broad PIT yday redesign sweep is complete:
  - outputs prefix: STOCKS_PIT_FULL_YDAY_REDESIGN_VARIANTS_NOWARMUP_2026-09-13.
  - B ret60 <= -20%: PnL $95.952k, CAGR 17.2%, DD -$35.372k, Sharpe 0.632.
  - B ret60 <= -20% and price 15-100: PnL $74.897k, CAGR 14.5%, DD -$29.705k, Sharpe 0.635.
  - These are in-sample redesign hypotheses, not promoted candidates.
- Broad PIT ticker-fallback impact audit is complete:
  - outputs prefix: STOCKS_PIT_FULL_TICKER_FALLBACK_IMPACT_NOWARMUP_2026-09-13.
  - fallback-stripped B ret60 <= -20% drops to about $72.650k-$73.331k.
  - fallback-stripped B ret60 <= -20% and price 15-100 drops to about $50.182k-$51.118k.
  - fallback materially inflates attractive yday redesign variants; do not promote.
- Yearly attribution and drawdown-by-year filter check is complete:
  - outputs prefix: STOCKS_PIT_FULL_YEARLY_ATTRIBUTION_NOWARMUP_2026-09-13.
  - best DD reducer is price 15-100, drop fallback, but return is weak.
  - best balance is ret60 <= -20% and price 15-100, drop fallback: PnL $50.182k, CAGR 10.8%, DD -$24.761k, Sharpe 0.528.
  - 2022 is mostly broad/local drawdown, not yday.
- Market-regime overlay for 2020/2022 broad-local drawdown is complete:
  - outputs prefix: STOCKS_PIT_FULL_REGIME_OVERLAY_NOWARMUP_2026-09-13.
  - best tested overlay on balanced yday: skip broad+local entries when broad-universe 20-session return univ20 < -8%.
  - result: PnL $42.588k, CAGR 9.5%, DD -$19.490k, Sharpe 0.520.
  - helps DD but cuts return; still not production-quality.
- Restricted-62 broad PIT replay and rank-displacement audit are complete:
  - scripts:
    - `raits/research/stocks_pit_full_restricted62_nowarmup.py`.
    - `raits/research/stocks_pit_full_restricted62_rank_displacement_nowarmup.py`.
  - outputs prefix:
    - `STOCKS_PIT_FULL_RESTRICTED62_NOWARMUP_2026-09-13`.
    - `STOCKS_PIT_FULL_RESTRICTED62_RANK_DISPLACEMENT_NOWARMUP_2026-09-13`.
  - restricted-to-62 PIT nowarmup B: PnL $91.363k, CAGR 16.6%, DD -$13.834k, Sharpe 1.141, trades 31,324, 2023 $26.095k, 2024 $22.868k.
  - full broad PIT nowarmup B was only PnL $29.361k, CAGR 7.1%, DD -$23.691k, Sharpe 0.271.
  - interpretation: the broad PIT underperformance is mainly universe competition/rank displacement, not a fatal PIT join or engine bug.
  - rank audit:
    - broad restricted-62 picks are often rank 51-500 in the full universe; in 2023-2024, 3,238 of 4,283 restricted-62 broad picks rank 51-500.
    - local restricted-62 picks are almost all displaced by the full universe; in 2023-2024, only 26 of 4,780 remain top-10.
    - yday rolling3 overlap is almost zero; 127 restricted-62 picks over 2018-2024 overlap full broad PIT yday only once, and overlap is zero in 2023-2024.
  - conclusion: the old 62-stock universe acted like an implicit quality/mega-cap/liquidity filter. Do not promote restricted-62; use it only as the diagnostic explaining why full broad does not match Polygon-62.
- Causal quality-universe gate test is complete:
  - script: `raits/research/stocks_pit_full_quality_universe_gate_nowarmup.py`.
  - outputs prefix: `STOCKS_PIT_FULL_QUALITY_UNIVERSE_GATE_NOWARMUP_2026-09-13`.
  - gates tested: price/ADV/no-fallback/volatility thresholds and daily top100/top200/top500 by trailing ADV20.
  - best tested gate: `q_top200adv_p10_nofb`, PnL $33.825k, CAGR 7.9%, DD -$31.167k, Sharpe 0.310, 2023 $11.748k, 2024 $18.833k.
  - base full PIT in the same script: PnL $29.368k, CAGR 7.1%, DD -$23.691k, Sharpe 0.271.
  - conclusion: simple causal quality gates do not recover restricted-62 ($91.363k) and top-ADV worsens 2022 DD. Price/liquidity alone is not the missing ingredient.
  - likely missing ingredient is true historical large-cap/index-membership/market-cap quality, sector mix, or another curation/survivorship effect.
- Reverse-profile quality gate from Polygon-62 is complete:
  - script: `raits/research/stocks_pit_full_quality_universe_gate_nowarmup.py`.
  - outputs prefix: `STOCKS_PIT_FULL_QUALITY_UNIVERSE_GATE_NOWARMUP_2026-09-13`.
  - variants added:
    - `profile62_train_q10`;
    - `profile62_train_q25`;
    - `profile62_score_top100`;
    - `profile62_score_top200`.
  - profile uses 2018-2020 Polygon-62 proxy profile: daily ADV percentile, prior-close percentile, vol20 percentile, age/history coverage, and no ticker-fallback rows.
  - best diagnostic: `profile62_score_top100`, PnL $55.055k, CAGR 11.6%, DD -$11.184k, Sharpe 0.860, 2023 $9.081k, 2024 $9.444k.
  - `profile62_train_q25`: PnL $52.655k, CAGR 11.2%, DD -$16.468k, Sharpe 0.846.
  - interpretation: the user's reverse-filter intuition was right. Price/ADV alone failed, but a learned 62-like profile materially improves broad PIT versus base full PIT ($29.368k, Sharpe 0.271).
  - caveat: reverse profile is diagnostic/WARN, not production PASS, because it learns from the old 62 universe and still lacks real sector/index/market-cap history.
- Profile62 selection audit is complete:
  - script: `raits/research/stocks_pit_full_profile62_selection_audit_nowarmup.py`.
  - outputs prefix: `STOCKS_PIT_FULL_PROFILE62_SELECTION_AUDIT_NOWARMUP_2026-09-14`.
  - answer to "why 2023-2024 still does not recover 62":
    - local is mostly recovered: in 2023-2024, 1,535 restricted-62 local picks are rank 1-10 inside the profile universe and all are selected; overlap PnL $5.937k.
    - broad is only partly recovered: 2,566 restricted-62 broad picks are allowed by profile in 2023-2024, but only 479 overlap profile-selected broad candidates due active position/ticker-cap/capacity mechanics.
    - yday is still weak: 69 restricted-62 rolling3 yday picks in 2023-2024, only 6 overlap profile-selected yday; those 6 make $4.756k, while 13 profile yday replacements lose -$2.124k.
  - conclusion: profile gate improves universe, but it does not recreate exact Polygon-62 broad/yday rule path. Missing 2023-2024 PnL is mainly exact old broad/yday winners and weaker replacements.
- Recreate-selection-path audit is complete:
  - scripts:
    - `raits/research/stocks_pit_full_quality_universe_gate_nowarmup.py`.
    - `raits/research/stocks_pit_full_profile62_yday_path_audit_nowarmup.py`.
    - `raits/research/stocks_pit_full_profile62_frozen_yday_engine_nowarmup.py`.
  - outputs:
    - `STOCKS_PIT_FULL_PROFILE62_YDAY_PATH_AUDIT_NOWARMUP_2026-09-14_*`.
    - `STOCKS_PIT_FULL_PROFILE62_FROZEN_YDAY_ENGINE_NOWARMUP_2026-09-14_*`.
  - narrowing reverse-profile universe does not recover the path:
    - `profile62_score_top50`: PnL $51.379k, DD -$13.743k, Sharpe 0.780, 2023 $11.111k, 2024 $7.975k.
    - `profile62_score_top62`: PnL $48.266k, DD -$15.079k, Sharpe 0.748.
    - `profile62_score_top75`: PnL $49.021k, DD -$14.282k, Sharpe 0.743.
  - freezing yday to restricted-62 inferred rules helps but still does not recover:
    - `profile62_score_top100` + frozen yday rules: PnL $57.114k, CAGR 11.9%, DD -$11.907k, Sharpe 0.935, 2023 $14.756k, 2024 $9.629k.
    - `profile62_train_q25` + frozen yday rules: PnL $59.118k, CAGR 12.2%, DD -$13.854k, Sharpe 1.041, 2023 $14.487k, 2024 $14.361k.
  - exact restricted-to-62 remains much higher: PnL $91.363k, 2023 $26.095k, 2024 $22.868k.
  - conclusion: exact path cannot be recreated from current local proxy fields alone. Need actual 62 membership, or true historical index/large-cap/market-cap/sector membership data.
- Exact restricted-62 selection path trace is complete:
  - script: `raits/research/stocks_pit_full_restricted62_exact_path_trace_nowarmup.py`.
  - outputs prefix: `STOCKS_PIT_FULL_RESTRICTED62_EXACT_PATH_TRACE_NOWARMUP_2026-09-14`.
  - trace file includes each restricted-62 trade's date/ticker/sleeve/PnL, selection rule text, restricted/full/profile rank, and full/profile selected flags.
  - 2023-2024 summary:
    - broad: 4,283 restricted trades, $13.610k PnL, 434 full overlap, 479 profile overlap, median full rank 94, median profile rank 34.
    - local: 4,780 restricted trades, $18.553k PnL, 26 full overlap, 1,535 profile overlap, median full rank 267, median profile rank 9.
    - yday: 69 restricted trades, $13.332k PnL, 0 full overlap, 6 profile overlap.
  - top missing 2023-2024 winners are mostly yday `gapdown_-4`: TSLA 2024-07-12 +$2.680k, ORCL 2023-06-14 +$1.951k, MU 2024-08-05 +$1.887k, TSLA 2024-06-17 +$1.767k, NVDA 2024-08-02 +$1.720k.
- Market-cap fetch and replay are complete through report section 6.144:
  - market-cap field audit script: `raits/research/stocks_polygon_market_cap_field_audit.py`.
  - resumable fetcher: `raits/research/stocks_polygon_market_cap_snapshot_fetch.py`.
  - fetched output: `raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv`.
  - fetch scope: quarterly first PIT trading day, local PIT eligible universe, 2018-01-02 through 2024-10-01.
  - fetch rows: 55,612; HTTP 200 rows: 55,611; rows with market cap: 52,332.
  - replay script: `raits/research/stocks_pit_full_market_cap_universe_replay_nowarmup.py`.
  - replay outputs prefix: `STOCKS_PIT_FULL_MARKET_CAP_UNIVERSE_NOWARMUP_2026-09-14`.
  - market-cap top62: PnL $52.821k, CAGR 11.3%, DD -$18.694k, Sharpe 0.762, 2023 $7.773k, 2024 $19.485k.
  - market-cap top100: PnL $55.148k, CAGR 11.6%, DD -$16.619k, Sharpe 0.775, 2023 $14.760k, 2024 $13.517k.
  - market-cap top200: PnL $45.637k, CAGR 10.1%, DD -$23.847k, Sharpe 0.592.
  - market-cap top500: PnL $34.438k, CAGR 8.1%, DD -$21.217k, Sharpe 0.440.
  - interpretation: market-cap rank improves broad PIT but does not recreate restricted-62; old 62-name edge is not just top market cap.
- Polygon-62 universe provenance is traced through report section 6.145:
  - `stocks_polygon_fetch_5min_2018_2024_62.py` reads symbols from `stocks_intraday_0935_features_CAUSEQA_2026-09-10.pkl`.
  - `stocks_feature_cache_builder.py` built that cache from `raits/data/cache/window_debug_5min.pkl`.
  - `window_debug_5min.pkl` matches exactly the static `TICKERS` list in `raits/raits/scripts/window_debug.py`.
  - Exact rule:
    `["SPY","QQQ","IWM"] + SECTOR_ETFS + UNIVERSE + PHASE1 + PHASE2 + PE_EXPANSION`.
  - Exact equity breakdown:
    - original fixed universe, 8: TSLA, NVDA, AAPL, META, AMZN, MSFT, AMD, GOOGL.
    - Phase 1, 20: INTU, COST, VRTX, AMAT, REGN, AVGO, ADBE, MS, SBUX, TXN, XOM, AMGN, ORCL, EBAY, QCOM, CVX, CSCO, GS, CRM, JPM.
    - Phase 2, 9: MU, HON, MA, NFLX, INTC, V, GILD, BIIB, MMM.
    - PE_SHORT expansion, 25: PFE, MRK, LLY, ABBV, JNJ, BMY, BAC, WFC, C, WMT, TGT, HD, LOW, MCD, NKE, PG, KO, PEP, CAT, DE, BA, GE, PYPL, PANW, NOW.
  - Interpretation: 62 equities are not top market cap/top sector/index-membership rule. They are a staged/manual research universe with explicit curation risk.

Your task:
1. Continue from current state, do not restart analysis from scratch.
2. Recommended next step is stop broad-PIT micro-optimization unless explicitly requested; current broad PIT family is WARN/research-only.
3. Do not spend more time on simple price/ADV/volatility gates; they failed to recover the edge.
4. If continuing this family, freeze `profile62_score_top100` and `profile62_train_q25_frozen_yday_rules` as diagnostic hypotheses only.
   Next real step requires true historical large-cap/index/market-cap data, or explicitly define the 62 tickers as a manual product universe.
5. If testing variants, pre-register only balanced yday fallback-excluded, balanced yday fallback-excluded + univ20 < -8% overlay, and the reverse-profile quality gate family.
6. Do not promote any candidate until warmup-matched broad PIT replay stats are available.

Deliverables:
- Broad PIT 5-minute coverage status.
- Broad PIT replay status and candidate ledger delta versus section 6.122.
- Restricted-62 diagnostic status and rank-displacement explanation.
- Replay join/coverage QA.
- Ambiguous ticker/fallback impact audit.
- Explicit caveat if any candidates are still measured on Polygon-62 rather than broad PIT-filtered data.
```

## Deprecated Prompt For New Session

Paste this into a new session:

```text
Bạn đang ở repo D:\raits.

Chỉ làm hướng CỔ PHIẾU. KHÔNG đọc/chạy/sửa các thư mục futures/non-equity/off-limits:
global_index/**, monitor/**, futures/**, orb_futures/**, nonequity/**, tier2/**, xsect/**, docs/futures/**, scratch/**.
Không delete parquet/cache. Không mở 2025-2026 OOS. Không commit nếu chưa được yêu cầu.

Đọc handoff trước:
STOCKS_HANDOFF_NEXT_SESSION_2026-09-11.md

Report chính:
STOCKS_CODEX_REVIEW_2026-09-07.md

Các mục cần đọc kỹ trong report:
6.91, 6.92, 6.93, 6.94, 6.95, 6.96, 6.97, 6.98, 6.99, 6.100, 6.101.

Current status:
- Official lead: B_polygon62_no_intraday_cap40
  PnL $109.480k, CAGR 19.0%, DD -$15.439k, Sharpe 1.256, maxGross 0.677x, trades 31,193, 2022 -$2.617k.
- Higher-gross reference: A_polygon62_no_intraday_cap40
  PnL $135.817k, CAGR 21.7%, DD -$19.444k, Sharpe 1.251, maxGross 0.773x.
- Hold5-vol20 variant is research-only:
  B hold5 engine sizing PnL $116.977k, Sharpe 1.280, 2022 +$0.094k, but fair-sizing showed the PnL gain is mostly from higher local notional due to engine sizing by sleeve_gross / hold.
- ML is headline FAIL/research-only.
- intraday_ex10 is FAIL for Polygon-62 2018-2024 and excluded from lead.

Your task:
1. Continue from current state, do not restart analysis from scratch.
2. Recommended next step is to add/fetch 2016-2017 Polygon warmup so 2018 can be scored as a full calendar year.
3. Keep existing 2018-2024 outputs untouched; write separate warmup-labeled outputs.
4. Rerun the no-ML/no-intraday A/B base and, optionally, the hold-vol fair-sizing variants on the 2016 warmup -> 2018-2024 scoring window.
5. Document results in the main report as the next section after 6.101.

Deliverables:
- Clear stats for A/B base with full-year 2018.
- Whether the 2018 negative year changes after warmup.
- Whether current lead B remains lead.
- Explicit caveat that this is still current-survivor Polygon-62, not survivorship-aware.
```
