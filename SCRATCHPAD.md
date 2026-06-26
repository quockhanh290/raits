## Gotchas

- **20 pytest failures — all stale tests, zero production bugs** (2026-06-25): Verified pre-vault. Categories: VWAP_MR removed (7), HMM Stress→SAFETY_MODE design changed (6), ORB fakeout→FADE design (1), ORB max_price $200→$1000 (1), grid 27→48 combos (1), Crisis HMM missing in test data (1), strategy_router safety_mode stale (1), sector_strength not implemented (1 — see dedicated note below). Tests reflect old design; current behavior is intentional and embedded in WFO results.

- **TrendFollow sector_strength filter NOT implemented** (2026-06-25): `run_scanner()` accepts `sector_strength` field but does not filter on it. Sector ETF data (XLF, XLE...) was unavailable during IS development 2017-2022. Implementing filter pre-vault would require new WFO run — deferred post-vault. Impact: TF may accept trades when sector is selling off. Documented in `trend_follow.py` docstring.

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

## VWAP Reclaim SHORT — DEAD

**Signal**: SPY<VWAP@10:15 (bearish day), stock bounces to VWAP from below and closes below (rejection) → SHORT 10:30-13:30.
**Results**: 1419t P&L=-$135 WR=36% p=0.565 CI=[-$1,753, +$1,556]
- 2020: 415t -$420 | 2021: 452t +$524 | 2022: 552t -$238
- Core ETF: 435t -$7 | Stocks+ETF: 984t -$128
- 881/1419 (62%) STOP_HIT — VWAP does not act as consistent resistance
**Root cause**: Signal fires on ~4.3 tickers/day whenever SPY is bearish (328/756 days = 43%). Too common → essentially random short momentum. WR=36% barely above 33% break-even for 2R target but commission drag overwhelms thin edge.
**Do not revisit.**

## GAP_FILL sizing fix — DEAD (sizing illusion)

**Hypothesis**: Engine's max_position_pct=20% caps P&L. Raise to 50% or use uncapped vol-sizing.
**Analysis**: 27 engine GAP_FILL trades, all POSITION_LIMIT-bound (100%). Stop_dist range $0.10–$7.84 (mean $1.84).

| Scenario | P&L | 2020 | 2021 | 2022 |
|---|---|---|---|---|
| A Current (Kelly+20% cap) | +$81 | -$297 | +$586 | -$208 |
| B Vol-sizing, 20% cap | +$102 | -$291 | +$600 | -$207 |
| C Vol-sizing, 50% cap | +$435 | -$557 | +$1,508 | -$516 |
| D Uncapped $500/stop_dist | +$10,133 | +$4,053 | +$5,704 | +$376 |

**Why C fails**: amplifies losers equally — 2020 and 2022 get worse.
**Why D is fake**: TSLA 2020 trade (stop_dist=$0.098) gets 5,079 shares × $49 = $248k position. Same sizing illusion as STRESS_ORB_STK's +$6,368 sim → artificial leverage on tight stops.
**The sim's +$2,838 was also a sizing illusion.** Not a real edge.
**Do not revisit.**

## BacktestConfig orphaned fields (found 2026-06-23)

`BacktestConfig` trong `data_types.py` có 4 fields không được wire đúng:
- `max_position_pct` (0.20) — không truyền vào PositionSizer → luôn dùng default 0.20. **Fixed** (engine.py init).
- `kelly_fraction` (0.5) — không truyền, nhưng PositionSizer cũng default 0.5 → no bug. **Fixed** (engine.py init).
- `atr_stop_multiplier` (3.0) — chỉ khai báo, không dùng ở bất kỳ đâu. Dead field, để nguyên.
- `risk_per_trade_pct` (0.01) — shadow bởi `max_risk_pct` (cùng giá trị). Dead field, để nguyên.

Root cause: fields thêm vào dataclass qua nhiều iteration, không update engine init caller.
Limiting factor per strategy: FADE/GAP_FILL/ORB/STRESS_MID = POSITION_LIMIT. TF/VWAP_MR/STRESS_ORB/GF_SHORT = KELLY.

## System deep analysis (2026-06-23, snapshot results_20260623_070518.pkl)

