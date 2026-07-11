# RAITS Futures — Operations Runbook

**Audience:** Operator chạy paper/live trading  
**Branch:** `future/incorporation`

---

## B3 MISMATCH — Broker/file position mismatch

### Triệu chứng

Log xuất hiện CRITICAL khi startup:

```
CRITICAL  B3 MISMATCH: file has LONG MES ×1 but IBKR shows ×0 — investigate before trading; file state will be used
CRITICAL  B3: 2 mismatch(es) — new entries HALTED until resolved. Verify live_positions.json matches IBKR, then restart.
```

Runner tiếp tục chạy nhưng **entry bị block hoàn toàn**. Exit vẫn hoạt động bình thường.

### Nguyên nhân

Crash của runner **sau khi IBKR thực thi lệnh** nhưng **trước khi `dump_state()` ghi `live_positions.json`** → file không phản ánh vị thế thật trên IBKR.

### Quy trình giải quyết (4 bước)

**Bước 1 — Kiểm vị thế THẬT ở IBKR (nguồn chân lý)**

Mở IBKR TWS / IB Gateway → Account → Positions  
Ghi lại từng vị thế: instrument, direction (LONG/SHORT), số contracts.

Hoặc qua log: IBKR shows `×N` trong dòng B3 MISMATCH.

**Bước 2 — Sửa `live_positions.json` cho khớp IBKR**

Mở `live_positions.json` ở thư mục `d:\raits\`:

```json
{
  "schema_version": 1,
  "positions": [
    {
      "inst": "MES",
      "direction": "LONG",
      "contracts": 1,
      "cluster": "swing_tf_MES_LONG",
      "entry_day": "2026-07-10T00:00:00",
      "entry_price": 5320.0,
      "pnl_sized": 150.0,
      "exit_pending": false
    }
  ],
  "breaker": { ... }
}
```

Sửa để `positions` array khớp với vị thế THẬT ở IBKR:
- Nếu IBKR có vị thế nhưng file thiếu → thêm vào `positions`
- Nếu file có vị thế nhưng IBKR không có → xóa khỏi `positions`
- Nếu số contracts khác → sửa `contracts`

> **Giữ nguyên `breaker` block** — chứa `peak_equity` và `day_start_equity`.

**Bước 3 — Verify file == IBKR**

Đọc lại file và so sánh thủ công với TWS. Mỗi vị thế trong `positions` phải có pair trên IBKR.

Kiểm tra nhanh qua Python (offline, không connect IBKR):
```powershell
cd d:\raits
python -c "import json; d=json.load(open('live_positions.json')); [print(p['direction'], p['inst'], '×' + str(p['contracts'])) for p in d.get('positions', [])]"
```

**Bước 4 — Cron tiếp theo B3 check → halt tự nhả**

Không cần restart thủ công. Mỗi cron invocation tạo process mới, B3 check lại từ đầu:

```
cron N+1 → new process → _b3_halt_entries=False → B3 check → match → stays False → entries resume ✓
```

Xác nhận nhả bằng log:
```
INFO  B3: broker/file positions match (1 position(s))
```

---

## D5 STOP_FILE — Dừng entries khẩn cấp

### Kích hoạt

```powershell
New-Item -ItemType File d:\raits\STOP_TRADING
```

Runner cron tiếp theo thấy file → entry bị block, exit vẫn chạy bình thường.

### Nhả

```powershell
Remove-Item d:\raits\STOP_TRADING
```

---

## E1 PID LOCK — Duplicate runner instance

### Triệu chứng

```
CRITICAL  Another runner instance is already active (PID XXXXX). Exiting.
```

### Nguyên nhân

Cron fired khi cron trước vẫn còn chạy, hoặc PID file (`runner.pid`) bị stale sau crash.

### Giải quyết

Kiểm tra process còn sống không:
```powershell
Get-Process -Id (Get-Content d:\raits\runner.pid) -ErrorAction SilentlyContinue
```

Nếu process đã chết nhưng file còn:
```powershell
Remove-Item d:\raits\runner.pid
```

Nếu process còn sống và là instance hợp lệ: chờ nó xong rồi cron sau chạy tiếp.

---

## Circuit Breaker — Daily drawdown / streak loss halt

### Triệu chứng

```
CRITICAL  Circuit breaker triggered: daily loss -4.2% exceeds -4.0% limit
```

Runner block cả entry lẫn exit signal mới. Vị thế hiện có vẫn được monitor.

### Giải quyết

Circuit breaker reset tự động vào ngày giao dịch tiếp theo. Không cần can thiệp thủ công.

Để force-reset sớm (không khuyến nghị): xóa `live_positions.json` và tạo lại empty:
```json
{"schema_version": 1, "positions": [], "breaker": {}}
```

> **Cảnh báo:** Xóa positions state khi còn vị thế mở ở IBKR sẽ tạo B3 MISMATCH ở cron tiếp theo.

---

## STP overnight — Stop order triggered while cron was not running

### Triệu chứng (B3 với STP hint)

```
CRITICAL  B3 MISMATCH: file has LONG MES ×1 but IBKR shows ×0
          — stop orderId=12345 status=NOT_FOUND;
          STP may have triggered overnight — check TWS executions.
          If STP filled: remove position from live_positions.json and restart.
          If not: investigate crash/orphan.
