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

## STP hoãn sang phiên sau — vị thế KHÔNG có stop trong đêm đầu là ĐÚNG

### Luật
Vị thế **swing (Rổ 4) và MNKD** mở trong ngày **không được đặt STP ngay**. B4 đặt ở
**lần chạy đầu tiên của phiên kế tiếp**. Đây là chủ đích, không phải lỗi.

Lý do: `backtest_swing_tf` chỉ xét stop **từ ngày hôm sau** (khối thoát chạy trước khối
vào lệnh trong cùng vòng lặp ngày). Đặt STP ngay lúc khớp là một luật thoát **chặt hơn
luật đã kiểm định**, và nó ăn hết edge:

| | Rổ 4 | MNKD |
|---|---|---|
| STP đặt ngay lúc khớp | **−$10.832** | **−$10.854** |
| STP đặt sang phiên sau | **+$47.166** | **+$22.294** |

STRESS_MID **không** hoãn — adapter của nó xét stop ngay từ bar vào lệnh.

### Đọc log
```
[STP HOAN] MES SHORT @ 7769.03 — dat vao phien sau, dung luat da kiem dinh
B4: MES/roska4_swing chua co STP — dang trong cua so hoan CO CHU DICH (vao ngay 2026-08-10)
```

**Stop được đặt lúc 09:31 ET sáng hôm sau**, không phải 14:05. Job `maxhold_exit` dựng
`FuturesRunner`, mà B4 chạy ngay trong `__init__` — nên nó là chỗ đặt STP hoãn, sớm hơn
slot giao dịch ~4,5 tiếng. Sáng hôm sau tìm trong log của job đó:
```
B4 REPLACED: MES/roska4_swing was open with no stop order — re-placed @ 7769.0300
```
**Không thấy** = cửa sổ không đóng lại → vị thế trần vô thời hạn → xử lý tay ngay.

⚠️ Hệ quả: nếu ai đó sửa `run_maxhold_exit.py` thôi không dựng `FuturesRunner` nữa, việc
đặt STP hoãn lùi về slot 14:05 — vẫn cùng ngày, nhưng thêm 4,5 tiếng không có bảo vệ.

### ⚠️ KHÔNG chạy `repair_stops.py --execute` cho vị thế đang trong cửa sổ
`check_open_orders.py` báo dòng đó là **`DEFERRED`**, không phải `NAKED`, và **vẫn `PASS`**:

```
DEFERRED  MES    SHORT → chua co stop, dang trong cua so hoan CO CHU DICH (muc 7769.03);
                         B4 dat o phien sau. KHONG chay repair_stops cho dong nay.
```

Thấy `NAKED` mới là bất thường — nghĩa là cửa sổ đã qua mà stop vẫn thiếu. `repair_stops`
tự bỏ qua `DEFERRED`, nhưng đừng ép nó bằng tay: đặt stop trong cửa sổ là quay lại đúng
cấu hình **−$10.832**.

### Rủi ro đã đo của quãng không có stop
Đo trên **toàn bộ** quãng trần — từ lúc khớp tới lúc B4 đặt STP lúc 09:31 ET hôm sau, vắt
qua ranh giới ngày:

| | trung vị | p95 | xấu nhất |
|---|---|---|---|
| Rổ 4 (quãng trần ~9,5–19h) | $73 | **$379** | $1.563 |
| MNKD (~22,5h) | $115 | **$463** | $1.665 |

(Con số p95 $271 báo trước đó chỉ tính trong ngày vào lệnh, chưa vắt qua đêm — thiếu.)
Đây là tệ nhất **quan sát được**, không phải chặn trên.

### 🔴 09:31 ET là mốc ĐÃ ĐO, không phải chỗ chưa ai để ý — ĐỪNG "sửa" cho khớp engine
Engine bật stop từ ranh giới ngày của nó (Rổ 4: 00:00 ET; MNKD: 00:00 JST). Live bật lúc
09:31 ET. Nhìn qua thì đó là một khe hở cần bịt. **Đo rồi thì ngược lại**
(`model_stop_activation_gap.py`, cổng đối chiếu từng lệnh):

