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

## Báo cáo phiên — thứ đọc mỗi sáng

`global_index/session_report.py`. **Tự chạy khi việc cuối cùng trong ngày xong**, ghi
`bao_cao_MMDD.txt` ở thư mục gốc. Chạy tay lúc nào cũng được:

    cd d:aits
    python -m global_index.session_report                  # hôm nay
    python -m global_index.session_report --date 2026-08-07
    python -m global_index.session_report --out bao_cao.txt

Mã thoát **0** = không có gì phải làm, **1** = có. Dùng làm cổng được.

### Cách nó chạy — không phải cron

Bám sự kiện `EVENT_JOB_EXECUTED | EVENT_JOB_ERROR` của **việc có giờ muộn nhất**, và việc
đó **tính ra từ lịch** chứ không viết cứng — thêm một việc muộn hơn thì báo cáo tự dời theo.
Kèm lưới an toàn cron 23:55 chỉ bắn khi cờ trong ngày chưa được đặt, tức chỉ khi việc cuối
không chạy nên sự kiện không bao giờ tới.

Hai lần đầu tôi đặt cron 16:00 rồi 23:50, cả hai đều sai cùng một kiểu: **lấy một con số
thay cho một điều kiện**. 16:00 bỏ trắng 8 việc chạy sau đó; 23:50 vẫn ra trước nếu lượt
quét 23:20 chạy quá 30 phút. Bất biến "báo cáo phải là việc cuối" ghim ở
`test_session_report_slot.py`.

### Đọc gì trong đó

| mục | nói gì |
|---|---|
| TÓM TẮT | một đoạn: có chặn giao dịch không, bao nhiêu việc theo lịch đã chạy, đang giữ mấy vị thế |
| VẤN ĐỀ | mỗi vấn đề ba câu — là chuyện gì · nghĩa gì với tiền và vị thế · cần làm gì (copy được câu lệnh) |
| VIỆC THEO LỊCH ĐÃ KHÔNG CHẠY | phần log **không tự nói ra được**: không chạy thì không có dòng nào |
| DIỄN RA BÌNH THƯỜNG | `STP HOAN`, "cửa sổ hoãn"… — nói ra để không bị sửa nhầm |
| CHUYỂN SANG RESUME | đếm phiên đủ 5 mã KHỚP liên tiếp; thiếu mã KHÔNG tính đạt, một mã LỆCH đưa chuỗi **về 0** |
| ĐANG GIỮ GÌ | từng vị thế, và với vị thế chưa có stop thì nói **giờ nào** nó sẽ được vũ trang |

Mức độ: `CHẶN GIAO DỊCH` > `NẶNG` > `CẦN BIẾT`. Xếp theo mức, không theo số lần.

### Ba cái bẫy nó đã xử — biết để tin được nó

**Đồng hồ.** Log ghi giờ **MÁY** (hiện là MST, ET = máy + 2h); báo cáo đổi sang ET trước khi
so với lịch job. Bẫy nặng không phải độ lệch 2 tiếng mà là **ranh giới ngày**: cửa sổ đêm
NKD 01:10–02:55 ET là 23:10–00:55 giờ máy, vắt qua nửa đêm của máy. Bản chưa đổi báo 7 slot
`nkd_night_01xx` là "không chạy" trong khi chúng chạy bình thường.

**Ngày quá khứ.** `--date` một ngày cũ thì báo cáo **không** in vị thế hiện tại (sổ chỉ giữ
trạng thái hiện tại, in ra sẽ thành "ngày 07/08 đang giữ vị thế vào lệnh ngày 10/08") và
**không** điểm danh theo lịch hiện tại (lịch đổi theo thời gian).

**Log cũ lẫn dòng pytest.** Đã chặn từ gốc, nhưng file cũ vẫn còn; bộ lọc **đếm và báo** số
dòng đã bỏ chứ không bỏ im lặng. Báo cáo trước ngày 10/08 vì thế vẫn nhiễu — đừng đọc phần
VẤN ĐỀ của chúng như tường thuật thật.

### Nuôi bảng nhận diện

Mỗi loại sự cố là một dòng trong `_KNOWN` (khoá tìm trong log · mức · tiêu đề · nghĩa là gì
· cần làm gì). Lỗi mới sẽ rơi vào khoảng trống và **không được diễn giải** — gặp thì thêm
một dòng. Phần đắt là câu "nghĩa là gì": log không bao giờ nói ra nó.

## clientId — mọi tiến trình chạm STP phải dùng CHUNG một id

