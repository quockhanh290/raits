# Futures — CALMAR PROVENANCE
_Xuất xứ và cơ sở đo của mọi con số Calmar đang được hardcode hoặc trích dẫn._
_Lập: 2026-08-15. Read-only audit — không sửa code nào khi lập tài liệu này._

> **Tại sao có file này.** Cùng một hệ thống đã cho ba con số Calmar hợp lệ (2.744 / 2.299 / 1.678)
> mà không con nào sai. `FreezeRecord` lưu `calmar` nhưng **không lưu cơ sở đo** — không slippage,
> không mốc cắt, không phiên bản code — nên 2.744 không tái tạo được **do thiết kế**.
> Hệ quả: cổng promotion của re-freeze đang so hai số khác cơ sở với nhau.
>
> File này **đóng dòng ⚠️ còn treo** trong [FUTURES_TRUST_AUDIT_TODO.md](../../FUTURES_TRUST_AUDIT_TODO.md)
> (2026-07-05): *"fit_A degradation floor | Calmar 2.38 | **unclear** — check verify_runner_real.py output"*.
> TODO đó đề đúng ngày 2.38 được hardcode vào `refreeze.py`, và chưa bao giờ được trả lời.
>
> Liên quan: [INVARIANTS.md](INVARIANTS.md) (số hiện hành), [DECISIONS.md](DECISIONS.md) (lý do chọn),
> [OOS_VALIDATION_LOG.md](OOS_VALIDATION_LOG.md) (bảng run gốc), [LESSONS.md](LESSONS.md) L11 (tiêu chí refit).

---

## 1. Chín trục làm Calmar đổi giá trị

Hai số Calmar chỉ so được với nhau khi **cả chín trục** giống nhau.

| # | Trục | Giá trị cũ | Giá trị hiện hành | Đổi từ | Nguồn |
|---|---|---|---|---|---|
| 1 | Slippage | 1-tick (default) | **2-tick/side** | 2026-07-09 | `deploy_sim.py:133` `default=1.0`; INVARIANTS dòng 21 |
| 2 | Data | parquet incremental (trôi mỗi ngày) | **`frozen_sim/`** | 2026-07-09 | INVARIANTS dòng 24–27 |
| 3 | Mốc cắt | replay tới ngày chạy | **`--end 2024-12-31`** | 2026-07-09 | INVARIANTS dòng 22 |
| 4 | Entry scan | look-ahead (retroactive) | **causal** | 2026-07-10 | INVARIANTS dòng 9 |
| 5 | MAX_HOLD exit | bar 0 = 00:00 ET | **09:30 ET** | 2026-07-11 | INVARIANTS dòng 13 |
| 6 | `global_nkd` cap | 2% | **6%** | 2026-08-04 | `net_exposure_multi.py:88`; commit `f8a1f13` |
| 7 | Regime CSV | `spy_daily.csv` (dừng 2024-12-31) | **`spy_daily_live.csv`** | — | INVARIANTS dòng 45–46 |
| 8 | Nội dung CSV | — | **+sụt giá cả rổ tháng 3/2026** | 2026-08-13 | SCRATCHPAD (bản sửa `REGIME_CSV`) |
| 9 | Stress sleeve | — | dòng floor là **no-stress** | 2026-07-09 | DECISIONS dòng 36 |

Trục 4, 5, 6 là **sửa code**: mọi số đo trước ngày tương ứng không so được với số sau, kể cả khi
lệnh chạy giống hệt nhau.

---

## 2. Bảng truy nguyên từng con số

### 2.1 `CALMAR_FLOOR = 2.38` — `futures/refreeze.py:53`

> **ĐÃ XỬ LÝ 2026-08-15** — giờ là `1.50` và chỉ còn vai trò **chặn thảm hoạ**; cổng chính
> là đo theo cặp trên 3 thước (`paired_verdict`). Phần dưới giữ lại làm hồ sơ truy nguyên.

