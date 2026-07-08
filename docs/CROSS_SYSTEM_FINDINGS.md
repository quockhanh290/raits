# Cross-System Findings
_Futures session audit → classify → verify on stocks code_  
_Created: 2026-07-07_

---

## Summary of Futures Findings (this session)

Four issues surfaced while reviewing `docs/futures/SYSTEM_MODEL.md` against actual code.

| ID | Finding | Type | Disposition |
|----|---------|------|-------------|
| F1 | C2 (stale_guard fail) missing from CHIỀU 3 intervention order diagram | Documentation bug | Fixed: C2 added to SYSTEM_MODEL + VISUALIZE |
| F2 | equity restart: state.equity vs broker.get_equity() — two sources? | Potential behavior bug | Verified CORRECT: both receive same delta; broker is source-of-truth on restart; peak_equity persists separately via B1 |
| F3 | same-day entry+exit order: 3-phase question | Clarification | Verified: Phase 2+3 are nested per-entry (not all-OPEN then all-CLOSE) |
| F4 | WARN dead field in circuit_breaker.py | Unknown intent | Verified INTENTIONAL: `circuit_breaker.py:19` says so; system is binary (full-size or HALT), WARN was removed by design |

---

## Classification: Common vs Futures-Specific

| Finding | Class | Reason |
|---------|-------|--------|
| F1 – C2 diagram gap | Documentation | Code was correct; doc missed one row |
| F2 – equity restart | Common pattern | Any live system that restarts needs an equity source-of-truth |
| F3 – same-day order phases | Futures-specific | Stocks BacktestEngine closes positions at EOD, no same-day entry+exit mechanics |
| F4 – WARN dead field | Futures-specific | Stocks circuit breaker has no WARN state; only HALT_DAY and SHUTDOWN |

---

## Stocks Code Verification

For each "Common" finding, the stocks code path was read and verified.

### a. ADJUSTMENT INCONSISTENCY

**Futures finding:** SPY CSV for HMM training (`benchmark_daily()`) may differ in adjustment type from intraday signal bars.

**Stocks code checked:** `raits/raits/data/raits_polygon_fetcher.py`, `raits/raits/backtest/engine.py`, `raits/raits/backtest/wfo.py`

- `fetch_daily_bars(adjusted=True)` → Polygon param `adjusted=true` (split+dividend)
- `fetch_intraday_bars()` → Polygon param `adjusted=true` (split+dividend) — confirmed at `_fetch_from_polygon_intraday` line 369
- HMM initial fit: reads `SPY_daily_2007_2024.parquet` (adjustment type depends on how originally fetched)

**Finding already documented in `docs/stocks/OPEN_QUESTIONS.md`:**  
The intraday 5-min SPY bars used for weekly HMM retraining are split-only (how Polygon returns intraday bars without explicit adjustment), while daily data uses dividend-adjusted. This is a known open question with ~24 ex-div days/year at risk of misclassification.

**Status:** Already tracked. Stocks path is INDEPENDENT of the futures CSV fix.

---

### b. HMM CONTAMINATION

**Futures finding:** `label_regimes()` is anchored to `hmm_fit_end=2024-12-31`; no WFO OOS boundary contamination found.

**Stocks code checked:** `raits/raits/backtest/engine.py:219-256`, `raits/raits/backtest/wfo.py:720-767`

Key observations:

1. **Initial HMM fit (engine.py:234-235):**
   ```python
   _spy_hist_close = _spy_hist_close[_spy_hist_close.index < _bt_start]
   ```
   `_bt_start = min(market_data["SPY"].index)`. HMM trained strictly BEFORE the backtest/OOS window starts.

2. **Vault protection (wfo.py:374-375):**
   ```python
   wfo_data = self._slice_before(market_data, vault_boundary)
   ```
   WFO never touches vault-period data.

3. **Weekly retrains during OOS (engine.py:422-423):**
   ```python
   recent_spy = spy_data[spy_data.index.normalize() <= day]
   ```
   Causal — only past data.

