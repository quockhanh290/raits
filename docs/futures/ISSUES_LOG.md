# Futures — ISSUES LOG
_Nhật ký mọi vấn đề đã address, theo nhóm. Nguồn verify: code thật / docs / commit._
_Cập nhật: 2026-07-07_

> **Nguyên tắc:** Mỗi entry ghi root cause + fix thật + nguồn verify. Không viết từ trí nhớ.  
> Mã [cần xác nhận] = chưa tìm thấy trong code/doc tại thời điểm ghi.

---

## NHÓM 1 — DATA INTEGRITY

### I1.1 — SPY CSV dividend bug (freeze-2017)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED |
| **Root cause** | `spy_daily.csv` là snapshot frozen lấy từ 2017, không refresh → thiếu 8 năm dividend adjustment. SPY trả 4 dividends/năm × 8 năm = **32 ex-div events** không được cộng dồn vào adjusted close. Log-returns trên ex-div ngày bị lệch (ví dụ: 2018-09-18 logret −0.09% trong adjusted nhưng giá drop ~$1.36 thật). |
| **Impact đo** | 80 HMM label changes, deploy delta **−0.05%** ($52,962 → $52,936). 21 vault trades bị ảnh hưởng label. |
| **Fix** | Chuyển sang Polygon `adjusted=True` fetch. `update_spy_csv.py` wired live. |
| **Bài học** | Audit pass trên data tự-nhất-quán (frozen data nhất quán với nhau nhưng không nhất quán với thực tế). Cần verify với external source, không chỉ internal consistency. |
| **Nguồn** | `_archive/scratch/pnl_impact_corrected.py` (32 ex-div list, 80 labels), `_archive/scratch/audit_spy_exdiv.py`; OPEN_QUESTIONS.md dòng 109; DECISIONS.md "CSV = Polygon corrected" |

### I1.2 — Live 4.2% divergence từ spy_daily.csv mismatch
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED (cùng fix với I1.1) |
| **Root cause** | Nếu live dùng Polygon real-time SPY nhưng deploy_sim dùng frozen CSV → regime labels khác nhau giữa backtest và live → P&L diverge. |
| **Fix** | Corrected CSV deployed; 0 divergence sau fix. |
| **Nguồn** | OPEN_QUESTIONS.md "Live 4.2% divergence" → RESOLVED |

---

## NHÓM 2 — HMM / REGIME

### I2.1 — Anchor=2018 bug trong refreeze
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED |
| **Root cause** | `refreeze_hmm()` dùng `anchor="2018-01-01"` (default cũ). Vì fit dùng anchored-expanding window bắt đầu từ anchor, anchor=2018 clips dữ liệu 2017 → HMM không thấy 2017 market regime → Calmar tính được **2.49** thay vì **2.744** đúng. |
| **Impact đo** | Calmar 2.49 vs production-correct 2.744 (+0.254 gap — đủ để pass/fail degradation threshold 2.38). |
| **Fix** | `anchor` đổi thành required param, `default="2017-01-01"` trong CLI. Entry anchor=2018 trong registry bị đánh dấu `invalid=True`. |
| **Nguồn** | `futures/refreeze.py:65` (anchor field), `:667` (default 2017-01-01); `futures/test_refreeze.py:554-556` (calmar:2.49, invalid:True); `docs/futures/INVARIANTS.md` dòng 28; OPEN_QUESTIONS.md dòng 110 |

### I2.2 — HMM contamination trong vault test
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED |
| **Root cause** | Vault 2023-2024 chạy với HMM fit tới 2024-12-31 (`fit-2024`). HMM "thấy" 2023-2024 trong training → labels tối ưu hoá cho test period → **MaxDD nhỏ giả** (không phải P&L tăng) → Calmar inflate. |
| **Impact đo** | Calmar **4.52** (contaminated) vs **3.33** (clean fit-2022 cho vault 2023-2024). **+1.19 Calmar inflate** — hoàn toàn qua MaxDD artifact, P&L gần không đổi ($14,017 → $14,144 delta $127). |
| **Fix** | Rule: **fit phải trước test period**. Vault 2023-2024 → HMM fit-2022. Vault 2025 → HMM fit-2024. |
| **Nguồn** | DECISIONS.md "HMM clean: fit trước test period"; OPEN_QUESTIONS.md dòng 118; STATUS.md vault table; `vault_2023_2024_result.txt` (sealed) |

### I2.3 — Rollback bug: pop history[0] không check invalid
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED |
| **Root cause** | `rollback()` trước fix: khi rollback, dùng `history[-1]` (hoặc pop cuối) mà không kiểm tra `invalid=True`. Nếu entry cuối là anchor=2018 bug entry (invalid), rollback về entry sai → bung Calmar 2.49 trở lại. |
| **Fix** | Thêm `invalid` field vào `FreezeRecord`. `rollback()` skip invalid entries, trả về valid entry gần nhất. Audit trail giữ nguyên (invalid entry không bị xóa). `from_dict()` backward-compat: entry cũ không có field → default `invalid=False`. |
| **Nguồn** | `futures/test_refreeze.py:534-596` (T12, 8 cases: T12.1-T12.8); OPEN_QUESTIONS.md dòng 111 |

### I2.4 — C2 thiếu trong intervention order diagram (doc bug)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED (doc) |
| **Root cause** | SYSTEM_MODEL.md CHIỀU 3 liệt kê 16 cơ chế nhưng bảng intervention order bỏ sót C2 (stale_guard fail → fail-CLOSED). |
| **Fix** | C2 thêm vào bảng CHIỀU 3 (giữa C4 và G1) trong cả SYSTEM_MODEL.md và VISUALIZE.md. Verify code: `global_index/runner.py:446-460` — `entries_allowed = False` trong except → fail-CLOSED confirmed. |
| **Nguồn** | `docs/futures/SYSTEM_MODEL.md` CHIỀU 3 (updated); `docs/futures/VISUALIZE.md` (updated); `global_index/runner.py:446-460` |

### I2.5 — equity restart two-source (không phải bug)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | VERIFIED CORRECT |
| **Vấn đề** | state.equity và broker.get_equity() có diverge sau restart không? |
| **Kết luận** | Correct by design: (1) cả hai nhận cùng delta pnl_sized mỗi CLOSE (live_decision.py:85 và :124 + broker.py:103); (2) restart: `state.equity = broker.get_equity()` → broker là source-of-truth; (3) `peak_equity` phải persist riêng (B1) vì broker không lưu historical peak. Không có bug. |
| **Nguồn** | `global_index/live_decision.py:85,124`, `global_index/broker.py:103`; docs/futures/SYSTEM_MODEL.md CHIỀU 4 |

