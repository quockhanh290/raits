# Review độc lập bản clean retest cổ phiếu

Ngày chạy: 2026-09-08, 03:0x ET (máy Calgary 01:0x MDT). Commit HEAD khi đo: `5e426cb`.

Hợp đồng đã giữ: chỉ đọc và chạy lại. Không sửa một dòng code nào, không commit, không xoá
gì, không mở vùng futures. Tệp duy nhất tôi tạo là báo cáo này; mọi output tôi sinh ra đều
ghi vào thư mục tạm ngoài kho, không đè lên các tệp `STOCKS_WFO_CLEAN_RETEST_*` của Codex.

Tài liệu này nối tiếp `STOCKS_CLAUDE_AUDIT_WFO_CANDIDATE_2026-09-08.md`.

---

## 0. Phán quyết

**PASS cho phép đo. WARN cho chiến lược.**

Đây là một sự đảo chiều so với đợt rà trước, và nó có cơ sở. Lần trước tôi phải viết rằng
con số công bố không tồn tại ở dạng dựng lại được. Lần này tôi chạy lại đúng hai lệnh đã
công bố và **mọi con số khớp tuyệt đối** — không phải "gần đúng", mà trùng tới từng đơn vị:

| Chỉ số | Codex công bố | Tôi chạy lại | |
|---|---:|---:|---|
| anchored N / lãi / PF / DD / CAGR | 252 · `$37.878` · 1,44 · `−$14.293` · 12,2% | 252 · `$37.878` · 1,44 · `−$14.293` · 12,2% | khớp |
| rolling3 N / lãi / PF / DD / CAGR | 198 · `$41.284` · 1,70 · `−$4.972` · 13,0% | 198 · `$41.284` · 1,70 · `−$4.972` · 13,0% | khớp |
| có PE, anchored | 220 · `$38.456` · 1,59 | 220 · `$38.456` · 1,59 | khớp |
| có PE, rolling3 | 122 · `$23.661` · 1,85 | 122 · `$23.661` · 1,85 | khớp |
| mã băm kho dữ liệu | `e9a2b100…` | `e9a2b100…` | khớp |
| chuỗi luật được chọn từng năm | — | trùng từng năm, cả hai chế độ | khớp |

Và sổ lệnh **tự nhất quán tuyệt đối**: tôi dựng lại từng dòng bằng công thức
`lãi = vốn trước lệnh × 40% × (tỉ suất − chi phí)`, sai số lớn nhất trên 198 lệnh là
**0,000000**. Sổ lệnh đủ để rà từng lệnh một; không có dòng nào không giải thích được.

**Bốn trong năm lỗi nghiêm trọng của đợt trước đã được sửa thật**, không phải sửa bằng lời.
Lỗi thứ năm — thiên lệch sống sót — chưa được sửa, và Codex nói thẳng là chưa, đúng như nó
đáng được nói.

**Nhưng phép đo sạch hơn lại cho thấy chiến lược mỏng hơn.** Đó là điều đáng lẽ phải xảy ra
khi bỏ các nguồn thổi phồng đi, và nó đã xảy ra đúng chiều. Con số `$41.284` không đến từ năm
năm giao dịch: **2020 gánh 63%, và riêng cửa sổ hoảng loạn COVID tháng 2 đến tháng 4/2020
gánh 46%**. Hai trong năm năm kiểm gần như không có mẫu — 2021 có **4 lệnh, ba trong số đó
rơi vào cùng một ngày**, còn 2023 có **5 lệnh**. Gọi đó là "walk-forward năm năm" là gọi rộng
hơn thứ dữ liệu cho phép.

Nhãn tôi đề nghị giữ cho hướng này: **research lead — nền đo đã tin được, bằng chứng thì
chưa.** Vẫn chưa phải chiến lược triển khai được.

---

## 1. Bảng điểm: audit cũ → trạng thái mới

