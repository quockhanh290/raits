# Rà soát độc lập candidate `Rolling-3Y WFO: YDAY crash/panic + PE`

Ngày chạy: 2026-09-08, 02:07 ET (máy Calgary 00:07 MDT). Commit HEAD khi đo: `1f2ad55`.

Hợp đồng đã giữ: chỉ đọc code, dữ liệu và tài liệu. Không sửa code, không sửa cấu hình,
không commit, không xoá gì. Không mở bất kỳ tệp nào trong vùng futures bị cấm. Tệp duy nhất
tôi tạo là báo cáo này; mọi script đo nằm ở thư mục tạm ngoài kho.

---

## 0. Phán quyết

**Hướng nghiên cứu: có thật. Bộ số công bố: không dùng được.**

Tôi dựng lại toàn bộ candidate bằng đường đo riêng, đọc thẳng kho bar 5 phút, không dùng
một dòng code nào của vòng trước. Kết quả tách làm hai nửa rõ rệt:

**Nửa tái lập được.** Cách chọn cổ phiếu tái lập gần như chính xác. Số lệnh của bảy luật
trong rổ ứng viên lệch 1-5% so với bản gốc (ví dụ luật panic: 148 lệnh của tôi so với 147).
Quy trình walk-forward cuốn chiếu 3 năm của tôi **chọn đúng những luật mà bản gốc đã chọn**,
đúng từng năm một: luật panic cho 2020-2022, luật quality cho 2023-2024. Và tín hiệu gốc là
thật: mua cổ phiếu vừa sập ít nhất 7% hôm trước, giữ từ mở cửa tới 15:55, trung bình được
**+1,97% mỗi lệnh với 70% số lệnh thắng**. Đó không phải nhiễu.

**Nửa không tái lập được.** Số tiền. Bản gốc công bố `+$52.639`. Đường đo của tôi, trên đúng
những luật đó, đúng những năm đó, ra **`+$29.805`**. Quan trọng hơn con số lệch: tôi chạy lại
với **chi phí giao dịch bằng không** — tức trần tuyệt đối mà bộ luật này có thể sinh ra trên
kho dữ liệu này — và trần đó là **`$37.996`**. Con số công bố **cao hơn trần không-chi-phí
của tôi 39%**. Không có mức phí nào, không có cách tính vốn nào đưa được `$29.805` lên
`$52.639`; muốn tới đó phải có thêm tiền từ chỗ khác mà tôi không tìm ra.

Và chỗ lệch không rải đều. Nó dồn vào đúng hai năm mang toàn bộ sức thuyết phục:

| Năm | Bản gốc công bố | Đường đo của tôi | Ghi chú |
|---|---:|---:|---|
| 2020 | `$13.891` | `$12.756` | khớp, lệch 8% |
| 2021 | `$4.910` | `$5.058` | khớp, lệch 3% |
| 2022 | `$12.907` | **`$636`** | **lệch 20 lần** |
| 2023 | `$13.164` | **`$6.466`** | **lệch 2 lần** |
| 2024 | `$7.768` | `$4.889` | lệch 1,6 lần |

Hai năm đầu khớp đẹp. Đúng năm 2022 — năm được dùng để nói "candidate này sống qua thị
trường gấu" — thì không khớp, và không khớp tới hai chục lần. Cũng đúng 2023, năm gần nhất
có nhiều lệnh. Một sai số ngẫu nhiên không chọn đúng hai năm mang thông điệp.

**Và ngay cả khi bỏ qua toàn bộ chuyện số liệu, quy trình walk-forward vẫn không chứng minh
được điều nó tự nhận.** Xem mục 3 — đây là phát hiện nặng nhất của đợt rà.

Nhãn theo thang đã thống nhất: **FAIL** cho bộ số đã công bố. **WARN** cho hướng nghiên cứu.

---

## 1. Bảng checklist

