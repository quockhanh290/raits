# Rà soát định giá lệnh thoát — nhánh futures

_Đo ngày 18–19/08/2026. Chỉ đọc: không sửa mã production, không sửa cấu hình, không commit._
_Tài liệu này nêu **trạng thái đã đúng**, thay cho mười mục rời trong `TASK.md`._

Mỗi khẳng định dưới đây mang một trong ba nhãn:

- **[ĐO]** — đo được, có mỏ neo hoặc kiểm được bằng một lệnh
- **[MÔ HÌNH]** — chiều chắc chắn, độ lớn do tôi dựng
- **[CHƯA KIỂM]** — chưa ai đo

---

## 1. Phát hiện

**[ĐO] Backtest ghi lệnh thoát ở những mức giá chưa hề giao dịch.**

Trên tập lệnh Rổ 4, kỳ 2018-2024:

| | ngoài biên độ **cây nến thoát** | ngoài biên độ **cả ngày** |
|---|---|---|
| quy ước engine (sinh ra baseline) | 594/2.496 = **23,8%** | 116/2.496 = **4,6%** |
| luật live 14:05 | 637/2.030 = 31,4% | 91/2.030 = 4,5% |

Kiểm một ca bằng một lệnh, không qua phép tính nào của tôi:

```powershell
$env:PYTHONIOENCODING="utf-8"
python scratch\verify_one.py --inst MNQ --date 2022-05-12
```

Kết quả: lệnh bán khống vào 13.759, mô hình ghi thoát tại **13.809,10** ngày 13/05;
thị trường hôm đó chỉ chạy **14.055,00 – 14.422,25**. Mức ghi sổ thấp hơn đáy cả ngày
246 điểm. Engine ghi lỗ $103; thoát ở giá thật lúc lệnh dừng đầu tiên có thể tồn tại
(14.103,50) thì lỗ $689.

---

## 2. Cơ chế

**[ĐO] Vị thế không có lệnh dừng nào trên sàn trong 22–24 tiếng đầu.**

Live vũ trang stop tại D+1 14:00 trên đồng hồ của từng sleeve (`runner._ARM_BY_CLUSTER` =
Rổ 4 `America/New_York 14:00`, NKD `Asia/Tokyo 14:00`). Vào lệnh lúc 14:00–15:55 ngày D, nên
quãng trần thực tế là 22–24 giờ. Quy ước engine (xét stop từ ranh giới ngày) cho 8–10 giờ.

**[ĐO] 76,4% số vị thế đi qua chính mức giá lẽ ra cắt chúng trong quãng trần đó.**

**[ĐO] Mô hình vẫn ghi thoát tại MỨC STOP.** Nó lấy **luật thời gian** của phương án
"chưa có stop" nhưng lấy **giá khớp** của phương án "stop đã nằm sẵn trên sàn". Hai luật đó
không thể cùng đúng.

**[ĐO] Luật đúng đã có sẵn trong code, khoá sau điều kiện sai.** Nhánh thoát tính
`gapped = gap_fill and isg[i] and (giá mở đã vượt mức stop)` → khớp tại giá mở. Cờ `isg`
trả lời "trước bar này có nghỉ phiên không", không trả lời "lệnh stop có vừa mới được đặt
không". Giữa phiên `isg` tắt nên nhánh đúng không bao giờ chạy.

**Sửa đúng = bỏ điều kiện `isg`**, giữ lại đúng vế "giá mở đã vượt mức stop".

---

## 3. Phép hiệu chỉnh và kiểm chứng nó đầy đủ

**[MÔ HÌNH] Cách tính**: với lệnh thoát rơi vào bar mà giá mở đã ở bên kia mức stop, khớp
tại **giá mở** thay vì tại mức stop — đúng quy ước engine đang dùng cho lệnh thoát qua khe hở.

**[ĐO] Nó tương đương chính xác với việc sửa luật trong engine**: đổi giá thoát không đổi
thời điểm thoát, và trong vòng lặp chỉ có mốc thời gian đi tiếp.

