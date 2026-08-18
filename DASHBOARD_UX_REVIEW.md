# Rà soát THIẾT KẾ bảng giám sát RAITS Futures

Ngày đo: 2026-08-16 · Backend 127.0.0.1:5002 · Chrome, đo trên trang đã render
Phạm vi: `/realtime`, `/paper`, `/analytics`, `/reports`, `/`
Cách đo: mở trang thật, đọc hình chữ nhật đã bố trí của từng phần tử, đổi bề rộng
cửa sổ, lọc màu xám, mô phỏng cảm ứng ở 390px.

**Đây là rà soát THIẾT KẾ.** Tính đúng đắn của số liệu đã được rà ở hai đợt trước và
không lặp lại ở đây.

Mọi mục đều gắn một trong hai nhãn:

- **CHỨC NĂNG** — người vận hành đọc sai hoặc không đọc được thứ họ cần.
- **THẨM MỸ** — trang vẫn dùng được, nhưng nhìn thiếu chỉn chu.

Thứ tự trong mỗi nhóm là thứ tự mức độ.

---

## Câu hỏi trung tâm, trả lời thẳng

> *"Có gì đang hỏng không, và tôi phải làm gì bây giờ?"* — trả lời được trong 5 giây không?

**Chưa.** Đo trên vùng màn hình đầu tiên của `/realtime`, xếp theo cỡ chữ:

| Hạng | Nội dung | Cỡ chữ | Có trả lời câu hỏi đó không? |
|---|---|---|---|
| 1 | `$50,229` (vốn giấy) | **37px** | Không |
| 2 | `0.09%` (mức dùng rủi ro) | **29px** | Không — đang là 0,6% của hạn mức |
| 3 | `Now Monitor` (nhãn mục) | 25px | Không |
| 4 | `1` · `1` · `1 co…` | 21px | Một phần |
| … | `20 mo stale`, `45 warn` | 16px | **Có** |
| … | `systems nominal … 1 issue open` | **13px** | **Có** |

Hai con số **to nhất** trên màn hình đều nói *"mọi thứ ổn"*. Ba dấu hiệu bất thường
thật sự — mô hình cũ 20 tháng, 45 cảnh báo, 1 sự cố đang mở — nằm ở cỡ chữ **13–16px**,
tức nhỏ hơn phần trang trí. Người vận hành mở trang lúc 2 giờ sáng phải **quét ngược
từ dưới lên** để tìm câu trả lời.

---

# A. VẤN ĐỀ CHỨC NĂNG

## A1. Thanh điều hướng bị đè chữ — mất hẳn hai mục *(chỉ trang `/realtime`)*

**Vấn đề.** Hàng trên cùng chia làm ba khối: tên hệ thống · điều hướng · trạng thái
sống. Khối trạng thái sống không được phép xuống dòng, lại căn phải, nên khi nó rộng
hơn chỗ được cấp, phần thừa **tràn ngược sang trái và in đè lên thanh điều hướng**.

Đo được, ở bề rộng cửa sổ 1366px:

| Mục điều hướng | Bị che |
|---|---|
| Realtime | 0% |
| Historical | 0% |
| Paper | **84%** |
| Reports | **100%** |

Khối trạng thái sống cần **721px** nhưng ô của nó chỉ được cấp **457px** (ở 1440px).
Trang chỉ sạch khi cửa sổ rộng **≥ 1920px**. Ở 1920px nó thoát đúng **1 pixel**.

Nghĩa là: **ở mọi màn hình laptop thông thường, hàng đầu trang đang hỏng.** Ở 1440px
chữ "REPORTS" và "Aug 14, 2026" chồng lên nhau thành `REPORT14, 2026`.

**Tác động lúc vội.** Người vận hành nghi có chuyện, muốn nhảy sang trang khác để đối
chiếu — thì đúng hai lối đi đó bị chữ khác phủ lên. Chữ chồng chữ còn khiến trang trông
như bị lỗi tải, làm người ta nghi ngờ cả những phần đang hiển thị đúng.

**Vì sao phép kiểm cũ không bắt được.** Tràn hướng **sang trái**, và khung trang bị
đặt `overflow-x: hidden`. Đo bằng `scrollWidth > clientWidth` ra `1425 == 1425` — **xanh**.
Đây đúng là cạm bẫy đã ghi trong yêu cầu.

**Bản sửa.** Cho khối trạng thái được xuống dòng, và để ô cuối co giãn theo nội dung
thay vì bị chốt sàn ở 300px. Luật xuống dòng **đã có sẵn** trong tệp, nhưng chỉ áp
dụng từ **680px** trở xuống — chỉ cần nâng nó lên mọi bề rộng.

```css
/* realtime.css:35 — ô thứ ba đang bị chốt sàn 300px nên không nở theo nội dung */
.app-header { grid-template-columns: minmax(240px, auto) auto minmax(300px, auto); }

/* realtime.css:45 — bỏ nowrap, cho xuống dòng ở MỌI bề rộng (hiện chỉ có ở ≤680px) */
.header-live-context {
  flex-wrap: wrap; row-gap: 6px; justify-content: flex-end; white-space: normal;
}
```

**Cách kiểm sau khi sửa.** Không dùng `scrollWidth`. Lấy mép phải của thanh điều hướng
so với mép trái của khối trạng thái; hai số này không được chồng nhau ở 1280 / 1366 /
1440 / 1600px.

---

## A2. Trạng thái mã hoá **chỉ bằng màu** — xanh và vàng là cùng một chấm

**Vấn đề.** Có 6 chấm trạng thái trên `/realtime`. Cả 6 đều là hình tròn 7px, **không
nhãn, không hình dạng riêng, không thuộc tính mô tả cho trình đọc màn hình**. Khác
biệt duy nhất giữa "bình thường", "cảnh báo" và "hỏng" là màu.

