# Futures — SCRIPT INVENTORY
_Phân loại từ trace thật (runner.py run_day import chain). KHÔNG đoán từ tên._
_Cập nhật: 2026-07-06. Tổng: 53 scripts (global_index/ 35 + futures/ 18)._

---

## Production Chain — từ runner.py run_day()

```
runner.py (entry point)
├── global_index.broker              (Order — abstract base)
├── global_index.live_decision       (decide_day, DecisionState, OpenPos)
│   └── global_index.net_exposure_multi  (MultiClusterGuard, Position)
├── (dynamic in run_day)
│   └── futures._validated_core      (_SWING_CACHE.clear())
└── (dynamic in _build_operational_status)
    └── global_index.hmm_stale_guard (check_day, G1/G2 guards)
        └── global_index.notify      (notify())

INJECTED AT CONSTRUCTION (signal_fn + broker + breaker):
  global_index.ibkr_broker        → global_index.broker (Broker ABC)
  global_index.signal_layer       → futures._validated_core (daily_atr_series)
  futures.swing_tf (SwingTFEngine) → futures.basket, futures.cost
  futures.stress_mid (StressMidEngine) → futures.basket
  futures.circuit_breaker         → futures.basket (RISK)
  futures.sizer (size_basket)     → futures.basket (via futures/__init__)
  global_index.specs              (NKD instrument spec — MNKD)
  global_index.regime             (RegimeLabels — NKD lag labeling)
  futures.basket                  (BASKET, SWING_TF_PARAM, params)
  futures.cost                    (FuturesCost)
  futures._validated_core         (label_regimes, backtest_swing_tf, ...)
```

---

## global_index/ — 35 scripts

| Script | Loại | Chạy khi nào | Ghi chú |
|---|---|---|---|
| `runner.py` | **PRODUCTION** | mỗi ngày live (run_day) | Entry point. FuturesRunner. Injected: broker, signal_fn, breaker, hmm_stale_guard |
| `live_decision.py` | **PRODUCTION** | mỗi ngày (imported runner) | decide_day() — risk brain. ~80% runner logic không phải broker I/O |
| `broker.py` | **PRODUCTION** | mỗi ngày (imported runner) | Abstract base: Broker ABC, Order, Fill, BrokerPosition, MockBroker |
| `net_exposure_multi.py` | **PRODUCTION** | mỗi ngày (imported live_decision) | MultiClusterGuard — per-cluster exposure caps (Rổ4/stress/NKD) |
| `hmm_stale_guard.py` | **PRODUCTION** | mỗi ngày (dynamic import runner) | G1 SPY stale / G2 model age. Imported dynamically in `_build_operational_status` |
| `notify.py` | **PRODUCTION** | mỗi ngày (imported hmm_stale_guard) | Notification wrapper — called when G1/G2 transitions |
| `ibkr_broker.py` | **PRODUCTION** (injected, 3 stubs) | mỗi ngày live | IBKRBroker extends broker.Broker. 3 NotImplementedError: `_fetch_raw`, `send_order`, `get_positions` — chờ IBKR |
| `signal_layer.py` | **PRODUCTION** (injected, verified) | mỗi ngày live (signal_fn) | Bridge engines → decide_day. `generate_today_signals`. Chưa wired trực tiếp vào runner nhưng verified correct qua `verify_runner_real.py`. Diff desired-vs-held logic |
| `update_spy_csv.py` | **DATA-PREP** | TRƯỚC run_day (manual/cron) | Cập nhật spy_daily.csv từ Polygon. Phải chạy trước run_day để G1 không trigger. Không import bởi runner |
| `fetch.py` | **DATA-PREP** | một lần khi fetch dữ liệu mới | Fetch NKD parquet từ IBKR/Polygon. Standalone, chạy khi cần data mới |
| `specs.py` | **PRODUCTION** (lib) | Imported khi inject signal_fn | NKD instrument specs (MNKD: mult, margin, pv, etc.). Sẽ cần ibkr_broker khi live |
| `regime.py` | **PRODUCTION** (lib) | Imported khi inject signal_fn | SPY→NKD regime labeling với lag=1 day (lookahead-safe). `load_spy_regime`, `RegimeLabels` |
| `_core.py` | **BACKTEST** (lib) | Imported bởi NKD backtest scripts | Verbatim copies của `futures/_validated_core` primitives. Dùng để NKD scripts standalone. Không dùng trong runner |
| `__init__.py` | — | — | Docs only. Không import gì |
| `deploy_sim.py` | **BACKTEST** | validate/vault (không live) | Primary backtest simulator. Vault runs, baseline, scaling. `replay()`, `size_combined()`, `metrics()` |
| `run_smoke_test.py` | **TEST** | pre-live verify (không thường xuyên) | Integration test: size_combined() → assert N==1; baseline $52,936; 5 checks |
| `verify_runner_real.py` | **TEST** | pre-live verify (không thường xuyên) | runner + MockBroker + real signal_fn == deploy_sim trade-for-trade. N_CONTRACTS=1 hardcoded |
| `test_ibkr_injection.py` | **TEST** | regression (pytest hoặc manual) | IBKRBroker C3/C5/C6 specs. 14/14 PASS |
| `test_hmm_stale.py` | **TEST** | regression | G1/G2 guards. 42/42 PASS |
| `test_operational_fixes.py` | **TEST** | regression | B1/C1-C4/E1/E3. 59/59 PASS |
| `test_event_playback.py` | **TEST** | manual verify | runner.dump_state → live_state_data.js → dashboard pipeline. 30 synthetic days |
| `generate_replay_snapshots.py` | **PRODUCTION-PLANNED** | hiện tại: manual (IS replay) | Dashboard IS data. Khi IBKRBroker ready: runner gọi dump_state() mỗi cycle → live dashboard. NOT in run_day hiện tại |
| `combined.py` | **ARCHIVED** | `_archive/answered/` | Gate: NKD naive-pool GO. Answered — xem [ARCHIVE_LOG.md](ARCHIVE_LOG.md) |
| `combined_system.py` | **ARCHIVED** | `_archive/answered/` | Gate: NKD + risk layer GO. Answered — `deploy_sim.py` là tool tiếp theo |
| `wfo.py` | **ARCHIVED** | `_archive/answered/` | NKD gated vs agnostic OOS. Answered (agnostic thắng, deployed) |
| `vault.py` | **ARCHIVED** | `_archive/answered/` | NKD standalone vault Gate 5 GO. Answered — `deploy_sim.py` cover full system |
| `scaling_dd_trust.py` | **ARCHIVED** | `_archive/answered/` | $55,784 threshold PARTIALLY (ee75963; NKD bug + self-ref error; true threshold ~$58-59k; xem SCALING_ANALYSIS.md). Answered |
| `stress_mid_trust.py` | **ARCHIVED** | `_archive/answered/` | STRESS_MID $6,632 IS CONFIRMED (ee75963). Answered |
| `hmm_flip_year_trust.py` | **ARCHIVED** | `_archive/answered/` | HMM flip 17.16% CONFIRMED. Answered |
| `cap_sweep.py` | **RESEARCH** | khi cần review sizing caps | Sweep `max_gross_pct` caps. Chưa answered — có thể cần lại |
| `priority_sweep.py` | **ARCHIVED** | `_archive/answered/` | Entry priority: risk-high-first thắng. Baked vào `live_decision.py` |
| `risk_diagnostic.py` | **ARCHIVED** | `_archive/answered/` | Real risk$ per position. Answered — dẫn đến ATR-based cap design |
| `hold_vs_entry_diagnostic.py` | **ARCHIVED** | `_archive/answered/` | Hold-time vs entry-race. Answered — behavior understood |
| `reject_diagnostic.py` | **ARCHIVED** | `_archive/answered/` | 22% reject benign or biased? Answered — benign |
| `reject_value_diagnostic.py` | **ARCHIVED** | `_archive/answered/` | $ value của rejects. Answered — dẫn đến priority_sweep |

