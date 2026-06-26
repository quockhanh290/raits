# Decision Unit — Task 3: RefactoredBacktestEngine

> **For agentic workers:** Use superpowers:subagent-driven-development to execute.
> Depends on Tasks 1 and 2.

**Goal:** Create `engine_refactored.py` — identical to `engine.py` except `_run_day`'s bar loop delegates entry/exit decisions to `DecisionUnit.decide()`.

**Files:**
- Create: `raits/raits/backtest/engine_refactored.py`
- NEVER modify: `raits/raits/backtest/engine.py`

---

## What changes vs engine.py

1. `__init__` creates a `DecisionUnit` instance (stored as `self._decision_unit`)
2. `run()` passes strategy/risk instances to `DecisionUnit` at construction time
3. `_run_day()` is restructured: the bar loop calls `decision_unit.decide(ctx)` then executes intents
4. Everything else (`_close_trade`, `_close_all`, `_update_swing_stops`, `_compute_costs`, `_load_modules`, etc.) is UNCHANGED

---

- [ ] **Step 1: Write `raits/raits/backtest/engine_refactored.py`**

Start by copying `engine.py` verbatim, then apply these targeted changes:

**Add import at top (after existing imports):**
```python
from raits.decision.decision_unit import DecisionUnit
from raits.decision.types import BarContext
```

**In `run()`, after creating `trend` and before `hmm = HMMEngine()`, construct the DecisionUnit:**
```python
self._decision_unit = DecisionUnit(
    config=self.config,
    orb=orb,
    stress_orb=stress_orb,
    fade_orb=fade_orb,
    vwap_mr=vwap_mr,
    trend=trend,
    coordinator=coordinator,
    position_sizer=position_sizer,
    pdt_guard=pdt_guard,
)
```

**In `_run_day()`, after daily resets and before the bar loop, call:**
```python
self._decision_unit.reset_day(day, orb_signal_start, orb_signal_end)
```
(Remove: `orb.reset()`, `stress_orb.reset()`, `fade_orb.reset()`, `vwap_mr.reset()` / `trend.reset()` calls, and `coordinator.reset_for_new_session()` call — those are now inside `reset_day()`.)

**Replace the entire bar loop body** with a delegate + execute pattern. The bar loop becomes:

