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
- **Gap Fill 3-5%**: Only 1 trade in 3 years — gaps this large almost never qualify on Normal days.
- **Gap Fill window extension 10:30→11:30**: p=0.053, ticker concentrated (61% top 3), scan times noisy. Old PKL.
- **RVOL filter for RS**: >1.2x collapses to 5 trades. Universe too small.
- **Calm afternoon strategy**: No edge. 52 days, 71% in 2021, all signal types noisy.
- **VWAP_MR universe removal (IWM, QQQ, XLV, XLP)**: Curve fitting. Rejected.
- **VWAP_MR signal filters (wick/rejection/volume)**: All make things worse in combined tests.
- **Yesterday's large mover momentum/reversal** (threshold 2.5%): Total 2771t -$82,636. STOP_HIT rate 29-33% kills 2R setup. TIME_STOP positive drift (+$76-86/trade) but 2R target unreachable. 2021 vs 2022 inconsistent.
- **Failed Gap Short** (gap UP 1.5-3%, fail at 10:30): 106t +$10,156 overall BUT 2022-only edge. 2020 p=0.434, 2021 p=0.165, 2020+2021 combined p=0.282. SPY filter does all the work — removes 106 trades worth -$9,228. In 2022 SPY was below VWAP 100% of signal days (bear market), TARGET_HIT 75% vs 28% in 2020. Structurally a macro bear-market bet, not a replicable Normal-regime edge. DEFERRED.

## STRESS_MID (Stress 10:15–14:00 ETF momentum)

**Signal**: close[10:15] < VWAP(9:30-10:15) AND close[10:15] < open → SHORT
**Stop**: swing high (9:45-10:15) + 0.1% — VWAP stop too tight (47% stop-hit rate)
**Results** (sim, 97 Stress days): 86t, +$21,918, WR=66%, avg=$254.9/trade
- 2020: 20t +$4,693 WR=60% | 2021: 20t +$7,390 WR=80% | 2022: 46t +$9,835 WR=63%
- Raw directional edge: 73% WR without stops
- **Position sizing caveat**: stop=$2.165 avg → 231 shares × $315 = $72k notional on $25k account
  Engine PositionSizer sẽ cap position → real P&L estimate ~$2,800–4,000
- **Status**: IMPLEMENTED in engine.py section 7e. Verify trades appear via window_debug --year 2022.
- Script: `raits/raits/scripts/stress_mid_sim.py`

## STRESS_ORB_STK (DEFERRED — reverted from engine)

**Status**: Reverted. Engine produced -$2,528 / 224 trades across 3 windows (2020-2022). Sim showed +$5,581. Discrepancy unresolved.

