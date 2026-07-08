# Futures — Bug Sweep Round 2
_Quét hệ thống các path chưa đào sâu. Mọi kết luận trace về code thật._
_2026-07-07_

> Quy tắc: KHÔNG tuyên bố "hết bug" — ghi những gì đã verify và những gì còn cần verify.  
> Mọi line number trace về code hiện tại trên branch `future/incorporation`.

---

## CAT 1 — Live decision path: biến live≠backtest

**Scope**: `global_index/live_decision.py` + grep toàn bộ `pnl_sized` trong codebase.

**Kết luận: `pnl_sized` là pattern duy nhất diverge giữa live và backtest.**

| File:line | Code | Backtest | Live | Trạng thái |
|---|---|---|---|---|
| `live_decision.py:85` | `state.equity += p.pnl_sized` | ledger pnl | 0.0 | H4 fix covers (broker.get_equity() sync) |
| `live_decision.py:122` | `t.get("pnl_sized", 0.0)` | ledger pnl | 0.0 | Residual gap (STRESS_MID same-session) |
| `live_decision.py:124` | `state.equity += newp.pnl_sized` | ledger pnl | 0.0 | Residual gap (STRESS_MID same-session) |
| `runner.py:508` | CLOSE order `pnl_sized=p.pnl_sized` | ledger pnl | 0.0 | Not a bug: IBKRBroker compute từ fill |
| `runner.py:551` | OPEN order `pnl_sized=t.get(...)` | ledger pnl | 0.0 | Correct: live entry chưa có pnl |
| `runner.py:557` | same-day CLOSE `pnl_sized=t.get(...)` | ledger pnl | 0.0 | IBKRBroker sẽ compute từ fill |

Các diverge khác **đều intentional**:
- `t.get("exit")` → None trong live (signal_fn set `exit_day` khi chandelier fire, không pre-compute)
- `contract_month` không có trên OpenPos → live contract switching là IBKR-gated

**Pattern H4 là exhaustive.** Không có pattern ẩn nào khác trong nhóm này.

H4 fix approach đúng: dùng `broker.get_equity()` (total equity sau fills + MTM) thay vì per-fill pnl → backwards-compatible với MockBroker (delta ≈ 0 khi pnl_sized = ledger).

### Residual gap: STRESS_MID same-session

`decide_day()` xử lý STRESS_MID entry+exit atomic (line 123-124): `state.equity += newp.pnl_sized = 0.0`. Sau đó runner gửi OPEN→CLOSE trong OPEN loop (lines 549-557). H4 fix ở step 3 đã chạy TRƯỚC OPEN loop → không capture được STRESS_MID pnl trong cùng session.

Tác động: nếu STRESS_MID lỗ > 4% ngày trong cùng session, HALT_DAY không fire cho các entry SAU STRESS_MID trong cùng run_day. Các session/ngày tiếp theo: H4 sync tại construction picks up real equity → HALT_DAY fire đúng.

**Chấp nhận**: một lần, một event, Stress regime chỉ. Fix đòi refactor decide_day thành 2 pass (close → sync → entry).

---

## CAT 2 — Exec path: fill/partial/reject

**Scope**: `runner.py:505-558`, `ibkr_broker.py:290-356`, `broker.py:40-50`.

### Gap 2.1 — Position removed from state BEFORE CLOSE sent (I4.8)

**Code trace** (runner.py):
```
decide_day()          → state.open_positions = still  ← exits REMOVED (live_decision.py:88)
↓
for p in decision.exits:
    self.broker.send_order(CLOSE ...)   # Fill return value DISCARDED (line 505-508)
```

`send_order()` return giá trị bị bỏ (`for p in decision.exits: self.broker.send_order(...)` — không có `f = ...`). Nếu IBKRBroker.send_order(CLOSE) raise hoặc return FAILED:
1. Runner không biết (return value discarded)
2. Position đã xóa khỏi `state.open_positions`
3. Không có retry (`exit_pending` không tồn tại — grep xác nhận: 0 matches trong runner.py)
4. `_persist_state()` chạy → file ghi position = gone
5. Restart: runner nghĩ closed, IBKR vẫn hold → diverge vĩnh viễn đến khi B3 hoặc manual

Confirm bằng grep:
```
grep "exit_pending"    global_index/runner.py  → 0 matches
grep "_retry_pending"  global_index/runner.py  → 0 matches
```

**Severity**: HIGH cho live. IBKR-gated (A1-A5 đã ghi trong STATUS.md). Nhưng sequence cụ thể "state mutated → CLOSE fail → file persist = silent orphan" chưa có entry riêng.

### Gap 2.2 — Fill.status không implement (A1-A5)

`broker.py::Fill` dataclass:
```python
@dataclass
class Fill:
    inst: str; action: str; direction: str; contracts: int; cluster: str
    pnl_sized: float = 0.0   # no status, no filled_qty, no error_msg
```

