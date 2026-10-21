# Mở lại hướng cổ phiếu — dựng lại nền đo

_Ngày chạy: 2026-09-07 (giờ máy Calgary, MDT). Commit HEAD: `62332c3`._
_Đối chiếu với `STOCKS_AUDIT_2026-08-17.md` (commit `3cafcaa`), cách nhau 21 ngày._
_Hợp đồng: CHỈ ĐỌC với mã và cấu hình. Không sửa engine, không sửa tham số, không commit,_
_không chạm futures. Có hai lượt chạy thử ngắn — khai báo ở mục 9._

---

## 0. Trả lời ngắn

**Hướng cổ phiếu không nhúc nhích một milimét nào trong 21 ngày qua**, và mọi con số của
đợt rà soát tháng 8 **tái lập được hôm nay tới từng xu**. Nên đợt rà đó vẫn dùng được
nguyên vẹn — nó không phải một ảnh chụp đã hết hạn.

Nhưng ba phép đo mới cho thấy tình trạng **xấu hơn** bản rà soát mô tả, ở ba chỗ nó không
nhìn tới:

1. Lần cuối có người thử chạy lại tối ưu hoá cuốn chiếu là **2026-08-15** — hai ngày
   *trước* đợt rà soát. Nó phóng ra **327 lượt tính và không lượt nào chạy xong**. Không
   ai biết, vì thất bại kiểu này **không in ra chữ nào**: mỗi lượt hỏng được ghi thành
   điểm số `-999`, và khi cả lưới cùng `-999` thì bộ tối ưu **âm thầm giữ nguyên bộ tham
   số mặc định viết cứng trong mã**. Không ngoại lệ nào nổi lên, không cảnh báo nào.
2. Ba con số bị gọi chung một tên **khác nhau nhiều hơn** bản rà soát đo được: không phải
   ba chỗ mà là **bảy trong mười bốn** trường cấu hình.
3. Bộ kiểm tự động của phần cổ phiếu — thứ bản rà soát tự ghi là "chưa mở, không biết còn
   xanh hay không" — hôm nay chạy ra **495 xanh / 6 đỏ**.

Và một chỗ bản rà soát nói **sai**, tôi đã kiểm: xem mục 5.

---

## 1. Dựng lại nền đo — đo lại, không chép

Mỗi ô dưới đây đo lại từ đầu hôm nay bằng đúng phương pháp bản cũ mô tả.

| Thứ đo | Bản rà 17/08 | Đo lại 07/09 | Lệch |
|---|---|---|---|
| Ảnh chụp kết quả cổ phiếu trên đĩa | 1 tệp (07/07) | **1 tệp, 07/07/2026 11:03** | không |
| Lãi lỗ tổng của ảnh chụp đó | $33.550 | **$33.550,18** — 1.292 lệnh | không |
| Nền so sánh sau khi sửa phanh | $15.020 · 605 lệnh · Calmar 0,76 | **$15.019,79 · 605 lệnh · Calmar 0,7621 · Sharpe 0,9338** | không |
| Mã engine cổ phiếu sửa lần cuối | 10/07 | **09/07/2026 10:57** | −1 ngày¹ |
| Dữ liệu 5 phút | 117.533 tệp · 75 mã | **117.533 tệp · 75 mã · 1,31 GB** | không |
| Tệp 5 phút mới nhất được ghi | — | **09/07/2026** — *toàn bộ* 117.533 tệp ghi trong tháng 7 | — |
| Dữ liệu ngày | 38 tệp, dừng 2024-12-31 | **38 tệp, cả 38 dừng 2024-12-31** | không |
| Việc cổ phiếu trong bộ lập lịch | không có | **không có** | không |
| Bộ chạy live cổ phiếu | sửa 05/07, chưa gắn lịch | **sửa 05/07/2026 17:47, không xuất hiện ở đâu trong bộ lập lịch** | không |

¹ Chênh một ngày là do cách đếm, không phải do có ai sửa mã: tệp mã cổ phiếu mới nhất ghi
09/07 lúc 10:57, và không tệp mã cổ phiếu nào có dấu thời gian sau ngày đó.

**Tự kiểm phép đo** — bảy phép kiểm chạy trước khi công bố bất kỳ con số nào ở trên, tất cả
xanh: mỗi cửa sổ phải có danh sách lệnh **khác rỗng** (nếu không thì bảng vẫn "đúng" trên
một bảng trống); tổng lãi lỗ dựng lại bằng **hai đường độc lập** — cộng từng lệnh, và lấy
lãi gộp trừ lỗ gộp — khớp $0,00; số lệnh lưu trong thống kê phải bằng độ dài danh sách lệnh
(1.292 = 1.292, tức ảnh chụp không bị cắt); và tổng lãi lỗ theo từng chiến lược phải bằng
lãi lỗ của cả cửa sổ.

