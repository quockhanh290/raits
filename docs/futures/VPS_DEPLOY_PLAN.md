# Kế hoạch chuyển hệ futures sang VPS Windows

**Ngày viết:** 2026-08-18 · **Máy hiện tại:** cá nhân, Calgary · **Đích:** VPS Windows, giữ ổ `D:`

Mọi con số trong tài liệu này được đo ngày 2026-08-18 trừ chỗ ghi rõ **[CHƯA ĐO]**.
Chỗ ghi **[CHƯA ĐO]** là giả định phải xác minh trước khi dùng để quyết, không phải số đã đo.

---

## 1. Vì sao chuyển bây giờ chứ không sau khi paper xong

`PAPER_ROUTE.md` xếp VPS vào ô *"sau paper, trước live"*. Đo lại thì thứ tự đó có một lỗ.

Paper mới đi được **15/60 phiên**. Giữ nguyên thứ tự nghĩa là toàn bộ bằng chứng —
100 fill, 60 phiên, mọi mẫu C1 — được chứng minh trên máy A, rồi tiền thật chạy trên
máy B chưa từng đóng góp một mẫu nào. Đó đúng họ lỗi "chứng nhận trên một môi trường,
chạy trên môi trường khác".

Chuyển sớm thì ngược lại: ~45 phiên còn lại sinh ra **trên chính môi trường sẽ chạy tiền**.
Giá phải trả là mẫu bị cắt làm hai — cắt ở phiên 15 rẻ hơn nhiều so với cắt ở phiên 60.

Bằng chứng máy hiện tại không đủ ổn định để mang tiền thật:

| Đo được | Số |
|---|---|
| Lần khởi động scheduler, 30/7 → 18/8 (20 ngày) | **44** (~2,2/ngày) |
| Job `completed OK` / job `exited` khác 0 | 203 / **35** |
| Đêm hỏng cả cụm slot NKD 02:00–02:25 ET | 14/8 — đúng khung không ai trực ở Calgary |

Máy này vừa là nơi phát triển vừa là nơi chạy tiền. Log tháng 8 còn lẫn cả lượt replay
(có dòng `today=2026-01-15` nằm giữa). Sang VPS mà còn lẫn thì mất luôn khả năng nói
"đêm qua có sự cố thật không".

---

## 2. Vì sao Windows chứ không Linux

Quyết định của chủ dự án 18/8. Cơ sở đo:

| | Windows VPS | Linux VPS |
|---|---|---|
| `monitor/ops.py` — 550 dòng chống trùng tiến trình (`Get-CimInstance`, `netstat -ano`, `taskkill`, `pythonw`) | chạy nguyên | phải viết lại toàn bộ |
| `exercise_rollover_live.py` | chạy nguyên | phải viết lại |
| IB Gateway tự đăng nhập lại sau restart 17:00 ET | như đang chạy | cần Xvfb + IBC, **[CHƯA ĐO]** với đường B3/STP-VERIFY |
| Chi phí | cao hơn | thấp hơn |
| Tự khởi động lại vì cập nhật hệ điều hành | **còn** — phải xử lý ở §5 | không |

Đổi lại việc port gần bằng 0, Windows mang theo đúng một rủi ro phải bịt bằng cấu hình:
hệ điều hành tự khởi động lại. Xem §5.

Hai thứ đã portable sẵn, không phải sửa dù chọn nhánh nào: `runner.py::_pid_alive`
có nhánh POSIX, và `flex_pull` đọc env có guard `sys.platform`.

---

## 3. Bề mặt phải mang theo (đã đo)

### Dữ liệu — 2,7 GB, KHÔNG được dựng lại

| Đường | Đo được |
|---|---|
| `data/cache/futures` | 71 tệp parquet, **2 501 MB** |
| `global_index/data` | **178 MB** |

Dựng lại từ Polygon/Databento mất 2–3 giờ và có rủi ro back-adjustment làm dịch giá
lịch sử. Đây là **chép**, không phải tải lại.

### Thư mục `models/` — chép hai tệp JSON, KHÔNG chép 43 575 pickle

Đo được: `models/hmm/` chứa **43 575 tệp `.pkl`** (54,8 MB) cộng đúng một tệp
`futures_freeze_registry.json` (761 B).

Truy xem ai đọc gì:

| Thứ | Ai đọc trên nhánh futures |
|---|---|
| `futures_freeze_registry.json` (761 B) | `futures/refreeze.py:51` — **phải chép** |
| `refreeze_pending.json` (cờ G3) | `futures/refreeze.py:68` — **phải chép nếu đang tồn tại** |
| 43 575 tệp `hmm_*.pkl` (54,8 MB) | **không tệp nào** |

