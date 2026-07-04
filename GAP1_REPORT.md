# Gap 1 — Live vs Backtest Divergence Report

**Branch:** `future/incorporation`  
**Date:** 2026-07-04  
**Scope:** IS 2017–2022 (604 trades verified)  
**Finding:** 9 trades with different `exit_price` between `LivePolygonFeed` (incremental) and `ReplayContextFeed` (full-day)

---

## Background

Part 3 verification confirmed `ReplayContextFeed == engine_refactored` to the cent (604/604 trades, $15,952.15 net PnL). This session ran Part 3 again with `LivePolygonFeed` (`_test_market_data` mode, incremental `day_stocks` semantics). Result: **595 trades match exactly; 9 trades diverge in `exit_price`**.

The 9 divergent trades (entry matches; only exit_price differs):

| Ticker | Strategy | Exit Date |
|--------|----------|-----------|
| AAPL   | TREND_FOLLOW | 2022-11-03 |
| ADBE   | TREND_FOLLOW | 2022-11-04 |
| AMZN   | TREND_FOLLOW | 2019-09-05 |
| INTC   | ORB          | 2022-01-05 |
| META   | PE_SHORT     | 2022-10-27 |
| QQQ    | STRESS_MID   | 2019-01-03 |
| QQQ    | STRESS_ORB   | 2020-10-30 |
| REGN   | TREND_FOLLOW | 2022-10-27 |
| VRTX   | ORB          | 2019-08-01 |

---

## STEP 1 — When Are Chandelier / day_stocks Values Read?

### `_update_swing_stops` (chandelier stops, TF only)

Called at **day boundary** in runner — start of day D+1, using `_prev_ctx.day_stocks`:

```python
# runner.py — on new-day detection
self._update_swing_stops(
    _prev_ctx.day, _prev_ctx.market_data, _prev_ctx.day_stocks
)
```

`_prev_ctx` = last bar of day D (the 15:55 bar). At that point, `LivePolygonFeed` incremental has accumulated **all bars of day D** (9:30 → 15:55). So:

```python
# engine_refactored.py:1467
day_high = float(day_stocks[ticker]["high"].max())   # all bars present
day_low  = float(day_stocks[ticker]["low"].min())
```

**Result: identical** between engine and live. Chandelier stop LEVEL is the same in both paths.

### Intraday reads (VWAP, ATR, signal computation)

Engine uses `.loc[:bar_ts]` on full-day `day_stocks`. Live incremental `day_stocks` already contains only bars up to `bar_ts`. Result is the same slice — **identical**.

### MAX_HOLD exit price

```python
# engine_refactored.py:626 and runner.py:753 — both use iloc[0]
_px = float(day_stocks[ticker].iloc[0]["open"])   # first bar of new day
```

At the first bar of day D+1, both paths have the first bar available. `.iloc[0]` = 9:30 open — **identical**.

**STEP 1 conclusion:** Chandelier stop level, intraday reads, and MAX_HOLD are all equivalent. The divergence is elsewhere.

---

## STEP 2 — Why Only 9 Trades Diverge, Not All 604

### Why 595 match

The vast majority of exits go through `_check_exits` in `decision_unit.py`:

```python
# decision_unit.py:1057
bar = day_stocks[trade.ticker].loc[bar_ts]   # direct key lookup for current bar
bar_low   = float(bar["low"])
bar_high  = float(bar["high"])
bar_close = float(bar["close"])
```