Đổi ba màu trạng thái sang thang xám:

| Cặp | Lệch mức xám (trên 255) | Tỉ lệ tương phản |
|---|---|---|
| xanh ↔ **vàng** | **6** | **1.06** |
| xanh ↔ đỏ | 26 | 1.38 |
| đỏ ↔ vàng | 32 | 1.47 |

**Xanh và vàng lệch nhau 6 mức xám trên 255.** Đã chụp lại màn hình có lọc xám để đối
chiếu: ba chấm trông giống hệt nhau.

**Tác động lúc vội.** Đây là dạng hỏng im lặng nguy hiểm nhất trong bảng này: hệ thống
chuyển từ "bình thường" sang "cảnh báo" mà **chấm gần như không đổi**. Người bị mù màu
đỏ–lục, người dùng màn hình kém, hoặc ảnh chụp màn hình gửi qua chat bị nén — đều đọc
ra "vẫn xanh". Không có báo động nào kêu; chỉ có một chấm lặng lẽ đổi sắc.

**Bản sửa.** Mã hoá trạng thái bằng **hình dạng cộng chữ**, giữ màu làm lớp thứ ba
(bổ trợ, không phải nguồn thông tin duy nhất):

| Trạng thái | Hình | Chữ | Màu |
|---|---|---|---|
| bình thường | ● tròn | `OK` | xanh |
| cảnh báo | ▲ tam giác | `WARN` | vàng |
| hỏng | ■ vuông | `FAIL` | đỏ |

```css
.status-dot[data-state]        { width: 8px; height: 8px; }
.status-dot[data-state="ok"]   { border-radius: 50%; background: var(--green); }
.status-dot[data-state="warn"] { border-radius: 0; background: var(--amber);
                                 clip-path: polygon(50% 0, 100% 100%, 0 100%); }
.status-dot[data-state="fail"] { border-radius: 0; background: var(--red); }
.status-dot[data-state]::after { margin-left: 6px; font: 700 10px/1 var(--mono); }
.status-dot[data-state="ok"]::after   { content: "OK"; }
.status-dot[data-state="warn"]::after { content: "WARN"; }
.status-dot[data-state="fail"]::after { content: "FAIL"; }
```

Kèm `aria-label` bằng đúng chữ đó để trình đọc màn hình đọc được.

**Cách kiểm.** Chụp màn hình, lọc xám, che phần chữ dài — vẫn phải phân biệt được ba
trạng thái. Nếu không phân biệt được thì chưa sửa xong.

---

## A3. Thứ quan trọng nhất bị chôn dưới thứ to hơn

**Vấn đề.** Xem bảng ở đầu tài liệu. Kết luận sức khoẻ hệ thống —
`systems nominal: feeds live, positions protected · 1 issue open` — nằm ở **13px**,
trên một dải mảnh, cùng một sức nặng thị giác cho cả phần "ổn" lẫn phần "1 sự cố".

Cụm `1 issue open` được viết cùng cỡ, cùng màu, cùng dòng với cụm `systems nominal`.
Câu đó tự mâu thuẫn khi đọc lướt: nửa đầu nói ổn, nửa sau nói có sự cố, và không có
gì báo cho mắt biết nên tin nửa nào.

**Tác động lúc vội.** Người vận hành đọc `systems nominal`, thấy chữ xanh, đóng trang.
Cụm `1 issue open` ở cuối câu không bao giờ được đọc tới.

**Bản sửa.** Đảo ngôi thứ trên vùng màn hình đầu:

1. Đưa **kết luận sức khoẻ + việc phải làm** lên dòng đầu tiên, cỡ chữ lớn nhất trang
   (hiện đang là `$50,229`). Vốn giấy tụt xuống hàng chỉ số.
2. Khi có sự cố mở, **tách `1 issue open` ra khỏi câu "nominal"** thành một khối riêng
   có nền, kèm hình dạng cảnh báo và nút đi thẳng tới sự cố đó.
3. Khi không có gì mở, dòng đó thu lại thành một dòng xanh ngắn.

Nguyên tắc: **cỡ chữ phải tỉ lệ với mức độ cần hành động, không tỉ lệ với độ đẹp của
con số.**

---

## A4. Giá trị an toàn bị cắt cụt thành `1 co…`

**Vấn đề.** Ô "Protection" trong khối phơi nhiễm hiển thị `1 co…`. Đo được: chỗ hiển
thị rộng 70px, nội dung thật rộng 111px — **mất 41px**, tức mất hẳn chữ `covered`.

Ba chỗ khác cũng đang bị cắt: tên công việc kế tiếp (`STOP_REPAIR_SUN_1830`, mất 17px),
tiêu đề sự cố (mất 23px), và dòng nguồn vị thế (mất 27px).

**Tác động lúc vội.** `1 co…` có thể đọc thành *"1 covered"* (được bảo vệ) hoặc
*"1 concern"* / *"1 conflict"* (có vấn đề). Đây là ô cho biết vị thế **có được lệnh
dừng bảo vệ hay không** — đúng thứ người ta mở trang lúc 2 giờ sáng để xem. Bắt người
đọc đoán một từ bị cắt, ở đúng ô đó, là chỗ tệ nhất để tiết kiệm 41 pixel.

**Bản sửa.** Không bao giờ cắt cụt một giá trị trạng thái. Cho ô này xuống dòng, hoặc
rút gọn nhãn cột thay vì rút gọn giá trị:

```css
.exposure-zone .zone-grid > * { min-width: 0; }
.exposure-zone .zone-value { white-space: normal; overflow: visible; text-overflow: clip; }
```

