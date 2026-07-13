# Futures — STATUS
_Cập nhật: 2026-07-12. Source of truth cho trạng thái futures subsystem._

**Đường đi paper → live: [PAPER_ROUTE.md](PAPER_ROUTE.md)**
Bước tiếp theo: **P0b** (thứ Hai 14:05 ET) — xem PAPER_ROUTE.md § P0b.

---

## SESSION WRAP-UP — 2026-07-12 (offline xong, chờ P0b)

| Hạng mục | Trạng thái |
|----------|-----------|
| P0a plumbing | PASS (code cuối — after all session commits) |
| B1 verify_concat | PASS 30/30 (3 runs) |
| B2 cron ET-native | PASS (APScheduler 3.11.3, 14:05/09:31 ET verified) |
| Account clean | PASS (broker []+file []+4 nguồu đồng ý) |
| C1 fill monitoring | DONE (signed slippage + running mean persist slip_stats.json) |
| _strip_tz fix | DONE (concat frozen/live TZ mismatch) |
| INVARIANTS | baseline 1.66/$40,919 \| floor 1.57 \| vault 2.77/3.39 \| STP -$573 |
| Git state | CLEAN (f0d9097) |

**Tất cả offline đóng.** Bug tiếp lộ trong P0b/P2 khi chạy thật.

---

## PRE-PAPER MILESTONE — 2026-07-08

### NỀN — verified (consistency)

| Metric | Giá trị |
|---|---|
| Net P&L | **$52,936** (n=1, 2-tick/side, fit_C 2024-12-31) |
| Calmar | **2.744** |
| MaxDD | **$2,789** (5.6%) |
| Degradation floor | Calmar **2.38** (fit_A 2022, locked) |

Baseline locked tại `baseline_fit_c.txt`. Re-run chỉ khi annual re-freeze.

**Reconcile 4× 0 mismatch — LƯU Ý**: đây là CONSISTENCY check (engine ≡ harness), KHÔNG phải CORRECTNESS check.
- Nếu engine và harness cùng có bug → reconcile PASS giả (sweep 5 finding — xem L10)
- Correctness được verify bởi: vault OOS (Rổ4+NKD GO) + paper (chưa)
- Reconcile kiểm tra 4 fields (day, exit_day, pnl, direction) — không kiểm entry price

| Tầng | Script | Kết quả |
|---|---|---|
| Swing GĐ0 | `futures/reconcile_gd0.py` | MES/MNQ/MYM/M2K MATCH (423/432/436/435 trades) |
| Stress | `futures/reconcile_stress.py` | 0 mismatches, 265 Stress days |
| NKD Phase 1 | `futures/reconcile_nkd.py` | 528t/$12,405 field_mismatch=0 |
| Swing desired | `futures/reconcile_swing_desired.py` | 4 instruments PASS |
| verify_runner_real | `global_index/verify_runner_real.py` | diff=$0.00, ALL PASS |

---

### VAULT — verdict theo sleeve

| Period | Net P&L | Calmar | PF | Config | Verdict |
|---|---|---|---|---|---|
| 2023-2024 | $14,144 | **3.33** | 1.73 | n=1, HMM fit-2022 (clean OOS) | ✓ GO |
| 2025 | $6,754 | **2.99** | 1.57 | n=1, HMM fit-2024 (fully clean OOS) | ✓ GO |

Floor = 2.38 (fit_A). 3 năm dương liên tiếp: 2023 +$8k / 2024 +$6k / 2025 +$6.7k.

**Verdict KHÔNG đồng nhất theo sleeve:**
- **Rổ4 swing-TF**: 642 trades OOS → **GO** ✓ (robust OOS, statistically meaningful)
- **NKD**: 201 trades OOS → **GO** ✓ (đủ OOS, budget thoải mái)
- **STRESS_MID**: 7 trades OOS 2025 (−$44) → **WEAK-BET / OOS-pending-bear**
  - IS 2022: +$6,632 nhưng 1 event; bootstrap p=0.112 không-significant
  - Deploy vì asymmetry: phí $0–44/năm calm, hedge bear tiềm năng

Sealed: `vault_2023_2024_result.txt`, `vault_2025_result.txt`. Không re-run.

---

### AN TOÀN — 16 cơ chế + bugs fixed

**16 cơ chế an toàn** (grep-verified): E1 PID lock, D5 STOP_FILE, C3 empty bars warn, E3 clock skew, C1 signal_fn fail-CLOSED, C4 per-cluster isolation, J2 cache clear, C2 stale_guard fail-CLOSED, G1 HARD/SOFT SPY stale, G2 model age warn, G3 refreeze coverage abort, CircuitBreaker HALT/HALT_DAY, MultiClusterGuard admits, F3 fat-finger.

**Bugs fixed kỳ này (session 2026-07-08):**

