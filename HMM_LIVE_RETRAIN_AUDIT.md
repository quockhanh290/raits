# HMM Live Retrain Cadence Audit

> Investigation only — no code changed. Generated 2026-07-02.
> Branch: future/incorporation

---

## Summary Table

| | Equity | Futures |
|---|---|---|
| **HMM fit at startup** | Once, anchored: SPY 2007 → `min(market_data)`−1day, from parquet | Once, `label_regimes()` call with `hmm_fit_end=2024-12-31` |
| **Periodic live retrain** | **WIRED** — Monday check in `_iter_live`, expands from 2017-01-03 | **NOT WIRED** — labels baked at startup, no scheduler |
| **Retrain trigger** | Day-boundary on first incoming WebSocket bar + `weekday() == 0`, 7-day min gap | N/A |
| **Retrain data window** | `_daily_spy_close` (sourced from `daily_data` passed at construction) | N/A |
| **Annual re-freeze** | N/A | **Manual only** — edit `basket.py`, update SPY CSV, restart |
| **Emergency retrain** | **NOT implemented** | **NOT implemented** |
| **Vol override (not a retrain)** | Wired — `cur_vol >= 0.50 → "Crisis"` | Not present |
| **<5% label change gate** | Not implemented | Not implemented (planned only) |

---

## STEP 1 — Equity Weekly Retrain: Is It Wired for Live?

**Answer: YES — fully wired in all three execution paths.**

### Path A: ReplayContextFeed (replay / paper-trading mode)

`raits/live/context_feed.py:267–277`, inside `_iter_all()`, at day boundary after each day:

```python
if config.hmm_retrain_weekly and day.weekday() == 0:
    if last_retrain is None or (day - last_retrain).days >= 7:
        recent_spy  = spy_data[spy_data.index.normalize() <= day]
        daily_close = _to_daily_close(recent_spy)
        if hmm is not None and len(daily_close) >= 35:
            try:
                hmm.retrain(daily_close)
            except Exception as e:
                logger.debug("HMM retrain failed: %s", e)
        last_retrain = day
```

### Path B: LivePolygonFeed — test injection mode

`raits/live/context_feed.py:724–734`, inside `_iter_test()`. Identical Monday check after each
simulated day. **WIRED.**

### Path C: LivePolygonFeed — actual WebSocket live mode

`raits/live/context_feed.py:1213–1225`, inside `_iter_live()`, at the day-boundary transition
(when the first bar of the next session arrives):

```python
if _cur_day is None or bar_day != _cur_day:
    if _cur_day is not None:
        if (config.hmm_retrain_weekly
                and _cur_day.weekday() == 0
                and (_last_retrain is None
                     or (_cur_day - _last_retrain).days >= 7)
                and _hmm is not None
                and len(_daily_spy_close) >= 35):
            try:
                _hmm.retrain(_daily_spy_close)
            except Exception as e:
                logger.debug("HMM retrain failed: %s", e)
            _last_retrain = _cur_day
```

**Trigger mechanism:** day-boundary detection (when `bar_day != _cur_day`), not a wall-clock
scheduler. Retrain fires on the first incoming WebSocket bar of the day following a Monday.

**Window:** expanding from dataset start (same as backtest). Uses `recent_spy[:today]` in
replay modes; uses `_daily_spy_close` in live mode. NOT rolling 252-day.

**Configuration guard:** `config.hmm_retrain_weekly` (default `True` in `BacktestConfig`).

### Caveat — live mode data dependency

In `_iter_live`, the retrain uses `_daily_spy_close`, which is computed from `self._daily["SPY"]`
— the `daily_data` dict passed at `LivePolygonFeed` construction. If that dict is a static
snapshot loaded at startup and not refreshed with recent close prices, the live retrain silently
operates on a stale window frozen at the last known date. The live WebSocket 5-min bars do NOT
automatically update `_daily_spy_close`. Whoever calls `LivePolygonFeed(daily_data=...)` must
keep `daily_data["SPY"]` current.

### Dead code note

`LiveContextFeed` in `raits/live/runner.py:79–92` raises `NotImplementedError` — it is an
unreleased stub. The real live feed class is `LivePolygonFeed` in `context_feed.py`.

---

## STEP 2 — Futures Annual Re-Freeze: Is It Wired for Live?

**Answer: NOT implemented. Manual/planned only.**

### How labels enter the live path

`global_index/verify_runner_real.py:107`, at script startup — called ONCE, never again:

```python
bench = benchmark_daily(a.regime_csv)
swing_labels = label_regimes(bench, "2018-01-01", 3, REGIME["hmm_fit_end"])
```

`REGIME["hmm_fit_end"]` is `"2024-12-31"` — hardcoded in `futures/basket.py:44`, never
advanced.

`label_regimes()` returns a static `dict[Timestamp, str]`. That dict is bound into the
`real_signal_fn` closure and used for the lifetime of the process.

### FuturesRunner has no HMM knowledge

`global_index/runner.py` — `FuturesRunner.__init__` takes `signal_fn` as a closure. The runner
never calls any HMM function. No `label_regimes`, no `basket_labels`, no `hmm_fit_end`
reference anywhere in the file.

