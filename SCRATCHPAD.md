## Gotchas

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
