## Task: RAITS — Phase Transition to WFO + OOS
Status: IN PROGRESS

### Completed
- [x] Remove ORB_FADE from engine.py → +$330
- [x] RS Momentum — DEFERRED (2021-driven, universe too small)
- [x] Gap Fill — implemented (27t +$81 engine, WR=63%)
- [x] GF_SHORT — implemented (25t +$140 engine, WR=60%)
- [x] STRESS_MID — verified in engine (208t +$1,569 WR=52%)
- [x] PE_SHORT — implemented + expanded (18t +$2,630, 37+25 stock universe)
- [x] VIX gates — ORB (VIX<25) + STRESS_ORB (VIX≥30), same-day close
- [x] STRESS_ORB_STK — REVERTED (engine fires only 23% sim trades, all configs negative)
- [x] Strategy exploration Round 1 — 7+ hypotheses, all dead or deferred
- [x] Strategy exploration Round 2 (structural gaps) — all dead after engine filters:
  - Midday Continuation LONG: v1 +$4,747 → v2 -$1,133 after scanner filter (edge was in low-quality stocks)
  - Late-Day Breakout: 56t +$1,268 p=0.067 — borderline, 2021=-$217 (fails in target env)
  - Calm Swing LONG: 74t +$1,462 p=0.238 — not significant, 2021=-$173
  - Normal SHORT Breakdown: 132t +$1,006 p=0.429 — not significant, 2021=-$2,302
  - VWAP Reclaim LONG: -$109,143 p=1.0 — dead
  - PE_LONG (gap-up): -$2,314 WR=39% — dead (from prior session)
- [x] System deep analysis — Sharpe=2.49, Sortino=3.67, Calmar=3.42, CAGR=11.75%/yr
  - TREND_FOLLOW = 54% of P&L (concentration risk)
  - TSLA = 17.3% of P&L, top 5 tickers = 64%
  - TF declining: 2020 avg $49 → 2021 $34 → 2022 $21.7/trade
  - Max DD = -3.4% (well within -4% circuit breaker)
  - Swing > intraday: $12,437 / 292t vs $5,192 / 717t
  - Dead zone 11:00-14:00: structural (all strategies fail there)

### Current baseline — LOCKED
- **snapshot: results_20260623_070518.pkl**
- **Total: $17,629** | 2020=+$6,139 | 2021=+$8,017 | 2022=+$3,473
- **CAGR: 11.75%/yr | Max DD: -3.4% | Sharpe: 2.49 | Sortino: 3.67**
- TREND_FOLLOW: 277t +$9,526 | PE_SHORT: 18t +$2,630 | ORB: 39t +$2,042
- STRESS_MID: 208t +$1,569 | STRESS_ORB: 76t +$933 | FADE: 196t +$717
- GF_SHORT: 25t +$140 | GAP_FILL: 27t +$81 | VWAP_MR: 143t -$11

### Next steps (ordered)
- [ ] **BLOCKER: VWAP_MR replacement** — must find + implement before WFO/OOS
  - VWAP_MR: 143t -$11 Sharpe=-0.20. Occupies 10:15-14:00 slot (Calm + Normal)
  - All intraday replacements tested with 2020-2022 data failed (midday continuation, VWAP reclaim, etc.)
  - Need new approach or new data source (options IV? sector rotation?)
- [ ] **WFO** (blocked by above) — 48 combos, lock hyperparams
- [ ] **Fetch 2023-2024 data** (blocked) — ~3hr Polygon download
- [ ] **OOS 2023-2024** (blocked) — run once, no iteration

### Key decisions
- WFO/OOS blocked until VWAP_MR is replaced — OOS là one-shot; nếu dùng OOS với VWAP_MR còn âm rồi sau đó tìm được replacement, không thể re-run OOS nữa (data đã bị nhìn)
- Strategy space exhausted with 2020-2022 data — all gap-filling attempts fail in 2021 (bull/low-VIX)
- 11:00-14:00 dead zone is structural (market microstructure, not fixable with OHLCV data)
- OOS must be run ONCE without iteration — viewing results and adjusting = in-sample
- New strategies for 2023-2024 gap require options IV data or economic calendar

### Files touched
raits/backtest/engine.py
raits/raits/scripts/window_debug.py
raits/raits/scripts/midday_continuation_sim.py (new — dead)
raits/raits/scripts/midday_continuation_sim_v2.py (new — dead after filters)
raits/raits/scripts/remaining_strategies_sim.py (new — all dead)
raits/raits/scripts/fetch_new_stocks.py
d:\raits\analyze_system.py (diagnostic)
d:\raits\analyze_timeframe.py (diagnostic)
d:\raits\analyze_deep.py (diagnostic)