| STP lên sàn | Rổ 4 P&L / MaxDD | MNKD P&L / MaxDD |
|---|---|---|
| engine (ranh giới ngày) | +$47.166 / $8.234 | +$22.294 / $2.122 |
| **live (09:31 ET)** | **+$93.375 / $7.144** | **+$33.571 / $1.920** |
| không có stop | −$46.369 / $60.138 | +$7.486 / $5.870 |

Mốc live **tốt hơn trên cả hai trục** ở cả hai sleeve. Nhánh không-stop (lỗ nặng, MaxDD
gấp 7 lần ở Rổ 4) chứng minh đây không phải kiểu "hoãn càng lâu càng lãi" — có điểm tối
ưu ở giữa và 09:31 nằm gần nó.

Cơ chế hợp lý: 00:00–09:31 ET là phiên Globex đêm, thanh khoản mỏng; stop hẹp (~1/22 dải
chandelier) bị quét rồi giá hồi trước giờ mở cửa Mỹ.

**Bền tới đâu** (`model_gap_robustness.py` — tách theo năm + so trên vault; KHÔNG chạy WFO
vì WFO là để CHỌN tham số, mà ở đây không chọn gì, 09:31 là thứ hệ thống làm sẵn):

| | Rổ 4 | MNKD |
|---|---|---|
| live thắng | **9/9 năm** | 7/9 (thua 2020 −$170, 2022 −$492) |
| năm lớn nhất | 2022 = 37% tổng chênh | 2026 = 35% |
| IS (trước 2023) | +$25.674 | **+$324** ← ~bằng 0 |
| VAULT 2023–24 (OOS) | +$8.520 | +$4.888 |
| sau vault (2025+) | +$12.016 | +$6.064 |

Rổ 4 dương ở cả ba giai đoạn, không năm nào áp đảo → **kết luận vững**.
MNKD lợi thế **chỉ từ 2023**; trong mẫu IS gần như không có. Mạnh ngoài mẫu yếu trong mẫu
là hướng ngược với overfit (không có gì được fit), nhưng gợi ý một thay đổi chế độ chứ
không phải quy luật xuyên suốt → **với MNKD chỉ nói "khe hở không gây hại", đừng dựa vào
con số**.

⚠️ Thêm một job đặt STP lúc ~00:05 ET để "khớp engine" sẽ **làm xấu đi**, không cải thiện.

⚠️ **09:31 KHÔNG phải mốc được thiết kế** — nó là giờ chạy job `MAX_HOLD` (chọn để khớp
mốc thoát 09:30 RTH của backtest), còn B4 đặt STP ở đó chỉ vì `run_maxhold_exit` dựng
`FuturesRunner`. Hai quyết định không liên quan nhau. Đã đo và nó tốt hơn ranh giới ngày,
nhưng mới có **ba điểm** (00:00 / 09:31 / không bao giờ) — **không đủ để nói 09:31 tối
ưu**. Đổi giờ job MAX_HOLD, hoặc sửa nó thôi không dựng `FuturesRunner`, sẽ dời giờ đặt
STP theo mà không có gì báo.

⚠️ Điều này cũng nói rằng **luật của engine không phải chỗ tối ưu** — nhưng đó là phát
hiện về CHIẾN LƯỢC, phải qua WFO. Không được chỉnh mốc theo đỉnh backtest: ta giữ 09:31 vì
đó là thứ hệ thống đang làm sẵn, không phải vì nó là đỉnh.

### Mức stop là CỐ ĐỊNH, không trail
Live gửi mức chandelier tính lúc vào lệnh và giữ nguyên suốt đời lệnh (backtest thì siết
dần). Đo được: chênh **+$132 (0,3%)**, chỉ 9/3.044 lệnh thoát khác — **không cần sửa**.

---

