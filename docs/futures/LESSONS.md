# Futures — LESSONS
_Bài học meta từ quá trình build. Không phải convention — là lỗi thật đã gặp._
_Cập nhật: 2026-07-07_

> **Mục đích:** Tránh lặp lại cùng class of mistake. Mỗi lesson = 1 case thật đã xảy ra.

---

## L1 — Data tự-nhất-quán ≠ đúng-reality

**Case:** SPY CSV freeze-2017. Toàn bộ audit chain (reconcile_gd0, reconcile_stress, verify_runner_real) PASS với CSV cũ — vì audit so deploy_sim với runner, cả hai đều dùng cùng frozen CSV. Self-consistent ≠ correct.

**Bài học:** Consistency audit chỉ check "các component đồng ý với nhau" — không check "đồng ý với thực tế". Cần source-of-truth bên ngoài (Polygon, IBKR) để verify at boundary. Reconcile + deploy = consistency. Polygon source = reality. Cần cả hai.

**Fix pattern:** Verify mỗi input data source một lần với external ground-truth trước khi trust. Sau đó internal consistency là đủ.

---

## L2 — Completeness từ grep/trace, không trí nhớ

**Case:** SYSTEM_MODEL.md CHIỀU 3 liệt kê 16 cơ chế nhưng bảng intervention order bỏ sót C2. Không phát hiện cho đến khi grep verify tất cả mã (`B1/J2/G1/C2/...`) trong code thật.

**Bài học:** Danh sách viết từ trí nhớ luôn thiếu. Chỉ tin vào danh sách được build bằng grep/trace từ code. Pattern: write → grep verify → điều chỉnh.

**Fix pattern:** Với mọi "danh sách đầy đủ" → chạy grep verify trên code trước khi kết luận complete.

---

## L3 — Bug ẩn ở baseline, lộ khi thay đổi config

**Case:** Sizer auto-scale không phải bug khi n=1 (không cắn). Chỉ lộ khi vault dùng window calm → auto-n=3. Runner test với n=1 PASS; vault với n=3 FAIL vì NKD budget vượt.

**Bài học:** Một bug không manifest ở operating point không có nghĩa là không có bug. Cần explicit boundary test (khác config, khác window). Invariant phải pin operating condition, không chỉ đúng với default.

**Fix pattern:** Với mọi auto-computed param → explicit assert ở operating condition. `run_smoke_test.py:208` assert n_contracts==1 là đúng pattern.

---

## L4 — Estimate ≠ measurement (số từ snapshot vs số từ full run)

**Cases:**
- 2-micro MaxDD: claimed $9,854 (old pre-NKD) → $5,890 (scaling_dd_trust.py, NKD bug) → measured $3,810 (deploy_sim re-run @$55,784, 2026-07-08). Gap tổng: 61%.
- Scaling threshold: $82k (thủ công) → $55,784 (formula, dùng MaxDD@$50k) → ~$58-59k (ước tính tự tham chiếu, chưa đo; 2026-07-08). Mỗi bước: 47% → ~5%. [số cuối: sau deploy_sim --account 59000]
- STRESS_MID 2022: claimed $5,296 (cũ) → measured $6,632 (fit_C, stress_mid_trust.py).
- MaxDD fit_C: $5,185 (pre-NKD estimate) → $2,789 (actual baseline).

**Bài học:** Mọi số từ "estimate", "snapshot", "extrapolation" đều cần đo lại với config hiện tại trước khi dùng làm ngưỡng. Số stale dễ tồn tại hàng tháng.

**Fix pattern:** Mọi threshold/gate quantitative → trace về script chạy với config production. `ASSUMPTIONS.md` track số chưa đo. Số không có script traceable = cần đo.

---

## L5 — Khẳng định ≠ bằng chứng (vault "passed" nhưng contaminated/sai config)

**Cases:**
- Vault cũ: chạy với n=3 (sai config), NKD 0 trades, report PASS. Không phải pass thật.
- Vault với fit-2024 cho period 2023-2024: Calmar 4.52 — số đẹp nhưng inflate +1.19 vì contamination.

**Bài học:** Test pass không có nghĩa test đúng. Cần verify: (a) test config == production config, (b) HMM fit window không thấy test period, (c) metric không là artifact của sai setup. "Vault GO" chỉ có giá trị nếu setup đã được audit.