| Mục | Trạng thái | Câu một dòng |
|---|---|---|
| Nhân quả của từng đặc trưng | **PASS có điều kiện** | Mọi đặc trưng đều dịch đúng, không nhìn tương lai. Một đặc trưng có rủi ro khớp lệnh chứ không phải rủi ro nhân quả |
| Giá vào lệnh có khớp được không | **WARN** | Với nhóm luật panic thì khớp được. Với nhóm luật gapdown thì không, và nhóm đó gánh 40% tiền |
| Thanh khoản / quy mô lệnh | **PASS** | Lệnh trung vị `$35.000` trên `$228` triệu khớp trong 5 phút đầu — chiếm 0,01%. Không phải nút thắt |
| Quy trình walk-forward | **FAIL** | Rổ ứng viên được lọc bằng chính kết quả 2023-2024 trước khi walk-forward bắt đầu |
| Tái lập được con số chính | **FAIL** | `$29.805` so với `$52.639`; trần không-chi-phí của tôi là `$37.996` |
| Nhiễu dữ liệu | **PASS** | Vùng META hỏng vẫn còn trong kho nhưng không chạm một lệnh nào của candidate |
| Nguồn ngày earnings | **WARN** | Không phải ngày công bố kết quả mà là ngày nộp hồ sơ lên uỷ ban chứng khoán; thiếu hẳn một quý mỗi năm |
| Thiên lệch sống sót | **FAIL** | Rổ 62 mã có mặt đủ từ ngày đầu tới ngày cuối, không một mã nào rời sàn |
| Tập trung rủi ro | **FAIL** | Một mã gánh 46% lợi nhuận; 10 lệnh tốt nhất gánh 63% |
| Kiểm định lại bằng lấy mẫu theo ngày | **WARN** | Bền trên tập hiện có, nhưng tập đó đã nhiễm nên phép kiểm chỉ đo độ tản, không đo tính đúng |

---

## 2. Nhân quả và khớp lệnh

### 2.1 Không có nhìn trộm tương lai

Đây là điều tôi kiểm trước tiên, và tôi không tìm thấy vi phạm. Tôi dựng lại từng đặc trưng
bằng phép dịch chặt và kiểm chéo bằng cách thử cả các biến thể *có* nhìn trộm để xem chúng
trông thế nào:

- Mức sụt hôm trước lấy từ giá mở cửa và giá 15:55 của **ngày hôm trước**. Sạch.
- Khoảng hở sáng nay so giá mở cửa hôm nay với giá đóng hôm qua. Cả hai đều biết lúc 09:30.
- Chỉ báo đà 20 ngày kết thúc ở **ngày liền trước**, không chạm ngày giao dịch.
- Điều kiện về chỉ số thị trường lấy phiên hôm trước.

Phép kiểm quyết định: tôi chạy lại luật panic với điều kiện thị trường lấy **cùng ngày**
thay vì hôm trước — tức cố tình tạo ra nhìn trộm. Kết quả **tệ hẳn đi**: từ `$56.965` xuống
`$3.346`. Nếu bản gốc có nhìn trộm ở chỗ này thì nó đã phải cho số cao hơn, không phải thấp
hơn. Nên tôi loại giả thuyết look-ahead ở tầng đặc trưng.

### 2.2 Nhưng có một chỗ giá vào lệnh không lấy được

Đây là chỗ cần tách bạch, vì hai nhóm luật khác hẳn nhau và tài liệu gốc gộp chúng làm một.

**Nhóm panic — khớp được.** Điều kiện chỉ gồm mức sụt hôm qua và chỉ số hôm qua. Cả hai
biết từ tối hôm trước. Có thể đặt lệnh mua theo giá mở cửa từ đêm và nó sẽ khớp đúng ở phiên
khớp lệnh mở cửa. Giá dùng trong mô phỏng là giá lấy được thật.

**Nhóm gapdown — không khớp được như đã viết.** Điều kiện gồm "sáng nay mở cửa thấp hơn giá
đóng hôm qua". Muốn biết điều đó phải thấy giá mở cửa. Nhưng mô phỏng lại **mua chính ở giá
mở cửa đó**. Không ai vừa nhìn thấy giá khớp lệnh mở cửa vừa mua được ở giá ấy — phiên khớp
lệnh mở cửa in ra một giá duy nhất, và lệnh của bạn phải nằm trong sổ *trước* khi nó in.

Tôi đo mức giá phải trả cho việc này bằng cách dời điểm vào lệnh sang 09:35 — thời điểm sớm
nhất chắc chắn lấy được sau khi đã thấy giá mở cửa:

| Nhóm lệnh | Vào lúc 09:30 | Vào lúc 09:35 | Mất |
|---|---:|---:|---:|
| Luật quality (chọn cho 2023-2024) | +1,614% | +1,140% | −29% |
| Luật panic | +1,970% | +1,577% | −20% |
| Nhánh bán khống theo earnings | +0,993% | +0,471% | **−53%** |

