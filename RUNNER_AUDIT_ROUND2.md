# Rà soát vòng 2 — các bản sửa runner futures

**Ngày:** 2026-08-16 (Chủ nhật; máy ở Calgary, giờ ET dùng cho mọi mốc thị trường)
**Phạm vi:** 17 commit `5182b8b..63c63da` trên `future/incorporation`, đối chiếu với ba
bản rà đã đóng (runner · paper dashboard · realtime dashboard).
**Chế độ:** CHỈ ĐỌC. Không sửa một dòng code, cấu hình hay state file nào. Không kết nối
IBKR. Không xoá parquet. Tệp duy nhất được tạo là chính tệp này.

**Cây đo:** `git worktree --detach` tại HEAD `63c63da` ở `C:\tmp\raits_r2_head`, **không**
phải working tree. Mọi script đo đều mang dòng
`assert module.__file__.startswith(WT)` để tự chứng minh nó đọc đúng cây.

---

## 0. Kết luận trong một trang

Trong 26 mục được khai là đã đóng (22 mục của bản rà gốc cộng bốn mục phát sinh), tôi
**xác nhận đóng 19**, **đóng một phần 4**, và **một mục có tiền đề sai** — con số ngưỡng
được hiệu chuẩn trên một đại lượng khác với đại lượng nó đang canh. Hai mục còn lại là
"để lại theo quyết định chủ dự án", tôi xác nhận cả hai thật sự bằng 0 hôm nay.

Suite ở HEAD với đủ dữ liệu: **848 xanh, 0 đỏ** — đúng con số đề bài. Và các phép kiểm mới
**không xanh vì lý do khác**: tôi gỡ sáu cơ chế trong tiến trình, cả sáu lần đều đúng phép
kiểm được cho là canh nó chuyển đỏ.

Đợt sửa **tạo ra một lỗi mới**: một phép kiểm sẽ tự chuyển sang đỏ vĩnh viễn kể từ
**04/9/2026** — đúng ngày chuyển hợp đồng Nikkei, tức đúng ngày cơ chế mà nó canh mới có
việc để làm.

> **Trạng thái đọc ngày 17/8, sau đợt sửa — đọc trước phần dưới.** Bảy chỗ hở mục 3 nay
> còn **một**: sáu đã đóng và một bị **rút lại vì không phải lỗi** (đường lấy bar, mục
> 3.8 — splice tính lại mốc neo mỗi lượt nên chênh lệch đổi hợp đồng bị hấp thụ trọn).
> Mục còn lại là ngưỡng đối soát $250, **chặn bởi dữ liệu chứ không bởi công sức**.
> Phần thân bên dưới giữ nguyên như lúc rà — nó là bản ghi lịch sử. Chi tiết từng mục
> ở §11.

Và vòng này tìm thêm **sáu chỗ hở chưa ai chạy qua**, trong đó nghiêm trọng nhất là:
**suốt ngày chuyển hợp đồng, mọi lệnh gửi đi đã trỏ sang tháng mới ngay từ 00:00 giờ ET,
trong khi vị thế chỉ thực sự được chuyển lúc phiên chính chạy — 01:10 với Nikkei, 14:05
với Rổ 4.** Lệnh đóng theo hạn nắm giữ chạy lúc 09:31 và sáu lượt quét sửa stop trong đêm
đều rơi vào khoảng hở đó. Với Rổ 4, khoảng hở là **14 tiếng**, và lần tới là **11/9/2026**.
Đây chính là hình dạng của lỗi C1, sống sót bên trong bản sửa C1.

---

## 1. Trả lời bốn câu hỏi được đặt riêng

### 1.1 Cơ chế duy nhất có quyền TỪ CHỐI gửi lệnh — nó có bắn nhầm không?

**Không bắn nhầm. Nhưng nó cũng không thể bắn được, trên lịch chạy hiện tại.**

Cơ chế so hai câu trả lời cho câu hỏi "hợp đồng tháng nào": một lấy theo **ngày phiên đang
xử lý**, một lấy theo **đồng hồ tường lúc gửi lệnh**. Lệch nhau thì từ chối.

Đo trên HEAD, hôm nay:

```
ngày phiên == ngày ET hiện tại (2026-08-16):  0/7 mã bị chặn
```

Quét tiếp: chỉ cần **lệch một ngày** là nó bắn, và chỉ bắn khi cặp ngày đó vắt qua một mốc
chuyển hợp đồng — ví dụ phiên 03/9 xử lý dưới đồng hồ 04/9 (Nikkei), hay phiên 10/9 dưới
đồng hồ 11/9 (Rổ 4).

Vấn đề là **không có đường nào trong production tạo ra độ lệch đó**:

- Ngày phiên được lấy bằng `giờ ET hiện tại` ngay khi tiến trình khởi động, rồi truyền
  xuống. Không có tham số dòng lệnh nào cho phép chạy bù một ngày quá khứ.
- Nên hai đồng hồ chỉ tách nhau nếu **ngày ET đổi giữa chừng một lượt chạy**.
- Trần thời gian một tiến trình con là **20 phút**, hạn trễ lịch là **5 phút**. Slot muộn
  nhất trong ngày là lượt quét sửa stop lúc **22:20 ET** → kết thúc chậm nhất **22:45 ET**.
  Không slot nào chạm nửa đêm.
- Lượt quét sửa stop không đi qua đường này (nó không gọi phiên chạy chính).

**Kết cục:** cơ chế được nối đúng chỗ (hai điểm gửi lệnh, có phép kiểm canh chỗ nối), không
thể chặn nhầm, và cũng **không thể phát hiện được gì** vì kịch bản nó mô tả — "chạy bù hoặc
phát lại vắt qua mốc chuyển hợp đồng" — không có đường sinh ra trong hệ hiện tại. Nó là một
người gác đúng cửa nhưng cửa đó đã bị xây bịt.

**Hai đầu vào bất thường thì nó xử lý sai:**

| Ngày phiên truyền vào | Kết quả |
|---|---|
| `None`, chuỗi rỗng, `0` | im lặng — đúng |
| `NaT` (ngày không xác định) | **bắn, và báo tháng 202703** — vì so chuỗi `"2026-03-13" <= "NaT"` luôn đúng, nên nó nhận nhầm mốc chuyển cuối bảng |
| chuỗi không phải ngày | **ném lỗi phân tích ngày**, loại lỗi khác với loại mà đường gọi bắt |

Đường gửi lệnh có `try/except` bao ngoài nên biến nó thành một lệnh hỏng có kiểm soát.
Đường chuyển hợp đồng **không có**, và nó chạy trong vòng lặp trên từng vị thế mở, ngoài
mọi `try` — nên một lần ném lỗi ở đó **giết cả phiên**, kể cả các lệnh đóng của những vị
thế khác. Cả hai đều thuộc nhóm *chưa ai chạy qua*.

### 1.2 Chuẩn hoá tháng hợp đồng trên bản ghi khớp lệnh — giả định có đúng không?

**Giả định chưa được đo, và cái tên đang gọi hai đại lượng khác nhau.**

Quy tắc hiện tại: nếu giá trị là chuỗi toàn chữ số dài hơn 6 ký tự thì cắt lấy 6 ký tự đầu.
Ý định: `"20260911"` → `"202609"`.

Tôi tìm khắp repo, log vận hành và mọi artifact JSON: **không có một bản ghi nào lưu lại
giá trị thật mà môi giới trả về.** Hai "bằng chứng" mà bản sửa dẫn ra đều không phải quan
sát:

- một script so bằng `.startswith` — đó là *cách viết phòng xa*, không phải giá trị đo được;
- một script khác truyền vào `"20260910"` — đó là **đầu vào do repo tự viết**, không phải
  đầu ra của môi giới.

Đo các giá trị biên:

| Vào | Ra | Nhận xét |
|---|---|---|
| `"20260911"` | `"202609"` | đúng ý định |
| `"202609"` | `"202609"` | luỹ đẳng — đúng |
| `"20261120"` | `"202611"` | **sai tháng** nếu ngày giao dịch cuối rơi vào tháng trước tháng hợp đồng |
| `"2026091"` (7 chữ số) | `"202609"` | cắt một giá trị dị dạng thay vì để nguyên — trái với chính lời hứa trong tài liệu của hàm |
| `""` | `""` | rỗng đi thẳng vào sổ; và thư viện môi giới mặc định trả chuỗi rỗng chứ không phải `None`, nên nhánh dự phòng `None` là code chết |
| `202609` (số nguyên) | `202609` | giữ nguyên kiểu số → mọi phép so với chuỗi đều trượt |

Dòng `"20261120"` là điểm cốt lõi: phép cắt đang tính **tháng của ngày giao dịch cuối**, rồi
lưu nó dưới cái tên **tháng hợp đồng**. Với sáu mã hiện tại hai đại lượng trùng nhau, nên
hôm nay không sai. Nó sẽ sai ở mã đầu tiên không có tính chất đó.

> **ĐO ĐƯỢC 16/8 11:27 ET — giả định này nay đã có bằng chứng.** Bộ đọc bảng điều khiển
> đang chạy giữ giá trị **nguyên dạng** từ `reqContractDetails`, và nó đọc được qua một
> endpoint chỉ lấy cache trong bộ nhớ, không gọi thêm gì tới môi giới:
>
> ```
> connected=True   observed_at=2026-08-16T15:27:13Z   age=0.7s
>   M2K   local=M2KU6   lastTradeDateOrContractMonth = 20260918
>   MES   local=MESU6                                  20260918
>   MNQ   local=MNQU6                                  20260918
>   MYM   local=MYMU6                                  20260918
>   MNKD  local=MNKU6                                  20260910
>   NKD   local=NKDU6                                  20260910
> ```
>
> Ba điều được chốt:
> 1. **Môi giới thật sự trả 8 chữ số YYYYMMDD** — không còn là suy ra từ mã trong repo.
> 2. **Phép cắt cho đúng kết quả với cả sáu mã**: `20260918 → 202609`, `20260910 → 202609`,
>    và cả sáu đều là hợp đồng tháng 9 (hậu tố `U6`). Tháng ngày-giao-dịch-cuối trùng tháng
>    hợp đồng ở đây, nên quy tắc cắt an toàn **cho rổ hiện tại** — đã đo, không phải giả định.
> 3. **Hai cách viết cùng tồn tại là chuyện thật, không phải giả thuyết.** Ngay lúc này bảng
>    điều khiển đang công bố `20260918` dưới tên `contract_month`, còn sổ vị thế sẽ ghi
>    `202609` dưới đúng cái tên đó.
>
> Vẫn là *suy ra chứ chưa đo* một bước cuối: đường khớp lệnh đọc trường này sau
> `qualifyContracts`, còn phép đo trên đi qua `reqContractDetails`. Hai lời gọi khác nhau
> trên cùng một nguồn — thư viện lấy trường đã giải từ chính `ContractDetails` — nên gần như
> chắc trùng, nhưng chưa quan sát trực tiếp.
>
> Đính chính bản gốc: bản rà runner ghi *"MNKU6 hết hạn 11/9"*. Môi giới nói **10/9**. Và
> hợp đồng Rổ 4 hết hạn **18/9**, tức mốc chuyển 11/9 nằm **một tuần trước** hạn chứ không
> sát hạn.

**Và bản sửa chỉ chuẩn hoá được một trong hai nơi sinh ra trường này.** Bộ đọc phục vụ bảng
điều khiển lấy cùng một trường từ môi giới và ghi **nguyên dạng 8 chữ số**, dưới **đúng cái
tên `contract_month`**. Nên trên cùng một trang, sổ vị thế nói `202609` còn khối thông số
hợp đồng nói `20260911`. Hôm nay không ai đối chiếu hai chỗ đó, nên chưa gây hại — nhưng
đây đúng là khuyết tật mà tài liệu của bản sửa nói nó tồn tại để ngăn, chỉ là ngăn ở một nửa.

### 1.3 Đệm khoá cho mọi dòng đóng lệnh — có consumer nào hỏng không?

**Không. Đã kiểm hết, và câu trả lời là phủ định có bằng chứng.**

Tôi quét mọi bên đọc nhật ký giao dịch (bốn bộ đọc của bảng điều khiển, bộ đối soát sao kê,
bộ dựng lịch sử) tìm chỗ phân biệt "khoá vắng" với "khoá null":

- Mọi bên đọc đều dùng `.get(...)` kèm `or`, tức **null và vắng cho cùng kết quả**.
- Chỗ duy nhất trong toàn hệ thật sự phân biệt `undefined` với giá trị rỗng nằm ở giao diện,
  và nó đọc **ảnh chụp vị thế**, không đọc nhật ký giao dịch. Phép đệm không chạm tới đó.

Đo lại hình dạng sau khi đệm: **5 bên ghi dòng đóng lệnh, cả 5 đều đủ 22 trường** (23 khoá
trên đĩa, kể cả dấu thời gian). Dòng mở lệnh cố ý không đệm, và có phép kiểm đối chứng canh
điều đó.

**Ba nhận xét còn lại:**