---

## NHÓM 3 — SIZING / VALIDATION

### I3.1 — Sizer auto-scale: vault dùng n=3 thay n=1
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED |
| **Root cause** | `size_combined()` auto-size dùng period maxDD. Vault window 2023-2024 = calm period (không có COVID 2020 trong lookback) → auto-n=3. Production startup dùng full IS 2018-2024 có COVID → auto-n=1. Vault config ≠ production config → vault test không representative. |
| **Consequence** | Vault n=3 → NKD risk $1,312 > budget $1,000 → NKD guard reject → **NKD 0 trades trong vault cũ** — giả mạo. Vault result với n=3 superseded. |
| **Fix** | Pin `--n-contracts 1` explicit. Guard warning trong `deploy_sim` khi không pin. `run_smoke_test.py:208` assert `n_contracts==1`. |
| **Audit** | 3 confirmations production n=1: deploy_sim, run_smoke_test, signal_layer. |
| **Nguồn** | DECISIONS.md "Vault dùng production config n=1"; OPEN_QUESTIONS.md dòng 117; `global_index/run_smoke_test.py:208-209` (assert n_contracts=1 PASS); INVARIANTS.md dòng 31 |

### I3.2 — NKD sizing: gán n_contracts cùng Rổ4 (open)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | PARTIALLY FIXED — không cắn n=1, OPEN khi scale |
| **Root cause** | `deploy_sim` cũ gán `contracts_by[NKD] = n_contracts` (cùng Rổ4). Không ảnh hưởng n=1 (risk ~$437 < budget $1,000). Nhưng khi n≥2: NKD risk $875-1,312 → vượt hoặc borderline budget → sai. |
| **Fix hiện tại** | `deploy_sim.py:254-257`: `contracts_by[NKD] = 1` hardcoded. Scaling projection script cần audit riêng. |
| **Còn open** | `scaling_dd_trust.py` cần verify NKD giữ n=1 khi Rổ4 scale (audit trước khi quyết định scale). |
| **Nguồn** | `global_index/deploy_sim.py:254-257` (NKD fix, comment); OPEN_QUESTIONS.md dòng 74-82 |

### I3.3 — Stale scaling threshold $82k
| Trường | Nội dung |
|---|---|
| **Trạng thái** | CORRECTED (2026-07-08: second-order correction) |
| **Root cause** | Threshold $82k để scale 1→2 micro không có formula derivation — số thủ công với 47% buffer không rõ nguồn. |
| **Đo lại (ee75963)** | `scaling_dd_trust.py`: force n=2 IS run. 2-micro MaxDD = $5,890. Formula n × MaxDD ≤ 20% × $50k → threshold $55,784. ⚠️ NKD bug: script scale NKD@n (sai; deploy_sim hardcoded n=1) → MaxDD inflate nhẹ. |
| **Đo lại (2026-07-08)** | deploy_sim re-run n=2 @ $55,784: MaxDD = **$3,810** (không phải $5,890). Threshold tự tham chiếu: tại $55,784 dd_scale=1.92 < 2.0 → sizer vẫn n=1. Hội tụ ~**$58-59k** (xem SCALING_ANALYSIS.md). |
| **Nguồn** | SCALING_ANALYSIS.md; `_archive/answered/scaling_dd_trust.py` (ee75963) |

### I3.4 — Vault verdict: không đồng nhất theo sleeve
| Trường | Nội dung |
|---|---|
| **Trạng thái** | DOCUMENTED (không phải bug — design clarification) |
| **Nội dung** | Vault GO không có nghĩa toàn bộ hệ GO đồng nhất. Rổ4 (642 OOS trades): **GO** — robust OOS. NKD (201 OOS trades): **GO** — đủ sample. STRESS_MID (7 OOS 2025, −$44): **WEAK-BET / OOS-pending-bear** — IS-2022 mạnh nhưng 1 event; bootstrap p=0.112. |
| **Quyết định** | Deploy full system vì asymmetry: STRESS_MID phí $0 khi calm, hedge bear tiềm năng. OOS evidence accumulates in next bear. |
| **Nguồn** | `docs/futures/STATUS.md` vault verdict table; DECISIONS.md "Deploy full system gồm STRESS_MID" |

---

## NHÓM 4 — OPERATIONAL SAFETY

### I4.1 — 16 cơ chế an toàn: grep-verified, documented
| Trường | Nội dung |
|---|---|
| **Trạng thái** | VERIFIED + DOCUMENTED |
| **Cơ chế (grep-confirmed)** | E1 PID lock (`runner.py:34,91`), D5 STOP_FILE (`runner.py:255,338,434`), C3 empty bars warn, E3 clock skew, C1 signal_fn fail, C4 per-cluster fail, J2 cache clear (`_validated_core.py` `_SWING_CACHE`), C2 stale_guard fail → entries_allowed=False, G1 HARD/SOFT SPY CSV stale (`hmm_stale_guard.py`), G2 model age warn, G3 refreeze data coverage (`refreeze.py`), CircuitBreaker HALT/HALT_DAY (`circuit_breaker.py`), MultiClusterGuard.admits, F3 fat-finger (`runner.py:511`) |
| **Phân loại** | batch-kill (E1/D5/G1 HARD/CB HALT/CB HALT_DAY), per-entry (C2/C4/G1 SOFT/F3/MultiCluster), alert-only (C3/E3/G2) |
| **Nguồn** | `docs/futures/SYSTEM_MODEL.md` CHIỀU 3; `docs/futures/VISUALIZE.md` Tầng C |

### I4.2 — WARN dead field: size_multiplier=0.5 không wire
| Trường | Nội dung |
|---|---|
| **Trạng thái** | INTENTIONAL — DOCUMENTED |
| **Chi tiết** | `futures/circuit_breaker.py:13-19`: comment rõ "INTENTIONALLY NOT WIRED". `status()` trả `level="WARN"` và `size_multiplier=0.5` khi DD≥10%, nhưng `decide_day()` không đọc `size_multiplier`. Hệ binary: full-size hoặc HALT. |
| **Lý do không wire** | (1) Binary đơn giản hơn, không cần re-validate WFO+vault với half-size; (2) WARN gần như unreachable vì HALT_DAY (4% daily stop) trigger trước WARN (10% portfolio DD) trong điều kiện thực tế. |
| **Nguồn** | `futures/circuit_breaker.py:13-19` (comment intent), `:74,78-79` (code); DECISIONS.md "size_multiplier=0.5 CỐ Ý KHÔNG WIRE" |

