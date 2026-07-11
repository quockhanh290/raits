# Live Runner Audit — Signal Timing Divergence

**Date**: 2026-07-09  
**Status**: FINDINGS COMPLETE — fix not yet implemented  
**Branch**: `future/incorporation`

---

## TL;DR

`run_live_day.py` uses a **pre-computed timeline lookup** (copied from `verify_runner_real.py`) instead of calling `generate_today_signals()`. The strategy fires entries intraday at 14:05–15:55 ET; the live runner fills at ~16:00 ET after the A5 parquet update. Measured delta across IS: **−$9,112 (−20.2% of backtest P&L)**. Six specific mismatches documented. Fix is Option C: replace signal_fn with `generate_today_signals()` wrapper + through=now() + 5-min cron.

---

## 1. Strategy Design (Ground Truth)

`SwingTFEngine` is an **intraday event-driven** strategy:

```python
# futures/_validated_core.py:310-326
bars5 = b5[day]; win = bars5.between_time("14:00", "15:55")
for n in range(1, len(idx)):
    hist = bars5.loc[:idx[n]]          # all bars from midnight → scan point
    ema = s.calculate_ema(hist, ema_period)
    sig = s.generate_signal(win.loc[idx[n-1]], win.loc[idx[n]], ema, atr, reg, avgv)
    if sig:
        pos = dict(..., entry=sig["entry_price"], entry_time=idx[n])
        break
```

- Window scanned: 14:00–15:55 ET, bar-by-bar
- Signal fires at **first bar** where pullback+volume pattern matches
- Entry = **that bar's close price** (could be 14:05, 14:30, 15:00, etc.)
- `entry_time` stored in trade dict = actual fire timestamp

**Measured fire-time distribution (IS, 1,749 swing trades):**

| Window        | Trades | Share |
|---------------|-------:|------:|
| 14:00–14:15   |    217 |  12%  |
| 14:15–14:30   |    298 |  17%  |
| 14:30–15:00   |    540 |  31%  |
| 15:00–15:35   |    499 |  29%  |
| 15:35–15:55   |    195 |  11%  |

- **Median fire**: 14:45 ET (45 min into window)
- **40% fire after 15:00**

---

## 2. Root Cause

### Where the timeline pattern came from

`verify_runner_real.py` runs an 8-year replay. Calling `desired_position()` per day would be O(n²) via `_SWING_CACHE`. Its docstring (line 6):

> "Uses pre-computed trade timelines (O(n) total) instead of calling desired_position() per day (which would be O(n²) via _SWING_CACHE)."

`real_signal_fn` in `verify_runner_real.py` builds `swing_sorted`, `nkd_sorted`, `stress_by_day` then does a dict lookup per day.

### What went wrong

`run_live_day.py` **copied this timeline pattern** verbatim. For live execution (1 day), O(n) vs O(n²) is irrelevant — but the pattern was carried over anyway. Result: the live runner bypasses `generate_today_signals()` entirely.

`runner.py` docstring (line 5) explicitly states the intent:

> "broker.fetch_bars → **signal_layer.generate_today_signals** → decide_day"

And line 162:

> "signal_fn wraps signal_layer.generate_today_signals"

The implementation violates both docstrings.

---

## 3. The Six Mismatches (A–F)

### A — `_bars` ignored (underscore convention)

`runner.py:527`:
```python
bars = {i: self.broker.fetch_bars(i, through=day) for i in insts}
```

`run_live_day.py` `signal_fn` receives these bars as `_bars` (underscore = intentionally ignored). No intraday bar data reaches the signal function.

### B — `through=midnight` → yesterday's bars

`day` passed to `fetch_bars` is:
```python
day = pd.Timestamp.now().normalize()   # midnight today
```

`fetch_bars(through=midnight)` with `durationStr="2 D"` returns yesterday's bars. Combined with Mismatch A (bars ignored), this is doubly irrelevant — but fixing A without fixing B would still give wrong data.

**Fix**: `through = pd.Timestamp(day) + pd.Timedelta(hours=23, minutes=59)` to get bars through end of session.

### C — Timeline lookup instead of `generate_today_signals`

The signal_fn in `run_live_day.py` (around line 254):
1. Runs full backtest on historical parquet: `swing_bt, stress_bt, nkd_bt`
2. Pre-sorts by entry_day: `swing_sorted, nkd_sorted, stress_by_day`
3. Per-day: looks up `new_ed` (entry_day) from sorted list → `desired[key] = sig if new_ed == day_ts else None`