| Trường | Nội dung |
|---|---|
| **Trạng thái** | ❌ **STALE — sai 5 convention.** Chưa bao giờ được sửa. |
| **Viết ngày** | 2026-07-05 21:59:09, commit `e773e3b`. `git log -S"CALMAR_FLOOR" -- futures/refreeze.py` → **đúng 1 commit** |
| **Comment trong code** | `# degradation floor from fit_A; do not promote below this` |
| **Cơ sở thật** | fit_A degradation floor đo **2026-07-02**: net **$47,838**, data **incremental**, **1-tick**, look-ahead, bar-0 exit, nkd cap 2%, `spy_daily.csv` |
| **Bằng chứng deprecate** | [DECISIONS.md](DECISIONS.md) dòng 128: *"floor cũ **2.38 (1-tick)** — không match production slippage convention 2-tick"* — viết **2026-07-09**, tức 4 ngày SAU khi hardcode |
| **Đương lượng hôm nay** | **1.65** (xem §2.3) |
| **Mức lệch** | Cổng đang siết chặt hơn **~44%** so với ý định của chính nó |

> ⚠️ **VA CHẠM SỐ — đây là cái bẫy đọc doc.** Có **hai run khác hẳn nhau** cùng làm tròn ra 2.38:
>
> | | Run mà refreeze lấy | Run trong INVARIANTS dòng 11 |
> |---|---|---|
> | HMM fit | fit_A (2022-12-31) | fit_C (2024-12-31) |
> | Vai trò | degradation **floor** | IS **baseline** |
> | Net P&L | $47,838 | $47,186 |
> | Slippage | 1-tick | 2-tick |
> | Data | incremental | frozen_2024 |
> | Nguồn | DECISIONS dòng 128 | [OOS_VALIDATION_LOG.md](OOS_VALIDATION_LOG.md) hàng **B1** |
>
> [DECISIONS.md](DECISIONS.md) dòng 37 từ chối **cả hai** làm floor:
> *"floor từ fit_C (2.50/2.38) — **baseline không phải floor**"*.
> Đọc "2.38" ở bất kỳ đâu mà không hỏi "run nào" là đọc sai.

### 2.2 `calmar: 2.7442784981765844` — `models/hmm/futures_freeze_registry.json`

| Trường | Nội dung |
|---|---|
| **Trạng thái** | ❌ **KHÔNG TÁI TẠO ĐƯỢC** — và không phục dựng được cơ sở từ chính bản ghi |
| **Ghi lúc** | `frozen_at` = 2026-07-06T16:48:35Z; commit `5d137b2` (2026-07-08 15:13:01) |
| **Xác nhận** | commit message của `5d137b2`: *"reconcile 4x 0-mismatch + **baseline 52936/2.744** unchanged"* |
| **Cơ sở** | Sinh bởi chính `run_verify`: **2-tick** (`refreeze.py:360` hardcode `SLIPPAGE = 2.0`), n=1, **CÓ stress**, replay **toàn lịch sử tới ngày chạy**, `data_dir` do CLI truyền, data **incremental** |
| **Trục chưa có** | causal (4), MAX_HOLD 09:30 (5), nkd 6% (6), CSV sửa 08-13 (8) — tất cả đều đến SAU |
| **Vì sao không tái tạo** | net $52,936 đã được chứng minh là artifact của data incremental; ground truth trên frozen = **$53,021** ([ISSUES_LOG.md](ISSUES_LOG.md) dòng 288) |
| **Lỗi thiết kế** | `FreezeRecord` (`refreeze.py:61-79`) lưu `calmar` nhưng không lưu trục nào ở §1 |

### 2.3 `BACKTEST_CALMAR_FLOOR = 1.65` — `global_index/runner.py:106`