Nhánh bán khống mất hơn nửa lợi thế trong đúng năm phút đầu. Đó là dấu hiệu kinh điển của
một mức giá không lấy được.

**Nhưng — và chỗ này phải nói cho công bằng — bản thân bộ lọc gapdown không phải ảo giác.**
Tôi tách riêng để kiểm: trong nhóm cổ phiếu vừa sập ít nhất 4%, những mã sáng nay mở cửa
thấp hơn hôm qua chạy tốt hơn những mã còn lại **+0,613%** nếu đo tại 09:30, và vẫn
**+0,583%** nếu đo tại 09:35. Sức phân biệt gần như không suy giảm khi dời điểm vào lệnh.
Nghĩa là bộ lọc mang thông tin thật; chỉ có **mức lời tuyệt đối** bị thổi lên bởi giá vào
lệnh không lấy được. Đây là điểm mạnh có thật của vòng 6.24 và tôi xác nhận nó.

Kết luận mục này: **lạc quan, không phải bất khả thi.** Muốn dùng thì phải đo lại toàn bộ với
điểm vào 09:35 trở đi cho mọi luật có điều kiện chạm tới giá mở cửa.

### 2.3 Quy mô lệnh không phải vấn đề

Lệnh trung vị `$35.102`. Riêng thanh 5 phút đầu tiên của phiên đã khớp trung vị **`$227,6`
triệu** ở chính mã đó, ngày đó. Lệnh chiếm **0,01%**, trường hợp nặng nhất trong 148 lệnh là
2,55%. Ở quy mô tài khoản `$50.000` thì thanh khoản không giới hạn gì cả. Mục này sạch.

---

## 3. Chỗ hỏng nặng nhất: walk-forward chạy trên một rổ đã biết đáp án

Đây là phát hiện quan trọng nhất và nó không cần con số nào để thấy — nó nằm ngay trong
tài liệu gốc, ở hai mục cách nhau vài trang.

Vòng trước sàng 432 cấu hình và giữ lại 300 cấu hình theo ba tiêu chí. Tiêu chí thứ hai,
nguyên văn, là: **kết quả 2023-2024 phải dương**.

Vòng sau lấy rổ ứng viên cho walk-forward là "các luật đơn giản đã sống qua vòng trước".

Ghép hai câu đó lại: **rổ bảy luật mà walk-forward được phép chọn đã được lọc bằng chính
kết quả của kỳ mà walk-forward dùng để kiểm.** Quy trình tự nhận là mỗi năm chỉ chọn bằng
dữ liệu quá khứ, nhưng cái *danh sách* để chọn thì đã được xây bằng dữ liệu tương lai.

Tôi đo hệ quả trực tiếp:

| Luật trong rổ | Lãi 2023-2024 |
|---|---:|
| raw_-4 | `$15.923` |
| gapdown_-4 | `$15.082` |
| gapdown_-5 | `$11.340` |
| quality_mompos_-5 | `$8.294` |
| panic_-7_spyBD | `$6.759` |
| panic_-7_spyBD_momneg | `$6.641` |
| panic_-7_nodeep_spyBD_momneg | `$6.641` |

**Bảy trên bảy đều dương.** Không phải may — đó là điều kiện tuyển. Nghĩa là với năm 2023 và
2024, walk-forward **không thể chọn sai**, vì mọi lựa chọn đều đã được bảo đảm có lãi từ
trước. Hai năm đó đóng góp `$20.932` trong `$52.639`, tức **40% con số chính**, và chúng
không mang một chút giá trị kiểm định nào.

Điều này cũng giải thích một chuyện lẽ ra phải gây nghi ngờ ngay: bản gốc thấy walk-forward
cuốn chiếu (`$52.639`) tốt hơn hẳn walk-forward neo gốc (`$30.261`) và ghi nhận như một ưu
điểm. Trong đường đo của tôi **thứ tự đảo ngược**: neo gốc `$39.098`, cuốn chiếu `$29.805`.
Khi hai cách chia dữ liệu cho kết quả đảo chiều tuỳ người đo, cái đang được đo không phải là
chất lượng của luật.

### 3.1 Hàm chấm điểm là một tham số tự do chưa ai khai báo

Tài liệu gốc mô tả cách chấm điểm để chọn luật là "lãi cộng hệ số lời/lỗ, phạt sụt vốn và
phạt số lệnh quá ít". Đó là một câu văn, không phải một công thức. Tôi thử năm hàm chấm
điểm đều khớp với mô tả ấy:

