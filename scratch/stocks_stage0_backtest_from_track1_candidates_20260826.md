# Stage STOCKS-0 — dựng tuyến cổ phiếu từ logic ứng viên đã kiểm của Track 1

**2026-08-26, giờ máy Calgary (MDT) · CHỈ ĐỌC.** Không ghi một tệp sản xuất nào, không khởi chạy hay dừng scheduler/backend, **không mở kết nối IBKR hay bất kỳ broker nào**, không dựng một đối tượng lệnh nào, không chạm parquet hay CSV nào ngoài `scratch/`, không commit. Toàn bộ số dưới đây do các script nằm trong `scratch/` sinh ra; chúng *import* gói sản xuất chứ không sửa nó.

---

## Phán quyết

| | |
|---|---|
| **Backtest có hợp lệ không?** | **BACKTEST_VALID** — kèm ba giới hạn nêu bên dưới, giới hạn lớn nhất là thiên lệch sống sót |
| **Có edge chuyển được sang cổ phiếu không?** | **NO_EVIDENCE_OF_PORTABLE_EDGE** |

Dòng edge được **tính** từ một cổng đã **cam kết trước khi lượt chạy kết thúc**, và cố ý lỏng — đây là phép sàng tầng 0 hỏi "có gì ở đây không", không phải cổng thăng hạng. Cả ba phải đạt:

| kiểm tra đã cam kết trước | đo được | kết |
|---|---:|---|
| lãi ròng ngoài mẫu > $0 | -2,324 | TRƯỢT |
| p ngoài mẫu < 0.1 | 0.5799 | TRƯỢT |
| trượt giá hoà vốn >= 6.0 bps/chiều | 7.38 | ĐẠT |

Cấu hình chính (`spy_short_gate`), cửa sổ 2019-01-02 .. 2022-12-30:

```text
ứng viên       6268      nhận       883      từ chối      5385
lãi gộp    +$18,790      chi phí +$9,507      lãi ròng  +$9,282
lợi nhuận     9.28%      CAGR      2.3%      sụt tối đa +$19,900
PF             1.08      thắng    50.4%      Calmar       0.12

trong mẫu  ròng   +$11,607   lệnh   435   PF   1.24
ngoài mẫu  ròng    -$2,324   lệnh   448   PF   0.96
trượt giá hoà vốn: 7.38 bps mỗi chiều
```

---

## 1. Bảy câu hỏi, trả lời trước khi chạy bất cứ thứ gì

### 1.1 Dùng lại đúng phần logic ứng viên nào của Track 1?

**Chỉ Normal-R4, và chỉ những phần nói về GIÁ chứ không nói về HỢP ĐỒNG.** Không Calm, không Stress, không NKD, không dòng artifact swing.

Chọn Normal-R4 không phải vì thích. Tín hiệu của nó *vốn đã là* một chiến lược cổ phiếu: `global_index/track1_normal_r4._strategy` dựng một `raits.strategies.trend_follow.TrendFollowStrategy` — lớp viết cho bar 5 phút của cổ phiếu — rồi cấu hình `ema_period=50` và `allowed_regimes=['Normal']`. Sleeve futures chính là chiến lược cổ phiếu đó chĩa vào chỉ số tương lai. Đưa nó về lại cổ phiếu là quãng đường ngắn hơn vẻ ngoài — kèm đúng một cảnh báo đã đo về việc EMA có bao nhiêu lịch sử phía sau lúc 14:00, ở mục 6.1.

Ba sleeve còn lại không chuyển được, mỗi cái hỏng theo cách riêng:

| sleeve | vì sao không dùng lại |
|---|---|
| **Calm A** | **chuyển được — chỉ là chưa chạy ở tầng này.** Xem đính chính ngay dưới bảng |
| **Stress-MNQ** | bộ dò của nó *chính là* bốn hợp đồng futures cụ thể — cả bốn `MES/MNQ/MYM/M2K` nằm dưới cả giá mở cửa lẫn VWAP phiên tính tới 10:30, ba trên bốn gap xuống. Đó là phép đọc độ rộng chéo công cụ trên một họ chỉ số. Bản cổ phiếu sẽ là một tín hiệu khác đội tên cũ |
| **NKD / MNKD** | công cụ phiên Tokyo, đồng hồ `Asia/Tokyo`, mã tách đôi giữa lịch sử (`NKD`) và lệnh (`MNK`). Không có gì trong đó nói về cổ phiếu |

**Đính chính, ghi lại nguyên vẹn thay vì sửa lặng lẽ.** Bản đầu của mục này viết rằng Calm A *không* chuyển được, vì nó là "luật hồi quy trong ngày ở tầng chỉ số". Đọc lại mã thì sai. Mọi điều kiện của nó chỉ đọc bar **của chính công cụ đó**: vị trí giá đóng RTH hôm trước trong biên độ hôm trước, lợi suất RTH hôm trước, khoảng nhảy so với giá đóng RTH hôm trước, cộng nhãn chế độ Calm lấy từ SPY. Danh sách `("MES", "MNQ")` trong cấu hình chỉ là một cổng chặn danh sách trắng, không phải phụ thuộc cấu trúc.

Nên **Calm A chuyển được sang cổ phiếu đúng theo nghĩa Normal-R4 chuyển được**, và nó còn RẺ hơn nhiều: một lần vào lệnh lúc 10:00, thoát 15:55, không có vòng quét trong ngày. Cái không chuyển là **hiệu chỉnh** của nó — ngưỡng một phần ba, khoảng nhảy −1,0%, cắt lỗ 1,5 lần ATR15 — vì cả ba suy ra từ phân bố futures, đúng cùng loại cảnh báo đã áp cho ngưỡng biên độ ở mục 2.3. Nó không được chạy ở tầng này vì phạm vi tầng này là *một* luật, không phải vì nó không chuyển được.

Hai sleeve kia thì lý do vẫn đứng: Stress-MNQ cần đọc độ rộng **chéo bốn công cụ**, nên bản cổ phiếu phải bịa ra một thước độ rộng thay thế — đó là luật mới. NKD là công cụ phiên Tokyo.

Cái gì đi theo, nói chính xác:

```text
DÙNG LẠI bằng import và gọi — không chép, không monkeypatch
  raits.strategies.trend_follow.TrendFollowStrategy   tín hiệu pullback + khối lượng
  track1_normal_r4._strategy                          cấu hình Normal-R4 của nó
  track1_normal_r4.make_signal_fn                     thứ tự cổng + neo lại stop
  track1_normal_r4.scan_signals                       tín hiệu được nhận đầu tiên/phiên
  track1_normal_r4._replay                            vũ trang, gap fill, max hold,
                                                      vào lại trong ngày
  track1_normal_filters.R4ContextFilter               biên độ hôm trước + rvol bar vào
  track1_normal_filters.short_days_from_csv           cổng SHORT theo SPY D-1
  futures._validated_core.label_regimes               HMM 3 trạng thái trên SPY

TỪ CHỐI, lý do ở mục 2
  point_value / tick / hệ số hợp đồng                 một cổ phần không phải một hợp đồng
  daily_atr_series (chưa dịch)                        đọc chính ngày mà nó được dùng
  FLOOR_RANGE_P90 = 0.02652                           một phân vị futures, không phải luật
  label_lag_days = 0                                  nhãn đó chưa tồn tại lúc 14:00
```

Một bản cài đặt thứ hai của luật vào lệnh không chứng minh được gì về bản thứ nhất. Nên phép chuyển ở đây là *cùng một đoạn mã, khác bộ bar*; và chỗ nào buộc phải bỏ một hằng số futures thì bỏ ra mặt, chứ không lặng lẽ chỉnh lại.

### 1.2 Rổ cổ phiếu nào?

Mọi mã đã có bar 5 phút trên đĩa, lọc lấy những mã có ít nhất 250 phiên bên trong cửa sổ kiểm. Đo được:

```text
mã đã cache               75   (62 mã đơn lẻ, 13 ETF)
phiên sẵn có            1510   2017-01-03 -> 2022-12-30
độ phủ mỗi mã           nhỏ nhất 290  trung vị 1510  lớn nhất 1510
```

**Đây KHÔNG phải rổ theo thời điểm, và trên đĩa này không có rổ như thế.** Đã tìm: các tệp có dáng danh sách thành phần chỉ gồm `raits/data/cache/research_daily/universe_BUY.txt`, `universe_CO.txt`, `universe_COA.txt` và `universe_classification.parquet` — tất cả dựng cho một nghiên cứu Databento 2023-2026 từ một bảng phân loại *hiện tại*, không tệp nào mang tư cách thành viên tính theo một ngày trong quá khứ.

Vậy rổ này là danh sách những cái tên lớn và thanh khoản **vào lúc cache được dựng**, đem áp ngược về 2019-2022. Mã nào cũng sống sót. Điều này được nhắc lại như một giới hạn hạng nhất ở mục 7, và nó là lý do lớn nhất để không đọc con số đầu bảng như một kỳ vọng.

**Độ phủ trong cửa sổ không đồng đều, và ba ngoại lệ đáng chú ý hơn kích cỡ của chúng.** Trong 75 mã, **72** mã có đủ 1008 phiên. Còn lại:

| mã | phiên | đầu | cuối | là gì |
|---|---:|---|---|---|
| META | 290 | 2021-06-30 | 2022-12-30 | **một lần đổi mã ngay trong cửa sổ.** Trong cache này không có `FB`, nên lịch sử của Meta từ 2019 tới giữa 2021 vắng mặt dưới cả hai tên — mã chỉ đơn giản bắt đầu muộn và không có gì báo |
| LOW | 797 | 2019-01-02 | 2022-03-01 | lượt fetch dừng sớm; thiếu 10 tháng cuối cửa sổ |
| SBUX | 970 | 2019-01-02 | 2022-11-04 | lượt fetch dừng sớm; thiếu 2 tháng cuối cửa sổ |