1. **Tháng hợp đồng không nằm trong bộ 22 trường.** Sổ vị thế nay ghi được tháng, nhật ký
   giao dịch thì không. Bộ đối soát với sao kê của môi giới ghép cặp bằng
   `(mã, ngày vào, ngày ra)` — không có tháng — nên đúng cái điểm mù mà C1 từng sống trong
   đó vẫn còn nguyên ở phía nhật ký.
2. **Thứ tự khoá trong mỗi dòng đổi theo từng tiến trình.** Bộ khoá được lưu dưới dạng tập
   hợp không thứ tự, và Python xáo hàm băm chuỗi mỗi lần khởi động. Mỗi slot cron là một
   tiến trình mới, nên các dòng viết cùng ngày có thứ tự trường khác nhau. Đo: ba lần chạy
   liên tiếp cho ba thứ tự khác nhau. Chỉ gây khó đọc, không sai số.
3. Xem mục 2 — H4: có một đường ghi ra dòng đủ 22 trường mà **hai bên đọc quan trọng nhất
   vẫn vứt đi**.

### 1.4 Ngưỡng đối soát tài khoản 250 đô — đo lại

**Không có dữ liệu mới** (log cuối cùng là 14/8; 15 và 16/8 là cuối tuần), nhưng đo lại
chính dữ liệu cũ thì phát hiện ngưỡng được dựng trên **một đại lượng khác** với đại lượng
nó đang canh.

Bộ phân tích của tôi tái tạo đúng con số bản gốc công bố (đây là điều kiện để tin nó):

```
                       n   trung vị      p99       max    >$100
bản gốc ghi  trước   238       5.72   889.58   2455.00     28
tôi đo lại   trước   238       5.72   889.58   2455.00     28
bản gốc ghi   sau     29       2.83    84.51     84.51      0
tôi đo lại    sau     29       2.83    84.51     84.51      0
```

Bốn trên năm thống kê trùng tới từng xu. Riêng p90 lệch (bản gốc 143,42 · tôi 136,12) — đó là
khác cách nội suy phân vị, không phải khác dữ liệu, vì mọi con số còn lại đều trùng tuyệt đối.
Lần chạy đầu tiên của bộ phân tích chỉ đọc được **207/267** dòng vì có hai thế hệ định dạng
log; tôi chỉ dùng nó sau khi nó đọc đủ 267 và dựng lại đúng bảng trên.

Nhưng phân bố trên là của **mức dịch chuyển toàn tài khoản**. Cái mà cổng thật sự so với
250 là **phần dư** = mức dịch chuyển tài khoản − phần sleeve đã ghi sổ trong cùng lượt chạy.
Tái dựng phần dư từ chính các dòng log (chúng in cả số dư sleeve):

```
trong 29 quan sát dùng để đặt ngưỡng, số lượt mà sleeve GHI SỔ khác 0:  0 / 29
trong toàn bộ 206 lượt tái dựng được, số lượt ghi sổ khác 0:            2 / 206
     10/8  tài khoản -2455.00, sleeve ghi  +162.00, phần dư -2617.00
     11/8  tài khoản  -889.58, sleeve ghi   +66.75, phần dư  -956.33
```

Nghĩa là: **cửa sổ hiệu chuẩn không chứa một quan sát sạch nào của đúng tình huống mà cổng
sinh ra để đánh giá.** Trên cả 29 lượt, phần dư bằng đúng mức dịch chuyển, vì không có lệnh
nào đóng. Câu "250 là gấp ba lần quan sát sạch lớn nhất" chỉ đúng cho **những ngày không
giao dịch**. Đây không phải "n=29 hơi mỏng" — đây là **n=0 cho trường hợp quan trọng**.

Hai hệ quả:
- Ngưỡng không nới ra được bằng dữ liệu hiện có, vì các log cũ **không in phần sleeve ghi
  sổ trong lượt**, chỉ in số dư luỹ kế. Muốn hiệu chuẩn đúng thì phải chờ log mới.
- Cổng này **chưa chạy một lần nào** trong đời thật: 0 dòng cảnh báo trong toàn bộ nhật ký.
  Đó là *chưa đo*, không phải *đã đo và không sao*.

Điểm đáng ghi nhận: nếu đã tồn tại, cổng sẽ bắt được **cả hai** lần lệch thật (ngày 10 và
11/8), và bắt bằng phần dư còn to hơn mức dịch chuyển thô — tức chọn phần dư làm đại lượng
là **đúng**. Chỉ có con số là chưa được dựng trên nó.

---

## 2. Từng mục đã khai đóng

Nhãn: **XÁC NHẬN ĐÓNG** (có phép đo) · **ĐÓNG MỘT PHẦN** · **KHÔNG ĐÓNG** · **TIỀN ĐỀ SAI**.

| Mục | Kết cục vòng 2 | Bằng chứng đo được |
|---|---|---|
| **C1** — Nikkei không bao giờ chuyển hợp đồng | ✅ **XÁC NHẬN ĐÓNG** | Quét cả năm 2026: mã Nikkei của runner nay trả **4 ngày chuyển** (06/3, 05/6, 04/9, 04/12), khớp từng ngày với tên IBKR và tên đầy đủ; 04/9 trả cặp `202609 → 202612`. Bốn mã Rổ 4 vẫn đúng 4 ngày như cũ — đối chứng không đổi |
| **C2** — lệnh vào bị huỷ để lại vị thế ma | ✅ **XÁC NHẬN ĐÓNG** | Nhánh xử lý nay bắt mọi trạng thái không phải khớp/khớp một phần, gỡ vị thế khỏi sổ và phát sự kiện; sổ được ghi xuống đĩa ở cuối lượt chạy. Phép kiểm hỏi cả ba: sổ rỗng, đĩa rỗng, có sự kiện — cộng một phép kiểm riêng chứng minh **ngày hôm sau không có lệnh đóng nào đi ra** |
| **H1** — bốn nơi tự dựng hợp đồng | ⚠️ **ĐÓNG MỘT PHẦN** | Trong tệp môi giới, đúng **một** nơi dựng hợp đồng, có bất biến cú pháp canh và bất biến đó tự kiểm locator. Nhưng bộ đọc phục vụ bảng điều khiển **vẫn dựng hợp đồng thứ năm bằng tay**, nằm ngoài phạm vi bất biến: nó không kiểm mã định danh trả về, truyền thêm loại tiền tệ mà nơi kia không truyền, và chính nó sinh ra cách viết tháng thứ hai (xem 1.2) |
| **H2** — công tắc dừng khẩn cấp không nối vào đâu | ✅ **XÁC NHẬN ĐÓNG** | Tên tệp khai một lần, ba entry point đều truyền, **và tham số có giá trị mặc định thật** — nên công tắc sống kể cả khi người vận hành không thêm cờ. Cổng chặn xoá danh sách ứng viên vào lệnh **trước** khâu ra quyết định, nên phủ cả hai loại lệnh vào; lệnh ra không bị chạm. Tệp công tắc không tồn tại trên đĩa và không bị git bỏ qua |
| **H3** — cổng đóng băng lại là hằng số | ✅ **XÁC NHẬN ĐÓNG** | Đọc thẳng đường dẫn cờ từ module sở hữu nó; **hỏng file → báo là đang chờ xử lý** (đóng theo chiều an toàn), vì bên đọc ánh xạ giá trị rỗng thẳng sang "ổn" |
| **H4** — đường đóng lệnh book tiền mà không ghi sổ | ⚠️ **ĐÓNG MỘT PHẦN** | **6/6** nơi chuyển tiền vào sổ vốn nay đều ghi một dòng — đã dò bằng cú pháp, không sót. **Nhưng** đường ghi khi môi giới đã quên bản ghi khớp lệnh đặt **ngày ra = rỗng**, và cả hai bên đọc quan trọng đều lọc theo ngày ra. Đo trực tiếp: dòng đó **không được đếm là một lần thoát bằng stop**, và bộ đối soát sao kê ghép cặp bằng khoá có chứa ngày ra nên **không bao giờ khớp được**. Tiền đã vào sổ vốn, dòng đã tồn tại, cổng vẫn mù |
| **H5** — không có trần thời gian cho một slot | ✅ **XÁC NHẬN ĐÓNG** (kèm hai lưu ý) | Trần 20 phút có thật, bắt đúng ngoại lệ hết giờ, và phần mô tả "chồng một nhịp" vs "phiên đã chết" được tách thành hàm thuần nên kiểm được cái nó *quyết định*. Lưu ý 1: ngưỡng "đã kẹt" đặt ở 25 phút, **cao hơn trần giết tiến trình**, nên nhánh đó gần như không thể chạm tới — chính chú thích trong code thừa nhận nó chỉ dành cho trường hợp lệnh giết không ăn. Lưu ý 2: xem mục 3.6 |
| **M1** — khớp một phần | ⏸️ ĐỂ LẠI (chủ dự án chốt) — xác nhận bằng 0 hôm nay | |
| **M2** — báo stop mồ côi sai sự thật | ✅ **XÁC NHẬN ĐÓNG** | Hỏi trạng thái lệnh trước khi kết luận; bốn kết cục tách bạch, trong đó "không tìm thấy" trả về **chưa xác minh** thay vì khẳng định. Có hai phép kiểm đối chứng giữ cảnh báo thật |
| **M3** — ghép bản ghi khớp lệnh chỉ bằng số lệnh | ✅ **XÁC NHẬN ĐÓNG** | Lọc thêm theo mã hợp đồng, và **từ chối đoán** khi còn nhiều ứng viên. Cả hai nơi gọi đều truyền mã — có phép kiểm cú pháp canh chỗ nối, kèm tự kiểm locator. Lưu ý cho trục tăng quy mô: một lệnh khớp làm nhiều lần cũng rơi vào nhánh "nhiều ứng viên" và bị từ chối, tức lùi về giá ước lượng dù bản ghi thật đang có trong tay |
| **M4** — hai đồng hồ quyết định tháng hợp đồng | ⚠️ **ĐÓNG MỘT PHẦN** | Xem 1.1. Không chặn nhầm (đo: 0/7 mã hôm nay), nhưng cũng không có đường nào kích hoạt được nó trên lịch hiện tại; cộng hai đầu vào bất thường xử lý sai |
| **M5** — mức dịch chuyển tài khoản đo rồi vứt | ❌ **TIỀN ĐỀ SAI** (cơ chế đúng, con số chưa có cơ sở) | Xem 1.4. Chọn phần dư làm đại lượng là đúng và sẽ bắt được cả hai sự cố đã biết; nhưng 250 lấy từ phân bố của **mức dịch chuyển thô**, và cả 29 quan sát hiệu chuẩn đều rơi vào ngày sleeve **không ghi sổ đồng nào** |
| **M6** — bốn trường vận hành là hằng số | ✅ **XÁC NHẬN ĐÓNG** | Hai trường sụt vốn nay là **cực đại luỹ tích thật**, được ghi xuống đĩa trong khối trạng thái và nạp lại khi khởi động — thiếu bước đó thì "cực đại mọi thời" reset mỗi 5 phút. Số ngày đếm **ngày phân biệt**. Trạng thái kết nối giữ "không biết" khi môi giới không trả lời được, thay vì khai "mất kết nối" |
| **L1** — hai khoá thừa trong bảng chuyển hợp đồng | ✅ **XÁC NHẬN: bác bỏ là đúng** | Đo lại: bộ đọc bảng điều khiển duyệt đúng **6 mã, có mã Nikkei đầy đủ**, và tra tháng cho mã đó trả `202609`. Xoá hai dòng ấy sẽ làm hợp đồng thiếu định danh |
| **L2** — sàn Calmar không bị ràng buộc | ✅ **XÁC NHẬN ĐÓNG** | Phép kiểm đọc tài liệu chủ quản và so với hằng số, **tự kiểm biểu thức dò trước** — locator hỏng thì đỏ, không xanh |
| **L3** | ⏸️ ĐỂ LẠI (chủ dự án chốt) | |
| **L4** — hoàn lại khoản đã ghi khi lệnh đóng hỏng | ✅ **XÁC NHẬN ĐÓNG** | Khoản lãi/lỗ được trừ lại đúng lúc khôi phục vị thế. Chú thích của chính bản sửa nói thẳng: **tác động ở đường live bằng 0**, nó chỉ đúng ở đường xác minh — nên đây là sửa cho tính nhất quán, không phải cho tiền |
| **§4.1** — phép kiểm kịch bản C2 không assert gì | ✅ **XÁC NHẬN ĐÓNG** | Nay hỏi ba câu độc lập cộng một phép kiểm riêng cho ngày hôm sau |
| **§4.2** — cổng đóng băng lại không có phép kiểm đỏ được | ✅ **XÁC NHẬN ĐÓNG** | Phép kiểm đi hết đường tới chỗ công bố, không dừng ở hàm phụ |
| **§4.3** — bảng lịch chuyển thiếu mã Nikkei của runner | ✅ **XÁC NHẬN ĐÓNG** | Bốn dòng mới trong bảng tham số |
| **§4.4** — không phép kiểm nào chạm đường chuyển hợp đồng thật | ✅ **XÁC NHẬN ĐÓNG** (kèm lưu ý) | Ba phép kiểm gỡ đường tắt chế độ thử và chạy đúng hàm thật. Lưu ý: chúng **tắt cơ chế từ chối ở mục 1.1** bằng monkeypatch — có ghi lý do trong code và đúng nguyên tắc "một phép kiểm không nên canh hai thứ", nhưng nghĩa là đường chuyển hợp đồng **chưa từng được chạy cùng cơ chế từ chối đang bật** |
| **§4.5** — công tắc dừng không có phép kiểm nào | ✅ **XÁC NHẬN ĐÓNG** | Ba phép kiểm cú pháp trên từng entry point (khuyết tật là *một tham số bị quên*, không assert runtime nào thấy được) cộng hai phép kiểm hành vi **có đối chứng** — và đối chứng là thứ đã bắt được một lỗi thật trong chính phép kiểm kia |
| **Trường tháng hợp đồng** (phát sinh) | ⚠️ **ĐÓNG MỘT PHẦN** | Trường chạy thông từ khớp lệnh → sổ → đĩa → bảng điều khiển, có phép kiểm chứng minh khâu ra quyết định **không đọc** nó, và có phép kiểm tương thích ngược với file cũ. Nhưng: nhật ký giao dịch không có trường này; bộ đọc bảng điều khiển công bố cùng tên ở dạng khác; và quy tắc chuẩn hoá chưa được đo (1.2) |
| **Hợp nhất hình dạng dòng đóng lệnh** (từ audit paper) | ✅ **XÁC NHẬN ĐÓNG** về hình dạng | 5/5 bên ghi đủ 22 trường; dòng mở lệnh không bị đệm, có đối chứng. Ba nhận xét ở 1.3 |
| **Phép kiểm khoá slot kiểm bản sao** | ✅ **XÁC NHẬN ĐÓNG** | Đã tách thành hàm cấp module và bên chạy thật gọi đúng nó — phép kiểm và production nay chạy chung một đoạn mã |
| **43 phép kiểm không thể đỏ** | ✅ **XÁC NHẬN ĐÓNG, và xác nhận là zero bug** | Quét độc lập bằng cú pháp trên **56 tệp kiểm / 756 hàm kiểm cấp module**: **0 tệp có thể làm hỏng khâu thu thập**. Về khả năng đỏ, chia ba nhóm và không nhóm nào hở: 695 hàm có `assert` trực tiếp · 60 hàm dùng bộ ghi nhận nhưng **có móc cưỡng chế** trong cùng tệp (bốn tệp, và mutation ở mục 4 chứng minh móc đó hoạt động thật) · 1 hàm không có cả hai, và nó thuộc dạng "chạy không được ném lỗi" — vẫn đỏ được. Bản gốc ghi đúng rằng bật 43 phép kiểm ấy lên không tìm ra lỗi nào, và không tính nó là chiến công |

