# RAITS Equity Live Path — Operational Failure Audit

**Date:** 2026-07-05  
**Scope:** Equity only, investigation only (no fixes)  
**Files audited:** `live/runner.py`, `live/context_feed.py`, `live/broker.py`, `live/reconciliation.py`, `risk/circuit_breakers.py`

---

## Classification

- **TYPE 1 — SILENT WRONG:** keeps trading on bad input (most dangerous — loses money without stopping)
- **TYPE 2 — HARD STOP:** crashes / disconnects / no data (safe but interrupts)
- **TYPE 3 — EDGE/RARE:** boundary conditions

---

## A. DATA FEED

| Failure | Type | Handled? | Where / Notes |
|---|---|---|---|
| WS disconnect | 2 | ✅ Yes | `_ws_thread` exponential backoff `[1,2,4,8,16,30s]` + REST backfill on reconnect |
| Auth fail (bad API key) | 2 | ⚠️ Partial | Caught as generic `except Exception` — retries forever, no distinction from transient disconnect |
| Subscription rejected | 2 | ⚠️ Partial | Same broad catch in `_ws_thread` — retries forever even if persistently rejected |
| Bars stop mid-session (WS quiet, market open) | 1/2 | ⚠️ Partial | `bar_q.get(timeout=10s)` loops; if market open but bars stopped → hangs silently, no BarContext emitted, open positions not exited until proactive EOD fires (possibly at wrong price if `day_stocks` stale) |
| Malformed bar | 3 | ✅ Yes | `try/except` in `_handle()`, logs WARNING, bar dropped silently |
| Stale `daily_data` (L1+L2) | 1 | ✅ Yes | Soft-stale 5 bdays: skip retrain + WARNING. Hard-stale 10 bdays: `regime_unreliable=True` + `notify()` + entries blocked |
| **Single ticker bars stop mid-session** | **1** | **❌ No** | Ticker absent from `day_stocks` → no TIME_STOP signal → EOD close uses `trade.entry_price` as fallback → **wrong EOD close price, silent** |
| Duplicate / out-of-order bars | 3 | ✅ Yes | `_BarAccumulator` last-write-wins by `(ticker, ts)`, sorted on demand |
| Rate limit (REST backfill) | 2 | ⚠️ Partial | Per-ticker backfill failure logged as ERROR, no retry |

---

## B. BROKER (IBKR)

| Failure | Type | Handled? | Where / Notes |
|---|---|---|---|
| Connection lost / Gateway restart | 2 | ⚠️ Partial | `_require_connection()` raises `IBKRConnectionError`; `submit_order` re-raises; **not caught in PaperTrader bar loop → process crash** |
| Order rejected (buying power / PDT / invalid) | 2 | ✅ Yes | `FillStatus.REJECTED` returned; `orders_rejected += 1`; no position opened |
| Partial fill | 3 | ✅ Yes | `FillStatus.PARTIAL` → trade opened with `filled_qty` |
| **Fill timeout (order in-flight at IBKR)** | **1** | **❌ No** | `IBKRBroker` sets `FillStatus.PENDING` after 30s timeout; PaperTrader `else: orders_rejected += 1` → **position recorded as not-entered, but IBKR executed it → POSITION MISMATCH** |
| **Exit order rejected** | **1** | **❌ No** | `_process_exit` line 532: `REJECTED` → `orders_rejected += 1` but **position stays in `_open_positions` silently, no retry, no alert** |
| Account query fails | 2 | ✅ Isolated | `account_equity()` raises `IBKRConnectionError`; PaperTrader doesn't call it (tracks equity internally) |
| Wrong contract / delisted ticker | 3 | ✅ Yes | `except Exception` in `submit_order` → `FillStatus.REJECTED` |
| `cancel_order` not implemented | 2 | ⚠️ Partial | Raises `NotImplementedError`; no UUID→IBKR orderId map; not called in normal flow |

---

## C. EXECUTION STATE

| Failure | Type | Handled? | Where / Notes |
|---|---|---|---|
| **Order sent, crash before fill recorded** | **1** | **❌ No** | Process crashes after `ib.placeOrder()` but before `_open_positions[trade_id] = trade` — IBKR has position, we have none |
| **Duplicate order on restart** | **1** | **❌ No** | Fresh PaperTrader starts with empty `_open_positions`; strategies generate new entry signals; IBKR receives second entry on top of existing position |
| **Position mismatch (our state vs IBKR actual)** | **1** | **❌ No** | No reconciliation of `_open_positions` against IBKR's actual portfolio at startup or during run |
| Recon log shows unexpected / missing order | 1 | ❌ No | `ReconciliationLog` is append-only order log; never compared against IBKR positions |

---

## D. COMPUTE

| Failure | Type | Handled? | Where / Notes |
|---|---|---|---|
| HMM retrain fails mid-session | 3 | ✅ Yes | `try/except` in both `_iter_all` and `_iter_live`; logs DEBUG; old HMM kept |
| **`decide()` raises on a bar** | **2** | **❌ No** | `runner.py:320` — `decision = self._du.decide(ctx)` has **no try/except**; exception propagates → run loop crashes → process dies |
| `_process_entry` / `_process_exit` raises | 2 | ❌ No | No try/except around either; exception crashes bar loop |
| **NaN/inf in entry price, shares, or pnl** | **1** | **❌ No** | Propagates through `Order.limit_price` → `fill_price` → `gross_pnl` → `net_pnl` → `record_trade_result(NaN)` → circuit breaker gets NaN → undefined behavior. No guard anywhere in the chain |
| Strategy throws internally | 2 | ❌ No | No guard at runner level; depends on DecisionUnit internals |

