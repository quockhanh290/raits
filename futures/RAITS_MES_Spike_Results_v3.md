# RAITS — Futures Pivot Spike: Tổng kết v3

*Cập nhật lớn so với v2: swing TREND_FOLLOW được phát hiện là ENGINE ĐỀU đã validate trọn vẹn (mọi cổng), đảo ngược verdict "TF fail" sai trong v2 (v2 test nhầm TF dưới dạng intraday; production TF là swing giữ 5 ngày).*

---

## 1. Trạng thái hiện tại — HAI engine thật, bổ trợ nhau

Sau toàn bộ spike, RAITS-futures có **hai mảnh đã validate**, vai trò khác nhau:

| | swing TREND_FOLLOW (rổ) | STRESS_MID (rổ) |
|---|---|---|
| **Vai trò** | **ENGINE ĐỀU (core)** | sleeve stress (hedge) |
| **Validate** | Cổng 4 pooled WFO + Cổng 5 vault | Cổng 5 vault (không WFO được) |
| **Khi nào kiếm** | quanh năm (Normal+Stress) | chỉ bear/stress |
| **Tần suất** | ~340 trade/năm | ~5 trade/năm |
| **Ngủ đông** | Không | Có (0 trade 2023–24) |
| **Regime** | dùng chung HMM SPY của RAITS | dùng chung HMM SPY của RAITS |

Hai engine bổ trợ: swing TF kiếm đều trong trend; STRESS_MID thêm alpha khi bear (lúc swing TF có thể chững). Cùng dùng regime brain RAITS.

---

## 2. Engine chính: swing TREND_FOLLOW — đã qua MỌI cổng

### 2.1. Phát hiện & sửa sai

v2 kết luận "TF fail Cổng 4". **Sai** — v2 test TF dưới dạng intraday (đóng lệnh 15:55). Production TF là **swing**: `allow_swing_hold=True`, `max_hold_days=5`, chandelier trailing bằng daily-ATR (×3.0) chạy qua nhiều ngày. Test đúng dạng swing đảo ngược verdict hoàn toàn.

### 2.2. Kết quả validate đầy đủ

**Cổng 2 (edge, per-instrument):** ES PF 1.42, NQ 1.46, RTY 1.17, YM 1.10 — tất cả dương, profile CTA thật (WR 15–19%, thua nhỏ nhiều/thắng lớn ít).

> **LƯU Ý: tất cả số dưới đây đã tính GAP-FILL ĐÚNG** (mô hình stop bị gap xuyên qua ở ranh giới phiên thật — maintenance break/cuối tuần — trên data 24h continuous). Gap risk thật ≈ **14% haircut** (GAP ~4.7% số lệnh). HMM tái lập (seed ổn định, 520/627/112 lặp lại). Số cũ "lạc quan" (không gap-fill) cao hơn ~14-26% nhưng KHÔNG thực tế.

**Cổng 4 (pooled WFO, rổ as-a-whole, param chung mỗi fold, GAP-FILL ĐÚNG):**
| Rổ | Stitched Calmar 1× | 2× cost | fold dương |
|---|---|---|---|
| **4 index (ES+NQ+YM+RTY)** | **2.31** | **1.95** | **6/6** |
| ES+NQ | 2.21 | 1.91 | 5/6 |

Param chung (ema=30, mult=2.5) thắng 5/6 fold → ổn định, không overfit. **Rổ 4 thắng WFO** (2.29 > 2.21) + gấp đôi trade (1055 vs 521) → bền hơn qua chu kỳ.

**Cổng 5 (pooled vault, 2023–2024 chưa-đụng, param đóng băng, GAP-FILL ĐÚNG):**
| Rổ | Calmar | PF | net | 2023 | 2024 | YM |
|---|---|---|---|---|---|---|
| **4 index** | 3.21 | 1.83 | +$16,089 | +$10,391 | +$5,698 | **+$1,641 (dương)** |
| ES+NQ | 3.69 | 2.10 | +$14,287 | +$8,909 | +$5,378 | — |

**Cả hai năm dương, nhiều trade** → engine đều thật. **YM dương với gap-fill đúng** (số bug từng báo âm — sai) → rổ 4 hợp lệ, không cần bỏ instrument nào. ES+NQ vault cao hơn (bull 2023-24 hợp tech/NQ) nhưng WFO thấp hơn → rổ 4 bền hơn qua chu kỳ.

**Quyết định rổ: RỔ 4** (ES+NQ+YM+RTY) — WFO cao nhất, đa dạng, mọi instrument dương.