| Hàm chấm | Luật được chọn | Lãi |
|---|---|---:|
| A, C, E | đúng như bản gốc | `$29.805` |
| B | lệch ở năm 2024 | `$32.350` |
| D (chỉ theo lãi) | lệch bốn trong năm năm | `$16.322` |

Ba trong năm hàm chọn ra **đúng chuỗi luật của bản gốc** — đó là bằng chứng tốt cho quy
trình. Nhưng khoảng dao động của kết quả là từ `$16.322` tới `$32.350`, tức **gấp đôi**, chỉ
do một lựa chọn không được ghi ra ở đâu và được ấn định sau khi đã nhìn dữ liệu.

---

## 4. Nguồn ngày earnings không phải thứ nó tự nhận

Nhánh bán khống theo earnings đóng góp `$10.783` trong `$29.805` của đường đo của tôi — hơn
một phần ba. Nó dựa vào một tệp danh sách ngày. Tôi đọc đoạn mã đã tạo ra tệp đó và thấy nó
lấy **ngày nộp báo cáo tài chính lên uỷ ban chứng khoán**, không phải ngày doanh nghiệp công
bố kết quả. Hai thứ này khác nhau, và sự khác nhau để lại dấu vết đo được:

- Toàn bộ danh sách có **1.457 ngày cho 62 mã trong 8 năm — trung bình 2,94 lần một năm**,
  trong khi doanh nghiệp Mỹ báo cáo bốn lần. **Thiếu khoảng 26%.** Và thiếu có hệ thống: quý
  cuối niên độ được gộp vào báo cáo năm, mà truy vấn chỉ xin báo cáo quý. Ví dụ rõ nhất là
  Apple — tệp có đủ ba kỳ tháng Hai, tháng Năm, tháng Tám của **cả tám năm**, và không có
  một kỳ mùa thu nào.
- Với những mã nộp hồ sơ tách rời ngày công bố, ngày trong tệp lệch hẳn. Adobe có các mốc
  cách nhau **đúng 91 ngày** suốt tám năm — một nhịp đều đặn như vậy không phải là lịch công
  bố kết quả thật.

**Nhưng nhãn không sai hoàn toàn**, và tôi phải nói rõ điều này thay vì kết luận sớm. Tôi đo
xem những ngày được gắn cờ có thật sự trùng với ngày thị trường phản ứng không: ngày được
gắn cờ có xác suất hở giá quá 5% là **11,1%**, so với **0,9%** ở ngày không gắn cờ — **cao
gấp 12,5 lần**. Và phép kiểm đối chứng nói rõ hơn nữa: những ngày hở giá xuống quá 5% mà
**không** nằm trên danh sách chỉ cho +0,073% mỗi lệnh, trong khi những ngày có nằm trên danh
sách cho **+0,993%** — gấp mười ba lần. Cái cờ này mang thông tin thật, không phải chỉ đang
lọc ra các cú hở giá lớn.

Nên phát biểu đúng là: **nhánh này có tín hiệu thật, nhưng nó không đang giao dịch cái mà
tên gọi của nó nói.** Nó bỏ sót một phần tư số sự kiện và bao gồm một số ngày không phải
ngày phản ứng. Khi triển khai thật với lịch công bố kết quả đúng, tập lệnh sẽ **khác hẳn**,
đông hơn, và con số đo được ở đây không chuyển sang được.

---

## 5. Thiên lệch sống sót — có, và đúng hướng gây hại nhất

Rổ 62 mã là một danh sách viết tay nằm trong mã nguồn. Tôi kiểm ngày đầu và ngày cuối của
từng mã trong kho dữ liệu:

- **62 trên 62 mã có mặt cả ở phiên đầu tiên (03/01/2017) lẫn phiên cuối cùng (31/12/2024).**
- Không một mã nào rời sàn, bị mua lại, hay biến mất giữa chừng.
- Mua và giữ suốt kỳ: trung vị **+165%**, chỉ **5 trên 62 mã** lỗ.