> Lần chạy đầu, công cụ của tôi **báo xanh trên một bảng rỗng** — nó đoán sai tên trường nên
> đọc ra 0 lệnh, rồi "kết luận" rằng mỗi năm đều đặt lại vốn. Đó là lý do phép kiểm "danh
> sách phải khác rỗng" có mặt ở trên.

**Kết luận mục này:** không có gì thay đổi mà không ai ghi lại. Hướng cổ phiếu đứng yên đúng
nghĩa đen — không một byte dữ liệu mới, không một dòng mã mới, không một lần chạy nào để
lại kết quả.

---

## 2. Hai thứ *có* đổi trong 21 ngày

**a) Sáu kết luận âm của tháng 8 đã vào kho — 06/09.** Bản rà soát cảnh báo rằng mã nghiên
cứu và bảy báo cáo đang nằm rời ở thư mục gốc và "sẽ mất khi ai đó dọn thư mục". Hôm 06/09
một lượt gom lớn đã đưa **10 tệp mã nghiên cứu và cả 8 báo cáo** vào kho. Rủi ro mất trắng
đã đóng.

Nhưng nửa còn lại của cảnh báo **vẫn đúng**: sáu kết luận âm ấy vẫn **không có một dòng nào**
trong nhật ký công việc chung. Ai đọc nhật ký sáu tháng nữa sẽ không biết sáu hướng đó đã
được thử và đã chết — họ sẽ thử lại.

**b) Không có gì khác.** Toàn bộ 113 lượt ghi kho trong 21 ngày thuộc về futures và bảng
điều khiển.

---

## 3. Phát hiện mới, không có trong bản rà cũ: bộ tối ưu hoá đã chạy và hỏng câm

Bản rà soát ghi tối ưu hoá cuốn chiếu "bản mới nhất là 25/06" và xếp nó vào danh sách việc
chưa làm. Đúng về kết quả, nhưng bỏ sót chuyện đã xảy ra.

Nhật ký tiến độ của bộ tối ưu ghi **327 dòng "BẮT ĐẦU" và 0 dòng "XONG"**, ba đợt phóng,
đợt cuối lúc **06:45 ngày 15/08** — hai ngày trước bản rà soát. Cùng phút đó có một tệp
nhật ký backtest **dài 0 byte**.

Bộ ghi nhật ký này **có** in dòng "XONG" khi một lượt tính chạy trọn — tôi đọc mã để chắc,
chứ không suy từ việc không thấy nó. Nên 327/0 nghĩa là: **không một lượt nào trong 327
lượt chạy xong.**

Cấu trúc thời gian nói rõ hơn: 48 lượt của một cửa sổ cùng bắt đầu trong khoảng bốn giây,
rồi 48 lượt của cửa sổ kế tiếp bắt đầu **sáu giây sau đó**. Cửa sổ sau chỉ khởi động khi
cửa sổ trước đã đóng hết. Tức **cả 48 lượt tính kết thúc trong khoảng mười giây**.

Để biết mười giây đó có phải là "chạy nhanh" không, tôi chạy thử hai lượt tính bằng đúng
đường mà bộ tối ưu đi, chỉ hạ số tiến trình song song từ 16 xuống 2:

```
done=0  still_running=2  at t+240.0s
```

**Bốn phút, hai lượt, không lượt nào xong.** Một lượt chạy riêng lẻ trước đó cũng chưa xong
sau 15 phút. Vậy mười giây cho 48 lượt không phải là nhanh — đó là **48 lần hỏng**.

### Vì sao không ai biết

Ba tầng che nhau, và đây mới là phần đáng sửa:

- **Lượt tính hỏng trả về điểm số `-999` thay vì báo lỗi.** Mọi ngoại lệ đều bị nuốt; không
  ghi lỗi, không ghi lý do, không ghi cả việc là có lỗi.
- **Bộ chọn tham số chỉ nhận điểm *lớn hơn* mốc khởi đầu, mà mốc khởi đầu cũng đúng bằng
  `-999`.** Nên khi cả 48 lượt cùng hỏng, không lượt nào thắng, và bộ tối ưu **giữ nguyên
  bộ tham số mặc định viết cứng trong mã** rồi đi tiếp như không có chuyện gì.
- **Điểm `-999` ghi vào kết quả cũng chính là điểm mà chế độ "khoá tham số cố định" ghi ra
  một cách có chủ đích.** Người đọc kết quả về sau **không phân biệt được** "48 tổ hợp đều
  hỏng" với "chạy ở chế độ khoá tham số".

Đây đúng dạng lỗi "phép đo không đo được thì phải nói *không biết*": hàm gộp "tôi hỏng" vào
"kết quả tệ", và cái chốt chặn phía sau mở toang theo chiều im lặng.

