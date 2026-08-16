# Báo cáo Audit — RAITS Paper Evidence Dashboard

**Ngày audit:** 2026-08-14
**Cập nhật lần cuối:** 2026-08-14 cuối phiên, sau batch 1 (7 mục cơ học), batch 2 (C1 + C4 + vá marker), C8 (định tuyến MNKD), và batch 3 (M1–M7, L3–L5, H3, bút toán đối soát, nền tảng tiền broker; M8 sửa được sau khi dựng panel TWS)
**Phạm vi:** `global_index/dash/paper/{index.html,paper.js,paper.css}`, `monitor/backend/paper_evidence_reader.py`, `monitor/test_dashboard_backend.py` — mở rộng trong quá trình audit sang `global_index/ibkr_broker.py`, `global_index/statement.py`, `monitor/paper_pnl_compare.py`
**Trang:** http://127.0.0.1:5002/paper

**Kết quả chạy kiểm chứng (lúc audit):**
- `node --check global_index/dash/paper/paper.js` → OK
- `python -m pytest monitor/test_dashboard_backend.py -q` → **89 passed** (hiện tại: **142 passed**)
- `python -m pytest global_index/test_statement.py -q` → **13 passed** (mới thêm 3)
- Dump payload `/api/v1/paper-evidence` và đối chiếu với UI thực tế
- Playwright ở 1440px và 390px: **0 lỗi console, 0 tràn ngang cấp trang**

> Lưu ý môi trường: gọi offline `read_paper_evidence(Path('.'))` cho `contract_spec_guard = MISSING` (không có cache IBKR); server đang chạy cho `OBSERVED`. Cả hai đều được dùng ở dưới khi liên quan.

---

## TRẠNG THÁI SỬA CHỮA

| Mã | Mức | Trạng thái | Ghi chú |
|---|---|---|---|
| **C1** | Critical | ✅ **ĐÃ SỬA** | Lọc theo khối. Ô nhiễm **lớn hơn báo cáo gốc rất nhiều** — xem phần cập nhật ở mục C1 |
| **C2** | Critical | ✅ **ĐÃ SỬA** | `min_distinct_sessions = 10`. Gate PASS giả đã biến mất — **không còn gate nào tự nhận PASS** |
| **C3** | Critical | ✅ **ĐÃ SỬA** | `compositeStatus` đã nhận đủ 3 đầu vào |
| **C4** | Critical | ✅ **ĐÃ SỬA** | `cold_starts` 0 → 8; mismatch gộp thành episode |
| **H2** | High | ✅ **ĐÃ SỬA** | `QUALITY_BREACH` + class `.quality-breach`, render vàng |
| **H5** | High | ✅ **ĐÃ SỬA** | Đã gỡ nút TWS trỏ sai. B3 vẫn chưa có drill-down |
| **H7** | High | ✅ **ĐÃ SỬA** | Guard phủ 6 mã gồm MNKD. **Kèm 1 regression đã vá** — xem mục H7 |
| **H8** | High | ✅ **ĐÃ SỬA** | Đã xoá phép so sánh chính-nó và fallback-về-chính-nó |
| **L1, L2** | Low | ✅ **ĐÃ SỬA** | 3 hàm chết + 7 ID mồ côi đã gỡ |
| **C5** | Critical | 🟡 **VÁ TẠM** | Gate đổi `PENDING` → `STRUCTURAL_GAP`, nói rõ là thiếu công cụ đo. **Sửa gốc vẫn ở runner** |
| **C6** | Critical | ❌ Chưa | Lỗi runner. Không phải lỗi an toàn — xem phần đính chính ở mục C6 |
| **H1** | High | ✅ **ĐÃ SỬA** | Cả 7 dòng "current status" khớp payload nguyên văn |
| **H6** | High | ✅ **ĐÃ SỬA** | Kèm 1 thụt lùi đã vá — xem mục H6 |
| **H3** | High | ✅ **ĐÃ SỬA** | Trung bình theo từng mã + quy đổi đô-la; giữ cảnh báo gộp |
| **H4** | High | ✅ **ĐÃ SỬA** | `min_n=30` cho STP close, dẫn xuất từ nhịp mẫu đo được (Phụ lục K) |
| **M1, M3–M7** | Medium | ✅ **ĐÃ SỬA** | M5/M6 cần chủ dự án chọn cách trình bày trước — đã chọn và làm |
| **M8** | Medium | ✅ **ĐÃ SỬA** (vòng 2) | Ban đầu kết luận không sửa được — đúng lúc đó. Sau khi dựng panel TWS (I.3) thì có đích hợp lệ; 4/4 gap có nút |
| **M2** | Medium | 🟡 **TỰ KHỎI** | Hết nhiễu nhờ C1; regex gốc đã siết bằng exclude `OPERATOR:\s` |
| **L3–L5** | Low | ✅ **ĐÃ SỬA** | Làm tròn 4dp, giữ tiêu đề section, sắp thẻ theo mức độ |
| **C7** | — | ⛔ **RÚT LẠI** | Kết luận sai về cơ chế thoát lệnh, chủ dự án đính chính — xem mục C7 |
| **C8** | **Critical** | ✅ **ĐÃ SỬA** | **Lỗi nghiêm trọng nhất cả đợt.** Lệnh MNKD định tuyến sang hợp đồng gấp 10 lần. Phụ lục A/D/E/F |
| **G1** | **High** | ✅ **ĐÃ SỬA** | Phép đối chiếu Flex dựng tiền bằng `point_value` cục bộ nên tự triệt tiêu sai multiplier. Phụ lục B/G |
| **G2** | Medium | ✅ **ĐÃ SỬA** | Chuỗi mô tả nguồn tiền là literal cứng, thành sai sau khi G1 được sửa. Phụ lục G |
| **G3** | Medium | ⚠️ **ĐÃ GHI NHẬN** | Dashboard đọc artifact sinh sẵn `paper_pnl_compare.json` — sửa code không tới UI cho tới khi regenerate. Phụ lục G |

> **C8 không phải lỗi dashboard.** Nó là lỗi định tuyến lệnh trong runner, và chỉ lộ ra vì lỗ hổng `contract_spec_guard` ở H7 khiến tôi đi hỏi thẳng IBKR. Xét về tiền thật, nó lớn hơn toàn bộ các mục còn lại cộng lại.

**Kết quả đo được sau khi sửa:**

| Chỉ số | Lúc audit | Hiện tại |
|---|---|---|
| `stp_failed` | 2 (100% mock) | **0** |
| B3 mismatch | "100 mismatch" | **1 episode / 2 vị thế / 50 phút** |
| `cold_starts` | 0 (regex chết) | **8** |
| `dropped_test_lines` | 319 | **1160** (54 khối) |
| `manual_intervention` candidate | 128 | **0** (toàn bộ là mock) |
| TWS candidate | 281 | **4** (281 → 192 sau lọc khối, → 4 sau exclude M1) |
| `stp_verification` | PASS (1 record tự khai) | **PENDING — 1/10 phiên** |
| Số gate tự nhận PASS | 1 | **0** |
| `exit_path_coverage` | PENDING (như thiếu mẫu) | **STRUCTURAL_GAP** (nói rõ không đo được) |
| `contract_spec_guard` | 4 mã, MNKD không được hỏi | **6/6 PASS**, MNKD → `MNKU6` |
| **Định tuyến MNKD** | **→ `NKD`, multiplier 5** | **→ `MNK`, multiplier 0.5** |
| Nguồn tiền phía Flex | `point_value` cục bộ (0/9 lot) | **Proceeds của sao kê (9/9 lot)** |
| `paper_minus_flex` | $0.00 (sai triệt tiêu hai vế) | **+$1,260.00**, khớp bút toán tới từng xu |
| Thẻ P&L trên Overview | không có | **`OBSERVED` — strategy −$43.25 / broker −$1,303.25** |
| Bảng tràn ngang ở 390px | 3 bảng cắt cột, không cuộn được | **0** (≈20 bảng có `overflow-x: auto`) |
| Auto-refresh | repaint mỗi 60s, phá chỗ đọc | **chỉ phát hiện; người đọc bấm chip mới repaint** |
| Test dashboard | 89 passed | **142 passed** |
| Test runner | 491 passed (baseline) | **495 passed** |

### Phát hiện phát sinh: lỗ hổng lọc log ở các reader khác

Chỉ `paper_evidence_reader.py` có lọc test marker. **5 reader khác cùng đọc `scheduler_*.log` / `live_day_*.log` thì không có:** `job_journal_reader`, `open_issue_reader`, `report_reader`, `schedule_status`, `session_event_reader`.

Đã đo trạng thái hiện tại, **chưa có reader nào đang xuất ra dữ liệu sai**: `/api/v1/open-issues` trả 1 issue duy nhất (`known_debt:model_age`, từ `hmm_stale_guard`, không phải mock); `/api/v1/session-events/2026-08-10` trả 18 event, **0 event dính dấu vết mock**.

Nên đây là **rủi ro tiềm ẩn chứ không phải lỗi đang hoạt động**. Nhưng nó xác nhận kết luận ở mục C1: nên chặn ở nguồn (tách log handler của test khỏi log production) thay vì nhân bản bộ lọc ra 6 reader.

---

## 1. Phát hiện, xếp theo mức độ

### CRITICAL

---

#### C1 — Log của một lần chạy test/mock đang được tính là bằng chứng paper thật