---

## futures/ — 18 scripts

| Script | Loại | Chạy khi nào | Ghi chú |
|---|---|---|---|
| `_validated_core.py` | **PRODUCTION** (lib) | mỗi ngày (dynamic runner + signal construction) | Locked engine: `backtest_swing_tf`, `label_regimes`, `load_parquet`, `daily_atr_series`. KHÔNG sửa |
| `basket.py` | **PRODUCTION** (lib) | mỗi ngày (swing_tf, circuit_breaker, sizer) | Frozen params: ema=30, mult=2.5. BASKET, SWING_TF_PARAM, REGIME, RISK |
| `swing_tf.py` | **PRODUCTION** (lib) | mỗi ngày (SwingTFEngine trong signal_fn) | SwingTFEngine — desired_position + state diff. basket + cost |
| `stress_mid.py` | **PRODUCTION** (lib) | mỗi ngày khi Stress regime | StressMidEngine — SHORT tại 10:15. basket |
| `circuit_breaker.py` | **PRODUCTION** (lib) | mỗi ngày (injected as breaker) | CircuitBreaker — account DD halt. basket(RISK) |
| `cost.py` | **PRODUCTION** (lib) | mỗi ngày (via swing_tf) | FuturesCost — commission + slippage per contract |
| `sizer.py` | **PRODUCTION** (lib, startup) | một lần khi start (size_basket) | Tính n_contracts tại startup. Re-exported qua `futures/__init__`. Không gọi trong run_day |
| `__init__.py` | **PRODUCTION** (lib) | bất kỳ `from futures.xxx` | Re-exports: FuturesCost, BASKET, SwingTFEngine, StressMidEngine, CircuitBreaker, size_basket |
| `refreeze.py` | **ADMIN** | annually (manual, ~Dec) | Annual HMM retrain. Gate 3-nhánh, anchored-expanding, auto-rollback. Không trong run_day chain |
| `test_refreeze.py` | **TEST** | regression | 68/68 PASS. Gate + rollback + T12 skip-invalid |
| `reconcile_gd0.py` | **VALIDATION** | trước mỗi live change | Reconcile engine vs harness. 0 mismatch |
| `reconcile_stress.py` | **VALIDATION** | trước mỗi live change | Stress reconcile. 0 mismatch, 269 Stress days |
| `reconcile_nkd.py` | **VALIDATION** | trước mỗi live change | NKD reconcile: 515t/$12,306, field_mismatch=0 |
| `reconcile_swing_desired.py` | **VALIDATION** | trước mỗi live change | Swing desired_position reconcile (live path proof) |
| `swing_tf_harness.py` | **BACKTEST** (lib) | từ pooled_swing_vault/wfo | Backtest harness dùng bởi pooled_swing_vault.py, pooled_swing_wfo.py. Không dùng trong production runner |
| `backtest_combined.py` | **BACKTEST** | ad-hoc (Rổ4 only, no risk layer) | Naive Rổ4 pool. Pre-NKD. Ít dùng khi đã có deploy_sim |
| `backtest_system.py` | **ARCHIVED** | `_archive/superseded/` | 2-cluster design tiền-NKD. Superseded bởi `combined_system.py` → `deploy_sim.py` |
| `net_exposure.py` | **ARCHIVED** | `_archive/superseded/` | Old NetExposureGuard (2 clusters). Production dùng `global_index/net_exposure_multi.py` |