Cả ba đều vượt sàn 250 phiên lịch sử nên cả ba đều có giao dịch. Sàn đó đặt ra để bảo đảm đủ lịch sử cho một EMA 50 và một trung vị 20 phiên, và nó làm đúng việc ấy — nhưng nó **không** phải phép kiểm tính đầy đủ, và một mã thiếu nửa sau cửa sổ chỉ đóng góp lệnh của một phần giai đoạn trong khi vẫn được tính là thành viên đầy đủ của rổ. Nêu tên chứ không lọc bỏ, vì lọc sau khi đã biết chúng là mã nào là một lựa chọn dựa trên hậu kiến.

### 1.3 Nguồn dữ liệu nào?

| | |
|---|---|
| nhà cung cấp | Polygon.io, qua cache 5 phút sẵn có `raits/data/cache/data` |
| điều chỉnh | **đã điều chỉnh chia tách và cổ tức** — `raits_polygon_fetcher` gửi `adjusted=true` |
| khung bar | bar 5 phút (tuyến này không lấy mẫu lại từ 1 phút) |
| đồng hồ | **ET không mang tz**. Bộ fetch đổi mili-giây UTC của Polygon sang `US/Eastern` naive ngay lúc nhập; tuyến này đọc đúng như đã ghi và **từ chối** một frame đến kèm tz thay vì tự chuyển đổi |
| phiên | **chỉ RTH 09:30-15:55**, đây là quyết định của tuyến cổ phiếu. Frame trong cache mang 04:00-19:55; các lệnh khớp ngoài giờ mỏng và sẽ chui vào ATR ngày, biên độ hôm trước và trung vị khối lượng theo khung giờ mà không bao giờ giao dịch được ở quy mô tuyến này cần |
| lịch | tập phiên có bar trên đĩa, lấy từ chính các tệp của SPY. Một phiên nhà cung cấp chưa từng giao thì không giao dịch được, dù sàn có mở hay không |

**1,9 GB dữ liệu 1 phút Databento đã mua KHÔNG dùng được cho tuyến này, và điều đó là đo chứ không phải đoán.** Nó chứa 17.754.609 dòng, 314 mã, 839 phiên — nhưng chỉ từ **09:30 tới 10:44 ET**, đúng 75 mốc phút khác nhau mỗi ngày. Nó được mua đã cắt sẵn theo cửa sổ ORB. Normal-R4 giao dịch 14:00-15:55. Phần giao nhau bằng rỗng.

### 1.4 Mô hình thực thi nào?

Thừa hưởng từ sleeve, viết đúng như nó chạy:

```text
vào lệnh   giá ĐÓNG của bar 5 phút resume, trong 14:00-15:55 ET,
           tín hiệu được nhận đầu tiên của phiên, tối đa một vị thế mỗi mã
stop       entry -+ 2.0 x ATR ngày(14), neo tại entry, KHÔNG BAO GIỜ dịch theo,
           và chưa sống cho tới 14:05 của phiên SAU khi vào
thoát stop khớp tại stop, trừ khi bar MỞ CỬA vượt qua nó thì khớp tại giá mở
           (`fill_law = production_gap_after_15min_break`)
max hold   5 -- và là 5 ngày LỊCH, không phải 5 phiên: xem mục 8, phát hiện S-3
thoát max  tại bar 09:30 của phiên thoát
```

Hai hệ quả riêng của cổ phiếu, và chúng *không* phải khác biệt về mã:

1. **Khoảng nhảy qua đêm là khoảng nhảy duy nhất.** Trên frame futures liên tục, phép kiểm gián đoạn 15 phút nổ ở giờ bảo trì; trên frame cổ phiếu RTH, gián đoạn duy nhất dài quá 15 phút là 15:55 sang 09:30. Nên luật fill sản xuất rơi đúng vào bar qua đêm và không rơi vào đâu khác — luật thừa hưởng tình cờ chính xác ở đây, và điều đó đáng nói vì nó rất dễ đã không như vậy.
2. **Đêm đầu tiên vị thế không được bảo vệ.** Stop chưa vũ trang cho tới 14:05 phiên sau. Trên thị trường futures 23 giờ, đó là lựa chọn thiết kế về thời điểm một lệnh chờ trở nên sống. Trên cổ phiếu, nó có nghĩa là khoảng nhảy qua đêm đầu tiên — rủi ro đơn lẻ lớn nhất mà một vị thế swing cổ phiếu mang — xảy ra khi **không có stop nào trong sổ**. Luật được chuyển nguyên vẹn và hệ quả được nêu tên, không làm mềm đi.

### 1.5 Mô hình chi phí nào?

Mọi con số dưới đây là **giả định**, không phải phép đo. Không có sao kê broker, biểu phí hay tệp lãi vay nào được đọc cho tuyến này, và trong kho cũng không có. Tất cả đều được quét ở mục 4.

```text
hoa hồng     $0,005 mỗi cổ phần mỗi chiều, tối thiểu $1,00 mỗi lệnh
             (dáng bậc thang bán lẻ IBKR US -- GIẢ ĐỊNH, phải xác minh trước khi paper)
trượt giá    3,0 bps giá mỗi chiều.
             Có tính cấu trúc chứ không tuỳ chọn: engine ghi giá vào lệnh tại giá ĐÓNG
             của bar resume, một mức giá đã giao dịch xong vào lúc bar được biết. Phải
             trả một cái gì đó để có mặt ở đó.
thoát stop   cộng thêm 5,0 bps. Thoát stop là một lệnh stop-THỊ TRƯỜNG trong sổ đang
             chạy, không phải lệnh giới hạn nằm chờ tại stop. Thoát GAP đã được ghi tại
             giá mở, chính đó LÀ phần nhượng bộ, nên không tính phí hai lần.
lãi vay bán khống  50 bps/năm trên giá trị bán khống x số ngày nắm giữ / 252.
             GIẢ ĐỊNH: vốn hoá lớn, dễ vay. Khả năng vay được là giả định, không kiểm --
             trên đĩa này không có dữ liệu khả dụng cho vay.
```

### 1.6 Mô hình định cỡ nào?

```text
số cổ phần = floor( risk_pct x cơ sở vốn / |giá tín hiệu - stop| )

cơ sở vốn = vốn ban đầu + lãi/lỗ ĐÃ THỰC HIỆN     <- không bao giờ là giá thị trường
risk_pct                        0,50% mỗi lệnh
trần giá trị mỗi mã              20% cơ sở vốn
trần giá trị gộp                100% cơ sở vốn     <- không đòn bẩy
số vị thế mở đồng thời tối đa      8
tỉ lệ tham gia                   <= 1% số cổ phần ADV trung vị trượt
                                 <= 10% khối lượng của chính bar vào lệnh
```

Cơ sở vốn chỉ tính lãi đã thực hiện, vì lý do kho này đã trả giá để học: định cỡ trên vốn tính theo giá thị trường là bảo sổ tiêu khoản lãi chưa thực hiện, và khi đo trên tuyến futures nó tốn **288 trên 691 lần vào lệnh (42%) bị ảnh hưởng vì hết tiền, 170 lệnh mất hẳn**, tiền mặt ở phân vị 10 bằng 0%. Bản sửa hiệu quả không phải cái đệm đắp lên một cơ sở sai — mà là đổi chính cơ sở. Ở đây tiền mặt không âm **theo cấu trúc**.

Số cổ phần tính từ khoảng cách stop **của chính luật** — giá tín hiệu chưa làm tròn so với stop chưa làm tròn, đúng bằng `2,0 x ATR ngày` — chứ không phải từ giá vào lệnh hai chữ số thập phân mà engine ghi sổ. Định cỡ trên cặp đã làm tròn chỉ tái tạo được luật trên 58% số dòng. Chỗ này bị một phép tự kiểm bắt, không phải do đọc mà ra; xem mục 5.3.

### 1.7 Kiểm soát rủi ro nào chuyển được, cái nào phải thiết kế lại?

| kiểm soát của Track 1 | tuyến cổ phiếu |
|---|---|
| stop cố định `2,0 x ATR ngày`, neo tại entry, không dịch theo | **chuyển nguyên vẹn về hình thức.** Bội số là đại lượng không thứ nguyên. *Tác dụng* của nó thì không chuyển: xem mục 8 S-2 |
| max hold 5 | **chuyển được, và mang theo một lỗi** — phép đếm là ngày lịch (S-3) |
| stop vũ trang 14:05 phiên sau | **chuyển được, và ở đây nguy hiểm hơn** (mục 1.4) |
| trần cụm theo % tài khoản $50k (`5,0/4,4%` swing, `10%` stress, `6%` NKD) | **không chuyển được.** Đó là trần gộp/ròng theo cụm trên một sổ futures nhiều nhất năm công cụ. Thay bằng rủi ro mỗi lệnh cộng trần theo mã, trần gộp và trần đồng thời, vì ràng buộc thật của một sổ 60 mã cổ phiếu là bề rộng chứ không phải một cụm |
| ngắt tài khoản: sụt cứng 15%, lỗ ngày 4% | **chưa cài ở tầng này, và đó là lỗ hổng chứ không phải quyết định.** Stage STOCKS-0 đo xem tín hiệu có sống qua chi phí không; một cái ngắt sẽ đổi tập lệnh và làm nhiễu phép đo đó. Nó là chốt chặn trước khi paper |
| chốt chặn day-trade PDT | **không ràng buộc, và điều này là đo chứ không phải lập luận.** Vào lệnh 14:00-15:55 và giữ tối thiểu một phiên, nên không có vòng trọn nào mở và đóng trong cùng ngày |
| `point_value`, `tick`, `tradable_symbol` | **đã thay.** Mục 2 |
| khả năng vay để bán khống | **mới, và chưa đáp ứng.** Bán khống futures không cần đi vay. Trên đĩa này không có dữ liệu vay, nên khả năng vay là giả định |
| sự kiện doanh nghiệp | **mới.** Chỉ được xử lý bởi phép điều chỉnh chia tách/cổ tức của nhà cung cấp. Mục 7.3 nói cái đó phủ và không phủ những gì |