## STRESS_MID — slot 10:20 ET và bất biến bắt buộc

### Chạy khi nào
| giờ ET | job | làm gì |
|---|---|---|
| **10:20** | `stress_mid` | vào lệnh STRESS_MID từ bar 09:30–10:15, `--clusters stress --stress-entry` |
| **14:05** | `live_day` | `diff_desired_vs_held` **đóng** vị thế stress (gần mốc 14:00 của adapter) |

Sleeve chỉ vào lệnh trong chế độ **Stress** — ~59 lệnh/năm toàn rổ, dồn vào các năm biến
động. **Một năm êm có thể không có lệnh nào**; im lặng không phải là hỏng.

`prev_preflight=True` vì job 13:45 chưa chạy lúc 10:20 — dùng bản cập nhật dữ liệu của
ngày làm việc trước, cùng cơ chế slot đêm NKD.

### 🔴 BẤT BIẾN — KHÔNG thêm slot nào gọi `run_live_day` giữa 10:20 và 14:05 ET
`_mark_held_unchanged` **không** được gọi cho cluster stress, nên `diff_desired_vs_held`
đóng vị thế ở **lần chạy kế tiếp**, bất kể lần đó là khi nào. Với lịch hiện tại lần đó là
14:05 — và đó là lý do sleeve giữ được **~91%** luật đã kiểm định.

| | P&L |
|---|---|
| luật đã kiểm định (stop/target/14:00) | +$14.151 |
| live hiện tại (đóng ở slot 14:05) | **+$12.850** |
| nếu có slot xen giữa buổi sáng | **−$450** |

Vi phạm bất biến này **không phát ra tín hiệu nào** — không log đỏ, không guard. Đã chốt
bằng test `test_stress_slot_invariant.py`; nó quét toàn bộ job của scheduler.

⚠️ **Đừng sửa bằng cách thêm `_mark_held_unchanged` cho stress** — khi đó không gì đóng vị
thế nữa và nó qua đêm. Muốn bỏ bất biến thì phải cho stress một luật thoát tường minh
trước.

### Ba sai lệch so với backtest, đã đo
| | ảnh hưởng |
|---|---|
| `to_candidate` vứt bỏ `target` 2R → không có lệnh chốt lời | −5% |
| giá vào trễ ~10 phút (bar đóng +5, `run_day` +5) | −15% |
| thoát ~14:10 thay vì 14:00 | +$1.520 (tình cờ có lợi, không phải thiết kế) |

Nên **đừng so P&L paper của sleeve này với số backtest rồi kết luận về edge** — hai bên
chạy hai luật khác nhau. Sleeve vốn ở mức **p=0,112**: chưa đủ bằng chứng, không phải đã
chứng minh không có edge. Đang chạy để theo dõi, và theo dõi ở đây là chuyện nhiều năm.

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

---

## Khởi động scheduler hằng ngày

```powershell
pythonw -m global_index.run_scheduler --port 4002 [--shadow-resume]
```

**Phải sống trước 13:45 ET** (pre-flight). Nếu không, mọi slot trong ngày bị bỏ qua —
fail-closed, không đoán từ parquet.

### ⚠️ Bật sau 09:31 ET = mất `maxhold_exit` hôm đó, KHÔNG có cảnh báo

APScheduler tính lần bắn kế tiếp lúc khởi động. Bật lúc 09:43 thì mốc 09:31 hôm nay
**không trễ — nó không tồn tại**, lần kế là 09:31 ngày mai. Không log, không notify.

Hệ quả: vị thế đủ 5 ngày sẽ thoát qua `run_live_day` lúc ~14:10 ET thay vì 09:30 ET,
tức **muộn hơn quy ước backtest 4h40**. Đã xảy ra 2 ngày liên tiếp (08-05 bật 09:43,
08-06 bật 10:35); không tốn tiền vì hôm đó chưa vị thế nào đủ 5 ngày.