### I4.3 — Same-day order 3-phase: clarification
| Trường | Nội dung |
|---|---|
| **Trạng thái** | CLARIFIED (không phải bug) |
| **Câu hỏi** | Thứ tự OPEN/CLOSE trong same-day: "all-OPEN rồi all-CLOSE" hay nested? |
| **Xác nhận** | `global_index/runner.py:505-535`: Phase 1 = ALL exits (CLOSE). Phase 2+3 = **nested per-entry loop**: OPEN ngay lập tức CLOSE nếu same-day. Không phải all-OPEN rồi all-CLOSE. |
| **Nguồn** | `global_index/runner.py:505-535`; docs/futures/SYSTEM_MODEL.md CHIỀU 1 "run_day() execution tree" |

### I4.4 — B1 atomic state persist
| Trường | Nội dung |
|---|---|
| **Trạng thái** | IMPLEMENTED + TESTED |
| **Cơ chế** | `live_positions.json` chứa: open_positions + breaker.peak_equity + _day_start_equity + cur_day. Write qua `.tmp` → `os.replace` atomic. |
| **Lý do** | peak_equity không thể recover từ broker sau restart (broker không lưu historical peak). CircuitBreaker HALT = computed từ peak_equity — nếu mất peak → restart HALT-mù. |
| **Nguồn** | `global_index/runner.py` `_persist_state()`; `global_index/test_operational_fixes.py` (59/59 PASS); DECISIONS.md "Operational state persist atomic" |

### I4.5 — J2 cache clear: _SWING_CACHE bounded
| Trường | Nội dung |
|---|---|
| **Trạng thái** | IMPLEMENTED |
| **Cơ chế** | `futures/_validated_core.py` line ~197: `_SWING_CACHE = {}` cleared sau mỗi signal gen call. Ngăn memory leak trong long-running live process. |
| **Nguồn** | `futures/_validated_core.py` (`_SWING_CACHE`); `global_index/runner.py:424` (clear call); INVARIANTS.md "events[] bounded 500" (cùng pattern) |

### I4.6 — H4: HALT_DAY mù intraday (state.equity không sync trong live session)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED (2026-07-07) |
| **Root cause** | `state.equity` được khởi tạo từ `broker.get_equity()` tại construction nhưng chỉ được cộng `+= pnl_sized` trong `decide_day` (từ ledger backtest). Trong live mode, `pnl_sized=0.0` cho mọi lệnh → `state.equity` không đổi trong suốt session. `HALT_DAY` check trong `decide_day` dùng `state.equity` tĩnh này → `daily_loss_pct = 0%` mãi → không bao giờ fire. |
| **Impact** | **Không có phanh intraday trong live mode.** Mất 4% daily loss guard. Worst-case: tất cả clusters hit stop cùng ngày (STRESS_MID ~$1,250 + NKD ~$1,000 + swing ~$1,500) = ~$3,750 (7.5%) mà không bị chặn. HALT 15% cumulative vẫn hoạt động nhưng chỉ qua restart (overnight), không intraday. |
| **Fix** | Sau vòng lặp CLOSE (trước vòng lặp OPEN entries): `_h4_eq = self.broker.get_equity()` → nếu delta > $0.01: sync `state.equity = _h4_eq`, re-check breaker, nếu HALT_DAY: `decision.entries.clear()`. Trong verify mode (MockBroker): cả hai track cùng ledger pnl → delta ≈ 0 → no-op. Backwards-compatible. |
| **Residual gap** | STRESS_MID (same-session entry+exit): decide_day xử lý atomic trong một call, không có điểm để inject broker sync trước entry. Tác động thực tế nhỏ: STRESS_MID cần Stress regime + signal cụ thể, chỉ 1 entry/ngày. |
| **Classify** | HIGH severity. HALT_DAY là stated safety mechanism — live không có nó = chạy không phanh trong ngày. BẮT BUỘC trước IBKRBroker live. WARN dead (I4.2) là design decision; H4 là implementation bug. |
| **Nguồn** | `global_index/runner.py:509-529` (H4 fix location); `global_index/circuit_breaker.py:57-79` (HALT_DAY logic); `global_index/live_decision.py:95-117` (state.equity tĩnh); `global_index/test_operational_fixes.py` T29.1-T29.2 |

### I4.7 — C1-EXIT: thoát trễ 1 ngày nếu signal_fn throw trên exit day
| Trường | Nội dung |
|---|---|
| **Trạng thái** | KNOWN — LOW severity, accepted |
| **Root cause** | Khi signal_fn throw (C1 exception), runner bắt exception và set `exit_positions = []` (fail-CLOSED-entry, giữ exits đã pre-set). Nhưng nếu exit signal của ngày hôm nay chưa được set (vị thế cần chandelier stop HON NAY) → không có pre-set exit_day → runner không biết phải đóng → vị thế ở lại thêm 1 ngày. |
| **Impact** | 1-ngày exit delay. Ngày hôm sau signal_fn thành công → signal identifies position cần exit → đóng đúng. Không stuck vĩnh viễn. In practice: C1 (signal exception) rất hiếm gặp; chandelier stop thường được detect vào EOD sau khi bars có sẵn. |
| **Không fix** | C1 exception safety (T3) đã verify: pre-set exits (exit_day đã set từ ngày trước) vẫn chạy đúng khi signal throw. C1-EXIT chỉ ảnh hưởng case: (1) signal throw và (2) exit cần được identify HON NAY (not pre-set). Đây là edge case của edge case. Fix sẽ cần signal_fn chạy 2 lần hoặc cache last-good → cost > benefit. |
| **Nguồn** | `global_index/runner.py:446-460` (C1 exception catch, fail-CLOSED); `global_index/test_operational_fixes.py:T3` (pre-set exit verify); SYSTEM_MODEL.md CHIỀU 3 |

### I4.8 — Exit fail: position xóa khỏi state TRƯỚC CLOSE sent, Fill discarded
| Trường | Nội dung |
|---|---|
| **Trạng thái** | OFFLINE LOGIC DONE — IBKR test pending (A1) |
| **Root cause** | `decide_day()` xóa exit position khỏi `state.open_positions` (line 88) TRƯỚC khi `runner.py` gửi CLOSE order (line 505-508). Fill return value bị discard: `for p in decision.exits: self.broker.send_order(...)` — không có `f = ...`. Nếu IBKRBroker.send_order(CLOSE) fail/raise: (1) position đã mất khỏi state, (2) runner không biết (no status check), (3) không có retry (`exit_pending` không tồn tại — grep: 0 matches), (4) `_persist_state()` ghi state với position gone, (5) IBKR vẫn hold position → diverge vĩnh viễn. |
| **Fix (offline)** | (a) `Fill.status: str` field added. (b) fill.status check sau CLOSE → flag `exit_pending=True` trên OpenPos nếu "REJECTED"/"TIMEOUT". (c) `_retry_pending_exits()` runs đầu `run_day()` trước signal. (d) B3: `get_positions()` cross-check sau restart (chờ IBKR). T30 PASS. |
| **Còn pending** | A1 (real IBKRBroker fill/reject test). B3 cross-check không implement được đến khi IBKRBroker.get_positions() wired. |
| **Nguồn** | `global_index/runner.py:329-374` (`_retry_pending_exits()`), `:505-508` (Fill check); `global_index/live_decision.py:83-88`; `global_index/test_operational_fixes.py` T30; `docs/futures/BUG_SWEEP_R2.md` Cat 2 |

