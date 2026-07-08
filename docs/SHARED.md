# SHARED — Code và Data dùng chung giữa Futures và Stocks
_Cập nhật: 2026-07-06_

> **NGUY HIỂM NHẤT trong toàn bộ hệ thống.**  
> Mọi thứ ở đây: đụng một → verify CẢ HAI subsystem trước khi commit.

---

## Nguyên tắc

Khi sửa bất kỳ item nào ở đây:
1. Chạy test cả hai subsystem (futures reconcile chain + stocks backtest/live tests)
2. `git log <file>` — ghi nhận commit hash vào DECISIONS của cả hai
3. Ghi vào `futures/DECISIONS.md` VÀ `stocks/DECISIONS.md` lý do + impact

---

## HMMEngine class (`raits.hmm.engine`)

**File:** `raits/hmm/engine.py`

| Subsystem | Cấu hình | Trạng thái |
|---|---|---|
| Futures | 3-state (Normal/Stress/Crisis), anchored-expanding, frozen fit_C 2024-12-31 | PRODUCTION — locked |
| Stocks | 4-state (Calm/Normal/Stress/Crisis), weekly-expanding retrain | LIVE-READY — weekly retrain wired |

**Phân biệt an toàn vs nguy hiểm:**
- **AN TOÀN**: Đổi params (n_states, covariance_type) riêng từng subsystem — không đụng class
- **NGUY HIỂM**: Đổi interface HMMEngine class (method signature, return type, fit/predict API) → phá cả hai

**Khi đụng HMMEngine class:**
```
1. futures: chạy toàn bộ reconcile chain (gd0/stress/nkd/swing_desired) → 0 mismatches
2. stocks: chạy raits/tests/ full suite → all PASS
3. futures refreeze: python futures/test_refreeze.py → 40/40 PASS
4. git log raits/hmm/engine.py → ghi hash vào cả hai DECISIONS.md
```

**Verify nhanh HMMEngine class không bị sửa:**
```powershell
git log --oneline raits/hmm/engine.py | head -5
```

---

## SPY daily data — HAI nguồn ĐỘC LẬP, cùng chủ đề

| Subsystem | File / Nguồn | Loại | Ghi chú |
|---|---|---|---|
| Futures | `spy_daily.csv` (root) | Polygon corrected adjusted | Dùng cho HMM regime labels; đã corrected (vs freeze-2017 buggy) |
| Stocks HMM | `raits/data/cache/*.parquet` (5-min daily) | Polygon parquet | Dùng để train HMM weekly; split-adjusted only (NOT dividend-adjusted) |
| Stocks scanner | Polygon parquet (daily) | Dividend-adjusted | Khác với HMM source |

**QUAN TRỌNG — không tự động sạch:**
- Fix dividend adjustment trong futures CSV → KHÔNG tự động fix stocks parquet
- Fix adjustment trong stocks parquet → KHÔNG tự động fix futures CSV
- Cùng chủ đề "SPY adjustment" nhưng là 2 file/nguồn riêng biệt

**Khi phát hiện SPY adjustment issue ở một bên:**
```
→ Ghi vào stocks/OPEN_QUESTIONS.md (hoặc futures/OPEN_QUESTIONS.md)
→ Ghi note trong SHARED.md rằng cùng chủ đề, impact bên kia CHƯA ĐO
→ Không assume fix một phía = đã sạch cả hai
```

---

## Utilities / Loaders dùng chung (liệt kê khi phát hiện)

| File | Dùng chung gì | Futures | Stocks |
|---|---|---|---|
| `raits/hmm/engine.py` | HMMEngine class | ✓ | ✓ |
| `raits/hmm/features.py` | Feature matrix builder | ✓ (qua engine) | ✓ (qua engine) |
| _[thêm khi tìm thấy]_ | | | |

---

## INVARIANT khi đụng shared items

| Invariant | Verify command | Tại sao |
|---|---|---|
| HMMEngine class không thay đổi interface | `git log --oneline raits/hmm/engine.py` | Futures frozen / stocks weekly đều depend |
| Sau sửa engine: futures reconcile PASS | `python -m futures.reconcile_gd0 ...` | Baseline $52,936 bất biến |
| Sau sửa engine: stocks tests PASS | `pytest raits/tests/` | Weekly retrain logic intact |
| SPY fix một bên → ghi note bên kia | Check cả hai OPEN_QUESTIONS.md | Hai nguồn độc lập, không tự sync |

---

## Bài học HMM contamination (2026-07-06)

**Hiện tượng:** `label_regimes(fit_end=2024)` khi test period = 2023-2024 → HMM model params thấy test period → labels tối ưu cho khoảng đó → MaxDD nhỏ giả → Calmar inflate +1.19 (4.52 → 3.33).

**Áp dụng cả hai subsystem:**
- Futures: đã fix — vault 2023-2024 dùng `--hmm-fit-end 2022-12-31`. Sealed.
- Stocks: **chưa kiểm tra** — khi chạy vault/OOS cho stocks, verify rằng HMM train set KHÔNG include test period. Weekly retrain train trên dữ liệu đến fit_end; nếu fit_end > test_start → contaminated.

**Rule tổng quát:** HMM fit_end < test_start. Nếu fit_end ≥ test_start → số OOS không tin được (Calmar inflate qua MaxDD, P&L gần như không đổi → khó phát hiện bằng P&L đơn thuần).