**Fix pattern:** Trước mỗi vault/OOS run: checklist setup (n=1, HMM fit boundary, spy CSV correct). Sealed result chỉ seal sau verify checklist — không chỉ sau số đẹp.

---

## L6 — Vault verdict tách sleeve (không kết luận GO cho toàn hệ)

**Case:** Vault 2023-2024+2025: Rổ4 GO (642 OOS trades), NKD GO (201 OOS trades), STRESS_MID WEAK-BET (7 OOS trades). Một verdict duy nhất "GO" ẩn đi sự không đồng nhất này.

**Bài học:** Với multi-strategy system, OOS verdict phải per-sleeve. Sleeve có OOS nhỏ (STRESS_MID: 7 trades) không thể confirm/deny; deploy as IS-bet với asymmetry argument, không phải "passed vault". Treat khác nhau trong monitoring (không panic nếu STRESS_MID âm trong calm).

**Fix pattern:** Vault report phải list trades/sleeve, verdict/sleeve. Không aggregate thành 1 verdict.

---

## L7 — Proof-path trước khi viết fact (no fabrication principle)

**Case:** Nhiều lần trong quá trình: số "likely" hoặc "probably" được viết ra mà không trace code. Ví dụ: "98.5% HMM stability" → thực tế 68% (30pp gap). "$82k scaling threshold" không có formula.

**Bài học:** Bất kỳ số nào viết trong doc phải trace về: (a) script committed, (b) file:line trong code, hoặc (c) test output. Nếu chưa trace → đánh dấu [cần đo] trong ASSUMPTIONS.md, không viết như fact.

**Fix pattern:** Rule: "không viết số nếu không có nguồn". ASSUMPTIONS.md = place holder cho số chưa verified. Mọi số move từ ASSUMPTIONS sang docs chính phải kèm script/commit.

---

## L8 — Rollback cần check validity, không chỉ order

**Case:** Rollback bug (I2.3): code rollback về "entry gần nhất trong history" mà không check `invalid` field. Entry anchor=2018 bug được đánh dấu invalid nhưng rollback vẫn pick nó lên.

**Bài học:** State machine có "undo" cần biết phân biệt "undo về state hợp lệ gần nhất" vs "undo về state gần nhất". Rollback ≠ undo last write.

**Fix pattern:** Mọi rollback/undo mechanism → "last valid" không phải "last written". Check validity condition trước khi promote.

---

## L9 — Contamination qua MaxDD, không qua P&L

**Case:** HMM contamination (I2.2): P&L gần không đổi ($127 delta) nhưng Calmar inflate 1.19 vì MaxDD giảm giả từ "optimal labels". Nếu chỉ check P&L → miss contamination.

**Bài học:** Contamination ảnh hưởng metric phụ thuộc path (MaxDD, drawdown duration) nhiều hơn metric aggregate (total P&L). Kiểm tra contamination cần so sánh cả distribution of losses, không chỉ sum.

**Fix pattern:** OOS validation: luôn check cả P&L, MaxDD, và year-by-year breakdown. Số tổng đẹp có thể ẩn regime-specific artifact.

---

## L10 — Reconcile = consistency, KHÔNG phải correctness

**Case:** Sweep 5 (2026-07-08): reconcile 4× PASS 0 mismatch sau mỗi protected-file change. Nhưng reconcile chỉ so engine output vs harness output — nếu cả hai cùng có bug, reconcile PASS giả. Reconcile_gd0 kiểm tra 4 fields (day/exit_day/pnl/direction) — thiếu entry price. Pattern giống I1.1: SPY CSV audit pass vì dữ liệu self-consistent (frozen snapshot nhất quán nội bộ nhưng sai vs external reality).

**Bài học:** Reconcile PASS chứng minh: engine ≡ harness (đồng thuận). KHÔNG chứng minh: engine đúng. Correctness phải verify từ external source: vault OOS (historical holdout) hoặc paper (real fills).

**Fix pattern:** Khi cite reconcile làm evidence → luôn kèm caveat "consistency check, not correctness". Correctness = vault OOS + paper. Reconcile = regression guard (phát hiện change, không verify truth).

---

## L11 — Đo trước khi refit: data mới ≠ model cũ sai

