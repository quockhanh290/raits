# Rà soát độc lập — hướng RAITS cổ phiếu

_Ngày chạy: 2026-08-17 (giờ máy Calgary, MDT). Commit HEAD: `3cafcaa`._
_Hợp đồng: CHỈ ĐỌC. Không sửa mã, không sửa cấu hình, không chạy backtest mới,
không commit. Mọi con số dưới đây đo lại từ artifact trên đĩa, không chép lại từ tài liệu cũ._

---

## 0. Câu hỏi được đặt ra

Hệ cổ phiếu có còn đáng đi tiếp không, và hiện nó đang đứng ở đâu?

Trả lời ngắn: **hệ cổ phiếu đã đứng yên 5,5 tuần, và bằng chứng mà nó đang dựa vào yếu hơn
tài liệu đang mô tả.** Không phải vì có ai làm hỏng — mà vì ba con số vẫn được gọi chung là
"baseline in-sample" thật ra do **ba cấu hình khác nhau của cùng một engine** sinh ra, và
cái duy nhất được đem đi kiểm định thống kê lại là cái **không phải cấu hình sản xuất**.

---

## 1. Nền đo

| Thứ đo | Giá trị | Cách đo |
|---|---|---|
| Commit | `3cafcaa` | `git rev-parse` |
| Ảnh chụp kết quả cổ phiếu còn trên đĩa | **đúng 1 tệp** (07/07/2026) | quét toàn kho tìm `results_*.pkl` |
| Mã engine cổ phiếu sửa lần cuối | **10/07/2026** | mtime toàn bộ mã gói cổ phiếu, trừ thư mục nghiên cứu |
| Dữ liệu 5 phút cổ phiếu | 117.533 tệp, 75 mã, phủ **2017-01-03 → 2022-12-30** (1.510 phiên) | đếm tệp + đọc mốc thời gian 300 tệp ngẫu nhiên |
| Dữ liệu 5 phút cho 2023-2024 | **1,3% số tệp** (4/300 mẫu) — chỉ những ngày đã cần đến | cùng phép đo trên |
| Dữ liệu 2025 | **không có dòng nào** — mọi tệp dữ liệu ngày kết thúc 2024-12-31 | liệt kê 38 tệp dữ liệu ngày |
| Dữ liệu 1 phút mua tháng 8 | 1,9 GB, 5 sàn, 314 mã, 2023-03-28 → 2026-07-31 | `du` + tiêu đề báo cáo |
| Việc chạy theo lịch mỗi ngày | **100% là futures** — không có việc nào của cổ phiếu | liệt kê job trong bộ lập lịch |
| Bộ chạy live cổ phiếu | có mã, sửa lần cuối 05/07, **chưa từng được gắn lịch** | mtime + không xuất hiện trong bộ lập lịch |

Tự kiểm: tổng lãi lỗ tôi tính lại từ ảnh chụp ra **$33.550,18**; một ghi chú độc lập trong
sổ tay dự án (viết hồi tháng 8 cho việc khác) cũng ghi `$33.550`. Hai đường độc lập khớp,
nên phép đọc ảnh chụp của tôi đáng tin. Tương tự, nền so sánh 605 lệnh tôi đọc ra
$15.019,79 — khớp đúng con số $15.020 trong báo cáo bootstrap tháng 7.

---

## 2. Phát hiện chính — ba "baseline" là ba hệ khác nhau

Đây là chỗ quan trọng nhất của cả đợt rà soát. Ba con số vẫn được nhắc tới như thể cùng
một hệ, thật ra khác nhau ở **luật vào lệnh**, không chỉ ở khoảng thời gian.

