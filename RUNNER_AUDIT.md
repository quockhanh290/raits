# Báo cáo rà soát — RAITS futures runner

**Ngày:** 2026-08-15
**Phạm vi:** `global_index/runner.py` (2.759), `ibkr_broker.py` (1.532), `run_scheduler.py` (980),
`run_live_day.py` (762), `signal_layer.py` (431), `live_decision.py` (178),
`net_exposure_multi.py` (178), + 46 tệp test trong `global_index/`
**Chế độ:** CHỈ ĐỌC. Không sửa một dòng code, cấu hình hay state file nào. Không kết nối IBKR.
Mọi phép đo chạy offline bằng broker giả hoặc bằng chính bảng tra cứu trong module.

---

## TRẠNG THÁI SỬA CHỮA

**Rà lại 2026-08-15, sau khi viết bản gốc.** Bản audit dưới đây giữ nguyên — nó là bản ghi
lịch sử, không sửa lùi. Khối này ghi cái gì đã đóng và cái gì còn nguyên.

Mọi dòng đo trên `git worktree --detach` tại HEAD **`77594ff`** (`C:\tmp\raits-head-77594ff`),
**không** trên working tree. Bản audit gốc đo working tree, và đó chính là cách `a450712` từng
lọt qua ba lớp kiểm.

### Bảng tổng hợp

| Mã | Mức | Trạng thái | Ghi chú |
|---|---|---|---|
| **C1** | **Critical** | ✅ **ĐÃ SỬA 2026-08-15** | Xác minh còn nguyên ở HEAD trước (MNKD = **0** ngày roll), rồi sửa **tại `get_roll_event`** (`ibkr_broker.py:248`): phân giải qua `_RAITS_TO_IBKR` như mọi lookup khác — chính comment của `ROLL_SCHEDULE` đã khai *"every call site resolves the symbol first"*, và đây là chỗ duy nhất không làm. **Không** thêm khoá `MNKD` vào bảng: bản sao thứ ba của cùng chu kỳ đáo hạn bên cạnh `MNK`/`NKD` là lỗi L1, và nó vẫn để mã kế tiếp mang tên runner hỏng y hệt. Đo lại: MNKD **0 → 4** ngày roll, 04/9 trả `('202609','202612')` khớp đúng tháng lệnh đi vào; bốn mã Rổ 4 **không đổi** (đối chứng). **Bốn điểm cụ thể hoá — xem khối dưới bảng** |
| **C2** | **Critical** | ✅ **ĐÃ SỬA 2026-08-15** | Xác minh còn nguyên ở HEAD trước (`repro_c2.py` trùng từng dòng, kèm cột đối chứng), rồi sửa. `runner.py:1776` đổi `== "FAILED"` → `not in ("FILLED","PARTIAL")`: gỡ vị thế `decide_day` đã ghi trước khi lệnh đi, phát event `ALERT/EXEC`. **Không đổi `ibkr_broker`** — `CANCELLED` cho OPEN là từ vựng đúng, chỗ sai là bên đọc. Sau sửa: sổ rỗng, đĩa rỗng, có sự kiện, **ngày 2 không gửi gì**; cột đối chứng FILLED **không đổi một dòng nào** |
| **H1** | High | ✅ **ĐÃ SỬA 2026-08-15** | Xác minh `ce4ea2d` **không** chạm đường roll, rồi tách `_month_contract(ib, ibi, inst, month)` làm nơi dựng hợp đồng **duy nhất**; `_front_month_contract` và cả hai chỗ trong `_handle_rollover` cùng gọi nó. Tháng là **tham số** vì roll cần cả tháng đi ra, thứ `_current_front_month` không trả được (đúng ngày roll nó đã trả tháng mới). **Sửa C1 làm H1 thành gấp chứ không còn tuỳ chọn**: trước đó `ibi.Future("MNKD", …)` là code chết vì roll không bao giờ chạy cho Nikkei |
| **H2** | High | ✅ **ĐÃ SỬA 2026-08-15** | `STOP_FILE_NAME = "STOP_TRADING"` khai **một lần** ở `runner.py:66`; ba entry point import và truyền `stop_path=a.stop_path` (thêm cờ `--stop-path`, có mặc định nên không caller nào phải đổi). Không viết literal ba lần — đó đúng hình dạng đã cho `ROLL_SCHEDULE` hai khoá cho một hợp đồng. Đã kiểm `STOP_TRADING` **không** tồn tại trên đĩa, và nó **không** bị gitignore nên sẽ hiện trong `git status` nếu ai đó tạo |
| **H3** | High | ✅ **ĐÃ SỬA** — `5c901f0` | Hằng số biến mất. `runner.py:2439 _refreeze_status()` đọc `futures.refreeze.PENDING_PATH`, **fail closed** (file không parse được → `pending: True, unknown: True`), gọi ở `:2564`. Xem mục "Đính chính" bên dưới |
| **H4** | High | ✅ **ĐÃ SỬA** `c1fd242` | Đường B gọi `_record_stop_exit` kèm cờ mới **`fill_price_estimated`** — giá ghi là mức stop **đã đặt**, không phải giá khớp, và một ước lượng không gắn nhãn sẽ lan vào chỉ số slippage như thể được đo. Đường F ghi cả OPEN lẫn CLOSE, `exit_reason: SAME_DAY`. Cả hai nằm **trong** cổng `avg_price > 0` sẵn có: nới cổng cho test xanh sẽ sinh dòng giá 0 ở mọi lượt replay — lệch hai sổ theo chiều ngược lại. ⚠️ **Sửa "dòng không tồn tại", KHÔNG sửa "các dòng lệch hình dạng"** — xem khối schema CLOSE |
| **H5** | High | ✅ **ĐÃ SỬA** `59b476d` | `timeout=20 phút` cho tiến trình con + bắt `TimeoutExpired`. Ngưỡng là **trần chứ không phải đích**: chạy thường ~5,5′, hai slot có shadow replay thêm ~5′, nên ~11′ là hợp lệ. Nửa thứ hai quan trọng hơn: dòng SKIPPED nay mang **đã bao lâu** và leo thang qua ngưỡng đặt **trên** trần subprocess — đặt dưới thì một lần chạy sắp bị giết sẽ bị báo là "phiên chết" trước, hai thông điệp đá nhau. Tách `_inflight_report()` thành hàm thuần để test được cái nó **quyết định** |
| **M1** | Medium | ⏸️ **ĐỂ LẠI — trục scaling** | Bằng **0** hôm nay (`N_CONTRACTS = 1`, lệnh thị trường 1 hợp đồng không khớp một phần). Chủ dự án chốt để lại. Thuộc danh sách chặn của mục *Scaling — bốn trục* (`TASK.md:3179`), **không** thuộc danh sách lỗi — gộp vào là báo một lỗi không đang chảy máu |
| **M2** | Medium | ✅ **ĐÃ SỬA** `acdc9fa` | Hỏi `get_order_status` trước khi kết luận. `FILLED` → **không phải orphan**, phát ALERT *"runner cũng vừa gửi CLOSE của chính nó, kiểm tài khoản có bị đảo chiều không"* (cùng hình dạng C2); `CANCELLED` → INFO; `NOT_FOUND` → **UNVERIFIED**, không còn khẳng định "still live" khi chưa hề hỏi; còn sống → CRITICAL giữ nguyên. `test_stp9` + `stp14b` là hai đối chứng chứng minh cảnh báo thật **không** bị xoá |
| **M3** | Medium | ✅ **ĐÃ SỬA** `9322984` | Lọc thêm theo **hợp đồng** (caller luôn có `OpenPos`), và **từ chối đoán** khi còn nhiều ứng viên — trả `None` để caller rơi vào đường ước lượng có gắn nhãn của H4. Kèm `test_fe7` canh **chỗ nối**: bộ lọc không ai truyền `inst` là H2 lặp lại. Ba stub broker đã lệch chữ ký so với hàm thật, và `except Exception` biến `TypeError` thành "không có fill" — một câu trả lời sai thay vì một tiếng nổ |
| **M4** | Medium | ⏸️ **HOÃN CÓ CHỦ ĐÍCH** | Sửa đúng là luồn **ngày phiên** qua `_front_month_contract` tới cả ba call site, mà `place_stop` hiện không biết ngày phiên — đổi chữ ký xuyên broker. Xứng đáng một lượt riêng chứ không nhét vào cuối một batch dọn dẹp |
| **M5** | Medium | ✅ **ĐÃ SỬA** `3f8a0e9` | So **phần dư** `delta − số sleeve book cùng lần chạy`, không phải `\|delta\|` trần. Ngưỡng **$250 đo được, không bốc** — xem bảng phân bố dưới đây. Phát ALERT chứ không CRITICAL: ngưỡng dựng trên n=29 chưa đủ tin để tiêu vào ngân sách mà `run_scheduler` dành cho CRITICAL (bài học M2) |
| **M6** | Medium | ✅ **ĐÃ SỬA** `e59e321` | `max_dd_dollars` và `max_dd_pct` là **max thật**, bền hoá trong khối breaker — thiếu bước đó thì "all-time max" reset mỗi 5 phút, cùng lời nói dối ở dạng khác. `total_days` đếm **ngày phân biệt** (dump lại mỗi slot nên `len()` thô đếm trùng); `ibkr_connected` hỏi `_ib.isConnected()`, giữ `None` khi broker không trả lời được thay vì khai `False`; `model_name` theo `fit_end` guard đang giữ |
| **L1** | Low | ⛔ **BÁC BỎ — tiền đề sai ở HEAD** | Audit viết *"không đường production nào còn tra `ROLL_SCHEDULE[\"NKD\"]`"*. Đo lại: `ibkr_reader` duyệt `{**BASKET, **SPECS}` = **6 mã gồm `NKD`**, và `_current_front_month("NKD")` trả `202609`. Xoá hai dòng đó sẽ làm panel contract-specs dựng hợp đồng NKD không đủ định danh — đúng lỗi IBKR từ chối vì mơ hồ. **Mục thứ hai của audit sai ở HEAD, sau H3** |
| **L2** | Low | ✅ **ĐÃ SỬA** `e59e321` | Test đọc `INVARIANTS.md` và so với `BACKTEST_CALMAR_FLOOR`. Nó **tự kiểm trước**: nếu regex không còn khớp thì FAIL, vì một locator hỏng lặng lẽ sẽ làm test xanh đúng vào lúc nó ngừng hoạt động. Đã chứng minh đỏ được bằng cách đổi hằng số trong bộ nhớ |
| **L3** | Low | ⏸️ **ĐỂ LẠI — trục scaling** | Chủ dự án chốt để lại. Thêm một lý do kỹ thuật: bản ở `live_decision.py` là **code engine**, đổi nó động tới tính tương đương trade-for-trade với `deploy_sim.replay` — không phải thứ nên phá trong một batch dọn dẹp |
| **L4** | Low | ✅ **ĐÃ SỬA** `e59e321` | Hoàn lại `pnl_sized` **lúc khôi phục vị thế**, không phải bỏ cộng lúc retry: giữa hai lần đó vị thế **chưa đóng**, mà breaker đọc chính equity ấy mỗi slot. Số RED nói rõ: `50000 → 50300` khi CLOSE hỏng, `→ 50600` sau retry |
| **§4.1** | — | ✅ **ĐÃ ĐÓNG 2026-08-15** | `test_stp4_no_stp_when_open_cancelled` nay hỏi đủ bốn câu nó bỏ trống (sổ, đĩa, sự kiện, và `entry_price`), cộng `test_stp4b` canh lệnh CLOSE ngày hôm sau. Cả hai **đã xem đỏ trước khi sửa**: `Left behind: [('MES', 1, None)]` và `closes=[('MES','LONG',1)]` |
| **§4.2** | — | ✅ **ĐÃ ĐÓNG** — `5c901f0` | **Mục này của bản gốc nay đã sai.** Xem "Đính chính" |
| **§4.3** | — | ✅ **ĐÃ ĐÓNG 2026-08-15** | Bốn dòng `("MNKD", …)` thêm vào bảng parametrize — đỏ đúng 4/4 trước khi sửa `get_roll_event`, trong khi 11 dòng cũ vẫn xanh |
| **§4.4** | — | ✅ **ĐÃ ĐÓNG 2026-08-15** | `test_symbol_boundary.py` sb6/sb7/sb8 chạy **`IBKRBroker._handle_rollover` thật** với `ib_insync` giả và `_raw_fetcher = None` (short-circuit test-mode chính là lý do chưa test nào chạm tới đây). sb5 thêm bất biến `ast`: **chỉ một hàm** được dựng hợp đồng — chặn call site thứ năm |
| **`contract_month`** ✚ | — | ✅ **ĐÃ THÊM 2026-08-15** | Trường docstring hứa ba lần mà chưa bao giờ tồn tại. Nay chạy suốt `Fill` → `OpenPos` → JSON → dashboard. 6 gate trong `test_contract_month.py`, gồm **cm3**: `ast` chứng minh `decide_day` **không đọc** trường này — quan sát-thuần như `entry_price`/`exit_reason`. `MockBroker` để `None` nên verify/replay không đổi |
| **§4.5** | — | ✅ **ĐÃ ĐÓNG 2026-08-15** | `global_index/test_kill_switch.py`: 3 test đọc **AST** của từng entry point (khiếm khuyết là một tham số bị quên ở call site — không assert runtime nào trên runner tự dựng nhìn thấy được điều đó) + 2 test hành vi có **đối chứng** |