### 2.3. Đây là strategy ĐẦU TIÊN cả dự án qua WFO rolling đúng nghĩa
Mọi thứ khác chết Cổng 4 (intraday TF, ORB) hoặc không WFO được (STRESS_MID). swing TF qua *cả* WFO 6/6 fold *lẫn* vault OOS — bằng chứng mạnh nhất khả dĩ.

### 2.4. Portfolio GỘP 2 engine (swing TF + STRESS_MID) — validate cùng nhau

Full-history (2018–2024), 1 micro mỗi cái, gộp P&L thành một equity curve (đúng cái deploy):

| | Calmar | net | MaxDD | PF |
|---|---|---|---|---|
| swing TF một mình | 1.17 | $41,878 | $5,185 | 1.49 |
| **COMBINED 2 engine** | **1.28** | **$45,714** | **$5,185** | 1.50 |

**Diversification thật — STRESS_MID nâng Calmar (1.17→1.28) mà KHÔNG tăng MaxDD.** Đóng góp theo năm:

| Năm | swing TF | STRESS_MID | Bối cảnh |
|---|---|---|---|
| 2020 | +12,410 | −446 | COVID, swing gánh |
| 2021 | +4,650 | 0 | calm, STRESS ngủ |
| **2022** | **−232** | **+5,296** | **bear — swing gãy, STRESS_MID cứu** |
| 2023 | +10,391 | 0 | bull |
| 2024 | +5,698 | 0 | bull |

2022 là bằng chứng vàng: swing TF lỗ nhẹ trong bear, STRESS_MID kiếm +$5,296 đúng năm đó → 2 engine bổ trợ ĐÚNG TIMING (kiếm khác thời điểm, không trùng).

**Kỳ vọng đúng về STRESS_MID:** standalone kém (Calmar 0.23, lỗ vặt năm calm), nhưng trong portfolio là BẢO HIỂM RẺ — cứu năm bear, nâng combined Calmar. Phần lớn return từ swing TF; STRESS_MID làm mượt đường cong qua bear. Lưu ý: combined full-history 1.28 < WFO 2.31 vì trộn mọi năm + region tune; số neo deploy vẫn là WFO 2.31 (OOS).



---

## 3. Engine phụ: STRESS_MID — sleeve stress đã validate

- Cổng 2/3: ALPHA mọi index (MNQ PF 1.65 tốt nhất, beta −0.03, dương cả up/down months).
- Bootstrap: edge nhất quán giữa instrument (không phải may mắn lẻ).
- Cổng 4: **không WFO được** (Stress hiếm + dồn cục → 13-trade folds vô nghĩa).
- Cổng 5 pooled vault (2022): GO, +$5,033, 5/5 index dương.
- Bản chất: kiếm 82% từ bear-2022, breakeven COVID-2020, ngủ đông calm → **sleeve có-điều-kiện**, không phải engine đều.

---

## 4. Đã loại (kết quả âm = thành tựu)

| Hướng | Verdict |
|---|---|
| intraday TREND_FOLLOW | Loại (Cổng 4 Calmar 0.26, chết 2× cost) — *nhưng swing TF pass* |
| ORB | Loại (beta-suspect) |
| NORMAL_MID | Loại (dead-zone) |
| VWAP_MR | Loại (no edge) |
| Globex overnight | Ngõ cụt (random walk, no continuation) |
| Mean-reversion Calm/Normal | Ngõ cụt (Variance Ratio ≈ 1) |
| RTY/YM cho swing TF | Yếu hơn ES/NQ (per-instrument fail), nhưng đóng góp trong rổ |

**Phát hiện nền tảng:** intraday equity index ≈ random walk (VR ≈ 1 mọi regime). Edge tồn tại ở **(a) swing/multi-day trend** (quán tính đa ngày) và **(b) momentum-trong-Stress** — không ở intraday momentum thuần.

---

## 5. Foundation fixes (đã lock)

HMM `--hmm-fit-end` (Stress labeling ổn định) · regime SPY `--regime-csv` (instrument-agnostic) · cost auto-derive tick_value · "not converging" xác nhận KHÔNG phải bug (dao động LL vi mô, stock cũng vậy).

---

## 6. Kỳ vọng return — TRUNG THỰC, gap-fill đã tính

Rổ 4, 1-micro-mỗi-cái: **~$8,000/năm** (sau gap-fill, nhất quán WFO + vault). Trên $50k:
- Sizing bảo thủ (1–2 micro, margin ~$5–10k): **~12–20%/năm trong năm trend-tốt**.
- **Lumpy, không đều:** năm trend cao, năm choppy có thể ~0 hoặc âm.
- **Trung bình qua chu kỳ (gồm năm xấu): ~10–15%/năm** *nếu* edge giữ live.

