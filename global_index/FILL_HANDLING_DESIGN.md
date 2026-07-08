# Fill Handling Design
**Status:** Design-only. Pending IBKR account. No live functions implemented.
**Files affected when implementing:** `broker.py`, `live_decision.py`, `runner.py`, `ibkr_broker.py`

---

## 1. Fill Contract

### Extended `Fill` dataclass (planned — not yet in broker.py)

```python
@dataclass
class Fill:
    inst: str
    action: str           # "OPEN" | "CLOSE"
    direction: str
    contracts: int        # ORDERED qty — NOT necessarily filled
    cluster: str
    pnl_sized: float = 0.0
    # ── live fields (added when IBKRBroker.send_order is implemented) ────────
    status: str = "FILLED"          # "FILLED" | "PARTIAL" | "CANCELLED" | "FAILED"
    filled_qty: int = 0             # actual contracts filled; 0 = backward-compat sentinel
    avg_price: float | None = None  # actual fill price from IBKR
    error_msg: str = ""             # rejection reason if FAILED
```

**Backward-compat sentinel:** `filled_qty == 0` means "use `contracts`" (MockBroker path).
Runner reads:
```python
effective_qty = fill.filled_qty if fill.filled_qty > 0 else fill.contracts
```
MockBroker returns `Fill(status="FILLED", filled_qty=0)` — unchanged from today.

### `send_order` contract (blocking)

`send_order` is **synchronous and blocking** in IBKRBroker:
1. Submit order to IBKR
2. Poll `Trade.orderStatus` until terminal state or timeout
3. Return `Fill` with actual fill data

Runner does **not** poll after `send_order` returns. IBKRBroker owns the polling.

Terminal states and their `Fill.status` mapping:
| IBKR `orderStatus.status` | `Fill.status` |
|---|---|
| `Filled` | `FILLED` |
| `PartiallyFilled` + timeout expired | `PARTIAL` |
| `Cancelled` | `CANCELLED` |
| `Inactive` / rejected | `FAILED` |

---

## 2. Entry: Timeout + Skip

**Timeout: `ENTRY_FILL_TIMEOUT_SECS = 30`**

Rationale: MES/MNQ market orders on Globex fill in < 5s under normal conditions.
NKD (Globex Nikkei, power-hour window) is less liquid but still active during session.
30s = 6× expected fill time. Short enough to detect hung orders before session close.

### Runner logic (skeleton in runner.py)

```python
def _handle_entry_fill(self, fill: Fill, entry: dict, ordered_qty: int) -> OpenPos | None:
    if fill.status == "FILLED":
        return OpenPos(entry["inst"], entry["direction"], effective_qty,
                       entry["risk_sized"], entry["cluster"], ...)
    if fill.status == "PARTIAL":
        risk_per_contract = entry["risk_sized"] / ordered_qty
        risk_actual = risk_per_contract * fill.filled_qty
        # emit WARN SIGNAL "partial fill: ordered N, filled M"
        self._entry_divergence_count += 1
        return OpenPos(..., contracts=fill.filled_qty, risk_dollars=risk_actual, ...)
    if fill.status in ("CANCELLED", "FAILED"):
        # emit ALERT SIGNAL "entry unfilled — backtest divergence +1"
        self._entry_divergence_count += 1
        return None  # no position created
```

### ⚠ Divergence clarification

`_entry_divergence_count` counts SKIP events. It is **not** a measure of total divergence.

Each skip frees cap → a different trade (which backtest rejected) may now be admitted.
That different trade affects the entire subsequent chain: different positions, different
exit timing, different regime exposure. The divergence cascades and compounds.

**`_entry_divergence_count` is a floor bound on divergence events, not the full measure.**

True optimism measure = compare cumulative P&L at end of paper period:
```
optimism = backtest_pnl_same_period - paper_actual_pnl
```
A low skip count but large optimism means the cascade effect dominated.
A high skip count but low optimism means skipped trades were marginal.

Track both: skip count (cheap, real-time) + P&L comparison (true measure, post-hoc).

---

## 3. Exit: Market Order + Retry — Never Skip

**Exit order type: always MARKET.** No limit orders. Slippage is acceptable; a stranded
position is not.

