# Futures — ARCHIVE LOG
_Di chuyển thực hiện: 2026-07-06. KHÔNG xóa — reversible._
_Tất cả file nằm trong `_archive/superseded/` hoặc `_archive/answered/`._

Format: **Script** | Nguồn | Đích | Lý do | Thay thế bởi

---

## _archive/superseded/ — Thiết kế cũ, có bản thay hoàn chỉnh

### `futures/backtest_system.py`
- **Đích:** `_archive/superseded/backtest_system.py`
- **Lý do:** Dùng 2-cluster NetExposureGuard (Rổ4 + stress) thời tiền-NKD. Comment trong file: "HARNESS: documents 2-cluster risk-layer stage." Thiết kế này đã bị supersede khi NKD được thêm vào.
- **Thay thế:** `global_index/combined_system.py` (design gate) → `global_index/deploy_sim.py` (primary backtest hiện tại)
- **Verify trước khi move:** Không có production file nào import `futures.backtest_system`. Chỉ `_archive/superseded/futures_runner_2cluster.py` import (đã archived).

### `futures/net_exposure.py`
- **Đích:** `_archive/superseded/net_exposure.py`
- **Lý do:** Old `NetExposureGuard` với 2 clusters. Chỉ dùng bởi `backtest_system.py`. Comment trong `futures/__init__.py`: "không re-export — live deploy dùng global_index/net_exposure_multi". Production dùng `MultiClusterGuard` (5 clusters: roska4_swing, roska4_stress, global_nkd, + mở rộng).
- **Thay thế:** `global_index/net_exposure_multi.py` (MultiClusterGuard)
- **Verify trước khi move:** Không có production file nào import `futures.net_exposure`. Chỉ `backtest_system.py` (đã moved cùng lúc) và `futures_runner_2cluster.py` (đã trong _archive).

---

## _archive/answered/ — Research one-shot, câu hỏi đã trả lời

### `global_index/combined.py`
- **Đích:** `_archive/answered/combined.py`
- **Câu hỏi:** "NKD naive-pool có cải thiện Calmar Rổ4 không?"
- **Kết quả:** GO — NKD thêm giá trị ngay ở naive pool level.
- **Lý do archive:** Câu hỏi đã trả lời. `combined_system.py` trả lời câu quan trọng hơn (có risk layer). `deploy_sim.py` là tool backtest hiện tại. Không cần chạy lại trừ có câu hỏi mới về naive pool.

### `global_index/combined_system.py`
- **Đích:** `_archive/answered/combined_system.py`
- **Câu hỏi:** "NKD + risk layer (MultiClusterGuard + CircuitBreaker) — pass deployment gate không?"
- **Kết quả:** GO — NKD survive risk layer. Xem kết quả trong file hoặc git log.
- **Lý do archive:** Gate đã pass. `deploy_sim.py` là tool tiếp theo cho vault/backtest. `combined_system.py` có thiết kế đơn giản hơn deploy_sim (không có --n-contracts, --hmm-fit-end, NKD fixed) — đã hoàn thành vai trò "gate".
- **Chú ý:** Không duplicate deploy_sim — thiết kế khác nhau, answered specific gate.

### `global_index/wfo.py`
- **Đích:** `_archive/answered/wfo.py`
- **Câu hỏi:** "NKD WFO: gated (theo regime) vs regime-agnostic — cái nào OOS tốt hơn?"
- **Kết quả:** Agnostic thắng → đây là thiết kế được deploy trong `deploy_sim.py` (NKD không filter theo regime, chỉ lag 1 day).
- **Lý do archive:** Decision đã được thực hiện và baked vào production design. Không cần chạy lại trừ có câu hỏi mới về NKD regime gating.

### `global_index/vault.py`
- **Đích:** `_archive/answered/vault.py`
- **Câu hỏi:** "NKD standalone vault (Gate 5) — pass không?"
- **Kết quả:** GO.
- **Lý do archive:** `deploy_sim.py` bây giờ cover full system vault (Rổ4 + NKD + STRESS_MID). Vault kết quả sealed: `vault_2023_2024_result.txt`, `vault_2025_result.txt`. `vault.py` chỉ test NKD standalone — đã bị supersede bởi full-system vault.