```python
for bar_ts, spy_bar in day_spy.iterrows():
    if self._circuit_breaker_active:
        break

    spy_history.append(spy_bar)
    bar_t  = bar_ts.time()
    bar_dt = bar_ts.to_pydatetime()

    # Compute HMM state once per day (stays in engine; result passed to DecisionUnit via BarContext)
    if not _regime_updated_today:
        spy_daily = to_daily_close(
            spy_data[spy_data.index.normalize() <= bar_ts.normalize()]
        )
        if len(spy_daily) >= 20:
            try:
                if _hmm is not None and len(spy_daily) >= 21:
                    _state_idx = _hmm.predict_current(spy_daily)
                    self._hmm_state = _hmm.state_name(_state_idx)
                _log_ret = np.log(spy_daily / spy_daily.shift(1)).dropna()
                _rv = _log_ret.rolling(5).std() * np.sqrt(252)
                _rv = _rv.dropna()
                if len(_rv) >= 5:
                    _cur_vol = float(_rv.iloc[-1])
                    if _cur_vol >= 0.50:
                        self._hmm_state = "Crisis"
            except Exception as e:
                logger.debug(f"regime detection failed: {e}")
        _regime_updated_today = True

    self._regime_bar_counts[self._hmm_state] = (
        self._regime_bar_counts.get(self._hmm_state, 0) + 1
    )

    # Build BarContext for this bar
    ctx = BarContext(
        bar_ts=bar_ts,
        spy_bar=spy_bar,
        spy_history=list(spy_history),
        day_stocks=day_stocks,
        market_data=market_data,
        open_trades=list(self.trade_log.open_trades),
        hmm_state=self._hmm_state,
        cur_vol=_cur_vol,
        day=day,
        orb_vix_ok=_orb_vix_ok,
        stress_orb_vix_ok=_stress_orb_vix_ok,
        effective_orb_universe=_effective_orb_universe,
        effective_vwap_universe=_effective_vwap_universe,
        effective_fade_universe=_effective_fade_universe,
        all_tickers=_all_tickers,
        base_universe=_base_universe,
        stress_stocks=_stress_stocks,
        spy_or_high=_spy_or_high,
        spy_or_low=_spy_or_low,
        spy_bull_trend=_spy_bull_trend,
        daily_spy_close=_daily_spy_close,
        pe_short_calendar=self._pe_short_calendar,
        fade_atr_top2=fade_atr_top2,
        vwap_bb_std=self.config.vwap_bb_std,
        ema_period=self.config.ema_period,
        vwap_mr_vol_threshold=self.config.vwap_mr_vol_threshold,
        allow_swing_hold=self.config.allow_swing_hold,
        enable_pdt_guard=self.config.enable_pdt_guard,
        stress_size_fraction=self.config.stress_size_fraction,
        orb_signal_start=orb_signal_start,
        orb_signal_end=orb_signal_end,
    )

    # Get decisions from DecisionUnit
    result = self._decision_unit.decide(ctx)

    if result.override_active:
        if not self._safety_mode_active:
            logger.critical(f"{bar_ts} | SAFETY MODE ON")
            self._safety_mode_active = True
    else:
        if self._safety_mode_active:
            logger.info(f"{bar_ts} | SAFETY MODE OFF")
            self._safety_mode_active = False

    # Execute exits
    for exit_intent in result.exits:
        self._close_trade(
            exit_intent.trade, bar_ts, exit_intent.exit_price, exit_intent.reason,
            circuit_breakers, coordinator, bar_dt,
        )

    # Execute entries
    for entry_intent in result.entries:
        trade = self.trade_log.open_trade(
            ticker=entry_intent.ticker,
            strategy=entry_intent.strategy,
            direction=entry_intent.direction,
            entry_time=bar_ts,
            entry_price=entry_intent.entry_price,
            shares=entry_intent.shares,
            stop=entry_intent.stop,
            target=entry_intent.target,
            hmm_state=entry_intent.hmm_state,
            limiting_factor=entry_intent.limiting_factor,
        )
        self._decision_unit.on_trade_opened(trade, entry_intent)
        logger.info(
            f"{bar_ts} | OPEN {entry_intent.ticker} {entry_intent.strategy} "
            f"{entry_intent.direction} {entry_intent.shares}sh "
            f"@ ${entry_intent.entry_price:.2f} | "
            f"stop=${entry_intent.stop:.2f} target=${entry_intent.target:.2f} | "
            f"Regime:{entry_intent.hmm_state} Limit:{entry_intent.limiting_factor}"
        )
        if self.config.enable_pdt_guard and entry_intent.is_day_trade:
            try:
                pdt_guard.record_day_trade(bar_ts.date())
            except Exception:
                pass

    # Daily drawdown circuit breaker (stays in engine — needs equity)
    try:
        dd = circuit_breakers.check_daily_drawdown(
            account_equity=self.equity_tracker.equity,
            session_start_equity=session_start_equity,
        )
        if dd.kill_switch:
            try:
                coordinator.notify_circuit_breaker(bar_dt)
            except Exception:
                pass
            logger.critical(f"{bar_ts} | CIRCUIT BREAKER: {dd.reason}")
            self._close_all(bar_ts, day_stocks, "CIRCUIT_BREAKER")
            self._circuit_breaker_active = True
            break
    except Exception as e:
        logger.debug(f"CB check error: {e}")
        pnl_pct = self.equity_tracker.daily_pnl_pct
        if pnl_pct <= -0.04:
            logger.critical(f"{bar_ts} | CIRCUIT BREAKER (fallback): {pnl_pct:.2%}")
            self._close_all(bar_ts, day_stocks, "CIRCUIT_BREAKER")
            self._circuit_breaker_active = True
            break
```

**Variables that must be initialised before the bar loop** (remove from bar loop where they were computed inline, add before `for bar_ts, spy_bar in day_spy.iterrows():`):
```python
_regime_updated_today = False
_cur_vol: float = 0.20
spy_history: List[pd.Series] = []
```