### Nguyên nhân gốc thì tôi **chưa chứng minh được**

Điều đo được: mỗi tiến trình con **đọc trọn bộ nhớ đệm 5 phút — cả 117.533 tệp, 1,31 GB —
rồi mới cắt xuống cửa sổ huấn luyện**. Bộ lọc theo ngày nằm *sau* bước đọc, không phải
trước. Mười sáu tiến trình cùng làm việc đó một lúc trên máy 34 GB.

Đó là một cơ chế hợp lý cho việc cả 48 lượt cùng gục nhanh, nhưng **tôi chưa bắt được ngoại
lệ thật**. Tôi dừng ở đây có chủ đích: tái lập đúng điều kiện nghĩa là ép 16 tiến trình cùng
ngốn bộ nhớ trên chính cái máy đang chạy futures giấy trong giờ giao dịch. Không đáng đổi.

**Nhãn: cơ chế im lặng và việc bộ tham số rơi về mặc định = đã xác minh. Nguyên nhân gốc =
thiếu bằng chứng.**

### Vì sao chuyện này quan trọng cho quyết định sắp tới

Tài liệu trạng thái xếp "chạy lại tối ưu hoá cuốn chiếu" ở mức **CAO**, ghi lý do "tham số
15/2.0/30 đã cũ vì engine đổi". Bây giờ biết thêm: bộ tham số đang bị coi là "đã cũ" ấy
**chính là bộ mặc định viết cứng mà bộ tối ưu rơi về khi cả lưới hỏng**. Ai chạy lại và chỉ
nhìn kết quả cuối sẽ thấy đúng bộ tham số cũ quay ra, và rất dễ đọc thành "đã chạy lại, kết
quả xác nhận bộ cũ".

**Trước khi bàn lựa chọn B hay C, phải sửa chỗ này.** Không phải vì nó làm sai một con số,
mà vì ở dạng hiện tại nó **không thể cho biết nó có chạy hay không**.

---

## 4. Câu hỏi trung tâm của bản rà cũ: hôm nay cấu hình sản xuất là cái nào?

**Cấu hình sản xuất là cái nằm trong `wfo_real_run.py`** — bộ quét BẬT (top 15), luật chặn
day-trade TẮT, rủi ro 1,5% mỗi lệnh, rổ chính 37 mã, rổ ETF 12 mã, nhóm mở rộng 25 mã. Tôi
đọc thẳng mã dựng cấu hình, không đọc mặc định của công cụ.

**Con số đã được kiểm định thống kê trên đúng cấu hình đó: vẫn là không có cái nào.** Bản
rà soát nói vậy cách đây ba tuần, và không có gì chạy từ đó tới nay.

Nhưng khoảng cách **rộng hơn** bản rà soát đo. Bản cũ nêu ba chỗ khác nhau. Đối chiếu từng
trường giữa cấu hình *lưu trong chính artifact* và cấu hình sản xuất:

| Trường | Artifact được kiểm định | Cấu hình sản xuất | |
|---|---|---|---|
| Bộ quét chọn mã (3 công tắc) | TẮT | **BẬT** | khác |
| Luật chặn day-trade | BẬT | **TẮT** | khác |
| Rổ ORB | 37 mã | **rỗng** (do bộ quét cấp) | khác |
| Rổ hồi quy trung bình | 3 mã (SPY/QQQ/IWM) | **12 mã ETF ngành** | khác |
| Nhóm mở rộng cho PE_SHORT | **không có trường này** | 25 mã | khác |
| Rủi ro mỗi lệnh | 1,5% | 1,5% | giống |
| Vốn · trần vị thế · giữ qua đêm · số ngày giữ | giống nhau cả bốn | | giống |

**Bảy trên mười bốn trường khác nhau** — cộng thêm một khác biệt nữa không nằm trong cấu
hình: một bên chạy từng năm đặt lại vốn, bên kia chạy một mạch.

Hai chỗ bản rà soát **không** nêu là rổ ORB (37 so với rỗng) và rổ hồi quy trung bình (3 so
với 12). Và chi tiết nó nêu bằng lời — "danh sách 37 tên không bao gồm nhóm 25 mã mà
PE_SHORT lấy tín hiệu" — đo ra còn mạnh hơn: trường đó **không tồn tại** trong cấu hình đã
lưu.

Nghĩa là câu "bộ có edge triển khai được = TREND_FOLLOW + PE_SHORT" được kết luận trên một
hệ mà PE_SHORT **không có rổ tín hiệu của nó**.

---

## 5. Một chỗ bản rà cũ nói sai

Bản rà soát liệt kê bốn "quyết định đã ra nhưng không ghi vì sao", trong đó có:

> *Ngưỡng "1% rủi ro mỗi lệnh" trong nền đó so với "1,5%" ở nơi khác — không có ghi chú.*