| Lỗi đợt trước | Trạng thái | Bằng chứng đo được |
|---|---|---|
| Không có script, số không dựng lại được | **ĐÃ SỬA** | Chạy lại hai lệnh, mọi con số khớp tuyệt đối; script tự in cấu hình và mã băm dữ liệu vào cả màn hình lẫn báo cáo |
| Rổ ứng viên bị lọc bằng kết quả 2023-2024 | **ĐÃ SỬA** | Rổ 12 luật khai báo cứng trong mã, không có bước lọc nào. Cửa sổ huấn luyện là `năm−3 … năm−1` (cuốn chiếu) hoặc `2017 … năm−1` (neo gốc) — tôi đọc và xác nhận không có dữ liệu năm kiểm nào lọt vào phép chấm điểm |
| Luật gapdown quyết định bằng giá mở cửa rồi khớp ở chính giá đó | **ĐÃ SỬA** | Luật nào có điều kiện chạm tới giá mở cửa thì vào lệnh lúc 09:35; luật chỉ dùng thông tin hôm trước thì vào bằng lệnh khớp giá mở cửa. Trong 198 lệnh: 24 lệnh vào lúc 09:35, 174 lệnh vào bằng lệnh mở cửa — và cả 174 lệnh đó đều thuộc luật chỉ dùng dữ liệu hôm trước, tức đặt lệnh từ đêm được |
| Nhánh earnings dùng ngày nộp hồ sơ | **ĐÃ TÁCH NHÃN** | Mặc định **tắt**. Khi bật thì mang tên `PE_FILING_WARN` trong từng dòng sổ lệnh, và vào lệnh lúc 09:35 chứ không phải giá mở cửa |
| Phiên nửa ngày, mô hình chi phí, hàm chấm điểm không ghi ở đâu | **ĐÃ SỬA** | Cả ba là tham số dòng lệnh, in ra trong báo cáo. Chính sách phiên nửa ngày là bỏ qua, và số phiên bị bỏ được đếm ra: **1.170** |
| Số cũ 6.25-6.26 | **ĐÃ THAY THẾ RÕ** | Mục 6.27 nói thẳng số cũ bị thay thế, không dùng nữa |
| Thiên lệch sống sót | **CHƯA SỬA** | Rổ vẫn là 62 mã cố định, 62/62 có mặt từ phiên đầu tới phiên cuối. Codex ghi nhận và tự chặn việc mở rộng rổ — đúng, nhưng vấn đề còn nguyên |

---

## 2. Rà đúng từng điểm đã được yêu cầu

Tôi đọc hết đường tính, không đọc mô tả:

- **Mức sụt hôm trước** lấy giá mở cửa và giá 15:55 **đều đã dịch lùi một phiên**. Đúng.
- **Đà 20 ngày** tính trên chuỗi giá đóng **đã dịch lùi một phiên** rồi mới lùi tiếp 20 phiên,
  nên nó kết thúc ở phiên liền trước và không chạm ngày giao dịch. Đúng.
- **Điều kiện chỉ số thị trường** dựng từ chính bảng ngày của chỉ số, lấy mức sụt trong phiên
  **hôm trước**. Đúng.
- **Khoảng hở sáng nay** so giá mở cửa hôm nay với giá đóng hôm qua — cả hai biết lúc 09:30.
  Đúng, và luật dùng nó thì vào lệnh lúc 09:35.
- **Chọn top 3** xếp theo mức sụt hôm trước, không xếp theo bất kỳ đại lượng nào của ngày
  giao dịch. Đúng.
- **Chống trùng mã trong ngày** ưu tiên nhánh YDAY trước nhánh PE, và tôi kiểm sổ lệnh:
  **0 dòng trùng cặp ngày-mã**, và **không ngày nào quá 3 vị thế**. Đúng.
- **Chấm điểm chọn luật** chỉ nhận vào kết quả của các năm huấn luyện. Đúng.

Tôi không tìm thấy nhìn trộm tương lai nào ở tầng đặc trưng.

---

## 3. Chỗ phép đo sạch nhưng bằng chứng mỏng