**Tổng: 19/22 mục đã đóng. Không còn mục Critical, High hay Medium nào mở.**

| Kết cục | Mục |
|---|---|
| ✅ Đã sửa trong đợt 15–16/8 | C1, C2, H1, H2, H4, H5, M2, M3, M5, M6, L2, L4 + §4.1, §4.3, §4.4, §4.5 |
| ✅ Đã đóng trước đợt này (`5c901f0`) | H3, §4.2 |
| ⛔ Bác bỏ — tiền đề sai ở HEAD | L1 |
| ⏸️ Hoãn có chủ đích | M4 (đổi chữ ký xuyên broker) · M1, L3 (trục scaling) |

**Bốn mục phát sinh trong lúc sửa, đều đã đóng:** trường `contract_month` (docstring hứa
ba lần, chưa bao giờ tồn tại) · hai định dạng tháng trong một trường · nhánh PARTIAL không
điền tháng · hai anh em của C1 ở `_current_front_month` và `ibkr_reader`.

> **Một mục "đã đóng" mà KHÔNG tìm ra lỗi nào.** `test_hmm_stale.py` có 43 phép kiểm không
> thể làm pytest đỏ — cùng khuyết tật audit realtime đã vá cho hai tệp khác và bỏ sót tệp
> này. Bật lên thì **cả 43 đều đúng**. Đó là **zero bug**, không phải chiến công, và ghi nó
> vào cột "đã sửa" là báo một lỗi không tồn tại — đúng cái Phase 2 của audit realtime cảnh
> báo (5/7 đường hoá ra đã đúng sẵn). Giá trị của nó nằm ở tương lai: từ giờ nếu một trong
> 43 cái đó gãy, sẽ có người biết.

### Việc runner còn mở, đến từ audit khác

`PAPER_DASHBOARD_AUDIT.md` có hai mục Critical mà **gốc rễ nằm ở runner** và vẫn chưa đóng:
**C5** (🟡 vá tạm — *"sửa gốc vẫn ở runner"*) và **C6** (❌ chưa). Kèm đề xuất ở `:746`:
*"hợp nhất một schema CLOSE duy nhất… Đây là sửa ở runner."*

Đo ở HEAD: **5 chỗ ghi dòng CLOSE, 22 khoá khác nhau, chỉ 12 khoá có mặt ở cả 5.** Mỗi chỗ
thiếu một kiểu; chỗ same-day mà H4 vừa thêm là mỏng nhất (thiếu 8). **H4 sửa "dòng không
tồn tại", không sửa "các dòng lệch hình dạng"** — ba mục này cùng một chỗ, cùng một nguyên
nhân, và nên làm cùng một lượt.

> **Vì sao C2 và H2 đi trước C1** dù C1 mới là mục có hạn chót: C2 không cần dịp nào cả —
> chỉ cần một lệnh vào hết 30 giây chờ — và **14:05 ET thứ Hai 17/8 là lần đầu `send_order`
> chạy thật với `ce4ea2d`**. H2 là kế hoạch ứng cứu cho cả C1 lẫn C2, và là diff nhỏ nhất
> cả danh sách. C1 cần sửa cùng H1 và có 20 ngày.
>
> **Và C1 phải đi kèm H1, đúng như dự đoán — theo hướng ngược lại.** Bản gốc viết *"hai lỗi
> che nhau"*. Cụ thể là: chừng nào C1 còn, đường roll **không bao giờ chạy** cho Nikkei, nên
> `ibi.Future("MNKD", …)` là code chết. Sửa C1 xong thì đường đó **sống dậy** và đâm thẳng
> vào một mã IBKR không tồn tại. Sửa C1 một mình không phải là "sửa được một nửa" — nó là
> đổi một lỗi im lặng lấy một lỗi nổ ngay ở lệnh đóng đầu tiên.

### C1 cụ thể hoá — bốn điểm đo thêm 15/8

**1. NKD giữ vị thế qua đêm là THIẾT KẾ, không phải trường hợp biên.**
`_DEFERRED_STOP_CLUSTERS = {"roska4_swing", "global_nkd"}` (`runner.py:70`) — stop cố ý
hoãn sang phiên sau, arm 14:00 `Asia/Tokyo` (`_ARM_BY_CLUSTER`). Tiền đề *"có vị thế MNKD
mở qua 04/9"* là vận hành bình thường. Vị thế M2K trong `live_positions.json` lúc rà đã
mở sang ngày thứ 5, cùng cơ chế.

**2. Nhưng bản ghi live chưa từng có ca nào.** Cả `trade_log.jsonl` chỉ có **2 vòng MNKD**
(10/8 và 11/8), cả hai `entry_day == exit_day`, thoát theo tín hiệu. Tỷ lệ mang qua đêm
thực đo: **0/2** — *chưa đo*, không phải *bằng không*.