```

Hoặc (auto-resolved):
```
INFO  B3 STP EXIT: MES LONG stop orderId=12345 filled overnight — position cleared (stop_price=5250.0000)
```

### Tình huống xảy ra

1. Cron 15:55 ET ngày T: runner enter LONG MES, đặt GTC STP @ 5250 (orderId=12345)
2. Đêm T: giá drop qua 5250 → STP fill → IBKR đóng position
3. Cron 14:05 ET ngày T+1: runner restart → B3 check → file có MES LONG ×1, IBKR có ×0

### Kết quả có thể

- **`status=FILLED`** (runner tìm thấy trong IBKR): auto-clear, no halt, `INFO B3 STP EXIT`
- **`status=NOT_FOUND`** (Gateway restart đã xóa order history): CRITICAL + halt entries, nhưng hint rõ

### Giải quyết khi `NOT_FOUND`

**Bước 1** — Verify STP đã fill trong TWS:
Account → Trade Log hoặc Activity Statement → tìm STP order cho MES ngày T-1 đêm

**Bước 2** — Nếu STP filled: xóa position khỏi `live_positions.json`:
Mở file, xóa entry MES LONG khỏi `positions` array. Giữ `breaker` block.

**Bước 3** — Nếu STP chưa fill (crash orphan thật): xem quy trình B3 MISMATCH ở trên.

**Bước 4** — Cron tiếp theo: B3 check lại → halt tự nhả nếu file == IBKR.

---

## Log monitoring — Các pattern CRITICAL cần chú ý

| Pattern | Ý nghĩa | Hành động |
|---------|---------|-----------|
| `B3 MISMATCH` | Broker/file không khớp | Bước 1–4 ở trên |
| `B3 HALT: N entry signal(s) BLOCKED` | Entry đang bị halt do B3 | Giải quyết mismatch |
| `D5: STOP_FILE present` | Operator halt đang active | Remove file nếu muốn resume |
| `E1: Another runner instance` | Duplicate process | Kiểm tra PID |
| `Circuit breaker triggered` | DD hoặc streak loss limit | Chờ ngày hôm sau |
| `C3: empty bars` | Feed gap cho instrument đang có position | Kiểm tra IBKR data feed |
| `HMM labels stale` | SPY regime labels quá cũ | Update spy_daily.csv |
| `STP: place_stop FAILED` | GTC stop order không đặt được | Đặt STP thủ công trong TWS cho position đó |
| `B3 STP EXIT` | STP fill đêm qua — position auto-cleared | Không cần can thiệp (INFO) |
| `B3 MISMATCH ... stop orderId` | STP có thể đã fill, Gateway restart xóa history | Check TWS Trade Log, xóa pos nếu xác nhận fill |
