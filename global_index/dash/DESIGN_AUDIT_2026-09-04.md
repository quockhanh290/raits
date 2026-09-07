# Rà hệ thống thiết kế — trang chạy so với hợp đồng

**Ngày đo:** 2026-09-04 · **Trang:** `/realtime` · **Khổ:** 1900×1000 và 390×844
**Công cụ:** Playwright, đọc `getComputedStyle` của mọi element đang hiện.

Tài liệu `COVERAGE.md` đã trả lời câu *"spec có mô tả đủ component của bản design
không"*. Bản này trả lời câu ngược lại, chưa ai đo: **trang đang chạy có nằm trong
thang mà hợp đồng quy định không.**

---

## Cách đo, và một lần phải làm lại

Danh sách màu hợp lệ **suy từ tài liệu**, không gõ tay: mọi mã hex xuất hiện trong
`DESIGN_SPEC.md` (50 màu), `SECTION_ANATOMY.md` (32) và chính file design
`Realtime Dashboard.dc.html` (52) — hợp lại 57 màu riêng biệt. Định nghĩa "ngoài
thang" vì thế là: **một màu không ai viết xuống ở đâu cả.**

Lần đo đầu gõ tay danh sách từ riêng mục 1 của `DESIGN_SPEC` và ra **40 màu ngoài
thang** — con số đó SAI. Nó xếp `#2e2745` (viền badge lane) và `#2a323d` (viền badge
state) là vi phạm, trong khi `SECTION_ANATOMY` quy định đúng hai màu ấy; và nó xếp
màu trạng thái ra ngoài nhóm "nền" dù hợp đồng nói rõ chúng dùng cho **dot**. Con số
đúng là 11.

---

## Kết quả

| Trục | Đo được | Kết luận |
|---|---|---|
| **Cỡ chữ** | 13 cỡ riêng biệt, **0 ngoài thang 13 cỡ** | Đạt, cả hai khổ |
| **Màu chữ** | 20 giá trị · **3** không có trong tài liệu nào | 3 việc |
| **Màu nền** | 23 giá trị · **5** (khổ hẹp: 4) | 5 việc |
| **Màu viền** | 22 giá trị · **3** | 3 việc |
| **Bán kính** | 2·3·4·5·7·8·50 · **1 ngoài thang: 7px** | 1 việc |

Thang cỡ chữ đạt tuyệt đối là kết quả đáng chú ý: hợp đồng liệt 13 cỡ và nói "mỗi cỡ
chỉ có một việc", trang dùng đúng 13 cỡ đó, không thừa một cỡ nào.

### 11 màu không tài liệu nào nhắc tới

Tất cả đến từ **`realtime/realtime.css`** — bảng nền dùng chung cho năm dashboard, và
là bảng màu *trước* redesign. Chúng lọt qua ở những chỗ lớp phủ chưa với tới.

| Màu | Ở đâu | Khai tại |
|---|---|---|
| `#56697e` | chữ `.font-control`, `.system-facts small` | `realtime.css:60,136` |
| `#7194c2` | chữ `.equity-zone > small em` | `realtime.css:76` |
| `#7891ad` | chữ `.equity-zone > small strong` | `realtime.css:77` |
| `#4ea1ff` | chấm chế độ Normal | `realtime.css:759` (`--accent`) |
| `#58a3ff` | biến `--blue` cũ | `realtime.css:14` |
| `#090d11` | nền `--bg` cũ, header trang | `realtime.css:2,35` |
| `#0c1116` | nền `select`, `.position-card` | `realtime.css:61,337` |
| `#0f0e0b` · `#2a2620` | nền + viền `.mv2-pill.warn` | `realtime.css:1263` |
| `#191d24` | vạch giữa hai section-band | `realtime.css:159` |
| `#202b34` | biến `--line` cũ | `realtime.css:5` |

**Ba màu chữ đầu bảng là việc đáng làm nhất.** Hợp đồng dựng đúng bốn bậc xám và nói
thẳng lý do: *"Bản Ops Console cũ có 8 bậc xám gần giống nhau và đó chính là thứ lần
redesign này bỏ đi."* `#56697e`, `#7194c2`, `#7891ad` là ba bậc thứ năm–bảy đang sống
lại. Sửa: đè trong `next.css`, ánh xạ về `--t-label` hoặc `--t-null`.