Nếu thật sự hết chỗ, đổi giá trị thành dạng ngắn mà **vẫn trọn nghĩa**: `1/1 ✓` thay
vì `1 covered` bị cắt.

---

## A5. Tương phản chữ dưới chuẩn ở 111 chỗ — gần như chỉ do **một** biến màu

**Vấn đề.** Đo tỉ lệ tương phản của toàn bộ nút chữ trên `/realtime`, có ghép đúng
nền trong suốt nhiều lớp: **111 trên 292 nút chữ dưới ngưỡng WCAG AA**.

Nhưng gom lại thì chỉ có 18 tổ hợp, và phần lớn quy về **một biến màu duy nhất**:

| Biến | Giá trị | Nền | Tỉ lệ | Cần | Số chỗ |
|---|---|---|---|---|---|
| `--dim` | `#5b6975` | nhật ký công việc | **3.25** | 4.5 | 38 |
| `--dim` | `#5b6975` | dấu `+` mở rộng, 18px | **3.25** | 4.5 | 19 |
| `--dim` | `#5b6975` | các nhãn khác | 3.14–3.48 | 4.5 | ~40 |

Toàn bộ mốc thời gian và thời lượng trong Nhật ký công việc (`08-14, 22:20 ET`, `12s`)
đều nằm ở mức 3.25 — dưới chuẩn.

**Tác động lúc vội.** Khung đêm ET rơi vào giờ làm việc ICT, khung ngày ET rơi vào đêm
khuya. Trang này thường được mở lúc mệt, và chữ mờ là thứ mắt mệt bỏ qua đầu tiên.
Mốc thời gian trong nhật ký chính là thứ dùng để trả lời *"chuyện này xảy ra lúc nào,
trước hay sau lần chạy vừa rồi"*.

**Bản sửa.** Một dòng. Nâng `--dim` lên vừa đủ, giữ nguyên sắc:

```css
:root { --dim: #728392; }   /* thay cho #5b6975 */
```

Đo lại sau khi đổi: **4.55** trên nền sáng nhất (`#111920`), **5.0** trên nền tối nhất
(`#090d11`) — đạt AA ở mọi nền đang dùng. Biến `--muted` hiện đã đạt 6.0, không cần đụng.

---

## A6. Ở 390px, dòng đối chiếu môi giới bị cắt và **không cuộn tới được**

**Vấn đề.** Ở bề rộng 390px, dòng `Broker acct $996,440 / -$4,040 since Jul 8, 2026`
kèm liên kết `Paper reconcile` tràn **41px** ra ngoài mép phải. Khung trang đặt
`overflow-x: hidden` nên phần thừa bị **cắt bỏ**, không cuộn tới được.

Phép kiểm ngây thơ vẫn xanh: `documentElement.scrollWidth == clientWidth == 390`.
Nhưng `body.scrollWidth = 602`. Chênh lệch đó chính là phần bị cắt.

**Tác động lúc vội.** `Paper reconcile` là lối đi tới trang đối chiếu sổ với môi giới —
việc cần làm khi nghi số liệu lệch. Trên điện thoại, lối đi đó **không tồn tại**: không
thấy, không bấm được, không cuộn tới được.

**Bản sửa.** Cho khối này xuống dòng ở màn hình hẹp thay vì để bị cắt:

```css
@media (max-width: 680px) {   /* dùng đúng 680px — xem cảnh báo ở mục F2 */
  .broker-account-line { white-space: normal; overflow-wrap: anywhere; }
  .broker-account-line a { display: inline-block; margin-top: 4px; }
}
```

**Ghi chú về cách kiểm.** `overflow-x: hidden` ở khung trang làm mọi phép kiểm dựa trên
`scrollWidth` của trang trở nên vô dụng — nó biến "bị cắt" thành "vừa khít". Phép kiểm
đúng là: với mỗi phần tử vượt mép, đi ngược lên tìm khối cuộn ngang gần nhất; **có** khối
cuộn thật → nội dung *tới được*; **không có** → nội dung *bị mất*. Áp phép kiểm này cho
cả năm trang thì ra đúng **một** chỗ mất nội dung, là chỗ vừa nêu.

---

## A7. Vùng bấm quá nhỏ để dùng bằng ngón tay

**Vấn đề.** Đo ở 390px có mô phỏng cảm ứng, chuẩn tối thiểu 44×44px:

| Phần tử | Cao thật | Có ở trang |
|---|---|---|
| 4 mục điều hướng (`Realtime` … `Reports`) | **12px** | tất cả |
| Nút `Open detail` | **20px** | `/paper` |
| Ô chọn phông | 25px | `/realtime` |

Thanh điều hướng cao 42px nhưng vùng bấm thật của mỗi mục chỉ **12px** — phần đệm
trên dưới bị bỏ, chữ chỉ được căn giữa trong thanh.

**Tác động lúc vội.** 12px là khoảng một phần ba đầu ngón tay. Bấm trượt sang mục bên
cạnh sẽ chuyển sang trang khác — lúc đang xử lý sự cố, mỗi lần tải nhầm trang là vài
giây mất trắng và một lần mất mạch suy nghĩ.

**Bản sửa.** Cho mục điều hướng chiếm trọn chiều cao thanh:

```css
@media (max-width: 680px) {   /* dùng đúng 680px — xem cảnh báo ở mục F2 */
  .module-nav a { display: flex; align-items: center; min-height: 44px; padding: 0 12px; }
  .module-nav { height: auto; }
}
```

Nút `Open detail` nâng `min-height: 44px` tương tự.

---

## A8. Mất vòng viền tiêu điểm ở 21 chỗ có chú giải