**Root causes to investigate before re-enabling**:
1. **Universe expansion**: Adding `_STOCK_STRESS_UNIVERSE` to `_all_tickers` caused FADE/GAP_FILL to also trade these stocks → -$380 + -$264 collateral P&L. Fix: fetch STK stock bars separately, don't inject into global `day_stocks`.
2. **9:35 co-confirm timing works** (confirmed via debug log — TRADE_OPENED events fired correctly). Timing is NOT the problem.
3. **Engine P&L -$2,528**: possible causes: (a) HMM Normal in H1 2022 → too few Stress days in 2020/2021 to show edge; (b) stop too wide (1.0×ATR vs sim's 0.5×ATR); (c) SHORT bias wrong during 2020 COVID recovery; (d) position sizing reduces trade size vs sim's fixed $500 risk.
4. **Sim vs engine discrepancy**: sim used fixed per-trade risk, engine uses Kelly × account equity. On a 37-stock universe the trades are infrequent enough that sim/engine diverge materially.

**When to re-investigate**: after STRESS_MID is live and baseline is stable. Baseline after revert: **$14,932**.

## Post-earnings gap-down SHORT (DEFERRED)

**Finding**: SHORT after earnings gap-down ≥1% on Normal regime days.
- Polygon data (8-K dates): 27t +$2,689 WR=70%, all 3 years positive
- Best config: Normal ≥1%, Hold 1 day, Stop 1.5×ATR, Target 3×ATR
- Engine estimate: ~$900–1,100

**Why deferred**:
- 2022 = +$228 only (bear market → mostly Stress regime → no Normal days → no signal)
- 9 trades/year too thin for implementation overhead
- SHORT execution complex (margin, borrow)
- Needs earnings calendar maintenance (Polygon API weekly)

**Revisit when**: universe expanded to 60+ stocks → expect 15+/year → worth implementing.
- Data source confirmed: Polygon `/vX/reference/financials` `filing_date` = 8-K date = reaction day
- yfinance was noisier (more "trades" but lower quality, non-earnings gaps included)

## Pre-market bar exploration (all dead)

Pre-market bars ARE in raw parquet cache (04:00 ET start, all 50 tickers). PKL strips them at line 94.
Built `raits/data/raits_premarket.py` + `premarket_strategy_sim.py`. Results:

- **H1 PM direction filter**: removes good trades (WR filtered=50% vs removed=63%). Dead.
- **H2 Gap-and-Go LONG** (pm_return>1.5%, not fading → LONG 9:35): 91t +$1,788 p=0.234, 2022=-$462. Dead.
- **H3 PM Fade SHORT** (pm_return>1.5%, fading → SHORT 9:35): 2 trades in 3yr. Dead.

Pre-market data adds no edge over existing signals on current universe.

## VIX gate — T-1 vs same-day

**Bug**: initial implementation used prior-day VIX close (T-1). STRESS_ORB went -$510 because:
- Spike day (most profitable SHORT): T-1 VIX = 25-28 → gate BLOCKS it
- Recovery day (bad SHORT): T-1 VIX = 35+ → gate ALLOWS it
**Fix**: same-day VIX close. Works for STRESS_ORB (brief spikes). T-1 works for ORB (sustained VIX≥25 periods).

## VWAP Reclaim LONG — DEAD

**Signal**: dip below VWAP before 10:30, reclaim at 11:00, SPY above VWAP → LONG to 14:00
**Results**: 4,584t -$109,143 WR=45% | 2020=+$18,540 | 2021=-$31,380 | 2022=-$96,304
**Bootstrap**: p=1.000, CI=[$-150k, -$69k]
**Root cause**: Stop:Target = 578:59 (10:1), 23 trades/day = too noisy, 2022 bear kills edge.
**Do not revisit.**

## VIX cascade effects (accepted, no fix)

VIX gate unblocks circuit breaker → STRESS_MID fires 2× more days (106→208t), GAP_FILL fires on 6 extra bad days. Attempts to fix with VIX gate on STRESS_MID would block $+982 of profitable trades. GAP_FILL fix requires N=6 threshold = curve fitting. Accepted as cost of VIX gates; net system is still +$1,015.

## New strategy exploration results (all dead/deferred)

- **D Sector ETF divergence**: 9 ETFs vs SPY 9:35 divergence, WR=32-35% all configs, all negative. DEAD.
- **B ORB direction/DOW**: both LONG and SHORT profitable (WR=57% each). No filter justified.
- **E ORB SPY bar filter**: SPY 9:30 bar >2× mean → N=5 blocked, N=3 incremental after VIX gate. Curve fitting. DEAD.
- **C Earnings Gap UP + Fail SHORT**: best gap≥3% fail@10:15, 21t +$4,500 WR=57% p=0.040 — CI touches zero, 2022-concentrated, N too small. DEFERRED.
- **A Power Hour**: overlaps TF window (14:00-15:55). Not tested — structural conflict.
- Strategy space exhausted with current data. New sources needed for new edges (options IV, etc.).

## Open questions

- **GAP_FILL discrepancy**: CLOSED. Engine 21t +$1,163 WR=81% (GF_SHORT 25t +$140). Shortfall vs sim ($2,838) explained by position limit being binding: max_position_pct=20%×$50k=$10k/trade cap → actual risk ~$100-200/trade vs sim's fixed $500. Vol target ($500) never binding because most stocks need 500 shares = $50k notional. Not a bug — deliberate 20% concentration limit. To match sim, raise max_position_pct (but affects ALL strategies).
- **ORB 2022 crash**: WR=26%, fixed by VIX≥25 gate (-437 in 2022 = only 4 remaining bad trades, no more easy fix)