Nhánh futures không bao giờ nạp pickle: `futures/_validated_core.py:112` gọi
`eng.fit(train, version_tag="gate2_spike", save=False)` — fit lại trong tiến trình,
`save=False`. Không có lời gọi `load_latest` nào trong `global_index/`, `futures/`
hay `monitor/`.

Đống pickle là dư của các lượt quét backtest, không phải của vận hành: **34 294 trên
43 575 tệp (79%) sinh trong đúng hai ngày 06–07/6**, còn ngày gần nhất có ghi (15/8)
chỉ 446 tệp. Mỗi tệp một nội dung khác nhau (kiểm 200 tệp liên tiếp → 200 hash phân biệt),
nên đây là tích tụ thật chứ không phải bản sao lặp.

**Cảnh báo lệch phạm vi, không phải mục chặn của futures:** engine HMM của nhánh
cổ phiếu (`raits/hmm/engine.py:368`) có `load_latest()` chọn pickle theo **thời gian
sửa tệp**. Nhánh đó đứng yên từ 10/7 và không nằm trong đợt chuyển này. Nhưng nếu sau
này dựng lại nó trên VPS thì một thao tác chép làm mới mtime sẽ đổi tệp được chọn —
phải chép giữ nguyên mtime, hoặc chốt tệp bằng tên chứ đừng bằng thứ tự thời gian.

### Phép chứng minh bản kiểm kê 2,7 GB là ĐỦ

Toàn repo có **123 033 tệp parquet / 7 362 MB**, trong đó **1 094 tệp nằm ngoài** hai
thư mục ở trên. Nên câu hỏi không phải "còn parquet nào không" mà **"đường chạy slot
đọc thư mục nào"**.

`run_live_day` khai `--data-dir` và `--nkd-parquet` là `required=True` — **không có
mặc định**, nên chữ ký CLI không trả lời được câu hỏi. Phải đọc bên gọi.

Liệt kê đủ tám module mà scheduler bắn ra, và mọi đường dữ liệu chúng nhận:

| Module | Đường dữ liệu |
|---|---|
| `run_live_day` | `data/cache/futures` · `global_index/data/NKD_...parquet` · `spy_daily_live.csv` · `live_positions.json` |
| `update_ibkr_daily` | `data/cache/futures` · `global_index/data/NKD_...parquet` |
| `update_spy_csv` | `spy_daily_live.csv` |
| `run_maxhold_exit` · `run_stop_repair` | `live_positions.json` |
| `session_report` · `flex_pull` · `paper_pnl_compare` | thư mục gốc, không parquet |

Không job nào chạm ra ngoài bản kiểm kê. 1 094 tệp còn lại thuộc `nonequity/`,
`intraday_pressure/`, `data/cache/data/` (SPY 5 phút của nhánh cổ phiếu) và
`data/cache/futures_vault2025` — không nhánh nào của lịch chạy đọc tới.

### Cái KHÔNG chép: 5,6 GB cache của nhánh cổ phiếu

`raits/data/cache` = **5,6 GB**. Nhánh cổ phiếu đứng yên từ 10/7 và không thuộc đợt
chuyển này. Đợt chuyển là **2,7 GB**, không phải "chép cả `d:\raits`" — chép cả thư
mục gốc là 8,3 GB, trong đó hai phần ba không có ai trên VPS đọc tới.

Hệ quả phải nói ra: sau khi chuyển, **máy cũ trở thành nơi duy nhất giữ 5,6 GB đó**,
và nó dựng lại mất 2–3 giờ. Máy cũ không được coi là máy bỏ đi cho tới khi có quyết
định riêng về khối dữ liệu này.

### Tệp trạng thái sống — chép ở bước chuyển giao, KHÔNG chép sớm

| Tệp | Kích thước |
|---|---|
| `live_positions.json` | 481 B |
| `trade_log.jsonl` | 8,5 KB |
| `spy_daily_live.csv` | 45,7 KB |

Chép sớm là mở đường cho hai máy cùng tin mình đang giữ vị thế.

### Bốn biến môi trường + một tệp bí mật

`POLYGON_API_KEY` · `DATABENTO_API_KEY` · `IBKR_FLEX_TOKEN` · `IBKR_FLEX_QUERY_ID`
· `config_private.py` (gitignored, không nằm trong repo)

Đặt bằng `setx`, **không** bằng `$env:` — `$env:` chỉ tới được cửa sổ PowerShell đó,
không bao giờ tới scheduler. Chính `flex_pull` đã phải viết riêng thông điệp lỗi để
phân biệt hai ca này. Đặt xong phải khởi động lại scheduler thì nó mới đọc được.

### Cổng và định danh phiên IBKR