### I4.9 — Zone 4: NaN risk_sized bypass MultiClusterGuard cap
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED (2026-07-08) |
| **Root cause** | `_asof_naive()` trong `signal_layer.py`: nếu ATR series rỗng/all-NaN → `asof()` raise `IndexError` → fallback `median()` returns NaN → `risk_sized=NaN` → `NaN > cap_pct = False` → `to_candidate()` không reject → MultiClusterGuard.admits() bypass → oversized candidate pass qua → có thể OPEN > cap không ngờ. |
| **Attack path** | "Zone 4" trong sweep R2: numerical/NaN silent bypass. 3-layer chain: ATR empty → IndexError → NaN → cap bypass. |
| **Fix** | 3-layer guard: (1) `_asof_naive()` raise ValueError nếu empty/all-NaN thay vì median fallback. (2) `to_candidate()` explicit check: `if math.isnan(risk_sized): raise ValueError`. (3) Per-cluster C4 try/except trong `generate_today_signals()` bắt ValueError → skip cluster, không propagate. |
| **Proof** | 7 unit tests (T-NaN-1 → T-NaN-7) PASS + reconcile 4× 0 mismatch + baseline $52,936/2.744 không đổi. |
| **Nguồn** | `global_index/signal_layer.py` `_asof_naive()`, `to_candidate()`, `generate_today_signals()`; `global_index/test_operational_fixes.py` T-NaN series |

### I4.10 — Silent HMM exception: không log khi label fail
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED (2026-07-08) |
| **Root cause** | `_validated_core.py` `label_regimes()`: `except Exception: continue` — nếu HMM.predict() throw (bad day, NaN features, etc.), exception bị swallow hoàn toàn. Không có log → không phát hiện ngày bị skip → regime silent mismatch possible. |
| **Fix** | `except Exception as exc: logger.error("HMM label failed for %s: %s", pd.Timestamp(d).date(), exc); continue`. Không thay đổi control flow — exception vẫn bị bắt và continue, chỉ thêm logging. |
| **Proof** | Reconcile 4× 0 mismatch (control flow không đổi). Protected file edge — cần reconcile proof. |
| **Nguồn** | `futures/_validated_core.py` `label_regimes()` lines ~119-121; reconcile scripts 4× PASS |

### I4.11 — ATR=0: chandelier stop không fire khi ATR bằng không
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED (2026-07-08) |
| **Root cause** | `_swing_cache()` trong `_validated_core.py`: condition `if not np.isnan(da) and len(high)` — khi `da=0` (ATR bằng 0, e.g. ngày không biến động), condition TRUE → `hl[day] = (high, low, 0)` → chandelier stop = `pivot_high - 2.5 * 0 = pivot_high` → stop level = entry ngay lập tức → stop fire ngay. Hoặc reverse: tùy `da=0` semantics. Anycase: `da=0` không có ý nghĩa vật lý (range = 0 trong futures hiếm gặp) — cần guard. |
| **Fix** | `if not np.isnan(da) and da > 0 and len(high)` — skip ngày có ATR=0 (treat như missing ATR). |
| **Proof** | Reconcile 4× 0 mismatch (protected file — cần reconcile proof). Clean futures data không có ATR=0 trading days nên không ảnh hưởng baseline. |
| **Nguồn** | `futures/_validated_core.py` `_swing_cache()` line ~263 |

---

## NHÓM 4B — BUG SWEEP FINDINGS (sweep 4–5, 2026-07-08)

### F1 — NaN trong 1m bars: chandelier stop không fire
| Trường | Nội dung |
|---|---|
| **Trạng thái** | MEDIUM-LOW — KNOWN, monitor |
| **Root cause** | `_swing_cache()` builds `hl[day]` từ raw 1m arrays WITHOUT dropna. Nếu NaN xuất hiện trong high/low của 1m bars (bad tick, data gap): `stop_prev = high_prev - mult * da` → `NaN` → `low_bar <= NaN = False` → chandelier không fire → position giữ đến MAX_HOLD. MAX_HOLD là backstop (không infinite). |
| **Likelihood** | Clean CME futures data không có NaN OHLC. Trigger cần: bad tick hoặc data gap trong intraday bars từ IBKRBroker. |
| **Mitigation** | MAX_HOLD backstop (finite hold). Chưa fix vì: (1) clean data không trigger, (2) fix cần reconcile proof mới. Monitor khi IBKRBroker wired: log warning nếu NaN xuất hiện trong 1m bars. |
| **Nguồn** | `futures/_validated_core.py` `_swing_cache()` lines ~203-228; sweep 4 Góc 1 F1 |

### F2 — real_risk() trong deploy_sim: NaN fallback không raise
| Trường | Nội dung |
|---|---|
| **Trạng thái** | LOW — diagnostic-only, live path safe |
| **Root cause** | `deploy_sim.py:real_risk()` dùng `median()` fallback nếu ATR empty → trả NaN silently. Khác `signal_layer._asof_naive()` đã có ValueError guard (I4.9). NaN cap bypass có thể xảy ra trong deploy_sim replay nếu ATR series all-NaN. |
| **Impact** | deploy_sim là diagnostic script (không live path). Live path (`signal_layer.py`) đã có 3-layer guard từ I4.9. Deploy_sim result với NaN ATR không phản ánh live behavior. |
| **Không fix** | deploy_sim là replay harness, không production code. Sửa tách rời khỏi I4.9 fix tránh drift giữa 2 code paths. |
| **Nguồn** | `global_index/deploy_sim.py` `real_risk()` lines ~198-205; sweep 5 Góc 1 |

### F3 — Reconcile consistency limit (structural)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | KNOWN LIMITATION — documented |
| **Vấn đề** | Nếu engine và harness cùng có bug → reconcile PASS giả (0 mismatch). Reconcile chỉ check 4 fields (day/exit_day/pnl/direction) — không check entry price. Self-consistency ≠ correctness. |
| **Implication** | Reconcile PASS chứng minh consistency, KHÔNG chứng minh correctness. Correctness check là vault OOS + paper. |
| **Nguồn** | `futures/reconcile_gd0.py` (4-field check only); sweep 5 Góc 3; LESSONS.md L10 |

