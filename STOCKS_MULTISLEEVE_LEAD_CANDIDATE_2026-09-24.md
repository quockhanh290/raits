# Stocks Multi-Sleeve Lead Candidate - 2026-09-24

## Status

**Lead:** 75% `sic_pairs_quarterly_z2_hold10` plus 25% `spy_first5_x25_fin25_cost4`, run at 1.0x.

**Verdict:** keep 1.0x as a frozen forward benchmark only; kill the 1.5x challenger; not a production PASS.

This lead was selected by the final cost-aware four-sleeve development grid in report section 6.215. It is
not based on the old manual/restricted 62, and 2025-2026 was not used for selection. That later interval has
now been consumed as a touched implementation replay and cannot be called future clean OOS again.

## Data Contract

- Development: 2018-04-27 through 2022-12-30.
- Touched validation: 2023-01-03 through 2024-12-31. This is not clean unseen OOS.
- Full descriptive path: 2018-04-27 through 2024-12-31, 1,681 union-calendar sessions.
- Pairs use broad-PIT features, quarterly rolling same-SIC formation, z-score 2 entry, and maximum 10-session hold.
- Calendar sleeve holds 2.5x SPY on the first five trading sessions of each month and zero otherwise.
- Shared-book costs: 4 bps aggregate target-weight turnover, 1% annual short borrow, and 2.5% annual financing
  on additive gross above 1x. No cross-sleeve netting benefit is credited.
- Missing source date: zero exposure/return for that source on the union calendar. Source-level missing-price
  behavior remains inherited from each original replay.

## Results

| period | CAGR | PnL | Sharpe | DD $ / % | positive years | avg / max gross |
|---|---:|---:|---:|---:|---:|---:|
| 2018-22 development | 10.20% | `$57.478k` | 1.411 | `-$12.607k` / -7.50% | 4/5 | 0.78x / 1.38x |
| 2023-24 touched validation | 5.36% | `$10.974k` | 1.029 | `-$9.333k` / -8.03% | 2/2 | 0.89x / 1.38x |
| full touched 2018-24 | 8.72% | `$74.760k` | 1.309 | `-$14.698k` / -8.03% | 6/7 | 0.82x / 1.38x |

Full-path yearly PnL: 2018 `$2.803k`; 2019 `$5.031k`; 2020 `$31.553k`; 2021 `$19.405k`;
2022 `-$1.314k`; 2023 `$13.226k`; 2024 `$4.057k`.

Full-path gross source attribution is `$42.080k` pairs and `$51.943k` SPY calendar. Shared trading, borrow,
and financing costs remove `$14.059k`, `$3.264k`, and `$1.940k` respectively.

## Concentration And Risk

- SPY contributes 65.66% of full-path net PnL and 71.27% of touched-validation PnL.
- Effective positive-PnL ticker count is 16.54 over the full path.
- Full-path top1/top3/top5/top10 net-PnL shares are 65.66%/78.26%/86.99%/105.51%. The top10 share exceeds
  100% because winning names offset losing pair names.
- 2020 contributes 42.2% of full-path net PnL. 2022 remains negative.
- Scaling is not the lead: the same portfolio at 1.5x has 12.63% full CAGR and -11.94% DD; at 2.0x it has
  16.06% CAGR, -15.80% DD, `$47.310k` dollar DD, and 72.27% SPY PnL share.

## Audit Gaps

- The family and 2023-2024 are heavily touched; no claim of clean OOS robustness is allowed.
- Pair ticker cost reversal and shared-cost allocation reconcile exactly at portfolio level but are diagnostic
  allocations because the source ledger does not persist every daily position weight.
- Exact pair daily holdings, shared single-name caps, PIT ADV sizing, cross-sleeve collision netting, and a
  strict missing-price replay remain required before production.
- Static-weight combination mining is closed by section 6.215's stopping rule. A new candidate must change
  portfolio construction or introduce genuinely new edge, not refine these weights again.

## Reproduction

- Report: `STOCKS_CODEX_REVIEW_2026-09-07.md`, sections 6.214-6.215.
- Preregistration: `STOCKS_FINAL_COSTAWARE_FOUR_SLEEVE_GRID_PREREG_2026-09-24.json`, SHA256
  `E5EAA99B39D296732439F9D0FBF5BFEA4AD2CCB2643F7823514EB2A1A1F08805`.
- Script: `raits/research/stocks_final_costaware_four_sleeve_grid.py`, SHA256
  `849FA4DFA495EBBAAC1B9870D86786C760FB202869CC76CF4CF5C605D967E62D`.
- Selected output prefix: `STOCKS_FINAL_COSTAWARE_FOUR_SLEEVE_GRID_2026-09-24_`.
- Selection: `pairs=0.750|calendar=0.250`; 1.0x is the lead paper scale.
- No 2025-2026 input was consumed. No production PASS is permitted from these artifacts.

## Forward Paper Implementation

The frozen harness is implemented and post-2024 use was explicitly approved. Data through 2026-09-16 was
then consumed as a **touched implementation replay**, not genuine forward paper: the protocol was frozen on
2026-09-24. Genuine forward sessions and PnL therefore remain zero; the first eligible forward observation
is the first market session strictly after 2026-09-24.

The corrected 2025-01-02 through 2026-09-16 replay produced:

| account | CAGR | PnL | DD $ / % | max gross | status |
|---|---:|---:|---:|---:|---|
| 1.0x primary | 2.39% | `$4.107k` | `-$10.254k` / -10.14% | 1.390x | active |
| 1.5x challenger | -6.51% | `-$10.829k` | `-$15.245k` / -15.01% | 2.079x | halted 2025-04-07 |

For 1.0x, 2025 lost `$3.404k`: SPY first-five lost `$5.800k`, partly offset by pairs at `+$2.397k`.
Through 2026-09-16 it recovered `+$7.511k`: pairs `+$4.654k`, SPY `+$2.856k`. Full-replay positive-PnL
concentration is top1/top3/top5/top10 6.49%/17.96%/25.27%/36.16%, with effective positive ticker count
44.70. Net-PnL shares are 68.72%/190.04%/267.45%/382.66% because losers offset most gross winners.

The first post-2024 run was invalidated when its market packet stopped carrying BRK.A after a missing exact
bar even though the runner still held a residual. All 15 original artifacts are preserved under the
`STOCKS_MULTISLEEVE_POST2024_IMPLEMENTATION_REPLAY_INVALID_INPUT_COVERAGE_` prefix. The builder now emits
exact-clock marks for every potential constituent at every session. The corrected replay has zero hard
execution violations; event reconciliation is zero, ticker reconciliation is below `3.3e-10`, and maximum
balance-sheet error is below `2.91e-11`. Its borrow flag is still assumed true, so this is not production
evidence.

Protocol: `STOCKS_MULTISLEEVE_FORWARD_PAPER_PROTOCOL_2026-09-24.json`. Runner:
`raits/research/stocks_multisleeve_forward_paper.py`. Post-2024 builder:
`raits/research/stocks_multisleeve_post2024_target_builder.py`. Audit:
`raits/research/stocks_multisleeve_post2024_replay_audit.py`. Current state and hashes are recorded in
`STOCKS_MULTISLEEVE_FORWARD_PAPER_STATUS_2026-09-24.json`.