| | Giá trị |
|---|---|
| IB Gateway paper | 4002 |
| Backend API | 5002 |
| `clientId` của runner | 1 |
| `clientId` của backend | 99 |

### Môi trường chạy

Python **3.11.4** — cài đúng bản, không "3.11 mới nhất". Lịch chạy dùng APScheduler
`timezone="America/New_York"`, ET-native, DST tự động → **đổi múi giờ máy không đổi lịch**.

### Ba đường dẫn cứng — lý do giữ ổ `D:`

`generate_replay_snapshots.py` ghi cứng `D:\raits\data\cache\futures`,
`D:\raits\spy_daily_live.csv`, `D:\raits\global_index\data\NKD_continuous_1m_8y.parquet`.

Tệp này **không** nằm trên đường chạy slot — nó sinh artifact offline mà runner và
dashboard đọc lại. Nhưng nếu VPS dùng ổ khác thì lần sinh snapshot kế tiếp sẽ gãy.
Giữ `D:\raits` trên VPS thì ba dòng này không phải đụng tới, và không phát sinh
một bản sửa nào cần kiểm.

---

## 4. Giai đoạn 0 — đo trước khi mua máy

Chưa đủ số để chọn cấu hình. Ba việc, làm trước:

**0.1 Đo RAM đỉnh của một slot** — **[CHƯA ĐO]**. Slot nặng nhất là 15:55 ET và
02:55 ET: chúng chạy `--shadow-verify`, tức một lượt replay đầy đủ (~5 phút). Cộng
IB Gateway (Java) và backend Flask chạy thường trực. Cấu hình VPS phải chọn từ con
số này, không phải từ ước lượng.

**0.2 Kiểm kê 44 lần khởi động lại** — bao nhiêu là cố ý (sửa code, đổi cấu hình),
bao nhiêu là máy tự? Chỉ phần "máy tự" mới là biện minh cho VPS. Hiện chỉ đếm được tổng.

**0.3 Tách log phát triển khỏi log vận hành** — hiện `scheduler_*.log` lẫn cả lượt
replay. Việc này phải xong **trước** khi dựng VPS, nếu không thì giai đoạn đối soát
song song ở §6 không đọc được.

---

## 5. Giai đoạn 1 — dựng máy, chưa chạy gì thật

1. VPS Windows Server, **ổ dữ liệu gắn là `D:`**, thư mục `D:\raits`.
2. **Đồng bộ giờ**: bật `w32tm`, kiểm bằng cách in giờ thật rồi so với nguồn ngoài.
   Lệch đồng hồ → đọc nhầm bar. Đây là mục `PAPER_ROUTE` đã ghi là defer từ paper.
3. **Chặn Windows tự khởi động lại**: đây là rủi ro riêng của nhánh Windows. Đặt
   giờ hoạt động phủ trọn 01:00–16:00 ET, và hoãn cập nhật tính năng. Cấu hình xong
   phải **chứng minh** bằng một lần kiểm, không tin là đã đặt.
4. Cài Python 3.11.4, `pip install -r requirements.txt`, cài repo editable.
5. Chép 2,7 GB dữ liệu (§3). **Không** chép `live_positions.json` / `trade_log.jsonl`.
6. Đặt 4 biến env bằng `setx` + đặt `config_private.py`.
7. Cài IB Gateway paper, đăng nhập, cấu hình khởi động lại 17:00 ET.
8. Chạy `pytest` — mốc so là **914 passed** trên máy hiện tại. Khác con số này thì
   dừng, điều tra, chưa đi tiếp.

**Cổng ra giai đoạn 1:** suite xanh đúng số cũ · giờ hệ thống khớp nguồn ngoài ·
IB Gateway đăng nhập được ở 4002 · 4 biến env đọc được **từ chính tiến trình sẽ chạy**,
không phải từ cửa sổ shell.

---

## 6. Giai đoạn 2 — chạy song song, máy cũ vẫn là máy thật

Đây là giai đoạn tốn thời gian nhất và là giai đoạn không được cắt.

**Nguyên tắc 1 — VPS chạy `--dry-run` tuyệt đối.** Cả hai máy nói chuyện với cùng một
tài khoản paper. Nếu VPS đặt lệnh thì có hai chương trình cùng đặt lệnh vào một tài khoản.

**Nguyên tắc 2 — cô lập MỌI đầu ra của VPS**, kể cả `live_day_*.log`. Tệp đó
được `paper_evidence_reader` quét. Đã có tiền lệ: một lượt `--dry-run` thêm một
episode B3 và làm đỏ một cổng, rồi bị quy nhầm cho việc của phiên khác. VPS phải ghi
sang thư mục riêng, hoặc dashboard phải được chỉ rõ chỉ đọc máy cũ.

