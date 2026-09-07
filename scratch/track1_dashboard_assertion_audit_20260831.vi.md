# Báo cáo audit dashboard Track 1 - 2026-08-31

Phạm vi: `/realtime` và `/paper` tại `http://127.0.0.1:5002`, dùng backend đang chạy sẵn trên port 5002.

Tôi không restart backend vì `python monitor\ops.py status` không đọc được process scan do `Access denied` và lúc đầu báo mode không chắc chắn. Để tránh đổi trạng thái vận hành, audit chỉ đọc API/DOM và không sửa runtime, scheduler, strategy logic hay evidence generated.

Artifact đo chính:

- `scratch/track1_dashboard_inventory_20260831.json`
- `scratch/track1_assertions_audit_1365.png`
- `scratch/track1_assertions_audit_390.png`
- `scratch/paper_assertions_audit_1365.png`
- `scratch/paper_assertions_audit_390.png`

## Tóm tắt

Audit vòng 2 tìm được 3 lỗi đã xác minh:

1. `/realtime`: NKD setup card ghép sai giá và thời điểm trong dòng `market ref`.
2. `/paper`: `Overall status` không phản ánh severity xấu nhất đang hiện trong chính danh sách blocker.
3. `/paper`: dòng source/timestamp làm người đọc hiểu nhầm timestamp của runner-state là timestamp của toàn bộ `paper_evidence`.

Các nhóm lỗi cũ như `Number(null) -> 0`, `NOT REPORTED` tràn lan, và thiếu nhãn stored session đã được kiểm lại và không còn xuất hiện trong DOM/payload hiện tại.

## Finding 1 - Đã xác minh

### Trang nói gì

Trên `/realtime`, NKD setup card render:

`market ref 66,620.00 · 02:55 ET`

Cùng card render các reading recorded:

- `Close used 66,440.00`
- `Daily ATR 55.36`
- `Volume 0`
- `Average volume (10 bars) 32`
- source badge: `RECORDED`

### Sự thật là gì

Dòng header đang ghép một giá và một thời điểm từ hai sự kiện khác nhau.

Đo từ `/api/v1/track1-market-view`:

| Trường | Giá trị |
| --- | --- |
| Session của market view | `2026-08-31` |
| Chart bars của NKD lấy từ | `bars_session_date=2026-08-28` |
| Stored bar lúc `02:55` | close `66,640.00` |
| Stored context bar cuối | `03:05` close `66,620.00` |
| Recorded slot-series lúc `02:55` | close `66,440.00` |

Code path:

- `realtime.js:2308` lấy `lastBar` từ `s.bars[s.bars.length - 1]`
- `realtime.js:2312` lấy `lastSlot` từ slot cuối không phải future
- `realtime.js:2398` in `lastBar.close` cạnh `lastSlot.time_et`

### Measurement tách được lỗi

Playwright đọc DOM ở 1365px và 390px đều thấy dòng `market ref 66,620.00 · 02:55 ET`. Payload cho thấy `66,620.00` là giá của context bar cuối `03:05` ngày `2026-08-28`, không phải giá slot `02:55` và cũng không phải recorded slot close ngày `2026-08-31`.

### Rủi ro vận hành

Operator có thể tưởng `66,620.00` là market reference tại slot quyết định `02:55 ET`. Sai theo cả hai hướng:

- stored chart `02:55` close là `66,640.00`
- recorded runtime slot close là `66,440.00`

Nhãn hiện tại làm một stale/context price đọc như slot-timed decision price.

### Layer sở hữu

Display layer. Backend đã publish riêng các fact cần thiết: `bars`, `bars_session_date`, `bars_note`, `slot_series`, setup metrics, và slot times. UI là nơi ghép sai.

### Test nên thêm khi sửa

DOM fixture có:

- `bars=[{time:"03:05", close:66620}]`
- last slot `02:55`
- `strategy.slot_series[-1].close=66440`

Assert setup header hoặc dùng đúng slot-series close cho slot reference, hoặc ghi rõ stored context bar time/date. Nếu bỏ fix, test phải quay lại thấy `market ref 66,620.00 · 02:55 ET` và fail.

## Finding 2 - Đã xác minh

### Trang nói gì

Trên `/paper`, top-level readiness render:

`Overall status SPEC BLOCKED`

Reason:

`At least one gate needs a quantified decision before it can pass`

Nhưng ngay trong cùng first screen, danh sách `What blocks live now` render các blocker `BREACH`, gồm:

- `BREACH EPOCH P&L strategy -$43.25 / broker -$1,123.75`
- `BREACH DATA FRESHNESS regime=OK | model=URGENT | refreeze_pending=False`

### Sự thật là gì

`Overall status` không lấy severity xấu nhất của các blocker đang visible. Nó chỉ tính từ `payload.gates`, trong khi blocker list được dựng từ cả `gates` và `coverage`.

Đo từ `/api/v1/paper-evidence`:

| Collection | Status liên quan |
| --- | --- |
| `payload.gates` | `PENDING`, `STRUCTURAL_GAP`, `QUALITY_BREACH`, `EXPLAINED` |
| `payload.coverage.paper_vs_backtest` | `BREACH` |
| `payload.coverage.data_freshness` | `BREACH` |
| `payload.coverage.open_incidents` | `BREACH` |
| DOM blocker cards | Có `BREACH` trước dòng top-level `SPEC BLOCKED` |

Code path:

- `paper.js:411` dựng blocker cards từ coverage rows như `data_freshness`, `open_incidents`, `pnl_thresholds`
- `paper.js:2406` tạo `statuses` chỉ từ `gates`
- `paper.js:2432` chọn `#overallStatus` từ list gate-only đó

### Measurement tách được lỗi