---

## 2. Đã từ chối những gì, và cái giá của việc từ chối

Ba giả định futures bị gỡ. Mỗi cái là một con số, không phải một ý kiến.

### 2.1 Định cỡ theo hợp đồng

Engine chạy với `point_value = 1.0` và `round_turn_cost = 0.0`, nên cột `pnl` của nó là chuyển động giá của **một cổ phần**, và mọi đồng chi phí được áp ở tầng sổ, nơi số cổ phần tồn tại và soi được từng dòng. Trong tuyến này không có chỗ nào nhân giá với một hệ số futures.

Đây đúng là họ lỗi mà Track 1 đã tìm ra bằng cách đắt tiền vào 2026-08-14: lệnh MNKD định tuyến sang hợp đồng NKD cỡ đầy đủ, gấp mười lần kích cỡ dự định, **-$1.400,00 ở broker so với -$140,00 trong sổ sleeve, đúng 10,0000 lần**. Hash cấu hình của tuyến cổ phiếu không mang `point_value` nào cả, vì không có gì cho nó gọi tên.

### 2.2 Cái ATR mà stop neo vào

`futures._validated_core.daily_atr_series` là `tr.rolling(period).mean()` đánh chỉ số theo ngày, nên giá trị tại ngày D là trung bình **kết thúc TẠI D** và chứa chính đỉnh và đáy của D. `track1_normal_r4.make_signal_fn` đọc nó bằng `datr.asof(day)` cho một lần vào lệnh lúc 14:00 của chính ngày D đó.

Đo trên cache này — hai định nghĩa trên cùng một frame ngày:

| mã | phiên | causal == engine.shift(1) | lệch trung vị | p90 | lớn nhất |
|---|---:|---|---:|---:|---:|
| AAPL | 1496 | có | 2.92% | 8.29% | 51.49% |
| MSFT | 1496 | có | 2.73% | 7.93% | 71.01% |
| JPM | 1496 | có | 2.56% | 7.44% | 35.20% |
| XOM | 1496 | có | 2.56% | 6.78% | 32.10% |
| TSLA | 1496 | có | 2.69% | 7.92% | 41.52% |
| SPY | 1496 | có | 3.21% | 8.59% | 31.97% |

Và nó không đều. Trên 20 phiên biên độ rộng nhất của AAPL, hai định nghĩa lệch nhau trung vị **7.70%**, so với 2.92% trên toàn bộ số ngày — khoảng cách lớn nhất đúng ở nơi độ rộng stop quan trọng nhất.

Tuyến cổ phiếu neo vào chuỗi đã dịch một phiên. **Chuyện này gây ra gì cho tuyến futures thì ở đây KHÔNG đo và KHÔNG khẳng định** — xem mục 8, phát hiện T-1.

### 2.3 Ngưỡng của bộ lọc bối cảnh R4

`FLOOR_RANGE_P90 = 0.02652437` được ghi rõ là *p90 của biên độ RTH hôm trước trên các lần vào lệnh R4 ở cửa sổ nền* — tức một phân vị của phân bố **futures**. Đem sang cổ phiếu đơn lẻ, nó vẫn là một con số nhưng không còn là một phân vị. Chính `route_params` mang `r4_range_threshold` và `r4_range_derivation_window` thành hai trường riêng đúng vì lý do này: *một ngưỡng suy ra từ một cửa sổ là một thứ khác khi cửa sổ dịch đi*.

Việc bỏ bộ lọc thay vì cấy ngưỡng sang cũng có tiền lệ: `run_instrument(..., apply_context_filter=False)` chính là cách sleeve `global_nkd` chạy cùng bộ máy đó, vì bộ lọc là chuyện của R4 và áp nó lên một họ công cụ khác là bịa ra một luật mới.

Nên cấu hình chính chạy **không có** nó, và cả hai phương án đều được đo như độ nhạy đã khai báo: cấu hình `C` cấy nguyên hằng số futures, cấu hình `D` suy lại p90 chỉ trên nửa trong mẫu của cổ phiếu. Mục 3.4.

---

## 3. Kết quả

### 3.1 Bốn cấu hình

Cả bốn đều khai báo trước. Không cái nào được chọn sau khi nhìn kết quả; `B` được gọi tên là cấu hình chính trước lượt chạy đầu tiên.

| | cấu hình | ứng viên | nhận | ròng | gộp | chi phí | PF | thắng | sụt tối đa | Calmar |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | `signal_only` | 7385 | 894 | -$16,178 | -$7,890 | +$8,289 | 0.84 | 45.5% | +$20,778 | -0.2 |
| B | `spy_short_gate` **(chính)** | 6268 | 883 | +$9,282 | +$18,790 | +$9,507 | 1.08 | 50.4% | +$19,900 | 0.12 |
| C | `r4_filter_futures_threshold` | 4689 | 858 | +$3,897 | +$13,123 | +$9,226 | 1.04 | 51.5% | +$18,972 | 0.05 |
| D | `r4_filter_stock_p90` | 5296 | 868 | -$1,662 | +$7,369 | +$9,031 | 0.98 | 49.7% | +$24,298 | -0.02 |

### 3.2 Trong mẫu so với ngoài mẫu (cấu hình chính)

Phép chia này để mô tả, không để chọn: **không thứ gì ở tầng này được chọn trên nửa trong mẫu**, nên nửa ngoài mẫu là một cái nhìn thứ hai vào cùng một luật chưa tinh chỉnh, chứ không phải phép xác nhận cho một luật đã khớp.

| nửa | lệnh | ròng | PF | thắng | kỳ vọng/lệnh | sụt tối đa |
|---|---:|---:|---:|---:|---:|---:|
| trong mẫu 2019-2020 | 435 | +$11,607 | 1.24 | 51.5% | +$27 | +$8,948 |
| ngoài mẫu 2021-2022 | 448 | -$2,324 | 0.96 | 49.3% | -$5 | +$19,900 |

### 3.3 Từng năm (cấu hình chính)

| năm | lệnh | ròng | tỉ lệ thắng |
|---|---:|---:|---:|
| 2019 | 195 | +$10,146 | 53.3% |
| 2020 | 240 | +$1,460 | 50.0% |
| 2021 | 236 | +$5,038 | 52.1% |
| 2022 | 212 | -$7,362 | 46.2% |

### 3.4 Hai biến thể bộ lọc làm được gì

**Cấu hình C — cấy nguyên hằng số futures.** Ngưỡng `0.02652437134968455`.

```text
bar đưa vào bộ lọc                17,488
chặn vì biên độ hôm trước          4,608    26.3%
chặn vì rvol bar vào               3,560    20.4%
chặn vì thiếu đặc trưng                0     0.0%
cho qua                            9,320    53.3%
```

Kết quả: 4689 ứng viên, 858 nhận, ròng +$3,897, PF 1.04.

**Cấu hình D — suy lại p90 chỉ trên nửa trong mẫu của cổ phiếu.** Ngưỡng `0.035788452563709244`.

```text
bar đưa vào bộ lọc                16,838
chặn vì biên độ hôm trước          1,663     9.9%
chặn vì rvol bar vào               4,223    25.1%
chặn vì thiếu đặc trưng                0     0.0%
cho qua                           10,952    65.0%
```

Kết quả: 5296 ứng viên, 868 nhận, ròng -$1,662, PF 0.98.

### 3.5 Tiền đến từ đâu (cấu hình chính)

```text
số mã có giao dịch      75
phần của mã số 1        26.9%
phần của 5 mã đầu       110.5%
```

Mười mã tốt nhất và mười mã tệ nhất:

| mã | lệnh | ròng | | mã | lệnh | ròng |
|---|---:|---:|---|---|---:|---:|
| PEP | 11 | +$2,499 | | QQQ | 21 | -$4,228 |
| PANW | 19 | +$2,472 | | ORCL | 12 | -$1,600 |
| QCOM | 15 | +$1,814 | | MSFT | 9 | -$1,208 |
| CSCO | 9 | +$1,771 | | NFLX | 14 | -$1,194 |
| EBAY | 7 | +$1,698 | | LLY | 17 | -$1,172 |
| XLE | 8 | +$1,507 | | SPY | 13 | -$1,148 |
| JPM | 8 | +$1,397 | | PYPL | 14 | -$1,142 |
| TXN | 10 | +$1,299 | | NOW | 12 | -$910 |
| HD | 10 | +$1,234 | | AMGN | 17 | -$887 |
| XLY | 17 | +$1,221 | | AVGO | 14 | -$813 |

### 3.6 Lệnh kết thúc kiểu gì, và quay về hướng nào

| lý do thoát | lệnh | ròng |
|---|---:|---:|
| `MAX_HOLD` | 789 | +$61,648 |
| `CHANDELIER` | 88 | -$48,593 |
| `GAP` | 6 | -$3,772 |

| hướng | lệnh | ròng |
|---|---:|---:|
| LONG | 783 | +$18,289 |
| SHORT | 100 | -$9,007 |

```text
nắm giữ trung bình  5.72 ngày lịch   (trung vị 6.0)
vòng quay           112.0 lần vốn ban đầu trong 3.9 năm
chi phí             50.6% lãi gộp
```