| | Ảnh chụp 07/07 | Nền so sánh sau khi sửa phanh | Kiểm ngoài mẫu 2023-2024 |
|---|---|---|---|
| Cách chạy | **từng năm một**, mỗi năm đặt lại $50k | **một mạch 6 năm** | một mạch 2 năm |
| Bộ quét chọn mã | **BẬT** (top 15) | **TẮT** — chỉ 37 mã cố định | **BẬT** |
| Luật chặn day-trade (PDT) | **TẮT** | **BẬT** | **TẮT** |
| Số lệnh | 1.292 | 605 | 430 |
| Số lệnh mỗi năm | 215 | 101 | 215 |
| Lãi lỗ | +$33.550 | +$15.020 | +$6.666 |
| Lợi nhuận năm | ~11%/năm *(không cộng dồn — xem dưới)* | **4,49%/năm** | ~6,4%/năm |
| Calmar | — | **0,76** | 0,96 |

Ba điều rút ra, cả ba đều **đã xác minh bằng phép đo**:

**(a) Con số $33.550 không phải là con số triển khai được.** Mỗi năm trong ảnh chụp đó bắt
đầu lại ở đúng $50.000 — tôi kiểm bằng cách chia: lãi lỗ mỗi năm chia cho 50.000 ra đúng
bằng cột "lợi nhuận" đã lưu, tới từng chữ số. Nghĩa là thua lỗ năm trước **không** làm nhỏ
vốn năm sau, và lãi năm trước cũng không được tái đầu tư. Đó là số để so sánh chiến lược,
không phải số để kỳ vọng.

**(b) Toàn bộ kết luận "chiến lược nào có edge" được đo trên cột giữa — cột duy nhất không
phải cấu hình sản xuất.** Cột giữa tắt bộ quét chọn mã và bật luật chặn day-trade; hai cột
kia thì ngược lại. Đợt kiểm định bootstrap tháng 7 kết luận *"bộ có edge triển khai được =
TREND_FOLLOW + PE_SHORT"* và *"ORB / STRESS_ORB / STRESS_MID không có edge"* — tất cả chạy
trên cột giữa. Tài liệu giải thích những cú lật verdict đó là do "đổi cách chạy: từng năm
so với liên tục". Nhưng phép đo cho thấy **còn ít nhất hai thứ khác cùng đổi**: bộ quét và
luật PDT. Ba nguyên nhân chồng lên nhau, chưa ai tách ra.

Cùng chỗ này còn một chi tiết đáng chú ý: danh sách mã của nền so sánh đó chỉ có 37 tên, và
**không bao gồm nhóm 25 mã mở rộng vốn là nơi chiến lược PE_SHORT lấy tín hiệu**. PE_SHORT
lại chính là chiến lược đóng góp 48% kết quả của nền đó.

**(c) Chưa từng tồn tại một con số nào vừa đúng cấu hình sản xuất, vừa chạy liên tục nhiều
năm trong mẫu.** Cái gần nhất là kiểm ngoài mẫu 2 năm: **+$6.666**.

---

## 3. Bằng chứng ngoài mẫu thực sự nói gì

Đợt kiểm 2023-2024 (chạy 08/07) kết luận **"HOLDS"**. Đọc kỹ chính báo cáo đó thì:

- Bỏ **5 lệnh** lãi nhất trong tổng số 430 lệnh → còn lại **$261** trên $6.666.
  Tức **96% kết quả nằm ở 1,2% số lệnh.** Mục kết luận của báo cáo không nhắc tới mục
  jackknife nằm ngay phía trên nó.
- Kiểm định lại theo bội số rủi ro: TREND_FOLLOW p=0,108 · PE_SHORT p=0,185 · phần còn lại
  p≥0,2. **Không chiến lược nào đạt ngưỡng ngoài mẫu.**
- Ba chiến lược ORB / STRESS_ORB / STRESS_MID cộng lại **−$1.529** ngoài mẫu, đúng như
  trong mẫu đã cảnh báo.

Nhãn đúng cho trạng thái này là **"thiếu bằng chứng"**, không phải "không có edge" và cũng
không phải "đã xác nhận". Nhưng tài liệu trạng thái đang ghi *"Live-ready. Edge hẹp."* —
viết ngày 06/07, tức **trước** cả đợt bootstrap 08/07 lẫn đợt kiểm ngoài mẫu 09/07, và
chưa được cập nhật lần nào kể từ đó.

