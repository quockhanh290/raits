## Task: Engine Improvement Backlog
Status: IN PROGRESS

### Completed
- [x] Remove ORB_FADE from engine.py → +$330
- [x] RS Momentum — DEFERRED (2021-driven)
- [x] Gap Fill — implemented (21t +$1,163 engine, WR=81%)
- [x] STRESS_MID — verified in engine (106t +$2,035 WR=52%)
- [x] Strategy exploration round — 7+ hypotheses tested, all dead or deferred (see SCRATCHPAD)
- [x] FADE deep dive — LONG FADE flat, SHORT FADE 2021-driven. No clean fix.
- [x] PE_SHORT sim — All reg ≥5% gap-down, 36t +$5,625 WR=72% (62 stocks, 3yr)
- [x] PE_SHORT engine — DONE (swing hold, 37-stock universe, ~11t +$827)
  - Active in ALL regimes; entry 9:30 open; stop=1.5×ATR14; target=2×stop; is_day_trade=False
  - Bug: duplicate _compute_daily_atr — fixed (use existing sig: market_data, ticker, as_of)
  - snapshot: results_20260622_174404.pkl  Total=$15,669 (baseline $14,932, delta +$737)
- [x] PE_SHORT expansion data prep — fetch_new_stocks.py --pe flag added
  - 25 stocks: PFE MRK LLY ABBV JNJ BMY BAC WFC C WMT TGT HD LOW MCD NKE PG KO PEP CAT DE BA GE PYPL PANW NOW
  - Date range: 2019-01-02 → 2022-12-30 (~3 hr download)

### Next steps
- [ ] Run fetch: cd d:\raits\raits && py -3.11 raits\scripts\fetch_new_stocks.py --pe
  After done: py -3.11 raits\scripts\window_debug.py  (no --use-results-cache)
  Expected: ~+$500 PE_SHORT, total PE_SHORT ~$1,300
- [ ] STRESS_ORB_STK re-enable: fix universe isolation FIRST, then add VIX≥30 filter
  Step 1: fetch STK stock bars separately, don't inject into global day_stocks
  Step 2: add VIX≥30 gate (same as STRESS_ORB ETFs — p=0.001)
  Do NOT add VIX filter without Step 1 — collateral damage persists
- [ ] ORB VIX gate: block ORB when VIX≥25 → +$761 (10t -$761 eliminated, 2022 fix)
- [ ] STRESS_ORB VIX gate: require VIX≥30 → +$1,249 net gain (p=0.001)

### VIX analysis (raits/scripts/vix_regime_sim.py — completed)
- STRESS_ORB: VIX≥30 → 80t +$1,249 WR=61% (p=0.001 ✓) vs VIX<30 215t -$742. Gate worth adding.
- ORB: VIX≥25 strongly negative (10t -$761). Block ORB when VIX≥25 → engine +$761. Fixes 2022 crash.
- STRESS_ORB_STK: VIX≥30 likely helps (same structural reason + fixes 2020 recovery SHORT bias)
  but collateral damage from universe expansion must be fixed FIRST (see SCRATCHPAD)
- STRESS_MID: VIX≥25 marginal benefit, low priority
- GAP_FILL/GF_SHORT: bucket N too small (6-9t) — curve fitting risk. No action.
- FADE/VWAP_MR: no VIX relationship. Leave as-is.

### Engine baseline (results_20260622_174404.pkl) — PE_SHORT live, 37-stock universe
- Total: $15,669 | 2020=+$7,513 | 2021=+$6,093 | 2022=+$2,063
- TREND_FOLLOW: 285t +$8,755 | STRESS_MID: 106t +$2,035 | GAP_FILL: 21t +$1,163
- FADE: 193t +$958 | GF_SHORT: 25t +$140 | STRESS_ORB: 295t +$507
- ORB: 49t +$1,282 | VWAP_MR: 144t +$2 | PE_SHORT: ~11t +$827

### Files touched
raits/raits/backtest/engine.py (PE_SHORT: constants, universe, calendar, entry, exits, swing hold, ATR fix)
raits/raits/scripts/window_debug.py (PE_EXPANSION tickers + PE_SHORT display section)
raits/raits/scripts/fetch_new_stocks.py (--pe flag + PE_EXPANSION list)
raits/raits/scripts/post_earnings_drift_sim.py (new)
raits/raits/scripts/post_earnings_short_sim.py (new)
raits/raits/scripts/post_earnings_expansion_sim.py (new)