**Vấn đề.** Có 21 phần tử mang chú giải (hiện khi rê chuột). Chúng bấm được bằng bàn
phím, nhưng vòng viền tiêu điểm bị tắt tường minh:

```css
.has-tip { position: relative; cursor: help; outline: none; }   /* realtime.css:458, paper.css:126 */
```

**Tác động lúc vội.** Người dùng bàn phím mất dấu con trỏ tiêu điểm khi đi qua vùng
này. Có giảm nhẹ: chú giải vẫn hiện khi nhận tiêu điểm bàn phím, nên vẫn có phản hồi —
nhưng phản hồi đó nằm ở **bong bóng nổi**, không phải ở chính phần tử, nên khó biết
đang đứng ở đâu trong hàng.

**Bản sửa.** Bỏ `outline: none`, thay bằng vòng viền chỉ hiện với bàn phím:

```css
.has-tip { position: relative; cursor: help; }
.has-tip:focus-visible { outline: 1px solid var(--blue); outline-offset: 2px; }
```

---

# B. ĐỀ XUẤT THẨM MỸ

Những mục này **không** cản người vận hành. Đừng làm trước phần A.

## B1. Thang cỡ chữ có 16 bậc

Đếm được 16 cỡ chữ khác nhau đang dùng đồng thời trên `/realtime`: 9.17 · 10 · 11 · 12 ·
13 · 14 · 15 · 16 · 17 · 18 · 20 · 21 · 25 · 26 · 29 · 38px. Riêng `9.17px` là kết quả
của một phép thu tỉ lệ, không phải một lựa chọn.

Rút về 6 bậc (`11 · 12 · 14 · 18 · 24 · 36`) sẽ làm ngôi thứ thị giác tự rõ ra, và
tránh chuyện hai thứ khác tầm quan trọng lại chênh nhau đúng 1px.

## B2. Liên kết chỉ khác chữ thường ở màu

Toàn trang đặt `a { text-decoration: none }`. `Paper reconcile` là chữ xanh `#58a3ff`
không gạch chân. Trong thang xám, xanh lệch chữ thường **8 mức**. Người mù màu hoặc
đọc bản in đen trắng không thấy đó là chỗ bấm được.

Thêm gạch chân mờ cho liên kết nằm trong đoạn văn (không cần cho mục điều hướng và nút):

```css
main a[href]:not(.module-nav a) { text-decoration: underline; text-underline-offset: 2px;
                                  text-decoration-color: color-mix(in srgb, currentColor 40%, transparent); }
```

## B3. Chú giải không có dấu hiệu nhìn thấy được

21 chỗ có chú giải, nhưng chúng trông y hệt chữ thường — chỉ khi rê chuột tới, con trỏ
mới đổi thành dấu hỏi. Người vận hành **không có cách nào biết** chỗ nào có thêm thông
tin nếu không rê chuột khắp trang.

Thêm gạch chân chấm mờ để chúng tự nói ra:

```css
.has-tip { border-bottom: 1px dotted color-mix(in srgb, currentColor 35%, transparent); }
```

## B4. Nhật ký công việc lặp một câu

Sáu mục liên tiếp trong Nhật ký công việc đều mang đúng câu
*"The execution completed without trade or protection changes."* Câu này chiếm hai dòng
mỗi mục, đẩy mốc thời gian và tên công việc thưa ra.

Với lần chạy không có gì thay đổi, thu về một chữ (`no change`) và chỉ mở rộng khi có
thay đổi thật. Mật độ tăng lên, và mắt bắt ngay được mục **khác** với phần còn lại.

---

# C. Những chỗ đã đo và **không** có vấn đề

Ghi lại để lần sau khỏi rà lại, và để phân biệt *"đã đo, ổn"* với *"chưa ai kiểm"*.

| Hạng mục | Kết quả đo |
|---|---|
| **Chữ số có đẳng rộng không** | **Có, không cần sửa.** Đã thử cả 7 phông trong ô chọn phông, kể cả `System UI`: chữ số `0`/`1`/`7` **luôn cùng bề rộng**. Không cần `tabular-nums`. |
| **Bảng rộng có khối cuộn riêng không** | **Có.** Bảng Lệnh đang mở ở `/realtime` nằm trong khối cuộn ngang riêng (rộng thật 506px, ô chứa 357px, cuộn được). Cột `Status` và `ID` **cuộn tới được**, không mất. `/paper` cũng đúng: hai bảng rộng 2332px và 3522px đều có khối cuộn riêng. |
| **`/analytics` ở 390px** | 609 phần tử vượt mép, nhưng **cả 609 đều nằm trong khối cuộn thật** → tới được. Không phải lỗi. |
| **`/paper`, `/reports`, `/` ở 1440px và 390px** | 0 chỗ đè chữ, 0 chỗ mất nội dung. |
| **Đè chữ ở các trang khác** | Chỉ `/realtime` mang khối trạng thái sống. Ba trang còn lại chỉ có thanh điều hướng, nên **không dính lỗi A1**. |
| **Số cần so sánh có đặt cạnh nhau không** | Chỗ quan trọng nhất làm đúng: `stop 3,020.2 · plan 3,020.24 · −0.17%` nằm cùng một hàng, cùng thang, đọc chéo được ngay. |

---

# D. Thứ tự đề nghị làm