### 3.7 Mười lệnh lãi nhất và mười lệnh lỗ nhất

| | mã | vào lệnh | hướng | cổ phần | ròng | thoát |
|---|---|---|---|---:|---:|---|
| L1 | QCOM | 2020-07-29 14:15 | LONG | 111 | +$1,594 | `MAX_HOLD` |
| L2 | BIIB | 2020-08-03 14:15 | LONG | 43 | +$1,243 | `MAX_HOLD` |
| L3 | CSCO | 2019-05-13 14:35 | LONG | 262 | +$1,160 | `MAX_HOLD` |
| L4 | GOOGL | 2021-07-20 14:10 | LONG | 168 | +$1,080 | `MAX_HOLD` |
| L5 | PEP | 2021-07-12 14:15 | LONG | 162 | +$1,073 | `MAX_HOLD` |
| L6 | GE | 2021-05-26 14:30 | LONG | 210 | +$968 | `MAX_HOLD` |
| L7 | MA | 2022-01-24 14:25 | LONG | 25 | +$954 | `MAX_HOLD` |
| L8 | XLY | 2019-06-03 14:10 | LONG | 301 | +$902 | `MAX_HOLD` |
| L9 | JNJ | 2019-05-28 14:10 | SHORT | 129 | +$856 | `MAX_HOLD` |
| L10 | LLY | 2022-04-18 14:15 | SHORT | 43 | +$851 | `MAX_HOLD` |
| X1 | WFC | 2020-01-09 14:10 | LONG | 418 | -$1,050 | `MAX_HOLD` |
| X2 | XLI | 2020-06-08 14:10 | LONG | 140 | -$921 | `GAP` |
| X3 | DE | 2021-07-12 14:10 | LONG | 43 | -$814 | `MAX_HOLD` |
| X4 | GS | 2021-09-20 14:15 | SHORT | 42 | -$670 | `GAP` |
| X5 | GOOGL | 2021-09-20 14:20 | SHORT | 157 | -$650 | `CHANDELIER` |
| X6 | MRK | 2021-09-20 14:15 | SHORT | 269 | -$650 | `CHANDELIER` |
| X7 | CAT | 2021-09-20 14:15 | SHORT | 86 | -$639 | `CHANDELIER` |
| X8 | QQQ | 2021-09-27 14:15 | LONG | 61 | -$626 | `CHANDELIER` |
| X9 | ORCL | 2021-09-27 14:15 | LONG | 157 | -$625 | `CHANDELIER` |
| X10 | AMAT | 2021-07-12 14:10 | LONG | 80 | -$621 | `CHANDELIER` |

### 3.8 Vì sao ứng viên bị từ chối

| lý do | số lượng |
|---|---:|
| `max_concurrent_positions` | 5077 |
| `gross_notional_cap` | 283 |
| `price_below_floor` | 16 |
| `adv_below_floor` | 9 |

Một ứng viên bị từ chối **không** giải phóng mã của nó cho một lần vào lệnh khác trong phiên. Engine giữ tối đa một vị thế mỗi mã và sổ mới quyết sau đó là có kham nổi hay không, nên một lần từ chối lấy đi một lệnh mà không mở ra một suất. Sổ của chính Track 1 cũng vậy; nêu ra ở đây vì bảng từ chối rất dễ bị đọc như thể những lệnh đó đã được thay bằng lệnh khác.

### 3.9 Cửa sổ dài nhất dữ liệu cho phép: 2018-01-02 → 2022-12-30

Câu hỏi đặt ra là lãi ròng cho **2018 đến 2026**. Cửa sổ đó không dựng được, và biên giới là dữ liệu chứ không phải lựa chọn. Đếm số phiên có bar 5 phút thật, trên toàn bộ 75 mã, theo từng năm:

| năm | phiên-mã có bar |
|---|---:|
| 2017 | 18,574 |
| 2018 | 18,574 |
| 2019 | 18,648 |
| 2020 | 18,722 |
| 2021 | 18,777 |
| 2022 | 18,486 |
| 2023 | **0** |
| 2024 | **0** |
| 2025 | **0** |
| 2026 | **0** |

**2023 tới 2026 rỗng tuyệt đối** — không phải thưa, là không có bar nào, kiểm chéo trên sáu mã lớn nhất đều đủ 251-253 phiên mỗi năm tới hết 2022 rồi đúng 0 từ 2023. **2017 có bar nhưng không gán nhãn chế độ được**: mô hình HMM chỉ gán nhãn cho các ngày SAU cửa sổ huấn luyện, và bản sản xuất bắt đầu gán từ 2018-01-02.

Nên cửa sổ dài nhất khả thi là **năm năm 2018-2022**, và nó chỉ chạy được với bộ nhãn **sản xuất** — bộ khớp tới 2024-12-31. Với các phiên 2018-2022 thì đó là **nhìn trước ở tầng nhãn**. Con số dưới đây mang tư cách đó và không được đặt ngang hàng với con số bốn năm sạch nhân quả ở trên.

```text
ứng viên       9388      nhận      1259      từ chối      8129
lãi gộp    +$16,528      chi phí +$12,856      lãi ròng  +$3,672
tổng          3.67%      CAGR     0.74%      sụt tối đa +$19,325
PF             1.02      thắng    51.2%      Calmar       0.04
chi phí ăn 77.8% lãi gộp
```

| năm | lệnh | ròng | thắng |
|---|---:|---:|---:|
| 2018 | 201 | +$3,032 | 53.2% |
| 2019 | 183 | +$5,840 | 53.0% |
| 2020 | 271 | -$1,196 | 51.7% |
| 2021 | 267 | +$7,794 | 55.8% |
| 2022 | 337 | -$11,798 | 44.8% |

Trả lời thẳng: **2018 đóng góp n/a**, và tổng năm năm vẫn nhỏ hơn khoản thua của riêng năm 2022.

| nửa | lệnh | ròng | PF | sụt tối đa |
|---|---:|---:|---:|---:|
| trong mẫu 2018 → giữa 2020 | 479 | +$6,774 | 1.11 | +$8,661 |
| ngoài mẫu giữa 2020 → 2022 | 780 | -$3,102 | 0.97 | +$19,817 |

Và phân rã theo lối thoát trên cửa sổ này nói rõ hình dạng lãi/lỗ hơn bất kỳ chỉ số tổng hợp nào:

| thoát kiểu | lệnh | ròng | mỗi lệnh |
|---|---:|---:|---:|
| `MAX_HOLD` | 1121 | +$81,482 | +$73 |
| `CHANDELIER` | 125 | -$67,988 | -$544 |
| `GAP` | 13 | -$9,822 | -$756 |

**138 trên 1259 lệnh (11%) làm mất -$77,810; số còn lại kiếm +$81,482.** Phần chênh mỏng dính đó là toàn bộ "lãi" của năm năm — và nó khớp đúng với S-3: mức cắt lỗ chưa sống trong đêm đầu tiên, nên khi nó kích hoạt thì cú đi ngược đã hoàn tất, còn những lần nhảy qua mức cắt lỗ khớp tại giá mở.

---

## 4. Độ nhạy theo chi phí, trượt giá và định cỡ

Mỗi dòng dưới đây ghi sổ lại **cùng một dòng ứng viên đã cache**, chỉ đổi đúng một đầu vào. Chạy lại cả backtest cho từng biến thể sẽ đổi luôn tập lệnh, và khi đó một khoản chênh lệch là bằng chứng về hai backtest chứ không phải về một tham số. Đây đúng là hình dạng mà Stage 5Q-9 của Track 1 dùng để giải quyết câu hỏi cơ sở định cỡ của chính nó.

### 4.1 Trượt giá

| bps mỗi chiều | ròng | chi phí | PF | thắng | lệnh |
|---:|---:|---:|---:|---:|---:|
| 0.0 | +$16,108 | +$2,832 | 1.14 | 52.1% | 886 |
| 1.0 | +$13,905 | +$5,104 | 1.13 | 51.9% | 885 |
| 3.0 | +$9,282 | +$9,507 | 1.08 | 50.4% | 883 |
| 5.0 | +$4,961 | +$13,743 | 1.04 | 49.4% | 884 |
| 10.0 | -$5,268 | +$23,587 | 0.95 | 47.7% | 884 |
| 20.0 | -$22,790 | +$40,419 | 0.79 | 44.4% | 885 |

**Trượt giá hoà vốn: 7.38 bps mỗi chiều.** Vượt mức đó thì lãi ròng của tuyến này âm. Đây là con số liên quan tới quyết định nhiều nhất trong cả báo cáo: nó nói kết quả đang mua bằng bao nhiêu chất lượng thực thi, và phải đem so với thứ tài khoản thật sự đạt được, chứ không so với một hy vọng.

### 4.2 Hoa hồng

| $/cổ phần | lệnh | ròng | sụt tối đa | PF |
|---:|---:|---:|---:|---:|
| 0.0 | 887 | +$9,501 | +$19,922 | 1.09 |
| 0.0035 | 884 | +$9,446 | +$19,901 | 1.09 |
| 0.005 | 883 | +$9,282 | +$19,900 | 1.08 |
| 0.01 | 884 | +$8,383 | +$20,268 | 1.08 |

### 4.3 Lãi vay bán khống

| bps/năm | lệnh | ròng | sụt tối đa | PF |
|---:|---:|---:|---:|---:|
| 0.0 | 887 | +$9,359 | +$19,862 | 1.08 |
| 50.0 | 883 | +$9,282 | +$19,900 | 1.08 |
| 200.0 | 885 | +$8,897 | +$20,307 | 1.08 |
| 1000.0 | 886 | +$6,850 | +$20,857 | 1.06 |

### 4.4 Rủi ro mỗi lệnh