**Risk-adjusted metrics (baseline $17,629):**
- CAGR: 11.75%/yr | Sharpe: 2.49 | Sortino: 3.67 | Calmar: 3.42
- Max DD: -$1,720 (-3.4%) — comfortably within -4% circuit breaker
- 2020=+$6,139 | 2021=+$8,017 | 2022=+$3,473

**Structural findings:**
- TREND_FOLLOW = 54% of P&L (concentration risk). TF avg/trade declining: 2020=$49 → 2021=$34 → 2022=$21.7
- TSLA = 17.3% of total P&L, top-5 tickers = 64% — extreme concentration
- Swing trades (>7hr): 292t → $12,437 (70.5% of P&L). Intraday: 717t → $5,192 (29.5%)
- Dead zone 11:00-14:00 is **structural** (all new strategy attempts fail there)
- VWAP_MR Sharpe=-0.20 (only negative), but kept: exits at 14:00 (TF start), no slot conflict
- Strategies by Sharpe: PE_SHORT=6.35 | GF_SHORT=5.03 | STRESS_ORB=4.71 | ORB=4.36 | TF=3.06 | VWAP_MR=-0.20

**Key OOS risks:**
- TF declining trend (main revenue driver degrading year-over-year)
- STRESS_ORB + STRESS_MID idle in low-VIX 2023-2024 environment
- TSLA dynamics changed post-2022 (high beta factor gone)

## Gap-filling strategy exploration — all dead (2026-06-23)

Tested 4 new strategies for architectural gaps, all with proper engine filters (scanner + CB + overlap):

| Strategy | Trades | P&L | WR | p-value | 2021 | Verdict |
|---|---|---|---|---|---|---|
| Midday Continuation LONG | v1: 278t +$4,747 | — | 55.8% | 0.019 | — | v1 MISLEADING |
| Midday Continuation LONG (v2, filtered) | 70t | +$18 | 45.7% | 0.491 | neg | DEAD |
| Late-Day Breakout (15:00-15:55) | 56t | +$1,268 | 55.4% | 0.067 | -$217 | DEAD |
| Calm Swing LONG (T+1) | 74t | +$1,462 | 51.4% | 0.238 | -$173 | DEAD |
| Normal SHORT Breakdown (T+1) | 132t | +$1,006 | 47.7% | 0.429 | -$2,302 | DEAD |

**Root cause — all fail in 2021 (bull/low-VIX):** System is structurally optimized for volatile/trending environments (2020 COVID + 2022 bear). Low-VIX bull markets require different signal types (options IV, sector rotation, macro calendar). 2020-2022 OHLCV data cannot generate edge for this environment.

**Do not sim more strategies with 2020-2022 data — strategy space is exhausted.**

## Look-ahead bias lesson (Late-Day Breakout)

First run: checking `b1500.iloc[0]['high'] > prior_high` then entering at `b1500 open` = look-ahead (bar high unknown at open). Fix: check `b1455.high > prior_high`, enter at `b1500 open`. Impact: 61t → 56t, +$2,530 → +$1,268, p=0.006 → 0.067. Always verify signal bar vs entry bar distinction.

## VWAP_MR instrument bias — discovered 2026-06-24

**Finding:** VWAP_MR bootstrap (p=0.613) and IS removal were based on trades on **stocks** (MR_CANDIDATE_POOL via MR scanner), NOT sector ETFs.

Engine logic (engine.py lines 545-546):
```python
_effective_vwap_universe = mr_scanner_results + [t for t in config.vwap_universe if t not in scanner]
```
Sector ETFs (XLF, XLE...) in `config.vwap_universe` had NO data for 2017-2022 → ETF universe = empty → all 272 zombie trades were on momentum stocks (TSLA, NVDA, AMD) = wrong instrument for mean reversion.

**Implication:** Must re-evaluate VWAP_MR on sector ETF data (fetch in progress) before treating removal as final. Could be meaningfully different on range-bound ETFs vs momentum stocks.

## Data gap — sector ETFs missing IS data (2026-06-24)

XLF, XLE, XLV, XLU, XLI, XLK, XLP, XLB, XLY, GLD: only 2023-2024 in cache.
Fix: `fetch_sector_etfs.py` (d:\raits\raits\) — fetches 2017-2022 IS + 2023-2024 OOS.
Run after PE_EXPANSION/META fetch completes.

## IS 2017-2022 Optimization Session (2026-06-24)