Sai cả hai vế, và tôi kiểm bằng cách đọc mã đã sinh ra artifact:

- Nền so sánh đó **dùng 1,5%**, không phải 1%. Cấu hình lưu trong artifact ghi `0.015`, và
  mã tạo ra nó cũng đặt `0.015`.
- Và **có ghi chú**: sổ quyết định của hướng cổ phiếu có hẳn một mục
  *"max_risk_pct = 1,5% (thay vì 1,0%)"* kèm lý do — ràng buộc mục tiêu biến động, 1% quá
  chặt cho rổ cổ phiếu.

Ba mục còn lại trong danh sách đó tôi **chưa kiểm**.

Ghi ra đây vì bản rà cũ đang được dùng làm nền, nên chỗ nó sai phải sửa **tại chỗ nó đang
sống**, không phải ghi vào một tệp khác rồi để nguyên.

---

## 6. Năm gạch đầu dòng bản rà cũ tự nhận chưa làm — đã đóng một

Bản rà soát tự liệt kê năm chỗ chưa kiểm. Tôi đóng được một, rẻ nhất:

> *Chưa mở bộ kiểm tự động của phần cổ phiếu — không biết nó còn xanh hay không.*

**Đo được: 501 phép kiểm · 495 xanh · 6 đỏ · 14,2 giây.** Sáu cái đỏ chia làm hai nhóm, và
đọc kỹ thì **cả sáu trông như phép kiểm đã lỗi thời, không phải engine hỏng** — nhưng nhóm
thứ hai cần một bước xác minh nữa mới kết luận được:

**Nhóm 1 — bốn phép kiểm HMM viết cho mô hình 3 trạng thái.** Hệ cổ phiếu dùng **4 trạng
thái** (Calm/Normal/Stress/Crisis) — đúng như tài liệu kiến trúc mô tả là chủ đích. Các
phép kiểm này đòi đúng 3, nên đỏ vì mô hình trả về trạng thái thứ tư. Engine không sai;
phép kiểm chưa được cập nhật khi hệ cổ phiếu chuyển sang 4 trạng thái.

**Nhóm 2 — hai phép kiểm ORB đòi một hành vi chặn mà mã không làm ở chỗ nó đứng nhìn.**

- Một phép kiểm đòi loại cổ phiếu giá $246 vì "vượt trần $200". Trần giá thật trong mã là
  **$1.000**, và tra lịch sử kho thì trần $200 **chưa từng tồn tại** ở bộ quét. Đây là phép
  kiểm ghim một con số cứng đã trôi khỏi mã.
- Phép kiểm còn lại đòi từ chối nến "phá giả". Hàm sinh tín hiệu **có** nhận ra nến đó — nó
  trả về cờ `phá giả = đúng` ngay trong kết quả — nhưng nó **không** từ chối ở bước đó;
  việc từ chối nằm ở bước xác nhận phía sau, nơi mã ghi rõ *"không bao giờ xác nhận một nến
  phá giả thành lệnh vào ORB"*. Phép kiểm đang soi sai tầng.

  **Chưa xác minh:** tôi đọc thấy hai tầng trong mã chiến lược, nhưng **chưa truy xem engine
  thật sự gọi tầng nào**. Nếu engine gọi thẳng hàm sinh tín hiệu và bỏ qua bước xác nhận,
  thì cái cờ kia được tính ra rồi vứt đi — và đó là lỗ lọc thật, không phải phép kiểm lỗi
  thời. **Đây là việc rẻ nhất còn lại và nên làm trước tiên.**

Vì sao đáng nói: tài liệu kiến trúc dùng chung đặt ra một cổng — *"khi đụng vào lớp HMM dùng
chung, phần cổ phiếu phải chạy toàn bộ bộ kiểm và tất cả phải xanh"*. Cổng đó hôm nay
**không xanh**, nên nó không chặn được gì; và vì bốn cái đỏ là phép kiểm cũ chứ không phải
lỗi, người tiếp theo gặp nó nhiều khả năng sẽ bỏ qua cả sáu — kể cả cái thứ sáu chưa ai truy
tới đáy.

**Ba gạch còn lại vẫn chưa ai kiểm**: đọc engine cổ phiếu theo tuần tự; rà tham chiếu chéo
giữa engine cổ phiếu và futures; ảnh hưởng của cách hiệu chỉnh giá SPY lên nhãn chế độ.

---

## 7. Hai tài liệu đang nói sai, không phải một

Bản rà soát chỉ ra tài liệu trạng thái của hướng cổ phiếu vẫn ghi **"Live-ready. Edge hẹp."**
— viết 06/07, trước cả hai đợt kiểm định 08/07 và 09/07, chưa cập nhật lần nào. Hôm nay vẫn
nguyên văn.