| risk_pct | lệnh | ròng | sụt tối đa | PF |
|---:|---:|---:|---:|---:|
| 0.0025 | 888 | +$3,412 | +$10,547 | 1.06 |
| 0.005 | 883 | +$9,282 | +$19,900 | 1.08 |
| 0.01 | 815 | +$8,474 | +$24,402 | 1.07 |
| 0.02 | 802 | +$6,573 | +$28,461 | 1.05 |

### 4.5 Trần số vị thế đồng thời

| max_concurrent_positions | lệnh | ròng | sụt tối đa | PF |
|---:|---:|---:|---:|---:|
| 2 | 224 | -$1,316 | +$6,670 | 0.95 |
| 4 | 446 | +$482 | +$12,221 | 1.01 |
| 8 | 883 | +$9,282 | +$19,900 | 1.08 |
| 16 | 1187 | +$9,649 | +$22,729 | 1.08 |
| 100 | 1189 | +$9,688 | +$22,692 | 1.08 |

### 4.6 Trần tỉ lệ tham gia ADV

| max_pct_of_adv_shares | lệnh | ròng | sụt tối đa | PF |
|---:|---:|---:|---:|---:|
| 0.001 | 883 | +$9,282 | +$19,900 | 1.08 |
| 0.005 | 883 | +$9,282 | +$19,900 | 1.08 |
| 0.01 | 883 | +$9,282 | +$19,900 | 1.08 |
| 0.05 | 883 | +$9,282 | +$19,900 | 1.08 |

### 4.7 Mã đơn lẻ so với ETF

| tập con | ứng viên | lệnh | ròng | PF | thắng |
|---|---:|---:|---:|---:|---:|
| chỉ mã đơn lẻ | 5045 | 875 | +$11,513 | 1.1 | 51.3% |
| chỉ ETF | 1223 | 772 | +$10,965 | 1.12 | 52.8% |

Đáng tách ra vì một ETF ngành và một mã đơn lẻ không phải cùng một công cụ khi hỏi về vay mượn, thanh khoản hay sự kiện doanh nghiệp, và một con số đầu bảng gộp cả hai sẽ che mất cái nào đang gánh.

### 4.8 Lãi ròng có phân biệt được với 0 không?

Các lệnh không phải những lần rút độc lập — nhiều mã thường phát tín hiệu trong cùng một phiên rồi cùng chia nhau hướng đi của thị trường suốt năm ngày sau. Nên đơn vị lấy mẫu lại ở đây là **phiên vào lệnh**: rút một ngày có hoàn lại thì mọi lệnh của ngày đó đi theo. Giả thuyết null là lãi/lỗ mỗi lệnh **đã dịch về trung bình 0**, và điều này nói thẳng ra vì kho này đã tìm thấy phương án ngược lại trong chính mã của mình: một null chưa căn giữa trong `cluster_bootstrap.py` đã thổi phồng mức ý nghĩa lên khoảng 2 lần, và lấy mẫu lại từ mẫu thô là đang kiểm "chiến lược này có đúng cái edge mà nó trông như đang có không" — câu đó mẫu nào cũng qua.

| cửa sổ | lệnh | ngày vào lệnh | ròng | KTC 95% | p (một phía) |
|---|---:|---:|---:|---|---:|
| toàn bộ 2019-01-02..2022-12-30 | 883 | 157 | +$9,282 | [-$23,601, +$41,298] | **0.2855** |
| trong mẫu 2019-2020 | 435 | 70 | +$11,607 | [-$9,702, +$32,739] | **0.1459** |
| ngoài mẫu 2021-2022 | 448 | 87 | -$2,324 | [-$26,697, +$21,691] | **0.5799** |

Phép tự kiểm có khả năng đỏ: một mẫu **không có edge** dựng nhân tạo, cùng cách gom cụm theo ngày và cùng độ phân tán, cho p = **0.967**. Nếu cái đó ra có ý nghĩa thống kê thì null đã căn sai và mọi p-value bên trên đều vô giá trị.

Cái nó **không** nói: không nói gì về thiên lệch sống sót, không nói gì về việc các giả định chi phí có đúng không, và không nói gì về việc luật có được chọn sau khi nhìn dữ liệu hay không. Một p nhỏ trên một danh sách toàn kẻ sống sót vẫn là một p nhỏ trên một mẫu thiên lệch. Và một p không vượt ngưỡng là **thiếu bằng chứng, chứ không phải bằng chứng phủ định** — dự án này đã phải nói câu đó hai lần rồi.

### 4.9 Tách tuyến thành từng nhánh

Một con số gộp che mất nhánh nào gánh và nhánh nào kéo xuống. Nhưng phép tách này phải đọc bằng **hai nghĩa khác nhau**, và lẫn chúng là cách dễ nhất để kết luận sai:

- **Quy kết** — lấy đúng các dòng của nhánh đó *trong cuốn sổ đã chạy*. Các nhánh cộng lại đúng bằng tổng (đã kiểm: lệch $0,00).
- **Phản thực** — ghi sổ lại chỉ với ứng viên của nhánh đó, cho nó *toàn bộ* sức chứa. Các nhánh **không** cộng lại thành tổng, vì mỗi nhánh được dùng lại cùng số vốn.

Sổ bị chặn bởi vốn — khoảng chín vị thế cùng lúc cho 6.268 ứng viên — nên bỏ một nhánh thì nhánh còn lại không giữ nguyên số lệnh của nó: nó được thêm suất.

**Quy kết** (cộng lại = tổng sổ):

| nhánh | lệnh | ròng | $/lệnh | KTC 95% | p |
|---|---:|---:|---:|---|---:|
| LONG | 783 | +$18,289 | +$23 | [-$13,716, +$48,497] | 0.1221 |
| SHORT | 100 | -$9,007 | -$90 | [-$21,513, +$3,497] | 0.9318 |
| mã đơn lẻ | 697 | +$12,264 | +$18 | [-$13,075, +$37,165] | 0.1661 |
| ETF | 186 | -$2,982 | -$16 | [-$14,612, +$8,197] | 0.7041 |
| LONG · mã đơn lẻ | 613 | +$20,752 | +$34 | [-$2,788, +$43,850] | 0.0378 |
| LONG · ETF | 170 | -$2,463 | -$14 | [-$13,811, +$8,491] | 0.6709 |
| SHORT · mã đơn lẻ | 84 | -$8,488 | -$101 | [-$19,984, +$2,567] | 0.9412 |
| SHORT · ETF | 16 | -$519 | -$32 | n/a | n/a |

**Phản thực** (mỗi nhánh chạy riêng, nguyên vốn — KHÔNG cộng lại được):

| nhánh | ứng viên | lệnh | ròng | PF | sụt tối đa | p |
|---|---:|---:|---:|---:|---:|---:|
| LONG | 5567 | 872 | +$24,014 | 1.22 | +$20,617 | 0.1044 |
| SHORT | 701 | 213 | -$15,958 | 0.53 | +$18,194 | 0.9681 |
| mã đơn lẻ | 5045 | 875 | +$11,513 | 1.1 | +$15,151 | 0.2272 |
| ETF | 1223 | 772 | +$10,965 | 1.12 | +$22,944 | 0.2436 |
| LONG · mã đơn lẻ | 4470 | 861 | +$27,757 | 1.25 | +$15,795 | 0.0646 |
| LONG · ETF | 1097 | 728 | +$18,117 | 1.21 | +$23,232 | 0.1458 |
| SHORT · mã đơn lẻ | 575 | 209 | -$15,046 | 0.55 | +$17,356 | 0.9636 |
| SHORT · ETF | 126 | 109 | -$5,337 | 0.68 | +$10,960 | 0.7998 |

**Bỏ một nhánh khỏi sổ gộp:**

| bỏ nhánh | lệnh | ròng | chênh so với gộp | PF |
|---|---:|---:|---:|---:|
| bỏ SHORT | 872 | +$24,014 | +$14,731 | 1.22 |
| bỏ ETF | 875 | +$11,513 | +$2,231 | 1.1 |
| bỏ SHORT · mã đơn lẻ | 886 | +$16,476 | +$7,194 | 1.15 |
| bỏ SHORT · ETF | 884 | +$7,157 | -$2,126 | 1.06 |

Dòng cuối bảng đó là phép kiểm cho chính lời cảnh báo ở trên: **bỏ nhánh `SHORT · ETF` làm sổ XẤU ĐI** dù bản thân nhánh ấy lỗ. Bỏ 16 lệnh thua nhỏ giải phóng suất cho những lệnh còn tệ hơn. Dưới ràng buộc vốn, "cắt cái đang lỗ" không phải phép cộng.

#### Đọc kết quả này thế nào cho đúng

**Chân bán khống là gánh nặng, và điều đó nhất quán ở mọi cách cắt.** Quy kết −$90 mỗi lệnh; chạy riêng thì PF 0,53 và p = 0,97 — tức bằng chứng nghiêng hẳn về phía nó thật sự âm, không phải nhiễu. Bỏ nó ra, sổ đi từ +$9.282 lên +$24.014.

**Nhưng nhánh tốt nhất là nhánh bị nhiễm nặng nhất, và p của nó không sống nổi qua phép đếm.** `LONG · mã đơn lẻ` cho p = 0,0378 khi quy kết và 0,0646 khi chạy riêng. Đó là **một trong tám nhánh** được thử. Với tám phép kiểm, xác suất có ít nhất một p < 0,05 thuần do may rủi đã là khoảng 34%; nhân thô cho số phép kiểm thì 0,0378 × 8 ≈ 0,30. Các nhánh lại lồng nhau nên phép nhân đó là bảo thủ — nhưng kết luận không đổi: **đây là một lát cắt hậu kiến, không phải một phát hiện**.

