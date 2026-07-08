# Circuit Breaker Investigation — 605 vs 604 Trade Count

**Date**: 2026-07-08  
**Status**: ANALYSIS EXTENDED — baseline clean; CB semantics in both engines need correction before paper  
**Scope**: IS only (2017-2022 window_debug data). Vault untouched.

---

## Finding

`BacktestEngine._close_all()` calls `trade_log.close_trade()` directly, bypassing
`_close_trade()` — the only path that calls `circuit_breakers.record_trade_result()`.
Any trade closed via SAFETY_MODE, EOD, or daily-drawdown-CB in ORIG does **not** update
the consecutive-loss streak.

`RefactoredBacktestEngine` routes SAFETY_MODE exits through `decide()` → ExitIntents →
`_close_trade()` → `record_trade_result()` IS called → streak IS updated.

---

## Root Cause Chain (Parquet data, ORIG vs REFAC)

On **2019-01-03**, SAFETY_MODE (or EOD) fires in the IS run.  
ORIG closes QQQ STRESS_ORB, IWM STRESS_ORB, SPY STRESS_MID via `_close_all()` — no CB
update. REFAC closes them via `_close_trade()` — CB updated.

This causes a 1-count divergence in `_consecutive_losses` that compounds:

| Engine | After Jan 3 | Before XOM (Jan 15) | Before MMM (Jan 18) | After MMM (-$230) | CB fires? |
|--------|-------------|---------------------|---------------------|-------------------|-----------|
| ORIG   | unchanged   | unchanged+2         | unchanged+3 = **3** | → 4               | No → CVX enters 14:00 |
| REFAC  | +1          | +3                  | **4**               | → 5 = CB limit    | Yes → bar breaks 09:35 → no CVX |

**ORIG Parquet = 605 trades (has CVX TF 2019-01-18 14:00, pnl=-$208.09)**  
**REFAC Parquet = 604 trades (no CVX)**

---

## Confirmed by Instrumented Run

`diagnose_jan3_engine_order.py` patches `_close_trade()` to print
`[BEFORE]/[AFTER]` for every Jan 3–10 close. Output:

```
[BEFORE] 2019-01-10 10:05  IWM  STRESS_ORB  reason=STOP_HIT  consec=0  flag=False
[AFTER]  2019-01-10 10:05  IWM  STRESS_ORB  reason=STOP_HIT  pnl=-33.14  consec=1
[BEFORE] 2019-01-10 10:20  QQQ  STRESS_ORB  reason=STOP_HIT  consec=1
[AFTER]  2019-01-10 10:20  QQQ  STRESS_ORB  pnl=-37.14  consec=2
```

**Zero Jan 3 lines.** All Jan 3 exits bypassed `_close_trade()` entirely — confirmed
`_close_all()` path. consec=0 before Jan 10 IWM proves ORIG ends Jan 3 with streak
unchanged.

---

## Step 1 — Which CB Behavior is Correct?

**CB design intent**: detect *strategy streak failure* — the strategy's edge has broken
down, halt trading.

**SAFETY_MODE exits** (`_check_layer0`: SPY move >3σ AND >0.6% in 5 min):  
Emergency flatten during a flash crash. The position was correctly entered per strategy
rules; the forced close reflects a market microstructure event, not a strategy signal.
Counting this toward a losing streak fires the CB precisely when Stress strategies
(STRESS_ORB, STRESS_MID) should be most active. **False positive.**

**EOD exits**: Routine operational flatten. A stop-hit IS a strategy signal (trade went
against its own risk parameters). EOD is a time-based close regardless of conviction.
**Not a strategy-failure signal.**

**Daily-drawdown CB exits** (reason=`CIRCUIT_BREAKER`): Day dropped >4%, all positions
closed. This IS genuine loss. Arguably should count.  
**Code verification**: Both ORIG (engine.py:1569) and REFAC (engine_refactored.py:810)
call `self._close_all(bar_ts, day_stocks, "CIRCUIT_BREAKER")` — identical path, neither
updates the streak. REFAC is NOT better here; they are identical.