---

## 3. Chỗ hở tìm được ở vòng 2

Xếp theo hậu quả nếu chạm phải. Mục 3.2 là **đã xác minh** — tôi tái lập được nó bằng cách
dịch đồng hồ. Sáu mục còn lại thuộc nhóm **chưa ai chạy qua**: chúng đến từ đọc mã và từ
bảng lịch, không từ một lần hỏng thật.

### 3.1 Khoảng hở 14 tiếng của ngày chuyển hợp đồng — nghiêm trọng nhất

Ngay khi ngày ET bước sang ngày chuyển hợp đồng, hàm trả "tháng đang giao dịch" **đã trả
tháng mới**. Đo trên bảng lịch:

```
mã Rổ 4, ngày 2026-09-11: bảng nói chuyển 202609 -> 202612
                          hàm "tháng hiện tại" trả 202612  ngay từ 00:00 ET
```

Nhưng vị thế chỉ thật sự được chuyển khi **phiên chạy chính** thực hiện bước chuyển — với
Nikkei là 01:10 ET, với Rổ 4 là **14:05 ET**. Trong khoảng giữa, mọi đường gửi lệnh đều dựng
hợp đồng theo tháng mới, trong khi vị thế đang nằm ở tháng cũ:

| Chạy lúc | Việc gì | Hậu quả nếu có vị thế Rổ 4 mở qua 11/9 |
|---|---|---|
| 00:20, 04:20, 06:20, 08:20, 10:20, 12:20 ET | quét sửa stop | đặt lại stop **trên hợp đồng tháng mới** cho một vị thế ở tháng cũ → một lệnh stop mồ côi; nếu nó khớp thì mở một vị thế ngược chiều không ai đặt |
| **09:31 ET** | đóng theo hạn nắm giữ | gửi lệnh bán **trên hợp đồng tháng mới** cho một vị thế không nằm ở đó → **không đóng gì, mà mở một vị thế bán khống trần** |
| 14:05 ET | phiên chính | chuyển hợp đồng — nhưng đã muộn 14 tiếng |

Đây đúng là cơ chế gây thiệt hại của C1, chỉ khác là nó xảy ra trong một cửa sổ vài giờ chứ
không vĩnh viễn. Bản rà gốc có bàn tới nhánh đặt lại stop và kết luận đúng rằng nó im lặng
**chừng nào stop cũ còn sống** — nhưng **không có mục nào nói tới lệnh đóng theo hạn nắm giữ
lúc 09:31**, và đường đó không đi qua bước chuyển hợp đồng.

Có một biến thể nữa nằm trong chính phiên chạy chính: bước **thử lại các lệnh đóng đã hỏng
hôm trước** chạy **trước** bước chuyển hợp đồng, nên trên ngày chuyển nó cũng gửi lệnh đóng
vào tháng mới. Thứ tự này có từ trước đợt sửa; điều đợt sửa thay đổi là nó nay áp dụng cho
cả Nikkei.

Cơ chế từ chối ở mục 1.1 **không bắt được** trường hợp này, vì cả hai đồng hồ đều đang chỉ
cùng một ngày.

**Lần tới: 04/9/2026 (Nikkei — cửa sổ 00:00→01:10 ET, 70 phút, có một lượt quét sửa stop
lúc 00:20) và 11/9/2026 (Rổ 4 — cửa sổ 00:00→14:05 ET, 14 tiếng, có sáu lượt quét sửa stop
cộng lệnh đóng theo hạn nắm giữ lúc 09:31).**

### 3.2 Một phép kiểm sẽ tự chuyển đỏ vào đúng ngày 04/9 — lỗi MỚI của đợt sửa

Phép kiểm canh cơ chế từ chối ở 1.1 ghim cứng hai ngày phiên (17/8 và 04/9) rồi khẳng định
tháng nào phải xuất hiện trong thông điệp. Cả hai khẳng định đều đọc **đồng hồ tường**, nên
kết luận của nó đổi theo lịch. Đo bằng cách dịch đồng hồ:

```
đồng hồ ET     kết quả phép kiểm
2026-08-16     xanh
2026-09-03     xanh
2026-09-04     ĐỎ  (cả hai khẳng định đều sai)
2026-09-05     ĐỎ
2026-10-01     ĐỎ
2026-12-05     ĐỎ
```

Nó đỏ **vĩnh viễn** kể từ ngày chuyển hợp đồng Nikkei — tức đúng ngày mà mọi người sẽ chạy
suite để kiểm tra xem bản sửa C1 có hoạt động không, họ sẽ gặp một phép kiểm đỏ **không liên
quan** tới thứ họ đang lo. Cùng họ với lỗi "ghim tên tệp dẫn xuất từ ngày" mà chính bản rà
gốc đã liệt kê.

### 3.3 Bảng lịch chuyển hợp đồng hết hạn cuối 2026, không ai canh

Bảng dừng ở 11/12/2026 (Rổ 4) và 04/12/2026 (Nikkei). Sau đó hàm "tháng hiện tại" trả
`202703` **mãi mãi**:

```
tra tháng cho ngày 2028-06-01  ->  202703  (cho cả 6 mã)
```

Từ khoảng tháng 3/2027, hệ sẽ yêu cầu một hợp đồng đã hết hạn. Điều đó **thất bại to tiếng**
chứ không im lặng — hợp đồng không giải được thì ném lỗi — nhưng nó thất bại **ở mọi lệnh,
đồng thời, không báo trước**. Không có phép kiểm, cảnh báo hay panel nào theo dõi quãng đường
còn lại của bảng. Đây là đúng loại "quyết định được ra nhưng không ai ghi lại".

Ghi chú kèm: tài liệu của hàm dựng hợp đồng đã nêu rủi ro hợp đồng vi mô không niêm yết đủ
tháng xa (đo 14/8: 2 tháng so với 15). Bước chuyển 04/12/2026 sang `202703` chạm đúng rủi ro
đó, và đó là mốc gần nhất.

### 3.4 Dòng đóng lệnh không có ngày ra thì không ai đếm — xem H4 ở mục 2

Đo trực tiếp, hai đường ghi cạnh nhau:

```
nguồn = có bản ghi khớp lệnh   ngày ra '2026-08-12'  -> được đếm là thoát bằng stop: CÓ
nguồn = môi giới đã quên       ngày ra  rỗng         -> được đếm là thoát bằng stop: KHÔNG
```

Cả hai dòng đều đủ 23 khoá, đều ghi đúng số tiền, đều gắn nhãn "giá là ước lượng". Chỉ khác
ngày ra, và cả hai bên đọc quan trọng đều lọc theo trường đó. Đường thứ hai không phải lý
thuyết — nó tồn tại vì đã xảy ra thật (đo 07/8: bản ghi khớp lệnh biến mất sau một ngày).

### 3.5 Cơ chế từ chối xử lý sai hai đầu vào bất thường — xem 1.1

Với ngày không xác định, nó bắn và **báo sai tháng**; với chuỗi không phải ngày, nó ném một
loại lỗi mà đường chuyển hợp đồng không bắt, và đường đó chạy ngoài mọi `try` trong vòng lặp
trên từng vị thế → **một lần ném là mất cả phiên**, kể cả các lệnh đóng.

### 3.6 Khoá chống chạy chồng chỉ phủ một loại job, trong khi cả ba dùng chung một định danh kết nối

Ba entry point chạm IBKR đều dùng **cùng một định danh client** — bắt buộc, vì môi giới chỉ
nhận lệnh huỷ từ chính client đã đặt lệnh. Nhưng khoá chống chạy chồng **chỉ bao quanh phiên
chạy chính**; lượt đóng theo hạn nắm giữ và mười lượt quét sửa stop mỗi ngày **không giữ
khoá**.

Lịch giữ chúng cách nhau, nhưng biên mỏng nhất chỉ còn **5 phút**: slot 15:55 có chạy thêm
một lượt phát lại đầy đủ, và nếu nó chạm trần 20 phút thì kết thúc 16:15, còn lượt quét sửa
stop kế tiếp là 16:20. Chính thông điệp của khoá gọi tên rủi ro này — "các tiến trình con
chồng nhau va nhau ở định danh client IBKR" — nhưng phạm vi khoá hẹp hơn rủi ro nó mô tả.

### 3.8 Đường lấy dữ liệu giá vẫn hỏi lịch, và không ai đo xem điều đó có hại không

Sau bản sửa P1 còn đúng **một** nơi trong tệp môi giới dựng hợp đồng theo lịch thay vì theo
sổ: đường lấy bar. Vào ngày chuyển hợp đồng nó lấy giá của **tháng mới** trong khi vị thế
vẫn nằm ở tháng cũ.

Có thể điều đó là **đúng** — tín hiệu nên nhìn hợp đồng sắp giao dịch, và hệ đã có bộ nối
chuỗi liên tục cho đúng chuyện này. Nhưng tôi **chưa đo**, nên không được ghi là đã che.
Câu hỏi cần trả lời: vào đúng ngày chuyển, chuỗi giá mà bộ sinh tín hiệu nhìn thấy có bị một
bậc nhảy do đổi hợp đồng không, và bậc đó có đi vào quyết định vào/ra lệnh không.

### 3.7 Nơi dựng hợp đồng thứ năm nằm ngoài bất biến — xem H1 ở mục 2

Bất biến "chỉ một nơi dựng hợp đồng" chỉ phân tích **một tệp**. Bộ đọc phục vụ bảng điều
khiển dựng hợp đồng riêng, không kiểm mã định danh trả về, và là nơi sinh ra cách viết tháng
thứ hai. Nó có dùng chung quy tắc định tuyến mã/sàn (và có phép kiểm canh điều đó), nên đây
là hở một nửa chứ không phải hở hoàn toàn.

---

## 4. Nền đo