Và chiều của thiên lệch trỏ đúng vào nhánh ấy. Rổ mã là danh sách kẻ sống sót; mua cổ phiếu đơn lẻ đã biết là sống sót chính là thứ được cho sẵn đáp án nhiều nhất, còn bán khống chúng là thứ bị phạt nặng nhất. **Hai phát hiện — chân mua thắng, chân bán thua — không phải hai bằng chứng độc lập; chúng là cùng một thiên lệch nhìn từ hai phía.**

---

## 5. Chứng minh không nhìn trước

Một tuyên bố về nhân quả mà không thể đỏ thì không phải chứng minh. Mọi phép kiểm ở đây đều là **đột biến**, nói trước câu trả lời phải dịch theo hướng nào, và mỗi nhánh xanh đều đi kèm một nhánh đỏ bắt buộc phải dịch — nếu không thì nhánh xanh đang qua một cách rỗng.

| kiểm | phá cái gì | kết quả bắt buộc | đo được |
|---|---|---|---|
| **P1** | mọi bar NGAY SAU bar tín hiệu, nhân 1,5 | tín hiệu được nhận không đổi | **36/36 không đổi** |
| **P1r** *(nhánh đỏ)* | mọi bar NGAY TRƯỚC bar tín hiệu, nhân 1,5 | tín hiệu PHẢI dịch, nếu không thì P1 chẳng chứng minh gì | **36/36 đã dịch** |
| **P2** | không phá gì — cắt cửa sổ tại bar tín hiệu | phép quét nhân-quả-như-live tìm ra cùng bar, cùng hướng, cùng giá vào và cùng stop như phép quét nghiên cứu cả ngày | **36/36 trùng khít** |
| **P3** | giá đóng SPY CỦA ngày D, nhân 10 | nhãn chế độ mà tuyến này đọc cho D không dịch, còn các nhãn sau đó thì dịch | **không đổi=True, 8/40 nhãn sau đã dịch** |
| **P4** | y như trên, qua `short_days_from_csv` | tư cách thành viên cổng SHORT của chính D không dịch, các ngày sau thì dịch | **không đổi=True, 48/62 ngày sau đã dịch** |

Cả 11 phép tự kiểm đều qua.

**P2 chính là câu trả lời riêng cho câu hỏi về phép quét cả ngày.** Nghiên cứu quét 14:00-15:55 trong một lượt; một slot live tại thời điểm T chỉ nhìn được 14:00..T. Hai bên trùng nhau, và trùng vì một lý do phát biểu được chứ không phải nhờ may: `_scan_window` lấy khối lượng trung bình từ `win['volume'].iloc[k-11:k-1]`, tức nhìn hoàn toàn về phía sau từ mỗi bar, nên cắt đuôi cửa sổ không thể đổi trung bình ở bất kỳ bar nào sống sót qua nhát cắt. Track 1 khẳng định đúng phép tương đương này cho `detect_entry_for_slot`; đây là khẳng định đó chạy lại trên bar cổ phiếu.

### 5.1 Cái gì nhân quả theo cấu tạo, và nói rõ ra như vậy

```text
ATR ngày          dịch một phiên        -- mục 2.2
nhãn chế độ       lag 1                 -- nhãn mới nhất TỒN TẠI lúc 14:00 ngày D
cổng SHORT SPY    lag 1 theo cấu tạo    -- spy.shift(1) bên trong spy_feature_frame
sàn ADV           trung vị, dịch một phiên
biên độ hôm trước phiên TRƯỚC, dịch bên trong prev_rth_range_map
rvol bar vào      khối lượng của chính bar vào, thứ ĐÃ biết tại giá đóng của nó, vì
                  engine vào lệnh tại chính giá đóng đó
```

### 5.2 Đúng một thứ ở đây KHÔNG được chứng minh

Mô hình HMM trong bộ nhãn `production` khớp tới **2024-12-31** và được dùng để gán nhãn cho các phiên 2019-2022. Đó là nhìn trước, không tránh được nếu muốn dùng bản đóng băng sản xuất của futures, và đó là lý do lượt chạy chính dùng bộ nhãn `causal` — khớp tới 2018-12-31, chỉ gán nhãn các phiên sau đó. Hai bộ thống nhất trên **80,3% số phiên**, nên lựa chọn này có gánh việc và cả hai đều được báo cáo. Mục 6.2.

### 5.3 Một phép tự kiểm đã đỏ, và nó bắt được gì

`LC4` khẳng định `stop_distance == 2,0 x ATR ngày` tới 1e-9. Ở lượt chạy đầu nó đo được **0,5802** — 42% số dòng sai. Nguyên nhân không nằm ở engine: sổ đang đo khoảng cách stop so với giá vào lệnh *đã ghi sổ* hai chữ số thập phân, trong khi bản thân stop chưa làm tròn, nên khoảng cách sai tới nửa xu và số cổ phần sai theo. Sửa bằng cách định cỡ trên khoảng cách của chính luật và mang theo cả hai mức giá. `LC4` giờ đo được **1,0**, và lãi ròng dịch khoảng $6 trên lượt chạy thử ba mã — đó mới là điểm chính: đây là lỗi về tính đúng đắn, không phải về độ lớn, và chỉ một phép kiểm có khả năng đỏ mới bao giờ tìm ra nó.

---

## 6. Độ ổn định

**Cam kết trước khi chạy: `ema_period` giữ nguyên 50, bảng này in ra gì cũng vậy.** 50 là giá trị mà các artifact Track 1 được sinh ra dưới đó, và tầng này được giao việc tái tạo logic ứng viên chứ không phải tinh chỉnh nó. Phép quét trả lời một câu hỏi khác — kết quả có nằm trên lưỡi dao không — và một phép quét làm dịch giá trị đã chốt thì là curve fitting khoác áo nhãn ổn định.

Tập con: first 20 symbols alphabetically.

| lượt | lệnh | ròng | PF | thắng | sụt tối đa |
|---|---:|---:|---:|---:|---:|
| `ema20` | 858 | +$7,960 | 1.07 | 53.5% | +$19,665 |
| `ema30` | 860 | +$5,059 | 1.04 | 51.9% | +$22,136 |
| `ema50` | 821 | +$22,175 | 1.21 | 53.2% | +$12,645 |
| `prod_lag1` | 1005 | +$20,018 | 1.16 | 52.3% | +$19,263 |
| `prod_lag0` | 1033 | -$1,880 | 0.99 | 50.1% | +$15,342 |
| `causal_lag0` | 860 | +$10,112 | 1.09 | 51.4% | +$15,998 |

### 6.1 Vì sao phép quét EMA cũng là phép dò khả năng chuyển tuyến

Engine tính EMA trên bar 5 phút **của chính phiên đó**, bắt đầu từ bar đầu phiên. Đo trên `ES_continuous_1m.parquet` giai đoạn 2019-2022: một ngày lịch futures mang trung vị **273** bar 5 phút, trong đó **169 bar rơi vào lúc 14:00 ET hoặc sớm hơn**. Một phiên cổ phiếu RTH mang **78** bar, trong đó **55** bar rơi vào 14:00 hoặc sớm hơn. Vậy cùng một `EMA(50)` có 169 bar phía sau trên futures và 55 bar trên cổ phiếu — nhỉnh hơn chính chu kỳ của nó một chút, và vẫn còn bị giá trị khởi tạo chi phối thấy rõ. Đó không phải cùng một chỉ báo trên hai công cụ, dù tham số là cùng một con số. Nếu kết quả đảo mạnh qua 20/30/50 thì quãng khởi động đó đang gánh việc, và phép chuyển tuyến mong manh vì một lý do chẳng liên quan gì tới edge.

### 6.2 Nhãn chế độ và độ trễ

`causal` khớp HMM tới 2018-12-31; `production` là lời gọi y hệt của futures (`train_end=2018-01-01`, `hmm_fit_end=2024-12-31`). Hai bộ thống nhất trên **80,3%** số phiên và lệch nhau theo một hướng cụ thể — bản khớp causal gọi **26,0%** số phiên là Stress so với **13,4%** của bản production, đúng thứ mà docstring của chính `label_regimes` cảnh báo: một cửa sổ khớp ngắn làm trạng thái Stress bị định nghĩa thiếu. `lag0` là thứ `track1_params` khai báo cho `roska4_swing`; nó được đo và nó không phải con số đầu bảng, vì lúc 14:00 ngày D thì nhãn của D là hàm của một giá đóng còn cách đó hai tiếng.

---

## 7. Sống sót, thanh khoản và sự kiện doanh nghiệp

### 7.1 Thiên lệch sống sót — cảnh báo lớn nhất

> **Kết quả này thiên lệch vì sống sót và vì cách chọn mẫu, và không có gì trên đĩa này sửa được thiên lệch đó.**

Rổ mã là tập những cái tên mà ai đó đã chọn để cache bar 5 phút. Mã nào cũng lớn và thanh khoản vào lúc được chọn, và mã nào cũng sống qua 2019-2022. Một luật thiên về mua và đi theo xu hướng, chạy trên một danh sách toàn kẻ sống sót đã biết, là đang được cho sẵn đáp án. Trong kho không có tệp thành phần theo thời điểm nào — điều đó là **đã tìm**, không phải giả định, và mục 1.2 nêu tên những gì tìm thấy thay vào đó.

Phân bố hướng làm mức phơi nhiễm này thành cụ thể: **783 trên 883 lệnh (89%) là MUA**. Một danh sách kẻ sống sót thiên vị đúng phía đó.

### 7.2 Thanh khoản

```text
giá tối thiểu              $5,00
ADV tối thiểu              $20.000.000   (TRUNG VỊ giá trị giao dịch 20 phiên trượt,
                                          đã dịch một phiên)
tỉ lệ tham gia tối đa      1% số cổ phần ADV
                           10% khối lượng của chính bar 5 phút vào lệnh
```

