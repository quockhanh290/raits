# Futures — DECISIONS
_Quyết định đã chốt + lý do + alternatives bị reject._
_Cập nhật: 2026-07-07_

Format: **Quyết định** | Why | Alternatives rejected

---

## Data

**Baseline = $52,936 corrected (vs $52,962 pre-correction)**  
Why: freeze-2017 spy_daily.csv bị lỗi dividend adjustment; corrected = Polygon source-of-truth. Delta $26 không material nhưng data phải đúng trước vault.  
Rejected: giữ freeze-2017 — inconsistent với live feed, prereq vault sai.

**CSV = Polygon corrected (vs freeze-2017)**  
Why: data correct + live consistency (live sẽ dùng Polygon real-time) + prereq cho vault 2025.  
Rejected: keep freeze — sai nguồn, sẽ cần sửa lại khi live.

**IBKR data only (không mua Polygon/Databento real-time)**  
Why: IBKR CME bundle cấp đủ historical + real-time. Tiết kiệm chi phí.  
Rejected: Polygon real-time — redundant khi IBKR đã cover.

---

## HMM / Regime

**Re-freeze ANNUAL tại year-boundary (vs freeze-when-data-available)**  
Why: so-sánh năm-qua-năm consistent; tránh overfit vào partial-year noise; gate label-change có ý nghĩa.  
Rejected: freeze khi data available — không có reference point để so sánh.

**fit_C (2024-12-31) là production baseline**  
Why: most recent full-year fit, 17.16% A→C flip là justified (83/101 Normal→Stress trong 2020+2022 bear markets).  
Rejected: giữ fit_A — stale, underestimates Stress.

**Degradation floor = Calmar 2.04 (fit_A, frozen_2024, no-stress, 2-tick)**  
Why: conservative floor — fit_A (fit-2022) là worst-case retrain đã observe; no-stress vì with-stress floor (2.54) > baseline with-stress (2.50) = inverted (lý do: fit_A label nhiều Stress hơn → IS P&L cao hơn bằng STRESS_MID, không phải core system tốt hơn). 2-tick = production slippage convention. floor/baseline ratio = 85.7% (2.04/2.38) ổn định.  
Rejected: floor từ fit_C (2.50/2.38) — baseline không phải floor; floor từ 1-tick (2.69) — không match production slippage; with-stress floor (2.54) — inverted logic.

**Giữ fit-2024 (hmm_fit_end=2024-12-31), KHÔNG refit gồm 2025 — 2026-07-09**  
Why: đo fit-2024 vs fit-2025 decode 2026 → 93.7% giống (118/126 ngày), chỉ 6.3% khác (8 ngày). 7/8 flip là Normal↔Calm (ít impact hành vi giao dịch); 1/8 là Stress→Normal (2026-04-06). Cải thiện MINIMAL — không bù được chi phí refit: mất OOS 2025 backtest (Calmar 3.42) + re-validate baseline/floor/vault. Decode-forward (fit cố định, gán nhãn ngày mới không retrain) là đủ cho paper regime 2026.  
Rejected: refit gồm 2025 — cải thiện 6.3% không đáng đánh đổi; refit định kỳ ("mỗi năm") — quán tính, không theo nhu cầu đo được.  
Measurement: `compare_refit_2025.py` (scratchpad, 2026-07-09); see LESSONS.md L11 cho refit criteria tổng quát.

**Deploy dùng `label_regimes()` (không dùng `regime_coordinator`)**  
Why: validated path qua toàn bộ reconcile chain; regime_coordinator là code path khác, chưa validate.  
Rejected: regime_coordinator — chưa chứng minh identical output.

**Gate re-freeze: AUTO_APPROVE <5%, VERIFY 5-15% / calm-flip>0, HOLD ≥15% / calm-flip>10**  
Why: calm↔stress flip là economically dangerous (regime inversion); cần human verify ngay cả khi % thấp.  
Rejected: gate chỉ dựa % đơn giản — miss calm-flip danger.

---

## Trade Execution

**Entry unfilled → SKIP (không chase/retry)**  
Why: trade lỡ < fill giá xấu. Backtest entry = open price; chase = deviation from backtest.  
Rejected: retry / chase — slippage accumulates, không match backtest assumption.

**Exit → MARKET order (không LIMIT)**  
Why: phải thoát khỏi position; slippage < kẹt position overnight.  
Rejected: limit exit — có thể không fill, kẹt position.

**Kill switch → dừng-entry-giữ-exit (không force-close-all)**  
Why: consistent với G1/E3 halt logic; force-close = kill PID, riskier.  
Rejected: force-close-all — crash mid-trade có thể để position trạng thái không rõ.

---

## Sizing / Risk

**1 micro/instrument (không 2)**  
Why: through-cycle MaxDD với 2 micro = $3,810 (@$55,784; deploy_sim đo thật; cap reject giảm concurrent → 1.31× n=1, không 2×) = 6.8% DD OK. Nhưng Calmar n=2 IS = 2.28 < floor 2.38 → gate fail. Cần vault n=2 OOS riêng trước khi scale.  
Rejected: 2 micro từ đầu — Calmar IS fail, chưa vault n=2 OOS, root cause structural (cap/n mismatch).