**File:** [monitor/backend/paper_evidence_reader.py:73-78](monitor/backend/paper_evidence_reader.py#L73-L78) (`_TEST_MARKERS`), [:748-767](monitor/backend/paper_evidence_reader.py#L748-L767)

**Vấn đề:** `scheduler_0810.log` mở đầu bằng 27 dòng cùng timestamp `2026-08-10 00:42:35`, có `_RecordingMockBroker`, `orderId=ibkr-456`, `cancel_order(stp-MES-0)`, `fetch_bars empty for MES on 2024-03-12`. Đây là output log của một lần chạy test bị ghi vào log scheduler production.

Bộ lọc hygiene lọc **theo từng dòng**, nên chỉ 6/27 dòng có chuỗi marker bị loại. 21 dòng còn lại được tính là bằng chứng thật. Số đo thực tế:

| Chỉ số | Đến từ block mock | Hiển thị trên UI |
|---|---|---|
| Dòng `place_stop FAILED` | **2 trên 2 (100%)** | Panel STP: "PLACEMENT FAILED **2**" màu đỏ |
| `B3: N mismatch(es)` | 2 | Gộp vào "100 mismatch(es)" |
| Candidate manual-intervention | 7 | Gộp vào "128 operator-action candidate line(s)" |

**Tại sao quan trọng:** Toàn bộ "failed stop placement" trên dashboard này là giả. Con số đỏ duy nhất về execution trong panel bảo vệ stop không có cơ sở production nào.

Lỗi đặt stop là failure mode hậu quả cao nhất đang được gate. Bằng chứng nhiễm bẩn theo *bất kỳ chiều nào* đều loại trừ độ tin cậy — hôm nay nó tạo ra báo động giả; ngày mai cùng bộ lọc theo dòng đó sẽ âm thầm loại bỏ một lỗi thật vì dòng kế bên trùng `(mock-`.

**Đề xuất sửa:** Lọc theo **khối chạy** (đoạn liên tục cùng timestamp có chứa bất kỳ marker nào), không lọc theo dòng. Đóng dấu `run_id` vào logger của runner và loại theo `run_id`. Thêm field `excluded_blocks` vào payload để việc loại trừ có thể audit được thay vì vô hình.

#### ✅ ĐÃ SỬA — và ô nhiễm lớn hơn báo cáo gốc rất nhiều

Đã triển khai lọc theo khối (`_retain_production_log_lines`, `_excluded_log_block`), có `excluded_blocks` audit được trong `payload.summary` và coverage `log_hygiene`.

**Phát hiện mới khi chạy bộ lọc thật:** báo cáo gốc chỉ bắt được **1 khối / 27 dòng**. Thực tế là **54 khối / 1160 dòng** — cùng một kịch bản mock MES được replay suốt ngày 2026-08-10 vào log scheduler production. Marker tìm thấy: `orderId=stp-` (611 dòng), `test_spy.csv` (172), `injected ` (122), `pytest-of-` (109), `_RecordingMockBroker` (50), `(stp-` (44), `stp-MES-` (22), `ibkr-456` (15), `_naked_broker` (9).

**Đây là vấn đề của runner/test setup, không chỉ của dashboard:** một bộ test đang ghi output vào `scheduler_0810.log` production. Nên tách handler log của test ra khỏi log production, thay vì chỉ lọc ở phía đọc.

**Kiểm chứng chống lọc-quá-tay (đã chạy):**

| Phép thử | Kết quả |
|---|---|
| Khối apscheduler 208 dòng `@08:25:13` (production hợp lệ, 0 marker) | ✅ Còn nguyên |
| Khối `@09:06:31`, `@09:24:37` | ✅ Còn nguyên |
| `live_day_*.log` (log production thật) | ✅ **0 khối bị loại** |
| Toàn bộ 54 khối bị loại | Đều nằm trong `scheduler_0810.log` |

**Tác động dây chuyền:** `stp_failed` 2 → **0** (cả hai dòng đều là mock), `manual_intervention` candidate 128 → **0**, TWS candidate 281 → 192.

#### Lỗi phụ đã vá cùng batch: marker Windows không bao giờ khớp

Marker `\Temp\tmp` chưa từng khớp dòng nào. Runner ghi thông điệp `OSError` qua `repr()`, nên đường dẫn tmpdir vào log với backslash nhân đôi:

```
marker định nghĩa : \Temp\tmp
log thật ghi      : 'C:\\Users\\quock\\AppData\\Local\\Temp\\tmpjs8qj72h\\...'
```

Chuỗi `\\Temp\\tmp` **không chứa** substring `\Temp\tmp`. Hậu quả: một khối mock 5 dòng lúc `02:28:21` sống sót và được đếm thành **một episode B3 thật**.

Đã sửa `_test_marker()` để so khớp thêm trên bản đã gộp backslash. Kèm 2 test: một test khẳng định khối tmpdir escape bị loại, một test khẳng định dòng production chỉ *nhắc tới* đường dẫn thì **không** bị loại nhầm (chặn over-collapse). Sau khi vá: B3 từ 2 episode → **1 episode / 2 vị thế**, hoàn toàn từ `live_day_0810.log`.

---

#### C2 — Gate PASS duy nhất trên bảng đạt PASS nhờ 1 dòng JSON tự khai, không có ngưỡng tối thiểu

**File:** [monitor/backend/paper_evidence_reader.py:949-978](monitor/backend/paper_evidence_reader.py#L949-L978)
**Dữ liệu:** `monitor/paper_inputs.json` → `stp_verification` (1 record, 2026-08-13)

**Vấn đề:** `_stp_input_status` trả về `PASS` ngay khi `paper_inputs.json` có ≥1 record với `verified/false_halt/double_stp` đúng. Không có `stp_verification_spec`, không có `min_checks`, không yêu cầu độ phủ phiên nào.

Mọi gate khác đều có ngưỡng rõ ràng trong cùng file đó:

| Gate | Ngưỡng |
|---|---|
| C1 slippage | `min_n: 100` |
| Fill quality | `min_fills: 100` |
| TWS restart | `min_nights: 10` |
| STP placement | `required_continuous_sessions: 10` |
| **STP verification** | **1** (không có spec) |

Và record đó do người vận hành tự viết (mô tả nguồn ghi rõ: "Updated manually or by monitoring-only tooling").

Chuỗi `requirement` của chính gate đó đã thừa nhận lỗ hổng: *"No false halt; false-halt classification is not defined in structured evidence."* Gate vẫn hiện PASS.

**Tại sao quan trọng:** Người review lướt tab Gates thấy đúng một chữ PASS xanh, nằm ở phần bảo vệ stop. Đó là tự khai trong một ngày duy nhất, được trình bày với trọng số thị giác ngang bằng một gate được đo thật.

**Đề xuất sửa:** Thêm `stp_verification_spec = {min_checks, min_distinct_sessions, max_age_days}` vào `paper_inputs.json` và enforce trong `_stp_input_status`. Khi chưa có spec, trả `SPEC_GAP` chứ không phải `PASS` — đúng pattern mà `_c1_status` đã dùng tại [:925-926](monitor/backend/paper_evidence_reader.py#L925-L926).

---

#### C3 — "Stop Protection Readiness" tổng hợp loại `current_protection` ra khỏi chính status của nó

**File:** [global_index/dash/paper/paper.js:480](global_index/dash/paper/paper.js#L480) · [:497](global_index/dash/paper/paper.js#L497) · [:511-514](global_index/dash/paper/paper.js#L511-L514)

```js
const status = compositeStatus(gate.status || 'UNKNOWN', [placement.status]);   // 2 đầu vào
...
panelVerdictMetric(status, `Verification ${gate.status}, placement ${placement.status},
                            current protection ${currentProtection?.status}.`,
                   'Composite status is the worst relevant stop-readiness status.')  // nêu tên 3
```

**Vấn đề:** Câu verdict nêu tên **ba** đầu vào. Phép tính dùng **hai**. `current_protection` — *"mọi vị thế mở hiện tại phải có `stop_order_id`"*, kiểm tra duy nhất phản ánh trạng thái **ngay bây giờ** — chỉ được render như một thẻ cross-reference, không hơn.

**Kịch bản hỏng:** Sổ lệnh live có một vị thế mở với `stop_order_id: null`. `current_protection` chuyển sang BREACH. `stp_verification` vẫn PASS (record cũ của operator), `stp_placement` vẫn PENDING. `compositeStatus('PASS', ['PENDING'])` → **PENDING**. Tiêu đề panel vẫn vàng, câu chữ ghi "…current protection BREACH" bị chôn trong thẻ `<small>` của một metric card.

**Một vị thế live không được bảo vệ KHÔNG làm panel stop chuyển đỏ.**

**Đề xuất sửa:** `compositeStatus(gate.status, [placement.status, currentProtection?.status])`. Thêm contract test cho payload, khẳng định fixture `current_protection: BREACH` phải cho composite = BREACH.

#### ✅ ĐÃ SỬA

`updateSTPPanel` giờ gọi `compositeStatus(gate.status || 'UNKNOWN', [placement.status, currentProtection?.status])`. Câu verdict và phép tính đã khớp nhau.

**Chưa kiểm chứng được trên trang thật:** không dựng được kịch bản `current_protection: BREACH` từ dữ liệu hiện có (sổ lệnh đang có 1 vị thế PROTECTED). Đây là chỗ **cần một test hành vi với fixture** thay vì tin vào việc đọc code — vẫn còn nợ.

---

#### C4 — Gate B3 không thể quan sát được thứ nó gate, và con số headline là tổng heartbeat

**File:** [monitor/backend/paper_evidence_reader.py:27](monitor/backend/paper_evidence_reader.py#L27) · [:772-774](monitor/backend/paper_evidence_reader.py#L772-L774)

Hai lỗi độc lập trong cùng một gate:

**(a) `cold_starts` bằng 0 về mặt cấu trúc.**
`_COLD_START = re.compile(r"Runner started: loaded")` khớp **0 dòng trong mọi log của repo**. Chữ ký cold-start thật là `run_scheduler — Scheduler started. Ctrl-C to stop.`, xuất hiện 3 lần chỉ riêng ngày 2026-08-10 và mỗi ngày sau đó.

Gate tên *"B3 cold-start reconcile"*, requirement *"0 mismatches on every cold start"*, báo `cold_starts: 0` — nó **chưa bao giờ đánh giá được requirement của chính nó**, mà vẫn báo BREACH.

**(b) "100 mismatch(es)" không phải 100 mismatch.**
Reader cộng dồn capture `count` trên mọi dòng khớp. Trong epoch có **83 dòng, cộng lại thành 100**, tất cả nằm giữa `00:05:22` và `09:18:43` ngày 2026-08-10 — cùng một trạng thái lệch 2 vị thế, được ghi lại mỗi 5 phút theo decision slot:

```
live_day_0810.log:942   00:05:22  B3: 2 mismatch(es) — new entries HALTED until resolved.
live_day_0810.log:1855  00:10:21  B3: 2 mismatch(es) — new entries HALTED until resolved.
live_day_0810.log:2768  00:15:36  B3: 2 mismatch(es) — ...
```

`matches: 164` cũng là cùng loại artifact (45/ngày trong 08-11…08-13). UI hiện "match 164 | mismatch 100" — đọc ra như tỉ lệ reconcile pass 62% trên 264 lần thử.

**Sự thật là:** một sự cố, 2 vị thế, ~9 giờ, vào ngày đầu tiên của epoch, rồi sạch từ đó đến nay.

**Tại sao quan trọng:** Đây chính là thứ đẩy `overallStatus = BREACH` cấp trang. Người review không thể phân biệt hệ thống có vấn đề reconcile kinh niên (100 sự kiện) hay một sự cố state cũ trong ngày đầu (1 episode). Hai điều đó dẫn tới hai quyết định go-live hoàn toàn khác nhau.

**Đề xuất sửa:**
- (a) Sửa/tổng quát hóa `_COLD_START` theo chữ ký thật, tính lại gate theo ranh giới restart thực.
- (b) Gộp các dòng mismatch lặp lại thành episode: xuất `{episodes, positions_affected, first_seen, last_seen, resolved_at}`, hiển thị "1 episode / 2 vị thế / 9h / đã xử lý" thay vì đếm heartbeat.

#### ✅ ĐÃ SỬA cả (a) và (b)

**(a)** `_COLD_START` đổi sang `r"Scheduler started\. Ctrl-C to stop\."`, kèm dedupe theo `(file, timestamp tới giây)` để `run_scheduler` và `apscheduler` cùng ghi trong một giây không bị đếm hai lần.

Kiểm chứng: 16 dòng thô `"Scheduler started"` trong epoch → đúng **8 mốc giây riêng biệt** → `cold_starts = 8`. Lần đầu tiên gate này đo được thứ nó gate.

**(b)** Mismatch/match gộp thành episode với khoảng nghỉ `_B3_EPISODE_GAP = 30 phút`. Số heartbeat thô giữ lại dưới `raw_*` để đối chiếu.

Kết quả sau khi vá cả marker escaping:

```
B3 evidence: 16 match episode(s), 1 mismatch episode(s), 2 mismatch position(s) affected;
             raw mismatch heartbeat 22 across 11 line(s)
episode: 2026-08-10T06:05:22Z -> 2026-08-10T06:55:22Z | 2 vị thế | 11 dòng | live_day_0810.log
```

Từ *"100 mismatch"* thành **một sự cố, 2 vị thế, 50 phút, ngày đầu epoch, từ log production thật**. Đây mới là mức thông tin ra quyết định được.

#### Điều tra episode còn lại — và nó nối thẳng vào H7

Sau khi số liệu sạch, đã truy được nguyên nhân episode B3 duy nhất còn lại. Diễn biến thật trong `live_day_0810.log`:

```
00:00:17  B1: loaded 1 persisted position(s)          <- sạch
00:05:18  B1: loaded 2 persisted position(s)          <- xuất hiện vị thế thứ hai
00:05:22  B3 MISMATCH: file has LONG MNKD ×1 but IBKR shows ×0
00:05:22  B3 ORPHAN:   IBKR has LONG NKD  ×1 with no matching file entry
00:05:22  B3: 2 mismatch(es) — new entries HALTED
   ... lặp mỗi 5 phút ...
00:55:22  (lần cuối)
12:05:16  B1: loaded 1 persisted position(s)
12:05:20  B3: broker/file positions match (1 position(s))   <- tự hết
```

**Đây không phải hai lỗi, mà là một lỗi nhận dạng hợp đồng.** MISMATCH và ORPHAN là hai nửa của cùng một chênh lệch: file ghi **MNKD**, broker báo **NKD**. Số vị thế đi 1 → 2 → 1.

> **ĐÍNH CHÍNH (chủ dự án chỉ ra, code xác nhận).** Bản đầu của đoạn này kết luận rằng file ghi MNKD còn broker báo NKD là **hai hợp đồng khác nhau chênh 10 lần**, và gọi đó là "sai kích thước vị thế 10 lần". **SAI.** `MNKD` và `NKD` là **cùng một hợp đồng**: `ibkr_broker._RAITS_TO_IBKR = {'MNKD': 'NKD'}` — hệ thống gọi nội bộ là MNKD, IBKR gọi là NKD, cùng sàn, cùng tháng đáo hạn.

**Nguyên nhân thật: B3 không chuẩn hoá ký hiệu khi đối chiếu.**

```
B3 MISMATCH: file has LONG MNKD ×1 but IBKR shows ×0     ← tên nội bộ
B3 ORPHAN:   IBKR has LONG NKD  ×1 with no matching file entry   ← tên IBKR
```

Đây là **một vị thế duy nhất bị đếm hai lần dưới hai tên**. Runner có 1 vị thế, IBKR có 1 vị thế, khớp nhau hoàn toàn — B3 chỉ không áp `_RAITS_TO_IBKR` lúc so sánh. Vì thế nó vừa báo "thiếu ở broker" vừa báo "thừa ở broker" cho cùng một thứ, và cộng thành 2 mismatch.

**Điều này giải thích luôn vì sao nó "tự hết":** không có gì được sửa cả. Vị thế chưa bao giờ lệch. Sự cố biến mất khi vị thế MNKD đóng lại lúc 12:10 (khớp với bản ghi CLOSE trong `trade_log`), nên B3 không còn gì để so sai nữa.

**Sửa đúng chỗ:** áp `_RAITS_TO_IBKR` trong bước reconcile của B3. Đây là **lỗi runner**, không phải lỗi contract-spec, và không phải lỗi dashboard.

**Hệ quả cho khuyến nghị trước đó:** đề xuất "lấy IBKR ContractDetails cho NKD/MNKD để đóng nguyên nhân gốc B3" là **sai hướng** — ContractDetails không sửa được lỗi này.

#### Câu hỏi mở, cần chủ dự án trả lời: point_value của MNKD

Việc MNKD và NKD là cùng hợp đồng lại làm lộ một câu hỏi khác, mà `contract_spec_guard` sinh ra chính là để trả lời:

| Bản ghi trong `SPECS` | point_value | tick | tick_value |
|---|---:|---:|---:|
| `NKD` | 5.0 | 5.0 | $25.00 |
| `MNKD` | **0.5** | 5.0 | **$2.50** |

Hai bản ghi cho **cùng một hợp đồng IBKR** nhưng chênh nhau 10 lần. Hệ thống đang giao dịch dưới tên `MNKD`, tức dùng `point_value = 0.5`. Kiểm chứng trên `trade_log`: MNKD vào 66985, ra 66765 = 220 điểm; `pnl_sized = -110.0` = 220 × 0.5 × 1 ✓.

Nếu hợp đồng NKD thật ở IBKR có multiplier $5, thì P&L và risk sizing của rổ NKD đang bị ghi nhận **bằng 1/10 giá trị thật**. Nếu $0.5 mới đúng, thì bản ghi `NKD` trong `SPECS` là thứ sai.

**Đã hỏi IBKR trực tiếp — xem C8 ngay dưới. Câu trả lời là multiplier thật bằng 5.**

---

#### C8 — MNKD được ghi sổ bằng 1/10 giá trị thật; phép đối chiếu Flex không phát hiện được vì nó vòng tròn *(2026-08-14)*

**Mức độ: cao nhất trong toàn bộ audit này.** Đây là sai lệch tiền thật, trên hệ thống paper đang chạy, và cơ chế lẽ ra phải bắt được nó thì không thể bắt.

**Chuỗi bằng chứng, từng bước đã kiểm chứng:**

1. **Hỏi thẳng IBKR** (`reqContractDetails`, chỉ đọc, clientId 98):
   ```
   symbol=NKD  localSymbol=NKDU6  conId=652545722
   multiplier=5   minTick=5.0   exchange=CME
   desc="Dollar Denominated Nikkei 225 Index"
   ```
2. **`ibkr_broker._RAITS_TO_IBKR = {'MNKD': 'NKD'}`** — lệnh và truy vấn cho MNKD đi tới đúng hợp đồng đó.
3. **`SPECS` local:** `MNKD.point_value = 0.5`, `NKD.point_value = 5.0` — hai bản ghi cho cùng một hợp đồng, chênh 10 lần.
4. **Sao kê Flex tự xác nhận multiplier 5**, độc lập với ContractDetails:
   ```
   qty=1  price=66985  proceeds=334925   ->  334925 / (1 × 66985) = 5.0
   cot "Multiplier" ghi thang: 5
   ```
5. **`trade_log` ghi `pnl_sized = -110.0`** cho vòng 66985 → 66765 (220 điểm × 0.5 × 1).
6. **Thực tế bên broker:** 220 × **5** × 1 = **−$1,100**.

**Hệ quả 1 — sổ vốn của runner cũng sai theo.** `_book_realised` (`runner.py:879-888`) dùng chính `point_value(pos.inst)`:
```python
pv = point_value(pos.inst)                     # MNKD -> 0.5
pnl = (exit_price - entry_price) * pv * n * (±1)
self.state.equity += pnl
```
Nên **equity hệ thống, ngưỡng breaker và mức drawdown của rổ NKD đều đang tính trên 1/10 P&L thật.** Đây là vấn đề vận hành sống, không chỉ là báo cáo.

**Hệ quả 2 — phép đối chiếu Flex là vòng tròn.** `monitor/paper_pnl_compare.py` dựng lại P&L Flex bằng `point_value()` (L219, L247, L1266) và **không hề đọc cột `Proceeds` của sao kê** (đã grep: không có tham chiếu `proceeds`/`FifoPnlRealized` nào).

Nên hai vế của phép so sánh dùng **cùng một multiplier sai**:

```
paper_epoch_closed_realized          = -43.25
flex_epoch_rebased_realized          = -43.25
paper_minus_flex_epoch_rebased       =   0.00   ->  "RECONCILED"
```

Con số 0.00 đó **không chứng minh điều gì cả**. Nó không thể lệch, dù multiplier sai bao nhiêu đi nữa. Đây chính là lỗi cùng loại H8 (so sánh một giá trị với chính nó), nhưng nằm ở tuyên bố mạnh nhất của cả dashboard: *"paper khớp broker tuyệt đối"*.

**KẾT LUẬN: là khả năng B — lệnh bị định tuyến sang hợp đồng gấp 10 lần dự định.** Chuỗi xác nhận đã khép kín:

**1. Hợp đồng Micro có thật, ticker IBKR là `MNK`** (hỏi trực tiếp, chỉ đọc):

| | ticker IBKR | multiplier | minTick |
|---|---|---:|---:|
| Full-size | `NKD` → `NKDU6` | **5** | 5.0 |
| **Micro** | **`MNK`** → `MNKU6`, conId 863279730 | **0.5** | 5.0 |
| `SPECS['MNKD']` local | — | **0.5** | 5.0 |

`SPECS['MNKD']` **khớp chính xác hợp đồng Micro thật**. Nó không sai.

**2. Backtest chạy trên hợp đồng Micro** — `deploy_sim.py:126`:
```python
ap.add_argument("--nkd-instrument", default="MNKD", choices=list(gi_specs.SPECS.keys()))
```
→ `SPECS['MNKD']` → `point_value = 0.5`, `commission_rt = 1.40`, `est_margin = 900`.

**3. Xác nhận thực nghiệm từ chính số liệu backtest.** Lấy một lệnh thắng trong `replay_snapshots_data.js` (SHORT 20875 → 20365 = 510 điểm):
```
510 × 0.5 − (2 tick/phía × 2 phía × $2.50 + $1.40) = 255.00 − 11.40 = $243.60
backtest ghi:                                                        $243.60   ✓ khớp từng xu
```
Với `pv = 5` thì gross là $2,550 — muốn ra 243.60 phải có chi phí $2,306, vô lý. **Chỉ `pv = 0.5` khớp được.**

Dấu hiệu phụ củng cố: các lệnh **thua** cho multiplier suy ra > 0.5 (chi phí làm lỗ nặng thêm), lệnh **thắng** cho < 0.5 (chi phí ăn bớt lãi) — đúng dạng của một multiplier 0.5 cộng chi phí cố định.

**4. Lỗi nằm gọn ở một dòng** — `global_index/ibkr_broker.py`:
```python
_RAITS_TO_IBKR = {'MNKD': 'NKD'}   # ← trỏ sang FULL-SIZE, phải là 'MNK'
```
Ghi chú trong `specs.py:38` — *"CME Micro Nikkei USD **(confirm ticker w/ IBKR)**. DEPLOY"* — cho thấy việc xác nhận ticker chưa bao giờ được làm; ai đó điền tạm ticker full-size.

**Tác động thật:**
- Mọi lệnh MNKD từ khi triển khai đều khớp **hợp đồng full-size, gấp 10 lần kích thước đã kiểm định**.
- `net_exposure_multi.py:66` — `risk_dollars = contracts × stop_dist_points × point_value` — tính bằng 0.5, nên **rủi ro tiền thật gấp 10 lần dự định**.
- Ký quỹ: giả định $900, thực tế ~$9,000.
- Backtest và WFO **vẫn hợp lệ** — chúng chạy đúng hợp đồng Micro. `data_symbol="NKD"` là cố ý và đúng: micro và full dùng chung chuỗi giá.

#### Thiệt hại thật, đo từ sao kê broker

Dòng `EXECUTION` trong Flex, khớp với `SYMBOL_SUMMARY`:

| Ngày | qty | giá | FifoPnlRealized |
|---|---:|---:|---:|
| 2026-08-10 | +1 | 66.985 | −1.150,00 |
| 2026-08-10 | −1 | 66.765 | +50,00 |
| 2026-08-11 | −1 | 67.030 | −350,00 |
| 2026-08-11 | +1 | 67.090 | +50,00 |
| | | **broker** | **−1.400,00** |
| | | **hệ thống ghi** | **−140,00** |
| | | **tỷ lệ** | **10,0000** |

Giá vào/ra trong `trade_log` khớp chính xác sao kê. Lệnh **không bị từ chối, không sai giá, không sai chiều** — chỉ multiplier sai.

#### Phạm vi thiệt hại hẹp hơn thoạt nhìn — bản nháp đầu đã kết luận quá tay

> Bản nháp đầu đề xuất **"bỏ epoch paper hiện tại, bắt đầu epoch mới"**. Chủ dự án chỉ ra rằng sau khi sửa định tuyến thì sổ sách tự khớp. **Đúng, và còn hơn thế.**

`SPECS['MNKD'].point_value = 0.5` khớp chính xác multiplier của MNK. Nên sau khi đổi định tuyến, `_book_realised` và broker cùng tính bằng 0.5 — **khớp, không cần sửa thêm gì**.

Quan trọng hơn: **con số `−$140` đã ghi chính là số mà hệ thống cấu hình đúng sẽ tạo ra** với đúng những tín hiệu đó, đúng những mức giá đó, trên hợp đồng Micro. Nó là con số đúng của chiến lược. Docstring `_book_realised` xác nhận chủ ý: sổ sleeve cố tình theo quy ước backtest (`equity += pnl_sized`), không phải sổ tiền mặt broker.

Củng cố: **tick của NKD và MNK đều là 5.0** (cả `SPECS` lẫn IBKR). Nên slippage tính bằng tick — toàn bộ bằng chứng C1 — **so sánh được trực tiếp**, không bị méo bởi lỗi định tuyến.

**Bằng chứng epoch này phần lớn dùng được:** thời điểm tín hiệu, giá, chiều, P&L chiến lược, slippage theo tick đều đúng. Hai cảnh báo nhỏ khi diễn giải:
- Chất lượng khớp lệnh thu được trên hợp đồng thanh khoản hơn (NKD volume ≈ 1,75× MNK), nên slippage thật trên MNK có thể xấu hơn chút.
- Ký quỹ thật đã gấp 10 lần giả định ($9.000 thay vì $900) — không gây sự cố, nhưng epoch này chưa kiểm chứng hành vi khi ký quỹ sát hạn mức.

**Cái không tự khỏi:** tài khoản paper ở broker thật sự thấp hơn **$1.260** so với những gì sổ sleeve hàm ý. Đó là chi phí của lỗi định tuyến, không phải kết quả chiến lược. Nó sẽ lộ ra ngay khi bỏ tính vòng tròn của Flex check (`paper − flex` nhảy từ `0,00` thành `−1.260`), nên cần **một bút toán đối soát một lần** ghi rõ nguyên nhân — giống cách hệ thống đã làm với `MATCH_PRE_EPOCH_CARRY_FILL`.

**Ba việc, theo thứ tự:**
1. **Đổi `_RAITS_TO_IBKR = {'MNKD': 'MNK'}` VÀ thêm `ROLL_SCHEDULE['MNK']`** — cần chủ dự án duyệt vì đây là định tuyến lệnh. Chi tiết ở mục dưới.
2. Ghi bút toán đối soát một lần cho $1.260.
3. Sửa `paper_pnl_compare` đối chiếu bằng **`Proceeds`/`FifoPnlRealized` của sao kê** thay vì `point_value` local, và `ibkr_reader.py:197` hỏi IBKR cả `SPECS`. Nếu hai thứ này đã có từ đầu, `contract_spec_guard` đã bắt được lệch này từ ngày đầu tiên.

**Không cần rebase lịch sử, không cần epoch mới.**

#### Đổi định tuyến cụ thể là đổi gì — MỘT DÒNG LÀ KHÔNG ĐỦ

```
ROLL_SCHEDULE keys: ['MES','MNQ','MYM','M2K','NKD']   ← khong co MNK
_current_front_month('MNK') = None
```

Cả ba call site (`ibkr_broker.py:413` lấy bar, `:522` **đặt lệnh**, `:866` tra giá) đều rơi vào nhánh không định danh tháng khi `front_month` là `None`. Comment tại `:409` cảnh báo đúng tình huống đó: *"avoid 'Ambiguous contract' error"*. IBKR trả về **hai** hợp đồng MNK (`MNKU6`, `MNKZ6`) → không định danh thì lỗi ngay lần gọi đầu.

Nên phải thêm `ROLL_SCHEDULE['MNK']` cùng lịch với NKD (cùng underlying, cùng chu kỳ quý). **Roll kế tiếp: 2026-09-04.**

`_IBKR_TO_RAITS` tự suy ra ✓. `_IBKR_EXCHANGE` không cần đổi (MNK ở CME, đúng mặc định) ✓.

**Đã kiểm chỉ-đọc trên IBKR:**

| | bar 1-phút/2 ngày | volume 2 ngày | định danh tháng |
|---|---:|---:|---|
| NKD | 2.472 | 4.819 | 1 khớp ✓ |
| MNK | 2.473 | 2.746 | 1 khớp ✓ |

Giá bám sát nhau (68.565 vs 68.560) → cùng underlying. Với 1 hợp đồng thì thanh khoản MNK không phải vấn đề.

#### Mốc baseline test runner (trước khi đổi định tuyến)

```
python -m pytest global_index/ -q --ignore=global_index/test_ibkr_injection.py
-> 1 failed, 491 passed in 1827.42s (30m27s)
```

**Lỗi có sẵn, không do phiên làm việc này:** `test_runner_event_log.py::test_incomplete_tail_is_not_extended` — runner từ chối ghi tiếp vào event log hỏng (assert đầu PASS) nhưng **không set `_event_log_disabled = True`**, nên nó sẽ thử lại mỗi lần thay vì tắt hẳn một lần. `git diff` xác nhận `runner.py`, `ibkr_broker.py`, `specs.py` chưa bị đụng đến.

`test_ibkr_injection.py` phải loại trừ: nó là script, gọi `sys.exit()` lúc import và làm pytest INTERNALERROR.

**Đây là mốc so sánh cho bước "verify sau khi sửa": phải giữ nguyên 491 passed và đúng 1 lỗi đã biết đó.**

---

## PHỤ LỤC A — Thay đổi định tuyến lệnh MNKD (2026-08-14)

### A.1 Đã đổi gì

**File `global_index/ibkr_broker.py`, hai chỗ:**

```python
# 1. Bảng ánh xạ ký hiệu
_RAITS_TO_IBKR = {"MNKD": "NKD"}   →   {"MNKD": "MNK"}

# 2. Lịch roll — BẮT BUỘC, thiếu là hỏng ngay lần gọi đầu
ROLL_SCHEDULE["MNK"] = [
    ("2026-03-06", "202603", "202606"), ("2026-06-05", "202606", "202609"),
    ("2026-09-04", "202609", "202612"), ("2026-12-04", "202612", "202703"),
]
```

Vì sao chỗ thứ hai bắt buộc: cả ba call site (`:413` lấy bar, `:522` **đặt lệnh**, `:866` tra giá) gọi `_current_front_month(ibkr_sym)`. Không có mục `MNK` thì nó trả `None`, code rơi xuống nhánh `ibi.Future("MNK", exchange=...)` không định danh tháng, và IBKR từ chối vì `MNKU6` lẫn `MNKZ6` đều đang sống. Lỗi sẽ nổ ở **lần lấy bar hoặc lần đặt lệnh đầu tiên**, không phải lúc import.

**Quyết định về chiều ngược — `NKD` không còn ánh xạ về `MNKD`.** `_IBKR_TO_RAITS` suy ra từ bảng trên nên giờ chỉ dịch `MNK`. Một vị thế NKD sót lại sẽ hiện dưới tên của chính nó và bị coi là **orphan**. Đây là chủ ý: NKD lớn gấp 10 lần bất cứ thứ gì hệ thống này định cỡ, và nhận nó về làm MNKD sẽ khiến B4 đặt một stop tính cho hợp đồng micro lên gấp 10 lần exposure. Một orphan làm dừng vào lệnh là cảnh báo đúng.

### A.2 KHÔNG đổi gì — và vì sao

Đường **dữ liệu lịch sử** giữ nguyên `NKD`: `update_futures_data.py:71`, `update_ibkr_daily.py:146`, `repair_parquet_utc.py:52`, `fix_offset_step.py:79`, và `specs.py` (`data_symbol="NKD"`). Micro và full theo cùng một chỉ số, và chuỗi full-size là chuỗi dài hơn. **Chỉ định tuyến lệnh từng sai.**

Đã rà toàn bộ chuỗi `"NKD"` trong code không phải test để xác nhận không sót chỗ nào trên đường đặt lệnh. `monitor/backend/execution_quality_reader.py:14` chứa `{"NKD": 5.0, "MNKD": 5.0}` — đó là **tick size**, đúng cho cả hai (IBKR xác nhận `minTick 5.0`), không phải point value.

### A.3 Test đã cập nhật

`global_index/test_symbol_boundary.py` — file này tồn tại *chính vì* ranh giới MNKD/NKD:

| Test | Thay đổi |
|---|---|
| `test_sb1` | `_to_runner("NKD")` → `_to_runner("MNK") == "MNKD"` |
| `test_sb3` | vị thế giả lập `_Pos("NKD")` → `_Pos("MNK")` |
| **`test_sb4`** (mới) | khẳng định `_to_runner("NKD") == "NKD"` — full-size **không** được nhận về làm của mình |
| **`test_sb5`** (mới) | mọi ký hiệu trong `_RAITS_TO_IBKR` phải có mục `ROLL_SCHEDULE` và giải được front month |

`test_sb5` là bài học rút ra: lỗi thiếu `ROLL_SCHEDULE` sẽ không lộ ra lúc import mà đợi tới lần đặt lệnh đầu tiên. Giờ nó bị chặn ở tầng test.

### A.4 Verify trước/sau — baseline đã làm đúng việc của nó

| Lần chạy | Kết quả |
|---|---|
| **Baseline** (trước khi đổi) | `1 failed, 491 passed` — lỗi có sẵn `test_runner_event_log` |
| **Verify vòng 1** (sau khi đổi) | `4 failed, 490 passed` — **3 lỗi mới** |
| **Verify vòng 2** (sau khi sửa fixture) | `1 failed, 495 passed` — **đạt** |

Vòng 2 khớp ngưỡng chính xác: **cùng đúng một lỗi có sẵn** (`test_runner_event_log`, nội dung lỗi giống hệt baseline), và `491 → 495` đúng bằng **+4 test tôi thêm** (`test_sb4`, `test_sb5`, `test_a_stray_full_size_nkd_still_surfaces_under_its_own_name`, `test_ws4b_a_full_size_nkd_stop_does_not_count_as_micro_protection`). Không có hồi quy nào.

Nhờ có baseline mới tách bạch được ngay: lỗi `test_runner_event_log` là có sẵn, ba lỗi kia do thay đổi. Không có mốc này thì cả bốn sẽ trông như nhau.

**Ba lỗi mới — đều là fixture, không phải hồi quy:**

| Test | Vấn đề |
|---|---|
| `test_stp_accept::test_ws1_nkd_stop_is_keyed_by_runner_name` | fixture dựng `_StopTrade("NKD", …)` |
| `test_stp_accept::test_ws4_has_working_stop_also_speaks_runner_names` | như trên |
| `test_unprotected_positions::test_nkd_is_reported_under_its_runner_name` | fixture dựng `_Pos("NKD", …)` |

Cả ba mã hoá **cùng một bất biến**: thứ IBKR báo về phải trả ra dưới tên runner `MNKD`. Bất biến đó không đổi — chỉ ký hiệu trong fixture phải chuyển từ `NKD` sang `MNK`, vì đó là thứ IBKR gọi hợp đồng của ta bây giờ. Cùng loại với `test_sb1`/`test_sb3`; tôi đã sửa hai cái đó nhưng chưa tìm ra hai file này.

**Đã thêm hai test cho chiều ngược lại** — đây mới là phần có giá trị, vì nó khoá lại quyết định ở §A.1:

| Test mới | Khẳng định |
|---|---|
| `test_unprotected_positions::test_a_stray_full_size_nkd_still_surfaces_under_its_own_name` | vị thế NKD sót lại **vẫn được báo cáo** khi thiếu stop, nhưng dưới tên `NKD` — không bị bỏ qua, cũng không bị nhận về làm micro |
| `test_stp_accept::test_ws4b_a_full_size_nkd_stop_does_not_count_as_micro_protection` | stop nằm trên hợp đồng full-size **không** được tính là bảo vệ cho `MNKD` |

Cái thứ hai đáng chú ý: nếu thiếu nó, một stop trên NKD sẽ khiến B4 tưởng vị thế micro đã được che và bỏ qua việc đặt stop thật.

61 test trong ba file liên quan: **pass toàn bộ**.

Kết quả: `5 passed`. Xác minh trạng thái sau khi đổi:
```
_RAITS_TO_IBKR  : {'MNKD': 'MNK'}
_IBKR_TO_RAITS  : {'MNK': 'MNKD'}
front month MNK : 202609
_to_runner(MNK) : MNKD
_to_runner(NKD) : NKD      <- orphan, đúng chủ ý
```

---

## PHỤ LỤC B — Phép đối chiếu Flex không dùng Proceeds

### B.1 Cơ chế

`monitor/paper_pnl_compare.py:1256-1272` dựng lại các lot đã đóng của Flex như sau:

```python
from global_index.statement import point_value
pv  = point_value(str(inst))                    # ← multiplier LOCAL
pnl = (fill["price"] - o["price"]) * pv * qty * (1 if long_side else -1)
```

Nó lấy **giá, số lượng, ngày và cách ghép lot** từ sao kê broker — tất cả đều là sự thật của broker. Nhưng **số tiền thì tự tính bằng `point_value` local**. Đã grep toàn file: không có tham chiếu nào tới `Proceeds` hay `FifoPnlRealized`.

### B.2 Vì sao điều đó vô hiệu hoá chính phép kiểm

Sổ paper cũng dùng `point_value` (qua `_book_realised`). Nên **hai vế của phép so sánh dùng cùng một multiplier**. Nếu multiplier sai, nó sai ở cả hai vế và triệt tiêu:

```
paper_epoch_closed_realized    = -43.25
flex_epoch_rebased_realized    = -43.25
paper_minus_flex               =   0.00   ->  "RECONCILED"
```

Con số `0.00` đó **không thể lệch**, dù multiplier sai bao nhiêu lần. Đây chính là lỗi cùng loại H8 (so sánh một giá trị với chính nó), nhưng nằm ở tuyên bố mạnh nhất của dashboard: *"paper khớp broker tuyệt đối"*.

**Bằng chứng cụ thể:** lỗi định tuyến làm sai đúng 10 lần trên toàn bộ rổ NKD suốt epoch, và phép kiểm này báo `0.00` từ đầu đến cuối.

### B.3 Đã làm gì

Chưa sửa `paper_pnl_compare` (thay đổi lớn, chưa được duyệt). Nhưng đã **ghi rõ cơ sở đối chiếu vào payload** để người review không hiểu nhầm `0.00` là bằng chứng:

`paper_vs_backtest.metrics.flex_reconcile_basis` nay nêu thẳng rằng giá/số lượng/ghép lot đến từ broker còn tiền thì không, nên sai multiplier sẽ triệt tiêu ở cả hai vế.

**Việc còn lại:** chuyển phép đối chiếu sang `Proceeds`/`FifoPnlRealized` của sao kê. Không có bước này, phép kiểm Flex vĩnh viễn mù với đúng loại lỗi vừa xảy ra.

---

## PHỤ LỤC C — Bút toán đối soát

### C.1 Số liệu, lấy từ sao kê broker

Bốn dòng `EXECUTION` của `NKDU6` trong `flex_20260813T103831Z_q1603041_ref6822861365.csv`:

| Ngày | qty | giá | FifoPnlRealized | commission |
|---|---:|---:|---:|---:|
| 2026-08-10 | +1 | 66.985 | −1.150,00 | −3,01 |
| 2026-08-10 | −1 | 66.765 | +50,00 | −3,01 |
| 2026-08-11 | −1 | 67.030 | −350,00 | −3,01 |
| 2026-08-11 | +1 | 67.090 | +50,00 | −3,01 |
| | | **gross** | **−1.400,00** | **−12,04** |

| | |
|---|---:|
| Broker gross (FifoPnlRealized) | **−1.400,00** |
| Sổ sleeve ghi (`pnl_sized`) | **−140,00** |
| **Chênh lệch** | **−1.260,00** |
| Tỷ lệ | **10,0000** |

So sánh gross-với-gross vì `_book_realised` không trừ phí; hoa hồng broker −12,04 ghi riêng.

### C.2 Ghi ở đâu

`monitor/paper_inputs.json` → khoá mới `ledger_adjustments`, cùng chỗ với các dữ liệu operator đã duyệt khác. Bản ghi `mnkd_routing_2026_08_14` gồm: bốn fill bị ảnh hưởng, số liệu broker và sleeve, nguyên nhân gốc, bằng chứng, cách sửa, phạm vi ảnh hưởng, và ghi chú đối soát.

**Đã nối vào reader** (`_paper_vs_backtest_status`) để nó hiện trên dashboard:
```
paper_vs_backtest.metrics.ledger_adjustments        -> [1 ban ghi]
paper_vs_backtest.metrics.ledger_adjustment_total   -> -1260.0
```

Bút toán mà không có gì đọc thì chỉ là ghi chú. Nối vào payload để khi phép kiểm Flex được sửa theo Phụ lục B, khoản `−1.260` có chỗ quy về thay vì hiện ra như một sai lệch mới không giải thích được.

### C.3 Phạm vi — cái gì còn dùng được

**Còn dùng được:** thời điểm tín hiệu, chiều, giá vào/ra (khớp sao kê từng xu), P&L chiến lược (−140 chính là số hệ thống cấu hình đúng sẽ tạo ra), và slippage theo tick (tick 5.0 giống nhau ở cả hai hợp đồng).

**Không dùng được:** hành vi ký quỹ (thật ~$9.000 so với giả định $900) và chất lượng khớp lệnh (thu trên hợp đồng thanh khoản gấp ~1,75 lần).

**Không cần rebase lịch sử, không cần epoch mới.**

**Điểm đáng lo nhất:** giữa 00:55 và 12:05 **không có dòng log nào ghi nhận hành động của người vận hành** — chênh lệch tự biến mất. Panel manual_intervention cũng đã về 0 candidate. Tức là không ai biết vì sao nó hết, nên không có cơ sở nào nói nó sẽ không tái diễn.

#### Phát hiện phụ: `cold_starts = 8` vẫn đếm sai ranh giới

`_COLD_START` giờ bắt dòng `Scheduler started` → 8 mốc. Nhưng **B3 chạy lúc runner khởi động**, chữ ký là `B1: loaded N persisted position(s)` — trong epoch có **176 mốc**, không phải 8.

Nên mẫu số đúng cho requirement *"0 mismatches on every cold start"* là 176, và kết quả thật là:

> **12/176 lần reconcile lúc runner start bị lệch (6.8%)**, tất cả gói trong một cửa sổ 50 phút ngày đầu epoch, nguyên nhân là nhầm danh tính NKD/MNKD, tự hết lúc 12:05, sạch suốt 4 ngày sau.

Gate đi từ 0 (bộ dò chết) lên 8 (đúng hướng nhưng sai ranh giới). Vẫn cần sửa nốt để đếm theo runner start.

#### Kết luận: có nên giữ BREACH không?

**Có — nhưng vì lý do khác và cụ thể hơn hẳn lý do dashboard đang đưa ra.** Không phải vì "100 dòng mismatch chưa phân loại", mà vì:

1. Nguyên nhân gốc **vẫn chưa được xác minh** — `contract_spec_guard` hiện báo cả NKD và MNKD là MISSING.
2. Kiểu lỗi là **sai kích thước 10 lần**, không phải sai lệch nhỏ.
3. Nó **tự hết mà không có hành động nào được ghi nhận**, nên không có bằng chứng nào nói nó đã được xử lý.

**Hành động có giá trị cao nhất:** lấy IBKR ContractDetails cho NKD và MNKD để `contract_spec_guard` chuyển từ MISSING sang PASS. Việc này không chỉ làm xanh một panel — nó đóng lại đúng nguyên nhân gốc của breach B3 duy nhất có thật trong epoch.

---

#### C5 — Gate exit_path_coverage đếm một trường mà runner không bao giờ ghi *(phát hiện thêm 2026-08-14)*

**File:** `global_index/runner.py:926-942` và `:1482-1496`

Overview hiện **"exits 0/3"** kèm hướng dẫn *"collect at least three samples per exit path"*. Người review đọc ra là *"chưa đủ mẫu, chờ thêm"*. Sự thật là **không xác định được lần thoát nào thuộc loại gì**, và chờ bao lâu cũng không đổi.

Runner có **hai đường ghi bản ghi CLOSE**:

| Đường | Vị trí | Ghi `exit_reason`? |
|---|---|---|
| Thoát do stop (B3 STP exit) | `runner.py:934` | ✅ `"exit_reason": "STP"` |
| Thoát theo tín hiệu / quyết định (đường chính) | `runner.py:1482-1496` | ❌ **không có trường này** |

Đo trên `trade_log.jsonl`:

```
CLOSE trong epoch : 4/4 KHÔNG có exit_reason
Schema thực tế    : 15 khoá, không khoá nào là exit_reason
CLOSE có exit_reason trong toàn bộ log: chỉ 3 bản, cả 3 đều do backfill
    ghi ngược (backfill:observed_, backfill:reqExecutions,
    backfill:activity_statement) — không phải đường live
```

**Hệ quả:** `CHANDELIER` và `MAX_HOLD` đi qua đường ghi thứ hai nên **không bao giờ đếm được**. Gate chỉ đếm được `STP`. Vậy `exit_paths_complete` **không thể đạt 3/3** dù chạy paper bao lâu.

Cùng loại lỗi với C4a: **một gate đếm thứ chưa từng được phát ra**. Khác biệt là C4a nằm trong reader nên sửa được ở dashboard, còn C5 nằm ở runner.

**Runner có biết loại thoát:** `run_maxhold_exit()` tại `runner.py:1061` ghi log `MAX_HOLD_EXIT: closed %s/%s`. Thông tin tồn tại lúc thoát, chỉ là không được ghi xuống `trade_log` ở đường chính.

**Đề xuất sửa:** ghi `exit_reason` tại `runner.py:1482` (chandelier / max_hold / signal). Đây là **sửa ở runner, không phải dashboard** — dashboard đang phản ánh trung thực một trường không được ghi.

**Cho tới khi sửa:** Overview không được trình bày "exits 0/3" như thiếu mẫu. Phải ghi rõ là **thiếu công cụ đo**, kèm cảnh báo rằng mục này không tự đầy theo thời gian.

#### 🟡 ĐÃ VÁ TẠM phía dashboard *(sửa gốc vẫn ở runner)*

Reader giờ phân biệt CLOSE **có nhãn** với CLOSE **không nhãn**. Khi không có CLOSE nào phân loại được, gate trả `STRUCTURAL_GAP` thay vì `PENDING`:

```
status  : STRUCTURAL_GAP
evidence: Chandelier 0 | MAX_HOLD 0 | STP 0 | 4 CLOSE fill(s) carry no exit_reason,
          so their path cannot be identified
metrics : labelled_exits 0 | unlabelled_exits 4 | instrumentation_gap true
```

Thẻ Overview đổi luôn dòng "to pass / unlock": khi có instrumentation gap, nó **không còn bảo người review "thu thập thêm 3 mẫu mỗi loại"** — thay vào đó nói thẳng rằng chờ lâu hơn không giải quyết được, runner phải ghi `exit_reason`.

CSS thêm `.blocker-card.spec-gap` / `.structural-gap` màu tím: **một gap không phải mẫu đang chờ**, nên không được mượn màu vàng "đang tiến triển".

Kèm 2 test phân biệt đúng hai tình huống: không nhãn → `STRUCTURAL_GAP`; có nhãn nhưng thiếu mẫu → `PENDING` (trường hợp này chờ thì đầy thật). Mutation-test: đổi về `PENDING` → test fail `- STRUCTURAL_GAP / + PENDING`.

**Việc này KHÔNG thay thế việc sửa runner.** Nó chỉ khiến dashboard thôi nói dối về bản chất của vấn đề.

---

#### C6 — Hai đường ghi CLOSE có schema lệch nhau; P&L của lệnh cắt lỗ không được ghi *(phát hiện thêm 2026-08-14)*

**File:** `global_index/runner.py:926-942` và `:1482-1496`

Đào tiếp từ C5 thì thấy hai đường ghi CLOSE không chỉ khác nhau ở `exit_reason` — chúng **lệch schema hai chiều**:

| | Đường STP (`:934`) | Đường tín hiệu (`:1482`) |
|---|:---:|:---:|
| `exit_reason` | ✅ | ❌ |
| `order_id` / `perm_id` | ✅ | ❌ |
| `source` | ✅ | ❌ |
| **`pnl_sized`** | ❌ | ✅ |
| `slip` | ❌ | ✅ |
| `regime` | ❌ | ✅ |

Đối chiếu 10 bản ghi CLOSE thật trong `trade_log.jsonl` — khớp chính xác dự đoán:

```
3/10 CLOSE khong co pnl_sized — va ca 3 deu la STP/backfill:
   M2K entry=2026-08-05  exit_reason='STP'  source='backfill:observed_2026-08-06'
   M2K entry=2026-08-06  exit_reason='STP'  source='backfill:reqExecutions'
   M2K entry=2026-08-03  exit_reason=None   source='backfill:activity_statement'
7/10 CLOSE con lai (deu la thoat theo tin hieu): pnl_sized CO, slip CO, regime CO
```

**Ảnh hưởng — chỉ tới sổ suy từ trade_log, KHÔNG tới equity của runner.**

> **Đính chính (đã truy code trước khi kết luận).** Bản nháp đầu của mục này viết rằng P&L paper "lệch lên trên đúng lúc chiến lược bắt đầu thua", ngụ ý cả sổ vốn cũng sai. **Sai.** Equity đi đường riêng: `_book_realised()` (`runner.py:842`), và đường STP **có** gọi nó — `runner.py:782` và `:790`, cả hai với `why="stop"`. Nên **equity hệ thống ghi nhận đủ khoản lỗ do stop, không có lỗi sizing rủi ro khi giao dịch thật.** Phần dưới là mức ảnh hưởng thật.

Dashboard trình bày **hai** con số P&L song song:

| Con số | Nguồn | Có tính lệnh thoát bằng stop? |
|---|---|---|
| `actual_equity` / system ledger | `_book_realised()` → `state.equity` | ✅ **có** |
| `paper_trade_filter_equity`, và headline `paper_epoch_closed_realized` | `cumulative trade_log pnl_sized` | ❌ **không** |

Chỉ con số thứ hai bị thiếu. Mà đó lại chính là con số làm **headline** trong panel P&L Compare.

**Bằng chứng thực nghiệm:** ba lệnh M2K thoát bằng stop trước epoch không có `pnl_sized` nào trong sổ trade_log, trong khi Flex (broker, nguồn sự thật) vẫn ghi P&L cho chúng — payload báo `excluded_pre_epoch_exit_window_realized: $388.25` trên 2 lot đã đóng.

**Điểm cần ghi nhận cho dashboard:** nó **đã** phơi bày chênh lệch này qua trường `system_ledger_vs_trade_filter` (ngày 2026-08-10: `+272.0`), hiện đang được quy cho `ledger_offset_explanation: MATCH_PRE_EPOCH_CARRY_FILL`. Đây là thiết kế đúng. Nhưng khi một lệnh stop nổ **trong** epoch, khoảng cách sẽ nới ra và lời giải thích "carry trước epoch" sẽ không còn đúng nữa.

**Mức độ ảnh hưởng hiện tại: bằng 0** — epoch này chưa có lệnh nào thoát bằng stop. Đây là **thiên lệch tiềm ẩn của một trong hai con số P&L**, không phải lỗi sổ vốn.

**Hai hệ quả phụ:**
- `regime_coverage` đếm thiếu, vì STP close không ghi `regime`. Gate hiện báo chỉ thấy `Normal` — nếu một stop nổ trong `Stress` thì regime đó vẫn không được ghi nhận.
- Ngược lại, thoát theo tín hiệu không ghi `order_id`/`perm_id`, nên **không đối chiếu ngược được với lệnh bên broker** — làm yếu chính khả năng reconcile mà dashboard này dựa vào.

**Đề xuất sửa:** hợp nhất một schema CLOSE duy nhất cho cả hai đường ghi, đủ cả `exit_reason`, `pnl_sized`, `slip`, `regime`, `order_id`, `perm_id`, `source`. Đây là **sửa ở runner**. Nên làm cùng lúc với C5 vì cùng một chỗ, cùng một nguyên nhân.

**Kiểm chứng sau khi sửa:** thêm test khẳng định hai đường ghi CLOSE phát ra **cùng một tập khoá** — đây đúng loại lỗi mà một test contract schema sẽ chặn vĩnh viễn.

---

#### C7 — RÚT LẠI. Cơ chế thoát lệnh live đã được chủ dự án đính chính

> **Bản nháp đầu của mục này SAI và đã bị rút.** Nó dựa vào docstring của `_record_stop_exit` (`runner.py:902`) — *"chandelier stops are 79.5% of exits"* — để kết luận rằng chandelier nổ tại broker nên không tách được khỏi STP, và do đó gate không thể có nghĩa nếu chỉ sửa code. **Con số 79,5% đó là thống kê của backtest, không phải đường live.** Chủ dự án đính chính, và code xác nhận.

**Cơ chế thoát lệnh thật của đường live/paper**, xác nhận qua `live_decision.py:15-19` và `runner.py:1441-1454`:

| Loại thoát | Ai quyết định | Đường thực thi | Nhãn nhận được |
|---|---|---|---|
| **Chandelier / max-hold / regime** | signal layer đặt `pos.exit_day = today` | đóng bằng lệnh thị trường, `runner.py:1451` | ❌ **không nhãn** |
| **Stop nổ tại broker** (lưới an toàn qua đêm) | GTC STP đặt sẵn ở mức chandelier **lúc vào lệnh** | `_record_stop_exit` | ✅ `exit_reason="STP"` |

Lệnh đặt tại broker là **stop cố định, không ratchet**. Runner nói rõ hai lần:

```
L1458: # stop_price = entry chandelier level (fixed stop, not ratcheted yet).
L1720: # Note: stop_price = entry chandelier level; ratchet updates are not yet
```

Logic dời stop duy nhất (`L1850`) là để chuyển stop sang hợp đồng mới khi roll, không phải ratchet.

**Kết luận đúng — ngược lại bản nháp:** ba loại thoát **có** tương ứng với ba thứ phân biệt được trong live. Signal layer biết trigger nào kích hoạt. Vấn đề chỉ là **thông tin đó bị vứt đi**, tại đúng một chỗ:

```python
# runner.py:1441-1445
exit_keys = {(p.inst, p.cluster) for p in exit_positions}   # ← rút gọn còn identity
for p in self.state.open_positions:
    if (p.inst, p.cluster) in exit_keys:
        p.exit_day = day                                     # ← lý do biến mất tại đây
```

`signal_fn` trả về `(entry_candidates, exit_positions)` (hợp đồng ở `runner.py:221`), rồi L1442 rút gọn thành tập khoá `(inst, cluster)` và **vứt trigger**.

**Nên C5 rẻ hơn và định vị rõ hơn tôi ước lượng trước đó:** không cần định nghĩa lại phân loại; chỉ cần dẫn lý do đi qua 3 chặng — signal layer → `p.exit_reason` tại L1445 → bản ghi CLOSE tại L1482.

**Còn lại đúng từ bản nháp:** `run_maxhold_exit` (`runner.py:1061-1122`) có `_book_realised` (L1104) nhưng **không có lệnh ghi trade_log nào**. Lệnh thoát do cron max-hold lúc 09:30 vắng mặt hoàn toàn khỏi `trade_log.jsonl`. Đây là lỗi riêng, không liên quan tới nhãn.

**Bài học:** docstring `_record_stop_exit` trộn thống kê backtest vào phần mô tả đường live. Nó đã dẫn tôi tới một kết luận sai về kiến trúc. Nên tách bạch trong chính docstring đó.

#### Nghi ngờ cộng đôi equity — đã truy, KHÔNG phải lỗi

Trong lúc đọc `run_maxhold_exit` thấy `self.state.equity += p.pnl_sized` (L1102) đứng ngay trước `_book_realised` (L1104), mà `_book_realised` cũng `self.state.equity += pnl` (L888). Trông như cộng đôi.

**Đã truy đến cùng: không phải lỗi.** `pos.pnl_sized` chỉ được gán ở **đúng một chỗ** — L887, bên trong `_book_realised`, chạy lúc đóng lệnh rồi vị thế bị loại khỏi `open_positions`. Vị thế đang mở luôn mang giá trị mặc định `0.0` (`live_decision.py:47`), và `live_positions.json` lưu đúng `pnl_sized: 0.0`. Nên hai dòng L1043/L1102 cộng số 0.

**Là code thừa, nhưng là mối nguy tiềm ẩn:** nếu sau này có ai đó mark-to-market vào `pnl_sized` của vị thế đang mở, hai dòng này lập tức thành cộng đôi thật vào equity — tức vào ngưỡng breaker và sizing. Nên xoá khi tiện tay.

#### Có bắt buộc phải sửa runner không?

**Không gấp — và không nên gộp vào công việc dashboard.**

Runner là thứ đặt lệnh thật. Toàn bộ audit này tới giờ chỉ đụng code monitor chỉ-đọc và dashboard; sửa runner là bậc rủi ro khác hẳn. Ba lý do để tách riêng:

1. **Không có lỗi an toàn giao dịch nào.** Đã truy: `_book_realised` được gọi trên mọi đường đóng lệnh, kể cả stop. Equity và ngưỡng breaker đọc đúng số.
2. **C5 có đường vòng phía dashboard.** Runner *đã* ghi log `MAX_HOLD_EXIT: closed %s/%s` (`runner.py:1110`). Reader vốn đã phân tích log cho rất nhiều thứ khác, nên có thể suy loại thoát từ log mà không đụng runner. Kém chuẩn xác hơn ghi thẳng từ nguồn, nhưng đủ để gate thôi nói dối.
3. **C6 chỉ ảnh hưởng một trong hai con số P&L**, và dashboard vốn đã phơi bày chênh lệch qua `system_ledger_vs_trade_filter`.

**Việc rẻ nhất và trung thực nhất, làm được ngay phía dashboard:** thôi trình bày `exits 0/3` như thiếu mẫu. Đổi thành "thiếu công cụ đo", kèm ghi chú rằng mục này không tự đầy theo thời gian. Không cần đụng runner, mà xoá bỏ được đúng cái hiểu lầm nguy hiểm.

**Khi nào thì sửa runner:** trước khi lên live thật, vì lúc đó `exit_reason` và `order_id` là thứ cần để đối soát với sao kê broker. Nhưng nên là một thay đổi độc lập, có test riêng, không bó chung với công việc dashboard.

---

#### Số liệu cho quyết định H4 *(đo 2026-08-14)*

| Chỉ số | Giá trị |
|---|---|
| Số ngày epoch đã chạy | 5 |
| OPEN fill trong epoch | 5 → **1,00/ngày** |
| CLOSE fill trong epoch | 4 → 0,80/ngày |
| **STP close trong epoch** | **0** |

Với nhịp hiện tại, nhánh `c1_open` cần **~100 ngày (≈4,8 tháng giao dịch)** để đạt `min_n=100` — **dài hơn cả mục tiêu 60 ngày của gate duration**. Tức ngay cả nửa "khả thi" cũng không đạt được trong cửa sổ mà gate thời lượng đặt ra.

Nhánh `c1_stp_close` không ước lượng được vì mẫu bằng 0, và theo C5 thì STP là **loại thoát duy nhất còn đếm được** — nên con số này phụ thuộc trực tiếp vào việc sửa C5.

---

### HIGH

---

#### H1 — "current status" trên Overview là chữ cứng ở 6/7 thẻ blocker

**File:** [paper.js:272](global_index/dash/paper/paper.js#L272), [:282](global_index/dash/paper/paper.js#L282), [:292](global_index/dash/paper/paper.js#L292), [:302](global_index/dash/paper/paper.js#L302), [:322](global_index/dash/paper/paper.js#L322), [:332](global_index/dash/paper/paper.js#L332)

Tham số thứ 4 của `blockerCard()` được render dưới nhãn **"current status"**. Nó là chuỗi cố định:

| Thẻ | "current status" hiển thị | Lấy từ payload? |
|---|---|---|
| B3 reconcile | "Historical broker/file mismatch lines remain unclassified." | ❌ |
| Data freshness | "Model/data freshness is currently blocking readiness." | ❌ |
| Open issues | "Unresolved operational blockers are still present." | ❌ |
| Coverage sample | "Sample coverage is pending, not an operational failure." | ❌ |
| C1 execution | "Current OPEN mean +9.00 ticks vs 5 tick limit; STP close N=0." | ✅ |
| Stop placement | "Deferred stop placement route is still pending clean-session proof." | ❌ |
| TWS restart | "Candidate logs do not count as proven restart recovery." | ❌ |

**Tại sao quan trọng:** Khi B3 mismatch về 0 và gate chuyển PASS, thẻ vẫn ghi *"Historical broker/file mismatch lines remain unclassified."* Khi model age hết hạn cảnh báo, Data freshness vẫn ghi *"Model/data freshness is currently blocking readiness."*

Chính phần mà người review được huấn luyện để đọc như **trạng thái sống** lại là chữ tĩnh, chỉ tình cờ đúng ở thời điểm hôm nay.

**Đề xuất sửa:** Suy ra từ `evidence` + `metrics` của gate/coverage (cả hai đã có sẵn trong payload và đã đúng), giữ chữ tĩnh cho dòng "why needed" nơi nó thuộc về.

---

#### H2 — "BREACH NOW" render y hệt một BREACH thật (lỗi CSS class token)

**File:** [paper.js:266](global_index/dash/paper/paper.js#L266) · [:35-37](global_index/dash/paper/paper.js#L35-L37) · [paper.css:31](global_index/dash/paper/paper.css#L31), [:35](global_index/dash/paper/paper.css#L35)

`c1Quality = 'BREACH NOW'` (có dấu cách). `statusClass()` chỉ lowercase và thay `_`→`-`, cho ra `"breach now"` — **hai class token**.

Ý định của tác giả CSS ở `paper.css:31`: `.blocker-card.breach-now { box-shadow: inset 3px 0 0 var(--amber) }` — màu vàng. Selector đó **không bao giờ khớp**. Token `breach` khớp `.blocker-card.breach` thay thế. Đo trực tiếp trên browser:

```
[BREACH NOW] C1 EXECUTION | OPEN 5/100, STP 0/100
    class='blocker-card breach now'   chipColor=rgb(240, 91, 97)   ← ĐỎ, không phải vàng
    bar=rgb(240, 91, 97) 3px 0px 0px 0px inset                      ← ĐỎ, không phải vàng
```

**Hệ quả:** Một **đọc chất lượng hiện tại trên N=5 mẫu** được tô đúng màu đỏ của BREACH gate B3, trong khi status backend thật của gate C1 là `PENDING` và badge ở tab Gates cho cùng gate đó là vàng `PENDING`.

**Overview và Gates mâu thuẫn nhau về cùng một gate, cả màu lẫn chữ.**

**Đề xuất sửa:** Xuất `QUALITY_BREACH` (dấu gạch dưới sống sót qua `statusClass`) hoặc thêm thay thế `\s`→`-` trong `statusClass`, và thêm `.blocker-card.quality-breach`. Ghi nhãn "quality breach (sample pending)" để phân biệt với gate breach là rõ ràng bằng chữ, không phải bằng sắc độ màu.

#### ✅ ĐÃ SỬA

Áp dụng cả hai: token đổi thành `QUALITY_BREACH`, và `statusClass` giờ dùng `.replace(/[\s_]+/g, '-')` để khoảng trắng không sinh ra class token rác nữa. CSS thêm `.blocker-card.quality-breach`.

Đo lại trên browser:
```
status : QUALITY_BREACH
class  : blocker-card quality-breach
chip   : rgb(221, 163, 58)      ← vàng, đúng ý đồ CSS
bar    : rgb(221, 163, 58)
```

---

#### H3 — Số trung bình C1 gộp ticks giữa các mã có giá trị tick chênh 5 lần

**File:** [paper_evidence_reader.py:300-308](monitor/backend/paper_evidence_reader.py#L300-L308) · `_slippage` tại [:501](monitor/backend/paper_evidence_reader.py#L501)

`open_mean = 9.00 ticks` là trung bình phẳng trên 5 fill OPEN thuộc 4 mã, với giá trị tick từ $0.50 đến $2.50:

| Mã | slip ticks | slip pts | tick value | slip $ |
|---|---:|---:|---:|---:|
| MNKD | +6.00 | 30.0 | $2.50 | +$15.00 |
| MYM | +8.00 | 8.0 | $0.50 | +$4.00 |
| MES | −4.00 | −1.0 | $1.25 | −$5.00 |
| M2K | **+28.00** | 2.8 | $0.50 | +$14.00 |
| MNKD | +7.00 | 35.0 | $2.50 | +$17.50 |
| **TB** | **+9.00** | | | **+$9.10** |

M2K với +28 ticks (tick = 0.1 điểm chỉ số) chi phối trung bình nhưng lại tốn **ít tiền hơn** so với +7 ticks của MNKD. Spec `max_mean_ticks: 5` được áp lên con số gộp này, và Overview đẩy kết quả thành "BREACH NOW" đỏ.

**Tại sao quan trọng:** Đây là verdict định lượng duy nhất về chất lượng execution trên dashboard, và nó **không so sánh được về mặt kinh tế** giữa các mã trong rổ. Thêm một lệnh M2K nữa là "breach" dịch chuyển vài ticks mà slippage tính bằng tiền không đổi.

**Đề xuất sửa:** Báo trung bình theo từng mã (dữ liệu đã có sẵn trong `trade_samples.rows`) và thêm một tổng hợp chuẩn hóa theo đô-la (`slip_usd = slip_ticks × tick_value`) làm headline. Giữ spec ticks theo từng mã.

#### ✅ ĐÃ SỬA

`_slippage()` bổ sung `_tick_value()`, mảng `by_inst` (trung bình theo từng mã) và `open_mean_usd` (tổng hợp quy đô-la). Con số gộp **vẫn giữ** — vì spec hiện hành áp lên nó và bỏ đi là âm thầm đổi luật — nhưng đi kèm `pooled_tick_caveat` nói rõ nó gộp các mã có giá trị tick chênh 5 lần.

Nói cách khác: dashboard không còn *chỉ* công bố một con số không so sánh được về mặt kinh tế; nó công bố con số đó **kèm lý do đừng tin nó một mình**, cộng với những con số so sánh được.

#### ✅ ĐÃ DUYỆT VÀ TRIỂN KHAI (2026-08-15) — spec C1 mới

Xem **Phụ lục K** cho toàn bộ dẫn xuất. Tóm tắt thay đổi:

| Mục | Cũ | Mới |
|---|---|---|
| OPEN scope | gộp | **theo từng mã** |
| OPEN `min_n` | 100 (gộp) | **20 mỗi mã** |
| STP scope | gộp | gộp (giữ) |
| STP `min_n` | 100 | **30** |
| `max_mean_ticks` | 5 | **3** |
| Báo cáo | mean | **mean + khoảng tin cậy 95%** |

---

#### H4 — Gate C1 không thể đạt được về mặt cấu trúc

**File:** [paper_evidence_reader.py:934-936](monitor/backend/paper_evidence_reader.py#L934-L936)

Với `scope: "separate"`: `enough = open_n >= 100 AND stp_close_n >= 100`. `stp_close_n` chỉ đếm **các lần đóng do stop kích hoạt**.

Hiện trạng: **0 STP close trong 5 ngày, tổng 9 fill.** Gate `exit_path_coverage` chỉ đòi **3** STP exit và coi thế là đủ mẫu. C1 đòi **100** cùng loại sự kiện đó.

Với tốc độ quan sát được, C1 không thể pass trong mục tiêu 60 ngày paper — hay trong vài năm. Dashboard vì thế có một gate PENDING vĩnh viễn, vẫn sẽ PENDING vào đúng ngày operator muốn promote, mà không có dấu hiệu nào trên màn hình cho biết mục tiêu là bất khả thi.

**Đề xuất sửa:** Hoặc đặt `min_n` khả thi cho nhánh STP-close (và ghi rõ trong `evidence_note`), hoặc tách C1 thành `c1_open` (N≥100, đạt được) và `c1_stp_close` (N≥N_khả_thi) để nửa khả thi thực sự có thể clear. Hiện `projected_sessions_to_target` để tính bất khả thi nhìn thấy được thay vì phải suy ra.

---

#### H5 — Nút cross-reference TWS trên Overview mở sai panel Coverage

**File:** [paper.js:333](global_index/dash/paper/paper.js#L333)

Nút `Open detail` của thẻ blocker "TWS restart" mang `data-coverage-ref="runner_freshness"`. Kiểm chứng trên browser:

```
runner_freshness  -> tab=paper-tab-coverage  detail='Runner evidence freshness'
```

"Runner evidence freshness" nói về việc `live_state_data.js` có đang được ghi hay không — nó **không nói gì** về khôi phục sau restart. Không có Coverage item nào cho TWS restart, nên nút này đưa người review tới bằng chứng không liên quan trong khi trông có vẻ chính thống.

Lập luận tương tự (nhẹ hơn) áp cho thẻ C1 → `fill_quality`, vốn dùng chung các dòng trade nhưng không dùng chung spec C1 hay các số trung bình slippage.

Riêng: **thẻ B3 reconcile không có nút nào cả** (`refKey = ''` tại [:273](global_index/dash/paper/paper.js#L273)) — BREACH duy nhất không có đường drill-down — và thẻ **Coverage sample** cũng vậy.

**Đề xuất sửa:** Bỏ nút khi không có target đúng (tốt hơn là một target sai), hoặc thêm panel Coverage `tws_restart` / `b3_reconcile`. Thẻ B3 tối thiểu nên link tới `state_persist` / `open_incidents`, vốn đã được panel Gates của chính nó cross-reference tại [:578-582](global_index/dash/paper/paper.js#L578-L582).

#### ✅ ĐÃ SỬA (một phần)

Đã gỡ nút trỏ sai của thẻ TWS. Nhưng giờ **3/7 thẻ không có drill-down**: B3 reconcile, Coverage sample, TWS restart.

**Còn nợ:** B3 là BREACH duy nhất mà vẫn không có đường đi tới bằng chứng. Nên trỏ sang `state_persist` / `open_incidents` như panel Gates của chính nó đang làm.

---

#### H6 — Thanh "Active rule" của STP nêu luật chặt hơn luật backend thực thi

**File:** [paper.js:420-429](global_index/dash/paper/paper.js#L420-L429) · [:502](global_index/dash/paper/paper.js#L502) · reader `_stp_placement_status` tại [:1448](monitor/backend/paper_evidence_reader.py#L1448)

Render thực tế:
- Thanh rule: `PLACEMENT · accepted > 0, failed = 0`
- Metric card: `PLACEMENT FAILED · 2 · "Failed stop placement must be zero before pass."` màu đỏ
- Status panel: **PENDING**, không phải BREACH

Spec được thực thi là `max_trade_matched_failed: 0`, và `failed_matched_to_trade = 0` — 2 lỗi kia là `failed_unmatched_to_trade` (và theo C1 ở trên, cả hai đều là mock).

Thanh rule và caption của metric mô tả một luật mà code không áp dụng, và **lý do panel không breach thì không bao giờ được nêu trên panel**. Giải thích ("2 unmatched failed log line(s)", "not a paper OPEN") nằm cách đó hai cú click, trong bảng Coverage → Route Reconcile.

**Đề xuất sửa:** Render thanh rule từ `metrics.spec` thay vì literal cứng (cùng loại lỗi với M7), và tách metric thành "Failed (trade-matched) 0 / (unmatched) 2" với số unmatched được style như context, không phải breach.

---

#### H7 — Contract spec guard chỉ phủ 4/6 mã đang giao dịch; frontend giữ bản sao thứ hai của multiplier

**File:** [paper_evidence_reader.py:311-325](monitor/backend/paper_evidence_reader.py#L311-L325) · [paper.js:854](global_index/dash/paper/paper.js#L854)

`_local_contract_specs()` chỉ duyệt `futures.basket.BASKET`:

```
BASKET: ['MES', 'MNQ', 'MYM', 'M2K']
SPECS : ['NKD', 'MNKD']          ← MNKD tick=5.0, point_value=0.5
```

**MNKD bị loại khỏi guard** — trong khi MNKD chiếm **4/9 fill (44%)**, bao gồm hai dòng slip lớn nhất trên trang (`20.822` và `−8.214` ticks). `_tick()` tại [:306](monitor/backend/paper_evidence_reader.py#L306) *có* fallback sang `SPECS`, nên ticks của MNKD được tính từ một spec chưa bao giờ được đối chiếu với IBKR. Chuỗi evidence "0/4 local contract spec(s) reconciled" trình bày 4 như thể đó là toàn bộ vũ trụ.

Cộng thêm: [paper.js:854](global_index/dash/paper/paper.js#L854) hardcode `contractPointValues = { MES: 5, MNQ: 2, MYM: 0.5, M2K: 5, MNKD: 0.5 }` và dùng nó cho mọi con số đô-la trong Source Diff Analyzer. Giá trị tình cờ khớp hôm nay (tôi đã kiểm cả 5), nhưng một panel có mục đích công bố là *"Guards P&L conversion by reconciling local point_value/tick/tick_value"* lại bị chính bản sao thứ ba, không được guard, ở phía client làm suy yếu.

**Đề xuất sửa:** Duyệt `BASKET | SPECS` trong `_local_contract_specs()`; đưa `point_value`/`tick`/`tick_value` vào payload và xóa literal trong JS.

#### ✅ ĐÃ SỬA — kèm 1 regression phải vá thêm

Backend giờ duyệt `{**BASKET, **SPECS}` → vũ trụ 6 mã gồm MNKD (`point_value 0.5`, `tick 5.0`). `contract_specs` đã có trong payload `paper_vs_backtest`. Literal `contractPointValues` trong JS đã xoá.

**Regression phát sinh — đúng loại lỗi mà audit này sinh ra để diệt.** `pointValueFor` trả `null` khi thiếu spec, và `priceUsd` làm `Number(null)` → `0`, lọt qua `Number.isFinite` → nhân ra **`$0.00`**. Đo được trên browser: ô Entry Ref Value hiện `$0.00` thay vì `$15,112.50`.

Chứng minh:
```
specs CÓ   -> pv = 5     usd = 15112.5
specs RỖNG -> pv = null  usd = 0        ← Number(null)=0, isFinite(0)=true
```

Trước đây bản đồ hardcode luôn có giá trị nên nhánh này không bao giờ chạy. Sau khi bỏ nó, **thiếu input lại sinh ra một con số tự tin nhưng sai** — nguy hiểm hơn hẳn `--`.

Đã vá bằng guard trong `priceUsd`, chặn cả `price` (cột "Paper − Backtest" trong `varianceCompareGrid` dính cùng lỗi khi `deltaNumber` trả `null`):

```js
if (price == null || price === '' || pointValue == null || pointValue === '') return null;
```

Kèm 2 test hành vi chạy hàm thật qua `node` (`test_price_usd_refuses_to_price_an_unreconciled_contract`, `test_unpriced_cells_render_as_dashes_not_zero_dollars`). Đã mutation-test: gỡ guard → cả hai fail với `assert '+$0.00' == '--'`.

**Hệ quả cần biết:** sau khi restart server, `contract_spec_guard` sẽ chuyển `OBSERVED` → `MISSING` (NKD + MNKD chưa đối chiếu IBKR). Đó là fix chạy đúng — panel bắt đầu thành thật rằng MNKD chưa từng được xác nhận. Riêng NKD không giao dịch trong epoch nên sẽ là dòng MISSING vĩnh viễn; cân nhắc loại khỏi guard.

**Bài học cho các batch sau:** cả hai lần giao việc, chỗ duy nhất hỏng đều là chỗ **thay đổi luồng dữ liệu** và tạo ra đường "thiếu input" mới. Mọi thay đổi loại này phải kèm test cho trường hợp rỗng/thiếu ngay trong đề bài.

---

#### H8 — Hai phép reconcile so sánh một giá trị với chính nó, không bao giờ fail được

**File:** [paper.js:1122-1123](global_index/dash/paper/paper.js#L1122-L1123)

```js
const pbRecon = reconcileStatus(pl.paper_minus_backtest_realized, pl.paper_minus_backtest_realized);
const pfRecon = reconcileStatus(pl.paper_minus_flex_epoch_rebased_realized ?? …,
                                pl.paper_flex_bridge_diff_sum ?? pl.paper_minus_flex_epoch_rebased_realized ?? …);
```

`pbRecon` là so sánh chính nó theo đúng nghĩa đen → luôn `RECONCILED`, và sau đó **không hề được dùng** (verdict tại [:1125](global_index/dash/paper/paper.js#L1125) dùng `pfRecon` và `ledgerOk`).

`pfRecon` **suy biến thành so sánh chính nó** bất cứ khi nào `paper_flex_bridge_diff_sum` vắng mặt — âm thầm biến một phép kiểm tra chéo nguồn thành một pass được bảo đảm.

Cùng pattern `?? fallback-về-chính-nó` lặp lại tại [:788-789](global_index/dash/paper/paper.js#L788-L789), [:825-826](global_index/dash/paper/paper.js#L825-L826), [:1038-1039](global_index/dash/paper/paper.js#L1038-L1039), [:1097-1099](global_index/dash/paper/paper.js#L1097-L1099).

**Tại sao quan trọng:** "RECONCILED" là từ mạnh nhất mà dashboard này dùng. Nó **không bao giờ được phép** đạt tới bằng một field bị thiếu.

**Đề xuất sửa:** `reconcileStatus` phải trả `{label: 'UNAVAILABLE', cls: 'watch'}` khi một trong hai toán hạng vắng mặt, và không bao giờ nhận cùng một tham chiếu hai lần.

#### ✅ ĐÃ SỬA

`pbRecon` (so sánh chính nó, lại còn không được dùng) đã xoá hẳn. `pfRecon` bỏ fallback-về-chính-nó, giờ là `reconcileStatus(pl.paper_minus_flex_epoch_rebased_realized ?? …, pl.paper_flex_bridge_diff_sum)`.

**Đính chính báo cáo gốc:** mục H8 nói pattern này "lặp lại tại [:788-789], [:825-826], [:1038-1039], [:1097-1099]" — nhận định đó quá rộng. Đọc lại kỹ, các chỗ đó là fallback sang **tên field cũ khác** (`paper_minus_statement_entry_epoch_realized`) ở toán hạng thứ hai, còn toán hạng thứ nhất là giá trị thật sự khác. Chúng không phải so sánh chính-nó và không cần sửa. Chỉ dòng 1122–1123 là lỗi thật.

Khi thiếu field, `reconcileStatus` trả `{label:'CHECK', cls:'watch'}` — không còn âm thầm pass. Chưa dùng nhãn `UNAVAILABLE` như đề xuất, nhưng hành vi đã đúng.

---

### MEDIUM

**M1 — Bộ dò candidate TWS restart đếm cả cảnh báo B3 và ngắt kết nối thường lệ.**
[paper_evidence_reader.py:68-71](monitor/backend/paper_evidence_reader.py#L68-L71). Trong 281 dòng candidate: 175 là `[ibkr] Disconnected.` (teardown bình thường mỗi chu kỳ) và một khối lớn là cảnh báo B3 mismatch, khớp vì dòng đó ghi *"…Verify live_positions.json matches **IBKR**, then **restart**."* Gate từ chối tính candidate là bằng chứng (đúng), nên tác động giới hạn ở con số context "candidate lines 281 / 5 day(s)" và thẻ Gaps — nhưng những con số đó gợi ý mức bất ổn kết nối mà log không hề chứng minh. *Sửa:* yêu cầu động từ reconnect/restart tường minh gần một sự kiện kết nối IBKR, và loại các dòng đã được phân loại là B3.

#### ✅ ĐÃ SỬA

`_TWS_RESTART` giữ nguyên phần bắt rộng, thêm `_TWS_RESTART_EXCLUDE` loại bốn lớp dương tính giả đã đo được: `then restart` (chỉ dẫn trong cảnh báo, không phải sự kiện), tiền tố `B3:`, `[ibkr] Disconnected.` và `[ibkr] Connecting` (teardown/setup thường lệ mỗi chu kỳ). Candidate **281 → 192** (sau lọc khối C1) **→ 4** (sau exclude này). Cách bắt-rộng-rồi-loại được chọn thay vì siết regex chính, vì siết regex làm mất true positive khó đoán trước; exclude thì liệt kê được và test được từng lớp.

Nói cách khác: con số 281 gợi ý một hệ thống bất ổn kết nối liên tục. Con số thật là **4**. Gate vốn đã từ chối tính candidate là bằng chứng (đúng), nhưng thẻ Gaps và dòng context thì đang bán một câu chuyện mà log không hề chứng minh.

Đo chi phí sau khi đổi (2 file `live_day_*.log`): regex TWS 0,42s → 0,45s, MANUAL 0,52s → 0,39s. Không phải nguồn của độ trễ cold-cache.

**M2 — Bộ dò manual-intervention khớp chính chữ cảnh báo của hệ thống; mâu thuẫn với panel roll.**
[paper_evidence_reader.py:67](monitor/backend/paper_evidence_reader.py#L67). Cả 128 candidate đều nằm trong `scheduler_0810.log`; 108 khớp từ khóa **"operator"**, xuất hiện vì cảnh báo của chính runner ghi `OPERATOR: recompute the chandelier level…`. **Không có dòng nào cho thấy con người đã làm gì.**

Phân rã 128 dòng: 52 `B4 NAKED`, 20 `C2: Roll OPEN FAILED`, 17 `C2: rolled with no recorded stop level`, 15 `STP UNPROTECTED`, 14 `C2: replacement STP…`, 10 `B4 STP ID DRIFT`.

Chú ý ~51 dòng cảnh báo C2 roll — trong khi panel **Roll / C2 slippage** đồng thời báo *"No roll event exists in the current paper epoch"* (`roll_slippage_lines: 0`). **Hai panel, cùng epoch, tuyên bố mâu thuẫn nhau về việc roll có xảy ra hay không.** *Sửa:* khớp *hành động* của operator, không khớp *chỉ dẫn* trong cảnh báo (neo vào marker `OPERATOR ACTION`/`MANUAL CLOSE` mà runner nên phát ra); đồng bộ lại các bộ dò C2.

#### ✅ TỰ KHỎI nhờ C1 — nhưng gốc rễ vẫn còn

Sau khi lọc log theo khối, `manual_intervention` candidate rơi **128 → 0**. Toàn bộ 128 dòng đều nằm trong các khối mock, kể cả ~51 dòng `C2: Roll` — nên mâu thuẫn với panel Roll/C2 cũng biến mất theo. Panel giờ nhất quán: không có roll nào trong epoch, và không có candidate can thiệp thủ công nào.

**Gốc rễ chưa sửa:** regex `\b(manual|intervention|operator|override)\b` vẫn khớp chính chữ `OPERATOR:` trong cảnh báo do runner tự phát. Hiện tại vô hại vì nguồn nhiễu đã bị lọc, nhưng lần tới có cảnh báo `B4 NAKED` **thật** thì nó sẽ lại bị đếm thành "operator action candidate" trong khi không ai làm gì. Vẫn nên sửa theo đề xuất trên.

**M3 — Màu chip được regex-match trên chữ hiển thị, và bị đụng độ.**
[paper.js:170-177](global_index/dash/paper/paper.js#L170-L177). Regex `bad` chạy sau cùng và có chứa `halt`, nên **"no false halt evidence" render màu đỏ** (đo được `rgb(240,91,97)`) trên một panel có `B3 HALT lines = 0`. Trong khi đó `"structured checks 1"` và `"1/1 protected"` render xám trung tính — không có tín hiệu tích cực nào cho điều kiện đang pass. Màu là thuộc tính của câu chữ, không phải của dữ liệu. *Sửa:* mỗi reason phát ra `{text, severity}` từ đường dữ liệu; xóa bộ phân loại regex.

#### ✅ ĐÃ SỬA

`reason(text, tone)` nhận tone như tham số; `c1ReasonChip(item)` suy tone từ **dữ liệu** của chính item chứ không đọc câu chữ. Bộ phân loại regex đã xoá. `"no false halt evidence"` hết đỏ.

**M4 — Ba bảng bị cắt cột trên mobile mà không cách nào cuộn.**
[paper.css:383](global_index/dash/paper/paper.css#L383) đặt `overflow-x: hidden` **toàn cục** (không nằm trong media query) cho `.stp-placement-table`, `.stp-route-table`, `.rejection-table`, ghi đè `.trade-table { overflow: auto }` tại [:131](global_index/dash/paper/paper.css#L131). Đo tại 390px:

| Bảng | Container | Nội dung | Bị cắt | Chiều cao hàng |
|---|---:|---:|---:|---:|
| `.rejection-table` | 315px | 498px | **183px không tới được** | 531px |
| `.stp-placement-table` | 315px | 445px | **132px không tới được** | 236px |
| `.fill-quality-table` | 315px | 1360px | 0 (cuộn được) | 61px |

8 cột của bảng rejection bị nén còn 31–56px mỗi cột với `word-break: break-word`, tạo ra hàng cao 531px cho mỗi bản ghi. `.source-diff-table` đã được xử lý stack riêng cho mobile tại [:508-512](global_index/dash/paper/paper.css#L508-L512); ba bảng này thì không. *Sửa:* `overflow-x: auto`, hoặc cho chúng cùng cách xử lý stack.

#### ✅ ĐÃ SỬA — và phạm vi rộng hơn ba bảng

Rà lại thì không chỉ 3 bảng: **≈20 bảng** ở ≤680px đều bị nén cột chứ không cuộn. Đã cho tất cả `overflow-x: auto` + `min-width: 620px` trong media query. Chọn `min-width` thay vì stack vì các bảng này là **bảng đối chiếu** — giá trị nằm ở việc đọc theo hàng ngang, stack thì mất chính điều đó.

Kiểm chứng ở 390px: `scrollWidth == clientWidth == 390` ở cấp trang, cuộn ngang nằm trong từng container.

> **Cảnh báo về cách kiểm** (đã ghi SCRATCHPAD): *"trang không cuộn ngang" KHÔNG chứng minh không tràn.* Nội dung vượt mép có thể bị **cắt** thay vì cuộn, khi đó `scrollWidth == clientWidth` mà test vẫn xanh — chính là bẫy đã sinh ra M4. Kiểm đúng là so `scrollWidth` với `clientWidth` **của từng container bảng**.

**M5 — Auto-refresh 60 giây phá vị trí đọc của người review.**
[paper.js:1957](global_index/dash/paper/paper.js#L1957) → `render()` gán lại `innerHTML` cho mọi panel và cho `#paperCoverage`. Mỗi `<details>` đang mở ("More info", nhóm audit evidence), mỗi vị trí cuộn bảng, và mọi vùng bôi đen text đều reset mỗi phút. Toàn bộ giá trị của dashboard này nằm ở việc đọc các bảng bằng chứng dài. *Sửa:* diff-render, hoặc tạm dừng interval khi còn `<details open>` / khi document đang focus, kèm nút "có dữ liệu mới — refresh".

#### ✅ ĐÃ SỬA — poll giữ nguyên, quyền repaint chuyển cho người đọc

Lý do chọn hướng này thay vì diff-render: **nhịp poll lệch hẳn nhịp dữ liệu.** Payload đổi vài lần một ngày (có lúc đo được `observed_at` cũ 4,5 tiếng), nên repaint mỗi phút là lấy đi thứ có giá trị (chỗ đọc) để đổi lấy độ tươi không tồn tại. Diff-render bị loại vì tầng render ở đây là những chuỗi template lớn — diff đúng nghĩa là viết lại toàn bộ, rủi ro hồi quy cao ngay sau một loạt fix.

`load(force)` giờ tách hai việc: poll nền chỉ **so sánh** text phản hồi với bản đang hiển thị; khác thì hiện chip `NEW EVIDENCE AVAILABLE — REFRESH` ([index.html:20](global_index/dash/paper/index.html#L20), [paper.css:3-6](global_index/dash/paper/paper.css#L3-L6)). Chip **refetch** khi bấm chứ không phát lại payload đã bắt được, nên chip để 10 phút vẫn cho dữ liệu hiện hành.

Verify Playwright: mở 3 `<details>`, cuộn xuống 900px → poll không đụng gì; bấm chip → repaint, chip tự tắt. Mutation test: bỏ guard → cả 2 test đỏ.

**Một hành vi phát sinh đáng ghi:** nếu `render()` ném lỗi giữa chừng, `renderedText` không được gán, nên lần poll sau vẽ lại. Đó là đúng — render hỏng thì không được tính là "đã hiển thị".

**M6 — Kết quả paper không có trên Overview, và ba tổng P&L khác nhau nằm cạnh nhau.**
P&L realised của epoch là **−$43.25** (`paper_epoch_closed_realized`). Tab Overview **không bao giờ hiện nó** — không có thẻ blocker nào về khả năng sinh lời.

Trong bảng P&L, ba con số xuất hiện cùng nhau: Flex zero-base **−$43.25**, Flex ledger-aligned **+$228.75**, Realtime ledger **+$228.75**. Con số +$228.75 đến từ một lệnh carry trước epoch (`excluded_pre_epoch_exit_window_realized: $388.25` trên 2 lot; `ledger_offset_explanation: MATCH_PRE_EPOCH_CARRY_FILL`).

Có công bố, nhưng chỉ trong một `<p class="detail-note">` ở cuối `statementPnlCompareBlock`. Người review lướt bảng rất dễ đọc +$228.75 thành kết quả paper. *Sửa:* gắn nhãn rõ ràng kết quả chiến lược trong epoch là headline, hạ các con số reconcile ledger xuống một sub-grid "ledger check" riêng, và thêm thẻ P&L/edge vào Overview.

#### ✅ ĐÃ SỬA — nhưng đề bài đã đổi giữa chừng

Khi viết M6, `paper` và `flex` **cùng** là −$43.25, nên bảng trông nhất quán một cách giả tạo. Sau khi sửa G1 (Phụ lục G), hai vế lệch nhau **30 lần**, và sự lệch đó là thật. Câu hỏi "con số nào là headline" vì thế sắc hơn chứ không nhẹ đi.

Quyết định: **công bố cả hai, gắn nhãn theo câu hỏi mà mỗi con số trả lời**, vì chúng không thay thế được cho nhau.

| Con số | Trả lời |
|---|---|
| **−$43.25** | *Chiến lược có chạy không?* — đúng thứ paper test sinh ra để đo |
| **−$1,303.25** | *Tài khoản mất bao nhiêu?* — thực tế vận hành ở broker |

Chọn một cái làm "kết quả" là sai theo cả hai chiều: chỉ hiện −43 thì giấu mất tiền thật đi xa hơn 30 lần; chỉ hiện −1.303 thì đổ cho chiến lược một khoản lỗ do lỗi định tuyến gây ra.

Thẻ mới trên Overview ([paper.js:349-374](global_index/dash/paper/paper.js#L349-L374)) dùng đúng khuôn `purpose / why needed / current status / to pass-unlock` như 7 thẻ kia:

```
[OBSERVED] EPOCH P&L    strategy −$43.25 / broker −$1,303.25
  current status: Gap +$1,260.00 ... fully accounted for by recorded
                  ledger adjustment(s) totalling −$1,260.00. Based on
                  4 closed lot(s) — too few to read as strategy edge.
```

Nếu khoảng chênh **không** khớp bút toán, dòng đổi thành `part of the gap is unexplained` — cả hai nhánh đều có test.

**Cố ý `OBSERVED`, không phải blocker.** Với 4 lot đã đóng, mọi ngưỡng lỗ đều là ngưỡng đặt trên nhiễu; và các gate về *mẫu* đã chặn sẵn đúng sự thiếu đó — thêm blocker P&L là chặn hai lần cùng một thứ. Có test ghim riêng để thẻ này không âm thầm trở thành blocker.

**Việc còn nợ ở đây là quyết định chính sách, không phải kỹ thuật:** ngưỡng lỗ để chặn go-live. Không ai đặt con số đó, và tôi không tự đặt được. Để tham chiếu: $1.303 trên sleeve $50.000 là **2,6% trong 5 ngày**, so với ngân sách MaxDD 6,2% của backtest — tức ~42% hạn mức sụt giá mô hình cho phép, tiêu hết bởi một lỗi chứ không phải bởi giao dịch.

**M7 — Thanh "Active rule" là literal cứng, không lấy từ payload.**
[paper.js:343-352](global_index/dash/paper/paper.js#L343-L352) hardcode `Duration 60 days`, `Chandelier >= 3`, `MAX_HOLD >= 3`, `STP >= 3`; [:420-429](global_index/dash/paper/paper.js#L420-L429) hardcode thanh STP (xem H6); [:1912](global_index/dash/paper/paper.js#L1912) hardcode `/ 60`. Cả `duration.target` và `target_each` đều có trong payload. Đổi một spec trong `paper_inputs.json` là dòng "Active rule" âm thầm nói dối.

#### ✅ ĐÃ SỬA

Mọi ngưỡng trong thanh rule giờ đọc từ payload. Khi spec **thiếu**, hiển thị `missing` chứ không bịa tiến độ giả — có test riêng ghim cả hai trường hợp (`reads_duration_and_exit_targets_from_payload`, `shows_missing_spec_without_fake_progress`).

**M8 — Gap TWS restart không có nút "Open related panel".**
`related_key: null` trong payload. Kiểm chứng: 3/4 thẻ gap có nút, TWS thì không. Đây cũng là gap có yêu cầu tồn đọng lớn nhất (10 đêm).

#### ❌ KHÔNG SỬA — và lý do quan trọng hơn bản thân mục này

Tôi đã đánh dấu mục này ✅ rồi phải rút lại khi kiểm chứng lại payload: gap `"TWS restart coverage"` **vẫn** `related_key: null`.

Nó không sửa được bằng cách gán một khoá. `related_key` trỏ tới một **coverage panel**, và danh sách coverage hiện có 15 khoá — **không khoá nào là TWS**:

```
paper_vs_backtest, fill_quality, stp_placement, state_persist, rejections,
runner_freshness, data_freshness, contract_spec_guard, current_protection,
open_incidents, roll_slippage, manual_intervention, sample_denominators,
same_day_multi_day, log_hygiene
```

`tws_restart_nights` là một **gate**, không phải coverage. Bằng chứng restart TWS **không có panel chi tiết nào để mở**.

Và đây chính là điều làm mục này đáng nói: ứng viên gần nhất là `runner_freshness` — **đúng cái nút mà H5 vừa gỡ đi vì trỏ sai chỗ**. Sửa M8 theo cách hiển nhiên là tái tạo H5.

**Kết luận đúng:** M8 không phải lỗi thiếu một thuộc tính. Nó là triệu chứng của việc gate có yêu cầu tồn đọng lớn nhất (10 đêm) lại là gate **duy nhất không có bề mặt bằng chứng riêng**. Sửa thật là dựng một coverage panel TWS — việc mới, không phải một mục Medium.

#### ✅ ĐÃ SỬA sau đó (2026-08-15)

Panel `tws_restart` đã được dựng (Phụ lục I.3), nên `related_key` có đích hợp lệ để trỏ tới. **4/4 thẻ gap giờ có nút**, và thẻ blocker TWS trên Overview cũng có. Test `test_every_gap_card_can_open_the_panel_it_refers_to` khẳng định thêm rằng không gap nào bị trỏ về `runner_freshness`.

Đáng ghi lại vì trình tự mới là điểm chính: kết luận "không sửa được" **đúng tại thời điểm đó** — cách sửa hiển nhiên sẽ tái tạo H5. Nó chỉ sửa được sau khi dựng đúng thứ còn thiếu.

---

### LOW

- **L1 — Ba bảng hoàn chỉnh là code chết.** `pnlCompareRows` ([:708](global_index/dash/paper/paper.js#L708)), `lifecycleCompareRows` ([:783](global_index/dash/paper/paper.js#L783)), `pnlDailyRows` ([:1287](global_index/dash/paper/paper.js#L1287)) mỗi hàm xuất hiện đúng 1 lần trong file — chính là dòng định nghĩa. Không bao giờ được gọi. ~180 dòng, bao gồm cả footer reconcile đầy đủ.

- **L2 — Bảy element ID mồ côi.** `paperDays`, `regimesSeen`, `exitCoverage`, `slippageMean`, `slippageCount`, `c1SampleCaption`, `closeSlippageMean` được ghi bởi [`setText`](global_index/dash/paper/paper.js#L9) / `$()` nhưng không tồn tại trong `index.html` (bị xóa khi refactor sang tabs). No-op im lặng; `payload.summary` giờ gần như không được dùng ngoài vai trò fallback cho C1.

- **L3 — Số float thô render không format.** C1 → More info → Raw cumulative stats in ra `6.900000000000091` và `-1560.2000000000062` qua `metricLine` ([:417](global_index/dash/paper/paper.js#L417)), vốn không format số. Ngoài ra: raw `open_n=15` so với hiển thị `5`, raw `close_n=7` so với STP `0`, mà phần chú thích chỉ giải thích chênh lệch về *loại close* — khoảng cách 15-so-với-5 ở OPEN (tích lũy toàn thời gian vs giới hạn epoch) không được giải thích. Và `close_sum/close_n = −222.9 ticks` là con số người đọc tự tính ra được và dễ hiểu nhầm thành slippage stop thảm họa.

- **L4 — "Timeline Data Rows" render thẻ verdict tiêu đề "Daily divergence".** `pnlTimelineSupportRows` yêu cầu `backendVerdict(compare, 'daily')` ([:1281](global_index/dash/paper/paper.js#L1281)), có `title` backend là "Daily divergence" và summary "Some daily rows are stale." Tiêu đề fallback của chính section đó ("Timeline data") bị bỏ đi bất cứ khi nào verdict backend tồn tại.

- **L5 — Thứ tự thẻ Overview là mảng cố định**, không sắp theo mức độ. Ba thẻ BREACH tình cờ đứng đầu hôm nay; thứ tự sẽ không bám theo dữ liệu.

#### ✅ L3, L4, L5 — ĐÃ SỬA

- **L3:** `metricLine` làm tròn float về 4dp. `6.900000000000091` → `6.9`.
- **L4:** `renderVerdict(..., { keepSectionTitle })` giữ tiêu đề của chính section thay vì để verdict backend ghi đè. "Timeline Data Rows" hết mang tiêu đề "Daily divergence".
- **L5:** thêm `BLOCKER_RANK` + `blockerRank()`; thẻ sắp theo mức độ nặng trước. **Sắp ổn định** — thẻ cùng mức giữ nguyên thứ tự viết trong mã, nên layout chỉ dịch chuyển khi trạng thái thật sự đổi, không nhảy loạn giữa các lần render.

Thứ tự hiện tại xác nhận nó bám dữ liệu: `BREACH` ×3 → `QUALITY_BREACH` → `STRUCTURAL_GAP` → `PENDING` ×2 → `OBSERVED` (thẻ P&L mới).

---

## 2. Bảng nhất quán dữ liệu

| # | Chỉ số / status hiển thị | Field nguồn backend | Khớp? | Ghi chú |
|---|---|---|---|---|
| 1 | Hero `BREACH` / "At least one observed gate breached" | `gates[*].status` có `BREACH` | ✅ | Chỉ do `b3_reconcile` gây ra — xem C4 |
| 2 | Overview B3 "mismatch 100" | `gates.b3_reconcile.metrics.mismatches` | ⚠️ giá trị đúng, **ý nghĩa sai** | Tổng `count` trên 83 dòng heartbeat lặp = 1 episode |
| 3 | Overview B3 "current status" | — | ❌ | Chuỗi cứng (H1) |
| 4 | Overview Data freshness value | `coverage.data_freshness.evidence` | ✅ | nguyên văn |
| 5 | Overview Data freshness "current status" | — | ❌ | Chuỗi cứng (H1) |
| 6 | Overview Open issues "1 open issue(s)" | `coverage.open_incidents.evidence` | ✅ | |
| 7 | Overview Coverage sample status `PENDING` | — | ❌ | Literal `'PENDING'` tại [:299](global_index/dash/paper/paper.js#L299); bỏ qua 3 gate status |
| 8 | Overview Coverage sample "5/60 days, exits 0/3" | `paper_duration.metrics.{observed,target}` + `exit_path_coverage.metrics.exits` | ✅ | |
| 9 | Overview C1 status `BREACH NOW` | JS tự suy từ `open_mean` vs `spec.max_mean_ticks` | ⚠️ | Gate status backend là `PENDING`; render đỏ (H2) |
| 10 | Overview C1 "OPEN 5/100, STP 0/100" | `c1_slippage.metrics.{open_n,stp_close_n,spec.min_n}` | ✅ | Nhánh STP bất khả thi (H4) |
| 11 | Overview Stop placement "2/10 clean sessions" | `coverage.stp_placement.metrics.{continuous_session_streak,required_continuous_sessions}` | ✅ | |
| 12 | Overview TWS "0/10 proven nights" | `tws_restart_nights.metrics.{restart_nights,required_nights}` | ✅ | |
| 13 | Overview TWS target nút "Open detail" | — | ❌ | Trỏ tới `runner_freshness` (H5) |
| 14 | Gates C1 badge `PENDING` | `c1_slippage.status` | ✅ | Mâu thuẫn với dòng 9 |
| 15 | Gates C1 "OPEN mean +9.00 ticks" | `metrics.open_mean` | ⚠️ | Số học đúng, đơn vị không so sánh được (H3) |
| 16 | Gates C1 "Excluded closes 4" | `metrics.signal_close_with_stop_ref` | ✅ | Loại đúng; đã ghi trong Gaps |
| 17 | Gates C1 raw OPEN N=15 / sum 6.9 | `slip_stats.json` (toàn thời gian) | ⚠️ | So với hiển thị N=5 (epoch); khoảng cách không giải thích (L3) |
| 18 | Gates STP composite `PENDING` | `stp_verification.status` + `stp_placement.status` | ❌ | Loại `current_protection` dù chữ trên màn hình khẳng định có (C3) |
| 19 | Gates STP "failed 2" | `logs.stp_failed` | ⚠️ | Cả hai dòng đều là mock (C1); luật thực thi là `failed_matched_to_trade` (H6) |
| 20 | Gates STP rail "failed = 0" | lẽ ra là `spec.max_trade_matched_failed` | ❌ | Cứng, chặt hơn luật thực thi (H6, M7) |
| 21 | Gates STP "Checks 1" → gate PASS | `paper_inputs.json.stp_verification` (1 dòng) | ⚠️ | Không tồn tại ngưỡng tối thiểu (C2) |
| 22 | Gates STP chip "no false halt evidence" | `logs.b3_halt_lines = 0` | ⚠️ | Dữ liệu đúng, màu **đỏ** (M3) |
| 23 | Gates B3 "Cold starts 0" | `logs.cold_starts` | ❌ | Bộ dò không khớp gì cả (C4a) |
| 24 | Gates B3 "match 164" | `logs.b3_matches` | ⚠️ | Đếm heartbeat, không phải số lần reconcile |
| 25 | Gates TWS "candidate lines 281" | `metrics.candidate_log_lines` | ⚠️ | Gồm 175 disconnect thường lệ + cảnh báo B3 (M1) |
| 26 | Gates coverage rail "60 days / >=3" | lẽ ra là `duration.target`, `target_each` | ❌ | Cứng (M7) |
| 27 | Coverage → Manual intervention "128 candidates" | `logs.manual_intervention_lines` | ⚠️ | Khớp chính chữ `OPERATOR:` của runner (M2) |
| 28 | Coverage → Roll slippage "0 log lines / no roll event" | `logs.roll_slippage_lines` | ⚠️ | Mâu thuẫn với ~51 dòng `C2: Roll` ở dòng 27 (M2) |
| 29 | Coverage → Contract spec "0/4" (offline) / `OBSERVED` (live) | `_local_contract_specs()` trên `BASKET` | ⚠️ | Vũ trụ loại MNKD = 44% số fill (H7) |
| 30 | Coverage → P&L "Paper realised −$43.25" | `statement_pnl_compare.paper_epoch_closed_realized` | ✅ | Không xuất hiện trên Overview (M6) |
| 31 | Coverage → P&L "Paper − backtest +$119.90" | `paper_minus_backtest_realized` | ✅ | Verdict backend `EXPLAINED`, khớp footer |
| 32 | P&L headline `pbRecon` "RECONCILED" | so sánh với chính nó | ❌ | Không thể fail; cũng không được dùng (H8) |
| 33 | Timeline chuỗi Flex cuối −$43.25 | cộng dồn từ `flex_epoch_rebased_closed` | ✅ | Khớp bảng grid; đã kiểm chứng |
| 34 | Thẻ verdict "Timeline Data" | `verdicts.daily` (title "Daily divergence") | ⚠️ | Sai tiêu đề cho section (L4) |
| 35 | Open-position parity "1 / 1" | `open_position_parity.{paper_open_count,replay_open_count}` | ✅ | |
| 36 | Coverage → Log hygiene "319 dropped" | `logs.dropped_test_lines` | ⚠️ | Đếm thiếu — cùng lần chạy test rò 21 dòng không marker (C1) |

### Độ chính xác mô tả nguồn (kiểm cả 7)

| Nguồn hiển thị | Thực tế | Kết luận |
|---|---|---|
| `trade_log.jsonl` | `D:\raits\trade_log.jsonl`, 28 dòng, JSONL | ✅ chính xác (hiển thị không có thư mục, khác với các nguồn có tiền tố `global_index/` — không nhất quán về hình thức) |
| `slip_stats.json` | `D:\raits\slip_stats.json`, tổng/đếm tích lũy | ✅ chính xác; mô tả ghi đúng "cumulative" |
| `global_index/live_state_data.js` | tồn tại, `window.LIVE_DATA = …` | ✅ chính xác |
| `global_index/paper_history.json` | tồn tại, epoch/account/days | ✅ chính xác |
| `monitor/paper_inputs.json` | tồn tại; mô tả liệt kê đúng cả 9 khóa | ✅ chính xác — và ghi đúng "Updated manually" |
| `monitor/paper_pnl_compare.json` | được liệt kê là nguồn của `paper_vs_backtest` | ✅ có trong sources của payload |
| `scheduler_*.log` / `live_day_*.log` | ở gốc repo, 26 file | ✅ pattern đường dẫn chính xác. ❌ **"Retention: no code-level deletion or rotation observed" là gây hiểu nhầm** — chính `scheduler_0810.log` tự ghi `(rolls at midnight)`, và các file cũ hơn epoch tồn tại nhưng bị loại bởi bộ lọc epoch, chứ không phải được giữ-và-dùng |

**Mâu thuẫn gate ↔ coverage tìm thấy:** dòng 9/14 (C1 Overview vs Gates), dòng 18 (STP composite vs chính đầu vào của nó), dòng 28 (manual-intervention vs roll-slippage).

---

## 3. Khuyến nghị UI/UX

### GIỮ

- **Chia 4 tab.** Hoạt động tốt. Overview gọn trong một màn hình ở desktop; không tràn ngang cấp trang ở 1440px hay 390px trên bất kỳ tab nào; 0 lỗi console. Trạng thái tab thuần CSS nên chuyển tab tức thì và sống sót qua refresh 60s.
- **Cấu trúc thẻ purpose / why needed / current status / to pass-unlock.** Cả 7 thẻ render đủ 4 dòng. Đây là cấu trúc đúng cho quyết định promotion — chỉ cần nối dòng "current status" vào dữ liệu (H1).
- **Kỷ luật phân biệt candidate với proof.** Panel TWS và Manual-intervention từ chối rõ ràng việc coi log thô là bằng chứng, và nói ra điều đó trong `detail-note`. Đây chính là lập trường đúng và nên làm khuôn mẫu cho B3 (C4).
- **`status_rules` render inline trên mọi panel Coverage detail.** Người review thấy được định nghĩa PASS/BREACH/MISSING mà không phải rời panel.
- **Layout master–detail của Coverage** với 4 nhóm ngữ nghĩa; cả 15 item đều mở đúng panel chi tiết (đã kiểm từng click).
- **Backend tự viết `verdicts` và đè lên fallback frontend** (`renderVerdict`). Nên mở rộng thêm — nó đưa phán đoán ra khỏi tầng view.

### SỬA

1. ✅ **Nối "current status" vào payload** (H1) — sửa đơn lẻ có giá trị cao nhất trên trang.
2. ✅ **Cho quality breach một cấp thị giác riêng** (H2). `QUALITY_BREACH`, màu vàng, nhãn "sample pending".
3. ✅ **Hiện episode, không hiện heartbeat** cho B3 và mọi bộ đếm suy từ log (C4b). "1 episode · 2 vị thế · 00:05–09:18 · ngày 1 của epoch" là mức ra quyết định được; "100" thì không.
4. ✅ **Đưa spec đang thực thi lên màn hình** thay vì thanh rule cứng (H6, M7) — render mọi thanh rule từ `metrics.spec`.
5. ✅ **Sửa tràn bảng trên mobile** (M4) — hoá ra là ≈20 bảng, không phải 3.
6. ✅ **Thêm thẻ P&L / edge vào Overview** (M6) — công bố **cả hai** góc nhìn tiền, `OBSERVED` chứ không phải blocker.
7. ✅ **Sắp thẻ Overview theo mức độ** (L5) — sắp ổn định, thẻ cùng mức không nhảy chỗ.
8. ✅ **Tạm dừng refresh 60s** (M5) — poll chỉ phát hiện, chip trao quyền repaint cho người đọc.
9. ✅ **Suy màu chip từ dữ liệu, không từ chữ** (M3).
10. ❌ **Làm tooltip dễ phát hiện.** Nhãn của `metricCard` mang `data-tooltip` + `tabindex=0` nhưng không có dấu hiệu thị giác nào (không gạch chân, không icon). Trên thiết bị cảm ứng không có hover — **mọi định nghĩa metric đều vô hình trên mobile**. Thêm gạch chân chấm và chạm-để-bật. **Chưa làm** — không nằm trong M1–M8/L3–L5, phát hiện trong lúc rà UI.
11. ✅ **Thêm phân rã theo từng mã vào nhóm Current Quality của C1** (H3) — kèm quy đổi đô-la và cảnh báo về con số gộp.
12. ✅ **Hiện bút toán đối soát cạnh lưới P&L** — bảng `ledgerAdjustmentBlock`. Bút toán không ai thấy được là một ghi chú, không phải một chốt kiểm soát.

### BỎ hoặc GỘP

- **Bỏ** các hàm chết `pnlCompareRows`, `lifecycleCompareRows`, `pnlDailyRows` (L1) — và các test đang ghim chúng (xem §4).
- **Bỏ** 7 element ID mồ côi và các lời gọi `setText` tương ứng (L2).
- **Bỏ** dòng `pbRecon` tự so sánh và các fallback `?? self` tại các điểm gọi `reconcileStatus` (H8).
- **Gộp** `state_persist` và `current_protection` — cả hai đọc `live_positions.json`, cả hai render cùng bảng `stateProtectionPositionRows`, và status rules chồng lấn. Một panel "Trạng thái sổ lệnh hiện tại" với hai verdict.
- **Gộp** `runner_freshness` vào `data_freshness` — cả hai là độ tươi của đầu vào; việc để tách chính là thứ khiến cross-reference TWS (H5) trông có vẻ hợp lý.
- **Đổi tên** "Coverage progress" (tab Gates) → "Sample coverage", để không nhầm với tab "Coverage".
- **Đổi tên** "STOP PROTECTION READINESS" (tab Gates) → "Stop protection (verify + placement)" cho tới khi `current_protection` thực sự nằm trong composite (C3).
- **Đổi tên** verdict "Timeline Data Rows", hoặc ngừng dùng lại `verdicts.daily` cho hai section (L4).

---

## 4. Lỗ hổng test

`monitor/test_dashboard_backend.py` có 89 test pass, nhưng phần dành cho paper dashboard là một **bản kiểm kê chuỗi**, không phải bộ test hành vi. `test_paper_dashboard_exposes_c1_observed_detail` ([:644-789](monitor/test_dashboard_backend.py#L644-L789)) là ~145 dòng `assert "<literal>" in source`.

Ở ba chỗ nó **phản tác dụng**:

- [:700](monitor/test_dashboard_backend.py#L700) `assert "BREACH NOW" in source` — **ghim chặt lỗi H2.** Sửa lỗi CSS token là test này gãy.
- [:710](monitor/test_dashboard_backend.py#L710), [:713](monitor/test_dashboard_backend.py#L713), [:726](monitor/test_dashboard_backend.py#L726) — khẳng định `pnlCompareRows`, `lifecycleCompareRows`, `pnlDailyRows` tồn tại, **ghim code chết** (L1).
- [:703-705](monitor/test_dashboard_backend.py#L703-L705) — khẳng định đúng chuỗi chữ cứng của thẻ blocker trong H1, ghim luôn các chuỗi "current status" tĩnh.

| Thiếu coverage | Test đề xuất |
|---|---|
| Đầu vào của STP composite (C3) | Fixture: `current_protection.status = BREACH`, `stp_verification = PASS`, `stp_placement = PENDING`. Khẳng định composite là `BREACH`. Test hàm thuần `compositeStatus` qua node, hoặc assert render jsdom trên `#stpProgressStatus`. |
| Ngưỡng STP verification (C2) | Khẳng định `_stp_input_status([one_verified_row], logs)` trả `SPEC_GAP` (không phải `PASS`) khi chưa có `stp_verification_spec`; chỉ `PASS` khi `len(items) >= spec.min_checks`. |
| Phát hiện cold-start (C4a) | Nạp log chứa dòng thật `Scheduler started. Ctrl-C to stop.` và khẳng định `cold_starts >= 1`. Bộ log hôm nay sẽ fail test này — và đó chính là ý nghĩa của nó. |
| Gộp episode B3 (C4b) | Nạp 20 dòng `B3: 2 mismatch(es)` giống nhau cách 5 phút; khẳng định `episodes == 1`, không phải `mismatches == 40`. |
| Hygiene khối test (C1) | Nạp một khối liên tục cùng timestamp trong đó chỉ 1 dòng có marker; khẳng định **mọi** dòng trong khối bị loại và `excluded_blocks == 1`. |
| Vũ trụ contract spec (H7) | `assert set(_local_contract_specs()) >= set(BASKET) \| set(SPECS)` — fail ngay hôm nay, bắt được lỗ hổng MNKD. |
| Khả năng so sánh đơn vị C1 (H3) | Khẳng định payload metrics của C1 mang `by_inst` means và một tổng hợp `slip_usd`. |
| Tính toàn vẹn của reconcile (H8) | Unit-test `reconcileStatus`: cùng một tham chiếu hai lần → raise hoặc trả `UNAVAILABLE`; một toán hạng `null` → `UNAVAILABLE`, không bao giờ `RECONCILED`. |
| **Contract payload cho status** | Mở rộng `test_paper_evidence_payload_contract_is_stable` ([:611](monitor/test_dashboard_backend.py#L611)) — hiện chỉ kiểm tra *sự tồn tại* của khóa. Thêm: mọi `status` ∈ từ vựng đóng `{PASS, PENDING, BREACH, OBSERVED, MISSING, NEEDS_DECISION, SPEC_GAP, STRUCTURAL_GAP}`; mọi `metrics` của gate mang đủ field mà panel của nó đọc; mọi metric số đều hữu hạn. |
| **Tính hợp lệ của target cross-reference** | Test tĩnh trên `paper.js`: trích mọi literal `data-coverage-ref="X"` và khẳng định `X ∈ coverage keys` do reader phát ra. Hôm nay không bắt được gì — cần mở rộng thành **bản đồ target kỳ vọng** (`tws_restart_nights → tws_restart`, không phải `runner_freshness`) để bắt H5. |
| **DOM smoke (browser)** | Playwright, ~80 dòng, cả 4 kiểm tra đã chứng minh chạy được trong audit này: (a) click mỗi label tab lật `input[name=paper-tab]:checked` và hiện panel tương ứng; (b) mọi click `[data-coverage-ref]` và `[data-gap-related]` mở Coverage detail có `<h3>` bằng đúng tiêu đề kỳ vọng; (c) `documentElement.scrollWidth <= clientWidth` ở 1440/1024/390 trên cả 4 tab; (d) với mọi `.trade-table`, `scrollWidth - clientWidth == 0 \|\| getComputedStyle(el).overflowX == 'auto'` — riêng assertion này bắt được M4. |
| **Contract status→màu** | Khẳng định màu computed cho mỗi status token: `BREACH`→đỏ, `PENDING`/quality-breach→vàng, `PASS`/`OBSERVED`→xanh. Bắt trực tiếp H2 (`class='blocker-card breach now'` cho ra màu đỏ). |
| **Không có chữ status tĩnh** | Khẳng định text `<dd>` "current status" của mỗi thẻ blocker xuất hiện trong `evidence`/`metrics` của payload, không chỉ trong `paper.js`. Bắt H1 và ngăn nó quay lại. |

**Hành động:** Thay bản kiểm kê chuỗi bằng những test trên. Chỉ giữ lại các assertion mã hóa bất biến thật (ví dụ [:1167](monitor/test_dashboard_backend.py#L1167) `test_backend_routes_are_read_only` và [:1173](monitor/test_dashboard_backend.py#L1173) `test_backend_does_not_import_runner_or_write_state` là test tốt).

### Tình trạng: 89 → 142 test (dashboard), 10 → 13 (statement)

Ba assertion phản tác dụng nêu trên **đã gỡ** cùng lúc với lỗi mà chúng ghim. Các mục thiếu coverage trong bảng trên đã có test, trừ hai mục ghi rõ ở dưới.

Test mới của batch 3, theo nhóm:

| Nhóm | Test | Ghim điều gì |
|---|---|---|
| M6 | `overview_publishes_both_epoch_pnl_views_side_by_side` | Không con số nào một mình được nhận là "kết quả" |
| M6 | `overview_epoch_pnl_is_observed_not_a_blocker` | Thẻ không âm thầm biến thành blocker khi chưa có ngưỡng |
| M6 | `overview_epoch_pnl_says_whether_the_gap_is_fully_accounted_for` | Cả hai nhánh: khớp bút toán / còn dư chưa giải thích |
| M6 | `overview_epoch_pnl_reports_missing_rather_than_zero_when_absent` | Thiếu dữ liệu ra `--`, không phải `$0.00` |
| M5 | `background_poll_does_not_repaint_while_the_reader_is_reading` | Poll nền không cướp chỗ đọc |
| M5 | `unchanged_payload_does_not_raise_a_refresh_chip` | Chip không kêu khi không có gì đổi |
| G2 | `flex_reconcile_basis_is_read_from_the_lots_not_hardcoded` | Mô tả nguồn tiền suy từ dữ liệu |
| G2 | `flex_reconcile_basis_warns_when_any_lot_falls_back_to_local_point_value` | Lẫn lộn nền tảng không được đọc thành đã-đối-chiếu |
| G2 | `flex_reconcile_basis_is_absent_rather_than_asserted_with_no_lots` | Không lot thì không khẳng định gì |
| G1/G3 | `st11_pnl_comes_from_broker_proceeds_not_our_own_multiplier` | Đúng lỗi C8: dựng bằng `point_value` cho −110, broker là −1100 |
| G3 | `st12_a_lot_without_proceeds_reports_no_pnl_rather_than_a_local_guess` | Không fallback im lặng về điểm mù |
| G3 | `st13_a_partial_close_does_not_borrow_the_whole_fills_proceeds` | Close lệch size không ghi gấp đôi tiền |

**Còn thiếu, cố ý:**

- **Contract status→màu** — chưa làm. `QUALITY_BREACH` và `STRUCTURAL_GAP` đã có test cấp class, nhưng chưa có test màu computed cho toàn bộ từ vựng.
- **DOM smoke đầy đủ** — bốn kiểm tra đã chạy thủ công qua Playwright trong audit này (0 lỗi console, 0 tràn ngang ở 1440/390, mọi `data-coverage-ref` mở đúng panel), nhưng **chưa đóng gói thành test tự động**. Chúng đang là kiểm chứng một lần, không phải hàng rào.

---

## 5. Kết luận cuối

> **CẬP NHẬT 2026-08-14** — phần dưới là kết luận **tại thời điểm audit**, giữ nguyên làm mốc lịch sử. Kết luận hiện hành ở mục 5b cuối tài liệu.

### Dashboard đã an toàn để làm cơ sở quyết định paper → live chưa?

**CHƯA.**

Nó an toàn — và thực sự hữu ích — với vai trò **công cụ điều hướng bằng chứng**: xuất xứ nguồn, kỷ luật candidate-vs-proof, chuỗi reconcile P&L, và cấu trúc drill-down đều được xây tốt và phần lớn trung thực về giới hạn của chính nó.

Thứ khiến nó chưa dùng được để ra quyết định là: **ba trong bốn tín hiệu về bảo vệ stop và reconcile đang sai theo đúng chiều nguy hiểm**, và sai theo cách người đọc cẩn thận cũng không phát hiện được từ màn hình:

| # | Vấn đề |
|---|---|
| **C2** | PASS duy nhất trên bảng (stop verification) dựa trên 1 dòng JSON tự khai, không ngưỡng |
| **C3** | Status stop tổng hợp **về mặt cấu trúc không thể chuyển đỏ** khi có vị thế live không được bảo vệ |
| **C4** | BREACH duy nhất đang chi phối verdict cấp trang được khẳng định trên một điều kiện mà code chưa bao giờ quan sát được, với con số là artifact của logging |
| **C1** | Con số đỏ "2 failed stop placements" là **100% output của test mock** |

**Hệ quả ròng:** dashboard hiện **đánh giá thấp** rủi ro bảo vệ stop và **đánh giá cao** rủi ro reconcile. Cả hai sai lệch đều đẩy về phía một quyết định promotion sai — một cái bằng sự an tâm giả, một cái bằng báo động giả sẽ huấn luyện người review dần bỏ qua B3.

---

### Phải sửa gì trước khi dựa vào nó

#### Chặn (tính đúng đắn của tín hiệu an toàn)

1. **C3** — thêm `current_protection` vào STP composite. Sửa một dòng; lợi ích an toàn lớn nhất trên trang.
2. **C2** — thêm `stp_verification_spec.min_checks`; trả `SPEC_GAP` cho tới khi có spec.
3. **C1** — loại trừ log test theo khối, kèm `excluded_blocks` trong payload. Tính lại STP `failed`, B3 mismatch, và candidate manual-intervention sau đó.
4. **C4** — sửa `_COLD_START`; gộp heartbeat B3 thành episode.

#### Chặn (tính đúng đắn của thứ người review đọc)

5. **H1** — suy "current status" của Overview từ payload.
6. **H2** — ngừng render một đọc chất-lượng-chưa-đủ-mẫu như một BREACH đầy đủ.
7. **H8** — không phép reconcile nào được so sánh với chính nó hoặc suy biến thành luôn-pass.

#### Bắt buộc trước khi các con số có thể trích dẫn được

8. **H3 / H4** — trung bình C1 theo từng mã; mục tiêu STP-close khả thi (hoặc gắn cờ bất khả thi tường minh).
9. **H7** — đưa MNKD vào contract-spec guard; xóa multiplier trùng lặp trong `paper.js`.
10. **H5 / H6** — sửa target cross-reference TWS và thanh rule STP.

#### Sau đó

M1–M8 cho chất lượng tín hiệu và khả dụng trên mobile, và thay bộ test kiểm-kê-chuỗi (§4) — nếu không, sửa H1/H2/L1 sẽ làm gãy test suite, mà đó chính là dấu hiệu rõ nhất cho thấy test hiện tại đang đo sai thứ.

---

---

## 5b. Kết luận hiện hành (2026-08-14, cuối phiên)

### Phát hiện quan trọng nhất không nằm trong dashboard

**Lệnh MNKD được định tuyến sang hợp đồng gấp 10 lần kích thước đã kiểm định**, trong nhiều tháng. Broker tính −$1.400 cho vòng lệnh mà sổ ghi −$140. Rủi ro tiền thật của rổ NKD gấp 10 lần dự định; ký quỹ ~$9.000 thay vì $900.

Đường đi tới phát hiện đó đáng ghi lại, vì nó không phải kết quả của việc tìm lỗi định tuyến:

```
H7 (guard chỉ phủ 4/6 mã, MNKD không được hỏi)
  -> đi hỏi thẳng IBKR xem multiplier MNKD là bao nhiêu
    -> IBKR trả multiplier 5, specs.py ghi 0.5
      -> C8: lệnh chạy vào hợp đồng full-size
```

**Một lỗ hổng "phủ sót" trong panel quan sát đã che lỗi định tuyến tiền thật.** Đó là lập luận mạnh nhất cho việc panel guard phải phủ đủ, chứ không chỉ phủ phần dễ.

### Đã thay đổi gì về bản chất

Bốn tín hiệu sai hướng nêu ở mục 5 **đã xử lý xong cả bốn**:

- **C1** — bằng chứng mock không còn được tính. `stp_failed` 2 → 0, `manual_intervention` 128 → 0
- **C2** — gate PASS giả đã biến mất. **Không còn gate nào tự nhận PASS**
- **C3** — panel stop chuyển đỏ được khi có vị thế live không bảo vệ
- **C4** — B3 từ *"100 mismatch"* thành **1 episode / 2 vị thế / 50 phút**; `cold_starts` 0 → 8

Thêm **C5** (vá tạm: `STRUCTURAL_GAP` thay vì giả vờ là thiếu mẫu), **H1/H6** (UI đọc từ payload thay vì chữ cứng), **C8** (định tuyến).

**Batch 3 bổ sung một thay đổi bản chất nữa:** phép đối chiếu Flex giờ dùng **tiền của broker** chứ không phải tiền tự nhân lại (Phụ lục G). Trước đó nó ra `paper_minus_flex = 0.00` suốt bốn ngày trong khi tài khoản lệch $1.260 — một phép kiểm cùng sai ở cả hai vế thì không kiểm gì cả. Giờ nó ra **+$1.260,00**, khớp bút toán đối soát tới từng xu từ hai đường suy ra độc lập.

### Dashboard đã dùng được để ra quyết định chưa?

**Các con số thì dùng được. Bằng chứng thì vẫn mỏng.**

Mọi con số hiển thị giờ đối chiếu ngược về dữ liệu nguồn được, và không gate nào hứa điều nó chưa chứng minh. Đó là điều kiện cần, và trước phiên này thì chưa có.

Nhưng còn ba thứ chặn quyết định, **không cái nào sửa được bằng code**:

1. **Bằng chứng quá ít** — 5 ngày, 9 fill, 1 regime. Với nhịp 1 fill/ngày, C1 cần ~100 ngày để đủ mẫu OPEN, **dài hơn chính mục tiêu 60 ngày** của gate duration.
2. **Rổ NKD trong epoch này chạy sai kích thước 10 lần.** Tín hiệu, giá, P&L chiến lược và slippage-theo-tick vẫn dùng được (xem C8). Nhưng **hành vi ký quỹ và chất lượng khớp thì không** — chúng thu được trên hợp đồng khác.
3. **`exit_path_coverage` không thể đạt** cho tới khi runner ghi `exit_reason` (C5). Gate giờ nói thật về điều đó thay vì giả vờ đang chờ mẫu.

### Còn nợ, cần quyết định của chủ dự án

| Việc | Vì sao chặn |
|---|---|
| ~~`paper_pnl_compare` dùng `Proceeds`~~ | ✅ **Đã làm** — cả hai đường ghép lot, 9/9 lot (Phụ lục G.1, G.3) |
| ~~`ibkr_symbol` vào `Contract`~~ | ✅ **Đã làm** — trường bắt buộc, map suy ra, 3 test + mutation (Phụ lục I.1) |
| ~~Chống lệch artifact `paper_pnl_compare.json`~~ | ✅ **Đã làm** — `source_signature` hash nội dung, banner STALE (Phụ lục I.2) |
| ~~Coverage panel cho bằng chứng TWS restart~~ | ✅ **Đã làm** — 4/4 gap có nút mở panel (Phụ lục I.3) |
| ~~Duyệt ngưỡng lỗ chặn go-live~~ | ✅ **Đã duyệt 2026-08-15 và đã triển khai** — spec + 21 band + panel document đầy đủ trên dashboard (Phụ lục H.7) |
| Cảnh báo khi band lệch baseline backtest | Band đóng băng trong `paper_inputs.json`; `backtest_curve.json` đổi mà band không đổi thì **chưa có gì báo** |
| Sửa runner cho C5/C6 | `exit_reason` + hợp nhất schema CLOSE. Không gấp, nhưng gate không đạt được nếu thiếu |
| ~~`min_n` cho nhánh STP close (H4)~~ | ✅ **Đã duyệt 2026-08-15** — 30 (gộp). Tỉ lệ STP vẫn là **giả định 30%**, ghi rõ trong spec (Phụ lục K.5) |
| Warm cache lúc backend khởi động | Quét cold-cache 41,7s; timeout client đã nâng lên 90s nhưng đó là vá triệu chứng (Phụ lục I.4) |
| ~~Spec C1 theo từng mã~~ | ✅ **Đã duyệt 2026-08-15** — OPEN theo mã (N≥20/mã), trần 5→3 tick, kèm khoảng tin cậy (Phụ lục K) |

### Việc phát sinh ngoài dashboard

**Bộ test đang ghi output vào log production.** `scheduler_0810.log` chứa 54 khối / 1160 dòng của cùng một kịch bản mock MES replay suốt ngày. Dashboard đã lọc được ở phía đọc, nhưng nguồn phát vẫn còn — nên tách log handler của test khỏi log production, nếu không mọi công cụ đọc log khác đều dính cùng vấn đề.

### Kỷ luật đã dùng, nên giữ

Mọi fix trong hai batch đều được **mutation-test**: tạm gỡ fix, xác nhận test fail đúng chỗ, rồi khôi phục. Cách này đã bắt được:

- `assert 0 == 1` khi trả `_COLD_START` về regex hỏng
- `assert 20 == 1` khi phá phép gộp episode
- `assert '+$0.00' == '--'` khi gỡ guard của `priceUsd`
- `assert []` khi gỡ chuẩn hoá backslash
- `assert 'PASS' == 'SPEC_GAP'` khi trả gate STP về hành vi cũ
- `- STRUCTURAL_GAP / + PENDING` khi trả exit-path về `PENDING`
- `assert 36 == 18` khi gỡ guard detect-only của poll (M5)

### Ba bài học về phương pháp, rút ra từ batch 3

**1. Chuỗi mô tả code sẽ cũ đi, và không ai được báo.** `flex_reconcile_basis` là câu viết cứng nói tiền lấy từ `point_value`; sửa xong Proceeds thì nó mô tả code không còn tồn tại — trên đúng panel mà việc duy nhất là báo tiền đến từ đâu. Suy ra từ dữ liệu thay vì viết ra. Và ngay khi suy ra, nó tự tố cáo fix mới làm được 4/9.

**2. Fixture phải đóng vai nguồn dữ liệu, không mượn bảng của production.** Test `pair_fifo` cũ dựng trade không có `Proceeds` — tức là sao kê IBKR không bao giờ gửi. Sửa thành fixture tự khai multiplier broker (`_BROKER_MULTIPLIER` viết ngay trong file test); đọc từ bảng production mà `pair_fifo` cũng đọc thì mọi assert P&L tự đồng ý với chính nó.

**3. Đừng ghim chuỗi bootstrap khi test JS bằng Node.** Harness `_run_paper_js_probe` từng match nguyên văn `"  load();\n  window.setInterval(load, 60000);\n})();"`. Đổi chỗ nối refresh là **8 test đỏ cùng lúc**, đọc như 8 hành vi hỏng thay vì 1 fixture cũ. Chèn export vào trước `rindex("\n})();")`.

---

## PHỤ LỤC D — Gốc rễ: ba danh tính hợp đồng, không chỗ nào giữ đủ cả ba

### D.1 Vì sao tên nội bộ là `MNKD` chứ không phải `MNK`

Quy ước trong Rổ 4 (`futures/basket.py`):

| Tên nội bộ | `data_symbol` | Ticker IBKR thật |
|---|---|---|
| MES | ES | **MES** ✓ trùng |
| MNQ | NQ | **MNQ** ✓ trùng |
| MYM | YM | **MYM** ✓ trùng |
| M2K | RTY | **M2K** ✓ trùng |

Quy ước: `name` = **ticker thật của hợp đồng micro**, `data_symbol` = **mã full-size** dùng lấy lịch sử giá. Với cả bốn mã, `name` trùng ticker IBKR nên **không cần bảng ánh xạ nào** — hệ thống ngầm giả định "tên nội bộ chính là ticker".

Ba trong bốn theo mẫu "M + mã full" (ES→MES, NQ→MNQ, YM→MYM). Áp mẫu đó cho Nikkei ra **M + NKD = MNKD**. CME đặt tên nó là **MNK**.

Mỉa mai: **M2K đã phá mẫu ngay trong cùng file** — micro của Russell là M2K chứ không phải MRTY. Phản ví dụ nằm sẵn đó.

### D.2 Chuỗi nhân quả đầy đủ

1. Hệ thống ngầm giả định "tên nội bộ = ticker IBKR" — đúng với 4/4 mã Rổ 4
2. Tác giả suy `MNKD` theo mẫu, tự đánh dấu `(confirm ticker w/ IBKR)`
3. `MNKD` không phải ticker thật → lệnh sẽ lỗi
4. Ai đó thêm `_RAITS_TO_IBKR` để chữa
5. Họ điền **mã Nikkei duy nhất kiểm chứng được: `NKD`** — con full-size
6. Lệnh chạy vào hợp đồng gấp 10 lần

Lỗi không nằm ở việc *có* bảng ánh xạ — bảng đó đúng. Lỗi là **nó được điền bằng mã kiểm chứng được thay vì mã đúng**, vì mã đúng chưa ai đi tra.

### D.3 Phát hiện then chốt: `data_symbol` của `specs.py` không ai đọc

```python
# update_futures_data.py:66-72
for name, cfg in BASKET.items():
    jobs.append(dict(name=name, symbol=cfg.data_symbol, ...))   # Rổ 4 ĐỌC field
jobs.append(dict(name="MNKD", symbol="NKD", out=nkd_path))      # MNKD HARDCODE
```

Mọi chỗ dùng `data_symbol` — `basket.py:19,59` và `update_futures_data.py:69` — **đều chỉ cho Rổ 4**. Hai dòng khai trong `specs.py` không có nơi tiêu thụ. Đường dữ liệu thật của MNKD là chuỗi hardcode ở ba file: `update_futures_data.py:71`, `fix_offset_step.py:74`, `repair_parquet_utc.py:52`.

Bức tranh thật trong file tự nhận là *"the ONE source of pv/tick"*:

| Danh tính | Giá trị | Trạng thái |
|---|---|---|
| `name` | `MNKD` | ✅ dùng làm khoá — nhưng là **ticker đoán** |
| `data_symbol` | `NKD` | ❌ **khai mà không ai đọc** |
| Ticker IBKR | `MNK` | ❌ **không khai ở đây**, sống trong `ibkr_broker` |

Nếu `data_symbol` **có** được đọc, thì `update_futures_data.py:71` đã là `SPECS["MNKD"].data_symbol`, và người viết `_RAITS_TO_IBKR` sẽ thấy ngay rằng nguồn dữ liệu và nơi gửi lệnh là hai thứ khác nhau — đúng chỗ họ nhầm.

**Bài học tổng quát: trường khai mà không ai đọc là trường không bao giờ được kiểm chứng.** `data_symbol` đúng suốt thời gian qua, và sự đúng đó vô nghĩa.

### D.4 Khuyến nghị

1. Thêm `ibkr_symbol` vào `Contract`; `ibkr_broker` đọc từ đó thay vì giữ bảng riêng
2. `update_futures_data.py:71` đọc `SPECS["MNKD"].data_symbol` thay vì hardcode
3. Test: mọi trường danh tính trong `Contract` phải có ít nhất một nơi đọc

**Không khuyến nghị đổi tên nội bộ `MNKD` → `MNK`.** Về khái niệm thì đúng, nhưng `MNKD` nằm trong `trade_log.jsonl` lịch sử, `live_positions.json`, `paper_history`, replay snapshot, artifact backtest, hàng chục test, dashboard và cả bút toán đối soát. Đổi tên giữa epoch paper sẽ cắt đứt tính liên tục của bằng chứng.

---

## PHỤ LỤC E — Xác minh tương đương NKD ↔ MNK

Backtest chạy trên **giá NKD** với **kinh tế MNKD**. Trước khi chuyển định tuyến sang MNK, đã đo xem hai hợp đồng có thật sự thay thế được nhau không.

### E.1 Vì sao backtest dùng dữ liệu NKD — hai lý do, cả hai đã kiểm

**Lịch sử** — đếm bản ghi Databento (`GLBX.MDP3`, `ohlcv-1d`, `stype_in=parent`):

| Năm | `NKD.FUT` | `MNK.FUT` |
|---|---:|---:|
| 2018–2023 | 947–1.068 / năm | **422 — ký hiệu không tồn tại** |
| 2024 | 995 | **58** (chỉ Q4) |
| 2025 | 869 | 349 |
| 2026 | 562 | 250 |

MNK có dữ liệu từ **2024 Q4**. Parquet backtest phủ **2018-01-01 → 2026-08-14 (8,6 năm, 2.034.039 bar)**. Không thể chạy WFO trên MNK.

**Thanh khoản** — `specs.py` ghi rõ: NKD là *"Full — liquid backtest data"*.

> **Đính chính quy trình:** lần đầu tôi kết luận "MNK thiếu lịch sử" bằng cách so **một tháng hợp đồng** (`MNKU6`, 108 bar) với **chuỗi liên tục** 8,6 năm — sai đối tượng. Bằng chứng IBKR tôi trưng ra (`ContFuture` ~1,4 năm cho *cả hai*) không đỡ nổi kết luận, vì IBKR không phải nguồn dữ liệu. Kết luận trùng nhau chỉ là may.

### E.2 Giá — phải đo bằng mid-price, không phải last-trade

| Cách đo | Kết quả | Đánh giá |
|---|---|---|
| IBKR daily close | 0,32 điểm | quá lạc quan |
| Databento last-trade, cặp tháng khớp | 24–43 điểm | quá bi quan — **giá khớp cuối bị cũ** |
| **Databento mid-price (bbo-1m)** | **2,50 điểm = 0,50 tick** (trung vị) | ✅ đúng |

MNK in giá thưa hơn nên last-trade xa hơn, nhưng **giá thật bám nhau trong nửa tick**.

### E.3 Spread, độ sâu, độ liên tục (bbo-1m, tháng 7/2026)

| | NKD | MNK |
|---|---|---|
| Spread trung vị | **4,00 tick** | **4,00 tick** |
| Spread trung bình | 5,21 tick | 5,72 tick |
| Độ sâu bid/ask trung vị | **2 / 2 lot** | **10 / 10 lot** |
| Phút có báo giá hai chiều | 30.279 | 29.964 |

**Độ sâu MNK tốt hơn** ở quy mô 1 hợp đồng. Tính theo notional thì NKD sâu gấp đôi, nhưng 10 lot tại touch thoải mái hơn 2 lot.

**Xác nhận cost model:** spread trung vị 4 tick trên **cả hai** → vượt spread từ mid tốn đúng **2 tick/phía**, khớp giả định `slippage_ticks_per_side` của backtest.

### E.4 Khối lượng và ngày mỏng

Trên 189 ngày chồng nhau (3 cặp tháng hợp đồng):

| Ngưỡng | NKD | MNK |
|---|---|---|
| < 200 lot | 9 / 189 | 33 / 189 |

Nhưng **29/33 ngày mỏng của MNK là Chủ nhật** — phiên Globex tối CN, mà NKD cũng chỉ đạt trung vị 282 lot so với ~5.000 ngày thường.

Chỉ tính T2–T6 (159 ngày):

| Ngưỡng | NKD | MNK |
|---|---|---|
| < 100 lot | **2 / 159** | **2 / 159** |
| < 200 lot | 2 / 159 | 4 / 159 |
| < 500 lot | 2 / 159 | 11 / 159 |

Bốn ngày T2–T6 của MNK dưới 200 lot đều là ngày lễ: Giáng sinh (24, 25/12), Tết dương, Good Friday. **Hai ngày NKD cũng dưới 200 lot là đúng hai trong bốn ngày đó.**

Xu hướng: MNK/NKD tăng từ **0,20** (12/2025) lên **0,35–0,52** (giữa 2026), nhưng **nhiễu, chưa ngang bằng** — 30 ngày gần nhất MNK ≥ NKD **0/30**, tỷ lệ trung vị 2,79×. Sàn thanh khoản vững: **thấp nhất 857 lot, không ngày nào dưới 500**.

**Cảnh báo còn lại:** nửa phiên ngày lễ, MNK mỏng đi không cân xứng (Good Friday 8,9× so với 3,47× thường ngày).

### E.5 So sánh đặc tả hợp đồng (IBKR `reqContractDetails`)

| | NKD | MNK |
|---|---|---|
| multiplier | 5 | **0,5** = `specs.point_value` ✓ |
| minTick | 5,0 | **5,0** = `specs.tick` ✓ |
| tick_value | 25,0 | **2,5** = `specs.tick_value` ✓ |
| exchange / currency / secType | CME / USD / FUT | giống ✓ |
| minSize / sizeIncrement | 1,0 / 1,0 | giống ✓ |
| tradingHours / liquidHours | — | **giống hệt** ✓ |
| `orderTypes` | 44 loại | **44 loại, không lệch một cái** ✓ |
| **Ngày đáo hạn U6** | lastTrade 20260910, real 20260911 | **khớp tuyệt đối** ✓ |
| **Ngày đáo hạn Z6** | lastTrade 20261210, real 20261211 | **khớp tuyệt đối** ✓ |
| `validExchanges` | CME, **QBALGO** | CME |

`STP`, `STPLMT`, `MKT`, `LMT`, `GTC`, `TRAIL` — MNK hỗ trợ đủ. Ngày đáo hạn khớp nên `ROLL_SCHEDULE` sao chép từ NKD là đúng.

**Khác biệt duy nhất: QBALGO** — đích định tuyến thuật toán của IBKR, MNK không có. Không ảnh hưởng: `_IBKR_EXCHANGE` chốt `CME`, và runner chỉ gửi `MarketOrder` (`:631,:1422,:1475`), `LimitOrder` (`:628`), `StopOrder` (`:939`) — không chỗ nào đặt `algoStrategy`. Chỉ là ghi nhận nếu sau này muốn dùng algo chia lệnh khi tăng quy mô.

### E.6 Rủi ro tương lai — chuỗi tháng niêm yết ngắn hơn

```
NKD niêm yết 15 tháng: U6 ... Z1 (tới 2031)
MNK niêm yết  2 tháng: U6, Z6
```

`ROLL_SCHEDULE` có dòng `("2026-12-04", "202612", "202703")`. NKD có `NKDH7`; **MNK hiện chưa có `MNKH7`**. Nếu CME chưa niêm yết trước 2026-12-04 thì roll sẽ tạo ra hợp đồng không giải được.

**Roll kế tiếp (2026-09-04, U6→Z6) an toàn** — cả hai đều có Z6. Đã thêm guard, xem Phụ lục F.

---

## PHỤ LỤC F — Guard giải hợp đồng

### F.1 Vấn đề

Ba call site (`ibkr_broker.py`: lấy bar, **đặt lệnh**, tra giá) trùng lặp cùng 8 dòng dựng hợp đồng, cả ba kết thúc bằng `ib.qualifyContracts(contract)`.

**`qualifyContracts` không raise.** ib_insync để `conId = 0` và chỉ log cảnh báo. Request vẫn đi ra với hợp đồng IBKR chưa từng xác nhận, và lỗi hiện ra dưới dạng khác — thiếu bar, hoặc lệnh không xuất hiện.

Hai chế độ hỏng, cả hai trước đây lọt im lặng:

| Chế độ | Hành vi cũ |
|---|---|
| Không có `ROLL_SCHEDULE` | rơi xuống `ibi.Future(sym)` không định danh → IBKR báo ambiguous |
| Tháng sàn không niêm yết | `conId=0`, request vẫn gửi |

Chế độ 1 chính là thứ MNK sẽ gặp ngay lần đặt lệnh đầu tiên sau khi đổi định tuyến, vì `ROLL_SCHEDULE` khi đó chỉ có khoá `NKD`.

### F.2 Đã sửa

Gom ba call site thành `_front_month_contract(ib, ibi, inst)`, raise `ContractResolutionError` với tên mã và hướng xử lý cho cả hai chế độ.

Kèm `test_sb6` (thiếu `ROLL_SCHEDULE`) và `test_sb7` (`conId=0` sau qualify). Mutation-test: gỡ nhánh nào thì test tương ứng fail.

Test không fail trên code lỗi là test vô giá trị. Đây là tiêu chuẩn nên áp cho các batch còn lại.

---

## PHỤ LỤC G — Nền tảng tiền của phép đối chiếu Flex

Ba phát hiện nối nhau, tìm ra theo đúng thứ tự này. Mỗi cái lộ ra vì cái trước đã được sửa.

### G.1 Phép đối chiếu dựng tiền bằng `point_value` cục bộ nên tự triệt tiêu sai multiplier

Phụ lục B mô tả cơ chế; đây là kết quả sau khi sửa.

`paper_pnl_compare.py` lấy giá, số lượng và cách ghép lot từ sao kê broker, nhưng **tiền thì tự nhân lại** bằng `global_index.statement.point_value`. Sổ paper cũng dùng đúng bảng đó. Nên khi MNKD khớp ở hợp đồng gấp 10 lần, sai số xuất hiện ở **cả hai vế** của phép trừ và triệt tiêu:

```
paper_minus_flex_epoch_rebased_realized = 0.00     ← suốt bốn ngày
```

Một phép kiểm ra 0.00 vì cả hai vế cùng sai theo cùng một cách thì không kiểm gì cả.

**Đã sửa:** cả hai đường ghép lot đổi sang cộng trường `Proceeds` của sao kê. `Proceeds` là tiền broker ký nhận — âm khi mua, dương khi bán, luôn bằng giá × số lượng × multiplier của hợp đồng **thực sự khớp**. Cộng hai chân là số đã thực hiện.

Không có fallback im lặng về `point_value`: thiếu Proceeds thì `pnl = None`. Fallback chính là điểm mù.

**Kết quả:**

| | Trước | Sau |
|---|---:|---:|
| `flex_epoch_rebased_realized` | −43.25 | **−1,303.25** |
| `paper_minus_flex_epoch_rebased_realized` | 0.00 | **+1,260.00** |

+$1.260,00 khớp bút toán đối soát (Phụ lục C) **tới từng xu**, từ hai đường suy ra độc lập.

### G.2 Chuỗi mô tả nguồn tiền là literal cứng — và thành sai ngay khi G.1 được sửa

`flex_reconcile_basis` là một câu viết cứng trong `paper_evidence_reader.py`, nói tiền lấy từ `point_value` cục bộ. Sau G.1 nó mô tả code **không còn tồn tại** — trên đúng panel mà việc duy nhất là báo tiền đến từ đâu.

Đây là dạng lỗi mà bản audit này tồn tại để chống: **báo cáo trung thực về nguồn gốc số liệu**. Một câu văn mô tả code sẽ cũ đi, và không có gì báo cho ai biết.

**Đã sửa:** `_flex_reconcile_basis(trade_compare)` **suy ra** từ dữ liệu — mỗi lot mang `pnl_basis` mà nó thực sự được dựng từ đó, hàm này báo lại đúng những gì các lot khai. Đồng nhất → câu khẳng định kèm `n=`; lẫn lộn → cảnh báo nêu rõ lot nào chưa đối chiếu được với tiền broker.

### G.3 Việc suy ra ấy lập tức tố cáo G.1 mới làm được một nửa

Ngay lần chạy đầu, chuỗi derive trả về:

```
mixed basis across 9 closed lot(s): statement_proceeds, unknown
```

Fix G.1 mới phủ **4/9 lot**. `flex_ledger_aligned_realized` — thứ code **tự khai** là `comparable_source_of_truth` ([paper_pnl_compare.py:1586](monitor/paper_pnl_compare.py#L1586)) — vẫn trộn một lot dựng bằng `point_value`, vì `carry_exit` đến từ `statement["closed"]` do `pair_fifo` sinh ra, một đường ghép lot khác chưa được sửa.

**Đã sửa:** `pair_fifo` ([statement.py:203-224](global_index/statement.py#L203-L224)) dùng cùng luật Proceeds, kèm guard: chỉ áp khi hai chân **cùng size**. Một fill 2 lot đóng vị thế 1 lot mang Proceeds của cả 2 lot; cộng thẳng vào là ghi gấp đôi số tiền lot đó thực sự làm ra.

**Self-check:** sau khi sửa, **mọi con số đầu bảng không đổi** (−43,25 / −1.303,25 / +1.260,00 / −1.031,25). Đúng như phải thế — lot chưa verify là **MYM**, multiplier cục bộ vốn đúng; chỉ MNKD sai. Nguồn gốc tiền cải thiện, tiền không nhúc nhích. Nếu con số *có* đổi thì đã là một lỗi multiplier thứ hai chưa ai biết.

### G.4 Dashboard đọc artifact sinh sẵn, không tính live

Phát hiện trong lúc verify G.3: sau khi sửa `pair_fifo`, gọi thẳng nó cho **9/9 lot** `statement_proceeds`, nhưng dashboard **vẫn** báo `mixed ... unknown`.

Nguyên nhân: `paper_evidence_reader` đọc `monitor/paper_pnl_compare.json` ([paper_evidence_reader.py:2615](monitor/backend/paper_evidence_reader.py#L2615)) — một **artifact sinh sẵn**, không tính lại lúc phục vụ.

**Hệ quả vận hành:** sửa `monitor/paper_pnl_compare.py` hoặc `global_index/statement.py` **không tới dashboard** cho tới khi chạy lại `python monitor/paper_pnl_compare.py`. Không có cảnh báo, không có dấu hiệu cũ — dashboard cứ hiển thị số của code cũ với vẻ ngoài y hệt.

Chưa sửa. Hai hướng: dán chữ ký mã nguồn vào artifact và cho reader báo `STALE` khi lệch; hoặc tính live và cache theo chữ ký file đầu vào như các reader khác.

**Cách nó bị bắt đáng ghi lại:** không phải bằng suy luận, mà bằng **hai đường đo cùng một thứ cho hai kết quả khác nhau** — gọi `pair_fifo` trực tiếp so với đọc qua reader. Đó cũng là kỹ thuật đã bắt được lỗi cắt lát và lỗi khung thời gian ở các phiên trước.

### G.5 Vì sao ba mục này quan trọng hơn vẻ ngoài của chúng

C8 (định tuyến MNKD) là lỗi mất tiền. G.1 là lý do **không ai phát hiện ra nó trong bốn ngày**: phép kiểm được dựng ra để bắt đúng loại lỗi đó lại đang nhân sai số vào cả hai vế và báo 0.00.

Sau batch này, một lỗi multiplier tương lai sẽ hiện ra ở `paper_minus_flex`, chứ không triệt tiêu.

---

## PHỤ LỤC H — Ngưỡng lỗ chặn go-live (ĐỀ XUẤT, chờ duyệt)

Thẻ P&L ở M6 cố ý là `OBSERVED` vì chưa ai đặt ngưỡng. Đây là đề xuất, dẫn xuất **hoàn toàn từ phân phối của chính hệ thống** — không có benchmark ngoài nào.

### H.1 Vì sao không thể là một con số cố định

Phân phối P&L cửa sổ N ngày của backtest (khung full-system, xem H.2):

| N | p01 | p05 | median | P(lỗ) |
|---:|---:|---:|---:|---:|
| 5 | −$866 | −$643 | −$71 | **53%** |
| 10 | −$1,317 | −$994 | +$137 | 43% |
| 20 | −$2,073 | −$1,333 | +$450 | 36% |
| 30 | −$2,629 | −$1,448 | +$748 | 34% |
| 60 | −$2,927 | −$1,269 | +$1,790 | 21% |

*(bảng trên đã tính lại trên khung đúng 1.749 phiên — xem H.2)*

**Ở N=5, 53% cửa sổ khoẻ mạnh là âm.** Lỗ sau 5 ngày không mang thông tin gì. Một ngưỡng cố định vì thế hoặc vô dụng lúc đầu, hoặc bất công về sau.

Sàn **không đơn điệu**, và trên khung đúng thì hình dạng rõ hơn: nới dần từ −$2.073 (N=20) tới đáy khoảng −$2.969 (N=50), rồi **thắt lại** về −$1.294 ở N=120. Đã kiểm đây là thật chứ không phải lỗi cắt lát — median tăng đều theo N nên cả phân phối trôi sang phải và đuôi trái co lại ở N lớn. Về hành vi thì đúng: lỗ $1.300 sau 120 phiên đáng ngại hơn cùng số đó sau 20 phiên. Vẫn còn dao động nhỏ giữa các mốc kề nhau (N=30 −$2.629 so với N=35 −$2.560) — đó là nhiễu lấy mẫu, và là lý do luật chọn band **giữ mốc trước** thay vì nội suy.

### H.2 Khung đo — tôi cắt sai, và đã sửa

**Phiên bản đầu của phụ lục này cắt khung ở 2024-12-31 và điều đó SAI.** Giữ lại nguyên văn lập luận sai bên dưới vì cách nó sai mới là bài học.

Lập luận ban đầu: [generate_replay_snapshots.py:44-46](global_index/generate_replay_snapshots.py#L40-L52) ghi đoạn 2025-2026 là **NKD một mình** (nhãn regime đóng băng ở 2024-12-31 nên swing/stress ngừng vào lệnh), nên phải cắt.

**Vấn đề: comment đó mô tả trạng thái TRƯỚC bản sửa của chính nó.** `REGIME_CSV` đã đổi sang `spy_daily_live.csv` và curve sinh lại ngày 2026-08-13. Đo trên artifact hiện tại, khoảng `2025-01-01..2026-08-12`:

| Cluster | Thay đổi P&L trong đuôi |
|---|---:|
| `roska4_swing` | **+$5.112** |
| `global_nkd` | **+$4.636** |
| `roska4_stress` | −$109 |

Cả ba cluster đều chạy. Việc cắt đã **vứt đi 331 phiên bằng chứng hợp lệ và mới nhất**, và siết mọi band chặt hơn mức dữ liệu cho phép.

**Đã tính lại trên khung đúng (1.749 phiên):**

| | Khung sai (cắt) | **Khung đúng** |
|---|---:|---:|
| Phiên | 1.418 | **1.749** |
| Sàn N=20 | −$1.921 | **−$2.073** |
| Sàn N=60 | −$1.592 | **−$2.927** |
| Chặn nhầm | 4,2% | **3,55%** |
| Độ nhạy $50/phiên | 56,1% | **40,1%** |
| MaxDD | 6,23% | **8,10%** |

Đáng chú ý: khung đúng cho band **lỏng hơn** và chặn nhầm **ít hơn**, nhưng **độ nhạy thấp hơn** — 331 phiên thêm vào chứa một đợt sụt giá lớn hơn, làm đuôi trái dài ra. Đó là đánh đổi thật, không phải lỗi.

**Bài học phương pháp:** một comment mô tả trạng thái sẽ cũ đi sau khi chính nó được sửa. Đây là lần thứ hai trong đợt audit này một chuỗi mô tả code gây ra kết luận sai (lần đầu: `flex_reconcile_basis`, Phụ lục G.2). Khác biệt là lần đó tôi bắt được bằng cách derive từ dữ liệu; lần này tôi tin comment và phải bị bắt bởi một câu hỏi tình cờ.

Đã sửa comment gốc, kèm cảnh báo rõ ràng cho người đọc sau. Và spec giờ mang trường `coverage_check` **đo được** thay vì lời khẳng định — có test yêu cầu cả ba cluster phải được nêu tên.

Self-check `equity[2024-12-31] == 98,430.51` vẫn giữ ✅ — nhưng nó là **mốc kiểm chứng, không phải điểm cắt**. Rổ đã đối chiếu: backtest size chân Nikkei bằng `SPECS["MNKD"]` (pv 0,5) — **cùng hợp đồng live**.

### H.3 Đề xuất: hai cổng riêng cho hai kiểu hỏng

**Cổng 1 — Biên lợi thế (P&L chiến lược, sổ sleeve)**

- **Chưa vũ trang cho tới N ≥ 20 phiên.** Dưới mức đó lỗ không mang thông tin.
- Từ N=20: chặn khi P&L realised lũy kế **< p01 của phân phối cửa sổ N ngày** trong khung full-system.
- Cụ thể: N=20 → **−$2.073** (−4,15%); N=30 → −$2.629; N=60 → −$2.927; N=90 → xem bảng band trên dashboard.

**Cổng 2 — Vận hành (broker so với sổ)**

- Bất kỳ chênh lệch nào giữa P&L broker và sổ sleeve **không được bút toán đối soát nào giải thích** → chặn, **bất kể độ lớn**.
- Đây không phải câu hỏi thống kê. Chênh $1 chưa giải thích nghĩa là sổ không mô tả đúng tài khoản.

### H.4 Đo tỉ lệ báo động giả — chạy chính luật đó ngược lên backtest

Mỗi ngày bắt đầu trong backtest được coi là một epoch paper **mà ta biết là tốt**; luật đánh giá mỗi ngày từ N=ARM tới N=60.

| vũ trang từ | phân vị | tỉ lệ chặn nhầm |
|---:|---:|---:|
| N=5 | p05 | 21,4% |
| N=5 | p01 | 6,1% |
| N=20 | p05 | **16,3%** |
| **N=20** | **p01** | **3,55%** |
| N=30 | p01 | 3,8% |

p05 bị loại: chặn nhầm 1 trong 6 epoch khoẻ mạnh thì sẽ bị override, rồi bị phớt lờ.

**Độ nhạy (vũ trang N=20)** — làm hỏng epoch bằng cách trừ đều mỗi phiên:

| drag/phiên | p01 bắt được | p05 bắt được |
|---:|---:|---:|
| $10 | **5,4%** | 31,4% |
| $25 | **10,2%** | 48,8% |
| $50 | **40,1%** | 69,7% |
| $100 | **85,4%** | 96,8% |

**Giới hạn phải nói thẳng:** luật này bắt **sụp đổ**, không bắt **suy giảm từ từ**. Ở drag $25/phiên nó chỉ bắt **10%**. Muốn phát hiện suy giảm nhẹ cần epoch dài hơn hoặc một phép kiểm khác — ngưỡng P&L không làm được việc đó.

**Và ngưỡng được hiệu chỉnh trên chính phân phối dùng để kiểm nó** — đó là một phép *hiệu chỉnh*, không phải kiểm định out-of-sample. Con số 3,55% là "epoch tốt bị chặn bao nhiêu lần", không phải một p-value.

### H.5 Đối chiếu với các mốc rủi ro sẵn có

| Mốc | Giá trị |
|---|---:|
| Circuit breaker ngày (đang chạy) | −4% = **−$2,000** |
| Đề xuất N=20 p01 | **−$2.073** |
| Đề xuất N=30 p01 | −$2.629 |
| MaxDD backtest (khung đúng) | −$4.049 (**8,10%**) |

Ngưỡng 20 ngày rơi gần đúng bằng **một lần trip circuit breaker ngày**. Hai luật được dựng độc lập mà ra cùng cỡ — dấu hiệu tốt cho thấy cỡ này phù hợp với khẩu vị rủi ro đã cài sẵn của hệ thống.

### H.6 Kiểm luật trên chính epoch hiện tại

| Con số | Percentile trong phân phối N=5 | Cổng nào bắt |
|---|---:|---|
| Chiến lược −$43,25 | **48,8%** — trung bình y hệt | Không cổng nào. Đúng: chưa có gì bất thường |
| Broker −$1.303,25 | **0,07%** — tệ hơn 999/1000 cửa sổ 5 ngày trong 7 năm | **Cổng 2**, ngay ngày đầu |

Hai cổng chia việc đúng chỗ. Cổng 1 im lặng vì chiến lược không có gì lạ; Cổng 2 bắt lỗi định tuyến ngay lập tức, **không cần chờ đủ mẫu và không cần ngưỡng thống kê nào**.

### H.7 ĐÃ DUYỆT VÀ ĐÃ TRIỂN KHAI (2026-08-15)

Chủ dự án duyệt đề xuất, yêu cầu **ngưỡng phải được document đầy đủ trên chính dashboard** — không chỉ trong file audit này.

**Spec nằm ở `monitor/paper_inputs.json` → `pnl_threshold_spec`**, gồm 21 band (N=20…120, bước 5) đã **đóng băng** chứ không tính lại lúc đọc: một cổng âm thầm dịch chuyển khi artifact được sinh lại thì không còn là cổng. Kèm theo band là toàn bộ thứ cần để tranh luận với chúng — khung đo, self-check, tỉ lệ chặn nhầm, bảng độ nhạy, và giới hạn.

**Luật chọn band:** dùng band của mốc lớn nhất có `sessions <= N`. Giữa hai mốc thì **giữ band trước đó (lỏng hơn)** chứ không nội suy — cổng không được chặn dựa trên một con số không ai viết ra.

**Panel mới `pnl_thresholds`** ("Go-live loss thresholds", nhóm Execution health), 6 mục:

| Mục | Nội dung |
|---|---|
| The two gates | Hai thẻ cạnh nhau, mỗi cổng một trạng thái riêng |
| Why these numbers and not others | Lý do vũ trang muộn, lý do chọn p01, lý do cổng vận hành không có ngưỡng |
| Band table | 21 band, kèm % của base và số cửa sổ lấy mẫu; band đang áp được tô sáng |
| What the rule costs and what it misses | Tỉ lệ chặn nhầm 3,55%, bảng độ nhạy, **và giới hạn nói thẳng** |
| Where the distribution came from | Nguồn, kỳ, self-check, vì sao cắt đuôi, kiểm hợp đồng |
| Cross-check against existing risk limits | Circuit breaker ngày, MaxDD |

**Thẻ Overview** giờ đọc **cùng một verdict** panel công bố thay vì tự suy — hai chỗ cùng tính "có phải blocker không" là hai cơ hội bất đồng về việc hệ thống có được lên live hay không. Thẻ `BREACH` ngay khi một trong hai cổng breach; `PASS` chỉ khi **cả hai** pass; còn lại `OBSERVED`.

Trạng thái hiện tại trên dashboard:

```
[NOT_ARMED] Edge gate — is the strategy working?
            5 of 20 sessions. Below the arming point a loss carries
            no information, so this gate deliberately says nothing yet.
[PASS]      Operational gate — do the books match the account?
            The +$1,260.00 gap is fully covered by recorded ledger
            adjustment(s) totalling −$1,260.00.
```

**10 test mới.** Đáng chú ý `test_an_unarmed_edge_gate_never_reports_the_epoch_as_passed` — một cổng pass không phải là epoch pass; và `test_operational_gate_blocks_any_uncovered_gap_however_small` dùng khoảng chênh **$1** để ghim rằng cổng vận hành không có ngưỡng.

Còn nợ: nếu baseline backtest đổi, band phải tính lại và duyệt lại. Chưa có cơ chế cảnh báo khi `backtest_curve.json` đổi mà band thì không.

---

## PHỤ LỤC I — Ba việc đóng lỗ hổng cấu trúc (2026-08-15)

### I.1 `ibkr_symbol` trở thành trường bắt buộc trong `Contract`

Một hợp đồng có **ba** danh tính, không phải hai:

| trường | ý nghĩa |
|---|---|
| `name` | tên nội bộ của hệ thống |
| `data_symbol` | dữ liệu lịch sử nằm dưới tên nào |
| `ibkr_symbol` | **phải hỏi IBKR bằng tên nào** |

Trước đây chỉ có hai. `MNKD` mang `data_symbol="NKD"` (đúng — backtest dùng lịch sử NKD full-size vì nó bắt đầu 2018 trong khi dữ liệu micro chỉ từ Q4/2024), và tầng broker phải **tự đoán** cái thứ ba. Nó đoán `data_symbol` → C8.

Và `_RAITS_TO_IBKR` giờ **suy ra** từ `Contract.ibkr` chứ không còn là literal viết tay — bản sao thứ hai của danh tính là bản sẽ trôi, và bản trôi chính là bản định tuyến lệnh.

Test mới: `test_sb8` (order symbol không bao giờ được là data symbol), `test_sb9` (map phải derive, không hardcode ticker), `test_sb10` (neo vào những gì IBKR trả ngày 2026-08-14). Mutation: trả `ibkr_symbol` của MNKD về `"NKD"` → **5 test đỏ**.

`futures/basket.py` cũng nhận trường này với mặc định rỗng — không đổi hành vi Rổ 4 (cả bốn mã đã niêm yết đúng tên chúng), nhưng đóng cùng cái bẫy cho mã micro tiếp theo được thêm vào.

### I.2 Chống lệch artifact P&L (G.4)

`paper_pnl_compare.py` giờ đóng dấu `source_signature` — hash nội dung của `monitor/paper_pnl_compare.py` và `global_index/statement.py` — vào chính file nó sinh ra. Reader tính lại và so.

Dùng **hash nội dung, không dùng mtime**: checkout hay `touch` đổi mtime mà không đổi hành vi, và một cảnh báo kêu oan sẽ bị tắt.

Ba trạng thái: `CURRENT` (im lặng), `STALE` (banner đỏ **trên đầu** panel P&L, kèm lệnh cần chạy), `UNKNOWN` (artifact sinh bởi generator cũ chưa có dấu — nói rõ là không kiểm được, **không** nhận là tươi).

Kiểm chứng: thêm một dòng comment vào `statement.py` → `STALE` nêu đúng tên file; khôi phục → `CURRENT`.

### I.3 Panel bằng chứng TWS (M8)

Coverage 15 → 16 khoá. Panel dùng **cùng** hàm `_tws_input_status` mà gate dùng, nên hai bên không thể bất đồng về cùng những đêm đó; khác nhau ở chỗ gate trả lời *"đủ chưa"* còn panel trả lời *"đã ghi nhận được gì"*.

Trạng thái là `MISSING` chứ không mượn `PENDING` của gate — chưa có bản ghi nào thì đó là **không có bề mặt bằng chứng**, không phải "đã thu được ít, đang chờ thêm".

Panel nêu thẳng `what_counts`: một đêm chỉ tính khi `restart_proven` + `runner_resumed` + `broker_verified` đều true; dòng candidate kết nối là **context, not proof**.

Giờ **4/4 thẻ gap** có nút mở panel, và thẻ blocker TWS trên Overview cũng có. Test `test_every_gap_card_can_open_the_panel_it_refers_to` khẳng định thêm rằng không gap nào được trỏ về `runner_freshness` — đúng mục tiêu sai mà H5 đã gỡ.

### I.4 Phát sinh: lần tải đầu sau restart luôn hỏng

Đo được khi verify I.3: request cold-cache mất **41,7s**, trong khi client timeout là 30s. Nghĩa là **mọi lần tải trang đầu tiên sau khi restart backend đều báo "Paper evidence unavailable"** cho một backend đang chạy tốt. Request ấm: ~0,03s.

Đã nâng timeout lên 90s. Đây là **vá triệu chứng** — nguyên nhân là quét ~115MB log lúc lạnh, và chỗ đúng để sửa là warm cache khi backend khởi động. Ghi vào danh sách còn nợ.

---

## PHỤ LỤC J — Cổng re-freeze HMM không dùng được (HOÃN, chờ phiên riêng)

**Trạng thái: chưa sửa, cố ý hoãn 2026-08-15 để đào sâu ở phiên riêng.** Ghi lại đầy đủ ở đây để phiên sau không phải tìm lại.

### J.1 Vì sao đụng tới

`data_freshness` BREACH và `open_incidents` BREACH có **một gốc chung**: model HMM `fit_C` 20 tháng tuổi, guard bắn `G2 HARD: re-freeze immediately`. Lưu ý G2 là **cảnh báo, không halt** — [hmm_stale_guard.py](global_index/hmm_stale_guard.py) nói rõ *"an old model still decodes regime correctly for recent data"*. Đây là **nợ**, không phải sự cố.

### J.2 Đo được gì

Chạy `futures/verify_current_freeze.py` (công cụ mới, chỉ đọc) — nó chấm model đương nhiệm bằng **chính `refreeze.run_verify`** mà cổng promote dùng:

```
Calmar today   1.6781
floor          2.38
net            $57,950
drift vs freeze-time record  -1.0661 (-38.8%)
```

Net **$57.950 khớp chính xác** `backtest_curve.json` — hai đường độc lập cùng kết quả.

### J.3 Nguyên nhân: ba thước đo, không phải suy giảm

`calmar = (net / số_năm) / maxdd_$`. Kiểm: 57.950 / 8,53 / 4.048 = 1,678 ✅

| Cơ sở | net | MaxDD | Calmar |
|---|---:|---:|---:|
| Registry ghi lúc đóng băng 2026-07-06 | ? | ? | **2.744** |
| Đường cong **cũ** (đuôi NKD-only) | $61.088 | $3.115 | **2.299** |
| Đường cong **hiện tại** (đuôi đủ 3 cluster) | $57.950 | $4.049 | **1.678** |

Tái dựng đường cong cũ khớp tới từng đô: `48.431 + (12.851 − 194 + 0) = 61.088`, chia 8,53 năm chia 3.115 = **2,299**.

**Chuyện đã xảy ra:** bản sửa 2026-08-13 (`REGIME_CSV → spy_daily_live.csv`) cho swing/stress giao dịch trong 2025-2026, **thêm vào** đợt sụt giá cả rổ đỉnh điểm **2026-03-26**, đẩy MaxDD $3.115 → $4.049. Calmar rơi 2,14 → 1,56 trong riêng tháng 3.

Hệ thống **không tệ đi — cái nhìn về nó trở nên trung thực hơn**, và một sàn đặt trên cái nhìn cũ lập tức vô nghĩa.

Calmar theo ngày cắt, trên artifact hiện tại — **không ngày nào đạt 2.744**:

| cắt đến | net | maxdd | calmar |
|---|---:|---:|---:|
| 2024-12-31 | 48.431 | 3.115 | 2.247 |
| 2025-06-30 | 53.512 | 3.115 | **2.317** (đỉnh) |
| 2026-03-26 | 51.607 | 4.049 | 1.564 |
| **2026-07-06** (ngày đóng băng) | 53.346 | 4.049 | **1.563** |
| 2026-08-12 | 57.950 | 4.049 | 1.678 |

### J.4 Lỗi cấu trúc: số bị đóng băng mà thước đo thì không

`FreezeRecord` lưu:

```
version, fit_end, anchor, n_components, labels_hash, frozen_at, calmar, note, invalid
```

**Không slippage. Không ngày cuối dữ liệu. Không phiên bản code. Không chữ ký đường cong.** Nên 2.744 không tái tạo được — không phải do ai làm sai, mà **do thiết kế**.

Đây là lần thứ **ba** cùng một dạng lỗi trong đợt audit này:

| Lần | Chỗ | Dạng |
|---|---|---|
| 1 | `flex_reconcile_basis` (G.2) | chuỗi mô tả code, thành sai sau khi code đổi |
| 2 | comment `generate_replay_snapshots` (H.2) | mô tả trạng thái **trước bản sửa của chính nó** |
| 3 | `FreezeRecord.calmar` (J.4) | **số không kèm cơ sở đo** |

### J.5 Việc cho phiên sau — và **không** phải re-freeze trước

Re-freeze bây giờ sinh Calmar trên cơ sở 2-tick/đường-cong-mới rồi so với sàn 2.38 thuộc cơ sở khác. Cùng một lỗi phạm trù.

**Thứ tự đúng:**

1. **Đặt lại `CALMAR_FLOOR`** trên cơ sở hiện tại, y như cách đã làm với ngưỡng P&L (Phụ lục H): lấy phân phối của chính hệ thống hôm nay, tài liệu hoá đầy đủ. Giữ nguyên tỉ lệ cho phép suy giảm 13,3% đã duyệt trước đây thì sàn mới ≈ **1.45**. *Mức cho phép suy giảm là quyết định rủi ro của chủ dự án.*
2. **Cho `FreezeRecord` mang theo cơ sở**: slippage, ngày cuối dữ liệu, chữ ký `backtest_curve.json`, hash engine. Thiếu bước này thì sàn mới mục đúng như sàn cũ.
3. **Rồi mới** re-freeze. Về `fit_end`:

| `fit_end` | Out-of-sample còn lại | Đánh giá |
|---|---|---|
| 2026-08-13 (kịch trần dữ liệu) | **0 phiên** | `run_verify` replay toàn lịch sử → Calmar gần như in-sample. **Không so sánh được** |
| **2025-12-31** ✅ | ~155 phiên | Có đoạn thật ngoài mẫu; khớp nhịp re-freeze hằng năm; bước kế tiếp tự nhiên sau fit_C (2024-12-31) |

G3 chỉ chặn khi `spy_daily_live.csv` chưa với tới `fit_end` — CSV hiện tới **2026-08-13**, nên không phải ràng buộc.

Lưu ý tên tham số dễ nhầm: `anchor` lọc điểm bắt đầu chuỗi SPY (registry: 2017-01-01); `train_end` là nơi bắt đầu **gán nhãn** (2018-01-01); `fit_end` là nơi dừng **fit**. Production truyền `2018-01-01` làm `train_end` — khớp mặc định `refreeze`, **không mâu thuẫn** với registry.

### J.6 Công cụ để lại

[futures/verify_current_freeze.py](futures/verify_current_freeze.py) — chấm model đương nhiệm bằng chính hàm cổng promote dùng, trên nhãn production dựng ra hôm nay. Chỉ đọc: không đụng registry, model, state. Chạy ~170s.

---

## PHỤ LỤC K — Spec C1: dẫn xuất của từng con số (DUYỆT 2026-08-15)

Không con số nào ở đây được chọn theo cảm tính. Mỗi ngưỡng kèm phép đo sinh ra nó, và toàn bộ phần này được **công bố trong `c1_spec`** nên nó hiện trên chính dashboard, không chỉ nằm trong file audit.

### K.1 Hai lỗi cấu trúc của spec cũ

Spec cũ: `min_n=100, max_mean_ticks=5, scope=separate`.

**Lỗi 1 — gộp giữa các mã.** Một tick không phải một mức giá trên rổ này: $0,50 (MYM/M2K/MNQ), $1,25 (MES), $2,50 (MNKD). Trên đúng 5 fill đã có:

| | Gộp | M2K | MYM | MNKD | MES |
|---|---:|---:|---:|---:|---:|
| ticks | **+9,00** | **+28,00** | +8,00 | +6,50 | −4,00 |
| đô-la | +$9,10 | +$14,00 | +$4,00 | **+$16,25** | −$5,00 |

M2K ở **+28 tick = gấp 14 lần** chi phí mô hình, và số gộp 9,00 không để lộ. Thứ hạng **đảo ngược** giữa hai đơn vị — MNKD tốn tiền nhất dù ít tick hơn — nên phải công bố cả hai.

**Lỗi 2 — `min_n` không thể đạt.** Nhịp mẫu đo trên backtest: 3.279 lệnh / 1.749 phiên = **1,87 lệnh/phiên**.

| `min_n` | MNKD (0,49/phiên) | Rổ 4/mã (0,35/phiên) | STP gộp @30% |
|---:|---:|---:|---:|
| 20 | 41 | 58 | 36 |
| **30** | 61 | 87 | **53** |
| 100 | **203** | **289** | **178** |

Mục tiêu duration của gate là **60 phiên**. `min_n=100` cần 178–289 phiên — **gate không thể đạt trong chính mục tiêu của nó**, đúng loại lỗi `exit_path_coverage`.

### K.2 Vì sao đơn vị vẫn là tick, không đổi sang đô-la

Backtest mô hình hoá chi phí bằng `SLIPPAGE = 2.0 tick/bên` **áp cho từng mã** — nên tick-theo-mã chính là đơn vị của mô hình. **Cái sai là gộp, không phải đơn vị.** Đô-la được công bố kèm để đọc tác động kinh tế, không thay thế.

### K.3 Vì sao trần 3 tick, không phải 5

```
net/năm                            $6.794
chi phí 1 tick/bên thêm              $903/năm = 13% net năm
từ 2 tick (mô hình) → 5 tick        3 tick   = 40% net năm
từ 2 tick (mô hình) → 3 tick        1 tick   = 13% net năm
```

**Trần 5 tick cũ cho phép chi phí thực thi ăn ~40% biên lợi nhuận mô hình trước khi gate lên tiếng.**

Con số $903/tick/năm kiểm chéo hai đường độc lập: tính trực tiếp (số lệnh × 2 bên × tick value) ra ≈$7.633 trên 8,53 năm; phép stress-test slippage đo riêng đầu phiên ra −$7.756/tick. Lệch **1,6%**.

### K.4 Vì sao OPEN theo mã mà STP thì gộp

Không phải cho nhất quán — vì mật độ mẫu hai nhánh khác nhau. OPEN đủ dày để mỗi mã đạt 20 mẫu trong 41–58 phiên. STP theo từng mã cần **~136 phiên** cho riêng MNKD. Nhánh nào chấm được theo mã thì chấm; nhánh nào không thì gộp, kèm số đô-la.

### K.5 Điều KHÔNG đo được, và spec phải nói ra

**Tỉ lệ STP trong tổng lối thoát ở live chưa đo được.** Backtest chặn trên ~87% (13% giữ đủ 5 ngày → MAX_HOLD), nhưng live đặt stop **cố định ở mức chandelier lúc vào, không ratchet** — nên nhiều lối thoát chandelier của backtest thành signal exit 14:05. Quan sát: 3/10 dòng CLOSE là STP, quá ít.

Con số **30%** dùng để tính 53 phiên là **giả định giữa khoảng**. Nếu tỉ lệ thật thấp hơn thì 30 mẫu sẽ lâu hơn. Điều này được ghi thẳng vào spec ở trường `stp_share_is_assumed_not_measured` và có test bắt buộc nó tồn tại.

### K.6 Khoảng tin cậy — cải tiến quan trọng hơn con số

`min_n` là **một phỏng đoán về độ phân tán mà không ai đo**. Nên mỗi mean giờ đi kèm nửa khoảng tin cậy 95%: ở n=30 nó bằng ≈0,36×sd. Nếu sd≈6 tick thì ±2,1 so với trần 3 tick — mẫu chưa quyết định được, và **con số tự nói ra điều đó** thay vì để một bộ đếm cố định âm thầm chứng nhận một mean chưa ổn định.

Hiện trên dashboard: MNKD `N=2 · 95% CI ±0,98 ticks`; ba mã còn lại `CI needs N>=2`.

### K.7 Slippage thuận lợi vẫn tính là lệch

MES vào tốt hơn tham chiếu **4 tick** và vẫn bị tính vi phạm. Có chủ đích: đó vẫn là sai số 4 tick trong giá khớp kỳ vọng, và mô hình định cỡ rủi ro từ tham chiếu đó sai đúng bằng ngần ấy dù lệch chiều nào. Không phải lỗ về tiền — cột đô-la cho thấy dấu — nhưng là **lệch thực thi**. Trước đây điều này ngầm định trong `use_absolute: true`; giờ khai rõ ở `why_absolute`.

### K.8 Trạng thái sau khi áp

```
OPEN 0/4 instrument(s) at N>=20 | STP 0/30        QUALITY_BREACH
over limit: M2K, MES, MNKD, MYM
```

Cả 4 mã vượt trần trên n=1–2. Trạng thái là `QUALITY_BREACH` chứ không phải `BREACH` — **mẫu mỏng nằm ngay trong tên trạng thái**. Và mean vượt trần **vẫn được báo dù mẫu mỏng**: giấu nó tới khi đủ đếm chính là lỗi gộp ở dạng khác, giữ lại đúng phép đo dễ có ý nghĩa nhất.

### K.9 Test

7 test mới. Mutation: bỏ phán quyết theo mã → 3 test đỏ; cho mã thiếu mẫu vẫn PASS → 2 test đỏ. Đáng chú ý `test_c1_spec_publishes_why_each_threshold_is_what_it_is` — bắt buộc **mọi ngưỡng phải mang theo lý do**, kể cả lời thú nhận rằng 30% là giả định.

---

*Bản audit gốc chỉ đọc, không sửa file. Các mục đánh dấu ĐÃ SỬA được cập nhật sau khi thay đổi đã được kiểm chứng độc lập, không phải theo báo cáo của tác nhân thực hiện.*