Một chi tiết đi kèm: ảnh chụp mà tài liệu trạng thái trích dẫn làm "baseline đã khoá"
**không còn trên đĩa**. Không tái tạo được, nên không đối chiếu được. Cùng họ với bài học
"đóng băng con số mà không đóng băng thước đo".

Còn một mâu thuẫn chưa giải quyết được: hai tài liệu viết cùng tuần mô tả **cùng một tên
tệp ảnh chụp** theo hai cách khác nhau — một bên nói đó là 604 lệnh trên tập dữ liệu rút
gọn, một bên nói đó là baseline đầy đủ +$34.214. Tệp đã mất nên **không phân xử được bằng
đo**; ghi lại đây như một khoảng trống, không phải một lỗi.

---

## 4. Đợt nghiên cứu tháng 8 — sáu phép sàng, kết quả

Từ 09/08 đến 11/08 có sáu phép sàng tìm nguồn edge mới cho cổ phiếu. Tôi đọc lại từng báo
cáo và đối chiếu với **tiêu chí loại mà chính nó cam kết trước**:

| Ý tưởng | Kết quả đo được | Kết luận |
|---|---|---|
| Chờ giá quay lại kiểm định biên rồi mới vào (thay vì vào ngay lúc phá) | Kém hơn luật hiện tại ở **cả 6 ô tham số**, −0,118R đến −0,141R, xác suất "không tệ hơn" = 0,000. Càng nới cửa sổ càng tệ | **CHẾT** — và chết theo hướng khẳng định luật hiện tại đúng |
| Bám đà theo đường trung bình trong ngày | Biên độ thuận và nghịch bằng nhau tới chữ số thứ hai (0,327 vs −0,331). Lãi ròng ~0 | **CHẾT** — khuếch tán, không có hướng |
| Phá vùng nén sát đỉnh ngày (dữ liệu 1 phút mới mua) | Lãi gộp **1,15 điểm cơ bản**; chi phí khứ hồi 4 điểm cơ bản | **CHẾT** — chi phí gấp 3,5 lần biên |
| Trôi giá sau khi phá đỉnh ngày | Không có mốc thời gian nào vượt nổi 4 điểm cơ bản; tới cuối ngày âm | **CHẾT** |
| Sức mạnh tương đối chéo mã trong ngày | Chênh lệch nhóm đầu–nhóm cuối ±2 điểm cơ bản, khoảng tin cậy cắt qua 0 | **CHẾT** |
| Đảo chiều sau khoảng nhảy giá qua đêm | **Tín hiệu có thật và mạnh** tại giá mở cửa: −9,57 điểm cơ bản, xác suất sai 0,000. Nhưng vào lệnh lúc 09:35 thì còn **+1,05 và cắt qua 0** — mất **10,6 điểm cơ bản trong 5 phút đầu** | **CÓ THẬT NHƯNG KHÔNG VỚI TỚI** |

Ô cuối cùng là kết quả đáng giá nhất của cả đợt, và nó không phải tin xấu về ý tưởng — nó
là tin xấu về **nhịp chạy của hệ**: hệ này quyết định theo chu kỳ 5 phút, mà toàn bộ biên
nằm trong 5 phút đầu phiên. Cùng một cơ chế đã giết đề tài order-flow hồi đầu tháng 8.

Hai ghi chú về phương pháp của chính đợt này:

- **Tiêu chí loại "xác suất chạm +1R trước −1R ≤ 50% là trượt" bị đặt sai.** Trong cửa sổ
  15 phút, phần lớn đường giá **không chạm mốc nào**, nên chỉ số này gần như không bao giờ
  vượt 50% dù chiến lược tốt hay xấu. May là kết luận không phụ thuộc vào nó: bằng chứng
  giết các ý tưởng này là biên độ thuận ≈ biên độ nghịch và lãi ròng ≈ 0, hai thứ đo trực
  tiếp. Nhưng tiêu chí này không nên dùng lại.