Đây là phần quan trọng nhất của báo cáo, vì nó không phải lỗi của script — script đang nói
đúng sự thật, chỉ là sự thật mỏng hơn cái tiêu đề gợi ra.

### 3.1 Hai trong năm năm kiểm gần như không có mẫu

Toàn bộ năm 2021 của bản cuốn chiếu là bốn lệnh:

| Ngày | Mã | Tỉ suất | Lãi |
|---|---|---:|---:|
| 2021-12-02 | NOW | +3,88% | `$1.168` |
| 2021-12-02 | CRM | +3,43% | `$1.032` |
| 2021-12-02 | AMD | +2,03% | `$607` |
| 2021-12-17 | NVDA | −0,66% | `−$222` |

**Ba trong bốn lệnh nằm trên cùng một ngày.** Cả năm 2021 — với hệ số lời/lỗ 12,63 trông rất
đẹp trong bảng — thực chất là **một ngày giao dịch cộng một lệnh lẻ**. Năm 2023 là 5 lệnh
trải trên 5 ngày. Một hệ số lời/lỗ tính trên bốn quan sát không phải là một phép đo; nó là
một con số.

### 3.2 Kết quả dồn vào một cú sập

| Lát cắt | Lãi | Phần trăm |
|---|---:|---:|
| Toàn bộ cuốn chiếu 2020-2024 | `$41.284` | 100% |
| Riêng 2020 | `$26.032` | **63%** |
| Riêng cửa sổ COVID 15/02 – 30/04/2020 | `$19.036` | **46%** |
| Riêng TSLA (37 trên 198 lệnh) | `$17.610` | **43%** |
| 10 lệnh tốt nhất | — | **63%** |

Bỏ 2020 ra thì bốn năm còn lại cộng lại được `$15.252`. Lấy mẫu lại theo ngày:

| Tập | Xác suất lỗ | Phân vị 5% | Trung vị |
|---|---:|---:|---:|
| Nền, 124 ngày | 1,34% | `$9.905` | `$41.079` |
| Bỏ TSLA | 6,58% | **`−$2.375`** | `$23.579` |
| Bỏ 2020, còn 49 ngày | 4,20% | `$665` | `$15.035` |

Bỏ một mã ra là phân vị 5% xuống dưới không. Đây vẫn là cùng một hình dạng tôi đã mô tả đợt
trước, và bản clean retest **không làm nó nhẹ đi** — nó chỉ đo nó trung thực hơn.

### 3.3 Con số sụt vốn không bền theo hàm chấm điểm

Hàm chấm điểm giờ đã được khai báo — đó là bước tiến thật, và nó chữa đúng lỗi tôi nêu lần
trước. Nhưng khai báo một lựa chọn không làm cho lựa chọn ấy trở nên bền. Tôi thay hàm chấm
bằng bốn phương án đều hợp lý và giữ nguyên mọi thứ khác:

| Hàm chấm | Lãi | Hệ số lời/lỗ | Sụt vốn |
|---|---:|---:|---:|
| Bản đã công bố | `$41.284` | 1,70 | `−$4.972` |
| Chỉ theo hệ số lời/lỗ | `$36.389` | 2,67 | `−$3.892` |
| Chỉ theo lãi | `$50.815` | 1,51 | `−$15.330` |
| Lãi trên sụt vốn | `$42.663` | 1,53 | `−$14.293` |
| Lãi, lời/lỗ, phạt sụt vốn nặng hơn | `$56.759` | 1,63 | `−$16.468` |

Lãi dao động **1,6 lần**; **sụt vốn dao động 4,2 lần**. Ba trong bốn phương án thay thế cho
sụt vốn quanh `−$14.000` đến `−$16.000`, không phải `−$5.000`.

