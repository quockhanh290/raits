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
⚠️ Script scratchpad đó **chưa bao giờ được commit** → con số 6.3% không tái tạo được. Đã dựng lại và tái xác nhận 2026-08-15, xem entry dưới.

**TÁI XÁC NHẬN giữ fit-2024 — HOLD, không refit 2025-12-31 — 2026-08-15**  
Why: đo lại bằng `futures/compare_refit.py` (committed, có self-check, lưu kèm cơ sở đo). Cửa sổ L11 forward 2026-01-02..2026-08-13: **9/154 ngày khác = 5.84%** (ngưỡng L11 = 15-20%). Tái tạo gần chính xác lần đo 2026-07-09 (8/126 = 6.35%) — thêm ~6 tuần dữ liệu chỉ thêm **đúng 1 ngày** flip; phân rã trùng (8 Normal→Calm + 1 Stress→Normal, so với 7 + 1). Lần đo cũ chạy trên CSV TRƯỚC bản sửa 2026-08-13, lần này trên CSV đã sửa (có sụt giá tháng 3/2026) → bản sửa CSV **không lật kết luận**.  
Bằng chứng mạnh nhất là phân rã theo năm: flip rải đều **2-6% khắp 2018-2026**, không dồn vào 2025-2026 (2018=4.38%, 2022=5.58%, 2026=5.84%). Nếu fit-2025 học được điều gì mới về chế độ hiện tại thì flip phải tụ ở đuôi. Nó không tụ → đây là **nhiễu fit, không phải thông tin mới**.  
Rejected: refit 2025-12-31 — L11 điều kiện 1 trượt xa, và chi phí (2025 thành in-sample, mất vault 2025 làm bằng chứng OOS) không đổi.  
Measurement: `python futures/compare_refit.py` → `futures/compare_refit_report.{txt,json}`; basis: `spy_daily_live.csv` sha `0e3815c29df3d5b8` (2416 dòng, tới 2026-08-13), train_end 2018-01-01, n=3, commit `83ac849-dirty`.  
⚠️ Cùng lần chạy đó, `run_gate` trả **AUTO_APPROVE 3.87%** — tức pipeline re-freeze sẽ **tự động duyệt** đúng lần refit mà L11 nói không nên làm. Gate không có câu hỏi "có nên refit không"; nó chỉ hỏi "fit mới có khác đủ đáng sợ không". Xem CALMAR_PROVENANCE.md §3.1.

**SÀN NHIỄU: chênh lệch nhãn giữa hai `fit_end` KHÔNG phân biệt được với đổi random seed — 2026-08-15**  
Đo: `futures/measure_fit_noise.py`, 5 seed (42/1/7/123/2026), **cùng** `fit_end=2024-12-31`, 10 cặp.
`SC-FIDELITY` chứng minh bản chép vòng lặp == production (seed 42 → hash `b70204f002b1f717`, trùng `label_regimes` thật).

| Cửa sổ | nhiễu min | nhiễu trung vị | nhiễu max | tín hiệu fit-2024 vs fit-2025 |
|---|---|---|---|---|
| L11 (2026+) | 2.60% | **5.8442%** | 12.34% | **5.8442%** |
| gate (2019+) | 1.20% | 3.32% | **7.58%** | 3.87% |

Tín hiệu L11 trùng trung vị nhiễu **đến 4 chữ số thập phân** — không phải làm tròn: cùng mẫu số 154 ngày
và cùng **9 ngày** khác. Đổi `fit_end` 2024→2025 làm đổi đúng bằng số nhãn 2026 mà đổi seed 42→123 làm đổi.
→ Quyết định HOLD ở entry trên không chỉ "dưới ngưỡng" mà là **không mang thông tin nào**.

⚠️ **`GATE_AUTO_PCT = 5.0` nằm DƯỚI trần nhiễu 7.58%** trên chính cửa sổ gate. Hệ quả: chạy lại
**y hệt cấu hình cũ** với seed khác có thể ra verdict `VERIFY` (5-15%). Gate bắn được trên nhiễu thuần,
và ngược lại không phát hiện nổi thay đổi thật cỡ nhỏ. Ngưỡng 5% chưa bao giờ được neo vào sàn nhiễu.

Ghi nhận trấn an: A→C 17.16% (2026-07-02) vượt trần nhiễu 7.58% → quyết định nâng fit_C **vẫn đứng**.
Lưu ý hai phép đo khác cửa sổ (2019-2022 vs 2019+) và khác data → đây là dấu hiệu, chưa phải chứng minh.

Phân bố nhãn đổi theo seed đáng kể: Stress **253-321 ngày** (11.7%-14.8%), Calm 40.0%-44.3%.
Production ghim seed 42 qua `engine.RANDOM_SEED` — đúng cho khả năng tái tạo, nhưng chuỗi regime đang
chạy là **một lần rút** từ một phân bố khá rộng. Ảnh hưởng lên P&L CHƯA đo (cần deploy_sim từng seed).