`#4ea1ff` là một sắc xanh thứ hai cạnh `--blue #5b9cf0` của hợp đồng, và nó đang tô
**chấm chế độ Normal** — một chỗ màu LÀ thông điệp. Hai xanh gần nhau ở hai chỗ cùng
nói về trạng thái là chỗ dễ đọc nhầm nhất.

---

## Trục thứ hai: luật CSS không có tác dụng

Bộ kiểm sẵn có `test_every_rule_in_the_shared_sheet_actually_wins` chỉ quét
`shared/components.css`. **`next.css` chưa từng được quét** — đúng chỗ hai lỗi đã xảy
ra trong ngày.

Phép đo: chụp giá trị tính toán của mọi element khớp từng luật, rồi tắt/bật từng
stylesheet và so.

| | Số luật |
|---|---|
| Đọc được trong `next.css` | 269 |
| **Có tác dụng** | 141 |
| Không có element nào khớp trên payload hôm nay — **chưa xác minh được** | 103 |
| **Không đổi gì** | **25** |

25 luật ấy chia làm ba loại, và ba loại sửa khác nhau:

- **11 luật thua `skin-e.css`** — `skin-e` nạp SAU `next.css`. Cần nâng specificity
  hoặc bỏ hẳn: `.status-rail` (×2), `.now-schedule-facts`, `.next-when` (×3),
  `.dd-gauge`, `.module-nav` (×2), `.broker-account-line a`, và một luật
  `.now-monitor … > time`.
- **1 luật thua `realtime.css`** — `.regime-post-nostate`.
- **12 luật thừa** — khai đúng giá trị vốn đã có.

**Một đính chính với chính bản đo này.** Bản đầu xếp `.issue-evidence p` vào nhóm thua
`realtime.css`. Sai: font của nó ĐÃ là `Cascadia Mono`, đúng thứ luật khai. Bộ phân loại
gán nhầm vì nó tắt cả sheet, mà `realtime.css` là nơi khai `--mono` — tắt sheet ấy làm
giá trị đổi vì một lý do không liên quan. **6 trong 25 luật dùng `var()` nên phân loại
của chúng không tin được**; 19 luật còn lại thì tin được, vì `skin-e.css` chỉ khai đúng
một biến (`--fact-pad`) và không luật nào trong số đó dùng nó.

### Đã sửa trong lượt này

`.regime-post-nostate` là luật viết ngày 2026-09-04 cho dòng *"not in this model"* của
chế độ Crisis. `.regime-post-row > span` trong `realtime.css` có specificity (0,1,1),
cao hơn một class đơn, nên luật thua và dòng ấy nhận màu bậc **nhãn** `#798394` thay
vì bậc **không-có-giá-trị** `#4b5563` — đọc nặng ngang một nhãn thật, đúng cái nó
không được phép trông giống. Đã nâng lên `.regime-post-row > .regime-post-nostate`;
đo lại ra `rgb(75, 85, 99)` và họ chữ sans như thiết kế.

---

## Giới hạn của phép đo — đọc trước khi dùng số

- **103 luật chưa xác minh được** không phải là "đạt". Selector của chúng không khớp
  element nào trên payload hôm nay. Một payload khác sẽ trả lời khác.
- Phép tắt/bật cả sheet **không cô lập được từng luật**. Một luật của `next.css` có
  thể trông "thừa" vì một luật KHÁC cũng của `next.css` đã tạo ra đúng giá trị đó.
  Con số 12 "thừa" vì thế là **trần trên**, không phải con số chắc chắn.
- Chỉ đo thứ **đang hiện**. Tab Detector rules và các `<details>` đóng không nằm
  trong lượt đo này.
- Bán kính `50px` bị loại khỏi thống kê vì đó là hình tròn (`border-radius:50%`),
  không phải một bậc thang.

## Đã sửa — kết quả đo lại

