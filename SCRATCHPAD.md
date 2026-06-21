## Gotchas

- **Gap Fill "direct" trades = look-ahead bug**: Original RS sim showed +$10,465 because "direct" trades retroactively selected stocks that NEVER touched VWAP — not identifiable in real-time. Gap Fill doesn't have this issue (all filters checkable at 10:30).

- **Calm regime gap fill = negative**: Tested explicitly — 5t, -$193, WR=40% in Calm. Gap Fill edge is Normal-regime specific. Do NOT add Calm regime even if user asks "can we get more signals."

- **PositionSizer vs sim $500/trade**: Sim used fixed $500 risk. Engine uses max_risk_pct of account equity. Backtest shares/P&L will differ from sim numbers. Don't interpret this as a bug.

- **VWAP_MR TIME_STOP**: was 45 min, extended to 90 min (already in engine before this session).

- **TF equity amplification**: Removing losing trades → account equity higher at 14:00 → TF position sizer gives more shares → TF P&L increases. Works in reverse too. Always run full system backtest after any strategy change, not just check the target strategy.

- **Sim vs engine gap — always check 3 things before reverting:**
  1. Universe mismatch (sim fixed ~37 tickers vs engine dynamic scanner)
  2. Cross-strategy blocking (sim doesn't check MAX_TOTAL=8 or other strategies' open positions)
  3. Trailing stop / exit logic differences

- **--use-results-cache invalid after engine.py changes**: Must drop flag whenever backtest logic modified. Data PKL (5min) is separate from results PKL.

- **Low-beta 5min data fetched**: PG, KO, PEP, WMT, MO, CL, KMB, GIS, MDLZ, NEE, DUK, SO, D, AEP, JNJ, ABT, MRK, PFE, BMY, WFC, USB — saved to `data/cache/data/{ticker}_5min_{year}.parquet`. Used for Calm midday sims only, NOT in engine universe.

- **SMA50/SMA200 vs close/200MA lag**: Engine uses SMA50>SMA200 (death cross, ~6 weeks lag). Close vs 200MA is faster (catches Jan 2022 drop, SMA50/SMA200 doesn't until March 2022). Current engine has SMA50/SMA200 — consistent but misses early bear moves.

---

## Strategy Discovery Map — COMPLETED INVESTIGATIONS

### BASELINE HISTORY
| Date | Baseline | Change |
|------|----------|--------|
| Session start | $14,203 | — |
| ORB bear filter (SHORT added) | **$14,932** | +$729 |

---

### Calm midday (10:15–14:00) — PERMANENTLY CLOSED

**Tested 4 approaches, all fail with WR~37%:**

| Approach | Trades | P&L | WR | Stop rate |
|----------|--------|-----|----|-----------|
| VWAP_MR moving target, high-beta | ~144t | ~$0 | 47% | — |
| ORB boundary retest, high-beta | 294t | -$6,715 | 41% | 55% |
| ORB boundary retest, low-beta (PG/KO/NEE/JNJ) | 294t | -$25,146 | 37% | 59% |
| VWAP_MR snapshot VWAP target, low-beta | 294t | -$31,402 | 37% | 48% |

**Root cause**: OR boundaries are NOT reliable support/resistance in midday for ANY universe (high-beta OR low-beta). Individual stocks trend intraday regardless of SPY regime.

**Conclusion**: Do NOT revisit Calm midday mean-reversion without fundamentally different signal (non-OHLCV, or order flow data).

---

### GAP_FILL continuous fire (10:30→11:30) — REVERTED

- Sim: +$3,357, WR=59%, p=0.053 (NOT significant)
- Engine: -$905 net (TF position compression: more intraday churn → lower equity at 14:00 → smaller TF positions → TF -$880)
- Root cause was NOT slot competition (TF had same 284 trades). Was equity compression.
- Scripts: `gap_fill_window_sim.py`

---

### GF_SHORT window extension (10:30→11:30) — REJECTED

- Sim: 46t, -$981, WR=37%, p=0.771
- Script: `gf_short_window_sim.py`

---

### ORB 2022 bear filter — IMPLEMENTED ✓

- **Change**: Extended SMA50/SMA200 filter from "block LONG only" → "block ALL directions" in bear trend
- **Engine lines**: ~736 (confirm section), ~810 (signal section)
- **Result**: +$729 system (+$229 ORB direct, +$652 TF equity amplification, -$213 FADE/STRESS_MID ripple)
- **Caveat**: SMA50/SMA200 lags, misses Jan 2022 TSLA/GS losses (-$779) that close/200MA would catch
- Script: `orb_bear_filter_sim.py`

---

### STRESS_ORB QQQ-only filter — REJECTED (curve fitting)

- QQQ: 100t +$1,180 consistent all 3 years | SPY: 131t -$269 | IWM: 64t -$404
- Rejected: post-hoc selection. We saw QQQ win → wanted to keep. That's data snooping.
- If testing again: need out-of-sample data (2023+) or a priori hypothesis before seeing data.

---

### STRESS_ORB individual stocks — IN PROGRESS

- Hypothesis: high-beta stocks gap down harder than ETFs in Stress → better SHORT ORB follow-through
- Script: `stress_orb_stocks_sim.py`
- Setup: Stress days, gap↓≥1.5%, OR=9:30-9:35, SHORT breakout 9:35-10:15, stop=OR_high+0.5×ATR, target=2R

---

## Rejected approaches

- **RS LONG**: ALL configs negative.
- **RS SHORT**: tested 10 rounds, best=26t +$2,932 (Round 8). DEFERRED: 2021-driven (130% P&L), 2020=-$1,002, universe too small. Do NOT implement until re-evaluated with broader universe.
- **Gap Fill SHORT**: WR=40%, 2022 always negative.
- **Calm afternoon strategy**: No edge. 52 days.
- **VWAP_MR universe removal (IWM, QQQ, XLV, XLP)**: Curve fitting.
- **VWAP_MR signal filters (wick/rejection/volume)**: All worse in combined tests.
- **VWAP_MR F2+F3 filters**: +$182 system improvement — too small, 2020 unresolved.
- **ORB boundary retest (Calm midday)**: Concept wrong. Tested high-beta AND low-beta. Both fail.
- **VWAP_MR fixed target, low-beta**: -$31,402, WR=37%. Worse than everything. Universe not the issue.

---

## Open questions / Future work

- **Calm midday**: Accept no edge. Move on.
- **Normal 13:30–14:00 gap**: 30-min window with no strategy. Untested.
- **FADE consistency**: 2020: -$334, 2021: +$1,591, 2022: -$208. High variance, unclear root cause.
- **STRESS_ORB individual stocks**: sim in progress.
- **STRESS_ORB**: accept +$507 flat if individual stocks sim also fails.