| Thứ tự | Mục | Vì sao trước |
|---|---|---|
| 1 | **A2** hình dạng cho trạng thái | Hỏng im lặng: xanh → vàng gần như không đổi. Rủi ro cao nhất, không có gì bù. |
| 2 | **A1** hàng đầu trang bị đè | Mất hai lối đi ở mọi laptop. Sửa nhỏ, đã có sẵn luật trong tệp. |
| 3 | **A5** nâng `--dim` | Đổi **một dòng**, sửa 111 chỗ. Tỉ lệ lợi ích trên công sức cao nhất. |
| 4 | **A4** bỏ cắt cụt `1 co…` | Ô an toàn, không được để người đọc đoán. |
| 5 | **A3** đảo ngôi thứ đầu trang | Đúng trọng tâm nhất, nhưng động tới bố cục nên cần bàn trước. |
| 6 | **A6 · A7 · A8** | Chỉ ảnh hưởng màn hình hẹp và bàn phím. |
| 7 | **B1–B4** | Sau khi phần A xong. |

---

# E. Hướng cải thiện thiết kế (khác với sửa lỗi ở phần A)

Phần A sửa những chỗ **hỏng**. Phần này bàn chuyện làm cho trang **tốt hơn mức đang
đúng**. Xếp theo mức ảnh hưởng tới câu hỏi 5 giây.

## Trước hết: giữ nguyên những gì đang đúng

Có ba thứ nên **không** đụng tới, nói ra để tránh sửa nhầm chỗ:

- **Bảng màu hiện tại tốt hơn bảng màu mặc định.** Bộ màu đang dùng (nền `#090d11`,
  bốn màu trạng thái) có cá tính và hợp bối cảnh phòng tối. Không nên thay bằng một
  bộ xám xanh chung chung. Chỉ có **một** biến hỏng (`--dim`), đã nêu ở A5.
- **Mật độ đang đúng.** Đây là công cụ nghiệp vụ, không phải trang giới thiệu. Chữ 11–13px
  dày đặc là lựa chọn đúng — vấn đề nằm ở **ngôi thứ**, không nằm ở mật độ.
- **Đã có tôn trọng chế độ giảm chuyển động.** Rất ít bảng nội bộ làm điều này.

## E1. Một dòng phán quyết ở đỉnh trang *(thay đổi lớn nhất)*

Hiện trang mở đầu bằng **số liệu**, và người đọc phải tự tổng hợp ra phán quyết. Đảo lại:
mở đầu bằng **phán quyết**, số liệu lùi xuống làm bằng chứng.

```
┌──────────────────────────────────────────────────────────────┐
│  ▲  CÓ 1 VIỆC CẦN XỬ                                         │
│     Mô hình cũ 20 tháng — vẫn đang giao dịch, đây là nợ kỹ    │
│     thuật đã biết, không phải lệnh dừng mới.                  │
│     → Không có việc phải làm ngay. Xem lại khi tái đóng băng. │
└──────────────────────────────────────────────────────────────┘
```

Ba tầng, đúng thứ tự người vận hành cần: **có việc không → việc gì → làm gì bây giờ.**
Khi sạch, khối này thu thành một dòng xanh cao 40px. Khi có việc, nó nở ra và là thứ
to nhất màn hình.

Điểm mấu chốt: **dòng "làm gì bây giờ" hiện chưa tồn tại ở đâu trên trang.** Thông tin
đó đang nằm trong ô "ACTION" của thẻ sự cố, phải cuộn xuống mới thấy. Đưa nó lên đỉnh.

## E2. Tách hai chế độ đọc: *liếc* và *điều tra*

Trang hiện dựng cho **một** người đọc duy nhất — người đọc kỹ. Nhưng có hai tình huống
rất khác nhau, và trang đang phục vụ tình huống ít gặp hơn:

| | Liếc (90% số lần) | Điều tra (10%) |
|---|---|---|
| Câu hỏi | "có gì hỏng không?" | "chuyện gì đã xảy ra?" |
| Thời gian | 5 giây | 5 phút |
| Cần gì | phán quyết + việc phải làm | nhật ký, bằng chứng, mốc thời gian |
| Hiện đang | phải quét cả trang | vừa đủ |

Đề xuất: vùng màn hình đầu tiên **chỉ** phục vụ chế độ liếc — phán quyết, vị trí đang mở
kèm mức bảo vệ, cửa sổ vào lệnh kế tiếp. Mọi thứ còn lại (nhật ký công việc, chi tiết sự
cố, quyết định hôm nay) lùi xuống dưới nếp gấp. Không phải giấu đi — chỉ là **xếp sau**.

Đây là lý do thật sự khiến trang khó liếc, và nó không sửa được bằng đổi màu.

## E3. Ghi thời gian theo khung của **người vận hành**, không theo khung của máy

Hiện trang nói `NKD_NIGHT_0110 · Mon 01:10 ET`. Người vận hành ở giờ Việt Nam phải tự
dịch sang "trưa mai, còn khoảng 30 tiếng nữa". **Đó là một quy ước bắt người ta nhớ**,
đúng dạng cần loại bỏ — và phải nhẩm lúc 2 giờ sáng thì càng dễ sai.

Trang có sẵn ba đồng hồ (`ET · JST · HAN · YYC`) nhưng ở 11px góc phải, và chỉ báo **giờ
hiện tại**, không báo **còn bao lâu**.

Đề xuất — mỗi mốc thời gian hiện đủ ba tầng, tầng người vận hành đặt trước:

```
Cửa sổ vào lệnh đêm    mở sau 6g 38p        (12:10 trưa mai, giờ VN)
                       ├──────────────────────────────┤
                       01:10          02:55 ET
```

Và khi đang **trong** cửa sổ, đổi thành thanh tiến trình: *"đã vào cửa sổ 40 phút, còn
1g 10p"*. Đây là mô hình suy nghĩ thật của người vận hành — hiện trang không hề có.

## E4. Tách phông chữ cho văn xuôi khỏi phông cho số

Cả trang đang dùng **một** phông mono cho mọi thứ, kể cả văn xuôi. Mà văn xuôi thì
không ít: mô tả sự cố, ô tác động, ô hành động, mọi dòng trong nhật ký công việc.