| Trục | Trước | Sau |
|---|---|---|
| Màu ngoài thang @1900px | 11 | **0** |
| Màu ngoài thang @390px | 10 | **0** |
| Bán kính ngoài thang | 7px | **không còn** |
| Luật `next.css` vô tác dụng | 25 | **13** |
| Luật bị `skin-e` che | 12 | **0** |

Cỡ chữ vốn đã 13/13, không phải sửa.

### Cách sửa từng nhóm

- **`--accent` chưa từng được khai ở đâu.** Sáu chỗ viết `var(--accent, #4ea1ff)` trong
  `realtime.css` đều rơi về giá trị dự phòng, trong đó có chấm chế độ Normal — một chỗ
  màu LÀ thông điệp. Khai một lần ở `:root` trỏ về `--blue`, chữa cả sáu. Cùng hình dạng
  với lỗi `--mv-dim`/`--mv-fg` đã sửa trước đó trong ngày.
- **Năm bậc xám thừa** (`#56697e` ở ba chỗ, `#7194c2`, `#7891ad`) ánh xạ về bốn bậc theo
  VAI: nhãn/caption về `label`, giá trị phụ trong dòng meta về `secondary`.
- **Vạch và nền cấp trang** (`#191d24`, `#202b34`, `#090d11`, `#0c1116`) về `--line-page`,
  `--page`, `--deep`.
- **Chip cảnh báo Market View** tự chế cặp nền/viền riêng → dùng tone `warn` của hợp đồng.
- **Bán kính 7px** vừa ngoài thang vừa sai hình học: hai khối đều đệm 3px và vành trong
  5px, nên vành ngoài đúng là 8px. Bản sửa đầu đặt 5px — đúng thang nhưng vành ngoài bằng
  vành trong, góc trong phình ra. Đã sửa lại thành 8px.
- **11 luật bị `skin-e` che: xoá.** Chúng chưa từng có tác dụng, nên diện mạo hiện tại là
  diện mạo đã được duyệt suốt các lượt rà; bật chúng lên bây giờ là mười một thay đổi
  hình thức không ai yêu cầu. Riêng `.module-nav a { min-height: 44px }` được kiểm trước
  khi xoá vì nó mang ý định TIẾP CẬN, không phải thẩm mỹ — đo ra 44px ở khổ 390px và 28px
  ở 1900px, tức skin-e đã lo đúng theo khổ. Ý định vẫn thoả, luật thì thừa.
- **`.dd-gauge { position: relative }` GIỮ** dù đo ra "không đổi gì": `::after` vẽ vạch
  66% dựa vào nó. Một khai báo đang chống lưng cho thứ khác thì không phải rác.
- **12 luật "thừa" KHÔNG xoá.** Chính bản đo này đã ghi con số ấy là *trần trên* — phép
  tắt/bật cả sheet không tách được "thừa thật" khỏi "bị một luật khác cùng file che".
  Xoá theo bằng chứng không đủ là đúng thứ mục giới hạn ở trên cảnh báo.

### Phép kiểm mới, và thứ nó bắt được ngay

`test_no_rule_in_next_css_is_masked_by_the_skin_loaded_after_it` chụp giá trị tính toán
ba lần — cả hai sheet bật, tắt `next.css`, tắt `skin-e.css` — và bắt lỗi khi tắt
`next.css` không đổi gì mà tắt `skin-e` thì đổi. Bộ kiểm anh em đã làm việc này cho
`shared/components.css`; `next.css` trước nay chưa ai quét.

Chạy lần đầu, nó tìm ra một luật thứ **12** mà lượt rà tay bỏ sót:
`.status-rail:has(.system-conclusion.watch)` cùng cặp `.bad` — `skin-e:81-82` khai đúng
hai selector ấy bằng gradient. Lượt rà tay không thấy vì hai luật chỉ có element khớp khi
thanh trạng thái ở `watch`/`bad`, mà lúc đo trang đang bình thường. Đó chính là giới hạn
"103 luật chưa xác minh được" ở trên, hiện ra thành một ca thật — và là lý do phép kiểm
đáng giá hơn một lượt rà.

---

## Vòng hai — đệm chữ so với viền thẻ, và ba việc phát sinh

### Mốc chữ của section