Playwright đọc `/paper` ở 1365px và 390px:

- `overall=SPEC BLOCKED`
- `readinessBlockers` bắt đầu bằng `BREACH EPOCH P&L`
- cùng text có `BREACH DATA FRESHNESS`

API xác nhận các breach này đến từ `payload.coverage`, không phải `payload.gates`.

### Rủi ro vận hành

Operator đọc top line có thể nghĩ vấn đề chính là thiếu/spec evidence. Nhưng chính page bên dưới đang nói có observed breach. Hai trạng thái dẫn tới hành động khác nhau:

- `SPEC BLOCKED`: cần định lượng rule hoặc thêm evidence.
- `BREACH`: cần sửa, classify, hoặc chặn promotion.

### Layer sở hữu

Display layer, trừ khi backend contract định nghĩa rõ rằng overall readiness chỉ được tính từ gates. Vì blocker cards đã coi coverage là readiness evidence, top-level status nên dùng cùng severity set hoặc đổi nhãn thành gate-only status.

### Test nên thêm khi sửa

DOM fixture:

- `gates=[{status:"STRUCTURAL_GAP"}]`
- `coverage=[{key:"data_freshness", status:"BREACH"}]`

Assert `#overallStatus` là `BREACH`, hoặc nhãn top-level nói rõ nó chỉ là gate status. Nếu bỏ fix, test phải quay lại `SPEC BLOCKED` và fail.

## Finding 3 - Đã xác minh

### Trang nói gì

Trên `/paper`, source line render:

`Paper epoch 2026-08-10 | source paper_evidence | observed 2026-08-24T06:58:47.545152Z`

### Sự thật là gì

Timestamp đó không phải observation time của toàn bộ `paper_evidence` payload. Nó được copy từ `state.get("observed_at")`, tức timestamp của `live_state_data.js` / runner-state.

Trong cùng payload còn có nguồn mới hơn:

- `/api/v1/open-issues.observed_at = 2026-08-31T10:20:18Z`
- `paper_vs_backtest.metrics.artifact_freshness.status = CURRENT`
- contract spec guard dùng IBKR contract specs từ current backend cache

Code path:

- `paper_evidence_reader.py:3476` trả `"source": "paper_evidence"`
- `paper_evidence_reader.py:3477` trả `"observed_at": state.get("observed_at")`
- `paper.js:2417` render timestamp đó như timestamp của `paper_evidence`

### Measurement tách được lỗi

| Field | Giá trị |
| --- | --- |
| `/api/v1/paper-evidence.observed_at` | `2026-08-24T06:58:47.545152Z` |
| `/api/v1/paper-evidence.source` | `paper_evidence` |
| `/api/v1/open-issues.observed_at` | `2026-08-31T10:20:18Z` |
| `paper_vs_backtest.metrics.artifact_freshness.status` | `CURRENT` |
| `contract_spec_guard.evidence` | `6/6 local contract spec(s) reconciled to IBKR` |

### Rủi ro vận hành

Operator có thể hiểu nhầm toàn bộ paper evidence bundle đã cũ từ `2026-08-24`, hoặc ngược lại hiểu timestamp runner-state là bằng chứng tất cả source đều được observed lúc đó. Cả hai đều sai: một số row stale theo runner-state, một số row được derive mới hơn, nhưng page collapse thành một timestamp.

### Layer sở hữu

Backend/display contract. Reader nên expose `generated_at` hoặc source timestamp map, hoặc UI nên đổi label thành `runner-state observed`.

### Test nên thêm khi sửa

Fixture backend có runner-state observed `2026-08-24` và open-issues observed `2026-08-31`. Assert top UI không render runner timestamp như timestamp toàn bộ paper-evidence. Nếu bỏ fix, test phải quay lại dòng `source paper_evidence | observed 2026-08-24...` và fail.

## Những điểm đã kiểm và không thành finding

### Đã xác minh

- `/realtime` và `/paper` không overflow ở viewport đã đo. 1365px và 390px đều có `scrollWidth == clientWidth`.
- Track 1 market view hiện không render `NOT REPORTED` trong DOM hiện tại.
- Absence states được tách thành `no verdict`, `not reached`, `no record`, `not yet run`.
- NKD slot chart không còn kéo trục giá xuống zero/negative vì null. Axis nằm trong vùng hợp lý khoảng `66,067.40` đến `66,507.60`.
- `/paper` C1 tách được sample incompleteness khỏi quality breach: render `QUALITY_BREACH`, `sample gate incomplete`, và cảnh báo retest khi scale.
- `/paper` STP panel composite đúng với text hiện tại: verification `PENDING`, placement `BREACH`, current protection `MISSING` -> panel `BREACH`.

### Chưa chứng minh / chưa kiểm được

- Stress và Swing setup assertions chưa kiểm được trong live window. Lúc sweep, hai sleeve này vẫn `WAITING`.
- Daily ATR dùng cho stop sizing chưa được đối chiếu độc lập với order placement/live signal hôm nay.
- Không hard-refresh được browser operator thật vì browser connector trả `No browser is available`; audit dùng Playwright local.
- Chưa mutation-test red-on-removal vì deliverable lần này là findings document, chưa phải patch code.

## Verify đã chạy

- `python -m pytest monitor\test_dashboard_backend.py -k "track1_market_view or market_view or rule_lanes or setup_boundary or reconstructed_today" -q` -> `1 passed`
- `python -m pytest monitor\test_realtime_dom.py -k "market_view or stale_runner_state or scrollwidth or verdict" -q` -> `6 passed`
- `python -m pytest monitor\test_dashboard_backend.py -k "paper or current_protection or stp or ledger_adjustment or C1 or c1" -q` -> `33 passed`