**3. `OpenPos` KHÔNG có trường `contract_month`** *(đã thêm 15/8 — mô tả dưới đây là trạng thái lúc rà)* — và đây là lý do cơ học khiến C1 vô hình.
Docstring `_handle_rollover` nhắc tới nó ba lần (`:1388`, `:1390`, `:1394` — *"contract_month
field (**TBD in OpenPos**)"*), trường đó chưa bao giờ được thêm; `grep contract_month
global_index/*.py` chỉ ra đúng ba dòng docstring ấy. **Sổ không có ô nào chứa tháng hợp
đồng, cho mọi mã chứ không riêng MNKD.** Một lần roll Rổ 4 thành công cũng để lại sổ y hệt.
Nên không phép kiểm file-vs-file nào bắt được C1 — phải hỏi broker, và
`unprotected_positions` là lưới duy nhất vì nó đọc expiry thẳng từ object contract và so
`(sym, expiry, action)` (`ibkr_broker.py:1284`). **Bản sửa C1 phải thêm trường này**, nếu
không thì sau khi sửa vẫn không ai kiểm được là roll đã chạy đúng.

**4. Bước 2 của chuỗi hẹp hơn bản gốc gợi ý.** Danh sách `naked` của B4
(`runner.py:623-628`) chặn theo **id stop đã ghi có còn sống không**, không theo tháng.
Đúng ngày roll, stop MNKU6 vẫn sống → vị thế không vào `naked` → B4 im, đúng như bản gốc
nói. Bước 2 chỉ nổ khi stop U6 chết: TWS restart cuối tuần (đúng kịch bản sweep Chủ nhật),
hoặc **MNKU6 hết hạn 11/9**. Lúc đó B4 đặt lại → `_front_month_contract` → MNKZ6, và nó
**không lặp** (id Z6 mới thoả điều kiện id nên slot sau bỏ qua) — để lại đúng một stop mồ
côi trên Z6 cộng một vị thế U6 trần, B4 im từ đó, chỉ B5 còn kêu.

### Đính chính bản gốc — H3 và §4.2

Bản gốc viết *"`runner.py:2526` phát ra `"refreeze": {"pending": False}` — một literal"* và
*"H3 có 0 phép kiểm có khả năng thất bại trên toàn bộ 46 tệp"*. **Cả hai đã sai tại HEAD.**
`5c901f0` gỡ hằng số đó — và `5c901f0` **cũ hơn** `ce4ea2d`, thứ mà chính bản gốc trích dẫn ở H1.
Nghĩa là H3 được đo trên một checkout cũ hơn phần còn lại của đợt rà.

Test thay thế **có** khả năng đỏ, và đây là chỗ đáng đọc:
`test_operational_fixes.py:899 test_refreeze_pending_flag_is_read` monkeypatch
`futures.refreeze.PENDING_PATH` **trong tiến trình** (không sửa file trên đĩa), rồi đi
**hết** đường qua `_build_operational_status` chứ không dừng ở helper. Comment T19b.8 ghi
lại chính lý do: một mutation đặt `{"pending": False}` trở lại **vẫn để T19b.1–3 xanh**,
vì ba check đó không đi qua đường mà `dump_state` thật sự publish. Đó là bản vá đúng cho
khuyết tật "test không thể đỏ" mà đợt realtime rút ra.

Ba trạng thái được ràng: không có file → `pending False` · có file → `pending True` + `attempts`
+ `fit_end_target` · file hỏng → `pending True, unknown True` (**fail closed**, vì
`paper_evidence_reader` map `pending` falsy thẳng sang `OK`).

### Nền đo

| Chỉ số | Bản gốc ghi | Đo lại ở HEAD `77594ff` | Sau đợt sửa 15/8 |
|---|---|---|---|
| `pytest global_index/ --ignore=test_event_playback.py` | 506 passed | **507 passed** (+1 = T19b của `5c901f0`) | **517 passed** |
| `pytest` trần (mọi testpath) | — | — | **843 passed**, 0 đỏ, 0 skip, 19′58″ |
| Phép kiểm không thể đỏ dưới pytest | — | **43** (`test_hmm_stale`) | **0** — quét cả 56 tệp |
| Nơi dựng hợp đồng IBKR | 4 | *(như trên)* | **1**, có bất biến `ast` canh |
| Đường đóng lệnh book tiền mà không ghi sổ | **2 / 6** | *(như trên)* | **0 / 6** |
| Cặp song song không có phép đối soát | **7** | *(như trên)* | **6** (M5 đã nối; M4 hoãn) |
| Ngày roll của MNKD | **0** | *(như trên)* | **4**, khớp bốn mã Rổ 4 |
| Nơi dựng hợp đồng IBKR | 4 (một chỗ hand-rolled) | *(như trên)* | **1**, có bất biến `ast` canh |
| Sổ ghi tháng hợp đồng | **không có trường** | *(như trên)* | `contract_month` chạy tới tận dashboard |
| Hai Critical | ✅ đã xác minh | **✅ tái lập ở HEAD, trùng từng dòng** | C2 đóng · **C1 còn mở** |
| Vị thế ma sau lệnh vào bị huỷ | sổ ×1, đĩa ×1, 0 sự kiện | *(như trên)* | **sổ rỗng, đĩa rỗng, có sự kiện** |
| Ngày thoát sau lệnh vào bị huỷ | `CLOSE MES LONG ×1` ra sàn | *(như trên)* | **không gửi gì** |
| `STOP_TRADING` trên đĩa | không có tác dụng | *(như trên)* | **chặn entry, exit vẫn chạy** |

> **Chênh lệch số test không phải tất cả là của đợt này.** 809 gồm **6** test của đợt sửa
> (5 `test_kill_switch` + 1 `test_stp4b`) và **7** test của một luồng việc khác đang nằm
> trong working tree chưa commit (`run_scheduler.py`, `test_session_report_slot.py`,
> `monitor/paper_pnl_compare.py`, `monitor/test_dashboard_backend.py` — wiring Flex pull +
> refresh P&L, sửa lúc 10:08–10:14 ngày 15/8, **sau** lượt đo nền 507). Một test trong
> tổng cộng vẫn chưa quy được về nguồn nào; mốc 795 mà đề bài đưa ra có trước luồng việc
> kia nên không phải mốc so sánh sạch. Cái chắc chắn: **809/809 xanh, không đỏ, không skip.**

> **Cạm bẫy khi chạy lại trong worktree trần.** `test_ibkr_injection.py::C6.4` **đỏ** trong
> worktree (2,4s) và **xanh** trong working tree (10,9s). Không phải hồi quy: worktree không
> có `global_index/data/` (parquet bị gitignore). `git status --porcelain global_index/` cho
> thấy **không có sửa đổi tracked nào** dưới `global_index/`, nên hai cây giống hệt nhau về
> code — chênh lệch là dữ liệu. Số 507 lấy từ working tree vì lý do đó.

### Cách chạy lại ba repro ở HEAD

Ba script ở §6 đều `sys.path.insert(0, r"d:\raits")`, tức chúng đo **working tree**. Để đo HEAD,
nạp module từ worktree **trước** rồi mới `exec` script — `sys.path.insert` của nó thành vô hiệu
vì module đã nằm trong `sys.modules`:

```powershell
git worktree add --detach C:\tmp\raits-head-77594ff 77594ff
cd C:\tmp\raits-head-77594ff
$OLD = "C:\Users\quock\AppData\Local\Temp\claude\d--raits\c0cae186-a006-48bc-9d71-c502bc26d55c\scratchpad"
python -c @"
import sys
WT = r'C:\tmp\raits-head-77594ff'; OLD = r'$OLD'
sys.path.insert(0, OLD); sys.path.insert(0, WT)
import global_index.runner as R, global_index.ibkr_broker, global_index.broker
import global_index.net_exposure_multi, futures.circuit_breaker
assert R.__file__.lower().startswith(WT.lower()), R.__file__   # phep do phai chung minh no o dung cay
for name in ('repro_c1.py', 'repro_c2.py', 'repro_h4.py'):
    src = open(OLD + '\\' + name, encoding='utf-8').read()
    exec(compile(src, name, 'exec'), {'__name__': '__main__', '__file__': OLD + '\\' + name})
"@
```

Dòng `assert` không phải trang trí: thiếu nó thì script chạy vui vẻ trên working tree và
**không có gì trong output nói ra điều đó**.

### Thứ tự sửa đề xuất, theo rủi ro

**Mốc 0 — trước 18:30 ET Chủ nhật, không phải một finding.** Restart scheduler để nạp cron
sweep stop Chủ nhật của `83ac849`. Không restart thì tuần này vẫn hở 6,5 tiếng. Đây là việc
hết hạn **sớm nhất** trong toàn bộ danh sách.

**1 — H2 trước, vì nó là lưới đỡ cho mọi mục còn lại.** ✅ **XONG 15/8.** Diff nhỏ nhất cả danh sách: truyền
`stop_path=` ở ba entry point. Cả C1 lẫn C2 đều có cùng một câu trả lời vận hành — *dừng vào
lệnh, giữ exit, xử lý tay* — và đó đúng là việc D5 sinh ra để làm. Sửa nó **trước** thì hai
mục sau có chỗ lùi; sửa nó sau thì mỗi sự cố trong lúc chờ đều phải xử lý tay không.
Kèm một test dựng runner bằng **đúng** bộ tham số `run_live_day.py:699-720` truyền — §4.6 chỉ
ra một test đó chặn được cả bốn dạng lỗi.

**2 — C2, vì nó không cần dịp nào cả.** ✅ **XONG 15/8.** Không cần ngày roll, không cần sự cố: chỉ cần một lệnh
vào hết 30 giây chờ. Và **14:05 ET thứ Hai là lần đầu `send_order` chạy thật với bản sửa
`ce4ea2d`** — cửa sổ có xác suất hỏng cao nhất, đúng lúc nhánh này chưa có ai canh. Sửa: coi
`CANCELLED` như hỏng ở `runner.py:1770`, gỡ vị thế khỏi sổ, phát sự kiện. Trước đó cho
`test_stp.py:224` (§4.1) bốn câu hỏi nó đang bỏ trống — test mang đúng tên kịch bản này.

**3 — C1 và H1 cùng một lần, không tách.** ✅ **XONG 15/8**, kèm `contract_month` và hai lỗ hổng test §4.3/§4.4. Hạn 04/9 (còn 20 ngày), khung đêm 01:10–02:55 ET,
không ai trực. Sửa C1 một mình **đổi một lỗi lấy một lỗi khác**: từ "không bao giờ roll" thành
"roll vào một hợp đồng không giải được", vì đường roll dựng `ibi.Future("MNKD", …)` bằng tên
thô. H1 còn có mốc riêng của nó: **MYM roll 11/9** trên `exchange="CME"` trong khi
`_IBKR_EXCHANGE` khai `CBOT` — và lệnh đầu tiên trong cặp đó là lệnh **đóng**. Cách sửa đúng
hình dạng của `ce4ea2d`: cho đường roll đi qua `_front_month_contract`, để nó raise thay vì
đoán. Kèm §4.3 (một dòng `("MNKD", …)`) và §4.4 (một test chạm `IBKRBroker._handle_rollover` thật).

**4 — H4 + M5, trước khi trích dẫn bất kỳ con số P&L nào.** Đường B đang sống. Cho tới khi vá,
`paper_epoch_closed_realized` **thiên lệch có hệ thống**, và
`system_ledger_vs_trade_filter` đã có sẵn `MATCH_PRE_EPOCH_CARRY_FILL` để quy sai vào.
M5 đi cùng vì nó là cặp song song **duy nhất** còn đủ hai vế mà không có phép đối soát — đúng
chỗ C8 ($1.260) lẽ ra đã lộ ra ngày đầu.

**5 — M2, M3, H5: chất lượng cảnh báo.** M2 sinh `STP ORPHAN` **giả**, và `run_scheduler:363`
nâng nó lên log scheduler y như cảnh báo thật — làm mòn đúng cơ chế được thêm vào vì một
`STP ORPHAN` thật bị nuốt ngày 10/8. H5 thêm `timeout=` và tách chữ cho "chồng một nhịp"
khỏi "cả phiên đã chết".

**6 — M1 + L3: chặn của trục tăng quy mô.** Cả hai **bằng 0 hôm nay** (`N_CONTRACTS = 1`).
Không gấp, nhưng phải nằm trong danh sách chặn của mục *"Scaling — bốn trục"* (`TASK.md:3179`),
không nằm trong danh sách sửa lỗi.

**7 — M6, L1, L2, L4: trôi và tồn đọng.** L2 đáng làm sớm trong nhóm này vì nó rẻ và vì nó
đúng cơ chế đã để `refreeze.CALMAR_FLOOR = 2.38` sống sót sáu tuần.

---

## 0. Tóm tắt cho người bận

| # | Mức | Phát hiện một câu | Tin cậy |
|---|---|---|---|
| **C1** | **Critical** | Vị thế Nikkei **không bao giờ được roll**; từ 04/9 lệnh và vị thế nằm ở **hai tháng hợp đồng khác nhau** | ✅ đã xác minh |
| **C2** | **Critical** | Lệnh vào bị huỷ để lại **vị thế ma**; đến ngày thoát, runner gửi lệnh CLOSE và **mở một vị thế ngược chiều không stop** | ✅ đã xác minh |
| **H1** | High | Đường roll là **call site thứ tư** dựng hợp đồng bằng tay — dùng tên nội bộ làm mã IBKR, ép sàn `CME`, không kiểm `conId` | ✅ đã xác minh |
| **H2** | High | Công tắc dừng khẩn cấp **D5 không được nối** vào bất kỳ entry point nào; runbook hướng dẫn một việc vô tác dụng | ✅ đã xác minh |
| **H3** | High | Cổng `refreeze.pending` đọc một **hằng số `False` viết cứng** — không bao giờ FAIL được *(đã có trong tồn đọng D6; đợt này định lượng mức độ)* | ✅ đã xác minh |
| **H4** | High | **Hai đường đóng lệnh nữa** book tiền vào sổ vốn mà không ghi một dòng nào vào `trade_log.jsonl` | ✅ đã xác minh |
| **H5** | High | Không có **trần thời gian** cho một slot; một tiến trình con treo sẽ khoá cả phiên giao dịch | ✅ thiếu trần / 🟡 cơ chế treo |
| **M1** | Medium | Khớp một phần lệnh vào → stop đặt theo **số đã đặt**, không theo số đã khớp | ✅ đã xác minh (chặn khi tăng quy mô) |
| **M2** | Medium | `cancel_order` trả `False` cho một stop **đã khớp** → runner kêu "STP ORPHAN, vẫn sống ở sàn" — ngược sự thật | ✅ đã xác minh |
| **M3** | Medium | `find_execution` khớp theo `orderId` mà chính docstring của nó nói `orderId` lặp giữa các client | ✅ code / 🟡 tần suất |
| **M4** | Medium | **Hai đồng hồ** cùng quyết định tháng hợp đồng: ngày phiên vs đồng hồ tường | ✅ đã xác minh |
| **M5** | Medium | Delta tài khoản broker được **đo rồi vứt** — không có phép đối chiếu nào với sổ nội bộ | ✅ đã xác minh |
| **M6** | Medium | Bốn trường vận hành khác trong payload là **hằng số cứng** | ✅ đã xác minh |
| **L1–L4** | Low | Bảng roll chết vẫn được test; sàn Calmar không bị test ràng buộc; mặc định im lặng 1 hợp đồng; một đường cộng đôi tiềm ẩn | ✅ đã xác minh |

**Toàn bộ 518 test trong `global_index/` PASS — không loại trừ tệp nào — khi tất cả những điều trên đang đúng.**

---

## 1. Phát hiện xếp theo mức độ

### CRITICAL

---

#### C1 — Vị thế Nikkei không bao giờ được chuyển sang hợp đồng tháng sau, và sau ngày roll thì lệnh với vị thế nằm ở hai tháng khác nhau

**Cái gì sai (mô tả bằng hành vi).**
Mỗi ngày, trước khi sinh tín hiệu, runner hỏi từng vị thế đang mở: *"hôm nay có phải ngày chuyển hợp đồng của mày không?"*
Với bốn mã Rổ 4, câu trả lời đúng. Với Nikkei, câu trả lời **luôn luôn là không** — kể cả đúng ngày roll.
Một vị thế Nikkei mở qua ngày 04/9/2026 sẽ nằm lại hợp đồng tháng 9 cho tới khi hết hạn 11/9.

Tệ hơn: chỉ **đường roll** là mù. Đường đặt lệnh, đường đặt stop và đường lấy bar **có** biết ngày roll —
chúng tự tra tháng hợp đồng ở một chỗ khác. Nên từ 04/9 trở đi, ba đường đó nói "tháng 12"
trong khi vị thế vẫn nằm ở tháng 9.

**Nguyên nhân.** Hai bảng tra được đánh khoá bằng **hai loại tên khác nhau**:

| Bảng | Khoá thực có | Ai gọi | Gọi bằng gì |
|---|---|---|---|
| `ROLL_SCHEDULE` | `MES / MNQ / MYM / M2K / MNK / NKD` | `get_roll_event(inst, today)` | `pos.inst` = **tên nội bộ** |
| `_RAITS_TO_IBKR` | `MNKD → MNK` | `_front_month_contract` | tên nội bộ, **có dịch** |

`runner.py:1229` truyền `pos.inst`. `run_live_day.py:88` khai `NKD_INST = "MNKD"`.
`ROLL_SCHEDULE` có khoá `MNK` (mã IBKR) và `NKD` (mã cũ) — **không có `MNKD`**.
Lịch roll là bảng duy nhất trong `ibkr_broker.py` được tra bằng khoá thô, không đi qua `_RAITS_TO_IBKR`.

**Bằng chứng đo được.** `python <scratchpad>\repro_c1.py` (xem §6):

```
  MES    so ngay roll = 4  | co trong ROLL_SCHEDULE: True
  MNQ    so ngay roll = 4  | co trong ROLL_SCHEDULE: True
  MYM    so ngay roll = 4  | co trong ROLL_SCHEDULE: True
  M2K    so ngay roll = 4  | co trong ROLL_SCHEDULE: True
  MNKD   so ngay roll = 0  | co trong ROLL_SCHEDULE: False

  doi chung -- du lieu lich CO du, chi khoa tra la sai:
    get_roll_event('MNK', '2026-09-04') = ('202609', '202612')
    get_roll_event('NKD', '2026-09-04') = ('202609', '202612')

    2026-09-03: lenh MNKD -> MNK202609   | roll('MNKD') = None
    2026-09-04: lenh MNKD -> MNK202612   | roll('MNKD') = None
    2026-09-08: lenh MNKD -> MNK202612   | roll('MNKD') = None
    2026-09-11: lenh MNKD -> MNK202612   | roll('MNKD') = None
```

Phép đo chạy qua **chính** `IBKRBroker._handle_rollover` (test mode `_raw_fetcher`, không kết nối),
tức đúng hàm mà `runner.py:1229` gọi — không phải một bản sao viết lại.

**Tự kiểm.**
· *Bất đối xứng, không phải hỏng đồng loạt* — 4/5 mã roll đúng, đúng một mã không. Phép đo phân biệt được.
· *Hai đường suy ra độc lập* — (a) `_handle_rollover("MNKD", …)` trả `None`; (b) `"MNKD" in ROLL_SCHEDULE` là `False`. Khớp.
· *Loại trừ giả thuyết "thiếu dữ liệu lịch"* — `get_roll_event("MNK", …)` và `get_roll_event("NKD", …)`
  **đều** trả `('202609','202612')` cùng ngày. Dữ liệu lịch đầy đủ; chỉ khoá tra là sai.
  Điều này cô lập lỗi vào việc đánh khoá, không phải vào lịch.

**Hệ quả nếu không sửa.**

Mốc gần nhất: **04/9/2026 — còn 20 ngày.** Hết hạn: 11/9/2026.
`MNKD` point_value $0,50; NKD close cuối trong parquet 68.575 (2026-08-14)
⇒ **notional 1 hợp đồng ≈ $34.288**.

Chuỗi diễn ra nếu có vị thế Nikkei mở qua 04/9:

1. **04/9** — không roll. Vị thế ở `MNKU6`. STP cũ vẫn bảo vệ đúng `MNKU6` (đặt trước ngày roll),
   nên B4/B5 **không kêu**. Không có tín hiệu nào cho người vận hành.
2. **Bất kỳ lúc nào sau đó, nếu B4 phải đặt lại stop** — `place_stop` đi qua `_front_month_contract`
   → đặt STP lên `MNKZ6`. Vị thế `MNKU6` **trần**. (B5 sẽ bắt được cái này ở cuối `run_day`,
   vì `unprotected_positions` so theo `(mã, tháng, chiều)` — đó là lưới duy nhất hoạt động trong cả chuỗi.)
3. **Khi tín hiệu bảo thoát** — `send_order(CLOSE)` đi vào `MNKZ6`. Đó không phải lệnh đóng,
   đó là lệnh **BÁN MỞ** một vị thế short `MNKZ6`. Runner xoá vị thế khỏi sổ và tin rằng nó đã phẳng.
4. Tài khoản khi đó giữ **hai** vị thế mà sổ nội bộ ghi **không**: long `MNKU6` + short `MNKZ6`,
   tổng notional gộp ≈ **$68.575** — 137% vốn thiết kế $50.000, trong một mã, vô hình với sổ.
5. **11/9** — `MNKU6` hết hạn, IBKR tất toán. Còn lại **một short `MNKZ6` trần, không stop, không ai sở hữu.**

Tôi **không** đưa ra con số lỗ. Rủi ro ở đây là bản thân vị thế, không phải một khoản chi phí tính được;
đưa một con số sẽ là bịa. Cái đo được là: notional $34.288/hợp đồng, và lưới duy nhất chặn được
bước 3 là B5 — chạy **sau khi** lệnh đã đi ra.

**Tin cậy: ✅ đã xác minh.**

> **Lưu ý về lịch trực.** `TASK.md:2851` ghi *"Lần đầu 11/9/2026 — runbook ghi rõ nên có người theo dõi log 13:45–14:05 ET hôm đó."*
> Roll Nikkei là **04/9**, sớm hơn một tuần, và rơi vào khung đêm 01:10–02:55 ET chứ không phải 13:45–14:05.
> Không ai đang trực đúng cái ngày duy nhất mà lỗi này nổ.
>
> **Và bài diễn tập roll thật cũng không thể lộ ra nó.** `TASK.md:3269` ghi bài tập
> `exercise_rollover_live` *"Dùng **MNQ** (hệ thống không giữ mã này)"* — MNQ là Rổ 4,
> tức đúng họ mà lịch roll hoạt động bình thường. Bài diễn tập được thiết kế để an toàn,
> và chính sự an toàn đó chọn trúng mã duy nhất không thể phơi bày C1.

---

#### C2 — Một lệnh vào bị huỷ để lại vị thế ma; đến ngày thoát, runner tự mở một vị thế ngược chiều không stop

**Cái gì sai.**
Runner quyết định vào lệnh **trước**, gửi lệnh **sau**. Vị thế được ghi vào sổ ngay lúc quyết định
(`live_decision.py:155`), rồi lệnh mới đi ra. Nếu lệnh không khớp, không có gì gỡ vị thế đó khỏi sổ.

Đường "lệnh vào không khớp" của IBKR trả về status `CANCELLED`. Runner chỉ kiểm `== "FAILED"`.
`send_order` **không bao giờ** trả `"FAILED"` cho một lệnh OPEN — nó trả `CANCELLED` ở cả ba nhánh hỏng
(`ibkr_broker.py:678` hết 30 giây chờ, `:724` trạng thái cuối không khớp, `:741` bất kỳ exception nào).
Nên nhánh xử lý lỗi của lệnh vào (`runner.py:1770`) là **code chết**.

**Bằng chứng đo được.** `python <scratchpad>\repro_c2.py`:

```
=== NHANH HONG THAT (send_order tra ve 'CANCELLED' cho OPEN) ===
  ngay 1 gui           : [('OPEN', 'MES', 'LONG', 1)] | broker giu: []
  so runner            : [('MES', 1, 'entry_price=None')]
  trade_log            : 0 dong
  su kien EXEC/RISK    : []
  file state tren dia  : [('MES', None)]
  ngay 2 gui           : [('CLOSE', 'MES', 'LONG', 1)]

=== DOI CHUNG (send_order tra ve 'FILLED' cho OPEN) ===
  ngay 1 gui           : [('OPEN', 'MES', 'LONG', 1)] | broker giu: []
  so runner            : [('MES', 1, 'entry_price=7800.0')]
  trade_log            : 1 dong
  su kien EXEC/RISK    : ['OPEN MES LONG ×1 @7800.0000', 'STP hoan sang phien sau …']
  file state tren dia  : [('MES', 7800.0)]
  ngay 2 gui           : [('CLOSE', 'MES', 'LONG', 1)]
```

**Đọc kết quả.** Lệnh vào bị huỷ. Sau đó:
· sổ runner **có** vị thế, broker **không** — vị thế ma;
· `live_positions.json` **ghi nó xuống đĩa**, `entry_price = None`;
· `trade_log.jsonl`: **0 dòng**;
· danh sách sự kiện (thứ dashboard đọc): **rỗng**;
· không một dòng `ERROR`/`CRITICAL` nào từ runner;
· **Ngày 2: một lệnh `CLOSE MES LONG` đi thẳng ra sàn** — bán mở 1 hợp đồng MES short.

**Tự kiểm.**
· *Phép đo có phân biệt được không?* Có — cột đối chứng ngay bên dưới. Với broker khớp thật,
  cùng runner ấy cho `entry_price = 7800.0` và `trade_log` 1 dòng. Vậy "sổ có vị thế" một mình
  **không** phân biệt được; cái phân biệt là **bộ ba** `entry_price=None` + broker rỗng + trade_log 0 dòng,
  và bộ ba đó chỉ xuất hiện ở nhánh CANCELLED.
· *Hai đường suy ra độc lập* — trạng thái trong bộ nhớ và nội dung file trên đĩa nói cùng một điều.
· *Giá trị bất khả thi* — `entry_price = None` trên một vị thế mà sổ tin là đang mở là trạng thái
  không được phép tồn tại: `_book_realised` (`runner.py:904`) sẽ từ chối định giá nó
  và ghi `UNPRICEABLE CLOSE`.

**Hệ quả nếu không sửa.** Ba tầng, theo thứ tự thời gian:

1. **Trong cùng phiên** — vị thế ma chiếm hạn mức cluster. `MultiClusterGuard.admits` cộng `risk_dollars`
   của nó, nên một lệnh thật sau đó có thể bị từ chối vì một vị thế không tồn tại. Im lặng.
2. **Slot kế tiếp (5 phút sau)** — tiến trình mới, B3 so file với broker: file có ×1, broker có ×0,
   vị thế không có `stop_order_id` → rơi vào nhánh `B3 MISMATCH` (`runner.py:544`)
   → `_b3_halt_entries = True` → **toàn bộ lệnh vào của mọi sleeve bị chặn** cho tới khi
   có người sửa tay `live_positions.json`. Đây là lưới an toàn, và nó hoạt động — nhưng cái giá là
   dừng cả hệ thống vì một lệnh hết giờ chờ.
3. **Lệnh CLOSE vẫn đi ra bất chấp B3** — B3 chỉ chặn **entry**; `runner.py:1450` ghi rõ *"exits unaffected"*.
   1 hợp đồng MES ở 7.799 × $5 = **notional $38.995**, ngược chiều, không stop, không nằm trong sổ nào.

**Tin cậy: ✅ đã xác minh.**

---

### HIGH

---

#### H1 — Đường roll là call site thứ tư dựng hợp đồng bằng tay, và nó giữ nguyên cả ba khiếm khuyết mà Phụ lục F đã sửa cho ba call site kia

**Cái gì sai.**
`PAPER_DASHBOARD_AUDIT.md` Phụ lục F viết: *"Ba call site (lấy bar, đặt lệnh, tra giá) trùng lặp cùng 8 dòng
dựng hợp đồng"* và gom cả ba về `_front_month_contract`. **Có bốn call site.** Đường roll bị bỏ sót.

**Bằng chứng đo được.**

```bash
cd d:/raits && python -c "import inspect; from global_index import ibkr_broker as B; [print(n,':',[l.strip() for l in inspect.getsource(getattr(B.IBKRBroker,n)).splitlines() if '_front_month_contract' in l or 'ibi.Future(' in l or 'exchange=\"' in l]) for n in ('send_order','place_stop','_fetch_raw','_handle_rollover')]"
```

```
send_order        : ['contract = _front_month_contract(ib, ibi, order.inst)']
place_stop        : ['contract = _front_month_contract(ib, ibi, inst)']
_fetch_raw        : ['contract = _front_month_contract(ib, ibi, inst)']
_handle_rollover  : ['front_contract = ibi.Future(inst, lastTradeDateOrContractMonth=front_month,',
                     'exchange="CME")',
                     'next_contract = ibi.Future(inst, lastTradeDateOrContractMonth=next_month,',
                     'exchange="CME")']
```

Ba khiếm khuyết còn nguyên ở `ibkr_broker.py:1427` và `:1480`:

| # | Khiếm khuyết | `_front_month_contract` xử lý | Đường roll |
|---|---|---|---|
| 1 | Tên nội bộ ≠ mã IBKR | `_RAITS_TO_IBKR.get(inst, inst)` | ❌ dùng `inst` thô |
| 2 | Sàn theo mã | `_IBKR_EXCHANGE.get(sym, "CME")` | ❌ ép cứng `"CME"` |
| 3 | `qualifyContracts` không raise | kiểm `conId`, raise `ContractResolutionError` | ❌ không kiểm |

**Hệ quả cụ thể, mã theo mã.**

· **MYM** — `_IBKR_EXCHANGE` khai `MYM → CBOT`. Đường roll gửi `exchange="CME"`.
  `qualifyContracts` để `conId = 0` và không raise, nên **hai lệnh thị trường đi ra trên một hợp đồng
  IBKR chưa từng xác nhận** — trong đó lệnh đầu là lệnh ĐÓNG vị thế. Mốc: **11/9/2026**.
· **MNKD** — khiếm khuyết #1 sẽ khiến `ibi.Future("MNKD", …)` không giải được. Nhưng nó **không bao giờ chạy tới đó**,
  vì C1 chặn trước ở `get_roll_event`. **Hai lỗi che nhau:** sửa C1 mà không sửa H1 thì đổi một lỗi
  "không roll" thành một lỗi "roll vào một hợp đồng không tồn tại".

**Tin cậy: ✅ đã xác minh** (đọc code; hành vi `qualifyContracts` lấy từ chính docstring
`_front_month_contract`, thứ đợt trước đã kiểm chứng — không phải giả định của tôi).

---

#### H2 — Công tắc dừng khẩn cấp D5 không được nối vào bất kỳ entry point production nào

**Cái gì sai.**
`docs/futures/OPERATIONS.md:89` có hẳn một mục *"D5 STOP_FILE — Dừng entries khẩn cấp"*:

```powershell
New-Item -ItemType File d:\raits\STOP_TRADING
```

*"Runner cron tiếp theo thấy file → entry bị block, exit vẫn chạy bình thường."*

`docs/futures/STATUS.md:76` đếm D5 vào **"16 cơ chế an toàn (grep-verified)"**. Bảy tệp tài liệu mô tả nó.
Runner **có** cài đặt nó (`runner.py:757` nhận tham số, `:1341` kiểm, `:1447` bỏ entry).
**Không entry point nào truyền `stop_path`**,
nên `self._stop_path` luôn `None` và điều kiện luôn `False`.

**Bằng chứng đo được.**

```powershell
Get-ChildItem global_index\run_live_day.py,global_index\run_maxhold_exit.py,global_index\run_stop_repair.py |
  ForEach-Object { "$($_.Name): $((Select-String stop_path $_).Count)" }
```

```
run_live_day.py     : 0
run_maxhold_exit.py : 0
run_stop_repair.py  : 0
```

Và đo end-to-end, dựng runner đúng bộ tham số `run_live_day.py:699-720` truyền:

```
runner._stop_path                  : None
lenh da gui khi cong tac 'bat'     : [('OPEN', 'MES')]
```

**Tự kiểm.** Đây là loại khẳng định dễ sai theo hướng *"tôi grep thiếu chỗ"*. Hai đường suy ra:
(a) đếm chuỗi `stop_path` trong từng entry point = 0;
(b) dựng runner thật, đọc `runner._stop_path` = `None` và thấy lệnh vẫn đi ra.
Cả hai khớp. Không có đường thứ ba: `stop_path` là tham số của `__init__`, chỉ truyền được lúc dựng.

**Hệ quả.** Trong một sự cố, người vận hành làm đúng runbook, thấy file đã tạo, tin rằng hệ thống
đã dừng vào lệnh — và nó vẫn vào lệnh. Không có cảnh báo nào cho biết công tắc không được nối.
Đây tệ hơn *"không có công tắc"*: **một công tắc giả tạo ra cảm giác đã kiểm soát.**

**Tin cậy: ✅ đã xác minh.**

---

#### H3 — Cổng re-freeze là một hằng số `False` viết cứng, không bao giờ FAIL được

> **ĐÃ ĐƯỢC GHI NHẬN TỪ TRƯỚC — không phải phát hiện mới.**
> `TASK.md:3950` đã có mục tồn đọng **D6**: *"nối `refreeze_pending.json` vào `dump_state` —
> `runner.py:2479` đang hardcode `False`"*. (Số dòng đã trôi từ 2479 sang 2526.)
> Cái đợt này thêm vào là **mức độ**, không phải sự tồn tại: nó không chỉ là một trường chưa nối,
> nó là **một cổng go-live đang báo PASS**, và **test phủ nó assert kiểu dữ liệu của chính hằng số đó** (§4.2).
> Vì vậy nó được xếp High chứ không phải một mục doc-drift.

**Cái gì sai.**
`runner.py:2526` phát ra `"refreeze": {"pending": False}` — một literal, không đọc gì.
Trong khi đó `futures/refreeze.py` **có** duy trì một cờ pending thật ở `models/hmm/refreeze_pending.json`
(`_write_pending_flag` `:190`, `_read_pending_flag` `:213`, `_alert_if_pending` `:223`).
Runner không bao giờ đọc file đó.

Phía tiêu thụ, `monitor/backend/paper_evidence_reader.py:2987`:

```python
"status": "PENDING" if refreeze.get("pending") else "OK"
```

**Bằng chứng đo được.**

```bash
cd d:/raits && grep -n '"refreeze"' global_index/runner.py
grep -c "refreeze_pending" global_index/runner.py
grep -n "refreeze.get" monitor/backend/paper_evidence_reader.py
```

```
global_index/runner.py:2526:            "refreeze": {"pending": False},
0
monitor/backend/paper_evidence_reader.py:2962: refreeze.get('pending', '--')
monitor/backend/paper_evidence_reader.py:2987: refreeze.get("pending")
monitor/backend/paper_evidence_reader.py:2988: refreeze.get('pending', '--')
```

**Hệ quả.** Thẻ "Data freshness" trên dashboard báo `refreeze_pending=False → OK` **vĩnh viễn**,
kể cả khi `refreeze_pending.json` đang nằm trên đĩa ghi rằng một lần re-freeze đã thất bại.
Đúng loại lỗi mà đợt rà dashboard tồn tại để chống: **một phép kiểm không có khả năng thất bại**
(cùng họ với H8 "hai phép reconcile so sánh một giá trị với chính nó").

Đáng chú ý hơn: `Phụ lục J` ghi cổng re-freeze HMM là **HOÃN, chờ phiên riêng** —
nghĩa là chính cái cổng đang được coi là *"chưa dùng được"* lại đang báo OK trên bảng vận hành.

**Tin cậy: ✅ đã xác minh.**

---

#### H4 — Còn hai đường đóng lệnh nữa book tiền vào sổ vốn mà không ghi một dòng nào vào sổ lệnh

> Ba đường im lặng đã sửa 15/8 (thoát theo tín hiệu, MAX_HOLD, retry) **không** nằm trong mục này.
> Đây là hai đường khác, và cả hai vẫn im.

**Đường B — stop báo FILLED nhưng không lấy được bản ghi khớp.**
`runner.py:826-830`. IBKR nói lệnh stop đã khớp, nhưng `reqExecutions` đã quên bản ghi
(docstring `find_execution` `:1330`: *"reqExecutions phục vụ một fill trong ngày nó xảy ra và đã quên nó ngày hôm sau"*).
Nhánh này gọi `_book_realised` — **không** gọi `_record_stop_exit`. Nhánh kề bên nó gọi cả hai.
Khả năng chạm tới: một stop nổ rồi bị phát hiện muộn hơn ~2 ngày — đúng kịch bản quét lại sau cuối tuần
(commit `83ac849` *"Sweep for lost stops when the market reopens on Sunday"*).

**Đường F — lệnh vào và ra trong cùng phiên (STRESS_MID).**
`runner.py:1629-1662`. Vòng lặp same-day gửi **hai lệnh thật**, gọi `_book_realised`,
và **không hề gọi `_append_trade` lần nào** — không dòng OPEN, không dòng CLOSE, không sự kiện.

**Bằng chứng đo được.** `python <scratchpad>\repro_h4.py`:

```
H4 duong B -- stop bao FILLED, khong lay duoc ban ghi khop (runner.py:830)
  so von      : 50000.00 -> 49500.00   (-100 diem x pv 5 x 1 = -500)
  vi the      : []
  trade_log   : 0 dong

H4 duong F -- vao+ra trong cung phien (runner.py:1644-1662)
  so von      : 50000.00 -> 49950.00
  lenh da gui : [('OPEN', 'MES', 'SHORT', 1), ('CLOSE', 'MES', 'SHORT', 1)]
  trade_log   : 0 dong
  su kien EXEC: []
```

**Bảng đầy đủ — sáu đường book tiền, bốn đường ghi sổ:**

| # | Đường đóng | Vị trí | `_book_realised` | `_append_trade` |
|---|---|---|---|---|
| A | B3 stop khớp, **có** bản ghi khớp | `runner.py:822-825` | ✅ | ✅ `_record_stop_exit` |
| B | B3 stop báo FILLED, **không** có bản ghi khớp | `runner.py:830` | ✅ | ❌ **không gì cả** |
| C | Retry lệnh CLOSE hỏng | `runner.py:1085` | ✅ | ✅ `:1091` |
| D | MAX_HOLD 09:31 | `runner.py:1164` | ✅ | ✅ `:1171` |
| E | Thoát theo tín hiệu | `runner.py:1542` | ✅ | ✅ `:1563` |
| F | Vào-ra trong cùng phiên | `runner.py:1660` | ✅ | ❌ **không gì cả** |

**Hệ quả.**
Sổ vốn (`state.equity` → circuit breaker) đúng. Sổ suy từ `trade_log` — tức
`paper_epoch_closed_realized`, con số **headline** trong panel P&L Compare — thiếu đúng khoản đó.
Khoảng cách `system_ledger_vs_trade_filter` sẽ nới ra, và lời giải thích đang gắn với nó
(`ledger_offset_explanation: MATCH_PRE_EPOCH_CARRY_FILL`) sẽ **sai mà không có gì báo**.
Ngoài ra `exit_path_coverage` mất một mẫu STP, và `live_history.build_snapshots` sẽ thấy một OPEN
không có CLOSE tương ứng.

Đường F hiện **ảnh hưởng bằng 0** vì cron 10:20 đang tắt. Đường B thì sống.

**Tin cậy: ✅ đã xác minh.**

---

#### H5 — Không có trần thời gian cho một slot; một tiến trình con treo sẽ khoá toàn bộ phiên

**Cái gì sai.**
`run_scheduler.py:350` gọi `subprocess.run(args, cwd=…, capture_output=True, text=True, errors="replace")`
— **không có tham số `timeout`**. Cả tệp không có chữ `timeout` nào ngoài một dòng comment ở `:220`.

Slot được nối tiếp bằng một mutex (`_slot_lock`, `:558`). Nếu một `run_live_day` không bao giờ trả về,
mutex không bao giờ được nhả, và mọi slot sau đó trong ngày chỉ ghi:

```
[LIVE_DAY_xxxx] SKIPPED — previous run_live_day still in flight.
```

ở mức **WARNING** — cùng dòng chữ mà một lần chồng slot bình thường (chuyện xảy ra thường xuyên, vì
một lần chạy mất ~5,5 phút trong khe 5 phút) cũng sinh ra. **Không phân biệt được** giữa
"chồng một nhịp, bình thường" và "cả phiên đã chết".

**Bằng chứng đo được.**

```bash
cd d:/raits && grep -n "timeout" global_index/run_scheduler.py global_index/run_live_day.py
```

```
global_index/run_scheduler.py:220:# timeout counts on a clock that does NOT advance while the machine sleeps, so every
```

(dòng duy nhất, và nó là comment về giấc ngủ của Windows, không phải tham số.)

**Cơ chế treo — nghi ngờ có căn cứ, chưa đo.**
Các vòng chờ tôi đọc được **đều có trần**: `send_order` (30s/120s), `get_equity` (~14s),
`get_positions` (~8s), `_await_stop_accepted` (5s), `cancel_order` (5s).
Nhưng các lời gọi ib_insync **đồng bộ, không truyền timeout** — `ib.qualifyContracts`,
`ib.reqAllOpenOrders`, `ib.reqExecutions`, `reqHistoricalData` — không có trần nào ở phía runner.
Tôi **chưa đo** rằng một trong số đó thực sự treo vô hạn khi TWS đứng; tôi chỉ xác minh rằng
**nếu** nó treo, không có gì ở phía cha cắt được.

**Lưới đang có.** `dump_state` chỉ chạy khi `run_day` xong, nên `live_state_data.js` sẽ ngừng cập nhật
và cổng `runner_freshness` trên dashboard **sẽ** bắt được. Nhịp tim của scheduler (`:404`) là job riêng
và vẫn đập, nên **log trông vẫn sống** — đừng dùng log để kết luận.

**Tin cậy: ✅ đã xác minh (thiếu trần) / 🟡 nghi ngờ có căn cứ (cơ chế treo).**

---

### MEDIUM

---

#### M1 — Khớp một phần lệnh vào: stop đặt theo số đã ĐẶT, không theo số đã KHỚP

**Đo được** (`repro_h4.py`, phần cuối):

```
M1 -- dat mua 3, khop 1 (cluster khong thuoc dien hoan stop)
  place_stop goi voi contracts = 3   (thuc te giu 1)
  so runner contracts          = [3]
  trade_log (contracts, filled_qty) = (3, 1)
```

Trade log **có** ghi đúng cả hai con số. Nhưng `state.open_positions` giữ `contracts = 3`,
và mọi thứ hạ nguồn đọc con số đó: `place_stop` (`runner.py:1861`), lệnh CLOSE (`:1534`),
và `risk_dollars` cho hạn mức cluster.

**Hệ quả.** Nếu stop nổ: bán 3 trong khi giữ 1 → **short 2 hợp đồng, không stop**.
Docstring `send_order` `[2]` (`ibkr_broker.py:568`) khai *"PARTIAL exit → runner flags remaining
contracts exit_pending=True"* — **runner không làm việc đó**. Một hợp đồng đã viết ra mà không ai thực hiện.

**Mức độ hiện tại: bằng 0.** `run_live_day.py:276` đặt `N_CONTRACTS = 1`, và một lệnh thị trường
1 hợp đồng không thể khớp một phần. **Đây là chặn khi tăng quy mô, không phải lỗi đang chảy máu.**
Vì `TASK.md:3179` đang mở mục *"Scaling — bốn trục"*, nó cần nằm trong danh sách chặn của trục đó.

**Tin cậy: ✅ đã xác minh.**

---

#### M2 — `cancel_order` trả `False` cho một stop đã khớp, và runner kêu ngược sự thật

`ibkr_broker.py:1074` tìm lệnh trong `reqAllOpenOrders()` và lọc `not t.isDone()`.
Một stop **đã khớp** không nằm trong danh sách đó → `matching` rỗng → `return False`.

Runner nhận `False`, gọi `_report_stop_cancel(False, p)` (`runner.py:2164`), in:

> `STP ORPHAN: … the stop is still working at the broker and will open an unintended position when it fires.`

**Ngược hoàn toàn**: stop không còn sống, nó đã khớp.

**Hệ quả.** `run_scheduler._run` (`:363`) lọc mọi dòng `CRITICAL`/`ERROR` từ tiến trình con và nâng
lên log của scheduler kể cả khi mã thoát 0 — cơ chế này được thêm vào **chính vì** một `STP ORPHAN`
thật đã bị nuốt ngày 2026-08-10. Giờ một `STP ORPHAN` giả cũng được nâng lên như vậy,
làm mòn đúng cảnh báo mà cơ chế đó sinh ra để bảo vệ.

**Tin cậy: ✅ đã xác minh** (đọc hết chuỗi; chưa đo trên IBKR thật vì không được kết nối).

---

#### M3 — `find_execution` khớp theo `orderId`, chính docstring của nó nói `orderId` lặp giữa các client

`ibkr_broker.py:1354`: `if getattr(ex, "orderId", None) != order_id_int: continue`.
Docstring ngay trên đó (`:1333`):

> *"permId is included because it is IBKR's stable global identifier. **orderId repeats across clients** — the ambiguity behind the #62-vs-#9 mix-up."*

Hàm **trả** `perm_id` trong kết quả nhưng **không dùng** nó để lọc.
Nó dừng lại đúng một bước trước chỗ mà nó tự chẩn đoán.

**Hệ quả.** `_book_realised` ở đường B3 lấy `price` và `shares` từ bản ghi này để ghi sổ vốn.
Nếu một client khác từng dùng cùng `orderId`, sổ vốn được ghi bằng **giá khớp của một lệnh khác**.
Bối cảnh làm chuyện này không viển vông: `cancel_order` `:1096` ghi lại một sự cố thật
ngày 2026-08-06 với các clientId 1, 77, 82, 93 cùng chạm vào một tài khoản.

**Tin cậy: ✅ đã xác minh (code) / cần đo thêm (tần suất va chạm orderId thực tế).**

---

#### M4 — Hai đồng hồ cùng quyết định tháng hợp đồng

| Ai hỏi | Hàm | Khung thời gian |
|---|---|---|
| "hôm nay có phải ngày roll không" | `get_roll_event(inst, today)` | **ngày phiên** runner truyền vào |
| "lệnh này đi vào tháng nào" | `_current_front_month(sym)` — `_front_month_contract:308` gọi **không truyền `today`** | **đồng hồ tường** `pd.Timestamp.now(tz=ET)` |

Runner nói rõ (`runner.py:61-64`) rằng mọi câu hỏi *"hôm nay là ngày nào"* phải trả lời bằng ET
và không bao giờ bằng đồng hồ máy — máy chạy trước 11 tiếng.
`_current_front_month` **có** dùng ET, nên nó không sai múi giờ; nhưng nó trả lời câu hỏi
*"hôm nay ở thực tại"* chứ không phải *"phiên nào đang được xử lý"*.

**Hệ quả.** Trong mọi lần chạy bình thường hai đồng hồ trùng nhau. Chúng tách ra khi:
· chạy bù một phiên đã qua · replay · một slot bắt đầu trước nửa đêm ET và kết thúc sau.
Khi tách, `_handle_rollover` quyết định theo một tháng còn lệnh đi vào tháng kia — đúng hình dạng C1.

**Tin cậy: ✅ đã xác minh** (`repro_c1.py`, phần M4).

---

#### M5 — Delta tài khoản broker được đo rồi vứt, không có phép đối chiếu nào

`runner.py:1673-1684` đọc `broker.get_equity()`, tính `_h4_delta`, cập nhật `_last_broker_equity`,
rồi in một dòng log **và không so nó với gì cả**. Comment nói thẳng:
*"The line stays because a large unexplained move in the account is still worth seeing."*

Không có ngưỡng, không có so sánh với tổng P&L đã book trong cùng lần chạy, không có sự kiện phát ra.
*"Đáng để nhìn"* không phải một phép kiểm — nó là một dòng trong một tệp log không ai đọc mỗi 5 phút.

Đây là cặp song song **duy nhất** trong runner có sẵn cả hai vế (delta broker và tổng `_book_realised`
của cùng lần chạy) mà **không** có phép đối soát nào. Tài khoản là CAD ~$996k, gấp 20 lần sleeve,
nên không thể so tuyệt đối — nhưng một **cận trên** thì so được. Đúng chỗ mà C8 ($1.260) lẽ ra đã lộ ra ngay ngày đầu.

**Tin cậy: ✅ đã xác minh.**

---

#### M6 — Bốn trường vận hành khác trong payload là hằng số cứng

| Trường | Giá trị | Vấn đề |
|---|---|---|
| `runner_health.ibkr_connected` | `None` (`:2742`) | Runner **đang** cầm một kết nối IBKR sống khi ghi dòng này. Trường tồn tại, không ai điền. |
| `model_age.model_name` | `"fit_C"` (`:2503`) | Tên model viết cứng. Đổi model → dashboard vẫn báo `fit_C`. Cùng họ với `refreeze.CALMAR_FLOOR = 2.38` sống sót sáu tuần. |
| `meta.total_days` | `1` (`:2724`) | Luôn là 1 kể cả khi `snapshots` có tới 500 phần tử. |
| `snapshot.max_dd_dollars` | `= snap_dd_dollars` (`:2683`) | Đây là **drawdown hiện tại** (`peak − cur`), không phải max drawdown. Hai khái niệm khác nhau mang cùng một tên. |

**Tin cậy: ✅ đã xác minh.**

---

### LOW

**L1 — `ROLL_SCHEDULE["NKD"]` đã chết nhưng vẫn được test.**
Từ 14/8, `_RAITS_TO_IBKR` chỉ sinh `MNKD → MNK`, và `_to_runner` cố ý **không** dịch ngược `NKD`.
Không đường production nào còn tra `ROLL_SCHEDULE["NKD"]`. Nó vẫn ở đó, là bản sao thứ hai của
đúng chu kỳ đáo hạn với `MNK` — hai bản sao là hai cơ hội trôi. Xem §4.3 về việc test đang neo vào bản chết.

**L2 — Sàn Calmar 1,65 không bị test nào ràng buộc với `INVARIANTS.md`.**
`generate_replay_snapshots.py:37` đã import từ `runner`, nên hai bản sao **code** đã hợp nhất — tốt.
Nhưng `INVARIANTS.md` được khai là nguồn sự thật và **không có test nào so hai bên**:
`grep -rl BACKTEST_CALMAR_FLOOR global_index/test_*.py futures/test_*.py` → rỗng.
Đây đúng cơ chế đã để `refreeze.CALMAR_FLOOR = 2.38` sống sót sáu tuần sau khi bị khai tử.

**L3 — `contracts_by_inst.get(inst, 1)` mặc định im lặng 1 hợp đồng.**
`live_decision.py:138` và `runner.py:1630,1716`. Một mã chưa khai trong bảng vẫn giao dịch 1 hợp đồng
thay vì bị từ chối. Hôm nay vô hại (mọi mã đều = 1); thành cái bẫy đúng lúc bắt đầu tăng quy mô.

**L4 — `_retry_pending_exits` cộng `p.pnl_sized` lần thứ hai.**
`live_decision.py:98` đã cộng `p.pnl_sized` khi quyết định thoát. Nếu lệnh CLOSE hỏng, vị thế được
đưa lại vào sổ (`runner.py:1594`), và `runner.py:1083` cộng **lại** `p.pnl_sized` ở lần retry.
Trong live `pnl_sized = 0.0` nên không có tác dụng; trong verify mode `MockBroker` luôn `FILLED`
nên không bao giờ chạm tới. **Tiềm ẩn, chưa từng nổ** — nhưng nó là loại lỗi mà không test nào có thể đỏ.

---

## 2. Bảng "quyết định được ra nhưng không ai ghi lại"

Mọi đường có thể mở / đóng / sửa một vị thế hoặc một lệnh dừng, và cái nó để lại.

| # | Đường | Vị trí | Sổ vốn | `trade_log` | Sự kiện (dashboard) | Log | Đánh giá |
|---|---|---|---|---|---|---|---|
| 1 | Mở, khớp đủ hoặc một phần | `runner.py:1733` | — | ✅ | ✅ | ✅ | đủ |
| 2 | **Mở, bị huỷ (`CANCELLED`)** | `runner.py:1733` | — | ❌ | ❌ | ❌ | **C2 — mù hoàn toàn** |
| 3 | Vào + ra cùng phiên | `runner.py:1644` | ✅ | ❌ | ❌ | ❌ | **H4 đường F** |
| 4 | Thoát theo tín hiệu, khớp | `runner.py:1533` | ✅ | ✅ | ✅ | ✅ | đủ (sửa 15/8) |
| 5 | Thoát theo tín hiệu, `FAILED` | `runner.py:1592` | — | ❌ | ✅ | ✅ | chấp nhận được — sẽ retry |
| 6 | Retry thoát | `runner.py:1071` | ✅ | ✅ | ✅ | ✅ | đủ (sửa 15/8) |
| 7 | MAX_HOLD 09:31 | `runner.py:1145` | ✅ | ✅ | ✅ (khi hỏng) | ✅ | đủ (sửa 15/8) |
| 8 | B3: stop khớp, **có** bản ghi khớp | `runner.py:822` | ✅ | ✅ | — | ✅ | đủ |
| 9 | **B3: stop FILLED, không có bản ghi khớp** | `runner.py:830` | ✅ | ❌ | ❌ | ✅ | **H4 đường B** |
| 10 | B3: vị thế biến mất không giải thích được | `runner.py:520` | — | — | ❌ | ✅ CRITICAL | halt entry — đúng |
| 11 | Roll: đóng cũ + mở mới | `runner.py:1229` | — | ❌ | ✅ | ✅ | **không dòng trade nào cho hai lệnh thật** |
| 12 | Roll: mở hỏng sau khi đóng xong | `runner.py:1250` | — | ❌ | ✅ CRITICAL | ✅ | vị thế bị gỡ khỏi sổ, không ghi CLOSE |
| 13 | B4 đặt lại stop | `runner.py:680` | — | ❌ | ❌ | ✅ WARNING | **không sự kiện** |
| 14 | B4 phát hiện vị thế trần | `runner.py:695` | — | — | ❌ | ✅ CRITICAL | **không sự kiện** |
| 15 | B5 phát hiện vị thế trần cuối phiên | `runner.py:2094` | — | — | ✅ CRITICAL | ✅ | đủ |
| 16 | Đặt STP lúc vào lệnh | `runner.py:1860` | — | ❌ | ✅ | ✅ | đủ |
| 17 | Hoãn STP sang phiên sau | `runner.py:1844` | — | ❌ | ✅ | ✅ | đủ |
| 18 | Huỷ STP khi đóng vị thế | `runner.py:1613` | — | ❌ | ✅ (khi hỏng) | ✅ | đủ, nhưng xem M2 |
| 19 | Huỷ STP khi roll | `runner.py:1290` | — | ❌ | ❌ | ✅ CRITICAL | **không sự kiện khi huỷ hỏng** |
| 20 | Dời mức STP khi roll | `runner.py:1933` | — | ❌ | ❌ | ✅ CRITICAL | **không sự kiện** |

**Bốn cụm đáng chú ý.**

1. **Hai đường (#2, #3) không để lại dấu vết nào ở đâu cả.** Không phải "ghi thiếu trường" — là **không ghi gì**.
2. **Hai đường (#3, #9) chuyển tiền trong sổ vốn mà sổ lệnh không biết** (H4).
3. **Toàn bộ đường roll (#11, #12, #19, #20) không ghi một dòng `trade_log` nào**, dù #11 gửi hai lệnh thị trường thật.
   Sau roll đầu tiên, `trade_log` sẽ không giải thích được vì sao giá vào của vị thế thay đổi.
4. **B4 (#13, #14) chỉ nói qua log, B5 (#15) phát sự kiện.** Nên một vị thế trần do B4 phát hiện
   lúc khởi động **không xuất hiện trên dashboard**; chỉ bản B5 tìm thấy cuối `run_day` mới xuất hiện.
   Hai guard cho cùng một tình huống, hai độ hiển thị khác nhau.

---

## 3. Bảng "cặp chạy song song và tình trạng đối soát"

| # | Hai đường tính cùng một thứ | Phép đối soát | CÓ THỂ THẤT BẠI? |
|---|---|---|---|
| 1 | `live_positions.json` ↔ vị thế thật ở IBKR | **B3** (`runner.py:431-557`) | ✅ **có** — halt entry, đã nổ thật |
| 2 | Stop theo **id** (`get_working_stops`) ↔ stop theo **hợp đồng** (`unprotected_positions`) | **B4** (`runner.py:645`) — bất đồng thì tin bên hợp đồng | ✅ **có**, có ưu tiên rõ ràng |
| 3 | `_ARM_BY_CLUSTER` ↔ `_DEFERRED_STOP_CLUSTERS` | `test_arm_time_per_sleeve.py:114` assert hai tập bằng nhau | ✅ **có** |
| 4 | Đích từ checkpoint ↔ đích từ replay đầy đủ | `--shadow-verify`, 1 lần/ngày ở slot cuối | ✅ **có** |
| 5 | Sổ vốn (`state.equity`) ↔ sổ suy từ `trade_log` | `system_ledger_vs_trade_filter` trên dashboard | 🟡 **có, nhưng lệch do H4 sẽ bị quy cho `MATCH_PRE_EPOCH_CARRY_FILL`** |
| 6 | **Delta NetLiquidation broker ↔ tổng P&L đã book cùng lần chạy** | **KHÔNG CÓ** — chỉ in một dòng log | ❌ **M5** |
| 7 | **`get_roll_event(inst, ngày phiên)` ↔ `_current_front_month(sym, đồng hồ tường)`** | **KHÔNG CÓ** | ❌ **M4, và là cơ chế của C1** |
| 8 | **`_handle_rollover` dựng hợp đồng ↔ `_front_month_contract` dựng hợp đồng** | **KHÔNG CÓ** | ❌ **H1** |
| 9 | **`refreeze_pending.json` trên đĩa ↔ `refreeze.pending` trong payload** | **KHÔNG CÓ** — payload là literal `False` | ❌ **H3** |
| 10 | `contracts` đã đặt ↔ `filled_qty` đã khớp | ghi cả hai vào `trade_log`, **không ai so** | ❌ **M1** |
| 11 | `guard.account` ↔ `breaker.account` | cả hai nhận `ACCOUNT` từ `run_live_day.py:701,704` | 🟢 trùng nguồn, không cần đối soát |
| 12 | `BASKET.point_value` ↔ `SPECS.point_value` | chuỗi fallback trong `statement.point_value` — BASKET thắng im lặng | 🟢 **hai tập khoá rời nhau** (`{M2K,MES,MNQ,MYM}` vs `{MNKD,NKD}`), hôm nay không có chỗ nào trôi được. Thêm một mã vào cả hai bảng là mở lại bẫy. |
| 13 | `BACKTEST_CALMAR_FLOOR` ↔ `INVARIANTS.md` | **KHÔNG CÓ TEST** | ❌ **L2** |
| 14 | `ROLL_SCHEDULE["MNK"]` ↔ `ROLL_SCHEDULE["NKD"]` | **KHÔNG CÓ** — hai bản sao cùng chu kỳ đáo hạn | ❌ **L1** |

**Đếm: 4 cặp có đối soát thất bại được, 1 cặp có nhưng dễ bị quy sai, 7 cặp không có gì.**

---

## 4. Lỗ hổng test — chỗ một lỗi sẽ lọt qua toàn bộ 46 tệp

**Nền: `518/518` PASS, không loại trừ tệp nào.** Mọi phát hiện ở §1 đang đúng trong lúc bộ test xanh hoàn toàn.

```bash
cd d:/raits
# phan nhanh -- 506 test
python -m pytest global_index/ -q --ignore=global_index/test_event_playback.py -p no:randomly
# 506 passed in 15.56s

# phan cham -- 12 test, ~17 phut (replay 1381 ngay). GHI THANG RA FILE, dung pipe qua tail:
python -m pytest global_index/test_event_playback.py -v -p no:randomly > playback.txt 2>&1
# 12 passed in 995.12s (0:16:35)
```

> **Cách phép đo này suýt sai.** Lần chạy đầu tôi pipe qua `tail -25`: exit code 0 nhưng output
> chỉ có **8 dấu chấm** trong khi `--collect-only` đếm **12** test. Không phải test bị bỏ —
> là buffer bị cắt. Bắt được vì 8 ≠ 12 là một giá trị bất khả thi, không phải vì nghi ngờ gì.
> Ghi thẳng ra file cho đủ 12 dòng `PASSED` và dòng tổng kết.

### 4.1 Một test được viết đúng cho kịch bản C2 — và nó không assert gì

`global_index/test_stp.py:224`:

```python
def test_stp4_no_stp_when_open_cancelled():
    broker = _CancelledOpenBroker({}, ACCOUNT)
    runner = FuturesRunner(broker=broker, guard=_make_guard(), …)
    # Must not raise (asserting inside _CancelledOpenBroker.place_stop)
    runner.run_day(DAY1)
```

Thân hàm **không có một `assert` nào**. Nó dựa vào `_CancelledOpenBroker.place_stop` tự `raise`,
tức kiểm đúng một điều: *stop không được đặt*. Nó **không** hỏi:
· vị thế còn nằm trong `state.open_positions` không?
· `entry_price` có bị bỏ trống không?
· có dòng `trade_log` nào không?
· có sự kiện nào không?

Toàn bộ C2 nằm gọn trong bốn câu hỏi không được hỏi, **ngay trong test mang tên chính kịch bản đó**.

### 4.2 Cổng re-freeze có hai test, và không cái nào có khả năng đỏ

Chỉ hai tệp chạm `refreeze` trong payload runner. Cả hai đều tránh đúng câu hỏi duy nhất đáng hỏi.

`global_index/test_operational_fixes.py:891` — assert **kiểu**:

```python
check("T19.6 refreeze.pending is bool",
      isinstance(ops["refreeze"]["pending"], bool))
```

Cái được assert là `isinstance(False, bool)`. Chứng minh rằng một literal là một literal.

`global_index/test_event_playback.py:733` — assert **sự có mặt của khoá**:

```python
required_ops = {"runner", "breaker", "regime_freshness", "model_age",
                "positions", "refreeze", "regime_unreliable"}
check("P3.2 all 7 ops-status keys present", required_ops.issubset(ops.keys()))
```

Không cái nào so `refreeze.pending` với `models/hmm/refreeze_pending.json` — thứ duy nhất
làm cổng này có nghĩa. **H3 có 0 phép kiểm có khả năng thất bại trên toàn bộ 46 tệp.**
Một trường có thể bị đóng băng thành `False` vĩnh viễn và cả hai test vẫn xanh; đó chính là
tình trạng hiện tại.

### 4.3 Test lịch roll neo vào một khoá mà production không bao giờ dùng

`global_index/test_rollover.py:196-203`:

```python
("NKD", "2026-09-04", "202609", "202612"),
```

Production gọi `get_roll_event(pos.inst, …)` với `pos.inst = "MNKD"`.
Test gọi bằng `"NKD"` — mã full-size, đã bị gỡ khỏi mọi đường định tuyến từ 14/8.
**Test xanh trên một khoá không tồn tại trong đường chạy.** Đây chính xác là cái đã cho C1 sống:
sửa định tuyến ngày 14/8 đổi khoá mà production truyền vào, còn test vẫn hỏi bằng khoá cũ.

Test còn thiếu: `("MNKD", "2026-09-04", …)`. Một dòng.

### 4.4 Không test nào chạy `IBKRBroker._handle_rollover` thật

Cả `test_rollover.py` lẫn `test_rollover_stop.py` đều cài **`_handle_rollover` giả** trên broker mock
(`test_rollover.py:66`, `test_rollover_stop.py:53`). Chúng kiểm phản ứng của **runner** trước các
kết quả roll — đúng và có giá trị — nhưng chưa bao giờ chạm vào cách `IBKRBroker` **dựng hợp đồng**.
H1 (tên thô, sàn ép cứng, không kiểm `conId`) nằm trọn trong vùng không ai chạm.

### 4.5 Không test nào biết tới `stop_path` / D5

```bash
cd d:/raits && grep -rl "stop_path\|STOP_FILE" global_index/test_*.py     # rỗng
```

D5 được đếm là 1 trong 16 cơ chế an toàn "grep-verified" (`STATUS.md:76`) và có **0 test**.
Không có test nào để đỏ khi nó bị tháo ra khỏi dây.

### 4.6 Bốn dạng lỗi mà toàn bộ 46 tệp sẽ để lọt

| Dạng | Vì sao lọt | Ví dụ trong báo cáo này |
|---|---|---|
| **Trạng thái broker ≠ trạng thái runner sau một lệnh không khớp** | mọi mock broker mặc định `FILLED`; các mock hỏng chỉ dùng để kiểm *lệnh không được gửi*, không kiểm *sổ sách sau đó* | C2, M1 |
| **Một bảng tra được đánh khoá sai loại tên** | test tra bằng chính khoá mà bảng đang có, không phải khoá mà production truyền vào | C1, L1 |
| **Một trường payload là hằng số** | test assert kiểu, không assert quan hệ với nguồn thật | H3, M6 |
| **Một tham số an toàn không được truyền** | không test nào dựng runner bằng **đúng bộ tham số production**; mỗi test tự dựng bộ tối thiểu của nó | H2 và mọi tham số tuỳ chọn khác |

**Một test sẽ chặn được cả bốn dạng:** dựng runner bằng đúng danh sách tham số mà `run_live_day.py:699`
truyền, rồi assert từng cơ chế an toàn đang thật sự được nối. Hôm nay không có test nào nhìn vào
`run_live_day.py` cả — mỗi test tự dựng runner theo cách riêng, nên khoảng cách giữa
*runner có thể làm gì* và *runner được nối để làm gì* không ai đo.

---

## 5. Kết luận

### Runner có an toàn để chạy tiền thật chưa?

**Chưa.** Ba thứ chặn cứng, theo thứ tự gấp:

#### Chặn 1 — C1, và nó có hạn chót

Roll Nikkei **04/9/2026, còn 20 ngày**. Nếu có một vị thế `MNKD` mở qua ngày đó,
vị thế và lệnh tách ra hai tháng hợp đồng, và lệnh đóng kế tiếp **mở** một vị thế thay vì đóng.
Không guard nào chặn được bước đó — B5 chỉ báo **sau khi** lệnh đã ra.
Lịch trực hiện tại nhắm vào 11/9 và khung 13:45–14:05 ET; roll Nikkei rơi vào 04/9 khung đêm.

Sửa tối thiểu là một khoá trong `ROLL_SCHEDULE`. Nhưng **sửa một dòng là không đủ** —
nó chỉ mở đường tới H1, nơi hợp đồng được dựng bằng tên thô trên sàn ép cứng.
Đây đúng bài học Phụ lục A: *"ĐỔI ĐỊNH TUYẾN CỤ THỂ LÀ ĐỔI GÌ — MỘT DÒNG LÀ KHÔNG ĐỦ."*

#### Chặn 2 — C2, và nó không cần dịp đặc biệt nào

Không cần ngày roll, không cần sự cố. Chỉ cần **một lệnh vào hết 30 giây chờ** — đường hỏng
thường gặp nhất của bất kỳ hệ đặt lệnh nào, và là đường mà `send_order` có hẳn một hằng số riêng
(`ENTRY_FILL_TIMEOUT_SECS = 30`) để phục vụ. Kết quả tốt nhất là cả hệ thống halt entry cho tới khi
có người sửa tay; kết quả xấu nhất là một vị thế ngược chiều không stop, notional $38.995.

#### Chặn 3 — H2, vì nó phá kế hoạch ứng cứu của hai chặn trên

Cả C1 lẫn C2 đều có cùng một câu trả lời vận hành: *dừng vào lệnh, giữ nguyên exit, xử lý tay*.
Đó chính xác là việc D5 sinh ra để làm, runbook mô tả nó, `STATUS.md` đếm nó vào 16 cơ chế an toàn,
và **nó không được nối**. Người vận hành sẽ làm đúng quy trình và tin rằng hệ thống đã dừng.

### Còn nợ trước khi các con số có thể trích dẫn được

· **H4** — hai đường đóng lệnh chuyển tiền trong sổ vốn mà sổ lệnh không thấy.
  Cho tới khi vá, `paper_epoch_closed_realized` là một con số **thiên lệch có hệ thống**,
  và cơ chế hiện có để phát hiện thiên lệch đó (`system_ledger_vs_trade_filter`)
  đã có sẵn một lời giải thích để quy cho.
· **H3** — cổng re-freeze đang báo OK bằng một hằng số, trong khi Phụ lục J ghi chính cổng đó là *"chưa dùng được, hoãn"*.
· **M5** — cặp song song duy nhất còn đủ hai vế mà không có phép đối soát nào.

### Cái tôi đã đo và KHÔNG thấy vấn đề

Nói rõ để phân biệt với *"chưa đo"*:

· **Cửa sổ hoãn stop** (`_stop_deferred`, `runner.py:1998`) — luật đúng, giờ vũ trang khai theo **múi giờ**
  chứ không theo giờ ET cố định, nên DST không làm trôi; B4/B5 đều hỏi vị từ này trước khi gọi một vị thế
  là trần; `test_arm_time_per_sleeve` ràng `_ARM_BY_CLUSTER` với `_DEFERRED_STOP_CLUSTERS`. Không tìm được lỗ.
· **`_verified_status`** (`ibkr_broker.py:746`) — xử lý đúng `Cancelled` giả của ib_insync;
  chỉ re-poll khi `filled == 0`, và ưu tiên execution report hơn cờ trạng thái. Đúng.
· **Ranh giới ký hiệu** — `_to_runner` được áp ở `get_positions`, `has_working_stop`,
  `unprotected_positions`, `get_working_stops`; `_RAITS_TO_IBKR` **được suy ra** từ `Contract.ibkr`
  chứ không viết tay; `test_symbol_boundary` đọc chính tệp nguồn để chặn một call site thứ bảy.
  Việc sửa 14–15/8 làm đúng — **trừ đường roll**, thứ không đi qua ranh giới đó (H1).
· **`_splice_live` khi mất bar** (`run_live_day.py:312`) — bar sống rỗng thì trả nguyên parquet,
  **không** trả khung rỗng. Nên một lần mất feed **không** làm `desired_position` trả `None`
  và **không** sinh lệnh đóng giả. Tôi đã đi tìm đúng lỗi này và nó không có ở đây.
· **`_mark_held_unchanged`** (`signal_layer.py:130`) — im lặng không bị hiểu là "đóng hết";
  cluster bị tắt được gắn dummy giữ nguyên chiều. Đúng.
· **Gán nhãn `exit_reason`** — `_record_exit_reason` (`swing_tf.py:84`) chỉ báo lý do cho một lệnh
  đóng **đúng ngày bar cuối**, nên một lý do cũ không thể dán lên lệnh thoát hôm nay.
  Ba nhánh sinh exit (không còn muốn giữ / đảo chiều / cùng chiều nhưng trade mới) đều lấy đúng
  trade vừa đóng. Đúng.
· **Thứ tự exit-trước-entry và điểm đo phanh ngày** — `decide_day` chốt baseline **sau** các lệnh đóng
  (`live_decision.py:104-119`), lệch với tên hàm nhưng **cố ý**, có ghi ngày quyết định, và trùng `deploy_sim.replay`.
  Runner còn kiểm phanh **lần hai** trước khi thả lệnh vào nhiều ngày (`runner.py:1694`). Đúng.
· **`BASKET` vs `SPECS`** — hai tập khoá rời nhau, nên chuỗi fallback trong `point_value` và `_tick_size`
  hôm nay không có chỗ nào để trôi. Không phải *"không có vấn đề mãi mãi"*: thêm một mã vào cả hai bảng là mở lại bẫy.

### Cái tôi CHƯA đo được

· **Cơ chế treo cụ thể của H5.** Tôi xác minh không có trần thời gian; tôi **không** xác minh
  được rằng một lời gọi ib_insync cụ thể sẽ treo vô hạn khi TWS đứng. Cần một lần đo có chủ đích với Gateway.
· **Tần suất va chạm `orderId` giữa các client (M3).** Cần đọc `reqExecutions` thật trên nhiều client.
· **Hành vi `qualifyContracts` với `exchange="CME"` cho MYM (H1).** Tôi dựa vào chính docstring
  `_front_month_contract` (đã kiểm chứng đợt trước) rằng nó để `conId = 0` và không raise.
  Chưa gọi IBKR để xác nhận sàn sai cho ra đúng hành vi đó — không được phép kết nối trong đợt này.
· *(Đã đóng sau khi viết bản đầu — 2026-08-15)* **`test_event_playback.py`**: chạy rồi, exit code 0.
  Nó **không** bắt được H3 — `:733` chỉ assert khoá `refreeze` có mặt, không assert giá trị.
  Xem §4.2 đã cập nhật: H3 có 0 phép kiểm có khả năng thất bại trên toàn bộ 46 tệp.
· *(Đính chính đề bài)* `test_runner_event_log::test_incomplete_tail_is_not_extended` được nêu là
  "hỏng sẵn từ baseline" — nó **đang xanh**, do commit `a450712` sửa. Không còn là một mục đã biết.

---

## 6. Lệnh để chạy lại mọi phép đo

Các kịch bản tái lập đã được ghi ra thư mục scratchpad của phiên. Không tệp nào ghi vào repo,
không tệp nào kết nối IBKR, không tệp nào chạm `live_positions.json` hay bất kỳ `.parquet` nào.

```powershell
cd d:\raits
$S = "C:\Users\quock\AppData\Local\Temp\claude\d--raits\c0cae186-a006-48bc-9d71-c502bc26d55c\scratchpad"

python $S\repro_c1.py     # C1 + M4 : lich roll va hai dong ho
python $S\repro_c2.py     # C2      : vi the ma + lenh nguoc chieu (co cot doi chung)
python $S\repro_h4.py     # H4 + M1 : hai duong dong lenh khong ghi so; stop theo so da dat
```

```powershell
# H1 -- bon call site dung hop dong
python -c "import inspect; from global_index import ibkr_broker as B; [print(n,':',[l.strip() for l in inspect.getsource(getattr(B.IBKRBroker,n)).splitlines() if '_front_month_contract' in l or 'ibi.Future(' in l or 'exchange=\"' in l]) for n in ('send_order','place_stop','_fetch_raw','_handle_rollover')]"

# H2 -- cong tac D5 khong duoc noi
Get-ChildItem global_index\run_live_day.py,global_index\run_maxhold_exit.py,global_index\run_stop_repair.py |
  ForEach-Object { "$($_.Name): $((Select-String stop_path $_).Count)" }

# H3 -- cong refreeze la mot hang so
Select-String '"refreeze"' global_index\runner.py
Select-String 'refreeze.get' monitor\backend\paper_evidence_reader.py

# H5 -- khong co tran thoi gian cho mot slot
Select-String 'timeout|subprocess.run' global_index\run_scheduler.py

# L2 -- san Calmar khong bi test rang buoc
Select-String BACKTEST_CALMAR_FLOOR global_index\test_*.py futures\test_*.py

# Nen do (16s, khong dung IBKR)
python -m pytest global_index/ -q --ignore=global_index/test_event_playback.py -p no:randomly
```

**Toàn bộ đợt rà này không sửa một dòng code, cấu hình hay state file nào,
không kết nối IBKR, và không xoá tệp nào.**
