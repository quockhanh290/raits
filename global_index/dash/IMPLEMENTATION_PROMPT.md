# Realtime dashboard — đối chiếu repo ↔ bản design

Đối chiếu `dash/realtime/` + `dash/realtime-next/` với `Realtime Dashboard.dc.html`.

**Đã đọc, lần này đầy đủ:** `index.html`; trong `realtime.js`: `renderRail`
(`:841`), `renderMonitor` (`:962`), `renderOpenIssues` (`:3366`), `renderRegime`
(`:3158`), `renderTrack1` (`:3490`), `renderJobJournal` (`:4379`),
`renderEventJournal` (`:4409`), `renderClocks` (`:4447`), `render` (`:4478`),
`mvVerdict` (`:1877`), `mvPriceHead` (`:2212`), `mvBarGrid` (`:2140`),
`mvSlotChart` (`:2600-2830`), `mvSetupCard` (`:2828`); trong `realtime-next`:
`next.css` (group bands, density, metrics, rail, mv2), `next.js`
(`matchFigureLayout`, `foldRestatedThreshold`, `wireSlotHover`, `groupBands`).

Kết luận có hai chiều, và **chiều thứ hai quan trọng hơn**.

---

# Phần 1 · Repo còn thiếu so với design (5 điểm)

## G1 · Pane giá không có nhãn ngày

`mvPriceHead()` (`realtime.js:2212-2244`) emit `kicker / OHLC / change / note`,
không có chip ngày. Pane series thì có: `:2796` in `mv2-sc-day` từ
`chartDay = strategy.slot_series_session` (`:2762`).

Hai chart xếp trên nhau, chỉ pane dưới ghi ngày — trong khi nến đến từ
`s.bars` / `bars_session_date`, series đến từ `slot_series_session`. Hai field
khác nhau, người đọc mặc định cùng ngày.

**Cần:** pane giá mang `bars · <bars_session_date>`; pane series đổi thành
`slots · <slot_series_session>`. Cùng class, để hai chip trông giống nhau.

## G2 · Không có gì báo khi hai ngày lệch nhau

Không có chỗ nào so `bars_session_date` với `slot_series_session`.

**Cần:** khi khác nhau, in `div.mv2-tabnote` nói rõ pane nào ngày nào, và
crosshair chỉ khớp trong phạm vi từng pane. Không tự chuẩn hoá về một ngày.

## G3 · Trục x dùng chung là *có điều kiện*, và im lặng khi fallback

`:2805-2808` set `data-xspan="shared"|"own"`; span lấy từ pane giá (`:1576`,
`:2633`). Khi pane giá không publish span, series tự tính scale riêng — nhưng
`wireSlotHover()` (`next.js:485`) vẫn sync crosshair giữa hai pane.

Hover khi đó đọc ra hai thời điểm khác nhau, không dấu hiệu gì.

**Cần:** đọc `data-xspan`; khi `own` thì bỏ sync, mỗi pane hover độc lập, và in
nhãn "trục riêng" trên pane series.

## G4 · Metadata dưới verdict chỉ có 2 mục, design có 5

`mvVerdict()` (`:1889-1896`) — `.mv2-verdict-side` chỉ chứa `blocked`
(`X failed N of M`) + `provenance`.

Design chạy một hàng mono, vạch dọc phân cách, 5 mục:

```
N/N slots │ latest HH:MM ET │ <boundary kind> │ <blocking rule> → <regime> │ live|reviewing <date>
```

`boundary kind` có sẵn ở `:1491-1493`; `provenance` có sẵn ở `mvEvidenceProvenance()`
(`:1869`).

## G5 · Chip verdict còn nhồi detail vào trong

`:1897-1898`: `<b>${st.word}</b><span>· ${mvVerdictDetail(s)}</span>`.
Design: chip chỉ một từ; detail xuống hàng metadata ở G4.

## G6 · Now Monitor trùng cấu trúc với Open Issues — **CHƯA DUYỆT**

`index.html:139-146` (`nowMonitorList` + `nowMonitorDetail`) và `:154-160`
(`openIssueList` + `openIssueDetail`) cùng một hình dạng, cách nhau ~260px.

