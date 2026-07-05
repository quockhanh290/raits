# RAITS Futures — Trạng thái triển khai
_Cập nhật: 2026-07-05. Source of truth DUY NHẤT cho futures system._  
_Chi tiết divergence audit → `global_index/DIVERGENCE_SWEEP.md`_

---

## 1. OFFLINE — ĐÃ ĐÓNG HẾT

### Baseline (fit_C, 2-tick slippage, $50k, 7 năm IS 2018–2024)
| Metric | Giá trị |
|---|---|
| Net P&L | **$52,961.74** |
| Calmar | **2.75** |
| MaxDD | **$2,789** |
| hmm_fit_end | 2024-12-31 (fit_C) |
| Degradation floor | Calmar 2.38 (fit_A 2022) — không thay đổi |

Baseline lưu tại `baseline_fit_c.txt`. Locked — không re-run trừ khi annual re-freeze.

### 5+ tầng reconcile — tất cả PASS
| Tầng | Script | Kết quả |
|---|---|---|
| Swing GĐ0 | `futures/reconcile_gd0.py` | MES/MNQ/MYM/M2K all MATCH |
| Stress | `futures/reconcile_stress.py` | 0 mismatches, 269 Stress days |
| NKD Phase 1+2 | `futures/reconcile_nkd.py` | 515t/$12,306 field_mismatch=0 |
| Swing desired | `futures/reconcile_swing_desired.py` | 20 samples/inst, all PASS |
| verify_runner_real | `global_index/verify_runner_real.py` | diff=$0.00, ALL PASS |

### HMM fit_C — production + verified
- `futures/basket.py` canonical `hmm_fit_end=2024-12-31`
- NKD verified dùng fit_C (không trộn fit_A) — 225/1556 NKD days label khác (14.5%); economically justified
- Annual re-freeze gate: `hmm_sensitivity_gate.py` — approve nếu label change <5%

### Divergence sweep A–E — đóng
| Item | Trạng thái |
|---|---|
| UT-2: stale price retry | ✅ Fixed — guard `new_ed == today_norm` trong `signal_layer.py` |
| UT-5: NKD late-bar stale entry | ✅ Fixed — dùng `today_norm` (ET) thay `nkd_today_norm` (JST) |
| UT-1: breaker init gap | ✅ Fixed — `FuturesRunner.__init__` yêu cầu `breaker` positional |
| UT-3: same-day state-diff | ✅ Closed — path dead trong live (không có `exit` field); synthetic PASS |
| UT-4: half-day CME | ✅ Closed — A1-A4 PASS: no crash, no entry, position carries |
| WARN size_multiplier | ✅ Closed — cố ý không wire (xem ràng buộc §4) |
| C1/C2/C4/C7: feed conditions | ✅ PASS |
| C3/C5/C6: IBKRBroker specs | ✅ Implemented + 14/14 PASS (`test_ibkr_injection.py`) |
| UT-6: NKD synthetic coverage | 🟡 Medium — path dead by design |
| UT-1: HALT path never exercised | 🟡 Medium — HALT < 15% by construction; synthetic tested |

Operational constraint (NKD): runner phải chạy sau ~02:30 ET (NKD đóng cửa). Documented trong `runner.py` + `DIVERGENCE_SWEEP.md`.

### Trust audit — số load-bearing traceable (ee75963, 2026-07-05)
| Script | Đo | Kết quả |
|---|---|---|
| `global_index/stress_mid_trust.py` | STRESS_MID 2022 P&L standalone + marginal | **CONFIRMED**: $6,632 standalone (claim $5,296 — fit_A→fit_C diff) |
| `global_index/scaling_dd_trust.py` | 2-micro MaxDD, sizer threshold, nguồn $82k | **CORRECTED**: MaxDD $5,890 (claim $9,854 pre-NKD); threshold $55,784 (claim $82k = +47% buffer thủ công) |
| `global_index/hmm_flip_year_trust.py` | fit_C A→C flip breakdown per year | **CONFIRMED**: 17.16% / 101 N→S / 83 trong 2020+2022 — economically justified |

Chi tiết → `FUTURES_TRUST_AUDIT.md`.

