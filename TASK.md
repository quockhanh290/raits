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
- [x] PE_SHORT engine — DONE (swing hold, 37-stock universe, ~11t +$827 → baseline $14,932)
- [x] PE_SHORT expansion — 25 extra stocks fetched (GE, PANW, NOW, PYPL + 21 others)
  - Engine +$945 vs VIX baseline: 18t +$2,630 total (7+6+5 per year)
  - snapshot: results_20260623_070518.pkl
- [x] VIX gates — implemented in engine.py (same-day VIX, yfinance fetch)
  - ORB: block VIX≥25 → +$760 (39t vs 49t baseline)
  - STRESS_ORB: require VIX≥30 → +$426 (76t vs 295t)
  - T-1 bug: STRESS_ORB went -$510 with T-1; fixed to same-day VIX
  - Net engine impact: +$1,015 ($15,669 → $16,684)
  - snapshot: results_20260622_211709.pkl
- [x] New strategy exploration: D/A/B/E/C all DEAD or DEFERRED (see SCRATCHPAD)
- [x] STRESS_ORB_STK — REVERTED (cannot replicate in engine)
  - 5 configs tested: all STK P&L negative (-$208 to -$342)
  - Root cause: engine only fires 47-56/200 sim trades (VIX≥30 gate + MAX_STK_SLOTS + signal filter)
  - System gained +$300-400 from cascade only — not direct STK alpha, unreliable OOS
  - Options tried: daily ATR, intraday ATR, slots=3/5, gap-size ranking — all failed
  - No principled fix found without curve fitting

### Current baseline — LOCKED
- **snapshot: results_20260623_070518.pkl**
- **Total: $17,629** | 2020=+$6,139 | 2021=+$8,017 | 2022=+$3,473
- TREND_FOLLOW: 277t +$9,526 | STRESS_MID: 208t +$1,569 | GAP_FILL: 27t +$81
- FADE: 196t +$717 | GF_SHORT: 25t +$140 | STRESS_ORB: 76t +$933
- ORB: 39t +$2,042 | VWAP_MR: 143t -$11 | PE_SHORT: 18t +$2,630

### Next steps
- [ ] New strategy ideas — need OOS data (2023-2024) or new data sources (options IV, etc.)
- [ ] Day-level bootstrap for STRESS_ORB_STK if OOS data available → proper CI before re-enabling

### Key decisions
- VIX: same-day close (not T-1) because STRESS_ORB VIX spikes are brief (1-3 days)
- PE_SHORT expansion: +$945 despite 2020 regression; 2021+2022 more than compensate
- Cascade effect accepted: STRESS_MID +102 trades (cascade), GAP_FILL +6 bad trades — not worth fixing
- STRESS_ORB_STK reverted: structural issue — engine fires only 23% of sim trades; no non-curve-fitting fix found
- Strategy space exhausted with 2020-2022 data

### Files touched
raits/backtest/engine.py
raits/raits/scripts/window_debug.py
raits/raits/scripts/fetch_vix_daily.py (new)
raits/raits/scripts/cascade_vix_diagnostic.py (new)
raits/raits/scripts/load_all_snapshots.py (new)