**Không làm cho đến khi có xác nhận.** Đọc kỹ `renderMonitor` (`:962-1100+`) thì
Now Monitor không phải bản sao của Open Issues: nó dựng incident **tại thời điểm
này** từ 8 nguồn (`regime_unreliable`, `connectivity_outage`, `broker_reconcile`,
`schedule.open_incidents`, `runner.freshness==='late'`, `orphanStops`,
`unprotected`, `invalidStops`, `stopIdDrift`), còn Open Issues dựng từ
**evidence lưu lại** có `first_seen`/`last_seen`/`occurrences`/`resolution_evidence`.
Hai câu hỏi khác nhau: "đang sai gì lúc này" vs "còn gì chưa đóng".
Trùng là trùng *hình*, không trùng *nội dung* — nên bỏ pane là mất chức năng.

---

# Phần 2 · Repo đi TRƯỚC design — không được copy DC vào

Đây là phần prompt trước của mình thiếu, và là rủi ro lớn hơn Phần 1.
Mỗi mục dưới đây là chỗ DC của mình **sai hoặc thô hơn** repo. Giữ repo.

## R1 · Source Clocks — DC ghi sai nhãn

DC in `Runner freshness / not expected yet`. Repo (`renderClocks`, `:4447-4476`)
in `Schedule freshness / <value> · whether another slot is due today, not the
runner's health`, kèm ghi chú Stage 5ZZZ-BU: field đó **không nói về runner**,
`fresh` được set khi schedule còn slot trong ngày. Repo đã sửa một mâu thuẫn
thật (runner observed 08-24 + freshness `fresh`). **DC sai. Giữ repo.**

Cũng vậy: repo in `Runner observed … · legacy route, retired` khi
`legacyRunnerStale()`. DC in ngày trần.

## R2 · Job journal — DC bỏ mất `presentation`

DC hardcode `state`/`tag`. Repo (`:4392-4399`) dùng `jobPresentation(job)` cho
`component` / `status` / `statusLabel` / `problem`, và `tone` phân biệt
`recovered` / `known_debt` / `jobTone(job.status)`. **DC thô hơn. Giữ repo.**

## R3 · Event journal — DC bỏ mất `actionable`

Repo (`:4413-4425`) chỉ render button + `event-detail` khi
`row.problem || row.impact || row.action || row.evidence`; còn lại là
`div.event-static` không bấm được. DC cho mọi event trông như bấm được.
**Giữ repo.**

## R4 · Open Issues — DC bỏ mất `active_count` vs `retired_history_count`

Repo (`:3378-3395`) tách `active_count` (backend đánh
`counts_as_active: false` cho legacy paper reconciliation) khỏi
`issues.length`, và group toàn-retired **mở ở trạng thái đóng** (`:3419+`).
DC in `2 open · 7 retired legacy` như chuỗi cố định, không có logic.
**Giữ repo.** `<details>` đóng là *cố ý*, không phải lỗi.

## R5 · Status rail — DC nén 20 điều kiện thành một câu

Repo (`:841-960`) dựng `stripConditions` từ ~14 nhánh, phân biệt
`routeModeKnown === false` ("nobody could look") với `legacy` — và
`legacyStaleByDesign` được nói bằng câu riêng thay vì raise alarm.
DC in đúng một câu literal. **Giữ repo.**

## R6 · Track 1 Runtime — DC bỏ mất trạng thái thứ tư