**Nguyên tắc 3 — `clientId` khác.** Runner máy cũ giữ 1, backend giữ 99. VPS
lấy số khác hẳn. Hai scheduler tranh `clientId=1` chính là thứ đã làm hỏng sáu slot
vào lệnh — không lặp lại nó ở đây.

**Đối soát mỗi ngày:** danh sách tín hiệu VPS sinh ra phải khớp **từng dòng** với
máy cũ — cùng mã, cùng chiều, cùng cụm, cùng `risk_sized`. Lệch một dòng là dừng
và điều tra, không phải "sai số chấp nhận được".

**Cổng ra giai đoạn 2 — [CHỜ CHỦ DỰ ÁN CHỐT]:** bao nhiêu ngày liên tiếp 0 lệch thì
đủ? Cần phủ tối thiểu một cuối tuần (để thấy slot 18:30 Chủ nhật), một đêm NKD, và
một lần IB Gateway restart 17:00 ET. Đề xuất 5 ngày giao dịch liên tiếp — chờ chốt.

---

## 7. Giai đoạn 3 — chuyển giao

Ngày chuyển phải chọn, không phải gặp đâu làm đó.

1. **Chọn ngày không có vị thế mở** nếu có thể. Nếu không có ngày nào thì chuyển
   `live_positions.json` như một thao tác nguyên tử, và chấp nhận nó là bước rủi ro
   nhất của cả kế hoạch.
2. **Tắt scheduler máy cũ TRƯỚC**, xác nhận đã chết bằng phép đếm chứ không bằng
   mã trả về của lệnh giết — `taskkill` trả về trước khi tiến trình được thu hồi.
3. Chép `live_positions.json` + `trade_log.jsonl` + `spy_daily_live.csv` sang VPS.
4. Bật scheduler VPS **không** `--dry-run`, `clientId=1`.
5. Sáng hôm sau: B3 cold-start phải không HALT giả, `live_positions.json` giữ nguyên,
   STP-VERIFY thấy order.

**Cổng ra:** đúng một scheduler tồn tại trên đời · một phiên đầy đủ chạy sạch ·
sổ lệnh khớp giữa hai máy tại thời điểm cắt.

---

## 8. Giai đoạn 4 — thứ VPS phải có mà máy cá nhân không có

Đây là lý do tồn tại của VPS. Thiếu phần này thì chỉ là đổi chỗ máy.

- **Tự khởi động lại khi chết** — scheduler và backend chạy như dịch vụ Windows, không
  phải như tiến trình rời. Runner chết mà IBKR còn giữ vị thế thì không ai gửi lệnh
  đóng: đó là mục E2 của rà soát vận hành, tới giờ vẫn để ngỏ và ghi rõ là "việc vận hành".
- **Chính sách bỏ lỡ của APScheduler** — nếu tiến trình khởi động lại đúng lúc tới giờ
  bắn thì slot đó xử lý thế nào. `misfire_grace_time` đã có; phải kiểm nó cư xử đúng
  khi dịch vụ tự dựng lại, chứ không chỉ khi khởi động tay.
- **Cảnh báo khi không chạy** — không chạy mà không ai biết là ca xấu nhất. Và mọi báo
  động phải có điều kiện **tắt**: sáu slot NKD hỏng lúc 02:00 từng giữ thanh trạng thái
  đỏ tới hết ngày dù 02:30 đã chạy sạch.

---

## 9. Việc làm được ngay, không phụ thuộc VPS

Ba việc này đúng cho mọi nhánh, làm song song với paper, không cắt mẫu:

1. **`exit_reason` không được ghi lại** — 8/10 dòng CLOSE đang rỗng. Cổng C1 nhánh STP
   đòi n=30; nó **không thể đầy** chừng nào lỗi này còn. Đây là cổng chặn go-live, và
   nó đang không đếm được.
2. **Tách log phát triển khỏi log vận hành** (§0.3).
3. **Kiểm kê 44 lần khởi động lại** (§0.2).

---

## 10. Ràng buộc thời điểm

**Không đụng scheduler hay backend trước 22:20 ET 18/8** (= 20:20 Calgary 18/8
= 09:20 Việt Nam 19/8). Phép đo độ trễ công bố Flex chốt ở mốc đó; khởi động lại
trước đó là vứt phép đo đang chạy.

---

## 11. Chỗ còn chờ quyết

| Việc | Chờ ai |
|---|---|
| Cấu hình VPS (RAM/đĩa) | chờ §4.1 đo xong |
| Số ngày đối soát song song trước khi chuyển | chủ dự án chốt |
| Chuyển khi đang có vị thế mở, hay chờ ngày phẳng | chủ dự án chốt |