| Trường | Nội dung |
|---|---|
| **Trạng thái** | ✅ **TÁI TẠO ĐƯỢC** — con số duy nhất có lệnh đo viết ngay bên trên nó (`runner.py:100-105`) |
| **Đo ngày** | 2026-08-04, commit `f8a1f13` |
| **Cơ sở** | fit_A, `frozen_sim`, `spy_daily_live.csv`, `--end 2024-12-31`, `--hmm-fit-end 2022-12-31`, n=1, **2-tick**, **no-stress**, causal, MAX_HOLD 09:30, nkd 6% |
| **Kết quả kèm** | Calmar 1.65, net $42,565, MaxDD $3,744 (7.5%) |
| **Mirror** | `generate_replay_snapshots.py` (INVARIANTS dòng 30 yêu cầu hai chỗ khớp nhau) |

**Đây là mẫu nên theo:** số + lệnh sinh ra nó, cạnh nhau, trong cùng một file.

### 2.4 Chuỗi tiến hoá của floor

```
2.38  1-tick, data incremental, look-ahead, bar-0, nkd 2%      (2026-07-02)
 ↓    → chuyển 2-tick + frozen + --end 2024-12-31              (2026-07-09)
2.04  2-tick, frozen_2024, no-stress, look-ahead               ← OOS_VALIDATION F1
 ↓    → sửa look-ahead                                         (2026-07-10)
1.53  causal, bar-0 exit
 ↓    → sửa MAX_HOLD 00:00 → 09:30 ET                          (2026-07-11)
1.57  causal, MAX_HOLD 09:30, nkd cap 2%
 ↓    → nâng global_nkd cap 2% → 6%                            (2026-08-04)
1.65  ← HIỆN HÀNH (runner.py:106)
```

`refreeze.py:53` vẫn đứng ở đầu chuỗi. Nó bỏ lỡ cả 4 bước.

### 2.5 Các số khác đang lưu hành

| Số | Nguồn | Cơ sở | Trạng thái |
|---|---|---|---|
| **2.04** | OOS_VALIDATION F1 | fit_A, frozen_2024, no-stress, 2-tick, **look-ahead** | Chết yểu — đo 2026-07-09, sửa causal ngày hôm sau |
| **1.72** | INVARIANTS dòng 22 | baseline fit_C hiện hành, no-stress, `--end 2024-12-31` | ✅ Hiện hành |
| **2.86 / 2.54** | INVARIANTS dòng 28–29 | vault 2023-24 (fit_A) / vault 2025 (fit_C, **có stress**) | ✅ Hiện hành |
| **2.299** | SCRATCHPAD, phiên 2026-08 | đường cong cũ, đuôi NKD-only, net $61,088, MaxDD $3,115 | ⚠️ Chưa có bản ghi cam kết |
| **1.678** | SCRATCHPAD, phiên 2026-08 | net $57,950, MaxDD $4,049 | ⚠️ Chưa có bản ghi cam kết |

> `calmar = (net / số_năm) / maxdd_$`. Luôn kiểm một con số Calmar bằng cách tái dựng **cả ba**
> thành phần — chênh lệch giữa 2.299 và 1.678 nằm ở tử lẫn mẫu, **không phải suy giảm hiệu năng**.

---

## 3. Ba lỗi cấu trúc trong `run_verify` — không phải trôi theo thời gian

Đây là lý do 2.744 và 1.678 không so được với nhau, và không con nào so được với 1.65.

| # | Lỗi | Vị trí | Hệ quả |
|---|---|---|---|
| V1 | **Luôn bật stress**, vô điều kiện | `refreeze.py:383` (`stress_bt = StressMidEngine()...`), append tại `:407-413` | Cả dòng floor 2.04 → 1.65 là **no-stress**. [DECISIONS.md](DECISIONS.md) dòng 36 chọn no-stress có lý do đo được: with-stress floor bị **INVERTED** (2.54 > baseline 2.50), vì fit_A gán nhiều Stress hơn → STRESS_MID kiếm thêm IS P&L, không phải core system tốt hơn |
| V2 | **Không cắt mốc** — không có `--end` | `refreeze.py:423` gọi `deploy_replay` trên toàn bộ `all_tr` | Số đổi **mỗi ngày** khi parquet append. Cổng promotion không phải hằng số |
| V3 | **`data_dir` do caller quyết** | `refreeze.py:363`, tham số `data_dir` | `verify_current_freeze.py:45` trỏ vào `data/cache/futures` (live, trôi) chứ không phải `frozen_sim` |