Điều đáng nói: **ý định tách phông đã có sẵn trong mã**, chỉ là chưa hạ cánh —

```css
--mono: var(--font-ui);
--sans: var(--font-ui);   /* trỏ vào chính phông mono */
```

`--sans` **có** được dùng thật (trong chú giải), nhưng vì nó trỏ về mono nên không có
tác dụng gì. Ai đó đã định làm việc này rồi dừng giữa chừng.

Đề xuất: trỏ `--sans` vào một phông sans thật, rồi dùng nó cho văn xuôi; giữ mono cho
số, mã hợp đồng, mã lệnh, mốc thời gian. Chữ mono ở cỡ 11px đọc lâu **mệt hơn** sans
đáng kể, và phần lớn chữ trên trang này là văn xuôi chứ không phải số.

```css
--sans: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
```

Ràng buộc phải giữ: **mọi thứ là số vẫn phải ở mono** để cột số thẳng hàng. Nếu không
chắc tách sạch được thì đừng làm — thà cả trang mono còn hơn số bị lệch cột.

## E5. Một hệ ký hiệu trạng thái dùng chung cho cả 5 trang

A2 sửa chỗ chấm trạng thái. Nhưng nên nâng thành **hệ ký hiệu** áp cho cả 5 trang, để
người vận hành học **một lần** rồi đọc được mọi nơi:

| Nghĩa | Hình | Chữ | Dùng ở |
|---|---|---|---|
| đúng / xong | ● | `OK` | mọi trang |
| cảnh báo / nợ đã biết | ▲ | `WARN` | mọi trang |
| hỏng / cần xử ngay | ■ | `FAIL` | mọi trang |
| chưa có dữ liệu | ○ rỗng | `—` | mọi trang |

Bốn trạng thái, không hơn. Hiện mỗi trang đang tự mã hoá theo cách riêng (lớp
`positive`/`warning`/`negative` ở trang này, `ok`/`watch`/`bad` ở khối khác), nên cùng
một ý nghĩa lại mang tên khác nhau tuỳ chỗ.

## E6. Thanh rủi ro nên nói ra ngưỡng, thay vì bắt tự tính

Hiện: một thanh mảnh, kèm chữ `0.6% of 15.00% hard limit`. Người đọc phải tự dựng trong
đầu xem 0,09% nằm ở đâu so với ngưỡng.

Dạng phù hợp cho "giá trị so với ngưỡng, chỗ hẹp" là **thanh dạng bullet có vùng ngưỡng
ghi chữ** — vẽ sẵn vùng an toàn / cảnh báo / vượt hạn, đặt vạch mốc ở 15%, và ghi chữ
lên từng vùng thay vì chỉ tô màu:

```
rủi ro đang dùng  0.09%
  ▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
  an toàn        │ theo dõi │ vượt hạn  ╵15.00%
  0            7.5%       12%
```

Nguyên tắc kèm theo: vùng ngưỡng phải **ghi chữ**, không được chỉ phân biệt bằng màu —
cùng lý do với E5.

---

# F. Sửa những mục này có đụng vào logic không?

Đã đo, không suy đoán. Kiểm bốn đường: (1) tệp nào phải sửa, (2) test nào đang ghim,
(3) JS có đọc kiểu dáng/hình học không, (4) CSS có bị buộc vào hành vi JS không.

## F1. Bảng phân loại

| Mục | Tệp phải sửa | Đụng logic? |
|---|---|---|
| **A1** hàng đầu trang | `realtime.css` | **Không** |
| **A4** cắt cụt `1 co…` | `realtime.css` | **Không** |
| **A5** nâng `--dim` | `realtime.css` | **Không** |
| **A6** dòng môi giới ở 390px | `realtime.css` | **Không** |
| **A7** vùng bấm | `realtime.css`, `paper.css` | **Không** — nhưng xem F2 |
| **A8** vòng viền tiêu điểm | `realtime.css`, `paper.css` | **Không** |
| **A2** hình dạng trạng thái | `realtime.css` | **Không** cho phần nhìn thấy; **có** nếu muốn thêm nhãn cho trình đọc màn hình |
| **A3** đảo ngôi thứ đầu trang | `index.html` + `realtime.js` | **CÓ — đây là mục duy nhất động vào mã dựng trang** |
| B1–B4 | CSS (B4 cần JS) | B1–B3 không; **B4 có** |

**Sáu mục A1 · A4 · A5 · A6 · A7 · A8 là CSS thuần.** Không chạm tệp Python nào,
không chạm runner, không chạm engine, không chạm mã đặt lệnh.

**A2 làm được bằng CSS thuần** — điều này phải kiểm mới biết. Trạng thái đã nằm sẵn
trong lớp mà JS gán (`positive` / `warning` / `negative`, và `ok` / `watch` / `bad` trên
khối kết luận), còn CSS thì đã đọc lớp đó để tô màu. Cả **6 chấm** đều có đường lấy
trạng thái từ CSS, nên thêm hình dạng và chữ chỉ là thêm luật CSS trên đúng các bộ chọn
đang có. Riêng nhãn cho trình đọc màn hình thì CSS không đặt được — muốn có phải sửa JS,
và đó là việc **tách riêng, không bắt buộc** để đạt phần lợi ích chính.

**A3 là mục duy nhất thật sự động vào mã dựng trang.** Đảo ngôi thứ nghĩa là đổi thứ tự
khối trong trang và đổi hàm dựng. Vẫn chỉ là mã giao diện — không phải mã giao dịch —
nhưng khác hẳn về mức rủi ro so với sáu mục kia. **Nên tách thành một lượt riêng.**

