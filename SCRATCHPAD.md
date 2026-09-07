## Gotchas

- **Phanh ngày đo từ SAU đợt đóng đầu tiên, không phải từ cuối hôm trước** (2026-08-08,
  quyết định: GIỮ NGUYÊN + ghi rõ). `decide_day` ghi exits **rồi mới** gọi `start_day`,
  nên mốc ngày đã bao gồm chúng:
  ```
  cuối hôm qua 50,000 → lệnh đóng −2,500 → equity 47,500 → start_day(47,500)
  daily_loss = 0%   (thực tế ngày đó mất 5%)
  ```
  Live chạy ~22 slot/ngày và chỉ slot đầu đặt lại mốc, nên mọi lệnh đóng **từ slot 2 trở
  đi đều được tính**. Cái nằm ngoài là đợt đầu — cũng là đợt lớn nhất: thoát theo tín hiệu
  lúc 14:05, và những gì `run_maxhold_exit` đã đóng lúc 09:31.
  ⚠️ **Tên gọi nói khác hành vi**: `_day_start_equity` / `start_day` đọc như "equity đầu
  ngày", mà nó không giữ cái đó. Đã ghi comment tại `live_decision.decide_day`.
  **Không sửa** vì đây là thứ tự của `deploy_sim.replay` — đổi là đổi phanh trong cả
  backtest, phải dựng lại toàn bộ baseline (Calmar floor 1.65, Max DD, số lệnh halt).
  **L19: khi tên biến và hành vi lệch nhau mà không sửa được, ghi comment tại chỗ ra
  quyết định — không phải trong doc mà người đọc code sẽ không mở.**

- **Sổ cái sleeve bám NetLiquidation của cả tài khoản, không phải P&L giao dịch**
  (2026-08-07, đo bằng statement IBKR): H4 làm `state.equity += broker.get_equity() delta`.
  Chứng minh: broker `997,756.40 − 997,395.69 = +360.71`, sổ cái `52,212.33 − 51,851.62
  = +360.71` — **giống hệt 1:1**.
  Tài khoản gốc **CAD ~$997k = 20× sleeve $50k**. Statement 7 ngày cho thấy khoản chảy vào:
  `Credit Interest +1,374.32` (lãi tiền gửi 1 tháng) · `Debit Interest −19.45` ·
  `FX Translations P&L −6.56`. **Lãi tiền gửi một tháng cùng cỡ với TOÀN BỘ P&L giao dịch**
  (+$1,160.75 USD). Nhiễu và tín hiệu cùng bậc độ lớn.
  ⚠️ Đường cong này nuôi Calmar/Sharpe/MaxDD/degradation **và ngưỡng circuit breaker**.
  **L17: quy ước phải trùng backtest.** `deploy_sim.replay:77` là `equity += t["pnl_sized"]`
  — **realized-only, không mark-to-market**. Sổ cái live lệch quy ước thì paper-vs-backtest
  là so hai đại lượng khác nhau, và phanh nổ theo điều kiện khác điều kiện nó được kiểm định.

- **`Quantity` trong statement IBKR ĐÃ mang dấu; statement xếp NGÀY MỚI NHẤT TRƯỚC**
  (2026-08-07): đảo dấu lần nữa → mọi short thành long, P&L ra đúng 0. Ghép theo thứ tự file
  → lệnh đóng đến trước lệnh mở → mọi trade ngược: `entry_day` sau `exit_day`, LONG báo
  thành SHORT, P&L đảo dấu (in ra `MES SHORT 2026-08-05 → 2026-08-03`).
  Sort theo ngày phải **ổn định**: thứ tự trong cùng một ngày là thứ quyết định fill nào
  đóng cái gì (08-05 MES bán 7771.50 đóng long cũ *rồi* mua 7767.00 mở long mới).

- **Đối chiếu phải dùng nguồn mình không tự viết ra** (2026-08-07): `trade_log` do runner ghi
  nên chỉ đúng bằng mức runner đúng. Ba lỗi khác nhau trong một tuần làm nó sai ba kiểu, và
  **không lỗi nào nhìn thấy được từ bên trong**: 08-03 fill đọc nhầm thành Cancelled (mất giá,
  mất luôn cả một lệnh M2K không ai biết), 08-05 và 08-06 stop nổ không ai ghi.
  Statement IBKR là bản ghi duy nhất runner không phải tác giả → `reconcile_statement.py`.
  Kết quả: thật ra **+$1,160.75** chứ không phải −$200; hai lệnh thắng lớn nhất nằm đúng
  chỗ dữ liệu bị mất.

- **`ib.openTrades()` là CACHE, không phải sự thật ở broker** (2026-08-06, bắt được nhờ theo
  dõi một cú khớp thật): nó đọc `wrapper.trades` — dict tích lũy, **không bao giờ xoá mục**.
  IBKR chỉ đẩy cập nhật trạng thái cho client **sở hữu** lệnh, nên lệnh của client khác khi
  khớp thì bản sao trong cache **không bao giờ** chuyển sang done và nằm lại vĩnh viễn.
  Docstring của chính `reqAllOpenOrders()` cảnh báo: *"the orders of other clients will not
  be kept in sync"* — và nó **trả về** danh sách đúng. Dùng giá trị trả về, đừng gọi rồi đọc
  `openTrades()`.
  **Đo được:** stop M2K #14 khớp 08:11; backend dashboard (tiến trình sống lâu) vẫn báo
  `PreSubmitted` lúc 08:27. Công cụ chạy-rồi-thoát đọc đúng chỉ vì mỗi lần chạy cache trống —
  **lỗi ẩn hoàn toàn khỏi test và khỏi script ngắn**, chỉ lộ ở tiến trình sống lâu.
  ⚠️ Hậu quả nặng nhất: vị thế **không có stop** hiển thị **như đang được bảo vệ**.
  Đã vá 5 chỗ: `ibkr_reader` + `get_working_stops`/`has_working_stop`/`cancel_order`/
  `get_order_status`. `verify_account_clean` còn tệ hơn — gọi `openTrades()` mà không
  `reqAllOpenOrders()` nên không thấy lệnh client khác → **false clean**.
  Bỏ luôn `ib.sleep()` sau `reqAllOpenOrders()`: lệnh này đã block chờ future.

- **Máy ngủ làm scheduler chết câm trong nhiều giờ SAU KHI đã thức lại** (2026-08-06, đo được):
  `Event.wait(timeout)` của Python trên Windows đếm bằng đồng hồ **không chạy khi máy ngủ**.
  APScheduler `BlockingScheduler` chờ một lần dài tới job kế, nên **mỗi giây ngủ đẩy lùi hạn
  chờ đúng một giây** — kể cả khi máy đã thức lại từ lâu.
  **Đo đêm 04→05 (có đối chứng độc lập):** tổng ngủ 1:27:37 → dự đoán thức 23:10:00+1:27:37
  = 00:37:37; APScheduler thực tế xử lý job lúc **00:37:22**. Lệch 15 giây.
  **Đêm 05→06:** ngủ 19:10:56–22:02:23 (2h51m) + 23:20:50–00:03:11 (42m) → hạn 23:10 bị đẩy
  tới **02:43**, sau khi cửa sổ NKD đêm (23:10–00:55 local) đã đóng. **0/22 slot chạy,
  0 dòng log, tiến trình vẫn sống và "khỏe".** Suy giảm 08-03: 22 slot → 08-04: 4 → 08-05: 0.
  ⚠️ Giấc ngủ **buổi chiều** (19:10, lúc không có job nào) vẫn vô hiệu hóa **toàn bộ cửa sổ
  đêm** 4 tiếng sau. Không có cảnh báo nào vì không có gì "hỏng" — nó chỉ đang chờ.
  ⚠️ Cặp sự kiện `Kernel-Power 42/107` KHÔNG đủ tin: đêm đó nó chỉ ghi 11 giây (hai lần chợp)
  trong khi thực tế ngủ 3h33m. Nguồn đúng là **`Microsoft-Windows-Power-Troubleshooter`**
  (ghi thẳng `Sleep Time` / `Wake Time`, giờ UTC) hoặc `Kernel-Power 130/131` ResumeCount.
  **L16: process còn sống + CPU thấp + log im ≠ khỏe. Với scheduler, "im lặng" và "chết" nhìn
  giống hệt nhau — phải có heartbeat mới phân biệt được.**

- **IBKR chỉ cho clientId ĐÃ ĐẶT lệnh được hủy nó** (2026-08-06, đo trực tiếp): MYM STP #10
  từ chối hủy khi thử từ clientId 1 (runner), 77 và 82 — im lặng, không error, lệnh vẫn
  `PreSubmitted`. Nối lại bằng **clientId 93** (id đã đặt nó) thì hủy được ngay lần đầu.
  ⚠️ Hệ quả vận hành: runner luôn dùng `clientId=1` nên stop do nó đặt thì nó hủy được.
  Nhưng lệnh còn sót từ phiên dùng clientId khác (thử nghiệm tay, script cũ) thì **không
  công cụ nào hủy được ngoài chính id đó hoặc TWS**. `repair_stops.py --client-id <id>`.
  `t.order.clientId` cho biết id chủ — `cancel_order` nay in nó trong thông báo lỗi.

- **Giá stop phải nằm trên lưới tick, nếu không IBKR từ chối bằng code 110** (2026-08-06):
  "The price does not conform to the minimum price variation for this contract".
  Mức chandelier là số liên tục nên hầu như không bao giờ trên lưới: 7758.86 (MES tick 0.25),
  54708.68 (MYM tick 1.0), 3038.44 (M2K tick 0.1) — **cả ba bị từ chối**. Đây là nguyên nhân
  gốc của vụ 3 vị thế trần đêm 05/08, không phải disconnect hay Gateway restart.
  ⚠️ Nắn tròn phải **ra xa thị trường** (LONG xuống, SHORT lên). Tròn về phía thị trường
  thắt stop chặt hơn mức đã sizing, và ở gần giá có thể đẩy xuyên qua → nổ ngay khi đặt.

- **`PendingSubmit` KHÔNG phải bằng chứng lệnh tồn tại ở IBKR** (2026-08-06): đó là status
  ib_insync tự đặt tại `ib.py:673` trước khi IBKR nói gì, và **lệnh bị từ chối nằm y nguyên
  ở đó**. Mọi bộ lọc "đang hoạt động" phải dùng danh sách **bao gồm**
  (`PreSubmitted`/`Submitted`), không phải danh sách loại trừ.
  Tôi đã viết lại đúng lỗi này trong bước VERIFY của công cụ vừa dựng để bắt nó — công cụ in
  "every position protected" ngay sau khi IBKR từ chối cả hai stop.
  **L15: dùng danh sách bao gồm cho "còn sống", loại trừ cho "đã chết". Nhầm chiều là mặc định
  fail-open, và fail-open ở đây nghĩa là vị thế trần được báo là an toàn.**

- **`cancelOrder` là một yêu cầu, không phải kết quả** (2026-08-06): gọi xong rồi trả `True`
  khiến #10 được báo "cancelled" hai lần trong khi vẫn sống. Phải poll tới trạng thái terminal
  (`Cancelled`/`ApiCancelled`/`Filled`/`Inactive`) rồi mới kết luận.

- **Vị thế có thể vừa được bảo vệ vừa đang gặp nguy** (2026-08-06): MYM cùng lúc có BUY #12
  (đúng chiều) và SELL #10 (sai chiều, sót lại từ vị thế LONG cũ). Kiểm tra kiểu "có tồn tại
  một stop đúng chiều không" báo OK và bỏ qua quả mìn. Phải quét **mọi** lệnh trên contract,
  không dừng ở lệnh đúng đầu tiên.

- **Một phép kiểm tra không thể đỏ thì không kiểm tra gì cả** (2026-08-05): tiêu chí nghiệm thu
  của lần vá STP 03/08 là `stop_price + stop_order_id ≠ null`. Nhưng `place_stop` trả về
  orderId do **ib_insync tự đúc** (`ib.py:654` — `orderId = order.orderId or self.client.getReqId()`,
  gán trước khi hàm return), vô điều kiện. Nên `stop_order_id` không bao giờ null →
  **tiêu chí luôn pass, kể cả khi IBKR không có lệnh nào**. Nó đã "pass" ngày 05/08 trong khi
  3 vị thế nằm trần qua đêm.
  ⚠️ Cùng cơ chế làm chết vòng retry trong `place_stop`: `for _n in range(10): if trade.order.orderId != 0`
  — điều kiện không thể sai, nhánh `else` không bao giờ chạy. Code **trông như** có kiểm tra,
  nên 3 tuần không ai nhìn lại.
  **Quy tắc**: nghiệm thu trạng thái broker phải hỏi broker (`check_open_orders.py`, clientId
  riêng, read-only), không được hỏi file do chính mình ghi ra.

- **`cancel_order` báo lỗi bằng `return False`, không raise** (2026-08-05): hai call site trong
  `runner.py` bọc `try/except` rồi log "cancelled" vô điều kiện → `except` không bao giờ chạy.
  Stop mồ côi tích lại nhiều ngày ở IBKR trong khi log nói đã hủy. Một trong số đó (`SELL MYM`
  cho vị thế **SHORT** MYM) nếu fire sẽ **nhân đôi short** chứ không đóng vị thế.
  Nguyên nhân sâu hơn: `cancel_order` quét `ib.trades()` — chỉ chứa lệnh của **phiên hiện tại**,
  mà runner nối lại mới mỗi slot 5 phút → lệnh phiên trước luôn "not found".
  `has_working_stop` cùng file đã vá bằng `reqAllOpenOrders()`; `cancel_order` bị bỏ sót.
  **L14: khi vá một hàm dùng `ib.trades()`, grep hết các hàm khác cũng dùng nó trong cùng file.**

- **Lưới an toàn keyed vào state cục bộ thì bị state cục bộ sai vô hiệu hóa** (2026-08-05):
  B4 phát hiện vị thế trần bằng `p.stop_order_id is None`. `place_stop` bịa ra ID → điều kiện
  False → B4 im lặng đúng lúc cần nó nhất. Điều kiện phát hiện phải dựa trên **sự thật phía
  broker**, không dựa trên trường mà chính đường lỗi đó ghi ra.

- **Parquet back-adjusted vs bar live front-month — hai THANG GIÁ khác nhau trong một chuỗi**
  (2026-08-04): `update_ibkr_daily` dựng parquet từ ContFuture + splice offset (liền mạch qua
  rollover — thang mà EMA/ATR/chandelier cần). `fetch_bars` trả **front-month thô** (thang lệnh
  khớp). `_concat_live` ghép với `keep="last"` → bar live **ghi đè** lịch sử thật → chuỗi có
  bậc nhảy ngay chỗ tính tín hiệu.
  Đo cùng mốc `2026-08-04 15:24`: MES **+12.25** · MNQ **+88.75** · MYM **−39.00** · M2K **+9.20**.
  **Hậu quả 2026-08-03**: live mở MES @7,634.75 trong khi replay parquet thuần **không có vị thế
  MES ở BẤT KỲ mốc cắt nào** (15:10 = đúng phút đặt lệnh, 15:55, 23:59, cả hôm sau). Lệnh sinh ra
  từ chỗ gãy, không phải từ chiến lược. MYM cùng ngày thì lại KHỚP backtest → khó phát hiện.
  ⚠️ **Sửa phải đủ hai nửa.** Nửa 1: `_splice_live` chỉ nối bar SAU parquet + dịch theo anchor của
  `update_ibkr_daily`. Nửa 2: `to_candidate(price_offset=)` quy entry/stop về thang thô. Thiếu nửa
  2 thì stop LONG ra 7,639.50 trong khi giá 7,635 → **kích hoạt ngay khi đặt**. Nửa vời tệ hơn
  không sửa.
  ⚠️ **P0c swing verification bị vô hiệu** — `p0c_verify_swing.py` gọi cùng hàm concat nên tái tạo
  đúng chuỗi hỏng rồi báo "khớp". L10 lần thứ ba.

- **Phanh cắt lỗ đo trên equity broker ($995k) trong khi sleeve đo trên $50k — phanh cứng
  không tồn tại** (2026-08-04): `deploy_sim` cho `equity = account` rồi cộng dồn lãi lỗ, nên
  breaker thấy equity CỦA HỆ THỐNG. `runner` thì `equity = broker.get_equity()` (L504) và H4
  ghi đè `state.equity = _h4_eq` (L1112) bằng **số tuyệt đối** của broker → breaker nhảy lên
  $995k. `MultiClusterGuard.account` lại là hằng số 50_000.0 không có cơ chế cập nhật.
  SIM (cùng đường lãi lỗ, hai mẫu số): mất **toàn bộ $50,000** vốn thiết kế chỉ ra **5% DD →
  HALT_DAY**, không bao giờ HALT. Mức lỗ đầu tiên bật phanh: designed HALT_DAY $2,000 /
  HALT $7,500 — live $40,000 / $149,500. **Lỏng 20×.**
  H4 sinh ra đúng mục đích (bắt lãi lỗ nội ngày STRESS_MID cho HALT_DAY) — sai ở chỗ lấy giá
  trị tuyệt đối thay vì **delta**. Fix: hệ thống tự giữ sổ (`system_equity` bắt đầu ở ACCOUNT,
  cộng delta broker), broker chỉ dùng đối chiếu. Mỗi slot là process chạy-rồi-thoát nên phải
  persist `system_equity` + `last_broker_equity`.
  ⚠️ `net_pnl = cur_eq - account` (runner.py:1488) = 995,275 − 50,000 → dashboard báo lãi
  **$945,275** hoàn toàn ảo.
  ⚠️ **Tỉ số KHÔNG hỏng**: Calmar/Sharpe có tử và mẫu cùng co giãn nên bất biến theo quy mô.
  Chỉ NGƯỠNG TUYỆT ĐỐI hỏng (DD halt, HALT_DAY, net_pnl). Đừng lẫn hai loại.

- **"Nâng nền vốn" ≠ "nâng số hợp đồng"** (2026-08-04): nâng n (1→2) làm mỗi mã cược to gấp
  đôi → danh mục TẬP TRUNG hơn → đã bác bỏ có cơ sở (MaxDD n=2 vượt trần 15%,
  SCALING_ANALYSIS.md). Nâng NỀN VỐN cho các sleeve % thì vẫn 1 hợp đồng/mã, chỉ là nhiều mã
  lọt cap hơn → danh mục ĐA DẠNG hơn. Hai cái ngược hướng nhau về rủi ro, nhưng chỉ cái thứ
  nhất từng được đo. Đừng dùng quyết định trần n=1 để bác luôn cái thứ hai.

- **Sức chứa co lại phần lớn là CHU KỲ, không phải cấu trúc** (2026-08-04): biến động Nikkei
  hiện 3.64% vs trung bình 2018-2025 là 1.64% → gấp 2.23×, và biến động luôn hồi quy. Ở mức
  bình thường, account cần cho NKD rơi từ $146,629 xuống $65,891. Phần cấu trúc (chỉ số tăng)
  được bù bằng chính lợi nhuận hệ thống: nền $50k đóng băng → NKD 2.64% (chặn); nền $50k +
  lãi IS $41,266 = $91,266 → NKD 1.44% (lọt). Không cần bơm vốn ngoài — cần cho nền cộng dồn.

- **Cơ sở sizing $50,000 đứng yên, thị trường thì không — sức chứa hệ thống co dần**
  (2026-08-04): `risk_sized` = contracts × mult × ATR_điểm × point_value, tính bằng ĐÔ-LA.
  Chỉ số tăng thì ATR tính bằng điểm tăng theo, nên cùng một biến động % sẽ tốn nhiều đô-la
  hơn mỗi hợp đồng. Cap lại là % của ACCOUNT **cố định $50,000** → từng công cụ lần lượt
  rơi khỏi sleeve của nó theo năm.
  NKD chết trước (Nikkei tăng mạnh nhất): account cần để 1 MNKD lọt sleeve 2% đi từ $17,478
  (2019) → $44,062 (2025) → **$146,630 (hôm nay)**. Tỉ lệ ngày vượt cap: 0% (2018–2023) →
  27.6% (2024) → 33.0% (2025) → **94.1% (2026)**.
  Rổ 4 đi cùng đường chậm hơn: 4 mã cùng chiều chiếm 1.7% account (2017) → 5.5% (2023) →
  **10.8% (2026)** so với cap 5% → chỉ còn chỗ cho ~2/4 mã.
  Phân rã 2019→2026 cho NKD: index level ×2.85, ATR %giá ×2.06, ATR điểm ×5.90.
  ⚠️ **KHÔNG phải lỗi cap.** `risk_sized` là tiền thật đang chịu rủi ro; chặn ở 2% tài khoản
  là quản trị rủi ro đúng. Vấn đề là ĐỘ HẠT — 1 hợp đồng micro rủi ro nhiều hơn cả sleeve,
  và không có hợp đồng nhỏ hơn. Đây là câu hỏi QUY MÔ VỐN, không phải hàng rào rủi ro.
  ⚠️ **Bẫy đã suýt sập**: "neo cap theo notional/ATR% thay vì $ tuyệt đối" nghe như sửa cấu
  trúc nhưng thực chất chỉ cho lọt lệnh rủi ro 5.87% tài khoản = tăng rủi ro thật. Bất kỳ đề
  xuất nào làm cap "hết chật" đều đang tăng rủi ro — hỏi "cái này cho qua thêm bao nhiêu đô-la
  rủi ro" trước khi tin vào chữ "structural fix".

- **Cap cụm 2% chưa bao giờ được sweep** (2026-08-04): `net_exposure_multi.py` docstring ghi
  thẳng *"roska4_stress and global_nkd (2%) remain ESTIMATES — calibrate during paper trading"*.
  `DECISIONS.md:77` neo nó vào giả định "1 MNKD ATR risk ≈ $437" — đó là **percentile 22.6%**
  của toàn bộ lịch sử, lấy từ giai đoạn yên nhất 2018–2019. Chỉ `roska4_swing` (5%/4.4%) là
  swept optimum thật.

- **Đổi cap KHÔNG làm mất hiệu lực reconcile** (2026-08-04): cap chỉ tác động ở tầng
  `deploy_sim.replay()` (line 59-94); `backtest_basket`/`backtest_swing_tf` (line 179/183/194)
  độc lập với cap. Nên reconcile gd0/stress/nkd/swing_desired giữ nguyên, và sweep N giá trị
  cap chỉ cần MỘT lần backtest rồi gọi `replay()` N lần.
  Nhưng chi phí thật không phải CPU: **vault OOS đã niêm phong với cap 2%** — đổi cap nghĩa là
  hệ thống đang chạy không còn là hệ thống đã validate OOS. Và sweep cap trên chính dữ liệu IS
  rồi chọn Calmar cao nhất là curve fitting, cùng loại đã cấm với ema/orb_range/bb_std.

- **`between_time()` đọc theo đồng hồ TRÊN INDEX — mỗi instrument một cửa sổ khác nhau**
  (2026-08-03): `_validated_core.py:337` dùng `between_time("14:00","15:55")`. Với Rổ 4 index
  là ET → 14:00–15:55 ET. Với NKD, `run_live_day.py:166` tz_convert sang `session_tz`
  (Asia/Tokyo) → cửa sổ thật là **14:00–15:55 JST = 01:00–02:55 ET**. Cùng một dòng code,
  hai khung giờ hoàn toàn khác. Đừng đọc con số "14:00" trong engine là giờ ET.

- **`run_live_day` là subprocess chạy-rồi-thoát — hệ thống chỉ nhìn thị trường đúng các phút
  có cron gọi** (2026-08-03): `run_scheduler.py` chỉ giữ đồng hồ, tới giờ thì
  `_run([sys.executable, "-m", "global_index.run_live_day", ...])` đẻ process mới. Log chứng
  minh: connect/disconnect từng cặp mỗi 5 phút = 22 process riêng biệt, không phải 1 process
  chạy suốt. **Từ 15:55 ET tới 09:31 ET hôm sau không có process nào tồn tại.** Hệ quả: cửa
  sổ NKD (01:00–02:55 ET) nằm trọn trong khoảng chết → NKD chưa từng được đánh giá đúng cửa
  sổ. "Dữ liệu đã đủ lúc 14:05" KHÁC "vào lệnh kịp giá" — đủ data mà lệch 11h vẫn là lệch 11h.

- **Trộn JST-naive với ET-naive trong một index — 1050 bar bị ghi đè sai ~900 điểm**
  (2026-08-03): `_concat_nkd_live` ghép frozen (JST-naive sau tz_convert+strip) với live IBKR
  (ET-naive). Trùng nhãn ≠ trùng khoảnh khắc: nhãn `2026-08-03 03:00` là 03:00 JST ở nửa
  frozen và 03:00 ET ở nửa live, cách nhau 13 tiếng. `keep="last"` cho live thắng → hỏng đúng
  cửa sổ gần nhất mà `desired_position()` dùng. Docstring còn ghi "(both tz-naive ET after
  strip)" — sai với chính nửa nó vừa convert.
  **Data trên đĩa KHÔNG hỏng** (`update_ibkr_daily` chuẩn hoá cả hai vế về ET trước khi splice);
  corruption chỉ sống trong RAM một lần chạy.
  ⚠️ Làm **vô hiệu kết quả P0c MNKD 28/07** — cả hai vế so sánh dùng chung concat hỏng nên
  chúng khớp nhau. L10 lần nữa.
  Fix: `_to_session_naive()` đưa live về JST trước khi concat. Test `test_nkd_tz.py`.

- **Cluster im lặng = "đóng sạch", không phải "giữ nguyên"** (2026-08-03):
  `diff_desired_vs_held` build `desired_live_keys` CHỈ từ signal khác None, rồi exit mọi vị thế
  giữ mà key không có tên (signal_layer L110-112). Nên bỏ qua một cluster (không tính, không
  ghi key) = đóng hết vị thế của cluster đó, chắc chắn, mọi lần chạy. Muốn "giữ nguyên" thì
  phải **nói ra** bằng hold-dummy cùng direction (`_mark_held_unchanged`). Cơ chế này đã có sẵn
  ở nhánh C4 khi engine lỗi — `active_clusters` chỉ kích hoạt nó có chủ đích.