### 3.1 Cửa sổ của `run_gate` khác cửa sổ của L11

`COMMON_START = "2019-01-01"` (`refreeze.py:56`) và `common_end = min(max_prev, max_new)` —
nghĩa là gate so nhãn trên **~7,5 năm**. [LESSONS L11](LESSONS.md) lại đặt câu hỏi trên
**period hiện tại** (2026 YTD). Hai cửa sổ này có thể cho hai kết luận ngược nhau: một khác biệt
tập trung ở vài chục ngày gần đây bị pha loãng thành phần trăm rất nhỏ trên mẫu 7,5 năm.

Gate và L11 **không thay thế được cho nhau**. Gate hỏi "model có đổi nhiều không"; L11 hỏi
"model cũ có sai không". Chỉ L11 mới là điều kiện khởi động refit.

---

## 4. Doc-drift phát hiện kèm (chưa sửa)

| # | Mô tả sai | Vị trí | Thực tế |
|---|---|---|---|
| D1 | `refreeze.py → models/PRODUCTION.pkl` | [PIPELINE_FLOW.md](PIPELINE_FLOW.md) dòng 15 | Không có `PRODUCTION.pkl`. `label_regimes` gọi `eng.fit(..., save=False)` — model chỉ tồn tại trong RAM. `models/hmm/` chỉ có 16 `.pkl` từ 2026-06-05 (artifact test của stocks) + registry JSON |
| D2 | `HMMStaleGuard chưa wire trong production` | [PIPELINE_FLOW.md](PIPELINE_FLOW.md) dòng 13, 22 | **Đã wire**: `run_live_day.py:709` truyền `hmm_stale_guard=HMMStaleGuard(...)` |
| D3 | `Degradation floor = Calmar 2.38 (fit_A 2022, locked)` | [STATUS.md](STATUS.md) dòng 35 | Floor hiện hành 1.65; STATUS cập nhật lần cuối 2026-07-12 |
| D4 | `Calmar 2.38 — nếu production thấp hơn, dừng lại` | [GLOSSARY.md](GLOSSARY.md) dòng 186 | Cùng lỗi D3 |
| D5 | `regime_csv` là tham số của `run_refreeze_pipeline` | `refreeze.py:509` | Nhận vào nhưng **không dùng ở đâu** trong thân hàm (`:503-624`) |
| D6 | `"refreeze": {"pending": False}` | `runner.py:2479` | **Hardcode** — không đọc `models/hmm/refreeze_pending.json`. Consumer duy nhất là dòng hiển thị `paper_evidence_reader.py:2722` → dashboard mù với mọi lần re-freeze fail |

---

## 4b. HAI SÀN, HAI MỤC ĐÍCH — đọc mục này trước khi sửa bất kỳ sàn nào

_Thêm 2026-08-15, ngay sau khi cổng promotion đổi sang đo theo cặp._

Từ 2026-08-15 trong hệ có **hai** hằng số tên gần giống nhau, giá trị khác nhau, và **suy ra từ hai
lập luận khác nhau**. Nhầm hai cái này là tái lập đúng cái bẫy mà tài liệu này được viết ra để chặn.

| | `refreeze.CALMAR_FLOOR` | `runner.BACKTEST_CALMAR_FLOOR` |
|---|---|---|
| **Giá trị** | **1.50** | **1.65** |
| **Trả lời câu hỏi** | "Có nên **thay** model không?" | "Paper có đang **suy giảm** so với backtest không?" |
| **Chạy khi nào** | Hàng năm, lúc re-freeze | Mỗi ngày, hiển thị trên dashboard |
| **Vai trò** | **Chặn thảm hoạ** — cổng chính là đo theo cặp | **Ngưỡng chính**, không có gì đứng sau |
| **Suy từ** | Dưới đáy nhiễu seed đo được (1.56) để không bao giờ bắn vì hạt giống | fit_A trên cơ sở ghim, 2026-08-04 (`runner.py:100-105`) |
| **Có miễn nhiễm nhiễu seed?** | **Có** — vì cổng chính so cặp cùng seed | **KHÔNG** — nó là ngưỡng tuyệt đối |