Đo thẳng trên `Realtime Dashboard.dc.html` trước khi sửa bất cứ gì. Kết quả cứu một bản
sửa sai: **thiết kế cũng đặt Now Monitor ở 37px và Regime Monitor ở 39px.** Chênh 2px ấy
có chủ đích — `.mv2-head` dùng gap 14px, `.section-heading` dùng 12px. Gộp về một mốc là
phá đúng chỗ đang khớp.

**Cột phải thì sai thật.** Thiết kế cho nó đúng MỘT mép nội dung (x=1538): thẻ job, thanh
tab, hàng Source Clocks đều bắt đầu ở đó, và hai tiêu đề nằm cùng một x. Bản chạy có hai
mép — 23px cho nhật ký, 49px cho Source Clocks — nên hai tiêu đề lệch **26px**.
`.section-band` mặc định `padding: 24px 26px`; `.journal-section` khai `padding: 0` để
nhường đệm cho chính cột, `.source-section` không được khai. Đã cho nó theo hàng xóm:
hai tiêu đề về cùng 38px, hàng dữ liệu về đúng mép thẻ 23px.

### Token chưa khai — lần thứ ba

Đo lại sau khi sửa thì hai màu ngoài thang hiện ra. Quét toàn bộ `realtime.css`: 16 token
dùng kèm giá trị dự phòng, **hai chưa tồn tại** — `--ok` (rơi về `#4a9d6e`, sắc xanh lá
thứ tư) và `--mv-hair` (rơi về `#23262d`, bậc viền thứ sáu). Cùng hình dạng với
`--mv-dim`/`--mv-fg` và `--accent`: ba lần trong một ngày.

Chip mang `--ok` chỉ hiện khi phiên CÓ ghi chẩn đoán runtime, nên ba lượt đo trước không
gặp. Đã ghim bằng phép kiểm **không phụ thuộc trạng thái trang**: đọc token từ file, hỏi
trình duyệt token ấy có giá trị hay không.

### Luật 3 — không phải vi phạm, mà là điểm mù của luật

Bộ dò báo `#modelInputsZone` lồng trong `.rg2-card`. Đo ra: `margin: 0`, bán kính
`8px 8px 0 0` (chỉ hai góc trên), nền `inset #0b0d11`, viền dưới là vạch hairline. Đó là
**header của thẻ** — đúng thứ bảng token quy định — không phải thẻ lồng thẻ.

Spec đã tự nhận điểm mù này cho luật 1/4/6 và viết lại chúng "có phạm vi, có cách đếm, có
ngoại lệ ghi thẳng"; luật 3 chưa được viết lại. Tiêu chí phân biệt, đo được: **một thẻ
lồng thì trôi bên trong thẻ cha (có lề) và bo cả bốn góc; một header thì lề bằng 0 và chỉ
bo hai góc nó chia chung với cha.** Đã ghim theo tiêu chí ấy.

### Ngoài phạm vi lượt này

`/reports` có **bảy** mức đệm cho cùng lớp `report-box` (14·17·18·20·22·30·36px @1900,
sáu giá trị khác @390); bốn thẻ khai `padding: 0` và mượn đệm từ nội dung bên trong.
`/analytics` có hai hệ cạnh nhau (13px 14px cho ô chỉ số, 15px cho panel). `/paper` là
trang duy nhất không lệch một pixel — tám `blocker-card` đều `16px 20px`.
Ba trang này dùng sheet riêng, không phải `next.css`.


---

## Vòng ba — luật 5 đóng lại

Trục chữ đã ra khỏi SVG. `svg[preserveAspectRatio="none"] text` giờ trả về **0**; 24 nhãn
(17 ở biểu đồ nến, 7 ở pane chuỗi) là span HTML phủ lên SVG, định vị bằng phần trăm của
viewBox. SVG kéo giãn lấp đầy khung nên phép quy đổi ấy là **ánh xạ chính xác**, không
phải xấp xỉ; chữ HTML thì nằm ngoài hệ toạ độ bị kéo nên không có gì để méo.

Bản vá cũ — phản-co từng nhãn theo tỉ lệ đo được — đã bỏ khỏi `next.js`. Nó chữa được
triệu chứng nhưng phải chạy lại mỗi lần khung đổi kích thước, và vẫn để nguyên cấu trúc
mà luật cấm. Phần chỉnh `rx` của ellipse thì giữ: chấm vẫn là hình trong SVG, vẫn bị kéo.