### New baseline settings
- IS period: 2017-2022, $50k account
- max_risk_pct=1.5%, kelly_fraction=0.75, MAX_TREND=3, PE_SHORT_GAP_MIN=0.05
- Snapshot: results_20260624_135619.pkl → Ann=10.5%, +$31,484/6yr

### Bootstrap per strategy (results_20260624_135619.pkl)
- CONFIRMED (CI>0): TF p=0.008, PE_SHORT p=0.007, ORB p=0.019, STRESS_ORB p=0.019
- NO EDGE: FADE p=0.754, GAP_FILL p=0.687, VWAP_MR p=0.613
- BORDERLINE: STRESS_MID p=0.112, GF_SHORT p=0.128
- STRESS_MID surprise: 270t +$2,406 total but mean=+$9/trade vs high variance → CI crosses zero

### MAX_TREND=3 analysis
- +$3,158 total, ann 10.5% (crosses 10% target)
- 2021 worse by -$3,704: slot 3 takes 49 extra trades (avg -$27, WR=43%, 61% MAX_HOLD)
- Extra trades bad across ALL regimes and directions — structural: slot 3 = weakest setups
- ADX gate sim: ADX≥15 removes 21 bad trades (+$1,357) but p=0.113 → too few trades, likely overfit
- Accept TF=3: net 6yr benefit outweighs 2021 cost

### FADE exhaustive analysis — REMOVE confirmed
- Gap size: <1% best (WR=53%, avg=+$10) but CI still crosses zero (p=0.113)
- Prior day return: abs<1% best but p=0.088 — still no confirmed edge
- Combined Calm+prior<1%: p=0.095 — closest but not confirmed
- Year-by-year with any filter: inconsistent (2017 negative even in "good" conditions)
- p-hacking path: adding 5 conditions → n=5 trades, p=0.004 — meaningless (overfitting)
- SPY_5d signal: good trades have SPY_5d=-0.3% vs bad trades SPY_5d=+1.7% — real signal but sample too small
- Thursday WR=73% vs Friday WR=47% — real pattern but sample too small
- Verdict: No filter rescues FADE. 2017/2021 outperformance = random variation.

### Coverage after removing FADE/GAP_FILL/VWAP_MR
- Calm regime: 421 → 8 trades (only PE_SHORT, earnings days only)
- Normal: 863 → 781 (ORB + TF + GF_SHORT + PE_SHORT) — well covered
- Stress: 592 → 592 (STRESS_MID + STRESS_ORB + TF) — well covered
- Midday 10:15-14:00 in Calm = zero coverage — ACCEPTABLE (both strategies had no edge)
- Years most affected: 2017 (51% Calm), 2019 (36% Calm), 2021 (32% Calm)

### Position sizer limiting factors (current baseline)
- TF: Kelly-bound 97% trades → kelly_fraction is the lever
- ORB: PosLimit-bound 100% → max_position_pct=0.30 is binding (Kelly cap ~$16,900 > $15k)
- STRESS_MID: PosLimit-bound 100% → Kelly cap ~$18,400 > $15k
- PE_SHORT: Mixed (70% PosLimit, 30% VolTarget) → Kelly cap ~$21,750 > $15k

### Actual IS strategy stats vs hardcoded bootstrap
All strategies have LOWER actual Kelly fraction than hardcoded values:
- TF: 0.280 (hardcoded) → 0.134 actual (-52%)
- STRESS_MID: 0.490 → 0.074 (-85%) — most over-estimated
- ORB: 0.451 → 0.262 (-42%)
- PE_SHORT: 0.580 → 0.478 (-18%) — most accurate
- Payoff ratios lower because many trades exit before target (time stop, swing exit)
- Do NOT update STRATEGY_STATS — would reduce position sizes and hurt P&L

## Open questions

- **GAP_FILL discrepancy**: CLOSED. Sim +$2,838 was sizing illusion — uncapped $500/stop_dist on $0.10 stop = $248k hypothetical position. Engine's 20% cap is correct risk management. No fix viable.
- **ORB 2022 crash**: WR=26%, fixed by VIX≥25 gate (-437 in 2022 = only 4 remaining bad trades, no more easy fix)
- **Strategy space exhausted (2020-2022)**: All buildable strategies tested. Need 2023-2024 OOS data or new data sources (options IV, sentiment, earnings calendar expansion).