---

## NHÓM 5 — DESIGN CHỜ WIRE (IBKR-gated)

### I5.1 — Fill handling (entry-skip / exit-market / retry)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | DESIGN DONE — chờ IBKR |
| **Design** | Entry unfilled → SKIP (không chase). Exit → MARKET order (không LIMIT). Retry logic với block 265s worst-case. |
| **Nguồn** | DECISIONS.md "Entry unfilled → SKIP", "Exit → MARKET order"; ASSUMPTIONS.md (fill timeout, fill rate) |

### I5.2 — Rollover (C2) — code done, IBKR-gated
| Trường | Nội dung |
|---|---|
| **Trạng thái** | CODE-COMPLETE — chờ paper/P2 để verify với real IBKR fills |
| **Code verify (2026-07-16)** | `ibkr_broker.py:891-1044` — `_handle_rollover()` đã implement đầy đủ: CLOSE front-month, OPEN next-month, 3 nhánh Fill outcome. `runner.py:626-700` — `_handle_rollover_if_needed()`: SUCCESS/CLOSE-fail/OPEN-fail-FLAT logic verified. `test_rollover.py` RO1-RO6 viết và sẵn sàng chạy. ROLL_SCHEDULE 2026 verify RO5 (11 parametrized cases MES/MNQ/MYM/M2K/NKD). |
| **Gaps còn lại** | Xem I5.13 (persist OPEN-fail), I5.15 (contract_month TBD), I5.16 (real fills pending). |
| **Nguồn** | `global_index/ibkr_broker.py:891-1044`; `global_index/runner.py:626-700`; `global_index/test_rollover.py`; I5.13/I5.15/I5.16 |

### I5.3 — Kill switch D5 / Fat-finger F3
| Trường | Nội dung |
|---|---|
| **Trạng thái** | IMPLEMENTED trong runner — verify với live |
| **D5** | `runner.py:338,434`: STOP_FILE → entries halted, exits unaffected |
| **F3** | `runner.py:511`: max_contracts_per_order guard → block oversized order |
| **Nguồn** | `global_index/runner.py:255,338,434,511` |

### I5.4 — update_spy_csv look-ahead risk
| Trường | Nội dung |
|---|---|
| **Trạng thái** | OPEN — chờ runner timing decision |
| **Risk** | Nếu `update_spy_csv.py` chạy intra-session (khi run_day đang chạy) → có thể fetch close T (same day) → look-ahead 1 ngày cho regime T. |
| **Fix proposal** | Chạy update_spy_csv TRƯỚC khi khởi động runner, không intra-session. |
| **Nguồn** | OPEN_QUESTIONS.md "update_spy_csv timing look-ahead risk" |

### I5.5 — Databento re-fetch contamination (A5 in-place update mất frozen baseline)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | RESOLVED (2026-07-09) — frozen ground truth = $53,021 (clean Databento full-refetch) |
| **Root cause** | `update_futures_data.py` append mode thực hiện 2 thao tác: (1) shift toàn lịch sử bằng constant offset → ATR/P&L KHÔNG đổi (differences cancel); (2) **replace overlap window bars** (30 ngày) bằng new_adj từ anchor mới → bar-level giá Dec 2024 thay đổi → ATR14 cuối 2024 thay đổi → baseline drift $52,936 → $53,172 (+$236). |
| **A5 cụ thể** | 2026-07-08: `*_8y.parquet` update in-place qua Databento, overlap Dec 2024, không có frozen copy → ground truth mất. |
| **Fix baseline** | Re-fetch `--full-refetch --end 2024-12-31`. Frozen files: `data/cache/futures/*_frozen_2024.parquet` + `global_index/data/NKD_frozen_2024.parquet`. Staged tại `frozen_sim/` cho deploy_sim. |
| **Kết quả** | Net=$53,021 / Calmar=3.07 / MaxDD=$2,501. Run 2 = byte-identical (**REPRODUCIBLE**). $52,936 là incremental artifact (non-reproducible). $53,021 = ground truth thật. Fit_A floor trên frozen: $51,459 / Calmar=2.69 (thay thế stale 2.38). |
| **Live signal** | **STABLE**: `update_ibkr_daily.py` chỉ append new bars (không re-splice lịch sử). Rủi ro chỉ xảy ra khi chạy `update_futures_data.py` (Databento re-fetch). |
| **Quy tắc mới** | TRƯỚC BẤT KỲ `update_futures_data.py` nào: tạo frozen copy `*_frozen_YYYY.parquet`, verify baseline, sau đó mới update. |
| **Nguồn** | `global_index/update_futures_data.py` lines 87-108 (`_compute_splice_offset`), 210-235 (overlap replacement); đo 2026-07-09. |

### I5.6 — Live signal stability qua quarterly roll (IBKR ContFuture)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | VERIFIED STABLE — minor caveat documented |
| **Phân tích** | `update_ibkr_daily.py` append-only: (1) một lần duy nhất compute splice offset Databento→IBKR, lưu `_ibkr_splice_offsets.json`; (2) các lần sau apply stored offset uniformly cho new bars; (3) historical bars NEVER touched. → Signal ổn định giữa các lần Databento re-fetch. |
| **Quarterly IBKR roll** | IBKR ContFuture tự handle back-adjust khi contract roll (Mar/Jun/Sep/Dec). Stored splice offset áp uniformly cho tất cả new bars. Historical parquet không đổi. ATR14 có thể lệch nhẹ ~14 ngày sau roll do roll spread (~1-3 ES points) — chấp nhận được. |
| **Risk còn lại** | Chỉ xảy ra khi chạy lại `update_futures_data.py` (Databento re-fetch) không có frozen copy → xem I5.5. |
| **Nguồn** | `global_index/update_ibkr_daily.py` lines 119-133 (`_apply_splice_offset`), 236-253 (stored offset logic); phân tích 2026-07-09. |

### I5.7 — MYM exchange CME→CBOT (update_ibkr_daily)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED (2026-07-13) |
| **Root cause** | `_build_jobs()` hardcode `exchange="CME"` cho tất cả instruments. MYM (Micro E-mini Dow Jones) là CBOT, không CME → IBKR reject "No security definition" → 0 bars fetched. Chỉ lộ khi fetch thật với Gateway. |
| **Impact** | MYM không có bars mới từ ngày wire update_ibkr_daily. |
| **Fix** | `_EXCHANGE = {"MYM": "CBOT"}` dict trong `_build_jobs()`; các instrument khác default CME. |
| **Nguồn** | `global_index/update_ibkr_daily.py:63-70` (`_build_jobs`); committed 2026-07-13. |