- **Phép đếm phễu ngày 09/08 nói mẫu chỉ còn ~78-96 lệnh nếu giữ đúng các cổng của engine**
  (chỉ chế độ Normal, VIX<25, xu hướng SPY), và khuyên "thu hẹp đề bài trước khi mua dữ
  liệu". Sáng hôm sau dữ liệu được mua (~$38) và phép kiểm chạy trên **785-1.379 lệnh** —
  đạt được cỡ mẫu đó bằng cách **bỏ các cổng của engine**. Kết luận âm mạnh tới mức khả
  năng đảo chiều rất thấp, nên tôi không coi đây là lỗi kết luận; nhưng cần ghi rõ: **phép
  kiểm đã chạy không phải phép kiểm mà phễu đã hiệu chỉnh cỡ mẫu cho.**

Và một điểm về lưu vết: toàn bộ đợt này — mã, báo cáo, dữ liệu mua — **không có dòng nào
trong nhật ký công việc chung**, mã chưa vào kho, bảy tệp báo cáo nằm rời ở thư mục gốc.
Sáu kết luận âm là tài sản: chúng đóng sáu hướng. Ở dạng hiện tại chúng sẽ mất khi ai đó
dọn thư mục.

---

## 5. Cặp chạy song song chưa được đối soát

| Cặp | Tình trạng |
|---|---|
| Cấu hình sinh baseline trong mẫu vs cấu hình sinh kết quả ngoài mẫu | **Chưa đối soát** — khác nhau ở bộ quét, luật PDT, cách chạy. Đây là mục 2 |
| Bộ chạy giấy cổ phiếu vs engine backtest | Đã đối soát **một lần** hồi tháng 6/7 trên tập rút gọn 604 lệnh, engine **trước** bản sửa phanh. Chưa lặp lại trên engine hiện tại |
| Mô hình chế độ của cổ phiếu vs của futures | Hai hệ, hai cách hiệu chỉnh giá SPY (một bên chỉ điều chỉnh chia tách, một bên có cả cổ tức). Đã ghi nhận từ tháng 7, **chưa ai đo** ảnh hưởng — ước ~24 ngày chia cổ tức mỗi năm có thể bị gán nhãn sai |
| Kết quả 5 phút vs 1 phút của cùng một hiện tượng | Báo cáo tự nói "mức độ không so sánh được"; chỉ hình dạng đường trôi là dùng chung được. Đây là xử lý **đúng**, ghi lại để khỏi ai gộp nhầm về sau |

---

## 6. Quyết định đã ra nhưng không có chỗ nào ghi vì sao

- Vì sao nền so sánh trong mẫu lại tắt bộ quét chọn mã và bật luật PDT, trong khi cả bản
  kiểm quyết định lẫn kiểm ngoài mẫu đều làm ngược lại? Không có ghi chú nào.
- Vì sao danh sách mã của nền so sánh đó chỉ có 37 tên, bỏ hẳn nhóm 25 mã mở rộng vốn là
  nơi chiến lược PE_SHORT lấy tín hiệu? Không có ghi chú nào.
- Ngưỡng "1% rủi ro mỗi lệnh" trong nền đó so với "1,5%" ở nơi khác — không có ghi chú.
- Bộ tham số đã niêm phong từ 01/07 được chốt trên engine **trước** ba lần sửa sau đó. Tài
  liệu ghi rõ "phải chạy lại tối ưu hoá cuốn chiếu", và việc đó **chưa chạy**.

---

## 7. Muốn chạy được phép thử quyết định (Vault 2025) thì còn thiếu gì