Bản đã công bố **không phải là bản đẹp nhất** — phương án chỉ-theo-hệ-số cho sụt vốn thấp hơn
nữa — nên tôi không có cơ sở nói hàm chấm bị chọn để lấy con số đẹp. Nhưng kết luận vận hành
thì rõ: **`−$4.972` là con số của một hàm chấm cụ thể, không phải đặc tính của chiến lược.**
Khi báo cáo, con số sụt vốn phải đi kèm dải `−$4.000` đến `−$16.500`, nếu không người đọc sau
sẽ dùng `−$5.000` để đặt hạn mức rủi ro.

---

## 4. Các phát hiện mới, xếp theo mức nghiêm trọng

**Trung bình**

1. **Sụt vốn công bố không bền theo hàm chấm điểm** — dao động 4,2 lần. Xem 3.3. Nên công bố
   kèm dải, không công bố một số.
2. **Hai năm kiểm có mẫu gần bằng không** (4 lệnh và 5 lệnh), và cổng chặn mẫu nhỏ hiện chỉ
   áp cho giai đoạn huấn luyện, không áp cho giai đoạn kiểm. Hệ quả là bảng kết quả in ra
   những hệ số lời/lỗ như 12,63 và 8,31 trông như bằng chứng mạnh, trong khi chúng đứng trên
   bốn và năm quan sát. Nên in thẳng cảnh báo mẫu mỏng cạnh những dòng đó.
3. **Tập trung vẫn nặng**: 2020 gánh 63%, TSLA gánh 43%, mười lệnh tốt nhất gánh 63%, và
   phân vị 5% âm khi bỏ TSLA.

**Thấp**

4. **Bản chạy chi phí bằng không đang trả lời sai câu hỏi.** Nó **chọn lại luật**, nên
   `$40.576` không so được với `$41.284`. Giữ nguyên chuỗi luật đã chọn ở mức 4 điểm cơ bản
   rồi hạ chi phí về không thì được **`$44.202`** — tức chi phí thật sự ăn mất **`$2.918`**.
   Đó mới là con số trả lời "chi phí đáng bao nhiêu". Cách trình bày hiện tại dễ bị đọc thành
   "chi phí không quan trọng", thậm chí "bỏ chi phí thì tệ hơn", cả hai đều sai.

   Nói thêm cho công bằng: tôi đã quét chi phí từ 0 đến 15 điểm cơ bản, và **từ 1 điểm trở lên
   chuỗi luật hoàn toàn ổn định**, lãi giảm đều từ `$43.464` xuống `$33.715`, sụt vốn giữ
   quanh `−$5.000`. Hiện tượng lật luật chỉ xảy ra **đúng tại điểm không**. Đây là một chỗ lồi
   ở rìa, không phải bất ổn định chung — nhẹ hơn nhiều so với mức tôi nghi ban đầu.

5. **Danh sách loại quỹ ETF thiếu vàng.** Kho có 13 quỹ, danh sách loại trừ chỉ bắt 12 — sót
   quỹ vàng, nên rổ "cổ phiếu" thành 63 mã thay vì 62. Đây chính là lý do báo cáo ghi 63.
   **Ảnh hưởng đo được: bằng không** — quỹ vàng chưa bao giờ sụt đủ 4% trong một phiên nên
   không sinh tín hiệu nào; tôi kiểm cả ba tệp sổ lệnh, **0 lệnh**. Vẫn nên sửa, vì nó là một
   con số sai trong dòng cấu hình mà người sau sẽ đọc.

6. **Tỉ suất kép tính trên khoảng từ lệnh đầu tới lệnh cuối**, tức 4,91 năm, chứ không phải
   trọn kỳ kiểm 5 năm. Thổi lên khoảng 0,2 điểm phần trăm: `13,0%` thay vì `12,8%`. Nhỏ, nhưng
   là loại sai lệch chỉ đi một chiều.

7. **Bỏ phiên nửa ngày làm đặc trưng "hôm trước" thỉnh thoảng nhảy qua hai phiên.** Khi một
   phiên bị bỏ, dòng liền trước trong bảng là phiên trước nữa, nên "mức sụt hôm trước" và
   "khoảng hở" thực ra bắc qua hai phiên. Xảy ra ở **0,63% số dòng**, và trong 198 lệnh của
   kết quả cuối chỉ **1 lệnh** dính. Cơ chế có thật, ảnh hưởng gần bằng không.