Note: `day_stocks`, `_effective_orb_universe`, `_effective_vwap_universe`, `_effective_fade_universe`, `_all_tickers`, `_base_universe`, `_stress_stocks`, `_spy_or_high`, `_spy_or_low`, `_spy_bull_trend`, `_daily_spy_close`, `_orb_vix_ok`, `_stress_orb_vix_ok`, `fade_atr_top2` are all set before the bar loop in `_run_day()` — keep them exactly as in `engine.py`.

**Remove from `_run_day()`** all the variables that are now inside `DecisionUnit`:
- `orb_scanned`, `or_ranges`, `pending_orb`, `orb_hist_avg_vol`
- `fade_scanned_done`, `fade_or_ranges`, `pending_fades`
- `stress_orb_scanned`, `stress_or_ranges`
- `_gf_triggered`, `_gfs_triggered`, `_rs_triggered`, `_stress_mid_triggered`, `_pe_triggered`
- `_gf_stop_dists`, `_gfs_stop_dists`

**`_close_trade()` addition** — after the existing TF cooldown line, add a call for when a TF STOP_HIT occurs. Actually, the DecisionUnit already handles TF cooldown internally in `decide()` when it detects STOP_HIT in the swing exit section. So NO change needed to `_close_trade()` for TF cooldown — the DecisionUnit detects the exit and updates its own `_tf_cooldown` before returning ExitIntent.

However, to keep `_close_trade()` identical to `engine.py`, keep the TF cooldown line there too (it's idempotent since DecisionUnit already set it):

Actually, this creates a problem: if `_close_trade()` sets TF cooldown AND `decide()` also sets it, we'd set it twice. In the DecisionUnit, the cooldown is set when detect exits in section 2 (swing exits). In the original engine, it's set in `_close_trade`. These must agree.

**Solution**: In `engine_refactored.py`, remove the TF cooldown line from `_close_trade()` since `DecisionUnit.decide()` now owns `_tf_cooldown`. The cooldown is set in `decide()` when it adds a TF STOP_HIT to exits.

BUT there's a problem: `_tf_cooldown` is now inside `DecisionUnit`. The engine's `_close_all` (for CIRCUIT_BREAKER, EOD, SAFETY_MODE) also closes TF positions. When CB closes a TF position at STOP_HIT equivalent... actually CB doesn't set cooldown in the original engine either — only `_close_trade` with `reason=="STOP_HIT"` does. And CB bypass is a different code path.

For the refactored engine: the only place TF STOP_HIT is detected is in `decide()` section 2 (swing exits). When `_close_all` runs (CB, EOD), those aren't STOP_HIT. So cooldown is only set in decide(). The `_close_trade()` in `engine_refactored.py` should NOT set `_tf_cooldown` (it belongs to DecisionUnit now).

**`_close_trade()` in `engine_refactored.py`**: Remove the lines:
```python
if reason == "STOP_HIT" and trade.strategy == "TREND_FOLLOW":
    self._tf_cooldown.setdefault(trade.ticker, {})[trade.direction] = trade.stop
```
And remove `self._tf_cooldown` from `__init__` (it lives in DecisionUnit now).

**Summary of changes to `engine.py` → `engine_refactored.py`:**

| What | Change |
|------|--------|
| `__init__` | Remove `_tf_cooldown`; add `_decision_unit: Optional[DecisionUnit] = None` |
| `run()` | Construct `DecisionUnit` after strategy instances, before HMM training |
| `_run_day()` | Add `reset_day()` call; bar loop delegates to `decide()`; remove all intraday state vars |
| `_close_trade()` | Remove TF cooldown lines (owned by DecisionUnit) |
| Everything else | Identical to engine.py |

- [ ] **Step 2: Smoke test — can construct and run one day**
```python
# smoke_test_refactored.py
import sys; sys.path.insert(0, ".")
from raits.backtest.engine_refactored import RefactoredBacktestEngine
from raits.backtest.data_types import BacktestConfig
from raits.data.raits_mock_data import generate_mock_market_data
print("RefactoredBacktestEngine imported OK")
```

Run:
```
cd d:\raits\raits
python smoke_test_refactored.py
```
Expected: no ImportError.

- [ ] **Step 3: Commit**
```
git add raits/backtest/engine_refactored.py
git commit -m "feat: implement RefactoredBacktestEngine delegating bar decisions to DecisionUnit"
```