**Kiểm mỗi sáng:** vị thế nào có `hold >= 4` trong `live_positions.json`? Nếu có, bảo
đảm scheduler sống trước 09:31 ET, hoặc chạy tay:
```powershell
python -m global_index.run_maxhold_exit --positions-path live_positions.json --port 4002
```
Script này idempotent (đóng vị thế `hold >= 5`, chạy lại khi đã đóng thì không làm gì)
và **không cần parquet tươi** — nó đọc `live_positions.json` + broker, nên không phụ
thuộc pre-flight 13:45.

---

## Checkpoint replay + shadow

`run_live_day` phát lại 2018→nay, 4 instrument, **mỗi slot**, chỉ để biết hiện nên giữ
vị thế gì — mất 5 phút 03 trong tổng 5,5 phút mỗi lần chạy. Engine có thể resume từ vị
thế cuối ngày hôm trước thay vì làm lại (`futures/_validated_core.backtest_swing_tf`,
tham số `resume_pos` / `resume_after_day` / `datr`).

### Hai cờ, chi phí lệch nhau 15 lần

| cờ | làm gì | tốn |
|---|---|---|
| `--shadow-resume` | tính đường resume, ghi log, đẩy checkpoint | **~30 giây** |
| `--shadow-verify` | **thêm** replay đầy đủ để tự đối chiếu | **~7,5 phút** |

**`--shadow-verify` chỉ bật ở slot cuối ngày (15:55 ET).** Nó phải chạy đúng cái replay
đầy đủ mà việc này sinh ra để tránh. Bật ở mọi slot thì `run_live_day` lên ~13 phút →
bỏ 2 trong 3 slot thay vì 1 trong 2 → **độ trễ vào lệnh tệ hơn hiện tại, bằng tiền thật**.
Một lần mỗi ngày là đủ: nếu hai đường lệch thì lệch cả ngày, không lệch riêng một slot.
Ở slot 15:55 phiên đã đóng, chạy quá sang 16:08 cũng không có lệnh nào chờ.

### Khởi tạo checkpoint (một lần, hoặc sau khi sửa parquet)

```powershell
python -m global_index.replay_checkpoint --bootstrap
```
~10 phút, replay đầy đủ 5 instrument. Sau đó live chỉ resume và bước tới.

### Checkpoint hỏng thì sao — không sao

Mỗi entry mang fingerprint của lịch sử **tính đến `last_day`**. Parquet đổi → fingerprint
lệch → tự bỏ qua, replay đầy đủ như cũ. **Chậm, không bao giờ sai.** Log ghi
`khong co checkpoint dung duoc`. Chữa: chạy `--bootstrap` lại.

Fingerprint cố ý **không** phủ phần sau `last_day`, để append hằng ngày lúc 13:45 không
tự huỷ checkpoint mỗi chiều.

⚠️ **Bấy nhiêu là chưa đủ, và phiên 2026-08-07 đã chứng minh.** Append lúc 13:45 ET bổ
sung cả **phần đuôi của ngày hôm trước** — 13:46→23:59 ET. Nếu checkpoint đã neo vào ngày
đó khi parquet mới có nửa ngày, thì phần lịch sử "tính đến `last_day`" vẫn lớn lên và
fingerprint tự hỏng sau đúng một ngày. Cả phiên 08-07, bốn mã Rổ 4 đều báo
`khong co checkpoint dung duoc`, lệch **554 bar** = đúng số bar 13:46→23:59 ET ngày 08-06;
**phiên đó không thu được bằng chứng nào**.

MNKD thì không sao, và lý do cho điều kiện tổng quát: khung của nó là **Tokyo**, ngày đóng
lúc 00:00 JST = **15:00 UTC**, tức **trước** mốc append (13:45 ET = 17:45 UTC). Rổ 4 khung
**ET**, ngày đóng 00:00 ET = 04:00 UTC hôm sau, tức **sau** mốc append. Điều kiện là **mốc
cắt phải nằm trước ranh giới append**, và lấy session áp chót *trên chính khung của dữ
liệu* thoả cả hai mà không phải phân biệt mã nào.

