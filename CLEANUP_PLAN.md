# RAITS Cleanup Plan — Pre-Deploy Classification
_Generated: 2026-07-01_
_Status: AWAITING APPROVAL — no files moved yet_

---

## TABLE 2: Canonical vs Stale/Copy/Duplicate

> Đây là deliverable quan trọng nhất — nguồn gốc "không biết bản nào final"

### Case 1 — `configs/final_params.yaml` (GIÁ TRỊ KHÁC NHAU ⚠️)

| File | Values | Status |
|---|---|---|
| `d:\raits\configs\final_params.yaml` | orb=**15**, bb=**2.5**, ema=30 | 🔴 **STALE** — old per_strategy_diagnostic params. Không có script production nào đọc file này. |
| `d:\raits\raits\configs\final_params.yaml` | orb=**20**, bb=**1.5**, ema=30 | ✅ **CANONICAL** — locked Vault params. Đọc bởi: `wfo.py`, `vault_test.py`, `window_debug.py`, `verify_context.py`, `verify_parallel_run.py`, `diagnose_parallel_run.py`, `diagnose_first_divergence.py`. Tất cả dùng path relative `_SCRIPTS_DIR/../../configs/` → resolve đúng về `raits/raits/configs/`. |

### Case 2 — `_validated_core.py` copies

| File | Status | Note |
|---|---|---|
| `futures/_validated_core.py` | ✅ **CANONICAL** | Source of truth. Chứa toàn bộ logic: `load_parquet`, `atr14`, `resample_5m`, `Trade`, `FuturesCost`, `backtest_swing_tf`, `StressMidAdapter`, `benchmark_daily`, `label_regimes`. |
| `global_index/_core.py` | **INTENTIONAL COPY** | Verbatim copy của primitives (không có backtest_swing_tf/StressMidAdapter). Canonical cho global_index/ vì package phải standalone. Imported bởi 12+ global_index modules. |
| `nonequity/_core.py` | **INTENTIONAL COPY** | Verbatim copy + FuturesCost + `daily_bars()`. Canonical cho nonequity/. |

> ⚠️ Nếu `futures/_validated_core.py` thay đổi → phải sync thủ công `global_index/_core.py` và `nonequity/_core.py` rồi re-run reconcile harnesses.

### Case 3 — `models/hmm/` (hai thư mục)