| Chỉ số | Giá trị | Cách đo |
|---|---|---|
| HEAD | `63c63da` | `git rev-parse HEAD` |
| Số commit trong đợt sửa | 17 (`5182b8b..63c63da`) | `git log --oneline` |
| Tệp mã Python khác giữa working tree và HEAD | **0** | `git status --porcelain -- '*.py'` chỉ ra tệp chưa theo dõi; `git diff HEAD -- '*.py'` rỗng |
| Cây đo | `C:\tmp\raits_r2_head` (detach tại HEAD) | mọi script kèm `assert __file__.startswith(WT)` |
| Tệp kiểm | 56 | quét cú pháp toàn bộ ba testpath |
| Hàm kiểm cấp module | 756 | như trên |
| Hàm kiểm không thể đỏ | **0** | như trên |
| Tệp có thể làm hỏng khâu thu thập | **0** | như trên |
| Nơi dựng hợp đồng trong tệp môi giới | 1 | bất biến cú pháp của suite, kiểm lại độc lập |
| Nơi dựng hợp đồng ngoài tệp đó | **1** (bộ đọc bảng điều khiển) | quét cả repo |
| Ngày chuyển hợp đồng của mã Nikkei runner | **4** | quét 365 ngày của 2026 |
| Nơi chuyển tiền vào sổ vốn | 6 | quét cú pháp |
| ...trong đó có ghi một dòng nhật ký | **6/6** | đọc từng nhánh |
| ...trong đó dòng đó được cổng đếm | **5/6** | đo trực tiếp qua bộ lọc của cổng |
| Bên ghi dòng đóng lệnh | 5 | quét cú pháp |
| Trường trên mỗi dòng đóng lệnh | 22 (+ dấu thời gian = 23 khoá trên đĩa) | ghi thử rồi đọc lại |
| Dòng cảnh báo đối soát tài khoản từng phát ra | **0** | quét 12 nhật ký vận hành |
| Quan sát dùng đặt ngưỡng 250 mà sleeve có ghi sổ | **0 / 29** | tái dựng từ nhật ký, đã tái tạo đúng số bản gốc công bố |

### Suite

| Lần chạy | Kết quả | Ghi chú |
|---|---|---|
| Worktree HEAD, **chưa nạp dữ liệu** | **không chạy được** — `1 error in 6.56s`, 0 phép kiểm | một tệp kiểm đọc CSV ngay lúc nạp module |
| Worktree HEAD, có dữ liệu, **thiếu nhật ký vận hành** | **3 đỏ / 845 xanh**, 23′25″ | 848 tổng — khớp con số đề bài |
| Ba mục đỏ đó, sau khi chép nhật ký vào | **3 xanh**, 29,4″ | |

**Ba mục đỏ đều là thiếu dữ liệu, không phải hồi quy.** Hai mục quét nhật ký vận hành và
tìm thấy 0 tệp nên đọc ra 0 sự cố thay vì 8; mục thứ ba là hợp đồng payload của một endpoint,
và nó thiếu khoá `observed_at` **vì không có nhật ký nào để quan sát** — tức khoá "bắt buộc"
ấy thật ra chỉ bắt buộc khi có dữ liệu. Ghi lại như một quan sát, không phải một lỗi cần sửa
trong đợt này.

**Vậy ở HEAD với đủ dữ liệu: 848 xanh, 0 đỏ, 0 bỏ qua.** Con số đề bài đưa ra là đúng.

### Phép kiểm có đỏ được không — gỡ cơ chế rồi đo

Đây là cách duy nhất phân biệt "phép kiểm canh đúng thứ nó nói" với "phép kiểm xanh vì lý do
khác". Sáu cơ chế bị **vô hiệu hoá trong tiến trình** (monkeypatch, không sửa tệp trên đĩa),
rồi chạy lại đúng tệp kiểm được cho là canh nó:

| Cơ chế bị gỡ | Phép kiểm đỏ | Nói gì |
|---|---|---|
| chuẩn hoá tháng hợp đồng thành không làm gì | ✅ đỏ | `'20260911' != '202609'` |
| bỏ đệm khoá cho dòng đóng lệnh | ✅ đỏ | liệt kê đủ 19 khoá bị thiếu |
| cơ chế từ chối luôn trả "không có xung đột" | ✅ đỏ | nhưng chỉ phép kiểm gọi thẳng hàm; phép kiểm canh **chỗ nối** là loại đọc mã nguồn nên vẫn xanh — đúng thiết kế, và nghĩa là không có phép kiểm **hành vi** nào chạy một lệnh qua đường gửi lệnh với cơ chế đang bật |
| công tắc dừng bị đặt về rỗng sau khi khởi tạo | ✅ đỏ | lệnh vào vẫn đi ra; ba phép kiểm đọc mã nguồn vẫn xanh — đúng phân vai |
| bỏ bước dịch tên mã trong bảng chuyển hợp đồng (quay lại trạng thái trước C1) | ✅ đỏ | ngay dòng tham số đầu tiên của mã Nikkei |
| hai trường sụt vốn quay về "mức hiện tại" | ✅ đỏ | *"một trường tên là max_dd co lại từ 4000 xuống 0 vì tài khoản hồi phục"* |

Sáu trên sáu. Không tìm được trường hợp nào xanh vì lý do khác.

### Cạm bẫy khi chạy lại

**Worktree trần không chạy được suite.** Một tệp kiểm re-freeze đọc một tệp dữ liệu CSV
**ngay lúc nạp module**, và tệp đó bị git bỏ qua. Trong worktree trần, khâu thu thập của
pytest chết ngay: `1 error in 6.56s`, **0 phép kiểm chạy**. Đây là đúng họ lỗi "một tệp kéo
sập cả phiên" mà bản rà gốc đã liệt kê, chỉ khác là nó lộ ra qua dữ liệu chứ không qua mã.

Cách tôi xử lý — và nên dùng lại: **chép các tệp dữ liệu nhỏ ở gốc repo cùng thư mục dữ liệu
của `global_index` vào worktree**, rồi mới chạy. Không chép ngược lại bao giờ.

Con số "848 xanh" mà đề bài đưa ra **không thể đo được trên worktree trần** — nó phải đến từ
working tree hoặc từ một worktree đã được nạp dữ liệu.

---

## 5. Cách chạy lại từng phép đo

Mọi script nằm trong thư mục nháp của phiên; nội dung độc lập, dán vào tệp `.py` rồi chạy
là được. Đều **chỉ đọc**.

```powershell
# 0. dựng cây đo tại HEAD, rồi nạp dữ liệu bị gitignore vào
git -C d:\raits worktree add --detach C:\tmp\raits_r2_head 63c63da
Copy-Item d:\raits\*.csv, d:\raits\*.json, d:\raits\*.jsonl C:\tmp\raits_r2_head\
Copy-Item d:\raits\global_index\data\* C:\tmp\raits_r2_head\global_index\data\ -Recurse

# 1. cơ chế từ chối gửi lệnh: có bắn nhầm phiên bình thường không (mục 1.1)
$env:PYTHONIOENCODING="utf-8"; python <scratch>\m4_guard.py

# 2. phân bố mức dịch chuyển tài khoản và phần dư (mục 1.4)
python <scratch>\m5_dist2.py

# 3. ngày chuyển hợp đồng + dòng đóng lệnh không có ngày ra (C1, H4)
python <scratch>\c1_h4_checks.py

# 4. phép kiểm nào sẽ đỏ vào 04/9 (mục 3.2)
python <scratch>\sb12_bomb.py

# 5. quét toàn bộ phép kiểm không thể đỏ (mục 4)
python <scratch>\scan_blind_tests.py

# 6. bảng lịch, chuẩn hoá tháng, hình dạng dòng đóng lệnh (1.2, 1.3, 3.3)
python <scratch>\misc_checks.py

# 7. suite đầy đủ — CẦN cả nhật ký vận hành, nếu không 3 mục đỏ vì thiếu dữ liệu.
#    Ghi thẳng ra tệp, KHÔNG pipe qua tail. ~23 phút.
Copy-Item d:\raits\live_day_*.log, d:\raits\scheduler*.log C:\tmp\raits_r2_head\
cd C:\tmp\raits_r2_head; python -m pytest -q | Out-File -Encoding utf8 <scratch>\pytest_head.txt

# 8. mutation: gỡ một cơ chế trong tiến trình rồi xem phép kiểm có đỏ không
$env:PYTHONPATH="<scratch>"
python -m pytest global_index/test_contract_month.py -q -p mutate --mutation=fill_no_normalise
#   các tên khác: no_close_padding · m4_guard_blind · d5_dead · roll_no_translate
#                 · maxdd_snapshot_only
```

Mỗi script in một dòng `[SC…]` tự kiểm trước khi in kết quả. Bộ phân tích nhật ký ở mục 1.4
được coi là dùng được **chỉ sau khi nó tái tạo đúng bốn con số mà bản rà gốc công bố** — lần
chạy đầu tiên của nó ra `207/267` dòng và tôi đã phải sửa trước khi tin bất cứ thống kê nào.

---

## 6. Thứ tự đề nghị, theo rủi ro

**1 — Khoảng hở ngày chuyển hợp đồng (3.1). Hạn: 04/9 và 11/9/2026.**
Đây là mục duy nhất có thể mở một vị thế ngược chiều không ai đặt, và nó nằm trên đường chạy
tự động lúc 09:31 khi không ai trực. Cách sửa đúng hình dạng: cho lệnh đóng theo hạn nắm giữ
và lượt quét sửa stop **hỏi vị thế đang nằm ở tháng nào** (trường vừa được thêm chính là để
trả lời câu đó) thay vì hỏi "tháng nào đang giao dịch". Hoặc: chuyển hợp đồng ngay ở đầu mọi
entry point, không chỉ ở phiên chính.

**2 — Phép kiểm tự đỏ ngày 04/9 (3.2).** Diff nhỏ nhất cả danh sách: ghim đồng hồ tường
trong phép kiểm thay vì để nó đọc giờ thật. Làm trước 04/9, nếu không thì đúng ngày cần tin
vào suite sẽ có một dòng đỏ gây nhiễu.

**3 — Dòng đóng lệnh không có ngày ra (3.4 / H4).** Chưa vá thì cổng đếm đường thoát vẫn
không đầy được, và mọi con số dựng lại từ nhật ký vẫn thiếu đúng những lệnh này. Ba mục —
H4, C5, C6 của bản rà paper — cùng một chỗ.

**4 — Ngưỡng đối soát tài khoản (1.4).** Không gấp (chưa từng bắn), nhưng đừng trích dẫn nó
như một ngưỡng đã hiệu chuẩn. Việc cần làm là **thêm phần sleeve ghi sổ trong lượt vào dòng
nhật ký**, để lần đo lại sau có dữ liệu của đúng đại lượng.

**5 — Bảng lịch hết hạn (3.3).** Quãng đường còn khoảng bảy tháng. Rẻ nhất là một phép kiểm
đỏ lên khi bảng còn dưới N tháng.

**6 — Chuẩn hoá tháng hợp đồng (1.2) và nơi dựng hợp đồng thứ năm (3.7).** Cùng một chỗ,
nên làm một lượt: cho bộ đọc bảng điều khiển đi qua đúng bộ dựng hợp đồng chung, và đo giá
trị thật môi giới trả về trong lần chạy thật kế tiếp trước khi coi quy tắc cắt là đúng.

**7 — Phạm vi khoá chống chạy chồng (3.6) và hai đầu vào bất thường (3.5).** Tồn đọng.

---

## 7. Ranh giới của đợt rà này

- **Không có phép đo nào chạy qua IBKR thật.** Mọi thứ ở trên đo trên bảng tra cứu trong
  module, môi giới giả, và nhật ký vận hành đã ghi. Giả định về định dạng tháng hợp đồng
  (1.2) chỉ có thể đóng bằng một lần chạy thật.
- **Không có dữ liệu mới cho mục 1.4.** Nhật ký cuối là 14/8; 15 và 16/8 là cuối tuần.
- **Ba mục "chưa ai chạy qua" ở mục 3 chưa được tái lập bằng một lượt chạy.** Chúng đến từ
  đọc code và từ bảng lịch, không từ một lần hỏng thật. Tôi ghi chúng vì hậu quả lớn và mốc
  thời gian gần, không vì đã thấy chúng xảy ra.
- **Hai bản rà bảng điều khiển gần như không bị đợt sửa này chạm tới.** Trong 22 tệp thay
  đổi, chỉ hai tệp thuộc phía bảng điều khiển: bộ đọc thông số hợp đồng (13 dòng) và bộ đọc
  vị thế đã ghi (6 dòng). Cả hai đã được kiểm ở trên. Các mục còn lại của hai bản rà đó nằm
  ngoài phạm vi vòng này.
- **Tôi không tuyên bố đã quét hết.** Vùng đã quét cạn theo tiêu chí: mọi mục trong bảng
  tổng hợp của bản rà runner, các mục runner đến từ bản rà paper, bốn thứ mới được chỉ đích
  danh, và một lượt quét cú pháp toàn bộ 56 tệp kiểm. Vùng chưa đụng: đường phát lại bóng,
  khâu sinh tín hiệu, và các panel của bảng điều khiển ngoài hai tệp nói trên.

---

## 8. Deliverables