**Một bẫy trong lúc làm.** Lớp phủ của pane chuỗi ban đầu lấy mốc từ cả khối
`.mv2-slotchart` — trong đó còn head và ghi chú phía trên — nên bảy nhãn rơi ra ngoài
vùng vẽ và biến mất khỏi màn hình. Biểu đồ nến không dính vì SVG ở đó lấp đầy `.mv2-plot`.
Đã bọc SVG và lớp phủ của nó vào một khung riêng.

**Phép kiểm cũ tự báo nó hết việc.** `test_a_chart_label_is_not_stretched_by_the_pane...`
có chốt chặn "phải có ≥5 nhãn SVG để đo"; hết `<text>` thì chốt ấy đỏ — đúng thiết kế của
nó. Đã thay bằng phép kiểm theo đúng tiêu chí luật 5 viết ra, và ghim **cả hai vế**:
không còn `<text>`, VÀ nhãn HTML vẫn có mặt — thiếu vế sau thì xoá sạch nhãn đi cũng qua.

### Màu ngoài thang, lần thứ tư từ một trạng thái mới

`#71849a` trên `.day-shift` — dấu "+1d/−1d" cạnh đồng hồ, chỉ hiện khi một múi giờ đã sang
ngày khác. Bốn lượt đo trước không gặp. Cùng lớp với `.status-rail:has(.watch)` và chip
`--ok`: **một lượt rà chỉ thấy trạng thái nó tình cờ gặp.** Đây là lý do mục "102 luật
chưa xác minh được" ở trên không phải mối lo lý thuyết.


---

## Vòng bốn (2026-09-05) — quét đa trạng thái và cô lập từng luật

Hai giới hạn ghi ở mục "Giới hạn của phép đo" đã được gỡ bằng hai công cụ.

### Cô lập từng luật

Tắt/bật cả sheet không tách được "thừa thật" khỏi "bị một luật khác CÙNG FILE che" — cả
hai cho cùng kết quả. Công cụ mới xoá **đúng một luật** khỏi CSSOM (`deleteRule`), đo lại,
rồi cắm trở lại đúng chỗ (`insertRule` tại cùng chỉ số, đối chiếu `cssText` để chắc). Có
chốt: cắm lại sai chỗ thì dừng, vì mọi phép đo sau đó sẽ sai.

### Quét 15 trạng thái

Trạng thái được lái có chủ đích, không chờ gặp may: ba tab con · mở mọi `<details>` · mở
một job · chọn một issue · ép thanh trạng thái vào `watch` và `bad` · ba khổ màn hình ·
và ba trạng thái **ghim payload** — nhật ký 112 job, market view một phiên Calm, và equity
có con số.

| | trước | sau |
|---|---|---|
| luật CÓ tác dụng | 158 | **200** |
| chưa xác minh được | 117 | **43** |
| "thừa" (nay đã cô lập từng luật) | 13 | **26** |
| phần tử giả `::` — phương pháp không đo được | lẫn vào "chưa khớp" | **10, tách riêng** |

### Bốn luật chết, xoá

Trong 43 luật không bao giờ khớp, kiểm tĩnh xem có gì trong repo tạo ra lớp đó không:

- `.mv2-calm-table`, `.mv2-calm-gatetable`, `.mv2-calm-ivs:has(> .mv2-calm-table)` — viết
  cho bản Calm dùng MỘT bảng chung, mà bản ấy đã được thay bằng panel-theo-mã lấy từ file
  design **trong cùng ngày**. Luật sống sót qua một lần đổi hình dạng.
- `.mv2-shell .mv2-lane-config` — lớp `mv2-lane-config` xuất hiện **0 lần** trong mọi file.
- `.rail-clock > span` — luật của chính tôi, thêm trong vòng rà màu; skin-e:93 đã đặt sẵn
  đúng `var(--t-label)` cho cùng selector. `#56697e` thật ra chỉ ở `.day-shift` và ba chỗ
  khác, không ở đây.