| Path | Files | Status |
|---|---|---|
| `d:\raits\raits\models\hmm\` | 55,730 pkl | ✅ **CANONICAL** — scripts chạy từ `d:\raits\raits\` (per CLAUDE.md), relative path `models/hmm` resolve về đây. |
| `d:\raits\models\hmm\` | 38,412 pkl | 🟡 **STALE/ORPHAN** — từ phase trước khi scripts chạy từ repo root. |

> Không đề xuất xóa data. Chỉ ghi nhận để tránh nhầm bộ nào production.

### Case 4 — `orb.py` (hai bản)

| File | Status | Evidence |
|---|---|---|
| `d:\raits\raits\strategies\orb.py` | ✅ **CANONICAL** | Có FADE params + `pending_breakouts`. Imported bởi engine.py, tests, root scripts. |
| `d:\raits\raits\raits\strategies\strategies\orb.py` | 🔴 **DEAD** | Bản cũ, thiếu FADE params. `min_gap_pct=0.02`, `max_price=200`. Không có gì import. |

### Case 5 — `swing_tf_harness.py` (hai bản — coexist intentionally)

| File | Status | Evidence |
|---|---|---|
| `d:\raits\swing_tf_harness.py` | ✅ **CANONICAL cho pool scripts** | Imported bởi `gate4_wfo.py`, `pooled_swing_wfo.py`, `pooled_swing_vault.py`. Không có `return_open` param. |
| `d:\raits\futures\swing_tf_harness.py` | ✅ **CANONICAL cho futures** | Có `return_open` param. Source reference cho `futures/_validated_core.py`. Hai bản coexist intentionally. |

### Case 6 — `fetch_es_continuous.py` (hai bản)

| File | Status | Evidence |
|---|---|---|
| `d:\raits\fetch_es_continuous.py` | ✅ **CANONICAL** | 299 lines — Databento spike thực sự. Được root script docstrings reference. |
| `d:\raits\futures\fetch_es_continuous.py` | 🔴 **DEAD** | 16 lines — chỉ có package docstring + 2 import lines. Không phải fetch script. Tạo nhầm. |

### Case 7 — `global_index/edge_test.py` vs `orb_futures/edge_test.py`

| File | Status | Evidence |
|---|---|---|
| `d:\raits\orb_futures\edge_test.py` | ✅ **CANONICAL** | Docstring đúng, `groupby` loop hiện đại. Đúng package. |
| `d:\raits\global_index\edge_test.py` | 🔴 **STALE COPY** | Docstring vẫn ghi `orb_futures/edge_test.py` (sai vị trí). Implementation cũ hơn. Không có gì trong global_index production import nó. |

### Case 8 — `swing_tf_powerhour.py` (hai bản)

| File | Status | Evidence |
|---|---|---|
| `d:\raits\nonequity\swing_tf_powerhour.py` | ✅ **CANONICAL** | Import từ `nonequity._core`, `nonequity.specs`. Đúng package. |
| `d:\raits\global_index\swing_tf_powerhour.py` | 🔴 **STALE COPY** | Prototype trước khi nonequity/ được setup. Import từ `global_index._core`. Không được import bởi bất kỳ global_index production module nào. |

### Case 9 — `global_index/fetch.py` vs `nonequity/fetch.py`

| File | Status | Evidence |
|---|---|---|
| `d:\raits\global_index\fetch.py` | ✅ **CANONICAL** | Imported bởi `tier2/fetch.py`. |
| `d:\raits\nonequity\fetch.py` | **INTENTIONAL COPY** | Byte-identical. Dùng standalone qua `python -m nonequity.fetch`. |

---

## TABLE 1: Phân loại toàn bộ file .py

### PRODUCTION — GIỮ NGUYÊN VỊ TRÍ (deploy path)

| File | Reason |
|---|---|
| `futures/__init__.py` | Package entry |
| `futures/_validated_core.py` | Source of truth: label_regimes + backtest_swing_tf |
| `futures/basket.py` | Rổ 4 contract specs + frozen params + RISK config |
| `futures/cost.py` | FuturesCost |
| `futures/swing_tf.py` | SwingTFEngine production class |
| `futures/stress_mid.py` | StressMidEngine production class |
| `futures/sizer.py` | Portfolio sizer |
| `futures/net_exposure.py` | NetExposureGuard |
| `futures/circuit_breaker.py` | Portfolio circuit breaker |
| `futures/runner.py` | Live orchestration (IBKR stubs) |
| `global_index/__init__.py` | Package entry |
| `global_index/_core.py` | Verbatim copy của primitives — canonical cho global_index |
| `global_index/specs.py` | NKD/MNKD contract specs |
| `global_index/regime.py` | SPY-HMM lookahead-safe regime. Imports `futures._validated_core` |
| `global_index/net_exposure_multi.py` | N-cluster exposure guard |
| `global_index/deploy_sim.py` | Deploy-realistic backtest — main entry point |
| `global_index/fetch.py` | Databento fetch. Imported bởi `tier2/fetch.py` |
| `raits/hmm/__init__.py` | Exports HMMEngine — imported bởi futures/_validated_core |
| `raits/hmm/engine.py` | HMMEngine — core của futures deploy path |
| `raits/hmm/features.py` | Feature matrix builder |
| `raits/hmm/state_sorting.py` | Label-switching safeguard |
| `raits/hmm/retraining.py` | Weekly retraining scheduler |
| `raits/hmm/volatility_override.py` | Real-time crash detection |
| `raits/strategies/trend_follow.py` | TrendFollowStrategy — imported bởi `futures/_validated_core.py` |

### STOCK-ENGINE — GIỮ NGUYÊN (equity engine, preserved)

`raits/backtest/`: `engine.py`, `engine_refactored.py`, `wfo.py`, `wfo_grid.py`, `data_types.py`, `metrics.py`, `equity_tracker.py`, `trade_log.py`, `orb_session.py`, `reject_funnel.py`, `__init__.py`

`raits/coordinator/`: `regime_coordinator.py`, `strategy_router.py`, `conflict_resolver.py`, `__init__.py`

`raits/decision/`: `decision_unit.py`, `types.py`, `__init__.py`

`raits/live/`: `broker.py`, `context_feed.py`, `runner.py`, `reconciliation.py`, `verify_context.py` *(M in git)*, `verify_live_path.py`, `__init__.py`

`raits/risk/`: `circuit_breakers.py`, `pdt_guard.py`, `portfolio.py`, `position_sizer.py`, `__init__.py`

`raits/data/`: `raits_polygon_fetcher.py`, `raits_data_cache.py`, `raits_data_models.py`, `raits_data_pipeline.py`, `raits_data_validator.py`, `raits_mock_data.py`, `raits_premarket.py`, `__init__.py`

`raits/strategies/`: `orb.py`, `vwap_mr.py`, `cash_defense.py`, `universe_scanner.py`, `__init__.py`

`raits/utils/__init__.py`, `raits/__init__.py`, `raits/costs.py`, `raits/data_cache.py`

`tests/` (root): tất cả coordinator/, integration/, risk/, fixtures/, test_*.py

`raits/tests/`: tất cả decision/, live/, fixtures/, unit/, test_*.py

### HARNESS — GIỮ NGUYÊN (proof artifacts + ops tooling)

| File | Reason |
|---|---|
| `gate2_edge_harness.py` | **⚠️ Source of truth** cho futures/_validated_core.py (được trích xuất từ đây) |
| `gate3_alpha_beta.py` | Alpha/beta proof artifact |
| `gate4_wfo.py` | Single-instrument WFO proof |
| `gate5_vault.py` | Single-instrument vault proof |
| `swing_tf_harness.py` (root) | Imported bởi gate4, pooled_swing_wfo, pooled_swing_vault |
| `pooled_swing_wfo.py` | Produced frozen param (ema=30, chandelier=2.5) |
| `pooled_swing_vault.py` | Basket vault proof |
| `pooled_basket_verify.py` | STRESS_MID basket robustness |
| `pooled_vault.py` | STRESS_MID basket vault |
| `fetch_es_continuous.py` (root) | Databento data spike, 299 lines |
| `debug_vault_labels.py` | Vault label alignment diagnostic |
| `mean_reversion_explore.py` | MR proof-of-rejection artifact |
| `overnight_explore.py` | Overnight proof-of-rejection artifact |
| `tf_index_proxy_test.py` | SPY/QQQ proxy screen |
| `tf_rewfo_qqq.py` | QQQ re-WFO |
| `futures/reconcile_gd0.py` | Proves SwingTFEngine == validated harness |
| `futures/reconcile_stress.py` | Proves StressMidEngine entry == adapter |
| `futures/backtest_combined.py` | Documents combined P&L before risk layer |
| `futures/backtest_system.py` | Documents risk-layer impact |
| `futures/swing_tf_harness.py` | Newer version với `return_open` param |
| `global_index/combined.py` | Gate: NKD improves Rổ 4? |
| `global_index/combined_system.py` | Full risk-layer NKD + Rổ 4 replay |
| `global_index/wfo.py` | Global index WFO |
| `global_index/vault.py` | Global index vault |
| `global_index/cap_sweep.py` | Exposure cap sweep |
| `global_index/priority_sweep.py` | Entry priority rules test |
| `global_index/risk_diagnostic.py` | Per-position risk$ diagnosis |
| `global_index/reject_diagnostic.py` | Rejection pattern analysis |
| `global_index/reject_value_diagnostic.py` | Rejection quality analysis |
| `global_index/hold_vs_entry_diagnostic.py` | Entry-race vs hold-time diagnosis |
| `raits/raits/scripts/vault_test.py` | ONE-SHOT equity vault (2023-2024 OOS) |
| `raits/raits/scripts/wfo_real_run.py` | Full 10-year WFO |
| `raits/raits/scripts/window_debug.py` | Per-window diagnostic — key ops tool |
| `raits/raits/scripts/per_strategy_diagnostic.py` | Per-strategy attribution |
| `raits/raits/scripts/verify_parallel_run.py` | Proves engine == refactored (604 trades, $0 diff) |
| `raits/raits/scripts/diagnose_parallel_run.py` | Parallel-run diagnosis |
| `raits/raits/scripts/diagnose_first_divergence.py` | First divergence finder |
| `raits/raits/scripts/hmm_regime_diagnostic.py` | HMM vs threshold comparison |
| `raits/raits/scripts/hmm_state_diagnostic.py` | HMM state structure analysis |
| `raits/raits/scripts/fetch_daily_data.py` | Fetches T-1 daily bars |
| `raits/raits/scripts/fetch_oos_data.py` | Fetches 2023-2024 OOS data |
| `raits/raits/scripts/fetch_vix_daily.py` | Data utility |
| `raits/raits/scripts/fetch_spy_historical.py` | Data utility |
| `raits/raits/scripts/fetch_lowbeta_5min.py` | Data utility |
| `raits/raits/scripts/fetch_new_stocks.py` | Data utility |
| `raits/raits/scripts/fetch_2025_data.py` | Data utility |
| `raits/raits/scripts/fetch_is_earnings.py` | Data utility |
| `raits/raits/scripts/system_summary.py` | System-level summary |
| `raits/raits/scripts/snapshot_summary.py` | Snapshot summary |
| `raits/raits/scripts/read_baseline.py` | Reads baseline snapshot |
| `raits/raits/scripts/current_status.py` | Current system status |
| `raits/raits/scripts/all_years_diff.py` | Year-by-year diff |
| `raits/raits/scripts/load_all_snapshots.py` | Loads all snapshots |
| `raits/raits/scripts/vault_metrics.py` | Vault metrics extraction |

### EXPERIMENTAL — GIỮ NGUYÊN (falsification records có giá trị)

`orb_futures/`: `_orb_core.py`, `edge_test.py`, `gap_fill.py`, `overnight.py`, `__init__.py`

`tier2/`: `fetch.py`, `structure_test.py`, `__init__.py`

`xsect/`: `momentum_structure.py`, `__init__.py`

`nonequity/`: `_core.py`, `fetch.py`, `specs.py`, `swing_tf_daily.py`, `swing_tf_powerhour.py`, `mr_explore.py`, `__init__.py`

`raits/raits/scripts/` — tất cả strategy exploration scripts (~70 files):
- `fade_*.py` (~15 files) — FADE analysis
- `gap_fill_*.py` (~12 files) — GAP_FILL analysis
- `rs_*.py` (~9 files) — RS Momentum analysis
- `stress_orb_*.py` (~8 files) — STRESS_ORB_STK analysis
- `stress_mid_*.py` (3 files) — STRESS_MID analysis
- `vmr_*.py` / `vwap_mr_*.py` (~8 files) — VWAP_MR analysis
- `orb_*.py` (~10 files) — ORB variant analysis
- `midday_*.py` (~7 files) — Midday exploration
- `morning_*.py`, `post_earnings_*.py`, `sector_divergence_sim.py` — Strategy sims
- `momentum_cont_test.py`, `irb_test.py`, `failed_breakout_fade_test.py` — Edge tests
- `gf_*.py`, `pf_analysis.py`, `vix_regime_sim.py`, `trend_blindness_diagnostic.py` — Diagnostics
- `bull_calm_strats.py`, `calm_afternoon_diagnostic.py`, `premarket_strategy_sim.py` — Exploration
- `yesterday_mover_sim.py`, `pre_tf_sim.py`, `orb_fade_combined_test.py` — Sims

### DEAD — đủ 3-check, đề xuất archive vào `_archive/dead/`

| File | (a) Import | (b) Path ref | (c) Data | Note |
|---|---|---|---|---|
| `futures/fetch_es_continuous.py` | none | none | none | Nội dung chỉ 16 dòng package docs — tạo nhầm |
| `global_index/edge_test.py` | none | none | none | Stale copy, docstring vẫn ghi `orb_futures/edge_test.py` |
| `global_index/swing_tf_powerhour.py` | none | none | none | Prototype, nonequity/ version là canonical |
| `raits/raits/strategies/strategies/orb.py` | none | none | none | Bản cũ, thiếu FADE params |
| `raits/raits/strategies/strategies/__init__.py` | none | none | none | Empty package marker của orphan dir |
| `scratch/check_tsla_times.py` | none | none | hardcode old path `C:\Users\quock\RAITS\` | |
| `scratch/inspect_tsla_cache.py` | none | none | hardcode old path `C:\Users\quock\RAITS\` | |
| `tests/.../import yfinance as yf, pandas as pd.py` | none (tên là Python statement, không importable) | none | none | Nội dung trùng với hmm_validate.py header |

### SCRATCH — đủ 3-check, đề xuất archive vào `_archive/scratch/`

**Root level:**
`regime_index_relevance.py`, `analyze_system.py`, `analyze_deep.py`, `analyze_timeframe.py`,
`inspect_wfo.py`, `diagnose_exits.py`, `diagnose_gap_freq.py`, `diagnose_monthly.py`,
`diagnose_orb_scanner.py`, `diagnose_orb_scanner2.py`, `diagnose_orb_stops.py`,
`diagnose_trades.py`, `diagnose_wfo.py`, `hmm_validate.py`, `hmm_real_data_check.py`,
`quick_hmm_check.py`, `check_opening_vols.py`, `verify_environment.py`,
`verify_step_1_complete.py`, `setup_project_structure.py`, `config_template.py`,
`fix_imports.py`, `example_data_usage.py`, `example_data_validation.py`,
`futures/beta_check.py`

**raits/ level:**
`check_30days.py`, `check_all_strats.py`, `check_calm.py`, `check_cb_effect.py`,
`check_jan18.py`, `check_premarket.py`, `check_stk.py`, `check_stk2.py`,
`check_stk_entries.py`, `check_stress_mid.py`, `check_tf_composition.py`,
`compare_snapshots.py`, `compare_stress_days.py`, `compare_stress_orb.py`,
`debug_stress_orb_stk.py`, `diag_trade.py`, `fetch_sector_etfs.py`, `find_snapshot.py`,
`grid_risk_trend.py`, `mini_stk_test.py`, `reconcile_sim_vs_engine.py`,
`stk_day_bootstrap.py`, `stk_deep.py`, `stk_results.py`, `stress_orb_engine_diag.py`,
`tmp_slot_analysis.py`, `trace_stk_day.py`, `trace_tf_day.py`, `verify_cb_trigger.py`,
`vwap_mr_etf_sim.py`

**raits/raits/scripts/ (quick diff/compare, not strategy exploration):**
`early2020_diff.py`, `tf_diff.py`, `raits_vs_hold.py`, `_check_oos_data.py`

### CẦN XEM — để owner quyết định

| File | Lý do chưa chắc |
|---|---|
| `config_private.py` | API key — gitignored, không archive. Giữ nguyên vị trí. |
| `raits/raits/scripts/_check_oos_data.py` | Hardcode `d:\raits\raits\raits\scripts\window_debug.py` — path artifact, còn cần dùng không? |
| `raits/raits/tests/decision/` (cả thư mục) | Orphan test copies — không có gì import, nhưng là test code, cẩn thận |

---

## Kế hoạch thực hiện (chờ owner duyệt)

### Bước 1 — Annotate STALE (không di chuyển, chỉ thêm comment)
- [ ] `d:\raits\configs\final_params.yaml` → thêm comment `# STALE — pre-vault params (orb=15/bb=2.5/ema=30). Production canonical: raits/configs/final_params.yaml (orb=20/bb=1.5/ema=30)`
- [ ] `futures/__init__.py` → fix docstring: "ONLY raits.hmm" → thêm `raits.strategies.trend_follow`