**Case:** 2026-07-09: câu hỏi "refit HMM gồm 2025 không?". Cám dỗ tự nhiên: có data mới → nên refit. Nhưng đo fit-2024 vs fit-2025 decode 2026 cho thấy 93.7% giống nhau (8/126 ngày flip, phần lớn Normal↔Calm ít tác động). Refit sẽ tốn OOS 2025 backtest (Calmar 3.42 bằng chứng độc lập) cho 6.3% cải thiện decode.

**Bài học:**  
Refit trigger phải là *model cũ sai*, không phải *có data mới*.  
Ba điều kiện độc lập cần kiểm tra:
1. **Decode khác đáng kể?** (đo: fit-cũ vs fit-mới decode period hiện tại, ngưỡng ~15-20%)  
2. **Model cũ miss regime thật?** (so label với thực tế thị trường: rõ ràng Stress mà label Normal?)  
3. **Có OOS mới bù?** (paper/live 2026+ thay thế OOS period bị đưa vào fit)

Nếu không đủ 3 điều kiện → giữ model cũ. Decode-forward (model freeze, gán nhãn ngày mới) đủ tốt khi market regime không đổi chất.

**Chi phí refit (luôn ghi rõ trước khi quyết):**
- Period đưa vào fit → thành in-sample → mất OOS evidence cho period đó
- Re-validate toàn bộ: baseline / floor / vault trên fit mới
- Rủi ro fit mới tệ hơn (new regime không well-represented trong training)

**Fix pattern:** Trước mỗi câu hỏi "refit không?" → chạy `compare_refit_*.py` (pattern từ scratchpad), đo % flip, so threshold 15-20%. Chỉ tiếp tục nếu flip đáng kể VÀ có OOS mới bù.

---

## L12 — Bug fetch/broker interface chỉ lộ khi chạy thật

**Cases (2026-07-13 — first real `update_ibkr_daily` run):**

1. **Splice anchor sai** (`_apply_splice_offset`): dùng `new_bars["open"].iloc[0]` = bar đầu tiên FETCH (18:00 Sunday, 6h trước splice thật 00:00 Monday). Globex move +808 pts trong window 6h đó → embedded vào offset → toàn bộ parquet post-splice shift +808 vĩnh viễn. Fix: `new_bars[new_bars.index > last_existing]["open"].iloc[0]` — bar đầu tiên SAU splice point thật. Confirm: gap=0.00 by construction, entry 53932→53124 (−808 exact).

2. **Dtype guard false positive**: `old_tail.equals(new_tail)` dtype-strict. Parquet stores volume int64, IBKR trả float64, concat upcast → `equals()` False dù values identical (`diff=[]`). Fix: cast cả hai `.astype("float64")` trước `equals()`. Precision safe: float64 exact tới 2^53 >> max volume.

3. **MYM exchange CBOT**: hardcode `exchange="CME"` cho tất cả instruments. MYM (Micro E-mini Dow Jones) là CBOT, không CME → IBKR reject "No security definition" → 0 bars. Fix: `_EXCHANGE = {"MYM": "CBOT"}` dict trong `_build_jobs()`.

**Lesson chung:** Ba bug đều tồn tại từ trước nhưng **không lộ trong backtest** (backtest đọc parquet sẵn, không fetch). Chỉ lộ khi `update_ibkr_daily` chạy thật với Gateway live. Offline test đủ cho logic — không đủ cho broker/data API interface.

**Fix pattern:** Code path chỉ chạy với service thật (IBKR, Polygon) → integration test với service thật sớm nhất có thể. Không assume offline test coverage đủ cho live interface. P0b dry-run tối thiểu trước khi dùng thật.

---

## Tổng hợp — Class of mistakes

| Class | Lessons |
|---|---|
| Data errors | L1 (self-consistency ≠ correctness) |
| Completeness gaps | L2 (grep verify), L6 (per-sleeve) |
| Config/environment | L3 (bug ẩn ở non-default), L5 (test config ≠ prod config) |
| Number hygiene | L4 (estimate ≠ measurement), L7 (no fabrication) |
| State machine | L8 (rollback = last valid, not last written) |
| Metric interpretation | L9 (contamination through path-dependent metrics) |
| Verification scope | L10 (reconcile = consistency, not correctness) |
| Model update | L11 (data mới ≠ model sai — đo trước khi refit) |
| Live interface | L12 (bug fetch/broker chỉ lộ khi chạy thật — splice/dtype/exchange) |