With parquet ending yesterday, `new_ed` for any pending trade is yesterday's date → `new_ed < today` → guard fails → **all signals suppressed for today**. Signals only appear for historical dates where parquet was current at run time.

**What should happen**: Call `generate_today_signals(day, swing_dfs, nkd_df, ...)` which calls `desired_basket()` → `desired_position()` → runs the backtest *through today's date* → returns open position at day-end → entry is active only if `entry_day == today`.

### D — One-shot instead of 5-min loop

Current architecture: runner called **once** after A5 parquet update (~16:00 ET), evaluates full session state in one shot.

Strategy design: should evaluate **at each 5-min bar** in 14:05–15:55 ET window, enter when signal first fires.

With a one-shot at 15:55, the entry price can use the actual fire-bar close (Option B-live). With a one-shot at 16:00 (after parquet update), the earliest possible fill is 16:00 MARKET — a 75+ minute lag from median fire time of 14:45.

### E — UT-2 and UT-5 bug fixes in dead code

`DIVERGENCE_SWEEP.md:218-219`:

```
UT-2: Stale price retry — FIXED in generate_today_signals ✅ Fixed
UT-5: NKD late-bar — FIXED in generate_today_signals ✅ Fixed
```

Both fixes are implemented in `signal_layer.py:generate_today_signals()` (lines ~116 onwards). Since `generate_today_signals()` is never called in production (Mismatch C), both fixes are **dead code**.

- **UT-2**: `generate_today_signals()` retries stale price with backoff before treating signal as invalid
- **UT-5**: NKD date alignment — uses `today_norm` (ET) not `nkd_today_norm` to suppress late-feed bars

### F — runner.py docstring intent ≠ implementation

Two docstrings in `runner.py` explicitly state `generate_today_signals` as the intended path. The actual `run_live_day.py` injection never calls it. This gap was introduced when the timeline pattern was copied for the 8-year replay runner and then reused for live.

---

## 4. Impact Measurement

Script: `d:\raits\measure_fire_time.py`

**Delta: live@15:55 vs backtest@fire-time**

| Metric | Value |
|--------|-------|
| Trades analyzed | 1,749 |
| Backtest total P&L | +$45,079 |
| P&L delta (15:55 vs fire) | −$9,112 |
| Delta as % of BT | −20.2% |
| Per-trade delta | −$5 |
| Approximate Calmar BT | 5.39 |
| Approximate Calmar B-live (15:55) | 3.57 |
| Vault Calmar floor | 2.04 |

By fire-time bucket:
| Window | Trades | P&L Delta |
|--------|-------:|----------:|
| 14:00–14:15 | 217 | −$2,891 |
| 14:15–14:30 | 298 | −$2,541 |
| 14:30–15:00 | 540 | −$2,187 |
| 15:00–15:35 | 499 | −$1,214 |
| 15:35–15:55 | 195 | −$279 |

Early fires (14:00–14:15) have the largest absolute delta because prices move the most over a 1h45m interval. Late fires (15:35–15:55) are nearly irrelevant even for B-live@15:55.

**Verdict**: B-live (one-shot at 15:55) stays above vault Calmar floor (3.57 > 2.04), but loses 20% of P&L. **Option C (5-min loop) recovers this.**

---

## 5. The Correct Model — Option C

### What Option C looks like

```
09:30 ET — Morning runner:
    fetch_bars(through=now())
    generate_today_signals() → exits only + STRESS_MID entries
    send orders, persist state

14:05–15:55 ET — Every 5 minutes:
    fetch_bars(through=now())
    concat(frozen_parquet, live_bars) as swing_dfs
    generate_today_signals() → swing/NKD entries
    if new signal and entry_day==today → MarketOrder immediately
    persist state (live_positions.json prevents re-entry)

After 15:55: no new entries, trailing stops only
```

### Why Option C works

`desired_position()` runs the backtest *through now* and returns the open position at the end. If entry is today → signal is live. If run at 14:10 ET, entry fires at 14:10 bar close = same bar the backtest would enter. Fill lag: seconds (not hours).

`generate_today_signals()` docstring: *"live == backtest by construction because desired_position reads the backtest's own open-position timeline."*

State persistence (`live_positions.json`) prevents duplicate entries on subsequent 5-min runs.

### What `generate_today_signals()` already handles