Cố ý dùng trung vị chứ không phải trung bình cho ADV: một phiên báo cáo kết quả có thể kéo trung bình 20 ngày lên đủ để đưa một mã vượt qua cái sàn mà nó không giữ được vào ngày thường. Một ứng viên phạm sàn được ghi vào sổ là `REJECTED` kèm lý do, chứ không bị bỏ im lặng — một bộ lọc mà các lần từ chối vô hình thì không soi được.

Trên các mã lấy mẫu, các sàn này còn xa mới ràng buộc, và bản thân đó là một phát hiện — nghĩa là bộ lọc thanh khoản **không** phải thứ đang bảo vệ kết quả này, và một tuyến chạy trên rổ rộng hơn hoặc vốn hoá nhỏ hơn sẽ phải đo lại chứ không dùng lại:

| mã | ADV trung vị | ADV nhỏ nhất | giá đóng trung vị |
|---|---:|---:|---:|
| AAPL | $7,591,455,892 | $2,328,845,907 | $66.75 |
| MSFT | $3,654,315,703 | $902,607,116 | $153.69 |
| JPM | $1,211,374,761 | $797,113,558 | $113.35 |
| XOM | $870,275,578 | $442,272,011 | $76.32 |
| TSLA | $4,474,151,265 | $897,812,947 | $28.58 |
| SPY | $19,269,503,222 | $9,665,714,850 | $300.31 |

### 7.3 Sự kiện doanh nghiệp

**Chỉ** được xử lý bởi phép điều chỉnh chia tách và cổ tức của nhà cung cấp (`adjusted=true`). Cái đó phủ gì và không phủ gì:

| | |
|---|---|
| chia tách | có phủ — giá và khối lượng được điều chỉnh ngược |
| cổ tức thường | có phủ trong chuỗi giá, nên lãi/lỗ ngầm bao gồm cổ tức cho lệnh mua và tính phí cho lệnh bán khống, mà không bên nào hiện ra thành một dòng riêng |
| phép điều chỉnh ngược viết lại quá khứ | **đây là mối nguy đã biết, và ở đây KHÔNG đo.** Một khoản cổ tức trả năm 2026 làm đổi một mức giá đã điều chỉnh của 2019. Kho này đã từng phán về nguyên tắc đó cho futures: *giá lịch sử phải bất biến; nếu thêm dữ liệu mới mà giá của một năm cũ dịch đi thì phương pháp nối chuỗi sai.* Cache cổ phiếu mang đúng tính chất ấy theo cấu tạo và không có ảnh chụp đóng băng nào, nên **backtest này không tái tạo được tới từng xu sau lần làm mới cache kế tiếp** |
| huỷ niêm yết và sáp nhập | **không xử lý và ở đây không kiểm được** — trong rổ không có mã nào bị huỷ niêm yết, mà đó chính là bài toán sống sót nói lại một lần nữa |
| đổi mã | **không xử lý, và trong rổ có một ví dụ sống.** `META` chỉ có 290 trên 1008 phiên, bắt đầu 2021-06-30, và trong cache không hề có `FB`. Một mã đổi tên ngay trong cửa sổ thì bị thiếu lịch sử một cách im lặng chứ không có gì báo; sàn 250 phiên đã cho nó đi qua (mục 1.2) |

---

## 8. Phát hiện gửi lại — ba về Track 1, ba về phép chuyển tuyến

Ba mục về Track 1 lộ ra trong lúc đọc mã để chuyển nó. Mỗi mục được dán nhãn rõ cái gì đã đo và cái gì chưa, vì hai trong ba là quan sát từ đọc mã mà **tác động lên sổ futures thì tầng này không đo và không khẳng định**.

### T-1 · ATR của stop được đọc ngay trong ngày mà nó được tính từ đó — *đọc mã, chưa đo tác động trên futures*

`daily_atr_series` trả về trung bình trượt kết thúc tại ngày D. `make_signal_fn` đọc `datr.asof(day)` cho một lần vào lệnh trong 14:00-15:55 của chính ngày D đó. Nên giá trị ấy chứa các bar muộn hơn trong D so với thời điểm ra quyết định. Đo trên frame cổ phiếu, hai định nghĩa lệch trung vị khoảng 2,6-3,2% và tới 71%. **Nó gây ra gì cho sổ futures thì ở đây không đo.** Nó ảnh hưởng tới cả định cỡ lẫn thoát lệnh, vì `|entry - stop|` chính là cơ sở nhận lệnh mà Stage 5Q-9 đã chốt.

### T-2 · `roska4_swing` khai báo `label_lag_days = 0`, và live có thể không tôn trọng được điều đó — *đọc mã, CHƯA xác minh trọn đường*

```text
track1_params.py:414      label_lag_days=0                 (roska4_swing)
track1_normal_r4.py       labels.get(day)                  -- nhãn CỦA CHÍNH ngày D
run_scheduler.py:867      PRE-FLIGHT 13:45 ET -> update_spy_csv, fetch [.., today]
run_scheduler.py:955      spy_refresh_pm 16:20 ET          -- sau giờ đóng cửa
```

Nhãn của D là hàm của giá đóng 16:00 SPY ngày D. Một slot Normal-R4 nổ lúc 14:05 ngày D. Cả hai lần làm mới SPY đều nằm sai phía so với thời điểm đó: một lần lúc 13:45, khi giá đóng chưa tồn tại, và một lần lúc 16:20, sau khi slot đã qua. Vậy có ba trạng thái khả dĩ lúc 14:05 và **cả ba đều là một chỗ lệch giữa live và backtest**:

| lúc 14:05 ngày D, CSV đang giữ | thì `labels.get(D)` trả về | và live so với backtest |
|---|---|---|
| không có dòng nào cho D | `None` | sleeve không giao dịch được gì phiên đó |
| một dòng cho D dựng từ giá đóng **một phần** lúc 13:45 | một nhãn tính từ ảnh chụp trong ngày | một nhãn khác với nhãn backtest đã dùng, và nó bị ghi đè im lặng lúc 16:20 |
| một dòng cho D với giá đóng thật | đúng nhãn của backtest | bất khả thi lúc 14:05 |

**Chỗ này chưa truy tới kết luận và không được đọc như một kết luận.** Trạng thái nào xảy ra còn phụ thuộc vào việc Polygon có trả bar ngày đang dở lúc 13:45 hay không, và điều đó ở đây chưa kiểm. `track1_live_source` cũng mang một hàm phụ trợ `causal_regime_label` mà docstring của chính nó nói rằng đọc dòng của hôm nay là nhìn trước — nên tuyến live có thể đã lệch một cách có chủ đích, và khi đó thứ sai là *lời khai báo*, đúng hình dạng của phát hiện I-1 ở Stage 5Q-8.

Một thứ ĐÃ đo: lúc 2026-08-26 09:50 MDT, dòng cuối của `spy_daily_live.csv` là **2026-08-24**. Không có dòng nào cho thứ Ba 2026-08-25, nên dù cơ chế là gì, nhãn SPY mới nhất mà một slot đọc được hôm nay đã cũ hai phiên.

### T-3 · `max_hold_days` đếm theo ngày lịch — *đo ở đây, cả hai tuyến đều thừa hưởng*

`hold = (day - pos['entry_day']).days` với `max_hold_days = 5`. Vì phép đếm tính bằng ngày lịch trong khi vòng lặp bước qua từng phiên, số ngày nắm giữ thật phụ thuộc vào thứ trong tuần lúc vào lệnh: vào thứ Hai thì thoát sau năm phiên, vào thứ Tư thì thoát sau ba phiên. Trên frame futures gần như liên tục, méo mó này nhỏ hơn so với một tuần cổ phiếu năm phiên, nhưng nó là cùng một luật ở cả hai bên, và gần như chắc chắn không phải điều mà "max hold 5 ngày" định nói.

### S-1 · ngưỡng biên độ R4 là một phân vị futures — *đã đo*

Mục 2.3 và các dòng cấu hình `C`/`D` ở mục 3.4.

### S-2 · stop 2,0 x ATR gần như không ràng buộc trên cổ phiếu — *đã đo*

**789 trên 883 lần thoát (89%) là `MAX_HOLD`**, so với 88 lần thoát bằng stop (10.0%) và 6 lần thoát bằng gap. Trên chân trời năm ngày, cái stop gần như chỉ để trưng: luật đang hành xử như "giữ khoảng một tuần" kèm một tấm chắn rủi ro đuôi, chứ không phải như một lệnh được quản bằng stop. Hỗn hợp lối thoát của sleeve futures là gì thì cũng không phải cái này, và mọi trực giác mang từ bên đó sang về việc stop định hình phân bố ra sao đều không sống sót qua phép chuyển.

### S-3 · đêm đầu tiên không có stop — *hệ quả thiết kế, chưa đo thành chi phí*

Mục 1.4. Stop vũ trang lúc 14:05 phiên sau khi vào, nên khoảng nhảy qua đêm đầu tiên không được bảo vệ. Trên cổ phiếu đó là rủi ro đơn lẻ lớn nhất mà vị thế mang. Cái giá của nó ở tầng này **chưa** được tách ra; muốn tách phải chạy một lượt đổi luật vũ trang, và như vậy thì không còn là phép chuyển trung thành nữa.

---

## 9. Phán quyết, chốt chặn, tầng kế tiếp

### 9.1 Phán quyết