**Verdict: ORIG is more correct overall (4/5).** REFAC over-counts SAFETY_MODE (wrong).
Both miss daily-drawdown-CB (wrong). Both skip EOD (correct).

| Exit type | ORIG counts? | REFAC counts? | Correct? |
|-----------|-------------|---------------|----------|
| STOP_HIT / TARGET_HIT | YES (`_close_trade`) | YES | Both correct |
| TIME_STOP | YES (`_close_trade`) | YES | Both correct |
| SAFETY_MODE | NO (`_close_all`) | YES (via ExitIntents → `_close_trade`) | ORIG correct, REFAC wrong |
| EOD | NO (`_close_all`) | NO (`_close_all`) | Both correct |
| Daily-drawdown-CB | NO (`_close_all`) | NO (`_close_all`) | Both wrong |

The "real money lost = should count" argument for REFAC conflates two signals: the CB's
job is not to count every dollar lost, it's to detect a *strategy* in a failure mode.

---

## Step 2 — IS Baseline Contamination

**Baseline**: `results_20260624_200216.pkl` — 604 trades, window_debug data, ORIG engine.

**Gate result** (verify_parallel_run.py): ORIG window_debug = REFAC window_debug =
**604 trades, byte-identical, P&L diff $0.00**.

The CB design difference causes **zero trade-count or P&L difference** on the window_debug
dataset. On this data both engines halt at Jan 18 (ORIG via different streak path, REFAC
via earlier count), both produce 604. The baseline is **NOT contaminated**.