**Ghi nhận, không phải lỗi**

8. **Bộ lọc nhiễu có điều kiện trên chính kết quả cùng ngày.** Về nguyên tắc đó là lọc mẫu
   theo kết quả. Tôi đo: nó loại **28 dòng mà không bộ lọc nào khác bắt được, cả 28 đều là
   META** trong đúng vùng hỏng đã biết, và trong đó chỉ **2 dòng** lẽ ra thành tín hiệu. Nó
   đang làm đúng việc của nó, phạm vi ảnh hưởng đã chặn được. Chấp nhận, nhưng nên ghi vào
   tài liệu là lọc theo kết quả có chủ đích, kèm con số 28/2.

9. **Rổ 12 luật là hàng khai báo, nhưng bốn luật trong đó là người sống sót của vòng cũ.**
   Tám luật kia (`raw_` và `gapdown_` ở bốn ngưỡng) là một lưới đối xứng, sinh ra một cách hệ
   thống — rất tốt. Bốn luật còn lại được mang sang từ vòng đã nhiễm. Không định lượng được,
   nhưng đáng ghi. Điểm làm nhẹ lo ngại này: kết quả cuối **chủ yếu chọn các luật thuộc lưới
   hệ thống** (`raw_-5`, `raw_-7`, `gapdown_-5`), chỉ một năm chọn luật kế thừa.

---

## 5. Trả lời các câu hỏi đã đặt

**Có dùng được clean retest làm nền đo mới không?** — **Có.** Đây là phép đo đầu tiên của
hướng cổ phiếu trong loạt này mà tôi dựng lại được nguyên vẹn từ một lệnh, với cấu hình tự
ghi và sổ lệnh tự nhất quán tới sáu chữ số thập phân. Nó nên trở thành mốc so, và mọi con số
cũ của 6.24-6.26 nên coi như đã chết. Bốn sửa nhỏ ở mục 4 không làm hỏng kết luận nào.

**Có được mở rộng universe chưa?** — **Chưa, và giờ đây đó là chốt chặn duy nhất còn lại.**
Mọi lỗi đo lường khác đã sửa; thứ còn đứng là rổ 62 mã đều sống tới cuối. Với một chiến lược
**mua cổ phiếu vừa sập**, một rổ mà 62/62 mã đều sống sót là rổ đã bỏ sẵn những cái tên sập
rồi không dậy nữa. Mở rộng rổ mà chưa dựng theo thành phần lịch sử thì chỉ nhân bản thiên
lệch lên. Việc đúng là **dựng rổ theo thành phần tại từng thời điểm, gồm cả mã đã rời sàn**,
rồi chạy lại đúng script này. Codex tự chặn ở đúng chỗ này — tôi đồng ý với chỗ dừng đó.

**Có cần sửa script trước không?** — **Không bắt buộc trước khi dùng làm nền đo.** Bốn sửa
nhỏ nên làm khi tiện, không cái nào đổi kết luận: thêm quỹ vàng vào danh sách loại trừ; tính
tỉ suất kép trên trọn kỳ kiểm thay vì khoảng có lệnh; đổi cách trình bày bản chi phí bằng
không thành "giữ nguyên luật đã chọn, hạ chi phí"; và in cảnh báo mẫu mỏng cho những năm dưới
khoảng 20 lệnh. Việc **nên** làm thêm — và nó là việc đo, không phải sửa lỗi — là in kèm dải
sụt vốn theo vài hàm chấm điểm, để `−$4.972` không bị đọc như một hằng số.