⚠️ Khi tự kiểm bằng script: `futures._validated_core.load_parquet` trả khung **ET tz-aware**,
còn `global_index.update_ibkr_daily._load_parquet` trả khung **UTC**. Đếm bar bằng loader
này rồi so với fingerprint sinh bởi loader kia sẽ ra số vô nghĩa (đã mắc: 314 thay vì 554).

Vì vậy `replay_checkpoint.advance_day()` chọn ngày **theo parquet**, không theo khung đã
ghép (khung ghép có bar live nên đã đủ ngày hôm qua, parquet thì chưa), và luôn **lùi một
ngày so với session cuối của parquet**. Hệ quả cần biết khi đọc log: slot đêm chạy trước
13:45 ET sẽ chọn ngày sớm hơn slot chiều — **đúng như thiết kế**.

Sau **bất kỳ** lần ghi lại parquet (ví dụ `fix_offset_step.py`, backfill, rebuild) phải
chạy lại `--bootstrap`, nếu không shadow sẽ im lặng không thu được gì.

### Đọc log shadow

```
[shadow] MES: tu checkpoint 2026-08-06 -> SHORT entry=7743.75 stop=7753.21 vao=2026-08-06
[shadow] MES: checkpoint tien 2026-08-05 -> 2026-08-06   ← luôn lùi 1 ngày so với parquet
[shadow] MES: DOI CHIEU KHOP — day du == resume        ← chỉ có ở slot 15:55
```

**`DOI CHIEU LECH` là CRITICAL** — hai đường bất đồng, dừng kế hoạch chuyển sang resume
và điều tra trước khi làm gì tiếp.

⚠️ Giá trong dòng `[shadow]` nằm trên **thang back-adjusted**, còn giá lệnh thật
(`C1 OPEN`, `STP: placed`) trên **thang thô**. Chênh nhau đúng bằng offset splice in ở
dòng `[sig] live-bar price offsets`. Ví dụ MES offset 10,75: shadow 7743.75 ↔ lệnh
7733.00. **Chênh đúng bằng offset = khớp, không phải lệch.**

### Trạng thái hiện tại

Shadow **chưa quyết định gì** — đường replay đầy đủ vẫn là đường giao dịch. Chỉ sau vài
phiên `DOI CHIEU KHOP` liên tiếp mới xét chuyển sang dùng resume thật; khi đó `run_day`
xuống dưới 1 phút, hết bỏ slot, độ trễ vào lệnh từ ~7,9 xuống ~3,5 phút.

---

## Rollover hợp đồng — điều gì tự chạy, điều gì cần người

Roll 4 lần/năm (`ROLL_SCHEDULE` trong `ibkr_broker.py`). Rổ 4: 11/9, 11/12.
NKD sớm hơn một tuần: 4/9, 4/12.

### Tầng dữ liệu — thường TỰ XỬ LÝ

`update_ibkr_daily` phát hiện roll bằng **định danh hợp đồng** (`qualifyContracts`
trả `MESU6` → `MESZ6`), không phải suy từ độ lớn biến động. Nếu đủ bốn điều kiện thì
nó **tự neo lại offset và chạy tiếp**:

1. Định danh hợp đồng đã đổi
2. ≥ 500 bar chồng lấn giữa parquet và lần fetch
3. IQR ≤ 20% mức dịch — dịch mức sạch, không phải nhiễu
4. Mức dịch nằm trong 0,20%–2,00% giá — cỡ chi phí nắm giữ

Log sẽ hiện:
```
MES: CONTRACT ROLLED MESU6 -> MESZ6 — re-anchored and continuing.
     Shift -66.7500 (0.862% of price) over 3946 shared bars, IQR 1.7500 (3% of shift).
     Offset +0.0000 -> -66.7500.
     Tomorrow's alignment check verifies this.
```

