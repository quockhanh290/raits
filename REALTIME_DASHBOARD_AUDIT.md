# Realtime Dashboard Audit

**Phạm vi:** `http://127.0.0.1:5002/realtime` — `global_index/dash/realtime/{index.html,realtime.js,realtime.css}` + backend `monitor/backend/*`
**Ngày audit:** 2026-08-14 (server_now ≈ 15:30Z / 11:30 ET)
**Phương pháp:** đọc code, gọi API read-only, load trang thật trong Chrome, đọc DOM đã render, resize viewport, chạy `pytest monitor/test_dashboard_backend.py` (114 passed), `node --check realtime.js` (OK).
**Không sửa file source nào.** Chỉ tạo duy nhất file report này.

---

## Trạng thái sửa chữa (cập nhật 2026-08-14, sau audit)

Bản audit dưới đây giữ nguyên như lúc viết — nó là bản ghi lịch sử, không sửa lùi.
Khối này ghi cái gì đã đóng. Kế hoạch: [docs/futures/REALTIME_DASHBOARD_FIX_PLAN.md](docs/futures/REALTIME_DASHBOARD_FIX_PLAN.md).

### Bảng tổng hợp: vấn đề → cách sửa → hiện trạng

Cột "hiện trạng" là **số đo**, không phải mô tả ý định. Đo lúc 2026-08-15 00:0x ET trên trang
thật đang chạy và trên log production, trừ nơi ghi rõ là fixture.

| # | Vấn đề (audit phát hiện) | Sửa thế nào | Hiện trạng sau sửa |
|---|---|---|---|
| **C1** | Push incident cho mất-kết-nối-IBKR và lệch-position nằm trong `if ($('schedulerHealth'))` — element không tồn tại. Gap dự phòng lại bị nén bởi cờ `twsOutageOpen` suy ra từ chính incident không bao giờ bắn: hai lớp bảo vệ hỏng cùng hướng | Gỡ điều kiện, đưa hai vòng push ra ngoài. Nén gap dựa trên incident **có thật trong mảng** (`incidents.some(...)`) thay vì cờ suy diễn | Stub `connectivity_outage status=open` → Now Monitor hiện `IBKR connectivity unavailable`. Broker chết + outage mở → Now Monitor **không rỗng**. 2 DOM test |
| **C2** | `freshness` suy từ log scheduler + đồng hồ, `observed_at` chỉ dùng để kiểm `None`. Dòng duy nhất mang tuổi snapshot nằm trong `<b hidden>` không bao giờ được bỏ hidden | Thêm trạng thái `stale` + `state_age_seconds`, neo vào **tuổi snapshot** chứ không vào deadline slot. Bỏ `hidden`, gộp câu chữ về một hàm dùng chung với rail | Đo: snapshot 2 phút → `fresh`, 90 ngày → `stale` (trước: cả hai `fresh`). Trang thật hiện `On schedule · next 01:10 ET`, không còn ẩn |
| **H1** | Ba reader ba thuật toán "đã phục hồi chưa". Rail nói *systems nominal* trong khi panel ngay dưới liệt kê 6 slot là **OPEN** mà backend đã đánh dấu recovered | `job_journal_reader` set `lifecycle_status` cho **mọi** job failed/missed. Now Monitor đọc `open_incidents ?? incidents` — dùng `??` vì `[]` truthy nên `\|\|` rơi về danh sách đầy đủ | Bốn lane (rail, Now Monitor, Job Journal, reports) cùng một kết luận trên cùng một log. `open_incident_count` 6 → **0**. Test bốn-lane trong `test_realtime_contract.py` |
| **H2** | Sharpe `10.21` tính từ 4 quan sát ngày, hiển thị ngang hàng drawdown thật. Chuỗi đo 26.96 → 14.87 → 11.85 → 10.21 là phân rã `1/√n` | `MIN_METRIC_DAYS = 20`; dưới ngưỡng thì `--` kèm `title` nói rõ cỡ mẫu | Trang thật: `--`, title `n=5 trading day(s); needs 20`. Calmar cùng cơ chế |
| **H3** | Mọi event thiếu timestamp render `14:05 ET`, không phân biệt được với giờ thật — trong khi cron 14:10–15:55 tồn tại **chính vì** entry không xảy ra lúc 14:05 | `decisionTime` trả `{text, exact}`; thiếu giờ → `time not recorded`, in nghiêng khác màu. `sortKey` vẫn giữ mốc slot nhưng không được hiển thị như giờ | Chuỗi `14:05` biến mất khỏi Event Journal trên dữ liệu thật. Nhánh `time not recorded` khoá bằng stub |
| **H4** | `sortKey` so bằng `localeCompare` trên chuỗi trộn `...Z` (UTC) và naive ET → event 14:05 ET (=18:05Z) xếp như thể 14:05 UTC | `sortInstant` quy mọi mốc về epoch millis; chuỗi thiếu offset coi là ET | Test trộn hai định dạng, assert thứ tự theo thời gian tuyệt đối |
| **M1** | `validStopsFor` chỉ kiểm action/qty/status. SELL STP đặt **trên** giá thị trường cho vị thế LONG vẫn hiện `Protected` xanh | `stopPriceAgrees`: kiểm hướng so với `market_price`, và lệch so với `stop_price` của runner trong dung sai `4 × tick` (tick lấy từ `contract_specs`) | Stub stop lệch 100 điểm → `0 covered` + incident `invalid stop`. Position thật (lệch 0.04 = tick rounding) vẫn `PROTECTED #288` |
| **M2** | IBKR net mọi cluster thành một dòng; `runnerFor` trả phần tử **đầu tiên**. Hai cluster cùng giữ một micro → false *size mismatch* **và** cả hai stop hợp lệ bị đánh invalid | `runnersFor` trả danh sách; `expectedQuantity` cộng dồn; số lượng stop cộng dồn trước khi so với `\|position\|` | Stub 2 cluster × 1 contract + 2 stop → `1 covered`, không `size mismatch`, không `invalid stop` |
| **M3** | `persistedRunnerFor` đòi khớp đồng thời 6 trường, gồm float equality trên `entry_price` **và** `stop_order_id`. Runner ratchet stop → id mới → qty rơi về `null` | Khoá ổn định `positionKey` = `inst\|cluster\|direction\|entry_day`; giá và id thành bằng chứng phụ, không phải điều kiện khớp | Stub ratchet (id 288→301, snapshot chưa ghi lại) → không còn `quantity missing`, không `size mismatch` |
| **M4** ⬆ | **Nâng Medium → HIGH, thành blocker.** Không đối chiếu ledger runner ↔ tài khoản broker. `meta.broker_equity` và `paper_start` có trong payload nhưng không render ở đâu | Thêm dòng context dưới Paper Equity: số dư broker + delta so với `paper_start`, link sang `/paper`. Không trộn hai ledger — chỉ làm chúng **nhìn thấy được** | Trang thật: `Broker acct $996,440 / −$4,040 since Jul 8, 2026` ngay dưới `Paper Equity $50,229 / +$229`. Ở 390px kết thúc x=327 trong viewport 487, không cắt |
| **M5** | Màu ô HMM fit chỉ dựa `completed == attempts`, bỏ qua `non_convergence_count`. 22/22 fit cảnh báo mà ô vẫn **xanh** | `positive` chỉ khi `non_convergence_count === 0`; text kèm số cảnh báo | Trang thật: `45/45 complete / 45 warn`, class `warning` |
| **M6** | Header đếm covered mà bỏ qua `stop_deferred`; rail thì loại trừ deferred → position deferred hợp lệ hiện `0 / 1` trong khi rail nói nominal | `protectionSummary()` dùng chung cho cả hai, tách ba trạng thái | Trang thật: `1 covered`. Stub deferred → chữ `deferred`, rail vẫn nominal |
| **M7** | `coverage.to = max(dòng log cuối, hôm nay)` → UI luôn quảng cáo *evidence … to hôm nay* kể cả khi scheduler chết nhiều ngày | Tách `evidence_ends` + `stale_days`; UI hiện mốc thật, kèm *(ends N days ago)* khi trễ | Trang thật: `1 open / evidence 2026-07-30 to 2026-08-15`. Fixture log cũ → `stale_days ≥ 1` |
| **M8** | Một nguồn API hỏng lẻ chỉ được báo bằng `opacity: .42`, không chữ nào, không nói nguồn nào. `fatalBanner` chỉ bật khi **cả 5** endpoint fail | `stripDeadSources` gom `error` của cả 5 nguồn và gọi tên trong rail | ⚠️ **MỘT PHẦN** *(sửa lại 2026-08-15, trước đó ghi nhầm là ĐÓNG)*. Rail có gọi tên: stub 500 → chứa `runner-state`. Nhưng nửa sau **chưa làm**: `renderMetrics:320` vẫn `snap?.equity ?? meta.final_equity` không kiểm `error`, nên số từ nguồn đã chết vẫn render như đang sống, chỉ mờ 42%. `fatalBanner` cũng vẫn all-or-nothing (`realtime.js:261`) |
| **L1** | `renderRailLegacy` + `railItem` + `railTips` không được gọi ở đâu; CSS `.scheduler-health` mồ côi. Chúng khai báo 9 chỉ báo khiến người đọc tưởng rail vẫn hiển thị chúng | Xoá cả ba + CSS mồ côi | `rg` = **0** cho cả bốn tên |
| **L2** | `localTime()` không format giờ local — nó format **ET**, ở đúng phần code nhạy timezone nhất | Đổi tên `etDateTime()` | `localTime` còn **0** lần xuất hiện |
| **L3** | 16/28 dòng Job Journal là cùng một known-debt G2, che các dòng thật | Gộp thành một hàng tóm tắt khi vượt ngưỡng | Nhãn journal thật: `COMPLETED 13 · RECOVERED 6 · KNOWN DEBT 1` (39 dòng debt → 1) |
| **L4** | Trên mobile `openIssuesShell` đóng mặc định, giấu luôn issue duy nhất đang mở sau `<details>` | Mở khi `issues.length > 0`, bất kể viewport | `openIssuesShell.open === true` @390px khi có issue |
| **L5** | `GET /favicon.ico` → 404 thường trực làm lu mờ lỗi thật trong console | Route trả 204 | `curl` → **204**. Console trang thật: **0 error** |
| **L6** | `breaker.dd_pct` phát ra ở đơn vị **phần trăm** (0.086) trong khi `drawdown_pct` cạnh nó là **phân số** (0.00086) — chênh 100× | 🔒 **KHÔNG sửa có chủ đích.** Sửa nguồn là sửa `global_index/runner.py`, code giao dịch, cần quyết định riêng | UI không đọc field này. Khoá bằng `test_realtime_never_renders_the_percent_unit_breaker_field`. Ghi ở `OPEN_QUESTIONS.md` |
| **L7** ✚ | *(phát hiện trong lúc sửa H1)* `schedule_status` nhận cả `"completed ok"` lẫn `"thoat ok"`; `job_journal_reader` chỉ nhận `"completed OK"` và `"thoat OK nhung"`. Một dòng `"thoat OK"` **trần** để job kẹt `running` vĩnh viễn ở lane này trong khi rail gọi là `executed` | `CLEAN_EXIT_TOKENS`/`DEBT_EXIT_TOKENS` + `is_clean_exit`/`is_debt_exit` dùng chung. **Nhánh debt phải kiểm TRƯỚC** vì `"thoat OK nhung"` chứa `"thoat OK"` làm tiền tố | Log thật không đổi một phân loại nào (`thoat OK` trần = **0 lần**): `completed 13 · completed_with_debt 39 · failed 6`, **không job nào `running`** |