**Cảnh báo (đã cập nhật sau gap-fill):**
- Con số neo đáng tin = **WFO 2.31** (tick sàn đúng) (đã trừ gap risk ~14%), KHÔNG phải vault 3.18 (best-case bull 2023-24).
- Gap risk thật ≈ 14% haircut đã tính (GAP 4.7% số lệnh, xác nhận trên data 24h).
- Dữ liệu thiếu giai đoạn sideways-choppy dài (trend-following yếu nhất ở đó) — rủi ro chưa đo.
- Live thường thấp hơn backtest 20–40%. Đừng size đuổi 50%.
- Drawdown trần đã chốt **15%** → size để DD kỳ vọng ~10% (đệm cho live).

---

## 7. Kế hoạch incorporate vào RAITS (chi tiết mục dưới)

Engine RAITS hiện tại equities-only. Hai engine mới là futures-basket. Cách đúng: **module `futures/` song song, dùng chung `raits/hmm/`**, không nhồi vào engine cổ phiếu. Bước nền bắt buộc: **reconcile** adapter swing vs production engine (parallel-run, như DecisionUnit 604==604) trước tiền thật.

---



### 2.5. FULL SYSTEM backtest — 2 engine + risk layer (calibrate xong)

Khác 2.4 (chỉ gộp P&L), đây replay theo ngày QUA risk layer thật: mỗi entry qua circuit_breaker + net_exposure; entry bị chặn = bỏ thật. Budget TÁCH: swing TF (4 index) chịu net cap; STRESS_MID có budget sleeve riêng (không bị swing đẩy ra).

| Cap | Calmar | net | MaxDD | 2022 | entry chặn |
|---|---|---|---|---|---|
| **net 3.5% (mặc định)** | **1.34** | $45,709 | $4,927 | +$6,526 | 242 |
| net 5% (lỏng) | 1.27 | $45,714 | $5,198 | +$5,745 | 0 |
| net 8% | 1.27 | $45,714 | $5,198 | +$5,745 | 0 |
| naive (không cap) | 1.28 | $45,714 | $5,185 | +$5,064 | 0 |

**Kết luận:** net cap 3.5% gần như MIỄN PHÍ (mất $5 return) mà giảm MaxDD + nâng Calmar 1.28→1.34. Cap ≥5% không bao giờ bind (vô tác dụng). GIỮ cap 3.5% — KHÔNG phải vì 1.34 (in-sample, dễ overfit) mà vì nó là tail-guard gần-miễn-phí cho crash tương quan ngoài sample. Số neo deploy vẫn là WFO 2.31 (OOS); 1.34 chỉ nói "risk layer không hại, có thể giúp chút".

**Bug đã sửa trong quá trình:** STRESS_MID intraday (vào 10:15/ra 14:00 cùng ngày) bị replay cũ giữ trong open_pos mãi → tích lũy → lấp budget stress → chặn hedge 2022 (làm 2022 chỉ +$449). Fix: position same-day realize P&L ngay, không giữ qua đêm. Sau fix 2022 hồi về +$5-6.5k. (Lại một lần full-system test bắt bug mà combined không thấy.)


### 2.6. BETA vs ALPHA — swing TF deployed đo thật vs SPY

Hồi quy daily P&L của swing TF (rổ 4, 1 micro each) lên daily return SPY, 2018-2024:

| Metric | Giá trị | Đọc |
|---|---|---|
| **corr với SPY** | **−0.000** | tương quan ≈ ZERO tuyệt đối |
| beta | −11.9 $/1% | gần như không phụ thuộc hướng SPY |
| up-days net | +$25,800 (443 ngày) | kiếm khi SPY lên |
| **down-days net** | **+$16,220 (412 ngày)** | **kiếm khi SPY xuống (39% tổng)** |

**KẾT LUẬN: alpha-like, KHÔNG phải beta trá hình.** Hai bằng chứng quyết định: (1) corr ≈ 0 tuyệt đối — không có dấu vết equity beta tuyến tính; (2) down-days kiếm +$16k — beta thuần sẽ MẤT tiền những ngày này, việc kiếm được = short-side hoạt động thật, hai chiều. Hệ thống PASS beta-rejection test (dương cả up lẫn down, corr zero).