Với một chiến lược bất kỳ thì đây đã là vấn đề. Với **chiến lược mua cổ phiếu vừa sập** thì
nó tấn công đúng vào giả định cốt lõi. Luật nói: khi một cổ phiếu mất 7% trong một phiên,
hôm sau hãy mua. Điều luật đó cần biết là "cổ phiếu sập rồi thì có bật lại không". Còn rổ
này được chọn năm 2026, và mọi mã trong đó đều đã bật lại — vì đó là điều kiện để chúng còn
tồn tại và được đưa vào danh sách. Những cái tên sập 7% rồi sập tiếp cho đến khi không còn
gì thì không nằm trong rổ để mà thua.

Tôi **không đo được độ lớn** của thiên lệch này, vì làm thế cần một rổ dựng theo thành phần
tại từng thời điểm mà kho hiện tại không có. Nhãn đúng: **cơ chế đã xác minh, độ lớn chưa ai
đo.** Nhưng hướng thì không mơ hồ — nó chỉ có thể làm kết quả đẹp lên.

Đây cũng là lý do phải nói thẳng về "Đường 4 — mở rộng universe" trong vòng trước. Vòng đó
xếp mở rộng rổ là hướng tăng lợi nhuận tốt nhất về mặt cấu trúc. Đúng, nhưng lý do quan trọng
hơn không phải là để có thêm lệnh: **rổ hiện tại đang che mất một phần rủi ro thật.** Mở rộng
rổ mà không dựng lại theo thành phần lịch sử thì chỉ nhân bản thiên lệch lên gấp ba.

---

## 6. Tập trung rủi ro — nặng hơn bản gốc ghi nhận

Trên đường đo của tôi:

| Phép thử | Số lệnh | Lãi | Hệ số lời/lỗ |
|---|---:|---:|---:|
| Nền | 123 | `$29.805` | 2,04 |
| Bỏ TSLA | 104 | `$15.386` | 1,69 |
| Bỏ TSLA + NVDA + AMD | 88 | `$14.660` | 1,76 |
| Bỏ 5 lệnh tốt nhất | — | `$18.341` | — |
| Bỏ 10 lệnh tốt nhất | — | `$11.055` | — |
| Bỏ năm tốt nhất (2020) | — | `$17.049` | — |

Riêng **TSLA gánh `$13.803`, tức 46% toàn bộ lợi nhuận**, từ 19 lệnh. Mười lệnh tốt nhất
gánh **63%** — bản gốc báo con số này là 45,7%. Lấy mẫu lại theo ngày sau khi bỏ TSLA cho
xác suất lỗ **2,92%** và phân vị 5% chỉ còn **`$2.379`**; con số nền tương ứng của bản gốc là
`$32.189`.

Nói cho gọn: đây không phải một chiến lược có 116 quan sát độc lập. Đây là **khoảng mười cú
bật nảy lớn của cổ phiếu công nghệ vốn hoá lớn trong hai đợt hoảng loạn**, cộng một cái đuôi
dài gần như bằng không.

---

## 7. Nhiễu dữ liệu — mục này sạch

Tôi quét toàn bộ kho tìm bước nhảy giá bất thường giữa hai phiên liên tiếp:

- Vùng META hỏng đã biết từ trước **vẫn còn trong kho**: 70 phiên từ 08/07/2021 đến
  28/01/2022 có giá đóng dưới `$50` trong khi giá thật quanh `$330`. Nhưng tôi kiểm từng lệnh
  của candidate: **không một lệnh nào rơi vào vùng đó.** Không ảnh hưởng.
- Ngoài META còn đúng 10 bước nhảy quá 25%, và tôi đối chiếu từng cái: tất cả là sự kiện
  thật (Biogen với thuốc Alzheimer, Netflix mất 35% tháng 4/2022, Palo Alto tháng 2/2024,
  Intel tháng 8/2024, Salesforce tháng 8/2020). Không phải nhiễu chia tách.
- Không có dòng nào có giá mở cửa hay giá đóng nằm ngoài khoảng cao-thấp của ngày. Nhất quán
  nội bộ.
- Các mã đã chia tách đều được điều chỉnh ngược đồng nhất, không ảnh hưởng tỉ suất.

Một chỗ tôi **chưa kiểm được**: chuỗi giá của ServiceNow có hệ số quy đổi trôi nhẹ theo thời
gian thay vì cố định. Không có bước nhảy nội bộ nào nên khả năng ảnh hưởng thấp, nhưng tôi
không có nguồn giá độc lập để đối chiếu trong phiên này. Nhãn: **chưa ai kiểm.**

---

## 8. Vì sao tôi không dựng lại được con số gốc