**BACKTEST_VALID.** Tập lệnh tái tạo được từ chính đoạn mã sinh ra nó, mọi ứng viên đều nằm trên sổ kèm lý do được nhận hay bị từ chối, các phép kiểm nhân quả đều qua với nhánh đỏ hoạt động, và mọi giả định riêng của cổ phiếu đều được khai báo và quét. "Hợp lệ" ở đây nghĩa là *phép đo vững và giới hạn của nó được nói ra* — nó không có nghĩa là triển khai được.

Về câu hỏi edge có chuyển được không, bốn thứ được cân, theo thứ tự này:

1. **nửa ngoài mẫu** — ròng -$2,324 trên 448 lệnh, PF 0.96;
2. **cái đó có phân biệt được với 0 không** — gom cụm theo ngày, null đã căn giữa, p = **0.5799**, KTC 95% [-$26,697, +$21,691];
3. **nó đang mua bằng bao nhiêu chất lượng thực thi** — trượt giá hoà vốn 7.38 bps mỗi chiều so với mức giả định 3,0;
4. **mẫu là cái gì** — một danh sách kẻ sống sót, không sửa được theo thời điểm bằng bất cứ thứ gì trên đĩa này.

Dòng phán quyết ở đầu báo cáo suy ra từ bốn thứ đó. Điểm 4 không phải một chú thích cho ba điểm kia: nó chặn mức độ tin được của cả ba, và đó là lý do tầng kế tiếp nói về nền đo chứ không nói về chiến lược.

### 9.2 Chốt chặn trước khi paper

| # | chốt chặn | vì sao nó chặn |
|---|---|---|
| 1 | **Thiên lệch sống sót.** Không có rổ theo thời điểm | kết quả đo trên một danh sách kẻ sống sót đã biết. Chừng nào tư cách thành viên chưa tính theo ngày, con số đầu bảng là một cận trên chưa biết chặt tới đâu |
| 2 | **Mô hình chi phí là giả định, không phải đo** | hoa hồng, trượt giá và lãi vay đều là phỏng đoán đúng hình dạng. Con số trượt giá hoà vốn quyết định chuyện đó có quan trọng không, và nó phải đem so với một mẫu khớp lệnh thật, không phải với một hy vọng |
| 3 | **Chưa có ngắt tài khoản** | hai cái ngắt sụt cứng 15% và lỗ ngày 4% được cố ý bỏ ra ngoài để chúng không làm nhiễu phép đo tín hiệu. Chúng phải tồn tại trước khi có bất kỳ lệnh nào được định tuyến |
| 4 | **Khả năng vay để bán khống là giả định** | trên đĩa này không có dữ liệu vay. Mọi lệnh SHORT trong sổ đều giả định vay được |
| 5 | **Backtest không tái tạo được sau lần làm mới cache kế tiếp** | cache cổ phiếu được điều chỉnh ngược tại chỗ và không có ảnh chụp đóng băng (mục 7.3) |
| 6 | **T-2 còn để ngỏ** | nếu tuyến live futures không tôn trọng được `label_lag_days=0` thì cùng câu hỏi ấy áp cho mọi tuyến cổ phiếu dựng trên cùng hệ nhãn |

### 9.3 Tầng kế tiếp, chính xác

**STOCKS-1 — đóng băng nền đo, rồi mới định giá thiên lệch sống sót.** Theo đúng thứ tự này, vì việc thứ hai vô nghĩa nếu chưa có việc thứ nhất:

0. **Chạy Calm A trên cổ phiếu.** Rẻ nhất trong bốn việc — một lần vào lệnh lúc 10:00, không có vòng quét, nên chi phí tính toán chỉ bằng một phần nhỏ tầng này. Nó cho một luật thứ hai, độc lập, trên cùng nền dữ liệu; và vì nó là luật MUA trên phiên hồi phục sau một ngày giảm, nó chịu đúng cùng chiều thiên lệch sống sót, nên phải đọc kèm việc 2 chứ không đọc riêng.
1. **Đóng băng dữ liệu.** Ghi một parquet bất biến cho từng mã chứa đúng các frame 5 phút RTH đã dùng ở đây, kèm sha256 mỗi tệp ghi vào hash cấu hình. Chừng nào chưa có nó, không con số cổ phiếu nào dựng lại được sau một lần làm mới cache, và mọi phép so về sau đều đo trên nền đã trôi.
2. **Chặn thiên lệch sống sót.** Dựng một danh sách thành viên theo ngày — kể cả một danh sách thô từ bảng niêm yết/huỷ niêm yết — rồi chạy lại. Nếu không lấy được rổ theo thời điểm thì nói thẳng ra và vĩnh viễn coi con số đầu bảng là cận trên, chứ không lặng lẽ tiếp tục trích dẫn nó.
3. **Đo một mẫu khớp lệnh thật** đối chiếu với trượt giá hoà vốn ở mục 4.1. Đây là việc rẻ nhất trong ba việc và làm được từ dữ liệu broker mà tuyến futures vốn đã sinh ra.

Rõ ràng **không** phải việc kế tiếp: tinh chỉnh `ema_period`, suy lại ngưỡng biên độ để kết quả đẹp hơn, thêm sleeve Calm hay Stress, hay kéo dài cửa sổ bằng một nhà cung cấp thứ hai. Ba việc đầu là curve fitting trên một nền thiên lệch sống sót; việc thứ tư sẽ lặng lẽ trộn hai định danh dữ liệu vào một chuỗi.

---

## 10. Tệp

**Chỉ đọc. Không sửa mã sản xuất. Mọi thứ dưới đây nằm trong `scratch/`.**

```text
thêm    scratch/stocks_stage0_data_20260826.py          tầng dữ liệu cổ phiếu
thêm    scratch/stocks_stage0_regime_20260826.py        nhãn SPY-HMM, hai bản khớp
thêm    scratch/stocks_stage0_engine_20260826.py        chi phí / định cỡ / sổ / định danh
thêm    scratch/stocks_stage0_run_20260826.py           bộ chạy backtest
thêm    scratch/stocks_stage0_causality_20260826.py     chứng minh không nhìn trước
thêm    scratch/stocks_stage0_sensitivity_20260826.py   ghi sổ lại dòng ứng viên cache
thêm    scratch/stocks_stage0_stability_20260826.py     ổn định tham số / nhãn
thêm    scratch/stocks_stage0_bootstrap_20260826.py     gom cụm theo ngày, null căn giữa
thêm    scratch/stocks_stage0_decompose_20260826.py     tách nhánh: quy kết + phản thực
thêm    scratch/stocks_stage0_probe_20260826.py         dò độ phủ + nhân quả ATR
thêm    scratch/stocks_stage0_report_20260826.py        dựng báo cáo này

dữ liệu scratch/_stocks_stage0_probe.json
dữ liệu scratch/_stocks_stage0_regime_labels.csv
dữ liệu scratch/_stocks_stage0_results.json
dữ liệu scratch/_stocks_stage0_causality.json
dữ liệu scratch/_stocks_stage0_sensitivity.json
dữ liệu scratch/_stocks_stage0_stability.json
dữ liệu scratch/_stocks_stage0_bootstrap.json
dữ liệu scratch/_stocks_stage0_decompose.json
sổ      scratch/_stocks_stage0_ledger_<cấu hình>.csv
dòng    scratch/_stocks_stage0_candidates_<cấu hình>.pkl
```

### Định danh cấu hình của lượt chạy chính

Đây là câu trả lời của tuyến cổ phiếu cho `route_params.params_hash`. Nó cố ý **không** mang `point_value`, `tick` hay `tradable_symbol` — đó là những câu trả lời của futures — và nó **có** mang những thứ quyết định một số cổ phần, đúng chỗ trống mà Stage 5Q-8 đã tìm ra trong hash futures bằng cách đắt tiền.

```text
sha256:8b458dfe9207c8574bd14a68175bbc938945683e47e7a77845e646ba97e6eba8
```

<details><summary>mọi trường đã đi vào hash</summary>

```text
universe_definition                polygon_5min_cache_tickers_history>=250_sessions
universe_size                      75
universe_is_point_in_time          False
data_source_identity               polygon_5min_split_div_adjusted_ETnaive_rth_0930_1555
bar_interval                       5min
adjusted                           True
session                            RTH_0930_1555
timezone                           America/New_York
calendar_source                    SPY_cached_session_files
ema_period                         50
max_hold_days                      5
entry_window                       14:00-15:55
signal_rule                        trend_follow_ema_pullback_volume_resume
stop_basis                         fixed_entry_atr
stop_multiple                      2.0
stop_anchor                        entry
ratchet                            False
arm_hour                           14:05
arm_timezone                       America/New_York
atr_basis                          daily_atr14_rth_shift1_causal
fill_law                           production_gap_after_15min_break
regime_model                       spy_gaussian_hmm_3state
regime_fit_end                     2018-12-31
regime_label_lag_days              1
regime_csv_identity                spy_daily_live.csv
spy_short_filter                   below_sma50
spy_short_lookback                 50
spy_short_lag_days                 1
r4_context_filter                  None
r4_range_threshold                 None
r4_range_derivation_window         None
r4_rel_volume_max                  None
execution_model                    entry_at_resume_bar_close;stop_exit_at_stop;gap_exit_at_open;maxhold_exit_at_0930_bar_open
sizing_basis                       risk_pct_of_initial_plus_realised/|entry-stop|
risk_pct                           0.005
max_position_notional_pct          0.2
max_gross_notional_pct             1.0
max_concurrent_positions           8
commission_per_share               0.005
min_commission_per_order           1.0
slippage_bps_per_side              3.0
stop_exit_extra_bps                5.0
borrow_bps_per_year                50.0
min_price                          5.0
min_adv_usd                        20000000.0
min_history_sessions               250
max_pct_of_adv_shares              0.01
max_pct_of_entry_bar_volume        0.1
initial_capital                    100000.0
window                             2019-01-02..2022-12-30
```

</details>
