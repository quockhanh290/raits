# Futures System — Mã Nội Bộ và Viết Tắt

_Nguồn: trích trực tiếp từ code/docs, không đoán. Cập nhật: 2026-07-06._
_Xem thêm: [FUTURES_OPERATIONAL_AUDIT.md](../../FUTURES_OPERATIONAL_AUDIT.md) | [DIVERGENCE_SWEEP.md](../../global_index/DIVERGENCE_SWEEP.md)_

---

## Mục lục

1. [Operational Audit Codes (A–J)](#1-operational-audit-codes-a–j)
2. [Guards (G / D / E)](#2-guards-g--d--e)
3. [Xử lý IBKR (C)](#3-xử-lý-ibkr-c)
4. [Bug Fixes / Resilience (B / F / H / J)](#4-bug-fixes--resilience-b--f--h--j)
5. [Divergence Sweep Tests (UT)](#5-divergence-sweep-tests-ut)
6. [HMM / Regime](#6-hmm--regime)
7. [Metrics / Vault](#7-metrics--vault)
8. [Xung đột tên (naming collisions)](#8-xung-đột-tên-naming-collisions)

---

## 1. Operational Audit Codes (A–J)

> Nguồn: `FUTURES_OPERATIONAL_AUDIT.md`. Mỗi mã = 1 failure scenario hoặc design check.
> Status badge: ✅ FIXED | 🔴 CRITICAL | 🟠 HIGH | 🟡 MEDIUM | DEFERRED (IBKR)

### A — Order Failures

| Mã | Tên ngắn | Ý nghĩa | Trạng thái | Nguồn |
|---|---|---|---|---|
| **A1** | Order reject | `send_order` raises `NotImplementedError` khi lệnh bị sàn từ chối (margin, invalid, market-closed) | DEFERRED (IBKR) | audit:34 |
| **A2** | Partial fill | Runner giả sử `contracts == filled`; thực tế chỉ 1/2 contracts filled → risk$ sai | 🟠 HIGH before live | audit:35 |
| **A3** | Fill price drift | `fill_price ≠ order.entry` → PnL drift tích lũy không alert | LOW | audit:36 |
| **A4** | Order timeout | Không có ACK sau `send_order` → không retry, không check | DEFERRED (IBKR) | audit:37 |
| **A5** | Duplicate order | Crash sau `send_order` hoàn thành tại IBKR nhưng trước khi lưu state → restart gửi lại OPEN | 🟠 HIGH before live | audit:38 |

### B — State Failures

| Mã | Tên ngắn | Ý nghĩa | Trạng thái | Nguồn |
|---|---|---|---|---|
| **B1** | Position persist | `live_positions.json` ghi atomic (.tmp + os.replace) sau mỗi `run_day()`; reload khi start | ✅ FIXED (layer 1) | audit:46, `runner.py:30` |
| **B2** | State corrupt | File bị hỏng → except → fresh start + warning. Handled by B1. | ✅ handled by B1 | audit:47 |
| **B3** | Broker↔runner mismatch | `reconcile_positions()` chỉ dedup runner state, KHÔNG fetch từ IBKR → mismatch im lặng | 🔴 CRITICAL before live | audit:48, `ibkr_broker.py:204` |
| **B4** | State write fail | Disk full → log error + continue (không crash). Sau khi có Slack: escalate to notify(). | ✅ handled | audit:49 |

### C — Signal Failures (Exception Safety)

> **Lưu ý:** Namespace C trong audit = exception safety cho signal/runner components.
> **Khác** với C-codes trong `ibkr_broker.py` (IBKR data specs) — xem [Mục 8](#8-xung-đột-tên-naming-collisions).

| Mã | Tên ngắn | Ý nghĩa | Trạng thái | Nguồn |
|---|---|---|---|---|
| **C1** | signal_fn crash | `signal_fn()` wrapped try/except: failure → entries=0, exits tiếp tục bình thường | ✅ FIXED | audit:70, `runner.py:32` |
| **C2** | stale guard crash | `hmm_stale_guard.check_day()` wrapped try/except: throw → `entries_allowed=False` (conservative block) | ✅ FIXED | audit:71, `runner.py:438` |
| **C3** | Empty bars alert | Sau `fetch_bars()`, check từng instrument có open position: bars rỗng → `logger.warning("C3: ...")` | ✅ FIXED | audit:72, `runner.py:359-371` |
| **C4** | Cluster isolation | Per-cluster try/except trong `generate_today_signals()`: swing fail → NKD vẫn chạy; inject "hold" dummies tránh spurious exits | ✅ FIXED | audit:73, `signal_layer.py:140,181,236` |

### D — Guard Interactions

| Mã | Tên ngắn | Ý nghĩa | Trạng thái | Nguồn |
|---|---|---|---|---|
| **D1** | Breaker + G1 | Cả hai cùng fire → G1 dập entries trước, breaker idempotent, exits OK | ✅ graceful by design | audit:81 |
| **D2** | Re-freeze fail | refreeze.py fail → runner giữ pkl cũ, không ảnh hưởng | ✅ graceful | audit:82 |
| **D3** | Guard + open pos | Exits chạy TRƯỚC guard check → held positions luôn exit được | ✅ graceful by design | audit:83 |

### E — Process / Resource Failures

| Mã | Tên ngắn | Ý nghĩa | Trạng thái | Nguồn |
|---|---|---|---|---|
| **E1** | PID lockfile | Ngăn duplicate runner: ghi PID file; instance 2 → `RunnerLockError`; stale PID → auto-overwrite | ✅ FIXED | audit:91, `runner.py:34,62` |
| **E2** | No watchdog | Runner die không tự restart → orphan positions | 🟡 MEDIUM (ops) | audit:92 |
| **E3** | Clock skew | `today − last_bar > 3 days` → log error + entries discarded, signal_fn vẫn gọi cho exits | ✅ FIXED | audit:93, `runner.py:375-398` |

### F — Persist Timing

| Mã | Tên ngắn | Ý nghĩa | Trạng thái | Nguồn |
|---|---|---|---|---|
| **F1** | Persist-after-order | Crash sau `send_order()` nhưng trước `_persist_state()` → order tại broker, file cũ → duplicate OPEN khi restart | DEFERRED (root = A5) | audit:211 |
| **F2** | Atomic write | `.tmp` + `os.replace()` → không partial-write | ✅ CLEAN | audit:212 |
| **F3** | Mid-step die | Die sau exits sent nhưng trước entries sent → file stale, restart re-submit CLOSE | DEFERRED (root = A5) | audit:213 |

### G — Persist I/O Edge Cases

> **Lưu ý:** G-codes trong audit (section G) = I/O edge cases.
> **Khác** với G1/G2/G3 = SPY stale / model age / re-freeze guards — xem [Mục 2](#2-guards-g--d--e).

| Mã | Tên ngắn | Ý nghĩa | Trạng thái | Nguồn |
|---|---|---|---|---|
| **G1** (I/O) | Disk write fail | `_persist_state()` log-only; TODO: escalate to notify() sau Slack live | LOW | audit:223 |
| **G2** (I/O) | Permission/partial read | `except Exception` → fresh start; atomic write → partial-read impossible | ✅ CLEAN | audit:224 |
| **G3** (I/O) | notify() push fail | Hook wrapped try/except, console luôn in; hook fail không ảnh hưởng trading | ✅ CLEAN | audit:225 |
| **G4a** (I/O) | Lock path permission | `PermissionError` propagate → constructor fail (fail-safe); UX gap: generic error message | LOW | audit:226 |
| **G4b** (I/O) | Stale lock (SIGKILL) | `_pid_alive(old_pid)` → False → auto-overwrite | ✅ CLEAN | audit:227 |
| **G4c** (I/O) | PID reuse | Stale PID recycled to different process → `RunnerLockError`, manual delete needed | LOW (ops) | audit:228 |

### H — Data Integrity

| Mã | Tên ngắn | Ý nghĩa | Trạng thái | Nguồn |
|---|---|---|---|---|
| **H1** | Schema backward-compat | Optional OpenPos fields dùng `d.get()` → forward compat; `KeyError` → fresh start (graceful) | LOW (maintenance) | audit:238, `test_operational_fixes.py:609` |
| **H2** (audit) | Bounds validation | Load silently accept `contracts≤0` / `risk_dollars<0`; offline-fixable: discard + warn | LOW (offline-fixable) | audit:239, `runner.py:234-244` |
| **H3** (audit) | CSV duplicate dates | `benchmark_daily` sort nhưng không dedup → duplicate weight trong HMM training | LOW (offline-fixable) | audit:240, `regime.py:32` |

### I — State Consistency

| Mã | Tên ngắn | Ý nghĩa | Trạng thái | Nguồn |
|---|---|---|---|---|
| **I1** | Atomic persist | `positions + breaker` trong 1 `json.dump` + 1 `os.replace` → không split-brain | ✅ CLEAN | audit:250 |
| **I2** | Restart race | E1 (PID lock) + atomic write → không concurrent write | ✅ CLEAN | audit:251 |
| **I3** | Empty day | `{"positions": []}` write + reload correctly | ✅ CLEAN | audit:252 |

### J — Engine / Threading

| Mã | Tên ngắn | Ý nghĩa | Trạng thái | Nguồn |
|---|---|---|---|---|
| **J1** | Concurrency | Runner fully single-threaded hiện tại; khi wire `ib_insync` async → cần reassess | DEFERRED (IBKR async) | audit:262 |
| **J2** | `_SWING_CACHE` | Module-level dict, never evicted → memory growth unbounded (252 entries/yr × full swing arrays) | 🟡 MEDIUM (verify before live) | audit:263, `runner.py:420-425` |

---

## 2. Guards (G / D / E)

> Namespace thứ hai cho G/D/E: operational guards trong `hmm_stale_guard.py`, `runner.py`, `refreeze.py`.
> **Không trùng** với G-codes trong audit section G (I/O edge cases).

| Mã | Guard | Soft threshold | Hard threshold | Action | Nguồn |
|---|---|---|---|---|---|
| **G1** | SPY CSV stale | >2 business days → WARN | >5 business days → halt entries | `check_day()` trả về `entries_allowed=False` | `hmm_stale_guard.py:7-15,43-48` |
| **G2** | Model age | >12 months → WARN | >18 months → WARN (không halt) | Log warning, không dừng entries | `hmm_stale_guard.py:15-21,48` |
| **G3** | Re-freeze data coverage | — | spy_csv phải reach fit_end trước khi re-freeze | `refreeze.py` abort nếu coverage thiếu | `refreeze.py:127` |
| **G4a** | Lock path invalid | — | `PermissionError` → `RunnerLockError` với actionable message | Constructor fail (fail-safe) | `test_operational_fixes.py:640-643` |
| **D5** | Kill-switch (STOP_FILE) | — | File tồn tại → halt entries, giữ exits | `run_day()` check `STOP_FILE` mỗi cycle | `runner.py:338-344` |
| **E1** | PID lockfile | — | Duplicate runner → `RunnerLockError` | Ngăn chạy 2 instance đồng thời | `runner.py:34,62` |
| **E3** | Clock skew | — | today >3 days ahead of latest bar → skip entries | Entries discarded, signal_fn vẫn gọi cho exits | `runner.py:375-398` |

---

## 3. Xử lý IBKR (C)

> C-codes trong `ibkr_broker.py` = **IBKR data specs / contracts** (khác với C-codes trong audit = exception safety).
> Xem [Mục 8](#8-xung-đột-tên-naming-collisions) để biết sự chồng lấp.

| Mã | Spec | Ý nghĩa | Nguồn |
|---|---|---|---|
| **C2** (ibkr) | Rollover schedule | Contract rollover logic trong `IBKRBroker` | `ibkr_broker.py:50,387` |
| **C3** (ibkr) | Sort bars | `fetch_bars()` PHẢI `sort_index()` — IBKR có thể trả bars không theo thứ tự | `ibkr_broker.py:7` |
| **C5** (ibkr) | Reconcile positions | `reconcile_positions()` sau reconnect — dedup runner state | `ibkr_broker.py:11,204` |
| **C6** (ibkr) | Lowercase columns | `fetch_bars()` normalize `OPEN/HIGH/LOW/CLOSE/VOLUME` → lowercase | `ibkr_broker.py:17,252` |
| **C7** (ibkr) | NKD JST late feed | NKD feed từ Tokyo có thể đến muộn | `DIVERGENCE_SWEEP.md:185` (covered bởi UT-5) |

---

## 4. Bug Fixes / Resilience (B / F / H / J)

| Mã | Tên | Ý nghĩa kỹ thuật | Nguồn |
|---|---|---|---|
| **B1** | Atomic persist | `_persist_positions()` ghi `live_positions.json` atomically; peak_equity, day_start_equity, cur_day cũng được persist trong `"breaker"` key | `runner.py:30`, audit:46 |
| **B3** | Broker reconcile (TODO) | Layer 2 của B1: cross-check file vs `broker.get_positions()` khi startup — **chưa implement** | `runner.py:175`, audit:48 |
| **F3** | Fat-finger cap | Chặn `n > max_contracts` — nếu sizer tính sai → guard không cho gửi lệnh quá lớn | `runner.py:511-516` |
| **J2** | Swing cache eviction | `_SWING_CACHE.clear()` sau mỗi `run_day()` — tránh memory leak trong long-running process | `runner.py:420-425` |
| **H1** | Schema compat | `_openpos_from_dict` dùng `d.get()` cho optional fields → forward-compatible khi thêm field mới | `test_operational_fixes.py:609` |
| **H2** | Load bounds check | Discard positions với `contracts≤0` hoặc `risk_dollars<0` khi load | `runner.py:234-244` |
| **H3** | CSV dedup dates | `spy_daily.csv` có thể có duplicate dates → `sort_index()` + dedup trong `benchmark_daily` | `regime.py:32` |

---

## 5. Divergence Sweep Tests (UT)

> Nguồn: `global_index/DIVERGENCE_SWEEP.md`. UT = "Unit Test" trong divergence sweep.
> Mục đích: verify backtest vs live path không có gap.

| Mã | Scenario | Kết quả | Ghi chú | Nguồn |
|---|---|---|---|---|
| **UT-1** | CircuitBreaker HALT path | 🟡 Medium — chưa test live | Halt path không bao giờ được exercise trong test suite | `DIVERGENCE_SWEEP.md:117` |
| **UT-2** | Rejected entry stale price retry | ✅ FIXED | Bug: stale price không được retry khi entry bị reject → fixed trong `signal_layer.py` | `DIVERGENCE_SWEEP.md:129` |
| **UT-3** | Same-day state-diff (live path) | CLOSED | Path dead trong live, không phải bug | `DIVERGENCE_SWEEP.md:149` |
| **UT-4** | Half-day CME sessions | CLOSED (A1-A4 PASS) | 4 sub-scenarios (A1-A4) all pass | `DIVERGENCE_SWEEP.md:163` |
| **UT-5** | NKD JST late-bar entry | ✅ FIXED | Bug: NKD late bar tạo stale entry → fixed | `DIVERGENCE_SWEEP.md:218-219` |
| **UT-6** | NKD zero synthetic coverage | 🟡 Medium — chưa cover | NKD branch với zero synthetic data chưa có test | `DIVERGENCE_SWEEP.md:220` |

---

## 6. HMM / Regime

| Mã | Tên | Ý nghĩa | Nguồn |
|---|---|---|---|
| **fit_A** | HMM freeze 2022 | HMM trained đến 2022-12-31. **Degradation floor**: Calmar 2.38 — nếu production thấp hơn, dừng lại | `refreeze.py:53`, `FUTURES_TRUST_AUDIT.md:29` |
| **fit_B** | HMM freeze (trung gian) | Intermediate freeze được đề cập trong docs; chi tiết cần xác nhận | `FUTURES_TRUST_AUDIT_TODO.md:67` [cần xác nhận] |
| **fit_C** | HMM freeze 2024 (production) | HMM trained đến 2024-12-31. Paper baseline: $52,962 / Calmar 2.75. File: `models/PRODUCTION.pkl` | `docs/SHARED.md:24`, `refreeze.py` |
| **calm-flip** | Calm→{Stress,Normal} flip | Khi re-freeze, nếu số label Calm→{Stress,Normal} vượt `CALM_FLIP_LIMIT` → force VERIFY/HOLD thay vì auto-promote | `refreeze.py:51,88,296-310` |
| **KD-001** | Known Difference 001 | CB/SAFETY_MODE mid-day exits: backtest dùng look-ahead price (close of halt bar), live sẽ exit at market → giá khác nhau. Documented, không phải bug | `docs/futures/KNOWN_DIFFERENCES.md:9` |

---

## 7. Metrics / Vault

| Từ/Mã | Ý nghĩa | Nguồn |
|---|---|---|
| **Calmar** | Annual Return / Max Drawdown. Metric chính để đánh giá futures system | Standard finance; dùng xuyên suốt trong docs |
| **PF** | Profit Factor = Gross Profit / Gross Loss | audit docs, vault results |
| **IS / OOS** | In-Sample (training data) / Out-of-Sample (test data) | WFO terminology |
| **Vault** | Sealed backtest run trên OOS period — không được rerun sau khi lock | `docs/futures/DECISIONS.md` |
| **deploy_sim** | Primary backtest tool cho full system (Rổ4 + NKD + STRESS_MID) | `global_index/deploy_sim.py` |
| **Rổ4** | Tên gọi của 4-stock swing-TF cluster (basket 4) | `futures/basket.py` |
| **STRESS_MID** | SHORT strategy vào 10:15 ET trong Stress regime | `futures/stress_mid.py` |
| **MNKD** | Micro Nikkei 225 futures contract symbol tại CME | `global_index/specs.py` |
| **~$58-59k** | Scaling threshold (hội tụ): sizer auto-select n=2 khi `account ≥ 20 × MaxDD_1micro(account)` — tự tham chiếu, hội tụ ~$58-59k. $55,784 là threshold sai (tính MaxDD@$50k). Cần `deploy_sim --account 59000` xác nhận. | `docs/futures/SCALING_ANALYSIS.md` (2026-07-08) |
| **$52,962** | fit_C paper baseline: net PnL từ deploy_sim IS period với fit_C | `docs/SHARED.md:24` |
| **live_decision** | Module chứa `decide_day()` — "risk brain" của runner (~80% logic, không phải broker I/O) | `global_index/live_decision.py` |
| **MultiClusterGuard** | Per-cluster exposure caps: Rổ4-swing, Rổ4-stress, NKD | `global_index/net_exposure_multi.py` |

---

## 8. Xung đột tên (Naming Collisions)

Một số mã được dùng cho **nhiều khái niệm khác nhau** trong codebase. Khi đọc code, xác định context trước:

### C-codes — 2 namespaces

| Context | C1 | C2 | C3 | C4 |
|---|---|---|---|---|
| **Audit / runner.py** (exception safety) | signal_fn try/except | stale_guard try/except | Empty bars alert | Per-cluster isolation |
| **ibkr_broker.py** (IBKR data specs) | _(không có)_ | Rollover schedule | Sort bars timestamp | _(không có)_ |
| **STATUS.md / DIVERGENCE_SWEEP.md** (E-injection test scenarios) | Late bar injected | Dup bar injected | Out-of-order bars | Missing bars |

**Rule:** Khi thấy C3 trong runner.py → "empty bars alert". Khi trong ibkr_broker.py → "sort bars". Khi trong DIVERGENCE_SWEEP.md → "out-of-order bars test".

### G-codes — 2 namespaces

| Context | G1 | G2 | G3 | G4a |
|---|---|---|---|---|
| **Operational guards** (hmm_stale_guard.py, runner.py) | SPY CSV stale | Model age | Re-freeze coverage | Lock path invalid |
| **Audit section G** (I/O edge cases) | Disk write fail | Permission/partial read | notify() push fail | Lock permission-denied |

**Rule:** "G1 fires" thường = SPY stale guard. "G1 in audit section G" = disk write fail.

### H2 / H3 — 3 namespaces

| Context | H2 | H3 |
|---|---|---|
| **Audit** (futures runner) | Bounds validation on load | CSV duplicate dates |
| **stocks scripts** (`premarket_strategy_sim.py`) | Pre-market Gap-and-Go strategy | PM Fade reversal strategy |
| **stk_day_bootstrap.py** | Second-half 2022 (H2 2022 time period) | _(không có)_ |

**Rule:** Trong futures context → dùng audit definition. Trong stocks context → chiến lược khác hoàn toàn.

---

_Để thêm entry mới: (1) xác định nguồn gốc trong code, (2) ghi file:line, (3) kiểm tra xem có naming collision không._