### signal_layer and live_decision have no HMM knowledge

`global_index/signal_layer.py` — `generate_today_signals(*, swing_labels, ...)` receives
labels as a parameter; it does not generate or update them.

`global_index/live_decision.py` — pure position/decision logic. Labels consumed upstream.

### What is absent

No code that:
- Detects a new calendar year has begun
- Advances `hmm_fit_end` to the new year-end
- Calls `label_regimes()` a second time during live operation
- Writes a new `PRODUCTION.pkl` or updated label CSV
- Has a scheduler, cron, file-based trigger, or config flag for annual re-freeze
- Enforces the `<5% label change gate` at runtime

### Note on label coverage beyond 2024-12-31

The expanding-window `predict_current()` inside `label_regimes` can compute labels for dates
after 2024-12-31 (the frozen model can Viterbi decode any future sequence), but the model
parameters are permanently frozen at the 2024-12-31 training boundary. Labels for 2025+ use
2024-trained covariance/transition matrices with no adaptation.

### To advance the re-freeze (manual procedure)

1. Edit `futures/basket.py:REGIME["hmm_fit_end"]` to the new year-end (e.g. `"2025-12-31"`)
2. Update `spy_daily.csv` to include the new year's SPY data
3. Restart the runner so `label_regimes()` re-fits with the new training boundary
4. Apply the `<5% label change gate` check manually before promoting

---

## STEP 3 — Emergency / Event-Driven Retrain

**Answer: Not implemented anywhere. Blueprint-only.**

No code implements:
- VIX spike (>25%) triggered HMM retrain
- SPY daily move (>3%) triggered HMM retrain
- Any event-driven or emergency retrain mechanism in equity or futures live paths

The word "emergency" does not appear in any retrain context across the codebase. The word
"retrain" appears in:
- `raits/hmm/engine.py` — the `HMMEngine.retrain()` method itself
- `raits/hmm/retraining.py` — `simulate_weekly_retrains()` standalone utility (never called
  from live or backtest engine)
- `raits/live/context_feed.py` — the weekly Monday retrain (STEP 1)

### What does exist (not a retrain)

`context_feed.py` and backtest `engine.py` contain a volatility override:

```python
if cur_vol >= 0.50:
    hmm_state = "Crisis"
```

This overrides the HMM's Viterbi output to `"Crisis"` if 5-day realized SPY vol ≥ 50%
annualized. It is a post-hoc label override, not a model retrain. The vol threshold here is 50%
(not the blueprint's VIX >25% or SPY >3% triggers). This override is wired in all live paths.

---

## STEP 4 — Plan vs. Implementation: Net Verdict

### What actually runs if each system goes live today

**Equity:**
- Startup: HMM fitted on `SPY_daily_2007_2024.parquet` from 2007 through `min(SPY in
  market_data) - 1 day`
- Each Monday: `HMMEngine.retrain(all_SPY_daily[:today])` — expanding from 2017-01-03
- Trigger: day-boundary detection on first WebSocket bar of each session (not a scheduler)
- Guard: `config.hmm_retrain_weekly=True` (default, inherited by OOS configs)
- **Risk:** if `daily_data["SPY"]` passed to `LivePolygonFeed` is stale, retrains use stale
  window silently

**Futures:**
- Startup: `label_regimes()` called once with `hmm_fit_end="2024-12-31"` (from `basket.py`)
- Labels stored as a static dict for the entire process lifetime
- If restarted on 2026-01-01, still uses 2024-12-31 fit — no automatic advancement
- Model parameters are frozen; only prediction (Viterbi decoding) can extend beyond 2024-12-31

**Emergency retrain (both systems):** does not run. Blueprint specification only.

### Implementation status by item

| Item | Status | Location |
|---|---|---|
| Equity weekly retrain (live) | **LIVE-WIRED** | `context_feed.py:267–277`, `724–734`, `1213–1225` |
| Equity weekly retrain (backtest) | WIRED | `engine.py:419–429` |
| Futures annual re-freeze (live) | **ABSENT** | Manual edit of `basket.py` required |
| Futures annual re-freeze (backtest) | ABSENT | Not applicable — labels pre-computed |
| Emergency retrain (equity) | **BLUEPRINT-ONLY** | Not in code |
| Emergency retrain (futures) | **BLUEPRINT-ONLY** | Not in code |
| Vol override ≥50% → Crisis (not a retrain) | WIRED | `context_feed.py`, `engine.py` |
| <5% label change gate (live) | **ABSENT** | No runtime check; planned/manual only |

---

## Related Files

- [HMM_FIT_GROUND_TRUTH.md](HMM_FIT_GROUND_TRUTH.md) — equity vs. futures fit schemes
- [HMM_STABILITY_REPORT.md](HMM_STABILITY_REPORT.md) — weekly-expanding vs. annual re-freeze
  label stability analysis
- `raits/live/context_feed.py` — equity live feed (weekly retrain wired here)
- `raits/live/runner.py` — PaperTrader + LiveContextFeed stub
- `global_index/verify_runner_real.py` — futures live runner construction, one-time label fit
- `futures/basket.py` — hardcoded `REGIME["hmm_fit_end"]="2024-12-31"`