Có **chỗ thứ hai** bản rà soát không nêu: bảng kiến trúc dùng chung — tài liệu mà người làm
futures cũng đọc — ghi hệ HMM cổ phiếu ở trạng thái **"LIVE-READY"**. Ai đọc bảng đó sẽ mang
ấn tượng ấy sang mà không bao giờ mở tài liệu của riêng hướng cổ phiếu.

Và cùng tài liệu trạng thái ấy còn trích một "ảnh chụp nền đã khoá" với tổng **+$34.214** —
tệp đó **không còn ở bất kỳ đâu trong kho**. Tôi quét lại hôm nay để chắc. Một con số đã
khoá mà không tái tạo được thì không dùng để so bất cứ thứ gì.

---

## 8. Vậy bước tiếp theo rẻ nhất có giá trị là gì

Bản rà cũ đề xuất A (chốt hồ sơ) + B (chạy một lần đúng cấu hình sản xuất). Sau các phép đo
hôm nay, **B chưa chạy được** — không phải vì thiếu dữ liệu, mà vì công cụ sẽ chạy nó hiện
không phân biệt được "đã chạy" với "hỏng câm". Chạy B bây giờ là chạy một phép đo mà mình
không biết nó có đo hay không.

Thứ tự tôi đề nghị, rẻ trước:

**1. Truy một câu hỏi, khoảng 20 phút.** Engine gọi tầng nào của ORB — tầng sinh tín hiệu
hay tầng xác nhận? Nếu là tầng sinh tín hiệu thì cờ "phá giả" đang bị tính rồi vứt, và đó là
lỗ lọc thật đang nằm trong mọi kết quả cổ phiếu đã đo. Rẻ nhất, và là thứ duy nhất hôm nay
có thể lật một kết luận.

**2. Chốt hồ sơ — nửa buổi, không chạy gì.** Sửa **hai** chỗ đang ghi "live-ready" chứ không
phải một; ghi rõ bảy trường cấu hình khác nhau ở mục 4 để lần sau không ai đọc nhầm; sửa mục
1%-rủi-ro ngay trong bản rà tháng 8; ghi sáu kết luận âm tháng 8 vào nhật ký công việc; đánh
dấu con số $34.214 là **không tái tạo được**. Đây vẫn là việc có tỉ lệ giá trị trên chi phí
cao nhất, đúng như bản rà cũ kết luận.

**3. Sửa chỗ hỏng câm của bộ tối ưu — trước B, không phải trong lúc B.** Ba việc, đều là sửa
cách *báo cáo* chứ không đụng luật giao dịch, nên không dính vào chuyện uốn đường cong: cho
lượt tính hỏng ghi lại lý do thay vì nuốt; tách "hỏng" khỏi "điểm số tệ" để cả lưới hỏng
không rơi âm thầm về tham số mặc định; và **cắt cửa sổ ngày trước khi đọc tệp thay vì sau**
— hiện mỗi tiến trình đọc cả 1,31 GB rồi mới bỏ đi phần lớn.

**4. Chỉ khi đó mới bàn B.** Và khi bàn, cam kết ngưỡng trước khi nhìn kết quả, đúng như bản
rà cũ đã viết.

**Chưa nên đụng C (Vault 2025).** Điều kiện chặn của nó không đổi: không có dữ liệu 2025, và
bây giờ biết thêm là bộ tối ưu phải sửa trước.

---

## 9. Khai báo: hai lượt chạy thử của phiên này

Đúng hợp đồng chỉ-đọc với mã và cấu hình — không sửa, không commit gì cả. Nhưng hai lượt
chạy thử để xác minh mục 3 có để lại dấu vết, nên khai ra:

- Nhật ký tiến độ của bộ tối ưu **có thêm 3 dòng của tôi**, mốc `10:25:17` và hai dòng
  `10:32:21` ngày 07/09. Tệp này chỉ nối thêm và không nằm trong kho. Tôi **không xoá**
  chúng — sửa nhật ký vận hành là can thiệp vào chính dấu vết cần bảo vệ. Ai đọc tệp sau
  này bỏ qua ba dòng đó.
- Hai lượt chạy thử bị dừng chủ động (không để chạy tới cùng) vì chúng ngốn bộ nhớ trên máy
  đang chạy futures giấy trong giờ giao dịch. Không có tệp kết quả nào được ghi.
- Không xoá bất kỳ tệp `.parquet` hay dữ liệu đệm nào.

---

## 10. Điều tôi CHƯA kiểm

