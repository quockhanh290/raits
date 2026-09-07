# Vòng 2 — việc tiếp theo

Viết sau khi lỗi `<text>` bị kéo giãn đã được sửa và ghim bằng test.
Đọc cùng `DESIGN_SPEC.md` và `SECTION_ANATOMY.md`.

---

## Phần A · Còn dư từ vòng 1

### A1 · G1–G5 chưa làm

Lỗi `<text>` là luật 5 của mục 6, không nằm trong G1–G5. Năm việc gốc vẫn còn
nguyên — xem `IMPLEMENTATION_PROMPT.md` phần 4. Tóm lại:

| | Việc | File |
|---|---|---|
| G1 | pane giá thêm chip `bars · <date>`; pane series đổi thành `slots · <date>` | `realtime.js:2212`, `:2796` |
| G2 | báo khi hai ngày lệch nhau | `realtime.js` `mvSlotChart` |
| G3 | `data-xspan="own"` → bỏ sync crosshair, in nhãn "trục riêng" | `next.js:485` |
| G4 | `.mv2-verdict-side` → hàng metadata 5 mục | `realtime.js:1889` |
| G5 | pill chỉ còn một từ | `realtime.js:1897` |

G4 và G5 làm cùng lúc — G5 đẩy `mvVerdictDetail()` vào hàng metadata của G4.

### A2 · Bốn luật mục 6 đã kiểm được

`DESIGN_SPEC.md` mục 6 đã viết lại luật 1/2/4/6 với phạm vi và cách đếm cụ thể.
Hai dự đoán cần kiểm lại:

- **"7 section quá hai nền"** — luật 6 giờ loại chip khỏi phép đếm (diện tích
  < 600px², hoặc `border-radius ≥ 3px` cùng `padding` ngang ≤ 14px). Mục 1 cấp
  hẳn 6 nền cho chip theo tone. Đếm lại; con số thật có thể là 0.
- **"4 metric xếp dọc"** — luật 4 giờ định nghĩa metric compact bằng ba điều kiện
  đồng thời, và ô **ba con** xếp dọc là **đúng spec**. Regime Monitor và Today's
  Decision đều là ô ba con. Kiểm 4 cái đó có phải loại đó không.

Và một lỗi của spec đã sửa: heading cũ ghi "chữ — bốn bậc" trên bảng 5 dòng.
Giờ là **bốn bậc đọc** + **một dấu không-giá-trị** (`void` chỉ hợp lệ khi text
node đúng bằng `—`). Sàng đếm ra 6 là đang đối chiếu spec tự mâu thuẫn.

### A3 · Chưa đọc

`SECTION_ANATOMY.md` (11 section + khung ngoài) và `DESIGN_SPEC.md` mục 7–8
(breakpoint · giữ nguyên accessibility). Mục 8 quan trọng trước khi commit: nó
liệt 9 loại `aria-*`/`role`/`tabindex` repo có mà design không có.

---

## Phần B · Chỗ bản design CHƯA VẼ

Đây là khoảng trống lớn hơn cả A. Bản design vẽ **một** trạng thái cho mỗi
section — trạng thái **yên**: 0 position, 0 order, 0 entry, no signal. Mọi trạng
thái có dữ liệu đều **chưa được vẽ**.

Nghĩa là: với những trạng thái dưới đây, **không có spec nào để đối chiếu**. Đừng
suy ra từ trạng thái yên, và đừng coi việc repo trông khác là lệch.

### B1 · Market View khi levels ĐƯỢC publish — chỗ trống lớn nhất

Bản design chỉ vẽ `levels_armed === false`:

> *"None published — entry forms after the setup bar"*

Khi có candidate thật, repo render `mvSetupCard` (`realtime.js:2828`) với
`price_levels`, và pane giá vẽ đường entry/stop/target (`realtime.js:1699-1720`).
Bản design **không có** những thứ này. Cụ thể chưa vẽ:

- đường entry / stop / target trên pane nến — màu, kiểu nét, nhãn
- bảng levels trong setup card
- ba trạng thái đường giá mà `realtime.js:1699` gọi là "the three states they can be in"
- `boundary_type` khác `metric_boundary` (`price_boundary`, `two_phase`,
  `entry_after_setup_only`)

**Hệ quả:** phần lớn giá trị vận hành của Market View nằm ở trạng thái này, và nó
chưa qua thiết kế. Giữ nguyên repo. Nếu cần thiết kế thì đó là việc riêng, có
duyệt riêng.