Nói thẳng: **không có đoạn mã nào trong kho tạo ra các con số của vòng 6.24-6.26.** Tôi tìm
theo tên luật, theo tên đặc trưng, theo thời gian sửa tệp — không có gì. Vòng trước tự mô tả
là chạy mô phỏng trong bộ nhớ, một tiến trình, và không lưu lại.

Hệ quả không phải là "khó kiểm" mà là **con số đó không tồn tại ở dạng có thể dựng lại**.
Đúng cùng một dạng lỗi mà kho này đã trả giá với con số bị đóng băng mà không đóng băng
thước đo: một giá trị được công bố, được đưa vào bảng quyết định, và không ai — kể cả người
tạo ra nó — dựng lại được ở bất kỳ ngày cắt nào.

Ba tham số bắt buộc để tái lập đều **không được ghi ở đâu**: mô hình chi phí (chỉ ghi
"hoa hồng cộng chênh lệch giá cộng trượt giá"), hàm chấm điểm chọn luật, và cách xử lý phiên
giao dịch rút ngắn — kho có 1.002 phiên nửa ngày không có thanh 15:55, tức không có giá thoát.

Tôi đã thử **32 tổ hợp** định nghĩa hợp lý — mức sụt tính theo trong phiên hay giữa hai phiên
đóng cửa, điều kiện thị trường theo bốn cách, ngưỡng và số lệnh của nhánh earnings, hai mức
chi phí. Không tổ hợp nào chạm tới `$83.235` mà bản gốc báo cho luật panic; gần nhất là
`$63.419`, và bản đó khớp số lệnh 148/147 nhưng chỉ cho 2022 `$2.160` thay vì `$17.347`.

Một mâu thuẫn nội bộ nữa trong chính tài liệu gốc, cùng họ: cùng một bộ lọc thị trường được
báo là chữa được 2022 thành `+$10.769` ở một bảng và `−$3.014` ở bảng chi tiết theo năm ngay
bên dưới. Bản gốc có ghi nhận chỗ này và tự gọi là lỗi lệch ngày trong một lượt chạy — điều
đó trung thực, nhưng nó cũng nói rằng công cụ đo đã sai ít nhất một lần **ở đúng cái năm mà
lần này lại lệch 20 lần.**

---

## 9. Xếp theo mức nghiêm trọng

**Nghiêm trọng — phải sửa trước khi dùng bất kỳ con số nào**

1. **Walk-forward chạy trên rổ đã lọc bằng kết quả kỳ kiểm.** Bảy trên bảy luật đều có lãi
   2023-2024 vì đó là điều kiện tuyển. Hai năm đó là 40% con số chính và không mang giá trị
   kiểm định. Quy trình phải chạy lại với rổ đóng băng trước khi nhìn kỳ kiểm.
2. **Con số chính vượt trần không-chi-phí của bản dựng lại 39%.** `$52.639` so với trần
   `$37.996`. Sai lệch dồn vào 2022 (20 lần) và 2023 (2 lần).
3. **Không tái lập được vì không có mã.** Ba tham số quyết định kết quả không được ghi ở đâu.

**Cao — làm hỏng cách đọc kết quả**

4. **Thiên lệch sống sót đúng chiều gây hại.** Chiến lược mua cổ phiếu sập, chạy trên rổ mà
   62/62 mã đều sống và đa số tăng gấp đôi rưỡi.
5. **Giá vào lệnh không lấy được với nhóm luật gapdown**, và nhóm đó được chọn cho 2023-2024.
   Dời sang 09:35 mất 29% ở nhánh mua và 53% ở nhánh bán khống.
6. **Tập trung vào một mã.** TSLA gánh 46%; bỏ nó ra thì hệ số lời/lỗ rơi từ 2,04 xuống 1,69.

**Trung bình**

7. **Nhãn nhánh earnings sai.** Đang dùng ngày nộp hồ sơ, thiếu 26% số sự kiện một cách có
   hệ thống. Tín hiệu thật nhưng tập lệnh khi triển khai sẽ khác.
8. **Hàm chấm điểm là tham số tự do**, dao động kết quả gấp đôi.
9. **1.002 phiên nửa ngày không có giá thoát 15:55** và không ai ghi cách xử lý.

---

## 10. Trả lời ba câu hỏi đã đặt

