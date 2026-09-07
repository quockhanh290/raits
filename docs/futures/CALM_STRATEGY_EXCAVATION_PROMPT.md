# Prompt: Calm Strategy Excavation

Use this prompt to continue Calm-regime research without repeating the old impossible-fill mistake.

```text
You are working in D:\raits on the futures strategy repo.

Goal: excavate a Calm-regime strategy that can complement:
- Normal core: Normal-only TF, EMA50, 2x daily ATR stop, corrected/live fill, SHORT only when SPY D-1 below SMA50.
- Stress hedge: confirmed 10:20 liquidation short, MNQ/MES, breadth/range filters.

Hard rule: do not trust any PnL unless every trade passes fill feasibility.

Required fill audit:
- Entry must be at or after the signal timestamp.
- Stop/target exits must use the first later bar that crosses the level.
- If a bar gaps through stop/target and the theoretical level is not inside that bar, fill at the feasible bar open, not the theoretical level.
- Print `outside_exit_bar` and require it to be 0.
- Keep signal research and execution feasibility separate.

Use only local data first:
- Futures 1m: data/cache/futures/frozen_sim for 2018-2024.
- 2025 OOS: data/cache/futures/frozen_2025_sim.
- 2026 check: data/cache/futures through 2026-08-19.
- Regime labels from futures._validated_core.label_regimes using spy_daily_live.csv.

Do not optimize on 2025 before selecting a candidate from 2018-2024.

Calm hypotheses to test:

1. Opening range mean reversion, not generic VWAP fade:
   - Calm only.
   - Trade only after 10:00 or 10:30.
   - Fade extensions beyond the morning range percentile.
   - Require realized volatility/range to stay below a cap.
   - Exit by VWAP/midrange/time, not wide stops.

2. Previous-day range fade:
   - If price tests prior day high/low during Calm and fails to hold outside it, fade back toward prior close/mid.
   - Require SPY D-1 RV20 below threshold.
   - Test long and short separately.

3. Modest futures gap-fill:
   - Gap from prior RTH close to current RTH open.
   - Only small gaps, e.g. 0.25%-1.0%.
   - Enter only after partial reclaim/failure confirms direction.
   - Avoid large gap/stress days.

4. Overnight / session-boundary drift:
   - Calm only, direction-specific.
   - Test close-to-next-open and RTH-open-to-midday separately.
   - Exclude macro/event days if local event calendar exists; otherwise mark event filtering as missing.

5. Cross-index relative value:
   - Calm dispersion trades, e.g. MNQ vs MES or RTY vs ES.
   - Avoid directional market beta if possible.
   - Requires pair/spread execution assumptions to be explicit; do not mix single-leg PnL with pair logic.

Output format:
- Show 2018-2024 trade-level results by variant, instrument, direction, and year.
- Show fill audit.
- Pick at most 2 candidates before touching 2025.
- Then run 2025 OOS and 2026 sanity.
- Reject any candidate where edge comes from one year only, one instrument only without a reason, or a non-feasible fill.
- If a candidate survives, run deploy-level scratch integration against the current Normal+Stress research system.

Current known negatives:
- Calm TF pullback is bad.
- Calm SHORT-only is toxic.
- Generic Calm VWAP fade on futures was negative:
  threshold 0.35 morning range, stop 0.35: 3,144 trades, -$9,998, PF 0.84.
  threshold 0.50 morning range, stop 0.35: 2,879 trades, -$12,716, PF 0.79.
- Calm overnight long drift was weak/not robust.

Deliverables:
- A scratch probe script, not production code.
- A concise findings section for docs/futures/TF_REGIME_RESEARCH_2026-08-20.md.
- A verdict: reject / keep digging / deploy-level candidate.
```
