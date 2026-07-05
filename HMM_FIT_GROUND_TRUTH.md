# HMM Fit Ground Truth Report — RAITS Equity vs. Futures

> Investigation only — no code changed. Generated 2026-07-04.

---

## STEP 1 — How the equity backtest fits the HMM

**Engines involved:** `raits/backtest/engine.py` (used by WFO OOS) and `engine_refactored.py`
(identical HMM logic). WFO OOS calls `BacktestEngine(oos_cfg).run(oos_data)` — engine.py.

### Initial fit at `run()` startup

`engine.py:217–264` (identical in `engine_refactored.py:225–264`):

```python
hmm = HMMEngine()
_hist_path = ".../data/cache/daily/SPY_daily_2007_2024.parquet"
if os.path.exists(_hist_path):
    _spy_hist_close = spy_hist["close"].sort_index()
    _bt_start = pd.Timestamp(min(market_data["SPY"].index.normalize()))
    _spy_hist_close = _spy_hist_close[_spy_hist_close.index < _bt_start]   # ← slice
    if len(_spy_hist_close) >= 50:
        hmm.fit(_spy_hist_close)    # ANCHORED: 2007 → day before WFO data start
```

- **Training start:** Beginning of the parquet file (~2007-01-xx)
- **Training end:** `_bt_start - 1 day` = last day before `min(market_data["SPY"].index)`.
  For a WFO run with `DATASET_START="2017-01-03"`, `_slice_oos` gives SPY starting from
  2017-01-03, so `_bt_start = 2017-01-03` → initial fit uses **2007 through 2016-12-30**.
- **Scheme:** ANCHORED. Single `hmm.fit()` call. Not rolling. Not per-WFO-window.

### Weekly retrain during the run

`engine.py:419–429` (identical in `engine_refactored.py:426–436`):

```python
if self.config.hmm_retrain_weekly and day.weekday() == 0:   # Monday
    if (self._last_retrain_date is None
            or (day - self._last_retrain_date).days >= 7):
        recent_spy  = spy_data[spy_data.index.normalize() <= day]  # ALL SPY so far
        daily_close = to_daily_close(recent_spy)
        if hmm is not None and len(daily_close) >= 35:
            hmm.retrain(daily_close)
```

- `spy_data` for OOS runs is the **full Polygon dataset from 2017-01-03 → OOS end**
  (`_slice_oos` passes "Full history" SPY)
- Every Monday retrain uses **2017-01-03 → that Monday** (EXPANDING, NOT rolling 252-day)
- `HMMEngine.retrain()` **completely replaces** the model — after the first Monday retrain,
  the 2007-2016 parquet initial fit is discarded
- `hmm_retrain_weekly=True` is the `BacktestConfig` default (`data_types.py:85`).
  `_make_config()` does **NOT** pass this field → OOS configs inherit the `True` default.
- **Grid-search combos** (`wfo.py:118`): `"hmm_retrain_weekly": False` — HMM frozen
  for the 48-combo grid search for speed. Retrains only in OOS runs.

### Schematic for the verified equity IS/OOS run

```
startup:    hmm.fit(SPY 2007–2016)          ← one-time anchored init from parquet
Monday 1:  hmm.retrain(SPY 2017–M1)         ← replaces init; EXPANDING from 2017
Monday 2:  hmm.retrain(SPY 2017–M2)         ← still expanding from 2017
...
Monday N:  hmm.retrain(SPY 2017–MN)         ← expanding from 2017
```

**This is NOT rolling 252-day.** The implementation uses expanding-window anchored at
2017-01-03. The blueprint calls for rolling 252-day but the actual code diverges.

---

## STEP 2 — WFO vs. live: are they the same?

### Backtest (engine.py / WFO OOS) HMM scheme
- Initial: anchored 2007→2016 (parquet)
- Weekly: expanding from 2017 (Polygon 5-min resampled to daily)

### Live path (`ReplayContextFeed` / `LivePolygonFeed`)

`context_feed.py:192–276`:

```python
# _init_hmm — mirrors engine exactly:
def _init_hmm(self, spy_data, bt_start):
    hmm = HMMEngine()
    if os.path.exists(self._HMM_HIST_PATH):     # same SPY_daily_2007_2024.parquet
        spy_hist_close = spy_hist_close[spy_hist_close.index < bt_start]  # same slice
        if len(spy_hist_close) >= 50:
            hmm.fit(spy_hist_close)              # same initial fit
            return hmm
    hmm.fit(_to_daily_close(spy_data))          # same fallback
    return hmm

# Weekly retrain — same expanding logic:
if config.hmm_retrain_weekly and day.weekday() == 0:
    recent_spy  = spy_data[spy_data.index.normalize() <= day]
    daily_close = _to_daily_close(recent_spy)
    if hmm is not None and len(daily_close) >= 35:
        hmm.retrain(daily_close)
```

**The live path and backtest are structurally identical.** Same parquet → same initial fit,
same expanding-from-2017 weekly retrains, same `predict_current(spy_daily)` per bar.
The `context_feed.py` docstring confirms: "Architecture mirrors engine_refactored._run_day exactly."

**Caveat:** In live deployment, `spy_data` passed to the feed must start from 2017-01-03
(same as the backtest) for retrain windows to match. If `spy_data` starts from a different
date, regime labels will diverge from the validated backtest.

**The 604-trade verified run did not use `label_regimes`** — that function is futures-only.
The equity engine always runs HMM inline.

