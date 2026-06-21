## Task: Strategy Discovery & Optimization
Status: IN PROGRESS

### Completed
- [x] Remove ORB_FADE from engine.py → +$330
- [x] RS Momentum — 10 rounds tested, DEFERRED
- [x] Gap Fill — implemented (23t, +$2,838 sim, Normal regime)
- [x] GAP_FILL continuous fire (10:30→11:30) — sim +$3,357, engine -$905 (TF position compression), REVERTED
- [x] GF_SHORT window extension — p=0.771, WR=37%, REJECTED
- [x] Calm midday (4 approaches: VWAP_MR, ORB retest high/low-beta, VWAP_MR low-beta) — ALL FAIL, WR~37% across all approaches, accept no edge
- [x] ORB 2022 bear filter: extend SMA50/SMA200 to also block SHORT → +$229 ORB, +$729 system
- [x] New baseline: $14,932 (snapshot results_20260620_163631.pkl)

### In progress
- [ ] Discover next strategy opportunity

### Next steps (candidates, pick one)
1. STRESS_ORB filter — 295t only +$507, avg +$1.7/trade. Too many trades, almost no edge.
2. Normal 13:30–14:00 gap — no strategy running in this 30-min window
3. FADE consistency — 2020: -$334, 2021: +$1,591, 2022: -$208 (needs investigation)

### Key decisions
- Calm midday: permanently no edge with OHLCV 5-min data. Don't revisit.
- ORB bear filter: SMA50/SMA200 (existing variable), consistent with codebase. Lags close/200MA.
- TF equity amplification: removing losing trades → equity higher at 14:00 → TF gains. Works both ways.
- Sim vs engine gap: always debug cross-strategy blocking + position sizing before reverting.

### Discovery map
| Time | Calm | Normal | Stress |
|------|------|--------|--------|
| 9:35–10:15 | FADE ✓ | ORB ✓ FADE | STRESS_ORB flat |
| 10:15–13:30 | VWAP_MR dead | GAP_FILL ✓ GF_SHORT | STRESS_MID ✓ |
| 13:30–14:00 | dead | **empty** | — |
| 14:00–15:55 | TF ✓ | TF ✓ | TF ✓ |

### Files touched
raits/backtest/engine.py
raits/raits/scripts/orb_bear_filter_sim.py
raits/raits/scripts/vwap_mr_lowbeta_sim.py
raits/raits/scripts/orb_retest_sim.py
raits/raits/scripts/fetch_lowbeta_5min.py
raits/raits/scripts/compare_snapshots.py
raits/raits/scripts/check_stress_mid.py
