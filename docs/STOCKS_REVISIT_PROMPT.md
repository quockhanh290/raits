# Quay lại hướng cổ phiếu — đề bài cho phiên rà soát

_Viết 2026-09-07. Dùng làm prompt mở đầu cho một phiên mới, không phải tài liệu trạng thái._

---

## Bối cảnh, và vì sao đề bài này tồn tại

Bạn đang mở lại hướng **cổ phiếu** của RAITS. Đây là nửa đã đứng yên trong khi nửa kia —
futures Track 1 — chạy giấy mỗi ngày và đang tiến tới cổng đặt lệnh.

Đã có một đợt rà soát độc lập cho hướng này: `STOCKS_AUDIT_2026-08-17.md`. **Đọc nó trước
khi làm bất cứ gì**, và đọc với thái độ đúng: nó là **ảnh chụp của ngày viết**, không phải
mô tả hiện trạng. Ba tuần qua chỉ riêng phía futures đã có bảy chỗ trên màn hình hoá ra
đang mô tả một trạng thái đã qua — không cái nào là lỗi logic, mỗi cái đúng vào ngày nó
được viết. Giả định mặc định phải là: **mọi con số trong tài liệu đó có thể đã hết hạn.**

Điều đợt rà soát ấy kết luận, tóm lại:

- Không có bằng chứng nào nói hệ cổ phiếu hỏng. Nó dương cả trong mẫu lẫn ngoài mẫu.
- Cũng không có bằng chứng nào đủ để đưa vào tiền thật. Không chiến lược nào đạt ngưỡng
  ngoài mẫu; **96% kết quả ngoài mẫu nằm ở 5 lệnh**; ba năm gần cuối gần như bằng phẳng.
- Chỗ nghiêm trọng nhất: ba con số vẫn được gọi chung là "baseline in-sample" thật ra do
  **ba cấu hình khác nhau của cùng một engine** sinh ra, và cái duy nhất được kiểm định
  thống kê lại **không phải cấu hình sản xuất**.
- Sáu hướng tìm edge mới trong tháng 8 đều âm.

---

## Câu hỏi của phiên này

**Hướng cổ phiếu hiện đang đứng ở đâu, và bước tiếp theo rẻ nhất có giá trị là gì?**

Không phải "làm sao cho nó lãi hơn". Câu đó chưa trả lời được, và trả lời sớm là cách
nhanh nhất để rơi vào tối ưu hoá trên một nền chưa vững.

---

## Làm gì trước, theo thứ tự

**1. Dựng lại nền đo, đừng chép lại.** Đợt rà cũ ghi rõ cách nó đo từng con số. Chạy lại
đúng những phép đo ấy và **so với con số cũ**. Chỗ nào lệch là chỗ đáng nói trước tiên —
nó cho biết ba tuần qua có gì đổi mà không ai ghi lại.

Tối thiểu cần đo lại: có bao nhiêu ảnh chụp kết quả trên đĩa và ngày của chúng; mã engine
cổ phiếu sửa lần cuối khi nào; dữ liệu 5 phút phủ tới đâu; có việc cổ phiếu nào trong bộ
lập lịch chưa; bộ chạy live cổ phiếu đã được gắn lịch chưa.

**2. Kiểm chính chỗ đợt rà cũ chỉ ra là nguy hiểm nhất.** Ba cấu hình bị gọi bằng một tên.
Câu hỏi cụ thể: **hôm nay, cấu hình sản xuất là cái nào, và con số nào đã được kiểm định
trên đúng cấu hình đó?** Nếu câu trả lời vẫn là "không cái nào", thì đó là phát hiện đầu
tiên và mọi so sánh về sau phải mang nhãn ấy.

**3. Chỉ khi hai bước trên xong mới bàn tới hướng đi.** Đợt rà cũ đưa ba lựa chọn kèm cổng
kiểm. Đọc chúng, nhưng đừng chọn theo — điều kiện có thể đã đổi.

---

## Ràng buộc

