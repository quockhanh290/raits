# Dự đoán ghi TRƯỚC sự kiện — 2026-09-14

Viết lúc **10:35 ET thứ Hai 14/09/2026**. Với hôm nay, chỉ tính các slot **từ 11:00 ET trở đi**
— chắc chắn sau lúc tệp này được commit. Các slot Stress 10:35–10:55 đã có thể chạy trong lúc
viết, nên không được tính.

---

## Kết quả của dự đoán trước (ghi ngày 10/09)

| sự kiện | dự đoán | thực tế | |
|---|---|---|---|
| 13:45 ngày 10/09 neo lại NKD | 145–149 | +147,0 | ĐÚNG |
| NKD 01:10 ngày 11/09 | **chặn** bằng lệch giá | **chạy sạch, 88/88 `decided`** | **SAI** |
| NKD 01:10 ngày 14/09 | chạy bình thường | chạy sạch, 88/88 | ĐÚNG |

Dự đoán giữa **sai**, và tôi đã ghi trước rằng nếu vậy thì *"tôi đã hiểu sai cổng so giá"*.
Đúng thế. Hai chỗ hiểu sai, cả hai đã đo lại ngày 14/09:

**1. Cửa sổ so giá không phải 48 giờ, mà là 2 PHIÊN giao dịch, bắt đầu lúc 18:00 ET.** Tôi tính
756 bar cũ trong cửa sổ thứ Sáu bằng phép trừ 48 giờ. Thực tế cửa sổ thứ Sáu bắt đầu 18:00 ET thứ
Tư — sau bar cuối của hợp đồng cũ — nên nó không chạm tới bar cũ nào.

**2. Cổng so với HỢP ĐỒNG CỤ THỂ, không phải chuỗi liên tục.** Nguồn bar sống (`_bars_contract`)
hỏi chuỗi liên tục "đang ở tháng nào" rồi lấy giá thô của hợp đồng tháng đó, vì IBKR từ chối
`ContFuture` kèm mốc kết thúc. Nên sau roll, cổng so bar cũ trong tệp với **giá thô của hợp đồng
mới** tại cùng phút — hai hợp đồng khác nhau, chênh bằng spread giao dịch thật, không phải hằng số
hay tỉ lệ.

Hệ quả:

- Nhánh `bridge/roll-ratio` (commit `1b9f4b7`) được kiểm trên **sai nguồn dữ liệu**. Đo trên đúng
  dữ liệu cổng thấy: 3/1.185 bar khớp. **Không gộp.**
- Hai job neo (`52f14df`) chỉ đổi tên lời từ chối, **không cứu được phiên nào**.
- Cái giá thật mỗi lần roll: **phiên giao dịch đầu tiên sau roll**, không phải 2 ngày / 119 slot.

---

## Sự kiện A — Stress (từ 11:00) và Swing hôm nay, 14/09

Rổ Mỹ roll cuối tuần, sau lượt ghi 13:45 thứ Sáu. Cửa sổ hôm nay bắt đầu 18:00 ET thứ Năm, chứa
bar thứ Sáu ghi dưới hợp đồng tháng 9, đem so với giá thô tháng 12.

| | dự đoán |
|---|---|
| mọi slot `roska4_stress` từ 11:00 và mọi slot `roska4_swing` | **từ chối `overlap_disagreement`** |
| `series_rolled` | **không** — sổ neo đã là Z6 |
| `decided` | **không slot nào** |

**Sai nếu:** có slot nào `decided` → cửa sổ không chạm tới bar cũ như tôi nghĩ.

## Sự kiện B — pre-flight 13:45 hôm nay

| | dự đoán |
|---|---|
| kết quả | **OK**, không khoá ngày |
| sổ neo rổ Mỹ | **không đổi**: MES −67,75 · MNQ −300,5 · MYM −418,0 · M2K −21,7, cả bốn Z6 |
| NKD | không đổi: +147,0, NKDZ6 |

**Sai nếu:** pre-flight hỏng, hoặc có công cụ nào bị neo lại lần nữa.

## Sự kiện C — thứ Ba 15/09, cả ngày

Cửa sổ thứ Ba bắt đầu 18:00 ET Chủ nhật. Mọi bar trong đó được ghi lúc 13:45 hôm nay dưới neo mới.

| | dự đoán |
|---|---|
| `roska4_calm`, `roska4_stress`, `roska4_swing` | **không** `overlap_disagreement`, **không** `series_rolled` |
| `global_nkd` | không lời từ chối nào liên quan roll |

Chỉ đếm hai mã `overlap_disagreement` và `series_rolled`. Từ chối vì lý do khác (chế độ thị
trường, độ tươi dữ liệu, sàn đóng) không liên quan tới dự đoán này.

**Sai nếu:** có bất kỳ `overlap_disagreement` nào ở rổ Mỹ thứ Ba → luật "mất đúng một phiên" sai.

---

## Cơ sở đo (14/09, dữ liệu thật)

Tái lập đúng yêu cầu Calm 09:32 gửi (MESZ6 cụ thể, kết thúc 09:32 ET, 2 D): **1.185 bar chung**,
khớp số trong lời từ chối.

    tệp + 67,75  so với  MESZ6 thô     khớp 0/1.185   lệch lớn nhất 17,25   (= lời từ chối)
    spread trôi theo giờ               +2,00 (Thu 18:00) → +0,25 (Fri 12:00)
    thanh khoản MESZ6 trước roll       trung vị 8 hợp đồng / phút

Chuỗi liên tục so với MESZ6 cụ thể, theo phiên:

    Fri 11/09   khớp   2/398     ← còn là giá tháng 9 đã chỉnh
    Sun 13/09   khớp 360/360     ← từ 18:00 ET: chuỗi liên tục = giá thô tháng 12
    Mon 14/09   khớp 572/572

Tức IBKR roll chuỗi liên tục **đúng ranh giới phiên**. Đó là lý do dự đoán C có cơ sở.

Kiểm bằng: `python scratch/kiem_du_doan_20260914.py`
