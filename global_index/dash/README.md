# Handoff — realtime dashboard

Đặt cả ba file này vào `dash/` trong repo, rồi bảo Claude Code:

> Đọc `dash/IMPLEMENTATION_PROMPT.md` và làm theo phần 4.

Ba file, chia việc:

| File | Nội dung | Khi nào đọc |
|---|---|---|
| `ROUND_2.md` | việc tiếp theo · **phần B: chỗ bản design chưa vẽ** · prompt vòng 2 | Đọc trước nếu vòng 1 đã chạy |
| `COVERAGE.md` | bảng kiểm phủ: 48 danh sách / 18 nhánh / 18 grid, mỗi cái mô tả ở đâu | Khi cần biết một component có spec chưa |
| `IMPLEMENTATION_PROMPT.md` | 5 việc gốc (G1–G5) · 8 chỗ repo đúng hơn design · số đo mốc | Điểm vào của vòng 1 |
| `DESIGN_SPEC.md` | token · thang chữ · pattern · Market View (5 lớp + 3 tab) · breakpoint · giữ nguyên · 10 luật kiểm được | Tra khi cần một giá trị |
| `SECTION_ANATOMY.md` | giải phẫu 11 section + khung ngoài, kèm lý do | Tra khi sửa một section cụ thể |

**Không cần** `Realtime Dashboard.dc.html`. Nó là template runtime, style inline
rải khắp 1500 dòng — đọc nó như đọc spec thì phải tự suy ra token, và suy sai là
ra kết quả lệch. Ba file trên đã trích sẵn.

## Hai điều dễ làm sai nhất

1. **Bản design KHÔNG phải bản chuẩn về nội dung.** Repo đang đúng hơn ở 8 chỗ
   (Source Clocks, job/event journal, open issues, status rail, Track 1 runtime,
   regime check, threshold fold). Đọc `IMPLEMENTATION_PROMPT.md` phần 2 trước khi
   sửa bất cứ gì. Lấy màu/cỡ/khoảng cách từ spec; **đừng** lấy chữ.

2. **680px là hợp đồng với `realtime.js:11`,** không phải một lựa chọn thiết kế.
   Mọi media query màn hẹp phải đúng 680px.

## Và một điều dễ quên

**Bản design chỉ vẽ MỘT trạng thái cho mỗi section — trạng thái yên** (0
position, 0 order, no signal). Mọi trạng thái có dữ liệu đều chưa được vẽ, kể cả
Market View khi levels được publish — vốn là phần lớn giá trị vận hành của nó.
Danh sách đầy đủ ở `ROUND_2.md` phần B. Ở những chỗ đó **repo là nguồn đúng**, và
spec không có ý kiến.