### Chỗ còn hở

`BACKTEST_CALMAR_FLOOR = 1.65` nằm **bên trong** dải nhiễu seed đo được **[1.56, 1.72]**.
Hai trong năm seed của **cùng một hệ** cho Calmar dưới 1.65 (xem §4c). Nghĩa là nếu ai đó đổi
`engine.RANDOM_SEED`, hoặc nếu một lần nâng cấp `hmmlearn` làm EM rơi vào cực trị khác, dashboard
có thể báo "suy giảm" mà **không có gì suy giảm cả**.

Điều này **chưa được sửa**, và đó là chủ ý: cổng promotion có thể so cặp vì nó luôn có hai model để
so; phần theo dõi paper thì không — nó chỉ có một đường cong live và một hằng số. Muốn miễn nhiễm
nhiễu ở đó phải chọn một trong ba, và cả ba đều là quyết định của chủ dự án:

1. **Hạ 1.65 xuống dưới 1.56** — hết báo động giả, nhưng cũng mất khả năng phát hiện suy giảm nhẹ.
2. **Đổi sang Sharpe/PF** — hai thước này trải 2.42% và 0.68% (so với Calmar 9.47%), nhưng phải
   dựng lại baseline paper trên thước mới.
3. **Giữ 1.65 và ghi rõ** rằng một lần vượt sàn đơn lẻ chưa phải bằng chứng — cần xác nhận bằng
   cách chạy lại với seed production trước khi kết luận.

Cho tới khi chốt: **một lần Calmar paper xuống dưới 1.65 KHÔNG đủ để kết luận hệ suy giảm.**
Chạy `python futures/measure_seed_pnl.py` để xem con số đó có nằm trong dải nhiễu không, rồi mới kết luận.

### Đã chốt 2026-08-15: lựa chọn **3**, và một phát hiện lớn hơn nhiễu seed

Truy vào chỗ tiêu thụ mới thấy **sàn này chưa từng gate gì cả**. `analytics.js` chỉ *hiển thị*
hai ô cạnh nhau (`histCalmar`, `histBaseline`); không có phép so trong code, không ngưỡng, không
cảnh báo. Và trạng thái live: `running_metrics.calmar = null` (vì `max_dd = 0.0`), 5 snapshot
từ 2026-08-10, `paper_vs_backtest.divergence_pct = null`. UI hiện `insufficient observations`.

**Lệch nền giữa hai ô lớn hơn nhiều so với ±0.16 nhiễu seed** — và code đã tự khai từ trước:

| | ô `Calmar` | ô `Backtest fit_A` |
|---|---|---|
| dữ liệu | đầy đủ tới hiện tại | **frozen**, `--end 2024-12-31` |
| stress sleeve | **CÓ** | **KHÔNG** |
| nguồn | `metrics()` trên `_daily_realized` | `deploy_sim`, 2 tick, n=1 |

Khác **dữ liệu, khoảng thời gian, và thành phần sleeve**. Trước đây chỉ được che bằng tooltip,
trong khi nhãn ô lại là *"Floor"* — một chữ mời người đọc làm đúng phép so mà tooltip nói là
không làm được.

**Đã làm:** nhãn `Floor fit_A` → `Backtest fit_A`; dòng dưới ô thành *"nền khác — tham chiếu,
không phải ngưỡng"*; `CALMAR_NOTE` thêm hai điều — dashboard **không** so hai ô này, và kể cả
đưa về cùng quy ước thì 1.65 vẫn không phải vạch sắc (dải 1.56–1.72, 2/5 seed dưới sàn).
Giá trị hằng số **không đổi**.