### `OpenPos` new field (planned — not yet in live_decision.py)

```python
@dataclass
class OpenPos:
    ...
    exit_pending: bool = False    # True = market exit failed or partial; retry at next open
    exit_fail_count: int = 0      # consecutive exit failures (escalation at 3)
```

### Runner logic (skeleton in runner.py)

```python
def _handle_exit_fill(self, fill: Fill, pos: OpenPos) -> bool:
    """Returns True if position fully closed. Caller must NOT remove pos if False."""
    if fill.status == "FILLED":
        return True  # remove from open_positions, realize pnl normally
    if fill.status == "PARTIAL":
        # close fill.filled_qty contracts, flag remaining
        pos.contracts -= fill.filled_qty
        pos.exit_pending = True   # remaining handled by _retry_pending_exits
        # emit WARN ORDER "partial exit: closed M of N, {remaining} flagged exit_pending"
        return False  # position stays (with reduced contracts)
    if fill.status in ("CANCELLED", "FAILED"):
        pos.exit_pending = True
        pos.exit_fail_count += 1
        _handle_exit_escalation(pos)
        return False  # position stays

def _retry_pending_exits(self, day) -> None:
    """Force-exit all exit_pending positions. Called at START of run_day, before signal."""
    raise NotImplementedError
```

### ⚠ Partial exit remaining: exit_pending, NOT exit_day

When a partial exit occurs on exit day D, the remaining contracts need to exit.
`p.exit_day == D` has already fired — `decide_day` will NOT re-trigger it on day D+1.

**Remaining contracts rely on `exit_pending = True`, not `exit_day`.**

`_retry_pending_exits()` scans `[p for p in state.open_positions if p.exit_pending]`
and force-exits them regardless of `exit_day`. `exit_day` is irrelevant at that point.

This is why the `exit_pending` field exists as a separate flag, distinct from `exit_day`.

---

## 4. Exit Fail Escalation (3× rule)

### Escalation at `pos.exit_fail_count >= 3`

3 consecutive exit failures on the same position indicates an abnormal market condition:
prolonged halt, instrument suspension, exchange emergency stop, or connectivity failure
severe enough that MARKET orders cannot execute.

**This is beyond what the runner can self-resolve.** The runner's response:

```
1. emit CRITICAL ORDER event: "EXIT FAILED 3×: {inst} — MANUAL INTERVENTION REQUIRED.
   Market order unreachable. Check exchange status. Do not rely on automated retry."
2. Halt new entries (emit_event → set internal halt_entries flag or use breaker).
3. Continue retrying exits on every run_day (do not give up — position must close).
4. Mark position in live_state_data.js operational_status with a "manual_required" flag.
```

**Manual intervention required means:**
- Operator checks exchange status / instrument halt
- If exchange operational: close manually via broker platform (TWS/IBKR mobile)
- If instrument suspended: contact broker to force-close at suspension price
- After manual close: update positions file to remove the position (or runner re-reconciles via B3)

The runner never force-deletes a position from state. Only a successful fill or manual
reconcile via `reconcile_positions()` removes it.

---

## 5. Partial Fill: Risk$ Recalculation

```python
# Entry ordered N contracts, filled M:
ordered_qty = contracts_by_inst[inst]          # e.g. 2
risk_per_contract = entry["risk_sized"] / ordered_qty
risk_actual = risk_per_contract * fill.filled_qty

OpenPos(..., contracts=fill.filled_qty, risk_dollars=risk_actual, ...)
```

**Note:** Current system uses `contracts_by_inst = {"MES": 1, ...}` (all 1s). Partial fill
on a 1-contract instrument is impossible — minimum is 1. This math is correct for when
`contracts_by_inst` is increased. For 1-contract positions, `PARTIAL` means a real order
problem (filled 0 of 1, which maps to CANCELLED), not a partial fill.

Guard: `if fill.filled_qty == 0 and fill.status == "PARTIAL"` → treat as CANCELLED.
Partial with 0 filled is a broker reporting inconsistency; emit ALERT and skip.

---

## 6. Blocking Time Analysis

`send_order` blocks for up to 30s per entry order. Exit orders block until filled (no cap).