**Cổng promotion đổi sang ĐO THEO CẶP + 3 thước đo; `CALMAR_FLOOR` 2.38 → 1.50 (chỉ còn là chặn thảm hoạ) — 2026-08-15**  
Đo: `futures/measure_seed_pnl.py`, 5 seed, CÙNG `fit_end=2024-12-31`, cơ sở ghim (frozen_sim, `--end 2024-12-31`, n=1, 2-tick, no-stress). `SC-ANCHOR` PASS — seed 42 tái tạo đúng $42,459 / Calmar 1.72 của INVARIANTS dòng 22.

| seed | net | Calmar | MaxDD | PF | Sharpe |
|---|---|---|---|---|---|
| 42 (production) | $42,459 | 1.72 | $3,574 | 1.48 | 1.67 |
| 1 | $42,319 | 1.71 | $3,574 | 1.48 | 1.65 |
| 7 | $41,699 | 1.69 | $3,574 | 1.48 | 1.67 |
| 123 | $40,633 | **1.57** | $3,744 | 1.47 | 1.63 |
| 2026 | $40,254 | **1.56** | $3,744 | 1.48 | 1.65 |

**2/5 seed rơi dưới `BACKTEST_CALMAR_FLOOR = 1.65`** — cùng một hệ, chỉ khác hạt giống. Sàn tuyệt đối không phân biệt được "hệ suy giảm" với "fit rơi vào cực trị địa phương khác".

**Phát hiện then chốt — hệ ổn định, thước đo mới là thứ nhiễu.** Calmar trải **9.47%** trong khi PF trải **0.68%** và Sharpe **2.42%**. Nguyên nhân có cấu trúc: `calmar = (net/năm)/maxdd_$`, mẫu số là **một ngày duy nhất**, và qua 5 lần chạy MaxDD chỉ nhận **hai** giá trị ($3,574 / $3,744) — hàm bậc thang. PF và Sharpe trung bình hoá trên mọi ngày.

Why (cặp): hai vế chạy cùng cơ sở và **cùng seed** nên nhiễu là common-mode và triệt tiêu. Nhiễu seed chỉ là vấn đề khi so với một hằng số lịch sử — đúng thứ cổng cũ đang làm.  
Why (3 thước): Calmar là thước nhiễu nhất trong ba, không được là phiếu duy nhất.  
Why (`PAIRED_TOL = 0.05`): suy từ quyết định đã có, không phải khẩu vị — fit_A floor / fit_C baseline = 1.65/1.72 = 95.9% (INVARIANTS dòng 23), tức mức sụt ~4.1% đã được chấp nhận. 5% là con số đó làm tròn.  
Why (`CALMAR_FLOOR = 1.50`): đặt **dưới** đáy nhiễu đo được 1.56 để không bao giờ bắn vì seed. Vai trò đổi từ cổng chính thành chặn thảm hoạ.  
Rejected: hạ sàn xuống dưới 1.56 rồi giữ nguyên cổng tuyệt đối — hết báo động giả nhưng cũng gần hết khả năng phát hiện; giữ Calmar làm phiếu duy nhất — số liệu cho thấy nó nhiễu gấp 4–14 lần hai thước kia.  
⚠️ `runner.BACKTEST_CALMAR_FLOOR = 1.65` (theo dõi suy giảm paper) **chưa đổi** — nó cũng nằm trong dải nhiễu và cần quyết định riêng.

**G2 đổi động từ: cảnh báo tuổi model trỏ vào PHÉP ĐO, không trỏ vào re-freeze — 2026-08-15**  
Why: `MODEL AGE URGENT — schedule re-freeze immediately` bắn mỗi ngày từ tháng thứ 19, trong khi đáp án đo được là "không refit". Cảnh báo mà phản ứng đúng là phớt lờ sẽ dạy người vận hành phớt lờ mọi cảnh báo. Đổi tiêu đề thành `MODEL AGE CHECK DUE` và nội dung trỏ vào **phép đo**. Ngưỡng 12/18 tháng **giữ nguyên** — vấn đề là động từ, không phải nhịp.  
**Bổ sung cùng ngày:** cảnh báo trỏ vào **cả hai** script, vì chúng trả lời hai điều kiện L11 khác nhau và cái này sạch không có nghĩa cái kia sạch — `compare_refit.py` (điều kiện 1: fit mới có decode khác không) **và** `detect_regime_miss.py` (điều kiện 2: nhãn còn khớp thị trường không). Bản đầu chỉ trỏ vào cái thứ nhất vì detector chưa tồn tại lúc đó; để nguyên là để lại một mắt xích đứt — điều kiện 1 **không thể** trả lời điều kiện 2, nó so HMM với chính HMM. Điều kiện 3 (có OOS mới bù không) không tự động hoá được nên chỉ nêu tên trong comment, không script hoá.  
Rejected: nới `G2_HARD_MONTHS` — che triệu chứng, mất luôn nhịp kiểm tra định kỳ; tắt G2 — mất cảnh báo thật khi model thực sự lạc hậu.

