# RAITS Futures — Trạng thái triển khai
_Cập nhật: 2026-07-05 (session 2). Source of truth DUY NHẤT cho futures system._  
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

### Stale number audit — production sạch (2026-07-05)
- Live production path: SẠCH — không stale number nào ảnh hưởng quyết định live.
- 14 diagnostic scripts: default hmm-fit-end 2022→2024 (không phải 2024-12-31) — chỉ diagnostic, không ảnh hưởng production.
- `cap_sweep.py` verify caps khớp fit_C production: swing 5%/4.4%, stress 2.5%, NKD 2%.
- Doc số sửa: sizer `$2,517→$2,789` (MaxDD fit_C), net_exposure `$5,185→$2,789`.
- Cố ý giữ nguyên: CALMAR_FLOOR 2.38 (fit_A floor = degradation floor), account $50k, DD caps (15%/4%).

### Re-freeze cơ chế — Phần A DONE (2026-07-05)
`futures/refreeze.py` — anchored-expanding fit, gate 3 nhánh, auto-rollback, JSON registry `history[:3]`
- Gate logic (calm-flip-aware): `calm_flip > 0` → VERIFY dù % thấp; `≥15%` hoặc `calm_flip > 10` → HOLD/REJECT
- AUTO_APPROVE: `label_change < 5%` và `calm_flip == 0`
- 40/40 PASS (`futures/test_refreeze.py`). fit_C hash bất biến khi re-run. HMMEngine class không sửa (stocks an toàn).
- T2 thật: fit_2023 vs fit_C = 1.13% label change, calm_flip=0 → verdict=VERIFY
- G3 caller-side: fail graceful (không crash runner), re-alert lặp (T10), recovery clear flag (T11)
- Phần B (data pipeline live, trigger định kỳ, wire vào runner) → §3

### HMM stale guards G1/G2/G3 — DONE (2026-07-05)
`global_index/hmm_stale_guard.py` + `global_index/notify.py`
- **G1** SPY CSV stale: SOFT >2 bday warn-once / HARD >5 bday halt-entry-GIỮ-exit / recovery ≤2 bday clear
- **G2** model-age: SOFT >12 tháng warn / HARD >18 tháng urgent — warn-only, không halt (model degraded gradually, không sai ngay)
- **G3** re-freeze data coverage: abort nếu CSV < fit_end — caller-side trong `refreeze.py`
- Chặn-entry-GIỮ-exit verified: exits là HMM-independent (exit_day-based), không bị G1 block
- `runner.py` default `hmm_stale_guard=None` (disabled); production pass instance

### Operational fixes — 8 gaps DONE (2026-07-05)
`global_index/runner.py` + `global_index/signal_layer.py`  
59/59 PASS (`global_index/test_operational_fixes.py`). Baseline $52,961.74 bất biến.

| Fix | Mô tả |
|---|---|
| **B1** | Position persist: `_persist_state()` atomic `.tmp`+`os.replace`, load với try/except corrupt |
| **peak_equity** | CircuitBreaker state persist: `peak_equity` + `_day_start_equity` + `cur_day` trong `live_positions.json` → DD không reset về 0 sau restart |
| **C1** | `signal_fn()` try/except → entries skip, exits vẫn chạy qua exit_day |
| **C2** | `hmm_stale_guard.check_day()` try/except → block entries (conservative) on throw |
| **C3** | Empty `fetch_bars` alert cho instrument đang hold open position |
| **C4** | Per-cluster try/except trong `signal_layer`: swing/NKD fail → inject "hold" dummies, không spurious exit |
| **E1** | PID lockfile `RunnerLockError`; Windows dùng `OpenProcess` (không dùng `os.kill(pid,0)` = CTRL_C) |
| **E3** | Clock skew sanity: `today − last_bar > 3d` → alert + discard entries |

IBKR-gated (chưa fix được offline): B3 broker↔runner reconcile, B1 layer-2 cross-check, A2 partial fill, A5 duplicate order, A1/A4 → xem §2.

**Persist rà đầy đủ (2026-07-05):** Sau B1 + peak_equity fix, KHÔNG còn field nào LOST+gây-sai quyết định.  
- HALT là computed state (không stateful flag): `dd=(peak-cur)/peak ≥ 15%` → tự recover từ peak_equity persist.  
- `taken/rejected/halted` counter: LOST, nhưng chỉ audit — không dùng để ra quyết định.  
- `regime_unreliable`: LOST, nhưng re-derived từ CSV mỗi `check_day()` — không có window sai.  
- Cosmetic còn (low, TODO trước notify production): counter reset làm mất audit history; `_g1_soft_active`/`_g2_*_notified` reset → có thể gửi duplicate notification. Fix: persist dưới key `"guard"` trong `live_positions.json`.

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
4. Reconcile fill: đo slippage thật từ paper fills, so với **baseline 2-tick/side** (`baseline_fit_c.txt`, `run_smoke_test.py SLIPPAGE=2.0`). `deploy_sim` default 1-tick là upper-bound tham chiếu, KHÔNG phải baseline. Paper slippage > 2-tick → P&L sẽ thấp hơn $52,936.

### Data — đã chốt: IBKR only
| Instrument | Source | Ghi chú |
|---|---|---|
| MES/MNQ/MYM/M2K | IBKR CME bundle | US equity index micro futures |
| MNKD | IBKR CME bundle | Verify MNKD có trong bundle + Rule 576 cert |
| Không mua | Polygon/Databento real-time | IBKR tự cấp đủ |