---

## Production Manifest — CHÍNH XÁC scripts chạy khi live

### Static import chain (chạy mọi ngày):
```
runner.py
├── global_index/broker.py
├── global_index/live_decision.py
│   └── global_index/net_exposure_multi.py
├── global_index/hmm_stale_guard.py  (dynamic, _build_operational_status)
│   └── global_index/notify.py
└── futures/_validated_core.py       (dynamic, _SWING_CACHE.clear in run_day)
```

### Injected at construction (must be present for live):
```
global_index/ibkr_broker.py       (broker=IBKRBroker(...))
global_index/signal_layer.py      (signal_fn = wrap(generate_today_signals))
global_index/specs.py             (NKD spec)
global_index/regime.py            (NKD lag labels)
futures/_validated_core.py        (engines, label_regimes)
futures/basket.py
futures/swing_tf.py
futures/stress_mid.py
futures/circuit_breaker.py        (breaker=CircuitBreaker(...))
futures/cost.py
futures/sizer.py                  (startup sizing, futures/__init__)
```

### Data-prep (chạy TRƯỚC run_day, không import bởi runner):
```
global_index/update_spy_csv.py    → spy_daily.csv (G1 stale guard)
global_index/fetch.py             → NKD parquet (khi data cũ)
futures/refreeze.py               → models/PRODUCTION.pkl (annual)
```

### KHÔNG chạy khi live (mọi thứ còn lại):
deploy_sim, combined*, wfo, vault, *_trust, *_diagnostic, *_sweep,
generate_replay_snapshots (chưa wired), run_smoke_test, verify_runner_real,
backtest_system, net_exposure (superseded), reconcile_*, test_*,
swing_tf_harness, backtest_combined

---

## Đã xử (Archived 2026-07-06)

14 scripts moved to `_archive/`. Xem [ARCHIVE_LOG.md](ARCHIVE_LOG.md) cho lý do + trace đầy đủ.

| Đích | Scripts |
|---|---|
| `_archive/superseded/` | `futures/backtest_system.py`, `futures/net_exposure.py` |
| `_archive/answered/` | `combined.py`, `combined_system.py`, `wfo.py`, `vault.py`, `scaling_dd_trust.py`, `stress_mid_trust.py`, `hmm_flip_year_trust.py`, `risk_diagnostic.py`, `hold_vs_entry_diagnostic.py`, `reject_diagnostic.py`, `reject_value_diagnostic.py`, `priority_sweep.py` |

Verify clean: không có production file nào import từ các scripts này.

### D4 — combined vs combined_system vs deploy_sim (cho reference):
```
combined.py        = Naive pool, no risk layer. ARCHIVED. Câu hỏi naive pool đã trả lời.
combined_system.py = With risk layer. ARCHIVED. Gate đã pass, deploy_sim là tool tiếp theo.
deploy_sim.py      = THE primary backtest tool. NEVER superseded. Primary.
```

### PRODUCTION-PLANNED (không dead, nhưng chưa wired):
| Script | Trạng thái | Khi nào wire |
|---|---|---|
| `global_index/signal_layer.py` | Verified correct (verify_runner_real). Chưa có launch script wiring signal_fn | Khi viết launch script (trước live) |
| `global_index/generate_replay_snapshots.py` | Generates IS replay JS. Planned runner integration | Khi IBKRBroker ready |