| Issue | Location | Status after Option C |
|-------|----------|----------------------|
| UT-2 stale price retry | `signal_layer.py` ~line 140 | Active (was dead) |
| UT-5 NKD late-bar | `signal_layer.py` ~line 185 | Active (was dead) |
| Same-direction rollover | `signal_layer.py` `diff_desired_vs_held` | Active |
| C4 per-cluster isolation | `signal_layer.py` try/except | Active |
| Entry-day guard | `signal_layer.py` line ~130 | Active |

---

## 6. Files to Change

### Change 1 — `global_index/runner.py` (1 line)

**Line ~527:**
```python
# BEFORE
bars = {i: self.broker.fetch_bars(i, through=day) for i in insts}

# AFTER
through = pd.Timestamp(day) + pd.Timedelta(hours=23, minutes=59)
bars = {i: self.broker.fetch_bars(i, through=through) for i in insts}
```

This fixes Mismatch B. With `through=end-of-day`, `fetch_bars()` returns bars up to the current time (if `through` is in the past, returns all bars up to `through`).

### Change 2 — `global_index/run_live_day.py` (signal_fn replacement)

Replace the timeline lookup block with a `generate_today_signals()` wrapper:

```python
from global_index.signal_layer import generate_today_signals

def signal_fn(day, bars, held):
    day_ts = pd.Timestamp(day).normalize()
    today_norm = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)

    # concat frozen_parquet + live bars per instrument
    swing_dfs = {}
    for inst_key, inst in SWING_MAP.items():
        live = bars.get(inst_key)
        if live is not None and not live.empty:
            swing_dfs[inst_key] = pd.concat([frozen_dfs[inst_key], live]).sort_index().drop_duplicates()
        else:
            swing_dfs[inst_key] = frozen_dfs[inst_key]

    # nkd_df same pattern
    ...

    return generate_today_signals(day_ts, swing_dfs, nkd_df, labels, costs,
                                   held=held, today_norm=today_norm)
```

**Remove**: `swing_bt`, `stress_bt`, `nkd_bt` pre-compute block, `swing_sorted`, `nkd_sorted`, `stress_by_day` lookup. These were only needed for the O(n) timeline pattern.

### Change 3 — Cron schedule

Replace single 16:00 ET cron with:
- `09:30 ET` — morning runner (exits + STRESS_MID)
- `14:05, 14:10, ..., 15:55 ET` — every 5 min, swing/NKD entries

---

## 7. Pre-Implementation Checklist

Before implementing Option C:

- [ ] Verify `desired_position()` call path with live bars (concat parquet+live) produces same result as backtest on historical data
- [ ] Confirm `live_positions.json` re-entry prevention works across 5-min runs
- [ ] Test cold-start: first 14:05 run with no prior state → no spurious entries
- [ ] Confirm NKD timing: NKD session opens 18:00 ET prior day; 14:05 run sees today's NKD bars correctly
- [ ] Cron setup: Windows Task Scheduler or equivalent for 5-min cadence 14:05–15:55 ET

---

## 8. What Was NOT a Problem

- **No look-ahead bias**: Pre-computed timeline uses historical parquet (no future data). Guard `new_ed == day_ts` correctly suppresses signals when parquet ends yesterday. The runner does not cheat.
- **verify_runner_real.py**: The timeline pattern is *correct* there — designed for O(n) 8-year replay. The problem is only that it was copied to the live runner where performance trade-offs don't apply.
- **generate_today_signals() logic**: Already correct and tested. Option C doesn't require new signal logic — just wiring the existing function into the live path.

---

## 9. References

| File | Role |
|------|------|
| `global_index/run_live_day.py` | Production entry point — contains timeline lookup (to be replaced) |
| `global_index/runner.py` | FuturesRunner — `through=midnight` fix needed (line ~527) |
| `global_index/signal_layer.py` | `generate_today_signals()` — correct live path (currently dead) |
| `global_index/verify_runner_real.py` | Source of the O(n) timeline pattern |
| `global_index/DIVERGENCE_SWEEP.md` | UT-2/UT-5 tracking — "✅ Fixed" markers are misleading (dead code) |
| `futures/_validated_core.py:310-326` | Backtest scanning loop — defines correct intraday timing |
| `futures/swing_tf.py:47-61` | `desired_position()` — "live == backtest by construction" |
| `d:\raits\measure_fire_time.py` | Script that measured −$9,112 / −20.2% delta |
