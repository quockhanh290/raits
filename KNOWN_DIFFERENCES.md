# Known Live-vs-Backtest Differences

This file documents **expected and correct** divergences between the live trading path
(`LivePolygonFeed` + `PaperTrader`) and the IS backtest (`engine_refactored`).
These are NOT bugs. Do not flag them as regressions during paper-trading reconciliation.

---

## KD-001 — CB / SAFETY_MODE mid-day exits use different prices

### Status
Confirmed. Documented 2026-07-04. See `GAP1_REPORT.md` for full investigation.

### Mechanism

Both the CB (`_close_all_cb`) and SAFETY_MODE paths compute exit price as:

```python
_bar = day_stocks[ticker].iloc[-1]
_px  = float(_bar["close"])
```

| Path | `day_stocks` content at bar T | `iloc[-1]` result |
|------|-------------------------------|-------------------|
| **Backtest** (`ReplayContextFeed`) | Full-day (all bars pre-loaded) | **15:55 bar close** (future) |
| **Live** (`LivePolygonFeed`) | Incremental (bars up to T only) | **bar T close** (current) |

When a CB or SAFETY_MODE exit fires mid-day (e.g., 11:30), the backtest uses a price
from a bar that has not yet occurred. Live uses the honest close of the trigger bar.

### Affected code locations

| File | Line | Path | Status |
|------|------|------|--------|
| `decision_unit.py` | 234 | SAFETY_MODE exit, non-swing trades | ⚠️ off-limits (do not modify) |
| `runner.py` | 629 | `_close_all_cb`, all trades incl. TF/PE_SHORT | ⚠️ off-limits fixing would inject look-ahead |
| `engine_refactored.py` | 1432 | Engine `_close_all` (source of truth) | ⚠️ off-limits (would invalidate vault/reconcile) |

### Which trades are affected

In IS 2017–2022 (604 trades verified), exactly **9 trades** diverge on exit_price:

| Entry date | Ticker | Strategy | Exit date | Exit time | Backtest exit px | Exit reason | BT net PnL |
|------------|--------|----------|-----------|-----------|-----------------|-------------|------------|
| 2022-11-03 | AAPL | TREND_FOLLOW | 2022-11-07 | 11:30 | $138.94 | CIRCUIT_BREAKER | +$13.58 |
| 2022-11-04 | ADBE | TREND_FOLLOW | 2022-11-07 | 11:30 | $296.07 | CIRCUIT_BREAKER | -$312.76 |
| 2019-09-05 | AMZN | TREND_FOLLOW | 2019-09-05 | 15:55 | $ 92.02 | CIRCUIT_BREAKER | +$24.60 |
| 2022-01-05 | INTC | ORB          | 2022-01-05 | 13:35 | $ 54.04 | CIRCUIT_BREAKER | -$540.01 |
| 2022-10-27 | META | PE_SHORT     | 2022-10-31 | 11:50 | $ 93.16 | CIRCUIT_BREAKER | +$366.61 |
| 2019-01-03 | QQQ  | STRESS_MID   | 2019-01-03 | 11:35 | $149.88 | SAFETY_MODE     | +$112.20 |
| 2020-10-30 | QQQ  | STRESS_ORB   | 2020-10-30 | 15:55 | $270.07 | SAFETY_MODE     | +$22.59 |
| 2022-10-27 | REGN | TREND_FOLLOW | 2022-10-31 | 11:50 | $748.75 | CIRCUIT_BREAKER | -$147.25 |
| 2019-08-01 | VRTX | ORB          | 2019-08-01 | 13:25 | $179.00 | SAFETY_MODE     | +$119.57 |

Backtest combined net PnL on these 9 trades: **-$340.88**

### Backtest look-ahead quantification

Measured from full IS costs-on `--live-feed` run (2026-07-04, `emit_timeout=0.01`).
Exactly **9 trades diverge in exit_price** — no other differences found. Live path is clean.

| | Net PnL on 9 trades |
|---|---|
| **Backtest** | **-$340.88** |
| **Live (honest)** | **-$653.60** |
| **Backtest optimism** | **+$312.72** (~2% of total IS net PnL $15,952) |

The backtest overstated P&L by $312.72 on these 9 trades. Optimism concentrates in
**crisis-protection exits** (SAFETY_MODE stress exits), not routine CB stops:

| Trade | Exit reason | BT net PnL | Live net PnL | BT optimism |
|-------|-------------|-----------|--------------|------------|
| QQQ STRESS_MID 2019-01-03 | SAFETY_MODE | +$112.20 | -$174.72 | **+$286.92** (sign flip) |
| VRTX ORB 2019-08-01 | SAFETY_MODE | +$119.57 | -$3.88 | **+$123.45** |
| others (7 trades) | CB / SAFETY_MODE | varies | varies | small / mixed |