**Không đụng vào futures.** Tuyến Track 1 đang chạy giấy hằng ngày và có bộ lập lịch sống.
Mọi thứ trong `global_index/track1_*`, `run_scheduler.py`, `runner.py` và `monitor/backend/`
nằm ngoài phạm vi phiên này. Nếu một việc bắt buộc phải chạm vào đó, **nói ra trước** thay
vì làm.

**Đọc trước khi gọi tên.** Kho này có nhiều tài liệu rà soát — `RUNNER_AUDIT.md`,
`RUNNER_AUDIT_ROUND2.md`, `docs/CROSS_SYSTEM_FINDINGS.md`, `SCRATCHPAD.md`, `TASK.md`.
Trước khi gọi một hành vi là "chưa đo" hay "lỗi", tìm xem đã có ai viết về nó chưa. Câu
trả lời thường ở tầng khác và đã có người ghi lại.

**Đừng xoá dữ liệu.** Không xoá `.parquet`, không xoá `data/cache/`. Dựng lại mất 2–3 giờ
từ nguồn ngoài. "Xoá cache" ở đây nghĩa là `__pycache__` và `.pkl`, không bao giờ là
parquet.

**Đừng đề xuất đổi siêu tham số dựa trên kết quả backtest quan sát được.** Đó là uốn đường
cong. Chỉ sửa logic vào/ra lệnh và tham số rủi ro có cấu trúc.

---

## Cách làm việc

**Đo trước, rồi mới nói.** Một lời giải thích nghe hợp lý mà chưa đọc code là phỏng đoán
khoác áo kết luận. Mọi ý kiến, chẩn đoán hay ước lượng phải kèm một con số và cách lấy nó.

**Ba nhãn, giữ riêng:** *đã xác minh* (tái lập được, có số) · *thiếu bằng chứng* (đọc code
thấy đường đi, chưa chạy) · *chưa ai kiểm* (không có bằng chứng nào, cả tốt lẫn xấu).
"Không đạt ý nghĩa thống kê" là *thiếu bằng chứng*, không phải bằng chứng phủ định.

**Tự kiểm phép đo.** Giá trị bất khả thi, quan hệ bất đơn điệu, hai đường độc lập phải
khớp, kết quả quá gọn gàng — bốn dấu hiệu công cụ sai. Đợt rà cũ làm điều này và đó là lý
do tin được nó: nó dựng lại `$33.550` bằng đường riêng rồi mới dùng con số ấy.

**Muốn biết một artifact sinh ra bằng tham số nào thì đọc code đã tạo ra nó**, không đọc
mặc định của công cụ có thể tạo ra nó. Kho này đã trả giá hai lần cho đúng lỗi đó.

**Việc dài thì đưa lệnh cho chủ dự án chạy**, kèm ước lượng thời gian, đừng chôn trong tool
nền. Windows + PowerShell: đọc `argparse` hiện tại trước khi soạn lệnh, không dùng
`python -c` một dòng có nháy lồng, ghi output dài ra tệp rồi đọc tệp.

**Kết thúc bằng deliverable cụ thể** — cái gì đã đo, ra số nào, còn gì chưa. Không phải
tường thuật tiến trình.

---

## Điều dễ làm sai nhất ở phiên này

Hướng cổ phiếu đã đứng yên lâu, nên có một lực kéo rất mạnh về phía **làm gì đó cho có**:
chạy thêm một backtest, thử thêm một bộ lọc, tìm thêm một hướng edge. Sáu hướng tháng 8
đều âm, và đợt rà cũ đo được rằng cái duy nhất có tín hiệu thật lại nằm ngoài tầm với của
nhịp 5 phút mà hệ đang chạy.

Việc rẻ nhất và có giá trị nhất có thể là **không chạy gì cả** — chỉ làm cho tài liệu khớp
với bằng chứng, để sáu tháng nữa không ai đọc một dòng đã hết đúng rồi tin theo. Nếu phép
đo dẫn tới kết luận đó, nói thẳng, đừng tìm việc để làm cho phiên trông có ích.