- Nguyên nhân gốc khiến 327 lượt tính đều hỏng — có cơ chế hợp lý, **chưa bắt được ngoại lệ**.
- Engine ORB gọi tầng nào — chính là việc số 1 ở mục 8.
- Ba trong bốn "quyết định không ghi lý do" của bản rà cũ.
- Ba gạch đầu dòng còn lại bản rà cũ tự nhận chưa làm (mục 6).
- Cấu hình mà lượt chạy 15/08 thật sự dùng: dòng "BẮT ĐẦU" chỉ ghi cửa sổ và ba tham số,
  không ghi rổ mã. Bốn cửa sổ huấn luyện trong nhật ký **khớp với** cấu hình sản xuất, nên
  tôi tin là nó — nhưng đó là suy ra, không phải đọc được.

---

## 11. Look-ahead và fill bất khả thi — đã sửa chưa, và nếu sửa thì còn lại bao nhiêu

_Bổ sung cùng ngày 07/09, sau câu hỏi của chủ dự án._

### 11.1 Trả lời thẳng: chưa sửa cái nào

**Cả hai lỗi vẫn còn nguyên trong engine cổ phiếu ở HEAD hôm nay.** Tôi kiểm bằng cách đọc
mã đang chạy, không đọc báo cáo mô tả nó.

- **Look-ahead** — báo cáo Gap 1 viết ngày 04/07 đã tìm ra và ghi rõ ở mục cuối:
  *"Fix options (not yet applied)"*. Lượt ghi kho cuối cùng chạm vào engine cổ phiếu là
  08/07, và đọc bản thay đổi đó thì nó chỉ đổi **cách đếm chuỗi lệnh thua cho phanh ngắt**
  — không đụng một chữ nào tới giá thoát lệnh. Lỗi còn nguyên.
- **Fill bất khả thi** — chưa có ai đo trên nhánh cổ phiếu. Luật *"không được có fill bất
  khả thi"* tồn tại như một quy tắc P0 và đã được đối soát **bên futures**; bên cổ phiếu
  không có tài liệu nào, không có phép đo nào. Đây là **chưa ai kiểm**, không phải "đã đo
  và không sao".

### 11.2 Hai lỗi đó làm gì, bằng ngôn ngữ hình dung được

**Look-ahead — thoát lệnh bằng giá chưa xảy ra.** Khi phanh ngắt hoặc chế độ an toàn bắt
đóng vị thế lúc 10:15 sáng, engine ghi thời điểm thoát là 10:15 nhưng **lấy giá đóng cửa
của thanh cuối ngày** để tính lãi lỗ. Giá đó chưa tồn tại vào lúc 10:15. Một lệnh bị đóng
giữa buổi sáng nhưng được tính tiền theo giá 16:00.

**Fill bất khả thi — khớp ở mức giá thanh nến chưa bao giờ chạm tới.** Engine đặt lệnh
dừng lỗ, rồi mỗi thanh nến hỏi "giá thấp nhất có chạm mức dừng không?". Nếu có, nó khớp
**đúng tại mức dừng**. Nhưng khi giá nhảy qua hẳn — cả thanh nến nằm bên kia mức dừng —
câu hỏi đó vẫn trả lời "có", và engine vẫn khớp tại mức dừng, một mức giá **cao hơn đỉnh
của thanh nến đó**. Thị trường thật chưa từng giao dịch ở đó.

Ví dụ đo được, một lệnh mua TSLA ngày 23/02/2017: thanh nến giá cao nhất 17,64 — engine
khớp lệnh dừng ở **18,13**. Chênh lệch đó đi thẳng vào lãi: **+274 đô la** cho một lệnh.

Chiều lệch **không đối xứng**: nhảy giá qua mức **dừng lỗ** thì sổ sách luôn được lợi; nhảy
qua mức **chốt lời** thì sổ sách chịu thiệt. Trên bộ 605 lệnh: 8 lệnh có lợi cộng $958, 3
lệnh chịu thiệt trừ $154.

### 11.3 Đo được bao nhiêu

Nguồn thanh nến là chính bộ dữ liệu mà lượt chạy sinh ra nền so sánh đã dùng — tôi lấy tên
bộ đó từ **thông điệp của lượt ghi kho đã tạo ra artifact**, không đoán.

| | Nền so sánh liên tục 6 năm | Ảnh chụp từng-năm-một |
|---|---|---|
| Số lệnh | 605 | 1.292 |
| **Đã công bố** | **$15.019,79** | **$33.550,18** |
| Lệnh thoát ở giá ngoài thanh nến của nó | 21 (3,5%) | 85 (6,6%) |
| Sửa nhảy giá qua mức dừng/chốt | −$804 (11 lệnh) | −$4.498 (23 lệnh) |
| Sửa look-ahead, tính lại ở thanh kích hoạt | −$574 (15 lệnh) | −$3.027 (85 lệnh) |
| **Còn lại, ước lượng bậc một** | **$13.641,64 (−9,2%)** | **$26.025,10 (−22,4%)** |

