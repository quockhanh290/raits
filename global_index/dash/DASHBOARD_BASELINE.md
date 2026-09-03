# Mốc đo hiển thị — năm dashboard

Sinh bởi `global_index/dash/tools/measure_dashboards.py`. **Đừng sửa tay**:
chạy lại script để cập nhật, nếu không con số sẽ rời khỏi thứ nó mô tả.

- **measured_at_utc**: `2026-09-03 14:03:51Z`
- **commit**: `29859f5`
- **branch**: `future/incorporation`
- **dash_tree_state**: `M global_index/dash/DASHBOARD_BASELINE.json
 M global_index/dash/DASHBOARD_BASELINE.md
 M global_index/dash/paper/index.html
 M global_index/dash/realtime-next/index.html
 M global_index/dash/realtime-next/next.css
 M global_index/dash/realtime-next/preview-states.js
 M global_index/dash/realtime-next/preview.html
 M global_index/dash/realtime-next/skin-e.css
 M global_index/dash/tools/measure_dashboards.py
?? global_index/dash/COVERAGE.md
?? global_index/dash/DESIGN_SPEC.md
?? global_index/dash/IMPLEMENTATION_PROMPT.md
?? global_index/dash/README.md
?? global_index/dash/ROUND_2.md
?? "global_index/dash/Realtime Dashboard.dc.html"
?? global_index/dash/SECTION_ANATOMY.md
?? global_index/dash/support.js`
- **python**: `3.11.4`
- **min_text_nodes_required**: `40`
- **data_source**: `backend live — số ĐẾM là ảnh chụp, không phải mốc đóng băng`

## Kết quả

| Trang | Rộng | Node vẽ ra | Chữ đè chữ | Cắt ngoài mép | Tràn trang | Dưới AA | Cỡ chữ | Họ chữ |
|---|---|---|---|---|---|---|---|---|
| /realtime | 1900 | 277 | 0 | 0 | 0 | 7/446 | 12 | 2 |
| /realtime | 390 | 681 | 0 | 0 | 0 | 19/593 | 13 | 2 |
| /paper · Overview ⚠ | 1900 | 22 | 0 | 0 | 0 | 0/22 | 6 | 2 |
| /paper · Gates | 1900 | 46 | 0 | 0 | 0 | 0/46 | 6 | 2 |
| /paper · Coverage ⚠ | 1900 | 19 | 0 | 0 | 0 | 0/19 | 6 | 2 |
| /paper · Gaps | 1900 | 90 | 0 | 0 | 0 | 0/78 | 7 | 2 |
| /paper · Overview | 390 | 173 | 0 | 0 | 0 | 0/113 | 7 | 2 |
| /paper · Gates | 390 | 543 | 0 | 0 | 0 | 0/345 | 10 | 2 |
| /paper · Coverage | 390 | 449 | 0 | 0 | 0 | 0/338 | 10 | 2 |
| /paper · Gaps | 390 | 127 | 0 | 0 | 0 | 0/78 | 7 | 2 |
| /analytics | 1900 | 891 | 0 | 0 | 0 | 17/890 | 11 | 1 |
| /analytics | 390 | 493 | 0 | 0 | 0 | 17/890 | 10 | 1 |
| /reports | 1900 | 53 | 0 | 0 | 0 | 14/53 | 9 | 1 |
| /reports | 390 | 50 | 0 | 0 | 0 | 14/53 | 8 | 1 |
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

- /paper · Overview @1900px: chỉ 22 node được vẽ — trang chưa dựng xong, mọi số 0 ở dòng này không kiểm gì
- /paper · Coverage @1900px: chỉ 19 node được vẽ — trang chưa dựng xong, mọi số 0 ở dòng này không kiểm gì
- / @1900px: chỉ 19 node được vẽ — trang chưa dựng xong, mọi số 0 ở dòng này không kiểm gì
- / @390px: chỉ 26 node được vẽ — trang chưa dựng xong, mọi số 0 ở dòng này không kiểm gì
