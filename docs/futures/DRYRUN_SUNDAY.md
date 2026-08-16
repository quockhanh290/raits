# Dry-run Chủ nhật 18:00 ET — kiểm trước khi 16 commit lên live

**Mục đích hẹp, nói rõ để không kỳ vọng sai.** Bài này **không** kiểm logic — 848 test đã
phủ phần đó. Nó kiểm đúng ba thứ chỉ broker thật trả lời được:

1. Tiến trình khởi động sạch với IBKR thật, với bộ tham số production.
2. `session_month_conflict` (M4) **không chặn nhầm** một phiên bình thường. Đây là guard
   duy nhất trong đợt sửa có thể **từ chối gửi lệnh**; nếu giả định về đồng hồ lệch, nó sẽ
   chặn lệnh thật chứ không im lặng.
3. `_front_month_contract` giải được hợp đồng cho cả 5 mã, gồm `MNKD → MNK` — đường mà
   `ce4ea2d` sửa và chưa từng chạy qua broker.

Cái nó **không** kiểm: C1/C2/H4 chỉ chạm tới ở ngày roll hoặc khi một lệnh hỏng, không
dựng ra được trong một lượt dry-run.

---

## Cô lập: cwd, không phải một rừng cờ

`run_live_day.py:127` đặt log bằng `Path.cwd() / f"live_day_{MMDD}.log"`, và `trade_log`,
`live_positions.json`, `slip_stats.json` cũng đều theo cwd. **Nên chạy ở thư mục tạm là cô
lập được gần hết, không cần liệt kê từng đường ghi.**

Điều này quan trọng: `paper_evidence_reader` **quét `live_day_*.log`**. Một lượt dry-run
chạy trong repo đã từng thêm một B3 episode và làm đỏ một gate — rồi bị quy nhầm cho việc
của người khác.

`global_index` **không** import được từ cwd khác, nên phải đặt `PYTHONPATH`.

```powershell
# 1. Thư mục tạm, ngoài repo
$SANDBOX = "C:\tmp\dryrun_$(Get-Date -Format yyyyMMdd_HHmm)"
New-Item -ItemType Directory -Force $SANDBOX | Out-Null

# 2. PYTHONPATH trỏ về repo; cwd là sandbox
$env:PYTHONPATH = "d:\raits"
Set-Location $SANDBOX

# 3. Dữ liệu phải là đường dẫn TUYỆT ĐỐI — cwd không còn là repo nữa
python -m global_index.run_live_day `
  --dry-run `
  --data-dir        "d:\raits\data\cache\futures" `
  --nkd-parquet     "d:\raits\global_index\data\NKD_continuous_1m_8y.parquet" `
  --regime-csv      "d:\raits\spy_daily_live.csv" `
  --live-state-path "$SANDBOX\live_state_data.js" `
  --positions-path  "$SANDBOX\live_positions.json" `
  --lock-path       "$SANDBOX\runner.pid" `
  --stop-path       "$SANDBOX\STOP_TRADING" `
  --clusters        all `
  --port            4002
```

`--positions-path` trỏ vào sandbox **có chủ đích**: runner sẽ khởi động với sổ rỗng, nên B3
so sổ rỗng với vị thế thật ở broker và kêu mismatch. **Đó là kết quả đúng, không phải lỗi** —
xem bảng đọc kết quả. Trỏ vào `live_positions.json` thật thì dry-run sẽ **ghi đè** nó, và đó
là thứ tuyệt đối không muốn.

`--stop-path` trỏ vào sandbox để công tắc D5 không vô tình bị kích bởi file trong repo.

## Sau khi chạy: kiểm cô lập TRƯỚC khi đọc kết quả

```powershell
Set-Location d:\raits
git status --porcelain          # phai KHONG co live_day_*.log / live_positions.json / trade_log.jsonl moi
Get-ChildItem $SANDBOX          # log va state phai nam O DAY
```

Nếu có file nào mới xuất hiện trong repo thì việc cô lập đã hỏng — dọn trước khi làm gì
tiếp, và **đừng** tin số liệu dashboard cho tới khi dọn xong.

## Đọc kết quả

| Thấy gì | Nghĩa là |
|---|---|
| `M4: refusing to send …` hoặc `M4: refusing to roll …` | ⛔ **Dừng, đừng restart.** Guard mới chặn một phiên bình thường — giả định về đồng hồ sai |
| `ContractResolutionError` cho mã bất kỳ | ⛔ **Dừng.** `ce4ea2d` chưa giải được hợp đồng đó ở broker thật. Ghi lại mã và tháng |
| `contract_specs` đủ 5 mã, `MNKD → MNK…` | ✅ Định tuyến của `ce4ea2d` đúng trên broker thật |
| `B3 MISMATCH` / `entries HALTED` | ✅ **Bình thường trong dry-run** — sổ sandbox rỗng, broker có vị thế thật |
| `dry-run — command NOT executed` | ✅ Không lệnh nào đi ra |
| `TIMEOUT after …` | ⚠️ Gateway chậm. Trần 20 phút của H5 vừa chạy lần đầu; ghi lại thời gian thật |

## Rồi mới restart scheduler

**18:30 ET Chủ nhật, và nó bắt buộc bất kể dry-run ra sao** — APScheduler chỉ đọc cron lúc
khởi động, không restart thì cron sweep stop Chủ nhật của `83ac849` không tồn tại tuần này.

Sau khi lên, xác minh job có mặt:

```powershell
Select-String "stop_repair_sun_1830" (Get-ChildItem d:\raits\scheduler_*.log | Select-Object -Last 1)
```

## Cái dry-run này KHÔNG nói được

14:05 ET thứ Hai vẫn là lần đầu `send_order` và `place_stop` **gửi lệnh thật** với
`ce4ea2d`. Dry-run chứng minh hợp đồng giải được và guard không chặn nhầm; nó không chứng
minh một lệnh đi ra rồi khớp đúng.

Và định dạng `lastTradeDateOrContractMonth` vẫn là **suy ra từ code trong repo**
(`exercise_rollover_live` dùng `.startswith`, `backfill_nkd` truyền `"20260910"`), không
phải đo từ broker. `Fill.__post_init__` chuẩn hoá cả `YYYYMM` lẫn `YYYYMMDD` nên đoán sai
cũng không hỏng — nhưng nếu dry-run in ra giá trị thật thì **ghi lại**, đó là giả định lớn
nhất chưa kiểm của cả đợt.
