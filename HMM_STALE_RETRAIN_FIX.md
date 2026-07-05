# HMM Stale Retrain Fix — Fail-Loud on Stale daily_data["SPY"]

> Code changed. Generated 2026-07-04.
> Branch: future/incorporation
> Files touched: `raits/live/context_feed.py`, `raits/tests/live/test_context_builders.py`

---

## The Bug

The equity weekly HMM retrain in `_iter_live` is wired for live (confirmed in the live
retrain audit), but it silently retrains on whatever `daily_data["SPY"]` was passed at
`LivePolygonFeed` construction — even if that snapshot is weeks or months old.

### Root cause chain

1. `LivePolygonFeed.__init__` stores `self._daily = daily_data` (construction-time snapshot)
2. `_setup_day()` runs at every day boundary, computing `_daily_spy_close` from
   `self._daily["SPY"]` (`context_feed.py:_setup_day`, daily SPY close block)
3. The 5-min WebSocket bars accumulate in `_spy_bars_today` / `_acc` — **nothing feeds back
   into `self._daily["SPY"]`**
4. The Monday retrain uses `_daily_spy_close` which is always sliced from the same frozen dict

**Result:** if `daily_data["SPY"]` is a static snapshot loaded at startup and never refreshed,
the weekly retrain fires every Monday but always trains on the same stale data window.
The HMM model never actually adapts. No warning, no error — silent wrong-input behaviour.

### Analogy

This is the same class of bug as the DST fallback issue: a silent-wrong-input condition
that passes quietly while making the system appear to work correctly.

---

## The Fix

### New constant + helper function

Added to `context_feed.py` (module level, after `_compute_fade_atr_top2`):

```python
_STALE_SPY_BDAYS = 5

def _check_stale_and_warn(
    daily_spy_close: pd.Series,
    cur_day: pd.Timestamp,
    threshold_bdays: int = _STALE_SPY_BDAYS,
) -> bool:
    """
    Return True and emit a WARNING if daily_spy_close is stale relative to cur_day
    (more than threshold_bdays business days behind).

    Called before every weekly HMM retrain in _iter_live. A stale series means the
    weekly retrain would silently operate on the startup snapshot instead of recent
    market data — defeating the purpose of weekly adaptation.

    Returns False (and emits nothing) when the series is fresh or empty.
    """
    if daily_spy_close.empty:
        return False
    last = daily_spy_close.index[-1]
    gap = max(0, len(pd.bdate_range(last, cur_day)) - 1)
    if gap > threshold_bdays:
        logger.warning(
            "HMM weekly retrain SKIPPED — daily_data['SPY'] is STALE "
            "(last close %s, current day %s, %d business days behind). "
            "Retrain would NOT adapt to recent market conditions. "
            "Refresh daily_data['SPY'] with recent SPY closes before "
            "starting live trading.",
            last.date(), cur_day.date(), gap,
        )
        return True
    return False
```

**Threshold rationale:**
- Normal Friday→Monday gap = 1 business day
- After a long weekend (e.g. MLK Day): gap = 2
- After a 3-day holiday week: gap ≤ 4
- Threshold of 5 gives one full week of buffer before flagging as stale

### Retrain block in `_iter_live` (gated)

Before (silently retrains on any data):
```python
if (config.hmm_retrain_weekly and _cur_day.weekday() == 0 ...):
    try:
        _hmm.retrain(_daily_spy_close)
    except Exception as e:
        logger.debug("HMM retrain failed: %s", e)
    _last_retrain = _cur_day
```

After (skips + warns on stale, retrains only when fresh):
```python
if (config.hmm_retrain_weekly and _cur_day.weekday() == 0 ...):
    # _daily_spy_close is from self._daily["SPY"] (static snapshot, not live bars).
    # _check_stale_and_warn detects stale input and skips retrain rather than
    # silently adapting to a frozen data window.
    if not _check_stale_and_warn(_daily_spy_close, _cur_day):
        try:
            _hmm.retrain(_daily_spy_close)
        except Exception as e:
            logger.debug("HMM retrain failed: %s", e)
    _last_retrain = _cur_day
```

`_last_retrain` is always advanced (stale or not) to avoid a warning loop on every
subsequent Monday until the data is fixed.

### Comment in `_setup_day`

Added inline comment at the daily SPY close block:
```
# Daily SPY close — sourced from self._daily (static snapshot passed at
# construction).  WebSocket 5-min bars are NOT aggregated back here.
# Caller must keep daily_data["SPY"] current; see _check_stale_and_warn.
```

---

## Caller Requirement Documented

`LivePolygonFeed.__init__` docstring updated with an explicit **Live-deployment requirement**
block under the `daily_data` parameter:

> **`daily_data["SPY"]` must be refreshed with recent SPY daily closes before every live
> session (and ideally before each weekly HMM retrain).** The weekly retrain reads this
> series to adapt the HMM to recent market conditions; if the series is frozen at the
> startup snapshot, the retrain silently operates on stale data and the regime model
> never adapts. The feed detects staleness (> 5 business days behind) and emits a loud
> WARNING rather than retraining on stale input.

---

## Auto-Refresh Deferred (TODO)

Auto-refresh of `daily_data["SPY"]` is NOT implemented in this step. This is a larger
architecture decision: where does the daily SPY come from in live mode?

- Polygon REST API (fetch last N business days of daily closes on startup / before retrain)?
- IBKR historical data API?
- Aggregate the 5-min WebSocket bars into daily closes as they arrive?

**TODO (live-prep):** resolve the data source question and implement automatic refresh
of `daily_data["SPY"]` before the Monday weekly retrain fires. Until then, the operator
must pass a fresh `daily_data` at `LivePolygonFeed` construction.

---

## Tests

5 new tests in `raits/tests/live/test_context_builders.py`, all passing (171/171 full
live suite green):

| Test | What it verifies |
|---|---|
| `test_stale_spy_retrain_warns_and_skips` | 30-day-stale series → `is_stale=True`, "STALE" in warning message |
| `test_fresh_spy_retrain_no_warning` | 1 business day gap → `is_stale=False`, no warning emitted |
| `test_staleness_exactly_at_threshold_is_not_stale` | `gap == 5` → not stale (threshold is strict `>`, not `>=`) |
| `test_staleness_one_over_threshold_is_stale` | `gap == 6` → stale, warning fires |
| `test_empty_spy_series_is_not_stale` | empty series → `False`, no crash |

---

## What Is NOT Changed

- `engine.py` — untouched
- `decision_unit.py` — untouched
- `configs/final_params.yaml` — untouched
- Retrain logic / fit scheme — unchanged; only the staleness gate was added
- `_iter_test` path — no change; test mode retrains from `mkt["SPY"]` sliced to `<= day`,
  which is always current relative to the test day (staleness concern does not apply)
- `ReplayContextFeed` — no change; replay mode slices from `spy_data[:day]` inline,
  always current

---

## Related Files

- [HMM_LIVE_RETRAIN_AUDIT.md](HMM_LIVE_RETRAIN_AUDIT.md) — original live retrain cadence
  audit that identified this risk
- [HMM_FIT_GROUND_TRUTH.md](HMM_FIT_GROUND_TRUTH.md) — equity vs. futures HMM fit schemes
- `raits/live/context_feed.py` — fix location
- `raits/tests/live/test_context_builders.py` — new staleness tests