### I5.8 — History invariant guard dtype false positive
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED (2026-07-13) |
| **Root cause** | `old_tail.equals(new_tail)` là dtype-strict. Parquet lưu volume int64, IBKR trả float64; `pd.concat` upcast → `equals()` False dù values identical. Log: "HISTORY INVARIANT VIOLATED — Rows with diff: []" (empty list = không có row nào thật sự khác). |
| **Impact** | Guard báo VIOLATED trên mọi append → không save parquet → false abort. |
| **Fix** | Cast cả hai về float64 trước `equals()`. Precision safe: float64 exact tới 2^53 ≈ 9×10^15, đủ cho volume (max ~10^9). |
| **Nguồn** | `global_index/update_ibkr_daily.py:287-294`; committed 2026-07-13. |

### I1.3 — Splice anchor sai: first-fetched bar ≠ first-new bar
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED (2026-07-13) |
| **Root cause** | `_apply_splice_offset` dùng `new_bars["open"].iloc[0]` = bar đầu tiên FETCHED (18:00 Sunday, 6h trước splice thật 00:00 Monday). Nếu market move đáng kể trong window đó (MYM: +808 pts Globex 18:00→00:00), toàn bộ move đó embedded vào splice offset như delta giả giữa Databento và IBKR. |
| **Impact đo** | MYM stored offset: +751 (wrong) vs correct: −57. Gap: +808 pts. Toàn bộ parquet từ 07/07 00:00 shift +808 pts vĩnh viễn. Entry từ backtest: 53932 (wrong scale) vs 53124 (correct, −808 exact). `_concat_live` mixed scale (07/07-07/11 = IBKR+751, 07/12+ = IBKR raw) → chandelier stop +808 sai. |
| **Fix** | `new_after = new_bars[new_bars.index > last_existing]` → lấy bar đầu tiên SAU splice point thật. Caller truyền `last_existing`. |
| **Data repair** | Truncate parquet → backup → delete `_ibkr_splice_offsets.json` → re-fetch "7 D". Kết quả: gap=0.00 all 5, frozen 23/23 intact, entry 53124 exact. |
| **Nguồn** | `global_index/update_ibkr_daily.py:120-142` (`_apply_splice_offset`); committed 2026-07-13. |

### I5.9 — update_ibkr_daily exits 0 khi instrument fail fetch
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED (2026-07-13, commit 8351fd6) |
| **Root cause** | Khi IBKR trả 0 bars (Gateway down, maintenance), instrument vào `failed` list nhưng script vẫn `exit 0`. Pre-flight không phát hiện failure (`returncode=0` → `ibkr_ok=True` → `_preflight_ok[today]=True`). live_day chạy trên parquet stale. |
| **Phân biệt** | `new_bars.empty` (IBKR trả 0 bars) → `failed.append` → **BUG: exit 0, phải exit 1**. `new_only.empty` (parquet đã có bars mới rồi) → "already up to date" → **ĐÚNG: exit 0, không failure**. |
| **Fix** | `sys.exit(1)` sau `print(f"COMPLETED WITH ERRORS: {failed}")`. Pre-flight `ibkr_ok=False` → `_preflight_ok[today]=False` → live_day skip. |
| **Nguồn** | `global_index/update_ibkr_daily.py:320-325` (exit block); committed 8351fd6. |

### I5.10 — Pre-flight fail-safe: chuỗi fix (in-memory flag → Branch 3 loophole)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED, fail-closed (commits 0f91fc9 → 030de83 → 90a7000) |
| **Root cause** | `_preflight_ok` in-memory: restart scheduler giữa 13:45-14:05 → flag=None → live_day skip oan. Attempt fix: Branch 3 `_parquet_is_fresh()` — check parquet date >= today. **Loophole**: chỉ kiểm parquet, không kiểm spy_csv. Crash sau ibkr_daily xong trước spy_csv → parquet fresh, spy stale → Branch 3 chạy live_day với regime labels cũ. |
| **Chuỗi fix** | (1) `0f91fc9`: thêm pre-flight 13:45 với fail-safe. (2) `030de83`: Branch 3 (parquet-only check). (3) `90a7000`: xóa Branch 3 → fail-closed: chỉ chạy khi flag=True (cả hai bước confirmed). Restart → flag=None → skip. Trade-off có ý thức: skip oan (hiếm, 20-min window) vs run sai (không bao giờ). |
| **Trạng thái cuối** | 2 branch: flag=True→run; flag=False/None→skip. Không còn loophole. |
| **Nguồn** | `global_index/run_scheduler.py:53-57` (comment), `139-171` (job_live_day); `L13` trong LESSONS.md. |

### I5.11 — --print-signals cutoff midnight: không bars 14:00-15:55 (bỏ sót khi LIVE_RUNNER_AUDIT)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | CODE-COMPLETE / CHƯA VERIFIED (chờ P0c chạy bars thật) |
| **Root cause** | `--print-signals` dùng `fetch_bars(through=today)` where `today = normalize() = midnight`. Commit gốc 5f0cc7f5 viết khi signal_fn là Option B (pre-computed timeline lookup, bars ít quan trọng). LIVE_RUNNER_AUDIT đổi signal_fn sang Option C (`generate_today_signals` dùng live bars), đồng thời fix runner.py `_through = day+23:59` (Mismatch B). Nhưng `--print-signals through=today` không được sửa theo → midnight cắt toàn bộ bars RTH hôm nay. Hệ quả: `backtest_swing_tf` entry scan window `between_time("14:00","15:55")` cho today = EMPTY → không fire entry nào cho hôm nay, dù chạy lúc 14:10 hay 15:00. |
| **Impact** | P0b-B gate sai assumption: "4-field exact so `--print-signals` vs `desired_basket()`" không valid vì hai path dùng khác cutoff → khác bars → khác signal. P0c verify không thể thực hiện trước fix. |
| **Fix** | `run_live_day.py:272–273`: thêm `_ps_through = today + pd.Timedelta(hours=23, minutes=59)`, đổi `fetch_bars(through=_ps_through)`. Match `runner.py _through = day+23:59`. Sau fix IBKR cap `endDateTime` tại now → bars đến ~14:05 ET. |
| **Verify** | CODE-COMPLETE 2026-07-14. Chưa ✅ — cần P0c chạy `--print-signals` sau 14:10 ET, confirm output hiện `bars: MES✓Nb ... (N>0 bars hôm nay)` và có entry (nếu regime + signal fire). Bug data-fetch chỉ lộ khi fetch thật. |
| **Bài học** | Đổi signal_fn cần live bars → phải sửa MỌI `through` cutoff (run_day VÀ --print-signals), không chỉ run_day. Cùng pattern splice anchor/dtype: fix một chỗ, grep chỗ tương tự ngay. Khi LIVE_RUNNER_AUDIT viết "fix Mismatch B: through=day+23:59" → phải grep tất cả `through=today` để catch các chỗ dùng midnight cũ. |
| **Nguồn** | `global_index/run_live_day.py:270–275` (fix); `docs/futures/LIVE_RUNNER_AUDIT.md` (Mismatch B context); git blame :272 → 5f0cc7f5 (gốc) + f6dd232 (TZ refactor, không fix cutoff) |