**Tổng: 19/21 đóng, 1 một phần (M8), 1 hoãn có chủ đích (L6).**

➜ **[Audit Phase 2](#audit-phase-2--mở-2026-08-15)** mở ở cuối file: 10 mục nữa, trong đó
2 lỗi đã xác nhận và 7 đường dẫn chưa ai chạy (breaker HALTED, position broker-only/runner-only…).

⬆ = nâng severity giữa chừng · ✚ = phát hiện thêm trong lúc sửa · 🔒 = hoãn có chủ đích

---

**Bản ghi verify (2026-08-15 00:0x ET).** Trạng thái trên đến từ phép đo của tôi, không từ báo cáo
của agent thực thi — hai lượt trước nó hoàn thành việc mà không báo về, nên chỉ số liệu mới tính.

- `node --check realtime.js` sạch · không có định nghĩa trùng lặp
- **176 passed**: DOM 32 · contract 11 · backend 133
- Trang thật: **0 console error**; danh sách element bị cắt = `[]` ở **cả 1440 và 390**
- Header: `Sharpe --` (title `n=5 trading day(s); needs 20`) · `HMM fit 45/45 complete / 45 warn`
  (class `warning`) · `runnerContext` hiện · `evidence 2026-07-30 to 2026-08-15`

Một điểm dễ đọc nhầm là hồi quy: `incidentSummary` lúc verify là `0 incident / 0 telemetry gap`,
**không** kèm `/ 6 slot(s) lost, recovered`. Không phải hỏng — lúc đo đã sang ngày 15/08, và
`schedule-status` tính theo giờ hiện tại nên ngày mới chưa có incident, trong khi Job Journal bám
theo ngày của snapshot (14/08) nên vẫn hiện đủ `RECOVERED 6`. Hai vùng dùng hai mốc thời gian
khác nhau có chủ đích.

**Thêm ngoài phạm vi audit ban đầu:**
- **Lane `recovered` trong Now Monitor.** H1 bỏ incident đã phục hồi khỏi lane báo động —
  đúng, nhưng làm mất luôn con số "6 slot quyết định mất trong đêm". Giờ gộp thành một dòng
  đếm được, nhãn RECOVERED, không tính vào incident count.
- **Test bắt nội dung bị CẮT, không chỉ trang bị cuộn.** Phần "Desktop / mobile" dưới đây
  kết luận không overflow dựa trên `scrollWidth > clientWidth` — **chưa đủ**. Nội dung có
  thể vượt mép mà bị cắt, khi đó `scrollWidth == clientWidth` và assert vẫn xanh. Chính
  bản sửa C2 đã tạo ra một ca như vậy (header trải 608px trên viewport 487px, dòng độ tươi
  runner nằm ngoài màn hình) và test cũ không thấy. Đã thêm
  `test_no_content_is_clipped_off_the_right_edge`.

**M4 có bằng chứng thực tế, cân nhắc nâng Medium → High.** Cùng ngày, một bug định tuyến
`MNKD` sang contract full-size `NKD` thay vì micro `MNK` được phát hiện riêng: bốn lệnh
ngày 08-10/11 realised **−$1,400 ở broker** trong khi sleeve ledger book **−$140**, đúng
10.0000×. Giá vào/ra khớp statement đến từng cent — chỉ multiplier sai — nên mọi panel dựa
trên ledger runner đều nhìn "bình thường", và header vẫn ghi **+$229**. Không panel nào
trên trang Realtime có thể đã bắt được. Đó chính là loại divergence M4 mô tả. Thêm chi
tiết khớp: `contract_specs` IBKR trả về lúc audit chỉ có M2K/MES/MNQ/MYM, **không có**
entry nào cho MNKD/NKD, nên đến tick/point_value cũng không có gì để đối chiếu.

---

## Executive Summary

**Có an toàn để dùng cho live operational monitoring chưa? — CHƯA, không dùng một mình.**

Điểm mạnh thật sự: trang này **hoàn toàn read-only** — 0 form, 0 nút lệnh, 0 control restart/up/down, input duy nhất là chọn font. Backend chỉ có route `GET` (`test_backend_routes_are_read_only`, `test_backend_does_not_import_runner_or_write_state`). **Không có rủi ro thao tác nhầm gây tác động broker/runner.** Về mặt "gõ nhầm nút là mất tiền" thì trang này sạch.

Vấn đề nằm ở chiều ngược lại: **trang có thể im lặng khi hệ thống đang hỏng, và kêu sai khi hệ thống đang lành.**

5 rủi ro lớn nhất:

1. **Alarm mất kết nối IBKR và alarm lệch position broker/runner nằm trong nhánh code chết.** Toàn bộ khối push incident cho `connectivity_outage` và `broker_reconcile_incident` bị bọc trong `if (schedulerHealth)` — element `schedulerHealth` **không tồn tại** trong `index.html`. Tệ hơn: khi TWS outage đang mở, telemetry gap "Broker truth unavailable" bị **cố ý nén đi** vì code giả định incident sẽ hiện — mà nó không bao giờ hiện. Kết quả: mất broker feed → Now Monitor có thể báo **CLEAR**.

2. **Runner state cũ 90 ngày vẫn được backend gắn nhãn `fresh`.** `freshness` được suy ra hoàn toàn từ log scheduler + đồng hồ, `observed_at` chỉ dùng để kiểm tra `None`. Đã đo trực tiếp. Đồng thời dòng UI duy nhất hiển thị tuổi snapshot (`runnerContext`) mang thuộc tính `hidden` và không bao giờ được bỏ hidden.

3. **Ba kết luận mâu thuẫn về cùng một sự kiện, trên cùng một màn hình, cùng một lúc.** Ngay lúc audit: rail trên cùng ghi *"systems nominal: feeds live, positions protected"*, ngay dưới Now Monitor ghi *"6 incident"* với 6 dòng **OPEN**, Job Journal cũng 6 dòng **OPEN**, còn Open Issues ghi **1**. Cả 6 sự kiện đó backend đã đánh dấu `lifecycle: recovered`.

4. **Thời gian bịa.** Entry/exit/rejected không có timestamp được render là `14:05 ET` — không phân biệt được với giờ thật. Đây đúng chỗ nhạy cảm nhất: cả thiết kế Option C là để bắt entry trong 14:10–15:55.

5. **Không có đối chiếu ledger runner ↔ tài khoản broker.** Header ghi "Paper Equity $50,229 / **+$229**". Cùng payload có `broker_equity = 996,311.98` và `paper_start.equity = 1,000,480` → tài khoản paper thật **-$4,168** kể từ 2026-07-08. Không hiển thị ở đâu trên trang Realtime.

---

## Findings

### CRITICAL

---

#### C1 — Incident mất kết nối IBKR và lệch position broker/runner nằm trong nhánh chết

**Vị trí:** `global_index/dash/realtime/realtime.js:518-548` (khối `if (schedulerHealth)`), `realtime.js:631` (gap bị nén)

**Vấn đề:**
`renderMonitor()` lấy element `schedulerHealth`, và bọc **toàn bộ** phần push incident vào `if (schedulerHealth) { … }`:

```js
518  const schedulerHealth = $('schedulerHealth');
519  if (schedulerHealth) {
…
530    openConnectivity.forEach(event => incidents.push({ … 'IBKR connectivity unavailable' … }));
538    if (!brokerPositionsMatchNow()) openReconcile.forEach(event => incidents.push({ … }));
…
548  }
```

`index.html` **không có** id `schedulerHealth` (cũng không có `schedulerHealthValue`). Nên `openConnectivity` và `openReconcile` **không bao giờ** vào danh sách incident.

Nghiêm trọng hơn, dòng 631 nén luôn telemetry gap thay thế:

```js
631  if (!brokerUsable() && !twsOutageOpen) gaps.push({ key: 'gap:broker', … 'Broker truth unavailable' … });
```

`twsOutageOpen` (dòng 515-516) được tính **ngoài** nhánh chết nên vẫn hoạt động. Logic dự định là: "có outage đang mở thì đã có incident riêng rồi, khỏi cần gap". Nhưng incident đó chết. → **TWS outage đang mở ⇒ không incident, không gap.**

**Vì sao quan trọng operationally:**
Đây chính là kịch bản mà một monitor tồn tại để bắt. Mất TWS/IBKR nghĩa là stop order không được xác minh, position không được xác minh, runner có thể đang chạy mù. Trang lại có thể hiện `CLEAR`.

**Bằng chứng:**
- DOM runtime: `document.getElementById('schedulerHealth')` trả `null` → `schedulerHealthExists: false`.
- CSS mồ côi còn sót: `realtime.css:182-185` `.scheduler-health.ok/.bad` — markup đã bị xóa, JS chưa dọn theo.
- Các kind này **thật sự phát sinh** trong evidence lưu trữ (`monitor/backend/session_event_reader.py:291,315,388` cho `connectivity_outage`; `:440,464` cho `broker_reconcile_incident`). Quét API `/api/v1/session-events/<day>`:
  - `2026-08-07`: `connectivity_outage × 1`
  - `2026-08-10`: `broker_reconcile_incident × 1`, `stop_deferred × 4`
  - `2026-08-11`: `connectivity_outage × 4`
  - `2026-08-12`: `connectivity_outage × 1`
  Hiện tất cả đã `recovered` nên chưa lộ, nhưng đường dẫn code đã hỏng sẵn.

**Đề xuất fix:**
1. Bỏ hẳn `if (schedulerHealth)` (và cả biến `schedulerHealthClass/Text` không còn dùng), đưa 2 vòng `incidents.push` ra ngoài.
2. Bỏ điều kiện `&& !twsOutageOpen` ở dòng 631, hoặc chỉ nén khi **thực sự** đã có incident tương ứng trong mảng `incidents` (kiểm tra bằng `incidents.some(...)`, không phải bằng cờ suy diễn).
3. Thêm test DOM: render với payload có `connectivity_outage status=open` → assert Now Monitor có đúng 1 dòng incident IBKR.

---

#### C2 — `freshness` của runner-state không phụ thuộc tuổi snapshot; tuổi lại bị ẩn khỏi UI

**Vị trí:** `monitor/backend/schedule_status.py:269-286`; `global_index/dash/realtime/index.html:37`; `realtime.js:253-259`

**Vấn đề:**
Trong `get_schedule_status()`, tham số `observed_at` chỉ được dùng **một lần**, để kiểm tra `None`:

```python
269  if observed_at is None:
270      freshness = "missing"
271  elif not trading_today or before_first:  freshness = "not_expected_yet"
273  elif overdue_unexplained:                freshness = "late"
275  elif not active_window:                  freshness = "not_expected_yet"
…
281      if next_slot and next_slot["at"].date() == now_et.date():
282          freshness = "fresh"
```

Không có bất kỳ so sánh nào giữa `observed_at` và `latest_expected_at`. Nghĩa là chừng nào log scheduler còn ghi "thoat OK" thì file `live_state_data.js` cũ bao lâu cũng không đổi verdict.

**Vì sao quan trọng operationally:**
Nếu scheduler chạy nhưng bước `dump_state` fail âm thầm, hoặc file bị khóa/không ghi được mà job vẫn exit 0, thì equity, drawdown, open positions, decision, regime trên header đều là số cũ — và trang vẫn nói "On schedule". Đây đúng định nghĩa "stale data nhìn giống healthy".

Kèm theo, dòng UI duy nhất mang thông tin tuổi runner **bị ẩn vĩnh viễn**:

```html
index.html:37   <b id="runnerContext" hidden>Loading</b>
```

`realtime.js:258-259` ghi `textContent` và `className` vào element đó nhưng **không có chỗ nào bỏ `hidden`** (`rg "runnerContext"` chỉ ra đúng 2 dòng 258/259). Trong khi backend **có** trả `age_seconds`.

**Bằng chứng (đo trực tiếp, read-only, gọi `get_schedule_status` với `now`/`observed_at` giả lập):**

```
03:00 ET (trong NKD window)   obs 2min    -> freshness=fresh
03:00 ET (trong NKD window)   obs 90 DAYS -> freshness=fresh          ← giống hệt
04:00 ET (ngoài window)       obs 2min    -> freshness=not_expected_yet
04:00 ET (ngoài window)       obs 90 DAYS -> freshness=not_expected_yet
11:00 ET (ngoài window)       obs 2min    -> freshness=not_expected_yet
11:00 ET (ngoài window)       obs 90 DAYS -> freshness=not_expected_yet
```

Thực trạng lúc audit: `/api/v1/runner-state` trả `observed_at=2026-08-14T06:58:51Z`, `age_seconds=30654` (**8h31m**), `freshness=not_expected_yet`. DOM: `runnerContextHidden = true`, `runnerContextText = "On schedule · next 14:05 ET"` — chuỗi đó tồn tại trong DOM nhưng người vận hành không nhìn thấy. Nơi duy nhất còn dấu vết là Source Clocks cuối sidebar: `Runner observed 08-14, 02:58 ET`.

**Đề xuất fix:**
1. Trong `get_schedule_status`, thêm nhánh cứng: nếu `latest_expected_at` tồn tại và `observed_at < latest_expected_at - allowance` → `freshness = "stale"` bất kể log nói gì. Trả kèm `state_age_seconds`.
2. Bỏ `hidden` khỏi `index.html:37`, hoặc gộp tuổi runner vào `system-conclusion` của rail.
3. Test backend: `observed_at` cũ 3 ngày + log hôm nay sạch ⇒ freshness **không** được là `fresh`/`not_expected_yet`.

---

### HIGH

---

#### H1 — Ba lane cho ra ba verdict khác nhau về cùng 6 sự kiện

**Vị trí:** `realtime.js:410` (rail) vs `realtime.js:550` (Now Monitor) vs `monitor/backend/job_journal_reader.py:141-160` vs `monitor/backend/open_issue_reader.py:223-231`

**Vấn đề:** ba backend tự cài ba thuật toán "đã recover chưa" khác nhau, frontend tiêu thụ không nhất quán.

- `schedule_status._annotate_incident_lifecycle()` (`:187-207`) gắn `lifecycle` + `recovered_by` và xuất `open_incidents` riêng. Rail dùng đúng field này (`realtime.js:410`) → **đúng**.
- `renderMonitor` (`realtime.js:550`) dùng `schedule?.incidents` — danh sách **đầy đủ**, kể cả đã recover — và gán cứng `status: 'incident'` → `issueStatus()` render **OPEN**. → **sai**.
- `job_journal_reader` chỉ set `lifecycle_status` cho `status == "missed"` **và** `job_type == "stop_repair"` (`:141-154`). Job `failed` của `nkd_night` **không bao giờ** được set → `jobPresentation()` (`realtime.js:1179`) coi là chưa recover → **OPEN**. → **sai**.
- `open_issue_reader` có `later_recovery` riêng (`:223-231`) → loại đúng 6 job này. → **đúng**.

**Vì sao quan trọng operationally:** một alarm luôn đỏ là một alarm người vận hành ngừng đọc. Ở đây tệ hơn: rail nói nominal còn panel chính nói 6 OPEN — operator buộc phải chọn tin cái nào, và lựa chọn sai theo hướng nào cũng nguy hiểm.

**Bằng chứng (DOM đã render lúc 11:34 ET):**

| Vùng UI | Hiển thị |
|---|---|
| `#statusRail` | `systems nominal: feeds live, positions protected` · `1 issue open` |
| `#incidentSummary` | `6 incident / 0 telemetry gap` |
| `#nowMonitorList` | 6 dòng, `monitorStatuses = ["OPEN","OPEN","OPEN","OPEN","OPEN","OPEN"]` |
| `#journal` (Jobs) | `{COMPLETED: 6, "KNOWN DEBT": 16, OPEN: 6}` |
| `#openIssuesSource` | `1 open / evidence 2026-07-30 to 2026-08-14` |

Payload `/api/v1/schedule-status`: `"open_incidents": []`, mỗi phần tử `incidents` mang `"lifecycle":"recovered","recovered_by":"NKD_NIGHT_0230"`.
Payload `/api/v1/job-journal/2026-08-14`: 28 job, `lifecycle_status = None` cho **cả 28**; 6 job `NKD_NIGHT_0200…0225` `status=failed reason="exited with code 1"`, sau đó `NKD_NIGHT_0230…0255` đều `completed_with_debt`.

**Đề xuất fix:**
1. `realtime.js:550` → dùng `schedule?.open_incidents ?? schedule?.incidents` (dùng `??`, **không** `||` — `[]` là truthy trong JS). Incident đã recover đưa xuống lane lịch sử với label `RECOVERED`.
2. `job_journal_reader`: set `lifecycle_status` cho **mọi** job `failed`/`missed` bằng đúng quy tắc same-stream của `schedule_status._stream_of`, không chỉ `stop_repair`.
3. Rút một hàm recovery duy nhất dùng chung cho 3 reader; test: cùng một log ⇒ 3 endpoint cho cùng tập open.

---

#### H2 — Sharpe annualized tính từ 4 quan sát ngày, hiển thị như metric ngang hàng risk thật

**Vị trí:** `realtime.js:314`; nguồn `global_index/live_state_data.js` → `snapshots[].running_metrics.sharpe`

**Vấn đề:** header hiện `Sharpe 10.21`, không có cỡ mẫu, không có caveat, cùng hàng với `Open UPL` / `Realized today` / `Calmar`. Dữ liệu nền: `meta.total_days = 1`, epoch `2026-08-10`, chuỗi equity gồm 5 snapshot trong đó 3 ngày cuối bằng nhau (`50228.75`). Sharpe qua các snapshot: `26.96 → 14.87 → 11.85 → 10.21` — đang phân rã theo `1/√n` chứ không phải đo được gì.

**Vì sao quan trọng operationally:** Sharpe 10 cạnh drawdown thật tạo cảm giác hệ thống đã được chứng minh. Baseline của dự án (`meta.backtest_calmar = 1.65`) không dính dáng gì tới con số này.

**Bằng chứng:** DOM `performanceSharpe = "10.21"`, `performanceCalmar = "--"`, `performanceReturn = "+0.46%"`, `performanceScope = "since Aug 10, 2026"`. `running_metrics.calmar = null` (đúng — bị chặn vì thiếu lịch sử), nhưng `sharpe` thì không bị chặn tương tự.

**Đề xuất fix:** ẩn Sharpe/Calmar dưới ngưỡng cỡ mẫu tối thiểu (ví dụ 20 ngày giao dịch) và render `--` kèm tooltip "n=4, chưa đủ mẫu", giống cách Calmar đang được xử lý. Hoặc luôn in `n=` cạnh giá trị.

---

#### H3 — `14:05 ET` bịa cho mọi sự kiện không có timestamp

**Vị trí:** `realtime.js:931-933`, `:1087`, `:1096`, `:1105`, `:1109`

```js
931  function decisionTime(value, day) {
932    return value ? localTime(value) : `14:05 ET`;
933  }
```

Áp cho entry (`:1091`), exit (`:1100`), và rejected thì hardcode thẳng `time: '14:05 ET'` (`:1109`) cùng `sortKey: ${day}T14:05:00` (`:1105`). Tham số `day` khai báo mà không dùng.

**Vì sao quan trọng operationally:** đây đúng chỗ nhạy nhất của hệ thống. Theo `TASK.md`, cron liên tục 14:10–15:55 tồn tại **chính vì** entry không xảy ra lúc 14:05 (capture rate đo được: 14:10→22%, 14:30→50%, 15:55→100%). Một entry thật lúc 15:40 hiện thành `14:05 ET`, không phân biệt được với giờ có thật, và đó là dữ liệu người vận hành sẽ dùng để reconcile fill quality.

**Đề xuất fix:** khi không có timestamp, render `—` hoặc `time not emitted` và tô khác màu; giữ `sortKey` riêng cho sắp xếp nhưng không hiển thị nó như giờ.

---

#### H4 — Event Journal trộn UTC và naive-local khi sắp xếp và khi format

**Vị trí:** `realtime.js:1121` (sort), `:62-64` (`localTime`), `:1287` (INCURRED)

**Vấn đề:**
`sortKey` là **string** `localeCompare`, nhưng trộn hai định dạng:
- từ session events / runner events: `"2026-08-14T05:10:07Z"` (UTC, có `Z`)
- từ decision fallback: `"2026-08-14T14:05:00"` (naive, không zone)

`"…T14:05:00"` so với `"…T18:05:00Z"` bị so như thể 14:05 **UTC**. Một sự kiện 14:05 ET (=18:05Z) bị xếp sai vị trí ~4 giờ.

Cùng lỗi ở hiển thị: `localTime()` gọi `new Date(iso)`; chuỗi naive được JS parse theo **múi giờ browser**, rồi mới format sang ET. Máy chạy MDT ⇒ `14:05` naive → hiện `16:05 ET`. Cùng dòng, `row.time` lại ghi `14:05 ET`. Hai giờ khác nhau cho một sự kiện.

*Giảm nhẹ:* các dòng decision hiện có `actionable = false` nên block INCURRED không render — nhưng lỗi sắp xếp thì luôn có, và block sẽ render ngay khi decision rows được gắn `problem/impact/action`.

**Đề xuất fix:** chuẩn hóa mọi `sortKey` về epoch millis (`Date.parse`) sau khi gắn zone tường minh; không bao giờ tạo chuỗi ISO thiếu offset trong frontend.

---

### MEDIUM

---

#### M1 — `validStopsFor` không kiểm tra giá stop → stop sai mức vẫn tính "Protected"

**Vị trí:** `realtime.js:149-154`

Điều kiện hợp lệ chỉ gồm: có đủ field, `action` đúng chiều, `qty` khớp tuyệt đối, `status ∈ {PreSubmitted, Submitted}`. **Không** so `aux_price` với `runner.stop_price`, không kiểm tra stop nằm đúng phía so với `market_price`.

Hệ quả: một SELL STP đặt **trên** giá thị trường cho vị thế LONG (hoặc lệch một khoảng lớn do lỗi ratchet/làm tròn) vẫn render `Protected #<id>` màu xanh và vào `metricStopsCovered`.

Thực tế lúc audit: runner `stop_price = 3020.24`, broker `aux_price = 3020.2` — lệch nhỏ do tick (M2K tick = 0.1), UI có hiện cả hai (`stop 3,020.2 · plan 3,020.24`) nhưng **không có ngưỡng**: lệch 0.04 và lệch 40.0 render giống hệt nhau.

**Fix:** thêm điều kiện `|aux_price − runner.stop_price| ≤ k × tick` (`tick` đã có sẵn trong `contract_specs`) và kiểm tra hướng so với `market_price`; vi phạm → `invalid stop`.

---

#### M2 — Mô hình reconcile không biểu diễn được 2 cluster cùng giữ 1 instrument

**Vị trí:** `realtime.js:123-125` (`runnerFor`), `:146-154` (`stopsFor`/`validStopsFor`), `:160-169`

`runnerFor()` khớp broker position với runner position chỉ theo **root + direction**, và trả về phần tử **đầu tiên**. IBKR thì net thành một dòng cho mỗi contract.

Theo thiết kế hệ thống (cluster `roska4_swing` / `roska4_stress` trong `cluster_exposure` của live state), STRESS_MID và swing có thể cùng giữ một micro. Khi đó:
- broker `|position| = 2`, `runnerQuantity` = 1 → **false "size mismatch"** với text sai bản chất ("IBKR holds x2, while runner intent reports x1").
- hai STP × qty 1 vs broker position 2 → `validStopsFor` yêu cầu `qty == 2` ⇒ **cả hai stop bị coi là invalid**, `Stops covered` thành `0 / 1`, sinh 2 incident `invalid stop`, trong khi thực tế position **được bảo vệ đủ**.

**Vì sao quan trọng:** false alarm ở lane bảo vệ position là loại làm hỏng niềm tin nhanh nhất — và nó xảy ra đúng vào ngày STRESS_MID có lệnh, tức ngày rủi ro cao nhất.

**Fix:** reconcile theo **tổng** (sum runner contracts theo root + direction) thay vì phần tử đầu; cộng dồn qty của các stop cùng contract trước khi so với `|position|`.

---

#### M3 — Đối chiếu số lượng phụ thuộc so khớp 6 trường giữa 2 file ghi lệch thời điểm, có cả float equality

**Vị trí:** `realtime.js:126-145`

Snapshot `open_positions` **không có** field số lượng (đã kiểm tra `live_state_data.js`: chỉ `inst/cluster/direction/days_held/risk_sized/entry_day/entry_price/entry_time/stop_price/stop_order_id/stop_deferred`). Nên `runnerQuantity` luôn phải rơi xuống `persistedRunnerFor()`, vốn yêu cầu khớp **đồng thời**: root, direction, cluster, `entry_day[0:10]`, `|Δentry_price| < 1e-8`, **và** `stop_order_id` bằng nhau.

Hai nguồn ghi ở nhịp khác nhau: `live_positions.json` (mtime 07:31 local) vs `live_state_data.js` (mtime 00:58 local). Chỉ cần runner thay stop (ratchet ⇒ order id mới) là hai file lệch `stop_order_id` cho tới slot kế tiếp ⇒ `runnerQuantity = null` ⇒ telemetry gap "runner quantity missing" + `brokerPositionsMatchNow()` = false + "Position match: size unknown".

**Fix:** khớp theo khóa ổn định (`inst|cluster|direction|entry_day`), coi `entry_price`/`stop_order_id` là bằng chứng phụ chứ không phải điều kiện khớp; hoặc đưa `contracts` vào `dump_state` để bỏ hẳn đường vòng.

---

#### M4 — Không có đối chiếu ledger runner ↔ tài khoản broker trên trang Realtime

> **NÂNG LÊN HIGH (2026-08-14).** Giữ nguyên ID `M4` để mọi tham chiếu chéo còn trỏ đúng.
> Lý do nâng: cùng ngày phát hiện bug định tuyến `MNKD` sang contract full-size `NKD` thay
> vì micro `MNK` — bốn lệnh 08-10/11 realised **−$1,400 ở broker** trong khi sleeve ledger
> book **−$140**, đúng 10.0000×. Giá vào/ra khớp IBKR Flex statement đến từng cent, chỉ
> multiplier sai, nên mọi panel dựa trên ledger runner đều nhìn "bình thường" và header vẫn
> ghi **+$229**. Không panel nào trên trang này có thể đã bắt được. Đây thôi không còn là
> thiếu tiện nghi — nó là một lớp lỗi mất tiền mà dashboard mù hoàn toàn.

**Vị trí:** `index.html:44-48`; `realtime.js:270`, `:309-316`

Header: `Paper Equity $50,229` / `+$229` / `+0.46%` / `since Aug 10, 2026` / `base $50,000`.
Payload `runner-state` cùng lúc chứa: `meta.broker_equity = 996311.98`, `meta.paper_start = {date: 2026-07-08, equity: 1000480.0}` → **−$4,168 kể từ paper start**. Cả hai field **không được render ở đâu** trên trang này. `system_epoch = 2026-08-10` cũng có nghĩa ledger đã được re-anchor, khoản lỗ trước epoch không nằm trong `+$229`.

Đây là **quyết định có chủ đích** — tooltip nói rõ "excludes the broker account's total liquidation value", `monitor/paper_pnl_compare.json.notes` ghi *"broker equity is context only unless an IBKR ledger/Flex source is wired into the comparison"*, và test `test_frontend_modules_keep_data_boundaries` khẳng định `assert "Broker Equity" not in realtime`. Nhưng trên **màn hình realtime** thì hệ quả là: không có bất kỳ dấu hiệu nào cho biết tài khoản thật đang âm, cũng không có link sang `/paper` nơi việc reconcile được làm.

**Fix:** thêm một dòng nhỏ read-only `Broker acct: $996,312 (−$4,168 since 2026-07-08) → xem /paper`. Giữ nguyên nguyên tắc không trộn hai ledger, chỉ cần **nhìn thấy được** là chúng khác nhau.

---

#### M5 — `HMM fit 22/22 complete` tô xanh trong khi 22/22 fit đều có convergence warning

**Vị trí:** `realtime.js:246-251`

```js
248  $('modelFitStatus').className = fitDiagnostic?.completed_fits === fitDiagnostic?.attempts ? 'positive' : 'warning';
```

Màu chỉ dựa trên `completed == attempts`, bỏ qua `non_convergence_count`. Payload hôm nay: `attempts=22, completed_fits=22, non_convergence_count=22`. DOM: `hmmFit = "22/22 complete"`, `hmmFitClass = "positive"` (xanh). Số 22 warning chỉ nằm trong `title` (phải hover mới thấy).

Backend đã phân loại "diagnostic only, no gate failure" và điều đó hợp lý — nhưng **xanh** là màu của "không cần nhìn", còn đây là 100% fit không hội tụ trên một model đã 20 tháng tuổi.

**Fix:** `positive` chỉ khi `non_convergence_count === 0`; ngược lại `neutral/watch` với text `22/22 complete · 22 warn`.

---

#### M6 — `Stops covered` (header) và lane bảo vệ (rail/monitor) xử lý `stop_deferred` khác nhau

**Vị trí:** `realtime.js:296-299` vs `:391-394`, `:581`

- Header `metricStopsCovered` chỉ đếm `validStopsFor(position).length > 0` — **không** cộng deferred.
- Rail `stripUnprotected` và incident `unprotected` đều **loại trừ** deferred (`&& !runner.stop_deferred`).

Nên một position deferred hợp lệ ⇒ header `0 / 1` (nhìn như chưa được bảo vệ) trong khi rail nói nominal và card position ghi `Deferred by rule`. Đã xảy ra thật: `2026-08-10` có `stop_deferred × 4`, `2026-08-11` có `stop_deferred × 4`.

**Fix:** header dùng chung một hàm phân loại với rail, và tách hiển thị: `1 covered / 0 deferred / 0 naked` thay vì một phân số.

---

#### M7 — `coverage.to` luôn là hôm nay kể cả khi log dừng từ nhiều ngày trước

**Vị trí:** `monitor/backend/open_issue_reader.py:174`

```python
174  last_day = max(stamped_lines[-1][0].astimezone(ET).date(), dt.datetime.now(ET).date())
```

UI render trực tiếp: `openIssuesSource = "1 open / evidence 2026-07-30 to 2026-08-14"` (`realtime.js:679-681`). Nếu scheduler chết từ 2026-08-10, dòng này vẫn quảng cáo evidence tới hôm nay — trong khi tooltip của chính section nói *"Known debt remains open until positive resolution evidence exists"*, tức người đọc được dạy tin vào phạm vi evidence.

**Fix:** `coverage.to` = ngày của dòng log cuối cùng; nếu nhỏ hơn hôm nay thì hiển thị `evidence ends <date> (N days ago)` màu cảnh báo.

---

#### M8 — `fatalBanner` chỉ bật khi **cả 5** endpoint fail; fail lẻ chỉ được báo bằng opacity

**Vị trí:** `realtime.js:186-194`, `:213`; `realtime.css:111`

```js
213  $('fatalBanner').hidden = results.some(result => result.status === 'fulfilled');
```

Nếu `/api/v1/runner-state` fail còn 4 endpoint kia OK: banner **ẩn**; `state.runner` giữ payload cũ (`{...(state.runner||{}), freshness:'unknown'}`) nên `latestSnap()` vẫn trả snapshot cũ; equity / drawdown / regime / decision / positions runner-side tiếp tục render số cũ. Tín hiệu duy nhất:

```css
111  .metrics.broker-stale .broker-derived, .metrics.runner-stale .runner-derived { opacity: .42; }
```

Mờ 42%, **không có chữ nào**. Trên nền tối rất dễ bỏ qua; và nó không nói *nguồn nào* hỏng hay *bao lâu rồi*.

**Fix:** mỗi nguồn hỏng ⇒ một dòng text trong rail (`runner-state unreachable · last good 08:31 ET`), không chỉ opacity. Cân nhắc render `--` thay vì số cũ khi `state.runner.error` khác null.

---

### LOW

| # | Vị trí | Vấn đề | Fix |
|---|---|---|---|
| L1 | `realtime.js:454-505`, `:9-19`, `:319-321`; `realtime.css:182-185` | Dead code: `renderRailLegacy()` không được gọi ở đâu; `railItem()` và `railTips` (9 nhãn: Stop protection, Position match, Risk breaker, Regime data, Model health…) chỉ phục vụ nó; CSS `.scheduler-health` mồ côi. DOM xác nhận `#statusRail .status-item` = **0**. Người đọc code tưởng rail vẫn có 9 chỉ báo. | Xóa hoặc gắn comment `DEPRECATED` rõ ràng. |
| L2 | `realtime.js:62-64` | `localTime()` không format giờ local — nó format **ET**. Tên gây hiểu nhầm ở đúng phần code nhạy timezone nhất. | Đổi tên `etDateTime()`. |
| L3 | Job Journal | 16/28 dòng hôm nay là `KNOWN DEBT` với cùng một nội dung G2 model-age. Nhiễu che các dòng thật. | Gộp thành một dòng `16 slots · known debt (G2)`, giữ chi tiết trong detail. |
| L4 | `realtime.js:683-684`; `index.html:119-125` | Trên mobile (`≤680px`) `openIssuesShell.open = false` → issue đang mở duy nhất bị giấu sau `<details>`. DOM đo tại 487px: `issuesShellOpen = false`. | Luôn mở khi `issues.length > 0`. |
| L5 | Console | `GET /favicon.ico → 404`. Vô hại nhưng làm console không sạch, che lỗi thật. | Thêm favicon hoặc route no-content. |
| L7 | `monitor/backend/job_journal_reader.py:326,331` vs `monitor/backend/schedule_status.py:177` | **Hai reader bất đồng về thế nào là "job chạy xong".** `schedule_status._evidence` nhận cả `"completed ok"` lẫn `"thoat ok"`. `job_journal_reader` chỉ nhận `"completed OK"` và `"thoat OK nhung"` — một dòng `"thoat OK"` **trần** không khớp nhánh nào, nên job kẹt ở `running` vĩnh viễn trong Job Journal, `later_same_stream` không tìm ra nó, và `open_issue_reader` dựng issue `running` sau 20 phút; trong khi rail lại gọi slot ấy là `executed`. Cùng một hình dạng lỗi với H1. **Latent, chưa kích hoạt:** đo trên toàn bộ `scheduler_*.log` retained, mọi lần `thoat OK` đều kèm `nhung` (0 lần trần). Phát hiện khi dựng fixture cho H1: `"thoat OK"` cho `status=running`, `"completed OK"` cho `status=completed`. | Đưa việc nhận diện "hoàn tất" về một helper dùng chung cho cả hai reader thay vì hai bộ chuỗi riêng. |
| L6 | `live_state_data.js` → `meta.operational_status.breaker.dd_pct` | `breaker.dd_pct = 0.086` (đơn vị **phần trăm**) trong khi `snapshot.drawdown_pct = 0.00086` (đơn vị **phân số**) — cùng một payload, chênh 100×. Hiện UI không render field này nên **chưa có bug**, nhưng bất kỳ ai nối `pct(ops.breaker.dd_pct)` sẽ ra 8.6%. | Thống nhất đơn vị ở nguồn, hoặc đổi tên `dd_pct_display`. |

---

## Data Consistency Matrix

Đối chiếu UI đã render (DOM lúc 2026-08-14 11:34 ET) ↔ payload API ↔ file nguồn.

| UI metric / status | Giá trị hiển thị | Backend field / source | Match? | Ghi chú |
|---|---|---|---|---|
| Paper Equity | `$50,229` | `runner-state.payload.snapshots[-1].equity` = 50228.75 ← `global_index/live_state_data.js` | **yes** | Ledger runner, không phải NetLiquidation |
| Net / Return / Base | `+$229` / `+0.46%` / `$50,000` | `meta.net_pnl`, `running_metrics.total_return`, `meta.account` | **yes** | Scope `since Aug 10, 2026` = `meta.system_epoch` |
| *(không có)* Broker equity | — | `meta.broker_equity` = 996311.98; `live_positions.json.breaker.last_broker_equity` = 996311.98 | **no — không render** | M4. Δ vs `paper_start` = **−$4,168** |
| Open UPL | `+$201` | `broker.payload.unrealized_pnl` = 192.09 ← IBKR | **yes** | Lệch do poll khác thời điểm (`maximumFractionDigits: 0`) |
| Realized today | `+$0` | `snapshots[-1].decision.realized_today` = 0 | **yes** | |
| Sharpe | `10.21` | `running_metrics.sharpe` = 10.2112 | **yes (số)** / **no (ý nghĩa)** | H2 — n=4 ngày, không có caveat |
| Calmar | `--` | `running_metrics.calmar` = null | **yes** | Bị chặn đúng vì thiếu lịch sử |
| Drawdown | `0.09%` / `$43.25` / `0.6% of 15.00%` | `drawdown_pct`=0.0008603, `drawdown_dollars`=43.25, `meta.hard_dd_pct`=0.15 | **yes** | Đơn vị đúng ở đường render này |
| Peak MaxDD | `--` (dòng nhỏ) | `meta.max_dd_pct` = 0.00086 | **yes** | |
| Positions | `1` | `broker.payload.positions` (M2KU6 ×1) | **yes** | |
| Working orders | `1` | `broker.payload.orders` (STP SELL 1 @3020.2, PreSubmitted, GTC) | **yes** | |
| Stops covered | `1 / 1` | `validStopsFor()` — action/qty/status | **yes hôm nay** / **unclear tổng quát** | M1 (không check giá), M2 (multi-cluster), M6 (deferred) |
| Position card protection | `PROTECTED #288` | broker `order_id` 288 == snapshot `stop_order_id` "288" == `live_positions.json.stop_order_id` "288" | **yes** | 3 nguồn đồng ý |
| stop / plan | `3,020.2` / `3,020.24` | broker `aux_price` 3020.2 vs runner `stop_price` 3020.24 | **yes (hiển thị)** | Lệch 0.04 (tick=0.1) không được đánh giá — M1 |
| entry / last | `3,025.3` / `3,065.54` | `runner.entry_price` 3025.3; `broker.market_price` 3063.84 | **yes / lệch nhẹ** | `market_price` đổi giữa 2 lần poll |
| Opened | `2026-08-10` · `08-10, 15:10 ET` | `snapshot.entry_time = null` → phục hồi qua `entry_time_reader` từ `trade_log.jsonl` | **yes** | Cơ chế recovery hoạt động đúng |
| Held / Risk budget | `4d` / `$602` | `days_held`=4, `risk_sized`=602.14 | **yes** | |
| Regime | `Calm` | `snapshots[-1].regime` | **yes** | |
| SPY data | `Aug 12` | `operational_status.regime_freshness` = `{status: OK, bday_stale: 2, last_spy_date: 2026-08-12}` | **yes** | `status=OK` với 2 bday stale — đúng spec G1 (SOFT khi >2) |
| Model age | `20 mo stale` (amber) | `operational_status.model_age` = `{status: URGENT, months_old: 20, model_name: fit_C}` | **yes** | |
| HMM fit | `22/22 complete` (**xanh**) | `session-events.hmm_fit_diagnostic`: attempts 22, completed 22, `non_convergence_count: 22` | **no — màu sai** | M5 |
| Broker context | `Live · updated 7s ago` | `broker.connected=true`, `freshness=fresh`, `age_seconds=9.05` | **yes** | Ngưỡng 30s ở `app.py:169` |
| Runner context (ẩn) | *(hidden)* `On schedule · next 14:05 ET` | `runner-state.freshness=not_expected_yet`, `age_seconds=30654` (**8h31m**) | **no — không hiển thị** | C2 |
| Status rail | `systems nominal: feeds live, positions protected` · `1 issue open` | `schedule.open_incidents=[]` + `openIssues.issues.length=1` | **yes** | Đúng, nhưng mâu thuẫn với Now Monitor |
| Now Monitor | `6 incident / 0 telemetry gap`, 6× **OPEN** | `schedule.incidents` (6, tất cả `lifecycle: recovered`, `recovered_by: NKD_NIGHT_0230`) | **no** | H1 |
| Job Journal | 28 job: 6 COMPLETED / 16 KNOWN DEBT / 6 **OPEN** | job-journal: 6 `failed`, 16 `completed_with_debt`, 6 `completed`; `lifecycle_status = None` × 28 | **no** | H1 |
| Open Issues | `1 open / evidence 2026-07-30 to 2026-08-14` | `open-issues.issues` = 1 (`known_debt:model_age`, 163 occurrences) | **yes (count)** / **no (coverage.to)** | M7 |
| Schedule facts | NEXT JOB `STOP_REPAIR_1220` 12:20 ET · NEXT DECISION `PREFLIGHT` 13:45 ET · LATEST JOB `STOP_REPAIR_1020` · LATEST DECISION `MAX_HOLD_EXIT` | `next_scheduled_job` 16:20Z, `next_decision_job` 17:45Z, `latestObservedJob()`, `latestDecisionJob()` | **yes** | Dùng job_id thật của scheduler — tốt cho grep log |
| Source Clocks | Runner observed `08-14, 02:58 ET` · freshness `not_expected_yet` · Broker observed `11:34 ET` | khớp payload | **yes** | Là nơi **duy nhất** lộ ra runner đã 8.5h |
| *(không có)* connectivity / reconcile incidents | — | `session-events` phát `connectivity_outage`, `broker_reconcile_incident` (08-07/10/11/12) | **no — code chết** | C1 |
| Rejected signals / cap blocks | `No rejected or halted entries` | `decision.rejected_detail=[]`, `rejected_today={}`, `halted_today=0` | **yes** | Ngày 08-10 log có REJECTED cap-block thật (`paper_pnl_compare.signal_path_audit`) → panel có dữ liệu khi có việc |

---

## UI/UX Review

Trang trả lời được 6 câu hỏi vận hành tới đâu:

| Câu hỏi | Trả lời được? | Ghi chú |
|---|---|---|
| System có alive không? | **Một phần** | Broker alive rõ (`Live · 7s ago`). Runner alive **không rõ** — nhãn `fresh` không phụ thuộc tuổi (C2), tuổi thật bị ẩn. |
| Trading có safe không? | **Không trực tiếp** | Không có dòng nào nói "breaker OK / entries allowed". `breaker.level=OK` chỉ được dùng ngầm trong rail. Rail cũ có mục `Risk breaker` — đã thành dead code (L1). |
| Position có protected không? | **Có** | Card position rõ nhất trên trang: `PROTECTED #288`, có cả stop/plan/entry/last trên price track. Điểm mạnh thật sự. |
| Jobs có healthy không? | **Mâu thuẫn** | Ba câu trả lời khác nhau (H1). |
| Data/model có fresh không? | **Có, cho input** | `SPY data Aug 12` + `Model age 20 mo stale` rõ ràng. Nhưng `HMM fit` xanh sai (M5), và freshness của **chính runner state** thì không (C2). |
| Có blocker nào chưa resolve không? | **Có, nhưng bị pha loãng** | 1 open issue thật, chìm giữa 6 incident giả + 16 dòng KNOWN DEBT trùng lặp. |

### Nên giữ

- **Position card.** Price track với 3 marker (stop / entry / last), `stop … · plan …`, `PROTECTED #id`, và caption entry-time phân biệt 4 lý do vắng mặt (`fill time not recorded` / `trade log record does not match` / `no trade log record` / `not emitted`) — đây là phần honest nhất của toàn trang.
- **Kỷ luật "không tái tạo broker truth từ runner state"** (`realtime.js:736-739`): khi mất IBKR, grid ghi thẳng *"Positions are intentionally not reconstructed from runner state"*. Đúng nguyên tắc.
- **Dùng job_id gốc của scheduler** trong Schedule Facts thay vì đặt tên đẹp — operator grep thẳng ra `scheduler_MMDD.log`. Comment `realtime.js:371-373` giải thích rõ, giữ nguyên.
- **Cấu trúc Problem / Impact / Action / Evidence + "Closes when"** cho mỗi issue. Mẫu actionable đúng chuẩn.
- **Tách `broker-derived` vs `runner-derived`** bằng class — đúng ý niệm, chỉ cần biểu đạt mạnh hơn (M8).
- **Rail clock đa múi giờ với đánh dấu `+1`** cho phiên NKD — đúng nhu cầu thật; comment `:84-88` giải thích lý do không dùng superscript.

### Nên đổi

1. **Now Monitor phải dùng `open_incidents`**, incident đã recover xuống lane lịch sử với nhãn `RECOVERED` (H1).
2. **Đưa tuổi runner state lên rail** dạng text (C2), không phải chỉ opacity.
3. **`Stops covered` tách 3 trạng thái** thay vì phân số: `covered / deferred / naked` (M6).
4. **HMM fit đổi màu theo `non_convergence_count`** (M5).
5. **Thời gian không có thật phải render `—`**, không phải `14:05 ET` (H3).
6. **Sharpe kèm `n=`** hoặc ẩn dưới ngưỡng mẫu (H2).
7. **`coverage.to` phản ánh log thật** (M7).

### Nên bỏ / gộp

- `renderRailLegacy()` + `railItem()` + `railTips` + CSS `.scheduler-health` — dead code (L1).
- Khối `if (schedulerHealth)` — bỏ điều kiện, giữ nội dung (C1).
- 16 dòng `KNOWN DEBT` G2 trong Job Journal → gộp 1 dòng (L3).
- `decisionTime(value, day)` — tham số `day` không dùng.

### Nên promote thành top-level blocker

Bốn thứ hiện **không** ở trên cùng mà đáng ra phải:

1. **Broker feed unusable** — hiện chỉ là một telemetry gap trong danh sách (và bị nén khi có TWS outage). Đây là điều kiện làm **vô hiệu** toàn bộ kết luận về position và protection ⇒ phải là banner trên cùng, cùng cấp với `fatalBanner`.
2. **Runner state stale quá ngưỡng** — hiện vô hình. Mọi con số runner-derived (equity, drawdown, decision, regime, open positions) đều phụ thuộc nó.
3. **Bất kỳ position nào naked (không stop, không deferred)** — hiện là một dòng bình đẳng giữa 6 incident scheduler giả. Đây là loại duy nhất mất tiền trong vài phút.
4. **Broker ledger divergence** *(thêm 2026-08-14 cùng lúc nâng M4 lên HIGH)* — khoảng chênh giữa ledger runner và tài khoản broker thật. Hiện **không hiển thị ở đâu**, dù `meta.broker_equity` và `meta.paper_start` đều nằm sẵn trong payload. Bug MNKD 10× chứng minh vì sao điều này quan trọng: sai multiplier không làm lệch giá vào/ra, nên **không** panel nào dựa trên ledger runner có thể phát hiện — chỉ khoảng chênh với broker mới lộ ra. Đây là lớp lỗi mà mọi kiểm tra khác trên trang đều mù.

Đề xuất: rail hiện tại (`system-conclusion`) đúng là nơi cho bốn thứ này; hiện nó đang gộp tất cả thành một câu và câu đó bị 6 incident giả bên dưới phản bác.

### Desktop / mobile

Đo bằng DOM, không phải bằng mắt:

| Viewport | `documentElement.scrollWidth` / `clientWidth` | Overflow ngang trang | Ghi chú |
|---|---|---|---|
| 981px (desktop) | 981 / 981 | **Không** | 0 element vượt biên |
| 487px (compact, qua breakpoint 680px) | 487 / 487 | **Không** | 7 element vượt biên **nhưng đều nằm trong** `.table-wrap` có `overflow-x: auto` (sw=506, cw=454) → cuộn nội bộ đúng cách |

- Không có chồng chữ, không có layout shift do button (button chỉ toggle nội dung sẵn có, không đổi kích thước container).
- `.system-conclusion b` dùng `white-space: nowrap; text-overflow: ellipsis` ở desktop và `white-space: normal` ở ≤680px (`realtime.css:122`, `:530-532`) — xử lý đúng.
- **Vấn đề duy nhất ở mobile:** Open Issues collapse mặc định (L4).

### Warning/error có actionable không?

**Có, và tốt hơn mức trung bình.** Mọi incident/issue/job đều có `Action` cụ thể, ví dụ:
- *"Reconcile runner intent and IBKR protection immediately using the approved operational workflow."*
- *"Verify the order in IBKR and use the approved operational procedure if cancellation is required."*
- *"Keep out of the new-incident lane and complete the separately approved model re-freeze decision."*

Điểm trừ: các câu này trỏ tới "approved operational workflow" mà không link tới `docs/futures/OPERATIONS.md` — người vận hành phải tự nhớ runbook nào. Đề xuất thêm link tương đối.

---

## Safety Review

### Hidden risk

| Rủi ro | Cơ chế | Mức |
|---|---|---|
| Mất kết nối IBKR mà Now Monitor báo CLEAR | C1 — incident chết + gap bị nén bởi `twsOutageOpen` | **Critical** |
| Lệch position broker/runner không sinh incident | C1 — `openReconcile` trong nhánh chết | **Critical** |
| Stop đặt sai mức vẫn hiện `PROTECTED` xanh | M1 — không kiểm tra `aux_price` | High |
| Multi-cluster cùng instrument → 2 stop hợp lệ bị gắn `invalid`, `covered 0/1` | M2 | Medium (false alarm, không phải false safe) |
| Lỗ trước `system_epoch` không xuất hiện trong `+$229` | M4 — ledger re-anchor 2026-08-10, broker equity không render | Medium |
| Sharpe 10.21 tạo cảm giác đã được chứng minh | H2 | Medium |

### Stale data risk

Đây là nhóm nặng nhất.

1. **`freshness` mù với tuổi snapshot** (C2). Đã đo: 90 ngày = 2 phút.
2. **Tuổi snapshot bị ẩn khỏi UI** (C2) — `runnerContext` mang `hidden`, backend vẫn trả `age_seconds`. Thực tế lúc audit runner đã 8h31m và trang không nói gì.
3. **Fail lẻ một endpoint chỉ được báo bằng `opacity: .42`** (M8) — payload cũ tiếp tục render như số hiện tại.
4. **`coverage.to` luôn là hôm nay** (M7) — Open Issues quảng cáo phạm vi evidence không có thật.
5. **Không hiển thị `paper_vs_backtest.stale_through`** — snapshot ghi `expected_equity: null, divergence_pct: null, stale_through: "2026-08-12"`, tức backtest curve đã stale 2 ngày; Realtime bỏ qua hoàn toàn (chấp nhận được — đó là việc của `/paper`), nhưng vẫn hiện Sharpe/Return như thể đã đối chiếu.

**Kết luận nhóm này: có, stale data hiện tại nhìn giống healthy.**

### Command / control risk

**Không có rủi ro.** Đã kiểm tra runtime:

```
forms: 0
inputs: ["fontSelector"]
buttons: chỉ issue-list-row / job-trigger / data-journal-view  (đều là toggle hiển thị)
```

- Không có nút restart / up / down / cancel order / close position.
- Backend chỉ `@app.get` (14 route), có test khóa: `test_backend_routes_are_read_only`, `test_backend_does_not_import_runner_or_write_state`, `test_ibkr_reader_default_client_id_is_99` (99 ≠ runner 1).
- Các thao tác vận hành thật nằm ở `monitor/ops.py` (CLI riêng), **không** nối vào trang này. Đây là quyết định thiết kế đúng — **giữ nguyên**.
- Không có control mơ hồ, không có nút nào cần confirmation vì không có nút nào gây tác động.

### Missing confirmation / feedback

Không áp dụng cho command (không có command). Nhưng thiếu feedback ở tầng dữ liệu:

- Không có trạng thái `loading` cho lần poll đầu — trang hiện `--` / `Loading` rồi nhảy số, không phân biệt "đang tải" với "không có dữ liệu".
- Khi một endpoint fail, **không có thông báo nào cho biết endpoint nào** — `state.*.error` được lưu nhưng chỉ dùng làm `evidence` bên trong telemetry gap tương ứng, mà gap broker lại có thể bị nén (C1).
- `fatalBanner` là all-or-nothing (M8).

---

## Test Gaps

Hiện trạng: `monitor/test_dashboard_backend.py` — **114 test, tất cả PASS**, chất lượng backend cao (lifecycle recovery, ET/local boundary, torn JSONL line, tmpdir hygiene, entry-time price mismatch…). Nhưng **frontend chỉ có đúng 1 test**: `test_frontend_modules_keep_data_boundaries` (`:2573-2654`) gồm ~80 assert dạng `assert "chuỗi" in file`. Nó không thể bắt bất kỳ finding nào ở trên — thậm chí nó **assert `"system-conclusion" in realtime_js`** và vẫn PASS trong khi rail chỉ còn 0 mục và `renderRailLegacy` đã chết.

| Behavior chưa được test | Risk | Test đề xuất |
|---|---|---|
| Mọi `$('id')` trong JS đều tồn tại trong `index.html` | **C1** — nhánh chết im lặng vô hiệu 2 alarm | Test tĩnh: regex `\$\('(\w+)'\)` trong `realtime.js` → assert mỗi id có trong `index.html`, trừ allowlist khai báo tường minh |
| Không còn element mang `hidden` mà JS ghi nội dung vào | **C2** — `runnerContext` | Test tĩnh: id có `hidden` trong HTML ⇒ JS phải có chỗ set `.hidden = false` |
| `freshness` khi `observed_at` cũ nhưng log sạch | **C2** | Backend: `get_schedule_status(observed_at=now-3d, now=…)` trong active window ⇒ assert **không** phải `fresh` |
| Payload contract của `/api/v1/runner-state` | Đổi field im lặng làm hỏng UI | Contract test: assert khóa `{source, observed_at, server_now, age_seconds, freshness, expected_next_at, error, payload, entry_times, event_history}` và enum `freshness ∈ {fresh, not_expected_yet, late, missing, unknown, stale}` |
| Payload contract của `/api/v1/schedule-status` | H1 | Assert `incidents` ⊇ `open_incidents`, mọi phần tử `incidents` có `lifecycle ∈ {open, recovered}` và `recovered_by` |
| Ba reader cho cùng kết luận recovery | **H1** | Cùng một fixture log: assert `{incident open theo schedule_status}` == `{job open theo job_journal}` == `{issue incident theo open_issues}` |
| `job_journal_reader` set `lifecycle_status` cho job `failed` | **H1** | Fixture: `NKD_NIGHT_0200 failed` + `NKD_NIGHT_0230 completed` ⇒ assert `lifecycle_status == "recovered"` |
| Now Monitor không render incident đã recover là OPEN | **H1** | DOM smoke: stub `/api/v1/schedule-status` trả `open_incidents: []` + `incidents: [6 recovered]` ⇒ assert `#nowMonitorList .issue-status` không chứa `OPEN` |
| Rendering khi `connectivity_outage status=open` | **C1** | DOM smoke: stub session-events ⇒ assert Now Monitor có 1 dòng `IBKR connectivity`, và `monitorClearIndicator.hidden === true` |
| Rendering khi broker disconnect | **C1 / M8** | DOM smoke: stub `/api/v1/broker` `connected:false` ⇒ assert có dòng blocker dạng text (không chỉ opacity), assert Positions grid hiện thông báo "not reconstructed" |
| Rendering khi runner-state stale | **C2** | DOM smoke: stub `age_seconds: 86400` ⇒ assert có text tuổi hiển thị + class cảnh báo |
| Stop sai giá vẫn tính covered | **M1** | Unit JS: `validStopsFor` với `aux_price` lệch 50 tick ⇒ assert **không** hợp lệ |
| 2 cluster cùng instrument | **M2** | Unit JS: broker `|position|=2` + 2 runner position + 2 STP ×1 ⇒ assert `covered = 1/1`, **không** sinh `invalid stop` |
| `runnerQuantity` khi `stop_order_id` lệch giữa 2 file | **M3** | Unit JS: snapshot `stop_order_id="288"`, persisted `"301"` ⇒ hành vi phải khai báo tường minh, không rơi âm thầm về `null` |
| `decisionTime` không bịa giờ | **H3** | Unit JS: `decisionTime(null, day)` ⇒ assert **không** chứa `14:05` |
| Sắp xếp Event Journal trộn zone | **H4** | Unit JS: trộn `…T05:10:07Z` và `…T14:05:00` ⇒ assert thứ tự theo thời gian tuyệt đối |
| Không overflow ngang, desktop + mobile | Regression layout | Playwright: 1440×900 và 390×844 ⇒ assert `documentElement.scrollWidth <= clientWidth`; assert mọi element vượt biên đều nằm trong ancestor có `overflow-x: auto` |
| Page load không lỗi console | Regression | Playwright: assert 0 console error (loại trừ favicon 404, hoặc thêm favicon để assert 0 tuyệt đối) |
| Open Issues hiển thị được trên mobile | L4 | Playwright ≤680px: assert `#openIssuesShell.open === true` khi có issue |
| Font selector persist | Nhẹ | Playwright: đổi font ⇒ reload ⇒ assert `documentElement.dataset.font` giữ nguyên |
| *(không áp dụng)* command button disabled/loading/error/success | — | **Trang không có command button.** Thay vào đó đề xuất **test khóa**: assert `realtime.js` không chứa `method: 'POST'|'PUT'|'DELETE'` và `index.html` không chứa `<form`. Đây là bất biến an toàn đáng khóa lại bằng test. |

---

## Final Verdict

### Có thể rely dashboard này trong trading chưa?

**Chưa — không dùng làm nguồn kết luận duy nhất.**

Trang này an toàn ở chiều "không gây hại": read-only tuyệt đối, không có control nào có thể thao tác nhầm vào broker hay runner, client_id tách biệt (99 vs runner 1), backend không import runner. Về mặt đó nó vượt tiêu chuẩn.

Nhưng nó **chưa đủ tin cậy để kết luận "hệ thống đang ổn"**, vì hai lý do độc lập nhau, và mỗi lý do tự nó đủ để chặn:

- Hai alarm quan trọng nhất (mất IBKR, lệch position broker/runner) nằm trong code chết, **kèm theo** cơ chế nén gap khiến trạng thái mất broker feed có thể render thành CLEAR.
- Runner state cũ tùy ý vẫn được gắn nhãn `fresh`, và tuổi thật của nó bị ẩn khỏi giao diện.

Cộng thêm việc trang hiện đang **tự mâu thuẫn ngay lúc audit** (rail nominal vs 6 OPEN vs 1 issue), người vận hành không có cách nào biết nên tin vùng nào — và đó là trạng thái tệ hơn một dashboard đơn giản hơn nhưng nhất quán.

**Dùng được ngay hôm nay cho:** xem position + protection (card position đáng tin), xem quyết định trong ngày, xem lịch job sắp tới, tra order đang làm việc.
**Không dùng để kết luận:** "hệ thống alive", "không có blocker", "feed đang tốt".

### Bắt buộc phải sửa trước khi rely

**Chặn (blocker):**

1. **C1** — bỏ `if (schedulerHealth)` (`realtime.js:519,548`), đưa `openConnectivity` + `openReconcile` ra ngoài; bỏ `&& !twsOutageOpen` ở `:631` hoặc đổi sang kiểm tra incident thật sự tồn tại.
2. **C2** — `schedule_status.get_schedule_status` phải fail trên tuổi `observed_at`, thêm trạng thái `stale`; bỏ `hidden` khỏi `index.html:37`.
3. **H1** — `realtime.js:550` dùng `open_incidents`; `job_journal_reader` set `lifecycle_status` cho mọi job `failed`/`missed`; thống nhất một hàm recovery cho cả 3 reader.
4. **M4** *(nâng lên blocker 2026-08-14)* — hiển thị khoảng chênh ledger runner ↔ tài khoản broker. Bug MNKD 10× cho thấy đây là lớp lỗi mà **không** kiểm tra nào khác trên trang bắt được: sai multiplier giữ nguyên giá vào/ra nên mọi panel ledger-based đều xanh, chỉ khoảng chênh với broker mới lộ. Không cần trộn hai ledger — chỉ cần **nhìn thấy được** là chúng khác nhau.

**Bắt buộc kèm theo (nếu không, blocker sẽ tái phát):**

5. Test tĩnh "mọi `$('id')` tồn tại trong HTML" + "không ghi vào element `hidden`" — hai test này một mình chặn được cả C1 và C2 tái diễn.
6. Contract test cho `/api/v1/runner-state` và `/api/v1/schedule-status`.
7. Bộ DOM smoke tối thiểu: page load / broker disconnect / runner stale / open issue / no-overflow ở 2 viewport. **Bổ sung 2026-08-14:** "no-overflow" phải kiểm nội dung bị **cắt**, không chỉ trang bị cuộn — xem ghi chú ở khối trạng thái đầu file.

**Nên sửa sớm, không chặn:**

8. **H3** — không bịa `14:05 ET`.
9. **M1** — kiểm tra giá stop trước khi gọi là `Protected`.
10. **M6** — `Stops covered` tách covered / deferred / naked.
11. **H2 / M5** — Sharpe kèm cỡ mẫu; HMM fit không tô xanh khi 22/22 warning.

**Sau khi 1–7 xong**, trang này đủ tin cậy để làm màn hình vận hành chính cho phiên paper; các mục 8–11 nâng chất lượng kết luận nhưng không phải điều kiện an toàn.

---

# Audit Phase 2 — mở 2026-08-15

Phase 1 đóng 20/21 finding. Phase 2 mở ra từ một câu hỏi khác: **còn gì chưa ai nhìn?**

Khác biệt quan trọng so với Phase 1, và là lý do phần này tồn tại riêng: Phase 1 toàn **lỗi đã
xác nhận**, mỗi cái có bằng chứng đo được tại thời điểm phát hiện. Phase 2 phần lớn là **đường
dẫn chưa ai chạy** — code có tồn tại, nhánh có viết, nhưng chưa test nào đi qua và chưa lần nào
xảy ra thật. Chúng có thể hoàn toàn đúng. Không ai biết. Đó chính là vấn đề.

Trộn hai loại vào một danh sách sẽ khiến "chưa biết" đọc như "đã hỏng", hoặc tệ hơn, ngược lại.

## A. Lỗi đã xác nhận (2)

| # | Vấn đề | Bằng chứng | Mức |
|---|---|---|---|
| **P2-A1** ✅ | *(ĐÓNG 2026-08-15)* Số từ một nguồn API đã chết vẫn render như đang sống. Rail có gọi tên nguồn hỏng (M8 nửa đầu), nhưng `renderMetrics:320` là `snap?.equity ?? meta.final_equity` — **không kiểm `error`**. `state.runner?.error` chỉ được dùng ở `stripDeadSources` và trong text bằng chứng. Equity, drawdown, decision, regime tiếp tục hiện số cũ, chỉ mờ `opacity: .42` | Đọc code: `rg "state.runner\?\.error"` → chỉ dòng 484 và 637 | **High** — cùng họ với C2 "stale nhìn giống healthy", nhưng nhẹ hơn vì rail đã gọi tên nguồn |
| **P2-A2** ⬇ | *(RÚT LẠI 2026-08-15 — không phải lỗi)* Banner ghi **"Monitor backend unavailable."**. Một endpoint chết KHÔNG phải backend chết; hiện banner lúc đó là nói sai. Điều kiện all-or-nothing đúng với thông điệp nó mang, và khiếu nại gốc — fail lẻ vô hình — đã được rail đóng ở M8. Ghim bằng `test_the_fatal_banner_speaks_only_for_a_dead_backend` | Đọc code + test | ~~Medium~~ → **không phải finding** |

*P2-A1 và P2-A2 là hai nửa chưa làm của M8. Ô M8 trong bảng Phase 1 đã sửa từ ✅ thành ⚠️ MỘT PHẦN.*

## B. Đường dẫn chưa ai chạy (7)

Đo bằng cách tìm test nào thật sự **đặt** giá trị xấu, sau khi loại phần `BASE_PAYLOADS` — vì
field có mặt trong fixture **không** có nghĩa là trạng thái được kiểm.

| # | Trạng thái | Vì sao quan trọng | Mức |
|---|---|---|---|
| **P2-B1** | `breaker.level` = **HALTED / SHUTDOWN** | Trạng thái quan trọng nhất trên một dashboard giao dịch: hệ thống tự dừng vì lỗ ngày −4% hoặc 5 lệnh thua liên tiếp. `renderRail` có nhánh `stripBreakerBad`, chưa test nào đi qua. Nếu nhánh này hỏng thì nó hỏng đúng lúc mọi thứ đang tệ nhất | **High** |
| **P2-B2** | **broker-only position** — IBKR giữ một vị thế runner không biết | Phơi nhiễm mà runner không quản lý được: không stop theo kế hoạch, không nằm trong tính toán exposure. `renderMonitor` có nhánh `broker:only`, chưa test nào đi qua | **High** |
| **P2-B3** | **runner-only position** — runner nghĩ đang giữ, broker không có | Logic bảo vệ chạy trên trạng thái không tồn tại. Có `runnerOnly()`, chưa test | **High** |
| **P2-B4** | `model_age` = **URGENT** | Đây là trạng thái **THẬT của production ngay lúc này** (20 tháng, G2 HARD) — nhưng `BASE_PAYLOADS` dùng `OK`. Mọi DOM test đang chạy với một model khỏe mạnh giả định trong khi hệ thống thật thì không | **Medium** |
| **P2-B5** | `regime_unreliable = True` | HMM stale guard G1 HARD chặn mọi entry. Trang phải nói được điều đó | **Medium** |
| **P2-B6** | `halted_today > 0` và `rejected_detail` có bản ghi | Entry bị guard chặn, và cap block. Cả hai đều đã xảy ra thật (log 08-10 có `REJECTED SHORT MNQ ... gross 10.9% > cap 5.0%`) nhưng chưa test nào render chúng | **Medium** |
| **P2-B7** | `refreeze pending = True` | Re-freeze thất bại để lại cờ pending; runner re-alert mỗi lần chạy | **Low** |

## C. Bề mặt chưa có hợp đồng (1)

| # | Vấn đề | Mức |
|---|---|---|
| **P2-C1** | **8/10 endpoint không có contract test.** Chỉ `runner-state` và `schedule-status` có. Thiếu: `broker`, `runner-positions`, `open-issues`, `session-events`, `job-journal`, `execution-quality`, `reports`, `paper-evidence`. Frontend đọc các khóa này không qua lớp trung gian nào | **Medium** |

## Thứ tự đề xuất

Làm **B trước A**. Nghịch lý nhưng có lý: nhóm B rẻ (chỉ là stub + assert, không đổi code sản
phẩm) và mỗi test biến một "không biết" thành hoặc "ổn" hoặc "một finding thật". Chạy hết B rồi
mới biết Phase 2 thực sự lớn cỡ nào — có thể vài nhánh đã đúng sẵn, cũng có thể lòi thêm lỗi.

1. **P2-B1, B2, B3** — ba đường dẫn mất tiền. Cao nhất.
2. **P2-B4** — sửa `BASE_PAYLOADS` cho khớp production, rồi xem test nào vỡ.
3. **P2-A1, A2** — sau khi biết B lòi ra gì, vì bản sửa A1 có thể phải phối hợp.
4. **P2-B5, B6, C1**, rồi **B7**.

## Ghi chú về phương pháp

Lần đo đầu tiên cho Phase 2 **sai**: detector của tôi báo `regime_unreliable`, `refreeze`,
`HALTED` là "có test" vì chúng xuất hiện trong `BASE_PAYLOADS` như field mặc định (`False`,
`"OK"`). Field có mặt trong fixture không phải là trạng thái được kiểm. Cùng họ với bẫy "duyệt
danh sách rỗng rồi assert" đã dính hai lần ở Phase 1 — đủ ba lần trong một đợt để đáng ghi thành
luật: **một phép đo về độ phủ phải chứng minh được nó sẽ đỏ khi thứ nó canh biến mất.**