`.loc[bar_ts]` is a direct key lookup for bar T. In `ReplayContextFeed`, full-day `day_stocks` contains bar T; in `LivePolygonFeed`, incremental `day_stocks` also contains bar T (it's the current bar). **Both return identical data.** Exit prices (`trade.stop`, `trade.target`, `bar_close`) are the same.

### Why 9 diverge — the shared read-point

The 9 divergent trades all exit via **Circuit Breaker (CB) or SAFETY_MODE** — two code paths that use `day_stocks[ticker].iloc[-1]`:

| Code path | File | Line | Description |
|-----------|------|------|-------------|
| SAFETY_MODE | `decision_unit.py` | 234 | Force-close non-swing when `not trading_ok` |
| `_close_all_cb` | `runner.py` | 629 | Force-close all positions when CB kill switch fires |

Both compute exit price as:

```python
_bar = day_stocks[ticker].iloc[-1]
_px  = float(_bar["close"])
```

The comment in `decision_unit.py` explicitly states the assumption:

> *"day_stocks holds the full day's bars from the start, so iloc[-1] is the end-of-day bar."*

**This assumption is true for `ReplayContextFeed`, false for `LivePolygonFeed`:**

| Feed | `day_stocks` content at bar T | `iloc[-1]` result |
|------|-------------------------------|-------------------|
| `ReplayContextFeed` | Full-day (all 26 bars pre-loaded) | **15:55 bar close** |
| `LivePolygonFeed` | Incremental (bars 9:30 → T only) | **bar T close** |

When CB fires or SAFETY_MODE triggers at bar T (e.g., 10:30):
- **Backtest** exit price = 15:55 close (a price that hasn't occurred yet at 10:30)
- **Live** exit price = 10:30 close (the honest current-market price)

### Mechanism mapping for the 9 trades

`_close_all_cb` has **no TF/PE_SHORT exclusion** — closes all eligible positions. `SAFETY_MODE` in `decision_unit.py:228-229` **excludes TF and PE_SHORT**.

| Trade | Primary mechanism |
|-------|-------------------|
| AAPL TF 2022-11-03 | `_close_all_cb` — `runner.py:629` |
| ADBE TF 2022-11-04 | `_close_all_cb` — `runner.py:629` |
| AMZN TF 2019-09-05 | `_close_all_cb` — `runner.py:629` |
| REGN TF 2022-10-27 | `_close_all_cb` — `runner.py:629` |
| META PE_SHORT 2022-10-27 | `_close_all_cb` — `runner.py:629` |
| INTC ORB 2022-01-05 | SAFETY_MODE — `decision_unit.py:234` |
| QQQ STRESS_MID 2019-01-03 | SAFETY_MODE — `decision_unit.py:234` |
| QQQ STRESS_ORB 2020-10-30 | SAFETY_MODE — `decision_unit.py:234` |
| VRTX ORB 2019-08-01 | SAFETY_MODE — `decision_unit.py:234` |

---

## STEP 3 — Which Is Correct for Real Live Trading?

**Live (`iloc[-1]` = bar T close) is the correct behavior.**

In real live trading, when a CB fires at 10:30:
- Broker executes at ~10:30 market price
- The 15:55 close price does not yet exist — it cannot be the fill
- Using 15:55 close as the exit price assumes knowledge of a future bar

The backtest exit (`day_stocks.iloc[-1]` = full-day last bar = 15:55) is a **look-ahead**: it uses a price from a bar that hasn't occurred at the moment of the exit decision. Live correctly uses the close of the bar where the exit was triggered.

---

## STEP 4 — Summary

### Root cause

**`day_stocks[ticker].iloc[-1]["close"]`** — used in two places, both assuming full-day data:

1. `decision_unit.py:234` — SAFETY_MODE exit for non-swing trades
2. `runner.py:629` — `_close_all_cb` for all trades including TF/PE_SHORT

### Why only 9

595 other trades exit via `_check_exits` using `.loc[bar_ts]` — a key lookup that is identical in both feeds. Only CB and SAFETY_MODE exits use `iloc[-1]`, and only those trades open when a CB or SAFETY_MODE fires mid-day show divergence.

### Verdict

| Group | Mechanism | Is it a live bug? |
|-------|-----------|-------------------|
| TF×4, PE_SHORT×1 | `_close_all_cb` — `runner.py:629` | **No** — live is correct; backtest has look-ahead |
| ORB×2, STRESS_MID×1, STRESS_ORB×1 | SAFETY_MODE — `decision_unit.py:234` | **No** — live is correct; backtest has look-ahead |

**The backtest used a look-ahead price for 9/604 trades (1.5%).** Live P&L will differ from IS P&L on days where CB or SAFETY_MODE fires before 15:55. The direction of the difference is not systematic — it depends on whether price moved up or down from the trigger bar to 15:55 on each specific day.

### Fix options (not yet applied)

To make live match backtest (not recommended — introduces look-ahead into live):
- Replace `iloc[-1]` with `loc[bar_ts]` in both locations

To make backtest honest (recommended if modifying engine is ever permitted):
- Modify `engine._close_all` and `decision_unit.py` SAFETY_MODE path to use the trigger bar's price, not `iloc[-1]`
- Engine files are currently off-limits

### Current state

- `verify_live_path.py` patched with `emit_timeout=0.01` (previous run hung due to 10s queue timeout)
- Verification with `--live-feed` confirmed 9 divergent trades
- Gap 1 is **real but is backtest look-ahead, not a live bug**
- The 604-trade Replay==engine guarantee still holds; the live path diverges on 9 CB/SAFETY_MODE exits
- No code changes made to engine.py or decision_unit.py (per constraints)