4. **_slice_oos SPY handling (wfo.py:756-758):**
   ```python
   # Full history — HMM needs to see all regimes to calibrate
   sliced = df[df.index <= test_end + pd.Timedelta("1D")]
   ```
   OOS run receives FULL SPY history from wfo_data start to test_end. This pushes `_bt_start` back to 2018, so the parquet-based initial fit only covers 2007-2017. After the first Monday retrain, the HMM covers 2018-to-current. No lookahead; just a regime-coverage note (2008 GFC seen only at init, dropped after first retrain).

**Status: CLEAN.** No OOS contamination. Vault is untouched during WFO. Weekly retrains are causal.

**Note:** Grid-search subprocesses disable `hmm_retrain_weekly=False` (wfo.py:118). Only OOS test uses live retrains. This means grid search compares params under a frozen (pre-backtest-start) HMM, while OOS test uses the evolving HMM. The two are not directly comparable, but this is standard WFO practice and documented in the code comment.

---

### c. ANCHOR/REFREEZE

**Futures finding:** `futures/refreeze.py` implements a 5-step annual refreeze with a formal gate (AUTO_APPROVE <5% label change, VERIFY 5-15%, HOLD >15%), 3-record rollback registry, and Calmar floor 2.38.

**Stocks code checked:** `raits/raits/hmm/engine.py:164-214`, `raits/raits/hmm/retraining.py`

- `HMMEngine.retrain()`: validates new model before promoting; falls back to `_last_good_model` on failure. No gate thresholds, no rollback registry.
- `RetrainingScheduler`: schedules weekly retrains; no annual review cadence, no label-drift check.
- No equivalent of `CALMAR_FLOOR`, `AUTO_APPROVE`, `VERIFY`, or `HOLD` gates in stocks.

**Status: GAP.** Stocks HMM lacks annual refreeze gate. The model can drift without structured review. This is not a current blocker (stocks is not yet live) but becomes load-bearing before live deployment.

→ Tracked in `docs/stocks/OPEN_QUESTIONS.md` (new entry added).

---

### d. STATE PERSISTENCE

**Futures finding:** B1 atomic persist — `live_positions.json` stores `open_positions + breaker.peak_equity + _day_start_equity + cur_day`; written atomically via `.tmp → os.replace`. On restart: equity re-anchored from broker.

**Stocks code checked:** `raits/raits/live/runner.py`

- `PaperTrader` maintains `_running_equity` and `_session_start_equity` in memory only.
- `peak_equity` is not tracked at all (no Calmar-based circuit breaker requiring it).
- No `live_positions.json` equivalent; no atomic persist.
- `LiveContextFeed` raises `NotImplementedError` — stocks live path is not yet production-ready.

**Status: NOT APPLICABLE (yet).** Stocks is paper-trading mode only. State persistence is futures-specific for now. Becomes load-bearing when stocks goes live.

---

## Summary Table

| Dimension | Futures | Stocks | Gap? |
|-----------|---------|--------|------|
| Adjustment consistency | CSV vs Polygon intraday (open Q) | Intraday split-only vs daily dividend-adjusted (known, tracked) | Stocks gap already tracked |
| HMM contamination | Clean (anchored to fit_end) | Clean (strict < _bt_start; vault sliced out) | None |
| Annual refreeze gate | Full gate pipeline in refreeze.py | Per-retrain validation only; no annual gate | **YES — pre-live blocker** |
| State persistence | B1 atomic JSON persist, peak_equity, broker restart | In-memory only; paper-only | Not applicable until stocks goes live |

---

## Files Read for This Analysis

```
futures:  global_index/runner.py, signal_layer.py, live_decision.py,
          net_exposure_multi.py, circuit_breaker.py (futures/),
          hmm_stale_guard.py, _validated_core.py, broker.py, regime.py
          futures/refreeze.py, futures/basket.py, global_index/specs.py

stocks:   raits/raits/hmm/engine.py, raits/raits/hmm/retraining.py,
          raits/raits/hmm/features.py,
          raits/raits/data/raits_polygon_fetcher.py,
          raits/raits/backtest/engine.py, raits/raits/backtest/wfo.py,
          raits/raits/live/runner.py
```
