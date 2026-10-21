# Khởi động lại scheduler + nền dashboard — thứ Bảy 12/09/2026

Soạn 10/09/2026 13:10 ET. Chỉ đọc khi soạn — không lệnh nào dưới đây đã được chạy.

## Vì sao phải làm

Hai tiến trình đang chạy đều khởi động **trước** mọi thay đổi của tuần này:

    scheduler   PID 36860   07/09 01:35 giờ máy   --port 4002 --shadow-resume --track1-only-shadow
    backend     PID 53784   07/09 20:58 giờ máy   --ibkr-port 4002 --api-port 5002

APScheduler chỉ đọc lịch lúc khởi động. Nên ba commit sau đây **có trong kho nhưng chưa chạy**:

| commit | nội dung | bằng chứng chưa chạy |
|---|---|---|
| `b73d9e5` | dời thang SPY tối sang 18:20 / 20:10 / 22:00 ET | nhật ký 09/09: thang vẫn chạy 16:20 / 16:45 / 17:15 ET |
| `fc8d77e` | "hôm qua" thứ hai của scheduler theo lịch sàn | nằm trong chính tiến trình scheduler |
| `52f14df` | hai job neo 00:55 và 09:16 ET | không có dòng `Added job "Anchor check…"` nào trong nhật ký |

**Hạn chót:** trước roll rổ Mỹ dự kiến thứ Năm 17/09. Không có hai job neo thì Calm và Stress
mất trọn ngày hôm đó.

## Khi nào

**Thứ Bảy 12/09, giờ nào cũng được.** Đo trên HEAD: ngoài nhịp tim, không job nào chạy thứ Bảy.

Muộn nhất: **Chủ nhật 13/09 trước 17:45 ET** — lúc 18:00 ET có `spy_weekend_pre_nkd_check`,
18:30 ET có `track1_stop_repair_sun_1830`.

## BẪY PHẢI TRÁNH: khoá Polygon

Đo ngày 10/09:

    biến                  shell hiện tại   config_private.py
    POLYGON_API_KEY            KHÔNG              CÓ
    DATABENTO_API_KEY           CÓ              KHÔNG
    IBKR_FLEX_TOKEN             CÓ              KHÔNG
    IBKR_FLEX_QUERY_ID          CÓ              KHÔNG

Khoá Polygon **không có ở cấp nào của Windows** (Process / User / Machine đều trống), và
`update_spy_csv` dòng 441 **không** tự đọc `config_private.py` — nó chỉ đọc cờ `--api-key`
hoặc biến môi trường. Scheduler hiện tại có khoá chỉ vì shell khởi động nó hôm 07/09 đã xuất tay.

`ops.py` chép nguyên môi trường của shell sang scheduler mới (`_env` = `os.environ.copy()`).
**Khởi động lại từ một shell thiếu khoá → pre-flight 13:45 thứ Hai hỏng → cả ngày bị bỏ.**

Lệnh dưới nạp khoá từ `config_private.py` **vào môi trường của chính tiến trình**, không đặt nó
lên dòng lệnh (dòng lệnh hiện ra trong danh sách tiến trình của Windows).

## Trước khi chạy

    python -m monitor.ops status          # đúng 1 scheduler, 1 backend, không run_live_day mồ côi
    git log --oneline -1                  # HEAD là bản muốn chạy
    python -m pytest -q -p no:cacheprovider   # 1 đỏ có sẵn (test trình duyệt) là bình thường

## Lệnh (PowerShell, từ `d:\raits`)

```powershell
python -c "import os, runpy, sys, config_private as c; os.environ['POLYGON_API_KEY'] = c.POLYGON_API_KEY; sys.argv = ['ops', 'restart', '--scheduler', '--track1-only-shadow', '--yes']; runpy.run_module('monitor.ops', run_name='__main__')"
```

Cổng mặc định của `ops.py` là 4002 / 5002, khớp tiến trình hiện tại. `--shadow-resume` bật mặc
định. Đường `restart --scheduler` đã có chốt đúng nghĩa: `ensure_single` **từ chối** khi không dò
được tiến trình, đếm lại sau khi giết, và không khởi động cái thứ hai nếu cái cũ còn sống;
`stop_runners` giết cả `run_live_day` mồ côi đang giữ clientId 1.

## Sau khi chạy — sáu phép kiểm

1. **Đúng một** scheduler, thời điểm khởi động = vừa rồi, dòng lệnh
   `--port 4002 --shadow-resume --track1-only-shadow`.
2. **Đúng một** backend nghe cổng 5002.
3. Nhật ký scheduler hôm đó có đủ các dòng:

       Added job "Anchor check 00:55 ET"
       Added job "Anchor check 09:16 ET"
       Added job "SPY daily refresh 18:20 ET …"
       (và hai nấc 20:10, 22:00)

   Số dòng `Added job` phải bằng số job mà `make_scheduler(track1_only=True)` trả về trên HEAD
   — tính lúc kiểm, không so với một con số viết sẵn.
4. Lịch khớp gương:

       python -c "from global_index import track1_slots as t; print(t.parity_report(track1_only=True)['in_parity'])"

5. Bảng lịch trên dashboard có hai dòng `ANCHOR_CHECK_0055` và `ANCHOR_CHECK_0916`, và
   **không** có chúng trong ô "Next decision".
6. **Khoá Polygon tới được scheduler.** Không đọc được môi trường của tiến trình khác, nên bằng
   chứng đầu tiên là job Chủ nhật 18:00 ET `spy_weekend_pre_nkd_check`: nó phải `completed OK`.
   Nếu nó hỏng vì thiếu khoá thì còn tới 00:45 ET thứ Hai để sửa — trước khi bất cứ thứ gì phụ
   thuộc vào dữ liệu SPY chạy.

## Nếu có gì sai

Dừng, đừng để nửa vời. Lệnh trên chạy lại được nhiều lần — `ensure_single` bảo đảm luôn chỉ còn
một tiến trình. Không sửa nhật ký cũ.

## Ngoài phạm vi, ghi lại để không mất

`_run` trong `run_scheduler.py` ghi **toàn bộ dòng lệnh** vào nhật ký, và lệnh SPY được nối thêm
`--api-key <khoá>`. Đo ngày 10/09: **125 dòng trong 29 tệp nhật ký** chứa khoá Polygon ở dạng chữ
trơn. Nhật ký bị `.gitignore` nên không lọt vào kho — lộ cục bộ, không công khai. Sửa bằng cách
che giá trị trước khi ghi; chưa làm, chờ chủ dự án quyết.
