# RAITS Live Path — TYPE-1/TYPE-2 Fix Log

**Date:** 2026-07-05  
**Scope:** `raits/live/` only — engine.py / decision_unit.py / backtest logic untouched  
**Baseline throughout:** 604/604 trades identical, net P&L $15,952.15 costs-ON (to the cent)

---

## FIX 1 — Fill timeout must not be treated as rejected

**File:** `raits/live/runner.py` — `_process_entry()`  
**Problem (TYPE 1):** `IBKRBroker` sets `FillStatus.PENDING` after 30s fill timeout. The old `else` branch in `_process_entry` treated PENDING identically to REJECTED (`orders_rejected += 1`, returned None). IBKR may have actually filled the order → position mismatch: IBKR holds shares, our state shows nothing. Next bar generates a fresh entry on top.

**Fix:**
- `PENDING` now has its own branch: `orders_pending += 1`, ticker added to `self._pending_tickers`, `notify()` fired.
- Subsequent entries on a pending ticker are blocked before broker submission until operator clears the flag.
- `RunResult.orders_pending` counter added.

**Tests:** `test_pending_not_counted_as_rejected`, `test_pending_blocks_subsequent_entry`

---

## FIX 2 — Exit order rejected must not silently leave position open

**File:** `raits/live/runner.py` — `_process_exit()`  
**Problem (TYPE 1):** Exit REJECTED → `orders_rejected += 1`. Position stayed in `_open_positions` silently with no retry, no alert.

**Fix:**
- First attempt rejected → automatic retry (second `submit_order` call, recorded in recon log).
- Retry succeeds → position closed normally.
- Both attempts fail → `exits_failed += 1`, `notify()` with `"EXIT FAILED (both attempts): ticker … position remains OPEN"`. Position intentionally kept in `_open_positions` so risk is visible.
- `RunResult.exits_failed` counter added.

**Tests:** `test_exit_retry_succeeds_on_second_attempt`, `test_exit_both_attempts_fail_keeps_position_and_notifies`

---

## FIX 3 — Startup reconcile-or-halt

**Files:** `raits/live/runner.py` — `_startup_reconcile()`, `raits/live/broker.py` — `get_open_positions()`  
**Problem (TYPE 1):** On restart, `PaperTrader` starts with empty `_open_positions`. If IBKR holds positions from a prior session, strategies generate new entries on top — doubles the exposure with no detection.

**Fix:**
- `BrokerInterface` gets abstract `get_open_positions() → Dict[str, float]`.
- `MockBroker.get_open_positions()` returns `{}` (no halt in testing/replay).
- `IBKRBroker.get_open_positions()` queries the gateway portfolio.
- `PaperTrader._startup_reconcile()` called at top of `run()` (controlled by `reconcile_on_startup=True`): if broker returns any positions, `StartupMismatchError` is raised + `notify()` fired before the first bar is processed.

**Tests:** `test_startup_no_positions_proceeds`, `test_startup_mismatch_halts`, `test_startup_reconcile_skipped_when_disabled`

---

## FIX 4 — Exception on one bar must not crash the whole loop

**File:** `raits/live/runner.py` — `run()` bar loop  
**Problem (TYPE 2 → effective TYPE 1):** `decide()`, `_process_entry()`, `_process_exit()` called with no try/except. One bad bar crashes the entire process; all open positions become unmanaged.

**Fix — entries vs exits handled differently:**

| Call site | Exception behavior | Rationale |
|---|---|---|
| `self._du.decide(ctx)` | `bars_errored++`, `notify()` with bar_ts, `continue` | Entries and exits both missed for this bar; EOD is the safety net for open positions |
| Each swing `_process_exit()` (Step 1) | per-exit `try/except`, `notify()` with ticker + trade_id, next exit still runs | One exit crash must not block other exits on the same bar |
| Each intraday `_process_exit()` (Step 3) | same | same |
| Each `_process_entry()` (Step 4) | `notify()`, `continue` to next entry | Entry skip is safe — no new risk taken |
| Same-bar `_check_exits()` + inner `_process_exit()` | nested try/except, each layer independent | Position was opened; failure in same-bar check is non-fatal |

`RunResult.bars_errored` counter added.

**Tests:** `test_decide_exception_skips_bar_loop_continues`, `test_decide_exception_exits_still_process_on_next_bar`, `test_decide_exception_notifies`, `test_exit_exception_does_not_block_other_exits`

---

## FIX 5 — NaN/inf must fail loud at the first boundary

**File:** `raits/live/runner.py` — `_process_entry()`, `_process_exit()`, all four bulk-close methods  
**Problem (TYPE 1):** NaN in `entry_price` or `shares` propagates through `Order.limit_price → fill_price → gross_pnl → net_pnl → record_trade_result(NaN) → CB state + equity`, corrupting risk tracking silently. `NaN or 0.0` in Python evaluates to `NaN` (NaN is truthy), so the existing `trade.net_pnl or 0.0` guard did not protect the CB.

**Guards placed:**

| Boundary | Check | On violation |
|---|---|---|
| `_process_entry()` — before broker submission | `math.isfinite(price) and price > 0` and `math.isfinite(shares) and shares > 0` | `entries_nan_rejected++`, `notify()`, return None — order never reaches broker |
| `_process_exit()` first fill path | `math.isfinite(gross_pnl) and math.isfinite(net_pnl)` | `pnl_nan_guarded++`, `notify()`, position closed with pnl fields = None; equity/CB NOT updated |
| `_process_exit()` retry fill path | same | same |
| `_close_all_eod()` | same | position closed, equity not updated, `continue` to next position |
| `_close_end_of_period()` | same | position closed, CB not called |
| `_close_all_cb()` | same | position closed, equity not updated |
| `_check_max_hold()` | same | position closed, CB not called |

`RunResult.entries_nan_rejected` and `RunResult.pnl_nan_guarded` counters added.

**Tests:** `test_nan_entry_price_rejected`, `test_inf_entry_price_rejected`, `test_zero_shares_rejected`, `test_valid_entry_not_rejected`, `test_nan_pnl_in_process_exit_closes_position_without_equity_corruption`, `test_nan_pnl_does_not_trip_circuit_breaker`

---

## Summary

| Fix | Type | Guard location | Counter in RunResult |
|---|---|---|---|
| FIX 1 — PENDING ≠ REJECTED | TYPE 1 | `_process_entry` | `orders_pending` |
| FIX 2 — Exit retry + alert | TYPE 1 | `_process_exit` | `exits_failed` |
| FIX 3 — Startup reconcile-or-halt | TYPE 1 | `run()` → `_startup_reconcile()` | — (raises exception) |
| FIX 4 — Exception safety | TYPE 2 | bar loop (decide + exits + entries) | `bars_errored` |
| FIX 5 — NaN/inf guard | TYPE 1 | entry boundary + all 5 close paths | `entries_nan_rejected`, `pnl_nan_guarded` |

**Files modified:** `raits/live/runner.py`, `raits/live/broker.py`  
**Files added:** `raits/raits/tests/live/test_live_mismatch_fixes.py` (7 tests), `raits/raits/tests/live/test_live_exception_nan_fixes.py` (10 tests)  
**Test suite:** 198/198 pass  
**Baseline:** 604/604 trades, $15,952.15 costs-ON — unchanged to the cent