ibkr_broker.py:335 comment: "Extend Fill dataclass with status/filled_qty/avg_price/error_msg" — **chưa làm**. Runner không thể phân biệt partial fill, reject, timeout từ Fill object.

### Gap 2.3 — `_retry_pending_exits()` không tồn tại

ibkr_broker.py:307: "exit_pending positions are retried via `_retry_pending_exits()` at next run_day start." — function này không tồn tại trong runner.py. Design comment mô tả intent nhưng không implemented.

**Cả 3 gaps đều IBKR-gated.** Thứ tự implement khi IBKR available:
1. Extend Fill với `status: str` field
2. Check `fill.status` sau mỗi CLOSE → flag exit_pending trên OpenPos
3. Implement `_retry_pending_exits()` ở đầu run_day

---

## CAT 3 — State restart: các điểm ngoài H4

**Scope**: `runner.py:189-285` (B1 restore), `runner.py:295-323` (_persist_state).

### Đúng — các field persist OK

| Field | Persist | Restore | Verify |
|---|---|---|---|
| `peak_equity` | ✓ (line 304) | ✓ (line 274) | HALT tính đúng sau restart |
| `_day_start_equity` | ✓ (line 305-306) | ✓ (line 282-283) | HALT_DAY intraday restart OK |
| `cur_day` | ✓ (line 307-308) | ✓ (line 284-285) | `start_day()` không gọi lại cùng ngày |
| `exit_day` trên OpenPos | ✓ (`_openpos_to_dict:131`) | ✓ (`_openpos_from_dict:147`) | Vị thế cần exit hôm nay được load đúng |
| `pnl_sized` trên OpenPos | ✓ (`_openpos_to_dict:132`) | ✓ (`_openpos_from_dict:148`) | Luôn 0.0 trong live (correct) |

`_last_breaker_level` **KHÔNG persist** (reset "OK" sau restart). Đúng — transition event sẽ re-emit sau restart.

HALT sau restart: `peak_equity` loaded → `status(broker.get_equity())` tính dd = (peak-cur)/peak → HALT nếu ≥ 15%. ✓

### Gap 3.1 — Stale file window giữa decide_day và _persist_state

Sequence trong run_day():
```
decide_day()            ← state mutated (positions updated) — không persist
send_order(CLOSE) ×N    ← up to 265s worst-case (order × fill_time)
send_order(OPEN) ×N     ← ...
_persist_state()        ← file updated — persist window = 265s
```

Nếu crash trong 265s window:
- File = state của run_day trước (old)
- State = đã updated (exits removed, entries added)
- Restart: load old file → "closed" positions reappear → runner tries CLOSE lại
- IBKR đã close → double-CLOSE → position state wrong

**B3 (broker.get_positions()) sẽ catch.** Nhưng B3 không implement (`get_positions()` raises NotImplementedError).

Giải pháp không phải persist more granularly — bất kỳ điểm persist nào đều có race với IBKR fill confirm. Giải pháp đúng: B3 reconcile sau restart.

### Gap 3.2 — Restart giữa partial fill (không thể recover)

Nếu crash sau OPEN order 1 (vào IBKR) nhưng trước OPEN order 2:
- File: old state (không có position 1 hay 2)
- IBKR: position 1 open
- Restart: load old file → IBKR có position 1, runner không biết
- B3 would catch via position reconcile

Hiện tại: B3 không implement → position 1 là orphan cho đến manual.

---

## CAT 4 — n=2 config: code analysis + command

**Code trace**:
- `deploy_sim.py:254-261`: NKD `contracts_by[nkd] = 1` hardcoded ✓, Rổ4 `= n_contracts` ✓
- `generate_replay_snapshots.py:142`: `cb_map["MNKD"] = 1` ✓
- `signal_layer.to_candidate()`: `risk_sized = n × mult × ATR × pv` → đúng cho n=2 ✓
- `guard.admits()`: nhận `risk_sized` đã scale theo n → cap check đúng ✓
- `run_smoke_test.py:208`: `assert n_contracts == 1` → n=2 path **CHƯA BAO GIỜ chạy end-to-end**

Code trông đúng về logic, nhưng chưa verified. **Chạy:**

```powershell
cd d:\raits
python global_index/deploy_sim.py --n-contracts 2 2>&1 | Tee-Object docs\futures\n2_test_output.txt
```

Expect để verify:
1. NKD trade count ≈ n=1 run (NKD không scale → count và pnl giống)
2. Rổ4 trade count có thể giảm nhẹ (thêm cap rejections khi risk_sized × 2)
3. Rổ4 net P&L ≈ 2 × n=1 Rổ4 P&L (trừ rejected)
4. Sizer guard WARNING không xuất hiện (dùng --n-contracts, không --start/--end subset)
5. Không exception, không crash

