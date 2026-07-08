# RAITS — Docs Index
_Cập nhật: 2026-07-07_

Hệ tracking docs cho RAITS: futures và stocks là HAI subsystem độc lập, nhưng chia sẻ HMMEngine class và SPY data (từ nguồn riêng biệt).

---

## Cấu trúc

```
docs/
  README.md           ← bạn đang đọc — index + hướng dẫn dùng
  SHARED.md           ← NGUY HIỂM NHẤT — code/data dùng chung cả hai
  futures/
    STATUS.md         ← trạng thái hiện tại (đâu xong, đâu blocked, plan)
    DECISIONS.md      ← quyết định đã chốt + lý do + alternatives rejected
    OPEN_QUESTIONS.md ← câu hỏi chưa giải quyết + blocker + priority
    ASSUMPTIONS.md    ← số CHƯA đo + verify-when (chống số-đoán-trôi)
    INVARIANTS.md     ← bất biến + cách check
    PIPELINE_FLOW.md  ← run_day() 8 bước trace thật (file + logic + data in/out)
    SCRIPT_INVENTORY.md ← 53 scripts phân loại (production/test/archived)
    ARCHIVE_LOG.md    ← log 14 scripts đã archive + lý do + bản thay
    SYSTEM_EXPLORER.html ← interactive pipeline explorer (mở browser)
    GLOSSARY.md       ← mọi mã nội bộ (A–J, UT, fit_A/B/C, ...) + nguồn gốc + naming collisions
    SYSTEM_MODEL.md   ← 4-chiều model từ code (Control Flow / Data Flow / Safety / State). Grep-verified.
    VISUALIZE.md      ← 4 tầng ASCII visualization của SYSTEM_MODEL
    ISSUES_LOG.md     ← nhật ký 22 vấn đề theo nhóm — root cause + fix + nguồn code
    LESSONS.md        ← 9 bài học meta từ lỗi thật (class of mistakes)
  CROSS_SYSTEM_FINDINGS.md ← futures findings → classify → verify trên stocks code
  stocks/
    STATUS.md
    DECISIONS.md
    OPEN_QUESTIONS.md
    ASSUMPTIONS.md
    INVARIANTS.md
    CB_INVESTIGATION.md ← circuit breaker 605 vs 604 root cause + contamination verdict
```

---

## Khi nào đọc file nào

| Tình huống | Đọc file |
|---|---|
| "Hôm nay làm gì tiếp?" | `futures/STATUS.md` hoặc `stocks/STATUS.md` |
| "Tại sao quyết định X?" | `futures/DECISIONS.md` hoặc `stocks/DECISIONS.md` |
| "Số Y này từ đâu ra? Có đo chưa?" | `futures/ASSUMPTIONS.md` hoặc `stocks/ASSUMPTIONS.md` |
| "Cái này đã hỏi chưa, đang chờ gì?" | `futures/OPEN_QUESTIONS.md` hoặc `stocks/OPEN_QUESTIONS.md` |
| "Sửa file Z có ảnh hưởng gì không?" | `futures/INVARIANTS.md` + kiểm `SHARED.md` |
| "Vấn đề X đã fix chưa? Root cause là gì?" | `futures/ISSUES_LOG.md` |
| "Bài học từ lỗi cũ?" | `futures/LESSONS.md` |
| "Futures finding có áp stocks không?" | `CROSS_SYSTEM_FINDINGS.md` |
| "Đụng HMMEngine / SPY data" | `SHARED.md` TRƯỚC TIÊN |

---

## Nguyên tắc cập nhật

**Cập nhật KHI làm, không dồn cuối session.**

| Sự kiện | Cập nhật file |
|---|---|
| Hoàn thành một milestone | `STATUS.md` — move từ in-progress → done |
| Ra quyết định thiết kế | `DECISIONS.md` — ghi quyết định + lý do + alternatives |
| Phát hiện câu hỏi chưa có câu trả lời | `OPEN_QUESTIONS.md` |
| Dùng số chưa đo làm design assumption | `ASSUMPTIONS.md` |
| Measure được số từ assumption | Xóa khỏi ASSUMPTIONS, ghi vào "Lịch sử" + cập nhật DECISIONS nếu ảnh hưởng quyết định |
| Đóng open question | Ghi "Đã đóng" + resolution, di chuyển xuống section đã đóng |
| Sửa shared code | Cập nhật cả hai DECISIONS.md |

---

## SHARED — nguy hiểm nhất

`SHARED.md` liệt kê mọi thứ dùng chung giữa futures và stocks:
- **HMMEngine class** (`raits/hmm/engine.py`): đổi interface → phá cả hai
- **SPY daily data**: hai nguồn ĐỘC LẬP — fix một KHÔNG tự sạch cái kia

**Rule đơn giản:** đụng gì trong `SHARED.md` → chạy test cả hai subsystem trước khi commit.

---

## ASSUMPTIONS — chống số-đoán-trôi

Bài học từ session: $82k scaling threshold không có derivation → WRONG ($55,784 bước giữa dùng MaxDD@$50k; ước tính hiện tại ~$58-59k tự tham chiếu, chưa đo chính xác — cần deploy_sim --account 59000). 105s/$82k là minh chứng.

Rule:
- Mọi số design chưa đo bằng script → vào ASSUMPTIONS
- Không dùng số trong ASSUMPTIONS để ra quyết định live
- Khi đo được → move ra khỏi bảng, ghi vào "Lịch sử", update DECISIONS

---

## Giới hạn của docs này

Docs này track cái ĐÃ BIẾT. Cái CHƯA NGHĨ TỚI cần:
- Paper trading để lộ edge cases
- IBKR account để lộ integration bugs
- Live session để lộ timing issues

Không dùng docs để thay thế paper + production monitoring.