**Caveat (giữ nghi):** corr=0 là alpha SO VỚI SPY, KHÔNG phải uncorrelated với equity-trend nói chung. Nguồn return vẫn là "equity index CÓ trend để khai thác" — 4 instrument vẫn US equity, tương quan ~0.9 với NHAU (một nguồn alpha, không phải bốn). corr=0 có thể đẹp do data 2018-2024 có sẵn cả up-trend lẫn down-trend MƯỢT (2020 V-recovery, 2022 bear có trend); một năm sideways-choppy chưa test sẽ làm cả up lẫn down teo. Đây là tính chất CẤU TRÚC (corr, up/down split) nên khó bị bug thổi phồng hơn Calmar — đáng tin về bản chất, nhưng vẫn cần live xác nhận.

**Hệ quả cho non-equity:** nếu equity TF là alpha-like (corr 0, hai chiều), cùng edge trên non-equity (rates/commodities/FX) nhiều khả năng cũng alpha-like VÀ uncorrelated với equity → nhiều nguồn alpha độc lập = đa dạng hóa CTA thật. Baseline để so phiên sau: equity alpha, corr 0.

Tool: beta_check.py (regress daily P&L vs SPY return; up/down split).

## 7b. Trạng thái BUILD module futures (offline xong)

Module `futures/` tự chứa (chỉ import raits.hmm + tạm các script root đã validate). KHÔNG đụng engine stock.

| File | Trạng thái |
|---|---|
| cost.py | ✅ FuturesCost (tick sàn đúng) |
| basket.py | ✅ rổ 4 + param 30/2.5 + config risk (DD 15%/target 10%) |
| swing_tf.py | ✅ engine chính — reconcile PASS data thật (trade-for-trade) |
| stress_mid.py | ✅ sleeve stress (engine 2) |
| sizer.py | ✅ 1 micro/cái, DD-capped |
| net_exposure.py | ✅ trần net gộp 2 engine + 4 index tương quan |
| circuit_breaker.py | ✅ WARN 10% / HALT 15% / daily −4% |
| runner.py | ✅ orchestration đủ risk stack (3 stub IBKR) |
| reconcile_gd0.py | ✅ chứng minh engine == validated |
| backtest_combined.py | ✅ portfolio 2-engine (gộp P&L) |
| backtest_system.py | ✅ full system qua risk layer (cap configurable) |
| reconcile_stress.py | ✅ STRESS_MID entry_signal == adapter (PASS 4/4, 112 Stress days) |
| beta_check.py | ✅ beta/alpha đo thật (corr −0.000, alpha-like) |
| net_exposure.py | ✅ budget TÁCH swing/stress, cap 3.5% |

**Còn lại (cần máy + IBKR, không làm offline được):**
1. Cắm STUB 1: data feed live (Polygon real-time / IBKR).
2. Cắm STUB 2: order execution (ib_async, IB Gateway 7497, map MES/MNQ/MYM/M2K → ContFuture).
3. Cắm STUB 3: engine_signals = chạy backtest validate tới-hôm-nay, đọc action mới nhất (live == backtest by-construction).
4. PAPER TRADE vài tháng → đo edge/DD/slippage THẬT.
5. Scale 1→2 micro CHỈ sau khi paper xác nhận DD khớp.

## 8. Tools (production-ready, standalone read-only)

| Tool | Chức năng |
|---|---|
| `fetch_es_continuous.py` | Databento GLBX fetcher |
| `gate2_edge_harness.py` | Core lib: adapters, HMM, strategy×regime P&L; SPY regime, cost auto |
| `gate3_alpha_beta.py` | alpha/beta regression |
| `gate4_wfo.py` | rolling WFO + 2× cost, **+ `--swing` mode** |
| `gate5_vault.py` | one-shot vault |
| `swing_tf_harness.py` | swing TF backtest (multi-day chandelier, vectorized) + `backtest_swing_tf()` reusable |
| `pooled_swing_wfo.py` | **WFO rổ as-a-whole, shared param/fold** |
| `pooled_swing_vault.py` | **vault rổ swing, per-year breakdown** |
| `pooled_basket_verify.py` | per-episode + portfolio + bootstrap dispersion |
| `pooled_vault.py` | vault rổ STRESS_MID |
| `overnight_explore.py` / `mean_reversion_explore.py` | characterization (random-walk proofs) |
| `debug_vault_labels.py` | chẩn đoán 0-trade vault |

---

*Trạng thái: engine đều (swing TF rổ) validated trọn vẹn — kết quả lớn nhất dự án. Bước tiếp: reconcile adapter vs production → incorporate module futures → sizing → paper trade IBKR.*