### Order counts: MEASURED from IS 2018-2024 (N=1381 trading days)

Source: `replay_snapshots_data.js` decision.entries / decision.exits per snapshot.

| Stat | Entries/day | Exits/day | Total/day |
|---|---|---|---|
| Mean | 1.96 | 1.73 | 3.69 |
| Median (p50) | 2 | 2 | 3 |
| p75 | 3 | 3 | 5 |
| p90 | 4 | 4 | 7 |
| p95 | 5 | 4 | 8 |
| p99 | 6 | 5 | 10 |
| MAX (p100) | 9 | 5 | 13 |

Days with 0 entries: 380 (28%). Days with 0 exits: 229 (17%).
Distribution above threshold: >3 total orders = 49% of days; >6 = 15%; >10 = 0.4%.

**Peak day: 2018-03-27** — 8 entries + 5 exits = 13 orders.
Cause: all 3 clusters fired simultaneously (Stress regime).
Entry breakdown: roska4_swing=3, roska4_stress=4, global_nkd=1.

### Fill times: DESIGN ASSUMPTIONS — NOT YET MEASURED (verify in paper)

| Scenario | Assumption | Source |
|---|---|---|
| Entry fills normally | ~5s | Design assumption; micro futures market order |
| Entry times out | 30s | `ENTRY_FILL_TIMEOUT_SECS` = 30 (design) |
| Exit fills normally | ~5s | Design assumption; MARKET order |

**These fill times are unverified. Only real paper/IBKR fills will establish actual numbers.**

### Block time budget

```
block_time = n_entries × entry_time + n_exits × exit_time
```

| Percentile | Orders | Worst-case (all timeout) | Typical (fast fills) |
|---|---|---|---|
| p50 (median) | 2E+2X | 70s (1m10s) | 20s |
| p75 | 3E+3X | 105s (1m45s) | 30s |
| p90 | 4E+4X | 140s (2m20s) | 40s |
| p99 | 6E+5X | 205s (3m25s) | 55s |
| **p100 (peak)** | **8E+5X** | **265s (4m25s)** | **65s** |

*Worst-case = all entries timeout (30s each) + exits fill fast (5s each).*
*Typical = all orders fill fast (5s each). Both use unverified design assumptions.*

Note: the original "3+3 = 105s" estimate was the p75 case, not worst-case.
Real peak-day worst-case is **265s** (8 entries timeout + 5 exits). Typical peak = 65s.

### Session constraint (verify at implementation)

```
runner_start_time + block_time_budget < session_end_time
```

| Scenario | Budget to reserve | Comment |
|---|---|---|
| Daily EOD runner (after-hours) | No constraint | Session already closed |
| Intra-session, typical | ~65s (peak typical) | Almost always safe |
| Intra-session, worst-case | ~265s (~4.5 min) | Must start ≥5 min before session close |

For NKD power-hour runner: typical block 65s is fine if runner starts >10 min before close.
Worst-case (all 8 entries timeout) only possible in high-regime-stress days (Stress→all clusters).

**Action at implementation:**
- Log `runner_start_time` and `session_end_time`
- Emit WARN if `remaining_session_time < 300s` (5 min) at run_day start
- Verify p99 fill time empirically in first paper weeks; update 30s/5s assumptions

---

## 7. Implementation Checklist

When IBKR account is live, implement in this order:

- [ ] `broker.py`: add `status/filled_qty/avg_price/error_msg` to `Fill`
- [ ] `live_decision.py`: add `exit_pending/exit_fail_count` to `OpenPos`;
      update `_openpos_to_dict/_openpos_from_dict` for these fields
- [ ] `ibkr_broker.py`: implement `_wait_for_fill(trade, timeout_secs)` and live `send_order`
- [ ] `runner.py`: implement `_handle_entry_fill`, `_handle_exit_fill`, `_retry_pending_exits`;
      uncomment `self._retry_pending_exits(day)` call in `run_day`
- [ ] Verify: blocking time < session window (see §6)
- [ ] Test: `test_ibkr_injection.py` already has C3/C5/C6 injection harness — add fill scenarios
- [ ] Paper run: compare `_entry_divergence_count` + final P&L vs backtest same period