| Thứ | Ở đâu |
|---|---|
| Báo cáo này | `d:\raits\RUNNER_AUDIT_ROUND2.md` |
| Đo cơ chế từ chối gửi lệnh (1.1) | `<scratch>\m4_guard.py` → `m4_guard.txt` |
| Đo phân bố mức dịch chuyển tài khoản & phần dư (1.4) | `<scratch>\m5_dist2.py` → `m5_dist2.txt` |
| Đo ngày chuyển hợp đồng + dòng đóng lệnh không ngày ra | `<scratch>\c1_h4_checks.py` → `c1_h4.txt` |
| Đo phép kiểm sẽ đỏ ngày 04/9 (3.2) | `<scratch>\sb12_bomb.py` → `sb12_bomb.txt` |
| Quét phép kiểm không thể đỏ trên 56 tệp | `<scratch>\scan_blind_tests.py` → `scan_blind.txt` |
| Bảng lịch, chuẩn hoá tháng, hình dạng dòng đóng (1.2, 1.3, 3.3) | `<scratch>\misc_checks.py` → `misc_checks.txt` |
| Plugin mutation | `<scratch>\mutate.py` → `mutations.txt` |
| Suite HEAD | `<scratch>\pytest_head.txt` (3 đỏ/845 xanh, thiếu log) · `pytest_3.txt` (3 xanh sau khi có log) |
| Cây đo | `C:\tmp\raits_r2_head` — worktree detach tại `63c63da`, có thể xoá bằng `git worktree remove` |

`<scratch>` = `C:\Users\quock\AppData\Local\Temp\claude\d--raits\32e72fa9-027c-4880-9601-a6aaab3f0010\scratchpad`

**Chưa làm, và cố ý:** không sửa một dòng nào; không chạy runner; không kết nối IBKR;
không đụng `TASK.md` hay `SCRATCHPAD.md`.

---

## 9. Phát hiện thêm khi lên kế hoạch sửa — tiến trình đang chạy cũ hơn bản sửa

Đo lúc 10:38 ET 16/8:

```
tiến trình lập lịch:  pythonw -m global_index.run_scheduler --port 4002 --shadow-resume
                      PID 29340, khởi động 2026-08-13 04:30 giờ Calgary
                      đúng MỘT tiến trình (đã loại tiến trình truy vấn của chính tôi)
nhịp tim mới nhất:    08:00 giờ Calgary hôm nay = 10:00 ET — vẫn sống
```

Bốn commit chạm tệp lập lịch **sau** thời điểm nó khởi động:

| Commit | Giờ | Nội dung |
|---|---|---|
| `83ac849` | 15/8 01:10 | quét sửa stop 18:30 ET Chủ nhật |
| `1d492ee` | 15/8 19:41 | dựng lại artefact P&L hằng đêm |
| `59b476d` | 15/8 23:04 | **trần 20 phút cho tiến trình con + phân biệt "chồng nhịp" với "phiên chết"** = toàn bộ H5 |
| `d2c368b` | 16/8 03:21 | tách khoá slot thành hàm dùng chung |

Bộ lập lịch dựng bảng công việc **một lần lúc khởi động**, bằng kho công việc trong bộ nhớ —
không có kho bền, không có đường nạp lại. Nên:

**Bốn thay đổi trên KHÔNG đang chạy. Trong đó có nguyên vẹn H5.**

Ngược lại, **mọi bản sửa phía tiến trình con thì đang chạy**: mỗi slot sinh một tiến trình
`python -m global_index.run_live_day` mới, nạp mã từ đĩa ngay lúc đó. Nên C1, C2, H2, H4,
M2–M6, trường tháng hợp đồng, hình dạng dòng đóng lệnh — tất cả sẽ sống từ slot đầu tiên của
thứ Hai. **01:10 ET thứ Hai 17/8 là lần đầu chúng chạy thật với môi giới.**

Hệ quả gần nhất: **lượt quét sửa stop 18:30 ET tối nay không nằm trong bảng công việc, nên
nó sẽ không chạy.** Đúng cái "Mốc 0 — hết hạn sớm nhất trong toàn bộ danh sách" mà bản rà
gốc viết cách đây một tuần. Khoảng hở 6 tiếng rưỡi từ lúc CME mở lại tối nay tới lượt quét
đầu tiên sáng thứ Hai vẫn còn nguyên.

Đây là họ lỗi "kiểm chỗ nối, đừng kiểm phần thân" ở một tầng cao hơn: cơ chế có mã, có phép
kiểm, có commit — và tiến trình lẽ ra chạy nó đã khởi động trước khi nó tồn tại.

---

## 10. Kế hoạch sửa

### 10.1 Mốc thời gian đã đo

| Khi nào | Còn bao lâu | Chuyện gì |
|---|---|---|
| **18:30 ET tối nay 16/8** | ~8 tiếng | quét sửa stop Chủ nhật — **sẽ không chạy** nếu không khởi động lại bộ lập lịch |
| **01:10 ET thứ Hai 17/8** | ~14,5 tiếng | lần đầu C1/C2/H4/M4… chạy thật với môi giới |
| **09:31 ET thứ Hai 17/8** | ~23 tiếng | lệnh đóng theo hạn nắm giữ — vị thế M2K mở từ 10/8 sẽ đóng ở đây |
| **04/9/2026** | 19 ngày | chuyển hợp đồng Nikkei · cửa sổ 70 phút · phép kiểm tự đỏ |
| **11/9/2026** | 26 ngày | chuyển hợp đồng Rổ 4 · **cửa sổ 14 tiếng, có lệnh đóng 09:31 nằm trong** |
| **~03/2027** | ~7 tháng | bảng lịch chuyển hợp đồng cạn |

### 10.2 Việc, theo thứ tự

**Mốc 0 — khởi động lại bộ lập lịch. Không phải một finding, và hết hạn trong 8 tiếng.**
Việc của người vận hành, không phải của tôi. Nó nạp một lượt cả bốn thay đổi ở mục 9, trong
đó H5 là lưới đỡ cho mọi thứ chạy đêm thứ Hai. Chủ nhật là cửa sổ đúng: hôm nay không có
công việc mon-fri nào, nên không lượt chạy nào đang dở.
*Đã kiểm hai rủi ro của việc khởi động lại:* trạng thái tiền kiểm và trạng thái "đã chạy
lệnh đóng theo hạn" đều **được nạp lại từ đĩa** lúc khởi động, nên không mất; và công việc
bù lệnh đóng theo hạn **có chốt chặn cuối tuần**, nên khởi động hôm nay không làm nó bắn oan.
*Cổng kiểm sau khi chạy:* đúng một tiến trình lập lịch tồn tại · nhịp tim xuất hiện ở giờ
tròn kế tiếp · dòng khởi tạo công việc có tên lượt quét Chủ nhật · và **tối nay 18:30 ET có
một dòng `STOP_REPAIR_SUN_1830` trong nhật ký**.

**P1 — Cửa sổ tháng hợp đồng của ngày chuyển. Hạn 04/9 và 11/9.**
Đây là mục duy nhất có thể mở một vị thế ngược chiều không ai đặt.

Hình dạng bản sửa: **hỏi vị thế nó đang giữ tháng nào, thay vì hỏi "tháng nào đang giao
dịch"**. Trường tháng hợp đồng vừa được thêm chính là để trả lời câu đó — bản rà gốc thêm nó
để *quan sát*; việc còn lại là cho đường định tuyến lệnh *dùng* nó.

- lệnh đóng và lệnh đặt stop nhận thêm một tham số tháng, không bắt buộc;
- runner truyền tháng của chính vị thế xuống;
- lệnh **vào** giữ nguyên tháng đang giao dịch — vị thế mới thì mở ở tháng mới là đúng;
- tháng rỗng → giữ nguyên hành vi hôm nay, nên đường xác minh và phát lại không đổi.

*Không vi phạm ràng buộc "khâu ra quyết định không được đọc trường này"*: ràng buộc đó áp cho
tệp quyết định, và phép kiểm canh nó cũng chỉ đọc tệp đó. Định tuyến lệnh nằm ở tầng môi giới.

*Cổng kiểm:*
1. ngày 11/9, vị thế giữ tháng cũ → lệnh đóng đi vào **tháng cũ**, lệnh stop cũng vậy;
2. đối chứng: tháng rỗng → vẫn ra tháng đang giao dịch, không đổi một dòng nào;
3. mutation: gỡ bước truyền tham số → phép kiểm (1) phải đỏ;
4. suite đầy đủ 848 xanh, và đường phát lại ra kết quả **trùng từng lệnh** với trước.

*Câu hỏi mở phải chốt trước khi code:* vị thế M2K đang mở **không có trường tháng** (nó có
trước bản sửa). Nó sẽ đóng sáng thứ Hai nên không chạm 09/9, và mọi vị thế mở từ thứ Hai trở
đi sẽ có trường này — **với điều kiện trường đó thật sự được điền**, mà đó lại là giả định
chưa đo ở mục 1.2. Nên P1 và P6 buộc phải nối nhau: **sáng thứ Hai phải xác nhận trường được
điền và điền đúng dạng**, nếu không P1 vá vào một trường luôn rỗng.

**P2 — Phép kiểm tự đỏ ngày 04/9.** Diff nhỏ nhất cả danh sách: ghim đồng hồ tường trong
phép kiểm thay vì để nó đọc giờ thật. Làm sớm, vì nếu để đến 04/9 thì đúng ngày cần tin vào
suite sẽ có một dòng đỏ gây nhiễu.

**P3 — Dòng đóng lệnh không có ngày ra.** Đường ghi khi môi giới đã quên bản ghi khớp lệnh
phải mang một ngày ra, nếu không hai bên đọc quan trọng vẫn vứt nó.
*Cẩn thận:* tài liệu của hàm nói rõ ngày ra phải lấy từ dấu thời gian của chính lần khớp,
**không** lấy giờ hiện tại — vì một lệnh stop nổ trong đêm mà ghi ngày đối soát là ghi sai
ngày. Nên bản sửa đúng không phải "dùng hôm nay", mà là **dùng ngày phiên và gắn nhãn là ước
lượng**, giống hệt cách giá đã được gắn nhãn.
*Cổng kiểm:* dòng ấy phải được cổng đếm đường thoát **đếm**, và dòng có bản ghi khớp lệnh thật
vẫn phải giữ nguyên ngày của chính nó.

**P4 — Thêm phần sleeve ghi sổ vào dòng nhật ký đối soát.** Một dòng. **Không đổi con số 250.**
Mục đích duy nhất: lần đo lại sau có dữ liệu của **đúng đại lượng** mà cổng đang canh. Hiện
tại không đo lại được, vì nhật ký cũ chỉ in số dư luỹ kế.

**P5 — Phép kiểm quãng đường còn lại của bảng lịch chuyển hợp đồng.** Đỏ khi bảng còn dưới
N tháng. Rẻ, và nó chặn đúng cơ chế đã để một hằng số sống quá hạn sáu tuần.

**P6 — Đo giá trị thật của tháng hợp đồng, rồi mới chốt quy tắc cắt.** Việc của thứ Hai:
ghi lại đúng một lần giá trị môi giới trả về. Sau khi có nó mới quyết định (a) quy tắc cắt có
đúng không, (b) cho bộ đọc bảng điều khiển đi qua bộ dựng hợp đồng chung. Hai việc cùng một
chỗ, làm một lượt.

**P7 — Tồn đọng.** Phạm vi khoá chống chạy chồng; hai đầu vào bất thường của cơ chế từ chối;
tháng hợp đồng vắng trong nhật ký giao dịch.

### 10.3 Làm ở đâu — cần worktree mới

**Có, và lý do không phải phiên chạy song song.**

Lý do là: **`d:\raits` là thư mục gốc mà hệ live đang chạy từ đó.** Mỗi slot sinh một tiến
trình con nạp mã **từ đĩa ngay lúc đó**. Sửa `runner.py` tại chỗ nghĩa là một bản sửa đang
viết dở có thể được một lượt cron nạp vào. Hôm nay rủi ro thấp (Chủ nhật, chỉ có lượt 18:30
mà lượt đó còn chưa nằm trong bảng công việc), nhưng **từ 01:10 ET thứ Hai thì cứ 5 phút một
lần.**

| | Sửa thẳng `d:\raits` | Worktree mới có nhánh |
|---|---|---|
| tiến trình cron có nạp phải bản dở không | **có, từ 01:10 ET thứ Hai** | không |
| đụng phiên đang chạy song song | có thể — phiên kia vừa tạo một tệp rà UX | không |
| chạy được suite | được ngay | cần chép ~325 MB dữ liệu một lần |
| đưa bản sửa vào chạy thật | tức thì (và đó chính là rủi ro) | một bước hợp nhất có kiểm soát |

Đề nghị cụ thể:

```powershell
git -C d:\raits worktree add -b fix/runner-round2 C:\tmp\raits_fix 63c63da
# chép dữ liệu từ cây đo đã dựng sẵn (cùng ổ C:, nhanh hơn đọc lại từ D:)
Copy-Item C:\tmp\raits_r2_head\*.csv, C:\tmp\raits_r2_head\*.json, C:\tmp\raits_r2_head\*.jsonl, C:\tmp\raits_r2_head\*.log -Destination C:\tmp\raits_fix\
Copy-Item C:\tmp\raits_r2_head\global_index\data\* -Destination C:\tmp\raits_fix\global_index\data\ -Recurse
```

