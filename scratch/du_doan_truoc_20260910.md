# Dự đoán ghi TRƯỚC sự kiện — 2026-09-10

Viết lúc **12:40 ET ngày 10/09/2026**, tức trước job 13:45 và trước cửa sổ NKD 01:10 sáng
11/09. Commit `52f14df`.

Mục đích: mô hình về lần roll NKD tới giờ mới chỉ được kiểm **trong mẫu** — tôi đo dữ liệu
rồi giải thích chính dữ liệu ấy. Hai sự kiện sắp tới là phép kiểm ngoài mẫu duy nhất, và nó
chỉ có giá trị nếu dự đoán được ghi ra trước. Ghi sau là kể chuyện.

**Nếu dự đoán sai, dừng — không xây bản sửa cổng giá cho tới khi hiểu vì sao sai.**

---

## Sự kiện 1 — job 13:45 ET hôm nay (17:45 UTC)

| | dự đoán |
|---|---|
| MNKD | phát hiện roll `NKDU6 -> NKDZ6`, neo lại **thành công**, ghi bar bình thường |
| độ lệch mới | trong khoảng **145–149** (trung vị đo trên cửa sổ 3 ngày; 147 nếu giá không đổi nhiều) |
| MES · MNQ · MYM · M2K | `contract unchanged`, không neo lại |
| mã thoát | **0** — pre-flight OK, không khoá ngày |
| sổ neo sau đó | `MNKD: {offset: <145-149>, contract: "NKDZ6"}`, bốn cái kia giữ nguyên `offset 0.0` |

**Sai nếu:** neo lại bị từ chối, hoặc độ lệch nằm ngoài 145–149, hoặc bất kỳ công cụ Mỹ nào
báo roll, hoặc pre-flight fail.

## Sự kiện 2 — cửa sổ NKD 01:10 ET sáng 11/09 (05:10 UTC)

| | dự đoán |
|---|---|
| kết quả | **vẫn từ chối**, toàn bộ 22 slot |
| lý do | **`overlap_disagreement`** — KHÔNG phải `series_rolled` |
| bar cũ trong cửa sổ | ~756 |
| trong đó lệch giá | ~497 (65,7%) |
| lệch lớn nhất | ~2,00 điểm |

**Đây là hòn đá thử vàng.** Nếu nó vẫn từ chối bằng `series_rolled` thì việc neo lại không
tới được nơi cần tới. Nếu nó **chạy được** thì tôi đã hiểu sai cổng so giá, và toàn bộ con
số "119 slot mỗi lần roll" phải bỏ đi.

## Sự kiện 3 — cửa sổ NKD 01:10 ET thứ Hai 14/09

| | dự đoán |
|---|---|
| kết quả | **chạy bình thường**, không lời từ chối nào liên quan tới roll |
| lý do | cửa sổ 2 ngày đã trôi qua khỏi mốc 09/09 17:45; không còn bar cũ nào |

**Sai nếu:** vẫn từ chối. Khi đó "tự lành sau 2 ngày" là sai, và cái giá của mỗi lần roll
lớn hơn 119 slot.

---

## Cơ sở đo

Mọi con số trên đo trong ngày 10/09/2026 trên dữ liệu thật:

    tỉ lệ san dịch chuyển     1,0022582206  (khớp ngoài mẫu, 5.492 bar, 5 ngày)
    sai số còn lại            <= 0,498678 điểm, 5.492/5.492 bar — dấu vân tay của làm tròn
    chồng lấn 08/09-09/09     1.644 bar, 0 bar khớp tuyệt đối
    phân bố chênh             145 (19,6%) · 146 (13,9%) · 147 (56,0%) · 148 (10,5%)
    dung sai cổng so giá      1e-6, không có ngưỡng nào để chỉnh

Kiểm bằng: `python scratch/kiem_du_doan_20260910.py`