| Chặn | Trạng thái đo được | Ghi chú |
|---|---|---|
| Dữ liệu 2025 | **Không có** — dữ liệu ngày dừng ở 2024-12-31, dữ liệu 5 phút hầu như chỉ tới 2022 | Phải tải mới. **Ước lượng, chưa đo**: ~75 mã × ~250 phiên; theo nhịp gọi đang cấu hình thì cỡ vài giờ |
| Tối ưu hoá cuốn chiếu | Bản mới nhất là **25/06**, trước mọi bản sửa engine | Tài liệu tự đánh dấu là cũ |
| Ảnh chụp nền trước OOS | Ảnh gần nhất 07/07, và nó là bản chạy từng-năm-một | Cần một bản chạy liên tục đúng cấu hình sản xuất |
| Cổng đóng băng lại mô hình chế độ | **Chưa có** với cổ phiếu (futures đã có đủ) | Sẽ thành gánh nặng ngay khi chạy tiền thật |
| Lưu trạng thái khi khởi động lại | **Chỉ nằm trong bộ nhớ** — restart là mất vốn đỉnh và vị thế | Chặn cứng trước live |

Bốn mục dưới cùng đã nằm trong danh sách "chờ xử lý" từ **06/07** và không mục nào nhúc nhích.

---

## 8. So với hướng futures — cùng $50.000, cùng số năm

Đây là phép so sánh quyết định, nên tôi cắt về **đúng cùng khoảng 2018-2022** thay vì so
hai bảng có sẵn:

| | Cổ phiếu (chạy liên tục) | Futures (mô phỏng triển khai, trượt giá 2 tick) |
|---|---|---|
| 2018-2022, tổng | **+$13.509** | **+$38.100** |
| Calmar | 0,76 | 2,74 |
| Sharpe | 0,93 | 2,04 |
| Ngoài mẫu 2023-2024 | +$6.666 · Calmar 0,96 | +$14.144 · Calmar 3,33 |
| Ngoài mẫu 2025 | **chưa chạy được** (thiếu dữ liệu) | +$6.754 · Calmar 2,99 |
| Đang chạy thật (giấy) | không | có, mỗi ngày |

Hai điều cần nói rõ để bảng này không bị đọc quá tay:

1. Cột cổ phiếu là cấu hình **tắt bộ quét** — tức nhiều khả năng thấp hơn cấu hình sản xuất.
   Nhưng con số đúng cấu hình sản xuất, chạy liên tục, **không tồn tại**, nên không có gì
   để thay vào. Đó chính là phát hiện, không phải chỗ để ước lượng bù.
2. Đường lãi của cổ phiếu **teo dần trong chính mẫu**: 2019 +$7.214 → 2020 +$484 →
   2021 +$1.434 → 2022 −$30. **Ba năm cuối của giai đoạn trong mẫu cộng lại là $1.888.**
   Cùng ba năm đó futures làm $28.735. Chưa có ai giải thích vì sao — và đây là câu hỏi
   nặng hơn mọi phép kiểm định thống kê ở trên.

---

## 9. Kết luận

Về câu hỏi "hướng cổ phiếu có đáng đi tiếp không":

- **Không có bằng chứng nào nói hệ cổ phiếu hỏng.** Nó vẫn dương ở cả trong mẫu lẫn ngoài mẫu.
- **Cũng không có bằng chứng nào đủ để đưa nó vào tiền thật.** Không chiến lược nào đạt
  ngưỡng ngoài mẫu; 96% kết quả ngoài mẫu nằm ở 5 lệnh; ba năm gần cuối gần như bằng phẳng;
  và bộ verdict đang được trích dẫn thì đo trên một cấu hình không phải cấu hình sản xuất.
- **Sáu hướng tìm edge mới trong tháng 8 đều âm**, trong đó cái duy nhất có tín hiệu thật
  lại nằm ngoài tầm với của nhịp 5 phút mà hệ đang chạy.
- Trong khi đó hướng futures **đã qua hai cửa OOS độc lập và đang chạy giấy mỗi ngày**.

Ba lựa chọn, kèm cổng kiểm — không lựa chọn nào cần đụng vào futures:

**A. Đóng băng có kỷ luật (rẻ nhất, ~1 buổi).** Không chạy gì thêm. Chỉ ghi lại: đưa sáu
kết luận âm tháng 8 vào sổ, sửa tài liệu trạng thái cho khớp bằng chứng 08-09/07, ghi rõ ba
cấu hình khác nhau ở mục 2 để lần sau không ai đọc nhầm baseline. Chi phí gần bằng 0, và nó
chặn cái tốn kém nhất: sáu tháng nữa có người đọc "Live-ready. Edge hẹp." rồi tin theo.

**B. Trả lời đúng MỘT câu hỏi rồi mới quyết (~1 ngày chạy máy).** Chạy **một** lần duy nhất:
liên tục 2017-2022, **đúng cấu hình sản xuất** (bộ quét bật, PDT tắt, rủi ro 1,5%). Cam kết
ngưỡng **trước khi nhìn kết quả**. Đó là con số đang thiếu, và nó vừa cho biết edge thật là
bao nhiêu, vừa cho biết ba nguyên nhân chồng nhau ở mục 2 đóng góp thế nào. Cấm sửa tham số
sau khi nhìn kết quả — nếu không thì phép thử 2025 mất tính sạch.

**C. Đi thẳng tới Vault 2025.** Chỉ nên làm **sau** B, và cần tải dữ liệu 2025 + chạy lại
tối ưu hoá cuốn chiếu trước. Nếu làm khi baseline còn mơ hồ như hiện nay thì dù kết quả ra
sao cũng không phân xử được điều gì — không biết đang kiểm hệ nào.

Tôi nghiêng về **A + B**: chốt lại hồ sơ, rồi bỏ đúng một ngày máy để có con số còn thiếu.
C thì chưa, vì phép thử một-lần-duy-nhất chỉ đáng tiêu khi biết rõ mình đang thử cái gì.

---

## 10. Điều tôi CHƯA kiểm trong đợt này

Ghi ra để không ai đọc bản này như một bản quét cạn:

- Chưa đọc mã engine cổ phiếu theo tuần tự — chỉ đọc cấu hình lưu trong artifact và các
  đường dẫn liên quan tới câu hỏi trên.
- Chưa chạy lại phép kiểm định bootstrap nào; mọi p-value ở đây trích từ báo cáo tháng 7,
  và giá trị của chúng phụ thuộc vào phát hiện ở mục 2.
- Chưa xác minh tuyên bố "engine cổ phiếu và futures độc lập hoàn toàn" bằng cách rà tham
  chiếu chéo.
- Chưa mở bộ kiểm tự động của phần cổ phiếu — không biết nó còn xanh hay không.
- Ảnh hưởng của cách hiệu chỉnh giá SPY lên nhãn chế độ của cổ phiếu vẫn **chưa ai đo**,
  đúng như tài liệu tháng 7 đã ghi.

---

## Phụ lục — lệnh tái lập các phép đo chính

```powershell
cd d:\raits

# ba baseline, ba cấu hình  (đọc config lưu NGAY TRONG artifact, không đọc mặc định CLI)
python -c "import pickle;r=pickle.load(open(r'raits\data\cache\verify_cb_fixed_baseline.pkl','rb'));print(r.metrics);print(r.config)"

# ảnh chụp từng-năm-một: mỗi năm reset $50k
python -c "import pickle;d=pickle.load(open(r'raits\data\cache\snapshots\results_20260707_110323.pkl','rb'));[print(w['label'],w['stats']) for w in d]"

# phủ dữ liệu 5 phút
dir raits\data\cache\daily
```

Các báo cáo tháng 8 nằm ở thư mục gốc: `funnel_report.txt`, `orb_retest_report.txt`,
`ema_scalp_report.txt`, `hod_cons_1min.txt`, `hod_cons_5min.txt`, `hod_fwd_report.txt`,
`xs_rs_report.txt`, `gap_report.txt`. Mã sinh ra chúng ở `raits\raits\scripts\research\`.