### `global_index/scaling_dd_trust.py`
- **Đích:** `_archive/answered/scaling_dd_trust.py`
- **Câu hỏi:** "Số $55,784 scaling threshold — traceable không? 2-micro MaxDD là bao nhiêu?"
- **Kết quả:** PARTIALLY CORRECT (ee75963). Formula đúng hướng, nhưng hai lỗi: (1) NKD bug — script scale NKD@n (deploy_sim hardcoded n=1); MaxDD inflate → $5,890 sai, đúng = $3,810 (deploy_sim re-run @$55,784). (2) Threshold self-referential — $55,784 tính MaxDD@$50k; tại $55,784 thực tế dd_scale=1.92<2 → sizer không upgrade; hội tụ ~$58-59k.
- **Lý do archive:** Claim partially superseded 2026-07-08. Xem SCALING_ANALYSIS.md cho analysis đầy đủ.

### `global_index/stress_mid_trust.py`
- **Đích:** `_archive/answered/stress_mid_trust.py`
- **Câu hỏi:** "STRESS_MID IS 2022 claim $6,632 — traceable không?"
- **Kết quả:** CONFIRMED (commit ee75963). Số $6,632 IS 2022 traced và verified.
- **Lý do archive:** Claim committed. Xem `FUTURES_TRUST_AUDIT.md` + ee75963.

### `global_index/hmm_flip_year_trust.py`
- **Đích:** `_archive/answered/hmm_flip_year_trust.py`
- **Câu hỏi:** "HMM A→C flip 17.16% — justified không?"
- **Kết quả:** CONFIRMED. 83/101 label changes concentrated in 2020+2022 (bear/volatile years). Flip không random — có fundamental basis.
- **Lý do archive:** Claim verified. Không có open question nào liên quan còn lại.

### `global_index/risk_diagnostic.py`
- **Đích:** `_archive/answered/risk_diagnostic.py`
- **Câu hỏi:** "Real risk$ per position thật sự là bao nhiêu? (vs notional)"
- **Kết quả:** ANSWERED. Dùng để re-calibrate cap threshold — dẫn đến thiết kế ATR-based real risk trong `MultiClusterGuard`.
- **Lý do archive:** Thiết kế cap hiện tại (ATR-based) baked vào `net_exposure_multi.py`. Câu hỏi không còn open.

### `global_index/hold_vs_entry_diagnostic.py`
- **Đích:** `_archive/answered/hold_vs_entry_diagnostic.py`
- **Câu hỏi:** "Tại sao MES vẫn open trong hầu hết reject events?"
- **Kết quả:** ANSWERED. Hold-time behavior vs entry-race race condition được hiểu rõ. Follow-up từ reject_diagnostic.
- **Lý do archive:** Behavior đã understood và incorporated vào thiết kế decide_day. Không có action item còn lại.

### `global_index/reject_diagnostic.py`
- **Đích:** `_archive/answered/reject_diagnostic.py`
- **Câu hỏi:** "22% reject rate — benign (cap doing job) hay biased (miss good trades)?"
- **Kết quả:** ANSWERED. Reject behavior hiểu rõ, benign.
- **Lý do archive:** Câu hỏi đã trả lời. Kết quả dẫn đến reject_value_diagnostic → priority_sweep.

### `global_index/reject_value_diagnostic.py`
- **Đích:** `_archive/answered/reject_value_diagnostic.py`
- **Câu hỏi:** "$ value của rejects — không chỉ count?"
- **Kết quả:** ANSWERED. Xác định được value của rejected trades → dùng để prioritize entry ordering.
- **Lý do archive:** Kết quả dẫn trực tiếp đến priority_sweep → risk-high-first design bây giờ trong `live_decision.py`.

### `global_index/priority_sweep.py`
- **Đích:** `_archive/answered/priority_sweep.py`
- **Câu hỏi:** "Reordering entries within cap có recover value không? Thứ tự nào tốt nhất?"
- **Kết quả:** YES — risk-high-first thắng. 3 orderings tested: random, risk-low-first, risk-high-first.
- **Lý do archive:** Decision baked vào `live_decision.py` entry sort (`entry_priority_key`). Xem `docs/futures/DECISIONS.md` cho rationale.
- **Chain:** `reject_diagnostic → reject_value_diagnostic → priority_sweep` → kết quả: risk-high-first trong production.

---

## Verify sau khi move

```powershell
# Không có production file nào import các scripts đã archive:
Select-String -Path "d:\raits\global_index\*.py","d:\raits\futures\*.py" `
  -Pattern "backtest_system|net_exposure\b|from global_index\.(combined|wfo|vault|scaling_dd|stress_mid_trust|hmm_flip|risk_diag|hold_vs|reject_diag|priority_sweep)" `
  -List
# Expected: no results (chỉ _archive/ files có thể match)
```

Kết quả verify: CLEAN — chỉ `_archive/` files reference các scripts đã moved.