### I5.12 — G1 HMMStaleGuard wire vào production
| Trường | Nội dung |
|---|---|
| **Trạng thái** | DONE (2026-07-16) |
| **Fix thực hiện** | (1) `run_live_day.py:77` — import `HMMStaleGuard`. (2) `run_live_day.py:338-350` — `FuturesRunner(..., hmm_stale_guard=HMMStaleGuard(regime_csv=a.regime_csv, fit_end=HMM_FIT_END))`. Dùng `a.regime_csv` (không hardcode) — `run_scheduler.py:195` default `spy_daily_live.csv`. (3) Docstring `hmm_stale_guard.py:24`: `spy_daily.csv` → `spy_daily_live.csv`. (4) `run_live_day.py:26,102-103` — usage + argparser help. |
| **Verify** | `test_hmm_stale.py` 42/42 PASS. Production path đọc `spy_daily_live.csv` thật: gap=0 ngày 2026-07-16, không block oan. |
| **Nguồn** | `global_index/run_live_day.py:77,338-350`; `global_index/hmm_stale_guard.py:24`; `global_index/test_hmm_stale.py` (42 PASS) |

### I5.13 — Persist gap rollover OPEN-fail: crash-window state nói dối
| Trường | Nội dung |
|---|---|
| **Trạng thái** | FIXED (2026-07-16) — reconcile required (đụng runner) |
| **Root cause** | `_handle_rollover_if_needed()`: nhánh OPEN-fail dùng `to_remove` deferred list → xóa state memory nhưng persist chỉ ở cuối `run_day()`. Crash-window: JSON còn position, IBKR FLAT → state nói dối lúc critical nhất. |
| **Fix** | Xóa `to_remove = []` pattern. OPEN-fail branch: xóa trực tiếp `self.state.open_positions` (memory) + `self._persist_state()` ngay + `continue`. `_persist_state()` early-return khi `_pos_path=None` (tests không bị ảnh hưởng). Logic đúng GIỮ NGUYÊN: CRITICAL emit / no-retry / "manual intervention" log. |
| **Persist giữa không xung đột cuối** | `_persist_state()` là atomic write (`.tmp` + `os.replace`). Persist giữa ghi state hiện tại (flat) → cuối run_day persist lại (state cuối) → idempotent, không mất data. |
| **Verify** | `test_rollover.py` RO3b: OPEN-fail → JSON file empty ngay (không chờ cuối run_day). PENDING: reconcile_gd0 + reconcile_stress (bắt buộc, đụng runner). |
| **Nguồn** | `global_index/runner.py:668-683` (fix); `global_index/test_rollover.py` RO3b |

### I5.14 — Persist gap _retry_pending_exits (LOW — idempotent)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | OPEN — LOW, fix chung với I5.13 |
| **Root cause** | `runner.py:517-562` `_retry_pending_exits()`: sau retry thành công, xóa position khỏi `self.state.open_positions` (line 546-548) nhưng KHÔNG gọi `_persist_state()`. Persist chỉ xảy ra cuối `run_day()`. |
| **Crash-window gap** | Crash sau retry nhưng trước cuối run_day: JSON vẫn có `exit_pending=True` → restart: _retry_pending_exits chạy lại → gửi CLOSE lần 2. |
| **Tại sao LOW** | CLOSE retry là idempotent: IBKRBroker gửi CLOSE lần 2 cho position đã đóng → broker reject/return status "not found" → fill.status="FAILED" → exit_pending stays True → retry lần 3 ngày sau. Không tạo duplicate position. Worse-case: một CLOSE reject thêm, sau đó position tự clear vì không tồn tại trong IBKR. |
| **Fix đề xuất** | Thêm `self._persist_state()` cuối vòng lặp retry (sau khi xóa position thành công) hoặc sau toàn bộ vòng lặp. Fix chung với I5.13. |
| **Nguồn** | `global_index/runner.py:517-562` (`_retry_pending_exits`); I5.13 |

### I5.15 — contract_month OpenPos: SUCCESS roll không update field (DOCUMENTED — chấp nhận)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | DOCUMENTED — chấp nhận, không sửa trước live |
| **Chi tiết** | `runner.py:685-697` SUCCESS branch: chỉ log slippage, không update `contract_month` trên OpenPos. Docstring ibkr_broker.py:906-911: "only the contract_month field (TBD in OpenPos) changes" — TBD acknowledged. OpenPos field `contract_month` chưa tồn tại. |
| **Tại sao chấp nhận** | Exit logic dùng `exit_day` và `pnl_sized` (không dùng contract_month). Sau roll, runner state không track contract cụ thể nhưng IBKR đã mở next-month — đủ để exit đúng. Operator inspect JSON không thấy contract_month nhưng không gây confusion functional. |
| **Nếu cần sau** | Thêm `contract_month: str | None = None` vào OpenPos, update trong SUCCESS branch. Low priority. |
| **Nguồn** | `global_index/runner.py:685-697`; `global_index/ibkr_broker.py:906-911`; `global_index/live_decision.py` (OpenPos) |

### I5.16 — PENDING Gateway: MAX_HOLD CLI live / rollover real fills / STP overnight
| Trường | Nội dung |
|---|---|
| **Trạng thái** | PENDING — chờ paper/P2, không làm trước live tiền thật |
| **MAX_HOLD CLI live** | `run_maxhold_exit.py:96` — script gọi `broker.connect()` TRƯỚC dry-run gate. Không thể offline test CLI path không có Gateway. Logic verify offline xong (MH1-MH6 PASS). Cần: paper Gateway + real position (hold ≥ 5d) để test CLI end-to-end. |
| **Rollover real fills** | `ibkr_broker.py:917-1044` live path dùng `ib.qualifyContracts + placeOrder`. Chưa chạy với real IBKR. Verify: (a) contract month mapping đúng (first paper roll event MES 2026-09-11), (b) fill timeout params (EXIT_FILL_TIMEOUT_SECS, ENTRY_FILL_TIMEOUT_SECS) thực tế, (c) roll slippage đo được. |
| **STP overnight survive** | GTC stop `outsideRth=True` (ibkr_broker.py:715-777): chưa verify qua TWS restart. Test cần: place stop trên paper, restart TWS, kiểm stop còn active. |
| **Thời điểm** | Paper phase P2. Không phải blocker cho P0c/P1. MAX_HOLD logic offline verified (test_maxhold.py MH1-MH6). |
| **Nguồn** | `global_index/run_maxhold_exit.py:96`; `global_index/ibkr_broker.py:715-777,917-1044`; `global_index/test_maxhold.py`, `global_index/test_rollover.py` |