Nếu NKD P&L tăng gấp đôi → bug trong cb_map NKD.  
Nếu crash với cap/risk error → bug trong scaling path.

---

## CAT 5 — Reconcile edge verification

**Judgment "không cần test edge" — đúng một phần.**

**Backtest mode — OK, coverage đầy đủ:**

| Reconcile script | Coverage | Roll dates | Stress periods |
|---|---|---|---|
| `reconcile_gd0.py` | 2018-2024 full IS | ✓ ~120 rolls (5 insts × 6yr × quarterly) | ✓ COVID, 2022 bear |
| `reconcile_stress.py` | 269 Stress days | ✓ (Stress regime spans rolls) | ✓ all Stress periods |
| `reconcile_nkd.py` | 515 trades 2018-2024 | ✓ NKD quarterly rolls (Mar/Jun/Sep/Dec) | ✓ |
| `reconcile_swing_desired.py` | 20 samples/inst boundary | ✓ | ✓ |

0 mismatches in all 4 → no known issues at roll boundaries or extreme periods in backtest mode.

Ex-div: parquet `adjusted=True` → transparent. Không cần xử lý riêng.

**Live mode — khác hoàn toàn:**

- Reconcile scripts test continuous adjusted parquet ↔ runner → không test live contract switching
- `_handle_rollover()` raises `NotImplementedError` (I5.2)
- Roll dates trong live = đóng front month + mở next month = 2 fills + contract_month field (chưa có)
- **Đây là gap riêng (I5.2), không phải gap trong reconcile**

**Verdict**: Claim "không cần test edge" là đúng cho backtest. Sai nếu muốn "cover live roll dates" — nhưng đó là I5.2, không phải thiếu reconcile coverage.

---

## CAT 6 — Live vs backtest: systematic divergence scan

**Grep toàn bộ `global_index/*.py` và `futures/*.py` cho `pnl_sized` patterns.**

Không có pattern nào ngoài `pnl_sized`. Các live≠backtest còn lại:

| Divergence | Source | Live behavior | Backtest behavior | Design? |
|---|---|---|---|---|
| `pnl_sized=0.0` | live orders | H4 fix handles | ledger value | **Bug — fixed** |
| `exit_day=None` | signal_fn | signal sets later | engine pre-computes | Intentional |
| `contract_month` absent | OpenPos | no field | no field (parquet continuous) | IBKR-gated gap |
| ATR source | `to_candidate()` | live bars from IBKR | parquet historical | May diverge (data quality) |

ATR divergence (last row): `signal_layer.to_candidate()` uses `daily_atr_series.asof(entry_day)`. In live: `daily_atr_series` built from IBKRBroker.fetch_bars() output. If bars differ from parquet (different period, fill, missing data) → `risk_sized` differs → different cap decisions. Not a code bug; data quality issue. Mitigated by `C3` (empty bars alert) and `C6` (lowercase normalization).

---

## Tổng hợp — Checklist pre-live

| Code | Mô tả | Severity | Status |
|---|---|---|---|
| H4 | HALT_DAY equity sync intraday | HIGH | **FIXED** — T29 PASS |
| I4.8 | Exit fail: position xóa khỏi state trước CLOSE sent, Fill discarded | HIGH | **IBKR-gated** — cần Fill.status + exit_pending |
| A1-A5 | Fill.status / exit_pending / _retry_pending_exits | HIGH | **IBKR-gated** |
| B3 | Runner file ↔ IBKR reconcile sau restart | HIGH | **IBKR-gated** |
| n=2 end-to-end | deploy_sim --n-contracts 2 chưa run | MEDIUM | **Cần chạy command** |
| STRESS_MID residual | H4 gap trong same-session, không capture trước OPEN loop | LOW | Accepted |
| C1-EXIT | Exit trễ 1 ngày nếu signal throw trên exit day | LOW | Accepted |

---

## Action items

**Ngay bây giờ (pre-paper):**
1. Chạy `python global_index/deploy_sim.py --n-contracts 2` → verify NKD không scale, Rổ4 ≈ 2×

**Khi IBKR wired (thứ tự):**
1. Extend `broker.py::Fill` với `status: str`, `filled_qty: int`, `error_msg: str | None`
2. Runner check `fill.status` sau CLOSE → nếu FAILED: flag position `exit_pending=True` (thêm field vào OpenPos), persist
3. Implement `_retry_pending_exits()` đầu `run_day()` — gửi MARKET order lại cho exit_pending positions
4. B3: implement `IBKRBroker.get_positions()` → so với `state.open_positions` sau restart

**IBKR-gated nhưng cần plan:**
5. `contract_month` field trên OpenPos — cần trước khi `_handle_rollover()` implement
6. Roll slippage measurement trong paper (first roll = Mar 2027 nếu live Q1 2027)