**NKD hardcoded n=1 (không scale cùng Rổ4)**  
Why: risk budget 2% × $50k = $1,000; 1 MNKD ATR risk ≈ $437 < $1,000 OK; n=2 = $874 borderline và NKD volatility cao hơn Rổ4. NKD là overlay instrument — không nên scale song song cluster chính.  
Rejected: n=n_contracts (sizer auto) — n=2 khi Rổ4 scale sẽ vượt NKD budget; sizer không phân biệt cluster NKD vs Rổ4.

**Scaling n=2 threshold — tự tham chiếu, hội tụ ~$58-59k (vs stale $82k)**  
Why: `scaling_dd_trust.py` (ee75963) tính dùng MaxDD@$50k ($2,657) → ra $55,784. Nhưng tại account $55,784, MaxDD thực = $2,908 → dd_scale=1.92 < 2.0 → sizer vẫn chọn n=1. Threshold đúng giải hệ tự tham chiếu `account = 20 × MaxDD_1micro(account)`, hội tụ ~$58-59k (xem SCALING_ANALYSIS.md). Cần `deploy_sim --account 59000` để xác nhận chính xác.  
Rejected: giữ $82k — không có công thức.  
Note: $55,784 đúng hướng ($82k→giảm) nhưng sai giá trị (dùng MaxDD tại $50k, không tại chính $55,784).

**n=1 ceiling — không scale n=2 hiện tại**  
Why: ba điều kiện không đồng thời thoả: (1) sizer auto-select n=2 cần account ~$58-59k (ước tính, chưa đo chính xác); (2) Calmar IS n=2 = 2.28 < floor 2.38; (3) cap không scale với n — structural, capacity giảm 50% khi n×2. n=1 @ $55,784: Calmar 2.76 > 2.38 ✓, không có inconsistency.  
Rejected: scale n=2 ngay — IS Calmar fail, chưa vault n=2 OOS, root cause structural. Xem SCALING_ANALYSIS.md.  
Next: scale n=2 chỉ khi (a) vault OOS n=2 riêng (establish IS baseline + floor), hoặc (b) wire cap×n (cần vault mới), hoặc (c) thêm instrument (diversification thay concentration).

**`size_multiplier=0.5` tại 10% DD — CỐ Ý KHÔNG WIRE**  
Why: binary protection (0 hoặc full), không partial. Wire = phải re-validate WFO + vault toàn bộ.  
Rejected: wire half-size — re-validation cost quá cao, binary design đơn giản hơn.

---

## Architecture

**Operational state persist atomic (`.tmp` + `os.replace`)**  
Why: crash-safe — không corrupt `live_positions.json` nếu kill giữa chừng.  
Rejected: write-in-place — corrupt file khi kill mid-write.

**CircuitBreaker HALT không stateful (computed: `dd=(peak-cur)/peak ≥ 15%`)**  
Why: persist `peak_equity` đủ để recover đúng sau restart. Stateful flag = phải sync thêm.  
Rejected: halted bool flag — thêm state phải persist, thêm source-of-truth conflict.

**Events[] bounded 500 (UI)**  
Why: memory leak J2 lesson — unbounded list grows indefinitely.  
Rejected: unbounded — memory issue in long-running live session.

---

## Vault

**Vault dùng production config n=1 (`--n-contracts 1`, không auto-size)**  
Why: auto-size dùng period maxDD. Vault window calm (no COVID) → auto-n=3 ≠ production n=1 (COVID trong IS maxDD). n=3 → NKD budget vượt ($1,312 > $1,000) → NKD 0 trades → vault test config khác production. Vault cũ (n=3, NKD=0) SUPERSEDED.  
Rejected: auto-size trên vault period — không representative of production startup condition.

**HMM clean: fit trước test period (2023-2024 dùng fit-2022 / 2025 dùng fit-2024)**  
Why: HMM fit tới 2024 "thấy" 2023-2024 → label tối ưu → MaxDD nhỏ giả → Calmar 4.52 (contaminated) vs 3.33 (clean), inflation +1.19. P&L gần không đổi ($14,017 → $14,144); contamination là MaxDD artifact thuần túy.  
Rejected: fit-2024 cho vault 2023-2024 — contamination +1.19 Calmar đo được, không chấp nhận.

**Deploy full system gồm STRESS_MID (weak-bet / IS-bet)**  
Why: asymmetry — STRESS hibernates trong calm (phí $0), active chỉ trong Stress regime. Cost thực tế $0–44/năm. Mất hedge bear nếu bỏ. Logic đúng (regime-gated, round-number defaults, không tune 2022). OOS chưa proven nhưng phí ≈ 0 → không cần proven để giữ.  
Rejected: bỏ STRESS vì OOS yếu — chi phí bỏ (mất hedge bear asymmetric) > chi phí giữ ($44/năm).

**Vault verdict = Calmar > floor 2.04 (không điểm chính xác) + direction**  
Why: vault 1-2 năm, mẫu nhỏ → Calmar fragile. Floor 2.04 (fit_A degradation, 2-tick) làm ngưỡng hard; direction (3 năm dương: 2023 +$8k / 2024 +$6k / 2025 +$6.7k) là confirmation thứ hai. Biên rộng (3.08/3.35 vs floor 2.04) quan trọng hơn điểm chính xác.  
Rejected: Calmar ≥ 1.0 — không có basis từ degradation history; floor cũ 2.38 (1-tick) — không match production slippage convention 2-tick.