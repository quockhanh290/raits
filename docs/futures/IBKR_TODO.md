# Futures — IBKR TODO
_Items blocked on having a live IBKR account._  
_2026-07-08 — **ACCOUNT APPROVED** ✓ → bắt đầu implement theo thứ tự dưới._

## Thứ tự implement (theo dependency)

1. `IBKRBroker._fetch_raw()` → test C6 (column case), C3 (out-of-order bars), P2 (timezone)
2. `IBKRBroker.send_order()` → test A1 (fill/reject), A2 (partial), A3 (timeout), A4 (timing)
3. `IBKRBroker.get_positions()` → implement B3 (reconcile sau restart)
4. `_handle_rollover()` → roll cost thật, timing, `contract_month` field trên OpenPos

Paper goals sau khi wire: fill time thật (vs 30s/5s assumed), slippage thật (vs 2-tick baseline), fill rate, ≥1 Stress period live.

---

---

## B3 — Runner ↔ IBKR reconcile sau restart

**File**: `global_index/runner.py:175` (TODO comment), `global_index/ibkr_broker.py:get_positions()`

**Vấn đề**: `IBKRBroker.get_positions()` hiện raise `NotImplementedError`. Sau crash hoặc restart, runner load từ `live_positions.json` mà không verify với IBKR. Nếu file cũ (stale 265s window) hoặc CLOSE failed in prior session: runner state ≠ IBKR state → silent orphan position.

**Implement khi có account**:
1. Wire `IBKRBroker.get_positions()` → gọi `reqPositions()` / `positionEnd()` qua ib_async
2. Trong `FuturesRunner.__init__()`, sau khi load `live_positions.json`:
   ```python
   broker_positions = self.broker.get_positions()
   # cross-check inst/direction/contracts vs loaded positions
   # alert on mismatch → emit CRITICAL event + log
   ```
3. Test: mock broker returns position that doesn't match file → CRITICAL alert emitted

---

## A1 — Test fill-fail thật (CLOSE reject/timeout)

**File**: `global_index/ibkr_broker.py:send_order()` (NotImplementedError)

**Vấn đề**: Toàn bộ I4.8 path (`Fill.status=="FAILED"` → `exit_pending=True` → retry) chưa test với IBKR thật. MockBroker luôn trả `status="FILLED"`.

**Test khi có account**:
- Inject ORDER_CANCEL hoặc force timeout trên CLOSE → verify `Fill.status="FAILED"`
- Verify `exit_pending=True` được persist vào `live_positions.json`
- Verify `_retry_pending_exits()` gọi lại CLOSE hôm sau
- Measure: thời gian từ lúc gửi order đến lúc nhận fill confirm (vs assumed 5s)

---

## A2 — Test partial fill

**File**: `global_index/ibkr_broker.py:send_order()` ibkr_broker.py:305 comment `[2]` PARTIAL path

**Vấn đề**: Partial fill (`filled_qty < contracts`) chưa implement. `Fill.filled_qty` field có sẵn nhưng IBKRBroker không set nó.

**Implement khi có account**:
- `send_order()` CLOSE: nếu fill confirm `filled < contracts`:
  - Return `Fill(status="PARTIAL", filled_qty=filled, ...)`
  - Runner: set remaining contracts as `exit_pending` với `contracts = contracts - filled`
- Test: inject partial fill → verify only filled contracts removed from state, remainder exit_pending

---

## A3 — Test reject / timeout (OPEN entry)

**File**: `global_index/ibkr_broker.py:send_order()` comment `[1]`

**Vấn đề**: OPEN entry timeout 30s → cancel → expected path. Runner hiện discard OPEN Fill return (không có F3 equivalent cho reject).

**Implement khi có account**:
- OPEN reject: runner should NOT add position to `state.open_positions` (already not happening since decide_day adds it, not runner... wait: actually decide_day adds it. Need to cross-check)
- Actually: decide_day DOES add OpenPos to `state.open_positions` for multi-day entries (live_decision.py:127-131). If OPEN is rejected: position in state but not in IBKR → B3 reconcile catches it.
- Test: OPEN reject → B3 reconcile detects orphan → CRITICAL alert