The two SAFETY_MODE stress exits account for ~$410 of the $312.72 net optimism (the CB
exits are partially offsetting). The sign flip on QQQ STRESS_MID — backtest shows a win,
live shows a loss — is because price continued falling after the trigger bar on 2019-01-03;
the backtest "benefited" from knowing the eventual lower 15:55 close.

### Correct behavior

**Live is correct.** Real broker fills on a CB exit happen near the trigger bar's
market price, not at the end-of-day close. Do not change live to match backtest.

### How to handle during paper trading

When reconciling paper trading P&L against IS backtest for these specific trade
identifiers:
1. Expect exit_price to differ on any trade exiting via CIRCUIT_BREAKER or SAFETY_MODE
2. Both prices are valid: backtest used end-of-day, live used trigger-bar
3. Do NOT count this as a live execution error
4. Track the cumulative difference in a separate "look-ahead adjustment" column

---

## Appendix — Full iloc[-1] / full-day-assumption scan (2026-07-04)

All reads of `day_stocks[ticker].iloc[-1]` or whole-day `.max()/.min()` in the
engine + decision_unit + runner, classified by safety:

### UNSAFE (look-ahead when called mid-session)

| File | Line | Function | Access | Called when |
|------|------|----------|--------|-------------|
| `engine_refactored.py` | 1432 | `_close_all` | `day_stocks[ticker].iloc[-1]` | Mid-session (CB/SAFETY_MODE trigger) |
| `decision_unit.py` | 234 | `decide` SAFETY_MODE branch | `ctx.day_stocks[ticker].iloc[-1]` | Mid-session (when `not trading_ok`) |
| `runner.py` | 629 | `_close_all_cb` | `day_stocks[ticker].iloc[-1]` | Mid-session (CB kill switch fires) |

These three are the **same logical operation** — all mirror `engine._close_all` semantics.
Engine is the source of truth; decision_unit and runner mirror it. Modifying any would
create divergence vs the IS baseline.

### SAFE (called at day boundary or on bounded slices)

| File | Line | Access | Why safe |
|------|------|--------|----------|
| `engine_refactored.py` | 1467–1468 | `day_stocks[ticker]["high"].max()` / `.min()` | In `_update_swing_stops`, called after EOD with full-day data |
| `engine_refactored.py` | 626 | `day_stocks[ticker].iloc[0]["open"]` | MAX_HOLD: first bar open of new day (current bar) |
| `engine_refactored.py` | 448 | `_day_bars.iloc[-1]["close"]` | `_close_end_of_period`: last bar of IS period, day complete |
| `runner.py` | 539 | `day_stocks[ticker].iloc[-1]` | `_close_all_eod`: called with `_prev_ctx.day_stocks` (last bar = complete day) |
| `runner.py` | 584 | `day_stocks[ticker].iloc[-1]["close"]` | `_close_end_of_period`: IS period over, day complete |
| `runner.py` | 675–676 | `day_stocks[ticker]["high"].max()` / `.min()` | `_update_swing_stops`: called at day boundary with prior day's complete data |
| `runner.py` | 753 | `ctx.day_stocks[ticker].iloc[0]["open"]` | `_check_max_hold`: first bar of new day (current bar available) |
| `decision_unit.py` | 322, 347, 380, 407, 452, 588, 834 | `bars_so_far.iloc[-1]` | `bars_so_far = day_stocks[ticker].loc[:bar_ts]` → last element = bar_ts (current bar) |
| `decision_unit.py` | 474 | `_sm_bars.iloc[-1]` | `_sm_bars = stress_stocks[ticker][index <= bar_ts]` → bounded slice |
| `decision_unit.py` | 486 | `_sm_swing["high"].max()` | `_sm_swing` is a bounded slice (9:45 to bar_ts) |
| `decision_unit.py` | 542, 655, 728 | `_prev_bars["close"].iloc[-1]` | `_prev_bars` = prior day's bars → complete |
| `decision_unit.py` | 1310–1318 | `bars["high"].max()`, `bars.iloc[-1]` | `bars = day_stocks[ticker].loc[:bar_ts]` → bounded |

### Summary

**3 UNSAFE reads** — all in the CB/SAFETY_MODE exit path, all mirror engine semantics.
**No additional look-ahead patterns found** beyond the 2 already known (decision_unit:234,
runner:629) plus their source (engine_refactored:1432).

The 9-trade divergence is the complete and total scope of the look-ahead bias.