**Sàn nhiễu chốt bằng P95 trên 30 seed (thay vì max trên 5) — 2026-08-15**  
`measure_fit_noise.py --seeds <30 giá trị>`, 435 cặp, SC-FIDELITY PASS.

| cửa sổ | min | trung vị | p90 | **p95** | max |
|---|---|---|---|---|---|
| L11 (2026) | 0.00% | 3.90% | 9.74% | **11.04%** | 11.69% |
| gate (2019+) | 0.00% | 2.87% | 8.31% | **9.09%** | 10.03% |

Verdict đổi từ so với `max` sang so với **P95**: max của mẫu nhỏ là ước lượng đuôi tệ nhất.
Percentile dùng **nearest-rank**, không nội suy — nội suy trên mẫu nhỏ là bịa ra độ chính xác.

⚠️ **max ở đây KHÔNG phải trần thật.** Bộ 30 seed không chứa `123` và `2026` — đúng cặp sinh ra
12.34% ở lần chạy 5 seed. Gộp cả hai lần, **cực đại đã quan sát = 12.34%**.

Hệ quả: tín hiệu L11 **5.84% < P95 11.04%** → nằm trong nhiễu, xác nhận lại HOLD với thống kê
tốt hơn nhiều. `GATE_AUTO_PCT = 5.0` **thấp hơn P95 của chính cửa sổ nó dùng (9.09%)** — khẳng định
lại phát hiện cũ. Ngược lại, **ngưỡng L11 15–20% nằm TRÊN P95 → ngưỡng đó là hợp lệ**, không cần đổi.

**Detector cho L11 điều kiện 2 — `futures/detect_regime_miss.py` — 2026-08-15**  
Why: `compare_refit.py` so HMM với **chính HMM**; nếu cả hai fit cùng sai một kiểu, nó báo 0% và
mọi thứ trông ổn. Cần một thước không phải HMM.

Ba lớp, ghi rõ độ độc lập vì gọi nhầm là tự lừa mình:
- **Lớp A — độc lập thật**: HMM chỉ nhìn log-return + vol 5 ngày **trailing** (`features.py`), không
  bao giờ thấy tương lai. Nên hỏi: nhãn hôm nay có dự báo được vol **10 ngày tới** không? Đo bằng
  AUC vượt trội (dựa trên hạng, không ngưỡng).
- **Lớp B — KHÔNG độc lập**: vol trailing chính là feature của model → chỉ kiểm nhất quán, bắt
  sập/đảo trạng thái (kiểu hỏng của retrain 20260619).
- **Lớp C — độc lập yếu**: drawdown từ đỉnh 60 ngày, cùng chuỗi giá nhưng không phải feature.

**Neo IS 2018-2024 (bắt buộc, không đậu thì không phát verdict):**
- Lớp A **AUC = 0.8943** (n=265 Stress / 708 Calm) — *lần đầu HMM được kiểm chứng độc lập trong dự án*
- Lớp B đúng thứ tự: Calm 7.24% < Normal 15.13% < Stress 30.70%
- Lớp C: median drawdown Stress −9.10% vs Calm −0.30%

**Kết quả 12 tháng gần nhất: KHÔNG ĐÁNH GIÁ ĐƯỢC (thị trường chỉ vừa chạm).** 4 ngày Stress / 252.
Sụt sâu nhất −9.13% (2026-03-30), đúng 1 ngày chạm ngưỡng IS-Stress −9.10%, và model **có** bắn
Stress ở đó (lớp C AUC = 1.0 — cả 4 ngày Stress đều sâu hơn mọi ngày Calm).

Why bản phân tách: *"thiếu ngày Stress"* mơ hồ giữa **thị trường yên** và **model mù** — hai kết
luận đối lập, cùng một output. Script tách bằng drawdown (không phụ thuộc nhãn), ngưỡng lấy từ
median drawdown của chính những ngày IS gọi là Stress, **không bịa**.

**Không đặt ngưỡng suy giảm.** Chỉ tự kết luận ở hai trường hợp không cãi được: thứ tự bị đảo,
hoặc AUC ≤ 0.5. Một ngưỡng kiểu "giảm 15%" cần block bootstrap trên chuỗi tự tương quan — chưa làm.

**Trả lời "làm sao biết khi nào":** trigger tự động = **cửa sổ 12 tháng đầu tiên tích đủ ≥10 ngày
Stress**. Từ đó detector phát verdict thật. Không phải lịch, mà là dữ liệu.

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