---

## NHÓM 6 — DOCUMENTATION (session này)

### I6.1 — SYSTEM_MODEL.md + VISUALIZE.md (tạo mới)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | DONE |
| **Nội dung** | 4 chiều: Control Flow (run_day tree + annual refreeze), Data Flow (mạch đầy đủ), Safety (16 cơ chế + intervention order), State (categories + persist cycle + equity restart). 4 tầng ASCII visualization. Verify completeness via grep của tất cả mã (B1/J2/G1...). |
| **Nguồn** | `docs/futures/SYSTEM_MODEL.md`, `docs/futures/VISUALIZE.md` |

### I6.2 — CROSS_SYSTEM_FINDINGS.md (tạo mới)
| Trường | Nội dung |
|---|---|
| **Trạng thái** | DONE |
| **Nội dung** | 4 findings từ futures → classify common vs specific → verify stocks code. HMM contamination: CLEAN (stocks). Annual refreeze gate: GAP (stocks thiếu). State persistence: N/A (stocks paper-only). Adjustment: already tracked. |
| **Nguồn** | `docs/CROSS_SYSTEM_FINDINGS.md`; `docs/stocks/OPEN_QUESTIONS.md` (2 entries mới) |

---

## Index nhanh

| ID | Vấn đề | Nhóm | Trạng thái |
|---|---|---|---|
| I1.1 | SPY CSV dividend bug (32 ex-div) | Data | FIXED |
| I1.2 | Live divergence nếu CSV mismatch | Data | FIXED |
| I2.1 | Anchor=2018 bug → Calmar 2.49 vs 2.744 | HMM | FIXED |
| I2.2 | HMM contamination → +1.19 Calmar inflate | HMM | FIXED |
| I2.3 | Rollback không check invalid (T12) | HMM | FIXED |
| I2.4 | C2 missing diagram (doc) | HMM | FIXED (doc) |
| I2.5 | equity restart two-source | HMM | VERIFIED OK |
| I3.1 | Sizer auto-scale n=3 vault ≠ n=1 production | Sizing | FIXED |
| I3.2 | NKD sizing gán n_contracts Rổ4 | Sizing | PARTIAL (n=1 OK) |
| I3.3 | Scaling threshold $82k stale | Sizing | CORRECTED ~$58-59k (2x corr) |
| I3.4 | Vault verdict không đồng nhất | Sizing | DOCUMENTED |
| I4.1 | 16 cơ chế safety grep-verified | Ops | VERIFIED |
| I4.2 | WARN dead field size_multiplier=0.5 | Ops | INTENTIONAL |
| I4.3 | Same-day order phases 3-step | Ops | CLARIFIED |
| I4.4 | B1 atomic state persist | Ops | DONE |
| I4.5 | J2 cache clear _SWING_CACHE | Ops | DONE |
| I4.6 | H4: HALT_DAY mù intraday | Ops | FIXED |
| I4.7 | C1-EXIT: exit trễ 1 ngày nếu signal throw | Ops | KNOWN-LOW |
| I4.8 | Exit orphan khi CLOSE fail | Ops | OFFLINE DONE / IBKR pending |
| I4.9 | Zone 4: NaN risk_sized bypass cap | Ops | FIXED |
| I4.10 | Silent HMM exception no log | Ops | FIXED |
| I4.11 | ATR=0 chandelier guard | Ops | FIXED |
| F1 | NaN 1m bars: chandelier không fire | Sweep | MEDIUM-LOW / monitor |
| F2 | real_risk() deploy_sim NaN no raise | Sweep | LOW / diagnostic only |
| F3 | Reconcile consistency limit | Sweep | KNOWN LIMITATION |
| I5.1 | Fill handling design | Wire | PENDING IBKR |
| I5.2 | Rollover C2 wire | Wire | CODE-COMPLETE / IBKR-gated |
| I5.3 | Kill-switch D5 / Fat-finger F3 | Wire | PENDING VERIFY |
| I5.4 | update_spy_csv timing look-ahead | Wire | OPEN |
| I5.5 | Databento re-fetch contamination (A5 overlap replacement → $236 drift) | Data | RESOLVED ($53,021 / Calmar 3.07) |
| I5.6 | Live signal stability qua quarterly roll | Data | VERIFIED STABLE |
| I5.7 | MYM exchange CME→CBOT (0 bars fetched) | Wire | FIXED |
| I5.8 | History invariant dtype false positive (int64/float64) | Wire | FIXED |
| I5.9 | update_ibkr_daily exit 0 khi instrument fail (Gateway down) | Wire | FIXED |
| I5.10 | Pre-flight fail-safe chain: flag in-memory → Branch 3 loophole | Wire | FIXED (fail-closed) |
| I5.11 | --print-signals cutoff midnight → no bars 14:00-15:55 (bỏ sót LIVE_RUNNER_AUDIT B→C) | Wire | CODE-COMPLETE / chờ P0c verify |
| I5.12 | G1 HMMStaleGuard wire vào production | Wire | DONE (2026-07-16) |
| I5.13 | Persist gap rollover OPEN-fail: crash-window state nói dối | Wire | FIXED (2026-07-16) — reconcile pending |
| I5.14 | Persist gap _retry_pending_exits (idempotent) | Wire | OPEN — LOW, fix chung I5.13 |
| I5.15 | contract_month OpenPos SUCCESS roll không update | Wire | DOCUMENTED — chấp nhận |
| I5.16 | PENDING Gateway: MAX_HOLD CLI / rollover real fills / STP overnight | Wire | PENDING paper/P2 |
| I1.3 | Splice anchor wrong: iloc[0] fetched ≠ first-new-bar splice | Data | FIXED (+808 repair) |
| I6.1 | SYSTEM_MODEL + VISUALIZE docs | Docs | DONE |
| I6.2 | CROSS_SYSTEM_FINDINGS docs | Docs | DONE |