**Chưa làm — lựa chọn 1 thật sự:** bỏ so với hằng số lịch sử, so paper với backtest chạy trên
**đúng cửa sổ paper** — nguyên lý *đo theo cặp* đã áp cho cổng promotion, đem sang phần theo dõi.
Khung có sẵn: `paper_vs_backtest.expected_equity` / `divergence_pct` đang `null` chứ không phải
không tồn tại. Đây mới là thứ chữa **cả** lệch nền lẫn nhiễu seed. Chờ paper đủ dài.

**Rejected:** hạ 1.65 xuống dưới 1.56, hoặc chuyển sang Sharpe/PF — chỉ chữa nhiễu seed, để
nguyên lệch nền, và làm con số trông chính xác hơn thực tế.

### Bất biến mới cho cả hai sàn

> Không sàn nào được đặt **bên trong** dải nhiễu của chính phép đo sinh ra nó.
> Trước khi đổi bất kỳ sàn nào: chạy `measure_seed_pnl.py`, lấy `[min, max]`, đặt sàn ngoài dải đó.

---

## 4c. Nhiễu seed — số liệu gốc

_Đo 2026-08-15, `futures/measure_seed_pnl.py`, 5 seed, CÙNG `fit_end=2024-12-31`, cơ sở ghim
(`frozen_sim`, `--end 2024-12-31`, n=1, 2-tick, no-stress). `SC-ANCHOR` PASS: seed 42 tái tạo
đúng $42,459 / Calmar 1.72 của INVARIANTS dòng 22._

| seed | net | Calmar | MaxDD | PF | Sharpe |
|---|---|---|---|---|---|
| **42** (production) | $42,459 | **1.72** | $3,574 | 1.48 | 1.67 |
| 1 | $42,319 | 1.71 | $3,574 | 1.48 | 1.65 |
| 7 | $41,699 | 1.69 | $3,574 | 1.48 | 1.67 |
| 123 | $40,633 | **1.57** | $3,744 | 1.47 | 1.63 |
| 2026 | $40,254 | **1.56** | $3,744 | 1.48 | 1.65 |

| thước | dải | % của trung vị |
|---|---|---|
| **Calmar** | 1.56 – 1.72 | **9.47%** |
| net | $40,254 – $42,459 | 5.29% |
| MaxDD | $3,574 / $3,744 (**chỉ 2 giá trị**) | 4.76% |
| Sharpe | 1.63 – 1.67 | 2.42% |
| PF | 1.47 – 1.48 | **0.68%** |

**Vì sao Calmar nhiễu gấp 4–14 lần hai thước kia:** `calmar = (net/số_năm) / maxdd_$`. Mẫu số là
**một ngày duy nhất**, và qua 5 lần chạy nó chỉ nhận **hai** giá trị — một hàm bậc thang. PF và
Sharpe trung bình hoá trên mọi ngày nên không có bậc.

→ **Hệ giao dịch ổn định; thước đo mới là thứ không ổn định.** Seed không làm hệ đánh khác đi bao
nhiêu, nó chỉ đổi xem ngày sụt sâu nhất rơi vào đâu.

Lưu ý (n=5 nên bằng chứng yếu, nhưng đáng ghi): seed production 42 cho giá trị **cao nhất** trong
5 lần rút. Baseline 1.72 mà mọi thứ đang neo vào **không phải ước lượng trung tâm**.

---

## 5. Bài học rút ra

**Số phải đi kèm cơ sở đo, nếu không nó sẽ mồ côi trong vòng vài ngày.**

Ba bằng chứng độc lập trong chính hệ này:
1. `CALMAR_FLOOR = 2.38` sống sót 6 tuần sau khi bị deprecate, vì không ai nhìn vào nó thấy được nó đo bằng gì.
2. `FreezeRecord.calmar = 2.744` không phục dựng được, vì cấu trúc dữ liệu không có chỗ cho cơ sở.
3. `BACKTEST_CALMAR_FLOOR = 1.65` không gặp vấn đề nào — vì lệnh đo nằm ngay 6 dòng bên trên.