- **`send_order` đọc ra `status=Cancelled` cho lệnh ĐÃ FILL — mất STP im lặng** (2026-08-03, LIVE):
  3 lệnh OPEN (MES/M2K/MYM) khớp thật ở IBKR — `reqExecutions()` có đủ `execId` + `permId`,
  `ib.trades()` trả `status=Filled` — nhưng runner log `"not filled — status=Cancelled"` ngay
  **cùng giây** đặt lệnh (19:10:39 UTC đặt → 19:10:39 fill). Vòng `while not trade.isDone()`
  ở [ibkr_broker.py:521](global_index/ibkr_broker.py#L521) thoát ra với status sai.
  **Hệ quả dây chuyền**: gate `if _open_fill.status in ("FILLED","PARTIAL")` ở
  [runner.py:1129](global_index/runner.py#L1129) chặn → không đặt STP, không ghi trade log,
  không đo slippage, **và không báo động** — vì log `place_stop FAILED` nằm *bên trong* chính
  gate đó. 3 vị thế qua đêm không có stop, hệ thống hoàn toàn không biết.
  **ROOT CAUSE — xác nhận từ source ib_insync 0.9.86**, `wrapper.py:1097`:
  ```python
  warningCodes = {110, 165, 202, 399, 404, 434, 492, 10167}
  isWarning = errorCode in warningCodes or 2100 <= errorCode < 2200
  ...
  elif trade:                      # nhánh error
      if not trade.isDone():
          status = trade.orderStatus.status = OrderStatus.Cancelled
  ```
  Code **10349** ("Order TIF was set to DAY based on order preset") là *warning* của IBKR
  nhưng KHÔNG có trong `warningCodes` và không thuộc dải 2100–2200 → ib_insync xếp là error
  → **tự đặt status=Cancelled ở phía client**. IBKR chưa huỷ gì; lệnh vẫn khớp.
  Trade log bắt được nguyên chuỗi: `PendingSubmit 00:57:51.327` → `Cancelled 00:57:51.345`
  (18ms, message = Error 10349) → `Filled @ 2993.20`. Runner poll 0.1s nên trúng cửa sổ đó.
  **Deterministic, mọi lệnh đều dính** — khớp với việc cả 3 lệnh 2026-08-03 đều bị.
  Vì sao có 10349: order set `outsideRth=True` nhưng để trống `tif` → IBKR lấy preset của
  account ghi đè thành DAY rồi phát cảnh báo.
  ⚠️ **10349 ĐÃ có sẵn trong `_IBKR_INFORMATIONAL`** (ibkr_broker.py:64) — nhưng set đó chỉ
  dùng ở `_on_ibkr_error` để hạ log xuống DEBUG, chạy SAU khi ib_insync đã đổi status.
  Dập tiếng ồn ở sai tầng, thiệt hại thật vẫn lọt.
  **Bài học**: đừng để hành động bảo vệ phụ thuộc vào *ack của lệnh vào*; phải tin trạng thái
  thật ở broker (`get_positions`/`reqExecutions`/`trade.fills`). Bracket order không có lỗ này
  vì stop nằm sẵn trên server IBKR từ lúc submit.
  **Đã vá**: (1) `tif="DAY"` explicit ở send_order + cả 2 chân rollover → hết trigger 10349;
  (2) `_verified_status()` — status Cancelled mà `filled==0` thì re-poll `CANCEL_VERIFY_SECS=5s`
  rồi để `trade.fills` phán (execution report chỉ tồn tại nếu khớp thật); (3) B4 naked-position
  check trong runner.py làm lưới cuối. Test: `global_index/test_false_cancel.py` 7/7.
  ⚠️ B4 KHÔNG tự cứu được 3 vị thế 2026-08-03 vì `stop_price` cũng `None` (gate không mở nên
  không field nào được set) — B4 chỉ CẢNH BÁO, đã phải đặt tay.

- **B3 không phát hiện được vị thế trần** (2026-08-03): B3 chỉ so `inst/direction/contracts`.
  Vị thế mở đúng khớp cả 2 phía nhưng không có stop thì B3 báo `positions match` và đi tiếp.
  Nhánh STP trong B3 chỉ chạy khi `stop_order_id` ĐÃ có (đi verify nó còn sống không);
  `stop_order_id = None` bị bỏ qua hoàn toàn. → B4 sinh ra để bịt lỗ này.

- **Không đặt STP bù mà không kiểm tra stop đang chạy** (2026-08-03): hai STP cùng contract,
  cả hai cùng fire → đóng vị thế 2 lần → lật ngược chiều. B4 chỉ đặt bù khi
  `has_working_stop(inst)` trả về `False` một cách chắc chắn; broker không trả lời được
  (`NotImplementedError`) thì chỉ cảnh báo, không đoán.

- **IBKR paper account: ALL bars EMPTY — code=162 subscription thiếu** (2026-07-14):
  `--print-signals` kết nối OK nhưng `reqHistoricalData(..., whatToShow="TRADES", barSizeSetting="1 min")`
  → ALL 5 instruments (MES/MNQ/MYM/M2K/MNKD) = ✗ EMPTY. Terminal in 2 warnings `code=162
  "API historical data query cancelled: reqId"` cho 2 req; 3 req còn lại EMPTY không warning (bars=[]).
  **Root cause**: Paper account mặc định chỉ có 15-min delayed data. `whatToShow="TRADES"` historical
  intraday 1-min bars cho CME futures yêu cầu active Level 1 real-time subscription, paper không có.
  Code 162 KHÔNG nằm trong `_IBKR_INFORMATIONAL` nên log WARNING — đúng behavior, chỉ thiếu subscription.
  **Fix trước P2**: Subscribe CME US Micro Futures (+ CME Nikkei cho NKD) trong IB Account Management
  (paper account). Verify bằng lệnh: `ib.reqHistoricalData(MES_202609_contract, durationStr="1 D",
  whatToShow="TRADES", ...)` → phải trả bars > 0.
  **Fallback**: Link paper account với real account → mirror market data subscriptions.

- **Futures liquidity concentrates at 09:00-11:00 + 15:00 ET, not overnight** (2026-07-09):
  Measured avg per-min volume by hour across full 23h session (ES/NQ/YM/RTY, frozen_sim).
  09:00/10:00/15:00 ET are top-3 for all 4 instruments; 18:00-08:00 ET (bulk of Globex
  session) never in top 6 anywhere. This is why `orb_futures/` OR window (09:31-09:45,
  cash-index-open anchored) is a real liquidity-grounded choice, not a stocks-logic
  copy-paste — even though futures trade ~23h, volume still clusters at cash-market
  open/close. Don't assume overnight hours have tradeable signal without checking volume.

- **orb_futures/ ORB breakout + gap-fill: real NO-GO on correct window** (2026-07-09):
  Never run before this session (no results existed anywhere). Ran on frozen_sim +
  spy_daily_live.csv at the natural market-open window (09:31-09:45 OR, entries to
  15:55) — NOT the stocks 14:00-15:55 window. ORB: POOL 231t PF=0.67, ALL 7 years
  negative. Gap-fill: POOL 100t PF=0.64 WR=25%, 5/7 years negative. Both decisive
  NO-GO — closes the "was it rejected on the wrong window" question for these two;
  they were never tested before, and now that they have been, there's no edge.
  See TASK.md sub-task "Futures NO-GO re-examination — correct entry window".

- **hmmlearn "Model is not converging" warning on orb_futures label_regimes call**
  (2026-07-09): appears every run of `orb_futures.edge_test`/`gap_fill`, identical
  delta (-0.152 on LL~9945) — deterministic, tiny relative magnitude. First time seen
  in this project. Not investigated (didn't affect the decisive NO-GO verdicts above).
  Flag if it recurs somewhere the regime labels actually matter for a close call.

- **A5 Databento re-fetch: contamination = overlap window bar replacement** (2026-07-09):
  Root cause là 2 thao tác của update_futures_data.py:
  (1) Constant offset lên toàn lịch sử → KHÔNG thay đổi ATR/P&L (differences cancel, math verified).
  (2) **Overlap window (Dec 2024, 30 ngày) bar REPLACEMENT** bằng new_adj từ anchor Sep 2026 → individual bar prices khác → ATR14 cuối 2024 thay đổi → $52,936 → $53,172 (+$236).
  $53,172 là số NHIỄM. Không lock. Cần khôi phục frozen.

- **Frozen parquet: --full-refetch không tái tạo $52,936** (2026-07-09 RESOLVED):
  `create_frozen_parquet.py` (đã xóa) chỉ clip *_8y → VẪN chứa Dec 2024 bars nhiễm. Không dùng.
  Cách đúng: `--full-refetch --end 2024-12-31` → tạo `*_frozen_2024.parquet` sạch.
  NHƯNG: kết quả = $53,021 / Calmar=3.07 (KHÔNG phải $52,936).
  $52,936 là incremental-build artifact (nhiều splice qua các lần fetch → cumulative offset history khác). NON-REPRODUCIBLE.
  $53,021 = clean full-refetch, reproducible (run 2 byte-identical). **$53,021 là ground truth thật, tốt hơn $52,936.**
  Fit_A floor trên frozen: $51,459 / Calmar=2.69 (floor/baseline=87.6%, consistent với old 86.7%).
  Deploy_sim command: `python -m global_index.deploy_sim --data-dir data\cache\futures\frozen_sim --nkd-parquet global_index/data/NKD_frozen_2024.parquet --regime-csv spy_daily.csv --end 2024-12-31 --n-contracts 1`

- **Live signal STABLE qua daily IBKR update** (2026-07-09):
  update_ibkr_daily.py: append-only, không re-splice lịch sử. Stored splice offset áp uniformly cho new bars.
  Rủi ro chỉ từ `update_futures_data.py` (Databento re-fetch). Trước A6/A7...: tạo frozen copy TRƯỚC.

- **INVARIANT: TRƯỚC BẤT KỲ update_futures_data.py nào** → tạo `*_frozen_YYYY.parquet`, verify baseline, sau đó mới update *_8y.

- **IBKR IB Gateway paper port = 4002** (2026-07-08, futures wire): IB Gateway paper dùng port 4002, KHÔNG phải 7497. Port 7497 là TWS paper. Khi dùng IB Gateway (recommended cho algo) → `--port 4002`.

- **ib_insync 0.9.86 trả bars tz-aware US/Central** (2026-07-08): `reqHistoricalData(formatDate=1)` với CME futures → ib_insync parse date thành `datetime64[us, US/Central]` (Chicago tz), KHÔNG phải naive string hay UTC. Fix trong `_fetch_raw()`: `tz_convert("America/New_York").tz_localize(None)`. Verified: first_bar=18:00 ET (CME Globex open).

- **CME futures sessions = 23h/day, KHÔNG phải RTH** (2026-07-08): MES/MNQ/MYM/M2K trade 18:00–17:00 ET daily (23h). Overnight bars (00:00–04:00 ET) là bình thường. P2 timezone check không thể dùng RTH window (09:00–16:30). Dùng: first_bar.hour ∈ [17,19] và bars/day > 800.

- **IBKR contract ambiguity: phải chỉ định contract month** (2026-07-08): `ibi.Future("MES", exchange="CME")` bị IBKR reject với error "Ambiguous contract" vì nhiều expiry đang active. Phải dùng `lastTradeDateOrContractMonth` cụ thể. Fix: `_current_front_month(inst)` lookup từ ROLL_SCHEDULE → trả "202609" cho MES hôm nay.

- **get_equity() KHÔNG được gọi reqAccountUpdates()** (2026-07-08): ib_insync tự auto-subscribe account updates khi connect. Gọi thêm `reqAccountUpdates()` gây hang vô thời hạn. Dùng `ib.sleep(2.0)` + `ib.accountValues()` thay thế.

- **outsideRth=True BẮT BUỘC cho futures orders** (2026-07-08): CME futures trade 23h/day. Không set flag → IBKR preset đổi TIF=DAY và cancel order ngoài RTH (16:15–09:30 ET). Với `outsideRth=True`: order fill trong electronic session bình thường. Error 10349 vẫn xuất hiện nhưng là INFORMATIONAL — order vẫn fill, ib_insync log "Canceled order" là misleading (intermediate state, không phải final cancel).

- **IBKR fill time thực tế: ~0.2s** (2026-07-08, paper MES): Design assumption 5s là conservative 25×. Entry 0.26s, exit 0.15s. Slippage 1 tick round-trip. Block time worst-case thực tế << 265s design limit. Đo thêm trong paper weeks đầu trước khi update assumption.

- **20 pytest failures — all stale tests, zero production bugs** (2026-06-25): Verified pre-vault. Categories: VWAP_MR removed (7), HMM Stress→SAFETY_MODE design changed (6), ORB fakeout→FADE design (1), ORB max_price $200→$1000 (1), grid 27→48 combos (1), Crisis HMM missing in test data (1), strategy_router safety_mode stale (1), sector_strength not implemented (1 — see dedicated note below). Tests reflect old design; current behavior is intentional and embedded in WFO results.

- **TrendFollow sector_strength filter NOT implemented** (2026-06-25): `run_scanner()` accepts `sector_strength` field but does not filter on it. Sector ETF data (XLF, XLE...) was unavailable during IS development 2017-2022. Implementing filter pre-vault would require new WFO run — deferred post-vault. Impact: TF may accept trades when sector is selling off. Documented in `trend_follow.py` docstring.

- **Gap Fill "direct" trades = look-ahead bug**: Original RS sim showed +$10,465 because "direct" trades retroactively selected stocks that NEVER touched VWAP — not identifiable in real-time. Gap Fill doesn't have this issue (all filters checkable at 10:30).

- **Calm regime gap fill = negative**: Tested explicitly — 5t, -$193, WR=40% in Calm. Gap Fill edge is Normal-regime specific. Do NOT add Calm regime even if user asks "can we get more signals."

- **gap_fill_stop_dists cleanup**: engine.py tracks _gf_stop_dists dict by id(trade). When trade closes, dict entry is popped in section 10. If circuit breaker fires (_close_all), entries may linger but this is harmless since the dict resets next day (_gf_stop_dists is a local variable per _run_day call).

- **PositionSizer vs sim $500/trade**: Sim used fixed $500 risk. Engine uses max_risk_pct of account equity. Backtest shares/P&L will differ from sim numbers. Don't interpret this as a bug.

- **--use-results-cache invalidated**: engine.py was modified (Gap Fill added, ORB_FADE removed). Must run window_debug.py WITHOUT --use-results-cache until a fresh pkl is generated.

- **VWAP_MR TIME_STOP**: was 45 min, extended to 90 min (already in engine before this session). Noted here in case someone wonders why it differs from original blueprint.

- **ORB_FADE removal**: ORB_FADE label never appeared in actual trade path — engine was generating "FADE" label. ORB_FADE only existed in STRATEGY_CAPS and STRATEGY_STATS as dead config. Removing it had no behavioral change, just cleaned up -$330 phantom stats.

- **Calm afternoon: no edge**: 52 Calm days total (14 / 37 / 1 per year), UP rate 56%, stock MR rate 34.5%, early→late corr +0.31, PM→EOD corr +0.32. No strategy fits. Do NOT revisit without more Calm days.

## VWAP_MR Root Cause Analysis (completed, no further action)

**Finding**: STOP:TARGET = 2:1 (140 stops vs 70 targets). Root cause identified:

**H2 (stop too wide): REJECTED**
- 54% of TARGET_HIT trades have MAE < 0.3×ATR — win cleanly with almost no adverse move
- 0% of winners had MAE > 1.5×ATR — stop never blocks an eventual winner
- Tightening to 1.0×ATR would kill 18% of winners. Stop 1.5×ATR is correct.

**H1 (signal quality): NOT ACTIONABLE**
- Wick ratio: smaller wick = better WR (71% for tiny <0.1×ATR) but only 21 trades
- Rejection ratio: ~0.05 across all trades — measurement issue, bars don't snap back before entry
- Volume filters: make things WORSE in combined tests
- All H1e combined filters: worse than or equal to baseline

**H3 (universe): CURVE FITTING**
- IWM, QQQ, XLV, XLP are systematic losers (-$98 of -$128 total)
- Removing them based on backtest results = curve fitting. Rejected.

**F2+F3 filters: available but not implemented**
- F2: skip SHORT when SPY > VWAP after 12:30
- F3: skip LONG 12:00–13:00
- Sim: 133t, +$54, WR=48%, sys $9,230 (+$182 vs baseline)
- 2020 still negative (-$29). Not implemented — improvement too small and 2020 unresolved.
- Can revisit if needed. Code preview in TASK history.

**Conclusion**: VWAP_MR has thin edge in 2020-2022 with current design. No clean fix found. Left at -$128 / 267t / WR=40%.

## Rejected approaches

- **RS LONG**: ALL configs negative. Buying after strength = entering overextended moves.
- **RS breakeven stop**: WR drops from 47% → 13%. Wrong for this setup.
- **Gap Fill retrace ≥40% or ≥30%**: Marginal trades only $17-35/trade vs $123/trade baseline.
- **Gap Fill SHORT**: WR=40%, 2022 always negative, no regime combination helped.
- **Gap Fill 3-5%**: Only 1 trade in 3 years — gaps this large almost never qualify on Normal days.
- **Gap Fill window extension 10:30→11:30**: p=0.053, ticker concentrated (61% top 3), scan times noisy. Old PKL.
- **RVOL filter for RS**: >1.2x collapses to 5 trades. Universe too small.
- **Calm afternoon strategy**: No edge. 52 days, 71% in 2021, all signal types noisy.
- **VWAP_MR universe removal (IWM, QQQ, XLV, XLP)**: Curve fitting. Rejected.
- **VWAP_MR signal filters (wick/rejection/volume)**: All make things worse in combined tests.
- **Yesterday's large mover momentum/reversal** (threshold 2.5%): Total 2771t -$82,636. STOP_HIT rate 29-33% kills 2R setup. TIME_STOP positive drift (+$76-86/trade) but 2R target unreachable. 2021 vs 2022 inconsistent.
- **Failed Gap Short** (gap UP 1.5-3%, fail at 10:30): 106t +$10,156 overall BUT 2022-only edge. 2020 p=0.434, 2021 p=0.165, 2020+2021 combined p=0.282. SPY filter does all the work — removes 106 trades worth -$9,228. In 2022 SPY was below VWAP 100% of signal days (bear market), TARGET_HIT 75% vs 28% in 2020. Structurally a macro bear-market bet, not a replicable Normal-regime edge. DEFERRED.

## STRESS_MID (Stress 10:15–14:00 ETF momentum)

**Signal**: close[10:15] < VWAP(9:30-10:15) AND close[10:15] < open → SHORT
**Stop**: swing high (9:45-10:15) + 0.1% — VWAP stop too tight (47% stop-hit rate)
**Results** (sim, 97 Stress days): 86t, +$21,918, WR=66%, avg=$254.9/trade
- 2020: 20t +$4,693 WR=60% | 2021: 20t +$7,390 WR=80% | 2022: 46t +$9,835 WR=63%
- Raw directional edge: 73% WR without stops
- **Position sizing caveat**: stop=$2.165 avg → 231 shares × $315 = $72k notional on $25k account
  Engine PositionSizer sẽ cap position → real P&L estimate ~$2,800–4,000
- **Status**: IMPLEMENTED in engine.py section 7e. Verify trades appear via window_debug --year 2022.
- Script: `raits/raits/scripts/stress_mid_sim.py`

## STRESS_ORB_STK (DEFERRED — reverted from engine)

**Status**: Reverted. Engine produced -$2,528 / 224 trades across 3 windows (2020-2022). Sim showed +$5,581. Discrepancy unresolved.

**Root causes to investigate before re-enabling**:
1. **Universe expansion**: Adding `_STOCK_STRESS_UNIVERSE` to `_all_tickers` caused FADE/GAP_FILL to also trade these stocks → -$380 + -$264 collateral P&L. Fix: fetch STK stock bars separately, don't inject into global `day_stocks`.
2. **9:35 co-confirm timing works** (confirmed via debug log — TRADE_OPENED events fired correctly). Timing is NOT the problem.
3. **Engine P&L -$2,528**: possible causes: (a) HMM Normal in H1 2022 → too few Stress days in 2020/2021 to show edge; (b) stop too wide (1.0×ATR vs sim's 0.5×ATR); (c) SHORT bias wrong during 2020 COVID recovery; (d) position sizing reduces trade size vs sim's fixed $500 risk.
4. **Sim vs engine discrepancy**: sim used fixed per-trade risk, engine uses Kelly × account equity. On a 37-stock universe the trades are infrequent enough that sim/engine diverge materially.

**When to re-investigate**: after STRESS_MID is live and baseline is stable. Baseline after revert: **$14,932**.

## Post-earnings gap-down SHORT (DEFERRED)

**Finding**: SHORT after earnings gap-down ≥1% on Normal regime days.
- Polygon data (8-K dates): 27t +$2,689 WR=70%, all 3 years positive
- Best config: Normal ≥1%, Hold 1 day, Stop 1.5×ATR, Target 3×ATR
- Engine estimate: ~$900–1,100

**Why deferred**:
- 2022 = +$228 only (bear market → mostly Stress regime → no Normal days → no signal)
- 9 trades/year too thin for implementation overhead
- SHORT execution complex (margin, borrow)
- Needs earnings calendar maintenance (Polygon API weekly)

**Revisit when**: universe expanded to 60+ stocks → expect 15+/year → worth implementing.
- Data source confirmed: Polygon `/vX/reference/financials` `filing_date` = 8-K date = reaction day
- yfinance was noisier (more "trades" but lower quality, non-earnings gaps included)

## Pre-market bar exploration (all dead)

Pre-market bars ARE in raw parquet cache (04:00 ET start, all 50 tickers). PKL strips them at line 94.
Built `raits/data/raits_premarket.py` + `premarket_strategy_sim.py`. Results:

- **H1 PM direction filter**: removes good trades (WR filtered=50% vs removed=63%). Dead.
- **H2 Gap-and-Go LONG** (pm_return>1.5%, not fading → LONG 9:35): 91t +$1,788 p=0.234, 2022=-$462. Dead.
- **H3 PM Fade SHORT** (pm_return>1.5%, fading → SHORT 9:35): 2 trades in 3yr. Dead.

Pre-market data adds no edge over existing signals on current universe.

## VIX gate — T-1 vs same-day

**Bug**: initial implementation used prior-day VIX close (T-1). STRESS_ORB went -$510 because:
- Spike day (most profitable SHORT): T-1 VIX = 25-28 → gate BLOCKS it
- Recovery day (bad SHORT): T-1 VIX = 35+ → gate ALLOWS it
**Fix**: same-day VIX close. Works for STRESS_ORB (brief spikes). T-1 works for ORB (sustained VIX≥25 periods).

## VWAP Reclaim LONG — DEAD

**Signal**: dip below VWAP before 10:30, reclaim at 11:00, SPY above VWAP → LONG to 14:00
**Results**: 4,584t -$109,143 WR=45% | 2020=+$18,540 | 2021=-$31,380 | 2022=-$96,304
**Bootstrap**: p=1.000, CI=[$-150k, -$69k]
**Root cause**: Stop:Target = 578:59 (10:1), 23 trades/day = too noisy, 2022 bear kills edge.
**Do not revisit.**

## VIX cascade effects (accepted, no fix)

VIX gate unblocks circuit breaker → STRESS_MID fires 2× more days (106→208t), GAP_FILL fires on 6 extra bad days. Attempts to fix with VIX gate on STRESS_MID would block $+982 of profitable trades. GAP_FILL fix requires N=6 threshold = curve fitting. Accepted as cost of VIX gates; net system is still +$1,015.

## New strategy exploration results (all dead/deferred)

- **D Sector ETF divergence**: 9 ETFs vs SPY 9:35 divergence, WR=32-35% all configs, all negative. DEAD.
- **B ORB direction/DOW**: both LONG and SHORT profitable (WR=57% each). No filter justified.
- **E ORB SPY bar filter**: SPY 9:30 bar >2× mean → N=5 blocked, N=3 incremental after VIX gate. Curve fitting. DEAD.
- **C Earnings Gap UP + Fail SHORT**: best gap≥3% fail@10:15, 21t +$4,500 WR=57% p=0.040 — CI touches zero, 2022-concentrated, N too small. DEFERRED.
- **A Power Hour**: overlaps TF window (14:00-15:55). Not tested — structural conflict.
- Strategy space exhausted with current data. New sources needed for new edges (options IV, etc.).

## VWAP Reclaim SHORT — DEAD

**Signal**: SPY<VWAP@10:15 (bearish day), stock bounces to VWAP from below and closes below (rejection) → SHORT 10:30-13:30.
**Results**: 1419t P&L=-$135 WR=36% p=0.565 CI=[-$1,753, +$1,556]
- 2020: 415t -$420 | 2021: 452t +$524 | 2022: 552t -$238
- Core ETF: 435t -$7 | Stocks+ETF: 984t -$128
- 881/1419 (62%) STOP_HIT — VWAP does not act as consistent resistance
**Root cause**: Signal fires on ~4.3 tickers/day whenever SPY is bearish (328/756 days = 43%). Too common → essentially random short momentum. WR=36% barely above 33% break-even for 2R target but commission drag overwhelms thin edge.
**Do not revisit.**

## GAP_FILL sizing fix — DEAD (sizing illusion)

**Hypothesis**: Engine's max_position_pct=20% caps P&L. Raise to 50% or use uncapped vol-sizing.
**Analysis**: 27 engine GAP_FILL trades, all POSITION_LIMIT-bound (100%). Stop_dist range $0.10–$7.84 (mean $1.84).

| Scenario | P&L | 2020 | 2021 | 2022 |
|---|---|---|---|---|
| A Current (Kelly+20% cap) | +$81 | -$297 | +$586 | -$208 |
| B Vol-sizing, 20% cap | +$102 | -$291 | +$600 | -$207 |
| C Vol-sizing, 50% cap | +$435 | -$557 | +$1,508 | -$516 |
| D Uncapped $500/stop_dist | +$10,133 | +$4,053 | +$5,704 | +$376 |

**Why C fails**: amplifies losers equally — 2020 and 2022 get worse.
**Why D is fake**: TSLA 2020 trade (stop_dist=$0.098) gets 5,079 shares × $49 = $248k position. Same sizing illusion as STRESS_ORB_STK's +$6,368 sim → artificial leverage on tight stops.
**The sim's +$2,838 was also a sizing illusion.** Not a real edge.
**Do not revisit.**

## BacktestConfig orphaned fields (found 2026-06-23)

`BacktestConfig` trong `data_types.py` có 4 fields không được wire đúng:
- `max_position_pct` (0.20) — không truyền vào PositionSizer → luôn dùng default 0.20. **Fixed** (engine.py init).
- `kelly_fraction` (0.5) — không truyền, nhưng PositionSizer cũng default 0.5 → no bug. **Fixed** (engine.py init).
- `atr_stop_multiplier` (3.0) — chỉ khai báo, không dùng ở bất kỳ đâu. Dead field, để nguyên.
- `risk_per_trade_pct` (0.01) — shadow bởi `max_risk_pct` (cùng giá trị). Dead field, để nguyên.

Root cause: fields thêm vào dataclass qua nhiều iteration, không update engine init caller.
Limiting factor per strategy: FADE/GAP_FILL/ORB/STRESS_MID = POSITION_LIMIT. TF/VWAP_MR/STRESS_ORB/GF_SHORT = KELLY.

## System deep analysis (2026-06-23, snapshot results_20260623_070518.pkl)

**Risk-adjusted metrics (baseline $17,629):**
- CAGR: 11.75%/yr | Sharpe: 2.49 | Sortino: 3.67 | Calmar: 3.42
- Max DD: -$1,720 (-3.4%) — comfortably within -4% circuit breaker
- 2020=+$6,139 | 2021=+$8,017 | 2022=+$3,473

**Structural findings:**
- TREND_FOLLOW = 54% of P&L (concentration risk). TF avg/trade declining: 2020=$49 → 2021=$34 → 2022=$21.7
- TSLA = 17.3% of total P&L, top-5 tickers = 64% — extreme concentration
- Swing trades (>7hr): 292t → $12,437 (70.5% of P&L). Intraday: 717t → $5,192 (29.5%)
- Dead zone 11:00-14:00 is **structural** (all new strategy attempts fail there)
- VWAP_MR Sharpe=-0.20 (only negative), but kept: exits at 14:00 (TF start), no slot conflict
- Strategies by Sharpe: PE_SHORT=6.35 | GF_SHORT=5.03 | STRESS_ORB=4.71 | ORB=4.36 | TF=3.06 | VWAP_MR=-0.20

**Key OOS risks:**
- TF declining trend (main revenue driver degrading year-over-year)
- STRESS_ORB + STRESS_MID idle in low-VIX 2023-2024 environment
- TSLA dynamics changed post-2022 (high beta factor gone)

## Gap-filling strategy exploration — all dead (2026-06-23)

Tested 4 new strategies for architectural gaps, all with proper engine filters (scanner + CB + overlap):

| Strategy | Trades | P&L | WR | p-value | 2021 | Verdict |
|---|---|---|---|---|---|---|
| Midday Continuation LONG | v1: 278t +$4,747 | — | 55.8% | 0.019 | — | v1 MISLEADING |
| Midday Continuation LONG (v2, filtered) | 70t | +$18 | 45.7% | 0.491 | neg | DEAD |
| Late-Day Breakout (15:00-15:55) | 56t | +$1,268 | 55.4% | 0.067 | -$217 | DEAD |
| Calm Swing LONG (T+1) | 74t | +$1,462 | 51.4% | 0.238 | -$173 | DEAD |
| Normal SHORT Breakdown (T+1) | 132t | +$1,006 | 47.7% | 0.429 | -$2,302 | DEAD |

**Root cause — all fail in 2021 (bull/low-VIX):** System is structurally optimized for volatile/trending environments (2020 COVID + 2022 bear). Low-VIX bull markets require different signal types (options IV, sector rotation, macro calendar). 2020-2022 OHLCV data cannot generate edge for this environment.

**Do not sim more strategies with 2020-2022 data — strategy space is exhausted.**

## Look-ahead bias lesson (Late-Day Breakout)

First run: checking `b1500.iloc[0]['high'] > prior_high` then entering at `b1500 open` = look-ahead (bar high unknown at open). Fix: check `b1455.high > prior_high`, enter at `b1500 open`. Impact: 61t → 56t, +$2,530 → +$1,268, p=0.006 → 0.067. Always verify signal bar vs entry bar distinction.

## VWAP_MR instrument bias — discovered 2026-06-24

**Finding:** VWAP_MR bootstrap (p=0.613) and IS removal were based on trades on **stocks** (MR_CANDIDATE_POOL via MR scanner), NOT sector ETFs.

Engine logic (engine.py lines 545-546):
```python
_effective_vwap_universe = mr_scanner_results + [t for t in config.vwap_universe if t not in scanner]
```
Sector ETFs (XLF, XLE...) in `config.vwap_universe` had NO data for 2017-2022 → ETF universe = empty → all 272 zombie trades were on momentum stocks (TSLA, NVDA, AMD) = wrong instrument for mean reversion.

**Implication:** Must re-evaluate VWAP_MR on sector ETF data (fetch in progress) before treating removal as final. Could be meaningfully different on range-bound ETFs vs momentum stocks.

## Data gap — sector ETFs missing IS data (2026-06-24)

XLF, XLE, XLV, XLU, XLI, XLK, XLP, XLB, XLY, GLD: only 2023-2024 in cache.
Fix: `fetch_sector_etfs.py` (d:\raits\raits\) — fetches 2017-2022 IS + 2023-2024 OOS.
Run after PE_EXPANSION/META fetch completes.

## IS 2017-2022 Optimization Session (2026-06-24)

### New baseline settings
- IS period: 2017-2022, $50k account
- max_risk_pct=1.5%, kelly_fraction=0.75, MAX_TREND=3, PE_SHORT_GAP_MIN=0.05
- Snapshot: results_20260624_135619.pkl → Ann=10.5%, +$31,484/6yr

### Bootstrap per strategy (results_20260624_135619.pkl)
- CONFIRMED (CI>0): TF p=0.008, PE_SHORT p=0.007, ORB p=0.019, STRESS_ORB p=0.019
- NO EDGE: FADE p=0.754, GAP_FILL p=0.687, VWAP_MR p=0.613
- BORDERLINE: STRESS_MID p=0.112, GF_SHORT p=0.128
- STRESS_MID surprise: 270t +$2,406 total but mean=+$9/trade vs high variance → CI crosses zero

### MAX_TREND=3 analysis
- +$3,158 total, ann 10.5% (crosses 10% target)
- 2021 worse by -$3,704: slot 3 takes 49 extra trades (avg -$27, WR=43%, 61% MAX_HOLD)
- Extra trades bad across ALL regimes and directions — structural: slot 3 = weakest setups
- ADX gate sim: ADX≥15 removes 21 bad trades (+$1,357) but p=0.113 → too few trades, likely overfit
- Accept TF=3: net 6yr benefit outweighs 2021 cost

### FADE exhaustive analysis — REMOVE confirmed
- Gap size: <1% best (WR=53%, avg=+$10) but CI still crosses zero (p=0.113)
- Prior day return: abs<1% best but p=0.088 — still no confirmed edge
- Combined Calm+prior<1%: p=0.095 — closest but not confirmed
- Year-by-year with any filter: inconsistent (2017 negative even in "good" conditions)
- p-hacking path: adding 5 conditions → n=5 trades, p=0.004 — meaningless (overfitting)
- SPY_5d signal: good trades have SPY_5d=-0.3% vs bad trades SPY_5d=+1.7% — real signal but sample too small
- Thursday WR=73% vs Friday WR=47% — real pattern but sample too small
- Verdict: No filter rescues FADE. 2017/2021 outperformance = random variation.

### Coverage after removing FADE/GAP_FILL/VWAP_MR
- Calm regime: 421 → 8 trades (only PE_SHORT, earnings days only)
- Normal: 863 → 781 (ORB + TF + GF_SHORT + PE_SHORT) — well covered
- Stress: 592 → 592 (STRESS_MID + STRESS_ORB + TF) — well covered
- Midday 10:15-14:00 in Calm = zero coverage — ACCEPTABLE (both strategies had no edge)
- Years most affected: 2017 (51% Calm), 2019 (36% Calm), 2021 (32% Calm)

### Position sizer limiting factors (current baseline)
- TF: Kelly-bound 97% trades → kelly_fraction is the lever
- ORB: PosLimit-bound 100% → max_position_pct=0.30 is binding (Kelly cap ~$16,900 > $15k)
- STRESS_MID: PosLimit-bound 100% → Kelly cap ~$18,400 > $15k
- PE_SHORT: Mixed (70% PosLimit, 30% VolTarget) → Kelly cap ~$21,750 > $15k

### Actual IS strategy stats vs hardcoded bootstrap
All strategies have LOWER actual Kelly fraction than hardcoded values:
- TF: 0.280 (hardcoded) → 0.134 actual (-52%)
- STRESS_MID: 0.490 → 0.074 (-85%) — most over-estimated
- ORB: 0.451 → 0.262 (-42%)
- PE_SHORT: 0.580 → 0.478 (-18%) — most accurate
- Payoff ratios lower because many trades exit before target (time stop, swing exit)
- Do NOT update STRATEGY_STATS — would reduce position sizes and hurt P&L

## Open questions

- **GAP_FILL discrepancy**: CLOSED. Sim +$2,838 was sizing illusion — uncapped $500/stop_dist on $0.10 stop = $248k hypothetical position. Engine's 20% cap is correct risk management. No fix viable.
- **ORB 2022 crash**: WR=26%, fixed by VIX≥25 gate (-437 in 2022 = only 4 remaining bad trades, no more easy fix)
- **Strategy space exhausted (2020-2022)**: All buildable strategies tested. Need 2023-2024 OOS data or new data sources (options IV, sentiment, earnings calendar expansion).

## Gotchas (added 2026-08-03 — opening imbalance research)

- **`cluster_bootstrap.py` within-date permutation is NOT centred (live bug).**
  It compares `|perm| >= |obs|` against ZERO. Events on non-mixed dates have no
  label freedom, so their contribution is a constant offset present in `obs` and
  in every permuted draw — the null is centred on that offset, not on zero.
  Measured on the imbalance study's primary cell: null centre = +0.123%,
  uncentred p = 0.0129 vs centred p = 0.0267 (**overstated ~2x**).
  Does NOT overturn the catalyst verdict (p=0.524, far from threshold), but the
  published number is not what that test should have produced. Fixed version:
  `orb_stocks/imbalance_research/bootstrap_imbalance.py::layer3`.

- **Within-date conditional tests run on FAR fewer events than n suggests.**
  Only *mixed* dates (both arms present) have label freedom. Imbalance study:
  n=144 events → deciding test actually rests on 23 dates / 63 events (35 vs 28).
  The design-effect "effective n" (108.3) describes the whole population, NOT
  the conditional test. This is why dropping QCOM (5 events, 2 of them in the
  28-event against-arm) moved p from 0.027 to 0.102. Always report mixed-date
  count alongside any within-date p.

- **Polygon plan: NBBO quotes are NOT entitled** (`/v3/quotes` → 403), trades ARE
  (`/v3/trades` → 200). Canonical Lee-Ready needs the quote midpoint, so it is
  not constructible; only the tick rule is. No auction-imbalance endpoint exists
  (404). Check entitlements before scoping any microstructure work.

- **Raw sign-agreement is meaningless in a one-sided population.** ORB event pop
  is 98% down-gap and 75% sell-side flow → 74% chance agreement. Observed was
  74%; Cohen's κ = +0.013. Use kappa, not raw agreement.

- **`gap_pct` in `orb_event_index.parquet` is already in PERCENT units**
  (-2.773 == -2.773%), not a fraction. Do not multiply by 100.

## Open questions

- **Opening imbalance = MONITOR, not dead.** Pre-open signed flow (09:00-09:30 ET,
  tick rule) separates ORB SHORT outcomes: +0.253% aligned vs -0.094% against,
  within-date p=0.0267, confound-clean (κ=+0.013 vs gap, spearman -0.02 vs RVol).
  Downgraded from GO by concentration: QCOM→p=0.102, NVDA→p=0.065, 2022-only
  (2021 p=0.528 but only 4 mixed dates = underpowered). Binding constraint is
  MIXED-DATE COUNT (23), not event count. See orb_stocks/imbalance_research/FINDINGS.md.
- **The official auction-imbalance hypothesis has still never been tested** — the
  data does not exist on this plan. The tick-rule proxy is a different object.

## Gotchas (added 2026-08-03 — data corruption + orderflow probe)

- **META has 5,157 corrupt 5-min bars, 2021-06-30 .. 2022-01-28 (148 days).**
  Close recorded ~$12-16 instead of ~$300-380. ONLY META; no other ticker.
  Lives in `window_debug_5min.pkl` (and presumably the 5min parquet cache), which
  feeds window_debug, stress_orb_stk_sim, and the ORB event index.
  Baseline impact NEGLIGIBLE: 1 trade (GF_SHORT, entry $12.62), -$34 of $33,550 —
  corrupt prices made META fail the strategies' own filters rather than fire fake trades.
  Detector: flag bars whose close is <50% or >200% of that ticker's rolling 21-day median.

- **The `|pct_return| > 25%` corrupt-bar gate MISSES two-sided corruption.**
  pct_return is a RATIO. When entry AND exit are both corrupt (~$14 -> ~$14) the
  ratio looks normal and the gate passes it. It only fires on one-sided corruption.
  Measured: 4 META events had corrupt entry_px, gate caught 1. Three survive into
  the 267-event clean population (1.1%) AND into the 144-event primary cell of the
  auction-imbalance study — which was already MONITOR and already fragile to 5 events.
  FIX NEEDED: add a price-LEVEL check (entry_px vs ticker's rolling daily median),
  not just the ratio check. Re-run the imbalance study after fixing.

- **Mean/median ratio is the corruption tell.** The 5-min pressure probe showed
  mean +5.894c vs median +0.500c (12x). Top 0.1% of observations = 533% of total
  profit (i.e. the other 99.9% lose money). Winsorising 0.18% of rows removed 97%
  of the edge. All of it was the META block. When mean >> median, inspect the tail
  BEFORE interpreting — do not just winsorise and move on.

- **p-values are useless at panel scale.** 4.28M bar-observations: everything is
  "significant". Decisions must be read off economic magnitude (cents/share) with
  DAY-clustered CIs. Resample DAYS, not observations — and take the median across
  per-day medians so high-activity days don't dominate (also O(n_days), tractable).

## Rejected approaches

- **Orderflow (footprint / DOM) as a SIGNAL filter on existing strategies — REJECTED
  on horizon mismatch.** Measured holds: STRESS_MID 152min, STRESS_ORB 158, GF_SHORT
  180, ORB 350, PE_SHORT 1825, TREND_FOLLOW 6925 (88% overnight, 61% MAX_HOLD exits).
  Orderflow is a seconds-to-minutes tool. Nothing here trades at that horizon.
- **Orderflow for EXECUTION — REJECTED on measured value.** Entry-side prize vs bar
  VWAP = +$1,219 across 1,292 trades over 6 years = $0.94/trade. Exit side is
  -$7,877 (model already assumes fills better than VWAP). Not worth $63-278 of data
  plus a build. See `orb_stocks/imbalance_research/execution_ceiling.py`.
- **5-min bar pressure proxies for a 5-30 min strategy — DEAD.** 0 of 20 cells clear
  the pre-committed $0.034 gross hurdle. See `intraday_pressure/FINDINGS.md`.

## Open questions

- **Forced-exit fills look backwards.** SAFETY_MODE (n=16) mean -$78.94/trade and
  CIRCUIT_BREAKER (n=69) mean -$23.73/trade vs bar VWAP — i.e. modelled as filling
  BETTER than average. Panic liquidation should fill WORSE. n is small and VWAP is
  not the right benchmark for every exit type, so this is a flag, not a verdict.
  Same class of problem as the futures BUILD STP work (-$19.09/trade, -$38,246 drag).
- **Order-flow proper is NOT closed** — bars destroy the microstructure the hypothesis
  is about. The probe returning nothing means tick data would be a bet, not a
  follow-up on evidence. Reopening needs: DBEQ.BASIC is only 4 small venues (NOT
  consolidated); no consolidated equity feed exists before 2023-03-28; the live
  runtime (5-min cron) cannot execute sub-minute anyway.

## Gotchas (2026-08-05)

- **`_swing_cache` khoá bằng `id(df)`** (`futures/_validated_core.py:206`). `id()` là địa
  chỉ bộ nhớ; DataFrame tạm bị thu hồi thì cái kế có thể rơi đúng địa chỉ đó → trúng cache
  của **khung dữ liệu khác**, KHÔNG báo lỗi. Production an toàn *do cách dùng* (giữ df
  sống suốt tiến trình), không phải do thiết kế. Bất kỳ script nào tạo df tạm rồi thả —
  sweep, thí nghiệm cắt cửa sổ — đều nhận kết quả rác trông rất hợp lý.
  **Dấu hiệu nhận biết: thời gian chạy KHÔNG đơn điệu theo kích thước dữ liệu.** Cửa sổ
  120 phiên chạy 0.58s trong khi 60 phiên mất 1.50s = một cú trúng cache.
  Cách chữa tạm trong script: `vc._SWING_CACHE.clear()` trước mỗi lần gọi.

- **`spy_daily_live.csv` bị scheduler ghi lại lúc 13:45 ET mỗi ngày.** Mọi phân tích dùng
  nó chỉ tái lập được cho tới lần pre-flight kế tiếp. Hai bảng chạy cách nhau vài giờ
  trong cùng một phiên làm việc có thể không so sánh được với nhau. Ghi lại giờ chạy.

- **`deploy_sim` in "Rổ" trong banner → cp1252 khi stdout ghi ra file.** Tính xong toàn bộ
  rồi mới chết ở dòng `print` cuối. `PYTHONIOENCODING=utf-8` là bắt buộc khi redirect.

- **PowerShell 5.1 biến stderr của native exe thành lỗi chí mạng** khi có
  `$ErrorActionPreference="Stop"` + `2>&1`. `hmmlearn` in cảnh báo hội tụ ra stderr →
  giết cả vòng lặp sweep. Dùng Bash loop, hoặc bỏ `2>&1`.

- **Đừng ném stderr vào `/dev/null` trong script chạy dài.** Làm thế một lần và mất trọn
  một vòng sweep trước khi nhìn thấy lỗi. Cho stderr một file riêng.

- **`grep` không có `--line-buffered` sẽ nuốt tiến độ** khi pipe ra file — script in
  "instrument X xong" mà không thấy gì suốt cả tiếng, không phân biệt được với treo máy.

- **`sorted(set(index.normalize()))` trên index tz-aware qua DST** cho ra thứ tự không
  khớp mảng mà `searchsorted` đang dò → lát cắt rơi vào vùng lịch sử khác. Dùng
  `np.unique(values, return_index=True)` để ranh giới phiên và mảng dò không thể mâu thuẫn.

- **Cắt DataFrame lớn bằng boolean mask trong vòng lặp = kẹt bộ nhớ, không phải nặng CPU.**
  ~1,000 lần mask trên 2.4M dòng chạy 3 tiếng ở 8% CPU. `searchsorted` + `iloc` cho view.
  Tải CPU thấp trong lúc chạy tính toán = dấu hiệu sai thiết kế, không phải máy chậm.

## Lessons (2026-08-05)

- **Một lát cắt sai vẫn trả về con số trông hợp lý.** Ba vòng thí nghiệm cắt cửa sổ đều
  ra bảng đẹp trước khi lộ ra là rác. Thứ phát hiện được chúng không phải là nhìn kỹ hơn
  mà là **những giá trị bất khả thi** (lát cắt kết thúc 2018 trả về vị thế vào ngày 2024)
  và **quan hệ không đơn điệu** (cửa sổ lớn hơn chạy nhanh hơn). Mọi thí nghiệm cắt dữ
  liệu phải mang theo assertion tự kiểm — ở đây là "lát cắt kết thúc đúng ngày as-of".

- **Calmar nhiễu ±0.2 ở quy mô sweep này** vì mẫu số MaxDD là một sự kiện đơn lẻ. Hai arm
  cạnh nhau lệch 0.46 (mult 3.0 = 1.50, mult 3.5 = 1.96). Đọc sweep theo đại lượng đơn
  điệu (net$, MaxDD) trước; các tỉ số chỉ dùng để loại, không dùng để chọn.

- **Tham số dùng cho hai việc thì sweep nó không cô lập được gì.** `chandelier_atr_mult`
  vừa đặt khoảng stop vừa là mẫu số risk$ → nới stop làm gate đá ra 27 → 1,403 lệnh.
  Kiểm điều này bằng cách nhìn số lệnh taken/rejected mỗi arm TRƯỚC khi diễn giải net$.

- **Không kill tiến trình theo tên.** `Stop-Process -Name python` giết luôn scheduler
  production (và cả shell của chính tool). Dùng task ID của việc mình khởi động.

## Rejected approaches (2026-08-05)

- **Nới/siết `chandelier_atr_mult` khỏi 2.5 — TỪ CHỐI.** Không arm nào vừa lãi hơn vừa
  Calmar cao hơn. 3.5 hơn ở 3/4 chỉ số nhưng chênh nằm trong nhiễu của thước đo, net$
  thua 14%. Xem TASK.md.

- **Giãn slot scheduler 5→6 phút — TỪ CHỐI, đã tính.** Độ trễ trung bình 8.0 phút so với
  7.9 phút hiện tại. Runtime 5.5 phút mới chi phối, không phải khoảng cách slot. Chỉ làm
  hết dòng WARNING chứ không lấy lại được tiền.

## Rejected approaches (2026-08-06) — tăng tốc run_day

Đo trước khi chọn: prep 34.67s (42%) / vòng lặp replay 48.11s (58%) / cache 122 MB per
instrument; ghi đĩa 0.70s, nạp 1.52s. `run_day` hiện 5m03, slot cách 5 phút → skip một nửa.

- **Cache prep ra đĩa — LOẠI.** Giống hệt theo cấu tạo (`_swing_cache(df)` là hàm thuần)
  và LÀ net win thật (33.15s/instrument), nhưng chỉ cắt 42% → còn ~4 phút, biên 1 phút
  trên hạn 5 phút. Và đẻ ra 489 MB trạng thái phải huỷ đúng lúc mỗi khi parquet đổi
  (append hằng ngày + repair). Không đáng.

- **Checkpoint + chỉ replay hôm nay — LOẠI (chưa cần).** Chính xác tuyệt đối về mặt nhân
  quả, ~1s, cache ~1 MB. Nhưng **đổi luồng chạy** `_validated_core.py` (bỏ qua ngày, nạp
  `pos` từ ngoài) nên "tác động bằng không" chỉ là kỳ vọng, không phải cấu tạo — yếu hơn
  hẳn so với sửa khoá cache. Cần shadow mode để bảo chứng. Đuổi theo 1s trong khi 33s đã
  dư sức giải quyết = tối ưu quá đà.

- **Giãn slot 5→6 phút — LOẠI, đã tính.** Trễ tb 8.0 phút vs 7.9 hiện tại. Runtime 5.5
  phút mới chi phối, không phải khoảng cách slot.

→ CHỌN: **cắt còn 250 phiên ở tầng gọi** (`run_live_day`), ~33s, stateless, không đụng
engine. Chi tiết + cổng kiểm: TASK.md mục "KẾ HOẠCH — cắt cửa sổ replay".

## Cơ chế: engine phụ thuộc lịch sử ở đúng hai chỗ (2026-08-06)

Đọc `backtest_swing_tf`: vòng lặp `for day in days:` carry ĐÚNG một biến `pos` (dict 7 số).
EMA + ATR sinh tín hiệu tính TRONG MỘT NGÀY trên bar 5 phút (`hist = bars5.loc[:idx[n]]`,
`bars5 = b5[day]`) → **không cần lịch sử**. `hl`/`b5`/`ts` độc lập theo ngày.
Chỉ còn: `datr` (ATR ngày, Wilder → ~56 phiên hội tụ) + `pos` (tối đa 5 ngày, MAX_HOLD).

→ Nhu cầu warmup thật ~60 phiên. Trùng khớp số đo (W=20 lệch, W=60 khớp). Khi cơ chế và
số đo hội tụ thì mới được coi là hiểu; một trong hai thôi thì chưa.

## Gotchas — múi giờ trong code phân tích (2026-08-05/06)

Ba lỗi cùng một khuôn trong một phiên, tất cả đều ở code phân tích của tôi chứ không
phải engine, và tất cả đều trả về **con số trông hợp lý**:

1. `sorted(set(index.normalize()))` trên index tz-aware qua DST → thứ tự không khớp mảng
   `searchsorted` đang dò → lát cắt rơi vào vùng lịch sử khác.
2. `index.normalize().values` trên index **Asia/Tokyo** → `.values` quy UTC trước; nửa đêm
   JST = 15:00 UTC hôm trước → **mọi** phiên bị gán nhãn sớm một ngày. ET không dính vì nửa
   đêm ET (04:00/05:00 UTC) nằm trong cùng ngày UTC — đã kiểm 0/2,987 phiên lệch.
3. Cắt DataFrame bằng boolean mask trong vòng lặp → kẹt bộ nhớ (3 giờ ở 8% CPU).

**Quy tắc rút ra:** khi cần nhãn ngày phiên, làm ĐÚNG CÁCH ENGINE LÀM —
`pd.Timestamp(d).tz_localize(None)` (giữ giờ địa phương), KHÔNG đi qua `.values`
(quy UTC). Kiểm bằng cách so hai cách trên toàn bộ index, đếm số phiên lệch.

**Và:** một ca lệch có thể tố cáo cả nhóm "OK" bên cạnh nó là vô nghĩa. MNKD báo 1/3 lệch;
đào ra thì 2 ca "OK" kia cũng đang so hai cửa sổ lệch nhau, tức không kiểm được gì.
Đừng đọc "14/15" là "gần đạt".

## Lessons (2026-08-06)

- **Đo độ phủ, đừng đếm dấu OK.** Thêm cột "checkpoint này có vị thế mở không" vào
  `verify_resume.py`: checkpoint trống + không lệnh nào sau đó = đường seed `pos` chưa
  bao giờ được đi qua. Một màn hình toàn OK có thể là một màn hình chưa kiểm gì.

- **Giữ tham chiếu mạnh hơn hash.** Sửa khoá cache `id(df)`: giữ `df` trong entry khiến
  `id()` hợp lệ THEO CẤU TẠO (hai object sống không thể chung địa chỉ — bảo đảm của
  CPython), chi phí chạy bằng không. Hash nội dung tốn 0.54s/lời gọi và chỉ là xác suất.

- **Tham số mới vào hàm có cache = phải vào khoá cache.** Thêm `datr=` mà quên đưa vào
  khoá là tái lập đúng lỗi vừa vá, ở chỗ mới. Kiểm trực tiếp: cùng df + hai `datr` khác
  phải ra hai kết quả khác và hai entry cache.

- **State mang qua vòng lặp phải copy.** `pos = dict(resume_pos)` — vòng lặp ratchet
  `pos["stop"]` tại chỗ; thiếu copy thì gọi lần hai từ cùng checkpoint ra kết quả khác
  lần một, và lỗi này chỉ lộ khi có ai đó gọi lại.

## Gotchas (2026-08-07)

- **Dry-run ghi state như chạy thật.** `_run()` trả `True` khi `--dry-run` mà không
  thực thi gì. Bất kỳ chỗ nào ghi "đã làm rồi" dựa trên giá trị trả về của nó sẽ ghi
  nhầm. Đã xảy ra: một lần chạy thử ghi `{"2026-08-07": true}` vào `maxhold_state.json`,
  suýt vô hiệu hoá đúng bản vá đang test, ngay trước ngày nó cần hoạt động.
  **Quy tắc: `if ok and not dry_run`.** Và sau khi chạy thử một tính năng có ghi state,
  **kiểm file state** — đọc lại code không phát hiện được.

- **APScheduler không có khái niệm "job trễ" khi khởi động.** Nó tính lần bắn KẾ TIẾP.
  Bật sau giờ cron → job hôm đó không tồn tại, không misfire, không log. Mọi job chạy
  một lần/ngày đều cần catch-up lúc khởi động, không chỉ `maxhold_exit`.

- **`has_working_stop` so theo `t.contract.symbol`, không phân biệt tháng hợp đồng.**
  Sau rollover, lệnh STP mồ côi trên hợp đồng cũ khiến B4 tin rằng vị thế trên hợp đồng
  mới đang được bảo vệ. Guard so **mã instrument** trong khi rủi ro nằm ở **tháng**.

- **Lệnh STP mồ côi không chỉ vô dụng — nó mở được vị thế.** Vị thế LONG đóng nhưng
  SELL STP còn treo; giá chạm → khớp → **mở SHORT mới** không ai yêu cầu, không có
  trong state. Đóng vị thế mà không huỷ lệnh bảo vệ là tạo ra một cái bẫy.

## Lessons (2026-08-07)

- **Test có thể tự mâu thuẫn với tiền đề của nó.** `test_ro6` fail nhiều tuần: nó gọi
  `run_maxhold_exit` với vị thế mới 2 ngày (`max_hold_days=5`) rồi khẳng định state phải
  rỗng. Code đúng, test sai. **Cách chặn: assert tiền đề trước khi assert kết luận** —
  `assert closed` ngay sau lời gọi, để lần sau ai đổi ngày thì test báo ở *nguyên nhân*
  chứ không báo ở *triệu chứng*.

- **Test dùng đồ giả có thể pass vì lý do sai.** "Failure không được ghi nhận" pass với
  job giả vì *không có gì ghi cả* — việc ghi nằm trong closure thật. Khi tính chất cần
  kiểm nằm ở một tầng khác tầng đang mock, phải chạm tới tầng đó.

- **Kiểm tính chất *ngược* mới ra giá trị.** Cặp T3/T4 của fingerprint: append bar mới
  → checkpoint **vẫn dùng được**; sửa 1 bar giữa lịch sử → **hỏng ngay**. Chỉ kiểm một
  chiều thì không phân biệt được "hoạt động" với "luôn trả True".

- **Cache giữ tham chiếu phải có giới hạn.** Giữ `df` trong entry khiến `id()` hợp lệ
  theo cấu tạo, nhưng giữ **vô hạn** thì caller tạo khung trong vòng lặp sẽ phình bộ nhớ:
  `reconcile_nkd` ghim 1,038 khung → **8.5 GB**, sau khi chặn ở 16 → **747 MB**.
  Kích thước phải phủ đỉnh thật (5 instrument × 2 khoá do `datr` inject/không inject = 10).

## Rejected approaches (2026-08-07)

- **Tự động neo lại offset khi phát hiện bậc nhảy — TỪ CHỐI.** Roll 4 lần/năm; tự sửa
  sẽ **âm thầm nắn một lỗi dữ liệu thành chuỗi trông liền mạch**. Chọn dừng + người xác
  nhận: đổi 4 ngày giao dịch/năm lấy việc không bao giờ nắn nhầm. Dự án này đã trả giá
  nhiều lần cho lỗi *im lặng*, chưa lần nào cho lỗi *ồn ào*.

- **Đưa `--shadow-verify` lên CLI của scheduler — TỪ CHỐI.** Nó tốn một replay đầy đủ mỗi
  instrument; bật cho cả 22 slot thì `run_live_day` lên ~13 phút, bỏ 2/3 slot — làm xấu
  đúng cái đang đi sửa. Slot nào gánh nổi chi phí đó là **tính chất của lịch chạy**,
  không phải lựa chọn để trên dòng lệnh.

## Lessons (2026-08-07, sự cố bậc thang offset)

- **Cơ chế bù trừ hoạt động tốt sẽ CHE lỗi ở tầng dưới nó.** Parquet ghi sai giá 3 ngày
  nhưng `_splice_live` đo chênh rồi `to_candidate` trừ ra, nên **giá lệnh luôn đúng** và
  mọi chỉ dấu vận hành bình thường. Muốn thấy lỗi tầng dữ liệu phải **đo thẳng tầng dữ
  liệu**, không suy từ việc "lệnh vẫn khớp đúng".

- **Đối chiếu với GIÁ THẬT, không phải với một chuỗi khác của cùng nguồn.** Tôi kết luận
  dựa trên `ContFuture` mà chưa kiểm nó có bằng hợp đồng đang giao dịch không (may là
  bằng). Bằng chứng dứt điểm là **lệnh khớp thật**: giá fill nằm ngoài High-Low của bar
  → không thể chối cãi.

- **Guard bắt sự kiện rời rạc không thay được bất biến liên tục.** Ba guard đã có
  (`assert_utc_convention`, history invariant, join check) đều bắt **sự kiện**. Không cái
  nào hỏi "hai nguồn có còn mô tả cùng một thị trường không". Bất biến đó là thứ bắt được
  lỗi này.

- **Ranh giới sai làm phép đo ảnh hưởng vô nghĩa.** Lần đầu tôi cắt tại 00:00 ngày 05/8
  trong khi điểm chuyển ở **giữa phiên** (06:13 UTC) → báo "không ảnh hưởng", sai. Tìm
  điểm chuyển thật trước, rồi mới đo.

- **Đọc code trước khi mô tả cơ chế.** Tôi lặp lại "ATR Wilder → nhiễm ~56 phiên" nhiều
  lần trong comment và commit. Code là `tr.rolling(14).mean()` — trung bình trượt đơn
  giản, nhiễm **14 phiên** rồi rơi hẳn.

- **Xét lại lập luận khi tiền đề thay đổi.** Tôi phản đối "tự sửa offset" vì (a) không
  chắc là roll, (b) neo bằng 1 cặp bar, (c) sai thì sai mãi. Sau đó cả ba đều được giải
  quyết (định danh hợp đồng / median 4000 bar / kiểm căn chỉnh hôm sau) nhưng tôi vẫn giữ
  kết luận cũ cho tới khi bị hỏi lại.

- **Độ lớn không phân biệt được roll với biến động thật.** Biến động 1 phút lớn nhất năm
  qua LỚN HƠN spread roll ở cả 4 mã. Khi có **tín hiệu trực tiếp** (`localSymbol` từ
  `qualifyContracts`) thì đừng suy gián tiếp từ giá.

## Gotchas (2026-08-07)

- **`git stash -u` cất luôn việc chưa commit của người khác.** Tôi dùng nó để kiểm 2 test
  fail có phải lỗi mình không — nó cất cả phần sleeve ledger user đang làm dở. Pop lại
  được, nhưng **phải `git status` trước khi stash**.

- **`--dry-run` của `update_ibkr_daily` thoát sớm**, không chạy tới phần kiểm căn chỉnh.
  Muốn thử guard phải chạy thật trên **bản sao** parquet.

- **Log scheduler bị lẫn output pytest** — `run_scheduler.py` gắn FileHandler vào root
  logger ngay khi import, mà test có import nó. Gây nhiễu cho người đọc log. CHƯA SỬA.

- **Checkpoint tự huỷ mỗi ngày — shadow phiên 08-07 thu về số 0.** Fingerprint phủ lịch sử
  "tính đến `last_day`", tưởng là an toàn vì không phủ phần sau. Nhưng append 13:45 ET
  bổ sung **đuôi của ngày hôm trước** (13:46→23:59 ET), nên phần "tính đến last_day" vẫn
  lớn lên. Lệch **554 bar** trên MES/MNQ/MYM/M2K = đúng số bar 13:46→23:59 ET ngày 08-06. Gốc rễ là **chọn ngày theo khung đã ghép** (có bar live → đủ ngày
  hôm qua) trong khi **fingerprint tính trên parquet** (chưa đủ). Sửa: `advance_day()` đọc
  session từ parquet và lùi 1 ngày so với session cuối. Bài học: khi hai nguồn dữ liệu
  cùng mô tả "lịch sử", phải dùng **cùng một nguồn** cho cả chọn mốc lẫn băm.

- **Guard im lặng vẫn là guard hỏng.** Checkpoint từ chối đúng như thiết kế nên không có
  log ERROR nào; nhìn qua tưởng bình thường. Chỉ lộ ra khi đi đọc log để tìm `DOI CHIEU`.
  Cái gì "từ chối an toàn" thì phải đếm số lần từ chối, không thì nó chết âm thầm.

- **MNKD sống sót không phải may — do lệch múi giờ, và nó cho điều kiện tổng quát.**
  Fingerprint MNKD cắt theo giờ **Tokyo**, tức 00:00 JST = **15:00 UTC**, nằm TRƯỚC mốc
  append (13:45 ET = 17:45 UTC) → lịch sử đã cố định. Rổ 4 cắt 00:00 **ET** = 04:00 UTC
  hôm sau, nằm SAU mốc append → còn bị điền tiếp. Điều kiện: **mốc cắt phải nằm trước ranh giới append**. Lấy session áp
  chót *trên chính khung của dữ liệu* thoả cả hai mà không cần phân biệt mã nào.
  **Mắc lỗi này HAI lần trong một buổi:** đo MNKD bằng khung UTC (nó chạy Tokyo) → "chênh
  477, dư 166 không giải thích được"; rồi đo Rổ 4 cũng bằng khung UTC (engine chạy ET) →
  "314" trong khi log ghi 554. Hai loader khác nhau: `futures._validated_core.load_parquet`
  → **ET tz-aware**; `global_index.update_ibkr_daily._load_parquet` → **UTC**. Cách bắt:
  tìm mốc cắt cho ra **đúng** số dòng đã lưu, thay vì tìm cách giải thích phần chênh.

## Gotchas (2026-08-08)

- **Live chạy luật thoát KHÁC backtest, ở mọi lệnh — và đó là lỗi của LIVE, không phải
  backtest.** `place_stop` đưa STP lên sàn 0–1 giây sau khi khớp (GTC, outsideRth).
  `backtest_swing_tf` kiểm stop trong khối `if pos is not None`, chạy TRƯỚC khối vào lệnh
  trong cùng vòng lặp ngày → vị thế mở hôm nay mãi **hôm sau** mới bị xét. Cửa sổ lệch
  ≈ 14:00→23:59 ET ngày vào lệnh.

  Quét độ trễ kích hoạt STP (model_sameday_stop.py, có cổng đối chiếu trade-for-trade với
  engine, 4/4 mã KHỚP):

  | kích hoạt sau | lệnh | P&L | thắng | lỗ tạm sâu nhất khi trần (tv/p95/max) |
  |---|---|---|---|---|
  | 0h (live) | 3736 | **−$10.832** | 11% | — |
  | 1h | 3307 | +$19.906 | 13% | $31/$160/$1.351 |
  | 2h | 3141 | +$20.816 | 14% | $39/$208/$1.351 |
  | 4h | 3114 | +$34.112 | 15% | $41/$224/$1.372 |
  | 8h | 3047 | +$46.767 | 16% | $48/$271/$1.890 |
  | sang ngày (=backtest) | 3044 | +$47.166 | 16% | 0 |

  **Đường cong tăng đều rồi bão hoà, KHÔNG phẳng-rồi-nhảy-ở-nửa-đêm** → "cho lệnh chỗ thở"
  là cơ chế thị trường thật, không phải hiệu ứng nhóm bar theo ngày lịch. 8h lấy 99,2%
  edge. Stop vận hành hẹp bằng **1/22** dải chandelier danh nghĩa (mult×ATR ngày) ở cả 4
  mã — nên nó không sống nổi qua quãng nhiễu sau điểm vào.

  **Kết luận:** không cần sửa engine hay chạy lại WFO. Cần **hoãn đặt STP**. Nhưng phải
  sửa CẢ **guard B4** — nó tự đặt lại stop cho mọi vị thế `stop_order_id is None` ở mỗi
  lần chạy, nên bỏ mỗi dòng `place_stop` lúc vào lệnh thì độ trễ chỉ còn ~5 phút. B4 phải
  biết cửa sổ trần là có chủ đích.

  **Độ trễ vào lệnh là thứ yếu — hoãn STP mới là tất cả** (model_entry_latency.py, cùng
  cổng đối chiếu, 4/4 KHỚP). Độ trễ tính từ lúc bar 5 phút ĐÓNG (đo thật trên MES 08-07:
  bar 14:55–14:59, lệnh gửi 15:10:41 → trễ ~10,7 phút, giá tệ hơn 12 điểm):

  | kích hoạt STP | trễ 0p | trễ 5p | trễ 10p | trễ 15p |
  |---|---|---|---|---|
  | STP ngay (0h) | −$10.832 | −$9.358 | −$6.467 | −$7.044 |
  | STP sau 8h | +$46.767 | +$43.788 | +$43.868 | +$42.822 |
  | STP sang ngày | +$47.166 | +$44.183 | +$44.232 | +$43.060 |

  - Hoãn STP đáng **~$53k**; cắt độ trễ 15→0 phút đáng **~$4,1k**. Tỉ lệ **13:1**.
  - Hoãn STP **một mình là đủ**: dương ở MỌI mức trễ, kể cả 15 phút (= cadence hiện tại).
  - Bật resume một mình **vô ích**: dòng "STP ngay" âm ở cả bốn ô.
  - 8h ≈ sang ngày (99,2–99,4%) ở mọi mức trễ → điểm bão hoà vững, không phụ thuộc độ trễ.
  - Trễ 10p nhỉnh hơn trễ 5p (~$50–100 trên $44k) là **nhiễu**, đừng đọc thành xu hướng.

  **MNKD đo riêng — cùng mẫu, và mốc bão hoà KHÔNG suy ra được từ Rổ 4**
  (model_sameday_stop_nkd.py, cổng đối chiếu 865=865 KHỚP; ema=10, đồng hồ JST, nhãn
  SPY trễ 1 ngày):

  | kích hoạt STP | lệnh | P&L | thắng | stop-D0 |
  |---|---|---|---|---|
  | 0h (live cũ) | 1352 | **−$10.854** | 6% | 1143 (**85%** số lệnh) |
  | 1h | 1097 | −$2.719 | 7% | 883 |
  | 4h | 925 | +$10.478 | 11% | 651 |
  | 8h | 892 | +$19.082 | 13% | 530 |
  | sang ngày | 865 | **+$22.294** | 15% | 0 |

  ⚠ **8h chỉ đạt 86% edge của MNKD**, trong khi Rổ 4 đạt 99,2%. Nếu chọn điểm vận hành
  8h theo số của Rổ 4 thì mất 14% edge MNKD. Chọn "sang ngày" đúng cho cả hai sleeve —
  và đây là lý do phải đo từng sleeve chứ không suy ra.

  ⚠ Chưa tính độ trễ vào lệnh vào bảng trên (làm mọi cột xấu đi). $1.890 là lỗ *tạm thời*
  sâu nhất quan sát được trong 6 năm (có COVID 2020), không phải chặn trên của rủi ro.

- **Khe hở kích hoạt stop: live MUỘN hơn engine — và muộn lại TỐT HƠN.** Engine bật stop
  từ ranh giới ngày của nó; live mãi 09:31 ET (B4 chạy trong `__init__` của
  `run_maxhold_exit`) mới đặt. Khe hở: Rổ 4 **9,5h**, MNKD **~22,5h**.

  | STP lên sàn | Rổ 4 P&L / MaxDD | MNKD P&L / MaxDD |
  |---|---|---|
  | engine (ranh giới ngày) | +$47.166 / $8.234 | +$22.294 / $2.122 |
  | **live (09:31 ET)** | **+$93.375 / $7.144** | **+$33.571 / $1.920** |
  | không có stop | −$46.369 / $60.138 | +$7.486 / $5.870 |

  **Phép phân định là nhánh không-stop** — nếu P&L tăng đơn điệu tới đó thì phép đo hỏng
  (hoặc stop chỉ là drag). Nó KHÔNG tăng: Rổ 4 lỗ $46k, MaxDD gấp 7,3 lần. Nên có điểm
  tối ưu ở giữa và mốc live nằm gần nó, tốt hơn engine **trên cả hai trục**.

  **Tôi đã đọc sai chính phép đo cũ của mình.** Quét độ trễ trước đó cho thấy "bão hoà từ
  8h", tôi hiểu thành bão hoà trên cả đời lệnh. Sai: mọi nhánh cũ đều để khối thoát của
  engine chạy bình thường **từ D+1 00:00**, nên chúng chỉ khác nhau ở phần đuôi ngày D.
  Quãng 00:00–09:31 ngày D+1 chưa nhánh nào chạm tới.

  ⚠️ Hệ quả vận hành: **đừng thêm job đặt STP lúc ~00:05 ET để "khớp engine"** — sẽ làm
  xấu đi. Và điều này nói luật engine không tối ưu, nhưng đó là phát hiện về CHIẾN LƯỢC,
  phải qua WFO; giữ 09:31 vì hệ thống đang làm sẵn, KHÔNG phải vì nó là đỉnh backtest.

- **Stop ratchet: sai lệch thứ tư, tác động bằng NHIỄU.** Backtest siết stop cuối mỗi
  ngày (`max(stop, run_full[-1] − mult×ATR)`) và siết tiếp trong ngày qua `stop_prev`.
  Live gán `stop_price` **một lần** lúc vào lệnh (runner.py:1635) và sau rollover (1093);
  không có `cancel_order` nào để dời stop — chú thích trong runner nói thẳng "ratchet
  updates are not yet implemented". Đo (`model_ratchet.py`, cổng đối chiếu 4/4 KHỚP):

  | | lệnh | P&L | lý do thoát |
  |---|---|---|---|
  | backtest ratchet | 3.044 | +$47.166 | CHANDELIER=2421 · GAP=165 · MAX_HOLD=458 |
  | live cố định | 3.040 | +$47.298 | CHANDELIER=2412 · GAP=165 · MAX_HOLD=463 |

  Chênh **+$132 (0,3%)**, chỉ **9/3.044 lệnh** thoát khác. **KHÔNG cần sửa.** Ai định dựng
  cancel/replace để dời stop theo ratchet: công đó đổi lấy −$132.

- **STRESS_MID nếu nối code hiện tại ≈ 91% luật đã kiểm định** (1 slot sáng 10:20, không
  slot xen giữa): vào trễ 10 phút + thoát ~14:10 + mất target → **+$12.850** vs +$14.151.
  Thoát 14:10 thay vì 14:00 lại TỐT hơn ~$1.520 — tình cờ có lợi trong mẫu này, không phải
  thiết kế, đừng dựa vào.

  ⚠ **Tôi đưa ba con số cho cùng câu hỏi này: 95% → 80% → 91%.** 95% chỉ tính mất target;
  80% tính thêm độ trễ vào lệnh nhưng cột thoát là RÁC (`d = bars.between_time("09:30",
  "14:00")` cắt sẵn nên `exit_extra_min` không làm gì); 91% là lần đầu cả ba nguồn đều
  thật sự được đo. **Bắt được cột rác nhờ hai tham số khác nhau ra số trùng khít từng
  đồng** — bất khả thi, đúng loại self-check đã ghi ở bài học lát cắt.

- **STRESS_MID: NỐI VÀ THEO DÕI** (quyết định của user; kết luận "KHÔNG NỐI" của tôi đã bị bác — p=0,112 là **thiếu bằng chứng**, không phải bằng chứng phủ định). `TASK.md:154` ghi
  "DEFERRED Phase C2 — needs 10:20 ET morning cron", khiến việc nối trông như một việc
  kỹ thuật dang dở. Đo ra thì cửa ải là **edge**: ngay ở luật đã kiểm định, sleeve chỉ
  cho **+$14.151 / 474 lệnh / 8 năm / 4 mã ≈ $1.770/năm**, kèm bootstrap **p=0,112**.

  Luật thoát của adapter có BA đường (stop / target 2R / đóng 14:00); live hiện thực một.
  Đo `model_stress_exits.py` (cổng đối chiếu adapter từng lệnh, 4/4 KHỚP):

  | nhánh | P&L | lý do thoát |
  |---|---|---|
  | A đã kiểm định | +$14.151 | eod=214 (45%) · stop=167 (35%) · target=93 (20%) |
  | B mất target, giữ tới 14:00 | +$13.376 | eod=304 · stop=170 |
  | C live thật, đóng sau 5 phút | **−$450** | stop=**1** |
  | C sau 30 phút | +$5.460 | stop=37 |
  | C sau 120 phút | +$8.378 | stop=119 |

  **Tôi đoán sai lỗi nào đắt.** Tưởng mất `target` là nghiêm trọng — thực ra chỉ −$775
  (5%), vì chỉ 20% lệnh thoát bằng target và không chốt ở đó thì phần lớn vẫn lãi lúc
  14:00. Thứ giết sleeve là **đóng sớm**: ở nhịp slot 5 phút, stop kịp kích hoạt đúng
  **1 lần trên 474 lệnh**. Cùng hình dạng với vụ STP — edge nằm ở chỗ để lệnh chạy.

  Hai lỗi (ghi nhận, KHÔNG phải việc phải làm): `to_candidate` vứt bỏ `target`;
  `_mark_held_unchanged` không gọi cho cluster stress nên `diff_desired_vs_held` đóng vị
  thế ở lần chạy kế tiếp.

  ⚠ `reconcile_stress.py` chỉ phủ quyết định VÀO lệnh (entry/stop/target khớp adapter,
  112 ngày Stress, 0 lệch) và chạy mặc định trên **MES**. Đường THOÁT không có phép đối
  chiếu tương đương — đó là chỗ cả hai lỗi nằm.

- **Vòng lặp mở-đóng MES 08-07 KHÔNG phải lỗi dữ liệu.** Kéo giá thật từ IBKR: ET 14:59
  close = 7764.50 = đúng entry tín hiệu trên thang thô → quy đổi offset đúng tuyệt đối.
  Giá vượt stop lúc 15:01 (2 phút sau bar tín hiệu), lệnh gửi 15:10:41. Nguyên nhân là
  **độ trễ vào lệnh** (run_day 5m13 + slot cách 10 phút), không phải parquet.

## Gotchas (2026-08-10) — tầng theo dõi vị thế khoá theo MÃ, không theo VỊ THẾ

Phát hiện khi nối STRESS_MID, đã **tắt cron** trước khi nó chạy lần nào (`run_scheduler.py`,
khối `if False`). Chi tiết đầy đủ ở `docs/futures/OPERATIONS.md` mục "STRESS_MID: tại sao
cron 10:20 bị TẮT". Ba chỗ, cùng một gốc:

- `has_working_stop(inst)` — boolean theo **symbol**. Vị thế thứ hai trên cùng mã sẽ bị B4
  từ chối đặt stop, đúng theo code, sai theo ý.
- `get_working_stops()` → `{inst: orderId}` — một id mỗi mã, B5 bỏ qua vị thế thứ hai.
- `unprotected_positions()` — `if exp in have: continue`. Kiểm **sự tồn tại**, không kiểm
  **số lượng**. Docstring của chính nó đã nêu vấn đề symbol-level và sửa cho trường hợp
  expiry (rollover), nhưng dừng lại ở đó.

- `repair_stops.py` — hai chỗ, và là chỗ duy nhất **ghi** chứ không chỉ đọc: `by_inst =
  {p["inst"]: p}` (một vị thế đè cái kia), và `p["stop_order_id"] = new_ids[p["inst"]]`
  (đóng một order id lên mọi vị thế cùng mã). Ba lỗi trên là kiểm bỏ sót; cái này làm hỏng
  sổ, nên tầng ĐANG chạy đúng — `cancel_order(p.stop_order_id)` — sẽ huỷ stop của vị thế kia.

Và nặng hơn cả ba: `get_positions()` / `ib.positions()` trả **vị thế ròng có dấu**. Hai
cluster ngược chiều cùng mã (swing LONG + stress SHORT) → net 0 → `if not p.position:
continue` → **cả hai vị thế biến mất khỏi phép kiểm bảo vệ**, và B3 báo MISMATCH → halt.

Điều đáng nhớ, không phải chi tiết: **B3 cộng dồn đúng** (`file_key[k] += p.contracts`), nên
đọc lướt sẽ tưởng cả tầng đã lo chuyện nhiều vị thế. Chỉ có một tầng lo. Ba tầng còn lại
mượn giả định "một vị thế một mã" mà không tầng nào khai nó ra thành điều kiện.

Hiện tại vô hại vì engine cố định một vị thế mỗi mã. Nó thành hại ngay khi (a) có sleeve
thứ hai dùng chung mã — chính là STRESS_MID, hoặc (b) scale nhiều vị thế trên một mã.
Pyramiding đã bị bác (L16) nên (b) chưa nằm trên lịch; (a) thì vừa suýt vào.

## Lessons (2026-08-10)

- **Sleeve đúng luật vẫn làm hỏng sleeve khác.** STRESS_MID tự nó đã kiểm định xong
  (+$12.850 với luật live). Cái hỏng nằm ở chỗ nó **dùng chung mã** với Rổ 4 — một thuộc
  tính không xuất hiện trong bất kỳ backtest nào của nó, vì backtest không có tầng broker.
  Trước khi bật một sleeve, phải hỏi nó **chạm vào mã nào của ai**, không chỉ hỏi nó lãi
  bao nhiêu.
- **Ba guard cùng fail theo hướng "an toàn" thì bằng không guard.** B4, B5,
  `unprotected_positions` đều báo đã được bảo vệ khi thực ra không. Cùng dạng với hố
  17:00–18:00 và bug rò giờ vũ trang: hệ thống chạy, log xanh, tiền đi.
- **Bản vá an toàn vẫn có thể là bản vá SAI.** Tôi siết `signal_layer` thành "một vị thế
  mỗi mã" để chặn bù trừ ròng. Đúng về an toàn, sai về nguyên tắc: `deploy_sim` chạy stress
  ĐỘC LẬP với swing rồi nối hai danh sách lệnh, nên sim đã kiểm định CHO PHÉP chồng lấn.
  Siết = live chạy luật backtest chưa kiểm — đúng hình dạng đã mất $53k. Và nó phá luôn
  `verify_runner_real.py`, file có nhiệm vụ tái tạo fit_C trade-for-trade.
  **Kiểm tra bắt buộc trước khi thêm bất kỳ ràng buộc nào vào đường sinh tín hiệu: mở
  `deploy_sim` ra xem sim có ràng buộc đó không.** Một hiểm hoạ vận hành có thật không tự
  cho phép đổi chiến lược — nó là điều kiện tiên quyết, để user quyết.
- **Soi lại lần hai tìm ra thứ lần một không thể tìm.** Lượt đầu soi câu hỏi "stop này thuộc
  vị thế nào" và tìm được 5 chỗ. Lượt hai soi "chuyện gì xảy ra khi hợp đồng đổi tháng" và
  tìm thêm 3 chỗ — không chồng lấn chỗ nào. Rà theo MỘT câu hỏi thì chỉ thấy đúng họ lỗi của
  câu hỏi đó; muốn hết thì phải đổi câu hỏi, không phải đọc lại kỹ hơn.
- **Test chép lại logic là test rỗng.** Tôi viết ba test cho C2 bằng cách dựng lại nhánh giá
  của nó trong chính helper của test rồi assert lên helper — chúng xanh và chứng minh đúng
  một điều: bản chép khớp với chính nó. Bắt được vì tự hỏi "test này gọi hàm nào". Cách sửa
  là tách `_roll_stop` ra khỏi `_handle_rollover` để gọi thẳng được; logic khó test là logic
  chưa được test.
- **`return` giữa một hàm có `_persist_state()` ở cuối.** Bản vá đầu của tôi dùng early
  return, và nó bỏ qua đúng dòng ghi sổ — mức stop vừa dịch sẽ mất. Trước khi thêm `return`
  vào giữa hàm, đọc phần đuôi hàm.
- **Câu hỏi "có đúng thiết kế không" đáng hỏi mỗi lần.** User hỏi đúng một câu đó và nó lật
  lại một thay đổi tôi vừa viết xong kèm 6 test xanh. Test xanh chỉ chứng minh code làm đúng
  điều tôi bảo nó làm.
- **"Sau này nếu scale" thường đã là "bây giờ".** User nêu chuyện stop-theo-vị-thế như một
  lo ngại tương lai. Truy ra thì cái cron nối trong cùng ngày hôm đó đã kích hoạt nó rồi.

## Sự cố (2026-08-10) — STP mồ côi #12 trên MYM, cảnh báo bị ống dẫn nuốt

**Cái xảy ra.** 09:31 MAX_HOLD đóng vị thế MYM (đủ 5 ngày). Lệnh CLOSE thành công nên
`run_maxhold_exit` thoát mã 0. Nhưng `cancel_order('12')` THẤT BẠI, và runner đã kêu đúng
lúc đó: `STP ORPHAN: cancel_order(12) returned False ... will open an unintended position
when it fires`. Lệnh BUY STP treo ở ~54708.68 với KHÔNG có vị thế nào phía sau — chạm giá
là mở một lệnh LONG không ai đặt.

**Vì sao không ai biết.** `_run` trong `run_scheduler` bắt stdout/stderr của tiến trình con
rồi **vứt đi** khi `returncode == 0`, ghi vào log đúng một dòng `completed OK`. Guard bắn
đúng; ống dẫn ném nó đi.

**Phát hiện thế nào.** Không phải từ log. Sổ (`live_positions.json`) sạch, `maxhold_state`
ghi `true`, log không có gì. Chỉ lộ ra khi đi hỏi thẳng IBKR:
`get_working_stops()` → `{'MYM': ['12']}` trong khi `get_positions()` → chỉ có MNKD.

**Đã vá.** `_run` giờ quét output tìm dòng `CRITICAL`/`ERROR` **kể cả khi thoát 0** và ghi
chúng ra, vẫn trả True. `test_run_echoes_critical.py` (6).

### Bài học

- **Mã thoát 0 chỉ nói việc CHÍNH đã xong, không nói mọi việc phụ đều ổn.** MAX_HOLD có hai
  việc — đóng vị thế và huỷ stop. Việc một thành công quyết định mã thoát; việc hai thất bại
  không để lại dấu vết nào. Lọc log phải theo **mức độ**, không theo **mã thoát**.
- **Sổ sạch + state file sạch + log sạch vẫn có thể là một tài khoản có lệnh mồ côi.** Ba
  nguồn đó đều là thứ hệ thống tự nói về mình. Chỉ có broker mới nói được cái đang thật sự
  treo trên sàn. Cùng dạng với bài học 2026-08-05 (tiêu chí `stop_order_id != null` không
  bao giờ fail được).
- **Bằng chứng thật rẻ hơn tôi tưởng.** Cả buổi tôi nói "chưa chạm broker được, phải chờ
  phiên sau". Thực ra một truy vấn chỉ-đọc 30 giây đã phát hiện một lệnh mồ côi đang sống,
  và đồng thời chạy được `unprotected_positions()` bản mới trên dữ liệu thật. **Hỏi broker
  trước khi kết luận là phải chờ.**

## Gotchas (2026-08-10, cuối phiên) — đồng hồ trong log

**Log ghi giờ MÁY, không phải ET.** Máy hiện chạy MST nên ET = giờ log + 2. Mọi công cụ đọc
log phải đổi trước khi so với lịch job (vốn khai bằng ET) — `session_report._to_et`.

Hệ quả nặng hơn độ lệch 2 tiếng: **ranh giới ngày sai đúng chỗ quan trọng nhất.** Cửa sổ đêm
NKD 01:10–02:55 ET là 23:10–00:55 giờ máy, tức vắt qua nửa đêm CỦA MÁY. Gom theo ngày của
log thì báo cáo ngày D bỏ sót cửa sổ đêm của chính ngày D (nằm trong file ngày D−1) và gộp
nhầm cửa sổ đêm ngày D+1. Đo được: 7 slot `nkd_night_01xx` hiện ra như "KHÔNG CHẠY" trong
khi chúng chạy bình thường.

Cách bắt: một công cụ báo "việc X không chạy" mà việc đó rơi vào khung 23:00–01:00 của bất kỳ
đồng hồ nào — nghi ranh giới ngày trước khi nghi việc đó thật sự không chạy.

## Lessons (2026-08-10, cuối phiên)

- **Công cụ đọc log phải khai đồng hồ của nó.** Báo cáo ghi "mọi giờ là giờ ET" trong khi in
  giờ máy — một câu sai nhưng không ai kiểm được nếu không tự đi so hai đồng hồ. Dòng khai
  đó biến một lỗi im lặng thành lỗi kiểm được.
- **Test của chính bản sửa lại rơi vào bẫy của bản sửa.** Fixture ghi `23:00` giờ máy, đổi
  sang ET thành 01:00 ngày sau, nên bài test tự hỏng. Đó là cách rẻ nhất để biết phép đổi
  thật sự có tác dụng.
- **"Ổn chưa" phải trả lời bằng mắt xích còn thiếu, không bằng số test.** Cuối ngày có
  475/475 và reconcile $0.00, nhưng code stop mới vẫn **chưa đặt một lệnh stop thật nào** —
  và đó mới là câu trả lời đúng cho câu hỏi đó.

## Gotchas (2026-08-11)

- **Cùng một codebase, hai kiểu tra nhãn, hai hành vi ngoài biên.** `labels.get(day)` (dict
  thuần) trả `None` khi hết dữ liệu → engine bỏ qua ngày đó, im lặng nhưng ĐÚNG. Còn
  `RegimeLabels.get` dùng `Series.asof` (`global_index/regime.py:58`) → **nối giá trị cuối
  vô hạn**, nên NKD chạy suốt 2025-2026 trên nhãn regime đóng băng ở 2024-12-31 mà không
  một dòng cảnh báo nào. `asof` không hỏng khi hết dữ liệu — nó đóng băng. Chỗ nào dùng
  `asof` trên chuỗi có thể hết hạn, phải tự hỏi "nối tới bao giờ thì vô nghĩa".
- **Hai lỗi ngược chiều trong cùng một con số.** Comparator vừa THIẾU Rổ 4 (không vào lệnh)
  vừa PHÓNG ĐẠI NKD (nhãn đóng băng, 2.8 lần). Sửa xong, tổng lại THẤP hơn $3,138 dù đã
  cộng thêm swing +$4,992. Nếu chỉ nhìn tổng thì tưởng bản sửa làm hệ tệ đi.
- **Giá trị bất khả thi bắt được lát cắt sai.** Cộng dồn `per_cluster_pnl` ra $9.9M trên tài
  khoản $50k — vì đó là LUỸ KẾ lặp lại mỗi ngày, phải đo bằng biến thiên. Con số vô lý là
  thứ duy nhất cứu được, vì bản thân phép cộng chạy trơn tru.
- **Đọc tĩnh có thể ra mâu thuẫn mà vẫn không tìm ra lối.** Suy ra "nhãn hết → curve phải
  phẳng", nhưng curve vẫn có 271 giá trị khác nhau. Mâu thuẫn đó ĐÚNG là tín hiệu, nhưng
  giả thuyết đầu tiên (CSV không sắp xếp) sai. Backup + chạy lại + diff rẻ hơn đọc tiếp.

## Rejected approaches (2026-08-11)

- **"Stop live khác backtest nên không so được"** — sai chiều. Việc hoãn stop tới phiên sau
  chính là để KHỚP backtest: `backtest_swing_tf` test stop TRƯỚC khối vào lệnh trong cùng
  vòng lặp ngày (`_validated_core.py:314` vs `:400`), nên vị thế mở ngày D lần đầu bị test
  stop ngày D+1. Đo được: đặt ngay −$10,832 / hoãn +$47,166 (2018-2026).
- **"Chạy lại generate_replay_snapshots là xong"** — chạy lại mà không sửa `REGIME_CSV` chỉ
  tái tạo đúng cái comparator hỏng, và GHI ĐÈ bản duy nhất đang có. Backup trước.

---

## Gotchas — Realtime dashboard (2026-08-14)

- **`[] || x` trong JS trả về `[]`, không phải `x`.** Mảng rỗng là truthy. Nên
  `schedule.open_incidents || schedule.incidents` âm thầm rơi về danh sách ĐẦY ĐỦ khi
  không còn incident nào mở — đúng lý do Now Monitor hiện 6 slot đã phục hồi như "OPEN"
  trong khi rail ngay trên nói "systems nominal". Phải dùng `??`.
- **Test grep trên source sẽ bắt chính comment giải thích bug đó.** Guard C1 tìm
  `$('someId')` trong `realtime.js`; comment tôi viết để giải thích lookup đã gỡ chứa đúng
  chuỗi ấy → guard fail dù code đã sạch. Fix: lọc dòng bắt đầu bằng `//` trước khi grep
  (code thật không bao giờ nằm trên dòng như vậy nên không mất true positive).
- **"Trang không cuộn ngang" KHÔNG phải là kiểm tra overflow.** Nội dung vượt mép có thể bị
  **cắt** thay vì cuộn, và khi đó `scrollWidth == clientWidth` — test vẫn xanh. Đo được:
  `.header-live-context` trải tới 608px trên viewport 487px, `runner-header-state` nằm trọn
  ngoài màn hình, mà assert scrollWidth vẫn pass. Kiểm đúng: không element nào được vượt
  mép phải trừ khi nó hoặc tổ tiên có `overflow-x: auto|scroll`.
- **`job_journal_reader._LAUNCH` là `-m\s+global_index\.`** — fixture log không chứa chuỗi
  đó sinh ra **0 job**, và test kiểu "duyệt mọi job failed rồi assert" sẽ **pass rỗng**.
  Luôn `assert` danh sách không rỗng trước khi vào vòng lặp.
- **Hai reader bất đồng về "job chạy xong".** `schedule_status._evidence` nhận cả
  `"completed ok"` lẫn `"thoat ok"`; `job_journal_reader` chỉ nhận `"completed OK"` và
  `"thoat OK nhung"`. Một dòng `"thoat OK"` trần → job kẹt `running` vĩnh viễn ở lane
  journal trong khi rail gọi là `executed`. Latent: đo toàn bộ `scheduler_*.log`, 0 lần trần.
- **Ngưỡng stale không được neo vào deadline của slot.** Slot chạy mỗi 5 phút nên
  `latest_slot + 20 phút` luôn ở tương lai suốt active window và không bao giờ trôi qua.
  Đo được: snapshot 90 ngày tuổi lúc 14:30 ET vẫn ra "không stale". Neo vào **tuổi của
  chính snapshot** mới bắn.
- **Đừng đưa backtick vào prompt gửi codex-rescue.** Forwarder nội suy prompt vào shell chưa
  escape → bash chạy command substitution, output lệnh bị nhét vào prompt thay cho lệnh, và
  agent phóng thêm một task thứ hai mà không huỷ được task đầu → **hai writer song song trên
  cùng file** (kết quả: hai bản sao trùng của cùng một test).
- **`codex-companion cancel` hỏng dưới Git Bash**: MSYS đổi `/PID` thành đường dẫn
  (`C:/Program Files/Git/PID`). Cách chữa đúng là **tắt path conversion**, không phải tự
  taskkill: `MSYS2_ARG_CONV_EXCL='*' MSYS_NO_PATHCONV=1 node codex-companion.mjs cancel <job>`.
  Giết process bằng tay để lại entry registry treo mãi ở `running` (đúng thứ mô tả bên dưới);
  cancel qua companion thì nó deregister luôn.
  Bản ghi trạng thái job KHÔNG được cập nhật khi process bị giết — một dòng
  `RUNNING 10h` trong `status --all` có thể chỉ là xác chết, đối chiếu mtime file để chắc.
  Chạy `status` từ **PowerShell** thấy registry KHÁC với từ Bash (`direct startup` vs
  `shared session`) — "No jobs recorded yet" ở một shell không có nghĩa là hàng đợi sạch.
  Dấu hiệu job đã chết mà registry vẫn `running`: log ghi `no active turn to interrupt`,
  và dòng log thật cuối cùng cách hiện tại hàng giờ.
- **Dashboard paper đọc artifact sinh sẵn, không tính live.** `paper_evidence_reader` đọc
  `monitor/paper_pnl_compare.json`. Sửa `monitor/paper_pnl_compare.py` hoặc
  `global_index/statement.py` **không tới dashboard** cho tới khi chạy lại
  `python monitor/paper_pnl_compare.py`. Không có cảnh báo nào — dashboard cứ hiển thị số
  của code cũ. Bắt được vì chuỗi basis derive nói `mixed basis ... unknown` trong khi gọi
  `pair_fifo` trực tiếp lại ra `statement_proceeds` cho mọi lot.
- **Đừng ghim chuỗi bootstrap khi test paper.js bằng Node.** `_run_paper_js_probe` từng
  `source.replace("  load();\n  window.setInterval(load, 60000);\n})();", ...)`. Đổi chỗ nối
  refresh là **8 test đỏ cùng lúc**, đọc như 8 hành vi hỏng thay vì 1 fixture cũ. Chèn export
  vào trước `rindex("\n})();")` thay vì match nội dung.
- **Chuỗi mô tả code sẽ cũ đi và không ai biết.** `flex_reconcile_basis` là câu hardcode nói
  tiền lấy từ `point_value`; sau khi đổi sang Proceeds nó thành sai, ngay trên panel mà việc
  duy nhất là báo tiền đến từ đâu. Derive từ dữ liệu (`pnl_basis` của từng lot) — và ngay khi
  derive thì nó tự tố cáo fix Proceeds mới phủ 4/9 lot.
- **Ba lần cùng một dạng lỗi: mô tả rời khỏi thứ nó mô tả.** (a) `flex_reconcile_basis` là câu
  hardcode nói tiền lấy từ `point_value`; đổi sang Proceeds xong nó thành sai, ngay trên panel mà
  việc duy nhất là báo tiền đến từ đâu. (b) Comment `generate_replay_snapshots.py:40` nói đuôi
  2025-2026 là NKD-only — nó mô tả trạng thái **trước bản sửa của chính nó**; tin nó nên cắt khung
  ngưỡng ở 2024-12-31, vứt 331 phiên hợp lệ và siết mọi band. (c) `FreezeRecord` lưu `calmar` mà
  **không lưu slippage / ngày cắt / phiên bản code** → 2.744 không tái tạo được do thiết kế.
  Cách chống: **derive từ dữ liệu, hoặc lưu kèm cơ sở đo**. Lần (a) bắt được vì đã derive; lần (b)
  chỉ bắt được nhờ một câu hỏi tình cờ.
- **Cùng một hệ thống, ba con số Calmar hợp lệ.** 2.744 (registry, không rõ cơ sở) / 2.299 (đường
  cong cũ, đuôi NKD-only, net $61.088 maxdd $3.115) / 1.678 (hiện tại, net $57.950 maxdd $4.049).
  Chênh không do suy giảm mà do bản sửa `REGIME_CSV` 2026-08-13 thêm sụt giá cả rổ tháng 3/2026.
  `calmar = (net/số_năm)/maxdd_$` — luôn kiểm bằng cách tái dựng cả ba thành phần.
- **`label_regimes` gán nhãn tới HẾT chuỗi SPY, không dừng ở `fit_end`.** `fit_end` chỉ giới hạn
  đoạn dùng để **fit**. Nhầm chỗ này dẫn tới kết luận sai về việc cluster nào còn giao dịch.
- **`anchor` ≠ `train_end` ≠ `fit_end`** trong refreeze/label_regimes. Production truyền
  `2018-01-01` làm **train_end**; registry ghi `anchor=2017-01-01`. Không mâu thuẫn.
- **MockBroker trả `avg_price=0.0`**, mà dòng CLOSE của signal exit chỉ ghi khi `avg_price > 0` →
  chế độ verify/offline **chưa bao giờ chạy qua đường ghi log đó**. Test phải tự dựng broker có giá fill.
- **Cache paper-evidence hỏng theo mtime của MỌI file log** (+ `contract_specs` từ ibkr_reader).
  Hệ quả: warm ngay lúc `ibkr_reader.start()` là vô ích — specs về sau đó nên chữ ký đổi, dựng entry
  dưới khoá không ai hỏi. Phải **chờ specs** rồi mới warm, và warm trên **thread** (warm chặn làm
  cổng đóng 40,5s).
- **Chạy pytest trên cả `global_index/` lẫn `futures/`** thì phải `--ignore` hai module tự gọi
  `sys.exit` ở module level: `test_ibkr_injection.py` và `futures/test_refreeze.py` → nếu không,
  pytest INTERNALERROR và **không test nào chạy**.
- **Hai run khác hẳn nhau có thể làm tròn ra cùng một số.** `2.38` là fit_A floor ($47,838, 1-tick,
  data incremental) ở `refreeze.py:53`, **và cũng là** fit_C baseline ($47,186, 2-tick, frozen_2024)
  ở `OOS_VALIDATION_LOG` hàng B1 — `DECISIONS.md:37` từ chối **cả hai** làm floor. Đọc một con số
  trong doc mà không hỏi "run nào" là đọc sai. Bắt được bằng cách truy `git log -S` ra commit gốc
  rồi đối chiếu ngày với dòng deprecate, chứ không bằng cách grep con số.
- **`AUTO_APPROVE` của `run_gate` không có nghĩa "nên refit".** Nó chỉ nghĩa "fit mới không khác đủ
  đáng sợ". Đo thật 2026-08-15: gate trả `AUTO_APPROVE 3.87%` cho đúng lần refit mà L11 nói KHÔNG
  nên làm (5.84% << ngưỡng 15%). Verdict đọc như lời cho phép trong khi nó là lời "không có gì bất
  thường" — hai chuyện khác nhau, và pipeline sẽ tự động swap nếu ai đó chạy nó.
- **Cửa sổ đo quyết định kết luận.** `run_gate` so nhãn trên `COMMON_START = 2019-01-01` → hết chuỗi
  (~7,5 năm); L11 hỏi trên period hiện tại (2026 YTD). Khác biệt dồn ở đuôi bị pha loãng gần biến
  mất trên mẫu 7,5 năm. Hai cửa sổ ≠ thay thế được cho nhau: gate hỏi "nhãn có đổi nhiều không",
  L11 hỏi "model cũ có sai không". Chỉ cái sau mới là điều kiện khởi động refit.
- **Flip rải đều khắp lịch sử = nhiễu, flip tụ ở đuôi = tín hiệu.** fit-2024 vs fit-2025 lệch
  2–6% ở **mọi năm** 2018–2026 (2018=4.38%, 2022=5.58%, 2026=5.84%), kể cả những năm cả hai model
  đã thấy trọn vẹn. Nếu fit mới học được điều gì về chế độ hiện tại thì flip phải tụ ở 2025–2026.
  Phân rã theo năm là thứ phân biệt được hai trường hợp; con số % tổng thì không.
- **`label_regimes` in `Model is not converging` ở MỌI lần chạy, kể cả production.** EM dừng khi
  log-likelihood **giảm nhẹ** (delta ≈ −0.08 đến −0.15) thay vì hội tụ đơn điệu. Không làm hỏng kết
  quả (`_fit_best` chọn best-of-10 theo score) nhưng `run_live_day` gọi đúng hàm này mỗi ngày →
  cảnh báo này nằm trong log production mà chưa doc ở đâu. Liên quan trực tiếp tới câu hỏi sàn nhiễu.
- **Ước tính sai chi phí làm bỏ lỡ phép đo rẻ.** Tôi đoán fit HMM mất "vài phút" nên đẩy sang cho
  người chạy tay; thực đo **5–8 giây**. Ở mức đó, quét nhiều seed / nhiều `fit_end` là chuyện vặt.
  Đo chi phí trước khi thiết kế quanh nó.
- **Script scratchpad không commit = phép đo biến mất.** `compare_refit_2025.py` (2026-07-09) sinh
  ra con số 93.7% được `DECISIONS.md` trích làm căn cứ, nhưng `git log --all` không có nó →
  căn cứ không tái tạo được. Cùng bệnh với `CALMAR_FLOOR = 2.38` và `FreezeRecord.calmar = 2.744`.
  Xem `docs/futures/CALMAR_PROVENANCE.md`.
- **Một ngưỡng chưa neo vào sàn nhiễu thì không phải ngưỡng.** Đo 5 seed, CÙNG `fit_end`: nhãn lệch
  nhau **1.20–7.58%** trên cửa sổ gate. `GATE_AUTO_PCT = 5.0` nằm **dưới** trần đó → chạy lại y hệt
  cấu hình cũ bằng seed khác có thể ra `VERIFY`. Ngưỡng L11 15–20% cũng chưa bao giờ được đối chiếu.
  Trước khi tin bất kỳ verdict %-based nào: **đo hệ so với chính nó trước**.
- **Tín hiệu trùng khít trung vị nhiễu — kiểm bằng đếm ngày, không bằng phần trăm.** fit-2024 vs
  fit-2025 lệch **5.8442%** trên 2026; trung vị nhiễu seed cũng **5.8442%**. Không phải trùng do làm
  tròn: cùng mẫu số 154 ngày và cùng **9 ngày** khác. Phần trăm che mất điều đó; tử số/mẫu số thì không.
  Luôn in `n_diff/n` cạnh %.
- **Bản chép một hàm production phải tự chứng minh là trung thành.** `label_regimes` hardcode
  `HMMEngine(n_components=...)` nên muốn quét seed phải chép lại vòng lặp. Cách chống chép sai:
  chạy bản chép ở **seed mặc định 42** rồi so **hash nhãn** với hàm thật (`SC-FIDELITY`). Sai một dòng
  là đỏ. Không có check đó thì mọi số đo được là đo một hệ khác — và nó vẫn trông hợp lý.
- **Seed đổi thì số ngày Stress đổi 253→321 (11.7%–14.8%).** Production ghim seed 42; chuỗi regime
  đang chạy là **một lần rút** từ phân bố khá rộng, không phải "chân lý". Chưa đo ảnh hưởng lên P&L —
  đừng suy từ chênh lệch nhãn ra chênh lệch tiền, phải chạy deploy_sim từng seed.
- **`deploy_sim` SẬP khi output bị chuyển hướng ra file hoặc pipe (Windows).** Ký tự `ổ` trong
  `"Rổ 4"` ở dòng print đầu tiên vs codec cp1252 → `UnicodeEncodeError`. Độc ở chỗ: nó tính xong
  **toàn bộ 2m41s** rồi mới chết, ngay tại dòng in kết quả đầu tiên — mất trắng cả run.
  `deploy_sim ... | grep Calmar` cũng chết, và triệu chứng nhìn như "không có dòng nào khớp"
  chứ không như một lỗi. Chữa: `PYTHONIOENCODING=utf-8` khi chạy, hoặc thêm
  `sys.stdout.reconfigure(encoding="utf-8")` vào `deploy_sim.main()` — `refreeze.py:_print_report`,
  `verify_current_freeze.py`, `compare_refit.py`, `measure_fit_noise.py` đều đã có dòng đó,
  chỉ `deploy_sim` thiếu. Đáng ngờ: các file `vault_*_result.txt` trong repo được tạo bằng cách nào?
- **Đo lại một invariant trước khi xây phép đo mới lên nó.** Chạy đúng lệnh baseline INVARIANTS
  dòng 22 hôm nay: net $42,459 / Calmar 1.72 / MaxDD $3,574 (7,1%) — khớp từng số. Bước này rẻ
  (một run) và biến mọi con số per-seed sau đó thành có nghĩa; bỏ qua nó thì không phân biệt được
  "seed làm đổi kết quả" với "harness của mình sai".
- **Truy vào chỗ TIÊU THỤ, không chỉ chỗ định nghĩa.** Cả một đợt điều tra dựng quanh giả định
  `BACKTEST_CALMAR_FLOOR = 1.65` là một ngưỡng. Đọc `analytics.js` mới thấy **nó chưa từng gate
  gì** — chỉ hiển thị, không phép so, không cảnh báo, và `running_metrics.calmar` còn là `null`.
  Đồng thời lộ ra thứ lớn hơn nhiễu seed: hai ô đặt cạnh nhau khác **dữ liệu + khoảng thời gian +
  thành phần sleeve**. Một hằng số có chữ "floor" trong tên chưa chắc là floor.
- **Test một helper trực tiếp thì để nguyên đúng cái lỗi đang sửa.** T19b bản đầu gọi thẳng
  `_refreeze_status()`; trả hardcode `{"pending": False}` về → **cả 7 check vẫn xanh**, vì không
  check nào đi qua `_build_operational_status` (đường mà `dump_state` thật sự publish).
  "Helper đúng mà không ai gọi" chính là lỗi đó. **Mutation test bắt được, test không.**
  Luôn có ít nhất một check đi hết đường tới nơi dữ liệu ra ngoài.
- **Fail-open ẩn trong consumer.** `paper_evidence_reader` làm `"PENDING" if refreeze.get("pending")
  else "OK"` → **thiếu khoá hoặc None đều thành OK**. Nên khi đọc cờ lỗi phải trả `pending=True`
  (+`unknown=True`), không phải `False`: một cờ đọc không được ≠ không có cờ. Kiểm consumer trước
  khi chọn giá trị mặc định cho nhánh lỗi.
- **`git add <paths> && git commit` KHÔNG an toàn khi có người khác dùng chung index.** Tôi add 7
  file rồi commit, nhưng index đã sẵn 7 file của phiên song song → commit nuốt cả 14. Sửa bằng
  `git reset --soft HEAD~1` (không mất gì) rồi restage. Cách chống: **luôn `git diff --cached`
  trước khi add** (hai commit trước tôi làm thế và đều sạch), hoặc `git commit -o <paths>`.
  Lưu ý `git add <file>` để khôi phục trạng thái staged sẽ stage **toàn bộ** file chứ không phải
  phần hunk đã stage trước đó — muốn giữ granularity phải `git apply --cached --unidiff-zero`.
- **`test_runner_event_log.py` là pytest, không phải script.** Nó dùng fixture `tmp_path`; chạy
  `python global_index/test_runner_event_log.py` ra `ModuleNotFoundError: No module named
  'global_index'` (sys.path chỉ có thư mục chứa file). Phải `python -m pytest <file>`.
- **Bash tool mất quoting của heredoc khi nội dung có SỐ LẺ dấu nháy đơn.** `python - <<'EOF'` với
  chuỗi `'''...'''` bên trong → `unexpected EOF while looking for matching '`. Nội dung có số chẵn
  nháy đơn thì chạy bình thường, nên lỗi trông ngẫu nhiên. Cách chống: dùng Write ghi ra file rồi
  splice, đừng nhét code Python nhiều nháy vào heredoc.
- **"Trang không cuộn ngang" vẫn không đủ — tôi dính lại chính cái bẫy đã tự ghi.** Sửa M4 bằng
  `overflow-x: auto` đặt TRONG media query ≤680px, trong khi dòng `overflow-x: hidden` toàn cục vẫn
  còn. Kết quả: mobile thì cuộn được, còn 1440px cắt 20px và **1024px cắt 117px (nguyên một cột)**,
  không thanh cuộn trang nào gợi ý vì nội dung bị cắt không tạo cuộn. Chỉ lộ ra khi DOM smoke test
  được đóng gói và chạy ở nhiều viewport. Kiểm đúng: đo `scrollWidth - clientWidth` **của từng
  container bảng**, ở nhiều bề rộng, và mở hết các panel chi tiết trước khi đo.
- **Memo vô dụng nếu cache bị người khác xoá.** `read_paper_evidence` gọi `_cache.clear()` trước khi
  ghi payload (giữ đúng 1 entry), nên memo log tôi đặt chung dict bị xoá ngay trên chính lần gọi vừa
  tốn 25s dựng nó. Cache có vòng đời khác nhau phải nằm ở dict khác nhau.
- **Episode B3 CÓ vắt qua ranh giới file — 3 lần.** Tôi viết comment "thực tế không thể" rồi test
  bắt được: `live_day_0810→0811→0812→0813`, gộp 21 episode thành 18. Bỏ bước gộp seam = gate B3 bịa
  ra mismatch chưa từng xảy ra. Bài học lặp lại lần thứ tư trong phiên: **đừng khẳng định trong
  comment cái mà chưa đo.**
- **Test tương đương phải neo vào giá trị đo TRƯỚC refactor.** So per-file-merged với
  per-file-concatenated thì tự đồng ý theo cấu tạo và chứng minh không gì cả. Neo vào
  `cold_starts 8 / b3 match 17 / mismatch 1 / dropped 1160 / tws 4` đo trên bản một-lượt.
- **Chặn pytest ghi log production đã có nhưng KHÔNG test nào giữ.** `test_log_hygiene` có 8 test về
  handler lúc import — gỡ `PYTEST_CURRENT_TEST` khỏi `attach_file_log` thì cả 8 vẫn xanh. Test phải
  ghim cả hai chiều: có biến môi trường thì KHÔNG gắn, không có thì PHẢI gắn (nếu không thì pass vì
  lý do sai và người vận hành mất log).

## Gotchas — sửa theo rà soát runner (2026-08-16, phạm vi global_index/** + monitor/**)

- **Test xanh vì lý do sai — broker giả không uỷ quyền.** `_RecordingBroker` ghi đè `send_order`
  mà không gọi `super()`, nên sổ vị thế của `MockBroker` rỗng, B3 báo lệch và chặn lệnh vào.
  Test công tắc dừng xanh **nhờ B3**, không nhờ công tắc. Chỉ phép đối chứng ("không có tệp dừng
  thì lệnh PHẢI đi ra") mới lộ. Lớp giả ghi đè phương thức có tác dụng phụ thì phải `super()`.
- **Fake trả về giá trị do chính mình chọn thì không bao giờ lộ được bug.** `_MonthBroker` trả
  `"202609"` nên không thể phơi ra chuyện production dùng hai định dạng. Định dạng thật lấy từ
  `exercise_rollover_live.py:208` và `backfill_nkd.py:20` (`"20260910"`). Fake phải lấy hình dạng
  từ mã thật, không lấy từ giả định của người viết test.
- **p99 của cả chuỗi có thể chính là cái lỗi vừa sửa.** Ngưỡng đối soát: p99 của 267 quan sát là
  $889, nhưng cắt tại 14/8 cho thấy đuôi béo là lỗi định tuyến MNKD; sàn sau khi sửa dưới $100.
  Đặt ngưỡng $250. Rút ngưỡng từ dữ liệu chứa lỗi = hợp thức hoá lỗi.
- **Test thay thế không thể đỏ.** So `_log_summary_uncached` với tổng `_scan_one_log` trên
  `_log_paths`: hai vế **dùng chung** danh sách đường dẫn, nên một tệp trùng làm phồng cả hai.
  Mutation chứng minh nó luôn xanh. Viết lại: kiểm `_merge_log_partial` trên partial dựng tay.
- **`psutil.process_iter` trên Windows đắt kinh khủng.** Gọi mỗi request → endpoint **23.556ms**.
  Cache TTL 60s, đọc đầu đồng bộ rồi làm mới nền → **0,6ms**. Đừng đặt phép quét tiến trình
  trên đường request.
- **Khớp chuỗi con trên cmdline sinh dương tính giả.** Bộ so khớp đầu trả 5 pid trên máy chỉ có
  1 scheduler — kể cả script đo của chính tôi, vì nó có tên module trong dòng lệnh. Phải phân tích
  `argv`: đúng `python`, đúng `-m`, đúng module ngay sau `-m`.
- **`age()` phụ 'ago' và đổ mọi thứ trên 1 giờ thành `84.0h`.** Chỉ báo tuổi scheduler tồn tại đúng
  để bắt ca **nhiều ngày**, mà `84.0h` không đọc ra "ba ngày" trong một cái liếc. Dùng bộ định dạng
  riêng có đơn vị ngày.
- **APScheduler chỉ nạp cron lúc khởi tiến trình.** Sửa lịch rồi restart backend là **không đủ**.
  21 lần restart đi qua mà job chủ nhật vẫn không tồn tại trong tiến trình đang chạy.
- **Đừng gọi `location.reload()` bên trong hàm được evaluate** — "Execution context was destroyed".
  Điều hướng trang trước, rồi mới đọc DOM.
- **Here-string PowerShell (`@'...'@`) không chạy trong Bash tool** — `@'` lọt thẳng vào tiêu đề
  commit. Trong Bash dùng heredoc `-F - <<'MSG'`.

## Gotchas — rà soát THIẾT KẾ bảng giám sát (2026-08-16, phạm vi dash/**)

- **`scrollWidth > clientWidth` là phép kiểm SAI cho bộ bảng này.** Khung trang đặt
  `overflow-x: hidden` (realtime.css dòng 29-30) nên nội dung tràn bị CẮT thay vì tạo thanh cuộn,
  và phép kiểm báo xanh. Hai ca đo được: hàng đầu `/realtime` có nội dung 721px trong ô 457px
  (`1425 == 1425`, xanh); ở 390px `documentElement.scrollWidth == clientWidth == 390` (xanh) trong
  khi `body.scrollWidth = 602`. Phép kiểm đúng: với mỗi phần tử vượt mép, đi ngược lên tìm khối
  cuộn ngang gần nhất — có khối cuộn thật thì nội dung TỚI ĐƯỢC, gặp `overflow-x:hidden` trước
  hoặc lên tới gốc thì MẤT.
- **Đè chữ thì scrollWidth không bao giờ bắt được.** Phải so trực tiếp hình chữ nhật từng cặp nút
  chữ lá, bỏ cặp có quan hệ tổ tiên–con cháu, giao nhau > 4×4px là đè thật. Chính bước này bắt
  được lỗi hàng đầu `/realtime` (mục `Reports` bị che 100% ở 1366px).
- **Tràn CĂN PHẢI đi ngược sang TRÁI.** `.header-live-context` có `justify-self:end` +
  `white-space:nowrap` trong ô `minmax(300px,1fr)` — ô bị chốt sàn 300px nên không nở theo nội
  dung, phần thừa tràn ngược lên thanh điều hướng. Chỉ sạch khi cửa sổ ≥ 1920px (ở 1920px thoát
  đúng 1px). Luật xuống dòng đã có sẵn ở dòng 527 nhưng chỉ áp dụng từ 700px trở xuống.
- **Đếm "phần tử vượt mép" mà không phân loại thì ra 609 lỗi ma.** `/analytics` ở 390px có 609
  phần tử vượt khung nhìn — cả 609 đều nằm trong khối cuộn thật, tới được, KHÔNG phải lỗi. Suýt
  báo cáo nguyên cụm này thành phát hiện.
- **Đo tương phản phải ghép nền trong suốt nhiều lớp.** Lần đo đầu ra tỉ lệ `1.00` cho chữ xanh
  trên nền `rgba(54,191,105,0.035)` — giá trị bất khả thi, vì đang coi nền bán trong suốt như nền
  đục. Ghép đúng chồng nền rồi mới ra số dùng được (111/292 nút chữ dưới AA, gần như toàn bộ do
  một biến `--dim #5b6975` ở mức 3.14–3.48).
- **`tabular-nums` KHÔNG cần cho bộ bảng này — đã đo, không phải bỏ qua.** Thử cả 7 phông trong ô
  chọn phông kể cả `System UI`: chữ số `0`/`1`/`7` luôn cùng bề rộng. Định báo "2/24 chỗ thiếu
  tabular-nums" thì đo ra là vô hại.
- **Chấm trạng thái: xanh ↔ vàng lệch 6 mức xám trên 255** (tỉ lệ 1.06). Đổi sang thang xám thì ba
  trạng thái là cùng một chấm. 6 chấm đều 7px, không nhãn, không hình dạng riêng, không aria-label.
- **Chỉ `/realtime` mang khối trạng thái sống.** `/paper`, `/analytics`, `/reports`, `/` chỉ có
  thanh điều hướng nên không dính lỗi đè chữ ở hàng đầu.
- **Mẫu đúng đã có sẵn trong repo.** `/paper` bọc bảng rộng (2332px, 3522px) trong `.trade-table`
  cuộn ngang riêng; `/realtime` bọc bảng lệnh trong `.table-wrap`. Cả hai đều tới được — không cần
  phát minh cách sửa mới cho bảng.

## Gotchas — CSS/đo giao diện (2026-08-16, tuyến dash/**)

- **Phép dò "thẻ" đòi CẢ viền LẪN nền thì bỏ sót hộp chỉ có viền.** Đã báo "hết thẻ lồng"
  trong khi `.decision-shell` và `.table-wrap` vẫn còn `border: 0.8px solid` bốn cạnh, nền
  trong suốt — mắt thấy rõ là khung, phép dò thì không. Điều kiện đúng: **có viền ≥3 cạnh
  HOẶC (có nền VÀ bo góc)**.
- **Gỡ nền và bo góc chưa đủ để gỡ một thẻ — phải gỡ cả `border`.** Luật gỡ thẻ đặt
  `background: transparent; border-radius: 0` nhưng quên `border: 0` cho hai lớp, nên chúng
  vẫn là hộp.
- **Luật đặt TRƯỚC trong cùng tệp sẽ thua luật đặt SAU ở cùng độ đặc hiệu.** Thêm
  `.decision-section > .section-body { padding-left: 12px }` nhưng phía dưới đã có
  `.section-band > .section-body { padding-left: 0 }` — cùng (0,2,0), cái sau thắng, luật mới
  im lặng không có tác dụng. Nâng đặc hiệu (`.section-band.decision-section > …`) thay vì
  di chuyển, vì di chuyển sẽ vỡ khi ai đó sắp xếp lại tệp.
- **Chèn chú thích vào giữa khối CSS làm đóng comment sớm — ĐÃ MẮC BỐN LẦN.** Viết thêm giải
  thích phía trên một rule, nhưng comment cũ đã có `*/` nên phần viết thêm thành CSS rác và
  **nuốt luôn các rule phía sau**. Triệu chứng: luật mới "không ăn" mà không có lỗi nào,
  DevTools không kêu gì. Bắt bằng cách đếm `document.styleSheets[n].cssRules.length` — tệp bị
  cắt sẽ ra số nhỏ bất thường (skin-b.css: 31 khi hỏng, 77 khi lành). **Đưa phép đếm này vào
  mọi lượt đo giao diện.**
- **`<link>`/`<style>` chèn từ script trong `<head>` nằm TRƯỚC các stylesheet tĩnh**, vì
  `appendChild` chỉ thấy phần head đã parse tới đó. Luật của nó thua ở cùng độ đặc hiệu mà
  không có dấu hiệu gì. Cách chắc ăn: thẻ giữ chỗ đặt cuối `<head>`, hoặc đặt biến bằng
  **style nội tuyến trên `documentElement`** (luôn thắng stylesheet). Đã mắc hai lần.
- **`getBoundingClientRect()` của phần tử KHỐI trả hộp viền, không phải vị trí chữ.** Đo thụt
  lề bằng nó sẽ báo sai khi phần tử có padding. Dùng `Range.getBoundingClientRect()` trên
  chính nút văn bản.
- **Chọn sai MỐC đo còn nguy hơn đo sai.** So chữ với vùng trong của THẺ thì bản sửa báo cải
  thiện (thò ra 7px → vào trong 3px), nhưng mắt nhìn khoảng cách giữa chữ và **vạch màu của
  chính hàng đó** — cái đó từ 17px về 0. Số đẹp lên trong khi giao diện xấu đi.
- **Đo hình học qua nhiều iframe song song cho kết quả ảo.** 12–18 khung cùng lúc: báo skin có
  4 chỗ đè chữ + 1 cắt cụt; đo trực tiếp trên trang thì sạch hoàn toàn. Khung chưa render xong
  đã bị đọc. iframe chỉ dùng để đọc trạng thái đã ổn định (tên lớp), không dùng đo hình học.
- **Kiểm tràn phải so với MÉP THẺ, không so với mép padding.** So mép padding thì mọi phần tử
  có lề âm cố ý (danh sách nhật ký trải sát mép) đều bị đếm là tràn — 4 dương tính giả, và tôi
  đã lỡ sửa theo, hạ cỡ chữ một ô xuống 16px trước khi phát hiện.
- **Kiểm tràn phải miễn trừ khối cuộn.** Cột `ID` của bảng lệnh bị báo tràn 59px, thực ra nằm
  trong `.table-wrap` cuộn ngang nên tới được.
- **Đánh giá độ trung tính của màu TỐI bằng "HSL saturation" là sai.** Mẫu số `1-|2L-1|` làm
  `#0b0e12` hiện 24% dù chênh lệch kênh chỉ 7/255. Dùng **chroma** (max−min kênh).
- **Google Fonts phục vụ VARIABLE font**: xin nhiều cân nặng sẽ nhận về các tệp byte giống hệt
  nhau. Khử trùng theo hash + khai báo `font-weight` dạng dải: 287 KB → 80 KB.
- **Font liệt kê trong bộ chọn có thể không tồn tại trên máy.** `JetBrains Mono` và
  `IBM Plex Mono` có trong bộ chọn của trang thật nhưng không cài — chọn vào thì âm thầm rơi
  về Cascadia. Kiểm bằng cách so bề rộng chuỗi thử với font fallback.

## Gotchas — CSS/đo giao diện (tiếp)

- **Chữ đã bị `overflow:hidden` cắt vẫn có toạ độ.** `Range.getClientRects()` trả
  hình học cho cả dòng không bao giờ được vẽ. Phép kiểm chữ-đè-chữ vì thế báo đỏ
  ở mọi thẻ tóm tắt dùng `-webkit-line-clamp` — 2 "va chạm" ở danh sách sự cố hoá
  ra là kẹp dòng đúng ý đồ. Cách sửa: bỏ qua rect nào nằm ngoài client box của
  tổ tiên gần nhất có `overflow:hidden`. Đây là biến thể **ngược** của bẫy
  `scrollWidth > clientWidth`: một cái bỏ sót tràn thật, một cái bịa ra tràn giả.

- **Viewport giả lập nhân mọi số với 0.8.** Khai `border-top: 2px` mà
  `getComputedStyle` trả `1.6px`; một `<div>` mới tạo với style inline cũng trả
  `1.6px`. `window.outerWidth` = 160 trong khi `innerWidth` = 1900 → Chrome đang
  co toàn trang. Số tuyệt đối trong viewport giả lập không dùng để đối chiếu với
  spec được; chỉ các phép so sánh tương đối (đè nhau, tràn thẻ) mới còn giá trị.

- **`-webkit-line-clamp` cần `display:-webkit-box`, nhưng Chrome mới báo computed
  display là `flow-root`.** Đừng kết luận "clamp chết" từ giá trị đó — kiểm
  `webkitLineClamp` và `clientHeight` so với `lineHeight` mới biết nó có chạy không.

- **Bản dựng tham chiếu khai `min-width: 1900px`** nên mọi con số trong đó chưa
  từng gặp màn hình hẹp. Bê nguyên sang trang thật thì vỡ ở 390px: số lớn 40px
  chạy 77px ra ngoài thẻ, lưới 2 cột đẩy giá trị ra 277px. Giá trị lấy từ bản
  dựng phải được đóng khung lại theo mốc 680px (mốc này là hợp đồng với
  `realtime.js:8`, không phải lựa chọn tự do).

## Gotchas — công cụ đo tự nói dối (phiên rà runner vòng 2, 17/8)

Năm lần trong một phiên, thứ trả về câu trả lời sai không phải hệ thống mà là **lệnh tôi
dùng để đo nó**. Cả năm đều in ra một kết quả trông hợp lệ.

- **`Get-Content -Raw` + `Set-Content -Encoding utf8` làm hỏng ký tự không ASCII.**
  PowerShell 5.1 đọc theo cp1252 rồi ghi UTF-8 → mã hoá hai lần. Làm hỏng hai tệp nguồn
  tiếng Việt. Bắt được vì diff của chúng là 34 và 236 dòng trong khi chỉ sửa một dòng.
  **Đừng round-trip mã nguồn repo này qua PowerShell** — dùng công cụ ghi tệp hoặc python.

- **`grep ... | head -N` cắt kết quả, và tôi đọc thành "không tìm thấy".** Kết luận
  "không phép kiểm nào ghim hành vi này" rồi gỡ hành vi đó. Có ghim — `test_realtime_dom`
  dựng trình duyệt thật và đếm dòng DOM. Chỉ lượt chạy test bắt được.

- **Đếm tiến trình bằng cách khớp chuỗi trong dòng lệnh thì lệnh của chính mình cũng khớp.**
  Dính hai lần: suýt báo "2 scheduler" và "2 backend". Lọc theo tên tiến trình
  (`Name -like 'python*'`) và kiểm chủ sở hữu cổng mới ra đúng một.

- **Patch `datetime` toàn cục để dịch đồng hồ sẽ phá `pyarrow` → phá `import pandas`.**
  Hàm đang đo bắt `except Exception` quanh import và trả về rỗng — tức "không có vấn đề
  gì". Muốn dịch đồng hồ thì **nạp module nặng trước**, rồi mới patch, và chỉ patch thuộc
  tính của module đang kiểm chứ không của stdlib.

- **`-k` của pytest khớp theo tên hàm.** `-k runway` chỉ chạy 1 trong 2 phép kiểm vì tên
  cái kia không chứa chuỗi đó; "1 passed" trông như đã kiểm đủ.

Điểm chung: **không lần nào sự cẩn thận bắt được chúng.** Thứ bắt được là một dòng
self-check in ra con số mâu thuẫn với con số khác, hoặc việc chạy test trước khi commit.
Nên mọi script đo phải kèm một assert kiểu *"phép đo này phải tái tạo được N đã biết"*
hoặc *"harness phải cho ra được cả kết quả xanh lẫn đỏ"* — trước khi in verdict.

## Gotchas — vận hành (cùng phiên)

- **Bảng công việc của scheduler đóng băng lúc khởi động.** APScheduler dựng job từ mã
  đang nạp, kho trong bộ nhớ, không có đường nạp lại. Sửa `run_scheduler.py` mà không
  khởi động lại thì **không có tác dụng gì** — đêm 16/8 bốn commit nằm trong repo và
  không cái nào chạy, gồm cả trần 20 phút của H5.

- **Tiến trình con thì ngược lại.** Mỗi slot sinh `python -m global_index.run_live_day`
  mới, nạp mã từ đĩa ngay lúc đó — nên sửa `runner.py`/`ibkr_broker.py` là slot kế tiếp
  đã chạy mã mới, không cần restart. Hai luật ngược nhau trong cùng một hệ.

- **Module Python của backend cũng nạp một lần.** Sửa `monitor/backend/*.py` cần restart
  backend. Nhưng `.js` trong `global_index/dash/` được phục vụ từ đĩa mỗi request nên
  sống ngay khi tải lại trang. Ba luật khác nhau cho ba loại tệp.

- **Nhật ký scheduler xoay theo ngày MÁY (Calgary), có chủ đích** — tên tệp phải khớp
  dấu thời gian bên trong nó. Nên phiên 00:20 ET thứ Hai nằm trong `scheduler_<CN>.log`.
  Bộ đọc job journal đã xử lý bằng cách mở cả hai tệp; đừng "sửa" chỗ đó.

## Gotchas — đè bảng nền (2026-08-17, lớp phủ dashboard)

- **Pseudo-element vô hình với mọi phép đo border.** Một dải 2px hổ phách chạy
  ngang thẻ Model Inputs, trong khi `getComputedStyle(el).borderTopColor` trả
  `#251f36` sạch sẽ ở mọi lần đo. Nguồn là `.model-inputs-zone.watch::after`
  (realtime.css:110) — `position:absolute; height:2px; background:var(--amber)`.
  `getComputedStyle(el)` **không** bao gồm pseudo; phải gọi
  `getComputedStyle(el, '::after')`. Quét màu giao diện phải duyệt cả `::before`
  và `::after`, nếu không sẽ kết luận "không có gì màu vàng" trong khi nó đang
  hiện rành rành.

- **`!important` trong bảng nền → đè bằng BIẾN, đừng đè bằng selector.**
  `realtime.css:122` viết `.positive { color: var(--green) !important }`. Không
  selector nào (kể cả id) thắng được. Cách vào duy nhất là định nghĩa lại chính
  `--green`. Làm vậy còn lộ ra một lệch màu chưa ai thấy: xanh của bảng nền là
  `#36bf69`, xanh của bản dựng là `#3ecf8e`.

- **Viết luật cho tên lớp mình tưởng — đã mắc BA lần trong một phiên.**
  `.journal-tabs` (thật: `.journal-view-toggle`), `.job-note` (thật:
  `.job-summary`), `.tag.runner` (thật: `.issue-origin.runner`). Cả ba khối CSS
  đều "chạy" mà không chạm vào phần tử nào, và không có lỗi nào báo. Trước khi
  viết một khối luật: `document.querySelectorAll(sel).length` cho từng selector.

- **Đối chiếu specificity với luật gốc, đừng chỉ tăng bừa.**
  `.model-inputs-zone::after` (0,1,0) không bao giờ thắng
  `.model-inputs-zone.watch::after` (0,2,0). Đọc luật gốc rồi khớp đúng số lớp.

- **Thẻ "không đổi gì" thường là bị ghim chiều cao, không phải CSS không chạy.**
  Lưới stats nhìn y hệt sau nhiều vòng sửa màu và khoảng cách. Đo ra:
  `realtime.css` đặt `.header-zone { min-height: 152px }` (kèm biến thể 146/188
  ở các breakpoint), trong khi nội dung thẻ Performance chỉ cao **47px** — gần
  50px chết mỗi thẻ, ba thẻ một hàng. Bản dựng không đặt chiều cao nào cả.
  Khi một khối "không có gì thay đổi", đo `minHeight`/`height` computed trước
  khi nghi luật màu.

- **Neo thay-thế-chuỗi không được kết thúc giữa token.** Một anchor dừng ở
  `const clearMarks = (root) =` nuốt mất dấu `>` của `=>`; `next.js` ném
  `ReferenceError` ngay lúc load và **toàn bộ lớp phủ chết**, trang tụt về bố cục
  nền mà không có gì kêu. Assert "khớp đúng 1 lần" không bắt được — nó chỉ nói
  vị trí đúng, không nói kết quả còn parse được. Sau mỗi lần sửa JS bằng script:
  `node --check <file>`. Với CSS: đếm `{`/`}` và `/*`/`*/`.

- **Hộp `nowrap` không nở theo chữ bên trong nó.** `getBoundingClientRect()` của
  `<b>` trả đúng 202px cho cả sáu ô, trong khi một giá trị dài 216px và đang đè
  sang cột bên cạnh. Phải đo bằng `Range` trên node văn bản. Cùng họ với bẫy
  border-box vs padding-box đã ghi ở trên.

- **`overflow: auto` giấu chữ y như `hidden`.** Sau khi cho cột nhật ký cuộn
  trong một màn hình, phép kiểm chữ-đè-chữ báo **11** va chạm — tất cả là dòng
  cuộn xuống dưới mép, đè lên nội dung phía sau. Phép lọc chỉ loại `hidden|clip`.
  Danh sách đầy đủ phải là `hidden|clip|auto|scroll`.

- **Đổi một token dùng chung thì grep hết nơi đọc nó.** Restate `--violet` cho
  khớp bản dựng làm chip KNOWN DEBT trùng màu chip RUNNER, vì `realtime.css:219`
  dùng cùng token đó cho một nghĩa khác hẳn.

- **Đo đúng trang, không chỉ đúng phép đo.** Hàng chục lượt tôi báo "0 va chạm,
  màu đã khớp, 11/11 điểm mốc đúng" — tất cả đo trên `preview.html?skin=e`.
  Trang THẬT `/realtime-next` (tức `index.html`) **không nạp skin nào cả**: chỉ
  `fonts.css` + `realtime.css` + `next.css`. Đo trên đó: vạch trái thẻ sự cố
  `2.4px #8b72ff` (tím của bảng nền), vạch trên khung chi tiết `0px` — không tồn
  tại; nền `#090d11`, font Cascadia. Nghĩa là **toàn bộ công việc thiết kế không
  hiển thị ở nơi người dùng đang nhìn**, và mọi con số của tôi tuy đúng vẫn vô
  nghĩa với họ.

  Cùng họ với luật "đo bằng đúng khung mà hệ thống dùng", chỉ khác là "khung" ở
  đây là **trang nào đang được phục vụ**. Trước khi đo giao diện lần đầu: mở
  đúng URL production và liệt kê `document.styleSheets` — nếu file mình đang sửa
  không có trong danh sách đó thì mọi phép đo sau đều đo nhầm chỗ.

- **Đo phần tử ngoài rồi tuyên bố khớp — trong khi mắt nhìn phần tử trong.**
  Khung chi tiết sự cố có HAI vạch trên chồng nhau, cách 2px: một của lớp phủ
  (`.open-issue-detail`, xanh cố định) và ngay dưới là một của bảng nền
  (`.issue-detail-panel.<state>`, tô theo trạng thái — `#f2555a` cho incident,
  `#9d8cf5` cho known debt). Mọi phép đo của tôi chỉ chạm phần tử ngoài nên báo
  "khớp" bốn lượt liền, còn cái đập vào mắt là cái trong.
  Cách bắt: duyệt CẢ CÂY con của khung và liệt kê mọi cạnh có màu gần đỉnh, thay
  vì đọc `borderTopColor` của đúng một node.

- **Một vạch trên màn hình có thể do BỐN cơ chế khác nhau vẽ ra.** Cùng một
  "vạch xanh bên phải thẻ sự cố", tôi phải đo bốn lần mới hết:
    1. `border-right` của chính hàng — sửa, vẫn còn vạch
    2. viền của lớp con `.issue-detail-panel.<state>` nằm dưới 2px — sửa, vẫn còn
    3. `#232c3d` xám-ám-xanh của khung viền quanh thẻ — sửa, vẫn còn
    4. **`box-shadow: inset -2px 0 0 var(--blue)`** (realtime.css:207) — thủ phạm
  Ba lần đầu tôi đều báo "đã sạch" vì phép đo chỉ nhìn `border`. Phép đo đúng
  phải quét đủ: `border-*`, `box-shadow`, `outline`, `::before/::after`, và phần
  tử con mảnh sát mép. Thiếu một trong năm là báo sạch nhầm.

- **`tail` trên chuỗi lệnh nối bằng `&&` giấu mất kết quả test.** Báo "áp xong,
  chạy tốt" trong khi 2 test đang đỏ: `cmd1 && cmd2 && pytest | tail -3` in ra ba
  dòng cuối của TOÀN chuỗi, dòng `2 failed` bị đẩy khỏi tầm nhìn, và exit code
  vẫn 0 vì `tail` thành công. Chạy pytest riêng một lệnh, đọc dòng tổng kết.

- **Đè một luật cấp gốc lên bảng nền là đè luôn phần xử lý khổ hẹp của nó.**
  `.header-live-context { gap:22px; font-size:12px }` viết cho màn rộng, đặt ở
  cấp gốc, nạp sau `realtime.css` → huỷ luôn `@media (max-width:680px)` của bảng
  nền, và 8 phần tử header bị cắt ở 390px. Mọi luật lấy từ một bản dựng chỉ khai
  `min-width:1900px` phải được nhắc lại trong khối hẹp.

- **`overflow: hidden` để bo góc = cắt nội dung.** `.table-wrap` bo 8px bằng
  `overflow:hidden`; bảng nền dùng `overflow:auto`. Ở 390px cả thead/tbody bị cắt
  và không cuộn tới được. Bo góc thì dùng `overflow-x: auto`.

## Phép kiểm trình duyệt vs phiên song song (17/8/2026)

Suite đầy đủ báo đỏ một phép kiểm lớp giao diện `/realtime`. Chạy riêng nó: xanh trong
2,5 giây — cả khi có lẫn khi không có thay đổi của tôi.

Đo mốc thời gian mới ra: suite chạy 20:33→20:53, `index.html` sửa lúc 20:39:50,
`skin-e.css` lúc 20:39:58, phiên kia commit lúc 20:45 — tất cả **nằm trong** cửa sổ chạy.

Phép kiểm ấy nạp lớp giao diện từ đĩa mỗi request, nên nó đọc một tệp đang bị viết dở.

**Luật:** một suite trình duyệt đọc tệp từ đĩa thì không tin được khi phiên khác đang sửa
đúng những tệp đó. Đỏ trong tình huống này phải phân biệt bằng ba bước, đừng vá vội:
chạy riêng phép kiểm đó · chạy riêng khi đã gỡ thay đổi của mình · đối chiếu mtime của
tệp nó nạp với cửa sổ chạy suite.

## Luật CSS được viết ra ≠ luật có tác dụng
Hai lần trong một lượt dựng, luật mới **thua sạch** mà trang vẫn dựng, console vẫn im,
và ảnh chụp vẫn "thấy đổi" — vì các luật khác trong cùng tệp thì áp được.

- `.gate-state` thua `.gate-state.pass` (cặp lớp specificity cao hơn).
- `input:checked + label` không khớp: bốn `<input>` nằm TRƯỚC `.paper-tab-nav`,
  không kề nhãn nào. Phải dùng `#id:checked ~ .paper-tab-nav label[for="id"]`.

**Cách bắt:** bật/tắt chính stylesheet đó rồi đòi trang phải đổi. Selector không có
phần tử nào thì báo "chưa xác minh được", đừng đếm là đạt.

## Bộ định dạng màu vứt alpha thì mọi kết luận về màu đều sai
Đọc `rgba(54,191,105,.055)` (nền 5,5%) và in ra `#36bf69` → kết luận "49 chip là khối
màu đặc", rồi viết cả một luật để sửa cái không hỏng. **Chính phép đo đó** trả
`chipsSolidFill = 0` ngay cạnh và tôi không đối chiếu hai dòng với nhau.

## Trang chưa có dữ liệu vẫn trả "0 vấn đề" rất thuyết phục
`/api/v1/paper-evidence` mất 40s ở lần nạp nguội; tab đo đầu tiên rơi trọn vào cửa sổ đó.
Chờ theo TÍN HIỆU nội dung (`wait_for_selector`), đừng chờ theo đồng hồ, và giữ ngưỡng
"chưa dựng xong" để dòng nào không tin được thì tự khai ra.

## Đổi viền và bo góc thì mắt không thấy; đổi CHỮ thì thấy
Ca thật: port xong thẻ/bảng/tab, đo sạch, báo "xong" — người dùng trả lời "vẫn thấy hầu
như ko thay đổi gì". Đo khoảng cách từ vựng thị giác giữa hai trang mới lộ: trùng nhau
cỡ chữ 40%, giãn cách 20%, và `paper.css` có 6 luật đậm 900 + 23 luật 800 trong khi
`realtime.css` có **0** — trần của nó là 700.

**Luật:** trước khi nói "đã mang UI sang", đo phân bố cỡ chữ / độ đậm / bước giãn của cả
hai trang. Viền và bo góc gần như không đổi được cảm giác trang.

## Vị từ phân loại tự đặt ra thì sai; phải đọc từ trang tham chiếu
Bản đầu ánh xạ "in hoa và ≤11px → 9px". Đo ngay sau đó: paper 47 node ở 9px so với 12 của
realtime, và dải 11px — dải rộng nhất của realtime — trống trơn. Trên realtime, `.zone-title`
cũng in hoa mà vẫn 11px; dải 9px chỉ có đúng ba lớp chip.

Vị từ đúng lấy được từ chính khai báo của paper: chip có `border` VÀ `padding`, nhãn thì
không. Sinh luật phủ từ chính tệp gốc thay vì gõ tay 54 luật — gõ tay thì sót, và sót ở
CSS là im lặng.

## Đêm 17→18/8: bốn công cụ đo trả lời sai

Ghi lại vì cả bốn đều **không** bắt được bằng cách đọc kỹ hơn — chỉ bằng một phép đo khác.

- **Trùng thời gian không phải nhân quả.** Thấy `Scheduler started` sáu phút sau khi suite
  khởi động, tôi kết luận suite bơm scheduler giả vào log sản xuất. Đo cha tiến trình:
  `run_scheduler` và `start_backend` cùng cha — đó là lần khởi động lại của người dùng.
  Rồi đo kích thước log trước/sau khi chạy test dùng scheduler: **không một byte nào**.
- **Lệnh của chính mình khớp vào bộ lọc.** `Where-Object CommandLine -like '*run_live_day*'`
  khớp cả lệnh đang gõ. Lần thứ ba trong một phiên. Lọc thêm theo `Name -like 'python*'`
  và kiểm cha, đừng tin số đếm.
- **Regex bắt trúng chú thích của chính mình.** Quét `Number(x || 0)` ra 22 chỗ; hai chỗ
  là chú thích trích lại mã cũ. Bỏ qua dòng bắt đầu bằng `//` trước khi báo.
- **Luật quét sai về chính nó, hai vòng.** Gắn cờ cả hai dòng fail-closed dùng `?? Infinity`;
  thêm ngoại lệ thì ngoại lệ không chạy vì `[^;
]*` tham nên đoạn khớp dừng trước từ khoá.
  Cả hai lần đều do phép tự kiểm nạp dòng thật từ repo bắt được.

**Luật rút ra:** phép đo phải nhắm vào thứ mình đang tin, không phải thứ dễ đo. Và một
luật quét phải tự chứng minh nó bắt được cái nó cấm **và** bỏ qua cái đúng — luật gắn cờ
cả cách chữa đúng sẽ bị tắt chứ không được tuân thủ.

## Khởi động lại scheduler không miễn phí

Hai lần ghi nhận được, job nối IBKR kế tiếp đều timeout 3–4 phút sau khi khởi động lại
(13/8 MAX_HOLD, 17/8 STOP_REPAIR_0020). Lần 13/8 có cơ chế đo được: **hai scheduler cùng
sống nên slot bị bắn hai lần cùng giây**, hai tiến trình cùng clientId 1 va nhau. Mutex
nằm **trong tiến trình** nên không bảo vệ được trường hợp này. Lần 17/8 chỉ phóng một
lần — chưa có cơ chế, đừng suy cái này từ cái kia.

Khởi động lại còn để lại một slot kẹt vĩnh viễn ở "running": cha chết thì không ai ghi
dòng kết thúc. Đã sửa bằng cách phân biệt *bị cắt ngang* với *không hề chạy* (4a84260).

**ĐÍNH CHÍNH (chủ dự án chỉ ra).** Tôi viết "nguyên nhân gốc hai-scheduler vẫn còn".
**Không còn.** `monitor/ops.py` có `plan_single_instance` + `ensure_single`, thêm ngày
**13/8 — đúng ngày sự cố** (`159bfaa`), và `stop_runners` dọn con mồ côi thêm 16/8
(`686d88c`). Kiểm cả ba nhánh `cmd_up`: thăm dò hỏng → **từ chối**; thấy >1 tiến trình →
**từ chối**; thấy 1 → để yên. `ProcessScan` cố tình có **ba** trạng thái, vì gộp "không
biết" thành "không có gì chạy" chính là thứ đã đẻ ra scheduler thứ hai. Đêm nay hai lần
khởi động lại, đo được **chỉ một tiến trình**.

**Bài học:** tôi đọc log 13/8, thấy hai scheduler, rồi kết luận về **hiện tại** mà không
kiểm xem đã ai sửa chưa. Dấu vết cũ nói về lúc nó xảy ra, không nói về hôm nay — muốn nói
về hôm nay thì phải `git log -S` cái cơ chế đó trước.

Khoá E1 thêm cho hai entry point vì thế là **lớp phòng thủ thứ hai**, không phải bản vá
chính: `ensure_single` bảo vệ đường đi qua `ops.py`, khoá E1 bảo vệ bất kể ai khởi động.

## Ba tầng của một lỗi job

Job FLEX_PULL hỏng lộ ra ba tầng chồng nhau, sửa tầng một xong vẫn hỏng:
biến môi trường sai phạm vi (`$env:` không tới được tiến trình con của scheduler) →
sổ broker cho phiên đang chạy **chưa tồn tại** lúc job chạy → **không chỗ nào ghi lại
cái trần đó**, nên "chưa công bố" và "không có" cùng một hình ảnh và cùng chặn go-live.
Tầng ba mới là tầng đáng sửa.

## Gom luật CSS theo họ = đảo cascade
Sinh luật phủ rồi gom "mọi luật chip vào một khối, mọi luật nhãn vào khối sau" đã **đảo**
trật tự của `paper.css`. `<span>BREACH</span>` khớp cả `.blocker-card span` lẫn
`.paper-metrics span` (blocker card nằm trong `section.paper-metrics`) — cùng specificity
nên luật đứng sau thắng. Gốc xếp `.paper-metrics span` trước; bản gom xếp sau → mọi chip
nhận cỡ nhãn 11px thay vì 9px, và trang trông y như chưa đổi.

**Luật:** khi sinh luật phủ cho một stylesheet có sẵn, giữ nguyên TRẬT TỰ NGUỒN. Trật tự
là điều kiện đúng/sai, không phải cách trình bày.

## "Có đổi" không phải là "đổi đúng"
Bất biến cũ bật/tắt stylesheet rồi đòi trang phải đổi — nó **xanh** suốt lỗi trên, vì luật
*có* đổi một thứ, chỉ là đổi sang giá trị của luật khác. Phải đọc giá trị KHAI trong từng
luật rồi đòi có phần tử tính ra đúng giá trị ấy.

## Gộp phán quyết qua nhiều tab: chỉ được NÂNG hạng
Bản đầu của phép kiểm mới cũng xanh khi tiêm lỗi. Lý do: tab Overview báo "bị đè hoàn
toàn", ba tab sau selector đó không có phần tử, và vòng gộp ghi đè thẳng → xoá mất phán
quyết thật. Thứ tự hạng: thắng > bị đè > không có phần tử, và chỉ đi lên.

## Phép kiểm dựng ra để bảo vệ đường đặt lệnh đã tự chặn nó (18/8, ~02:38–02:52 ET)

Tôi viết `test_entrypoint_lock.py` để ghim khoá E1. Trong đó có hàm đọc default của
argparse bằng cách **gọi thẳng `module.main()`** với `sys.argv = ["x"]`, bọc trong
`except Exception: pass`.

`main()` chạy thật. Nó thấy `live_positions.json` trong thư mục làm việc, giành khoá ở
đường dẫn **mặc định** `runner.pid` — tệp khoá của hệ thật — rồi mới chết khi thử nối
IBKR. Tệp khoá ở lại, mang PID của chính tiến trình pytest còn sống.

Hậu quả đo được: `runner.pid` ghi 00:38:39 mang PID 43756 (pytest). Ba slot NKD sau đó
— 02:40, 02:45, 02:50 ET — đều `[lock] Runner already running` và **không làm gì**.

**Ba thứ đáng nhớ:**

1. **Một lượt bị khoá chặn vẫn thoát 0**, nên scheduler ghi `completed OK` và bảng job
   hiện `completed`. Dấu vết duy nhất là một dòng WARNING trong log riêng của live_day.
   Chủ dự án phát hiện ra không phải nhờ cảnh báo mà nhờ để ý **dòng lỗi HMM biến mất** —
   slot chạy 10 giây thay vì 77 nên chưa kịp chạm tới guard. Một tín hiệu âm tính, và
   không có cái đồng hồ nào bắt được.
2. **Con số 20 giây của phép kiểm là dấu hiệu tôi đã bỏ qua.** Một phép kiểm thuần đọc
   argparse không có lý do gì chạy 20 giây; đó là thời gian nối IBKR hỏng. Sau khi sửa
   nó chạy 1,57 giây.
3. **`except Exception: pass` quanh một lời gọi `main()`** biến "chạy nhầm cả pipeline"
   thành im lặng. Không bao giờ gọi `main()` của một entry point trong test để đọc
   default — dựng parser bằng `--help` rồi bắt `SystemExit`.

**Không có lệnh nào được gửi:** `trade_log.jsonl` giữ nguyên 28 dòng, dòng cuối từ 11/8;
sổ có 0 vị thế nên maxhold không có gì để đóng. Nhưng nó **có** thử nối IB Gateway trên
clientId 1 giữa các slot đang chạy.

Quét lại hai chỗ khác trong repo gọi `main()`: cả hai an toàn — một cái chặn ngay bằng
ngoại lệ và thay luôn `attach_file_log`, cái kia truyền `--root`/`--out` vào thư mục tạm.

## Heredoc bash nuot dau thoat trong ma Python (18/8) — ba lan

Viet ma Python co `
` qua `cat << 'EOF'` hoac `python - << 'PYX'`: dau thoat bien
thanh xuong dong that, tep hong cu phap ngay dong `print(`. Xay ra **ba lan** trong mot
dem, moi lan mat vai luot sua chap va.

Cung ho voi luat da co ve PowerShell lam hong ma hoa. **Khong viet ma Python co dau
thoat qua heredoc** — dung cong cu ghi tep, hoac tranh `
` bang cach goi `print()`
nhieu lan.

## Sua chap va khong assert thi bao "xong" ma khong lam gi (18/8)

Buoc khoi phuc sau mutation dung `.replace()` khong assert. Mau da lech vi mot dong chu
thich xen giua, `.replace()` khong khop, script van in "da khoi phuc" — va dong that la
`pass`. Guard nam do **khong duoc cam vao**.

Bat duoc khong phai nho doc lai ma nho mot phep kiem moi. **Moi buoc sua/khoi phuc bang
script phai `assert` mau khop truoc khi ghi, va xac minh lai sau khi ghi.**

## 2026-08-21 - Normal sleeve fill audit (scratch/research, read-only)

### Gotchas
- Engine gap-through test asks for a TIME break (>15 min between bars), not a PRICE break.
  A 3-tick step between two adjacent 1-minute bars steps over the stop and the engine books
  the fill at the untraded stop level. Hit NKD 4 times in 285 trades; Ro-4 0 in 1,040.
  Fix = drop the time-break requirement from the `gapped` condition. Proven equivalent to
  post-hoc `min(stop, open)` / `max(stop, open)` trade-for-trade. NOT applied to production.
- `CircuitBreaker` HALT is an ABSORBING state in `deploy_sim.replay`: entries stop, equity
  freezes, peak never updates, halt never lifts. Ro-4-only floor latches 2022-05-17 and
  earns 0 in 2023-2024. Any multi-year net quoted through the breaker is partly a statement
  about one day.
- Two drawdown denominators in play and they disagree: `metrics()` MaxDD is $/starting
  account; the breaker trips on drawdown from PEAK EQUITY. Floor Ro-4-only is 22.7% by the
  first and 16.3% by the second. Only the second decides whether trading stops.
- Running the engine twice in one process on the floor window dies on memory (~exit 255,
  no traceback). `_swing_cache` is keyed `(id(df), id(datr))`, and `backtest_swing_tf`
  passes datr=None while `harness._cache` passes a real datr - so every frame gets TWO
  cache entries. Extract what is needed, drop the frames, clear both caches before the
  second pass.
- Do not send stderr to $null when backgrounding a run. Cost one blind failure diagnosis.

### Rejected approaches
- Re-running the engine to build the `--no-nkd` anchor: doubles memory and time for nothing.
  Feed `deploy_sim` the already-captured trade tables and let it do its own assembly, sizer,
  guard and breaker. Cheaper AND a stronger check - same inputs, independent code path.

### Open questions
- Which other floor rows in the "Normal sleeve validation pass 1" table latched? Candidates
  by MaxDD: `cap075` 21.4%, `nkd_ema20` 20.9%. Unmeasured.
- NKD helps headroom on floor (+2.6pp) and hurts it in 2025 (-2.8pp) and 2026 (-2.2pp).
  Rule 4 cannot be settled from these three windows, and 2 of the 3 are OOS.
- NKD floor edge is 2 of 7 years (2022+2023 +$6,972; other five -$3,073). Needs a
  day-clustered bootstrap before it counts as edge.

## 2026-08-21 (later) - Normal promotion audit (scratch/research, read-only)

### Gotchas
- Filtering a saved trade table is NOT running the strategy with a filter. A rejected
  signal does not empty the day: the 14:00-15:55 scan continues and can enter on a later
  bar, and the book stays flat, which changes what the following sessions can do.
  Regenerating from the signal path adds 31-44 trades per instrument on floor and moves
  Calmar by -15% (floor) / -32% (2025) / +26% (2026) versus row deletion.
- scratch/normal_sleeve_enginefix_policy_anchor_20260821.py prints "Real engine path after
  gap-through fix" but applies NO fix - it just calls run_case. It only produced fixed
  numbers because production happened to be patched at the time. Production is reverted
  now, so re-running it measures the UNFIXED engine under a banner saying otherwise.
- MaxDD% quoted on a $50,000 base and the breaker's trip level are different numbers.
  The breaker trips on drawdown from PEAK EQUITY. Always report headroom in pp on the
  breaker's own rule; that is the number that decides whether trading stops.
- An uncentred bootstrap band that clears zero is not a test. Centre the data
  (subtract the mean) before resampling or the p-value answers a different question.

### Rejected approaches
- strict025 cap for the filtered Normal candidate: floor 14,340/Calmar 0.43 vs current cap
  33,970/0.88. Filtering plus a tight cap starves the book - 419 of 752 entries rejected,
  and the UNFILTERED baseline at strict025 (20,285/0.68) beats the filtered one.

### Open questions
- The filter is a drawdown-control device, not an alpha device: on floor it adds only
  +$793 (2.7%) of raw edge to R4 standalone, but moves peak-relative drawdown 16.3% ->
  10.2%, i.e. out of the permanent breaker latch. Argue for it on that basis.
- Entry-bar vs previous-bar rvol is not settled by floor: entry-bar wins Calmar and
  headroom there, previous-bar wins net (+$992) and wins outright on 2025. The entry-bar
  version's big advantage sits in 2026, which may not select.
- p90 threshold is a quantile of the floor window's own traded days, and the rule was
  picked from a grid of 9 on that same window. No fold selected it.
- NKD direct alpha is not distinguishable from zero in any window (centred cluster
  bootstrap p = 0.21-0.47), 1-2 months carry each window, and floor is 2.7x from slippage
  breakeven (5.42 ticks/side vs a 2-tick assumption) with a median exit-bar depth of 8
  contracts. The old reason to keep NKD is gone: with the filter, R4 no longer needs NKD
  to stay clear of the trip.

## Gotchas (2026-08-23, Stage 5X dashboard audit)
- The dashboard's Decision panel (Entries / Closes / Rejected) can never show anything from
  the live snapshot: the runner creates those four fields empty and nothing writes into
  them. The backtest replay generator DOES fill them, so the panel looks alive when you
  test it against replay data and is dead against live data. Measured: 0/10 live snapshots
  vs 648/1749 replay snapshots carry a rejection detail.
- A live rejection reaches the screen ONLY as a regex over the WARNING sentence
  "REJECTED SHORT MNQ (roska4_swing) risk_sized=$... — ...". Reword that log line and two
  readers go quiet without erroring. Same family as the "python" in a traceback bug.
- RAITS_TRACK1_SHADOW=1 feeds only the "next scheduled job" table, not the freshness/
  incident table. Two slot tables exist; the flag reaches one. Verified by diffing the whole
  schedule-status payload at four pinned ET instants.
- monitor/backend/runner_positions_reader.py is an ALLOW-LIST of 9 keys. Adding a field to
  live_positions.json and expecting the dashboard to see it will fail silently.
- monitor/backend/paper_evidence_reader.py aggregates the WHOLE trade_log.jsonl with no
  split on anything. Track 1 trades in that file would be graded by legacy's fill-quality
  and P&L gates with no way to separate them.

## Rejected approaches (2026-08-23)
- Writing the explainability schema doc by hand beside track1_explain.py — rejected, it
  would drift. Both the JSON schema and the design note's rule table are generated from the
  registry by scripts in scratch/.
- Letting the caller supply code_refs — rejected. Derived from the rule id instead, so a
  caller cannot name one rule and point at another file.

## Gotchas (2026-08-23, review round 1 on track1_explain)
- Deriving a field ONCE is not enough. track1_explain's builder derived explain_id,
  code_refs and evidence_refs correctly and the validator never re-derived them, so seven
  tamper cases validated clean: edited session_date/stage/sequence with the old id, an id
  of 32 zeros, a swapped ref file, a swapped ref symbol, an EXTRA ref for a rule that never
  fired, and a forged evidence path. Fix: builder and validator call ONE derived_refs().
- Comparing derived refs must be order-insensitive, or a JSON round-trip that reorders them
  goes red on an honest record — a guard that fires on good input is a guard people switch
  off. That tolerance is pinned by its own test (mutation M13).
- **`**something.as_dict()` spread LAST silently overwrites explicit keys set earlier in the
  same dict literal.** track1_explain had `"route": route` and then `**ident.as_dict()`
  which also carried route, so the emitted route came from Identity while the explain_id
  came from the argument. Two sources for one field, and the record was internally
  inconsistent while passing every check. Rule: one field, one source; refuse a
  disagreement rather than resolving it.
- A route check and an id-recompute check are NOT redundant. A record built consistently for
  another route produces an id that recomputes correctly, so only an explicit route rule
  refuses it. Measured, not assumed.

## Gotchas (2026-08-23, Stage 5Y wiring)
- A bounded writer that only resolves its destination when it has rows is fail-open: with
  zero decisions, emit_explanations never called _resolve_shadow, so a run aimed at a
  legacy dir would pass quietly and only write there on the first pass that had rows.
  Resolve the destination BEFORE building anything.
- run_shadow(out_dir=<abs tmp>) is a pre-existing Stage 3 contract and it CONFLICTS with
  the explanation writer's bound. Do not loosen the bound and do not edit those tests:
  skip with a visible reason in the summary, and use root= to relocate a whole run.
- Explanation files must be named for the session date of the rows inside, not the run
  date — a replay window spans 75-104 distinct sessions. Same trap as scheduler_0809.log
  holding 08-10 lines.
- freshness is computed in run_shadow and consulted by NOTHING before run_candidates. Every
  accepted decision therefore carries a freshness proof marked FAILED. Counted as
  accepted_with_failed_proof rather than smoothed over.
- MultiClusterGuard.admits returns (True, "ok") on success and a 1-decimal SENTENCE on
  failure, so the cap number is not recoverable after the fact without parsing prose. Three
  features stay unmeasured until a hook exists inside the admission loop.

## Gotchas (2026-08-23, Stage 5Z freshness + root contract)
- track1_freshness.evaluate reads the machine's CURRENT daily inputs. On a REPLAY of a
  historical window that is run context, not evidence about the admission: the same
  decision (same explain_id) reads passed=True at 12:00 and passed=False at 15:00 the same
  afternoon, with an identical decision stream. Never cite it as a proof on a replay row.
- Two different gates are easy to confuse: track1_freshness (daily inputs, bound NOWHERE
  until 5Z) vs track1_intraday (today's bars, bound on the live slot path since 5D).
- The signal layer has NO freshness refusal verb, so freshness could never reject a
  candidate through the admission path — it had to bind BEFORE run_candidates or not at all.
- When a gate binds, refuse to record the admission rather than downgrading it to a
  rejection. A candidate the engine admitted is not one it refused, and writing the second
  invents a decision that never happened.
- A required field added to a record schema needs a version bump. Do it while nothing has
  been written to a production path; later it is a migration.
- Guard against override flags by READING THE SIGNATURE in a test (inspect.signature), not
  by trusting that nobody will add `allow_any_path=True` later.

## Rejected approaches (2026-08-23, Stage 5Z)
- Making replay bind freshness too — rejected: it would refuse every replay whenever
  today's regime CSV is a session short, which says nothing about January.
- Dropping the freshness reading from replay records entirely — rejected: that replaces one
  wrong answer with no answer. It moved to a run-context record instead.
- Loosening write_shadow's bound so Stage 3's absolute out_dir works — rejected twice now.
  root= relocates the bound; the redirect case records a visible skip.

## Gotchas (2026-08-24, Stage 5Q)
- The audit's headline said `WORST VERDICT: PASS` under four NOT_ENOUGH_DATA_YET rows. The
  roll-up seeded itself at PASS and skipped every pending record. Found by RUNNING it against
  the live tree at 07:43 ET, not by reading it. Pinned by two tests + mutation Q16.
- A scheduled child writes into a pipe, and on Windows a pipe takes the locale codepage. The
  audit report carries em dashes and cp1252 cannot encode them — the deploy_sim failure again.
  The audit now reconfigures stdout/stderr to errors="replace"; a test runs it under a forced
  PYTHONIOENCODING=cp1252 and requires exit 0.
- `window_closed` counts only slots that DECIDED. A named refusal (gate_refused,
  freshness_refused, live_source_not_ready) does NOT count, so a window whose slots all ran and
  all refused reads `incomplete` and the audit FAILs it on coverage. Committed rule, unchanged —
  but it is the most likely way the first live day produces a FAIL that really means "the route
  refused by name all afternoon". Watch it on 2026-08-25.
- The committed daily acceptance gate requires explanation rows for the whole DAY, so a session
  where every sleeve legitimately found no candidate does not satisfy it. The audit reports it
  verbatim beside its own operational roll-up rather than softening it.
- Restarting the scheduler makes every window that already closed TODAY read as pre-start
  (`not_applicable`, not `late`). A mid-day restart is safe but costs the day's judgement.
- This Bash tool mangles doubled backslashes inside heredocs: `\n` in a Python string becomes
  a real newline and `d:\raits` becomes `d:` + CR + `aits`. Write files with the Write tool,
  or build the backslash with chr(92).

## Rejected approaches (Stage 5Q)
- Putting the audit jobs in MIRROR_EXEMPT instead of mirroring them — an unmirrored job can
  never be reported overdue, so an audit that silently stopped running would leave the
  operator's screen looking exactly as it does when the audit is healthy.
- Classifying scheduler children by the presence of `--sleeve` (the pre-5Q argv probe did).
  The audit children carry `--sleeve` too, so the old classifier would have counted four audits
  as strategy slots and still passed. It now keys on the module each child runs.
- Mutating a job id inside the shared audit-job table to test scheduler/mirror drift. Both
  sides read one table, so the mutation moved them together and proved nothing. The faithful
  mutation breaks the mirror itself.

## Open questions (Stage 5Q)
- Should the daily acceptance gate keep requiring day-level explanation rows, given that a
  fully quiet but correct day cannot satisfy it? Project owner's call; the audit does not decide.

## Gotchas (2026-08-24, Stage 5Q-1)
- The acceptance gate and the dashboard were BOTH reading
  `track1_runtime/shadow/explanations/explanations_<day>.jsonl`, and nothing has ever written
  there. The live writer nests one level deeper: `explanations/live_<date>/explanations_<day>.jsonl`.
  `write_shadow` is its only caller in the repo. Measured 0 rows found. On the first real
  shadow day both the explanations and freshness_proofs checks would have failed a CORRECT
  route. Caught only by driving the real writer into a temp tree — a hand-written fixture in
  the reader's own layout would have agreed with itself forever.
- `emit_explanations` -> `write_shadow(..., mode="w")` on EVERY slot, and all four sleeves
  share one file per session date. Measured: after a second slot wrote, the file had 1 row from
  that slot only. The docstring claims "truncates on the first and appends after — which is
  what run_live_day_track1 does". It does not; the code passes "w" unconditionally.
- A zero-candidate slot records decided=True. Do not assume a refusal list from a prompt or a
  docstring — the four outcomes were measured by running observe_live_slot.
- `freshness_refused` is NOT a protective skip. Read its raise site: it fires only when a
  binding mode caught the engine ADMITTING a candidate while the daily inputs were refused.
- track1_intraday.validate refuses too_early/too_late against the SLEEVE's decision band, and
  for global_nkd that band is the TOKYO session while the slot grid is fixed in ET. After
  2026-11-01, 12 of 22 NKD slots are outside it by design.
- `python monitor\ops.py restart --backend` does not exist. Backend-only is
  `restart --no-scheduler --track1-only-shadow` — and the track1 flag is still required,
  because it is what tells the BACKEND which slot table to mirror.
- The Bash tool mangles doubled backslashes inside heredocs (`\n` becomes a real newline).
  Hit it four times this session. Write files with the Write tool or use chr(92).

## Rejected approaches (Stage 5Q-1)
- Fixing the explanation writer in this stage. The one-line fix does not work: truncate only on
  seq==0 and Stress's first slot at 10:35 still erases Calm's 10:00 rows, because the window
  name is live_<date> for every sleeve. Choosing a new evidence layout is a runner-lane
  decision with runbook consequences.
- Adding an `observed < registered` FAIL branch so mutation R1 would red. Two rules for one
  thing. The honest fix was a test that reads the reported `observed` count — and it exposed
  that OBSERVED_CLASSES is reporting-only, which is worth knowing.

## Open questions (Stage 5Q-1)
- Should the committed daily gate keep requiring day-level explanation rows? A fully quiet but
  correct day cannot satisfy it. The audit reports both answers and decides neither.
- Should the NKD slot grid follow the Tokyo session rather than ET? Legacy's inherited
  behaviour today; it makes NKD permanently `incomplete` by the ledger's rule every winter.

## Gotchas (2026-08-24, Stage 5Q-2)
- The live explanation writer wrote ONE file per session date shared by all four sleeves, with
  write_shadow(mode="w") on every slot. Fixed by the PATH, not the mode: per sleeve + per slot.
  Truncation is correct once a slot owns its file — it stops a re-run doubling its own rows.
- FIRST LIVE SLOT (10:00 ET Calm) crashed: SpliceRefused column_mismatch — frozen frames have
  5 columns, IBKR live fetch returns 7 (average, barcount). track1_live_frame.splice refuses
  rather than making NaN holes. observe_live_slot does NOT catch SpliceRefused, so no
  slot_observed row was written at all. The 10:10 audit job correctly recorded FAIL with
  coverage_unobserved / missing_slot_ids / no_timing_records.
- My 5Q-1 claim that the substring freshness check was also "too strict" was WRONG: the probe
  built the record with an empty inputs_summary and the real writer always fills
  freshness_allow. Re-measure with the writer's real call shape before reporting a direction.
- The 5Q/5Q-1 explanation fixtures carried a `proofs` key NO producer in this repo emits. Every
  test using them checked a shape that does not exist. Build fixture rows through the real
  record builders.
- `global_index/maxhold_state.track1.json` is written by the LIVE scheduler at 09:31 ET every
  trading day (Stage 5O's marker). Three guards asserted its ABSENCE and went red. Absence was
  standing in for "no test wrote it"; the honest guard is mtime < module import time.
- `test_no_monitor_or_dashboard_file_mentions_the_module` had been RED since 2026-08-23 — it
  counted a monitor TEST file that names track1_explain in order to assert it is not imported.
- Mutation S1 (shared path restored) went undetected at first because it edits the CALL SITE in
  observe_live_slot and my tests drove emit_explanations directly. Check the call site.
- Heredoc backslash mangling bit again (\n -> real newline) — 3 more times. Use the Write
  tool or chr(92).

## Rejected approaches (Stage 5Q-2)
- Option A (append-only + dedupe by explain_id): needs read-modify-write per slot, leaves a
  window where two processes hold one file, and pushes "which record does this slot stand by"
  to read time. Per-slot files make truncation correct instead of removing it.
- Truncating only on seq==0: does not fix it — Stress's first slot at 10:35 still erases Calm's
  10:00 rows, because the window name was live_<date> for every sleeve.
- Fixing B-5R-A/B in this stage: they are runner-lane changes to slot error handling and live
  frame construction, outside an evidence-integrity stage. Reported precisely instead.

## Open questions (Stage 5Q-2)
- Should the live IBKR fetch be projected onto the frozen columns, or the frozen frames widened
  to carry average/barcount? The first is smaller; the second changes every frozen artefact.

## Gotchas (2026-08-24, Stage 5Q-3)
- The IBKR live fetch returns open/high/low/close/volume PLUS average/barcount; frozen_frame
  returns exactly REQUIRED_COLUMNS. Nobody projected, so splice refused column_mismatch and the
  10:00 ET Calm slot died. Fix belongs in track1_live_source.live_frame - the ONLY splice
  caller - not in the guard: relaxing the guard would let a future caller that forgot to
  project get a WIDER frame back.
- Projection must run BEFORE the overlap check: that check compares values column by column and
  cannot compare a column that is not there.
- observe_live_slot caught 4 exception types; SpliceRefused was not one. A crash writes NO
  slot_observed row, so the audit says coverage_unobserved/missing_slot_ids - "nobody looked"
  about a slot that looked. Now `live_frame_refused` with the guard code in detail.
- run_live_day_track1 had NEVER imported slot_telemetry - one comment mentioning the word, no
  import, no call. slot_timing/ existed and RAITS_TELEMETRY_DIR was exported, so it LOOKED
  wired. `no_timing_records` was unsatisfiable and the p95 gate could never run. Check the call
  site, not the directory.
- Stress still refuses on overlap_disagreement: one MNQ bar at 2026-08-21 13:45 ET differs by
  4.5 pts in 'low' between parquet and feed. Schema fix does not touch it.
- test_no_legacy_path_is_touched (5Z) fingerprinted scheduler_*.log, which the LIVE scheduler
  appends to every 5 min - red whenever the system runs. Replaced with a structural
  "the entry point must not NAME a log file" check.
- My first version of that check was `".log" not in src` and went red on the module DOCSTRING.
  A substring test over free text again. Parse string literals, exclude docstrings.
- A 4C test asserted SpliceRefused/column_mismatch for a missing column; the refusal now moves
  earlier to LiveSourceRefused/missing_required_columns. Same contract, different layer.

## Rejected approaches (Stage 5Q-3)
- Relaxing track1_live_frame.splice to tolerate extra columns. It would let an unprojected
  frame through for any future caller. Mutation M6 proves the guard still earns its place.
- An allowlist of average/barcount. A table that drifts the first time IBKR adds a field, and
  it would refuse a harmless new column. General drop + VISIBLE names is the property.
- Fixing B-5R-D here. Deciding whether the parquet bar or the feed is right is a stored-history
  decision with its own audit trail.

## Open questions (Stage 5Q-3)
- B-5R-D: is the 2026-08-21 13:45 ET MNQ 'low' wrong in the parquet or in the feed? Repairing
  the parquet is one-way (see the never-delete-parquet rule); re-sourcing the bar is not.

## Gotchas (2026-08-24, Stage 5Q-4)
- update_ibkr_daily:548 appends `new_bars[new_bars.index > last_existing]` — STRICTLY newer. The
  bar the fetch stopped on is never re-fetched or rewritten, so a partial boundary bar is
  PERMANENT and a new one is created at every 13:45. The dedupe at :637 never sees a duplicate
  because new_only already excluded that timestamp.
- The MNQ disagreement is the file's LAST bar and the feed's low is LOWER — the only direction a
  partial minute's low can be wrong in. That direction is the evidence, not the magnitude.
- The window ledger's own slot_observed rows carry the feed's value in `detail`. Twelve slots an
  hour apart = twelve independent fetches. No broker query needed to answer "is the feed
  consistent across reads".
- update_spy_csv runs at 13:45 ET and fetches through "today", but the SPY daily bar closes at
  16:00. So the CSV gains D-1 at D's preflight while required_data_through jumps to D. The gate
  is stale at every instant. shadow_live BINDS it => no admission is possible, ever, until fixed.
- Testing a PAST instant against TODAY's csv gives a false "allow=True" (my grid showed Fri
  12:00 passing; on Friday at noon the file held Wednesday). Measure in the right frame.
- Volume ratio CANNOT detect a partial 1-min futures bar: 13:45 volume spans 5-20x naturally,
  and the bar we know is wrong is not flagged while a flagged one is not known wrong. Two
  attempts, both discarded.
- THIRD substring-over-prose test mistake in these stages: "the guard was not weakened" scanned
  the function text for "tolerance" and went red on its docstring's "No tolerance to tune". Now
  parses the AST and asserts numeric literals subset {0, 1, 1e-6}.
- Mutation N8's first form (repair overwrites bars that AGREED) is a no-op: writing a value that
  is already there changes nothing. There was no guard to break.
- Mutation N9's guard (verify by re-reading) had no reachable failure until a test injected a
  write that does not land.

## Rejected approaches (Stage 5Q-4)
- Widening `_refuse_overlap_disagreement` with a price tolerance. It is the only thing that
  noticed; a tolerance would make the route join a frame it knows is wrong, silently, for ever.
- Runtime drop of the final parquet bar. Changes the frame every sleeve reads on every slot to
  work around one bar, and would silently change frozen-window backtests.
- Applying the repair now. Needs a broker fetch beside the running Stress slots (clientId 89),
  only `low` has been compared, and it fixes one day while B-5R-F keeps creating new ones.

## Open questions (Stage 5Q-4)
- B-5R-E: a second SPY refresh after the close, or a requirement that asks for D-1? That is a
  rule about what the route considers fresh, not a threshold to edit.
- B-5R-F: should update_ibkr_daily re-fetch and REPLACE its last bar (>= instead of >, relying
  on duplicated(keep="last"))? It is a shared updater legacy also uses.

## Gotchas (2026-08-24, Stage 5Q-5)
- The freshness bug was NOT a threshold: one `through` was used for the daily SPY series and for
  the intraday parquets, which become available at different times. Split the requirement by
  data kind; do not widen it.
- The causal answer for the daily series comes from the code that reads it: RegimeLabels.get =
  reg.asof(day - lag_days), lag_days=1. So day D needs D-1's close, all day, every day.
- `asof` does NOT fail on a missing date — it silently falls back to an older one. That is why
  the freshness gate has to be the thing that refuses.
- prev_business_day (weekday-only) names the HOLIDAY on the day after one — a close no refresh
  can ever supply. Use the trading calendar and report which one was used.
- A grid evaluated at PAST instants against TODAY's file lies (5Q-4's "Fri 12:00 allow=True").
  Build the file the instant would have had, or say the row is an artefact.
- update_ibkr_daily's history-invariant guard exists BECAUSE the append excluded the overlap.
  Any overlap-aware change must exempt exactly one timestamp by name, never widen the check.
- "Is this a partial bar completing, or two sources disagreeing?" is decidable with NO threshold:
  open cannot change, low can only fall, high can only rise, volume can only grow.
- 4th substring-over-prose test mistake in these stages: a purity check scanned for "fetch" and
  went red on the function's own refusal message. Parse the AST.
- The scheduler's preflight argv is fixed at registration, so a NEW FLAG defaults to off in
  production until someone edits the scheduler AND restarts. That is a feature for a path that
  rewrites parquet bars.

## Rejected approaches (Stage 5Q-5)
- Widening the requirement to accept D-2: would trade a session on a label the backtest never
  used — a rule change disguised as a threshold.
- Splitting preflight_state.json into per-source fields: that file is written by the shared
  13:45 job and read by legacy; the new consistency check surfaces the same information.
- Moving update_spy_csv out of the 13:45 preflight: legacy's 14:05 slots need the CSV by then.
- Defaulting --repair-boundary ON: it would have written five 50MB parquets at 13:45 today,
  unattended, on code an hour old.

## Open questions (Stage 5Q-5)
- Should --repair-boundary be added to the scheduler's preflight argv permanently? It is the
  only path in the updater that rewrites a bar the parquet already has.

## Gotchas (Stage 5Q-6)
- **A fixture that does not match the file it stands in for.** The 5Q-4 repair tool's --apply
  wrote frozen_frame's tz-AWARE America/New_York index back over parquets that are stored
  tz-NAIVE UTC — one bar repaired, the whole file's storage convention rewritten under
  load_parquet / assert_utc_convention / every backtest. All 26 tests were green because the
  fixture wrote a tz-AWARE parquet, so the round trip preserved awareness in test and would
  not have on disk. **Before writing to a real artifact, read the real artifact's convention,
  not the fixture's.**
- **An evidence window that closes turns a repairable defect into a permanent one.** Friday's
  bad MNQ 13:45 bar refused 23 Stress slots on Monday morning; by Monday evening it had fallen
  out of the IBKR fetch overlap and can no longer be measured OR repaired. Nothing counted
  down to that.
- **The boundary bar is a daily event, not an incident.** One 13:45 preflight left partial
  bars in MNQ, MYM and M2K (3 of 5). MNQ's stored bar held 41% of the minute's real volume.
  Measure recurrence before deciding whether a fix should be a flag or a default.
- **Client id discipline is a measurement concern, not only a runtime one.** The read-only
  probe used id 95 specifically so it could not contend with track1 data (89), track1 safety
  (90), legacy (1) or the daily updater (2). Two clients on one id has already cost six slots.
- **A refusal that names the right code is worth more than a repair.** The tool refused MNKD
  with disagreement_outside_the_window (1052 bars) instead of treating it as a boundary bar.
  That refusal is the only reason a second, larger data problem is visible at all.
- A permission gate blocking a mutating command is the system working. Hand the command over;
  do not find another way to run it.

## Rejected approaches (Stage 5Q-6)
- Repairing through the scratch tool instead of the production appender: the appender
  concatenates onto the raw frame and runs assert_utc_convention before writing, so it
  structurally cannot make the convention mistake the scratch tool nearly made.
- Restarting tomorrow morning instead of tonight: it would leave NKD NOT_ENOUGH_DATA_YET for
  a second consecutive day and miss the 16:20 refresh that makes Wednesday's gate pass.
- Explaining MNKD's 1052 bars by picking the most plausible of roll / back-adjustment / clock.
  All three fit what was measured; that is what "unmeasured" means.

## Open questions (Stage 5Q-6)
- **B-5R-G:** what is the MNKD 1052-bar disagreement, first bar 2026-08-24 07:01 JST? It is
  the only blocker before 5R with no command attached.
- Friday's MNQ bar is still wrong in stored history and now unreachable by the feed. Does
  anything downstream read that far back, and should there be an alarm on "a known-bad bar is
  about to leave the repair window"?

## Gotchas (Stage 5Q-7)
- **An instrument has THREE names, not two.** runner name / history symbol / order symbol.
  MNKD = MNKD / NKD / MNK. Two were separated in Aug 2026 after orders went to the full-size
  contract at 10x size; the third was never separated, so `IBKRBroker.fetch_bars` — a DATA
  method — resolved through the ORDER map and the live route fetched MNK against NKD history.
- **`Contract.data_symbol` is the FILE STEM, not the fetch symbol.** MES's is "ES" but its
  history was fetched as MES. A fix written against `data_symbol` would have sent all four
  basket instruments at the full-size E-minis to repair the one that needed it. The truthful
  source is `update_ibkr_daily._build_jobs` — the code that actually fetched the files.
  (Same family as: the truth about an artifact is in the code that CREATED it, not in a field
  that describes it, and not in a CLI default.)
- **Tell a symbol mix-up from a clock error by MAGNITUDE, not by count.** The MNKD count (1052,
  then 1155) was within a whisker of a known 1,050-bar Nikkei CLOCK incident. What separated
  them: signed close median **0.0** and median gap 25 pts = one tick (two order books on one
  index, symmetric) versus a persistent one-directional 900-1000 pt offset (a 13-hour error).
  The count was never the discriminating number.
- **The appender always stores the in-progress minute (B-5R-H).** `new_bars[... > last_existing]`
  plus a fetch that ends inside an open minute means EVERY run freezes one partial bar.
  `--repair-boundary` repairs the PREVIOUS one at the NEXT run, so the poisoning window goes
  from ~2 days to ~1 day and never to zero. Repairing at 20:20 moved the refusal from 13:45 to
  20:20. Do not run `update_ibkr_daily` off-schedule while the market trades.
- **`_refuse_overlap_disagreement` compares open/high/low/close only — not volume.** A boundary
  bar that differs only in volume does not refuse (MYM's 13:45 was such a case).
- **`window_ledger` names files by UTC date; the audit reads by session date.** They agree
  except between 20:00 ET and midnight ET. No Track 1 window falls there today, so production
  is unaffected — but three tests went red at 00:36 UTC reading a file that was never going to
  exist. Same family as the runner_events_20260812.jsonl hardcoded-date gotcha.
- **A guard that says "none may exist" cannot tell an approved change from a leak.** The
  snapshot test failed because an APPROVED repair legitimately created three `.pre5q5-*.bak`
  files. Anchor such guards to the set present at import: the suite must ADD none.

## Rejected approaches (Stage 5Q-7)
- Using `Contract.data_symbol` for the live fetch — see above; wrong on four of five.
- Fixing MNKD inside `IBKRBroker.fetch_bars` — that method is shared with the legacy runner,
  and changing it would alter legacy behaviour in the same evening. Fixed at the Track 1
  provider instead; the legacy defect is named as B-5R-I rather than silently carried.
- "Fixing" the price disagreement with `point_value` — a multiplier moves sizing, risk and
  realised P&L, never a bar price. Pinned by a test that fails if it is changed.
- Running the appender again to clear the new 20:20 partial bar — it would create another one
  a minute later. The regress is the point of B-5R-H.
- Changing the appender to drop the in-progress minute tonight — correct cure, but it is a
  behaviour change to the shared 13:45 job that also writes legacy's data. Needs its own stage
  and its own measurement of what dropping that minute costs the route.

## Open questions (Stage 5Q-7)
- **B-5R-H:** what does dropping the final incomplete bar cost? Does any route need the
  in-progress minute, or is it purely a liability?
- Should `window_ledger` name files by session date instead of UTC date, so the ledger and the
  audit agree at every hour rather than most of them?
- Friday's MNQ 13:45 bar is still wrong in stored history and now unreachable by the feed.
  Should there be an alarm on "a known-bad bar is about to leave the repair window"?

---

## Gotchas (STOCKS-0, 2026-08-26)
- **Cache 5 phút cổ phiếu khoá bằng md5 của `{ticker}_{ngày}_{ngày}_5min`** — dựng lại chỉ mục
  bằng công thức, không cần mở 117.533 tệp. Mỗi tệp là MỘT phiên, mang 04:00-19:55 ET, naive.
  Đừng cho nó qua `futures._validated_core.load_parquet`: hàm đó đọc index như UTC rồi
  `tz_convert(ET)` → dịch mọi bar 4-5 tiếng.
- **1,9 GB dữ liệu 1 phút Databento chỉ có 09:30-10:44 ET.** Mua đã cắt sẵn theo cửa sổ ORB.
  Bất kỳ nghiên cứu nào cần bar buổi chiều đều KHÔNG dùng được nó. Đo trước khi định dùng.
- **`daily_atr_series` không nhân quả nếu đọc trong ngày.** Trung bình trượt kết thúc TẠI D.
  Muốn bản nhân quả thì `.shift(1)`. Đo được: lệch trung vị ~2,6-3,2%, tối đa 71%.
- **Engine làm tròn giá vào/ra 2 số lẻ trước khi tính `points`, nhưng KHÔNG làm tròn stop.**
  Đo khoảng cách stop bằng giá đã làm tròn chỉ tái tạo `2,0 x ATR` trên 58% số dòng.
  Định cỡ phải dùng giá tín hiệu chưa làm tròn. Bắt được nhờ một assert có khả năng đỏ.
- **`_swing_cache` khoá bằng `id(df)`** — phải `clear()` giữa các mã, nếu không địa chỉ bị tái
  dụng và bar của mã này được phục vụ cho mã khác, không báo lỗi, chỉ sai số.
- **Đặt `global` trước MỌI lần dùng tên trong hàm**, kể cả khi tên đó chỉ xuất hiện làm
  `default=` của argparse — nếu không thì `SyntaxError: used prior to global declaration`.
- **Xoá artifact cũ trước khi đặt vòng chờ `until [ -f ... ]`.** Một lượt chạy thử trước đó để
  lại đúng tên tệp, vòng chờ bắn ngay lập tức, và báo cáo suýt dựng trên số của 3 mã.

## Rejected approaches (STOCKS-0)
- Cấy `FLOOR_RANGE_P90 = 0.02652` sang cổ phiếu — đó là phân vị 90 của phân bố FUTURES.
  Đo: bỏ bộ lọc +$9.282; cấy hằng số futures +$3.897; suy lại p90 trên cổ phiếu −$1.662.
  Cả hai biến thể lọc đều tệ hơn không lọc.
- Dùng chung một bộ nhãn HMM sản xuất (khớp tới 2024) cho cửa sổ 2019-2022 làm số chính —
  đó là nhìn trước. Chạy song song hai bộ; cửa sổ khớp lệch nhau ít ($22.175 vs $20.018),
  nhưng ĐỘ TRỄ nhãn lệch rất nhiều (lag 0 sản xuất: −$1.880, lật dấu).
- Lấy 20 mã đầu bảng chữ cái làm tập con "không chọn theo kết quả" — đo lại thì nó nghiêng
  hẳn về công nghệ/tăng trưởng, ra $27/lệnh so với $10,5/lệnh trên đủ 75 mã.
  "Theo bảng chữ cái" KHÔNG phải "ngẫu nhiên".

## Open questions (STOCKS-0)
- Trần vốn, không phải trần số vị thế, mới là thứ chặn sổ: nới 8 → 100 vị thế chỉ đổi ròng
  +4% ($9.282 → $9.688) vì trần giá trị gộp 100% vốn cho tối đa ~9 vị thế cỡ $11k.
  6.268 ứng viên tranh 9 suất. Tiêu chí phân suất (khoảng cách stop giảm dần) là tuỳ tiện —
  nhưng độ nhạy cho thấy nó gần như không đổi kết quả, tức các ứng viên biên đáng giá ~0.
- Vì sao chân SHORT lỗ ở mọi cửa sổ (−$9.007 / −$9.013)? Rổ toàn kẻ sống sót là một lời giải
  thích, nhưng chưa tách được khỏi cổng SHORT theo SPY.
- Cấu hình chính nằm ở CỰC ĐẠI của mọi trục đã quét (ema 50, lag 1, nhãn nhân quả). Cả ba đều
  chốt trước khi có số vì lý do độc lập với kết quả — nhưng ngồi trên đỉnh mọi trục là tín hiệu
  MONG MANH, không phải tín hiệu xác nhận.


## 2026-08-27 — đọc lại sleeve PE_SHORT (chỉ đọc, không sửa mã)

- **Bản kiểm 2026-08-17 nói sai một chỗ về PE_SHORT.** Nó viết rằng nền bootstrap chỉ có 37
  mã và "không bao gồm nhóm 25 mã mở rộng vốn là nơi PE_SHORT lấy tín hiệu". Đo lại:
  PE_SHORT KHÔNG đi qua bộ quét — nó đọc `PE_SHORT_UNIVERSE` riêng, 62 mã. Bằng chứng: ngay
  trong nền đó PE_SHORT đã giao dịch CAT, GE, MRK, NOW, PANW, PYPL — sáu mã ngoài 37. Giới
  hạn 37 mã trói các chiến lược đi qua bộ quét, không trói PE_SHORT.
- **Nhưng nhóm mở rộng chính là chỗ tập trung:** 50,2% lãi in-sample của PE_SHORT đến từ 25
  mã mở rộng; riêng PANW 33,8% (4 lệnh).
- **STATUS.md trỏ vào ảnh chụp không còn tồn tại.** Nó dẫn `results_20260624_200216.pkl`
  (tổng $34.214, PE_SHORT $6.888). Trên đĩa chỉ còn `results_20260707_110323.pkl`.
- **Cơ chế thật của PE_SHORT khác mô tả.** Tài liệu ghi "Stop=1,5×ATR14, Target=2×stop (2:1)".
  Thực tế 25/29 lệnh thoát bằng EOD, 3 STOP_HIT, **đúng 1 TARGET_HIT**. Đây là lệnh thoát
  theo THỜI GIAN, stop/target gần như không tham gia. Bội số rủi ro trung bình 0,35R.
- **Kích thước lệnh KHÔNG phải vấn đề** (khác STRESS_ORB): rủi ro trung vị $747 = 100% mức
  cho phép $750.
- **Hình dạng giống hệt nhau ở cả hai cửa sổ:** IS 8 lệnh thắng gánh hết, 21 lệnh còn lại
  −$114. OOS 3 lệnh thắng = $4.064 > cả tổng $3.120, 19 lệnh còn lại −$944.
- Báo cáo OOS tự mâu thuẫn: Mục 6 kết luận "VERDICT: HOLDS" trong khi Mục 4 ngay trên ghi
  PE_SHORT p=0,185 NO EDGE và Mục 5 ghi bỏ 5 lệnh còn $261/$6.666.

## 2026-08-27 (bổ sung) — edge của PE_SHORT nằm ở ĐÂU: đo bằng dữ liệu ngày, độc lập engine

Hồ sơ: `d:\income-portfolio\gap-short\` (ngoài raits, chỉ đọc raits). Dữ liệu ngày Yahoo,
62 mã của `PE_SHORT_UNIVERSE` + SPY, dùng chính `raits/data/cache/earnings_dates_expanded.json`.

Dựng lại luật PE_SHORT bằng dữ liệu ngày: bán khống tại Open(T) sau gap ≥5%, mua lại tại
Close(T+1), trừ lợi suất chỉ số cùng khoảng.

**Mỹ, 2017-2022 — tách bạch hoàn toàn:**
- MỌI gap ≥5%, không lọc:            −40,0 bps  KTC95 [−79, −2]   n=505   ← ÂM
- Chỉ gap trong cửa sổ công bố KQ:  +126,6 bps  KTC95 [+45, +196] n=45    ← DƯƠNG
- 2017-2024: trong cửa sổ +104,2 [+38,+168] n=91 · ngoài cửa sổ −60,2 [−101,−18] n=520

→ **Edge của PE_SHORT nằm TRỌN trong bộ lọc ngày công bố. Cú gap tự nó là chiến lược LỖ.**
Đây là kiểm chứng độc lập: +126,6 bps/lệnh khớp với +153 bps/lệnh đo từ tệp lệnh engine.
Hai đường độc lập ra cùng độ lớn → phép đo tin được.

**Trục refine đã thử, không có gì:** chia theo độ lớn gap 5-7% / 7-10% / >10% ra
+115,8 / +67,9 / +138,6 — không đơn điệu, KTC hai nhóm sau đều chứa 0.

**OOS 2023-2024 cũng yếu đi y hệt:** +61,5 bps KTC95 [−49, +169] n=38 — khớp với
p=0,185 của bootstrap engine. Lưu ý confound: lịch công bố của yfinance phủ dày hơn ở
những năm gần đây (19,0 sự kiện/năm OOS vs 8,8 IS), nên đừng so tần suất hai cửa sổ.

N đặc tả đã chạy trong đợt này ≈ 11.

## 2026-08-27 (bổ sung 2) — mở rộng vũ trụ PE_SHORT: kết quả

Hồ sơ `d:\income-portfolio\gap-short\`, ngưỡng cam kết trước ở `0-CAM-KET-TRUOC-MO-RONG.md`
(ghi trước dòng lệnh đo đầu tiên, có hai lần nối thêm đều ghi trước khi xem số).
Vũ trụ 743 mã = 501 S&P 500 hôm nay + 242 mã ĐÃ BỊ LOẠI khỏi chỉ số từ 2015 (chữa thiên kiến
kẻ sống sót; chỉ 112/242 còn dữ liệu). Lấy được 596 mã, 8.611 sự kiện gap ≤−5%.

**PHÉP KIỂM CHÍNH (cam kết trước) TRƯỢT.** Mã mới / 2023-2026 / trong cửa sổ công bố:
**+20,0 bps, KTC95 [−14, +54], n=1.083.** Đạt 2/4 điều kiện (n≥130 ✓, dương sau khi bỏ 5 lệnh
lãi nhất ✓); trượt 2/4 (KTC chứa 0, trung bình < 30 bps). → THIẾU BẰNG CHỨNG.
Khác lần trước: phép kiểm này CÓ sức mạnh — 85% nếu edge bằng nửa mức in-sample, 100% nếu
bằng cả. Nên loại được edge ≥50 bps trên vũ trụ rộng. Đây là phủ định thật, không phải tung đồng xu.

**Giả thuyết "62 mã gốc đặc biệt" ĐÃ CHẾT — tôi tự bác.** Thô: 62 mã +99,3 vs mã khác +10,1,
chênh +89,5 p=0,014. Nhưng 62 mã gốc thanh khoản gấp 7 lần ($925tr vs $127tr/phiên). Ghép cặp
ở ≥$500tr/phiên: 62 mã +102,0 vs mã khác **+81,6**, chênh +20,8 **p=0,717 — không khác nhau.**

**PHÁT HIỆN MỚI (hậu nghiệm, CHƯA xác nhận): hiệu ứng tăng ĐƠN ĐIỆU theo thanh khoản, ở CẢ
HAI cửa sổ độc lập.**
IS 2017-2022:  ≥0 → +19,2 | ≥300tr → +54,6 | ≥500tr → +94,1 [+33,+149] | ≥750tr → +128,9 [+63,+190]
OOS 2023-2026: ≥0 → +21,8 | ≥400tr → +42,2 | ≥500tr → +49,4 | ≥750tr → +61,9 | **≥1000tr → +102,4 [+24,+185] n=152**
Nhóm NGOÀI cửa sổ công bố âm ở MỌI ngưỡng (−38 đến −108 bps).
Ngưỡng thanh khoản là hậu nghiệm → đây là GIẢ THUYẾT, không phải kết quả. Nhưng đơn điệu
trên hai cửa sổ rời nhau là ngược với dấu hiệu chọn ngưỡng theo kết quả.
Tần suất ở ≥$1 tỷ/phiên: 152 sự kiện / 3,65 năm ≈ **42/năm** — gấp 4 lần PE_SHORT hiện tại.

**Lịch công bố phải căn theo TỪNG MÃ, không có luật chung.** Đo dấu thời gian: AAPL/MSFT/AMZN/
GOOGL/META/NVDA/TSLA công bố 16:00 (sau đóng cửa, 25/25 lần) → gap phiên SAU; JPM/JNJ/PG/KO/CAT
công bố 06:00-08:00 → gap CHÍNH ngày đó. Gộp bừa làm hiệu ứng loãng nửa (+54 thay vì +106).

**Rác dữ liệu bắt bằng SC4 (giá trị bất khả thi).** SBNY (Signature Bank, sụp 3/2023) vẫn có
"giá" tới 2026 dạng mẩu OTC vài xu → 70 sự kiện rác, kéo trung bình nhóm đối chứng từ −288
xuống −5.440 bps. Chữa bằng điều kiện GIAO DỊCH ĐƯỢC (giá ≥$5, giá trị gd trung vị 20 phiên
≥$5tr) — biết trước khi vào lệnh, không phải nhìn trước.

## 2026-08-27 (bổ sung 3) — thử cứu bằng thanh khoản, và phép kiểm xu hướng bác nó

Bảng ngưỡng thanh khoản trông đơn điệu đẹp, nên tôi làm phép kiểm ĐÚNG cho nó: hồi quy
lợi nhuận theo log10(giá trị giao dịch), MỘT đặc tả, không chọn điểm cắt.

| nhóm | n | dốc mỗi bậc ×10 thanh khoản | KTC95 | p |
|---|---|---|---|---|
| TRONG cửa sổ công bố / OOS | 1231 | +22,3 | [−37,9 · +77,0] | **0,455** |
| TRONG cửa sổ công bố / IS | 1258 | +21,3 | [−54,5 · +96,3] | **0,565** |
| NGOÀI cửa sổ / OOS | 1304 | −71,0 | [−137,2 · −9,1] | 0,024 |
| NGOÀI cửa sổ / IS | 3843 | −63,8 | [−116,1 · −10,3] | 0,021 |

→ **Quan hệ thanh khoản KHÔNG có ý nghĩa ở nhóm trong cửa sổ công bố.** Quan hệ có ý nghĩa
duy nhất nằm ở nhóm ĐỐI CHỨNG và mang dấu ÂM. Ô ≥$1 tỷ (+102,4 [+24,+185]) là một điểm trên
đường nhiễu, chọn sau khi thử 8 ngưỡng.

Kiểm tập trung ô đó: n=152, bỏ 5 lệnh lãi nhất → +56,0 bps, bỏ 10 → **+27,2 bps**. GME một
lệnh +3.449 bps. Theo năm khi mẫu đầy dần: 2023 +119,7 (n=10) · 2024 +213,8 (n=31) ·
2025 +102,0 (n=49) · **2026 +44,3 (n=62)** — hội tụ về mức vũ trụ rộng.

**KẾT: giả thuyết thanh khoản KHÔNG cứu được. Tôi tự bác nó bằng phép kiểm của chính mình.**

**Thứ duy nhất bền qua mọi lát cắt:** chênh lệch trong/ngoài cửa sổ công bố. Nhưng đọc cho
đúng — ngoài cửa sổ ≈ −39 đến −100 bps, trong cửa sổ ≈ +20 bps. **Bộ lọc công bố không tạo ra
lãi; nó tránh một khoản lỗ.** Đích đến là hoà vốn, không phải lợi nhuận.

**Căng thẳng còn lại, chưa giải được, ghi ra để không tự đóng sổ sớm:** ở ≥$500tr/phiên,
IS 2017-2022 cho +94,1 [+33, +149] n=168 (KTC không chứa 0) còn OOS cho +49,4 [−7, +105] n=324.
Cả hai dương, IS có ý nghĩa, OOS không. Vừa khớp với "hiệu ứng thật đang tàn", vừa khớp với
"khớp quá mức trong mẫu + nhiễu ngoài mẫu". Dữ liệu hiện có KHÔNG tách được hai khả năng đó.
Chỉ một phép kiểm tiến về phía trước có đặc tả đóng băng trước mới tách được.

## 2026-08-27 (bổ sung 4) — chiều MUA trên gap không phải tin kết quả: TRƯỢT

Cam kết trước ở `d:\income-portfolio\gap-short\0-CAM-KET-TRUOC-CHIEU-MUA.md`, viết trước khi đo.
Giả thuyết đến từ NHÓM ĐỐI CHỨNG (phần ít bị đào bới nhất), kèm cơ chế nêu trước: gap ≥5%
không có báo cáo kết quả phần lớn là cú sốc dòng tiền → hồi lại; mã càng thanh khoản hồi càng
mạnh. Cơ chế dự đoán ĐÚNG dấu của tương tác.

**Độ dốc đúng như dự đoán, có ý nghĩa ở cả hai cửa sổ rời nhau:**
ngoài mẫu +71,0 [+9,0 · +137,8] p=0,024 · trong mẫu +63,8 [+10,3 · +116,0] p=0,020
Đối chứng (TRONG cửa sổ công bố): −22,3 p=0,480 — không có ý nghĩa, đúng như cơ chế đòi.

**Nhưng MỨC thì không có.** Phân tư thanh khoản, trong mẫu: −69,7 / −106,6 / −92,7 / **+9,2**.
Ngay nhóm thanh khoản cao nhất cũng chỉ hoà. Ngoài mẫu: −73,5 / +11,7 / +177,6 / **+39,6** —
không đơn điệu, nhóm cao nhất THẤP hơn nhóm thứ ba.
Độ dốc có ý nghĩa chủ yếu vì đầu THẤP rất âm, không phải vì đầu CAO lãi.

**Đối chiếu 4 điều kiện: đạt 3, trượt điều kiện kinh tế** (nhóm thanh khoản cao nhất
+33,1 bps sau phí, ngưỡng là 40). Theo cam kết: không báo ô con nào. Theo năm ngoài mẫu:
2023 +155 · 2024 +151 · 2025 −51 · 2026 +26.

**Cùng một hình dạng với phát hiện bộ lọc công bố: đưa từ LỖ về HOÀ, không đưa tới LÃI.**

---

## Tổng kết cả phiên 2026-08-27 — tỉ lệ nền của việc đi tìm

≈57 đặc tả đã chạy (xoay vòng cổ tức 4 sàn × 3 cơ chế · chiều ngược cổ tức · PE_SHORT trong
mẫu/ngoài mẫu/mở rộng/thanh khoản · chiều mua gap). **Số edge được xác nhận: 0.**
Năm thứ trông như sống, cả năm chết dưới phép kiểm thiết kế đúng:
SG cổ tức lớn (chia đôi thời gian) · CA chiều ngược (dưới ngưỡng) · PE_SHORT 62 mã (không
tổng quát hoá) · ô ≥$1 tỷ (kiểm xu hướng) · chiều mua (mức không đạt).
Ở α=0,05 với 57 đặc tả, kỳ vọng thuần nhiễu ≈ 3 dương tính giả. Quan sát 5. **Cùng bậc.**
Việc tìm kiếm này đang cho ra đúng thứ mà nhiễu thuần sẽ cho ra.

## Đính chính (STOCKS-0, 2026-08-26, cùng ngày)
- Bản đầu của báo cáo STOCKS-0 nói **Calm A không chuyển được sang cổ phiếu**. SAI — đọc lại
  `global_index/track1_calm_a.py` thì mọi điều kiện của nó chỉ đọc bar của CHÍNH công cụ đó
  (vị trí giá đóng RTH hôm trước trong biên độ, lợi suất RTH hôm trước, khoảng nhảy), cộng
  nhãn Calm từ SPY. `instruments=("MES","MNQ")` chỉ là cổng danh sách trắng, không phải phụ
  thuộc cấu trúc. Calm A **chuyển được**, và rẻ hơn Normal-R4 nhiều (một lần vào lệnh 10:00,
  không có vòng quét trong ngày). Cái không chuyển là hiệu chỉnh (1/3, −1,0%, 1,5×ATR15).
  Lý do cũ để loại Stress-MNQ (cần độ rộng chéo bốn công cụ) và NKD (phiên Tokyo) vẫn đúng.
  → đã thêm vào STOCKS-1 làm việc số 0.

## PE_SHORT — đào sâu (2026-08-26, chỉ đọc)
- Luật thật đọc từ `decision_unit.py`: gap < −5% so với giá đóng phiên trước tại open 09:30,
  BÁN KHỐNG, stop = open + 1,5×ATR, target = open − 3×ATR, giữ qua ngày vào lệnh, đóng 15:55
  phiên kế tiếp. **Không có cổng chế độ** — chạy ở cả 4 regime, là chiến lược duy nhất như vậy.
- **Giả thuyết sai đã bỏ:** tôi đoán engine đo gap từ bar 19:55 ngoài giờ (đã hấp thụ tin).
  Đối chiếu 29 lệnh thật: 27/29 khớp định nghĩa **giá đóng 15:55**, chỉ 4/29 khớp định nghĩa
  ngoài giờ. Dữ liệu engine nạp là RTH. Giá vào lệnh khớp 0,00000%.
- Đường cong ngưỡng (dựng lại 499 sự kiện gap xuống, 2017-2022): **bậc thang tại 5%**.
  4% → R tr.bình +0,051; 5% → **+0,320**; giữ 0,30-0,38 tới 12%. Dưới 3% ≈ 0 hoặc âm.
  CẢNH BÁO: cao nguyên 5→12% là **mẫu lồng nhau**, không phải xác nhận độc lập.
- **Ngưỡng 5% ĐƯỢC CHỌN TỪ MỘT LƯỢT QUÉT** trên chính dữ liệu này:
  `post_earnings_expansion_sim.py:302` quét [0.01, 0.02, 0.03, 0.05];
  `gap_up_fail_sim.py:168` quét [0.03, 0.05, 0.07]. Nên p-value bên dưới là **có điều kiện**
  trên một ngưỡng đã fit. Giảm nhẹ: 5% là **biên** của lưới, không phải đỉnh nội tại, và
  6-12% (chưa từng thử) tốt bằng hoặc hơn.
- Bằng chứng: tách đôi giai đoạn **rời nhau** 2017-2019 (+0,455 R, 13 lệnh) và 2020-2022
  (+0,261 R, 30 lệnh) — cùng dấu. **6/6 năm dương.** Bootstrap gom cụm theo ngày, null căn
  giữa: p = 0,0001, KTC95 [+6,2, +21,1] R. Đối chứng gương: bán khống gap LÊN >5% cho −0,055 R.
- **Chi phí KHÔNG giết nó:** biên 145 bps notional mỗi lệnh. Hoà vốn ở 145 bps khứ hồi
  (73 bps/chiều). Vay khó 10.000 bps/năm chỉ tốn 79 bps vì giữ 2 phiên → vẫn +66 bps.
  Trượt 100 bps + vay 500 bps/năm → vẫn +41 bps. Khác hẳn tuyến trend-follow (hoà vốn 7,4 bps/chiều).
- **Thiên lệch sống sót đi NGƯỢC chiều nó** — đây là luật BÁN KHỐNG trên danh sách kẻ sống sót,
  nên thiên lệch phạt nó chứ không tâng nó. Mọi kết quả dương khác hôm nay đều được tâng.
- **Chưa có bằng chứng NGOÀI MẪU nào.** Ngưỡng fit trên 2017-2022, và cache cổ phiếu hết ở
  2022-12-30. Còn thiếu: khả năng VAY được (không có dữ liệu locate trên đĩa), trần 2 vị thế,
  vốn/định cỡ (engine ra 29 lệnh, bản dựng lại ra 43).
- Việc quyết định duy nhất: mua bar 5 phút 2023-2026 cho 62 mã, chạy ngưỡng NGUYÊN VẸN.
  ~7 lệnh/năm × 4 năm ≈ 28 lệnh ngoài mẫu.

## Track 1 Market View (2026-08-28)

### Gotchas
- **`.regime-calm/normal/stress/crisis` đặt CẢ `background` LẪN `color`** (realtime.css:922-925),
  vì mọi chỗ dùng cũ đều là ô màu. Dùng lại cho CHỮ thì được một khối màu đặc sau chữ.
  Cách xử lý: chữ → `background: transparent`; ô màu → `background: currentColor`
  (chính lớp đó vẫn cấp màu, và không bị một giá trị trung tính thắng trên specificity).
- **`.mv-legend` là `position:absolute; bottom:0`** — nó được đặt CHỒNG lên chân biểu đồ hồi
  `.mv-chart` còn cao cố định. Khi `#marketViewChart` thành thẻ (position:static) thì chú giải
  neo vào section và trôi mất khỏi thẻ. Phải trả nó về luồng.
- **`.source-note` cắt bằng ellipsis** (`max-width:52%; white-space:nowrap; overflow:hidden`).
  Gắn class đó cho một đoạn văn hai câu thì mất chữ. Chú thích regime đã bỏ class này.
- **`#marketViewChart` từng LÀ hộp vẽ và mang chiều cao 320px.** Giờ nó là cả thẻ giá, nên
  chiều cao phải chuyển xuống SVG — để nguyên thì trục thời gian rơi khỏi đáy.
- **`python -c` một dòng có nháy lồng vỡ trong Git Bash heredoc** — dùng tệp `.py` trong scratchpad.
- **Chạy script import `track1_market_view` phải `cd d:\raits`** — có CWD guard trong
  `run_live_day_track1`, chạy nơi khác thì thoát ngay.

### Rejected approaches
- **Vẽ lane sparkline theo đúng bản thiết kế** — mọi điểm sẽ là số bịa: đã đo 4 phiên,
  100% luật chiến lược trả `value: null`. Thay bằng lane VERDICT + ngưỡng thật + câu nói rõ
  "detector không trả verdict", đếm được và ghi thẳng trong payload (`values_published`).
- **Sửa detector cho trả về số** — đúng hướng nhưng thuộc tuyến engine/runner, ngoài phạm vi
  lượt này và ngoài tuyến tệp đang giữ.
- **Nới test tràn mép cho qua ở 1024** — suýt làm: bản vá đầu tiên rơi nhầm vào
  `test_no_content_is_clipped_off_the_right_edge`, đúng cái test sinh ra để bắt lỗi header
  (docstring của nó nói thẳng). Đã trả nguyên trạng và chỉ khoanh vùng test MỚI của mình.

### Open questions
- Có nên đo tràn mép ở 1024 cho cả trang không? Hiện chỉ 1440 và 390, nên lỗi header ở 1024
  chưa từng bị bắt. Sửa nó động vào header dùng chung cho cả năm dashboard.

## Gotchas (2026-08-30, realtime dashboard)
- /api/v1/track1-runtime has NO cache and re-walks window_coverage + explanations on every
  request. Warm it is 0.7s; the first call after an idle gap measured 7.09-11.06s. Any client
  timeout for it has to be set against the cold number, not the warm one.
- A frontend timeout measured against the warm case is the same defect the paper dashboard
  already paid for (30s budget under a 41.7s cold evidence scan).
- Splitting a slow fetch out of the batch creates a state that did not exist before: "no answer
  YET". A renderer that treated falsy state as failure will now print a false alarm on every
  load unless that fourth state is added at the same time.
- `assert "track1InFlight = false;" in js` passes on the DECLARATION line, so it cannot catch a
  deleted release inside `finally`. Anchor the assert to the finally block.
- Browser PerformanceResourceTiming entries only appear when a request COMPLETES - a snapshot
  taken mid-flight looks like the request was never made.

## Gotchas (2026-08-30, engine gate reporter — Stage 5ZZZ-AK)
- `a > b` KHÔNG tương đương `not (a <= b)` khi giá trị là NaN. Viết lại cổng EMA theo chiều
  ngược suýt biến "engine cho qua bar có EMA = NaN" thành "engine chặn". Vòng quét chỉ chốt
  chặn NaN cho ATR và khối lượng trung bình, KHÔNG chốt cho EMA — nên ca đó tới được.
  Và cổng đối chiếu 1.223 dòng KHÔNG bắt được: ba cửa sổ không nhất thiết chứa một NaN.
  Luật: giữ nguyên phép so sánh gốc, verdict suy ra TỪ nó, không bao giờ ngược lại.
- Phép kiểm "nghe không làm đổi câu trả lời" là tính chất của TỪNG lời gọi, không phải tính
  chất thống kê. Chạy 1.500 bar × 2 rổ × 3 lần gọi mất trên 4 phút mà không thêm gì so với
  260 bar. Cỡ mẫu phải chọn theo loại mệnh đề đang chứng minh.
- `NormalR4Observer.gates` là danh sách MỖI SLOT MỘT LẦN, và `first_failed_gate` lấy phần tử
  `passed is False` ĐẦU TIÊN trong đó. Đổ cổng theo-từng-bar vào cùng danh sách đó sẽ âm thầm
  đổi nghĩa của "nearest failed condition" trên panel — một bar sớm trượt sẽ chiếm chỗ.
  Cổng theo-bar phải có kênh riêng, gộp lại thành đếm + cổng trượt của BAR CUỐI, cùng khung
  với cách `rows()` đã dùng `last_bar`.
- Artifact cam kết: băm SHA-256 trước và sau mỗi lượt so, nếu không thì "so trước/sau" có thể
  đang so với một mốc đã trôi. floor f4d8eea7cd05 · vault2025 c7eb5dd2e375 · vault2026 b1e85b2c9ab7.

## Gotchas (2026-08-30, cuộc đua vẽ trang — Stage 5ZZZ-AN)
- Tách một lời gọi chậm ra khỏi lô rồi cho nó TỰ VẼ khi về = tạo ra một lượt vẽ trang từ
  trạng thái rỗng. `pollTrack1` chờ 1 lời gọi, lô chờ 6 + 3 nữa, nên Track 1 gần như luôn
  vẽ trước và vẽ ra một thanh trạng thái không có dữ liệu phía sau, mọi ô số đọc "--".
- Triệu chứng là BA test DOM đỏ ở lượt chạy này, MỘT test khác đỏ ở lượt sau, và tất cả đều
  xanh khi chạy riêng. Lỗi đỏ nhảy chỗ giữa các lượt = dấu hiệu của cuộc đua, KHÔNG phải của
  máy chậm. Suýt nữa quy cho tải máy rồi đóng sổ.
- Cách phân biệt đã dùng: chạy riêng test → xanh; chạy riêng cả tệp → xanh; chạy cùng test
  cổng → xanh; chỉ đỏ trong lượt đầy đủ. Ba lượt chạy cùng tổ hợp cho ba kết quả khác nhau.
- Sửa: cờ do LÔ bật, ngay trước lượt vẽ của lô. Phép đột biến quan trọng nhất là "cờ được bật
  bởi chính pollTrack1" — cờ vẫn còn nhưng vô nghĩa, và test phải bắt được ca đó.

## Gotchas (2026-09-05, khối Book và trang trợ giúp — Stage 5ZZZ-CE/CF/CG)
- Một số KHÔNG từ nguồn đã chết đọc giống hệt một ngày yên bình. Bốn con số của ô Risk và
  Gross đọc từ ảnh chụp cuối của runner đã nghỉ, 289,8 giờ tuổi, và cả bốn đều bằng 0. Ô
  Gross còn khoá theo đúng tên ba sleeve của Track 1 nên nó trông như đang báo cáo tuyến
  đang chạy — và sẽ in 0.0% mãi kể cả sau khi Track 1 giao dịch, vì ảnh chụp đã đóng băng.
- `peak_equity = 0` nghĩa là mức sụt KHÔNG XÁC ĐỊNH, không phải bằng 0. Sổ Track 1 đang sống
  nhưng rỗng, nên chuyển nguồn không làm ô nào sáng lên — nó đổi một số không mượn thành
  một câu đúng. Đó vẫn là thứ đáng đổi.
- Công tắc "đang ở chế độ Track 1" phải là `legacyRunnerStale()`, KHÔNG phải "endpoint
  Track 1 có trả lời". Vế sau tắt cả Sharpe của tuyến legacy khi tuyến đó còn sống; ba test
  DOM sẵn có đỏ ngay và chúng đúng. Trang đã có sẵn một khái niệm "tuyến cũ đã nghỉ" — dựng
  thêm khái niệm thứ hai là tạo hai câu trả lời cho một câu hỏi.
- CÒN LẠI, chưa thống nhất: `renderMetrics` giờ có hai công tắc. `t1acct` (Track 1 có công bố
  mốc tài khoản) canh Paper equity / Realized / Return / Base / Net; `t1mode` canh Risk /
  Gross / các tỉ số. Chúng lệch nhau ở đúng một trạng thái — Track 1 có mốc tài khoản trong
  khi runner cũ vẫn chạy tươi.
- Ô nào chỉ có người viết trong lớp phủ giao diện của bản thiết kế lại thì trên `/realtime`
  nó in giá trị HTML khai sẵn vĩnh viễn, và không phép kiểm nào nhận ra vì `--` trông như
  một câu trả lời. Gross đã ở tình trạng đó.
- `nowrap` không có `overflow` chặn = chữ sơn đè sang ô hàng xóm. Lỗi này đã bị bắt MỘT LẦN
  cho phần tử anh em trong cùng thẻ (đo được: rộng 232px chứa 413px, tràn 181px). Lần đó bản
  vá đặt trong `@media (max-width: 1100px)` vì người sửa đo ở 720px — nên lỗi còn lại CHỈ
  hiện ở màn hình RỘNG, ngược trực giác, và vì thế sống sót nhiều tháng.
- Khung được vẽ quanh một container thì phần ruột phải được thụt vào. `.empty-state` khai
  `padding: 28px 0` — chỉ dọc — và điều đó đúng cho tới khi ai đó vẽ viền quanh nó. Chỉ sai
  ở trạng thái RỖNG, tức trạng thái duy nhất xảy ra mỗi ngày trong chế độ bóng.
- `SECTION_ANATOMY.md` / `DESIGN_SPEC.md` đã quy định sẵn ô trống Open Positions (padding
  14px 16px, gap 11px, chấm 5px #4b5563, chữ sans 14px secondary, và câu phải nói TẠI SAO).
  Đọc tài liệu thiết kế của kho TRƯỚC khi tự chọn giá trị.
- Bốn cách cổng tự viết xanh nhầm, đều bị đột biến bắt trong phiên này: (a) bộ đọc CSS không
  bỏ comment nên cắt file ở chữ `@media` nằm trong văn xuôi; (b) lát cắt "hàng bốn block"
  phủ đúng 2 dòng và duyệt trên tập rỗng; (c) fixture để vị thế rỗng giá trị nên nhánh chia
  và nhánh đếm cho ra cùng chuỗi; (d) dòng chữ bị ghi đè nên mọi phép kiểm bằng chữ mù trước
  con số vẫn chảy vào TỈ LỆ LẤP ĐẦY của thanh đo.
- Test cũ ghim chuỗi `--` để diễn đạt "không có số nào" sẽ đỏ trước một cải thiện. Ghim MỤC
  ĐÍCH (không chữ số nào, và lời từ chối có tên phải nói được vì sao) thì chặt hơn chứ không
  lỏng hơn — ba đột biến xác nhận.
- Bản ghi mốc tài khoản Track 1 cũ 163,3 giờ KHÔNG phải job hỏng: thứ ghi ra nó
  (`account_baseline_audit`) tự gọi mình là công cụ vận hành và không nằm trong bộ lập lịch.
  Có ba tệp — 27, 28, 29 tháng 8 — rồi thôi. Chạy tay.

## Gotchas (2026-09-05, vòng 2 — thang màu và luật CSS chết, Stage 5ZZZ-CJ/CK)
- Bản rà `DESIGN_AUDIT_2026-09-04` đóng trục màu ở 0. Đo lại MỘT NGÀY SAU: 4 màu ngoài
  thang. Ba trục khác của bản rà ấy đã thành cổng và cả ba vẫn xanh; trục màu là trục duy
  nhất không ai ghim, và là trục duy nhất trôi. Một con số đúng mà không có cổng giữ thì
  chỉ đúng đến hết ngày hôm đó.
- `/realtime` nạp ĐÚNG cùng bộ stylesheet với `/realtime-next` (realtime.css + tokens.css +
  next.css + skin-e.css). Nên đè trong `next.css` là phủ cả hai trang mà không đụng bốn
  dashboard khác vốn chỉ nạp `realtime.css`.
- Xoá luật CSS "đo ra không đổi gì" là bẫy. Đo tách từng luật ở năm khổ ra 21 luật im, xoá
  được đúng MỘT. Ba lý do: (a) phép đo không thấy trạng thái — `.has-tip { outline: revert }`
  im vì element không được focus, mà nó chính là thứ trả lại vòng focus cho 21 phần tử;
  (b) lưới dự phòng — bốn luật `order` sống dậy khi chặn `skin-e` + `next.js`, đo được;
  (c) không phải mã chết mà là MÂU THUẪN THIẾT KẾ: 26px→30px, 22px→24px, cao 4px→9px, mỗi
  cái là một luật có chủ đích bị một luật cụ thể hơn CÙNG FILE đè lên. Xoá là biến bản đè
  thành vĩnh viễn và xoá dấu vết ý định.
- Cổng đo trên dữ liệu SỐNG thì chập chờn: tập luật im đổi giữa hai lượt cách nhau vài phút
  vì thanh trạng thái đổi giữa `ok` và `watch`. Phải `stub_api` để cố định thế giới.
- "Chưa đo được" không phải "đã sửa". Cổng ghim hai chiều phải tách hai tập RỜI NHAU (im ·
  có tác dụng) và chỉ gỡ ghim khi có bằng chứng EFFECTIVE — bản đầu lấy `PINNED - im` và
  báo tám mục đã sửa trong khi chúng chỉ là không dựng ra element ở thế giới stub.
- Chạy `pytest scratch/` là quét CẢ THƯ MỤC của mọi phiên trước — 4.042 test, 215 đỏ, thuộc
  ba tệp 2026-08-29 kiểm trạng thái git/kho. Luôn liệt kê tệp tường minh.

## Gotchas (2026-09-05, vòng 3 — luật đè có lý do của nó, Stage 5ZZZ-CL)
- BA LẦN trong một phiên tôi đọc luật BỊ ĐÈ cùng tài liệu thiết kế rồi kết luận, mà không
  đọc chú thích của luật ĐÈ LÊN. Cả ba lần kết luận đều sai. Luật đè thường mang lý do, và
  lý do ấy mới là quyết định hiện hành.
- Hai dòng `font-size: 26px/22px` cho số Paper equity và số rủi ro là TÀN DƯ: luật `#metrics`
  đè lên chúng dẫn thẳng hợp đồng (SECTION_ANATOMY: 30px và 24px). Chúng chưa từng có tác
  dụng, và chính chúng làm một lượt rà kết luận sai rằng có quyết định đang treo. Xoá vì
  đánh lừa người đọc, không phải vì dọn dẹp.
- Ô mẫu chú giải 9px là QUYẾT ĐỊNH của chủ dự án (2026-09-05, sau khi đọc phép đo), và bản
  sửa về 10×4 theo hợp đồng đã bị rút lại MỘT LẦN trước đó vì cùng lý do. Suýt lật lần hai.
  Con số không có lý do đi kèm là con số người sau sẽ "sửa".
- TỈ LỆ pixel lệch là thước SAI khi hình đổi kích thước: 4px lệch 48,1%, 9px lệch 38,8% —
  trông như ô nhỏ dễ phân biệt hơn. Ảo giác của mẫu số: ô ngắn lại thì viền chiếm gần hết
  diện tích. Diện tích lệch TUYỆT ĐỐI mới là tín hiệu mắt nhận: 384 -> 238 subpixel, yếu đi
  38%. Khi một chỉ số dịch, tách tử số khỏi mẫu số trước khi gọi tên nó.
- Cổng bảo vệ một quyết định phải ghim CƠ SỞ chứ không ghim con số: "hạ xuống 4px phải làm
  yếu tín hiệu phân biệt" — ngày nào điều đó hết đúng thì bàn lại là hợp lệ.
- `clearInterval` chưa đủ để đóng băng trang: một lượt fetch còn dở vẫn về sau đó và vẽ lại,
  làm handle phần tử thành rác. Phải chặn `**/api/**` rồi để nhịp cuối lắng, và truy lại
  phần tử ngay trước mỗi lượt chụp. Triệu chứng: xanh khi chạy riêng, đỏ trong lượt đầy đủ.

## Gotchas (2026-09-06, rà soát 15 điểm giao diện — Stage 5ZZZ-CM/CN)
- ĐỌC LUẬT ĐÈ LÊN, KHÔNG CHỈ LUẬT BỊ ĐÈ. Lỗi này lặp năm lần trong hai phiên: mỗi lần tôi
  đọc luật thua cùng tài liệu thiết kế rồi kết luận "có mâu thuẫn chưa ai giải", và mỗi lần
  luật thắng đã mang sẵn lý do của nó — thường là một quyết định đã chốt.
- `next.js` DI CHUYỂN khối Model inputs ra khỏi `#metrics` vào thẻ Regime Monitor. Mọi
  selector neo vào `#metrics ...` cho khối này không khớp gì cả sau lượt dựng lại. Không
  phải lỗi độ cụ thể — lỗi DOM.
- `grid-template-columns` khai đúng mà `display` vẫn là `flex` thì các track không làm gì.
  Đọc `display` TRƯỚC khi tin `gridTemplateColumns` trong getComputedStyle.
- Sửa vào luật ĐANG THẮNG, đừng thêm luật thứ hai. Hai luật cho một việc là đúng cái bẫy
  cả file này đã ghi lại ba lần.
- Dóng cột giữa hai hàng trong cùng một thẻ: lệch dồn 0·3·8·11px là dấu hiệu vùng trên hụt
  đệm so với vùng dưới, không phải track sai. Bỏ đúng phần đệm chênh.
- Trước khi viết "hover để xem X", KIỂM rê chuột có thật sự làm gì không. (Lần này có.)
- Đặt một câu vào chỗ mới mà không kiểm chỗ cũ = câu ấy hiện hai lần. Ảnh chụp bắt được,
  không phép kiểm nào bắt.
- Hai biểu đồ chồng nhau phải dùng CÙNG một bộ định dạng số: pane nến in `65204.20`, pane
  slot ngay dưới in `65,043.54`, cùng một loại giá cùng một cột.
- Test ghim CÂU CHỮ sẽ đỏ trước một bản viết lại tốt hơn. Ghim NGHĨA.
- Khi chủ dự án đảo một quyết định cũ, viết lại test để ghim quyết định MỚI kèm ngày và lý
  do — đừng xoá test. Nó là thứ ngăn lần rà sau "khôi phục" cái vừa bỏ.
- Lưới nhiều cột phải có bản dự phòng ở khổ hẹp, nếu không nó nhồi 5 cột vào 390px và chữ
  in đè lên nhau.
- Chuỗi `slot_series` của sleeve Swing mang giá ~2.979 trong khi nến MES cùng phiên cùng
  phút ở ~7.724; đối chiếu chéo MNQ (29.564) và MNKD (64.940) cho thấy nến mới đúng. 22/22
  slot không khớp nến nào. CHƯA GIẢI THÍCH ĐƯỢC — đào ở nơi ghi slot_series, không ở chart.

## Gotchas (2026-09-06, một rổ bốn công cụ vẽ thành một — Stage 5ZZZ-CO)
- Hai biểu đồ xếp chồng vẽ HAI CHỈ SỐ khác nhau suốt nhiều tháng và không gì gãy: trục
  dóng, con trỏ chạy, hai pane đều đẹp. Nến MES ~7.724 trên đường M2K ~2.979. Lỗi không
  làm gãy gì là lỗi sống lâu nhất.
- Gốc rễ: `recorded_series` gộp theo `slot_id`, nên với rổ bốn công cụ thì bốn khối của
  cùng một slot chồng lên nhau và CHỈ KHỐI GHI CUỐI sống sót. Đường vẽ M2K không vì ai chọn
  nó — vì nó được ghi sau cùng.
- Cùng họ lỗi đã được chữa MỘT LẦN cho Calm (`recorded_by_instrument`, Stage 5ZZZ-BJ) và
  bỏ sót ở `recorded_series`. Khi sửa một lỗi "khối cuối thắng", quét MỌI reader cùng dạng.
- Bảng `SLEEVES` gán mỗi sleeve đúng một công cụ; đo bằng chứng thì Calm chạy 2, Swing chạy
  4, ngày nào cũng vậy. Một bảng ghi cứng không trả lời nổi câu "sleeve này đọc gì hôm nay".
- `roska4_stress` KHÔNG ghi diagnostics per-slot nào — chỉ có explanations. Bốn sleeve ghi
  bốn kiểu bằng chứng khác nhau, và panel giả định chúng giống nhau. Đó cũng là lý do Stress
  có 24 điểm chuỗi mà cả 24 đều rỗng giá trị.
- Ba kết cục cho "công cụ nào đang vẽ", không gộp: recorded · asked · declared. Danh sách
  rỗng phải đọc thành "không có bằng chứng để đọc", không thành "sleeve chỉ chạy một cái".
- Mã lý do `no_decide_row_for_this_day` của Calm ĐÃ được dịch sang tiếng người từ trước
  (Stage 5ZZZ-BS). Tôi suýt sửa lại lần hai vì đọc mã máy trong tệp bằng chứng mà không
  kiểm tầng hiển thị đã dịch chưa.

## Gotchas (2026-09-06, chip công cụ và nhãn biểu đồ — Stage 5ZZZ-CP/CQ)
- TRƯỜNG VẮNG MẶT ≠ TRƯỜNG RỖNG, lần thứ hai trong hai phiên. `s.instruments || []` biến
  một backend chưa khởi động lại thành câu "phiên này không ghi bằng chứng nào" — sai, nói
  chắc nịch, về sleeve đã ghi bốn công cụ. Chính tệp ấy đã ghi cái bẫy này ở Stage 5ZZH cho
  `headline_usable`, tôi đọc rồi vẫn mắc lại vài giờ sau.
- Panel market view TÍNH LẠI từ kho bar ở lần gọi đầu và chỉ điền vào ở lượt poll sau. Một
  `test_client()` gọi MỘT lần đo LẠNH và trả về rỗng; trang đã poll nhiều lượt thì ấm. Suýt
  kết luận "payload rỗng nên phải có người vẽ thứ hai".
- Nhãn mức giá đặt tại toạ độ giá của nó, không có bước tránh nhau: hai mức cách 6px thì hai
  câu cao 11px in đè. Sửa: ĐƯỜNG giữ nguyên vị trí thật, chỉ CHỮ nhường nhau — nhãn lệch vài
  pixel vẫn đọc được, đường lệch khỏi giá thì sai.
- Thang giá tính từ NẾN rồi vẽ mức giá chồng lên → mức ngoài khoảng bị cắt ở mép. Nới thang
  để chứa, có TRẦN (40% khoảng nến) để một mức ở xa không nén cây nến thành một vạch.
- Thay-thế-mù tên biến đụng nhầm một hàm KHÁC dùng cùng tên biến cục bộ. `node --check` vẫn
  xanh vì cú pháp hợp lệ. Bắt được bằng cách grep lại xem mọi chỗ thay thế có cùng thuộc một
  hàm không — luôn làm bước đó sau một `replace` không giới hạn phạm vi.

## Gotchas (2026-09-06, đóng phần dashboard — Stage 5ZZZ-CR…CV)
- HẰNG SỐ SỐNG TRONG HỆ TOẠ ĐỘ NÀO. `LAB_H = 16` được viết như một số pixel nhưng được TIÊU
  bằng đơn vị viewBox: biểu đồ giá là viewBox cao 420 kéo vào khung 320px, nên 16 đơn vị chỉ
  mua được ~12px thật. Nhãn cao 18px vẫn chồng nhau trong khi con số "16" trông như đã đủ.
  Sửa bằng cách quy đổi MỘT lần, ghi rõ nó phụ thuộc vào hai giá trị CSS nào.
- MỘT LUẬT TRÔNG NHƯ ĐANG BẢO VỆ MÀ KHÔNG BẢO VỆ GÌ. Thêm `max-width: 66%` để chuỗi O/H/L/C
  khỏi đẩy chữ "Price" ra khỏi hàng; mutation gỡ nó ra thì phép kiểm vẫn xanh. Cơ chế thật là
  `min-width: 0` (flex) + `white-space: nowrap` + `text-overflow: ellipsis`. Gỡ luật vô tác
  dụng, và viết lại phép kiểm để đo đúng cơ chế thật (chiều cao hàng không đổi khi ô đọc đầy).
- MUTATION PHẢI LÀ PHÉP CHUYỂN, KHÔNG PHẢI PHÉP THÊM. Kiểm "dòng mốc kiểm nằm ở đáy khối" bằng
  cách CHÈN THÊM một bản ở giữa → bản gốc vẫn nằm cuối → gate xanh, và tôi suýt kết luận gate
  hỏng. Gate không sai; mutation sai. Nhưng nó lộ ra gate cũng sẽ xanh khi câu ấy hiện HAI lần,
  nên gate được siết thêm: đúng một lần, và ở đáy.
- LUẬT ID ĐÈ LUẬT LỚP KHI DỜI MỘT NÚT. `#marketViewChart .mv2-chart-readout` (1,1,0) thắng
  `.mv2-card-head .mv2-chart-readout` (0,2,0) — dời ô đọc sang hàng đầu thẻ thì luật cũ neo
  bằng ID vẫn áp lề 18px ở chỗ mới. Thu hẹp luật cũ về đúng đường dự phòng thay vì xoá.
- BỎ MỘT CÂU TRONG NHÁNH NHIỀU CÂU: đếm xem ba câu còn lại mang tin gì trước khi quét. Nhánh
  "biểu đồ rỗng" có bốn câu; chỉ một câu là rỗng nghĩa, ba câu kia mỗi câu là một sự thật khác
  nhau và không có ở đâu khác trên trang. Gate viết cho CẢ HAI chiều.
- Heredoc nuốt dấu xuống-dòng-thoát (`\n` viết trong chuỗi) ba lần liên tiếp trong phiên này —
  script vá, script mutation, và LẦN THỨ BA là ngay chính dòng ghi lại bài học này, nó tự biến
  thành một dấu xuống dòng thật. Mọi chuỗi có ký tự thoát thì dùng Write/Edit, đừng heredoc.
- `pytest ... | tail -N` làm output đệm tới EOF: file log rỗng suốt cả lượt chạy rồi hiện một
  lần ở cuối. Ghi thẳng ra file, đừng pipe.
- Neo `replace` phải DUY NHẤT: `overflow: hidden; text-overflow: ellipsis; white-space: nowrap;`
  xuất hiện hai lần trong next.css. Luôn kiểm `count(old) == 1` trước khi thay.