---

## A4 — Đo timing thật

**Assumed values** (từ ibkr_broker.py:304 comment):
- Entry fill timeout: 30s (6× expected fill time)
- Exit fill time: 5s worst-case (MARKET order)
- Block time worst-case: 265s = 5 orders × 5 exits + overhead

**Đo khi có account** (paper mode, ~10 ngày):
- Log timestamp từ lúc `send_order()` gọi đến lúc `execDetails()` callback fire
- Compare entry vs exit timing (LIMIT vs MARKET)
- If fill time >> 5s → revisit block time estimate và runner schedule

---

## A5 — Timing: runner schedule EOD vs intra-session

**Vấn đề**: 265s block time giả định runner chạy EOD (sau 16:00 ET). Nếu intra-session:
- Block time 265s = ~4 phút → ok trong 24h window
- Nhưng nếu runner schedule lúc 15:56 → block extends to 16:01 → after close → IBKR reject OPEN orders

**Quyết định khi có account**: chốt timing với thực tế session IBKR.

---

## P2 — Timezone verification (IBKR bars vs ET naive)

**File**: `global_index/ibkr_broker.py:_fetch_raw()`

**Vấn đề**: RAITS dùng ET naive datetimes (Polygon → converted at ingestion). IBKR `reqHistoricalData` trả về bars với timezone. `IBKRBroker._fetch_raw()` cần convert về ET naive để match runner expectations. Chưa verify với live data.

**Verify khi có account**:
- Log raw bar timestamps từ IBKR
- Verify `bar.date` → ET naive conversion đúng (không lệch 1h do DST)
- DST edge: 2nd Sunday March, 1st Sunday November

---

## P3 — Order crossing kiểm tra

**File**: `global_index/ibkr_broker.py:send_order()`

**Vấn đề**: Nếu nhiều instruments OPEN cùng lúc trong runner (loop pass 2): orders sent sequentially. Không có IBKR-side check rằng orders không self-cross (MES LONG + MES SHORT cùng cluster). Design guards via `ClusterBudget` prevent same-cluster opposing positions, nhưng chưa verify IBKR không reject theo rule riêng.

**Verify khi có account**: check IBKR error codes nếu có order crossing.

---

## Roll — I5.2 Contract rollover

**File**: `global_index/runner.py:_handle_rollover()` (raises NotImplementedError)

**Block hoàn toàn đến khi có account**.

Xem `docs/futures/OPEN_QUESTIONS.md` → "C2 Rollover" section cho full detail + nuances.

Roll schedule 2026:
- MES/MNQ/MYM/M2K: Mar 13, Jun 12, Sep 11, Dec 11
- NKD: Mar 6, Jun 5, Sep 4, Dec 4

First roll nếu live Q1 2027: MES Mar 19, NKD Mar 12 (2027).

---

## Roll — Slippage cost đo paper

**Context**: Backtest dùng continuous contract (không trả roll cost). Live: ~16 rolls/năm × slippage × 2 chiều.

MES tick=$1.25 → 2-tick roll = $2.50 × 16 ≈ $40/năm (nhỏ nhưng cần đo).

**Đo**: first paper roll → compare fill prices vs Barchart continuous roll prices → tính slippage thật.

---

## Thứ tự implement (khi IBKR account available)

```
1. Wire IBKRBroker._fetch_raw()  → test C6 (UPPERCASE), C3 (bar order), P2 (timezone)
2. Wire IBKRBroker.send_order()  → test A1/A2/A3/A4 (fill/partial/reject/timing)
3. Wire IBKRBroker.get_positions() → implement B3 reconcile
4. Wire _handle_rollover()       → test I5.2 (roll cost, timing, contract_month field)
5. P3 order crossing             → verify via paper log
```