### IBKRBroker skeleton — viết xong, chờ live
File: `global_index/ibkr_broker.py`  
Ba specs baked in, không thể bypass:
- **C3**: `fetch_bars` gọi `sort_index()` — IBKR trả bars out-of-order trên backfill/reconnect
- **C5**: `reconcile_positions(runner_state)` — dedup `(inst, cluster)` sau reconnect double-count
- **C6**: `fetch_bars` lowercase columns — IBKR uppercase `OPEN/HIGH/LOW/CLOSE/VOLUME`

Ba method cần implement live: `_fetch_raw`, `send_order`, `get_positions` (phần còn lại là `NotImplementedError`).

---

## 2. CHỜ IBKR ACCOUNT

### IBKRBroker — 3 hàm còn lại
```
_fetch_raw(inst, through)  → reqHistoricalData → DataFrame (raw, C3/C6 đã xử lý tự động)
send_order(order)          → build Contract, placeOrder, poll orderStatus → Fill
get_positions()            → ib.positions() → list[BrokerPosition]
```
Sau khi implement: chạy `test_ibkr_injection.py` với IBKR thật (không chỉ mock).

### Verify với IBKR thật
1. C6 format: kiểm IBKR reqHistoricalData thực sự trả uppercase OHLC — confirm lowercase fix applies
2. C3: kiểm có trường hợp out-of-order không với live backfill
3. C5: test reconnect với vị thế thật (paper mode)
4. Reconcile fill: verify `send_order` slippage/fill model khớp assumption deploy_sim (1-tick)

### Data — đã chốt: IBKR only
| Instrument | Source | Ghi chú |
|---|---|---|
| MES/MNQ/MYM/M2K | IBKR CME bundle | US equity index micro futures |
| MNKD | IBKR CME bundle | Verify MNKD có trong bundle + Rule 576 cert |
| Không mua | Polygon/Databento real-time | IBKR tự cấp đủ |

### Vận hành sau khi connect
- `dump_state()` Group B: slippage thật, fill quality, paper-vs-backtest, health, timing
- Dashboard live mode: poll `live_state.json`
- NKD timing: power-hour Nikkei (14:00-15:55 JST) = 12:00-13:55 trưa VN — canh được

---

## 3. TRƯỚC LIVE (sau paper)

1. **Re-freeze lần 1**: chạy `futures/refreeze.py` khi có data mới sau 2025 — approve nếu <5% label change (AUTO_APPROVE)
2. **Cơ chế GĐ3**: ✅ DONE — `futures/refreeze.py` + `futures/test_refreeze.py` 40/40 PASS
   - anchored-expanding: fit_once(2018→fit_end), gate 3 nhánh, auto-rollback, JSON registry
   - T2 thật: fit_2023 vs fit_C = 1.13% label change → verdict=VERIFY (dưới ngưỡng cần lo)
3. **Vault 2025**: one-shot OOS — không iterate, không chỉnh params sau khi nhìn kết quả
4. **Scale 1→2 micro** (sizer auto-select, từ `scaling_dd_trust.py` ee75963):
   - Equity ≥ **$55,784** → sizer tự chọn n=2 (binding: drawdown = 20 × $2,789 MaxDD)
   - 2-micro MaxDD = **$5,890** (2.11× 1-micro $2,789) = 11.8% của $50k → dưới 15% hard cap
   - Gate thực sự (không đổi): DD thật từ paper + qua ≥1 Stress regime live
   - _$82k cũ = $55,784 + 47% buffer thủ công, không có derivation — dùng làm thận trọng được nhưng không phải gate công thức_
   - _Nguồn sai: $9,854 ≈ 1.9 × $5,185 (MaxDD hệ pre-NKD, chưa cập nhật sau thêm NKD)_

---

## 4. RÀNG BUỘC (không được quên)