**[ĐO] Nó đầy đủ** (`scratch/correction_complete.py`):

| | tại bar vũ trang (phép sửa chạm) | ở chỗ khác (bỏ sót) |
|---|---|---|
| quy ước engine | 591 lệnh · $38.904 | **26 lệnh · $120** (0,3%) |
| luật live | 645 lệnh · $99.502 | **1 lệnh · $0** (0,0%) |

Phần bỏ sót gần như toàn bộ là làm tròn tick (mức stop lẻ, giá mở trên lưới tick). Một ca
thật duy nhất: MYM 13/03/2020, stop đã ratchet lên trong lúc giá rơi qua đêm — $110.

**[ĐO] Không nhạy với lựa chọn thời điểm.** Dịch mốc đặt lệnh 14:00 → 14:05 → 14:10 → 14:30
chỉ làm kết quả nhúc nhích trong $4.5k–9.5k trên nền hiệu chỉnh ~$100k.

**Kịch bản "khớp giữa mức stop và giá thị trường" đã bị RÚT** — lệnh dừng đã bị vượt thì
thành lệnh thị trường, mà lệnh thị trường không khớp tốt hơn giá thị trường. Đó là phép nội
suy tôi bịa ra, không phải kịch bản vật lý.

---

## 4. Hậu quả với các con số đang công bố

Chạy qua đúng đường sinh ra chúng (`deploy_sim`, có sizing + cap + breaker).
**Mỏ neo: mọi cờ tắt thì tái tạo đúng bốn số ghim tới từng đồng — đã PASS nhiều lần.**

| mốc trong INVARIANTS | đang công bố | quy ước engine + sửa | luật live + sửa |
|---|---|---|---|
| baseline | **$42.459 · Calmar 1,72** | −$2.240 · −0,05 | **$3.716 · 0,09** |
| sàn suy giảm fit_A | **1,65** | **−0,07** | 0,07 |
| vault 2023-2024 | **2,86** | 0,14 | **4,11** |
| vault 2025 | **2,54** | −0,00 | **1,11** |

**Đọc đúng bảng này:**

- Con số triển khai được của hệ hiện tại là cột **luật live + sửa** — vì đó là luật live thật
  sự chạy (hoãn stop, stop cố định không ratchet).
- **Hai vault vẫn dương và mạnh** (4,11 và 1,11). Toàn kỳ thì phẳng vì 2021–2022 âm.
- **Cổng suy giảm hỏng**: sàn −0,07 so với baseline 0,09 — hai số không phân biệt được nhau,
  nên cơ chế theo dõi suy giảm mất khả năng phát hiện. Đây là chuyện khác với "hai vault qua".
- **[ĐO] Dưới mốc so, hệ tự tắt sau 2022**: phanh nổ 1.072 lần, bảng theo năm dừng ở 2022,
  2023 và 2024 không có giao dịch nào. **[CHƯA KIỂM]** phanh có nhả ra không.

---

## 5. Hai đặc điểm cấu tạo tìm thấy trên đường đi

**[ĐO] Khoảng cách stop không phải đại lượng được thiết kế.**
`calculate_chandelier_stop` neo vào **cực trị của cây nến vào lệnh**, không neo vào giá vào:
`SHORT: stop = min(low của nến) + 2,5 × ATR5`. Nên khoảng cách thật từ giá vào
= băng ATR **trừ** vị trí giá vào trong chính cây nến đó.

Đo trên 3.356 tín hiệu: tỷ lệ khoảng-cách-thật / băng có trung vị 0,777, p10 0,395,
**p01 âm**. Rủi ro thật mỗi lệnh: trung vị **$33**, p10 $14, p90 $84 — chênh 6 lần giữa các
lệnh. Và **42 lệnh (1,25%) có stop rơi sang phía CÓ LÃI** — với lệnh bán thì stop nằm dưới
giá vào, tức không còn là điểm dừng lỗ. NKD tệ hơn: 25/981 = 2,55%.