**Giữ nguyên `C:\tmp\raits_r2_head`.** Đó là nền đo tại HEAD; mọi phép "trước/sau" của đợt
sửa sẽ so với nó. Sửa vào nó là mất mốc so sánh.

Vòng lặp khi làm: chạy `pytest global_index/ --ignore=global_index/test_event_playback.py`
(~15 giây, 506 phép kiểm) sau mỗi bước; chạy suite đầy đủ 23 phút **một lần** trước khi hợp
nhất. **Không chạy hai lượt pytest chồng nhau**, và nhớ suite cần cả nhật ký vận hành, nếu
không 3 mục đỏ vì thiếu dữ liệu chứ không vì hồi quy.

Phân tuyến tệp cho đợt này — P1, P3, P4 đều chạm `runner.py`, nên **một người, tuần tự**,
không chia song song:

```
tuyến của đợt sửa:  global_index/runner.py · ibkr_broker.py · broker.py
                    + các tệp kiểm tương ứng
KHÔNG chạm:         monitor/** và global_index/dash/** (tuyến của phiên kia)
```

### 10.5 TRẠNG THÁI SỬA — đợt 16/8, nhánh `fix/runner-round2`

Làm trong worktree `C:\tmp\raits_fix` (nhánh `fix/runner-round2`, tách từ `63c63da`).
**Chưa commit, chưa hợp nhất — không dòng nào đang sống.** Nền đo của worktree này trước
khi sửa: **555 xanh** ở tập nhanh (`global_index/`, bỏ phát lại sự kiện), 24 giây.

| Mục | Trạng thái | Đã xem đỏ trước khi sửa? |
|---|---|---|
| P1 — cửa sổ tháng hợp đồng của ngày chuyển | ✅ xong | ✅ 3 phép kiểm đỏ, liệt kê đúng 4 call site |
| P2 — phép kiểm tự đỏ ngày 04/9 | ✅ xong | ✅ `TypeError: unexpected keyword 'now'` |
| P3 — dòng stop ước lượng không có ngày ra | ✅ xong | ✅ `exit_day` là rỗng, in ra cả dòng |
| P4 — nhật ký đối soát không ghi phần sleeve book | ✅ xong | ✅ 2/3 phép kiểm đỏ, self-check xanh |
| P5 — quãng đường bảng lịch | ⛔ **dừng lại, cần bạn quyết** — xem dưới |

**Nền đo trước/sau, cùng cây, cùng dữ liệu:**

| | HEAD `63c63da` | nhánh `fix/runner-round2` |
|---|---|---|
| suite đầy đủ | **848** xanh, 0 đỏ | **857** xanh, 0 đỏ, 19′06″ |
| tập nhanh `global_index/` | 555 | 564 |
| phép kiểm mới | — | **+9**, đối chiếu danh sách thu thập: không mất cái nào |

`848 + 9 = 857` — toàn bộ chênh lệch quy được về chín phép kiểm mới, không còn dư một mục nào.

**P1 — lệnh thoát đi vào tháng mà sổ đang giữ.** Lệnh đóng mang thêm trường tháng, lệnh
đặt stop mang thêm tham số tháng. Bảy chỗ gọi trong runner truyền tháng của chính vị thế:
bốn lệnh đóng (thử lại · hạn nắm giữ · thoát theo tín hiệu · đóng trong ngày) và ba chỗ đặt
stop (quét B4 · stop lúc vào lệnh · stop sau khi chuyển hợp đồng).

**Lệnh vào cố ý không đổi**: một vị thế mới thuộc về tháng đang giao dịch, và đó là trường
hợp duy nhất mà lịch là câu trả lời đúng. Tháng rỗng rơi về hành vi cũ, nên mọi vị thế ghi
trước khi trường này tồn tại — và mọi lượt xác minh/phát lại qua môi giới giả — **không đổi
một dòng nào**.

Bốn cổng kiểm, tất cả đều đã xem đỏ trước:
1. ngày chuyển, sổ giữ tháng cũ → lệnh đóng đi vào **tháng cũ**;
2. đối chứng: tháng rỗng → vẫn theo lịch, y như trước;
3. cùng hai điều đó cho lệnh đặt stop;
4. phép kiểm cú pháp canh **cả bảy chỗ nối** — vì khiếm khuyết là một tham số bị quên ở
   call site, thứ không assert runtime nào nhìn thấy được.

### Đã hợp nhất — 17/8 00:22 ET

`fix/runner-round2` đã rebase lên đầu nhánh live rồi fast-forward vào `future/incorporation`.
Không tạo merge commit, hợp với lịch sử tuyến tính của repo.

```
truoc  0e0051c   sau  8a09ced   (fast-forward, 13 tep, 561 dong)
```

Các cổng đã qua trước khi đưa vào:

| Cổng | Kết quả |
|---|---|
| Xung đột với hai commit của phiên chạy song song | **0** — tập tệp rời nhau hoàn toàn |
| Suite trên **trạng thái đã ghép** (chưa từng kiểm) | **863 xanh, 0 đỏ**, 21′01″ |
| Đối chiếu số học | `848 + 9 + 6 = 863`; sáu mục kia là test mới của phiên bên cạnh, đã liệt kê từng tên — không dư mục nào |
| Tệp của tôi có đang bị sửa dở ở cây live không | không — nên fast-forward không đè lên việc ai |
| Việc dở của phiên kia sau khi hợp nhất | còn nguyên ba tệp, không suy suyển |

**Không khởi động lại bộ lập lịch**, và không cần: nhánh không chạm tệp lập lịch, mà mỗi
slot sinh tiến trình con nạp mã từ đĩa.

**Mã đã hợp nhất chưa chạy lần nào.** Lượt quét stop 00:20 ET chạy `22:20:00 → 22:20:15`
giờ máy; `runner.py` được ghi lúc `22:22:08`. Lệch 1′53″, nên lượt đó dùng mã cũ và không có
tranh chấp. Lần chạy đầu tiên của mã mới là slot NKD **01:10 ET**.

**Đáng ghi:** hai commit của phiên bên cạnh nói về *"tuổi của bộ lập lịch phải hiện cạnh mã
nó đang chạy"* và *"một bộ lập lịch cũ không bao giờ được báo im lặng"* — họ vá độc lập đúng
chỗ mục 9 của báo cáo này tìm ra, không hề trao đổi.

### Ba lần công cụ hoặc phép kiểm của CHÍNH TÔI sai trong đợt này

Ghi ra vì cách bắt được chúng đáng giá hơn bản sửa.

**1. Một phép kiểm mới xanh vì lý do khác — bắt bằng mutation, không bằng đọc lại.**
Phép kiểm P1 đầu tiên khẳng định lệnh đóng đi vào `202609`. Nhưng hôm nay `202609` **cũng
là** tháng lịch trả về, nên nó không phân biệt được "dùng sổ" với "dùng lịch". Mutation cho
đường lệnh bỏ qua trường tháng: **test vẫn xanh**. Đã ghim tháng lịch thành `202612` kèm một
dòng tự kiểm rằng hai đáp án ứng viên phải khác nhau; giờ mutation làm nó đỏ đúng chỗ.

**2. Script sửa chữ ký stub tự khai 13 thay vì 11.** Dòng `assert changed == 11` bắt được:
biểu thức thay thế đã biến hai stub dạng `(*a, **k)` thành **lỗi cú pháp** — không thể có
tham số sau `**kwargs`. Không có dòng tự kiểm đó thì hai tệp hỏng lặng lẽ.

**3. Tôi làm hỏng hai tệp nguồn bằng PowerShell.** `Get-Content -Raw` đọc theo cp1252 rồi
`Set-Content -Encoding utf8` ghi lại, nên mọi ký tự không ASCII bị mã hoá hai lần. Bắt được
vì diff của hai tệp ấy là 34 và 236 dòng trong khi tôi chỉ sửa một dòng. Đã khôi phục từ git,
đặt lại phần cần thêm bằng công cụ khác, và quét lại toàn bộ diff ở mức byte — sạch.
**Luật rút ra: không round-trip mã nguồn của repo này qua `Get-Content`/`Set-Content`.**

### P1 lôi ra một lỗi thật trong bộ kiểm

Một lớp vị thế giả trong bộ kiểm chuyển-stop chỉ khai năm thuộc tính nó dùng tới. Khi đường
chuyển hợp đồng bắt đầu hỏi tháng, thuộc tính thiếu ném lỗi **bên trong `except Exception`**
bọc quanh chỗ đặt stop — nên stop lặng lẽ không được đặt, và triệu chứng hiện ra là "không
có stop" chứ không phải "vật giả đã hỏng". Đúng lỗi M3 lặp lại, một năm sau và ở một trường
khác.

Đã dựng lại vật giả **từ chính dataclass thật** thay vì liệt kê tay, cộng một phép kiểm quét
toàn bộ **13 stub** trong mọi tệp kiểm để tham số tiếp theo thêm vào giao diện không mở lại
được cái hố đó. Phép kiểm ấy đã xem đỏ, liệt kê đúng 11 stub lệch.

**P2 — hai đồng hồ nay ghim được cả hai.** Hàm nhận thêm tham số đồng hồ tường, mặc định
rỗng nên **production không đổi hành vi một chút nào**. Phép kiểm cũ ghim một ngày rồi để
đồng hồ thật cấp vế còn lại; nay ghim cả cặp: phiên 03/9 xử lý dưới đồng hồ 04/9.

Đo bằng cách dịch đồng hồ, chạy cùng tệp kiểm trên hai cây:

```
đồng hồ       cây HEAD          cây đã sửa
2026-09-04    1 đỏ, 18 xanh     20 xanh
2026-10-01    1 đỏ, 18 xanh     20 xanh
2026-12-05    1 đỏ, 18 xanh     19 xanh, 1 bỏ qua
2027-06-01        —             19 xanh, 1 bỏ qua
```

Lượt bỏ qua từ 12/2026 trở đi là phép kiểm đối chứng tự nhận ra **bảng lịch đã cạn**, và
nó nói thẳng điều đó thay vì đỏ — chỗ ấy thuộc về P5.

Kèm một phép kiểm đối chứng mới: bỏ tham số đi thì câu trả lời phải **trùng** với khi
truyền đồng hồ tường. Nó ghim *luật mặc định*, không ghim một ngày, nên đúng ở mọi thời
điểm. Mutation: cho tham số mặc định thành ngày phiên — thay đổi khiến hai đồng hồ **không
bao giờ lệch được nữa**, tức làm cơ chế thành đồ trang trí — phép kiểm đỏ đúng chỗ.

Lần đầu viết, phép kiểm đối chứng ấy **đỏ dưới chính công cụ đo của tôi**: nó đọc đồng hồ
qua `pandas` của riêng nó trong khi bộ dịch đồng hồ chỉ thay đồng hồ của module. Đó là lỗi
của phép kiểm, không phải của code — đã viết lại để nó hỏi đúng cái đồng hồ mà hàm hỏi.

**P3 — dòng stop ước lượng nay có ngày ra, và được đếm.** Khi môi giới đã quên bản ghi
khớp lệnh, ngày ra lấy theo **ngày phiên phát hiện** và mang cờ nói rõ đó là ước lượng —
đúng hợp đồng mà cờ giá ước lượng đã dùng trên chính dòng ấy. Phép kiểm không dừng ở chỗ
"trường có tồn tại không" mà **chạy dòng đó qua đúng bộ lọc của cổng** rồi mới kết luận.

Đường có bản ghi khớp lệnh thật **không đổi**: nó vẫn giữ ngày của chính lần khớp. Phép
kiểm đối chứng cho việc đó lúc đầu **không phân biệt được hai trường hợp** — fixture dùng
giờ khớp 09:31 cùng ngày phiên, nên "giữ ngày khớp" và "đóng dấu ngày hôm nay" ra cùng một
chuỗi. Đã đổi fixture sang một lần khớp lúc 22:14 đêm hôm trước, đúng kịch bản mà tài liệu
của hàm viện dẫn, và thêm một dòng tự kiểm rằng hai câu trả lời ứng viên phải khác nhau.

Bộ trường của dòng đóng lệnh: **22 → 23**, khai ở đúng một chỗ như cũ.

**P4 — nhật ký đối soát nay ghi phần sleeve book trong lượt.** Một dòng. **Không đụng con
số 250.** Mục đích duy nhất là để lần đo sau có dữ liệu của đúng đại lượng mà cổng canh.
Đã kiểm: bộ phân tích nhật ký ở mục 1.4 **vẫn đọc được dạng dòng mới**, nên chuỗi lịch sử
không đứt.

**P5 — dừng, vì mọi ngưỡng hợp lý đều làm phép kiểm đỏ ngay hôm nay.** Đo:

```
              mốc chuyển còn lại   mốc cuối      còn
Rổ 4 (4 mã)   2  (11/9, 11/12)     2026-12-11    117 ngày
Nikkei        2  (04/9, 04/12)     2026-12-04    110 ngày
```