### Bước 2 — Archive DEAD (8 files, `git mv` → `_archive/dead/`)
Verify sau mỗi file: 5 lệnh import phải pass.

- [ ] `futures/fetch_es_continuous.py`
- [ ] `global_index/edge_test.py`
- [ ] `global_index/swing_tf_powerhour.py`
- [ ] `raits/raits/strategies/strategies/orb.py`
- [ ] `raits/raits/strategies/strategies/__init__.py`
- [ ] `scratch/check_tsla_times.py`
- [ ] `scratch/inspect_tsla_cache.py`
- [ ] `tests/.../import yfinance as yf, pandas as pd.py`

### Bước 3 — Archive SCRATCH root level (~25 files, `git mv` → `_archive/scratch/root/`)
Verify sau batch.

### Bước 4 — Archive SCRATCH raits/ level (~30 files, `git mv` → `_archive/scratch/raits/`)
Verify sau batch.

### Bước 5 — README markers
- [ ] `orb_futures/README.md` — "EXPERIMENTAL: ORB on futures. Falsification record. NO-GO."
- [ ] `tier2/README.md` — "EXPERIMENTAL: ZN/ZB/6E structure probe. Self-contained. NO-GO."
- [ ] `xsect/README.md` — "EXPERIMENTAL: Cross-sectional momentum probe. Self-contained. NO-GO."
- [ ] `nonequity/README.md` — "EXPERIMENTAL: Gold/crude/NKD daily probe. Self-contained. NO-GO."
- [ ] `raits/README.md` — "STOCK-ENGINE: Phase 1 equity engine. Preserved. raits.hmm + raits.strategies.trend_follow are shared PRODUCTION core."

---

## Verify script (chạy sau MỖI bước)

```powershell
cd D:\raits
python -c "from futures._validated_core import backtest_swing_tf, label_regimes; print('OK1')"
python -c "from global_index.deploy_sim import replay; print('OK2')"
python -c "from global_index.net_exposure_multi import MultiClusterGuard; print('OK3')"
python -c "from raits.hmm.engine import HMMEngine; print('OK4')"
python -c "from raits.strategies.trend_follow import TrendFollowStrategy; print('OK5')"
```

Tất cả phải in OK. Bất kỳ fail → `git reset --hard HEAD` (về checkpoint gần nhất).