So sánh: bộ sizing phân bổ vốn giả định rủi ro mỗi hợp đồng = `2,5 × ATR NGÀY × point_value`
= trung vị **$722**, tức **gấp 21 lần** khoảng cách stop thật.

**[ĐO] Chiều của cây nến vào lệnh không bị ràng buộc.** Hướng lệnh quyết định bởi nến
*pullback* (đóng ở phía nào của EMA); giá vào lấy ở nến *resume*; không có gì buộc hai bước
đó. 45,9% tín hiệu có nến resume chạy ngược chiều lệnh.

**ĐÍNH CHÍNH — đây KHÔNG phải khuyết tật giao dịch.** Docstring gọi nó là *"the bar where
price moved back in trend direction"* nên code lệch tài liệu — đó là sự kiện. Nhưng bán khống
ở nến tăng thì khớp ở **giá cao hơn**, tức giá vào **tốt hơn** cho lệnh đó, và lọc bỏ chúng
làm mất $7.256 ở tầng deploy. **Thứ cần sửa ở đây là tài liệu, không phải code.**
Hệ quả đáng chú ý duy nhất là nó sinh ra hình học stop ở trên.

---

## 6. Mọi cách sửa đã thử — không cách nào sống sót

Tất cả đo ở **tầng deploy**, mốc so = luật live + sửa khớp lệnh = $3.716 · 0,09.

| thử gì | baseline IS | vault 2023-24 | **vault 2025** |
|---|---|---|---|
| **mốc so** | $3.716 · 0,09 | $17.943 · 4,11 | $4.998 · 1,11 |
| quét tới nến resume đúng chiều (A) | $12.832 · 0,24 | $13.649 · 3,26 | $2.493 · 0,44 |
| mức dừng thảm hoạ 2× (D) | $10.967 · 0,20 | $6.401 · 1,15 | $1.006 · 0,23 |
| A + D | −$2.313 · −0,05 | — | — |
| lọc bỏ nến sai chiều | −$3.540 · −0,10 | — | — |
| stop neo vào giá vào (B) | $2.991 · 0,07 | — | — |

**A và D đều tốt lên trong mẫu và xấu đi ở cả hai vault.** Không áp dụng cái nào.

**[ĐO] A tự sửa luôn hình học stop**: stop sai phía 42 → 2, p01 tỷ lệ từ −0,052 lên +0,503,
băng bị ăn 22% → 11%. Nên hai đặc điểm ở mục 5 thực ra là một. Nhưng ép thêm "stop hoàn hảo"
lên trên A thì xấu đi ($10.779 < $12.832).

---

## 7. Vì sao không ai phát hiện

**[ĐO] Bốn trên năm đợt đối soát so hệ với chính nó.** `reconcile_gd0` tự viết
*"true by construction"*; `reconcile_nkd` *"proves the class interface is wired correctly"*.
Hai vế cùng gọi `backtest_swing_tf` nên cùng mang một luật khớp lệnh — khớp nhau tới từng xu
là tất yếu và không mang thông tin về tính đúng. Đợt duy nhất có nguồn ngoài là đối soát với
sao kê IBKR, chỉ tồn tại 8 ngày paper với 2 lần stop nổ.

**[ĐO] Giả định đã được đăng ký nhưng giao sai phép kiểm.** `ASSUMPTIONS.md` ghi
`Fill rate ~100% (fill-at-price)` và giao kiểm bằng "đo tỷ lệ trượt lệnh". Lệnh vẫn khớp
100%; phép kiểm đó không thể đỏ trước một lỗi về **giá** khớp.

**[ĐO] Cột đến gần nhất đo nhầm đại lượng.** Cột `>2×` trong `model_activation_sweep` ghi là
"hai lần khoảng cách stop" nhưng tính `2 × trung vị của chính mẫu`.