### Operational — IBKR-gated (chưa fix được offline)
| Item | Vấn đề |
|---|---|
| **B3** | Không có reconcile broker↔runner thật — `get_positions()` → NotImplementedError |
| **B1 lớp-2** | `live_positions.json` chưa cross-check vs IBKR `get_positions()` khi load |
| **A2** | Partial fill không handle — runner assume filled=ordered qty |
| **A5** | Duplicate OPEN sau restart — crash sau IBKR fill nhưng trước runner ghi state |
| **A1/A4** | Order reject + timeout → `NotImplementedError` (known, deferred) |

### Scale 1→2 micro (số đúng từ trust audit ee75963)
- Sizer n=2 ở **equity ≥ $55,784** — binding: `n × MaxDD ≤ 20%` của account
- 2-micro MaxDD = **$5,890** (2.11× 1-micro $2,789) = 11.8% của $50k → dưới hard cap 15%
- _$82k cũ = $55,784 + 47% buffer thủ công, không có derivation công thức_
- _$9,854 cũ = MaxDD pre-NKD (hệ cũ chưa có NKD), không áp dụng fit_C_
- Gate thực: DD thật trong paper + qua ≥1 Stress live (không đổi)

### Vận hành sau khi connect
- `dump_state()` Group B: slippage thật, fill quality, paper-vs-backtest, health, timing
- Dashboard live mode: poll `live_state.json`
- NKD timing: power-hour Nikkei (14:00-15:55 JST) = 12:00-13:55 trưa VN — canh được

---

## 3. TRƯỚC LIVE (sau paper)

1. **Re-freeze Phần A**: ✅ DONE — `futures/refreeze.py` 40/40 PASS. Gate + rollback + registry xong.
2. **Re-freeze Phần B**: Wire pipeline live vào runner (data tự động, trigger re-freeze định kỳ)
3. **Vault 2025**: one-shot OOS — không iterate, không chỉnh params sau khi nhìn kết quả
4. **Scale 1→2 micro** (số từ `scaling_dd_trust.py` ee75963 — xem §2 và §4)

---

## 4. RÀNG BUỘC (không được quên)

| Ràng buộc | Chi tiết |
|---|---|
| **WARN không wire** | `CircuitBreaker.status()` trả `size_multiplier=0.5` tại 10% DD nhưng `decide_day` không đọc. Cố ý: binary protection, wire = re-validate WFO + vault. Xem `futures/circuit_breaker.py` docstring. |
| **HMM shared class** | Sửa `HMMEngine` class → phải verify cả stocks pipeline. Đổi tham số (không đổi interface) là an toàn. |
| **Baseline locked** | `baseline_fit_c.txt` = $52,936/Calmar 2.74 (corrected 2026-07-06, CSV freeze-2017 bug fixed). Không re-run baseline trừ annual re-freeze. |
| **CWD = D:\raits** | Script chạy từ repo root. `_validated_core` resolve từ đây. |
| **Sửa _validated_core** | Bất kỳ sửa nào → phải re-run reconcile (gd0/stress/nkd/swing_desired) để chứng minh identical. |
| **Non-compound** | Deploy mặc định 1 micro/instrument. Sizer auto-select n=2 ở equity ≥ **$55,784** (DD-binding; 2-micro MaxDD = $5,890 = 11.8% của $50k). Gate thực: DD thật trong paper + qua ≥1 Stress live. $82k cũ là buffer thủ công +47%, không có derivation (xem §3.4). |
| **IBKRBroker C3/C5/C6** | Ba specs hardwired — không bypass. Test injection suite phải PASS trước paper. |
| **NKD runner timing** | Runner phải chạy sau ~02:30 ET. Nếu schedule thay đổi → review NKD date alignment. |
| **Operational state persist** | `live_positions.json`: `{"positions":[...], "breaker":{"peak_equity":..., "day_start_equity":..., "cur_day":"YYYY-MM-DD"}}`. Backward-compat: plain list → positions only. Không xóa/overwrite file thủ công khi runner đang chạy. |
| **Breaker HALT không stateful** | CircuitBreaker KHÔNG có `halted: bool` field. HALT = computed: `dd=(peak-cur)/peak ≥ 15%`. Persist `peak_equity` đủ để recover HALT đúng sau restart (T13 verified). Không cần persist thêm. |
| **Notification dedup TODO** | `_g1_soft_active`, `_g2_soft_notified`, `_g2_hard_notified` reset trên restart → duplicate notification. Low severity. Fix trước khi dùng `notify.py` production: persist 3 bool dưới key `"guard"` trong `live_positions.json`. |

---

## 5. UI MONITOR — chưa implement backend

UI RAITS Futures Monitor tồn tại (frontend). Operational status panel cần backend:
- **Chưa có**: event writer — runner chưa ghi guard/order/state/signal ra file mà UI đọc
- **Cần implement trước live**: `dump_state()` Group B ghi `live_state.json` định kỳ (signal/position/guard/breaker status)
- Dashboard live mode: UI poll `live_state.json` — wire lại sau khi runner ghi đủ fields
- Logging hoạt động (`runner.py` logger), nhưng không có structured JSON feed cho UI

---

## 6. STOCKS — hệ riêng, chờ vault 2025

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