**IBKR chỉ nhận lệnh huỷ từ chính clientId đã đặt lệnh.** `ibkr_broker.cancel_order` đã biết
điều này từ 2026-08-06 (*"MYM #10 refused cancels from clientIds 1, 77 and 82, then cancelled
first try from 93, the id that placed it"*) — nhưng kiến trúc thì chưa:

| tiến trình | clientId cũ | việc | hệ quả |
|---|---|---|---|
| `run_live_day` | 1 | runner **đặt** STP; C2 huỷ khi roll | cùng tiến trình, cùng id → OK |
| `run_maxhold_exit` | **2** | **huỷ** STP khi đóng vị thế | **không bao giờ thành công** |
| `repair_stops` | 86 | **huỷ** ORPHAN / WRONG-WAY / HAZARD | **không bao giờ thành công** với STP do runner đặt |

Hệ quả không phải một cảnh báo bị bỏ lỡ mà là **mỗi lần MAX_HOLD đóng vị thế lại để lại một
STP mồ côi**, và MAX_HOLD chiếm 15% số lệnh. Lệnh mồ côi khi khớp không vô hại — nó **MỞ một
vị thế ngược chiều** mà không ai đặt.

**Đã sửa:** `run_maxhold_exit` và `run_stop_repair` chuyển về clientId **1**, trùng runner.
Việc tránh đụng độ được xử bằng **lịch** chứ không bằng id: 09:31 và các slot quét sửa ở phút
:20 đều không giao với slot nào. Công cụ **chỉ đọc** (`check_open_orders`, id 88) giữ id
riêng — ép nó về 1 sẽ đá runner ra khỏi Gateway khi scheduler đang sống.

`repair_stops` (id 86) là công cụ tay và phải huỷ được lệnh do **bất kỳ** id nào đặt, nên nó
không thể có một id đúng cố định. Khi huỷ hụt nó in ra đúng lệnh chạy lại:

    python -X utf8 global_index/repair_stops.py --client-id N --execute

với `N` là id lấy từ dòng `placed by clientId=N` mà `cancel_order` ghi ra.

Ghim bằng `test_stop_client_id.py` (5).

### Sự cố 2026-08-10 — STP mồ côi #12 trên MYM

09:31 MAX_HOLD đóng MYM. CLOSE thành công → `run_maxhold_exit` thoát 0. `cancel_order('12')`
thất bại (sai chủ: #12 do clientId 81 đặt). Runner kêu CRITICAL `STP ORPHAN`, nhưng `_run`
bắt output của tiến trình con **rồi vứt đi** vì `returncode == 0` — log chỉ còn `completed
OK`. Lệnh BUY STP treo ở 54709.00 suốt buổi, không vị thế nào phía sau.

Sổ sạch, `maxhold_state` sạch, log sạch. Chỉ lộ ra khi hỏi thẳng IBKR:
`get_working_stops()` → `{'MYM': ['12']}` trong khi `get_positions()` → chỉ MNKD.

Xử lý: `repair_stops --client-id 81 --execute` → huỷ được ngay lần đầu (`code=202 Order
Canceled`), xác nhận chẩn đoán sai-chủ.

Hai bản vá kèm theo:
* `_run` nay quét output tìm dòng `CRITICAL`/`ERROR` **kể cả khi thoát 0** và ghi chúng ra
  (vẫn trả True). Lọc theo **mức độ**, không theo **mã thoát**: mã thoát chỉ nói việc chính
  đã xong, không nói mọi việc phụ đều ổn. `test_run_echoes_critical.py` (6).
* Khối VERIFY của `repair_stops` không còn đếm `DEFERRED` là thiếu sót — trước đó một lần sửa
  thành công vẫn in `FAIL — 1 gap(s) remain` chỉ vì có vị thế đang trong cửa sổ hoãn.

### Khung thời gian đặt lệnh — CÓ CHỦ ĐÍCH

**Luật một câu: cả Rổ 4 và NKD đều chỉ vũ trang stop 14 giờ sau khi sang ngày mới, đo trên
đồng hồ phiên của chính sleeve đó.** Một hằng số duy nhất, rơi vào hai giờ ET khác nhau vì
hai sleeve chạy hai đồng hồ:

| sleeve | giờ vũ trang | quy ra ET | slot đầu tiên ≥ giờ đó |
|---|---|---|---|
| `roska4_swing` | 14:00 America/New_York ngày N+1 | 14:00 ET | **14:05 ET** |
| `global_nkd` | 14:00 Asia/Tokyo ngày N+1 | 01:00 ET (hè) · 00:00 ET (đông) | **01:10 ET** |
| `roska4_stress` | không hoãn — adapter xét stop ngay từ bar vào lệnh | — | — |

Khai bằng **múi giờ**, không phải giờ ET cố định: chênh ET↔JST đổi theo DST (hè 13h, đông
14h), nên "01:00 ET" đúng mùa hè nhưng thành 15:00 JST mùa đông. Bảng `_ARM_BY_CLUSTER`
trong `runner.py` giữ cặp `(tz, hh, mm)`, không giữ giờ ET.

14h không phải đỉnh của một bảng số: hai phép walk-forward **độc lập** (Rổ 4 và MNKD — hai
đồng hồ, hai bộ dữ liệu) đều hội tụ về nó, chọn h\* trên các năm trước rồi đánh giá trên năm
giữ lại. Rổ 4 h\*=14h ở 6/7 năm, MNKD 7/7.

#### Vì sao B4 không lọc theo cluster — và tại sao điều đó là đúng

B4 chạy trong `FuturesRunner.__init__`, tức **mọi job dựng một runner đều chạy nó**, trên
**toàn bộ** vị thế trong sổ. Các job dựng runner: 22 slot đêm (01:10–02:55), 09:31 MAX_HOLD,
và 23 slot ngày (14:05–15:55). Cờ `--clusters` của job **không** giới hạn B4 — nó chỉ giới
hạn `generate_today_signals`, tức việc *sinh tín hiệu*.

Nghe qua thì như một lỗ hổng. Thực ra là hai việc khác nhau bị gộp vào một khối, và tách
chúng ra bằng cờ cluster sẽ hỏng cả hai:

* **Vũ trang lần đầu** — đặt cái stop đã được cố tình hoãn. Việc này PHẢI theo sleeve, và cái
  quyết định nó là vị từ `_stop_deferred`, không phải cờ job. Vị thế Rổ 4 mở hôm qua đi qua
  22 slot đêm mà không được đặt stop, vì `_stop_deferred` trả True cho tới 14:00 ET.
* **Sửa chữa** — đặt lại stop cho vị thế đã qua cửa sổ hoãn mà mất stop (bị từ chối, bị huỷ
  tay, id trỏ vào lệnh chết). Việc này KHÔNG được theo sleeve: một vị thế Rổ 4 mất stop lúc
  nửa đêm mà phải chờ tới 14:05 là 13 tiếng trần không vì lý do gì.

Nếu lọc B4 theo cluster thì vế thứ hai chết: slot đêm `--clusters nkd` sẽ bỏ qua một vị thế
Rổ 4 đang trần. Nếu bỏ `_stop_deferred` thì vế thứ nhất chết: slot đêm vũ trang Rổ 4 sớm 13
tiếng — đúng lỗi đã có, đo được chênh +$41.505 → +$116.530 ngoài mẫu.

#### Xác nhận: slot nào đặt stop cho sleeve nào

Chạy vị từ thật trên toàn bộ lịch slot:

| | slot đêm 01:10 | slot 14:05 |
|---|---|---|
| vị thế **mới** (vào lệnh ngày N, xét ngày N+1) | **chỉ NKD** | **chỉ Rổ 4** |
| vị thế **cũ** (đã qua cửa sổ hoãn) | cả hai, kể cả Rổ 4 | cả hai |

Nên câu "slot đêm chỉ đặt stop cho NKD" đúng cho **vũ trang**, không đúng cho **sửa chữa** —
và sự khác nhau đó là chủ đích, không phải rò rỉ. Hệ quả vận hành: thấy dòng
`B4 REPLACED: MES/roska4_swing` lúc 1 giờ sáng thì **không phải** giờ vũ trang bị rò; đó là
guard sửa chữa đang làm việc của nó, và nó có nghĩa là vị thế đó đã mất stop từ trước.

Bất biến này được ghim bằng test: `test_arm_time_per_sleeve.py` (giờ vũ trang theo sleeve,
kèm ca DST) và `test_slot_arms_which_sleeve.py` (bảng trên, chạy trên đúng lịch slot).

### Ba lỗ hổng tìm ra ở lượt soi lại (2026-08-10)

Lượt sửa trước soi câu hỏi *"stop này thuộc vị thế nào"*. Ba cái dưới đây thuộc câu hỏi
khác — *"chuyện gì xảy ra khi hợp đồng đổi tháng"* — nên lượt trước không chạm tới.

**1. Rollover ghi mức stop chỉ khi lệnh được nhận.** `pos.stop_price = _new_stop` nằm trong
nhánh `if _sid:`. Lệnh bị từ chối thì mức của hợp đồng **cũ** ở lại trên sổ, và B4 — vốn chỉ
đặt khi "đã biết mức" — sẽ đặt mức cũ đó lên thang giá hợp đồng **mới** ở phiên sau. Sai
đúng bằng khoảng chênh hai hợp đồng, và không có gì kêu. Sửa: ghi mức **trước** khi đặt, giữ
nguyên dù lệnh có được nhận hay không.

**2. Rollover vũ trang stop sớm.** C2 đặt stop mới ngay, bất kể cửa sổ hoãn. Vị thế vào lệnh
phiên trước rồi hợp đồng đổi tháng vào sáng hôm sau sẽ được vũ trang trước giờ — đúng một vị
thế, chỉ vì hợp đồng của nó tình cờ roll. Roll không dời `entry_day` nên cửa sổ không đổi.
Sửa: C2 tôn trọng `_stop_deferred`, chỉ ghi mức và để B4 đặt đúng giờ vũ trang của sleeve.

**3. `classify` có thể nhận nhầm stop của hợp đồng đã chết.** Khi C2 huỷ **hụt** (nó ghi
CRITICAL rồi chạy tiếp), hai STP cùng chiều cùng mã khác tháng đáo hạn cùng sống. Nhận theo
chiều + kích thước sẽ trao cho vị thế cái đến trước trong danh sách — có thể là cái của hợp
đồng đã chết — rồi báo stop **thật** là thừa, và `repair_stops` sẽ huỷ đúng cái đang bảo vệ.
`live_positions.json` không ghi expiry, nên định danh duy nhất có trên sổ là `stop_order_id`.
Sửa: nhận **lệnh mình ghi trước**, phần thiếu mới lấy tiếp theo chiều — và chỉ nhận id đã ghi
nếu nó đúng chiều bảo vệ.

`_roll_stop` được tách khỏi `_handle_rollover` để test gọi thẳng được. Bản test đầu tiên tôi
viết đã chép lại nhánh giá của C2 vào chính helper rồi assert lên nó — tức chỉ chứng minh bản
chép đúng với chính nó. Test: `test_stop_rollover_gaps.py` (9).

### Quét sửa stop trong ba khoảng trống (2026-08-10)

Việc sửa chữa của B4 cho tới nay chỉ **đi ké** các slot dựng runner, mà lịch slot được dựng
cho việc **vào lệnh**. Đo khoảng trống giữa chúng:

| khoảng | không có job nào |
|---|---|
| **15:55 → 01:10** | **9h15** — và đúng cái đêm stop sinh ra để bảo vệ |
| 02:55 → 09:31 | 6h36 |
| 09:31 → 14:05 | 4h34 |

Không ai chọn con số 9h15; nó là hệ quả. `run_stop_repair.py` lấp bằng **một lượt quét mỗi
~2 tiếng**, ở phút :20, **bỏ qua** lượt nào rơi vào cửa sổ vào lệnh (01:00–02:55 và
14:00–15:55 ET) — 10 lượt/ngày. Job dựng runner với `signal_fn` rỗng, **không** gọi `run_day`,
**không** gọi `run_maxhold_exit`; toàn bộ tác dụng nằm ở B1–B5 trong `__init__`.

Bỏ hai lượt trong cửa sổ để lại hai khoảng 4 tiếng trên giấy, nhưng khoảng **thật sự** không
ai nhìn ngắn hơn nhiều, vì trong cửa sổ đã có slot chạy mỗi 5 phút và mỗi slot đều dựng
runner: `00:20→01:10` (50p) · `02:55→04:20` (1h25) · `12:20→14:05` (1h45) · `15:55→16:20` (25p).

Số lượt này đã đi qua ba bản. Đầu tiên 19 lượt mỗi tiếng — sai vì lấy *"lấp kín khoảng
trống"* làm mục tiêu thay cho *"giảm thời gian không ai nhìn"*. Rồi cắt xuống 3. Cả hai đều
là lập luận suông, không phải số liệu: **mọi lần vị thế thật sự mất stop đều do bug đã sửa**
(order id sinh phía client 05/08, clientId sai khi huỷ 10/08), nên hiện không còn nguyên nhân
sống nào để lượt quét phòng. Mốc 2 tiếng là do người vận hành chốt, và nó là quyết định đúng
loại: đây là chi phí quan sát trong giai đoạn code stop mới chưa tự chứng minh, không phải
hạ tầng vĩnh viễn.

Một cái giá phải ghi rõ: `run_stop_repair` **ghi `live_positions.json`**. Đó là đường code
mới sửa file trạng thái lúc không ai nhìn — nếu vài phiên tới thấy nó không bắt được gì, bỏ
job đi là lựa chọn hợp lý chứ không phải thất bại.

Nó **không** đụng vế vũ trang: `_stop_deferred` vẫn chặn, nên một lần chạy lúc 20:00 ET
không vũ trang sớm vị thế Rổ 4 mở cùng ngày. Nó chỉ chạm vế sửa chữa.

Giá phải trả đã cân: mỗi lần chạy là một lượt B3 nữa, tức thêm cơ hội halt entry vì mismatch
giả. Ba khoảng trống đều nằm **ngoài** cả hai cửa sổ vào lệnh nên halt ở đó không tốn gì, và
`_b3_halt_entries` không ghi xuống đĩa còn mỗi lần chạy là tiến trình riêng — halt không
theo sang slot giao dịch. Chạy như job **trong** scheduler nên dùng chung `_slot_lock`,
không tranh chấp `live_positions.json` (khác `repair_stops.py`, vốn đòi dừng scheduler).

Ghim bằng `test_stop_repair_slots.py` (9): không slot nào rơi vào cửa sổ vào lệnh hay trùng
09:31; cả ba lỗ đều được phủ; và hai điều kiện khiến việc miễn trừ khỏi bất biến STRESS_MID
là hợp lệ — `signal_fn` còn rỗng và `run_day` còn không được gọi.

### `has_working_stop` mù tháng đáo hạn — ĐÃ VÁ

Nó khớp theo **symbol**. Kịch bản để nó trả lời sai: roll + huỷ hụt + đặt mới bị từ chối —
khi đó stop của hợp đồng cũ vẫn sống, B4 thấy "đã được phủ" và ghi `STP ID DRIFT` (WARNING)
trong khi vị thế thật sự trần.

**Đã vá:** B4 hỏi thêm `unprotected_positions()` (khớp `(mã, expiry, bên)`, cộng số hợp
đồng). Hai bên bất đồng thì bên này thắng và vị thế được coi là NAKED. `None` — broker không
trả lời được, ví dụ MockBroker — thì **không ghi đè**, hành vi cũ giữ nguyên; nếu không, mọi
broker không trả lời được sẽ bị hiểu thành "đang báo trần".

Ghim bằng `test_stp.py::test_b4_8/9/10`: ghi đè khi bất đồng, không ghi đè khi `None`, không
ghi đè khi hai bên đồng ý (chặn chiều hỏng ngược — đặt stop chồng lên vị thế đã có stop).

### Mốc gốc h=0 của backtest — để khỏi phải truy lại

`_validated_core.py` gom bar bằng `dfg.groupby(dfg.index.normalize())`, tức "ngày" là ngày
lịch **theo múi giờ của chính khung dữ liệu**; khối thoát rồi quét
`np.where(low <= stop_prev)[0]` từ **index 0**. Nên backtest vũ trang stop tại **bar đầu
tiên của ngày lịch kế tiếp**:

| sleeve | khung dữ liệu | h=0 của backtest |
|---|---|---|
| Rổ 4 | ET tz-aware | **00:00 ET** |
| MNKD | Asia/Tokyo | **00:00 JST** |

Đây là gốc toạ độ mà mọi con số trong bản quét giờ vũ trang được đo từ đó — không phải mốc
phải chạy theo. Giờ vũ trang thực tế (`_ARM_BY_CLUSTER`: 14:00 theo đồng hồ của từng sleeve)
là **lệch có chủ đích và đã đo**: quét nhiều mốc, tách theo năm, kiểm trên vault, walk-forward
chọn h\* trên các năm trước rồi đánh giá trên năm giữ lại (h\*=14h, Rổ 4 6/7 năm, MNKD 7/7).

Lưu ý một chuyện dễ hiểu nhầm: **cổng reconcile không nhìn thấy độ lệch này**.
`verify_runner_real` chạy `FuturesRunner + MockBroker`, mà `MockBroker.place_stop` chỉ trả
`f"mock-stp-{inst}"` và không mô phỏng khớp lệnh — lệnh đến từ timeline dựng sẵn. Nên
reconcile khớp fit_C **không** là bằng chứng gì về giờ vũ trang, và nó không phủ chuyện đó
cũng không phải lỗ hổng. Bằng chứng cho giờ vũ trang nằm ở `model_sameday_stop.py` /
`model_activation_sweep.py`, đều gated trên việc tái tạo engine trade-for-trade.

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

### 🔴 STP hoãn được đặt lúc 01:10 ET — và mốc đó là hệ quả phụ, không ai thiết kế

B4 đặt STP, mà B4 chạy trong `FuturesRunner.__init__` → việc đặt xảy ra ở **job nào dựng
runner đầu tiên trong ngày**. Hiện là **slot đêm NKD 01:10 ET**. `--clusters nkd` chỉ chặn
việc SINH LỆNH, không chặn B3/B4 — nên slot đêm vẫn đặt stop cho **cả Rổ 4**.

Dự phòng: nếu slot đêm trượt (thiếu bản ghi pre-flight ngày trước) thì job MAX_HOLD
**09:31 ET** đặt. Vào lệnh thứ Sáu thì phải đợi thứ Hai — slot đêm chỉ Mon–Fri.

⚠️ Nếu bỏ NKD khỏi hệ thống, giờ đặt của **Rổ 4** tự lùi về 09:31 — một sleeve đổi hành vi
vì sleeve khác bị gỡ. Đã chốt bằng `test_stop_placement_time.py`.

### Khe hở so với engine: ~1,2 tiếng, không đáng kể
Engine xét stop từ ranh giới ngày; live đặt lúc 01:10 ET. Đo (`model_stop_activation_gap.py`):

| | Rổ 4 | MNKD |
|---|---|---|
| engine (ranh giới ngày) | +$47.166 / MaxDD $8.234 | +$22.294 / $2.122 |
| **live thật (01:10 ET)** | **+$49.895 / $8.234** | **+$25.791 / $2.055** |

Chênh 5,8% với MaxDD y hệt → **khe hở không gây hại, không cần bịt**.

⚠️ Bản ghi trước đó của tài liệu này nêu +$93.375 — đó là mốc **09:31**, chỉ xảy ra khi
slot đêm trượt. Sai vì đọc code mà không kiểm job nào chạy trước. Đã sửa.

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

### Preferred one-command startup

Log in to IB Gateway paper first, then run:

```powershell
cd D:\raits
python monitor\ops.py up
```

The launcher replaces stale monitor backend listeners on port 5002, starts
`global_index.run_scheduler` if needed, starts `monitor\start_backend.py`, waits
for `/api/connection`, and prints the Realtime/Paper URLs.

Operational checks:

```powershell
python monitor\ops.py status
python monitor\ops.py restart
python monitor\ops.py restart --scheduler
python monitor\ops.py down
python monitor\ops.py down --scheduler
python monitor\ops.py up --restart-scheduler
```

Never use `python -m flask --app monitor.backend.app:app run` as the operational
backend command. It serves Flask routes but does not start `ibkr_reader`, so the
dashboard will show broker truth unavailable even when IB Gateway is logged in.

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

---

## STRESS_MID: tại sao cron 10:20 bị TẮT (2026-08-10)

Job `stress_mid` đã được nối vào `run_scheduler.py` rồi **tắt lại trong cùng ngày**, trước
khi nó chạy lần nào. Lý do không nằm ở sleeve — nó nằm ở tầng theo dõi vị thế, và nó cũng
là lý do đáng ghi lại nhất: sleeve đúng luật vẫn có thể làm hỏng những sleeve khác.

STRESS_MID dùng **đúng bốn mã của Rổ 4** (MES/MNQ/MYM/M2K) và **luôn SHORT**. Toàn bộ tầng
broker lại khoá theo **MÃ**, không theo **VỊ THẾ**. Ba hệ quả, xếp theo mức độ:

**1 — Bù trừ ròng làm mù cả hai vị thế.** `get_positions()` và `ib.positions()` trả vị thế
**ròng có dấu** cho mỗi hợp đồng. MES swing LONG 1 + MES stress SHORT 1 → IBKR báo net 0.

- `runner.py` B3 dựng `file_key[(inst, direction)]` *có cộng dồn* — cùng chiều thì khớp
  đúng — nhưng ngược chiều thì file có hai khoá, broker không có khoá nào → **MISMATCH →
  HALT toàn bộ entry**.
- `unprotected_positions()` lặp `for p in ib.positions()` với `if not p.position: continue`
  → cả hai vị thế **biến mất khỏi phép kiểm bảo vệ**. Không phải báo nhầm là an toàn — là
  không nhìn thấy chúng nữa.
- `held_stress` trong runner chỉ chặn khi đã có vị thế **STRESS** cùng mã; nó không chặn
  khi đang có vị thế **SWING** cùng mã. Nên tình huống trên vào được.

**2 — Cùng chiều: một hợp đồng trần vĩnh viễn, im lặng.** Không bù trừ, nhưng:

- `has_working_stop(inst)` khoá theo **symbol**. Stress đặt stop trước → B4 tính
  `_can_replace = not has_working_stop(p.inst)` = False → **từ chối đặt stop cho swing**,
  đúng theo ý định "tránh xếp chồng STP", chỉ là ý định đó giả định một vị thế một mã.
- `unprotected_positions()` kiểm `if exp in have` — **sự tồn tại**, không phải **số lượng**.
  Một STP cho 1 hợp đồng phủ cả hai vị thế trên giấy tờ.
- `get_working_stops()` trả `{inst: orderId}` — một order id cho mỗi mã, nên B5 cũng bỏ qua.

**3 — `repair_stops.py` ghi bằng chứng SAI vào sổ.** Đây là cái nặng nhất, vì ba chỗ trên
chỉ là phép kiểm bỏ sót, còn chỗ này làm hỏng dữ liệu mà những tầng *đang chạy đúng* dựa vào:

- dòng 150 `by_inst = {p.get("inst"): p for p in positions}` — hai vị thế cùng mã thì **một
  cái đè cái kia, im lặng**. Kế hoạch `("place", inst, by_inst[inst])` sẽ đặt stop bằng
  `stop_price` và `direction` của cái thắng cuộc đua dict.
- dòng 113–114 `p["stop_order_id"] = new_ids[p["inst"]]` — vòng lặp đóng **cùng một order id
  lên MỌI vị thế của mã đó**. File ghi hai vị thế "đã có stop", thực tế một order phủ một vị
  thế.

Hệ quả kéo dài: `cancel_order(p.stop_order_id)` là một trong số ít chỗ *đang* làm đúng
(theo vị thế) — nhưng nó tin vào id trong sổ. Đóng vị thế A sẽ huỷ đúng cái stop đang bảo vệ
vị thế B. Chính docstring của `_persist` đã cảnh báo "a stale id is not harmless"; nó chỉ
chưa lường tới trường hợp id không cũ, mà là của người khác.

**4 — Không guard nào kêu.** Cả ba đều fail theo hướng "báo an toàn". Đây là dạng hỏng
giống hệt hố 17:00–18:00 và bug rò giờ vũ trang: hệ thống chạy, log xanh, tiền đi.

### Đã sửa (2026-08-10)

Câu hỏi sai — *"có stop nào cho mã này không?"* — đã được đổi thành *"vị thế NÀY có được
phủ không?"* ở cả năm chỗ:

| chỗ | trước | sau |
|---|---|---|
| `check_open_orders.classify` | `matching[0]` — một STP phủ mọi vị thế cùng mã | mỗi STP được **một** vị thế nhận; thêm verdict `PARTIAL` |
| `repair_stops` | `{p["inst"]: p}` đè vị thế; một order id đóng lên mọi vị thế | khoá `(inst, cluster)`; id lấy từ `classify`, ghi theo từng vị thế |
| `unprotected_positions` | `if exp in have` — sự tồn tại, không xét bên | cộng **số hợp đồng** theo `(mã, expiry, bên)` rồi so với vị thế |
| `has_working_stop` | boolean theo symbol | nhận thêm `direction`/`contracts`, đếm độ phủ đúng bên (dạng cũ vẫn giữ) |
| `get_working_stops` + B4/B5 | `{inst: orderId}` — ghi đè, hỏi `p.inst in working` | `{inst: [orderId,…]}`; hỏi *"id mà vị thế này ghi nhận còn sống không"* |

Kèm hai chỗ phụ: `PROTECTIVE_SIDE` chuyển về `ibkr_broker` làm **nguồn duy nhất** (trước đó
chỉ CLI tool có, nên tầng broker không hề xét bên); và B5 chỉ tắt cảnh báo khi **mọi** vị
thế trên mã đó đang trong cửa sổ hoãn — trước đây một vị thế hoãn làm câm cảnh báo cho vị
thế khác cùng mã đã thật sự mất stop.

Thêm một chỗ B4 phải tách bạch: vị thế **được phủ nhưng id ghi trong sổ không trỏ vào lệnh
nào đang sống** giờ ra `B4 STP ID DRIFT` (WARNING) chứ không ra `B4 NAKED` (CRITICAL). Phép
kiểm cũ (`p.inst in working`) im lặng ở ca này — chính sự im lặng đó để MES mang id bịa 62
bên cạnh stop thật #9 ngày 2026-08-05 cho tới khi đóng vị thế thì huỷ nhầm một con ma và bỏ
lại lệnh thật không có vị thế phía sau. Nhưng hô NAKED vào một vị thế đang được bảo vệ thì
lại là kiểu cảnh báo giả hằng ngày làm người ta thôi đọc chữ NAKED.

Test: `test_stop_per_position.py` (13), `test_unprotected_positions.py` (15, thêm 5 ca
bên/độ phủ), cùng cập nhật `test_stp.py` / `test_stp_accept.py` / `test_deferred_verdict.py`.

### CHƯA giải: bù trừ ròng

Không sửa được ở tầng broker — tài khoản thật sự không giữ gì để mà kiểm.

Tôi đã thử chặn ở `signal_layer` bằng luật *một vị thế mỗi mã, tính trên mọi cluster*, rồi
**rút lại**. Lý do: `deploy_sim.py:180-218` chạy `StressMidEngine().backtest_basket()` ĐỘC
LẬP với swing rồi nối hai danh sách lệnh — nó không bao giờ hỏi swing đang giữ gì. Tức là
sim đã kiểm định **cho phép** stress nằm cùng mã với swing. Siết luật đó là cho live chạy
một luật backtest chưa kiểm, đúng hình dạng đã làm mất $53k ở chuyện đặt stop; và nó còn phá
`verify_runner_real.py`, file tự khai nhiệm vụ là *"proves the full live path reproduces
deploy_sim fit_C trade-for-trade"*.

Nên đây là **điều kiện tiên quyết để bật STRESS_MID**, không phải giấy phép lặng lẽ đổi
chiến lược. Ba đường đi — **đã chọn (1)** ngày 2026-08-10, chưa triển khai:

1. **← ĐÃ CHỌN. Tài khoản/subaccount riêng cho sleeve stress** — bù trừ ròng biến mất vì hai sleeve
   không còn chung sổ ở IBKR. Không đụng tới chiến lược, không cần đo lại. Tốn công vận
   hành và một kết nối nữa.
2. **Nhận luật một-vị-thế-mỗi-mã rồi ĐO LẠI** `deploy_sim --include-stress` với ràng buộc
   đó. Rổ 4 giữ vị thế trên phần lớn số ngày (4 mã mở đồng thời 45–47% số ngày) nên nhiều
   khả năng phần lớn lệnh stress bị cắt — con số +$12.850 sẽ khác hẳn, và có thể sleeve
   không còn đáng bật.
3. **Cho stress dùng mã KHÁC** (ES/NQ full-size, hoặc mã ngoài Rổ 4) — hết chồng lấn hợp
   đồng. Cũng phải đo lại, và đổi cả bậc rủi ro.

### Cron vẫn TẮT

Tầng theo dõi stop đã sạch, nhưng bù trừ ròng thì chưa — và nó là cái chặn entry
(B3 MISMATCH) chứ không chỉ làm mù phép kiểm. Bật cron trước khi chọn một trong ba đường
trên là bật một sleeve chắc chắn sẽ làm dừng entry của toàn hệ ngay hôm nó vào lệnh trùng mã.

`test_stress_slot_invariant.py::test_the_stress_slot_is_disabled` giữ cron tắt cho tới lúc
đó. Cờ `--stress-entry` của `run_live_day` vẫn còn để chạy tay khi kiểm thử — chạy tay thì
có người nhìn, cron thì không.

### Cùng gốc: STRESS_MID không thoát đúng 14:00

Bảng giờ ET có dòng "STRESS — thoát 14:00"; nói vậy là thiếu. 14:00 là **trần**, không phải
mốc thoát: `StressMidAdapter` thoát ở cái nào đến trước trong stop / target, nếu không có
thì mới lấy bar cuối ≤ 14:00. Tỉ lệ đo được: **stop 35% · target 20% · eod 45%** — 55% số
lệnh thoát sớm hơn 14:00. Live thoát ở slot 14:05 (thực tế ~14:10), không phải 14:00.