| Bug | Severity | Fix | Proof |
|---|---|---|---|
| H4: HALT_DAY mù intraday (I4.6) | HIGH | broker sync sau CLOSE loop | T29 PASS |
| I4.8: exit orphan nếu CLOSE fail | HIGH | Fill.status + exit_pending + retry | T30 PASS; IBKR test pending (A1) |
| Zone 4: NaN risk_sized bypass cap (I4.9) | HIGH | ValueError + 3-layer guard | 7 unit tests PASS + reconcile |
| Silent HMM exception (I4.10) | MEDIUM | logger.error + reconcile proof | Reconcile 0 mismatch |
| ATR=0 chandelier guard (I4.11) | MEDIUM | da > 0 guard | Reconcile 0 mismatch |

---

### BUG SWEEP — 6 cách quét, offline cạn cơ sở mạnh

| Sweep | Cách quét | Kết quả |
|---|---|---|
| 1–3 (5 zone) | REGIME / SIGNAL / DATA / NUMERICAL / MULTI-DAY | 2 bug fixed (Zone 4 + 2 protected edges) |
| 4 | Fuzzing (15 scenarios) + Interaction + Adversarial | 0 HIGH. F1 NaN 1m bars = MEDIUM-LOW |
| 5 | Config combo + Coverage + Reconcile-self-check + Long-run + Unexplored | 0 HIGH. real_risk NaN = LOW (diagnostic only) |

**F1 (MEDIUM-LOW, monitor)**: NaN trong 1m bars → chandelier stop propagates NaN → position holds đến MAX_HOLD. MAX_HOLD là backstop; clean CME data không trigger. IBKR-gated test.

**Còn lại**: IBKR-gated (fill/reconnect/clock skew thật/stale thật) — paper là test đúng nơi cho lớp này.

---

### SCALING — n=1 ceiling

**n=1 @ $50k: production config**, Calmar 2.744 ✓, floor 2.38 ✓.

**n=2: structural không thể hiện tại** — 3 điều kiện không đồng thời thoả:
1. Sizer auto-select n=2 cần account ~$58-59k (ước tính tự tham chiếu, chưa đo)
2. Calmar IS n=2 = 2.28 < floor 2.38 → gate fail
3. Cap = pct×account (fixed) → reject nặng hơn khi n×2 (structural)

Xem `docs/futures/SCALING_ANALYSIS.md` + `docs/futures/SCALING_PLAN.md` đầy đủ.

---

### CÔNG CỤ — Navigation

- `docs/futures/SYSTEM_MODEL.md`: 4-chiều model (Control Flow / Data Flow / Safety / State)
- `docs/futures/VISUALIZE.md`: ASCII 4 tầng
- `docs/futures/GLOSSARY.md`, `DECISIONS.md`, `ASSUMPTIONS.md`
- `docs/futures/SCALING_ANALYSIS.md` + `SCALING_PLAN.md`
- `docs/futures/IBKR_TODO.md`: thứ tự wire khi account available

---

### BLOCKER → PAPER

**Account APPROVED** (2026-07-08) → next: wire IBKR-gated → paper

Thứ tự implement (`IBKR_TODO.md`):
1. Wire `IBKRBroker._fetch_raw()` → test C6/C3/P2
2. Wire `IBKRBroker.send_order()` → test A1/A2/A3/A4 (fill/partial/reject/timing)
3. Wire `IBKRBroker.get_positions()` → implement B3 reconcile
4. Wire `_handle_rollover()` → roll cost, timing, contract_month field

Paper goals: đo fill time (30s entry / 5s exit), slippage thật vs 2-tick, fill rate, ≥1 Stress period live.

---

### GIỚI HẠN NHẬN THỨC (quan trọng — không skip)

1. **Reconcile = consistency, KHÔNG phải correctness.** Paper là correctness check thật tiếp theo.
2. **Offline sweep = reliable-enough-for-paper, không phải proven-profitable.** 6 cách quét, 0 HIGH, nhưng production always surprises.
3. **Real_risk NaN gap**: deploy_sim `real_risk()` không raise ValueError nếu ATR all-NaN (khác signal_layer). Diagnostic-only impact; live path đã có ValueError guard.
4. **Reconcile thiếu entry price**: 4-field check (day/exit_day/pnl/direction) — không check entry price. Shared bug → false PASS là structural limitation của self-consistency check.

---

## HISTORY — Milestones đã đóng

| Milestone | Ngày | Key |
|---|---|---|
| Baseline rebuild (CSV corrected) | 2026-07-06 | $52,936/2.744 ổn định |
| Vault 2023-2024 + 2025 sealed | 2026-07-06 | Rổ4+NKD GO (3.33/2.99) |
| Trust audit | 2026-07-05 | Tất cả số load-bearing traceable |
| Operational safety batch | 2026-07-07 | 123/123 PASS, 16 cơ chế verified |
| Re-freeze GĐ3 Phần A | 2026-07-07 | 76/76 PASS, refreeze.py + gate |
| HMM stale guards G1/G2/G3 | 2026-07-05 | 42/42 PASS |
| IBKRBroker skeleton | 2026-07-04 | 14/14 injection PASS |
| Bug sweep 1-5 | 2026-07-08 | 6 cách, offline cạn cơ sở mạnh |
| Scaling analysis + docs | 2026-07-08 | n=1 ceiling documented |