Khoảng dao động theo giả định khớp lại: nếu khớp ở **giá mở cửa** thanh nến (lệnh thị
trường thật sẽ được giá đó) thay vì ở đỉnh/đáy, phần nhảy giá thành −$563 với bộ 605 và
−$5.754 với bộ 1.292. Hai chiều khác nhau vì bộ 605 có ba lệnh chốt lời lệch ngược chiều.

**Đây là ước lượng bậc một, KHÔNG phải kết quả chạy lại.** Nó tính lại giá trên **đúng tập
lệnh cũ**. Sửa thật sẽ đổi vốn → đổi cỡ vị thế → đổi mọi lệnh sau đó. Calmar và Sharpe
**không tính lại tĩnh được** vì đường sụt giá thay đổi — muốn có thì phải chạy lại.

### 11.4 Tự kiểm

- **Ba đường độc lập cho cùng một con số nền**: đọc pickle, cộng từng lệnh, và đọc tệp CSV
  đã ghi kho riêng — cả ba ra $15.019,79.
- **Hai đường cho cùng một con số sửa**: cộng phần chênh từng lệnh, và dựng lại toàn bộ lãi
  lỗ từ giá đã sửa. Lệch **$0,00** trên cả hai bộ.
- **Công cụ phải chứng minh được nó biết nói "không"**: 583/604 lệnh được xếp là khớp *trong*
  thanh nến. Nếu nó gắn cờ tất cả thì đó là công cụ hỏng.
- **Kiểm quy ước tính tiền trước khi tính bất kỳ khoản sửa nào**: dựng lại lãi lỗ từ
  chiều lệnh × (giá ra − giá vào) × số cổ − chi phí, khớp 50/50 và 80/80 mẫu.
- **Một phép kiểm của tôi ĐỎ, và cái sai là giả định của tôi**: tôi cho rằng khớp lại ở giá
  mở cửa luôn thiệt hơn khớp ở đỉnh/đáy. Sai trên tổng, vì tổng cộng gộp cả lệnh lệch thuận
  lẫn lệch nghịch. Kiểm lại từng lệnh: **0/11 vi phạm** — công cụ đúng, giả định gộp của tôi
  sai.
- **Khớp chéo với công việc của người khác**: tôi tìm ra 15 lệnh thoát bằng giá look-ahead.
  Sáu trong đó kích hoạt lúc 15:55, tức chỉ trước thanh cuối **một nhịp**, nên chênh lệch
  không đáng kể. 15 − 6 = **9** — đúng bằng con số 9 lệnh mà báo cáo Gap 1 tìm ra hồi tháng
  7 bằng một phương pháp hoàn toàn khác (so đường live với đường replay).

### 11.5 Điều quan trọng nhất rút ra

Bản sửa **không cứu được** câu hỏi nặng nhất của bản rà tháng 8. Đường lãi ba năm cuối
trong mẫu, trước và sau khi sửa:

| | 2020 | 2021 | 2022 | ba năm cộng lại |
|---|---|---|---|---|
| Đã công bố | +$484 | +$1.434 | −$30 | **+$1.888** |
| Sau khi sửa | +$501 | +$1.422 | −$38 | **+$1.885** |

**Gần như không đổi.** Toàn bộ khoản sửa rơi vào 2017–2019 (riêng 2017 mất 41,7%). Nghĩa
là: hai lỗi này **không phải** lời giải thích cho việc hệ đi ngang ba năm cuối — chúng chỉ
làm mỏng thêm phần edge của những năm đầu, vốn là phần đang gánh cho cả bảng.

### 11.6 Điều CHƯA đo được ở mục này

- **Kết quả ngoài mẫu 2023-2024 (+$6.666)**: tệp lệnh của lượt chạy đó **không có trên đĩa**
  — chỉ còn báo cáo. Không đo được ảnh hưởng của hai lỗi này lên nó. Cùng engine nên cùng
  họ lỗi, nhưng đó là suy ra, không phải đo.
- **Calmar / Sharpe sau khi sửa**: phải chạy lại, không tính tĩnh được.
- **Con số đúng cấu hình sản xuất**: vẫn không tồn tại (mục 4). Cả hai con số ở mục 11.3
  đều thuộc cấu hình KHÔNG phải sản xuất.
- **Hai lệnh vào ở giá ngoài thanh nến** trên bộ 605: đã đếm được, chưa truy nguyên nhân.

### 11.7 "Vậy là không có edge?" — chạy lại đúng phép kiểm của dự án trên dữ liệu đã sửa

Câu "không có edge" là một **kết luận**, nên nó cũng phải được đo. Dự án đã có sẵn phép
kiểm edge của riêng nó — bootstrap theo khối trên bội số rủi ro, đọc đúng tệp CSV 605 lệnh
đã ghi kho. Tôi chạy **chính script đó, không sửa một dòng**, hai lần: một lần trên dữ liệu
gốc để chắc mình tái lập được, một lần trên dữ liệu đã sửa hai lỗi.