### Một dương tính giả, và cách bắt được

`#metrics .equity-line > b` (bậc 30px của equity) bị 14 trạng thái đầu báo là "thừa" — vì
cả 14 đều có equity ở trạng thái "not measured", nơi luật hạ bậc thắng nó. Thêm một trạng
thái có **con số thật** thì nó lập tức "có tác dụng". Danh sách rút từ 27 xuống 26 mà không
phải sửa công cụ.

**Bài học ghi lại:** "không đổi gì qua N trạng thái" KHÔNG bằng "xoá được". Mỗi luật trong
26 cần một trạng thái mà nó CÓ THỂ quan trọng trước khi bị xoá. Ba luật xoá ở trên qua được
mức đó bằng một tiêu chí khác hẳn — không có gì trong repo tạo ra lớp của chúng.


---

## Vòng năm — đóng nốt phần đóng được

Câu hỏi "không đóng hoàn toàn được à" là đúng: ba trong bốn thứ tôi gọi là "giới hạn
phương pháp" thật ra là **việc chưa làm**.

### Phần tử giả: đo được, chỉ là phải hỏi khác

10 luật `::before` / `::after` bị xếp "không đo được" vì `querySelectorAll` không khớp
chúng. Bỏ phần `::x` khỏi selector để tìm element chủ, rồi đọc
`getComputedStyle(el, '::x')` — đo được cả 10. Con số "không đo được" từ 10 xuống **0**.

### Ba trạng thái tương tác

`:focus-visible` chỉ bật khi focus đến TỪ BÀN PHÍM, nên phải `Tab` thật chứ không gọi
`el.focus()`. Thêm ba trạng thái tab + hover, trên tab mặc định, Setup rules và
Price context.

### Một trạng thái tự làm giảm độ phủ

Trạng thái "equity có con số" ban đầu ghim đè CẢ payload runtime, làm mất nguyên section
Track 1 Runtime: nó khớp 103 luật thay vì 177. Lấy payload thật rồi chỉ đè một trường thì
về 176. **Một trạng thái dựng sai làm hẹp phép đo trong khi trông như đang mở rộng nó.**

### Ba nhóm tách khỏi "chưa xác minh", vì chúng là KẾT LUẬN

- **Chỉ khai biến CSS (7)** — `:root { --x: … }`. Tác dụng của chúng là gián tiếp, qua mọi
  chỗ `var()` đọc; đọc thuộc tính tính toán của chính `<html>` không thấy gì. Đã xác minh
  bằng phép đo khác: bộ rà token chứng minh `--accent`, `--ok`, `--mv-hair` đều sống.
- **Bị sheet khác ẩn hẳn (16)** — element CÓ trong DOM nhưng không có hộp, vì
  `skin-e.css` đặt `display: none` (ví dụ cả họ `.window-bar`). Luật sẽ không bao giờ áp
  chừng nào element còn bị ẩn. Đó là một kết luận, không phải một khoảng trống.
- **Chưa vào được trạng thái (21)** — phần còn lại thật sự.

### Kết quả

| | đầu vòng ba | cuối vòng năm |
|---|---|---|
| CÓ tác dụng | 158 | **210** |
| "thừa" (cô lập từng luật) | 13 | 24 |
| chỉ khai biến — xác minh bằng cách khác | lẫn vào "chưa xác minh" | 7 |
| bị ẩn có chủ đích — kết luận | lẫn vào "chưa xác minh" | 16 |
| **chưa xác minh được** | **117** | **21** |
| phần tử giả không đo được | 10 | **0** |

Kiểm tĩnh 42 luật chưa khớp: **0 luật chết** còn lại — cả 42 đều có nơi tạo ra.

### Một phát hiện tiềm ẩn

`.system-facts small` (luật tôi thêm ở vòng rà màu) chưa gặp trạng thái nào, nhưng
`.system-facts` CÓ được dựng ở `realtime.js:1009`. Dòng CSS ngay cạnh nó,
`realtime.css:134`, mang `#687c92` — **một bậc xám thứ năm nữa**, chưa từng hiện ra nên
lượt rà màu chưa thấy. Nó sẽ thành vi phạm ngay khi khối ấy render lần đầu.