Repo (`:3502-3517`) có **bốn** trạng thái: chưa tới (`!t1` → "đang đọc, đây là
read chậm nhất trang"), lỗi endpoint, chạy rồi, chưa observe. DC chỉ có "chạy rồi".
Ghi chú trong code nói rõ: in "endpoint không trả lời" trong lúc đang đọc là
"cùng một lời dối theo chiều ngược lại". **Giữ repo.**

## R7 · Regime — DC bỏ mất `regimeCheckLine` và `held.capped`

Repo (`:3159-3175`) có 5 nhánh cho label check (PASS / UNKNOWN / drift / khác) và
`held.capped` → `held at least N days`. DC in `Label check passed · 1,761 days ·
no drift` cứng. **Giữ repo.**

## R8 · `foldRestatedThreshold` có guard, DC không

`next.js:280-288` chỉ ẩn tile "Shift threshold" **khi** footnote còn câu
"no fixed shift threshold" — nếu câu đó đổi, tile hiện lại, vì lúc đó nó là chỗ
duy nhất nói ra sự thật. DC xoá thẳng. **Giữ repo.**

---

# Phần 3 · Số đo (B)

## Không chạy được `measure_dashboards.py` từ đây

`dash/tools/measure_dashboards.py` chạy Playwright trên backend live
(`PAGES = ["/realtime", "/paper", …]`, `VIEWPORTS = [(1900,1000), (390,844)]`) —
cần Python + server đang chạy. Mình không có.

Và docstring của chính nó (`:26-38`) nói: kết quả **không tái tạo được** giữa
các phiên vì dữ liệu vận hành thay đổi — `/realtime` ra 226 node lần này, 294 lần
sau, cùng commit. Nên nó chỉ dùng được theo cách "chạy trước khi sửa, chạy lại
ngay sau khi sửa, **trong cùng một buổi**, rồi so hai lần chạy".

→ **Người implement phải tự chạy nó**, hai lần, cùng buổi.

## Số đo bản design, để làm mốc so

Đo trực tiếp `Realtime Dashboard.dc.html`, viewport 1714×1086:

| | |
|---|---|
| Chiều cao trang | **3638px** |
| Cột | **1520px / 380px** |
| Group band | **60px**, padding `16px 22px 13px` |
| Khoảng hở giữa nhóm | **14px** |

Chiều cao từng section (cùng viewport):

| Section | Cao | Padding |
|---|---|---|
| Now Monitor | 380 | `16px 22px` |
| Open Issues | 453 | `18px 22px` |
| Track 1 Runtime | 273 | `18px 22px` |
| Open Orders | 168 | `18px 22px 24px` |
| Paper equity (hàng 4 block) | 206 | `15px 22px` |
| Open Positions | 121 | `18px 22px` |
| Today's Decision | 256 | `18px 22px` |
| Regime Monitor | 514 | `18px 22px` |
| Track 1 Market View | 567 | `18px 22px` |
| Calm · two phases | 374 | `18px 22px` |

Đọc các số này **như tỉ lệ, không như pixel bắt buộc**: chúng phụ thuộc lượng dữ
liệu giả trong DC. Cái so được là *thứ tự*, *padding*, và *tỉ lệ giữa các section*.

## Thang chữ và họ chữ của bản design

- **Cỡ:** 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 23, 24, 30 — **14 cỡ**.
  Hơi nhiều cho một ops console; nếu repo ít hơn, repo đúng hơn.
- **Họ:** `IBM Plex Sans`, `IBM Plex Mono` — và **`Times New Roman`**.

**Times New Roman là lỗi trong bản design của mình**, không phải mục tiêu để đạt:
có element không thừa hưởng font (khả năng cao là `<text>` trong SVG hoặc một node
`<b>`/`<em>` chưa set family). Repo tuyệt đối không được copy chỗ này — và nên
kiểm chính nó có bị leak tương tự không.

---

# Phần 4 · Prompt implement

> Trong repo `dash/`, sửa dashboard realtime cho khớp bản design — **chỉ 5 điểm
> G1–G5 dưới đây**.
>
> Đọc trước, theo thứ tự:
> 1. `DESIGN_SPEC.md` — hợp đồng thị giác: token màu, thang chữ, pattern dùng
>    chung, Market View, số đo mốc, và mục 6 "điều KHÔNG được làm". **Lấy giá trị
>    từ đây, đừng suy ra từ file DC** — file DC là template runtime, style inline
>    rải khắp 1500 dòng.
> 2. `SECTION_ANATOMY.md` — giải phẫu từng section một (11 section + khung ngoài),
>    kèm lý do từng quyết định. Tra ở đây khi sửa một section cụ thể.
> 3. `IMPLEMENTATION_PROMPT.md` phần 2 — 8 chỗ repo đang **đúng hơn** bản design.
>    Nhiệm vụ này không được chạm vào chúng.
>
> Không cần mở `Realtime Dashboard.dc.html`.
>
> Ràng buộc của repo: **không sửa `dash/realtime/realtime.css`** (4 dashboard khác
> dùng chung). Cấu trúc → `dash/realtime-next/next.css`; hành vi bổ sung →
> `dash/realtime-next/next.js`. Chỉ sửa `dash/realtime/realtime.js` ở phần *nội
> dung* nó render (G1, G2, G4, G5), và giữ nguyên mọi `id` — `next.js` resolve
> bằng `getElementById`.
>
> **G1.** `mvPriceHead()` (`realtime.js:2212`): thêm chip ngay sau
> `<span class="mv2-kicker">Price</span>` →
> `<span class="mv2-sc-day">bars · ${s.bars_session_date}</span>`, dùng lại đúng
> class `.mv2-sc-day` của pane series. Ở `mvSlotChart()` (`:2796`) đổi nội dung
> chip thành `slots · ${chartDay}`. Ngày rỗng thì **không in chip** — đừng in
> `bars · --`.
>
> **G2.** `mvSlotChart()`: so `s.bars_session_date` với
> `strategy.slot_series_session`. Khác nhau → in `div.mv2-tabnote` ở đầu pane
> series, nói nến là ngày nào, series là ngày nào, và crosshair chỉ khớp trong
> từng pane. Không tự chuẩn hoá về một ngày.
>
> **G3.** `next.js` `wireSlotHover()` (`:485`): đọc `data-xspan` của
> `.mv2-sc-svg`. Khi `own` → không sync crosshair giữa hai pane (mỗi pane hover
> độc lập) và set attribute trên `.market-view-section` để `next.css` in nhãn
> "trục riêng" trên pane series. Khi `shared` → giữ nguyên hành vi hiện tại.
>
> **G4 + G5.** `mvVerdict()` (`realtime.js:1877`): pill chỉ còn
> `<i></i><b>${st.word}</b>`. Thay `.mv2-verdict-side` bằng
> `<div class="mv2-verdict-meta">` với 5 `<span>` theo thứ tự: `mvVerdictDetail(s)`
> · `latest <clock của slot cuối>` · boundary kind (map ở `:1491`) ·
> `${blocked.label} → ${regime}` · `${provenance}`. **Mục nào không có dữ liệu thì
> bỏ hẳn span, không in placeholder.** Trong `next.css`: `.mv2-verdict-meta` là
> flex wrap, mỗi span `padding: 0 11px; border-left: 1px solid #1e242c`, mono
> 11px; span đầu bỏ `border-left`. Màu: mục có số `#a8b1c0`, mục rule-fail
> `#f0b429`, mục provenance `#4b5563`. Cập nhật `#marketViewVerdict`
> (`next.css:704`) cho khớp grid mới.
>
> **Nghiệm thu.** Chạy `dash/tools/measure_dashboards.py` **trước khi sửa và ngay
> sau khi sửa, trong cùng một buổi** — docstring của nó (`:26-38`) nói kết quả
> không tái tạo được qua thời gian, nên chỉ so hai lần chạy đó với nhau. Yêu cầu:
> không có va chạm mới ở 1900×1000 và 390×844; số cỡ chữ và số họ chữ không tăng.
> Ngoài ra kiểm tay: hover ở cả ba inner tab (`Setup rules`, `Detector rules`,
> `Price context`); và ở sleeve **không có** diagnostics — `mvVerdict` phải không
> throw (xem fallback `mvStatusChip(s) || mvProgressChip(s)` ở `:1884`, đó là trạng
> thái trang mở ra mỗi sáng).
>
> **Giữ nguyên, không thương lượng** (chi tiết ở `DESIGN_SPEC.md` mục 8): mọi
> `has-tip` / `data-tooltip` / `tabindex` / `aria-*` / `role` hiện có; mọi `id`;
> `.metrics-figures` đang `hidden`; `<details id="openIssuesShell">`. Spec không
> nói gì về chúng vì bản design **không có** chúng — bản design là bản vẽ, không
> phải bản dựng. Thiếu ở đó nghĩa là chưa vẽ, không phải nên bỏ.
>
> **Breakpoint** (bảng đầy đủ ở `DESIGN_SPEC.md` mục 7): **680px là hợp đồng với
> `realtime.js:11`** — không đổi, và mọi media query màn hẹp phải đúng 680px.
> 681px và 1051px cũng không chạm. Chỉ 1600px là ngưỡng của bản design. Các grid
> mà spec không định nghĩa hành vi hẹp (`352px 1fr`, `300px 1fr`, `repeat(4,1fr)`,
> `repeat(5,1fr)`) thì giữ đúng cách `next.css` đang xử lý — đừng tự phát minh.
>
> **Không làm trong lần này:** G6 (gộp Now Monitor). Hai panel trả lời hai câu hỏi
> khác nhau — incident lúc này vs evidence chưa đóng — cần duyệt riêng.