Script ghi báo cáo vào thư mục con tính theo nơi chạy, nên chạy từ thư mục tạm là **không
đụng** tệp báo cáo tháng 7 trong kho. Lượt chạy gốc ra đúng **6.608 byte**, bằng đúng tệp
đang nằm trong kho — tái lập sạch.

**Một bẫy của công cụ, phải nói ra:** trong bảng kết quả, **hai cột đầu là số cứng chép từ
lần chạy trước**, không tính lại. Chỉ hai cột cuối — bootstrap theo khối và jackknife — là
tính mới. Nên so sánh chỉ có nghĩa trên hai cột đó.

| Chiến lược | Số lệnh | khối B20 trước | **sau** | jackknife trước | **sau** | Đổi |
|---|---|---|---|---|---|---|
| TREND_FOLLOW | 353 | 0,014 | **0,028** | 0,043 | **0,088** | bền → **tập trung** |
| PE_SHORT | 29 | 0,000 | 0,000 | 0,052 | 0,052 | không đổi |
| GF_SHORT | 12 | — | — | 0,004 | 0,004 | không đổi |
| ORB | 75 | 0,148 | 0,146 | 0,429 | 0,420 | không đổi |
| STRESS_MID | 28 | 0,325 | 0,353 | 0,622 | 0,664 | không đổi |
| STRESS_ORB | 108 | 0,320 | **0,517** | 0,485 | 0,638 | xấu đi rõ |

Kết quả **không đổi** khi dùng giả định khớp lại khắt khe hơn (giá mở cửa thay vì đỉnh/đáy):
TREND_FOLLOW ra 0,027 và 0,089 — cùng một câu chuyện.

**Vì sao chỉ vài chiến lược nhúc nhích** — kiểm tính nhất quán: 26 lệnh được sửa rơi vào
TREND_FOLLOW 16 lệnh (−$922), STRESS_ORB 7 lệnh (−$383), STRESS_MID 1 lệnh (−$127), ORB 2
lệnh (+$54). PE_SHORT và GF_SHORT **không có lệnh nào bị sửa** — đúng bằng hai chiến lược
có p-value không đổi một chữ số nào. Công cụ tự nhất quán.

### Trả lời

**Không. Bằng chứng không nói "không có edge".** Nó nói ba điều khác nhau, và gộp chúng lại
là mất thông tin:

1. **Trong mẫu, kể cả sau khi sửa hai lỗi, edge vẫn qua ngưỡng.** TREND_FOLLOW p=0,028;
   PE_SHORT và GF_SHORT vẫn đạt. Đây không phải "không có edge".
2. **Nhưng trụ chính vừa yếu đi đúng ở chỗ nhạy cảm nhất.** TREND_FOLLOW là 353 trên 605
   lệnh. Trước khi sửa nó là chiến lược duy nhất được kết luận *"không do tập trung"*. Sau
   khi sửa, jackknife 0,043 → 0,088 — nó rơi vào cùng nhãn "tập trung" với PE_SHORT.
   **Sau bản sửa, cả ba chiến lược dương đều mang nhãn tập trung. Không còn cái nào bền.**
3. **Ngoài mẫu vẫn là chỗ yếu nhất và không đổi**: không chiến lược nào đạt ngưỡng, 96% kết
   quả nằm ở 5 lệnh. Đó là **thiếu bằng chứng**, không phải bằng chứng phủ định.

Và cái khung bao trùm cả ba: **mọi con số trên đây đo trên cấu hình KHÔNG phải cấu hình sản
xuất** (mục 4). Muốn nói "có edge" hay "không có edge" cho hệ đang định chạy thật thì con
số đó vẫn chưa tồn tại.

**Muốn kết luận "không có edge" thì cần gì:** một phép kiểm đủ lực chạy trên **cấu hình sản
xuất** mà không đạt, hoặc ngoài mẫu đi âm. Hiện chưa có cái nào — không phải vì đã thử và
thất bại, mà vì **chưa ai chạy**.

**Nhãn đúng cho hôm nay: có dấu hiệu edge trong mẫu, mỏng và tập trung; ngoài mẫu thiếu
bằng chứng; và trên cấu hình sẽ chạy thật thì chưa đo.**

Hai ghi chú giữ cho câu trên không bị đọc quá tay: (a) đây vẫn là tính lại giá trên tập
lệnh cũ, chạy lại thật sẽ đổi cỡ vị thế và đổi mọi lệnh sau; (b) phép kiểm trong mẫu chạy
trên chính dữ liệu đã dùng để chọn ra các chiến lược này, nên nó lạc quan theo cấu tạo —
ngoài mẫu mới là phép kiểm thật, và ngoài mẫu thì chưa đủ bằng chứng.