**Có nên giữ script trong kho không?** — **Có, giữ nguyên chỗ hiện tại.** Nó đang nằm trong
một thư mục nghiên cứu riêng, không nằm trên đường chạy sản xuất, và không import gì từ engine
nên không kéo theo phụ thuộc. Đúng bài học đắt nhất của kho này là một con số được công bố mà
không ai dựng lại được; script này chính là thứ chặn việc đó tái diễn. Thời gian chạy khoảng
hai phút, phần lớn nằm ở khâu dựng bảng ngày từ bar 5 phút — chấp nhận được, chưa cần tối ưu.
Nếu sau này chạy nhiều cấu hình liên tiếp thì nên lưu bảng ngày ra đĩa một lần rồi dùng lại;
tôi đã làm đúng thế khi rà và nó đưa mỗi lượt xuống dưới một giây.

**Hướng YDAY panic/rebound nên giữ nhãn gì?** — **`research lead`, và nên nói rõ hơn nữa là
lead dựa chủ yếu trên một cú sập.** Nhãn "chưa đạt máy in tiền" của Codex đúng nhưng còn nhẹ.
Phát biểu chính xác hơn: *tín hiệu bật nảy sau hoảng loạn tồn tại và đã được đo bằng một quy
trình không còn nhìn trộm; nhưng bằng chứng ngoài mẫu hiện có là một cú sập lớn năm 2020 cộng
hai năm chỉ có bốn và năm lệnh, và gần một nửa lợi nhuận đến từ một cổ phiếu.* Đó vẫn là
thiếu bằng chứng, không phải bằng chứng phủ định — và cách rẻ nhất để chuyển nó sang một
trong hai phía là rổ theo thành phần lịch sử, không phải thêm bộ lọc.

**Nối vào engine?** — **Chưa.** Nền đo đã đủ tin để tiếp tục nghiên cứu; nó chưa đủ mẫu để
đặt lệnh.

---

## 6. Ba nhãn, giữ riêng

**Đã xác minh — tôi chạy lại và có số:** cả bốn bộ kết quả công bố khớp tuyệt đối; mã băm dữ
liệu khớp; chuỗi luật từng năm khớp; sổ lệnh tự nhất quán sai số 0,000000; sụt vốn và tỉ suất
kép dựng lại được từ sổ lệnh; 24/198 lệnh vào lúc 09:35 và 174 lệnh còn lại đều thuộc luật
chỉ dùng dữ liệu hôm trước; 0 dòng trùng, 0 ngày quá 3 vị thế; 2020 gánh 63%, COVID gánh 46%,
TSLA gánh 43%; dải sụt vốn theo hàm chấm `−$3.892` đến `−$16.468`; chi phí thật ăn `$2.918`;
chuỗi luật ổn định từ 1 đến 15 điểm cơ bản; quỹ vàng lọt rổ nhưng 0 lệnh; 1/198 lệnh dính
đặc trưng bắc hai phiên; bộ lọc theo kết quả loại 28 dòng META, 2 dòng lẽ ra thành tín hiệu.

**Thiếu bằng chứng — thấy đường đi, chưa đo:** độ lớn của thiên lệch sống sót; mức độ bốn luật
kế thừa từ vòng cũ còn mang hậu nghiệm.

**Chưa ai kiểm:** hành vi của chiến lược trên cổ phiếu ngoài rổ 62 mã; khả năng vay cổ phiếu
cho nhánh bán khống; trượt giá thật của lệnh khớp giá mở cửa trong phiên hoảng loạn — bản
hiện tại giả định một mức phí phẳng 4 điểm cơ bản cho mọi lệnh, kể cả ngày thị trường sập.

---

## 7. Lệnh chạy lại

```powershell
python raits\research\stocks_wfo_clean_retest.py
python raits\research\stocks_wfo_clean_retest.py --include-pe --output-md <md> --trades-csv <csv>
```

Khoảng hai phút mỗi lệnh. Khi rà tôi ghi output vào thư mục tạm để không đè lên tệp của
Codex; muốn so thì trỏ `--output-md` và `--trades-csv` sang chỗ khác rồi so bằng tay.

Tôi không tuyên bố đã quét cạn. Vùng tôi biết mình chưa chạm: hành vi ngoài rổ hiện tại, chi
phí thực thi trong ngày sập, và câu hỏi vay cổ phiếu.