## F2. Một chỗ CSS **có** buộc vào hành vi JS — phải biết trước khi sửa

`realtime.js` dòng 8 giữ `window.matchMedia('(max-width: 680px)')`, và dùng nó ở **6 chỗ**
để quyết định: ở màn hình hẹp thì **không** tự mở sẵn sự cố đầu tiên, và bấm lần nữa thì
đóng lại. Mốc 680px này **trùng đúng** mốc trong CSS (`realtime.css:515`).

Nghĩa là 680px không phải con số trang trí — nó là **giao ước giữa CSS và JS**. Nếu thêm
luật ở một mốc khác (ví dụ 700px), sẽ có một dải 20px mà trang hiển thị theo kiểu hẹp
nhưng JS vẫn xử theo kiểu rộng.

**Tôi đã suýt mắc đúng lỗi này.** Bản đầu của tài liệu viết `@media (max-width: 700px)`
ở hai chỗ và ghi nhầm mốc có sẵn là 700px. Đã sửa lại thành **680px**. Luật rút ra: mọi
luật mới thêm cho màn hình hẹp phải dùng **đúng 680px**, không phải một mốc gần đúng.

## F3. Test đang ghim những gì

- **79 câu ghim chuỗi trong CSS**, nhưng đều thuộc dạng *"tên lớp này phải có / không
  được có"*. **Không câu nào ghim giá trị thuộc tính** mà các bản sửa trên đụng tới —
  không ghim `--dim`, không ghim `grid-template-columns`, không ghim `white-space`,
  không ghim `outline`.
- Có sẵn **một test trình duyệt thật** kiểm tràn ngang ở nhiều bề rộng, và nó **đã** biết
  bỏ qua khối cuộn hợp lệ. Các bản sửa trên chỉ làm nó dễ xanh hơn.
  *Lưu ý:* test này đang xanh **trong khi hàng đầu trang vẫn đè chữ** — vì nó chỉ kiểm
  tràn của trang, không kiểm chữ đè chữ. Nên khi sửa A1, **phải thêm phép kiểm so hình
  chữ nhật từng cặp** (mục G), nếu không thì lỗi này quay lại mà test vẫn xanh.
- Hai chỗ đọc `realtime.css` trong test: một chỗ chỉ đòi `.scheduler-health` **không**
  còn trong tệp, một chỗ đọc nhưng không ghim gì về CSS. Cả hai không cản.

## F4. JS có đọc hình học không

Quét cả 5 tệp JS của bảng: **chỉ 3 chỗ** đọc hình học hoặc kiểu dáng.

| Chỗ | Đọc gì | Bản sửa trên có ảnh hưởng không |
|---|---|---|
| `realtime.js:8` | mốc màn hình 680px | **Có, nếu dùng sai mốc** — xem F2 |
| `analytics.js:122-123` | bề rộng/cao khung để vẽ biểu đồ | Không — không mục nào sửa CSS của `/analytics` |
| — | không có chỗ nào đo bề rộng chữ để cắt cụt | Không |

Không có chỗ nào trong bảng đọc màu, đọc kiểu dáng đã tính, hay đổi hành vi theo lớp CSS.
Nghĩa là **đổi màu và đổi giãn cách không thể làm lệch bất kỳ quyết định nào của trang.**

## F5. Kết luận

**Có** — nếu làm sáu mục A1 · A4 · A5 · A6 · A7 · A8 (cộng A2 ở dạng CSS), thì chỉ đụng
tệp CSS, không đụng một dòng logic nào, không đụng Python, không đụng runner hay engine.

**Hai điều kiện kèm theo:**

1. Luật mới cho màn hình hẹp phải dùng **đúng mốc 680px** (F2).
2. **A3 tách ra một lượt riêng** — đó là mục duy nhất sửa mã dựng trang.

**Cổng kiểm trước khi nhận bản sửa:** chạy bộ test của `monitor/` (3 tệp liên quan: kiểm
DOM, kiểm giao ước, kiểm backend) và thêm phép kiểm chữ-đè-chữ ở mục G cho các bề rộng
1280 / 1366 / 1440 / 1600 / 1920 / 390px. Không có phép kiểm chữ đè chữ thì lỗi A1
không có gì giữ.

---

# G. Ghi chú về cách kiểm tràn ngang

Bài học từ đợt đo này, đáng ghim vào phép kiểm tự động:

**`scrollWidth > clientWidth` là phép kiểm SAI cho trang này.** Khung trang đặt
`overflow-x: hidden`, nên nội dung tràn bị **cắt** thay vì tạo thanh cuộn, và phép kiểm
báo xanh. Đã gặp hai lần trong đợt này:

- Hàng đầu `/realtime`: nội dung 721px trong ô 457px, tràn **sang trái**, đè lên
  thanh điều hướng — `1425 == 1425`, **xanh**.
- Dòng môi giới ở 390px: `documentElement.scrollWidth == clientWidth == 390`, **xanh**,
  trong khi `body.scrollWidth = 602`.

**Phép kiểm đúng, ba bước:**

1. Duyệt mọi phần tử, lấy hình chữ nhật đã bố trí; giữ lại phần tử có mép phải vượt bề
   rộng khung nhìn **hoặc** mép trái âm.
2. Với mỗi phần tử đó, đi ngược lên cây tổ tiên tìm khối cuộn ngang gần nhất.
   - Tìm thấy khối có `overflow-x: auto|scroll` **và** `scrollWidth > clientWidth`
     → `REACHABLE`, không phải lỗi.
   - Gặp `overflow-x: hidden` trước, hoặc lên tới gốc → `CUT`, **là lỗi**.