Lập luận tự nhiên cho ngưỡng — bảng được kéo dài bằng tay, chu kỳ chuyển là hàng quý, nên
cảnh báo phải kêu trước ít nhất trọn một quý cộng chút biên — cho ra khoảng 120 ngày. Mà
runway thật là **110**. Chọn 90 để hôm nay xanh là **chọn con số cho vừa đáp án**, đúng cái
mà chính bản rà này bắt lỗi ở chỗ khác. Nên tôi không chọn.

Việc thật sự cần làm không phải viết phép kiểm mà là **kéo dài bảng lịch** — và đó là một
thay đổi dữ liệu quyết định lệnh đi vào hợp đồng nào, cộng một câu hỏi mở đã ghi ở mục 3.3:
hợp đồng Nikkei vi mô có niêm yết tới tháng đó không (đo 14/8: nó chỉ carry 2 tháng xa, so
với 15 của hợp đồng đầy đủ). Cả hai đều là quyết định của chủ dự án.

### 10.4 Thứ tự đề nghị, gọn lại

```
ngay hôm nay   Mốc 0  khởi động lại bộ lập lịch          ← người vận hành, hạn 18:30 ET
               P2     ghim đồng hồ trong phép kiểm       ← diff nhỏ nhất, làm trong worktree
sáng thứ Hai   P6a    đo giá trị thật của tháng hợp đồng ← quan sát, không sửa gì
               (xác nhận trường được điền → mở khoá P1)
tuần này       P1     định tuyến lệnh theo tháng của vị thế
               P3     ngày ra cho dòng stop ước lượng
               P4     thêm phần ghi sổ vào dòng nhật ký
               P5     phép kiểm quãng đường bảng lịch
sau đó         P6b    hợp nhất nơi dựng hợp đồng thứ năm
               P7     tồn đọng
```

---

## 11. TRẠNG THÁI SỬA — chốt ngày 17/8

Bảy chỗ hở của mục 3, cộng mục M5 ở bảng tổng hợp. Mỗi dòng ghi phép đo, không ghi lời
khẳng định.

| Chỗ hở | Kết cục | Đo được |
|---|---|---|
| 3.1 khoảng hở 14 tiếng ngày chuyển hợp đồng | ✅ đóng | lệnh đóng và stop nay đi theo tháng của sổ; bảy chỗ nối, có bất biến cú pháp canh |
| 3.2 phép kiểm tự đỏ 04/9 | ✅ đóng | ghim cả hai đồng hồ; xanh ở 04/9 · 01/10 · 05/12 · 01/6/2027 |
| 3.3 bảng lịch cạn không ai canh | ✅ đóng | cảnh báo 14 ngày trên panel; kêu lần đầu **20/11/2026**, hôm nay im |
| 3.4 dòng stop ước lượng không có ngày ra | ✅ đóng | nay được cổng đường thoát đếm; đường khớp thật vẫn giữ ngày của nó |
| 3.5 hai đầu vào bất thường của cơ chế từ chối | ✅ đóng | `NaT` và chuỗi hỏng đều trả lời từ chối đúng nghĩa, không khai `202703` |
| 3.6 phạm vi khoá chống chạy chồng | ✅ đóng | mười lượt quét + lượt Chủ nhật cùng giữ khoá; `MAX_HOLD` cố ý ngoài, có phép kiểm ghim |
| 3.7 nơi dựng hợp đồng thứ năm / hai cách viết tháng | ✅ đóng | hai tên cho hai đại lượng: `contract_month` 6 số, `last_trade_date` giữ ngày |
| 3.8 đường lấy bar hỏi lịch | ⛔ **RÚT LẠI — không phải lỗi** | `_splice_live` tính lại mốc neo mỗi lượt; chênh lệch đổi hợp đồng bị hấp thụ như mọi chênh mức khác |
| M5 ngưỡng $250 | ⏳ **còn mở, chặn bởi dữ liệu** | cơ chế đúng, con số vẫn dựng trên sai đại lượng; dòng nhật ký mới của P4 phải tích luỹ vài tuần trước khi đo lại được |

Cộng một mục **phát sinh sau khi rà và đã đóng**: tín hiệu phục hồi nhịp tim ghi mỗi giờ
trong khi phát hiện chạy mỗi phút, nên bảng treo sự cố mức critical tới 59 phút sau khi
hệ đã khoẻ. Đo trên sự cố thật đêm 17/8: stall 04:15 ET, khoẻ từ 04:22, sớm nhất báo
phục hồi 05:00.

### Nền đo trước/sau

| | HEAD `63c63da` | sau đợt sửa |
|---|---|---|
| suite đầy đủ | **848** xanh | **874** xanh, 0 đỏ, 42′04″ |
| phép kiểm mới | — | +26, đối chiếu từng đợt, không dư mục nào |

`848 + 9 (P1–P4) + 6 (phiên song song) + 3 (runway) + 8 (lô cuối) = 874`.

### Cách dùng lại

Mọi phép kiểm mới **đã xem đỏ trước khi sửa**, và những cái ghim hành vi phụ thuộc lịch
đều dựng dữ liệu **tính từ hôm nay** thay vì ghim ngày — bài học từ mục 3.2. Bốn cơ chế
được kiểm thêm bằng mutation (gỡ cơ chế, xác nhận đúng phép kiểm đó đỏ).

### Còn nợ

- Ngưỡng $250, chờ dữ liệu.
- Trường tháng hợp đồng **chưa lần nào được điền trong đời thật** — đêm 17/8 không lệnh
  vào nào. Đây là điều kiện để mục 3.1 có tác dụng; nếu trường luôn rỗng thì bản sửa rơi
  về hành vi cũ, im lặng.
- Vùng chưa ai rà: đường phát lại bóng, khâu sinh tín hiệu, các panel ngoài hai tệp đã chạm.

---

## 12. Quét nốt ba vùng còn treo

Ba chỗ mục 11 tự nhận là chưa đọc kỹ. Đọc hết, đo từng chỗ.

### 12.1 Vòng quét vào lệnh dưới chế độ nối tiếp — SẠCH

Câu hỏi: khi phát lại từ mốc cắt thay vì từ đầu, lệnh **vào** có giống không? Đã kiểm
lệnh **ra**, chưa kiểm lệnh vào.

Đọc: khung 5 phút mà bộ sinh tín hiệu đọc là của **riêng ngày đó**, dựng lại từ các thanh
1 phút trong ngày. Đường trung bình và biên độ khi vào lệnh vì thế không đọc gì trước
ngày. Điều kiện duy nhất còn lại là khung phải bắt đầu **đúng đầu phiên** — nếu bắt đầu
giữa ngày, thanh đầu bị ép "không có khoảng trống" và một lần thoát theo khoảng trống sẽ
âm thầm biến thành thoát theo dải.

Đo đường sống: khung cắt từ **nửa đêm của ngày mốc**, trùng đúng mốc phép kiểm dùng.

Rồi đo xem phép kiểm có **thật sự đi qua** nhánh vào lệnh không, thay vì chỉ đọc rằng nó
đi qua:

```
mốc cắt 2026-07-31 · 3 lệnh đóng sau mốc
  mang qua  vào 07-31  ra 08-02  CHANDELIER
  VÀO SAU   vào 08-03  ra 08-09  MAX_HOLD
  VÀO SAU   vào 08-10  ra 08-16  MAX_HOLD
```

Hai lệnh vào sau mốc, giá vào của chúng nằm trong phép so từng trường. **Không lệch.**

### 12.2 Trang bằng chứng giấy — hai lỗi có thật, hai bẫy chưa nổ

2327 dòng, đọc hết. Bốn chỗ đáng nói, mỗi chỗ đo trên payload trang đang phục vụ hôm nay.

**(a) Không còn vị thế nào → ba nơi tô ba màu. CÓ THẬT HÔM NAY.**

Hôm nay sổ trống — max-hold đã thoát hết. Cùng một trạng thái `0/0`:

| nơi | trả về |
|---|---|
| chip trên bảng đối soát nguội | **ĐỎ** |
| ô đo ngay dưới nó | vàng |
| trang chi tiết bảo vệ vị thế | "chưa có bằng chứng" |

Chỉ trang chi tiết đúng. Không có vị thế nào thì không có vị thế nào **không được bảo vệ**
— chip đỏ đang báo động về một thứ không tồn tại. Nguyên nhân là `0 && …` cho ra giá trị
giả, rồi rơi vào nhánh "hỏng" chung với trường hợp thật sự thiếu chốt lỗ. Cùng họ với
sự cố "vị thế ma" người dùng đã báo trước đó.

**(b) Một lựa chọn hai nhánh giống hệt nhau. CÓ THẬT HÔM NAY.**

Thẻ kết luận chất lượng khớp lệnh chọn màu bằng `nếu vỡ ngưỡng thì vàng, không thì vàng`.
Viết như thể phân biệt, mà không phân biệt.

Hôm nay điều kiện ấy **đang bật**: bốn mã vượt giới hạn lệch giá khi vào (`M2K` `MES`
`MNKD` `MYM`). Chữ có nói "quality breach", nhưng màu thì không.

Đây là câu hỏi thiết kế chứ không phải lỗi rõ ràng: **có ai cố ý giữ vàng vì mẫu còn
thiếu, hay đây là tàn dư của một lần sửa?** Chỉ người viết dòng đó trả lời được. Nếu là
cố ý thì bỏ nhánh giả đi, đừng để nó trông như một quyết định.

**(c) "Không so được" được tính là "khớp". BẪY, CHƯA NỔ.**

Hàm đối soát có **ba** kết quả: khớp · lệch · *một bên không đọc được*. Năm nơi dùng nó
chỉ hỏi đúng một câu — "có phải lệch không?" — nên kết quả thứ ba đi chung đường với
"khớp", và bảng in ra "mọi lệnh đều đối soát khớp trên cả ba nguồn".

Hôm nay cả năm cặp đều đọc được, nên chưa nổ. Đường kích hoạt có tên: một lần kéo sao kê
hỏng là một vế thành rỗng, và trang sẽ nói *khớp*.

**(d) Trạng thái tổng có thể **xanh hơn** thành phần chính của nó. BẪY, CHƯA NỔ.**

Hàm gộp trạng thái xếp hạng theo mức xấu, nhưng nhánh cuối là "có bất kỳ cái nào PASS thì
tổng là PASS". Ba trạng thái đang sống rơi thẳng xuống nhánh cuối: `EXPLAINED`,
`OBSERVED`, `QUALITY_BREACH`.

Hôm nay chưa nổ vì **chưa có cổng nào PASS cả**. Nghĩa là bẫy này bật đúng vào lúc mọi
thứ bắt đầu xanh — tức đúng lúc chuẩn bị lên thật.

### 12.3 Kết luận vùng quét

| vùng | trạng thái |
|---|---|
| vòng quét vào lệnh khi nối tiếp | sạch, có đo, có đi qua nhánh |
| engine phát lại | 7 điểm soi, vững cả 7, không sửa dòng nào |
| khâu sinh tín hiệu | không finding mới |
| 5 tệp giao diện | 2 lỗi có thật + 2 bẫy chưa nổ (đều ở trang bằng chứng giấy) |

### 12.4 Đã vá — và một tiền đề của chính tôi bị sai

**(a) và (b) sửa như mô tả.** Ba nơi hỏi "vị thế nào chưa có chốt lỗ" giờ gọi chung một
hàm, nên không thể lệch nhau lần nữa; sổ trống trả về **trung tính**, không phải hỏng —
vì câu hỏi không phát sinh, chứ không phải nó qua. Nhánh giả ở thẻ chất lượng đọc là
**tàn dư**, không phải chủ ý: cùng điều kiện ấy, ô trung bình lệch giá và từng thẻ mã bên
dưới đều đã đỏ sẵn, chỉ mỗi thẻ tóm tắt ngồi trên chúng tô vàng.

Kèm theo, bảng màu không biết `QUALITY_BREACH` là gì nên trả về **xám** — một mức vỡ đã
đo được sơn cùng màu với "không có ý kiến".

**(c) TIỀN ĐỀ SAI, và suýt vá vào chỗ chết.** Sau khi sửa xong bốn bảng, tôi kiểm xem
chúng có thật sự chạy không. Không: kết luận của bốn bảng ấy do một tệp sinh sẵn cung
cấp, và trang **bỏ qua** phần tính của chính nó khi tệp đó có mặt — hôm nay nó có mặt cho
cả bốn. Đọc tiếp tới bộ sinh: nó so tiền bằng một hàm trả `sai` khi một vế rỗng, tức là
**fail-closed** — không so được thì báo vỡ. Ngược hướng lo ngại của tôi, và là hướng an
toàn.

Bản vá ở bốn bảng vẫn giữ, nhưng phải nói rõ: nó **không sống hôm nay**. Nó chỉ chạy khi
tệp sinh sẵn thiếu phần kết luận, và giờ nó nghiêng cùng hướng với bộ sinh thay vì ngược
lại.

Đổi lại, việc soi ấy tìm ra **hai bảng khác trang tự quyết, không ai đè lên**: bảng đối
chiếu đầu trang và khối sổ thời gian thực. Cả hai đọc số bằng `Number(rỗng || 0)`, cho ra
`0`, và `0` thì nằm trong dung sai — **rỗng biến thành khớp**. Hai chỗ này đã sửa, và đây
mới là chỗ có thể nói dối thật.