⚠️ **Hôm sau phải kiểm log.** Nếu neo sai, `ALIGNMENT DRIFT` sẽ xuất hiện — **không
được bỏ qua một ALIGNMENT DRIFT vào ngày sau roll.**

### Khi guard CHẶN — quy trình

Thiếu bất kỳ điều kiện nào → từ chối → `exit(1)` → pre-flight fail → **toàn bộ slot
ngày đó skip**. Log nói rõ thiếu điều kiện nào.

**Bước 1 — đọc log, xác định loại lỗi:**

| thông báo | nghĩa là |
|---|---|
| `CONTRACT ROLLED ... refusing (IQR is N% of the shift)` | roll nhưng dữ liệu nhiễu — **không** neo tay, điều tra trước |
| `CONTRACT ROLLED ... refusing (shift is N% of price, outside ...)` | roll nhưng mức dịch không giống carry — kiểm xem có phải roll thật |
| `ALIGNMENT DRIFT` + IQR nhỏ | parquet bị dựng lại mà quên sidecar (**sự cố 05/8**) — log in sẵn offset đúng |
| `ALIGNMENT DRIFT` + IQR lớn | hai nguồn lệch từng bar — lỗi dữ liệu, **không phải** lỗi offset |
| `JOIN JUMP ... NO contract change` | bar hỏng / fetch nhầm hợp đồng |

**Bước 2 — kiểm chéo giữa các mã.** Roll thật làm **mọi** chỉ số tương quan dịch cùng
chiều, biên độ tương đương (%). Một mã lệch một mình = lỗi dữ liệu, không phải roll.

**Bước 3 — sửa.** Với ca "quên sidecar", log đã in đúng con số cần đặt:
```
The offset that would align it is +11.5000
```
Sửa `global_index/data/_ibkr_splice_offsets.json` rồi chạy lại:
```powershell
python -m global_index.update_ibkr_daily --port 4002
```
Phải thấy `ALL 5 INSTRUMENTS UPDATED`. Nếu vẫn báo lỗi — **dừng, đừng ép**.

**Bước 4 — chỉ khi bước 3 sạch**, bật lại scheduler để giao dịch trong ngày:
```powershell
pythonw -m global_index.run_scheduler --port 4002 --shadow-resume --assume-preflight-ok
```

⚠️ **`--assume-preflight-ok` bỏ qua toàn bộ cổng 13:45.** Nó chỉ hợp lệ khi bạn vừa
tự chạy `update_ibkr_daily` thành công. Dùng nó để "cho chạy tiếp" khi chưa sửa gì là
biến một ngày mất thành một ngày **giao dịch trên dữ liệu hỏng**.

Ngân sách thời gian: pre-flight 13:45 ET, phiên 14:05 ET → **20 phút**, trong đó
`update_ibkr_daily` mất ~3,5 phút.

### Tầng vị thế — tự xử lý

Khi roll, `_handle_rollover` đóng hợp đồng cũ và mở hợp đồng mới, rồi runner **huỷ
lệnh STP cũ và đặt lại trên hợp đồng mới**, mức stop dịch theo chênh lệch **đã khớp
thật** (`giá mở mới − giá đóng cũ`). Lệnh STP mồ côi trên hợp đồng cũ nguy hiểm hơn là
không có stop: nó có thể khớp và **mở một vị thế mới không ai yêu cầu**.

Cần chú ý trong log:
```
C2: cancelled old-contract stop orderId=... for MES
C2: stop rolled MES: 7700.0000 -> 7766.7500 (shift +66.7500) orderId=...
```
Bất kỳ dòng `C2: ... UNPROTECTED` hoặc `could NOT cancel` nào đều là **CRITICAL** —
vào TWS xử lý tay.

### Chưa từng chạy qua roll thật

Toàn bộ phần trên kiểm bằng dữ liệu dựng lại và bằng sự cố offset 05/8. **Lần roll
đầu tiên dưới đường ống này là 11/9/2026.** Hôm đó nên có người theo dõi log
13:45–14:05 ET thay vì tin hoàn toàn vào tự động.