### B2 · Các section ở trạng thái có dữ liệu

| Section | Design vẽ | Chưa vẽ |
|---|---|---|
| Open Positions | 0 position, một câu | hàng position, price track, marker stop/entry/last |
| Open Orders | bảng rỗng, một câu | hàng order thật, 7 cột có dữ liệu |
| Today's Decision | cả 5 số = 0, 3 nhóm rỗng | hàng entry/close/rejected thật |
| Now Monitor | CLEAR, detail "systems nominal" | incident thật (8 nguồn ở `realtime.js:962+`) |
| Status band | OK, xanh | mức `watch` và `bad`, và gradient đổi màu theo mức |
| Track 1 Runtime | 1 trạng thái (đã chạy) | 3 trạng thái kia: đang đọc, lỗi endpoint, chưa observe |
| Regime Monitor | label check PASS | UNKNOWN, drift, và `held.capped` |
| Paper equity | "not measured" | có số thật + `performanceNet` dương/âm |

Ở tất cả các dòng này: **repo là nguồn đúng**, spec không có ý kiến.

### B3 · Không phải trạng thái, mà là chưa từng vẽ

- **Focus / keyboard** — bản design không có focus ring nào. Repo có `tabindex`
  trên mọi node tooltip. Giữ repo, xem mục 8.
- **Tooltip** — bản design 0 tooltip. Repo dùng `has-tip` + `data-tooltip` khắp
  nơi. Giữ repo.
- **Chart ở màn hẹp** — xem mục 7, phần "Chỗ spec này KHÔNG nói gì".

---

## Phần C · Prompt

> Tiếp tục việc trên dashboard realtime trong `dash/`. Lỗi `<text>` bị pane kéo
> giãn đã sửa và ghim; giờ làm phần còn lại.
>
> **Đọc trước:** `DESIGN_SPEC.md` mục 6 (bốn luật đã viết lại, có cách đếm), mục
> 7 (breakpoint — **680px là hợp đồng với `realtime.js:11`**, không đổi), mục 8
> (những thứ phải giữ nguyên). Rồi `SECTION_ANATOMY.md` cho section nào bạn chạm
> tới. Và **phần B của file này** — nó nói rõ chỗ nào bản design chưa vẽ, tức là
> chỗ nào không có spec để đối chiếu.
>
> **Ràng buộc:** không sửa `dash/realtime/realtime.css`. Cấu trúc →
> `next.css`; hành vi → `next.js`; chỉ sửa `realtime.js` ở phần nội dung render.
> Giữ nguyên mọi `id`, `aria-*`, `role`, `tabindex`, `has-tip`, `data-tooltip`.
> Ẩn thì `display:none`, không xoá node.
>
> **Thứ tự làm:**
>
> 1. **G4 + G5 cùng lúc** — pill về một từ, `.mv2-verdict-side` thành hàng
>    metadata 5 mục. Đây là thay đổi nhìn thấy rõ nhất, làm trước để dễ soi.
>    Giá trị chính xác ở `DESIGN_SPEC.md` mục 4.3.
> 2. **G1 + G2** — chip ngày trên cả hai pane, và cảnh báo khi hai ngày lệch.
>    Mục 4.7 cho pane giá; `:2796` cho pane series.
> 3. **G3** — đọc `data-xspan`, bỏ sync crosshair khi `own`.
> 4. **Đếm lại luật 1/2/4/6** theo định nghĩa mới ở mục 6. Ghi rõ số nào là dương
>    tính giả của sàng cũ, số nào là lỗi thật.
>
> **Nghiệm thu:** chạy `dash/tools/measure_dashboards.py` trước và sau, **cùng một
> buổi** — docstring của nó nói kết quả không tái tạo được qua thời gian. Yêu cầu:
> không va chạm mới ở 1900×1000; số cỡ chữ và số họ chữ không tăng. Kiểm tay hover
> ở cả ba inner tab, và ở sleeve **không có** diagnostics (`mvVerdict` phải không
> throw — fallback ở `:1884`).
>
> **Không làm:** G6 (gộp Now Monitor). Và không thiết kế mới cho bất cứ mục nào ở
> phần B — nếu gặp một trạng thái phần B nói là chưa vẽ thì để nguyên repo và ghi
> lại, đừng tự vẽ.
>
> **Báo lại:** cái gì đã sửa, cái gì đã kiểm và bằng thước nào, cái gì chưa kiểm.
> Không ghi "đạt" cho thứ chưa đo.