**Có được phép mở rộng universe chưa?** — **Chưa, không phải theo cách đang định.** Mở rộng
để có thêm lệnh trên một quy trình đo đang hỏng thì chỉ nhân bản lỗi. Nhưng có một việc mở
rộng **phải làm trước**, vì lý do khác: dựng rổ theo thành phần tại từng thời điểm, gồm cả
những mã đã rời sàn. Đó không phải để tăng lợi nhuận mà để biết **rủi ro thật là bao nhiêu** —
và với một chiến lược bắt dao rơi thì đó là phép đo quan trọng nhất chưa ai làm.

**Có được phép nối vào engine chính chưa?** — **Chưa.** Nối vào engine là chuyển một con số
từ trạng thái "kết quả nghiên cứu" sang "cơ sở để đặt lệnh". Con số đó hiện không dựng lại
được, cao hơn trần của bản dựng lại 39%, và 40% của nó đến từ hai năm mà quy trình không thể
thua. Chưa đủ nền để nối.

**Hay phải sửa phép đo trước?** — **Đúng, và đây là việc duy nhất nên làm tiếp.** Theo thứ tự:

1. **Viết mô phỏng ra tệp và giữ nó lại**, kèm mô hình chi phí, hàm chấm điểm, cách xử lý
   phiên nửa ngày, và mã băm của kho dữ liệu. Không có bước này thì mọi vòng sau lặp lại đúng
   tình trạng hiện nay.
2. **Đóng băng rổ ứng viên bằng dữ liệu tới hết 2022, rồi mới chạy 2023-2024.** Bảy luật hiện
   tại không dùng lại được — chúng đã nhìn thấy đáp án. Phải sinh rổ mới từ giai đoạn huấn
   luyện.
3. **Dời điểm vào lệnh sang 09:35** cho mọi luật có điều kiện chạm tới giá mở cửa, và đo lại
   toàn bộ. Với nhóm panic thì giữ 09:30 được, nhưng nên ghi rõ là dùng lệnh khớp giá mở cửa.
4. **Dựng rổ theo thành phần lịch sử** rồi chạy lại. Đây là phép đo đắt nhất và có giá trị
   nhất còn lại.
5. **Thay danh sách ngày earnings** bằng lịch công bố kết quả thật.

Chỉ sau bốn bước đầu thì con số mới đáng đem ra so với bất kỳ ngưỡng nào.

---

## 11. Ba nhãn, giữ riêng

**Đã xác minh — tái lập được, có số của tôi:** cách chọn cổ phiếu của bảy luật; chuỗi luật mà
walk-forward chọn ra; lãi `$29.805` và trần không-chi-phí `$37.996`; lãi từng năm; suy giảm
theo điểm vào lệnh; bảy trên bảy luật dương ở kỳ kiểm; 62/62 mã sống sót; TSLA 46%; thanh
khoản 0,01%; vùng META không chạm lệnh nào; ngày earnings là ngày nộp hồ sơ và thiếu 26%.

**Thiếu bằng chứng — đọc thấy đường đi, chưa đo được:** vì sao bản gốc ra `$52.639`; độ lớn
của thiên lệch sống sót; cách bản gốc xử lý phiên nửa ngày.

**Chưa ai kiểm:** chuỗi giá ServiceNow; chiến lược này hoạt động thế nào trên cổ phiếu ngoài
rổ 62 mã; nhánh bán khống có vay được cổ phiếu để bán trong cơn hoảng loạn không.

---

## 12. Lệnh chạy lại

Mọi con số trong báo cáo này dựng từ kho bar 5 phút và tệp ngày earnings, bằng script trong
thư mục tạm của phiên. Chúng chạy dưới 30 giây mỗi cái. Nếu muốn giữ lại để chạy độc lập,
chép chúng vào một thư mục ngoài kho rồi chạy theo thứ tự: dựng bảng ngày từ bar 5 phút →
dựng đặc trưng có dịch → mô phỏng danh mục → walk-forward. Tôi không đặt chúng vào kho vì
hợp đồng của đợt rà là chỉ tạo đúng tệp báo cáo này.

Một điều tôi không tuyên bố: rằng tôi đã quét cạn. Ba vùng tôi đi qua thì mỗi vùng ra một
phát hiện, nên theo xác suất thuần, vùng thứ tư cũng có thể còn. Chỗ tôi biết là mình chưa
chạm tới: khả năng vay cổ phiếu để bán khống, cách xử lý phiên nửa ngày, và hành vi của
chiến lược ngoài rổ 62 mã.
