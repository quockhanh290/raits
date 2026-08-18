# Mốc đo hiển thị — năm dashboard

Sinh bởi `global_index/dash/tools/measure_dashboards.py`. **Đừng sửa tay**:
chạy lại script để cập nhật, nếu không con số sẽ rời khỏi thứ nó mô tả.

- **measured_at_utc**: `2026-08-18 03:28:02Z`
- **commit**: `df908ed`
- **branch**: `future/incorporation`
- **dash_tree_state**: `?? global_index/dash/DASHBOARD_BASELINE.json
?? global_index/dash/DASHBOARD_BASELINE.md
?? global_index/dash/tools/`
- **python**: `3.11.4`
- **min_text_nodes_required**: `40`
- **data_source**: `backend live — số ĐẾM là ảnh chụp, không phải mốc đóng băng`

## Kết quả

| Trang | Rộng | Node vẽ ra | Chữ đè chữ | Cắt ngoài mép | Tràn trang | Dưới AA | Cỡ chữ | Họ chữ |
|---|---|---|---|---|---|---|---|---|
| /realtime | 1900 | 226 | 0 | 0 | 0 | 4/572 | 12 | 2 |
| /realtime | 390 | 644 | 0 | 11 | 0 | 3/578 | 11 | 2 |
| /paper · Overview | 1900 | 131 | 0 | 0 | 0 | 33/113 | 9 | 1 |
| /paper · Gates | 1900 | 746 | 148 | 0 | 0 | 249/693 | 12 | 1 |
| /paper · Coverage | 1900 | 373 | 0 | 0 | 0 | 117/340 | 11 | 1 |
| /paper · Gaps | 1900 | 86 | 0 | 0 | 0 | 25/78 | 8 | 1 |
| /paper · Overview | 390 | 197 | 0 | 0 | 0 | 33/113 | 8 | 1 |
| /paper · Gates | 390 | 989 | 389 | 0 | 0 | 249/693 | 11 | 1 |
| /paper · Coverage | 390 | 464 | 13 | 0 | 0 | 117/340 | 10 | 1 |
| /paper · Gaps | 390 | 125 | 0 | 0 | 0 | 25/78 | 7 | 1 |
| /analytics | 1900 | 891 | 0 | 0 | 0 | 17/890 | 11 | 1 |
| /analytics | 390 | 493 | 0 | 0 | 0 | 17/890 | 10 | 1 |
| /reports | 1900 | 267 | 0 | 0 | 0 | 222/555 | 13 | 1 |
| /reports | 390 | 283 | 0 | 0 | 0 | 222/555 | 12 | 1 |
| / ⚠ | 1900 | 19 | 0 | 0 | 0 | 0/17 | 5 | 1 |
| / ⚠ | 390 | 26 | 0 | 0 | 0 | 0/17 | 6 | 1 |

## Đo được cái gì, và không đo được cái gì

- Chỉ nội dung ĐANG hiện. Ba tab của `/paper` được mở lần lượt, nhưng phần
  nằm trong `<details>` đóng thì không — chúng không có kích thước, và đếm
  chúng chính là cái đã cho ra một con số sai gấp mười lần.
- Tương phản tính sau khi ghép mọi lớp nền trong suốt xuống nền trang.
- Chữ bị `overflow` cắt không tính là va chạm: nó không được vẽ ra.
- Cột `Họ chữ` đếm số họ chữ khác nhau đang thật sự hiển thị trên trang.
- **Số đếm là ảnh chụp trên dữ liệu live.** Cùng một commit, `/realtime` đã
  ra 226 rồi 294 node ở hai lần chạy khác nhau. So hai lần chạy trong cùng
  một buổi thì có nghĩa; so với một bảng ghi từ tuần trước thì không.

## Dòng KHÔNG tin được

- / @1900px: chỉ 19 node được vẽ — trang chưa dựng xong, mọi số 0 ở dòng này không kiểm gì
- / @390px: chỉ 26 node được vẽ — trang chưa dựng xong, mọi số 0 ở dòng này không kiểm gì