**Cách chống:** hoặc **derive từ dữ liệu**, hoặc **lưu kèm cơ sở đo**. Một hằng số trần là mồ côi
ngay từ lúc gõ.

---

## 6. Việc còn treo (không làm trong lần audit này)

- [x] **RESOLVED 2026-08-15** (`futures/compare_refit.py`, verdict HOLD 5.84%) — nguyên văn cũ:
      Đo lại `compare_refit_2025` trên CSV hiện tại — script gốc **chưa bao giờ được commit**
      (`git log --all -- "*compare_refit_2025*"` → rỗng), nên con số 93.7% ở DECISIONS
      cũng không tái tạo được. Đây là điều kiện quyết định refit có xảy ra hay không.
- [x] **RESOLVED 2026-08-15** — `CALMAR_FLOOR` 2.38 → **1.50**, và vai trò đổi từ cổng chính
      thành **chặn thảm hoạ**. Cổng chính giờ là **đo theo cặp trên 3 thước** (`paired_verdict`).
      Lý do: 5 seed của cùng một hệ cho Calmar 1.56–1.72, **2/5 dưới sàn 1.65** — sàn tuyệt đối
      không phân biệt được suy giảm với đổi seed. Xem DECISIONS.md.
- [x] **RESOLVED 2026-08-15** — `FreezeRecord.calmar_basis` + `VerifyResult.basis`; mọi Calmar
      ghi ra từ nay mang theo cơ sở đo. Bản ghi cũ không có trường này vẫn load được (T13.8).
- [x] **RESOLVED 2026-08-15** — V1–V3 hết vì nguyên nhân chung bị gỡ: `run_verify` không còn
      bản chép pipeline, nó gọi thẳng `deploy_sim` qua subprocess trên cơ sở ghim. Thêm 2 guard
      fail-closed (contaminated theo I2.2; hash nhãn phải khớp). 87/87 test + mutation test.
- [x] D5 RESOLVED — `regime_csv` giờ được `run_verify` dùng thật.
- [x] **D3, D4 RESOLVED 2026-08-15** — STATUS.md và GLOSSARY.md không còn ghi sàn 2.38;
      GLOSSARY thêm 3 mục: sàn promote vs sàn theo dõi, đo theo cặp, sàn nhiễu.
- [x] **D1, D2 RESOLVED 2026-08-15** — `PIPELINE_FLOW.md` không còn ghi
      `refreeze.py → models/PRODUCTION.pkl` (không có file đó; `label_regimes` gọi
      `save=False`) và không còn ghi `HMMStaleGuard chưa wire` (đã wire, `run_live_day.py:709`).
- [x] **D6 RESOLVED 2026-08-15** — `runner._refreeze_status()` đọc `refreeze_pending.json`
      thật thay cho hardcode `{"pending": False}`. **Fail-closed**: cờ đọc không được thì báo
      `pending=True` + `unknown=True`, vì consumer map `pending` falsy thẳng sang trạng thái OK
      (`paper_evidence_reader.py`) — báo False khi lỗi đọc là in "an toàn" đè lên một lần
      re-freeze hỏng chưa xử lý. `pending` vẫn là bool (T19.6 ghim). Test T19b.1–.9, có
      mutation-test; **T19b.8/.9 đi qua `_build_operational_status`** vì chỉ test helper thì
      để nguyên đúng lỗi đang sửa — helper đúng mà không ai gọi.
- [ ] **QUYẾT ĐỊNH CỦA CHỦ Dự ÁN** — `runner.BACKTEST_CALMAR_FLOOR = 1.65` nằm trong dải
      nhiễu seed [1.56, 1.72]. **Đã document đầy đủ** (§4b + INVARIANTS + comment tại
      `runner.py:100-125` + GLOSSARY), **chưa sửa giá trị**. Ba lựa chọn ở §4b.