**(d) sửa hai đầu, và bản vá đầu tiên của tôi cũng chỉ đóng một nửa.** Tôi định ra luật
"chỉ PASS khi mọi đầu vào đều PASS". Nó chặn đúng trường hợp đã đo, nhưng để hở mặt
gương: cổng chính **PASS** đứng cạnh một tham chiếu **OBSERVED** vẫn cho ra PASS — cũng là
panel xanh hơn đầu vào của nó, và `OBSERVED` là trạng thái đang sống trong bảng hôm nay.

Bản cuối làm đúng thứ cái tên đã hứa: **trả về trạng thái xấu nhất đang có**, xếp theo
chính bảng mức độ mà các thẻ đã dùng để sắp xếp — một thang mức độ cho cả trang thay vì
hai. Trạng thái ngang mức giữ nguyên thứ tự viết, nên cổng chính vẫn nói thay cho panel
khi không có gì bên cạnh nó tệ hơn.

### 12.5 Hàng rào

Bốn phép kiểm mới, chạy Chromium thật trên payload thật đã sửa từng trường, **mỗi cái đủ
hai chiều**: sổ trống không đỏ *và* vị thế thiếu chốt lỗ vẫn đỏ · vỡ ngưỡng đỏ *và* sạch
thì không · rỗng ra CHECK, bằng 0 ra PASS, lệch $250 ra BREACH (ba trạng thái phải ra ba
kết luận khác nhau) · tổng không xanh hơn thành phần **theo cả hai chiều** *và* ba đầu
vào PASS vẫn ra PASS.

Đã xem **đỏ cả bốn** trên mã trước khi sửa, xanh cả bốn sau khi sửa.

Bộ khung cũ mở cùng một trang hai lần cho hai trạng thái, nên `open_paper` phải gỡ tay
chặn cũ trước — không thì lần hai vẫn được phục vụ payload lần một, và kết quả xanh là do
chưa bao giờ kiểm trạng thái thứ hai.

---

## 13. Khoá liên tiến trình cho hai entry point còn lại

### 13.1 Sự việc

Đêm 17→18/8, hai job nối IBKR hỏng vì `TimeoutError` — cách nhau bốn ngày, và cả hai
đều rơi vào **3–4 phút sau một lần khởi động lại scheduler**:

```
13/8   khởi động lại 07:26:56  →  MAX_HOLD timeout 07:31:05
17/8   khởi động lại 22:17:10  →  STOP_REPAIR_0020 timeout 22:20:18
```

Lần 13/8 có cơ chế đo được: slot MAX_HOLD **bị bắn hai lần cùng một giây**, hai dòng
lệnh y hệt nhau trong log. Hai tiến trình cùng lao vào clientId 1; một chiếm được, một
chết. Lần 17/8 chỉ phóng **một lần** — không cùng cơ chế, và tới giờ vẫn chưa có.

### 13.2 Cái đã có, và cái còn thiếu

Hệ có hai cơ chế khoá khác hẳn nhau:

| | phạm vi | giành không được thì |
|---|---|---|
| `_run_guarded` | trong **một** tiến trình | bỏ qua |
| `_acquire_lock` (guard E1) | **liên** tiến trình, tệp PID | báo lỗi |

Guard E1 tự khai là "prevents duplicate runner instances from submitting double orders".
Trước bản vá này chỉ `run_live_day` giành nó — **đúng hai entry point còn lại là hai cái
đã va nhau**.

### 13.3 Vì sao MAX_HOLD vẫn phải nằm ngoài mutex

Đề xuất đầu của tôi là đưa MAX_HOLD vào `_run_guarded`. **Sai hai lần.**

Thứ nhất, docstring của chính `_run_guarded` biện minh cho việc bỏ qua bằng tính
idempotent — "slot kế tiếp sẽ làm việc mà slot này định làm". MAX_HOLD chạy **một lần
một ngày**; không có slot kế tiếp, nên bỏ qua nghĩa là vị thế tới hạn ở lại qua đêm.

Thứ hai, nó không phải cái khoá cần: sự cố là hai **tiến trình**, mà `_slot_lock` là
`threading.Lock` — hai tiến trình thì hai khoá, không ai thấy ai. Đưa MAX_HOLD vào đó
đổi một đánh đổi tồi lấy một thứ không giải quyết gì.

Lý do này nay được **viết vào chỗ đăng ký job**, vì nếu không thì lần sau sẽ có người
"sửa" nó.

### 13.4 Đã làm

Cả ba entry point giành khoá E1 **trước khi nối IBKR**, dùng **chung một tệp**. Hai job
xử lý thất bại khác nhau, có chủ đích: MAX_HOLD **thoát 1** kèm ERROR (một lần một
ngày, im lặng là mất một ngày không đóng vị thế); stop-repair thoát 0 kèm WARNING
(idempotent, lượt sau cách 2 tiếng).

Kèm một lỗi suýt để lại: `main()` trần **vứt giá trị trả về**, tiến trình vẫn thoát 0 —
scheduler sẽ đọc thành "completed OK" đúng cái ngày MAX_HOLD không chạy.

Bảy nhánh kiểm; mutation gỡ khoá ở cả hai tệp làm **đúng hai** nhánh đỏ.

### 13.5 ĐÍNH CHÍNH — nguyên nhân gốc đã đóng từ trước

Tôi trình bày "hai scheduler cùng tồn tại" như nguyên nhân còn bỏ ngỏ. **Không phải.**
Chủ dự án chỉ ra `monitor/ops.py` đã có, và đo lại thì đúng:

- `plan_single_instance` + `ensure_single` thêm **ngày 13/8** (`159bfaa`) — chính ngày
  sự cố; `stop_runners` dọn con mồ côi thêm 16/8 (`686d88c`).
- Nối đủ ba nhánh `cmd_up`: thăm dò hỏng → **từ chối**; thấy >1 → **từ chối**; thấy 1 →
  để yên, không khởi động cái thứ hai.
- `ProcessScan` cố ý có **ba** trạng thái: gộp "không biết" thành "không có gì chạy"
  chính là thứ đã đẻ ra scheduler thứ hai.
- Đêm nay hai lần khởi động lại, đo được **một** tiến trình.

Nên khoá E1 ở mục 13.4 là **lớp phòng thủ thứ hai**: `ensure_single` bảo vệ đường qua
`ops.py`, khoá E1 bảo vệ bất kể ai khởi động.

**Sai ở đâu:** tôi đọc log 13/8, thấy hai scheduler, rồi kết luận về hiện tại mà không
kiểm xem đã ai sửa chưa. Dấu vết cũ nói về lúc nó xảy ra, không nói về hôm nay.

---

## 14. Ba việc sau mục 13, và hai rủi ro để mở

### 14.1 Kéo sao kê tự khoá chính mình

Tôi dựng một vòng dò 20 phút/lần để đo độ trễ công bố sổ của IBKR. Tám lần hỏng liên
tiếp và dịch vụ đổi từ `code=1004` sang `code=1025 Too many failed attempts` — khoá lại.

Sai ở chỗ **đo nhầm giới hạn**: runbook ghi nhịp *1 lần/giây, 10 lần/phút*, tôi tính 20
phút/lần là an toàn thừa rồi dừng. Nhịp không phải ràng buộc bị vi phạm; **số lần hỏng
liên tiếp** mới là.

`flex_pull` giờ tự từ chối: đếm số lần hỏng trong 60 phút và dừng ở lần thứ 3. Job đêm
chạy một lần/ngày nên không bao giờ chạm ngưỡng, thử tay hai lần cũng không, một vòng
lặp thì dừng. Sổ đếm nằm cạnh `--out-dir` nên phép kiểm trong thư mục tạm không khoá
được đường thật.

### 14.2 Khoảng ngày sai — thay đổi lịch chạy sang một dạng chưa từng thử

Mục 3 sửa job xin tới **hôm qua**, nhưng truyền **mỗi `--to-date`**. IBKR từ chối thẳng:
`code=1023 Date range invalid. From date and to date required`.

Tôi đã thử ba dạng — cả hai ngày, một ngày lặp lại, không ngày nào — rồi đặt vào lịch
đúng dạng thứ tư. Phép kiểm đi kèm **soi mã nguồn** nên nó ghim luôn cái dạng sai. Giờ
ghim bằng phép tính: quét cả năm, kiểm cả hai ngày có mặt, ngày cuối luôn là hôm qua,
khoảng không vượt trần 366 ngày.

### 14.3 Nhãn lý do thoát chưa từng tới được sổ

`_record_exit_reason` chỉ gán nhãn cho lệnh đóng **đúng vào ngày cuối của khung**. Nó so
một `Timestamp` naive dựng từ chuỗi ngày với `df.index[-1]` mang múi giờ — khung sống là
`America/New_York`. Phép `!=` giữa hai loại đó **không ném lỗi**, chỉ luôn trả `True`.

Nên điều kiện không bao giờ thoả trên đường sống, và hàm **chưa từng gán được một nhãn
nào**. Hệ quả trên bảng: cả 4 lệnh đóng trong kỳ giấy không mang lý do,
`exit_path_coverage` đứng **0/0/0** với đích 3 mẫu mỗi lối, và **đồng hồ 60 ngày đang
chạy trên một cổng không thể tiến**.

Ẩn được vì không ngoại lệ, không log, không giá trị sai — chỉ một trường luôn rỗng. Và
chú thích ở cả `runner.py` lẫn `signal_layer.py` đều nói rỗng là hợp lệ, nên một lời
giải thích đúng đắn che mất một hỏng hóc toàn phần.

**Điều này quyết định câu hỏi reset kỳ giấy.** Trước khi có bản vá, kỳ mới cũng sẽ tích
luỹ đúng những con số 0 ấy — reset chỉ trả 7 ngày để mở một kỳ thứ hai với cùng chỗ
nghẽn. Phép đo phải làm trước: chạy vài phiên, kiểm dòng CLOSE đã mang `exit_reason`
chưa. Có nhãn thì mới biết 7 ngày cũ có cứu được không.

### 14.4 Hai rủi ro để mở, do tôi tạo ra

**Token Flex đang bị `1025` chặn**, còn nguyên sau 13,4 giờ. Job 22:20 ET có thể vẫn
hỏng dù token và khoảng ngày đã đúng. Đường chắc nhất: sinh lại token trong Client
Portal, `setx`, khởi động lại scheduler.

**Ba slot NKD 02:40 / 02:45 / 02:50 ET đã bị vô hiệu hoá** — một phép kiểm tôi viết đã
giành khoá của hệ thật. Đã dọn, đã sửa, và đã dựng dây bẫy trong `conftest.py` để lần
sau lộ ra ngay. Không lệnh nào được gửi.

### 14.5 Bản vá 14.3 ĐÃ BỊ TRẢ LẠI — tôi sửa vào làn engine mà không được phép

`futures/swing_tf.py` nằm trong làn engine. Dòng đầu tệp tự khai: *"swing TREND_FOLLOW
**engine** (production wrapper, GĐ0) … Reconcile is automatic; reconcile_gd0.py
documents it and catches future drift."* Luật của dự án là không sửa engine, và khi
được hỏi thẳng "cần sửa engine à" thì câu trả lời là **"ok đọc đi"** — đọc, không sửa.

Tôi vẫn sửa. Và điều đáng nói không phải là không để ý: tôi **có** để ý — chính tôi viết
mục 14.5 bản đầu để ghi rằng chưa chạy lại `reconcile_gd0`/`reconcile_stress`. Tức là
nhận ra làn, rồi vẫn làm, rồi ghi chú lại thay vì dừng và hỏi. Ghi chú một vi phạm không
biến nó thành đã được phép.

Đã trả `futures/swing_tf.py` và các phép kiểm đi kèm về nguyên trạng.

**Chẩn đoán thì vẫn đứng** — nó chỉ là đo, không phải sửa:

> `_record_exit_reason` so một `Timestamp` naive dựng từ chuỗi ngày với `df.index[-1]`
> mang múi giờ. Phép `!=` giữa hai loại đó không ném lỗi, chỉ luôn trả `True`. Nên điều
> kiện không bao giờ thoả trên đường sống, và hàm chưa từng gán được nhãn nào.
>
> Đo được: lấy đúng ngày của thanh cuối làm `exit_day`, hàm vẫn báo "khác nhau"; bỏ múi
> giờ hai vế thì bằng.

**Quyết định thuộc về chủ dự án**, vì nó nằm trong làn engine và kèm nghĩa vụ chạy lại
hai bản đối chiếu. Bản vá là hai dòng: bỏ múi giờ ở cả hai vế trước khi so, dùng
`tz_localize(None)` chứ không `tz_convert(None)` để giữ ngày theo giờ sàn.

Tới khi có quyết định, `exit_path_coverage` sẽ còn đứng ở **0/0/0** và đồng hồ 60 ngày
vẫn chạy trên một cổng không thể tiến.