**[ĐO] Triệu chứng đã hiện một lần và bị đọc sai loại.** Ghi chú `_ARM_BY_CLUSTER` chép rằng
vũ trang lúc 17–18h ET làm tỷ lệ thoát GAP vọt 6%→40% và P&L sụp +$128.863→−$1.091. Đó chính
là lỗi này, lộ ra vì giờ nghỉ phiên bật cờ `isg`. Nó được kết luận thành ràng buộc về **lịch
chạy**, không thành câu hỏi về **cách định giá lệnh thoát**.

**Lý do sâu nhất**: lỗi làm mô hình **tự nhất quán**. P&L, MaxDD, Calmar, PF, Sharpe, bảng
theo năm — tất cả tính TỪ giá thoát, nên sai cùng chiều, đều đặn, ở mọi lát cắt. Không có mâu
thuẫn nội bộ nào để vấp phải. Chỉ nguồn bên ngoài mới bắt được, và nguồn đó chỉ có 8 ngày.

---

## 8. Còn mở

**[CHƯA KIỂM] Phanh có nhả không** sau khi hệ tự tắt năm 2022. Quyết định cách đọc mọi con số
ở cột mốc so. Rẻ để kiểm.

**[CHƯA KIỂM] Nhánh HALT chưa bao giờ chạy thật** (INVARIANTS: 0 lần trong 7 năm). Dưới cách
tính đúng nó thành cơ chế điều khiển chính.

**[CHƯA KIỂM] `place_stop` không kiểm mức giá** trong khi `repair_stops` có — bảo vệ tồn tại
nhưng chỉ ở một trong hai đường đặt lệnh. Và `_await_stop_accepted` xếp `Filled` vào nhóm
"chết", nên một stop khớp ngay bị ghi là đặt thất bại.

**[CHƯA KIỂM] Hành vi broker** khi đặt STP vào thị trường đã đi qua: khớp thị trường hay bị
từ chối? Paper có **0 quan sát** (10 lần đặt, tất cả PreSubmitted). Nhịp hiện tại ~0,8 lần
vũ trang/ngày nên cần hàng tháng.

**[CHƯA KIỂM] Kết quả 1 hợp đồng không mang sang deploy** — đã chứng minh hai lần, hai chiều
ngược nhau. Mọi kết luận dẫn xuất ở 1 hợp đồng cần đo lại: quét ratchet, quét độ rộng stop,
quét giờ vũ trang, lưới WFO 60 ô, quét mức thảm hoạ.

**[CHƯA KIỂM]** `_roll_stop`; đường thoát của STRESS_MID (runner ghi rõ `reconcile_stress`
chỉ phủ quyết định VÀO lệnh); `basket.py REGIME["allowed_regimes"]` là cấu hình chết không
được đọc ở đâu.

---

## 9. Công cụ

`scratch/harness.py` — chạy engine production với các bản sửa bật/tắt bằng cờ. **Không sao
chép dòng mã engine nào.** Cổng mỏ neo chạy trước mọi thứ và thoát nếu không tái tạo được
bốn số ghim.

```powershell
$env:PYTHONIOENCODING="utf-8"
python scratch\harness.py --anchor
python scratch\harness.py --deploy --arm 14.0833 --no-ratchet --fix-fill --all-sleeves
python scratch\harness.py --selfcheck        # bo quet tin hieu vs build_sig_cache
python scratch\verify_one.py --inst MNQ --date 2022-05-12
```

---

## 10. Việc đề nghị

1. **Chú thích vào `INVARIANTS.md`** rằng bốn con số đang ghi được đo bằng luật khớp lệnh có
   khuyết tật, kèm lệnh tự kiểm. Rẻ nhất, và ngăn phiên sau xây tiếp lên nền cũ.
2. **Kiểm phanh có nhả không** — ẩn số vận hành lớn nhất còn lại.
3. **Ghi nhật ký giá thị trường tại thời điểm đặt STP** — biến ẩn số cuối thành số đo được.
   Đụng đường live nên cần quyết định riêng.
4. Đo lại các đòn bẩy ở **tầng deploy** trước khi tin bất kỳ kết luận nào từ 1 hợp đồng.