---

## E. PROCESS / LIFECYCLE

| Failure | Type | Handled? | Where / Notes |
|---|---|---|---|
| **Crash + restart mid-session (open positions)** | **1** | **❌ No** | PaperTrader state entirely in-memory. On restart: `_open_positions = {}`, equity reset, CB reset. IBKR still holds positions. No recovery path. |
| Clock skew | 3 | ⚠️ Inherent | Proactive EOD uses `et_now_time()` from OS clock; acceptable for paper |
| Running past close | 3 | ✅ Yes | Proactive EOD fires when `et_now_time() >= market_close_time(current_day)`; half-day handled via `trading_calendar` |
| **Starting mid-session with IBKR open positions** | **1** | **❌ No** | Runner starts fresh; IBKR positions from prior session not queried; sit unmanaged |
| Starting mid-session (no prior positions) | 3 | ⚠️ Partial | Misses morning bars; ORB signals never fire; acceptable for paper |

---

## TYPE-1 PRIORITY LIST (Silent Wrong — no detection)

Ordered by danger:

| # | Gap | Mechanism | Detection |
|---|---|---|---|
| 1 | **Fill timeout → position mismatch** | `PENDING` treated as rejected; IBKR holds real position; our state shows nothing | None |
| 2 | **Crash + restart mid-session** | Fresh PaperTrader, empty `_open_positions`; strategies re-enter; IBKR gets duplicate orders | None |
| 3 | **Exit order rejected → silent open position** | `_process_exit` increments `orders_rejected` only; position stays in `_open_positions` indefinitely | Recon log records reject, but no alert and no re-attempt |
| 4 | **Order sent, crash before fill recorded** | IBKR has position; we don't | None |
| 5 | **NaN/inf in computed values** | Propagates through P&L → circuit breaker → equity tracking | None |
| 6 | **Single ticker bars stop** | EOD closes at `entry_price` (fallback) instead of actual last price | None |
| 7 | **Bars stop mid-session, market open** | Proactive EOD eventually fires but with stale `day_stocks`; pending exits never arrive | None until EOD |

---

## State Recovery for TYPE-2 (crash / restart)

### What exists
- REST backfill of missed bars on WS reconnect ✓
- `ReconciliationLog` append-only CSV + JSONL per-session ✓
- Consecutive-loss counter persists across `reset_for_new_session()` — **in-memory only, same process**

### What is missing

| Requirement | Status |
|---|---|
| Reconcile `_open_positions` vs IBKR actual positions on startup | ❌ Missing |
| Detect orders sent before crash whose fills arrived during downtime | ❌ Missing |
| Load prior session's `_open_positions` from disk on restart | ❌ Missing |
| Avoid duplicate orders on reconnect (check IBKR position before entering) | ❌ Missing |
| UUID → IBKR orderId map (to query in-flight order status on reconnect) | ❌ Missing — `cancel_order` raises `NotImplementedError` |
| Consecutive-loss counter persisted to disk (survives process restart) | ❌ Missing |

**Current restart behavior:** starts fresh → sends new entry signals → IBKR receives them on top of whatever it already holds → no detection of mismatch.

---

## Priority by Phase

### Must fix BEFORE paper (can lose money silently on paper with IBKR)

| Priority | Issue | Type |
|---|---|---|
| P0 | `decide()` raises → process crash (no try/except in bar loop) | 2 |
| P0 | Exit order rejected → position stays open silently, no retry, no alert | 1 |
| P0 | Fill timeout → `PENDING` treated as rejected → position mismatch with IBKR | 1 |
| P1 | NaN/inf in entry price / shares / pnl → silent corruption through CB + equity | 1 |

### Must fix BEFORE live (not a blocker for paper)

| Priority | Issue | Type |
|---|---|---|
| P0 | Crash + restart → no state recovery, no IBKR reconciliation | 1 |
| P0 | Starting with IBKR open positions → unmanaged positions | 1 |
| P1 | Order sent, crash before fill recorded → phantom IBKR position | 1 |
| P1 | Consecutive-loss counter not persisted to disk | 1 |
| P2 | Single ticker bars stop → wrong EOD close price (uses `entry_price` fallback) | 1 |
| P2 | Auth fail / persistent subscription reject → infinite retry loop | 2 |

### Monitor-only (acceptable as-is for paper)

| Issue | Why OK |
|---|---|
| Malformed bar | Dropped + logged ✓ |
| HMM retrain fails | Old HMM kept + logged ✓ |
| Duplicate / out-of-order bars | Deduplicated by `_BarAccumulator` ✓ |
| WS disconnect | Reconnect + REST backfill ✓ |
| `cancel_order` not implemented | Not called in normal flow |
| Starting mid-session (no prior positions) | Strategies miss morning signals only |
| Clock skew | Inherent OS limitation |
