# Paper Input Review Worksheet

Muc dich: gom cac artifact da tim thay thanh cau hoi review ro rang truoc khi dua vao `monitor/paper_inputs.json`.

Quy tac:

- File nay khong phai active input. Dashboard khong doc file nay.
- Chi record nao co verdict cua operator moi duoc chep sang `monitor/paper_inputs.json`.
- Candidate co marker test/mock bi tach rieng va khong duoc dung de PASS gate.
- Khong sua engine. Neu can engine moi co du lieu sach thi ghi vao muc can quyet dinh.

## 1. STP verification

Gate can chung minh: position co stop dung, khong false halt, khong double-STP.

Input active neu duoc review:

```json
{
  "date": "YYYY-MM-DD",
  "verified": true,
  "false_halt": false,
  "double_stp": false,
  "evidence": "path:line..."
}
```

### Candidate production co the review

| ID | Ngay | Noi dung | Evidence | Can ban xac nhan |
| --- | --- | --- | --- | --- |
| STP-2026-08-11-placement | 2026-08-11 | 3 stop orders duoc accepted cho MYM, MES, M2K. | `live_day_0811.log:14927`, `live_day_0811.log:14930`, `live_day_0811.log:14933` | Ngay 2026-08-11 co the xem la STP verified khong? Co false halt nao khong? Co double-STP/orphan working order nao khong? |
| STP-2026-08-13-current-protection | 2026-08-13 | Current state co M2K LONG x1 voi `stop_order_id=288`, `stop_price=3020.24`; IBKR fresh co M2KU6 LONG x1 va working STP SELL x1 order_id=288 aux_price=3020.2. | `GET /api/v1/broker` at `2026-08-13T09:31:06Z`; `GET /api/v1/runner-positions`. | Da add vao `monitor/paper_inputs.json` nhu current IBKR-reconciled STP verification pass. |

Log check 2026-08-11:

- Scan `live_day_0811.log,scheduler_0811.log` for `B3 HALT`, `STP ORPHAN`, `STP UNPROTECTED`, `place_stop FAILED`, `double`, `duplicate`, `B3 STP-VERIFY`, `B3 STP EXIT`.
- Ket qua: chi co 3 dong `place_stop: accepted`; khong co match cho false halt / orphan / duplicate trong pattern scan.
- Gioi han: absence of log pattern khong tu no chung minh broker truth; no chi la negative evidence trong retained logs. De pass bang IBKR reconcile cho ngay lich su, can retained broker snapshot tai thoi diem do.

Neu ca hai candidate tren duoc xac nhan tot, record de add co the la:

```json
{
  "date": "2026-08-11",
  "verified": true,
  "false_halt": false,
  "double_stp": false,
  "evidence": "live_day_0811.log:14927, live_day_0811.log:14930, live_day_0811.log:14933"
}
```

### Candidate bi loai / khong dung truc tiep

| ID | Ly do khong dung | Evidence |
| --- | --- | --- |
| STP-2026-08-10-mock-b3 | Co marker mock/test: `_RecordingMockBroker`, `ibkr-456`, `ibkr-789`, `stp-MES-0`; reader co `_TEST_MARKERS` va dang drop cac dong nay. | `scheduler_0810.log:2`, `scheduler_0810.log:3`, `scheduler_0810.log:6`, `scheduler_0810.log:19`, `scheduler_0810.log:21` |

## 2. TWS restart nights

Gate can chung minh moi dem:

- `restart_proven=true`: TWS/IBGateway da restart that.
- `runner_resumed=true`: runner/dashboard da doc lai state sau restart.
- `broker_verified=true`: broker truth da doi chieu sau restart.
- `evidence`: path:line hoac command output co ngay gio.

Dang thieu quyet dinh spec:

| Field | Can ban chot |
| --- | --- |
| `tws_restart_spec.min_nights` | Chot: 10 dem pass. Da add vao `monitor/paper_inputs.json`. |

Artifact hien co:

| Loai | Ket qua |
| --- | --- |
| Candidate logs | Reader thay 242 connectivity/restart candidate lines tren cac ngay `2026-08-10`, `2026-08-11`, `2026-08-12`, `2026-08-13`. |
| Structured proof | Chua co record trong `monitor/paper_inputs.json`. |

Khong tu dong dung candidate logs vi reconnect/disconnect text khong tu chung minh day la mot restart-night workflow da pass.

## 3. Manual interventions

Input active neu co:

```json
{
  "ts": "YYYY-MM-DDTHH:MM:SSZ",
  "reason": "why operator acted",
  "action": "what was done",
  "resolution_status": "resolved",
  "post_action_verified": true,
  "evidence": "path:line..."
}
```

Artifact hien co:

| Loai | Ket qua |
| --- | --- |
| Candidate logs | Reader thay 128 operator-action candidate lines tren `2026-08-10`. |
| Structured ledger | Chua co. |

Can ban review rieng: ngay 2026-08-10 co action that cua operator khong, hay chi la log warning/test-like instruction?

## 4. Roll / C2 slippage

Input active neu co:

```json
{
  "date": "YYYY-MM-DD",
  "inst": "MES",
  "ticks": 0,
  "evidence": "path:line..."
}
```

Artifact hien co:

| Loai | Ket qua |
| --- | --- |
| Raw C2 lines | Co nhieu dong `C2: Roll ... FAILED/UNPROTECTED/Manual verification required` trong `scheduler_0810.log`. |
| Clean slippage lines | Chua thay dong match pattern `C2: Roll ... slippage=` sau epoch. |

Khong dung lam roll slippage input cho den khi co fill/ref ro rang hoac operator review ticks.

## 5. Paper P&L vs backtest

Dang can quyet dinh source. Muc nay se cover Signal/market CLOSE vi C1 da exclude cac close khong co expected close reference sach.

Input active neu co:

```json
{
  "date": "YYYY-MM-DD",
  "actual_equity": 50228.75,
  "expected_equity": 50200.00,
  "evidence": "path:line or reviewed daily compare artifact"
}
```

Can chon mot trong cac nguon:

| Lua chon | Input can co |
| --- | --- |
| Daily backtest expected equity artifact | Ngay, expected equity/P&L, actual paper equity/P&L, diff, evidence path. |
| Session report | Neu `global_index/session_report.py` sinh duoc daily compare co format on dinh. |
| Manual reviewed daily compare | Operator nhap daily expected vs actual vao monitoring input. |

Trang thai hien tai:

| Loai | Ket qua |
| --- | --- |
| Backtest curve | Re-run `python -m global_index.generate_replay_snapshots` ngay 2026-08-13; curve van `generated=2026-08-12`, tuc source data chua phu den 2026-08-13. |
| Structured compare | Da add 3 record `paper_vs_backtest[]` trong `monitor/paper_inputs.json` cho 2026-08-10..2026-08-12, evidence tu `global_index/backtest_curve.json` + `global_index/paper_history.json`. |
| Current day | 2026-08-13 co actual paper mark nhung expected backtest stale through 2026-08-12; khong add active record cho 2026-08-13. |
| Audit report | `monitor/paper_pnl_compare.json` tach `equity_window` va `trade_filter` de khong tron convention. |

Khong dung actual-only de pass/observe gate vi no khong doi chieu duoc backtest. Can expected value tu replay/backtest artifact hoac reviewed session report.

Ket qua audit 2026-08-13:

| Date | Actual equity | Expected equity (account-window) | Diff | Trade-filter realized diff | Note |
| --- | ---: | ---: | ---: | ---: | --- |
| 2026-08-10 | 50162.00 | 50000.00 | +162.00 | -110.00 | Epoch day: paper_history level co carried/mark component; trade_log realized MNKD -110. |
| 2026-08-11 | 50228.75 | 49881.29 | +347.46 | +75.46 | Paper MES/MYM exits better than backtest, NKD timing differs. |
| 2026-08-12 | 50228.75 | 49836.85 | +391.90 | +119.90 | Backtest MNKD short exits 2026-08-12; paper MNKD short exited 2026-08-11. |
| 2026-08-13 | 50228.75 | n/a | n/a | +119.90 | Backtest curve stale through 2026-08-12. |

Giai thich lech hien tai:

- `account-window` la convention cua runner: `account + (bt[date] - bt[system_epoch])`.
- `trade-filter` la y tuong "loc trade co entry_day >= paper epoch". Den 2026-08-12, backtest realized -163.15, paper trade_log realized -43.25, paper tot hon +119.90.
- Paper NKD exit timing khac backtest: backtest MNKD LONG 2026-08-10 exit 2026-08-11, paper exit 2026-08-10; backtest MNKD SHORT 2026-08-11 exit 2026-08-12, paper exit 2026-08-11.
- `paper_history` vs `trade_log` khong dong nhat o epoch: paper_history 2026-08-10 = 50162.00 trong khi trade-filter realized = -110.00. Cho nen dung equity-level diff de danh gia edge can ghi ro convention, khong duoc doc nhu pure trade P&L.

## Cau hoi can ban tra loi truoc de ghi active input

1. Voi `STP-2026-08-11-placement`: ngay 2026-08-11 co duoc tinh la STP verification pass khong?
2. Neu co: co false halt nao trong ngay do khong?
3. Neu co: co double-STP/orphan working order nao trong ngay do khong?
4. TWS restart gate can toi thieu bao nhieu dem pass: chot 10 dem, da add.