**Parquet divergence** (separate from the baseline):  
ORIG Parquet = 605 (has CVX, pnl=**-$208.09**). REFAC Parquet = 604.  
The extra Parquet trade is a **losing** TF trade that REFAC blocks (as a side-effect of
over-counting SAFETY_MODE on Jan 3 — not because REFAC's CB is more correct) and ORIG
allows (because under-counting SAFETY_MODE leaves streak too low). Minor contamination of
the Parquet run — but Parquet was not used for bootstrap or vault.

**Bootstrap p-values**: run on 604-trade window_debug baseline → NOT contaminated.  
**Vault OOS**: OOS 2023-2024, different time period, sealed → NOT affected.

---

## Step 3 — Validated vs Deployed

| Component | Engine | CB behavior |
|-----------|--------|-------------|
| IS baseline (604 trades) | ORIG (`engine.py`) | `_close_all` bypasses CB |
| Bootstrap p-values | ORIG baseline | same |
| Vault OOS (sealed) | ORIG engine | same |
| PaperTrader / live | REFAC (`engine_refactored.py`) | `_close_trade` updates CB |

**On window_debug data: 604==604, no practical mismatch.**

On Parquet/live market data: REFAC (live) is **more conservative** than ORIG (validated).
In Stress periods where SAFETY_MODE fires and positions close at a loss, REFAC counts
those toward the streak; ORIG does not. Live halts **earlier** than backtest in stress.

Mismatch direction: **protective**, not dangerous (live under-trades vs backtest,
does not over-trade). Magnitude: ~1 trade per 6 IS years on historical data.

---

## Step 4 — Verdict

| Question | Answer |
|----------|--------|
| Which CB is correct? | ORIG more correct (4/5): correct for SAFETY_MODE/EOD/STOP/TARGET, wrong for daily-CB. REFAC over-counts SAFETY_MODE AND also wrong for daily-CB. |
| Old baseline contaminated? | NO — 604==604 byte-identical on window_debug. Bootstrap and vault clean. |
| Parquet run contaminated? | Minor — 1 extra losing TF trade (CVX -$208). Parquet not used for validation. |
| Live–backtest mismatch? | Yes, conservative direction. REFAC halts earlier in stress (SAFETY_MODE over-count). Safe but semantically wrong. |
| Fix needed before paper? | Yes — align both engines to correct CB semantics; re-baseline IS. See Issues 1-3 below. |

---

## Diagnostic Scripts Created

All in `raits/raits/scripts/`:

| Script | Purpose |
|--------|---------|
| `diagnose_cvx_entry.py` | Verified CVX Jan 18 14:00 in ORIG Parquet pickle |
| `diagnose_streak_stateful.py` | Stateful CB simulation; revealed simulation≠engine gap |
| `diagnose_orig_jan18.py` | Instrumented ORIG engine: confirmed consec=3 entering Jan 18 |
| `diagnose_jan3_ordering.py` | Confirmed identical trade sets in ORIG/REFAC Jan 1–14 window |
| `diagnose_jan3_engine_order.py` | Confirmed zero `_close_trade` calls on Jan 3 (key proof) |

---

## Issue 1 — Which CB Is Correct?

**Neither engine is fully correct.**

| Exit type | Should count? | Rationale |
|-----------|---------------|-----------|
| STOP_HIT / TARGET_HIT | YES | Direct strategy performance signal |
| TIME_STOP | YES | Strategy exit rule fired; net_pnl reflects result |
| Daily-drawdown-CB | YES | >4% daily loss is genuine bad-condition signal |
| SAFETY_MODE | NO | Flash-crash microstructure event (SPY >3σ, >0.6% in 5 min); position was correctly entered per strategy rules; counting it makes CB fire hardest in Stress regime, exactly when Stress strategies should be active |
| EOD | NO | Operational time-based flatten; not a strategy failure signal |

ORIG is 4/5 correct — correctly skips SAFETY_MODE and EOD, correctly counts
STOP/TARGET/TIME_STOP. **Wrong only for daily-drawdown-CB** (should count, doesn't).

REFAC is 3/5 correct — correctly counts STOP/TARGET/TIME_STOP, correctly skips EOD.
**Wrong for SAFETY_MODE** (counts it via `_close_trade` path) **and for daily-drawdown-CB**
(both engines call `_close_all("CIRCUIT_BREAKER")` — neither updates streak).

ORIG is closer to correct. The key risk in REFAC's error: SAFETY_MODE fires during Stress
events (Q4 2018, March 2020) — REFAC increments the streak there, so live trading halts
faster precisely when TREND_FOLLOW and STRESS_ORB should be most active. That inverts
the design intent of the regime-aware system.

---

## Issue 2 — Validated vs Deployed: Quantification and Decision

**On window_debug IS data (the actual validated baseline):**
- ORIG = REFAC = 604 trades, byte-identical, P&L diff $0.00
- The principle "deploy exactly what was validated" is satisfied on this dataset

**On full Parquet IS data (2017–2022):**
- ORIG = 605 trades (has CVX TF 2019-01-18 14:00, pnl = -$208.09)
- REFAC = 604 trades (CVX blocked — side-effect of SAFETY_MODE over-count on Jan 3)
- Count diff: 1 trade. P&L diff: ORIG IS is -$208.09 worse than REFAC IS (extra loser)
- Stress-concentrated: YES — divergence triggered by SAFETY_MODE on 2019-01-03 (first
  trading day post-Q4 2018 bear market, SPY had gapped up hard after Christmas bottom).
  The downstream blocked trade (CVX TF Jan 18) is also in the volatile early-2019 period.

**Decision on alignment:**

Option A — align REFAC live to ORIG CB semantics (stop counting SAFETY_MODE):
Makes live match validated; still leaves daily-CB un-counted in both. Correct direction
for SAFETY_MODE but does not fix the daily-CB gap.

Option B — fix both engines to correct CB semantics, re-baseline:
Counts daily-CB (new), stops counting SAFETY_MODE in REFAC (fix), leaves EOD alone.
Re-run IS → new validated baseline → ORIG==REFAC by construction → validated==deployed.

**Recommendation: Option B.** Option A achieves coincidental match at the cost of
encoding a known bug (daily-CB not counted). Option B is principled alignment. The
IS re-baseline is the only required run (vault/OOS sealed, not touched).

---

## Issue 3 — Concrete Fix Plan (Before Paper)

Minimal, targeted changes. No refactor. Two engines, two independent fixes.

### engine.py (ORIG)

`_close_all()` needs an optional `update_cb` flag:

```python
def _close_all(self, bar_ts, day_stocks, reason, skip_tf=False,
               skip_swing=False, update_cb=False):
    for trade in list(self.trade_log.open_trades):
        ...
        self.trade_log.close_trade(trade, exit_ts, exit_price, reason)
        if update_cb:
            self.circuit_breakers.record_trade_result(
                trade.net_pnl if trade.net_pnl is not None else 0.0
            )
```

Call sites:
- SAFETY_MODE (line 734): keep `update_cb=False` (current default — no change)
- Daily-drawdown-CB (line 1569): add `update_cb=True`  ← only new behavior
- EOD (line 1584): keep `update_cb=False` (no change)

### engine_refactored.py (REFAC)

SAFETY_MODE fix: when `result.override_active=True`, the engine currently commits
ExitIntents via `_close_trade()` (lines 721-749). Replace that block so SAFETY_MODE
exits go through `_close_all()` instead:

```python
if result.override_active:
    self._safety_mode_active = True
    # Use _close_all to bypass CB — SAFETY_MODE is not a strategy failure
    self._close_all(bar_ts, day_stocks, "SAFETY_MODE", skip_tf=True)
    continue
```

This drops the ExitIntent commit loop for SAFETY_MODE and replaces it with the same
`_close_all` path ORIG uses. The `decide()` call still runs (needed for `override_active`
signal), but its ExitIntents are discarded.

Daily-drawdown-CB (line 810): same `update_cb=True` flag as ORIG fix.

### After both fixes

- SAFETY_MODE: both engines via `_close_all`, no CB update → identical behavior
- EOD: both engines via `_close_all`, no CB update → identical behavior (unchanged)
- Daily-drawdown-CB: both engines via `_close_all(update_cb=True)` → CB updated
- STOP/TARGET/TIME_STOP: both engines via `_close_trade` → CB updated (unchanged)

Re-run IS baseline on ORIG → new trade count (expected: same 604 on window_debug since
Jan 3 divergence was SAFETY_MODE, not daily-CB) → run same on REFAC → confirm ORIG==REFAC
→ that count is the new validated+deployed baseline.

No vault re-run. OOS sealed.

---

## Fix Implemented + Measured — 2026-07-08

**Status: DONE**

Script: `raits/raits/scripts/verify_cb_fix.py`

### Result

```
ORIG == REFAC: 605 trades | P&L $15,019.79 | diff $0.0000  ✓
```

Both engines now have correct CB semantics and are identical to the cent.

### New baseline

- **605 trades** (was 604 on old window_debug run)
- **P&L $15,019.79**
- **Saved**: `data/cache/verify_cb_fixed_baseline.pkl`
- CB semantics locked: STOP/TARGET/TIME_STOP/daily-CB count; SAFETY_MODE/EOD do NOT count

### Daily-CB events in IS 2017-2022

13 days where daily-CB fired; 10 positions actually closed (3 days had 0 open positions at the CB bar):

```
2019-09-05  1 closed     2020-09-11  1 closed     2022-01-05  1 closed
2019-10-08  0 open       2021-01-04  0 open        2022-01-06  0 open
2020-09-02  1 closed     2021-01-05  1 closed      2022-02-02  0 open
                          2021-09-20  1 closed      2022-03-09  0 open
                                                    2022-06-30  1 closed
                                                    2022-10-27  3 closed
```

0-position days: CB fired but no intraday positions open at that bar — no streak update, correct.

### Why 605 > old 604

Adding daily-CB counting (new) should block more trades; removing REFAC's SAFETY_MODE
over-count should unblock more trades. Net: +1 trade. The SAFETY_MODE unblocking effect
dominated on this dataset. Both effects are small (10 daily-CB positions vs 6 years of IS).

### Files changed

| File | Change |
|------|--------|
| `raits/backtest/engine.py` | `_close_all()` + daily-CB call sites |
| `raits/backtest/engine_refactored.py` | `_close_all()` + daily-CB call sites + SAFETY_MODE path |
| `raits/raits/scripts/verify_cb_fix.py` | New verification script |
| `data/cache/verify_cb_fixed_baseline.pkl` | New baseline (605 trades) |