3. Riêng chuyện đè chữ thì `scrollWidth` không bao giờ bắt được. Phải so trực tiếp hình
   chữ nhật của từng cặp nút chữ lá, bỏ qua cặp có quan hệ tổ tiên–con cháu; phần giao
   nhau lớn hơn 4×4px là đè thật.

Bước 3 là bước đã bắt được lỗi A1. Không có nó thì hàng đầu trang vẫn "xanh".

---

# H. Trạng thái sau khi thực hiện — đo lại 2026-08-17

Bản rà soát ở trên viết ngày 2026-08-16, **trước** khi thiết kế lại được dựng và áp.
Phần này không viết lại phân tích cũ — nó chỉ nói mục nào đã đóng, mục nào chưa,
và sửa những con số nay đã sai.

Đo trên `/realtime` **thật** (không phải preview), Chrome, 1900×1000 và 390×844.
Một lưu ý về cách đo: suốt quá trình dựng, mọi phép đo đều chạy trên
`preview.html?skin=e` trong khi trang thật **không nạp skin nào** — nên hàng chục
báo cáo "đã khớp" đúng ở chỗ đo và vô nghĩa ở chỗ người dùng nhìn. Số dưới đây
lấy trên trang thật.

## H1. Câu hỏi trung tâm, đo lại

| Hạng | Nội dung | 2026-08-16 | 2026-08-17 |
|---|---|---|---|
| 1 | vốn giấy | 37px | **40px** |
| 2 | mức dùng rủi ro | 29px | 22px |
| 3 | nhãn mục | 25px | 17px |
| 4 | **câu phán quyết** | **13px** | **15px** |
| 4= | `20 mo stale`, `45 warn` | 16px | 15px |

**Chỉ đóng được một nửa.** Câu phán quyết lên 13→15px và giờ ngang hàng với các
dấu hiệu bất thường thay vì nằm dưới chúng. Nhưng **xét riêng cỡ chữ, con số vốn
vẫn to gấp 2,7 lần câu phán quyết** — tỉ lệ gần như không đổi (trước là 2,8).

Cái đã thay đổi thật là **vị trí và màu trạng thái**, không phải thang chữ: câu
phán quyết giờ nằm trên một dải riêng chạy hết bề ngang ngay dưới header, kèm chấm
và nhãn OK/FAIL, và cả dải đổi nền theo trạng thái. Nếu tiêu chí là "thứ trả lời
câu hỏi phải là thứ to nhất" thì **chưa đạt**; nếu tiêu chí là "phải là thứ đập vào
mắt trước tiên" thì đạt bằng con đường khác.

## H2. Từng mục

| Mục | Trạng thái | Đo được hôm nay |
|---|---|---|
| A1 chữ đè chữ ở thanh điều hướng | **đóng** | 0 va chạm, 234 node văn bản |
| A2 trạng thái chỉ mã hoá bằng màu | **đóng** | chip mang chữ (`OPEN`/`KNOWN DEBT`/`RECOVERED`), viền trung tính, màu chỉ ở chữ |
| A3 thứ quan trọng bị chôn | **một phần** | xem H1 |
| A4 giá trị an toàn bị cắt `1 co…` | **đóng** | 0 chữ vượt viền thẻ; Protection ra `--` hoặc số |
| A5 tương phản dưới AA ở 111 chỗ | **đóng** | **8/618** node còn dưới 4.5:1 |
| A6 390px cắt và không cuộn tới được | **đóng** | 0 phần tử bị cắt ở 390px (test browser ghim) |
| A7 vùng bấm quá nhỏ | **CHƯA** | **19** phần tử tương tác dưới 24px theo một chiều |
| A8 mất vòng viền tiêu điểm | **đóng** | 19 chỗ có chú giải, **0** thiếu vòng viền |
| B1 thang cỡ chữ 16 bậc | **một phần** | còn **11** bậc, chưa phải một thang |
| B2 liên kết chỉ khác ở màu | chưa rà lại | — |
| B3 chú giải không có dấu hiệu | chưa rà lại | — |
| B4 nhật ký lặp một câu | **đóng** | khối chẩn đoán tự ẩn khi trùng nguyên văn khối bằng chứng |

## H3. Phần E — hướng thiết kế

E1 (dải phán quyết), E2 (tách liếc/điều tra), E3 (giờ theo khung người vận hành),
E4 (tách phông văn xuôi khỏi phông số) đã dựng và đang chạy trên `/realtime`.

**E6 đã dựng rồi gỡ.** Ba nhãn ngưỡng dưới thanh rủi ro (`safe`/`watch`/`over limit`)
được thêm, sau đó ẩn đi: dòng ngay trên thanh đã in `0.6% of 15.00% hard limit`,
tức đã nói ra thang đo, nên ba nhãn kia là nói lại lần hai. Ghi ra đây vì "đã làm
rồi bỏ" khác với "chưa làm".

## H4. Còn mở

- **A7** — 19 vùng bấm dưới 24px. Phần lớn là chữ có `tabindex` để hiện chú giải,
  rộng nhưng chỉ cao 15px; ở 390px dùng ngón tay là trượt.
- **B1** — 11 cỡ chữ, chưa quy về một thang.
- **B2, B3** — chưa đo lại sau khi đổi thiết kế.
- Năm chuỗi do `realtime.js` sinh vẫn khác bản dựng tham chiếu (câu phán quyết viết
  hoa, cụm độ tươi, `hard limit`, ô `Held`, nút `Refit`). Sửa được, nhưng phải chọn:
  đụng file dùng chung với bốn dashboard kia, hay để lớp phủ viết lại chuỗi.
- Nhật ký công việc: bản dựng có mã thoát và mức `INFO`/`ERROR`; hai thứ đó **không
  tồn tại như trường dữ liệu** trong payload, nên không phải việc của CSS.