---

## STEP 3 — Shared HMMEngine: equity vs. futures fit schemes

### Equity (`engine.py`)
- Uses `HMMEngine` directly
- Fit scheme: anchored 2007→2016 init + EXPANDING-from-2017 weekly retrains
- Model is a live instance, refitted repeatedly during the run

### Futures (`futures/_validated_core.py` → `label_regimes`)

`_validated_core.py:79–119`:

```python
def label_regimes(daily, train_end, n_components, hmm_fit_end=None):
    fit_end_ts = pd.Timestamp(hmm_fit_end) if hmm_fit_end else train_end_ts

    train = daily[daily.index <= fit_end_ts]    # ALL data from start → hmm_fit_end
    eng = HMMEngine(n_components=n_components)
    eng.fit(train, version_tag="gate2_spike", save=False)  # FIT ONCE, NEVER RETRAINED

    test_days = daily[daily.index > train_end_ts].index
    for d in test_days:
        window = daily[daily.index <= d]        # expanding-window prediction
        state = eng.predict_current(window)
        labels[...] = eng.state_name(state)
    return labels
```

Called from `global_index/regime.py`:

```python
reg = label_regimes(daily,
                    train_end="2018-01-01",      # when labeling STARTS (not fit end)
                    n_components=3,
                    hmm_fit_end="2024-12-31")    # when HMM fit ends
```

**Futures HMM fit scheme:**
- Fit **ONCE** on all daily SPY close data from start of CSV up to **2024-12-31**
- **Never retrained** — completely frozen
- Labels day D via `predict_current(all_data[...≤D])` — expanding prediction, frozen model
- `train_end="2018-01-01"` controls when labeling **starts**, not the fit boundary

### Does HMMEngine support both schemes?

Yes — one class, no scheme flag. The scheme is determined by what data the caller passes:

| Caller | Call pattern | Scheme |
|---|---|---|
| Equity backtest startup | `fit(2007–2016)` once | Anchored init from parquet |
| Equity backtest Mondays | `retrain(2017→Monday)` weekly | Expanding from 2017 |
| Futures `label_regimes` | `fit(start→2024-12-31)` once, no retrain | Fully frozen anchored |
| Blueprint spec (not implemented) | `retrain(last_252_days)` weekly | Rolling 252-day |

`retraining.py:simulate_weekly_retrains()` **does** implement true rolling 252-day:
```python
window_start = max(0, window_end - TRAINING_LOOKBACK_DAYS)  # ← rolling 252-day
window = spy_daily_close.iloc[window_start:window_end]
```
But this function is **never called** from either engine — it is a standalone utility.

**Risk: changing HMMEngine affects both systems.** `HMMEngine.fit()`, `retrain()`,
`predict_current()`, or `build_feature_matrix()` changes propagate to equity and futures.

---

## STEP 4 — Summary table

| Question | Answer |
|---|---|
| **Equity backtest fit scheme** | NOT rolling 252-day. Initial fit: anchored 2007→2016 (parquet). Weekly retrain: EXPANDING from 2017-01-03 → current Monday (Polygon data). Two-phase scheme is an implicit design consequence, not an explicit flag. |
| **Equity HMM training start date** | Initial fit: ~2007 (parquet file start). After first Monday retrain: 2017-01-03 (Polygon WFO dataset start). |
| **Equity HMM training end date** | Initial fit: day before `min(SPY in wfo_data)` ≈ 2016-12-30. Retrains: grows to each Monday's date throughout the run. |
| **Refit cadence (equity backtest)** | WEEKLY (every Monday); `hmm_retrain_weekly=True` by default; grid-search combos use `False` for speed. |
| **Controlling files/config** | `engine.py:217–264` (initial fit), `engine.py:419–429` (weekly retrain). Config: `BacktestConfig.hmm_retrain_weekly` (default `True`, not passed by `_make_config` → stays `True` for OOS). |
| **Equity live HMM** | **Identical scheme** to backtest. `context_feed.py:192–276`. Same parquet init, same expanding weekly retrains. Matches IF `spy_data` starts from the same date as the backtest. |
| **Futures HMM fit scheme** | ANCHORED, SINGLE FIT on SPY daily from start → 2024-12-31. Never retrained. Completely frozen. `_validated_core.py:label_regimes()`. |
| **HMMEngine: both schemes? How selected?** | Yes, one class, no flag. Scheme determined by caller's use of `fit()`/`retrain()`. Equity calls `retrain(expanding)` weekly; futures calls `fit(full)` once and never retrains. |
| **Key deployment question** | The verified 604-trade equity run used EXPANDING-from-2017 (not rolling 252-day, not anchored-2018 frozen). Switching to either rolling or anchored-frozen changes IS regime labels → full re-validation required. |

### Blueprint delta

The blueprint specifies "rolling 252-day weekly retrain" for live HMM. The actual code uses
**expanding-from-dataset-start**. After 5+ years of operation the expanding window contains
5× more data than a 252-day rolling window — regime state boundaries will drift apart.

To match the blueprint exactly, the weekly retrain call in `engine.py:422-423` would need to
change from:
```python
recent_spy = spy_data[spy_data.index.normalize() <= day]    # expanding (current)
```
to:
```python
recent_spy = spy_data[spy_data.index.normalize() <= day].iloc[-252:]  # rolling 252-day
```
**Do not make this change without rerunning IS** — it changes regime labels throughout the
validated period and invalidates the vault test baseline.