| Ràng buộc | Chi tiết |
|---|---|
| **WARN không wire** | `CircuitBreaker.status()` trả `size_multiplier=0.5` tại 10% DD nhưng `decide_day` không đọc. Cố ý: binary protection, wire = re-validate WFO + vault. Xem `futures/circuit_breaker.py` docstring. |
| **HMM shared class** | Sửa `HMMEngine` class → phải verify cả stocks pipeline. Đổi tham số (không đổi interface) là an toàn. |
| **Baseline locked** | `baseline_fit_c.txt` = $52,962/Calmar 2.75. Không re-run baseline trừ annual re-freeze. |
| **CWD = D:\raits** | Script chạy từ repo root. `_validated_core` resolve từ đây. |
| **Sửa _validated_core** | Bất kỳ sửa nào → phải re-run reconcile (gd0/stress/nkd/swing_desired) để chứng minh identical. |
| **Non-compound** | Deploy mặc định 1 micro/instrument. Sizer auto-select n=2 ở equity ≥ **$55,784** (DD-binding; 2-micro MaxDD = $5,890 = 11.8% của $50k). Gate thực: DD thật trong paper + qua ≥1 Stress live. $82k cũ là buffer thủ công +47%, không có derivation (xem §3.4). |
| **IBKRBroker C3/C5/C6** | Ba specs hardwired — không bypass. Test injection suite phải PASS trước paper. |
| **NKD runner timing** | Runner phải chạy sau ~02:30 ET. Nếu schedule thay đổi → review NKD date alignment. |

---

## 5. STOCKS — hệ riêng, chờ vault 2025

Equity RAITS (`raits/`) là hệ độc lập. Vault params locked (`configs/final_params.yaml`).  
**Không đụng futures khi làm stocks, không đụng stocks khi làm futures.**  
Điểm duy nhất share: `HMMEngine` class — xem ràng buộc trên.

---

## Kiến trúc — File map (2 tầng)

### Tầng 1: Validated engines (`futures/`) — DO NOT MODIFY
```
futures/_validated_core.py   backtest_swing_tf(), daily_atr_series(), load_parquet()
futures/swing_tf.py          SwingTFEngine — desired_basket() + backtest_basket()
futures/stress_mid.py        StressMidEngine — entry_signal() + backtest_basket()
futures/circuit_breaker.py   CircuitBreaker — 2 active layers (HALT 15%, HALT_DAY 4%)
futures/basket.py            BASKET dict, RISK dict, hmm_fit_end="2024-12-31" canonical
```
Bất kỳ sửa nào → phải re-run toàn bộ reconcile chain để chứng minh identical.

### Tầng 2: Live decision pipeline (`global_index/`)
```
global_index/deploy_sim.py      Reference sim (offline). Canonical P&L + risk formulas.
                                 real_risk() = n × mult × daily_ATR14.asof(entry_day) × pv
global_index/live_decision.py   Risk brain — decide_day(). Cap/priority/circuit-breaker.
global_index/signal_layer.py    Engine → candidates bridge.
                                 generate_today_signals(): STATE (swing/NKD) + EVENT (stress)
global_index/net_exposure_multi.py  MultiClusterGuard — cap enforcement
global_index/broker.py          Broker ABC + MockBroker + Order/Fill dataclasses
global_index/ibkr_broker.py     IBKRBroker (C3/C5/C6 baked in, 3 live methods pending)
global_index/runner.py          FuturesRunner — daily loop, exits before entries
global_index/regime.py          RegimeLabels — NKD JST→ET, lag_days=0, fit_C path
global_index/signal_layer.py    UT-2/UT-5 fixes live, ROSKA4_MULT=NKD_MULT=2.5
```

### Constants must stay in sync
| Constant | Location | Must match |
|---|---|---|
| `mult = 2.5` | `signal_layer.py` ROSKA4_MULT, NKD_MULT | `deploy_sim --roska4-mult 2.5 --nkd-mult 2.5` |
| `daily_atr_series` | import từ `futures._validated_core` | Không reimplementát — dùng chung |
| Cluster names | `roska4_swing`, `roska4_stress`, `global_nkd` | `net_exposure_multi.py` clusters |

---

## Lệnh chạy nhanh (từ `D:\raits`)

```powershell
# Verify baseline (chạy khi nghi ngờ có thay đổi ảnh hưởng)
python global_index\verify_runner_real.py --data-dir data\cache\futures --nkd-parquet global_index\data\NKD_continuous_1m_8y.parquet --regime-csv spy_daily.csv

# Reconcile GĐ0 (swing)
python -m futures.reconcile_gd0 --data-dir data\cache\futures --regime-csv spy_daily.csv

# Injection suite C3/C5/C6 (IBKRBroker specs)
python global_index\test_ibkr_injection.py

# Smoke test (cold-start integration)
python global_index\run_smoke_test.py
```
