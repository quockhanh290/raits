## Gotchas

- **Gap Fill "direct" trades = look-ahead bug**: Original RS sim showed +$10,465 because "direct" trades retroactively selected stocks that NEVER touched VWAP — not identifiable in real-time. Gap Fill doesn't have this issue (all filters checkable at 10:30).

- **Calm regime gap fill = negative**: Tested explicitly — 5t, -$193, WR=40% in Calm. Gap Fill edge is Normal-regime specific. Do NOT add Calm regime even if user asks "can we get more signals."

- **gap_fill_stop_dists cleanup**: engine.py tracks _gf_stop_dists dict by id(trade). When trade closes, dict entry is popped in section 10. If circuit breaker fires (_close_all), entries may linger but this is harmless since the dict resets next day (_gf_stop_dists is a local variable per _run_day call).

- **PositionSizer vs sim $500/trade**: Sim used fixed $500 risk. Engine uses max_risk_pct of account equity. Backtest shares/P&L will differ from sim numbers. Don't interpret this as a bug.

- **--use-results-cache invalidated**: engine.py was modified (Gap Fill added, ORB_FADE removed). Must run window_debug.py WITHOUT --use-results-cache until a fresh pkl is generated.

- **VWAP_MR TIME_STOP**: was 45 min, extended to 90 min (already in engine before this session). Noted here in case someone wonders why it differs from original blueprint.

- **ORB_FADE removal**: ORB_FADE label never appeared in actual trade path — engine was generating "FADE" label. ORB_FADE only existed in STRATEGY_CAPS and STRATEGY_STATS as dead config. Removing it had no behavioral change, just cleaned up -$330 phantom stats.

- **Calm afternoon: no edge**: 52 Calm days total (14 / 37 / 1 per year), UP rate 56%, stock MR rate 34.5%, early→late corr +0.31, PM→EOD corr +0.32. No strategy fits. Do NOT revisit without more Calm days.

## VWAP_MR Root Cause Analysis (completed, no further action)

**Finding**: STOP:TARGET = 2:1 (140 stops vs 70 targets). Root cause identified:

**H2 (stop too wide): REJECTED**
- 54% of TARGET_HIT trades have MAE < 0.3×ATR — win cleanly with almost no adverse move
- 0% of winners had MAE > 1.5×ATR — stop never blocks an eventual winner
- Tightening to 1.0×ATR would kill 18% of winners. Stop 1.5×ATR is correct.

**H1 (signal quality): NOT ACTIONABLE**
- Wick ratio: smaller wick = better WR (71% for tiny <0.1×ATR) but only 21 trades
- Rejection ratio: ~0.05 across all trades — measurement issue, bars don't snap back before entry
- Volume filters: make things WORSE in combined tests
- All H1e combined filters: worse than or equal to baseline

**H3 (universe): CURVE FITTING**
- IWM, QQQ, XLV, XLP are systematic losers (-$98 of -$128 total)
- Removing them based on backtest results = curve fitting. Rejected.

**F2+F3 filters: available but not implemented**
- F2: skip SHORT when SPY > VWAP after 12:30
- F3: skip LONG 12:00–13:00
- Sim: 133t, +$54, WR=48%, sys $9,230 (+$182 vs baseline)
- 2020 still negative (-$29). Not implemented — improvement too small and 2020 unresolved.
- Can revisit if needed. Code preview in TASK history.

**Conclusion**: VWAP_MR has thin edge in 2020-2022 with current design. No clean fix found. Left at -$128 / 267t / WR=40%.

## Rejected approaches

- **RS LONG**: ALL configs negative. Buying after strength = entering overextended moves.
- **RS breakeven stop**: WR drops from 47% → 13%. Wrong for this setup.
- **Gap Fill retrace ≥40% or ≥30%**: Marginal trades only $17-35/trade vs $123/trade baseline.
- **Gap Fill SHORT**: WR=40%, 2022 always negative, no regime combination helped.
- **RVOL filter for RS**: >1.2x collapses to 5 trades. Universe too small.
- **Calm afternoon strategy**: No edge. 52 days, 71% in 2021, all signal types noisy.
- **VWAP_MR universe removal (IWM, QQQ, XLV, XLP)**: Curve fitting. Rejected.
- **VWAP_MR signal filters (wick/rejection/volume)**: All make things worse in combined tests.

## STRESS_MID (Stress 10:15–14:00 ETF momentum)

**Signal**: close[10:15] < VWAP(9:30-10:15) AND close[10:15] < open → SHORT
**Stop**: swing high (9:45-10:15) + 0.1% — VWAP stop too tight (47% stop-hit rate)
**Results** (sim, 97 Stress days): 86t, +$21,918, WR=66%, avg=$254.9/trade
- 2020: 20t +$4,693 WR=60% | 2021: 20t +$7,390 WR=80% | 2022: 46t +$9,835 WR=63%
- Raw directional edge: 73% WR without stops
- **Position sizing caveat**: stop=$2.165 avg → 231 shares × $315 = $72k notional on $25k account
  Engine PositionSizer sẽ cap position → real P&L estimate ~$2,800–4,000
- **Status**: NOT yet in engine. Edge confirmed, worth implementing.
- Script: `raits/raits/scripts/stress_mid_sim.py`

## STRESS_ORB_STK (DEFERRED — reverted from engine)

**Status**: Reverted. Engine produced -$2,528 / 224 trades across 3 windows (2020-2022). Sim showed +$5,581. Discrepancy unresolved.

**Root causes to investigate before re-enabling**:
1. **Universe expansion**: Adding `_STOCK_STRESS_UNIVERSE` to `_all_tickers` caused FADE/GAP_FILL to also trade these stocks → -$380 + -$264 collateral P&L. Fix: fetch STK stock bars separately, don't inject into global `day_stocks`.
2. **9:35 co-confirm timing works** (confirmed via debug log — TRADE_OPENED events fired correctly). Timing is NOT the problem.
3. **Engine P&L -$2,528**: possible causes: (a) HMM Normal in H1 2022 → too few Stress days in 2020/2021 to show edge; (b) stop too wide (1.0×ATR vs sim's 0.5×ATR); (c) SHORT bias wrong during 2020 COVID recovery; (d) position sizing reduces trade size vs sim's fixed $500 risk.
4. **Sim vs engine discrepancy**: sim used fixed per-trade risk, engine uses Kelly × account equity. On a 37-stock universe the trades are infrequent enough that sim/engine diverge materially.

**When to re-investigate**: after STRESS_MID is live and baseline is stable. Baseline after revert: **$14,932**.

## Open questions

- **GAP_FILL discrepancy**: sim +$2,838 vs engine actual -$61 — needs debug
- **ORB 2022 crash**: WR=26%, -$1,574 — direction filter (SPY alignment) could fix
- RS SHORT: already running in engine (136t, -$81 total) despite "deferred" status
- STRESS_ORB: enabled in engine but results not shown in last window_debug output
