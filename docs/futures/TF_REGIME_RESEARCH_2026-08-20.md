# Futures TF regime research - 2026-08-20

Scope: research note only. No production-code change is implied by this file.

## P0 correctness rule: no impossible fills

Do not trust any PnL table for a new Stress/Calm/Normal strategy until it passes an independent fill-feasibility audit.

Required checks:

1. Entry/exit prices must be reachable from the bar path after the order is live.
2. A stop fill may not be booked at a price that was never crossed after the stop was armed.
3. Same-day OHLC reach is not enough if the stop was armed after the high/low already happened.
4. For any trade table, audit both:
   - `outside_exit_bar`: exit price outside the chosen execution bar high/low.
   - `outside_exit_day`: exit price outside that day's high/low.
5. For stop corrections, use conservative path law:
   - LONG stop: fill at first later low crossing the stop; if bar gaps through, use the feasible crossing/open law used by the execution model.
   - SHORT stop: symmetric first later high crossing.
6. Research scripts must print fill-correction count and dollars before their PnL is considered comparable.

Reason: the prior TF backtest booked some exits at prices that did not exist in the data after the stop was live.
Independent audit found:

- checked trades: 2,496
- outside exit bar: 594 trades, 23.80%
- outside exit day: 116 trades, 4.65%
- corrected trades: 617, 24.72%
- old trade-table total: +$32,694
- corrected trade-table total: -$6,330
- PF: 1.299 -> 0.957

So future Stress/Calm excavation must treat signal research and execution feasibility as separate gates.

## Engine convention after correction

Whole deploy engine with corrected fill and live stop convention:

- baseline: +$3,716, Calmar 0.09
- floor: +$2,664, Calmar 0.07
- vault2324: +$17,943, Calmar 4.11
- vault2025: +$4,998, Calmar 1.11

Verdict: old baseline thesis collapsed; the deployable edge has to be rebuilt as regime-specific.

### Comparison against current repo baseline with old stop-fill bug

Repo default deploy baseline, rerun on `data/cache/futures/frozen_sim` through 2024-12-31 with 1 micro and 2 ticks/side:

| System | Net | PF | Sharpe | Calmar | MaxDD | Read |
|---|---:|---:|---:|---:|---:|---|
| Current repo default baseline, old stop-fill law | +$42,459 | 1.48 | 1.67 | 1.72 | 7.1% | Inflated by known impossible/too-favorable stop fills. |
| Corrected Normal candidate only | +$28,794 | 1.33 | 1.59 | 0.43 | 19.5% | More honest fill convention; lower net and much higher DD. |
| Corrected Normal candidate + Stress `breadth3` | +$34,833 | 1.36 | 1.73 | 0.76 | 13.3% | Recovers part of net/DD, Sharpe slightly above old baseline, but still lower PF/Calmar. |
| Repo default baseline + opt-in Stress candidate | +$45,314 | 1.54 | 1.85 | 1.84 | 7.1% | Smoke only; not valid for promotion because the default swing sleeve still carries the old fill bug. |

Interpretation:

- Do not compare against the current repo default as a valid target. It is the contaminated benchmark.
- The honest combined candidate recovers about +$6,039 vs corrected Normal-only, but remains -$7,626 below the old bugged baseline net.
- Sharpe is not worse after adding Stress (`1.73` vs old `1.67`), but Calmar remains much lower because corrected fills expose larger drawdown.
- The right bar is not "beat the bugged baseline"; it is "beat corrected baseline and survive OOS/bootstrap/live timing".

## Current best Normal TF candidate

Base candidate:

- Regime: Normal only.
- Entry: slower pullback filter, EMA50.
- Stop: fixed stop, live law, 2x daily ATR.
- Fill: corrected feasible-fill law.
- Stress/Calm: disabled for this sleeve.

Best current improvement:

- Keep LONG signals in Normal.
- Permit SHORT only when broad market is already weak.
- Current proxy: SPY D-1 close below SMA50.

Deploy-engine measurements for:

`Normal only + EMA50 + 2x daily ATR stop + LONG always + SHORT only if SPY below SMA50`

| Window | Net | PF | Sharpe | Calmar | MaxDD | Halts |
|---|---:|---:|---:|---:|---:|---:|
| baseline 2018-2024 | +$28,794 | 1.33 | 1.59 | 0.43 | 19.5% | 0 |
| floor 2018-2024 | +$33,181 | 1.36 | 1.73 | 0.52 | 18.5% | 0 |
| vault2324 | +$23,256 | 2.17 | 4.33 | 2.70 | 8.9% | 0 |
| vault2025 | +$6,857 | 1.51 | 2.33 | 1.47 | 10.1% | 0 |
| vault2026 to 2026-08-19 | +$6,747 | 1.46 | 2.43 | 1.62 | 15.0% | 0 |

Year split:

| Window | Net | Calmar | MaxDD | Halts |
|---|---:|---:|---:|---:|
| 2018-2020 | +$9,211 | 0.64 | 10.3% | 0 |
| 2021 | +$2,628 | 0.51 | 11.2% | 0 |
| 2022 | -$1,186 | -0.20 | 13.0% | 0 |
| 2023 | +$16,599 | 8.61 | 4.2% | 0 |
| 2024 | +$5,738 | 1.43 | 8.9% | 0 |

Trade-level 2021 diagnosis under Normal-only EMA50 stop2 before directional market filter:

- total 2021: -$8,501
- LONG 2021: +$2,965
- SHORT 2021: -$11,466

Interpretation:

- 2021 was not a generic TF failure. It was mainly SHORT exposure during a strong/low-drawdown bull market.
- The SPY below-SMA50 gate addresses the actual failure mode better than banning all shorts.
- 2022 remains weak, but much less toxic than before.
- Vault is better than baseline because 2023-2024 is the regime where this sleeve has the strongest edge; baseline includes slower/weak/poison years.

## What is not live-ready yet

This candidate is promising but not live-approved.

Open gates:

1. Re-run with a frozen WFO selection process, not hand-picked from a grid.
2. Confirm plateau around EMA40-60 and stop 1.5-2.5x daily ATR.
3. Re-audit fills on the final trade table.
4. Verify that SPY below-SMA50 uses only D-1 data in live path.
5. Check interaction with NKD and any non-Roska4 sleeves.
6. Recompute combined portfolio cap/breaker behavior after selecting final parameters.

### Normal sleeve validation pass 1 - standalone corrected core

Artifact: `scratch/normal_sleeve_validation.py`.

Purpose:

- Validate the corrected Normal core by itself before final 3-regime integration.
- Base candidate: Normal-only TF, EMA50, 2x daily ATR stop, corrected/live fill, fixed stop/no ratchet, SHORT only when SPY D-1 is below SMA50.
- Stress disabled. NKD included in the base Normal sleeve unless explicitly testing `r4_no_nkd`.

Current Normal base:

| Window | Net | PF | Sharpe | Calmar | MaxDD | Fill correction |
|---|---:|---:|---:|---:|---:|---:|
| 2018-2024 floor | +$33,181 | 1.36 | 1.73 | 0.52 | 18.5% | 4 trades / $483 |
| vault2324 | +$23,256 | 2.17 | 4.33 | 2.70 | 8.9% | 0 |
| 2025 OOS | +$6,857 | 1.51 | 2.33 | 1.47 | 10.1% | 0 |
| 2026 to 2026-08-19 | +$6,747 | 1.46 | 2.43 | 1.62 | 15.0% | 0 |

Key risk/parameter checks:

| Case | floor | vault2324 | 2025 OOS | 2026 sanity | Read |
|---|---:|---:|---:|---:|---|
| `r4_no_nkd` | +$8,570, Calmar 0.18, MaxDD 22.7% | +$19,792, Calmar 4.13, MaxDD 5.0% | +$4,654, Calmar 1.64, MaxDD 6.2% | +$736, Calmar 0.21, MaxDD 12.7% | NKD hurts 2023-2024 risk-adjusted but is crucial for floor/2026 net. |
| `hold3` | +$32,305, Calmar 0.66, MaxDD 14.2% | +$19,579, Calmar 1.89, MaxDD 10.7% | +$6,793, Calmar 1.48, MaxDD 9.9% | +$7,376, Calmar 2.94, MaxDD 9.1% | Best risk-control candidate, but gives up vault2324 strength. |
| `hold7` | +$27,789, Calmar 0.55, MaxDD 14.9% | not rerun | +$3,489, Calmar 0.57, MaxDD 13.1% | +$8,288, Calmar 1.96, MaxDD 15.2% | Higher 2026 net but worse 2025/floor; reject as default. |
| `cap025` | +$20,291, Calmar 0.68, MaxDD 8.7% | +$13,570, Calmar 1.62, MaxDD 8.7% | +$4,783, Calmar 1.31, MaxDD 7.9% | +$5,187, Calmar 1.94, MaxDD 9.7% | Lower-risk fallback; discards a lot of edge. |
| `cap075` | +$9,911, Calmar 0.22, MaxDD 21.4% | not rerun | -$2,105, Calmar -0.26, MaxDD 19.6% | -$6,308, Calmar -4.66, MaxDD 16.2% | Do not widen Normal cap. |
| `nkd_ema20` | +$8,224, Calmar 0.19, MaxDD 20.9% | not rerun | +$6,894, Calmar 1.33, MaxDD 11.2% | +$6,152, Calmar 1.40, MaxDD 15.8% | Reject; destroys floor lineage. |
| `ema40` | not rerun | not rerun | +$2,558, Calmar 0.55, MaxDD 10.1% | +$7,459, Calmar 1.86, MaxDD 14.5% | Mixed; 2025 too weak. |
| `ema60` | not rerun | not rerun | +$6,238, Calmar 1.32, MaxDD 10.2% | +$5,560, Calmar 1.26, MaxDD 15.9% | Worse than base. |
| `stop15` | not rerun | not rerun | +$7,736, Calmar 1.50, MaxDD 11.1% | +$3,271, Calmar 0.78, MaxDD 15.2% | Too harmful in 2026. |
| `stop25` | not rerun | not rerun | +$7,264, Calmar 1.88, MaxDD 8.4% | +$6,442, Calmar 1.60, MaxDD 14.6% | Viable sensitivity but not clearly better than base/hold3. |
| `short_weak_combo` | prior floor +$26,429, Calmar 0.46, MaxDD 16.8% | not rerun | +$8,213, Calmar 1.77, MaxDD 10.1% | +$6,329, Calmar 1.91, MaxDD 12.0% | OOS tempting but floor weaker; likely selection-pocket risk. |

Interpretation:

- Current Normal base remains the default corrected core.
- `hold3` is the only Normal parameter change that deserves WFO: it improves floor and 2026 drawdown/Calmar while barely hurting 2025, but it gives up a large part of the 2023-2024 vault.
- Do not widen the R4 Normal cap to 7.5%; it is strongly harmful in floor, 2025, and 2026.
- A tight 2.5% Normal cap is a defensive fallback, not an improvement: it lowers DD but gives up too much net.
- NKD is uncomfortable: it lowers vault2324 risk-adjusted metrics, but removing it destroys floor and 2026. Keep NKD for now, but do not tune NKD params from OOS pockets.
  - **Superseded 2026-08-21 - see "Normal sleeve independent fill audit".** Removing NKD does not destroy the floor edge; it trips the account circuit breaker on 2022-05-17, after which the halt never lifts and 2023-2024 are structurally zero. With the breaker off, `r4_no_nkd` on floor is +$29,278, not +$8,570. The floor column of this table is therefore not comparing like with like: rows whose floor MaxDD runs above about 20% of account (`r4_no_nkd` 22.7%, `cap075` 21.4%, `nkd_ema20` 20.9%) are candidates for the same latch and their floor nets are not comparable to unlatched rows. Which of those three actually latched is **not yet measured** - the test is to re-run those floor cases printing the halt count and the peak-relative drawdown.
- EMA/stop/short-filter tweaks are mixed. `short_weak_combo` should not be selected despite good 2025/2026 because prior floor was weaker.

Verdict: keep current Normal base for combined-system work, with `max_hold_days=3` as the only serious Normal WFO candidate. Final selection must be WFO/fold-based, not chosen from 2025/2026.

### Normal sleeve WFO pass 2 - max hold only

Artifact: `scratch/normal_sleeve_validation.py` with yearly custom windows.

Purpose:

- Decide whether to replace current `max_hold_days=5` with `3` or `4`.
- Keep everything else frozen: Normal-only, EMA50, 2x daily ATR stop, corrected/live fill, SPY D-1 below-SMA50 short filter, NKD included, Stress disabled.
- Selection uses 2018-2024 only. 2025/2026 are not used to choose.

Yearly results:

| Year | hold5 current | hold3 | hold4 |
|---|---:|---:|---:|
| 2018 | +$2,529 | +$5,145 | +$24 |
| 2019 | +$4,413 | +$2,538 | +$5,581 |
| 2020 | +$2,423 | +$4,133 | +$6,145 |
| 2021 | +$2,628 | -$1,614 | +$1,629 |
| 2022 | -$1,186 | +$57 | +$2,736 |
| 2023 | +$16,599 | +$12,849 | +$12,433 |
| 2024 | +$5,738 | +$5,293 | +$5,005 |

Static totals:

| Window | hold5 current | hold3 | hold4 |
|---|---:|---:|---:|
| 2018-2024 yearly sum | +$33,144 | +$28,401 | +$33,553 |
| 2021-2024 yearly sum | +$23,779 | +$16,585 | +$21,803 |

Simple WFO by prior cumulative net:

| Test year | Prior years | Selected hold | Test net |
|---|---|---:|---:|
| 2021 | 2018-2020 | 3 | -$1,614 |
| 2022 | 2018-2021 | 4 | +$2,736 |
| 2023 | 2018-2022 | 4 | +$12,433 |
| 2024 | 2018-2023 | 4 | +$5,005 |

WFO total 2021-2024: +$18,560.

Comparison on the same 2021-2024 test years:

- Always hold5 current: +$23,779.
- Always hold4: +$21,803.
- Always hold3: +$16,585.
- WFO-selected hold: +$18,560.

Interpretation:

- `hold4` has the best 2018-2024 static sum by a tiny margin, but it gives up too much in 2023-2024.
- The actual WFO rule does **not** beat simply keeping current hold5.
- `hold3` remains useful as a defensive stress test because it reduces drawdown in floor/2026, but the yearly WFO does not justify replacing the Normal base.

Verdict: **chốt Normal current hold5** for the combined system. Keep `hold3` only as a defensive alternative to test in combined portfolio sensitivity, not as the selected Normal sleeve.

## Stress status

Current TF pullback-continuation form does not work in Stress.

Measured attempts:

- Stress-only + EMA50 + stop2: baseline about -$7,186, Calmar -0.20.
- StressMid overlay on Normal candidate: baseline about +$3,282, Calmar 0.10; floor about -$1,298.

Interpretation:

- Stress likely needs a different strategy family.
- Intraday pullback-to-EMA is vulnerable to whipsaw, gaps, and fast volatility expansion.
- Candidate families to excavate:
  - ORB / opening-drive continuation.
  - Post-10:15 momentum continuation.
  - Breakout only after SPY/QQQ confirms direction.
  - Wider structural stops with fewer trades.
  - Crisis hedge with low carry, not daily alpha.

### Stress excavation pass 1 - futures 1m, fill-audited

Artifact: `scratch/regime_strategy_excavation.py`.

Data/test:

- Instruments: MES/MNQ/MYM/M2K via ES/NQ/YM/RTY 1m futures cache.
- Window: 2018-01-01 through 2024-12-31.
- HMM train end: 2018-01-01.
- HMM fit end: 2022-12-31.
- Cost: 2 ticks/side.
- Fill law: first later 1m bar crossing stop/target; gap-through stop/target fills at feasible bar open.
- Fill audit: `outside_exit_bar=0`.

Tested families:

1. `stress_mid_short`
   - 10:15 short if price is below VWAP and below day open.
   - Stop: 09:45-10:15 swing high + 0.1%.
   - Target: 2R.
   - Exit: 14:00.
2. `stress_orb_short`
   - Short first close below 09:30-09:45 opening range low.
   - Stop: OR high.
   - Target: 1.5R.
   - Exit: 11:30.
3. `stress_orb_bidir`
   - Long first close above OR high.
   - Stop: OR low.
   - Target: 1.5R.
   - Exit: 11:30.

Results:

| Strategy | Trades | Net | PF | Exp/trade |
|---|---:|---:|---:|---:|
| stress_mid_short | 171 | +$377 | 1.04 | +$2.20 |
| stress_orb_short | 228 | +$246 | 1.02 | +$1.08 |
| stress_orb_bidir | 168 | -$410 | 0.95 | -$2.44 |

Year behavior:

- `stress_mid_short`: 2022 +$1,888, but 2020 -$929 and 2019 -$612.
- `stress_orb_short`: 2022 +$3,052, but 2020 -$3,482.
- `stress_orb_bidir`: 2020 +$1,041, but 2022 -$1,513.

Interpretation:

- Stress has some directional movement, but the tested futures ORB/midday forms are close to noise after cost.
- The sign flips by crisis type: COVID-style 2020 and 2022 bear-stress want different behavior.
- Do not enable Stress alpha from this pass.
- Next Stress path, if continued: classify Stress subtypes before strategy selection, e.g. crash-gap/liquidation vs bear-trend continuation.

### StressMid audit - fill vs timing

Artifacts:

- `scratch/stress_mid_fill_audit.py`
- `scratch/stress_mid_timing_probe.py`

Findings:

1. The current `StressMidEngine` edge is not explained by impossible stop fills.
   - Current engine trades: 183.
   - Old PnL: +$3,700.
   - Conservative gap-through replay: +$3,700.
   - `outside_exit_bar=0`.
2. The bigger issue is timing semantics.
   - Backtest `StressMidAdapter` uses `resample_5m()` and selects the bar labeled `10:15`.
   - With pandas left-labeled 5m bars, that is effectively the 10:15-10:19 bar, known only around 10:20.
   - A live 10:15 decision using only raw bars through 10:15 is materially different.

Timing probe:

| Mode | Trades | Net | PF | Exp/trade |
|---|---:|---:|---:|---:|
| current 5m bar labeled 10:15 | 183 | +$3,700 | 1.38 | +$20.22 |
| confirmed 5m signal, enter 10:20 | 182 | +$3,313 | 1.34 | +$18.20 |
| raw/live exact 1m at 10:15 | 171 | +$377 | 1.04 | +$2.20 |

Interpretation:

- The useful signal is "wait for the full 10:15-10:19 5m bar to confirm downside, then enter around 10:20", not "enter at 10:15".
- The live scheduler currently keeps the 10:20 StressMid cron disabled due operational issues around netting/position-specific stops.
- If manually re-enabled as-is, `run_live_day._stress_bars()` cuts broker bars at 10:15 before resampling, which does not recreate the backtest's full 10:15-10:19 bar. That would drift toward the weak `raw/live exact 1m at 10:15` behavior.
- Therefore StressMid is not a fill-stop illusion, but it is not currently a clean live-ready sleeve either. It needs timing alignment plus broker/stop handling fixes before promotion.

### Stress excavation pass 2 - candidate paths

Artifact: `scratch/stress_path_excavation.py`.

Tested paths:

- `conf1020_*`: wait for the full 10:15-10:19 5m bar, enter around 10:20, short only.
- `breadth3`: at least 3 of MES/MNQ/MYM/M2K are below both VWAP and day open by the confirmed 5m signal.
- `wide_range3`: breadth3 plus at least 3 instruments have 09:30-10:20 range >= 0.75%.
- `failed_reclaim`: initial downside, bounce/reclaim VWAP, then fail back below VWAP/open.
- `late_cont_break`: after 11:00, break below the 10:20 low.

All variants use first-later-bar stop/target fills and `outside_exit_bar=0`.

Additional conservative timing audit on the selected 10:20 Stress path:

- Entry is the 10:20 1-minute bar open after the full 10:15-10:19 5-minute signal bar is known.
- Exit path now starts after the 10:20 entry timestamp, not on the same 10:20 bar.
- Rerunning official deploy smoke after this change produced the same result:
  - net +$45,314
  - PF 1.54
  - Sharpe 1.85
  - Calmar 1.84
  - MaxDD 7.1%
  - stress taken 84, rejected 0
- So the selected Stress edge is not coming from same-minute entry-bar high/low leakage.

Full R4, 2018-2024:

| Variant | Trades | Net | PF | Note |
|---|---:|---:|---:|---|
| conf1020_base | 182 | +$3,313 | 1.34 | Mostly 2022 payoff |
| conf1020_breadth3 | 160 | +$3,397 | 1.40 | Better than base |
| conf1020_wide_range3 | 116 | +$2,778 | 1.41 | Less 2020 damage |
| failed_reclaim | 81 | +$2 | 1.00 | Reject |
| late_cont_break | 91 | +$1,538 | 1.34 | More balanced by year, weaker total |

OOS 2025, full R4:

| Variant | Trades | Net | PF |
|---|---:|---:|---:|
| conf1020_base | 38 | +$4,064 | 2.99 |
| conf1020_breadth3 | 34 | +$4,752 | 4.50 |
| conf1020_wide_range3 | 28 | +$4,310 | 5.57 |
| failed_reclaim | 19 | -$93 | 0.91 |
| late_cont_break | 24 | +$555 | 1.27 |

Instrument finding:

- MNQ is the strongest Stress instrument.
- MES is useful secondary.
- M2K/MYM add noise for this sleeve.

MNQ+MES shortlist:

| Variant | 2018-2024 Net/PF | Year split | 2025 Net/PF |
|---|---:|---|---:|
| conf1020_breadth3 | +$2,749 / 1.49 | 2018 -444, 2019 -250, 2020 -537, 2022 +3,979 | +$4,095 / 7.10 |
| conf1020_wide_range3 | +$2,588 / 1.60 | 2018 -491, 2019 -250, 2020 -165, 2022 +3,493 | +$3,622 / 10.67 |
| late_cont_break | +$1,646 / 1.59 | 2018 +29, 2019 -237, 2020 +466, 2022 +1,388 | +$583 / 1.43 |

Current Stress candidate:

- Primary: `conf1020_wide_range3`, MNQ+MES only, 2R target.
- Reason: preserves 2022/2025 payoff while reducing 2020 whipsaw versus breadth-only.
- Secondary hedge-style candidate: `late_cont_break`, MNQ+MES only. Lower total, but more balanced across 2018/2020/2022.

Not enough evidence:

- 2026 has only 1 Stress trade in the tested window to 2026-08-19, so it is not informative.
- These are trade-level tests, not deploy-level cap/breaker runs.
- Promotion still requires live timing alignment: signal must use the full 10:15-10:19 5m bar and enter at/after 10:20, not raw 10:15 data.

### Stress deploy-level probe

Artifact: `scratch/stress_candidate_deploy_probe.py`.

Candidate engine shell:

- `futures/stress_liquidation_1020.py`
- Research-only for live purposes; wired into deploy sim by explicit opt-in flag, not wired into live/scheduler.
- Uses basket-level breadth, so it needs a future batch signal path rather than the old per-instrument `StressMidEngine.entry_signal()` shape.

Deploy sim flag:

```powershell
python -m global_index.deploy_sim `
  --data-dir data/cache/futures/frozen_sim `
  --nkd-parquet global_index/data/NKD_frozen_2024.parquet `
  --regime-csv spy_daily_live.csv `
  --end 2024-12-31 `
  --hmm-fit-end 2022-12-31 `
  --n-contracts 1 `
  --slippage-ticks 2 `
  --include-stress `
  --stress-engine liquidation1020 `
  --stress-variant breadth3 `
  --stress-instruments MNQ,MES `
  --stress-cap 0.075
```

Smoke result on the legacy/default swing system, not the new Normal research candidate:

- net +$45,314
- Calmar 1.84
- MaxDD 7.1%
- stress taken 84, rejected 0

This proves the deploy CLI can run the candidate. It does not replace the scratch combined Normal+Stress research measurement above.

Additional official deploy-smoke windows on continuous 8y data:

| Window | Without Stress | With `breadth3` Stress | Stress entries | Read |
|---|---:|---:|---:|---|
| 2025 | +$2,607, Calmar 0.58, MaxDD 10.0% | +$4,006, Calmar 1.00, MaxDD 8.9% | taken 8, rejected 4 | Stress improved official legacy deploy sim. |
| 2026 to 2026-08-19 | +$3,516 equivalent | +$3,516, Calmar 2.20, MaxDD 5.6% | taken 0, rejected 0 | No Stress impact in current 2026 sample. |

Note: a `frozen_sim` 2025 run failed because that frozen dataset ends at 2024 and the swing layer received an empty window. The successful 2025/2026 checks used `data/cache/futures` plus `global_index/data/NKD_continuous_1m_8y.parquet`.

Setup:

- Normal layer: current best research candidate.
  - Normal only.
  - EMA50.
  - 2x daily ATR stop.
  - live/fixed stop convention.
  - corrected feasible fill.
  - SHORT only when SPY D-1 is below SMA50.
- Stress layer: `conf1020_*`, MNQ+MES only, 2R target.
- Deploy sim: original `global_index.deploy_sim` with monkeypatched scratch Stress engine.

Important risk-layer finding:

- Current `roska4_stress` cap is 2.5% gross.
- Under that cap, 2025 Stress candidate was entirely blocked:
  - stress taken 0, rejected 15.
  - deploy delta $0 even though trade-level Stress edge was positive.
- So the current cap is not a neutral test of the candidate; it suppresses it.

What-if with `roska4_stress` gross cap = 7.5%:

`wide_range3`, MNQ+MES:

| Window | No Stress | With Stress | Delta | Calmar Change | MaxDD Change |
|---|---:|---:|---:|---:|---:|
| baseline | +$28,794 | +$32,657 | +$3,863 | 0.43 -> 0.64 | 19.5% -> 14.8% |
| floor | +$33,181 | +$35,769 | +$2,588 | 0.52 -> 0.68 | 18.5% -> 15.2% |
| vault2324 | +$23,256 | +$23,256 | $0 | 2.70 -> 2.70 | unchanged |
| vault2025 | +$6,857 | +$8,758 | +$1,901 | 1.47 -> 1.88 | 10.1% -> 10.1% |
| vault2026 to 2026-08-19 | +$6,747 | +$6,747 | $0 | 1.62 -> 1.62 | unchanged |

`breadth3`, MNQ+MES, same 7.5% cap:

| Window | No Stress | With Stress | Delta | Calmar Change | MaxDD Change |
|---|---:|---:|---:|---:|---:|
| baseline | +$28,794 | +$34,833 | +$6,039 | 0.43 -> 0.76 | 19.5% -> 13.3% |
| floor | +$33,181 | +$35,930 | +$2,749 | 0.52 -> 0.64 | 18.5% -> 16.2% |
| vault2324 | +$23,256 | +$23,256 | $0 | 2.70 -> 2.70 | unchanged |
| vault2025 | +$6,857 | +$9,364 | +$2,507 | 1.47 -> 2.01 | 10.1% -> 10.1% |
| vault2026 to 2026-08-19 | +$6,747 | +$6,747 | $0 | 1.62 -> 1.62 | unchanged |

Run note: the all-window `breadth3` probe timed out after printing baseline and floor; the remaining vault windows were rerun individually and completed.

Full metric table:

| Window | Sleeve | Net | PF | Sharpe | Calmar | MaxDD |
|---|---|---:|---:|---:|---:|---:|
| baseline | no Stress | +$28,794 | 1.33 | 1.59 | 0.43 | 19.5% |
| baseline | + Stress | +$34,833 | 1.36 | 1.73 | 0.76 | 13.3% |
| floor | no Stress | +$33,181 | 1.36 | 1.73 | 0.52 | 18.5% |
| floor | + Stress | +$35,930 | 1.38 | 1.78 | 0.64 | 16.2% |
| vault2324 | no Stress | +$23,256 | 2.17 | 4.33 | 2.70 | 8.9% |
| vault2324 | + Stress | +$23,256 | 2.17 | 4.33 | 2.70 | 8.9% |
| vault2025 | no Stress | +$6,857 | 1.51 | 2.33 | 1.47 | 10.1% |
| vault2025 | + Stress | +$9,364 | 1.70 | 2.98 | 2.01 | 10.1% |
| vault2026 to 2026-08-19 | no Stress | +$6,747 | 1.46 | 2.43 | 1.62 | 15.0% |
| vault2026 to 2026-08-19 | + Stress | +$6,747 | 1.46 | 2.43 | 1.62 | 15.0% |

### Bootstrap audit

Artifact: `scratch/combined_metrics_bootstrap.py`.

Method:

- Capture daily PnL after `global_index.deploy_sim.replay`, so results include portfolio caps and circuit breaker behavior.
- Moving/block bootstrap with 5-day blocks.
- Baseline/floor/vault2025 rerun after conservative Stress entry-minute change with 1,000 iterations.
- Vault2324/vault2026 have no Stress delta in this candidate, so their bootstrap table is unchanged by the Stress path timing change.

| Window | Sleeve | P(net>0) | P(Sharpe>0) | Net 5/50/95 | Sharpe 5% | Calmar 5% | PF 5% |
|---|---|---:|---:|---:|---:|---:|---:|
| baseline | no Stress | 0.976 | 0.976 | $5,054 / $29,719 / $55,656 | 0.27 | 0.06 | 1.05 |
| baseline | + Stress | 0.995 | 0.995 | $12,751 / $35,205 / $60,074 | 0.66 | 0.15 | 1.12 |
| floor | no Stress | 0.982 | 0.982 | $9,560 / $33,310 / $58,089 | 0.48 | 0.10 | 1.09 |
| floor | + Stress | 0.989 | 0.989 | $12,269 / $35,064 / $60,915 | 0.62 | 0.13 | 1.12 |
| vault2324 | no Stress | 1.000 | 1.000 | $9,261 / $21,638 / $34,963 | 1.81 | 0.93 | 1.38 |
| vault2324 | + Stress | 1.000 | 1.000 | $9,261 / $21,638 / $34,963 | 1.81 | 0.93 | 1.38 |
| vault2025 | no Stress | 0.770 | 0.770 | -$6,271 / $5,459 / $18,855 | -2.59 | -0.75 | 0.64 |
| vault2025 | + Stress | 0.858 | 0.858 | -$3,443 / $8,798 / $22,252 | -1.27 | -0.46 | 0.82 |
| vault2026 to 2026-08-19 | no Stress | 0.749 | 0.749 | -$7,467 / $5,087 / $17,607 | -2.62 | -1.31 | 0.66 |
| vault2026 to 2026-08-19 | + Stress | 0.749 | 0.749 | -$7,467 / $5,087 / $17,607 | -2.62 | -1.31 | 0.66 |

Bootstrap interpretation:

- Baseline/floor survive bootstrap better with Stress than without Stress.
- Vault2324 is robust but has no Stress contribution.
- Vault2025 point estimate improves a lot with Stress, but the 5% bootstrap tail is still negative because one-year sample size is small and Stress trades are sparse.
- Vault2026 is not confirmed; the point estimate is positive but bootstrap tail is negative and Stress contributes no trades.

### Lookahead audit

Current pass:

- Normal entry signal: no same-bar fill table is trusted; candidate uses corrected feasible fill and live/fixed stop convention from scratch harness.
- Normal SHORT market filter: `scratch/directional_market_filter_probe.py::feature_frame()` uses `spy.shift(1)` and `rolling(...).shift(1)`, so `below_sma50` is D-1 information.
- Stress signal timing: selected path waits for the full 10:15-10:19 5-minute bar, then enters at/after 10:20.
- Stress exit timing: forward path now starts strictly after the 10:20 entry timestamp.
- NKD regime mapping: `RegimeLabels(..., lag_days=1)` uses previous US trading information for the foreign session.
- Fill feasibility: selected Stress path has `outside_exit_bar=0`; the prior impossible fill bug is not present in the Stress tests.

Open caveat:

- Regime HMM fit is intentionally frozen through `hmm_fit_end`. For baseline/floor with `hmm_fit_end=2022-12-31`, the 2018-2022 section is not a clean OOS test of the HMM state model, although per-day prediction uses only data through that day. Treat 2023-2024 and 2025+ as the cleaner regime-label OOS/sanity windows.

### Old-parameter sensitivity

Artifact: `scratch/old_param_sensitivity.py`.

Purpose: identify which inherited engine parameters are worth WFO under corrected fill, not to select final params.

Current combined reference:

- `baseline`: +$34,833, PF 1.36, Sharpe 1.73, Calmar 0.76, MaxDD 13.3%.
- `floor`: +$35,930, PF 1.38, Sharpe 1.78, Calmar 0.64, MaxDD 16.2%.
- `vault2324`: +$23,256, PF 2.17, Sharpe 4.33, Calmar 2.70, MaxDD 8.9%.
- `vault2025`: +$9,364, PF 1.70, Sharpe 2.98, Calmar 2.01, MaxDD 10.1%.
- `vault2026`: +$6,747, PF 1.46, Sharpe 2.43, Calmar 1.62, MaxDD 15.0%.

Tested inherited parameters:

| Change | baseline | vault2025 | Read |
|---|---:|---:|---|
| `max_hold_days=3` | +$37,861, PF 1.41, Sharpe 1.97, Calmar 0.96, MaxDD 11.4% | +$9,300, PF 1.62, Sharpe 2.70, Calmar 2.22, MaxDD 9.0% | Best candidate for WFO. |
| `short_filter=weak_combo` | +$26,429, PF 1.26, Sharpe 1.28, Calmar 0.46, MaxDD 16.8% | +$10,719, PF 1.76, Sharpe 3.21, Calmar 2.31, MaxDD 10.1% | Looks good in 2025 but fails baseline; likely overfit/recent pocket. |
| `ema_proximity_pct=0.003` | +$32,489, PF 1.34, Sharpe 1.69, Calmar 0.75, MaxDD 12.6% | +$10,807, PF 1.81, Sharpe 2.84, Calmar 2.12, MaxDD 11.0% | Mixed; improves 2025 net/PF but not baseline. |
| `ema_proximity_pct=0.007` | not rerun baseline | +$5,126, PF 1.36, Sharpe 1.81, Calmar 1.10, MaxDD 10.1% | Reject. |
| `resume_volume_surge_mult=1.1` | not rerun baseline | +$7,907, PF 1.56, Sharpe 2.20, Calmar 1.25, MaxDD 13.7% | Reject. |
| `resume_volume_surge_mult=1.5` | not rerun baseline | +$5,425, PF 1.38, Sharpe 1.91, Calmar 0.98, MaxDD 11.9% | Reject. |
| `near_hod_lod_pct=0.02/0.04` | not rerun baseline | unchanged | No effect in this futures path; scanner-level inherited filter is not the active lever. |
| `nkd_ema=20` | not rerun baseline | +$9,400, PF 1.70, Sharpe 3.01, Calmar 1.82, MaxDD 11.2% | Tiny net change, worse Calmar; not first priority. |
| `nkd_mult=3.0` | not rerun baseline | unchanged | No useful signal in this pass. |

`max_hold_days=3` additional windows:

| Window | `max_hold=3` | Current | Read |
|---|---:|---:|---|
| floor | +$35,053, PF 1.36, Sharpe 1.74, Calmar 0.78, MaxDD 13.0% | +$35,930, Calmar 0.64, MaxDD 16.2% | Lower net, better Calmar/DD. |
| vault2324 | +$19,579, PF 1.91, Sharpe 3.44, Calmar 1.89, MaxDD 10.7% | +$23,256, Calmar 2.70, MaxDD 8.9% | Hurts strongest vault window. |
| vault2026 | +$7,376, PF 1.61, Sharpe 2.74, Calmar 2.94, MaxDD 9.1% | +$6,747, Calmar 1.62, MaxDD 15.0% | Improves current sample. |

Interpretation:

- The most promising inherited parameter to change is `max_hold_days`, especially testing `3` vs `5`.
- `max_hold=3` reduces tail/DD in several windows but gives up a lot in 2023-2024, so this must be WFO-selected, not hand-picked.
- Signal loosen/tighten parameters did not show broad improvement.
- `short_weak_combo` is a useful warning: single-window 2025 improvement can be misleading.

Interpretation:

- Deploy-level result is positive if the Stress cap is widened enough for trades to pass.
- `breadth3` looks better than `wide_range3` at deploy level, despite being rougher in trade-level 2020.
- The Stress sleeve appears to reduce account MaxDD in baseline/floor, not merely add PnL.
- 2023-2024 and 2026 have little/no accepted Stress activity in these windows; that is expected because Stress events are sparse.
- This is still not promotion-ready. It implies the next research question is not "does Stress have edge?" but "what is the right Stress cluster risk budget, and can live timing/broker netting support same-symbol stress positions safely?"

### Stress sleeve validation pass 1 - standalone event/risk check

Artifact: `scratch/stress_sleeve_validation.py`.

Purpose:

- Validate the current Stress hedge by itself before deeper 3-regime portfolio work.
- Base candidate: Stress only, full 10:15-10:19 5-minute confirmation, enter SHORT at/after 10:20, `breadth3`, MNQ/MES, 2R target, stop at 09:45-10:15 swing high plus 0.1%, exit by 14:00.
- Fill/timing audit: no entry before confirmed signal, no same-bar exit, no exit outside selected bar.

Standalone results:

| Window | Variant | Trades | Net | PF | Sharpe | Calmar | MaxDD | Read |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 2018-2024 floor | `breadth3_mnq_mes` | 84 | +$2,749 | 1.49 | 2.57 | 0.26 | $2,188 / 4.4% | Positive but event-concentrated. |
| 2018-2024 floor | `wide3_mnq_mes` | 61 | +$2,588 | 1.60 | 3.12 | 0.28 | $2,000 / 4.0% | Cleaner PF/Sharpe, fewer trades. |
| 2018-2024 floor | `breadth3_all4` | 160 | +$3,397 | 1.40 | 2.24 | 0.19 | $3,682 / 7.4% | More net, worse quality/DD. |
| 2018-2024 floor | `breadth3_mnq` | 41 | +$2,042 | 1.66 | 3.28 | 0.40 | $1,080 / 2.2% | MNQ is strongest leg. |
| 2018-2024 floor | `breadth3_mes` | 43 | +$707 | 1.28 | 1.62 | 0.12 | $1,205 / 2.4% | MES weaker. |
| 2018-2024 floor | `rr25` | 84 | +$3,697 | 1.66 | 3.21 | 0.37 | $2,086 / 4.2% | Best IS sensitivity, not OOS-selected. |
| 2018-2024 floor | `delay1025` | 82 | +$2,798 | 1.51 | 2.77 | 0.34 | $1,727 / 3.5% | Delay is viable and lowers DD. |
| vault2025 | `breadth3_mnq_mes` | 19 | +$4,095 | 7.10 | 10.53 | 54.09 | $658 / 1.3% | Very strong OOS event sample. |
| vault2025 | `wide3_mnq_mes` | 15 | +$3,622 | 10.67 | 11.39 | 89.15 | $362 / 0.7% | Cleaner but fewer trades. |
| vault2025 | `exit1555` | 19 | +$4,875 | 7.43 | 10.54 | 87.35 | $485 / 1.0% | More net in 2025; needs IS/OOS discipline. |
| vault2324 | base | 0 | $0 | n/a | n/a | n/a | n/a | No Stress trades. |
| vault2026 to 2026-08-19 | base | 0 | $0 | n/a | n/a | n/a | n/a | No Stress trades; 2026 cannot validate this sleeve. |

Base stability:

| Check | Result | Read |
|---|---|---|
| Fill/timing audit | floor/2025/2026 all `outside_exit_bar=0`, `signal_after_entry=0`, `same_bar_exit=0` | No repeat of the prior impossible-fill issue. |
| Floor year split | 2018 -$444; 2019 -$250; 2020 -$537; 2022 +$3,979 | Stress base is mostly a 2022 liquidation hedge, not broadly stable across Stress years. |
| 2025 | +$4,095 on 19 trades | Strong OOS, but small event sample. |
| 2023-2024 / 2026 | 0 trades | This hedge sleeps outside recognized liquidation stress. |
| Instrument split | floor MNQ +$2,042 PF 1.66; MES +$707 PF 1.28 | MNQ carries most quality. |
| MAE/MFE | floor median MAE -0.15 ATR, p05 -0.44 ATR; median MFE +0.21 ATR, p95 +0.70 ATR | Stop geometry is not wildly loose; event path is quick. |
| Bootstrap | floor trade P(net>0)=0.911, daily P(net>0)=0.856; daily 5% net -$1,365 | Tail is still negative because the sample is sparse and event-dependent. |
| Cap proxy | Using 2.5x daily ATR admission risk: 2.5% cap admits 20 trades and loses -$240; 7.5% admits 76 and nets +$1,487; 10% admits 83 and nets +$2,871 | Tight inherited stress cap suppresses/warps this sleeve; 7.5% is a minimum research cap, not final proof. |

Interpretation:

- Stress is not a robust standalone alpha sleeve. It is a sparse liquidation hedge with strong 2022 and 2025 behavior.
- The current base `breadth3` MNQ/MES survives fill/timing audit and has positive IS/OOS point estimates, but floor edge is dominated by 2022.
- `wide_range3` is cleaner but smaller. `rr25`, `exit1555`, and `delay1025` are promising sensitivities, but should not be selected from these outputs without a Stress-specific WFO/event protocol.
- The cap question is real: low caps reject exactly the trades needed for the hedge to matter.
- 2026 is not evidence for or against Stress because there were no accepted Stress events through 2026-08-19.

Verdict: keep Stress as a research hedge candidate, not a standalone deploy-ready sleeve. Next Stress work should be event-based WFO/holdout over crisis windows, cap policy under portfolio breaker, and live timing/broker netting validation for same-symbol positions.

### Calm excavation prompt

Prompt saved at `docs/futures/CALM_STRATEGY_EXCAVATION_PROMPT.md`.

## Calm status

Current TF form also does not work in Calm.

Measured attempts:

- Calm-only Normal candidate: negative across baseline/vault windows.
- Calm+Normal diluted recent performance and hurt 2026.
- Calm LONG-only had weak positive drift in some windows but not deployable.
- Calm SHORT-only was toxic.
- Calm mean-reversion probes showed variance ratio near random, not a strong edge.
- Calm overnight long close-to-next-open had weak/no robust edge.

Interpretation:

- Calm probably needs a separate low-vol mean-reversion or gap-fill model.
- Do not reuse TF pullback logic in Calm unless a new independent fill-audited test proves it.

Candidate families to excavate:

- Intraday VWAP fade with strict volatility cap.
- Gap-fill after modest gap down/up with SPY VWAP confirmation.
- Previous-day range fade with time stop.
- Overnight drift only with market filter and tight event exclusions.

### Calm excavation pass 1 - futures 1m, fill-audited

Artifact: `scratch/regime_strategy_excavation.py`.

Data/test is the same as Stress pass 1. Fill audit passed with `outside_exit_bar=0`.

Tested families:

1. `calm_vwap_fade`
   - After 10:30, fade price back to session VWAP when it is far from VWAP.
   - Stop/threshold based on morning range.
   - Exit by target/stop/time before 15:30.
2. `calm_gap_fill`
   - Modest overnight/RTH gap fill attempt.
   - In this futures setup it produced no meaningful candidate set in the first pass.

Results for `calm_vwap_fade`:

| Variant | Trades | Net | PF | Exp/trade | Fill audit |
|---|---:|---:|---:|---:|---:|
| threshold 0.35 morning range, stop 0.35 | 3,144 | -$9,998 | 0.84 | -$3.18 | 0 |
| threshold 0.50 morning range, stop 0.35 | 2,879 | -$12,716 | 0.79 | -$4.42 | 0 |

Base variant by year:

- 2018 -$2,180
- 2019 -$1,762
- 2020 -$1,110
- 2021 -$2,664
- 2022 +$381
- 2023 -$250
- 2024 -$2,413

Interpretation:

- Calm futures VWAP fade is not promising in this form.
- Widening the trigger did not help.
- Losses are broad across instruments and years, not one bad pocket.
- Next Calm path should not be generic VWAP fade on index futures. More plausible: event-excluded overnight/gap behavior or stock-specific idiosyncratic mean reversion, but that needs current stock cache and the same fill audit.

### Calm excavation pass 2 - no IS survivor

Artifact: `scratch/calm_strategy_excavation.py`.

Data/test:

- IS window: 2018-01-01 through 2024-12-31.
- Data: `data/cache/futures/frozen_sim`.
- Regime labels: `futures._validated_core.label_regimes` using `spy_daily_live.csv`.
- HMM train end: 2018-01-01.
- HMM fit end for IS: 2022-12-31.
- Cost: 2 ticks/side.
- Fill law: signal and execution separated; close-based signals enter on the next later bar open; stop/target exits use first later 1m crossing bar; gap-through exits fill at feasible bar open.
- Fill audit: `outside_exit_bar=0`.

Tested families:

1. Opening-range fade after 10:00 or 10:30 with range caps.
2. Previous-day high/low failure fade with SPY D-1 RV20 cap.
3. Modest futures gap-fill, 0.25%-1.0% RTH gap, after partial reclaim/failure.
4. Session-boundary drift, close-to-next-open and open-to-midday. Event filtering is marked missing.
5. MNQ/MES relative-value dispersion. Pair PnL is explicit: one MNQ leg plus one MES leg, no single-leg PnL mixed into pair logic.

Family-level IS results:

| Family | Trades | Net | Read |
|---|---:|---:|---|
| Opening-range fade | 473 | -$1,746 | Reject: low count in stricter variants; broad negative expectancy. |
| Previous-day range fade | 2,572 | -$7,979 | Reject: both RV caps negative across most years. |
| Modest gap-fill | 768 | +$1,906 | Near-miss, but weak before 2021 and not robust enough. |
| Session drift | 11,528 | -$37,995 | Reject; unfiltered drift is mostly cost/drag. |
| MNQ/MES pair dispersion | 142 | -$3,295 | Reject; explicit pair logic is negative. |

Modest gap-fill details:

| Slice | Trades | Net |
|---|---:|---:|
| All instruments/directions | 768 | +$1,906 |
| MES long | 70 | +$422 |
| MES short | 103 | +$561 |
| MNQ long | 91 | +$1,027 |
| MNQ short | 126 | +$772 |
| MYM total | 148 | -$443 |
| M2K total | 230 | -$435 |

MES+MNQ gap-fill by year:

| Year | Trades | Net |
|---|---:|---:|
| 2018 | 57 | -$124 |
| 2019 | 69 | -$20 |
| 2020 | 39 | -$495 |
| 2021 | 72 | +$1,232 |
| 2022 | 4 | +$95 |
| 2023 | 73 | +$1,497 |
| 2024 | 76 | +$595 |

Interpretation:

- No candidate was selected before touching 2025, so the 2025 OOS and 2026 sanity stages were intentionally not run.
- The modest gap-fill pocket is the only thing worth remembering, but it depends on excluding MYM/M2K and is negative in 2018-2020.
- The edge is too concentrated in 2021/2023 to count as a Calm complement to the current Normal+Stress system.

Verdict: keep digging. No deploy-level Calm candidate from this pass.

### Calm overlay candidate - overnight negative fade to noon

Artifact: `scratch/calm_candidate_deploy_probe.py`.

Candidate:

- Variant: `on_neg_fade_to_noon_mod001_008`.
- Regime: Calm only.
- Instruments: MES, MNQ, MYM.
- Direction: LONG.
- Signal: completed overnight return known at RTH open.
- Filter: overnight return in `(-0.8%, -0.1%]`.
- Entry: RTH open.
- Exit: 12:00 bar open, not close.
- Cost: 2 ticks/side.
- Fill audit: `calm_outside_exit_bar=0`.

Combined setup:

- Normal core: Normal-only TF, EMA50, 2x daily ATR stop, corrected/live fill, SHORT only below SPY SMA50 D-1.
- Stress hedge: liquidation1020 `breadth3`, MNQ/MES, stress cap 7.5%.
- NKD included.
- Calm risk proxy for cap: 1x daily ATR. Note this is a proxy because this Calm candidate has no explicit stop.

Main deploy-level result, Calm own cluster cap 2.5%:

| Window | Normal | Normal + Stress | + Calm Own Cap | Calm Delta | Calm Trades | Fill Audit |
|---|---:|---:|---:|---:|---:|---:|
| floor 2018-2024 | +$33,181, PF 1.36, Calmar 0.52, MaxDD 18.5% | +$35,930, PF 1.38, Calmar 0.64, MaxDD 16.2% | +$44,458, PF 1.39, Calmar 0.80, MaxDD 16.0% | +$8,528, Calmar +0.15, MaxDD -0.2pp | 685/685 taken | 0 |
| vault2025 | +$6,857, PF 1.51, Calmar 1.47, MaxDD 10.1% | +$9,364, PF 1.70, Calmar 2.01, MaxDD 10.1% | +$10,013, PF 1.57, Calmar 2.13, MaxDD 10.1% | +$649, Calmar +0.12, MaxDD +0.0pp | 80/80 taken | 0 |
| vault2026 to 2026-08-19 | +$6,747, PF 1.46, Calmar 1.62, MaxDD 15.0% | +$6,747, PF 1.46, Calmar 1.62, MaxDD 15.0% | +$7,641, PF 1.40, Calmar 1.69, MaxDD 14.8% | +$895, Calmar +0.06, MaxDD -0.2pp | 54/56 taken | 0 |

Yearly PnL for `+ Calm Own Cap`, floor 2018-2024:

| Year | Net |
|---|---:|
| 2018 | +$2,359 |
| 2019 | +$4,738 |
| 2020 | +$2,666 |
| 2021 | +$5,044 |
| 2022 | +$1,669 |
| 2023 | +$18,369 |
| 2024 | +$9,613 |

Cap / existing-position interaction:

| Window | Scenario | Net | Calm Taken/Rejected | Overlap Count | Rejected With Existing Same Instrument |
|---|---|---:|---:|---:|---:|
| floor 2018-2024 | Calm shares `roska4_swing` cap | +$44,855 | 654 / 31 | 59 | 27 |
| floor 2018-2024 | Calm own 2.5% cap | +$44,458 | 685 / 0 | 59 | 0 |
| floor 2018-2024 | Calm relaxed cap | +$44,458 | 685 / 0 | 59 | 0 |
| vault2025 | Calm shares `roska4_swing` cap | +$10,584 | 75 / 5 | 4 | 3 |
| vault2025 | Calm own 2.5% cap | +$10,013 | 80 / 0 | 4 | 0 |
| vault2025 | Calm relaxed cap | +$10,013 | 80 / 0 | 4 | 0 |
| vault2026 | Calm shares `roska4_swing` cap | +$8,781 | 51 / 5 | 7 | 1 |
| vault2026 | Calm own 2.5% cap | +$7,641 | 54 / 2 | 7 | 0 |
| vault2026 | Calm relaxed cap | +$7,643 | 56 / 0 | 7 | 0 |

Interpretation:

- The Calm overlay passes fill feasibility in all completed runs.
- With its own 2.5% Calm cap, the overlay improves floor, 2025, and 2026 without increasing MaxDD materially.
- Relaxing the Calm cap adds little versus a 2.5% own cap, so the candidate is not mainly cap-suppressed.
- Sharing the swing cap can perform better in 2025/2026 because it accidentally filters some Calm trades, but it also mixes Calm admission with Normal positions and is harder to reason about.
- Edge is not exclusively 2023/2024: 2019/2020/2021/2022 are positive in the floor yearly split, but 2023-2024 still contribute a large share of total PnL.
- Current verdict: superseded by `on_neg_fade_mod001_010_x1555`. Keep this noon variant only as a fallback/reference because the 15:55 extension has materially better IS, 2025 OOS, and 2026 sanity results with the same fill-feasibility discipline.

Backup variant:

- `on_neg_fade_to_noon_mod002_008`, overnight return in `(-0.8%, -0.2%]`.
- Completed OOS checks:
  - vault2025 own cap: +$9,961, PF 1.62, Calmar 2.13, MaxDD 10.1%, 50/50 Calm taken, audit 0.
  - vault2026 own cap: +$7,674, PF 1.42, Calmar 1.76, MaxDD 14.4%, 39/41 Calm taken, audit 0.
- The cleaner variant is similar/better in 2026 but slightly less net in 2025. Floor rerun exited early before printing; rerun before preferring it.

### Calm excavation pass 3 - drift/continuation, not mean reversion

Artifact: `scratch/calm_drift_excavation.py`.

Reason for this pass:

- Calm should not be limited to mean-reversion.
- The new hurdle is larger PnL/capacity, not merely a tiny clean pocket.
- Because prior broad overnight tests were weak, this pass first isolates the strongest observed pocket: MNQ Calm overnight/risk-on drift.

Data/test:

- IS window: 2018-01-01 through 2024-12-31.
- Data: `data/cache/futures/frozen_sim`.
- Regime labels: `futures._validated_core.label_regimes` using `spy_daily_live.csv`.
- HMM fit end for IS: 2022-12-31.
- Cost: 2 ticks/side.
- Fill audit: `outside_exit_bar=0`.

MNQ-only IS results:

| Variant | Rule | Trades | Net | PF | Years + | Read |
|---|---|---:|---:|---:|---:|---|
| `on_long_rth_up` | Calm day RTH up, hold long close-to-next-open | 437 | +$5,284 | 1.29 | 6/7 | Large enough to test OOS, but one-instrument. |
| `on_long_all` | All Calm days, hold long close-to-next-open | 796 | +$4,075 | 1.10 | 5/7 | Too broad/weak; 2024-heavy. |
| `on_long_close_top40` | Calm day closes in top 40% of range, hold long overnight | 416 | +$3,465 | 1.19 | 6/7 | Cleaner than all-days but smaller. |
| `on_neg_fade_to_noon` | Fade negative overnight into noon | 342 | +$2,013 | 1.11 | 5/7 | Too small for the new PnL hurdle. |

OOS/sanity:

| Variant | 2025 OOS | 2026 to 2026-08-19 | Verdict |
|---|---:|---:|---|
| `on_long_rth_up` | 65 trades, +$968, PF 1.19 | 32 trades, -$2,847, PF 0.54 | Reject |
| `on_long_all` | 111 trades, +$3,320, PF 1.36 | 63 trades, -$1,949, PF 0.84 | Reject |
| `on_long_close_top40` | 62 trades, +$706, PF 1.14 | 33 trades, -$1,956, PF 0.64 | Reject |

Interpretation:

- MNQ Calm overnight/risk-on drift is the first Calm direction with IS PnL above roughly +$5k at 1 micro.
- It is not robust enough: 2025 confirms, but 2026 breaks hard across sibling variants.
- The failure is not specific to one filter; `all`, `RTH up`, and `close top 40%` all lose materially in 2026.
- Do not promote MNQ overnight Calm drift without a structural 2026-aware risk filter that can be selected without looking at 2026.

Verdict: reject current MNQ overnight drift candidates; keep digging for larger Calm PnL.

### Calm excavation pass 4 - negative-overnight fade to noon

Artifact: `scratch/calm_drift_excavation.py`.

Reason for this pass:

- The prior MNQ overnight LONG drift had enough IS PnL but failed badly in 2026.
- Instead of forcing Calm into mean-reversion, this pass tests session-boundary continuation/reversal mechanisms.
- The candidate that survived is a **RTH fade after negative overnight**, not a generic VWAP fade:
  - Calm regime only.
  - If the instrument's overnight return into the RTH open is negative, go LONG at the RTH open.
  - Exit at the scheduled noon bar open.
  - Instruments: MES/MNQ/MYM. M2K excluded because it was negative in IS and did not add meaningful OOS benefit.

Fill/execution notes:

- Signal is known before the RTH open from the completed overnight/premarket move.
- Entry uses the RTH open.
- Time exit uses the noon bar open, not the noon close.
- No stop/target is used in this trade-level probe.
- Fill audit: `outside_exit_bar=0`.

Trade-level results, 1 micro each, 2 ticks/side:

| Window | Trades | Net | PF | Exp/trade | Verdict |
|---|---:|---:|---:|---:|---|
| 2018-2024 IS | 1,036 | +$6,869 | 1.21 | +$6.63 | Pass trade-level |
| 2025 OOS | 134 | +$1,680 | 1.24 | +$12.54 | Pass |
| 2026 to 2026-08-19 | 76 | +$1,332 | 1.19 | +$17.53 | Pass sanity |

IS by instrument:

| Instrument | Trades | Net | PF |
|---|---:|---:|---:|
| MES | 332 | +$2,632 | 1.36 |
| MNQ | 342 | +$2,220 | 1.12 |
| MYM | 362 | +$2,017 | 1.26 |

OOS/sanity by instrument:

| Window | MES | MNQ | MYM |
|---|---:|---:|---:|
| 2025 | +$417 | +$783 | +$480 |
| 2026 to 2026-08-19 | +$86 | +$1,207 | +$39 |

IS by year:

| Year | Trades | Net |
|---|---:|---:|
| 2018 | 186 | -$691 |
| 2019 | 192 | +$197 |
| 2020 | 95 | +$1,577 |
| 2021 | 186 | -$13 |
| 2022 | 6 | +$293 |
| 2023 | 164 | +$4,082 |
| 2024 | 207 | +$1,423 |

Interpretation:

- This is the first Calm candidate in the pass with both meaningful IS PnL and positive 2025/2026 checks.
- It is not a tiny gap-fill pocket: trade count is about 1,000 in IS and PnL is about +$6.9k at 1 micro.
- It is not one-instrument only: MES, MNQ, and MYM are all positive in IS and OOS.
- Weakness: 2023 contributes most of the IS PnL, and 2018 is negative. This needs deploy-level integration and a drawdown/correlation check before any promotion.
- The mechanism is plausible: in Calm, a negative overnight into RTH appears to mean-revert during the morning on the liquid index futures, while positive overnight continuation/fade variants did not survive as well.

Verdict: deploy-level candidate, trade-level only. Next step is scratch integration against the current Normal + Stress research system with cap/breaker accounting.

### Calm excavation pass 5 - refine negative-overnight fade

Artifact: `scratch/calm_drift_excavation.py`.

Refinement:

- The raw `on_neg_fade_to_noon` candidate was positive, but the tiny negative overnight moves carried almost no edge.
- Keep the same mechanism and instruments, but require the completed overnight return to be moderately negative:
  - Variant A: `-0.8% < overnight_ret <= -0.1%`.
  - Variant B: `-0.8% < overnight_ret <= -0.2%`.
- Same execution law: LONG at RTH open, exit at noon bar open.

Results, MES/MNQ/MYM, 1 micro each, 2 ticks/side:

| Variant | Window | Trades | Net | PF | Exp/trade |
|---|---|---:|---:|---:|---:|
| Raw negative overnight | 2018-2024 IS | 1,036 | +$6,869 | 1.21 | +$6.63 |
| Moderate `[-0.8%, -0.1%]` | 2018-2024 IS | 685 | +$8,528 | 1.42 | +$12.45 |
| Moderate `[-0.8%, -0.2%]` | 2018-2024 IS | 442 | +$7,510 | 1.56 | +$16.99 |
| Moderate `[-0.8%, -0.1%]` | 2025 OOS | 80 | +$649 | 1.14 | +$8.11 |
| Moderate `[-0.8%, -0.2%]` | 2025 OOS | 50 | +$597 | 1.20 | +$11.94 |
| Moderate `[-0.8%, -0.1%]` | 2026 to 2026-08-19 | 56 | +$896 | 1.18 | +$16.01 |
| Moderate `[-0.8%, -0.2%]` | 2026 to 2026-08-19 | 41 | +$929 | 1.22 | +$22.66 |

IS year split for `[-0.8%, -0.2%]`:

| Year | Trades | Net |
|---|---:|---:|
| 2018 | 91 | +$205 |
| 2019 | 77 | +$733 |
| 2020 | 40 | +$520 |
| 2021 | 73 | +$411 |
| 2022 | 1 | +$117 |
| 2023 | 73 | +$3,019 |
| 2024 | 87 | +$2,503 |

Instrument split for `[-0.8%, -0.2%]`:

| Window | MES | MNQ | MYM |
|---|---:|---:|---:|
| 2018-2024 IS | +$1,708 | +$4,490 | +$1,312 |
| 2025 OOS | +$181 | +$151 | +$264 |
| 2026 to 2026-08-19 | -$131 | +$802 | +$258 |

Interpretation:

- This is cleaner than the raw version: higher PF, higher expectancy, and all IS years positive.
- The cost is fewer trades and smaller 2025 OOS dollars.
- The `[-0.8%, -0.2%]` version is the preferred trade-level candidate because it removes tiny overnight noise and keeps 2025/2026 positive.
- Still not live-ready: it needs deploy-level integration, correlation with Normal+Stress, and a check that 2023/2024 concentration does not dominate portfolio-level behavior.

Verdict: keep as the current best Calm trade-level candidate; next step is deploy-level scratch integration.

### Calm deploy-level scratch integration - negative overnight fade

Artifact: `scratch/calm_candidate_deploy_probe.py`.

Config:

- Normal core: Normal-only TF, EMA50, 2x daily ATR stop, corrected/live fill, SHORT only when SPY D-1 is below SMA50.
- Stress hedge: confirmed 10:20 liquidation short, `breadth3`, MNQ/MES.
- Calm overlay: `on_neg_fade_to_noon_mod001_008`, MES/MNQ/MYM, LONG at RTH open when completed overnight return is in `(-0.8%, -0.1%]`, exit at noon bar open.
- Calm deploy risk accounting: separate `roska4_calm` cluster, gross cap 5%, net cap 5%, risk proxy 1x daily ATR because this scratch overlay is a time-exit strategy with no production stop yet.
- Fill audit: `outside_exit_bar=0`.

Deploy-level results, $50k account, 1 micro, 2 ticks/side:

| Window | Portfolio | Net | PF | Calmar | MaxDD | Return/yr |
|---|---|---:|---:|---:|---:|---:|
| 2018-2024 IS floor | Normal | +$27,235 | 1.33 | 0.29 | 27.4% | 8.0% |
| 2018-2024 IS floor | Normal + Stress | +$27,656 | 1.33 | 0.30 | 26.5% | 8.0% |
| 2018-2024 IS floor | Normal + Stress + Calm | +$36,184 | 1.35 | 0.40 | 26.1% | 10.4% |
| 2025 OOS | Normal | +$3,168 | 1.25 | 0.71 | 9.7% | 6.9% |
| 2025 OOS | Normal + Stress | +$3,571 | 1.29 | 0.87 | 8.9% | 7.8% |
| 2025 OOS | Normal + Stress + Calm | +$4,219 | 1.25 | 0.97 | 9.3% | 9.0% |
| 2026 to 2026-08-19 | Normal | +$17 | 1.00 | 0.00 | 15.4% | 0.1% |
| 2026 to 2026-08-19 | Normal + Stress | +$17 | 1.00 | 0.00 | 15.4% | 0.1% |
| 2026 to 2026-08-19 | Normal + Stress + Calm | +$914 | 1.06 | 0.19 | 15.4% | 3.0% |

Incremental Calm contribution versus Normal + Stress:

| Window | Delta net | Delta Calmar | Delta MaxDD |
|---|---:|---:|---:|
| 2018-2024 IS floor | +$8,528 | +0.09 | -0.3 pp |
| 2025 OOS | +$649 | +0.09 | +0.5 pp |
| 2026 to 2026-08-19 | +$896 | +0.19 | +0.1 pp |

Calm fill/trade audit:

| Window | Calm trades | MES | MNQ | MYM | `outside_exit_bar` |
|---|---:|---:|---:|---:|---:|
| 2018-2024 IS floor | 685 | 216 | 230 | 239 | 0 |
| 2025 OOS | 80 | 23 | 29 | 28 | 0 |
| 2026 to 2026-08-19 | 56 | 18 | 17 | 21 | 0 |

IS yearly combined portfolio net:

| Year | Normal + Stress | Normal + Stress + Calm |
|---|---:|---:|
| 2018 | +$4,631 | +$4,905 |
| 2019 | +$4,301 | +$5,030 |
| 2020 | +$4,183 | +$4,962 |
| 2021 | +$3,367 | +$3,661 |
| 2022 | -$4,367 | -$4,263 |
| 2023 | +$11,297 | +$14,687 |
| 2024 | +$4,245 | +$7,201 |

Interpretation:

- Calm improves IS, 2025 OOS, and 2026 sanity without a meaningful MaxDD penalty in this scratch replay.
- The candidate does not rescue 2022, but it slightly reduces that drawdown year.
- 2023/2024 remain large contributors, so this is not yet production-ready.
- A production version needs an explicit live risk/stop policy; the scratch replay used a declared 1x daily ATR risk proxy for cluster admission.

Verdict: deploy-level candidate, but still scratch-only. Next work: test a nearby failed-continuation/reclaim entry and a compression-expansion Calm trend family before WFO.

### Calm excavation pass 9 - failed continuation, compression expansion, and exit extension

Artifacts:

- `scratch/calm_failed_overnight_continuation_probe.py`
- `scratch/calm_compression_expansion_probe.py`
- `scratch/calm_neg_overnight_exit_sweep.py`
- `scratch/calm_neg_overnight_risk_filter_probe.py`
- `scratch/calm_neg_overnight_wfo_stability.py`
- `scratch/calm_neg_overnight_mae_profile.py`

Failed overnight continuation / reclaim:

- Setup: after a moderately negative overnight, require early RTH continuation lower, then reclaim the RTH open; enter LONG on the next minute open.
- Tested fail windows 09:40/09:50/10:00, push thresholds 0.05%/0.10%/0.15%, exits 11:00/12:00/14:00.
- Full-basket aggregate from per-instrument runs had `outside_exit_bar=0`.

Best aggregate IS pockets:

| Variant | Trades | Net | PF | Pos years | Pos inst | Verdict |
|---|---:|---:|---:|---:|---:|---|
| `mod002_008 fail30 push0.0005 exit14:00` | 243 | +$3,212 | 1.36 | 6 | 3 | Too small |
| `mod002_008 fail10 push0.0005 exit14:00` | 173 | +$2,710 | 1.41 | 5 | 3 | Too few trades |
| `mod001_008 fail10 push0.0005 exit14:00` | 265 | +$2,196 | 1.22 | 6 | 3 | Too small |

Verdict: reject as a standalone candidate. It is directionally consistent with the negative-overnight effect, but delaying for reclaim gives up too much total PnL.

Compression expansion:

- Setup: previous RTH range is compressed; current Calm session breaks previous high/low in the first hour; enter 10:31 open; exit 14:00 or 15:55.
- Tested momentum and fade variants with previous-day range caps.
- Fill audit: `outside_exit_bar=0`.

Best IS pockets:

| Variant | Trades | Net | PF | Pos years | Pos inst | Verdict |
|---|---:|---:|---:|---:|---:|---|
| `prev0.012 short-break fade exit15:55` | 342 | +$3,160 | 1.29 | 4 | 3 | Too small / weak year split |
| `prev0.012 short-break fade drive0.001 exit15:55` | 268 | +$2,923 | 1.32 | 5 | 3 | Too few trades |
| `prev0.010 short-break fade exit15:55` | 307 | +$2,608 | 1.29 | 5 | 3 | Too small |

Verdict: reject as deploy candidate.

Negative overnight exit extension:

- Setup: same robust mechanism as the current Calm candidate, but coarse-sweep the time exit through 10:00/10:30/11:00/12:00/13:00/14:00/15:55.
- Candidate selected before touching 2025: `on_neg_fade_mod001_010_x1555`.
- Rule: Calm only, MES/MNQ/MYM, completed overnight return in `(-1.0%, -0.1%]`, LONG at RTH open, exit at 15:55 bar open.
- Fill audit: `outside_exit_bar=0`.

Trade-level results:

| Window | Trades | Net | PF | Exp/trade |
|---|---:|---:|---:|---:|
| 2018-2024 IS | 699 | +$14,850 | 1.60 | +$21.25 |
| 2025 OOS | 87 | +$2,736 | 1.54 | +$31.45 |
| 2026 to 2026-08-19 | 63 | +$2,634 | 1.58 | +$41.82 |

IS by instrument:

| Instrument | Trades | Net | PF |
|---|---:|---:|---:|
| MES | 220 | +$4,698 | 1.89 |
| MNQ | 236 | +$6,012 | 1.43 |
| MYM | 243 | +$4,140 | 1.77 |

IS by year:

| Year | Trades | Net |
|---|---:|---:|
| 2018 | 127 | +$2,276 |
| 2019 | 128 | +$3,424 |
| 2020 | 63 | +$478 |
| 2021 | 121 | +$2,960 |
| 2022 | 2 | +$171 |
| 2023 | 118 | +$3,766 |
| 2024 | 140 | +$1,776 |

Deploy-level scratch results for `on_neg_fade_mod001_010_x1555`:

- Artifact: `scratch/calm_candidate_deploy_probe.py`.
- Config: Normal-only TF, EMA50, 2x daily ATR stop, corrected/live fill, SHORT only below SPY SMA50 D-1; Stress 10:20 liquidation short on MNQ/MES with breadth/range filters and 7.5% stress cap; Calm own sleeve uses MES/MNQ/MYM, LONG RTH open to 15:55 bar open, overnight return in `(-1.0%, -0.1%]`, 2 ticks/side, 1x daily ATR admission risk proxy. NKD remains in the Normal basket.
- Feasibility: entry timestamp equals RTH-open signal timestamp; exit is later 15:55 bar open; `calm_outside_exit_bar=0` in every run.

| Window | Portfolio | Net | PF | Sharpe | Calmar | MaxDD $ | MaxDD % | Return/yr |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2018-2024 IS floor | Normal | +$33,181 | 1.36 | 1.73 | 0.52 | $9,259 | 18.5% | 9.7% |
| 2018-2024 IS floor | Normal + Stress | +$35,930 | 1.38 | 1.78 | 0.64 | $8,108 | 16.2% | 10.4% |
| 2018-2024 IS floor | Normal + Stress + Calm own cap | +$50,780 | 1.43 | 1.90 | 1.06 | $6,842 | 13.7% | 14.6% |
| 2025 OOS | Normal | +$6,857 | 1.51 | 2.33 | 1.47 | $5,025 | 10.1% | 14.8% |
| 2025 OOS | Normal + Stress | +$9,364 | 1.70 | 2.98 | 2.01 | $5,025 | 10.1% | 20.2% |
| 2025 OOS | Normal + Stress + Calm own cap | +$12,100 | 1.67 | 2.78 | 2.58 | $5,025 | 10.1% | 25.9% |
| 2026 to 2026-08-19 | Normal | +$6,747 | 1.46 | 2.43 | 1.62 | $7,517 | 15.0% | 24.4% |
| 2026 to 2026-08-19 | Normal + Stress | +$6,747 | 1.46 | 2.43 | 1.62 | $7,517 | 15.0% | 24.4% |
| 2026 to 2026-08-19 | Normal + Stress + Calm own cap | +$8,948 | 1.49 | 2.43 | 1.98 | $7,394 | 14.8% | 29.3% |

Incremental Calm contribution:

| Window | Delta net | Delta PF | Delta Sharpe | Delta Calmar | Delta MaxDD | Calm taken/rejected | Overlap |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2018-2024 IS floor | +$14,850 | +0.05 | +0.12 | +0.42 | -2.5 pp | 699 / 0 | 58 |
| 2025 OOS | +$2,736 | -0.03 | -0.20 | +0.57 | +0.0 pp | 87 / 0 | 4 |
| 2026 to 2026-08-19 | +$2,202 | +0.03 | +0.00 | +0.36 | -0.2 pp | 60 / 3 | 8 |

Cap comparison:

| Window | Calm swing cap | Calm own cap | Calm relaxed cap | Existing-position note |
|---|---:|---:|---:|---|
| 2018-2024 IS floor | +$51,395, 670/29 | +$50,780, 699/0 | +$50,780, 699/0 | Sharing R4 swing cap rejects 26 Calm trades due existing positions yet slightly improves net. |
| 2025 OOS | +$12,585, 82/5 | +$12,100, 87/0 | +$12,100, 87/0 | Swing cap rejects 3 due existing positions and happens to improve net in this sample. |
| 2026 to 2026-08-19 | +$8,997, 58/5 | +$8,948, 60/3 | +$9,381, 63/0 | Own 2.5% Calm cap rejects 3 trades; relaxed cap captures the full trade-level +$2,634 increment. |

Interpretation:

- Exit extension to 15:55 roughly doubles the trade-level PnL versus the noon candidate while keeping 2025 and 2026 positive in the deploy pipeline.
- Unlike the delayed reclaim variant, entering at RTH open captures the full Calm reversal/relief path.
- All IS years are positive, all three instruments are positive, and OOS/sanity both improve portfolio-level results.
- Remaining concerns: this is a longer intraday hold and needs explicit live stop/risk policy before promotion; the 2026 own-cap run rejects 3 trades, so cap policy must be decided deliberately rather than inherited from the old engine.

Verdict: preferred Calm deploy-level candidate, scratch-only. It supersedes the noon Calm candidate, passes feasibility, and improves IS, 2025 OOS, and 2026 sanity, but promotion requires live-risk/stop design plus cap-policy validation.

### Calm excavation pass 10 - targeted risk/filter variants

Artifact: `scratch/calm_neg_overnight_risk_filter_probe.py`.

Purpose:

- Test targeted variants around the current preferred mechanism, not broad new strategy families.
- Candidate base: `mod001_010`, Calm only, MES/MNQ/MYM, overnight return in `(-1.0%, -0.1%]`, LONG RTH open to 15:55 open.
- Variants tested: normalized `50/50` noon/15:55 split, `0.75x` and `1.0x` daily ATR stops, SPY D-1 `rv20 <= 20%`, SPY above SMA50, SPY below SMA50.
- Local macro/event calendar: missing; event filtering remains unavailable.
- Fill audit: `outside_exit_bar=0`.

IS aggregate, 2018-2024, MES/MNQ/MYM:

| Variant | Trades | Net | PF | Pos years | Pos inst | Interpretation |
|---|---:|---:|---:|---:|---:|---|
| Base no-stop x15:55 | 699 | +$14,850 | 1.60 | 7 | 3 | Best |
| RV20 <= 20%, no-stop x15:55 | 683 | +$14,202 | 1.59 | 6 | 3 | Slightly lower; no OOS benefit |
| SPY above SMA50, no-stop x15:55 | 655 | +$12,648 | 1.55 | 6 | 3 | Lower PnL |
| 1.0x ATR stop x15:55 | 699 | +$12,218 | 1.45 | 7 | 3 | Cuts too much edge |
| 50/50 noon/15:55 split | 699 | +$11,294 | 1.53 | 7 | 3 | Risk compromise, lower edge |
| 0.75x ATR stop x15:55 | 699 | +$10,541 | 1.37 | 7 | 3 | Too tight |

OOS/sanity checks:

| Variant | 2025 Net | 2025 PF | 2026 Net | 2026 PF | Notes |
|---|---:|---:|---:|---:|---|
| Base no-stop x15:55 | +$2,736 | 1.54 | +$2,634 | 1.58 | Preferred |
| RV20 <= 20%, no-stop x15:55 | +$2,736 | 1.54 | +$2,634 | 1.58 | Same trades as base in OOS/sanity |
| 50/50 noon/15:55 split | +$1,871 | 1.40 | +$1,645 | 1.34 | Lower but still positive |
| 1.0x ATR stop x15:55 | +$1,909 | 1.32 | +$819 | 1.13 | Stop cuts winners / weak 2026 |
| 0.75x ATR stop x15:55 | +$2,579 | 1.49 | +$803 | 1.13 | Better 2025, weak 2026 |

Stop-path detail:

- 2025 `1.0x ATR`: 7 stop exits produced -$3,042; remaining time exits produced +$4,951.
- 2026 `1.0x ATR`: 4 stop exits produced -$2,703; remaining time exits produced +$3,523.
- 2026 `0.75x ATR`: 8 stop exits produced -$3,035; remaining time exits produced +$3,837.

Interpretation:

- The base no-stop/time-exit version remains strongest by IS, 2025, and 2026.
- RV20 filter is not useful; it trims a few IS trades and trims no OOS/sanity trades.
- SPY D-1 trend filters reduce PnL and do not justify the added complexity.
- Naive `0.75x-1.0x` daily ATR stops reduce total edge materially and hurt 2026.
- Partial noon/15:55 split remains a possible psychological/risk compromise, but it is not a stronger candidate.

Verdict: no replacement found. Keep `on_neg_fade_mod001_010_x1555` as preferred Calm candidate; continue with WFO/stability and smarter live risk design rather than hard ATR stops from this quick pass.

### Calm validation pass 11 - WFO/stability across negative-overnight variants

Artifact: `scratch/calm_neg_overnight_wfo_stability.py`.

Purpose:

- Run a coarse WFO/stability check without dense optimization.
- Compare only three predeclared x15:55 variants:
  - `raw`: any negative overnight.
  - `mod001_010`: overnight return in `(-1.0%, -0.1%]`.
  - `mod002_010`: overnight return in `(-1.0%, -0.2%]`.
- Use existing fill-audited trade CSVs; no new parquet scan is needed.
- Fill audit: `outside_exit_bar=0`.

Full 2018-2024 IS:

| Variant | Trades | Net | PF | MaxDD | Pos years | Pos inst | Top year share |
|---|---:|---:|---:|---:|---:|---:|---:|
| `raw_x1555` | 1,036 | +$15,205 | 1.38 | $2,216 | 7 | 3 | 0.37 |
| `mod001_010_x1555` | 699 | +$14,850 | 1.60 | $1,881 | 7 | 3 | 0.25 |
| `mod002_010_x1555` | 461 | +$14,383 | 1.94 | $1,739 | 7 | 3 | 0.29 |

Rolling coarse WFO:

| Train | Test | Selected by train | Test trades | Test net | Test PF | Notes |
|---|---|---|---:|---:|---:|---|
| 2018-2021 | 2022 | `mod001_010_x1555` | 2 | +$171 | 2.26 | 2022 has almost no Calm candidates |
| 2019-2022 | 2023 | `raw_x1555` | 159 | +$5,563 | 1.91 | Strong year for all variants |
| 2020-2023 | 2024 | `raw_x1555` | 207 | +$687 | 1.05 | Raw selection weak in 2024 |

Fixed-variant test-year observations:

- `mod001_010_x1555` test years:
  - 2022: +$171, PF 2.26, 2 trades.
  - 2023: +$3,766, PF 1.82, 118 trades.
  - 2024: +$1,776, PF 1.23, 140 trades.
- `mod002_010_x1555` test years:
  - 2022: +$306, 1 trade.
  - 2023: +$4,112, PF 2.48, 76 trades.
  - 2024: +$1,982, PF 1.40, 90 trades.
- `raw_x1555` has the highest IS and 2025 PnL, but its 2024 fold is weak: +$687, PF 1.05, with higher IS MaxDD.

Additional OOS/sanity for `mod002_010_x1555`:

| Window | Trades | Net | PF | Notes |
|---|---:|---:|---:|---|
| 2025 OOS | 57 | +$1,822 | 1.53 | Positive, less dollar PnL than `mod001_010` |
| 2026 to 2026-08-19 | 48 | +$2,410 | 1.59 | Positive and clean |

Interpretation:

- `raw_x1555` is tempting for dollars, especially 2025, but it is noisier and weak in the 2024 fold.
- `mod002_010_x1555` is the cleanest PF/MaxDD version, but has fewer trades and lower 2025 dollars.
- `mod001_010_x1555` remains the best balance: large enough trade count, strong PF, all IS years positive, good 2025/2026, and less noise than raw.

Verdict: keep `mod001_010_x1555` as preferred default; keep `mod002_010_x1555` as conservative backup for risk review. Do not promote `raw_x1555` as default despite higher dollars.

### Calm validation pass 12 - MAE/MFE live-risk profile

Artifact: `scratch/calm_neg_overnight_mae_profile.py`.

Purpose:

- Profile the adverse/favorable intraday path for the preferred Calm candidate.
- Candidate: `mod001_010_x1555`, MES/MNQ/MYM, Calm only, overnight return in `(-1.0%, -0.1%]`, LONG RTH open, exit 15:55 open.
- This is risk design only, not parameter optimization.
- Fill audit: `outside_exit_bar=0`.

MAE/MFE summary:

| Window | Trades | Net | PF | MAE p50 | MAE p75 | MAE p90 | MAE p95 | MAE ATR p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018-2024 IS | 699 | +$14,850 | 1.60 | $55 | $119 | $201 | $293 | 1.04 |
| 2025 OOS | 87 | +$2,736 | 1.54 | $90 | $178 | $339 | $508 | 1.10 |
| 2026 to 2026-08-19 | 63 | +$2,634 | 1.58 | $167 | $258 | $521 | $689 | 1.01 |

By-instrument MAE p95:

| Window | MES | MNQ | MYM |
|---|---:|---:|---:|
| 2018-2024 IS | 0.97 ATR / $205 | 1.22 ATR / $414 | 1.02 ATR / $165 |
| 2025 OOS | 1.07 ATR / $336 | 1.14 ATR / $728 | 0.97 ATR / $229 |
| 2026 to 2026-08-19 | 0.70 ATR / $267 | 1.11 ATR / $955 | 0.82 ATR / $243 |

Worst-path observations:

- The largest final losers are dominated by MNQ.
- 2026 MNQ has much larger dollar MAE because NQ volatility/price level is higher; e.g. 2026-01-29 had MNQ MAE about $1,195 / 1.46 ATR.
- A naive `0.75x-1.0x` daily ATR stop lands near the p75-p95 adverse path region, so it cuts a meaningful number of trades and explains why the stop pass reduced edge.

Risk design implication:

- Do not promote the naive `0.75x` or `1.0x` daily ATR hard stop as the default.
- A production version should prefer:
  - explicit Calm sleeve cap / relaxed cap decision,
  - account-level breaker interaction,
  - instrument-specific risk awareness, especially MNQ,
  - possible wide disaster stop above normal noise, likely wider than `1x` daily ATR or implemented as an account/sleeve kill switch rather than a tight trade stop.
- If a hard stop is required operationally, it should be treated as a disaster stop and validated separately; the quick pass shows tight ATR stops are too expensive.

Verdict: live-risk design should use cap and account/sleeve controls first; hard stop design remains unresolved and should not be fitted from this pass.

### Three-regime validation plan

Goal:

- Validate one combined deploy-level system: Normal TF core + Stress hedge + Calm overnight-fade overlay.
- Keep regime detection, signal generation, and execution feasibility separated.
- Do not promote any result unless all fills are feasible and signal timestamps are at or before entry timestamps.

Primary configuration to validate:

| Sleeve | Role | Current candidate | Main risk/cap question |
|---|---|---|---|
| Normal | Core return engine | Normal-only TF, EMA50, 2x daily ATR stop, corrected/live fills, SHORT only below SPY SMA50 D-1 | Does the old R4 swing cap remain optimal after adding Calm, or should Normal have a dedicated sleeve cap? |
| Stress | Crash/liquidation hedge | Confirmed 10:20 liquidation short, MNQ/MES, breadth/range filters, 7.5% stress cap | Is 7.5% stress cap robust, or is it too high for rare-event exposure and too dependent on 2022/2025-style paths? |
| Calm | Calm complement | `on_neg_fade_mod001_010_x1555`, MES/MNQ/MYM, LONG RTH open to 15:55 open, overnight return in `(-1.0%, -0.1%]` | Own 2.5% cap rejects trades in 2026; relaxed cap improves net, but live stop policy is still missing. |

Validation gates:

1. Fill and lookahead audit.
   - For every sleeve, print `outside_exit_bar`, entry-before-signal violations, same-bar stop/exit assumptions, and missing-bar fallbacks.
   - Calm must keep using 15:55 bar open, not close.
   - Stress confirmed 10:20 entry must use only information available at or before confirmation.

2. Sleeve-isolated metrics.
   - Measure each sleeve alone by year, instrument, regime, trade count, PF, Sharpe, Calmar, MaxDD $, MaxDD %, average trade, worst trade, and longest drawdown.
   - Run bootstrap on daily PnL and trade PnL for each sleeve, not only the combined portfolio.

3. Combined portfolio metrics.
   - Compare Normal, Normal + Stress, Normal + Calm, and Normal + Stress + Calm across 2018-2024, 2025 OOS, and 2026 sanity.
   - Report yearly net, monthly net, daily return distribution, tail days, overlap counts, rejected-by-cap counts, and exposure by sleeve/instrument.

4. Cap/risk grid, with strict no-optimization discipline.
   - Test coarse predeclared caps only: Normal swing cap, Stress cap, Calm own cap, Calm relaxed cap, and portfolio net cap.
   - Compare separate sleeve caps versus shared cap. Shared cap can improve historical PnL by filtering trades, but it may hide accidental selection bias.
   - For Calm, test 1x daily ATR risk proxy against explicit live stop candidates; do not trust a time-exit-only system for live promotion.

5. Parameter robustness.
   - Normal: EMA length, ATR stop multiple, max hold, short market filter, NKD inclusion, and daily ATR lookback.
   - Stress: confirmation time, breadth/range thresholds, entry delay, max hold/time exit, MNQ/MES weights, stress cap.
   - Calm: overnight return bounds, exit time, instrument set, RTH-open entry feasibility, stop/risk proxy, Calm cap.
   - Only use coarse grids and WFO-style selection; do not tune dense parameters on 2025/2026.

6. WFO and stability.
   - Use rolling train/test windows such as train 2018-2021 test 2022, train 2019-2022 test 2023, train 2020-2023 test 2024, then hold 2025/2026 untouched as final OOS/sanity.
   - Select parameters from train only, freeze them, then score test.
   - Reject if the combined edge depends mostly on 2023/2024 or if 2025/2026 gains vanish after cap/stop realism.

7. Live-readiness checklist.
   - Define production stop policy for Calm.
   - Define per-sleeve and portfolio caps in account-risk terms.
   - Confirm all instruments have reliable RTH open and 15:55 bars in live data.
   - Simulate order timing, slippage stress, missed bars, partial fills, and duplicate-signal prevention.
   - Run paper/live shadow before capital deployment.

### Three-regime combined pass 1 - selected Normal/Calm plus primary Stress

Artifact: `scratch/calm_candidate_deploy_probe.py`.

Selected sleeves:

| Sleeve | Selected config |
|---|---|
| Normal | Normal-only TF, EMA50, 2x daily ATR stop, corrected/live fill, fixed stop/no ratchet, SHORT only below SPY SMA50 D-1, NKD included, `max_hold_days=5`. |
| Stress | `breadth3_mnq_mes`, Stress only, full 10:15-10:19 5m confirmation, SHORT MNQ/MES at 10:20 1m open, per-symbol below VWAP/open gate, stop 09:45-10:15 swing high * 1.001, reject stop distance >1.5%, 2R target, time exit 14:00. |
| Calm | `on_neg_fade_mod001_010_x1555`, Calm only, MES/MNQ/MYM LONG RTH open when overnight return in `(-1.0%, -0.1%]`, exit 15:55 bar open, 1x daily ATR risk proxy, own 2.5% Calm cap. |

Primary combined results with Stress cap 7.5%:

| Window | Normal | Normal + Stress | Normal + Stress + Calm own cap | Stress taken/rejected | Calm taken/rejected | Fill/timing audit |
|---|---:|---:|---:|---:|---:|---|
| 2018-2024 floor | +$33,181, PF 1.36, Sharpe 1.73, Calmar 0.52, MaxDD 18.5% | +$35,930, PF 1.38, Sharpe 1.78, Calmar 0.64, MaxDD 16.2% | +$50,780, PF 1.43, Sharpe 1.90, Calmar 1.06, MaxDD 13.7% | 84 / 0 | 699 / 0 | Calm `outside_exit_bar=0`; Stress prior sleeve audit clean. |
| 2025 OOS | +$6,857, PF 1.51, Sharpe 2.33, Calmar 1.47, MaxDD 10.1% | +$9,364, PF 1.70, Sharpe 2.98, Calmar 2.01, MaxDD 10.1% | +$12,100, PF 1.67, Sharpe 2.78, Calmar 2.58, MaxDD 10.1% | 13 / 6 | 87 / 0 | Calm `outside_exit_bar=0`; Stress generated 19 trades. |
| 2026 to 2026-08-19 | +$6,747, PF 1.46, Sharpe 2.43, Calmar 1.62, MaxDD 15.0% | +$6,747, PF 1.46, Sharpe 2.43, Calmar 1.62, MaxDD 15.0% | +$8,948, PF 1.49, Sharpe 2.43, Calmar 1.98, MaxDD 14.8% | 0 / 0 | 60 / 3 | Calm `outside_exit_bar=0`; no Stress events. |

Yearly net, floor:

| Year | Normal | Normal + Stress | Normal + Stress + Calm own cap |
|---|---:|---:|---:|
| 2018 | +$2,529 | +$2,085 | +$4,361 |
| 2019 | +$4,259 | +$4,009 | +$7,433 |
| 2020 | +$2,423 | +$1,887 | +$2,364 |
| 2021 | +$4,749 | +$4,749 | +$7,709 |
| 2022 | -$2,415 | +$1,564 | +$1,735 |
| 2023 | +$14,978 | +$14,978 | +$18,745 |
| 2024 | +$6,657 | +$6,657 | +$8,433 |

Cap interaction:

- Stress cap 10% produced the same 2025/2026 deploy-level results as 7.5% in this combined harness.
- Therefore the 2025 Stress rejection count, 13 taken / 6 rejected out of 19 generated trades, is not solved by raising Stress gross cap from 7.5% to 10%.
- Next combined feasibility audit must inspect rejection reasons for those 6 Stress trades: likely overlap/same-symbol Normal positions, net cap, or account-level interaction.
- Calm own cap rejects 3 trades in 2026; relaxed Calm cap takes all 63 and lifts 2026 full-system net from +$8,948 to +$9,381 without worsening MaxDD in this sample. This remains a cap-policy question, not a signal rejection.

Verdict:

- The selected 3-regime system is coherent at scratch deploy level: Normal carries the base, Calm adds persistent OOS/sanity improvement, and Stress behaves as a sparse crisis hedge.
- This is not production-ready yet. The next gates are rejection-reason audit, combined bootstrap, production risk semantics, and live timing/netting design.

#### Combined strict fill/lookahead audit - 2026-08-21

Artifact: `scratch/calm_candidate_deploy_probe.py`.

Added audit rules:

- Signal availability: Stress signal bar 10:15-10:19 is treated as known only at 10:20; Calm completed overnight return is known at RTH open.
- Same/before-bar exit is rejected.
- Exit fill must be on a real bar: the recorded exit price must lie inside that bar's `[low, high]`.
- Calm time exit remains 15:55 bar open, not close.
- This audit is deliberately independent of PnL. If a trade fails fill feasibility, its PnL is not trusted.

Result:

| Window | Normal R4 exit audit | Stress audit | Calm audit | NKD audit |
|---|---|---|---|---|
| 2018-2024 floor | OK, 839 trades | OK, 84 trades | OK, 699 trades, `outside_exit_bar=0`, `signal_after_entry=0` | FAIL, 228 trades, `outside_exit_bar=3` |
| 2025 OOS | OK, 113 trades | OK, 19 trades | OK, 87 trades, `outside_exit_bar=0`, `signal_after_entry=0` | OK, 31 trades |
| 2026 to 2026-08-19 | OK, 88 trades | OK, 0 trades | OK, 63 trades, `outside_exit_bar=0`, `signal_after_entry=0` | FAIL, 26 trades, `outside_exit_bar=1` |

2026 NKD failing sample:

- `MNKD`, entry `2026-03-09 14:20 +09:00`, exit `2026-03-11 02:20 +09:00`, reason `CHANDELIER`, recorded exit `55738.57`.
- Actual 02:20 bar: open/high/low/close `55745/55780/55745/55745`.
- The recorded stop price is below the bar low, so that exit price did not trade in the recorded exit bar.

Interpretation:

- The selected R4 sleeves used for the 3-regime thesis are clean under this strict audit: Normal R4, Stress, and Calm have no detected lookahead/same-bar/exit-bar feasibility failures.
- The full reported combined system still includes NKD in the Normal basket. Because NKD has non-feasible stop exits in floor and 2026, full-system metrics including NKD are now conditional, not deploy-clean.
- `--exclude-nkd` rerun keeps only the clean R4 Normal sleeve plus Stress/Calm:

| Window | Normal R4 only | R4 Normal + Stress | R4 Normal + Stress + Calm own cap | Fill/lookahead audit |
|---|---:|---:|---:|---|
| 2018-2024 floor | +$29,278, PF 1.44, Sharpe 2.11, Calmar 0.38, MaxDD 22.7% | +$32,026, PF 1.45, Sharpe 2.13, Calmar 0.46, MaxDD 20.4% | +$46,877, PF 1.50, Sharpe 2.12, Calmar 0.74, MaxDD 18.2% | R4 Normal OK, Stress OK, Calm OK |
| 2025 OOS | +$4,654, PF 1.55, Sharpe 2.39, Calmar 1.64, MaxDD 6.2% | +$7,161, PF 1.85, Sharpe 3.32, Calmar 2.52, MaxDD 6.2% | +$9,897, PF 1.76, Sharpe 2.91, Calmar 3.43, MaxDD 6.2% | R4 Normal OK, Stress OK, Calm OK |
| 2026 to 2026-08-19 | +$736, PF 1.09, Sharpe 0.50, Calmar 0.21, MaxDD 12.7% | +$736, PF 1.09, Sharpe 0.50, Calmar 0.21, MaxDD 12.7% | +$2,938, PF 1.24, Sharpe 1.27, Calmar 0.74, MaxDD 13.1% | R4 Normal OK, Stress OK, Calm OK |

- Next gate: rebuild or exclude NKD with the same corrected/live stop-fill semantics before treating full combined metrics as final. The deploy-clean candidate set today is R4 Normal + Stress + Calm; the NKD diversifier remains useful but failed strict fill audit.

### Calm sleeve validation pass 1 - standalone risk/robustness

Artifact: `scratch/calm_sleeve_validation.py`.

Purpose:

- Validate the preferred Calm candidate by itself before deeper portfolio integration.
- Candidate remains `on_neg_fade_mod001_010_x1555`: Calm only, MES/MNQ/MYM, LONG RTH open, completed overnight return in `(-1.0%, -0.1%]`, exit at 15:55 bar open.
- This pass is sleeve-only: no Normal/Stress portfolio help, no shared cap selection.
- Fill audit remains mandatory: `outside_exit_bar=0`, `signal_after_entry=0`.

Standalone exit/stop/partial sensitivity:

| Window | Variant | Trades | Net | PF | Sharpe | Calmar | MaxDD | Note |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 2018-2024 floor | `x1200` | 706 | +$8,530 | 1.40 | 2.03 | 0.79 | $1,545 / 3.1% | Noon is viable but weaker. |
| 2018-2024 floor | `x1400` | 699 | +$9,576 | 1.39 | 1.93 | 0.68 | $2,023 / 4.0% | Weaker than 15:55. |
| 2018-2024 floor | `x1555` | 699 | +$14,850 | 1.60 | 2.81 | 1.13 | $1,881 / 3.8% | Best base variant. |
| 2018-2024 floor | `x1555_stop05` | 699 | +$9,532 | 1.34 | 1.90 | 0.69 | $1,983 / 4.0% | Tight stop gives up too much edge. |
| 2018-2024 floor | `x1555_stop075` | 699 | +$10,541 | 1.37 | 1.95 | 0.79 | $1,920 / 3.8% | Still materially weaker. |
| 2018-2024 floor | `x1555_stop10` | 699 | +$12,218 | 1.45 | 2.22 | 0.85 | $2,058 / 4.1% | Less bad, still below time exit. |
| 2018-2024 floor | `partial12_1555` | 699 | +$11,293 | 1.53 | 2.57 | 1.16 | $1,403 / 2.8% | Lower net, better DD/Calmar. |
| 2018-2024 floor | `partial14_1555` | 699 | +$12,213 | 1.51 | 2.46 | 0.96 | $1,822 / 3.6% | Middle ground. |
| 2025 OOS | `x1555` | 87 | +$2,736 | 1.54 | 2.52 | 1.41 | $2,074 / 4.1% | OOS positive. |
| 2025 OOS | `x1555_stop05` | 87 | +$2,316 | 1.44 | 2.40 | 1.47 | $1,683 / 3.4% | Tight stop still positive in 2025. |
| 2025 OOS | `partial12_1555` | 87 | +$1,871 | 1.40 | 1.91 | 0.95 | $2,107 / 4.2% | Partial reduces edge. |
| 2026 to 2026-08-19 | `x1555` | 63 | +$2,634 | 1.58 | 2.87 | 2.88 | $1,496 / 3.0% | Sanity positive. |
| 2026 to 2026-08-19 | `x1555_stop05` | 63 | -$714 | 0.91 | -0.65 | -0.33 | $3,561 / 7.1% | Tight disaster stop kills 2026. |
| 2026 to 2026-08-19 | `x1555_stop075` | 63 | +$1,257 | 1.21 | 1.27 | 0.82 | $2,506 / 5.0% | Positive but much weaker. |
| 2026 to 2026-08-19 | `partial12_1555` | 63 | +$1,645 | 1.34 | 1.88 | 1.35 | $1,998 / 4.0% | Lower net/Calmar than full 15:55. |

Stability:

| Check | Result | Read |
|---|---|---|
| Fill audit | floor/2025/2026 all `outside_exit_bar=0`, `signal_after_entry=0` | No repeat of the prior impossible-fill bug in this sleeve test. |
| IS year split | 2018 +$2,276; 2019 +$3,424; 2020 +$478; 2021 +$2,960; 2022 +$171 on 2 trades; 2023 +$3,766; 2024 +$1,776 | All years positive, but 2022 has almost no Calm sample. |
| IS instrument split | MES +$4,698 PF 1.89; MNQ +$6,012 PF 1.43; MYM +$4,140 PF 1.77 | Not one-instrument only. |
| 2025 instrument split | MES +$979; MNQ +$1,900; MYM -$142 | OOS MYM is weak/negative. |
| 2026 instrument split | MES +$311; MNQ +$1,897; MYM +$426 | MNQ carries most 2026 net. |
| Rough WFO by prior-year net | Prior years always select `x1555`; tests: 2021 +$2,960, 2022 +$171, 2023 +$3,766, 2024 +$1,776 | Crude fold stability supports 15:55. |
| MAE/MFE | IS median MAE -0.28 ATR, p05 MAE -1.04 ATR; median MFE +0.39 ATR, p95 MFE +1.06 ATR | A 0.5x ATR stop cuts into normal adverse excursion. |
| Bootstrap | IS trade/daily P(net>0)=1.000; 2025 trade 0.923, daily 0.861; 2026 trade 0.908, daily 0.850 | OOS point estimates are good, but one-year tails can still go negative. |
| Outlier dependence | IS top-5 winners are 15.9% of net; 2025 top-5 are 81.6%; 2026 top-5 are 100.2% | IS is not outlier-only; OOS/sanity samples are still outlier-sensitive. |
| Event/macro data | No obvious local macro/event calendar found | Macro-day vulnerability not tested yet. |

Interpretation:

- The standalone Calm sleeve survives the first validation pass, but it is not live-ready.
- The 15:55 exit is consistently better than noon/14:00 and wins the crude IS WFO folds.
- A naive hard disaster stop at 0.5x daily ATR is too tight and can destroy 2026; 0.75x/1.0x are less bad but still reduce edge materially.
- Partial exits reduce drawdown in IS but also reduce net and do not beat full 15:55 in 2025/2026.
- The likely risk design is not a tight profit-protecting stop; it should be a wider disaster/account breaker plus sleeve/per-instrument exposure limits.

Verdict: keep `x1555` as preferred Calm sleeve candidate, but require a second Calm risk pass focused on wider disaster stops, per-instrument caps, adverse-cutoff timing, and macro/event vulnerability.

### Calm sleeve validation pass 2 - risk design

Artifact: `scratch/calm_sleeve_validation.py` with `--variant-set risk2`.

Purpose:

- Test wider disaster stops, delayed stop arming, adverse cutoffs, max concurrent Calm exposure, and instrument-set caps.
- This is still sleeve-only and fill-audited, not a production implementation.

Risk variant results:

| Window | Variant | Net | PF | Sharpe | Calmar | MaxDD | Read |
|---|---|---:|---:|---:|---:|---:|---|
| 2018-2024 floor | `x1555` | +$14,850 | 1.60 | 2.81 | 1.13 | $1,881 / 3.8% | Baseline time exit. |
| 2018-2024 floor | `x1555_stop125` | +$13,654 | 1.53 | 2.51 | 0.98 | $2,000 / 4.0% | Slightly too tight. |
| 2018-2024 floor | `x1555_stop15` | +$14,052 | 1.55 | 2.62 | 1.07 | $1,881 / 3.8% | Near baseline, only 1.0% stopped. |
| 2018-2024 floor | `x1555_stop20` | +$14,850 | 1.60 | 2.81 | 1.13 | $1,881 / 3.8% | No historical effect; disaster-only. |
| 2018-2024 floor | `cut1030_05` | +$14,390 | 1.57 | 2.77 | 1.20 | $1,720 / 3.4% | Best risk tradeoff in IS. |
| 2025 OOS | `x1555` | +$2,736 | 1.54 | 2.52 | 1.41 | $2,074 / 4.1% | Baseline time exit. |
| 2025 OOS | `x1555_stop125` | +$2,557 | 1.49 | 2.28 | 1.32 | $2,074 / 4.1% | Mildly worse, still positive. |
| 2025 OOS | `x1555_stop15` | +$2,736 | 1.54 | 2.52 | 1.41 | $2,074 / 4.1% | No effect. |
| 2025 OOS | `cut1030_05` | +$2,735 | 1.54 | 2.61 | 1.20 | $2,447 / 4.9% | Same net, worse Calmar/DD. |
| 2026 to 2026-08-19 | `x1555` | +$2,634 | 1.58 | 2.87 | 2.88 | $1,496 / 3.0% | Baseline time exit. |
| 2026 to 2026-08-19 | `x1555_stop125` | +$1,909 | 1.36 | 1.92 | 1.41 | $2,221 / 4.4% | Cuts edge materially. |
| 2026 to 2026-08-19 | `x1555_stop15` | +$2,634 | 1.58 | 2.87 | 2.88 | $1,496 / 3.0% | No effect. |
| 2026 to 2026-08-19 | `cut1030_05` | +$2,145 | 1.42 | 2.23 | 1.77 | $1,985 / 4.0% | Positive but weaker. |

Sleeve cap / instrument-set proxy on `x1555`:

| Window | Policy | Trades | Net | PF | Calmar | MaxDD | Risk proxy p95 / max | Read |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 2018-2024 floor | all 3 instruments | 699 | +$14,850 | 1.60 | 1.13 | 3.8% | 2.0% / 2.7% | Baseline. |
| 2018-2024 floor | max 2 per day, most negative overnight first | 548 | +$11,576 | 1.56 | 0.98 | 3.4% | 1.6% / 2.1% | Lower risk and lower net; not clearly better. |
| 2018-2024 floor | max 1 per day, most negative overnight first | 327 | +$6,281 | 1.41 | 0.62 | 2.9% | 1.1% / 1.6% | Too much edge discarded. |
| 2018-2024 floor | no MYM | 456 | +$10,711 | 1.55 | 0.82 | 3.8% | 1.7% / 2.2% | Worse IS; do not drop MYM based on IS. |
| 2025 OOS | all 3 instruments | 87 | +$2,736 | 1.54 | 1.41 | 4.1% | 3.1% / 4.0% | Baseline. |
| 2025 OOS | no MYM | 55 | +$2,879 | 1.75 | 1.73 | 3.6% | 2.8% / 3.4% | Helps because MYM is negative in 2025. |
| 2026 to 2026-08-19 | all 3 instruments | 63 | +$2,634 | 1.58 | 2.88 | 3.0% | 3.9% / 4.1% | Baseline. |
| 2026 to 2026-08-19 | no MYM | 39 | +$2,209 | 1.62 | 2.60 | 2.8% | 3.4% / 3.5% | Slightly lower risk but loses net. |

Interpretation:

- A production Calm hard stop should probably be a **wide disaster stop**, not a tight tactical stop.
- `1.5x` daily ATR is the first tested hard-stop level that preserves 2025/2026 and barely touches IS; `2.0x` is effectively a disaster-only backstop in this sample.
- `0.5x` and `0.75x` daily ATR are too tight for this mechanism; they cut into normal adverse excursion and can destroy 2026.
- The best adverse cutoff tested is `10:30 open if down more than 0.5x daily ATR`; it improves IS DD/Calmar but is weaker in 2025/2026, so it is not yet preferred.
- Max concurrent Calm caps reduce risk proxy but also discard substantial edge. Max 2 per day may be a fallback if account risk forces it; max 1 is too restrictive.
- Dropping MYM helps 2025 but hurts IS and 2026; keep MYM for now, but monitor it as the weakest OOS leg.

Risk-design working recommendation:

- Keep signal/exit as `x1555`.
- Use a Calm sleeve cap that allows up to 3 concurrent micro positions only when account-level risk proxy permits; otherwise degrade to max 2 rather than max 1.
- For production design, test `1.5x` daily ATR and `2.0x` daily ATR as disaster stops, with account breaker still acting as the real portfolio-level brake.
- Do not use 0.5x/0.75x daily ATR as a hard stop unless a later WFO/risk pass proves a different cutoff timing.

### Calm excavation pass 6 - intraday opening drive / OR breakout

Artifacts:

- `scratch/calm_intraday_drive.py`
- `scratch/calm_or_breakout_time_probe.py`

Purpose:

- Test a non-overnight, non-generic-VWAP Calm family with larger trade count.
- Signals use only completed morning information.
- Entries are at the next minute open after the signal.
- Exits are scheduled opens; no theoretical stop/target fill is trusted.
- Fill audit: `outside_exit_bar=0`.

Results:

| Variant | Window | Trades | Net | PF | Verdict |
|---|---|---:|---:|---:|---|
| `drive_60m_fade_0.003_to_1555` | 2018-2024 IS | 643 | +$4,527 | 1.16 | Near miss |
| `drive_60m_fade_0.003_to_1555` | 2025 OOS | 104 | -$3,056 | 0.60 | Reject |
| `drive_60m_fade_0.003_to_1555` | 2026 to 2026-08-19 | 77 | +$517 | 1.10 | Mixed |
| Best OR60 breakout time-exit | 2018-2024 IS | 1,269 | +$1,320 | 1.04 | Too small / one instrument |

Interpretation:

- Morning drive had a tempting IS near-miss, but failed 2025 badly.
- OR60 long breakout is only slightly positive and concentrated in one instrument.
- OR60 short breakout is toxic in Calm; this confirms the earlier warning that Calm short exposure is dangerous.

Verdict: reject opening-drive / OR-breakout as a deploy candidate.

### Calm excavation pass 7 - cross-index dispersion pairs

Artifact: `scratch/calm_pair_dispersion_probe.py`.

Execution assumptions:

- Pair PnL is explicit: one micro contract on each leg.
- Signal: relative return dispersion from 09:30 to 10:30.
- Entry: both legs at 10:31 open.
- Exit: both legs at noon open or 15:55 open.
- Costs include both legs.
- Fill audit: `outside_exit_bar=0`.

Best IS results:

| Variant | Trades | Net | PF | Pos years | Verdict |
|---|---:|---:|---:|---:|---|
| `MNQ-MYM momentum, thr 0.005, exit 15:55` | 134 | +$1,417 | 1.21 | 6 | Too small / one pair |
| `MNQ-MYM momentum, thr 0.005, exit noon` | 134 | +$1,399 | 1.33 | 5 | Too small / one pair |
| `MNQ-MYM momentum, thr 0.0015, exit 15:55` | 497 | +$1,192 | 1.05 | 4 | Too weak |

Interpretation:

- The only positive pocket is MNQ-MYM first-hour relative momentum.
- PnL is not large enough, and the edge is one-pair only.
- Mean-reversion pair variants were broadly negative.

Verdict: reject as deploy candidate; keep only as a research note.

### Calm excavation pass 8 - midday drive

Artifact: `scratch/calm_midday_drive_probe.py`.

Setup:

- Signal: RTH open to noon return.
- Entry: 12:01 open.
- Exit: 14:00 open or 15:55 open.
- Tested momentum and fade with AM range caps.
- Fill audit: `outside_exit_bar=0`.

Best IS results:

| Variant | Trades | Net | PF | Verdict |
|---|---:|---:|---:|---|
| `midday_momo_thr0.0035_cap0.008_x1400` | 390 | +$104 | 1.01 | No edge |
| `midday_momo_thr0.005_cap0.008_x1400` | 129 | -$60 | 0.97 | Reject |
| Larger-count variants | 700-1,493 | Negative | < 1.00 | Reject |

Interpretation:

- Trade count is better, but expectancy is not there.
- After costs, Calm noon-to-close continuation/fade is mostly negative.

Verdict: reject midday drive.

## Research artifacts created in scratch

- `scratch/independent_exit_price_check.py`
- `scratch/independent_corrected_fill_measure.py`
- `scratch/regime_candidate_probe.py`
- `scratch/window_probe.py`
- `scratch/regime_filter_probe.py`
- `scratch/market_filter_probe.py`
- `scratch/stress_overlay_probe.py`
- `scratch/direction_regime_probe.py`
- `scratch/candidate_trade_breakdown.py`
- `scratch/candidate_feature_probe.py`
- `scratch/directional_market_filter_probe.py`
- `scratch/regime_strategy_excavation.py`
- `scratch/calm_strategy_excavation.py`
- `scratch/calm_gap_refine.py`
- `scratch/calm_drift_excavation.py`
- `scratch/calm_intraday_drive.py`
- `scratch/calm_or_breakout_probe.py`
- `scratch/calm_or_breakout_time_probe.py`
- `scratch/calm_pair_dispersion_probe.py`
- `scratch/calm_midday_drive_probe.py`
- `scratch/calm_candidate_deploy_probe.py`
- `scratch/calm_failed_overnight_continuation_probe.py`
- `scratch/calm_compression_expansion_probe.py`
- `scratch/calm_neg_overnight_exit_sweep.py`

These are research harness/probe files, not production engine changes.

### Calm sleeve independent audit - 2026-08-21

Artifacts:

- `docs/futures/CALM_SLEEVE_AUDIT_2026-08-21.md`
- `scratch/audit_calm_negon_20260821.py`
- `scratch/audit_calm_negon_20260821.txt`

Scope:

- Read-only audit of `on_neg_fade_mod001_010_x1555`.
- No production code changed and nothing committed.
- Auditor re-read 1-minute parquet bars instead of trusting saved trade logs.

Clean checks:

- Headline trade-level numbers reproduce from saved logs:
  - 2018-2024: 699 trades, +$14,850, PF 1.60.
  - 2025: 87 trades, +$2,736, PF 1.54.
  - 2026 to 2026-08-19: 63 trades, +$2,634, PF 1.58.
- Entry price is the 09:30 bar open with 0 mismatches.
- Exit price is the 15:55 bar open, not close, with 0 mismatches.
- Signal timestamp equals entry timestamp; exit is always later and same-day.
- Overnight return uses completed overnight data ending at 09:29, with no future bar.
- Band membership `(-1.0%, -0.1%]` has 0 violations.
- Normal SPY D-1 short filter and Normal core config were checked as non-leaking.
- Deploy probe's bar feasibility audit is real and was able to catch NKD impossible stop exits.
- Frozen/live futures data-vintage differences are immaterial for this sleeve: 12 of 699 IS trades differ, net impact about -$17.

Critical blockers found:

- **09:30 open fill dependence:** delaying entry from 09:30 open to 09:31 open reduces net by -$730 IS, -$202 in 2025, and -$586 in 2026. The honest 2026 figure under a 1-minute delay is +$2,049 rather than +$2,634. This is the main execution blocker because the opening minute is where micro spreads/slippage are least likely to match a flat 2 ticks/side assumption.
- **Calm cap is structurally inert for concurrency:** same-day Calm trades are not held in the open book for admission accounting, so the current "own cap" does not actually limit 2-3 simultaneous Calm micros. Three-instrument days are the most common IS state: 151 of 327 Calm trade days. The 2026 own-cap rejections were a per-trade MNQ ATR-proxy filter, not a true sleeve concurrency cap.
- **Some scratch audit columns are constants:** `outside_exit_bar=0` is hardcoded in several Calm sweep/profile scripts, and `signal_after_entry` is missing there. The independently re-read bars prove this candidate's construction is feasible, but the printed sweep audit field is not evidence and must be replaced before future variants are trusted.

High-risk concerns:

- The overnight-return band is not stable enough to call confirmed. The `-1.0%..-0.5%` bucket is +$6,930 IS but negative in both 2025 and 2026; the excluded `-0.1%..0%` bucket is negative IS but strongly positive in 2025. Only `-0.5%..-0.2%` is positive across all three windows, but changing to it now would be OOS-informed refit.
- WFO did not truly select the preferred candidate in usable folds. `raw_x1555` was selected for the 2023 and 2024 test folds; `mod001_010_x1555` was selected only for the 2022 fold with 2 test trades.
- Day-clustered OOS bootstrap intervals span zero: 2025 p=0.252, 2026 p=0.293, pooled OOS p=0.125. This is insufficient evidence, not disproof.
- Pooled OOS contribution is MNQ-heavy: MNQ is about 71% of pooled OOS net; MYM OOS contribution is only about +$284 over 56 trades.
- "7 positive years" should be read cautiously: 2022 has only 2 Calm trades, and 2020 contributes only a small positive.

Corrections to prior notes:

- Wider disaster stops were tested. `1.5x` daily ATR fires very rarely and is bit-identical in 2025/2026; `2.0x` daily ATR never fires in the tested sample. Shipping either means mostly shipping an unexercised code path.
- The sleeve is not outlier-driven: symmetric trim of the largest winners and losers keeps pooled OOS positive, and median trade/day is positive in all windows checked.
- No macro/event calendar exists in the repo, so event vulnerability remains untested.
- Calm standalone drawdown is realised-cash only; intraday mark-to-market risk is understated versus a live sleeve.

Updated verdict:

- **Research-confirmed, not production-ready.**
- Execution mechanics for the saved candidate are real and independently verified.
- Generalisation and live execution are not confirmed because the edge depends on obtaining the 09:30 open fill, WFO selection was overridden, OOS intervals span zero, and the current deploy cap does not implement true same-day Calm concurrency control.
- Next gate before deploy promotion: implement a real non-constant fill/timing audit in the scratch harness, run open-slippage / 09:31-entry sensitivity as the primary execution case, implement an actual same-day Calm sleeve cap, and only then rerun combined Normal + Stress + Calm metrics.

### Calm audit remediation pass - 2026-08-21

Code touched:

- Scratch only, no production code.
- `scratch/calm_neg_overnight_exit_sweep.py`: `outside_exit_bar`, `outside_entry_bar`, and `signal_after_entry` are now computed from the actual entry/exit bars instead of writing a literal zero.
- `scratch/calm_neg_overnight_risk_filter_probe.py`: stop/time exits now compute bar feasibility; selection gates require exit, entry, and timing audit to be clean.
- `scratch/calm_neg_overnight_mae_profile.py`: profile output now includes real entry/exit/timing audit fields.
- `scratch/calm_candidate_deploy_probe.py`: added `--calm-entry-delay-minutes`, `--calm-entry-extra-slippage-ticks`, and `--calm-max-per-day`; replay now has a real same-day Calm concurrency cap.
- `scratch/calm_auditfix_measure.py`: fast measurement harness from saved signals plus parquet repricing.

Rechecks:

- Independent audit rerun reproduced the prior clean mechanics and blocker measurements:
  - Base trade-level: IS 699 +$14,850 PF 1.60; 2025 87 +$2,736 PF 1.54; 2026 63 +$2,634 PF 1.58.
  - Entry/exit parquet check remains clean: entry at 09:30 open, exit at 15:55 open, `outside_exit_bar=0`, `signal_after_entry=0`.
  - Entry latency remains the key execution sensitivity: 2026 falls to +$2,049 at 09:31, +$1,942 at 09:32, and +$1,144 at 09:35.

Fast audit-fix Calm-only results:

| Window | Policy | Trades | Rejected | Net | PF | Sharpe | Calmar | MaxDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018-2024 | base 09:30 | 699 | 0 | +$14,850 | 1.60 | 2.81 | 1.13 | $1,881 |
| 2018-2024 | entry 09:31 | 699 | 0 | +$14,121 | 1.57 | 2.72 | 0.95 | $2,134 |
| 2018-2024 | entry cost +2 ticks | 699 | 0 | +$13,821 | 1.55 | 2.62 | 1.03 | $1,929 |
| 2018-2024 | max 2 per day, most negative ON first | 548 | 151 | +$11,576 | 1.56 | 2.61 | 0.98 | $1,696 |
| 2018-2024 | max 1 per day, most negative ON first | 327 | 372 | +$6,281 | 1.41 | 1.93 | 0.62 | $1,461 |
| 2025 | base 09:30 | 87 | 0 | +$2,736 | 1.54 | 2.52 | 1.41 | $2,074 |
| 2025 | entry 09:31 | 87 | 0 | +$2,535 | 1.50 | 2.45 | 1.58 | $1,714 |
| 2025 | max 2 per day | 72 | 15 | +$2,400 | 1.54 | 2.41 | 1.36 | $1,888 |
| 2026 | base 09:30 | 63 | 0 | +$2,634 | 1.58 | 2.87 | 2.88 | $1,496 |
| 2026 | entry 09:31 | 63 | 0 | +$2,049 | 1.43 | 2.17 | 1.89 | $1,776 |
| 2026 | max 2 per day | 52 | 11 | +$1,600 | 1.37 | 2.03 | 1.75 | $1,494 |
| 2026 | max 1 per day | 33 | 30 | +$692 | 1.22 | 1.18 | 0.94 | $1,204 |
| OOS pooled | base 09:30 | 150 | 0 | +$5,371 | 1.56 | 2.69 | 1.65 | $2,074 |
| OOS pooled | max 2 per day | 124 | 26 | +$4,000 | 1.46 | 2.25 | 1.35 | $1,888 |
| OOS pooled | max 1 per day | 80 | 70 | +$2,004 | 1.30 | 1.51 | 0.75 | $1,703 |

Combined R4 Normal + Stress + Calm, excluding NKD to isolate the clean audited R4 sleeves:

| Window | Calm Execution / Cap | Normal + Stress | With Calm Own Cap | Calm Delta | Calm Taken / Rejected | Audit |
|---|---|---:|---:|---:|---:|---|
| 2025 | base 09:30, no same-day cap, 2.5% ATR proxy cap | +$4,654, Calmar 1.64, MaxDD 6.2% | +$7,391, Calmar 2.56, MaxDD 6.2% | +$2,736 | 87 / 0 | OK |
| 2026 | base 09:30, no same-day cap, 2.5% ATR proxy cap | +$736, Calmar 0.21, MaxDD 12.7% | +$2,938, Calmar 0.74, MaxDD 13.1% | +$2,202 | 60 / 3 | OK |
| 2025 | max 2 per day, relaxed ATR cap | +$4,654, Calmar 1.64, MaxDD 6.2% | +$7,054, Calmar 2.44, MaxDD 6.2% | +$2,400 | 72 / 15 | OK |
| 2026 | max 2 per day, relaxed ATR cap | +$736, Calmar 0.21, MaxDD 12.7% | +$2,336, Calmar 0.58, MaxDD 13.2% | +$1,600 | 52 / 11 | OK |
| 2025 | entry 09:31, relaxed ATR cap | +$4,654, Calmar 1.64, MaxDD 6.2% | +$7,189, Calmar 2.49, MaxDD 6.2% | +$2,535 | 87 / 0 | OK |
| 2026 | entry 09:31, relaxed ATR cap | +$736, Calmar 0.21, MaxDD 12.7% | +$2,785, Calmar 0.66, MaxDD 13.7% | +$2,049 | 63 / 0 | OK |

Notes:

- Full 2018-2024 combined rerun timed out after 300s during the Normal/floor stage, so this remediation pass uses the fast Calm-only floor measurement plus combined 2025/2026 checks. The prior combined floor result should not be treated as refreshed under the new cap/latency options until a cached or longer-running combined harness is used.
- The audit claim about literal `outside_exit_bar` was confirmed and fixed in scratch.
- The audit claim about inert same-day cap was confirmed. A true max-2 cap still leaves positive OOS/sanity edge, but it reduces OOS pooled Calm net from +$5,371 to +$4,000 and 2026 from +$2,634 to +$1,600.
- The audit claim about 09:30 dependence was confirmed. A 09:31 feasible-entry case remains profitable but materially weaker, especially in 2026.
- The claim that extra open slippage matters is only modest under a cost-penalty model: +2 extra entry ticks still leaves IS +$13,821, 2025 +$2,613, and 2026 +$2,543. This does not solve the 09:30 fill-quality question, but it argues the main fragility is timing, not a small extra tick-cost penalty.

Updated remediation verdict:

- Keep the sleeve as a **research-confirmed Calm candidate**, not a deploy-level sleeve.
- For the next combined-system gate, use two honest execution cases:
  - optimistic: 09:30 open, max 2 or max 3 true same-day Calm cap,
  - conservative: 09:31 open, max 2 true same-day Calm cap.
- Do not use the old "own cap" result as concurrency evidence.
- Do not promote until full 2018-2024 combined metrics are rerun with the fixed cap and latency knobs, preferably from cached Normal/Stress trades to avoid 300s floor reruns.

### Calm audit repair follow-up - 2026-08-21

Source: `docs/futures/CALM_SLEEVE_AUDIT_2026-08-21.md` section 8.

Status changes:

- **C1 downgraded.** The 09:30-open concern remains a paper-trading measurement item, not a production blocker by itself. The 1-minute delay point estimate is negative in all windows, but day-clustered intervals include zero:
  - IS: -$730, CI [-$1,811, +$351], p=0.196.
  - 2025: -$202, p=0.657.
  - 2026: -$586, CI [-$1,339, +$103], p=0.114.
- First-minute drift is not statistically reliable: pooled share of 09:31 open above 09:30 open is 52.8%, binomial p=0.12.
- The move accumulates through the session rather than only at the bell. Share of 09:30-to-15:55 move already earned:

| Window | 09:31 | 09:35 | 10:00 | 12:00 |
|---|---:|---:|---:|---:|
| 2018-2024 | 4.1% | 9.6% | 29.4% | 60.0% |
| 2025 | 6.5% | 11.8% | -11.9% | 44.0% |
| 2026 | 20.2% | 51.5% | 16.8% | 31.6% |

Interpretation:

- Do not describe the edge as living in the first minute. The better description is a slow Calm-session drift/fade after a negative overnight.
- Still record live timestamps and slippage during paper trading. A systematic several-minute delay remains harmful, especially in 2026, but the +1 minute result alone is not enough to block paper deployment research.

C3 repair:

- Exit and entry-bar checks now have mutation evidence: pushing exit price outside the bar turns `outside_exit_bar` red.
- `signal_after_entry` needed a stronger definition. The old check compared `entry_ts.time() < 09:30`, which cannot fail after filtering RTH to 09:30 onward.
- Scratch probes now use the falsifiable form:

```python
"signal_after_entry": 1 if pre.index.max() >= entry_ts else 0
```

- Updated in:
  - `scratch/calm_neg_overnight_exit_sweep.py`
  - `scratch/calm_neg_overnight_risk_filter_probe.py`
  - `scratch/calm_neg_overnight_mae_profile.py`
- The risk-filter row writer no longer carries the misleading literal `"outside_entry_bar": 0` before `**meta`.

Cap follow-up:

- A true max-2 same-day cap keeps the sleeve recognizably similar.
- A max-1 cap changes the sleeve identity because the "most negative overnight first" tie-break systematically favors MNQ/MYM and drops MES:

| Window | Policy | MES / MNQ / MYM trade share | MES share of PnL |
|---|---|---|---:|
| 2018-2024 | base | 31% / 34% / 35% | +32% |
| 2018-2024 | max 2 | 31% / 36% / 33% | +36% |
| 2018-2024 | max 1 | 12% / 50% / 38% | +1% |
| 2026 | max 1 | 6% / 42% / 52% | -38% |

So max-1 is not a smaller version of the current sleeve; it is effectively a different MNQ/MYM-heavy sleeve. This is the structural reason to avoid max-1 unless risk constraints force it.

Honest-cap statistical position:

| Policy | OOS pooled net | 95% interval | p | MNQ share of net |
|---|---:|---|---:|---:|
| base | +$5,371 | [-$1,479, +$12,313] | 0.129 | 71% |
| max 2 | +$4,000 | [-$2,115, +$9,993] | 0.210 | 78% |

This means H3/H4 get worse under the honest cap: lower OOS net, wider uncertainty relative to edge, and more MNQ concentration. Keep this visible; do not let the old inert-cap metrics stand in as risk evidence.

Still open after repair:

- H1 remains the highest-priority unresolved issue: the `-1.0%..-0.5%` bucket is +$6,930 IS but negative in both 2025 and 2026.
- H2 remains open: WFO selected `raw_x1555` in both folds with usable sample.
- H3/H4 remain open and slightly worse under max-2.
- H5 should be stated as five contributing years, not seven.
- Full 2018-2024 combined metrics are still not refreshed under fixed cap/latency knobs.

### Calm C3 closure and artifact refresh - 2026-08-21

Source: `docs/futures/CALM_SLEEVE_AUDIT_2026-08-21.md` section 9 plus local rerun.

Closure:

- C3 is now closed. Mutation tests widened the overnight signal window in memory; all three probes went red under signal leakage and stayed clean under the correct 09:30 cutoff:

| Probe | Clean 09:30 | Mutate 09:36 | Mutate 10:00 |
|---|---:|---:|---:|
| `calm_neg_overnight_mae_profile.py` | 0 / 19 | 18 / 18 | 23 / 23 |
| `calm_neg_overnight_exit_sweep.py` | 0 / 19 | 18 / 18 | 23 / 23 |
| `calm_neg_overnight_risk_filter_probe.py` | 0 / 19 | 18 / 18 | 23 / 23 |

Non-regression:

- The fixed code reproduces the old 2026 candidate log exactly: 63 trades, +$2,634.38, same day/instrument set, max per-trade difference 0.

WFO gate fix:

- `scratch/calm_neg_overnight_wfo_stability.py` now requires all three audit columns:
  - `outside_exit_bar`
  - `outside_entry_bar`
  - `signal_after_entry`
- On stale logs, it fails loudly with missing-column error instead of reading a constant.
- After regenerating the sweep artifacts, WFO loads the refreshed IS log with all three audit sums at 0.

Artifacts refreshed:

- `scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_is.csv`
- `scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_2025.csv`
- `scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_2026.csv`
- `scratch/calm_neg_overnight_wfo_stability.csv`

Refreshed sweep headline:

| Variant | 2018-2024 IS | 2025 | 2026 |
|---|---:|---:|---:|
| `raw_x1555` | 1,036 trades, +$15,205, PF 1.38 | 132 trades, +$5,285, PF 1.81 | 76 trades, +$2,440, PF 1.38 |
| `mod001_010_x1555` | 699 trades, +$14,850, PF 1.60 | 87 trades, +$2,736, PF 1.54 | 63 trades, +$2,634, PF 1.58 |
| `mod002_010_x1555` | 461 trades, +$14,383, PF 1.94 | not selected by this rerun's two-candidate OOS pass | not selected by this rerun's two-candidate OOS pass |

Refreshed WFO:

| Train | Test | Selected | Read |
|---|---:|---|---|
| 2018-2021 | 2022 | `mod001_010_x1555` | Only 2 selected-candidate test trades. |
| 2019-2022 | 2023 | `raw_x1555` | Usable fold; raw selected. |
| 2020-2023 | 2024 | `raw_x1555` | Usable fold; raw selected. |

Interpretation:

- Mechanics/fill/timing gates are now live and regenerated.
- C1 remains downgraded to paper-trading measurement.
- C2 remains fixed via true same-day cap.
- H1/H2/H3/H4/H5 remain research-selection/statistical problems, not code defects.

### Calm code closure and sharper evidence status - 2026-08-21

Source: `docs/futures/CALM_SLEEVE_AUDIT_2026-08-21.md` section 10.

Code status:

- **All code-level findings are closed.**
- C1 is not a code blocker; it is a paper-trading fill/timestamp measurement item.
- C2 is fixed with a true same-day cap; max-1 is documented as a different MNQ/MYM-heavy sleeve, not a smaller version of the same sleeve.
- C3 is fully closed:
  - mutation-tested gates can go red,
  - artifacts were regenerated with `outside_exit_bar`, `outside_entry_bar`, and `signal_after_entry`,
  - WFO fails loudly on stale-shaped logs that lack the new columns.

Artifact non-regression:

- Regenerated artifacts changed no strategy numbers:

| Window | Variant | Trades | Net | Audit |
|---|---|---:|---:|---|
| 2018-2024 | `raw_x1555` | 1,036 | +$15,205 | 0 / 0 / 0 |
| 2018-2024 | `mod001_010_x1555` | 699 | +$14,850 | 0 / 0 / 0 |
| 2018-2024 | `mod002_010_x1555` | 461 | +$14,383 | 0 / 0 / 0 |
| 2025 | `raw_x1555` / `mod001_010_x1555` | 132 / 87 | +$5,285 / +$2,736 | 0 / 0 / 0 |
| 2026 | `raw_x1555` / `mod001_010_x1555` | 76 / 63 | +$2,440 / +$2,634 | 0 / 0 / 0 |

Note: `mod002_010_x1555` is still absent from the regenerated OOS logs, so its OOS provenance remains separate from this pipeline.

Held-out WFO view:

| Variant held fixed | 2022 | 2023 | 2024 | Sum | Trades | $/trade |
|---|---:|---:|---:|---:|---:|---:|
| `raw_x1555` | +$194 | +$5,563 | +$687 | +$6,444 | 372 | $17.32 |
| `mod001_010_x1555` | +$171 | +$3,766 | +$1,776 | +$5,713 | 260 | $21.97 |
| `mod002_010_x1555` | +$306 | +$4,112 | +$1,982 | +$6,401 | 167 | $38.33 |

Walk-forward policy comparison:

| Policy | Held-out net | Trades |
|---|---:|---:|
| Follow per-fold WFO pick | +$6,421 | 368 |
| Always trade `raw_x1555` | +$6,444 | 372 |
| Always trade `mod001_010_x1555` | +$5,713 | 260 |
| Always trade `mod002_010_x1555` | +$6,401 | 167 |

Interpretation:

- H2 is now sharper, not solved. The promoted candidate `mod001_010_x1555` is first in none of the three held-out years and last in two of them.
- This does **not** justify switching to `mod002_010_x1555`; ranking variants on these same held-out years is the same selection error one layer down.
- The correct read is that the three variants are not separable with the available held-out evidence, and the promoted candidate rests on a tiebreak that held-out data does not reproduce.
- H5 is visible inside the WFO robustness gate: train windows clear `posY=4`, but one of those years is 2022 with only 1-6 trades depending on variant. The 2022 test fold is also too thin to carry selection evidence.

Current Calm status:

- Code mechanics: closed.
- Candidate status: **research-confirmed, not deploy-level**.
- Open evidence questions:
  - H1: band boundaries invert OOS, especially `-1.0%..-0.5%`.
  - H2: held-out/WFO evidence does not choose `mod001_010_x1555`.
  - H3/H4: only 80 OOS days, CI spans zero, and OOS net is 71-78% MNQ-driven depending on cap.
  - H5: in-sample contribution is five meaningful years, not seven.

### Calm H1 bucket excavation - 2026-08-21

Artifact:

- `scratch/calm_h1_bucket_excavation.py`
- `scratch/calm_h1_bucket_excavation_summary.csv`
- `scratch/calm_h1_bucket_excavation_trades.csv`

Purpose:

- Test H1 directly: whether the selected overnight band is an unstable fit.
- Use the refreshed, fill-audited `raw_x1555` logs only.
- Keep buckets fixed before reading the output; do not optimize a new threshold from 2025/2026.
- Audit gate: input logs must have `outside_exit_bar=0`, `outside_entry_bar=0`, `signal_after_entry=0`.

Bucket summary:

| Bucket | 2018-2024 IS | 2025 | 2026 | OOS pooled | Read |
|---|---:|---:|---:|---:|---|
| `-2.0%..-1.0%` | 28 trades, +$1,499, PF 1.96 | 4 trades, +$849 | 4 trades, +$0 | 8 trades, +$849 | Too few trades. |
| `-1.0%..-0.5%` | 138 trades, +$6,930, PF 2.58 | 18 trades, -$862 | 22 trades, -$316 | 40 trades, -$1,178 | H1 confirmed; IS-only pocket fails OOS. |
| `-0.5%..-0.2%` | 323 trades, +$7,453, PF 1.68 | 39 trades, +$2,685 | 26 trades, +$2,726 | 65 trades, +$5,410 | Stable-looking, but selecting it now is OOS-informed. |
| `-0.2%..-0.1%` | 238 trades, +$467, PF 1.05 | 30 trades, +$914 | 15 trades, +$224 | 45 trades, +$1,138 | Weak IS; OOS positive but not selectable after seeing it. |
| `-0.1%..0.0%` | 309 trades, -$1,144, PF 0.92 | 41 trades, +$1,700 | 9 trades, -$195 | 50 trades, +$1,506 | Boundary instability; confirms original cut was fitted-looking. |

Day-cluster bootstrap:

| Bucket | IS P(net>0) / CI | 2025 P(net>0) / CI | 2026 P(net>0) / CI | OOS pooled P(net>0) / CI |
|---|---|---|---|---|
| `-1.0%..-0.5%` | 0.999 / [$3,353, $10,623] | 0.222 / [-$2,818, $818] | 0.407 / [-$2,743, $2,374] | 0.265 / [-$4,284, $2,007] |
| `-0.5%..-0.2%` | 0.993 / [$2,732, $12,205] | 0.960 / [$175, $5,185] | 0.960 / [$154, $5,558] | 0.996 / [$1,893, $9,083] |
| `-0.2%..-0.1%` | 0.595 / [-$2,902, $3,622] | 0.784 / [-$1,061, $2,746] | 0.745 / [-$390, $815] | 0.831 / [-$879, $3,173] |
| `-0.1%..0.0%` | 0.339 / [-$5,571, $3,413] | 0.960 / [$99, $3,395] | 0.434 / [-$1,985, $1,537] | 0.841 / [-$977, $3,895] |

Instrument details:

- `-1.0%..-0.5%` OOS pooled is negative across all three instruments:
  - MES -$12
  - MNQ -$847
  - MYM -$318
- `-0.5%..-0.2%` OOS pooled is positive across all three instruments:
  - MES +$461
  - MNQ +$4,186
  - MYM +$762
- The stable-looking bucket is still MNQ-heavy OOS, so H4 is not solved.

Year details:

- `-1.0%..-0.5%` is positive in every IS year, including a tiny 2022 sample, then negative in both OOS years. This is the clearest evidence that the current lower band boundary is fitted noise.
- `-0.5%..-0.2%` is positive in 2018, 2019, 2020, 2021, 2023, and 2024; there are no 2022 trades in this bucket. It is also positive in 2025 and 2026.

Interpretation:

- H1 is confirmed against the current `mod001_010_x1555` band. The selected band includes a large IS-only bucket that fails both OOS years.
- The original `-0.1%` upper cut is also not stable: `-0.1%..0.0%` was negative IS but strongly positive in 2025.
- The only stable-looking bucket is `-0.5%..-0.2%`, but promoting that band now would be OOS-informed threshold refitting.

Updated Calm verdict:

- Reject `on_neg_fade_mod001_010_x1555` as a deploy-level candidate.
- Keep the mechanism as research-useful: Calm negative-overnight RTH drift exists most cleanly in the moderate `-0.5%..-0.2%` overnight bucket.
- Do not productionize a narrowed `-0.5%..-0.2%` sleeve from this evidence alone. It can become a **predeclared paper candidate** or the seed for a future WFO protocol, but not a post-hoc deploy selection.
- Next work should either:
  - predeclare a new WFO selection rule using only future/unseen data, or
  - keep digging for another Calm mechanism with more separable held-out evidence.

### Calm selection protocol pass - 2026-08-21

Artifacts:

- `scratch/calm_selection_protocol.py`
- `scratch/calm_selection_protocol_folds.csv`
- `scratch/calm_selection_protocol_ranks.csv`

Purpose:

- Predefine a stricter selection protocol before promoting any Calm variant.
- Apply it to:
  - finalist variants: `raw_x1555`, `mod001_010_x1555`, `mod002_010_x1555`,
  - bucket variants: `-1.0%..-0.5%`, `-0.5%..-0.2%`, `-0.2%..-0.1%`, `-0.1%..0.0%`.

Protocol gates:

- All audit counters must be present and zero.
- Train eligibility:
  - at least 100 train trades,
  - PF >= 1.10,
  - positive train net,
  - at least 2 positive instruments,
  - top-year share <= 75%,
  - positive meaningful years only count if the year has at least 20 trades or 10 trade-days.
- Test fold is meaningful only if selected variant has at least 20 trades.
- Verdict rejects if any selected test fold is too thin.
- Verdict rejects if held-out does not confirm selection at least 2 of 3 folds.
- If candidates are too close, report not separable instead of forcing a winner.

Finalist protocol:

| Fold | Selected by train | Test net | Test trades | Held-out winner | Selected rank | Meaningful |
|---|---|---:|---:|---|---:|---|
| 2018-2021 -> 2022 | `mod001_010_x1555` | +$171 | 2 | `mod002_010_x1555` | 3 | no |
| 2019-2022 -> 2023 | `raw_x1555` | +$5,563 | 159 | `raw_x1555` | 1 | yes |
| 2020-2023 -> 2024 | `raw_x1555` | +$687 | 207 | `mod002_010_x1555` | 3 | yes |

Aggregate selected finalist folds:

- Net +$6,421.
- Trades 368.
- Meaningful folds 2/3.
- Winner matches 1/3.
- Protocol verdict: **reject_thin_test_fold**.

Bucket protocol:

| Fold | Selected by train | Test net | Test trades | Held-out winner | Selected rank | Meaningful |
|---|---|---:|---:|---|---:|---|
| 2018-2021 -> 2022 | `bucket_-0.5%..-0.2%` | +$0 | 0 | `bucket_-1.0%..-0.5%` | 2 | no |
| 2019-2022 -> 2023 | `bucket_-0.5%..-0.2%` | +$1,891 | 50 | `bucket_-1.0%..-0.5%` | 2 | yes |
| 2020-2023 -> 2024 | `bucket_-0.5%..-0.2%` | +$1,331 | 63 | `bucket_-0.5%..-0.2%` | 1 | yes |

Aggregate selected bucket folds:

- Net +$3,222.
- Trades 113.
- Meaningful folds 2/3.
- Winner matches 1/3.
- Protocol verdict: **reject_thin_test_fold**.

Interpretation:

- The stricter protocol prevents promotion of both the finalist family and the bucket family.
- `bucket_-0.5%..-0.2%` is train-selected consistently in the bucket family, which is a useful sign, but it has no 2022 test trades and only matches the held-out winner in 1 of 3 folds.
- This supports the earlier conclusion: the moderate negative-overnight bucket is a **paper/predeclared candidate seed**, not a deploy-level candidate.
- The protocol also formalizes H5: years with 1-6 trades no longer count as meaningful robustness evidence.

Updated Calm research status:

- No Calm sleeve is deploy-level after this pass.
- The best surviving mechanism seed is `Calm negative overnight, bucket (-0.5%, -0.2%], LONG RTH open to 15:55`.
- Next acceptable uses:
  - paper-track the seed prospectively under the fixed protocol,
  - or continue Calm excavation for a different mechanism with separable held-out evidence.

### Calm context excavation - opening drift / prior-day context

Artifacts:

- `scratch/calm_context_excavation.py`
- `scratch/calm_context_excavation_summary.csv`
- `scratch/calm_context_excavation_trades.csv`
- `scratch/calm_context_protocol.py`
- `scratch/calm_context_protocol_folds.csv`

Purpose:

- Continue Calm excavation away from the fitted overnight band.
- Test categorical context around the same broad mechanism: raw negative overnight, then RTH open-to-15:55 drift.
- Contexts are fixed categories, not dense thresholds:
  - prior day up/down,
  - RTH open location vs prior RTH range,
  - prior day compression/expansion versus rolling 20-day median range,
  - SPY D-1 above/below SMA50 and RV20 <= 20%.

IS-selected context variants before OOS:

| Variant | IS trades | IS net | IS PF | OOS pooled net | OOS PF | OOS P(net>0) | Read |
|---|---:|---:|---:|---:|---:|---:|---|
| `all_raw_neg` | 1,036 | +$15,205 | 1.38 | +$7,725 | 1.60 | 0.964 | Broadest signal; still not separable by WFO. |
| `spy_rv20_le20` | 1,013 | +$14,570 | 1.37 | +$7,725 | 1.60 | 0.965 | Nearly identical to raw in 2025/2026; not a real discriminator there. |
| `spy_above50` | 970 | +$13,257 | 1.36 | +$6,563 | 1.52 | 0.943 | Helpful in IS, but 2026 weaker. |
| `open_lower_third` | 579 | +$11,890 | 1.59 | +$6,101 | 1.89 | 0.981 | Strong 2025, weak 2026; needs protocol. |
| `prior_expand20` | 452 | +$10,644 | 1.64 | -$2,414 | 0.64 | 0.137 | Reject; classic IS-only filter. |
| `prior_up` | 579 | +$9,386 | 1.43 | +$6,782 | 2.00 | 0.982 | Best context seed from OOS check, but protocol still rejects. |
| `seed_m005_m002` | 323 | +$7,453 | 1.68 | +$5,410 | 2.86 | 0.992 | Prior bucket seed; cannot be selected post-hoc. |

Selected context protocol:

| Fold | Train-selected | Test net | Test trades | Held-out winner | Selected rank | Meaningful |
|---|---|---:|---:|---|---:|---|
| 2018-2021 -> 2022 | `open_lower_third` | +$406 | 2 | `prior_expand20` | 2 | no |
| 2019-2022 -> 2023 | `open_lower_third` | +$1,669 | 83 | `all_raw_neg` | 8 | yes |
| 2020-2023 -> 2024 | `all_raw_neg` | +$687 | 207 | `spy_above50` | 8 | yes |

Protocol aggregate:

- Net +$2,762.
- Trades 292.
- Meaningful folds 2/3.
- Winner matches 0/3.
- Verdict: **reject_thin_test_fold**.

Interpretation:

- Context excavation produced useful paper seeds, especially `prior_up` and `open_lower_third`, but no deploy-level candidate.
- `prior_expand20` is a good warning example: strong IS and negative OOS.
- `prior_up` has attractive OOS pooled performance (+$6,782, PF 2.00), but it was not selected by the held-out protocol. Treat it as a research clue, not a sleeve.
- `open_lower_third` is train-selected in early folds but ranks poorly in 2023 held-out and has only 2 trades in 2022.

Updated verdict:

- Still no Calm deploy-level sleeve.
- Best paper seeds:
  - raw negative overnight drift, for broad mechanism tracking,
  - `prior_up` context,
  - `open_lower_third` context,
  - moderate bucket `(-0.5%, -0.2%]`.
- These should be tracked prospectively or used as inputs to a future protocol; none should be promoted from this historical pass.

### Calm prior-day range reclaim/failure probe

Artifacts:

- `scratch/calm_prior_range_reclaim_probe.py`
- `scratch/calm_prior_range_reclaim_is.csv`
- `scratch/calm_prior_range_reclaim_is_summary.csv`
- `scratch/calm_prior_range_reclaim_2025.csv`
- `scratch/calm_prior_range_reclaim_2025_summary.csv`
- `scratch/calm_prior_range_reclaim_2026.csv`
- `scratch/calm_prior_range_reclaim_2026_summary.csv`

Setup:

- Calm only.
- MES/MNQ/MYM.
- New mechanism, not overnight-band selection:
  - `low_reclaim_long`: during 09:30-10:30, price breaks prior RTH low, then closes back above prior low; enter next minute open LONG.
  - `high_fail_short`: during 09:30-10:30, price breaks prior RTH high, then closes back below prior high; enter next minute open SHORT.
- Exits tested:
  - 15:55 bar open,
  - first feasible target at prior-day mid, otherwise 15:55,
  - first feasible target at prior-day close, otherwise 15:55.
- Fill/timing audit: `outside_exit_bar=0`, `outside_entry_bar=0`, `signal_after_entry=0`.

IS selection before OOS:

| Variant | Trades | Net | PF | Pos years | Pos inst | Audit |
|---|---:|---:|---:|---:|---:|---|
| `low_reclaim_long_scan1030_x15:55` | 454 | +$7,842 | 1.52 | 6/7 | 3 | 0/0/0 |
| `low_reclaim_long_scan1030_xtarget_mid_1555` | 454 | +$6,712 | 1.56 | 7/7 | 3 | 0/0/0 |
| `low_reclaim_long_scan1000_x15:55` | 340 | +$6,508 | 1.60 | 6/7 | 3 | 0/0/0 |
| `low_reclaim_long_scan1030_xtarget_close_1555` | 454 | +$5,970 | 1.72 | 7/7 | 3 | 0/0/0 |
| `high_fail_short_scan1000_xtarget_close_1555` | 511 | +$2,865 | 1.28 | 4/7 | 3 | 0/0/0 |

Selected before OOS:

- `low_reclaim_long_scan1030_x15:55`
- `low_reclaim_long_scan1030_xtarget_mid_1555`

OOS / sanity:

| Variant | 2025 | 2026 | Verdict |
|---|---:|---:|---|
| `low_reclaim_long_scan1030_x15:55` | 50 trades, +$2,750, PF 2.67 | 40 trades, -$423, PF 0.89 | Reject as deploy candidate. |
| `low_reclaim_long_scan1030_xtarget_mid_1555` | 50 trades, +$2,899, PF 3.71 | 40 trades, -$1,628, PF 0.58 | Reject as deploy candidate. |

Instrument notes from IS single-leg checks:

- MES, MNQ, and MYM all showed the same direction: low-reclaim LONG was positive; high-failure SHORT was weak or negative.
- MNQ carried the largest IS dollars in this family, but all three instruments were positive for the selected long reclaim variants.

Interpretation:

- Prior-day low reclaim is a real-looking Calm mechanism in IS and works very well in 2025.
- It fails 2026 sanity, so it is not deploy-level.
- High-failure SHORT remains unattractive; this reinforces the broader warning that Calm short exposure is hard to make robust.

Verdict:

- Reject prior-day range reclaim/failure as deploy candidate.
- Keep `low_reclaim_long` as a research clue/paper seed only.
- Do not optimize scan/end/target around 2026 to rescue it.

### Calm compression to directional expansion v2

Artifact:

- `scratch/calm_compression_expansion_v2.py`
- `scratch/calm_compression_expansion_v2_is.csv`
- `scratch/calm_compression_expansion_v2_is_summary.csv`

Setup:

- Calm only.
- MES/MNQ/MYM.
- New mechanism: prior compression plus first-hour expansion/break, enter 10:31 open, exit 14:00 or 15:55 open.
- Contexts:
  - `c1_exp60`: prior day RTH range <= rolling 20-day median range, and first-hour range > rolling median.
  - `c3_exp60`: prior 3-day range <= 3x rolling median, and first-hour range > rolling median.
  - Long only after first-hour break above prior high with positive 09:30-10:30 drive.
  - Short only after first-hour break below prior low with negative 09:30-10:30 drive.
- Fill/timing audit: `outside_exit_bar=0`, `outside_entry_bar=0`, `signal_after_entry=0`.

IS result:

| Variant | Trades | Net | PF | Audit | Verdict |
|---|---:|---:|---:|---|---|
| `c1_exp60_long_x1555` | 18 | -$405 | 0.63 | 0/0/0 | Reject |
| `c1_exp60_short_x1400` | 43 | -$487 | 0.72 | 0/0/0 | Reject |
| `c3_exp60_long_x1555` | 33 | -$587 | 0.65 | 0/0/0 | Reject |
| `c3_exp60_short_x1400` | 86 | -$618 | 0.84 | 0/0/0 | Reject |
| `c1_exp60_long_x1400` | 18 | -$693 | 0.30 | 0/0/0 | Reject |
| `c3_exp60_short_x1555` | 86 | -$3,022 | 0.44 | 0/0/0 | Reject |

Interpretation:

- No IS survivor, so 2025/2026 were not touched.
- This version of Calm compression-to-expansion is not promising.
- It also reinforces a recurring pattern: Calm first-hour break/short expansion is weak or toxic after costs.

Verdict: reject this mechanism form.

### Calm instrument rotation probe

Artifacts:

- `scratch/calm_rotation_probe.py`
- `scratch/calm_rotation_probe_summary.csv`

Setup:

- Use refreshed raw negative-overnight context trades only; no parquet rerun.
- Test a priori rotation / selection rules per Calm day:
  - trade all available instruments,
  - max 2 by most negative overnight,
  - max 2 by lowest open location in prior range,
  - one most negative overnight,
  - one highest prior-day RTH return,
  - moderate bucket `(-0.5%, -0.2%]` with one most-negative instrument.
- Fill audit inherited from context trades: all source trades have `outside_exit_bar=0`, `outside_entry_bar=0`, `signal_after_entry=0`.

IS-selected before OOS:

| Variant | IS trades | IS net | IS PF | OOS pooled net | OOS PF | OOS P(net>0) | Read |
|---|---:|---:|---:|---:|---:|---:|---|
| `all` | 1,036 | +$15,205 | 1.38 | +$7,725 | 1.60 | 0.967 | Baseline raw negative ON; not new. |
| `max2_most_negative` | 790 | +$11,960 | 1.38 | +$5,024 | 1.44 | 0.916 | Reduces exposure but not uncertainty enough. |
| `max2_lowest_open` | 790 | +$10,699 | 1.35 | +$4,788 | 1.43 | 0.920 | Similar to max2 most-negative. |
| `most_negative_on` | 446 | +$6,310 | 1.30 | +$2,238 | 1.27 | 0.799 | Reject by OOS P(net>0) threshold. |
| `highest_prior_ret` | 446 | +$5,488 | 1.29 | +$1,825 | 1.30 | 0.814 | Smaller paper clue only. |

Additional clue:

- `seed_m005_m002_most_negative` did not pass the IS trade-count gate (`197` IS trades, below `200`), but looked good:
  - IS: 197 trades, +$4,901, PF 1.65.
  - 2025: 25 trades, +$1,948, PF 2.79.
  - 2026: 19 trades, +$1,398, PF 2.39.
  - OOS pooled: 44 trades, +$3,346, PF 2.60, P(net>0)=0.990.
- This is not deploy evidence because it is thin and derives from the already OOS-informed moderate bucket seed.

Interpretation:

- Rotation can reduce exposure while retaining positive OOS, but it does not create a deploy-level Calm sleeve.
- Max2 variants are reasonable paper/risk-policy seeds, not standalone candidates.
- Single-instrument daily selection is too thin or too unstable; `most_negative_on` especially loses much of 2026 edge.

Verdict:

- No deploy candidate from instrument rotation.
- Keep max2 rotation as a risk-design idea for paper tracking, not as an edge upgrade.

### Stress audit response - 2026-08-21

Artifacts:

- `scratch/STRESS_SLEEVE_AUDIT_2026-08-21.md` - external audit notes.
- `scratch/STRESS_AUDIT_VERIFY_ADDENDUM_2026-08-21.md` - independent verification addendum.
- `scratch/stress_audit_response_20260821.py` - scratch-only measurement response.
- `scratch/stress_audit_response_20260821_report.md` - refreshed measured report.

Purpose:

- Recheck the audit claims rather than debating them.
- Treat lag-1 regime labels as the live-causal fix for a 10:20 entry.
- Recompute Stress standalone variants, event WFO, same-symbol overlap, risk/cap basis, and live bar-cut behavior after that fix.

Findings confirmed:

1. **Same-day Stress labels were lookahead for 10:20.**
   - The prior Stress table used labels from the same day's SPY close.
   - At 10:20, live can only know the prior session's label unless a separate intraday Stress detector exists.
   - Lag-1 labels are therefore the correct causal comparison for this sleeve.

2. **Headline Stress result falls materially under lag-1 labels.**

| Window | Variant | Lag-0 Net/PF | Lag-1 causal Net/PF |
|---|---|---:|---:|
| 2018-2024 floor | `breadth3_mnq_mes` | +$2,749 / 1.49 | +$776 / 1.14 |
| 2018-2024 floor | `wide3_mnq_mes` | +$2,588 / 1.60 | +$1,538 / 1.38 |
| 2025 OOS | `breadth3_mnq_mes` | +$4,095 / 7.10 | +$3,246 / 5.08 |
| 2025 OOS | `wide3_mnq_mes` | +$3,622 / 10.67 | +$3,680 / 11.17 |
| 2026 to 2026-08-19 | `breadth3_mnq_mes` | 0 trades | 2 trades, -$534 |
| 2026 to 2026-08-19 | `wide3_mnq_mes` | 0 trades | 2 trades, -$534 |

3. **The prior event WFO did not support the promoted primary.**
   - Lag-0 WFO selected `late_cont_break`, `rr25`, or `wide3_mnq_mes`, never `breadth3_mnq_mes`.
   - Lag-1 replacement WFO on floor:
     - held-out net +$571,
     - positive folds 4/9,
     - picks: `wide3_mnq_mes` 5, `rr25` 2, `delay1025` 2,
     - `breadth3_mnq_mes` again selected 0 times.
   - Independent addendum makes this worse than the headline:
     - E009 alone contributes +$1,422, or 248% of the total held-out net.
     - Removing E009 leaves -$849.
     - 2 of 9 folds have zero trades; among folds that trade, only 4/7 are positive.
     - The final four folds all select `wide3_mnq_mes` and return about -$1,012.
   - This fails the pre-commitment that no single event/year-like bucket should contribute more than half the total. It also rejects centering the next rule on `wide3_mnq_mes`: wide3 looks better in the aggregate lag-1 table, but the fold view does not support it.

4. **Fill/timing remains clean after the lag-1 fix.**
   - For `breadth3_mnq_mes`: `outside_exit_bar=0`, `signal_after_entry=0`, `same_bar_exit=0` in floor, 2025, and 2026.
   - So the rejection is not an impossible-fill issue.

5. **Same-symbol overlap remains a blocker.**

Measured using lag-1 Stress trades and current swing labels:

| Window | Variant | Swing already held same symbol | Opposite direction |
|---|---|---:|---:|
| floor | `breadth3_mnq_mes` | 59/78 | 34/78 |
| floor | `wide3_mnq_mes` | 41/57 | 27/57 |
| 2025 | `breadth3_mnq_mes` | 12/19 | 8/19 |
| 2025 | `wide3_mnq_mes` | 8/15 | 6/15 |
| 2026 | both | 2/2 | 0/2 |

Interpretation:

- Same-symbol conflict is still a common live blocker.
- The original lag-0 PnL-concentration claim is no longer the right evidence after lag-1 repair. On lag-1, opposite-conflict legs net close to flat in floor, but that is cancellation, not safety.
- Gross conflicted exposure remains large:
  - floor `breadth3_mnq_mes`: 34/78 opposite legs across 24 distinct conflict days; gross conflicted PnL about $5,486.
  - floor `wide3_mnq_mes`: 27/57 opposite legs across 18 distinct conflict days; gross conflicted PnL about $4,703.
- Stress cannot be papered until same-symbol overlap is blocked or the sleeve has separate account/position/stop ownership.

6. **The high-cap Stress narrative was wrong.**
   - True stop risk is based on the intraday swing-high stop, not `2.5x daily ATR`.
   - Lag-1 true stop-risk max per day:
     - floor: $664, about 1.3% of a $50k account,
     - 2025: $858, about 1.7%,
     - 2026: $524, about 1.0%.
   - The ATR proxy overstates median risk by about 9x-13x.
   - With true stop risk, 2.5% cap admits max-concurrent-2; high 7.5%-10% Stress cap should be dropped from the candidate narrative.

7. **Live bar cut at 10:15 is confirmed broken for this candidate.**
   - Using lag-1 labels and `entry_signals`:
     - floor `breadth3`: cut 10:15 = 0 signals; cut 10:20 = 41 days / 78 legs.
     - 2025 `breadth3`: cut 10:15 = 0 signals; cut 10:20 = 10 days / 19 legs.
     - 2026 `breadth3`: cut 10:15 = 0 signals; cut 10:20 = 1 day / 2 legs.
   - Live path must supply bars through at least 10:20 before this candidate can even be evaluated.

Updated Stress verdict after addendum:

- **Stop Stress as a paper/deploy candidate for now. Keep as research hedge only.**
- Do not start production deploy plumbing for Stress yet.
- The old primary `breadth3_mnq_mes` is no longer promoted after causal-label repair.
- `wide3_mnq_mes` has the best aggregate lag-1 table, but the fold view rejects centering on it: lag-1 WFO is -$849 without E009, and the final four folds that select wide3 lose about -$1,012.
- 2025 remains strong under lag-1, but it is one short six-week-like episode and cannot override weak floor/WFO evidence.

Next valid Stress step:

1. Default to stopping Stress promotion after lag-1 repair.
2. If continuing anyway, predeclare a causal event-WFO acceptance gate before testing more variants. Minimum gate:
   - positive held-out total after removing the single best event cluster,
   - no single event cluster contributes more than 50% of held-out net,
   - final folds do not deteriorate after selection converges,
   - promoted primary is selected by its own folds, not justified by another strategy family's folds.
3. Only if that survives, specify same-symbol overlap policy before any combo/deploy gate:
   - block Stress when same symbol is already open in another sleeve,
   - or separate account/position ownership,
   - or reject paper deployment.

### Swing regime-label causality audit - 2026-08-21

Artifacts:

- `scratch/swing_label_causality_audit_20260821.py` - scratch-only measurement harness.
- `scratch/swing_label_causality_audit_20260821_report.md` - measured report.

Purpose:

- Follow up on the Stress audit caveat that `label_regimes` is stack-wide, not Stress-only.
- Measure whether R4 swing baseline depends materially on same-day HMM labels that are not fully knowable until the 16:00 SPY close, while swing entries can occur from 14:00 to 15:55.
- Do not modify production code.

Method:

- `lag0` = current `label_regimes` output.
- `lag1` = previous available label, applied only to R4 swing.
- Combined deploy replay keeps NKD on its existing `RegimeLabels(..., lag_days=1)` path.
- Costs and windows use the existing harness settings.

R4 swing 1-micro results:

| Window | Lag0 Net/PF/Calmar | Lag1 Net/PF/Calmar | Read |
|---|---:|---:|---|
| floor | +$34,699 / 1.34 / 0.77 | +$37,785 / 1.38 / 0.83 | lag-1 improves |
| vault2324 | +$8,122 / 1.32 / 1.26 | +$11,589 / 1.46 / 1.83 | lag-1 improves |
| vault2025 | +$7,060 / 1.33 / 0.87 | +$8,536 / 1.38 / 0.96 | lag-1 improves, MaxDD higher |
| vault2026 | +$1,699 / 1.10 / 0.61 | +$3,560 / 1.24 / 1.56 | lag-1 improves |

Combined deploy replay, R4 labels varied and NKD held causal:

| Window | Lag0 Net/PF/Calmar | Lag1 Net/PF/Calmar | Read |
|---|---:|---:|---|
| floor | +$42,565 / 1.53 / 1.65 | +$45,811 / 1.58 / 1.77 | not invalidated |
| vault2324 | +$10,757 / 1.50 / 2.86 | +$13,828 / 1.66 / 3.66 | improves |
| vault2025 | +$7,448 / 1.56 / 2.58 | +$7,426 / 1.52 / 2.22 | roughly flat, worse Calmar |
| vault2026 | +$3,017 / 1.29 / 1.36 | +$3,108 / 1.31 / 1.51 | roughly flat/slightly better |

Trade-day movement:

| Window | Label flips | Lag0-only trade days / PnL | Lag1-only trade days / PnL |
|---|---:|---:|---:|
| floor | 147 | 56 / +$877 | 61 / +$1,316 |
| vault2324 | 46 | 22 / -$419 | 24 / +$1,172 |
| vault2025 | 31 | 14 / +$491 | 10 / -$1,181 |
| vault2026 | 20 | 11 / -$2,751 | 9 / +$170 |

Interpretation:

- This does **not** invalidate the R4 swing baseline the way it invalidated the Stress sleeve. Lag-1 repair does not reduce floor/OOS edge; floor combined improves from +$42.6k to +$45.8k.
- It is still not a harmless no-op: label flips move dozens of trade days, and 2025 combined Calmar falls from 2.58 to 2.22 because MaxDD rises.
- The live/research convention is inconsistent today: R4 swing uses raw `label_regimes`, while NKD deliberately wraps labels with `RegimeLabels(lag_days=1)`.

Verdict:

- **Swing baseline is not rejected by lag-1 causality repair.**
- Treat same-day R4 labels as quantified measurement debt, not a deployment-killer from this pass.
- Before the next baseline refresh or paper gate, decide explicitly whether R4 should follow the NKD convention and use prior-available regime labels in both research and live paths.

### Stress causal excavation pass 3 - 2026-08-21

Artifacts:

- `scratch/stress_causal_excavation_pass3_20260821.py` - scratch-only causal Stress excavation harness.
- `scratch/stress_causal_excavation_pass3_20260821_report.md` - measured report.

Purpose:

- Continue Stress research without rescuing the invalid lag-0 setup.
- Use lag-1 regime labels only.
- Test only features known at or before entry:
  - `breadth3` / `wide3`,
  - MNQ-only / MES-only,
  - RR 1.5 / 2.0 / 2.5,
  - exits 12:00 / 14:00 / 15:55,
  - 10:25 delay,
  - late continuation break,
  - partial 1R plus runner 2.5R,
  - crash-only / no-bear subtype filters,
  - breadth/range strength filters,
  - stop-width filters.

Predeclared acceptance gate:

- held-out event-WFO total must stay positive after removing the single best cluster,
- no single cluster may contribute more than 50% of held-out net,
- final four folds must not be negative after selection converges,
- promoted primary must be selected by its own folds, not by another strategy family's folds.

Standalone lag-1 rows looked better, but remained weak:

| Candidate | Floor trades | Clusters | Net | PF | Calmar | MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| `exit1555__no_bear` | 63 | 12 | +$2,695 | 1.59 | 0.33 | $1,730 |
| `rr25__no_bear` | 63 | 12 | +$2,522 | 1.59 | 0.28 | $1,871 |
| `exit1555__crash_only` | 57 | 10 | +$2,440 | 1.57 | 0.34 | $1,516 |
| `exit1555__range_ge_100bp` | 33 | 7 | +$2,175 | 1.95 | 0.71 | $812 |
| `rr25__crash_only` | 57 | 10 | +$2,124 | 1.53 | 0.27 | $1,658 |

Floor event-WFO after causal filters:

| WFO set | Held-out net | Best cluster | Net without best | Best share | Final 4 folds | Positive folds | Pass |
|---|---:|---:|---:|---:|---:|---:|---|
| full mined candidate set | +$618 | +$1,912 | -$1,294 | 310% | -$795 | 3/9 | no |
| restricted predeclared family | +$270 | +$1,215 | -$945 | 450% | -$1,013 | 4/9 | no |

OOS read:

- 2025 remains visually strong, but has only 3-4 event clusters. Its WFO gate cannot pass because the single available held-out fold is 100% of the total.
- 2026 remains negative or empty for the same candidate families; the causal 2026 Stress event is still the 2026-04-07 stop-out.

Interpretation:

- The pass found better standalone Stress filters, especially `exit1555__no_bear` and range-gated variants.
- They do **not** become deploy candidates because event-WFO still fails concentration and end-of-sample stability.
- The attractive rows should be treated as event-cluster mining, not robust hedge evidence.

Verdict:

- **No deploy-level Stress candidate found.**
- Keep Stress as research-only.
- Do not spend production or combo-plumbing time on Stress unless a future pass starts from a predeclared intraday Stress detector and passes the event-WFO concentration gate.

### Stress intraday detector excavation - 2026-08-21

Artifacts:

- `scratch/stress_intraday_detector_excavation_20260821.py` - scratch-only intraday detector harness.
- `scratch/stress_intraday_detector_excavation_20260821_report.md` - measured report.

Purpose:

- Stop forcing Stress research to be the daily-label 10:20 sleeve.
- Test intraday-only detectors that do **not** use daily Stress labels at all.
- Inputs are known by the signal time:
  - cross-index below-open and below-VWAP breadth,
  - opening range expansion,
  - gap-down breadth,
  - breakdown through the morning low.

Core detector set:

- Early liquidation shorts at 09:45 / 10:00 / 10:20 / 10:45.
- `below_count >= 3` and `below_count >= 4` variants.
- Wide-range and gap-down variants.
- Late breakdown variants after the morning low.
- RR 1.5 to 14:00 and RR 2.0 to 15:55 representatives.

Headline standalone results:

| Detector | Floor Net/PF | 2025 Net/PF | 2026 Net/PF | Read |
|---|---:|---:|---:|---|
| `liq_1020_b3_rr15_x1400` | +$15,396 / 1.32 | +$5,778 / 1.64 | -$1,636 / 0.81 | fails 2026 |
| `liq_1000_b3_rr15_x1400` | +$14,728 / 1.30 | +$6,875 / 1.70 | -$536 / 0.94 | weak 2026 |
| `liq_0945_b3_rr15_x1400` | +$14,299 / 1.32 | +$8,014 / 1.96 | -$574 / 0.93 | weak 2026 |
| `liq_1020_b4_rr2_x1555` | +$10,982 / 1.27 | +$6,952 / 2.14 | +$2,776 / 1.57 | static candidate survives all windows |
| `liq_1045_b3_rr2_x1555` | +$7,922 / 1.14 | +$3,078 / 1.33 | +$2,115 / 1.28 | weaker floor, survives OOS |

Event-WFO / concentration:

| Window | WFO net | Net without best | Final 4 folds | Pass |
|---|---:|---:|---:|---|
| floor | +$6,526 | +$5,021 | $0 | yes |
| 2025 | +$1,486 | +$485 | +$340 | no, best cluster still too concentrated |
| 2026 | -$1,108 | -$2,134 | $0 | no |

Interpretation:

- This is the first Stress-adjacent pass that finds a materially better branch outside the daily-label sleeve.
- It is **not** yet a deployable Stress sleeve:
  - the best broad liquidation rules trade hundreds to thousands of legs, so they are intraday short-alpha candidates, not sparse crisis hedges;
  - the WFO selector still fails in 2026;
  - same-symbol interaction with Normal/Calm is probably much larger than the old sparse Stress sleeve and remains unmeasured here.
- The one static rule worth preserving for the next audit is `liq_1020_b4_rr2_x1555`: full-basket below-open/below-VWAP breadth at 10:20, enter short MNQ/MES, RR 2.0, exit by 15:55, no daily Stress label.

Next gate for this new branch:

1. Freeze `liq_1020_b4_rr2_x1555` before further tuning.
2. Run fill/timing audit and same-symbol overlap against swing/Calm.
3. Measure by year, by instrument, by event cluster, and bootstrap on day/event PnL.
4. Reject if 2026 static survival disappears after overlap blocking, realistic slippage, or cap.

### Stress intraday static candidate audit - 2026-08-21

Artifacts:

- `scratch/stress_intraday_static_audit_20260821.py` - scratch-only static candidate audit.
- `scratch/stress_intraday_static_candidate_audit_20260821_report.md` - measured report.

Frozen candidate audited:

- `liq_1020_b4_rr2_x1555`
- No daily Stress label.
- Full R4 breadth below open and VWAP using the 5-minute bar stamped 10:20.
- Short MNQ/MES, RR 2.0, exit 15:55.

Critical correction:

- The 5-minute bar stamped 10:20 is a left-labeled 10:20-10:24 bar.
- Therefore the as-measured rule entering at 10:20 uses information not known until 10:25.
- The original standalone headline for this rule must be discarded unless entry is delayed to 10:25.

Timing audit:

| Window | Version | Trades | Net | PF | Calmar | signal_after_entry | same_bar_exit | outside_exit_bar |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| floor | as measured | 699 | +$10,982 | 1.27 | 0.57 | 699 | 0 | 0 |
| floor | causal delay 10:25 | 692 | +$3,411 | 1.08 | 0.11 | 0 | 0 | 0 |
| 2025 | as measured | 86 | +$6,952 | 2.14 | 5.38 | 86 | 0 | 0 |
| 2025 | causal delay 10:25 | 83 | +$4,088 | 1.65 | 3.32 | 0 | 0 | 0 |
| 2026 | as measured | 51 | +$2,776 | 1.57 | 3.36 | 51 | 0 | 0 |
| 2026 | causal delay 10:25 | 48 | +$1,743 | 1.31 | 1.93 | 0 | 0 | 0 |

Same-symbol overlap with current swing:

| Window | Version | Held same symbol | Opposite legs | Conflict days | Opposite gross PnL |
|---|---|---:|---:|---:|---:|
| floor | causal delay 10:25 | 291/692 | 168/692 | 113 | $25,935 |
| 2025 | causal delay 10:25 | 34/83 | 25/83 | 15 | $4,880 |
| 2026 | causal delay 10:25 | 23/48 | 12/48 | 8 | $3,913 |

Same-symbol overlap with Calm candidate `on_neg_fade_mod001_010_x1555` saved logs:

| Window | Version | Held same symbol | Opposite legs | Conflict days | Opposite gross PnL |
|---|---|---:|---:|---:|---:|
| floor | causal delay 10:25 | 63/692 | 63/692 | 39 | $6,123 |
| 2025 | causal delay 10:25 | 8/83 | 8/83 | 5 | $1,731 |
| 2026 | causal delay 10:25 | 3/48 | 3/48 | 2 | $735 |

Event bootstrap for causal delay 10:25:

| Window | Events | p_pos | 5th pct | Median | 95th pct |
|---|---:|---:|---:|---:|---:|
| floor | 237 | 72% | -$6,140 | +$3,338 | +$13,135 |
| 2025 | 31 | 94% | -$93 | +$4,097 | +$8,373 |
| 2026 | 19 | 69% | -$3,821 | +$1,746 | +$7,131 |

Interpretation:

- The promising static detector was partly a timing artifact. Causal entry at 10:25 keeps OOS positive, but the floor edge becomes thin.
- Floor causal PF is only 1.08 and 3x slippage stress leaves roughly +$959 before any overlap blocking.
- Opposite same-symbol overlap is again an operational blocker, now much larger in count than the sparse daily-label Stress sleeve. Swing overlap is the main blocker; Calm overlap is smaller but still directly opposite because Calm is long and this detector is short.
- The rule is no longer a deploy candidate. At best it is a research clue: broad 10:20 liquidation breadth may contain information, but the executable version needs a cleaner entry design or an earlier causal detector.

Verdict:

- **Reject `liq_1020_b4_rr2_x1555` as a paper/deploy candidate.**
- Keep only as research evidence that cross-index intraday liquidation breadth is worth studying.
- Next valid research branch, if any: use a fully closed earlier bar such as 10:15 with 10:20 entry, or a 10:20 signal with mandatory 10:25 entry, and require floor PF materially above 1.08 after overlap/slippage.

### Stress intraday 10:15-close causal pass - 2026-08-21

Artifacts:

- `scratch/stress_intraday_1015_causal_pass_20260821.py` - scratch-only causal detector harness.
- `scratch/stress_intraday_1015_causal_floor_20260821_report.md` - floor report.
- `scratch/stress_intraday_1015_causal_oos_20260821_report.md` - 2025/2026 report.

Scope:

- No daily Stress label is used.
- Signal uses the fully closed 5-minute bar stamped 10:15, known at 10:20.
- Entry is the 10:20 1-minute open.
- All tested rows have `signal_after_entry=0` and `same_bar_exit=0`.
- This is the clean causal repair of the prior invalid 10:20-bar detector, not another lag-0 daily-label test.

Candidate table:

| Window | Variant | Trades | Net | PF | Calmar | MaxDD | 2x slip net | 3x slip net | Timing |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| floor | `causal1015_b3_rr2_x1555` | 1099 | +$7,227 | 1.11 | 0.23 | $4,215 | +$5,230 | +$3,232 | 0/0 |
| floor | `causal1015_b4_mnq_rr2_x1555` | 327 | +$1,570 | 1.06 | 0.09 | $2,440 | +$1,243 | +$916 | 0/0 |
| floor | `causal1015_b4_rr2_x1555` | 671 | +$1,229 | 1.03 | 0.04 | $4,624 | +$42 | -$1,145 | 0/0 |
| floor | `causal1015_b4_rr15_x1400` | 671 | -$787 | 0.98 | -0.03 | $3,892 | -$1,974 | -$3,161 | 0/0 |
| floor | `causal1015_b4_wide3_rr2_x1555` | 207 | -$1,232 | 0.94 | -0.03 | $5,728 | -$1,607 | -$1,982 | 0/0 |
| 2025 | `causal1015_b4_rr2_x1555` | 88 | +$5,322 | 1.80 | 4.67 | $1,170 | +$5,167 | +$5,011 | 0/0 |
| 2025 | `causal1015_b3_rr2_x1555` | 137 | +$4,955 | 1.49 | 2.22 | $2,288 | +$4,705 | +$4,456 | 0/0 |
| 2026 | `causal1015_b4_mnq_rr2_x1555` | 18 | -$339 | 0.88 | -0.65 | $897 | -$357 | -$375 | 0/0 |
| 2026 | `causal1015_b3_rr2_x1555` | 74 | -$1,188 | 0.88 | -0.43 | $4,421 | -$1,324 | -$1,459 | 0/0 |
| 2026 | `causal1015_b4_rr2_x1555` | 40 | -$1,754 | 0.68 | -1.45 | $2,097 | -$1,827 | -$1,900 | 0/0 |

WFO/concentration:

| Window | WFO total | Best fold | Without best | Final 4 folds | Pass |
|---|---:|---:|---:|---:|---|
| floor | +$2,076 | +$1,806 | +$270 | -$1,064 | False |
| 2025 | -$2,029 | +$584 | -$2,613 | $0 | False |
| 2026 | -$2,948 | +$1,275 | -$4,223 | -$1,710 | False |

Same-symbol overlap:

| Window | Variant | Swing opposite | Swing conflict days | Swing opposite gross | Calm opposite | Calm conflict days | Calm opposite gross |
|---|---|---:|---:|---:|---:|---:|---:|
| floor | `causal1015_b3_rr2_x1555` | 269/1099 | 191 | $38,791 | 96/1099 | 63 | $8,618 |
| floor | `causal1015_b4_rr2_x1555` | 167/671 | 112 | $25,325 | 51/671 | 31 | $4,995 |
| 2025 | `causal1015_b4_rr2_x1555` | 20/88 | 13 | $3,614 | 7/88 | 4 | $1,285 |
| 2026 | `causal1015_b4_rr2_x1555` | 7/40 | 5 | $1,647 | 2/40 | 1 | $310 |

Read:

- The causal timing repair works mechanically: the detector can be reproduced live at 10:20 without using a future 5-minute bar.
- The edge does **not** survive as a deploy candidate. The broadest floor row is only PF 1.11 and fails WFO deterioration; the stricter `b4` row is PF 1.03 and is effectively flat at 2x slippage.
- 2025 remains strong, but 2026 rejects every tested rule. That is exactly the pattern the predeclared gate was designed to reject.
- Same-symbol overlap with current swing/Calm remains large enough that even a stronger standalone row would still need explicit broker/netting design.

Verdict:

- **Reject the fully causal 10:15-close -> 10:20-entry intraday Stress branch as a paper/deploy candidate.**
- Keep only the mechanism clue: early cross-index liquidation breadth has some crisis-window information, but the measurable edge is too thin and unstable once timing, WFO, slippage, and overlap are enforced.
- Do not continue tuning this branch for deployment. Any future Stress work should start from a genuinely new hypothesis, not more parameter search around the 10:15/10:20 liquidation detector.

### Stress new hypothesis pass - 2026-08-21

Artifacts:

- `scratch/stress_new_hypothesis_pass_20260821.py` - scratch-only new hypothesis harness.
- `scratch/stress_new_hypothesis_floor_20260821_report.md` - floor report.
- `scratch/stress_new_hypothesis_oos_20260821_report.md` - 2025/2026 report.

Scope:

- No daily Stress label.
- No 10:15/10:20 breadth-entry tuning.
- Hypotheses tested:
  - `late_break`: morning stress is not traded immediately; enter SHORT only if price breaks the morning low after 11:00 or 11:30.
  - `midday_expansion`: enter SHORT only on a fresh range break after noon.
  - `failed_stress_reclaim`: morning stress then VWAP reclaim after 11:30, LONG, included as a non-hedge control.
- All rows have `signal_after_entry=0` and `same_bar_exit=0`.

Main table:

| Window | Variant | Direction | Trades | Net | PF | Calmar | MaxDD | 2x slip | 3x slip | Bootstrap p_pos / p5 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| floor | `late_break_1100_b3_rr2_x1555` | SHORT | 378 | +$4,916 | 1.20 | 0.22 | $2,778 | +$4,160 | +$3,404 | 0.85 / -$2,844 |
| floor | `midday_expansion_1200_b3_rr2_x1555` | SHORT | 353 | +$3,448 | 1.21 | 0.24 | $1,791 | +$2,742 | +$2,036 | 0.83 / -$2,312 |
| floor | `late_break_1100_b4_rr2_x1555` | SHORT | 295 | +$3,367 | 1.18 | 0.14 | $2,944 | +$2,777 | +$2,187 | 0.78 / -$3,273 |
| floor | `failed_stress_reclaim_1130_b3_long_x1555` | LONG | 275 | +$2,016 | 1.13 | 0.15 | $1,682 | +$1,466 | +$916 | 0.72 / -$3,107 |
| floor | `late_break_1130_b3_rr2_x1555` | SHORT | 336 | -$109 | 0.99 | -0.00 | $3,302 | -$781 | -$1,453 | 0.51 / -$6,241 |
| 2025 | `late_break_1100_b3_rr2_x1555` | SHORT | 65 | +$2,182 | 1.37 | 1.02 | $2,163 | +$2,052 | +$1,922 | 0.74 / -$3,364 |
| 2025 | `midday_expansion_1200_b3_rr2_x1555` | SHORT | 51 | -$187 | 0.96 | -0.10 | $1,958 | -$289 | -$391 | 0.47 / -$3,620 |
| 2026 | `late_break_1100_b3_rr2_x1555` | SHORT | 37 | -$654 | 0.86 | -0.41 | $2,504 | -$728 | -$802 | 0.40 / -$4,789 |
| 2026 | `midday_expansion_1200_b3_rr2_x1555` | SHORT | 44 | -$947 | 0.76 | -1.07 | $1,399 | -$1,035 | -$1,123 | 0.33 / -$4,309 |
| 2026 | `failed_stress_reclaim_1130_b3_long_x1555` | LONG | 35 | +$1,093 | 1.43 | 1.89 | $917 | +$1,023 | +$953 | 0.77 / -$1,131 |

WFO/concentration:

| Window | WFO total | Best fold | Without best | Final 4 folds | Positive folds | Folds | Pass |
|---|---:|---:|---:|---:|---:|---:|---|
| floor | -$650 | +$1,030 | -$1,679 | $0 | 72 | 216 | False |
| 2025 | -$3,098 | +$423 | -$3,521 | $0 | 4 | 25 | False |
| 2026 | -$1,328 | +$342 | -$1,670 | -$673 | 3 | 16 | False |

Read:

- The best genuinely new SHORT clue is `late_break_1100_b3_rr2_x1555`: do not short the first liquidation print; wait until after 11:00 for a fresh morning-low break. It is causal, survives 2025, and keeps positive net after 3x slippage on floor.
- It still fails the gate: 2026 is negative, 2023-2024 are negative in the floor split, and the event WFO selector loses money on floor and OOS.
- `midday_expansion_1200_b3_rr2_x1555` has better floor drawdown shape than the old 10:15 branch but fails both 2025 and 2026 OOS.
- The only 2026-positive rule is the LONG reclaim control. That is not a Stress hedge sleeve; it is closer to an intraday reversal/mean-reversion clue and should not be used to rescue the Stress hedge thesis.

Verdict:

- **No deploy-level Stress candidate from the new-hypothesis pass.**
- Keep `late_break_1100_b3_rr2_x1555` as a named research clue only.
- If Stress work continues, the next pass should be externally motivated event logic, not parameter search: for example, calendar/news shock taxonomy, overnight gap/liquidity shock with predeclared entry family, or account-level crash-hedge overlay measured as insurance rather than standalone alpha.

### Stress new hypothesis pass 2 - 2026-08-21

Artifacts:

- `scratch/stress_new_hypothesis_pass2_20260821.py` - scratch-only pass.
- `scratch/stress_new_hypothesis_pass2_floor_gap_20260821_report.md` - floor gapdown subset.
- `scratch/stress_new_hypothesis_pass2_floor_late_20260821_report.md` - floor VWAP/late-day subset.
- `scratch/stress_new_hypothesis_pass2_oos_20260821_report.md` - 2025/2026 report.

Scope:

- No daily Stress label.
- No 10:15/10:20 or 11:00 late-break tuning from the prior pass.
- New mechanisms:
  - `gapdown_break`: overnight/RTH gap-down shock, then short only on post-setup morning-low break.
  - `vwap_reject`: gap-down stress, rally touches VWAP, then fails back through the setup low.
  - `late_day_break`: late-session breakdown after a gap-down stress day.
- All measured rows have `signal_after_entry=0` and `same_bar_exit=0`.

Main table:

| Window | Variant | Trades | Net | PF | Calmar | MaxDD | 2x slip | 3x slip | Bootstrap p_pos / p5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| floor | `gapdown_break_1030_b3_rr2_x1555` | 152 | +$1,776 | 1.17 | 0.09 | $2,607 | +$1,472 | +$1,168 | 0.70 / -$3,051 |
| floor | `gapdown_break_1130_b3_rr2_x1555` | 120 | +$306 | 1.04 | 0.01 | $2,746 | +$66 | -$174 | 0.56 / -$3,918 |
| floor | `vwap_reject_1200_b3_rr2_x1555` | 17 | +$161 | 1.40 | 0.08 | $259 | +$127 | +$93 | 0.68 / -$383 |
| floor | `late_day_break_1400_b3_rr2_x1555` | 82 | -$236 | 0.93 | -0.02 | $1,523 | -$400 | -$564 | 0.42 / -$2,514 |
| floor | `late_day_break_1400_b4_rr2_x1555` | 60 | -$933 | 0.63 | -0.09 | $1,230 | -$1,053 | -$1,173 | 0.16 / -$2,438 |
| 2025 | `gapdown_break_1030_b3_rr2_x1555` | 10 | +$781 | 1.90 | 0.93 | $845 | +$761 | +$741 | 0.74 / -$1,408 |
| 2025 | `gapdown_break_1130_b3_rr2_x1555` | 10 | -$1,477 | 0.20 | -0.92 | $1,621 | -$1,497 | -$1,517 | 0.06 / -$3,158 |
| 2026 | `gapdown_break_1130_b3_rr2_x1555` | 3 | +$1,513 | 14.91 | 22.09 | $109 | +$1,507 | +$1,501 | 0.74 / -$217 |
| 2026 | `late_day_break_1400_b3_rr2_x1555` | 8 | +$257 | 1.96 | 1.52 | $267 | +$241 | +$225 | 0.73 / -$322 |
| 2026 | `gapdown_break_1030_b3_rr2_x1555` | 9 | -$253 | 0.69 | -0.75 | $534 | -$271 | -$289 | 0.39 / -$1,338 |

WFO/concentration:

| Subset/window | WFO total | Best fold | Without best | Final 4 | Positive folds | Folds | Pass |
|---|---:|---:|---:|---:|---:|---:|---|
| floor gapdown subset | -$51 | +$869 | -$920 | +$630 | 30 | 78 | False |
| floor VWAP/late-day subset | -$703 | +$554 | -$1,256 | -$324 | 21 | 59 | False |
| 2025 all pass2 | $0 | $0 | $0 | $0 | 0 | 3 | False |
| 2026 all pass2 | $0 | $0 | $0 | $0 | 0 | 0 | False |

Read:

- The only interesting clue is conditional: `gapdown-full-breadth` does the work, while plain `gapdown` loses money in the best floor row. For `gapdown_break_1030_b3`, floor `gapdown-full-breadth` is +$3,892 and plain `gapdown` is -$2,116.
- That clue is too sparse and too fragile to promote. OOS has only 10 trades in 2025 for the 10:30 version and only 3 trades in 2026 for the 11:30 version.
- `vwap_reject` is tiny on floor and has no OOS trades in this pass.
- `late_day_break` is negative on floor despite a small positive 2026 sample.

Verdict:

- **No deploy-level Stress candidate from pass 2.**
- Keep one research note: overnight gap-down plus full cross-index breadth may identify better event quality than intraday breadth alone.
- Do not parameter-search this result. A valid next pass would need an event taxonomy around gap shocks and full-breadth confirmation, with the rule frozen before reading OOS.

### STRESS_MID legacy status after audit - 2026-08-21

Artifact:

- `scratch/stress_mid_legacy_status_20260821.py`
- `scratch/stress_mid_legacy_status_20260821_report.md`

Scope:

- Current legacy engine: `futures/stress_mid.py::StressMidEngine`.
- Compare current lag-0 research labels against lag-1 live-causal labels.
- Timing column treats the 5-minute bar stamped 10:15 as known only at 10:20.

Measured status:

| Window | Label basis | Trades | Days | Net | PF | Calmar | MaxDD | signal_after_entry |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| floor | lag0 current backtest | 183 | 61 | +$3,700 | 1.38 | 0.13 | $3,670 | 183 |
| floor | lag1 live-causal | 171 | 56 | +$1,313 | 1.14 | 0.06 | $2,802 | 171 |
| 2025 | lag0 current backtest | 38 | 14 | +$4,033 | 2.90 | 4.06 | $999 | 38 |
| 2025 | lag1 live-causal | 40 | 14 | +$3,998 | 3.13 | 4.03 | $999 | 40 |
| 2026 | lag0 current backtest | 1 | 1 | -$64 | 0.00 | -1.59 | $64 | 1 |
| 2026 | lag1 live-causal | 5 | 2 | -$779 | 0.00 | -1.59 | $779 | 5 |

Read:

- `STRESS_MID` is **not usable as a clean paper/deploy sleeve right now**.
- The causal label repair cuts floor from +$3,700 PF 1.38 to +$1,313 PF 1.14.
- 2025 still looks good, but 2026 is worse under lag-1.
- Timing is still not clean if the engine is interpreted as entering at the 10:15 5-minute bar. The bar stamped 10:15 is not fully known until 10:20.
- The live cron is already disabled for broker/netting reasons, and the audit evidence supports keeping it disabled.

Verdict:

- **Keep `STRESS_MID` disabled as a live/paper sleeve.**
- Do not spend engineering time on re-enabling the cron or broker plumbing for this rule.
- Preserve it only as historical context and as evidence that Stress detectors may have value as risk-off filters.

### Stress-as-filter probe - 2026-08-21

Artifacts:

- `scratch/stress_as_filter_probe_20260821.py`
- `scratch/stress_as_filter_floor_20260821_report.md`
- `scratch/stress_as_filter_oos_20260821_report.md`

Scope:

- Do not trade Stress.
- Use measured Stress detector days as **skip filters** for existing sleeves.
- Filters:
  - `late_break_1100_b3_days`
  - `gapdown_full_breadth_1030_days`
  - union of both.
- Sleeves tested:
  - Normal corrected trade log from the Normal audit.
  - Clean Calm open-location candidate `openloc_lower_third_long_e1000_x1555`.

Calm open-location 10:00 result:

| Window | Filter | Filter days | Skipped trades / PnL | Base net / PF / MaxDD | Kept net / PF / MaxDD | Delta |
|---|---|---:|---:|---|---|---:|
| floor | late break | 244 | 42 / -$3,288 | +$9,049 / 1.41 / $1,706 | +$12,337 / 1.67 / $1,304 | +$3,288 |
| floor | gapdown full breadth | 59 | 20 / -$1,651 | +$9,049 / 1.41 / $1,706 | +$10,700 / 1.53 / $1,418 | +$1,651 |
| floor | union | 266 | 53 / -$3,889 | +$9,049 / 1.41 / $1,706 | +$12,938 / 1.74 / $954 | +$3,889 |
| 2025 | union | 39 | 3 / -$113 | +$5,237 / 4.64 / $603 | +$5,351 / 5.22 / $603 | +$113 |
| 2026 | late break | 24 | 13 / -$1,124 | +$1,485 / 1.44 / $1,300 | +$2,609 / 2.68 / $420 | +$1,124 |
| 2026 | gapdown full breadth | 4 | 5 / -$1,113 | +$1,485 / 1.44 / $1,300 | +$2,598 / 2.14 / $738 | +$1,113 |
| 2026 | union | 25 | 13 / -$1,124 | +$1,485 / 1.44 / $1,300 | +$2,609 / 2.68 / $420 | +$1,124 |

Normal corrected result:

| Window | Filter | Skipped trades / PnL | Base net / PF / MaxDD | Kept net / PF / MaxDD | Delta |
|---|---|---:|---|---|---:|
| floor | union | 213 / +$10,575 | +$31,380 / 1.21 / $16,593 | +$20,804 / 1.17 / $19,618 | -$10,575 |
| 2025 | union | 23 / -$1,805 | +$5,505 / 1.19 / $9,457 | +$7,310 / 1.32 / $9,857 | +$1,805 |
| 2026 | union | 11 / +$4,070 | +$3,236 / 1.10 / $16,404 | -$834 / 0.97 / $16,256 | -$4,070 |

Read:

- This is the first Stress direction that improves a liveable Calm clue across floor and 2026: Stress days are bad entry days for Calm lower-third long.
- The same filter is **not** a global risk-off rule. It damages Normal on floor and 2026 because many Normal trades entered on detector days are profitable.
- Therefore the next valid branch is **Calm-specific Stress filter**, not Stress short sleeve and not account-wide Stress blocking.
- Important timing caveat: `late_break_1100_b3_days` is **not** live-causal as a skip for a 10:00 Calm entry because it fires after 11:00. This probe explains failure days and suggests a possible filter direction; it does not yet define a deployable 10:00 filter.

Verdict:

- **Do not revive any already-tested Stress traded sleeve.**
- Keep Stress-as-filter as **one research direction**, not the replacement for an independent Stress sleeve objective.
- Predeclare the next Calm-filter protocol separately: choose Calm lower-third 10:00 or a delayed Calm entry as base, allow only live-causal filters known before entry, train on floor folds, then test 2025/2026 without tuning.
- If the goal remains an independent Stress sleeve, it must be researched under a separate protocol and must not borrow the Calm-filter evidence as support.

### Independent Stress sleeve objective - still open

The Stress-as-filter result does **not** close the user's preference for a standalone Stress sleeve.
It only says that the tested Stress shorts did not clear deploy gates, while the detector may still
have risk-control value for Calm.

For a future independent Stress sleeve, the predeclared constraints are:

1. It must produce its own trades and PnL, not only skip Calm/Normal entries.
2. It must be live-causal:
   - no same-day HMM label unless the label is known before entry;
   - every intraday signal must declare `known_time`;
   - entry must be strictly after `known_time`.
3. It should avoid same-symbol netting with current R4/Calm where possible, or explicitly measure a separate account/subaccount design.
4. It must pass event-cluster WFO, not only yearly split.
5. It must survive 2x/3x slippage and not rely on 2025 alone.
6. It must be evaluated as both:
   - standalone sleeve; and
   - account-level crash hedge / insurance contribution.

Possible future sleeve directions, separate from the Calm-filter branch:

- **External event taxonomy:** CPI/FOMC/NFP/bank-crisis/news-shock clusters, with rules frozen before OOS.
- **Gap shock sleeve:** overnight gap-down plus full cross-index breadth, but rebuilt as a sparse event hedge with event WFO rather than parameter sweep.
- **Different instrument sleeve:** avoid MNQ/MES/MYM/M2K overlap, or use a separate subaccount, before spending broker plumbing.
- **Insurance overlay:** accept weak standalone PF only if portfolio CVaR/MaxDD improves under a predeclared cost budget.

### Stress gap-shock sleeve rebuild - 2026-08-21

Artifacts:

- `scratch/stress_gapshock_rebuild_20260821.py`
- `scratch/stress_gapshock_rebuild_floor_20260821_report.md`
- `scratch/stress_gapshock_rebuild_oos_20260821_report.md`

Protocol frozen before reading results:

- No daily Stress label.
- Event trigger: overnight/RTH gap-down in at least 3/4 R4 instruments plus 4/4 instruments below open and below VWAP on the 10:30 5-minute bar.
- Treat the 10:30 bar as known at 10:35; entries only from 10:40 onward.
- SHORT only; stop = setup high * 1.001; target 2R; exit 15:55.
- Candidate set limited to:
  - MNQ/MES low-break;
  - MNQ-only low-break;
  - MNQ/MES retest-fail.

Results:

| Window | Variant | Trades | Days/clusters | Net | PF | Calmar | MaxDD | 2x slip | 3x slip | Bootstrap p_pos / p5 | Timing |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| floor | `gapshock_full_breadth_break_1040_mnq_mes_rr2` | 101 | 57 / 51 | +$3,208 | 1.58 | 0.31 | $1,295 | +$3,006 | +$2,804 | 0.90 / -$842 | 0/0 |
| floor | `gapshock_full_breadth_break_1040_mnq_only_rr2` | 46 | 46 / 43 | +$2,554 | 1.98 | 0.48 | $670 | +$2,462 | +$2,370 | 0.97 / +$369 | 0/0 |
| floor | `gapshock_full_breadth_retestfail_1040_mnq_mes_rr2` | 23 | 15 / 15 | +$1,138 | 2.86 | 0.58 | $246 | +$1,092 | +$1,046 | 0.95 / -$40 | 0/0 |
| 2025 | `gapshock_full_breadth_break_1040_mnq_mes_rr2` | 6 | 3 / 3 | +$1,160 | 50.91 | inf | $0 | +$1,148 | +$1,136 | 1.00 / +$496 | 0/0 |
| 2025 | `gapshock_full_breadth_break_1040_mnq_only_rr2` | 3 | 3 / 3 | +$647 | 28.85 | 28.02 | $23 | +$641 | +$635 | 0.97 / +$226 | 0/0 |
| 2026 | `gapshock_full_breadth_break_1040_mnq_mes_rr2` | 8 | 4 / 4 | +$20 | 1.04 | 0.06 | $534 | +$4 | -$12 | 0.60 / -$1,053 | 0/0 |
| 2026 | `gapshock_full_breadth_break_1040_mnq_only_rr2` | 4 | 4 / 4 | -$58 | 0.84 | -0.26 | $359 | -$66 | -$74 | 0.42 / -$713 | 0/0 |

Event WFO:

| Window | WFO total | Best fold | Without best | Final 4 | Positive folds | Folds | Pass |
|---|---:|---:|---:|---:|---:|---:|---|
| floor | +$2,053 | +$944 | +$1,110 | +$624 | 22 | 43 | True |
| 2025 | $0 | $0 | $0 | $0 | 0 | 0 | False / insufficient folds |
| 2026 | $0 | $0 | $0 | $0 | 0 | 0 | False / insufficient folds |

Read:

- This is the **best standalone Stress-sleeve clue so far**. It is live-causal, does not use daily Stress labels, survives 3x slippage on floor, and passes floor event WFO.
- The floor edge is concentrated in MNQ; MNQ-only has better PF and drawdown than MNQ/MES.
- OOS is directionally encouraging in 2025 but extremely sparse: 3 event days.
- 2026 does not confirm it: MNQ/MES is roughly flat before slippage and negative after 3x slippage; MNQ-only is negative.
- Same-symbol overlap/broker interaction was not completed in this pass because rebuilding the swing overlap book timed out. It remains a required gate before any paper discussion.

Verdict:

- **Not deploy-level yet.**
- Promote from "dead Stress sleeve family" to **best research candidate for standalone Stress sleeve**.
- Next gate should be narrow and predeclared:
  1. save exact trade logs for this rule family;
  2. measure swing/Calm same-symbol overlap;
  3. test account-level insurance contribution;
  4. run event bootstrap with fixed event taxonomy;
  5. reject if 2026 remains flat/negative after slippage or if overlap requires a separate subaccount that the edge cannot justify.

### Stress gap-shock controlled expansion - 2026-08-21

Artifacts:

- `scratch/stress_gapshock_expansion_20260821.py`
- `scratch/stress_gapshock_expansion_floor_strict_20260821_report.md`
- `scratch/stress_gapshock_expansion_floor_relax_20260821_report.md`
- `scratch/stress_gapshock_expansion_oos_20260821_report.md`

Purpose: answer whether the strict gap-shock sleeve has too few trades because the trigger is too narrow, and whether controlled relaxation can add sample without destroying edge. This is not a broad parameter sweep; each row relaxes one condition from the strict rebuild.

Floor controlled expansion:

| Variant | Relaxation | Trades | Days/clusters | Net | PF | Calmar | MaxDD | 3x slip | Bootstrap p_pos / p5 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `strict_gap3_below4_mnq` | strict, MNQ only | 46 | 46 / 43 | +$2,554 | 1.98 | 0.48 | $670 | +$2,370 | 0.97 / +$394 |
| `strict_gap3_below4_mnqmes` | strict reference | 101 | 57 / 51 | +$3,208 | 1.58 | 0.31 | $1,295 | +$2,804 | 0.91 / -$756 |
| `smallgap_gap3_below4_mnqmes` | gap threshold -0.25% instead of -0.40% | 141 | 80 / 68 | +$3,554 | 1.45 | 0.26 | $1,685 | +$2,990 | 0.89 / -$1,321 |
| `relax_gap_gap2_below4_mnqmes` | 2/4 gap-down, still 4/4 below | 134 | 76 / 66 | +$3,910 | 1.53 | 0.30 | $1,646 | +$3,374 | 0.91 / -$749 |
| `relax_breadth_gap3_below3_mnqmes` | 3/4 below instead of 4/4 | 142 | 85 / 77 | +$2,040 | 1.23 | 0.13 | $2,017 | +$1,472 | 0.78 / -$2,428 |
| `wide_gap2_below3_mnqmes` | 2/4 gap + 3/4 below + smaller gap | 238 | 142 / 119 | +$3,186 | 1.22 | 0.20 | $1,989 | +$2,234 | 0.79 / -$3,003 |

OOS controlled expansion:

| Window | Variant | Trades | Days/clusters | Net | PF | 3x slip | Bootstrap p_pos / p5 |
|---|---|---:|---:|---:|---:|---:|---|
| 2025 | `smallgap_gap3_below4_mnqmes` | 8 | 4 / 4 | +$1,527 | 66.71 | +$1,495 | 1.00 / +$796 |
| 2025 | `strict_gap3_below4_mnqmes` | 6 | 3 / 3 | +$1,160 | 50.91 | +$1,136 | 1.00 / +$99 |
| 2025 | `wide_gap2_below3_mnqmes` | 16 | 8 / 7 | -$69 | 0.97 | -$133 | 0.49 / -$2,417 |
| 2026 | `strict_gap3_below4_mnqmes` | 8 | 4 / 4 | +$20 | 1.04 | -$12 | 0.61 / -$1,053 |
| 2026 | `smallgap_gap3_below4_mnqmes` | 21 | 11 / 10 | -$10 | 0.99 | -$94 | 0.52 / -$1,832 |
| 2026 | `relax_gap_gap2_below4_mnqmes` | 17 | 9 / 9 | -$809 | 0.53 | -$877 | 0.17 / -$2,337 |
| 2026 | `wide_gap2_below3_mnqmes` | 25 | 14 / 13 | -$2,011 | 0.46 | -$2,111 | 0.12 / -$4,786 |

WFO read:

| Subset | WFO total | Best fold | Without best | Final 4 | Folds | Pass |
|---|---:|---:|---:|---:|---:|---|
| strict/smallgap subset | +$1,029 | +$944 | +$85 | -$133 | 66 | False |
| relaxed subset | +$1,569 | +$1,372 | +$197 | -$1,098 | 122 | False |
| 2026 expansion | -$1,386 | $0 | -$1,386 | -$1,083 | 5 | False |

Read:

- The trade-count problem can be reduced, but not solved safely.
- Relaxing the gap threshold from -0.40% to -0.25% adds sample and keeps 2025 positive, but 2026 remains flat/negative and the bootstrap left tail worsens.
- Relaxing breadth from 4/4 to 3/4 clearly damages the clue. PF falls toward 1.2 on floor and 2026 gets worse.
- The wide row proves the boundary: more trades do not mean better Stress hedge; it turns into noisy short exposure.
- MNQ-only strict remains the cleanest standalone shape on floor, but OOS has only 3-4 event days.

Verdict:

- **Do not widen the gap-shock sleeve just to increase trade count.**
- Keep the strict full-breadth event as the core clue.
- `smallgap_gap3_below4_mnqmes` can remain a sensitivity row, not a promoted candidate.
- The next useful work is not another relaxation pass; it is overlap/account-insurance measurement for strict MNQ-only and strict MNQ/MES, plus external event taxonomy if more independent event sample is required.

### Stress gap-shock volume confirmation - 2026-08-21

Artifacts:

- `scratch/stress_gapshock_volume_20260821.py`
- `scratch/stress_gapshock_volume_oos_20260821_report.md`
- `scratch/stress_gapshock_volume_floor_base_mesmnq_20260821_report.md`
- `scratch/stress_gapshock_volume_floor_break_mesmnq_20260821_report.md`
- `scratch/stress_gapshock_volume_floor_cum_mesmnq_20260821_report.md`
- `scratch/stress_gapshock_volume_floor_both_mesmnq_20260821_report.md`
- `scratch/stress_gapshock_volume_floor_mnq_pair_20260821_report.md`

Purpose: test whether causal volume confirmation improves the strict gap-shock sleeve.

Volume filters:

- `cumvol12`: basket cumulative volume from 09:30-10:30 must have at least 3/4 instruments above 1.2x their prior-day-only rolling 20-session median for the same window.
- `breakvol12`: entry/break bar volume must be at least 1.2x the instrument's prior-day-only rolling 20-session median entry-window bar volume.
- `bothvol12`: both filters.

Results:

| Window | Variant | Trades | Days/clusters | Net | PF | Calmar | MaxDD | 3x slip | Bootstrap p_pos / p5 | Timing |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| floor | `gapshock_mnqmes_base` | 101 | 57 / 51 | +$3,208 | 1.58 | 0.31 | $1,295 | +$2,804 | 0.92 / -$485 | 0/0 |
| floor | `gapshock_mnqmes_breakvol12` | 95 | 54 / 49 | +$2,048 | 1.37 | 0.20 | $1,295 | +$1,668 | 0.82 / -$1,482 | 0/0 |
| floor | `gapshock_mnqmes_cumvol12` | 42 | 24 / 23 | -$458 | 0.85 | -0.04 | $1,469 | -$626 | 0.38 / -$3,256 | 0/0 |
| floor | `gapshock_mnqmes_bothvol12` | 42 | 24 / 23 | -$458 | 0.85 | -0.04 | $1,469 | -$626 | 0.38 / -$3,256 | 0/0 |
| floor | `gapshock_mnq_base` | 46 | 46 / 43 | +$2,554 | 1.98 | 0.48 | $670 | +$2,370 | 0.96 / +$191 | 0/0 |
| floor | `gapshock_mnq_breakvol12` | 43 | 43 / 40 | +$1,744 | 1.67 | 0.33 | $670 | +$1,572 | 0.89 / -$522 | 0/0 |
| 2025 | `gapshock_mnqmes_base` | 6 | 3 / 3 | +$1,160 | 50.91 | inf | $0 | +$1,136 | 1.00 / +$496 | 0/0 |
| 2025 | `gapshock_mnqmes_breakvol12` | 5 | 3 / 3 | +$1,104 | 48.48 | 47.78 | $23 | +$1,084 | 0.97 / +$384 | 0/0 |
| 2025 | `gapshock_mnqmes_cumvol12` | 2 | 1 / 1 | +$430 | inf | inf | $0 | +$422 | 1.00 / +$430 | 0/0 |
| 2026 | `gapshock_mnqmes_base` | 8 | 4 / 4 | +$20 | 1.04 | 0.06 | $534 | -$12 | 0.62 / -$699 | 0/0 |
| 2026 | `gapshock_mnqmes_breakvol12` | 6 | 4 / 4 | -$271 | 0.49 | -0.80 | $534 | -$295 | 0.27 / -$757 | 0/0 |
| 2026 | `gapshock_mnqmes_cumvol12` | 0 | 0 / 0 | $0 | inf | 0.00 | $0 | $0 | 0.00 / $0 | 0/0 |
| 2026 | `gapshock_mnq_breakvol12` | 3 | 3 / 3 | -$291 | 0.19 | -1.28 | $359 | -$303 | 0.03 / -$542 | 0/0 |

Read:

- Volume confirmation does **not** improve the strict gap-shock sleeve.
- Break-bar volume keeps most trades but lowers floor net/PF and makes 2026 worse.
- Cumulative volume is actively bad on floor: it cuts the sample to 42 trades and flips net negative.
- The volume filters do not solve the core issue: OOS event count remains tiny and 2026 remains flat/negative.

Verdict:

- **Reject volume confirmation for this gap-shock sleeve.**
- Keep the price/breadth strict base as the best measured version.
- Do not continue volume rescue on this branch unless a new volume hypothesis is externally motivated and predeclared.

### Stress gap-shock exhaustion / D-1 filters - 2026-08-21

Artifacts:

- `scratch/stress_gapshock_exhaustion_20260821.py`
- `scratch/stress_gapshock_exhaustion_oos_20260821_report.md`
- `scratch/stress_gapshock_exhaustion_floor_d1_20260821_report.md`
- `scratch/stress_gapshock_exhaustion_floor_notdeepgap_20260821_report.md`
- `scratch/stress_gapshock_exhaustion_floor_notextended_20260821_report.md`
- `scratch/stress_gapshock_exhaustion_floor_notdeep_or_ext_20260821_report.md`

Purpose: test whether gap/open quality, 10:30 extension, D-1 crash/weak-close, open location, or MNQ leadership can improve the strict gap-shock sleeve without widening the signal.

Floor:

| Variant | Filter | Trades | Days/clusters | Net | PF | Calmar | MaxDD | 3x slip | Bootstrap p_pos / p5 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `base_mnqmes` | none | 101 | 57 / 51 | +$3,208 | 1.58 | 0.31 | $1,295 | +$2,804 | 0.92 / -$485 |
| `d1_not_crash_mnqmes` | prior day not broad crash | 100 | 56 / 50 | +$3,390 | 1.63 | 0.33 | $1,295 | +$2,990 | 0.94 / -$297 |
| `not_deep_gap_mnqmes` | average gap not worse than -1.2% | 78 | 44 / 41 | +$1,973 | 1.45 | 0.24 | $1,019 | +$1,661 | 0.79 / -$1,494 |
| `not_extended_1030_mnqmes` | 10:30 move not worse than -1.8% from prior close | 74 | 41 / 38 | +$2,018 | 1.48 | 0.23 | $1,119 | +$1,722 | 0.83 / -$1,231 |
| `not_deep_gap_or_extended_mnqmes` | both not-deep filters | 70 | 39 / 37 | +$2,031 | 1.52 | 0.30 | $842 | +$1,751 | 0.84 / -$1,407 |
| `in_prior_range_open_mnqmes` | all opens inside/near prior range | 25 | 15 / 15 | +$3,255 | 7.15 | 1.21 | $337 | +$3,155 | 1.00 / +$1,505 |
| `leadership_mnq_weakest_mnq` | MNQ only when MNQ is weakest at 10:30 | 19 | 19 / 19 | +$1,515 | 2.07 | 0.38 | $504 | +$1,439 | 0.91 / -$412 |
| `d1_close_weak_not_extreme_mnqmes` | D-1 weak close but not extreme | 29 | 15 / 14 | -$294 | 0.84 | -0.03 | $1,170 | -$410 | 0.43 / -$2,128 |

OOS:

| Window | Variant | Trades | Days/clusters | Net | PF | 3x slip | Bootstrap p_pos / p5 |
|---|---|---:|---:|---:|---:|---:|---|
| 2025 | `base_mnqmes` | 6 | 3 / 3 | +$1,160 | 50.91 | +$1,136 | 1.00 / +$496 |
| 2025 | `d1_not_crash_mnqmes` | 6 | 3 / 3 | +$1,160 | 50.91 | +$1,136 | 1.00 / +$496 |
| 2025 | `not_deep_gap_mnqmes` | 4 | 2 / 2 | +$730 | 32.39 | +$714 | 1.00 / +$66 |
| 2025 | `not_extended_1030_mnqmes` | 2 | 1 / 1 | +$697 | inf | +$689 | 1.00 / +$697 |
| 2026 | `base_mnqmes` | 8 | 4 / 4 | +$20 | 1.04 | -$12 | 0.59 / -$1,053 |
| 2026 | `d1_not_crash_mnqmes` | 8 | 4 / 4 | +$20 | 1.04 | -$12 | 0.59 / -$1,053 |
| 2026 | `d1_close_weak_not_extreme_mnqmes` | 2 | 1 / 1 | +$428 | inf | +$420 | 1.00 / +$428 |
| 2026 | `leadership_mnq_weakest_mnq` | 2 | 2 / 2 | +$56 | 1.32 | +$48 | 0.75 / -$353 |
| 2026 | `in_prior_range_open_mnqmes` | 2 | 1 / 1 | -$275 | 0.00 | -$283 | 0.00 / -$275 |

Read:

- Exhaustion filters reduce drawdown but do not improve the sleeve. They cut too much good floor/2025 PnL and leave 2026 effectively unchanged.
- `d1_not_crash_mnqmes` is a harmless coarse filter and slightly improves floor, but it does not change OOS; it is not enough to promote.
- `in_prior_range_open_mnqmes` is visually strong on floor but fails 2026 and has zero 2025 trades. Treat it as an overfit warning, not a candidate.
- `d1_close_weak_not_extreme_mnqmes` looks good in 2026 but is floor-negative and has zero 2025 trades. Reject.
- MNQ leadership is a clue but sample is too small and 2025 is negative.

Verdict:

- **No exhaustion / D-1 / gap-quality filter promotes the gap-shock sleeve.**
- Keep `d1_not_crash_mnqmes` only as a coarse sensitivity row.
- The best measured sleeve remains the strict price/breadth base, with the same blocker: too few OOS event days and flat/negative 2026 after slippage.

### Stress gap-shock instrument autopsy - 2026-08-21

Artifact:

- `scratch/stress_instrument_autopsy_20260821.py`
- `scratch/stress_instrument_autopsy_20260821_report.md`

Purpose: decide whether future standalone Stress research should keep bundling MNQ/MES or split instruments.

Instrument evidence:

| Window | Variant / leg | Trades | Net | PF | MaxDD | 3x slip | Bootstrap p5 | Read |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| floor | MNQ/MES strict | 101 | +$3,208 | 1.58 | $1,295 | +$2,804 | -$842 | higher dollars, weaker quality |
| floor | MNQ-only strict | 46 | +$2,554 | 1.98 | $670 | +$2,370 | +$369 | cleaner standalone shape |
| floor, inside MNQ/MES | MNQ leg | 46 | +$2,554 | n/a | n/a | n/a | n/a | about 80% of total net |
| floor, inside MNQ/MES | MES leg | 55 | +$654 | n/a | n/a | n/a | n/a | adds trades, little edge |
| 2025 | MNQ/MES strict | 6 | +$1,160 | 50.91 | $0 | +$1,136 | +$496 | both legs good, tiny sample |
| 2025 | MNQ-only strict | 3 | +$647 | 28.85 | $23 | +$635 | +$226 | good, tiny sample |
| 2026 | MNQ/MES strict | 8 | +$20 | 1.04 | $534 | -$12 | -$1,053 | flat before slippage |
| 2026 | MNQ-only strict | 4 | -$58 | 0.84 | $359 | -$74 | -$713 | does not confirm |
| 2026, inside MNQ/MES | MES leg | 4 | +$78 | n/a | n/a | n/a | n/a | offsets MNQ in recent sample |
| 2026, inside MNQ/MES | MNQ leg | 4 | -$58 | n/a | n/a | n/a | n/a | fails recent sample |

Read:

- Floor says MNQ is the main edge carrier: about $2,554 of the $3,208 MNQ/MES total.
- MES adds only about $654 on floor while increasing trade count, drawdown, and same-symbol operational surface.
- Quality metrics favor MNQ-only on floor: PF 1.98 vs 1.58, MaxDD $670 vs $1,295, and bootstrap p5 positive instead of negative.
- OOS does not settle the choice: 2025 is too small and both variants win; 2026 is too small and MNQ loses while MES offsets it.

Verdict:

- **Yes, split instruments in future Stress research.**
- Carry `MNQ-only` and `MNQ/MES` as fixed variants through event-WFO; do not bundle by default.
- Do not promote MES as an equal edge source from current evidence.
- Do not promote MNQ-only yet either; it is cleaner on floor but unconfirmed in 2026.
- If broker/netting or subaccount cost matters, `MNQ-only` is the cleaner first candidate to test.

### Stress open search - 2026-08-21

Artifact:

- `scratch/stress_open_search_20260821.py`
- `scratch/stress_open_search_20260821_report.md`

Purpose: stop anchoring on any one Stress hypothesis and search a coarse, live-causal candidate space.

Search constraints:

- No same-day daily Stress regime label.
- Every setup bar is treated as known only five minutes after its timestamp.
- Families searched: continuation shorts, gap-continuation shorts, VWAP-reject shorts, and reclaim longs.
- Instruments searched as fixed variants: `MNQ` and `MNQ/MES`.
- Coarse grid only: setup `10:30`, `11:30`, `13:00`; RR 2.0; exit 15:55.
- Ranking penalizes single-cluster concentration, negative 3x slippage, negative OOS, zero OOS trades, and fill/timing failures.

Top robustness-ranked rows:

| Candidate | Dir | Inst | Floor trades | Floor net | PF | MaxDD | 3x slip | Boot p5 | Best share | 2025 | 2026 | Read |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `gap_cont_short_10:30_b4_mnqmes_rr20_x1555` | SHORT | MNQ/MES | 144 | +$5,054 | 1.64 | $1,630 | +$4,478 | +$91 | 0.32 | +$1,160 | -$773 | closest clue, fails 2026 |
| `cont_short_10:30_b3_mnq_rr20_x1555` | SHORT | MNQ | 302 | +$6,636 | 1.28 | $1,947 | +$5,428 | +$733 | 0.18 | -$253 | -$455 | broad but OOS-negative |
| `gap_cont_short_10:30_b4_mnq_rr20_x1555` | SHORT | MNQ | 68 | +$3,759 | 1.95 | $933 | +$3,487 | +$809 | 0.25 | +$647 | -$561 | clean floor, fails 2026 |
| `gap_cont_short_11:30_b4_mnqmes_rr20_x1555` | SHORT | MNQ/MES | 129 | +$2,184 | 1.39 | $1,635 | +$1,668 | -$1,435 | 0.40 | -$2,977 | +$1,939 | regime-flips across OOS |

Best-row autopsy:

- `gap_cont_short_10:30_b4_mnqmes_rr20_x1555` is a stricter version of the morning continuation idea:
  all four instruments below open/VWAP by 10:30, at least two gap-down, enter short on low break after 10:35, exit 15:55.
- Floor year split: 2018 -$545; 2019 +$417; 2020 +$1,052; 2021 +$542; 2022 +$3,639; 2023 -$471; 2024 +$420.
- Instrument split: MNQ +$3,759 / 68 trades; MES +$1,295 / 76 trades.
- Exit split: most PnL is time-exit continuation, not target hits: stop -$4,890 / 24 trades; target +$1,148 / 3 trades; time +$8,795 / 117 trades.

Verdict:

- **No deploy-level Stress candidate found in the coarse open search.**
- The closest new clue is `gap_cont_short_10:30_b4_mnqmes_rr20_x1555`, but it fails 2026 and remains 2022-heavy.
- The open search reinforces the earlier shape: Stress shorts have believable floor crisis behavior, but OOS alternates between 2025 and 2026 rather than surviving both.
- Do not tune this by adding more parameters immediately. If continued, the only honest follow-up is a narrow event-WFO/insurance-value pass for the closest clue versus the strict gap-shock base.

### Stress ex-2026 gate - 2026-08-21

Artifact:

- `scratch/stress_ex2026_gate_20260821.py`
- `scratch/stress_ex2026_gate_20260821_report.md`

User-directed gate change: **remove 2026 from selection/rejection**. Treat 2026 as a forward sanity/monitoring column only.

Gate inputs now:

- 2018-2024 floor quality.
- Event-cluster WFO on floor.
- 2025 OOS.
- Fill/timing audit.
- 2x/3x slippage sensitivity.
- 2026 reported but not used for ranking or rejection.

Top ex-2026 ranked candidates:

| Candidate | Dir | Inst | Floor trades | Clusters | Floor net | PF | MaxDD | 3x slip | Boot p5 | Best share | 2025 | 2026 sanity | Read |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `gap_cont_short_10:30_b4_mnqmes_rr20_x1555` | SHORT | MNQ/MES | 144 | 62 | +$5,054 | 1.64 | $1,630 | +$4,478 | -$349 | 0.37 | +$1,160 | -$773 | best ex-2026 research candidate |
| `gap_cont_short_10:30_b4_mnq_rr20_x1555` | SHORT | MNQ | 68 | 56 | +$3,759 | 1.95 | $933 | +$3,487 | +$843 | 0.25 | +$647 | -$561 | cleaner floor, smaller 2025 sample |
| `cont_short_10:30_b4_mnqmes_rr20_x1555` | SHORT | MNQ/MES | 519 | 178 | +$6,411 | 1.19 | $2,935 | +$4,335 | -$3,063 | 0.26 | +$415 | -$1,662 | too broad/noisy |
| `cont_short_10:30_b4_mnq_rr20_x1555` | SHORT | MNQ | 247 | 164 | +$5,174 | 1.27 | $1,891 | +$4,186 | -$550 | 0.20 | +$266 | -$921 | broad but weak OOS |

Event-WFO across the top candidate set:

| Total | Best fold | Without best | Final 4 | Positive folds | Folds | Pass |
|---:|---:|---:|---:|---:|---:|---|
| +$25,175 | +$2,447 | +$22,728 | +$191 | 162 | 572 | True |

Important caveat:

- This WFO is a **dynamic top-set selection** result, not proof that the single best fixed row is deploy-ready.
- It does show that, once 2026 is removed from the gate, the Stress search space is not dead.

Best fixed candidate read:

- `gap_cont_short_10:30_b4_mnqmes_rr20_x1555`:
  all four instruments below open/VWAP by 10:30, at least two gap-down, short low break after 10:35, exit 15:55.
- Floor year split: 2018 -$545; 2019 +$417; 2020 +$1,052; 2021 +$542; 2022 +$3,639; 2023 -$471; 2024 +$420.
- Instrument split: MNQ +$3,759 / 68 trades; MES +$1,295 / 76 trades.
- Exit split: stop -$4,890 / 24 trades; target +$1,148 / 3 trades; time +$8,795 / 117 trades.

Verdict under ex-2026 gate:

- Promote `gap_cont_short_10:30_b4_mnqmes_rr20_x1555` to **active research candidate**, not deploy candidate.
- Keep `gap_cont_short_10:30_b4_mnq_rr20_x1555` as the cleaner MNQ-only challenger.
- Next pass should be narrow: fixed-candidate event-WFO, 2025 holdout, portfolio-insurance scoring versus Normal/Calm drawdown days, and same-symbol overlap audit.
- 2026 should remain a visible warning column, but per this gate it does not reject the sleeve.

### Stress targeted ex-2026 search - 2026-08-21

Artifact:

- `scratch/stress_targeted_ex2026_20260821.py`
- `scratch/stress_targeted_ex2026_20260821_report.md`

Purpose: with 2026 removed from the gate, deepen the morning broad-weakness continuation family without using regime labels.

Search space:

- Setup `10:00` and `10:30`, known five minutes later.
- SHORT only, low-break continuation.
- Instruments: `MNQ` and `MNQ/MES`.
- Breadth: 3/4 or 4/4 below open/VWAP.
- Gap-down count: 1/4, 2/4, or 3/4.
- RR: 1.5, 2.0, 2.5.
- Exit: 14:00 or 15:55.
- 2026 reported only as sanity, not used for ranking or rejection.

Top rows:

| Candidate | Inst | Trades | Clusters | Floor net | PF | MaxDD | 3x slip | Boot p5 | Best share | 2025 | 2026 sanity | Read |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `target_gapcont_10:30_b4_g2_mnqmes_rr15_x1555` | MNQ/MES | 144 | 67 | +$5,347 | 1.68 | $1,630 | +$4,771 | +$266 | 0.28 | +$1,158 | -$773 | best fixed row |
| `target_gapcont_10:30_b4_g2_mnqmes_rr25_x1555` | MNQ/MES | 144 | 67 | +$5,097 | 1.65 | $1,630 | +$4,521 | -$13 | 0.31 | +$1,160 | -$773 | similar to RR2 |
| `target_gapcont_10:30_b4_g2_mnqmes_rr20_x1555` | MNQ/MES | 144 | 67 | +$5,054 | 1.64 | $1,630 | +$4,478 | +$44 | 0.32 | +$1,160 | -$773 | prior ex-2026 leader |
| `target_gapcont_10:30_b4_g3_mnqmes_rr15_x1555` | MNQ/MES | 107 | 52 | +$4,048 | 1.70 | $1,279 | +$3,620 | +$277 | 0.20 | +$1,158 | +$20 | stricter gap, less PnL |
| `target_gapcont_10:30_b4_g2_mnq_rr15_x1555` | MNQ | 68 | 59 | +$4,046 | 2.03 | $933 | +$3,774 | +$1,070 | 0.23 | +$647 | -$561 | cleaner instrument challenger |
| `target_gapcont_10:30_b4_g3_mnq_rr15_x1555` | MNQ | 50 | 45 | +$3,393 | 2.31 | $670 | +$3,193 | +$1,040 | 0.15 | +$647 | -$58 | strongest quality/small sample |

Dynamic event-WFO across top candidate set:

| Total | Best fold | Without best | Final 4 | Positive folds | Folds | Pass |
|---:|---:|---:|---:|---:|---:|---|
| +$2,472 | +$692 | +$1,780 | -$306 | 21 | 71 | False |

Best fixed row autopsy:

- `target_gapcont_10:30_b4_g2_mnqmes_rr15_x1555` is the same 10:30 full-breadth/gap-continuation structure as the prior leader, but with RR 1.5.
- Floor year split: 2018 -$545; 2019 +$484; 2020 +$1,556; 2021 +$542; 2022 +$3,302; 2023 -$471; 2024 +$479.
- Instrument split: MNQ +$4,046 / 68 trades; MES +$1,301 / 76 trades.
- Exit split improved versus RR2: stop -$4,890 / 24 trades; target +$5,007 / 14 trades; time +$5,229 / 106 trades.

Read:

- RR 1.5 is a real improvement on the fixed `10:30 b4 g2 MNQ/MES` structure: higher floor net, PF, 3x-slippage net, and positive bootstrap p5.
- `g3` reduces 2026 damage and improves quality, but gives up floor dollars and keeps 2025 at the same tiny 6 trades.
- MNQ-only remains cleaner: `b4 g2 rr15` has PF 2.03, MaxDD $933, and boot p5 +$1,070, but only 3 trades in 2025.
- The dynamic top-set WFO failing final4 means the broader parameter family is unstable. Do not treat the grid as validated selection machinery.

Verdict:

- Promote `target_gapcont_10:30_b4_g2_mnqmes_rr15_x1555` to the new **best fixed active research candidate** under the ex-2026 gate.
- Keep `target_gapcont_10:30_b4_g2_mnq_rr15_x1555` and `target_gapcont_10:30_b4_g3_mnq_rr15_x1555` as instrument-quality challengers.
- Still not deploy/paper-ready: next required gate is fixed-candidate event-WFO plus Normal/Calm insurance and overlap audit.

### Stress payoff / sizing probe - 2026-08-21

Artifact:

- `scratch/stress_payoff_sizing_20260821.py`
- `scratch/stress_payoff_sizing_20260821_report.md`

Purpose: test whether the best ex-2026 Stress candidates are thin because the signal is weak, or because 1-micro payoff is too small.

Assumptions:

- Synthetic scaling multiplies the same micro fills/PnL by N contracts.
- This is not a liquidity model and not a production sizing rule.
- $50k account, target DD 10% ($5k), hard DD 15% ($7.5k), margin budget 40% ($20k).
- 2026 remains sanity-only under the current Stress gate.

Sizing table:

| Candidate | Scale | Floor net | Floor MaxDD | DD % | Margin | 2025 | 2026 sanity | Read |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `b4 g2 MNQ/MES rr15` | 1x | +$5,347 | $1,630 | 3.3% | $3,600 | +$1,158 | -$773 | thin but clean |
| `b4 g2 MNQ/MES rr15` | 3x | +$16,041 | $4,889 | 9.8% | $10,800 | +$3,474 | -$2,318 | fits 10% target DD |
| `b4 g2 MNQ/MES rr15` | 4x | +$21,388 | $6,519 | 13.0% | $14,400 | +$4,631 | -$3,090 | under hard DD, above target |
| `b4 g2 MNQ/MES rr15` | 5x | +$26,735 | $8,149 | 16.3% | $18,000 | +$5,789 | -$3,863 | breaches hard DD |
| `b4 g2 MNQ rr15` | 5x | +$20,232 | $4,665 | 9.3% | $11,000 | +$3,236 | -$2,807 | fits target DD, only 3 OOS trades |
| `b4 g3 MNQ rr15` | 7x | +$23,749 | $4,688 | 9.4% | $15,400 | +$4,531 | -$406 | best sanity loss profile, small sample |
| `b4 g3 MNQ rr15` | 10x | +$33,927 | $6,697 | 13.4% | $22,000 | +$6,473 | -$580 | hard-DD ok, margin >40% |

Read:

- Scaling can solve the "thin PnL" problem mechanically.
- Under a 10% target DD, `b4 g2 MNQ/MES rr15` supports roughly 3x; under 15% hard DD, roughly 4x.
- MNQ-only supports larger synthetic scale because MaxDD is lower, especially strict `g3`, but its 2025 sample is only 3 trades.
- Scaling also linearly scales same-symbol conflict and 2026 sanity loss. It does not solve operational or insurance-value questions.

Verdict:

- Payoff/sizing is a viable next research dimension. The signal is not necessarily too weak; 1-micro sizing is too small for a standalone sleeve.
- Do **not** choose a deploy size from this table.
- Next gate must combine sizing with same-symbol overlap, margin, account breaker, and Normal/Calm insurance value.

### Stress MNQ-only strict deep dive - 2026-08-21

Artifact:

- `scratch/stress_mnq_strict_deepdive_20260821.py`
- `scratch/stress_mnq_strict_deepdive_20260821_report.md`

Purpose: investigate the cleaner MNQ-only strict Stress direction under the ex-2026 gate.

Search space:

- No daily Stress regime label.
- Setup `10:00`, `10:30`, `11:00`, known five minutes later.
- 4/4 basket below open/VWAP.
- Gap-down count 2/4, 3/4, or 4/4.
- MNQ only.
- SHORT low-break continuation.
- RR 1.0, 1.25, 1.5, 1.75, 2.0.
- Exit 14:00 or 15:55.
- 2026 sanity-only.

Top MNQ-only strict rows:

| Candidate | Trades | Clusters | Floor net | PF | MaxDD | 3x slip | Boot p5 | Best share | 2025 | 2026 sanity | Read |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `mnq_strict_10:30_b4_g2_rr175_x1555` | 68 | 60 | +$4,049 | 2.03 | $933 | +$3,777 | +$1,088 | 0.24 | +$647 | -$561 | top score, same shape as rr15 |
| `mnq_strict_10:30_b4_g2_rr15_x1555` | 68 | 60 | +$4,046 | 2.03 | $933 | +$3,774 | +$1,058 | 0.23 | +$647 | -$561 | practical rounded RR |
| `mnq_strict_10:30_b4_g3_rr175_x1555` | 50 | 45 | +$3,549 | 2.37 | $670 | +$3,349 | +$1,169 | 0.15 | +$647 | -$58 | best quality/sanity tradeoff |
| `mnq_strict_10:30_b4_g4_rr175_x1555` | 37 | 34 | +$3,318 | 2.99 | $587 | +$3,170 | +$1,337 | 0.16 | +$250 | +$125 | very clean but too sparse |
| `mnq_strict_11:00_b4_g4_rr175_x1555` | 43 | 40 | +$2,555 | 2.50 | $345 | +$2,383 | +$649 | 0.21 | +$1,202 | -$704 | lower DD, mixed sanity |

Dynamic WFO across top MNQ-strict set:

| Total | Best fold | Without best | Final 4 | Positive folds | Folds | Pass |
|---:|---:|---:|---:|---:|---:|---|
| +$2,039 | +$613 | +$1,426 | -$186 | 18 | 55 | False |

Best fixed candidate autopsy:

- `mnq_strict_10:30_b4_g2_rr175_x1555` is effectively the prior `b4 g2 MNQ rr15` shape with a slightly higher RR.
- Floor year split: 2018 -$190; 2019 +$503; 2020 +$1,022; 2021 +$262; 2022 +$2,499; 2023 -$214; 2024 +$167.
- Exit split: stop -$2,287 / 9 trades; target +$1,106 / 3 trades; time +$5,230 / 56 trades.
- Sizing sketch: 5x gives +$20,246 floor, $4,665 MaxDD (9.3%), +$3,236 in 2025, and -$2,807 in 2026 sanity.

Read:

- The RR1.75 top row is not a meaningful new discovery; it is a tiny parameter improvement over RR1.5 on the same trade set.
- The more interesting robust direction is `g3 MNQ`: lower net but materially better PF/DD/concentration and much smaller 2026 sanity loss.
- The very strict `g4` rows look beautiful by PF/DD but are too sparse to trust: 37 floor trades and 2 trades in 2025.
- Dynamic WFO failing final4 again says not to deploy a tuned MNQ-strict selector.

Verdict:

- Keep `mnq_strict_10:30_b4_g2_rr15_x1555` as the practical MNQ-only scale candidate.
- Keep `mnq_strict_10:30_b4_g3_rr175_x1555` or rounded `rr15` as the quality/sanity challenger.
- Do not select RR1.75 just because it ranked first by a few dollars.
- Still not deploy-ready until overlap/account-insurance scoring passes at the intended synthetic scale.

### Stress MNQ strict overlap / insurance probe - 2026-08-21

Artifact:

- `scratch/stress_mnq_overlap_insurance_20260821.py`
- `scratch/stress_mnq_overlap_insurance_20260821_report.md`

Purpose: test whether the MNQ-only strict Stress candidates are useful at intended synthetic scale after accounting for same-symbol overlap and payoff on bad Normal+Calm days.

Candidates:

- `mnq_strict_10:30_b4_g2_rr15_x1555` at 5x.
- `mnq_strict_10:30_b4_g3_rr15_x1555` at 7x.

Summary:

| Window | Candidate | Scale | Stress net | Stress MaxDD | Combined net | Combined MaxDD | MaxDD delta | Normal opposite days | Calm opposite days | Read |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| floor | `b4_g2_rr15` | 5x | +$20,232 | $4,665 | +$60,661 | $12,428 | -$3,802 | 28 | 6 | improves path DD, many Normal conflicts |
| floor | `b4_g3_rr15` | 7x | +$23,749 | $4,688 | +$64,178 | $13,577 | -$2,653 | 20 | 5 | higher net, less conflict, smaller DD help |
| 2025 | `b4_g2_rr15` | 5x | +$3,236 | $116 | +$13,978 | $7,870 | -$1,586 | 2 | 0 | improves combined DD, no Calm conflict |
| 2025 | `b4_g3_rr15` | 7x | +$4,531 | $163 | +$15,273 | $7,870 | -$1,586 | 2 | 0 | same DD help, more net |
| 2026 sanity | `b4_g2_rr15` | 5x | -$2,807 | $2,895 | +$1,915 | $16,868 | +$290 | 4 | 3 | worsens sanity |
| 2026 sanity | `b4_g3_rr15` | 7x | -$406 | $2,516 | +$4,316 | $16,984 | +$406 | 3 | 1 | smaller PnL loss, still worsens DD |

Insurance buckets:

| Window | Candidate | Worst 5 base days | Worst 10 base days | Worst 20 base days | All negative base days | Read |
|---|---|---:|---:|---:|---:|---|
| floor | `b4_g2_rr15` 5x | $0 | $0 | $0 | +$2,677 | not a worst-day crash hedge |
| floor | `b4_g3_rr15` 7x | $0 | $0 | $0 | +$4,065 | helps some losing days, not worst days |
| 2025 | `b4_g2_rr15` 5x | $0 | $0 | $0 | $0 | no bad-day insurance in 2025 |
| 2025 | `b4_g3_rr15` 7x | $0 | $0 | $0 | $0 | no bad-day insurance in 2025 |
| 2026 sanity | `b4_g2_rr15` 5x | $0 | $0 | -$1,797 | -$1,797 | anti-insurance in recent sanity |
| 2026 sanity | `b4_g3_rr15` 7x | $0 | $0 | -$2,516 | -$2,516 | anti-insurance in recent sanity |

Read:

- Scaling MNQ-only solves the thin-PnL problem mechanically and improves combined MaxDD in floor and 2025.
- But it does **not** pay on the worst 5/10/20 Normal+Calm daily-loss buckets in floor or 2025.
- The MaxDD improvement comes from drawdown-path timing, not from a direct worst-day crash payoff.
- Same-symbol overlap remains material even with MNQ-only: 20-28 floor days overlap an existing Normal MNQ LONG while Stress is SHORT.
- Calm conflicts are smaller: 5-6 floor days, none in 2025, 1-3 in 2026 sanity.
- 2026 remains non-gating by user choice, but it is a real warning: scaled Stress worsens combined MaxDD and loses on negative base days.

Verdict:

- **Sizing does not yet rescue MNQ-only strict as a deploy hedge.**
- Keep it as a research candidate only if the desired role is "drawdown-path diversifier", not "worst-day crash hedge".
- Same-symbol Normal overlap must be solved or blocked before any paper/deploy consideration.
- Between the two, `b4_g3_rr15` is cleaner operationally/recently; `b4_g2_rr15` has better trade count and slightly stronger floor DD improvement.

### Stress final gate - 2026-08-21

Artifact:

- `scratch/stress_final_gate_20260821.py`
- `scratch/stress_final_gate_20260821_report.md`

Purpose: stop tuning and decide whether the MNQ-only Stress branch survives as an active hedge/diversifier candidate.

Gate policy:

- 2026 is sanity-only, not a rejection input.
- Test only fixed candidates and fixed scales.
- Test both allowing overlap and blocking Stress when Normal already holds MNQ.
- Required to keep candidate: zero Normal same-symbol opposite overlap after policy, positive 2025, floor cluster stability, and no combined MaxDD worsening.

Scenarios:

| Window | Candidate | Scale | Policy | Raw / kept | Stress net | Combined MaxDD delta | Normal opposite days | Calm opposite days | Cluster pass | Read |
|---|---|---:|---|---:|---:|---:|---:|---:|---|---|
| floor | `b4_g2_rr15` | 5x | allow overlap | 68 / 68 | +$20,232 | -$3,802 | 28 | 6 | True | good numbers, not deployable |
| floor | `b4_g2_rr15` | 5x | block Normal MNQ | 68 / 30 | +$11,604 | +$335 | 0 | 4 | True | overlap fixed, DD benefit gone |
| floor | `b4_g3_rr15` | 7x | allow overlap | 50 / 50 | +$23,749 | -$2,653 | 20 | 5 | True | good numbers, not deployable |
| floor | `b4_g3_rr15` | 7x | block Normal MNQ | 50 / 22 | +$14,336 | +$565 | 0 | 3 | True | overlap fixed, DD benefit gone |
| 2025 | `b4_g2_rr15` | 5x | allow overlap | 3 / 3 | +$3,236 | -$1,586 | 2 | 0 | False | positive only with overlap |
| 2025 | `b4_g2_rr15` | 5x | block Normal MNQ | 3 / 1 | -$116 | $0 | 0 | 0 | False | fails 2025 |
| 2025 | `b4_g3_rr15` | 7x | allow overlap | 3 / 3 | +$4,531 | -$1,586 | 2 | 0 | False | positive only with overlap |
| 2025 | `b4_g3_rr15` | 7x | block Normal MNQ | 3 / 1 | -$163 | $0 | 0 | 0 | False | fails 2025 |

Decision table:

| Candidate | Scale | Policy | Floor cluster pass | Floor MaxDD delta | 2025 net | 2025 MaxDD delta | 2026 sanity net | Decision |
|---|---:|---|---|---:|---:|---:|---:|---|
| `b4_g2_rr15` | 5x | allow overlap | True | -$3,802 | +$3,236 | -$1,586 | -$2,807 | fail overlap |
| `b4_g2_rr15` | 5x | block Normal MNQ | True | +$335 | -$116 | $0 | -$2,355 | fail 2025 |
| `b4_g3_rr15` | 7x | allow overlap | True | -$2,653 | +$4,531 | -$1,586 | -$406 | fail overlap |
| `b4_g3_rr15` | 7x | block Normal MNQ | True | +$565 | -$163 | $0 | -$1,237 | fail 2025 |

Read:

- The attractive floor/2025 improvement requires allowing Stress SHORT MNQ while Normal is already LONG MNQ.
- Once same-symbol Normal overlap is blocked, the 2025 edge disappears and floor combined MaxDD worsens slightly instead of improving.
- The block policy also removes most of the economic reason to add the sleeve: 38/68 `g2` trades and 28/50 `g3` trades are blocked on floor.
- Therefore the apparent scaled Stress value is materially tied to same-symbol overlap/netting.

Verdict:

- **Reject independent Stress sleeve for paper/deploy under current constraints.**
- Keep the detector/rules as research artifacts only.
- Do not spend production broker/netting plumbing on this sleeve now.
- If Stress is revisited later, it needs a genuinely different payoff/instrument path or separate-account design; this MNQ-only strict path does not clear the final gate.

### Stress overlap filter ablation - 2026-08-21

Artifact:

- `scratch/stress_overlap_filter_ablation_20260821.py`
- `scratch/stress_overlap_filter_ablation_20260821_report.md`

Purpose: measure whether removing specific overlap classes makes the MNQ-only Stress candidates stronger.

Policies tested:

- `allow_all`: no overlap filter.
- `drop_normal_mnq`: remove Stress trades overlapping any Normal MNQ position.
- `drop_calm_mnq`: remove Stress trades overlapping any Calm MNQ position.
- `drop_any_mnq`: remove Stress trades overlapping Normal or Calm MNQ.
- `keep_normal_mnq_only`: keep only trades that overlap Normal MNQ, to test whether edge lives in the conflict.

Decision view:

| Candidate | Policy | Floor net | Floor MaxDD delta | Floor Normal opp | Floor Calm opp | 2025 net | 2025 MaxDD delta | Read |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `b4_g2_rr15` 5x | allow all | +$20,232 | -$3,802 | 28 | 6 | +$3,236 | -$1,586 | good but conflicted |
| `b4_g2_rr15` 5x | drop Normal MNQ | +$11,604 | +$335 | 0 | 4 | -$116 | $0 | fails |
| `b4_g2_rr15` 5x | drop Calm MNQ | +$19,127 | -$3,802 | 26 | 0 | +$3,236 | -$1,586 | helps only Calm overlap |
| `b4_g2_rr15` 5x | drop any MNQ | +$10,617 | +$335 | 0 | 0 | -$116 | $0 | fails |
| `b4_g2_rr15` 5x | keep Normal MNQ only | +$8,628 | -$5,165 | 28 | 2 | +$3,353 | -$1,586 | edge lives in conflict |
| `b4_g3_rr15` 7x | allow all | +$23,749 | -$2,653 | 20 | 5 | +$4,531 | -$1,586 | good but conflicted |
| `b4_g3_rr15` 7x | drop Normal MNQ | +$14,336 | +$565 | 0 | 3 | -$163 | $0 | fails |
| `b4_g3_rr15` 7x | drop Calm MNQ | +$21,713 | -$2,653 | 18 | 0 | +$4,531 | -$1,586 | helps only Calm overlap |
| `b4_g3_rr15` 7x | drop any MNQ | +$12,465 | +$565 | 0 | 0 | -$163 | $0 | fails |
| `b4_g3_rr15` 7x | keep Normal MNQ only | +$9,413 | -$3,196 | 20 | 2 | +$4,694 | -$1,586 | edge lives in conflict |

2026 sanity note:

- Dropping Calm overlap improves 2026 sanity:
  - `g2` 5x goes from -$2,807 to +$526.
  - `g3` 7x goes from -$406 to +$831.
- But this does not solve the deploy blocker because Normal MNQ opposite overlap remains.

Read:

- **Dropping Calm MNQ overlap is beneficial/cheap**, especially for 2026 sanity, and does not hurt 2025.
- **Dropping Normal MNQ overlap kills the edge**: 2025 flips negative and floor MaxDD improvement disappears.
- Keeping only Normal-overlap trades remains profitable and improves MaxDD, confirming that much of the measured edge is tied to the same-symbol conflict.

Verdict:

- If Stress were ever revisited, add a predeclared `drop_calm_mnq` rule.
- But no overlap removal produces a deployable candidate because removing the Normal MNQ conflict destroys the sleeve.
- The final rejection stands.

### Stress switch policy probe - 2026-08-22

Artifact:

- `scratch/stress_switch_policy_probe_20260822.py`
- `scratch/stress_switch_policy_probe_20260822_report.md`

Purpose: test the user's proposed alternative to blocking overlap:
if Stress wants to SHORT MNQ while Normal or Calm MNQ is open, close the existing MNQ trade at the Stress entry timestamp, then allow Stress.

This is a live-safe sleeve handoff approximation. It does not model order-book liquidity, partial fills, or production order sequencing.

Switch-policy result:

| Window | Candidate | Scale | Stress trades | Switched Normal | Normal PnL delta | Switched Calm | Calm PnL delta | Stress net | Combined net | Combined MaxDD delta | Read |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| floor | `b4_g2_rr15` | 5x | 68 | 29 | -$574 | 6 | +$438 | +$20,232 | +$60,525 | -$5,081 | strong |
| floor | `b4_g3_rr15` | 7x | 50 | 23 | +$366 | 5 | +$470 | +$23,749 | +$65,014 | -$3,931 | strong |
| 2025 | `b4_g2_rr15` | 5x | 3 | 2 | +$1,285 | 0 | $0 | +$3,236 | +$15,263 | -$1,586 | passes OOS |
| 2025 | `b4_g3_rr15` | 7x | 3 | 2 | +$1,285 | 0 | $0 | +$4,531 | +$16,558 | -$1,586 | passes OOS |
| 2026 sanity | `b4_g2_rr15` | 5x | 8 | 4 | +$492 | 3 | -$500 | -$2,807 | +$1,906 | -$1,722 | Stress loses, combo DD improves |
| 2026 sanity | `b4_g3_rr15` | 7x | 4 | 3 | +$2,117 | 1 | -$104 | -$406 | +$6,328 | -$1,606 | cleaner sanity |

Important read:

- The previous final gate rejected block policy because it removed the Stress edge.
- The switch policy is materially different: it keeps the Stress event while eliminating same-symbol simultaneous ownership.
- Floor and 2025 both remain positive, and combined MaxDD improves materially.
- 2026 remains sanity-only by user gate; under switch policy, Stress standalone still loses, but combined MaxDD improves.
- The best deployment direction changes from "reject outright" to **deploy-track research candidate, contingent on implementation feasibility**.

Caveats:

- This is not yet a production implementation audit.
- The probe assumes the existing MNQ trade can be closed at the Stress entry timestamp using the MNQ bar open.
- It does not model order sequencing, partial fills, slippage beyond the existing 2 ticks/side cost convention, or whether closing Normal early creates downstream re-entry/account-state effects.
- It still does not pay on worst 20 base daily-loss buckets; the value is drawdown-path diversification/handoff, not worst-day crash insurance.

Verdict:

- **Reopen Stress as deploy-track research only under a switch policy**, not under overlap/block policy.
- Best fixed candidate to carry: `b4_g3_rr15` at 7x, because it has higher combined net and much cleaner 2026 sanity than `g2`.
- Challenger: `b4_g2_rr15` at 5x, because it has more trades and stronger floor MaxDD improvement.
- Next required gate: production-feasibility simulation of close-existing-MNQ-then-enter-Stress, with explicit order sequencing, extra slippage, no same-symbol residual exposure, and account breaker interaction.

### Stress switch basket probe - 2026-08-22

Artifact:

- `scratch/stress_switch_basket_probe_20260822.py`
- `scratch/stress_switch_basket_probe_20260822_report.md`

Question: what if Stress trades the whole R4 basket instead of MNQ only?

Policy: close existing same-symbol Normal/Calm position at Stress entry timestamp, then allow Stress on that symbol.

Scenarios:

- `mnq_only_g3_q7`: MNQ only, qty 7.
- `r4_basket_g3_q1each`: MES/MNQ/MYM/M2K, qty 1 each.
- `r4_basket_g3_q2each`: MES/MNQ/MYM/M2K, qty 2 each.

Results:

| Window | Scenario | Legs / days | Margin est | Switched existing | Stress net | Combined net | Combined MaxDD delta | Bad20 stress | Read |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| floor | MNQ 7x | 50 / 50 | $15,400 | 28 | +$23,749 | +$65,014 | -$3,931 | $0 | best floor net |
| floor | R4 1x each | 202 / 61 | $5,300 | 86 | +$6,088 | +$47,829 | -$1,693 | $0 | capital efficient, lower edge |
| floor | R4 2x each | 202 / 61 | $10,600 | 86 | +$12,176 | +$53,918 | -$2,376 | $0 | middle ground |
| 2025 | MNQ 7x | 3 / 3 | $15,400 | 2 | +$4,531 | +$16,558 | -$1,586 | $0 | best OOS dollars |
| 2025 | R4 1x each | 15 / 6 | $5,300 | 9 | +$1,614 | +$12,784 | -$1,319 | $0 | more events, lower dollars |
| 2025 | R4 2x each | 15 / 6 | $10,600 | 9 | +$3,228 | +$14,399 | -$884 | $0 | more events, weaker DD help |
| 2026 sanity | MNQ 7x | 4 / 4 | $15,400 | 4 | -$406 | +$6,328 | -$1,606 | -$2,516 | Stress loses, combo ok |
| 2026 sanity | R4 1x each | 16 / 4 | $5,300 | 16 | +$121 | +$8,964 | -$4,243 | -$428 | best sanity/DD efficiency |
| 2026 sanity | R4 2x each | 16 / 4 | $10,600 | 16 | +$242 | +$9,085 | -$4,364 | -$856 | best sanity/DD, more size |

Read:

- MNQ-only 7x remains the best floor/2025 dollar candidate.
- R4 basket is much more capital-efficient and has better 2026 sanity, but lower floor/2025 net.
- R4 1x each has the cleanest margin profile ($5.3k estimate) and improves 2026 combined MaxDD the most.
- R4 2x each is a plausible middle ground, but it gives less 2025 MaxDD help than MNQ 7x.
- Basket Stress creates many more same-symbol handoffs: 86 on floor and 9 in 2025, versus 28 and 2 for MNQ-only.

Verdict:

- Keep two switch-policy candidates:
  1. `MNQ-only g3 rr15 qty 7` = best PnL candidate.
  2. `R4 basket g3 rr15 qty 1 each` = best capital-efficiency / 2026-sanity challenger.
- Do not promote R4 2x each yet; it is just a size interpolation.
- Next required gate should compare MNQ 7x vs R4 1x using extra handoff slippage, margin stress, and account breaker rules.

### Stress switch on Normal-R4 filtered probe - 2026-08-22

Artifact:

- `scratch/stress_switch_normal_r4_filtered_probe_20260822.py`
- `scratch/stress_switch_normal_r4_filtered_probe_20260822_report.md`

Purpose: rerun the switch-policy Stress comparison against the user's Normal promotion candidate shape:
Normal-R4 filtered only, `range_p90__vol_le_2`, MNKD/NKD excluded.

Implementation note:

- Base Normal is loaded from `normal_promotion_trades_{floor,vault2025,vault2026}_20260821.json`, bucket `filtered`, instruments MES/MNQ/MYM/M2K only.
- This uses the regenerated trade artifact directly. It is **not** a full production cap/breaker replay.
- The artifact sum differs from the published cap-row metrics, so this should be treated as a trade-level approximation until the full promotion harness is integrated.
- Switch policy: close existing same-symbol Normal-R4 position at Stress entry timestamp, then allow Stress on that symbol.

Results:

| Window | Scenario | Legs / days | Margin est | Switched Normal | Switch delta | Base net | Stress net | Combined net | Base MaxDD | Combined MaxDD | MaxDD delta | Read |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| floor | MNQ 7x | 50 / 50 | $15,400 | 20 | +$450 | +$27,711 | +$23,749 | +$51,910 | $16,866 | $11,854 | -$5,012 | best dollars |
| floor | R4 1x each | 202 / 61 | $5,300 | 64 | +$2,276 | +$27,711 | +$6,088 | +$36,076 | $16,866 | $12,778 | -$4,088 | capital efficient |
| floor | R4 2x each | 202 / 61 | $10,600 | 64 | +$2,276 | +$27,711 | +$12,176 | +$42,164 | $16,866 | $12,647 | -$4,219 | more size, not clearly better |
| 2025 | MNQ 7x | 3 / 3 | $15,400 | 2 | +$1,351 | +$8,751 | +$4,531 | +$14,633 | $5,846 | $5,209 | -$636 | best 2025 dollars |
| 2025 | R4 1x each | 15 / 6 | $5,300 | 7 | -$1,161 | +$8,751 | +$1,614 | +$9,204 | $5,846 | $5,644 | -$201 | small but positive |
| 2025 | R4 2x each | 15 / 6 | $10,600 | 7 | -$1,161 | +$8,751 | +$3,228 | +$10,818 | $5,846 | $6,079 | +$234 | worsens MaxDD |
| 2026 sanity | MNQ 7x | 4 / 4 | $15,400 | 3 | +$2,510 | +$2,534 | -$406 | +$4,638 | $12,890 | $10,691 | -$2,200 | Stress loses, combo improves |
| 2026 sanity | R4 1x each | 16 / 4 | $5,300 | 11 | +$4,256 | +$2,534 | +$121 | +$6,911 | $12,890 | $8,418 | -$4,473 | best sanity efficiency |
| 2026 sanity | R4 2x each | 16 / 4 | $10,600 | 11 | +$4,256 | +$2,534 | +$242 | +$7,031 | $12,890 | $8,297 | -$4,593 | stronger DD, 2025 MaxDD issue |

Read:

- Against Normal-R4 filtered-only, Stress switch policy remains constructive.
- MNQ 7x remains the best PnL add-on.
- R4 1x each becomes more attractive as a deploy-track challenger: much lower margin, more event legs, positive 2025, and strong 2026 sanity/DD improvement.
- R4 2x each is not preferred because it worsens 2025 MaxDD in this approximation.

Verdict:

- Keep two candidates for the next implementation-feasibility gate:
  1. `MNQ-only g3 rr15 qty 7` for max PnL.
  2. `R4 basket g3 rr15 qty 1 each` for capital efficiency / robustness.
- The next run must be a full cap/breaker replay against the exact Normal-R4 filtered promotion harness, not just trade-artifact summation.

### Stress switch on Normal-R4 filtered metrics - 2026-08-22

Artifact:

- `scratch/stress_switch_normal_r4_filtered_metrics_20260822.py`
- `scratch/stress_switch_normal_r4_filtered_metrics_20260822_report.md`

Scope:

- Same trade-artifact approximation as the prior section.
- Base: Normal-R4 filtered artifact, `filtered`, MES/MNQ/MYM/M2K only, MNKD excluded.
- Return % uses $50,000 account and raw window net, not annualized return.
- PF/Sharpe/Calmar computed from daily PnL series.
- Winrate is trade-level.

Metrics:

| Window | Book | Trades | Net | Return % | PF | Sharpe | Calmar | MaxDD | Winrate |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| floor | Normal-R4 filtered only | 752 | +$27,711 | 55.4% | 1.29 | 0.56 | 0.21 | $16,866 | 53.7% |
| floor | Combined + MNQ 7x | 802 | +$51,910 | 103.8% | 1.49 | 0.90 | 0.55 | $11,854 | 54.1% |
| floor | Combined + R4 1x each | 954 | +$36,076 | 72.2% | 1.38 | 0.75 | 0.35 | $12,778 | 54.7% |
| floor | Combined + R4 2x each | 954 | +$42,164 | 84.3% | 1.41 | 0.81 | 0.42 | $12,647 | 54.7% |
| 2025 | Normal-R4 filtered only | 105 | +$8,751 | 17.5% | 1.52 | 0.90 | 1.51 | $5,846 | 55.2% |
| 2025 | Combined + MNQ 7x | 108 | +$14,633 | 29.3% | 1.93 | 1.43 | 2.83 | $5,209 | 55.6% |
| 2025 | Combined + R4 1x each | 120 | +$9,204 | 18.4% | 1.63 | 1.21 | 1.64 | $5,644 | 59.2% |
| 2025 | Combined + R4 2x each | 120 | +$10,818 | 21.6% | 1.72 | 1.36 | 1.79 | $6,079 | 59.2% |
| 2026 sanity | Normal-R4 filtered only | 81 | +$2,534 | 5.1% | 1.14 | 0.31 | 0.31 | $12,890 | 54.3% |
| 2026 sanity | Combined + MNQ 7x | 85 | +$4,638 | 9.3% | 1.25 | 0.59 | 0.69 | $10,691 | 54.1% |
| 2026 sanity | Combined + R4 1x each | 97 | +$6,911 | 13.8% | 1.48 | 0.95 | 1.30 | $8,418 | 54.6% |
| 2026 sanity | Combined + R4 2x each | 97 | +$7,031 | 14.1% | 1.47 | 0.95 | 1.35 | $8,297 | 54.6% |

Stress standalone rows:

| Window | Stress book | Trades | Net | Return % | PF | Sharpe | Calmar | MaxDD | Winrate |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| floor | MNQ 7x | 50 | +$23,749 | 47.5% | 2.31 | 0.72 | 0.63 | $4,688 | 68.0% |
| floor | R4 1x each | 202 | +$6,088 | 12.2% | 1.73 | 0.53 | 0.49 | $1,560 | 60.4% |
| 2025 | MNQ 7x | 3 | +$4,531 | 9.1% | 28.85 | 1.21 | 28.02 | $163 | 66.7% |
| 2025 | R4 1x each | 15 | +$1,614 | 3.2% | 4.71 | 1.13 | 3.73 | $435 | 80.0% |
| 2026 sanity | MNQ 7x | 4 | -$406 | -0.8% | 0.84 | -0.19 | -0.26 | $2,516 | 50.0% |
| 2026 sanity | R4 1x each | 16 | +$121 | 0.2% | 1.25 | 0.20 | 0.39 | $488 | 56.2% |

Read:

- MNQ 7x is the strongest PnL add-on in floor and 2025.
- R4 1x each has lower PnL but stronger 2026 sanity and much lower margin.
- R4 2x each improves dollars but is not clearly superior because 2025 MaxDD worsens versus base.

### Stress candidate autopsy - 2026-08-21

Artifact:

- `scratch/stress_candidate_autopsy_20260821.py`
- `scratch/stress_candidate_autopsy_20260821_report.md`

Purpose: one-stop failure map for every Stress candidate tested in this thread.

Autopsy summary:

| Failure theme | Candidates affected | Lesson |
|---|---|---|
| Timing mirage | `liquidation1020` as-measured, `STRESS_MID` 10:15 interpretation | declare `known_time` and enter strictly after it |
| Lag-0 regime lookahead | daily-label Stress sleeves, legacy `STRESS_MID` | same-day HMM Stress label is not live-causal at intraday entry |
| Single-episode dependence | daily-label WFO, sparse gap candidates | event-cluster concentration gate is mandatory |
| Short hedge too late/noisy | causal 10:15, late-break, midday expansion | futures short sleeve PF stays too thin and OOS flips sign |
| Broker/netting blocker | `STRESS_MID`, `liquidation1020`, MNQ/MES short sleeves | do not spend broker plumbing on a sleeve that fails causal WFO |
| Filter specificity | Stress-as-filter | helps Calm longs, hurts Normal; not an account-wide kill switch |

Final read:

- No traded Stress sleeve survived as paper/deploy candidate.
- `late_break_1100_b3_rr2_x1555` survives only as a research clue.
- `gapdown-full-breadth` survives only as event-quality taxonomy.
- The only constructive measured branch so far is **Calm-specific Stress filter**, not Stress alpha.
- This does **not** mean the independent Stress sleeve objective is abandoned; it means the next sleeve attempt needs a new protocol, not further tuning of the failed 10:15/10:20/late-break families.

### Normal sleeve independent fill audit - 2026-08-21

Artifacts:

- `scratch/normal_sleeve_fill_audit.py` / `scratch/normal_sleeve_fill_audit_20260821.txt` / `.json`
- `scratch/normal_sleeve_halt_probe_20260821.py` / `scratch/normal_sleeve_halt_probe_20260821.txt` / `.json`
- `scratch/nkd_gap_mechanism_probe_20260821.py` / `.txt`
- `scratch/nsfa_correction_equivalence_20260821.py` / `scratch/nsfa_equivalence_20260821.txt`
- Trade tables: `scratch/normal_sleeve_trades_{floor,vault2025,vault2026}_20260821.json`

Scope: read-only. No production code changed, nothing committed. The engine is driven
through `scratch/harness.py` the same way `scratch/normal_sleeve_validation.py` drives it,
so the trades audited are the trades the current config books, not a re-implementation.
Exit prices are re-checked against each instrument's own 1-minute parquet bars.

Config audited: Normal regime only, Ro-4 EMA50, NKD ema=10 mult=2.5, 2x daily ATR stop,
fixed (no ratchet), armed 14:05 local on the next session, max_hold 5 days, SHORT only when
SPY D-1 close is below its SMA50, 2 ticks/side, 1 micro, $50,000, Stress disabled.

Anchors that had to pass before any number below was read:

- Re-assembly reproduces `deploy_sim` to the dollar in all three windows
  (floor +$33,181 / Calmar 0.52 / MaxDD $9,259 - the figures already in this file).
- The `R4 only` book reproduces `deploy_sim --no-nkd` exactly, including halt count
  (floor $8,570 / MaxDD $11,372 / 354 halts).
- The diagnostic replay reproduces `deploy_sim.replay` exactly.

#### Ro-4 audit result

Clean. 1,040 trades across the three windows, zero failures on every check:
`outside_exit_bar` 0, `outside_exit_day` 0, `signal_after_entry` 0,
`same_or_before_bar_exit` 0, `exit_before_entry` 0.

Entry convention confirmed rather than assumed: `entry_time` labels the START of the
5-minute resume bar and the booked entry price is that bar's CLOSE, on every trade with no
mismatches. Signal instant and fill instant are therefore the same moment, `entry_time`+5m,
and there is no lookahead - but a reader who treats `entry_time` as the fill timestamp is
reading it 5 minutes early. Zero-latency fill at the confirming bar's close remains an
execution assumption, not a measured one.

#### NKD audit result

Fails, but not where the P&L is.

| Window | NKD trades | outside_exit_bar | direction of the error |
|---|---:|---:|---|
| floor 2018-2024 | 228 | 3 | all favourable |
| 2025 | 31 | 0 | - |
| 2026 to 08-19 | 26 | 1 | favourable |

4 of 285 NKD trades (1.4%) book an exit at a price that never traded, and all four are
favourable - the fill is better than anything available in that bar. The 2026 case:

```
MNKD SHORT  entry 2026-03-09 14:20 JST -> exit 2026-03-11 02:20 JST  CHANDELIER
booked exit 55,738.57 | exit bar O 55,745  H 55,780  L 55,745  C 55,745
                      -> 6.43 points BELOW the bar low
```

**Mechanism.** The engine fills a stop at the bar open only when more than 15 minutes of
clock time separate that bar from the one before it. That is a test for a *time* break, and
what actually happened is a *price* break with no time break at all:

```
02:19  O 55,710  H 55,730  L 55,710  C 55,730
02:20  O 55,745  H 55,780  L 55,745  C 55,745    <- 12 contracts, one minute later
```

Price stepped 15 points (3 ticks) between two adjacent minutes and the stop sat inside the
step. No bar earlier that session had reached the stop, so this is the first touch, not a
missed earlier one. A stop level computed from ATR almost never lands on the tick grid, so
on a 5-point-tick instrument any stop between two ticks can only ever fill at the next tick
beyond it - the engine books it at the untraded level instead.

This is a defect in the gap test, not in NKD's data and not in NKD as an instrument.
Adjacent-bar steps larger than one tick run 26.8% of bars on NKD but 34.0% on MNQ and 41.5%
on M2K, so Ro-4's clean sheet is not explained by Ro-4 having smoother bars.

**Correction law used.** A stop the market stepped over fills at the ACTUAL bar open,
unconditionally: LONG `min(stop, open)`, SHORT `max(stop, open)`. Both are inside the bar
by construction given the hit condition.

**The correction is a real rule change, not bookkeeping.** Re-running the engine with the
time-break requirement removed produces trade tables that are key-for-key and price-for-price
identical to the post-hoc correction, on all five instruments. The production fix is that one
condition. It has NOT been made.

Scope of that proof: run on the **2026 window only** - the window that contains a live
repricing, so the branch is genuinely exercised rather than passing vacuously. The equivalence
is an identity (the engine's own `gapped` test already requires the open to be on the adverse
side of the stop, so forcing the flag on cannot convert a favourable open into a gap fill), but
it has not been re-run on floor. Independent corroboration that it holds on floor: the
conservative path law there selects exactly the 4 trades and exactly the $483.14 that the
harness day+1 rule selects, to the cent.

#### Original vs corrected vs excluded

Corrected-fill repricing versus the raw engine output, 1-contract basis:

| Window | conservative path law, Ro-4 | harness day+1 correction, Ro-4 | conservative path law, NKD |
|---|---|---|---|
| floor | 4 trades, $483.14 | 4 trades, $483.14 - the same 4 | 4 trades, $5.35 |
| 2025 | none | none | none |
| 2026 | none | none | 1 trade, $3.22 |

The two Ro-4 columns are not additive: on the floor window the conservative path law picks out
exactly the trades the harness day+1 correction already removes, to the cent. The path law
subsumes the day+1 rule rather than adding to it, which is why Ro-4's booked table already
audits clean. NKD is where the two differ - all five NKD repricings exit later than
`entry_day + 1`, so the day+1 rule never reaches them.

Effect on net, corrected minus original: floor -$5, 2025 $0, 2026 -$3. Total cost of
honest fills across eight and a half years: **$8.57**.

| Window | Variant | Net | PF | Sharpe | Calmar | MaxDD $ | MaxDD % | ret/yr | trades | taken | rej | out_exit_bar |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| floor | R4 only (NKD excluded) | $8,570 | 1.21 | 1.10 | 0.18 | 11,372 | 22.7% | 4.1% | 839 | 350 | 135 | 0 |
| floor | NKD only, original | $3,904 | 1.15 | 0.86 | 0.14 | 3,937 | 7.9% | 1.1% | 228 | 228 | 0 | 3 |
| floor | NKD only, corrected | $3,898 | 1.15 | 0.86 | 0.14 | 3,941 | 7.9% | 1.1% | 228 | 228 | 0 | 0 |
| floor | R4 + NKD, original | $33,181 | 1.36 | 1.73 | 0.52 | 9,259 | 18.5% | 9.7% | 1067 | 799 | 268 | 3 |
| floor | R4 + NKD, corrected | $33,176 | 1.36 | 1.73 | 0.52 | 9,259 | 18.5% | 9.7% | 1067 | 799 | 268 | 0 |
| 2025 | R4 only | $4,654 | 1.55 | 2.39 | 1.64 | 3,094 | 6.2% | 10.1% | 113 | 52 | 61 | 0 |
| 2025 | NKD only (identical either way) | $2,203 | 1.42 | 2.19 | 1.23 | 1,931 | 3.9% | 4.8% | 31 | 31 | 0 | 0 |
| 2025 | R4 + NKD (identical either way) | $6,857 | 1.51 | 2.33 | 1.47 | 5,025 | 10.1% | 14.8% | 144 | 83 | 61 | 0 |
| 2026 | R4 only | $736 | 1.09 | 0.50 | 0.21 | 6,342 | 12.7% | 2.7% | 88 | 46 | 42 | 0 |
| 2026 | NKD only, original | $6,011 | 1.95 | 4.33 | 4.36 | 2,504 | 5.0% | 21.8% | 26 | 24 | 2 | 1 |
| 2026 | NKD only, corrected | $6,007 | 1.95 | 4.32 | 4.35 | 2,507 | 5.0% | 21.8% | 26 | 24 | 2 | 0 |
| 2026 | R4 + NKD, original | $6,747 | 1.46 | 2.43 | 1.62 | 7,517 | 15.0% | 24.4% | 114 | 70 | 44 | 1 |
| 2026 | R4 + NKD, corrected | $6,743 | 1.46 | 2.43 | 1.62 | 7,520 | 15.0% | 24.4% | 114 | 70 | 44 | 0 |

Yearly net for the floor window, corrected: 2018 +$2,529, 2019 +$4,257, 2020 +$2,421,
2021 +$4,749, 2022 -$2,416, 2023 +$14,978, 2024 +$6,657.

Against the pre-declared rejection rules:

1. `outside_exit_bar > 0` - **rejects NKD-original**. NKD-corrected and Ro-4 pass.
2. Corrected fill destroying NKD's edge - **does not reject**. The correction costs $5 / $0 / $3.
3. NKD earning through impossible fills - **does not reject**. All four errors are favourable
   but worth $8.57 in total; NKD's result does not depend on them.
4. NKD worsening portfolio MaxDD - **this is the rule that bites**. See below.
5. No NKD selection or tuning was done on 2025/2026. Nothing in this pass changes a parameter.

#### What the audit found that the fill question does not explain

In the floor window the Ro-4-only book books **354 halted entries** and earns exactly zero in
2023 and 2024. `CircuitBreaker` blocks new entries once drawdown from PEAK equity reaches 15%,
and once entries stop the equity curve stops moving, so the peak never updates and the halt
never lifts: first block 2022-05-17, blocked on 262 days.

Turning the breaker off separates the sleeve's edge from the breaker's action, and the two
books then add exactly:

```
R4 only, breaker ON       $8,570
R4 only, breaker OFF     $29,278      <- Ro-4's own edge
NKD only (corrected)      $3,898
R4 + NKD                 $33,176   =   29,278 + 3,898  (to the dollar)
```

So the +$33,176 headline decomposes as **+$3,898 of NKD edge (11.8%)** and **+$20,708 of
"NKD's profits kept the shared account breaker from latching" (62.4%)**. The cushion is 5.3x
the edge. Part of that cushion is genuine diversification - NKD earned +$2,432 in 2022, the
year Ro-4 lost -$4,848 - but the headline cannot be read as the Normal sleeve's edge.

Headroom to the 15% trip, measured on the breaker's own rule (drawdown from peak equity, not
from the starting account):

| Window | R4 only | R4 + NKD | effect of adding NKD |
|---|---|---|---|
| floor | 16.3% on 2022-05-17 - **trips** | 13.7% same day, 1.3pp left | +2.6pp, saves the book |
| 2025 | 5.5%, 9.5pp left | 8.3%, 6.7pp left | -2.8pp |
| 2026 | 12.5%, 2.5pp left | 14.7%, **0.3pp left** | -2.2pp |

NKD moves headroom in opposite directions in different windows. "NKD diversifies and lowers
drawdown" is true in 2022 and false in 2025 and 2026: the 2026 NKD trough (03-11) and the
Ro-4 trough (04-09) are different events and do not offset. Adding NKD in 2026 leaves the
book 0.3 percentage points from a latch that, in this replay, is permanent.

Two concentration facts, independent of fills:

- NKD's floor edge is two years: 2022 + 2023 = +$6,972, the other five years = -$3,073.
- 2026 is 89% NKD: Ro-4 alone earns $736 against NKD's $6,007.

#### Normal risk/account halt validation - 2026-08-21

Artifacts:

- `scratch/normal_sleeve_risk_policy_probe_20260821.py` / `.txt` / `.json`
- `scratch/normal_sleeve_nkd_ema20_probe_20260821.py` / `.txt` / `.json`

Scope: scratch/research only. Production code was not changed. The risk-policy probe loads the
saved corrected trade tables from the fill audit and replays them through local copies of the
guard/breaker accounting with explicit breaker thresholds and release policies. `nkd_ema20`
requires fresh trade generation because it changes the NKD signal set; that run still applies
the same conservative corrected-fill law before metrics are read.

Key floor results, corrected fills:

| Candidate | Breaker | Cap | Net | PF | Sharpe | Calmar | MaxDD % | ret/yr | trades taken | halted days | blocked trades | lost-trade PnL |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R4 only | 15% latch | 5.0% | +$8,570 | 1.21 | 1.10 | 0.18 | 22.7% | 4.1% | 350 | 262 | 354 | +$20,921 |
| R4 only | off | 5.0% | +$29,278 | 1.44 | 2.11 | 0.38 | 22.7% | 8.6% | 571 | 0 | 0 | $0 |
| R4 + NKD ema10 | 15% latch | 5.0% | +$33,176 | 1.36 | 1.73 | 0.52 | 18.5% | 9.7% | 799 | 0 | 0 | $0 |
| R4 + NKD ema10 | off | 5.0% | +$33,176 | 1.36 | 1.73 | 0.52 | 18.5% | 9.7% | 799 | 0 | 0 | $0 |
| R4 + NKD ema10 | 15% latch | 7.5% | +$9,908 | 1.15 | 0.71 | 0.22 | 21.4% | 4.8% | 580 | 352 | 460 | +$20,518 |
| R4 + NKD ema10 | off | 7.5% | +$30,143 | 1.24 | 1.15 | 0.29 | 30.7% | 8.8% | 1,015 | 0 | 0 | $0 |
| R4 + NKD ema20 | 15% latch | 5.0% | +$8,212 | 1.15 | 0.76 | 0.19 | 20.9% | 3.9% | 482 | 346 | 450 | +$23,782 |
| R4 + NKD ema20 | off | 5.0% | +$31,781 | 1.35 | 1.66 | 0.44 | 20.9% | 9.3% | 799 | 0 | 0 | $0 |

Breaker/release reads:

- The 15% latch is the floor-window cliff. R4-only at 17.5%, 20%, 25%, and breaker-off all
  produce the same +$29,278 because the worst peak-relative breaker drawdown is 16.3%.
- A "flat reset" rule, modeled as resetting the peak once the book is flat while halted,
  also restores R4-only to +$29,278. This proves the old 2023/2024 zero years are a breaker
  semantics artifact, not a lack of signals.
- Fixed cooldown reset is not enough by itself: 20-day reset gives +$25,695 but raises MaxDD
  to 28.2%; 60-day reset gives +$27,235 with MaxDD 25.1%. These are release mechanics, not
  deploy candidates.
- `cap075` is now measured, not merely suspected. With the 15% latch it blocks 460 trades and
  leaves 2023/2024 at zero; with the breaker off it still has poor PF/Calmar and MaxDD 30.7%.
  The earlier "do not widen cap" conclusion survives, but the reason is now explicit.
- `nkd_ema20` is also measured. With the 15% latch it blocks 450 trades and produces the same
  structural 2023/2024 zero. With the breaker off it earns +$31,781, but still breaches the
  15% policy by 0.3pp on floor and is weaker than base NKD ema10 on risk-adjusted floor metrics.
  In 2026 it reaches 15.8% peak-relative drawdown and logs 3 halted days, although no proposed
  entry happens to arrive on those halted days.

OOS/sanity rows are not selection inputs, but they describe risk consistency:

| Window | R4 only | R4 + NKD ema10 corrected | R4 + NKD ema20 corrected |
|---|---:|---:|---:|
| 2025 | +$4,654, PF 1.55, MaxDD 6.2%, 9.5pp room | +$6,857, PF 1.51, MaxDD 10.1%, 6.7pp room | +$6,894, PF 1.51, MaxDD 11.2%, 5.9pp room |
| 2026 | +$736, PF 1.09, MaxDD 12.7%, 2.5pp room | +$6,743, PF 1.46, MaxDD 15.0%, 0.3pp room | +$6,148, PF 1.41, MaxDD 15.8%, -0.6pp room |

NKD direct-alpha bootstrap, floor corrected, clustered by realized PnL date:

| Cluster | Clusters | Net 2.5% | Net median | Net 97.5% | P(net > 0) | PF 5/50/95 | MaxDD 5/50/95 |
|---|---:|---:|---:|---:|---:|---|---|
| day | 2,502 | -$5,408 | +$3,876 | +$13,283 | 79.2% | 0.86 / 1.15 / 1.53 | $2,070 / $3,800 / $7,693 |
| week | 359 | -$6,028 | +$3,893 | +$13,746 | 77.8% | 0.84 / 1.17 / 1.63 | $2,149 / $4,078 / $8,335 |
| month | 83 | -$5,972 | +$3,794 | +$14,188 | 77.5% | 0.76 / 1.26 / 2.11 | $1,953 / $3,885 / $7,934 |

Interpretation:

- The NKD direct-alpha CI crosses zero under day, week, and month clustering. It cannot yet be
  treated as standalone alpha.
- The concentration remains severe: 2022+2023 = +$6,972, all other floor years = -$3,073.
- NKD ema10 is better understood as a weak, concentrated direct edge plus a large 2022 breaker
  cushion. The cushion is partly real diversification, but the headline Normal result still
  depends on the account-halt design.
- Current deploy-clean policy should therefore be **keep digging**. R4-only with breaker off is
  the cleanest read of Roska4's own edge, but it violates the current 15% breaker. R4+corrected
  NKD ema10 has clean fills and the best floor/OOS dollars, but depends on a small 1.3pp floor
  margin and only 0.3pp in 2026. `cap075` and `nkd_ema20` should not be promoted.

#### Normal position/cap policy probe - 2026-08-21

Artifacts:

- `scratch/normal_sleeve_position_sizing_policy_20260821.py` / `.txt` / `.json`

Scope: scratch/research only. This pass does not regenerate signals and does not change
production code. It loads the corrected trade tables and replays strict Ro-4 cap policies
through the same cluster-admission/account-breaker semantics. Floor is the only selection/read
window; 2025/2026 are sanity checks only.

Mechanical candidate gate used in the report:

- 15% latch breaker.
- No halted days and no blocked trades.
- At least 1.0 percentage point of peak-relative safety to the 15% breaker.
- Positive net and PF >= 1.20.

Important caveat: this is a cap-admission replay, not a final production-equivalent rerun after
the NKD fill-law fix. Treat it as policy discovery, not promotion.

Floor rows most relevant for policy:

| Candidate | Ro-4 cap | NKD cap | Net | PF | Sharpe | Calmar | MaxDD % | ret/yr | taken | rejected | blocked | Safety to 15% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R4 + NKD corrected, strict 2.5 | 2.5% gross/net | 6.0% | +$20,285 | 1.33 | 1.71 | 0.68 | 8.7% | 5.9% | 577 | 490 | 0 | 7.4pp |
| R4 + NKD corrected, strict 3.0 | 3.0% gross/net | 6.0% | +$24,013 | 1.33 | 1.61 | 0.60 | 11.6% | 7.0% | 631 | 436 | 0 | 4.7pp |
| R4 + NKD corrected, strict 3.5 | 3.5% gross/net | 6.0% | +$26,551 | 1.33 | 1.61 | 0.54 | 14.4% | 7.8% | 690 | 377 | 0 | about 1pp |
| R4 + NKD corrected, current | 5.0% gross / 4.4% net | 6.0% | +$33,176 | 1.36 | 1.73 | 0.52 | 18.5% | 9.7% | 799 | 268 | 0 | 1.3pp |
| R4 only, strict 1.5 | 1.5% gross/net | n/a | +$9,307 | 1.42 | 2.21 | 0.63 | 4.3% | 2.7% | 230 | 609 | 0 | 11.1pp |
| R4 only, strict 2.0 | 2.0% gross/net | n/a | +$13,121 | 1.45 | 2.24 | 0.56 | 6.9% | 3.8% | 294 | 545 | 0 | 9.0pp |
| R4 only, strict 2.5 | 2.5% gross/net | n/a | +$16,387 | 1.44 | 2.26 | 0.48 | 10.0% | 4.8% | 349 | 490 | 0 | about 5pp |
| R4 only, current | 5.0% gross / 4.4% net | n/a | +$8,570 | 1.21 | 1.10 | 0.18 | 22.7% | 4.1% | 350 | 135 | 354 | -1.3pp |

Cross-window sanity for floor-selected rows:

| Candidate | floor | 2025 sanity | 2026 sanity | Read |
|---|---:|---:|---:|---|
| R4 + NKD strict 2.5, NKD 6% | +$20,285 / PF 1.33 / MaxDD 8.7% | +$4,783 / PF 1.43 / MaxDD 7.9% | +$5,183 / PF 1.48 / MaxDD 9.7% | Cleanest balanced policy found without changing NKD cap. |
| R4 + NKD strict 3.0, NKD 6% | +$24,013 / PF 1.33 / MaxDD 11.6% | +$5,836 / PF 1.50 / MaxDD 8.1% | +$5,273 / PF 1.46 / MaxDD 10.2% | Higher floor net, still reasonable safety; more risk than 2.5%. |
| R4 + NKD strict 3.5, NKD 6% | +$26,551 / PF 1.33 / MaxDD 14.4% | +$6,889 / PF 1.56 / MaxDD 7.6% | +$3,805 / PF 1.28 / MaxDD 13.9% | Too close to the 15% line for a deploy-clean default. |
| R4 only strict 2.5 | +$16,387 / PF 1.44 / MaxDD 10.0% | +$2,580 / PF 1.44 / MaxDD 4.1% | -$824 / PF 0.82 / MaxDD 7.0% | Clean risk, but weak/negative sanity and much lower net. |
| R4 only strict 1.5 | +$9,307 / PF 1.42 / MaxDD 4.3% | +$1,384 / PF 1.50 / MaxDD 2.3% | +$490 / PF 1.41 / MaxDD 1.9% | Very safe but gives up too much edge and rejects 609 floor trades. |

Interpretation:

- A strict 2.5% Ro-4 cap with existing NKD 6% cap is the cleanest mechanical risk policy
  found in this pass: floor +$20,285, PF 1.33, MaxDD 8.7%, no halts/blocks, and broad safety
  to the 15% breaker. It also stays positive in 2025 and 2026 sanity without using those
  windows for selection.
- Strict 3.0% Ro-4 cap is a higher-return research alternative, but it is a less conservative
  risk policy. Strict 3.5% gets too close to the breaker and should not be a default.
- Tight R4-only policies prove Roska4 can be made breaker-clean, but the net is much lower and
  2026 sanity is weak unless the cap is so tight that most of the sleeve is rejected.
- Do not tune NKD cap from 2025/2026. Floor does not require changing the existing 6% NKD cap
  to find a breaker-clean candidate.

Policy read:

- **Best mechanical Normal policy to keep researching:** R4 + corrected NKD ema10, strict 2.5%
  Ro-4 gross/net cap, existing 6% NKD cap, 15% latch breaker.
- **Not promoted to production.** An engine-fix/cap dry-run was executed and then reverted from
  production files. Keep the strict 2.5% policy as the next candidate to test behind an explicit
  research flag or reviewed patch, not as the current default.

#### Normal engine-fix dry-run anchor - 2026-08-21

Artifacts:

- `scratch/normal_sleeve_fill_audit_enginefix_floor_20260821.txt` / `.json`
- `scratch/normal_sleeve_fill_audit_enginefix_vault2025_20260821.txt` / `.json`
- `scratch/normal_sleeve_fill_audit_enginefix_vault2026_20260821.txt` / `.json`
- `scratch/normal_sleeve_enginefix_policy_anchor_20260821.py`
- `scratch/normal_sleeve_enginefix_policy_anchor_{floor,vault2025,vault2026}_20260821.txt` / `.json`

Dry-run production changes tested, then reverted:

- `futures/_validated_core.py`: stop gap-through now fills at the hit bar open whenever that
  bar opens beyond the stop. The prior time-break requirement is removed. This fixes adjacent
  1-minute price steps that cross a stop without trading the stop level.
- `model_sameday_stop.py`: same gap-through semantics, so scratch/live-semantics research loops
  stay aligned with the production core.
- `global_index/net_exposure_multi.py`: `roska4_swing` default cluster cap changed from
  5.0% gross / 4.4% net to strict 2.5% gross / 2.5% net. NKD remains its own 6% cluster.

Revert check after this dry-run: production diffs for `futures/_validated_core.py`,
`model_sameday_stop.py`, and `global_index/net_exposure_multi.py` were cleared, and
`global_index.net_exposure_multi.DEFAULT_CLUSTERS["roska4_swing"]` again prints `0.05 0.044`.
The live/default engine therefore remains the pre-promotion engine.

Engine-fixed fill audit:

| Window | Engine net | PF | Sharpe | Calmar | MaxDD | out_exit_bar | post-hoc repricing |
|---|---:|---:|---:|---:|---:|---:|---:|
| floor | +$33,176 | 1.36 | 1.73 | 0.52 | $9,259 / 18.5% | 0 | 0 trades / $0 |
| 2025 | +$6,857 | 1.51 | 2.33 | 1.47 | $5,025 / 10.1% | 0 | 0 trades / $0 |
| 2026 | +$6,743 | 1.46 | 2.43 | 1.62 | $7,520 / 15.0% | 0 | 0 trades / $0 |

Production-equivalent dry-run default under the tested cap:

| Window | Default after patch | Net | PF | Sharpe | Calmar | MaxDD % | fill fix count |
|---|---|---:|---:|---:|---:|---:|---:|
| floor | R4 + NKD ema10, strict 2.5% Ro-4 cap | +$20,285 | 1.33 | 1.71 | 0.68 | 8.7% | 0 |
| 2025 sanity | same | +$4,783 | 1.43 | 1.95 | 1.31 | 7.9% | 0 |
| 2026 sanity | same | +$5,183 | 1.48 | 2.36 | 1.94 | 9.7% | 0 |

Interpretation:

- In the dry-run, the corrected fill law is engine-native: the old NKD original/corrected
  distinction disappears for this path, and independent fill audit reads clean in all three
  windows.
- In the dry-run, the strict 2.5% Normal policy is breaker-clean under the mechanical gate
  measured above. The old 5.0%/4.4% cap remains the actual default after revert.
- The trade-off is explicit: floor net falls from +$33,176 to +$20,285, but MaxDD falls from
  18.5% to 8.7% in the dry-run, and the account halt artifact is no longer part of that
  candidate's story.

#### Corrections to prior notes in this file

- The published floor figure of **+$33,181** is not the Normal sleeve's edge. Roughly 62% of
  it is Ro-4 trading in 2023-2024, years Ro-4 alone would have been halted out of. The same
  caveat applies to the +$28,794 baseline row and to the year split beneath it.
- `scratch/calm_candidate_deploy_probe.py` computes `signal_after_entry` only for
  `source == "stress"` and `source == "calm"`. There is no `normal` branch, so that counter is
  structurally zero for the Normal sleeve and a zero there was never evidence. This pass
  computes it independently; it is genuinely zero.
- The harness fill correction (`_correct`) only fires when the exit lands on `entry_day + 1`
  at the arm bar. Every NKD failure above exits later than that, which is why the current
  config's own correction never saw them.
- The sensitivity table under "Normal sleeve validation pass 1" concludes that "removing NKD
  destroys floor". It does not. `r4_no_nkd` on floor is +$29,278 with the breaker off and
  +$8,570 with it on, and the difference is one latch on 2022-05-17. The conclusion "keep NKD"
  may still be right, but it cannot rest on that comparison.
- Consequence for that whole table: a latched floor run and an unlatched floor run are not the
  same measurement, and the table mixes them in one column. Rows with floor MaxDD above about
  20% of account - `r4_no_nkd` 22.7%, `cap075` 21.4%, `nkd_ema20` 20.9% - are the candidates.
  These are now measured in `scratch/normal_sleeve_risk_policy_probe_20260821.py` and
  `scratch/normal_sleeve_nkd_ema20_probe_20260821.py`: `r4_no_nkd`, `cap075`, and
  `nkd_ema20` all trip/latch under the 15% floor breaker, while the breaker-off rows still
  breach the 15% policy.

#### Verdict

- **Deploy-clean on fills: Ro-4 + corrected NKD.** Ro-4 is clean as it stands; NKD is clean
  once the gap test stops requiring a time break, and that correction costs $8.57 across
  eight and a half years. NKD-original stays rejected under rule 1.
- **Deploy-ready: neither. Keep digging.** The blocker is no longer the fill law, it is the
  risk layer. Any net figure quoted for this sleeve is a statement about where the equity path
  fell relative to a 15% trip, and the combined book sits 1.3pp from that trip on floor and
  0.3pp in 2026.
- **Current Normal deploy-clean policy: no production promotion.** Use `R4-only, breaker off`
  only as the clean alpha read. The best next candidate is `R4 + corrected NKD ema10` with
  strict 2.5% Ro-4 gross/net cap and existing 6% NKD cap, but it must be applied via an
  explicit reviewed patch or research flag before being called default. Do not promote
  `cap075`, `nkd_ema20`, or the current 5.0%/4.4% Ro-4 cap as deploy-clean.

Gates before this sleeve is quoted or papered again:

1. Dry-run done then reverted 2026-08-21: fixing the gap test in the engine makes fill audit
   clean with zero post-hoc repricing, but production is currently back on the pre-fix engine.
2. Decide what a HALT means. A permanently absorbing halt makes every multi-year figure a
   function of one day in May 2022. Either model a reset rule or stop quoting multi-year nets
   through the breaker.
3. Dry-run done then reverted for Normal-only path 2026-08-21: strict 2.5% Ro-4 cap produces
   floor +$20,285, PF 1.33, Calmar 0.68, MaxDD 8.7%, zero fill corrections, and no account
   halt, but it is not the current production default.
4. Settle rule 4 on the floor window only: NKD helps headroom in 1 of 3 windows and hurts in 2.
   Two of those three are OOS and must not be used to make the call.
5. NKD bootstrap is now run and does **not** clear zero: floor corrected day/week/month clustered
   95% intervals are roughly -$5k to +$14k, with only 77-79% of resamples positive. Treat NKD as
   an unproven direct-alpha sleeve and a possible diversifier/risk-cushion only if the risk policy
   explicitly supports it.

### Calm Open-Location Drift, No Overnight Bucket

Date: 2026-08-21. Scratch probe only: `scratch/calm_open_location_drift.py`.

Purpose: test a Calm mechanism that is **not** conditioned on the OOS-informed negative-overnight
bucket. Signal family uses only Calm regime, prior RTH range, prior-day direction, and SPY D-1
SMA50 state. Entry/exit prices are scheduled bar opens. Cost is 2 ticks/side. Fill/timing audit
columns are `outside_exit_bar`, `outside_entry_bar`, and `signal_after_entry`.

Important caveat: the 09:30 variants use the 09:30 RTH open itself to classify open location
inside the prior-day range. The fill audit is mechanically clean because signal timestamp equals
entry timestamp, but this is a simultaneous-open research assumption. The 10:00 sensitivity is
therefore the cleaner liveability check, not a new post-OOS promotion.

IS selection before OOS, 2018-2024:

| Variant | Trades | Days | Net | PF | Avg/trade | MaxDD | Pos years | Pos inst | Audit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `openloc_lower_spy_above_long_e0930_x1555` | 609 | 294 | +$12,971 | 1.63 | $21.30 | $1,923 | 6/6 | 3 | 0/0/0 |
| `openloc_lower_third_long_e0930_x1555` | 666 | 315 | +$12,770 | 1.52 | $19.17 | $1,827 | 6/7 | 3 | 0/0/0 |

OOS/sanity for the two preselected variants:

| Variant | 2025 | 2026 through 2026-08-19 | 2025+2026 pooled |
|---|---:|---:|---:|
| `openloc_lower_spy_above_long_e0930_x1555` | 73 trades, +$5,807, PF 3.75 | 42 trades, +$218, PF 1.05 | 115 trades, +$6,025, PF 1.91 |
| `openloc_lower_third_long_e0930_x1555` | 73 trades, +$5,807, PF 3.75 | 48 trades, +$1,188, PF 1.25 | 121 trades, +$6,995, PF 2.02 |

Timing sensitivity, not promoted after OOS:

| Variant | IS | 2025 | 2026 | 2025+2026 pooled |
|---|---:|---:|---:|---:|
| `openloc_lower_third_long_e1000_x1555` | 666 trades, +$9,049, PF 1.41 | +$5,237, PF 4.64 | +$1,485, PF 1.44 | +$6,723, PF 2.39 |
| `openloc_lower_spy_above_long_e1000_x1555` | 609 trades, +$8,724, PF 1.46 | +$5,237, PF 4.64 | +$714, PF 1.24 | +$5,951, PF 2.36 |

Read:

- This is the cleanest new Calm clue so far: buy Calm days that open in the lower third of the
  prior RTH range, hold to 15:55.
- It does not rely on the negative-overnight bucket that failed H1/H2 discipline.
- The direction is one-sided. Comparable SHORT/open-upper variants are much weaker and more
  instrument-fragile.
- The 10:00 sensitivity keeps the effect alive, which argues the edge is not only the exact
  opening tick.

Why it is **not deploy-level yet**:

- OOS evidence is still only one full year plus a partial 2026; 2025 contributes most of the
  OOS dollars.
- The best IS rows are 09:30 simultaneous-open variants. Production needs a declared order model:
  either use 10:00 entry, or prove the 09:30 classification/order can be staged without lookahead.
- The family was discovered after many Calm probes, so it needs a strict protocol/WFO pass before
  promotion.
- Risk/combo with Normal+Stress has not been measured. A Calm sleeve can look good alone and still
  worsen account-level breaker behavior.

Verdict: **paper candidate / keep digging, not deploy.** Next step is a strict protocol around this
mechanism only: choose among lower-third 09:30 vs 10:00, optional SPY-above filter, and exit 15:55
using 2018-2024 folds; then measure 2025, 2026, and Normal+Stress combination only for the selected
rule.

#### Calm Open-Location Protocol And Risk Follow-Up

Date: 2026-08-21. Scratch probes:

- `scratch/calm_open_location_protocol.py`
- `scratch/calm_open_location_risk_probe.py`

Protocol family:

- `openloc_lower_third_long_e0930_x1555`
- `openloc_lower_spy_above_long_e0930_x1555`
- `openloc_lower_third_long_e1000_x1555`
- `openloc_lower_spy_above_long_e1000_x1555`

Full family fold protocol:

| Fold | Selected | Held-out | Net | PF | Winner | Rank | Meaningful |
|---|---|---:|---:|---:|---|---:|---|
| train 2018-2021, test 2022 | `openloc_lower_third_long_e0930_x1555` | 2022 | -$113 | 0.78 | `openloc_lower_third_long_e1000_x1555` | 4 | No |
| train 2019-2022, test 2023 | `openloc_lower_spy_above_long_e0930_x1555` | 2023 | +$1,145 | 1.38 | `openloc_lower_third_long_e0930_x1555` | 2 | Yes |
| train 2020-2023, test 2024 | `openloc_lower_third_long_e0930_x1555` | 2024 | +$1,842 | 1.26 | `openloc_lower_spy_above_long_e1000_x1555` | 4 | Yes |

Aggregate selected held-out: +$2,875 over 216 trades. Meaningful folds 2/3. Winner matches 0/3.
This does **not** clear a deploy-level protocol.

Liveable-only protocol, excluding simultaneous 09:30 entry:

| Fold | Selected | Held-out | Net | PF | Winner | Rank | Meaningful |
|---|---|---:|---:|---:|---|---:|---|
| train 2018-2021, test 2022 | `openloc_lower_third_long_e1000_x1555` | 2022 | +$270 | 2.25 | same | 1 | No |
| train 2019-2022, test 2023 | `openloc_lower_third_long_e1000_x1555` | 2023 | +$560 | 1.12 | same | 1 | Yes |
| train 2020-2023, test 2024 | `openloc_lower_third_long_e1000_x1555` | 2024 | +$2,353 | 1.39 | `openloc_lower_spy_above_long_e1000_x1555` | 2 | Yes |

Aggregate selected held-out: +$3,183 over 238 trades. Meaningful folds 2/3. Winner matches 2/3.
This is a better research read than the 09:30 family because the entry is liveable and the selector
collapses to a simple rule: **Calm, lower-third open, long at 10:00 open, exit 15:55 open**.

Liveable selected rule OOS:

| Window | Trades | Net | PF | Avg/trade | Pos inst | Audit |
|---|---:|---:|---:|---:|---:|---|
| 2025 | 73 | +$5,237 | 4.64 | $71.75 | 3 | 0/0/0 |
| 2026 through 2026-08-19 | 48 | +$1,485 | 1.44 | $30.94 | 2 | 0/0/0 |
| 2025+2026 | 121 | +$6,723 | 2.39 | $55.56 | 3 | 0/0/0 |

Disaster stop / adverse excursion for `openloc_lower_third_long_e1000_x1555`:

| Window | Stop | Net | PF | MaxDD | Stop hits | MAE ATR p50/p90/p95 | Audit |
|---|---|---:|---:|---:|---:|---|---|
| IS | none | +$9,049 | 1.41 | $1,706 | 0 | 0.28 / 0.84 / 1.06 | 0/0/0 |
| IS | 1.5x ATR | +$8,982 | 1.40 | $1,778 | 2 | 0.28 / 0.84 / 1.06 | 0/0/0 |
| IS | 2.0x ATR | +$9,049 | 1.41 | $1,706 | 0 | 0.28 / 0.84 / 1.06 | 0/0/0 |
| 2025+2026 | none | +$6,723 | 2.39 | $1,300 | 0 | 0.23 / 0.68 / 0.84 | 0/0/0 |
| 2025+2026 | 1.5x ATR | +$6,723 | 2.39 | $1,300 | 0 | 0.23 / 0.68 / 0.84 | 0/0/0 |
| 2025+2026 | 2.0x ATR | +$6,723 | 2.39 | $1,300 | 0 | 0.23 / 0.68 / 0.84 | 0/0/0 |

Read:

- The liveable 10:00 rule is now the cleanest Calm research seed.
- 1.5x/2.0x ATR disaster stops do not materially distort the rule; OOS has zero stop hits.
- The remaining blocker is selection evidence, not fill mechanics or stop geometry. 2022 is still
  too thin to be a meaningful held-out fold, and OOS is only 121 trades across 2025 plus partial
  2026.

Verdict: **strong paper candidate, not deploy-level yet.** Next required measurement is combination
with the current Normal+Stress system using the liveable rule only, with a max-position/risk policy
declared before reading combined PnL.

#### Calm Open-Location Standalone Deploy Gate

Date: 2026-08-21. Scratch probe: `scratch/calm_open_location_deploy_gate.py`.

Important process decision: **do not measure Normal+Stress combination until the Calm rule clears
a standalone deploy gate.** Otherwise combined PnL can turn into another selection layer and hide
the fact that the Calm sleeve itself has not been promoted.

Canonical rule tested:

- `openloc_lower_third_long_e1000_x1555_nostop`
- Calm only
- Prior RTH lower-third open location
- LONG at 10:00 open
- Exit at 15:55 open
- 2 ticks/side base cost
- Disaster stop result already measured separately: 1.5x/2.0x ATR does not change OOS and barely
  changes IS.

Standalone gate summary:

| Window | Trades | Days | Net | PF | Avg/trade | MaxDD | Pos inst | Day bootstrap p05/50/95 | Month p05 | Audit |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---|
| IS | 666 | 315 | +$9,049 | 1.41 | $13.59 | $1,706 | 3 | +$2,393 / +$9,027 / +$15,657 | +$3,775 | 0/0/0 |
| 2025 | 73 | 35 | +$5,237 | 4.64 | $71.75 | $603 | 3 | +$2,925 / +$5,223 / +$7,576 | +$3,507 | 0/0/0 |
| 2026 through 2026-08-19 | 48 | 27 | +$1,485 | 1.44 | $30.94 | $1,300 | 2 | -$1,610 / +$1,463 / +$4,457 | -$1,467 | 0/0/0 |
| 2025+2026 | 121 | 62 | +$6,723 | 2.39 | $55.56 | $1,300 | 3 | +$2,799 / +$6,793 / +$10,693 | +$2,930 | 0/0/0 |

Slippage sensitivity, 2025+2026 pooled:

| Slippage | Net | PF | Avg/trade |
|---:|---:|---:|---:|
| 2 ticks/side | +$6,723 | 2.39 | $55.56 |
| 3 ticks/side | +$6,545 | 2.34 | $54.09 |
| 4 ticks/side | +$6,367 | 2.29 | $52.62 |
| 6 ticks/side | +$6,011 | 2.19 | $49.68 |

OOS contribution:

| Slice | Trades | Net | PF |
|---|---:|---:|---:|
| 2025 | 73 | +$5,237 | 4.64 |
| 2026 | 48 | +$1,485 | 1.44 |
| OOS MES | 38 | +$1,947 | 2.81 |
| OOS MNQ | 41 | +$4,505 | 3.02 |
| OOS MYM | 42 | +$271 | 1.18 |

Gate verdict: **FAIL deploy-level, reason = `protocol_has_nonmeaningful_fold`.**

Read:

- Fill, slippage, stop geometry, and pooled OOS bootstrap are all supportive.
- 2026 alone is still statistically weak: day and month clustered p05 cross below zero.
- The blocking issue remains protocol evidence, not mechanics. The 2018-2024 walk-forward has one
  held-out fold, 2022, with only 5 trades; that cannot certify a deploy sleeve.
- Therefore **do not run combined Normal+Stress+Calm as a promotion test**. Combination testing is
  allowed only after the Calm sleeve clears standalone selection, or it must be labelled explicitly
  as exploratory/paper-risk research.

Current Calm verdict: **paper candidate only. Keep digging or paper-watch; no deploy and no
combined promotion test yet.**

### Calm Prior-Close-Location Hypothesis

Date: 2026-08-21. Scratch probes:

- `scratch/calm_prior_close_location_probe.py`
- `scratch/calm_prior_close_location_protocol.py`

New hypothesis: Calm has auction-memory drift after a prior RTH session that closed near the
bottom of its own range. This is deliberately separate from the earlier negative-overnight bucket
and from the current-day lower-third open-location candidate. Signal uses only D-1 RTH OHLC:

- Compute D-1 RTH close location within D-1 RTH high/low.
- Calm only.
- Test LONG/SHORT separately.
- Entry at 09:30 or 10:00 open, exit 15:55 open.
- Cost: 2 ticks/side.
- Fill/timing audit: `outside_exit_bar`, `outside_entry_bar`, `signal_after_entry`.

IS selection before OOS, 2018-2024:

| Variant | Trades | Days | Net | PF | Avg/trade | MaxDD | Pos years | Pos inst | Audit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `pcloc_prev_bottom_third_long_e1000_x1555` | 593 | 294 | +$8,291 | 1.39 | $13.98 | $2,401 | 5/7 | 3 | 0/0/0 |
| `pcloc_prev_bottom_down_long_e1000_x1555` | 558 | 282 | +$7,896 | 1.39 | $14.15 | $2,425 | 5/7 | 3 | 0/0/0 |

The direction read is consistent with other Calm work: LONG variants dominate; SHORT variants are
broadly toxic. The best form is liveable at 10:00, not a simultaneous-open fill.

Selected variant detail, `pcloc_prev_bottom_third_long_e1000_x1555`:

| Window | Trades | Net | PF | Notes |
|---|---:|---:|---:|---|
| IS 2018-2024 | 593 | +$8,291 | 1.39 | 2019 -$363, 2022 -$382 |
| 2025 | 54 | +$3,965 | 6.24 | positive all three instruments |
| 2026 through 2026-08-19 | 43 | +$510 | 1.20 | positive all three instruments but weak |
| 2025+2026 | 97 | +$4,475 | 2.34 | 53 days, audit 0/0/0 |

Protocol, liveable selected family:

| Fold | Selected | Held-out | Net | PF | Winner | Rank | Meaningful |
|---|---|---:|---:|---:|---|---:|---|
| train 2018-2021, test 2022 | `pcloc_prev_bottom_third_long_e1000_x1555` | 2022 | -$382 | 0.59 | same | 1 | No |
| train 2019-2022, test 2023 | `NONE` | 2023 | $0 | 0.00 | `pcloc_prev_bottom_third_long_e1000_x1555` | 0 | No |
| train 2020-2023, test 2024 | `pcloc_prev_bottom_third_long_e1000_x1555` | 2024 | +$3,642 | 1.83 | `pcloc_prev_bottom_down_long_e1000_x1555` | 2 | Yes |

Protocol verdict: **keep digging / protocol not decisive**.

Read:

- This is a real-looking paper clue: after a Calm-eligible prior day closes in the bottom third of
  its RTH range, next Calm RTH tends to mean-revert upward from 10:00 to 15:55.
- It is not deploy-level: the IS edge has two weak/negative years, 2022 is thin and negative, and
  one fold cannot select any variant under the predeclared train gates.
- It partially overlaps economically with the lower-third open-location candidate: both are
  versions of Calm downside exhaustion followed by slow intraday bid.

Current status: **paper candidate only, not deploy.** Do not combine-test for promotion.

### Calm Multi-Day Pullback Exhaustion Probe

Date: 2026-08-21. Scratch probe: `scratch/calm_multiday_pullback_probe.py`.

New hypothesis: instead of using overnight return or current-day open location, test whether Calm
RTH has a rebound after 2-3 prior RTH/down-close days or prior close near a 3-5 day low.

Rules:

- Calm only.
- Signal uses only D-1/D-2/D-3 RTH closes/ranges plus SPY D-1 context.
- Entry: 10:00 open.
- Exit: 15:55 open.
- LONG and SHORT tested separately.
- Cost: 2 ticks/side.
- Fill/timing audit: `outside_exit_bar`, `outside_entry_bar`, `signal_after_entry`.

IS result, 2018-2024:

| Variant | Trades | Days | Net | PF | Avg/trade | Pos years | Pos inst | Audit |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `mdpb_fut_2down_low3_spy2down_long_e1000_x1555` | 183 | 92 | +$1,406 | 1.17 | $7.68 | 4/7 | 2 | 0/0/0 |
| `mdpb_fut_2down_low3_spyabove_long_e1000_x1555` | 200 | 125 | +$887 | 1.10 | $4.44 | 5/7 | 2 | 0/0/0 |
| `mdpb_fut_2down_low3_long_e1000_x1555` | 235 | 143 | +$644 | 1.06 | $2.74 | 3/7 | 2 | 0/0/0 |
| `mdpb_fut_2down_long_e1000_x1555` | 405 | 233 | +$400 | 1.02 | $0.99 | 4/7 | 1 | 0/0/0 |

No variant cleared the pre-OOS selection gate (`n >= 250`, net >= $5k, PF >= 1.12, at least five
positive years, at least two positive instruments, audit clean). OOS was not touched.

Read:

- The broad direction remains consistent: LONG after downside is better than SHORT, and SHORT is
  negative across the tested forms.
- But pure multi-day pullback is too weak after cost. The stronger Calm clues need either current
  auction location (`openloc_lower_third`) or sharper D-1 auction memory (`prior close bottom third`).

Verdict: **reject this hypothesis form.**

### Calm Paper Candidate Failure Autopsy

Date: 2026-08-21. Scratch probe: `scratch/calm_paper_failure_autopsy.py`.

Question: stop broad excavation and inspect why the two strongest Calm paper candidates fail
deploy-level selection.

Candidates compared:

- `openloc_lower_third_long_e1000_x1555`
- `pcloc_prev_bottom_third_long_e1000_x1555`

Summary:

| Candidate | Window | Trades | Days | Net | PF | Avg/trade | MaxDD |
|---|---|---:|---:|---:|---:|---:|---:|
| openloc | IS | 666 | 315 | +$9,049 | 1.41 | $13.59 | $1,706 |
| openloc | 2025 | 73 | 35 | +$5,237 | 4.64 | $71.75 | $603 |
| openloc | 2026 | 48 | 27 | +$1,485 | 1.44 | $30.94 | $1,300 |
| pcloc | IS | 593 | 294 | +$8,291 | 1.39 | $13.98 | $2,401 |
| pcloc | 2025 | 54 | 28 | +$3,965 | 6.24 | $73.43 | $207 |
| pcloc | 2026 | 43 | 25 | +$510 | 1.20 | $11.86 | $608 |

The 2022 problem is denominator-driven:

| Candidate | Year | Calm days | Trigger days | Trigger share | Trades | Net |
|---|---:|---:|---:|---:|---:|---:|
| openloc | 2022 | 6 | 2 | 33.3% | 5 | +$270 |
| pcloc | 2022 | 6 | 3 | 50.0% | 9 | -$382 |

So 2022 is not thin because the rules barely trigger. It is thin because the Calm regime artifact has
only six Calm days in 2022. A fold that requires 2022 to be a meaningful held-out Calm sample cannot
certify any Calm sleeve with this label set.

Overlap between open-location and prior-close-location:

| Window | Bucket | Trades | Days | Net | PF | Avg/trade |
|---|---|---:|---:|---:|---:|---:|
| IS | openloc only | 334 | 184 | +$5,065 | 1.51 | $15.16 |
| IS | pcloc only | 261 | 150 | +$4,307 | 1.47 | $16.50 |
| IS | overlap | 332 | 187 | +$3,984 | 1.32 | $12.00 |
| OOS | openloc only | 73 | 42 | +$4,298 | 2.24 | $58.87 |
| OOS | overlap | 48 | 32 | +$2,425 | 2.78 | $50.52 |
| OOS | pcloc only | 49 | 28 | +$2,050 | 2.04 | $41.84 |

Read:

- The two paper candidates are related but not identical. The non-overlap buckets are positive
  in both IS and OOS, so this is not merely the same trade renamed.
- The shared mechanism is still the same high-level behavior: Calm downside auction exhaustion
  followed by slow intraday bid.
- IS yearly bootstrap by year is not the blocker: openloc year-cluster p05 is +$6,081 and pcloc
  year-cluster p05 is +$2,383.
- The practical blockers are:
  1. **Calm label denominator in 2022 is too small** for fold certification.
  2. **2026 is positive but weak**, with bad months in March/August for openloc and August/May for
     pcloc.
  3. **pcloc has weaker IS shape**, with 2019 and 2022 negative.

Conclusion:

- Broad excavation should pause. The best evidence says the Calm edge family exists, but the
  current deploy gate cannot certify it because one held-out year has almost no Calm samples.
- This is not a fill/cost/risk failure. It is a **selection-evidence failure under the current
  regime-label fold design**.
- Next useful work is not another random hypothesis. It is either:
  - redesign Calm validation folds around Calm sample counts rather than calendar years, or
  - paper-watch the openloc 10:00 rule until more 2026/2027 Calm samples accumulate.

Current verdict remains: **no deploy-level Calm sleeve. Strong paper candidate: openloc 10:00.**

### Calm Regime-Label Causality Audit And Causal Redo

Date: 2026-08-21. External audit reported in `CALM_OPENLOC_AUDIT_2026-08-21.md`.
Follow-up scratch probes:

- `scratch/calm_causal_lag1_excavation.py`
- `scratch/calm_causal_lag1_pcloc_protocol_folds.csv`
- `scratch/calm_causal_lag1_pcloc_deploy_gate_summary.csv`
- `scratch/calm_causal_lag1_pcloc_bottom_down_deploy_gate_summary.csv`
- `scratch/calm_sample_count_folds_with_causal*.csv`

Core audit finding:

- `label_regimes(daily[<=D])` uses SPY data through the close of day D.
- An intraday strategy entering at 10:00 on day D cannot know the `Calm` label for D.
- Therefore every previous Calm intraday result using same-day `labels[D] == "Calm"` is not
  tradable as quoted.
- Correct causal gate for a 10:00 entry is either:
  - D-1 regime label, or
  - a separate intraday detector using only data available by 09:30/10:00.

Audit reproduced impact for previously preferred candidates:

| Candidate | Window | Same-day Calm | D-1 causal Calm |
|---|---|---:|---:|
| `openloc_lower_third_long_e1000_x1555` | IS | +$9,049, PF 1.41 | -$769, PF 0.98 |
| `openloc_lower_third_long_e1000_x1555` | 2025 | +$4,925, PF 3.81 | +$1,935, PF 1.48 |
| `openloc_lower_third_long_e1000_x1555` | 2026 | +$1,485, PF 1.44 | -$2,514, PF 0.60 |
| `on_neg_fade_mod001_010_x1555` | IS | +$14,850, PF 1.60 | -$375, PF 0.99 |
| `on_neg_fade_mod001_010_x1555` | 2025 | +$2,736 | +$1,146, PF 1.19 |
| `on_neg_fade_mod001_010_x1555` | 2026 | +$2,634 | -$3,705, PF 0.59 |

Consequence:

- Reject `openloc_lower_third_long_e1000_x1555` as previously stated.
- Reject `on_neg_fade_mod001_010_x1555` as previously stated.
- Treat sample-count folds built on same-day Calm labels as measuring look-ahead stability, not
  deploy evidence.

#### Causal Lag-1 Calm Redo

The broad causal redo rebuilt labels as “latest fully known prior SPY regime label” and tested the
strong families again: open-location, prior-close-location, negative overnight, and multi-day
pullback.

IS 2018-2024 top causal results:

| Variant | Trades | Days | Net | PF | Avg/trade | Pos years | Pos inst | Audit |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `lag1calm_pcloc_bottom_long_e1000_x1555` | 597 | 298 | +$9,817 | 1.42 | $16.44 | 5/7 | 3 | 0/0/0 |
| `lag1calm_pcloc_bottom_down_long_e1000_x1555` | 561 | 283 | +$9,639 | 1.44 | $17.18 | 6/7 | 3 | 0/0/0 |
| `lag1calm_mdpb_2down_low3_long_e1000_x1555` | 247 | 150 | +$4,102 | 1.39 | $16.61 | 4/7 | 2 | 0/0/0 |
| `lag1calm_openloc_lower_long_e1000_x1555` | 710 | 334 | -$769 | 0.98 | -$1.08 | 3/7 | 1 | 0/0/0 |
| `lag1calm_negon_m001_m010_long_e1000_x1555` | 729 | 339 | -$3,030 | 0.91 | -$4.16 | 2/7 | 1 | 0/0/0 |

The causal survivor is not open-location. It is prior-close-location:

Canonical causal candidate:

- `lag1calm_pcloc_bottom_down_long_e1000_x1555`
- Gate: D-1 known regime label is Calm.
- Signal: prior RTH close is in the bottom third of its own RTH range, and prior RTH return <= 0.
- Entry: 10:00 open.
- Exit: 15:55 open.
- Direction: LONG.
- Instruments: MES, MNQ, MYM.
- Cost: 2 ticks/side.

OOS/sanity for `lag1calm_pcloc_bottom_down_long_e1000_x1555`:

| Window | Trades | Days | Net | PF | Avg/trade | Pos inst | Audit |
|---|---:|---:|---:|---:|---:|---:|---|
| 2025 | 76 | 39 | +$1,018 | 1.32 | $13.39 | 2 | 0/0/0 |
| 2026 through 2026-08-19 | 49 | 26 | +$1,073 | 1.34 | $21.89 | 3 | 0/0/0 |
| 2025+2026 | 125 | 65 | +$2,090 | 1.33 | $16.72 | 2 | 0/0/0 |

Slippage sensitivity, OOS pooled:

| Slippage | Net | PF | Avg/trade |
|---:|---:|---:|---:|
| 2 ticks/side | +$2,090 | 1.33 | $16.72 |
| 3 ticks/side | +$1,904 | 1.30 | $15.23 |
| 4 ticks/side | +$1,717 | 1.26 | $13.74 |
| 6 ticks/side | +$1,344 | 1.20 | $10.75 |

Deploy gate:

| Variant | Gate | Reasons |
|---|---|---|
| `lag1calm_pcloc_bottom_long_e1000_x1555` | FAIL | nonmeaningful protocol fold, selector instability, OOS day/month bootstrap crosses zero |
| `lag1calm_pcloc_bottom_down_long_e1000_x1555` | FAIL | nonmeaningful protocol fold, selector instability, OOS day/month bootstrap crosses zero |

Sample-count fold read, adding causal pcloc family:

| Protocol | Causal pcloc aggregate | Meaningful folds | Winner matches | Read |
|---|---:|---:|---:|---|
| Train 300 Calm days, test 150 | +$7,004 / 218 trades | 2/2 selected folds | 2/2 | Strong late evidence; first fold has no eligible train selection |
| Train 300 Calm days, test 100 | +$6,127 / 291 trades | 4/4 selected folds | 2/4 | One negative fold (-$400), late folds strong |

Read:

- The audit does **not** mean all causal Calm research is dead.
- It means the old preferred open-location and negative-overnight candidates were artifacts of
  same-day regime labels.
- Under D-1 causal labels, prior-close-location is the only family with meaningful IS edge and
  positive 2025/2026, but its OOS edge is modest and bootstrap still crosses zero.

Current causal Calm verdict:

- **No deploy-level candidate.**
- **Best causal paper candidate:** `lag1calm_pcloc_bottom_down_long_e1000_x1555`.
- It is not deploy-ready because OOS expectancy is too small, MYM is weak in 2025/OOS pooled, and
  day/month clustered OOS bootstrap crosses zero.

#### Causal PCLoc Refinement

Date: 2026-08-21. Scratch probe: `scratch/calm_causal_pcloc_refine.py`.

Scope: dig narrowly around `lag1calm_pcloc_bottom_down_long_e1000_x1555` using only causal fields
already present in the trade log. No same-day regime labels. Selection is still IS-first.

IS 2018-2024 top refinements:

| Filter | Trades | Net | PF | Avg/trade | MaxDD | Pos years | Pos inst | MES / MNQ / MYM |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| no big overnight gap (`overnight_ret >= -1%`) | 543 | +$10,714 | 1.55 | $19.73 | $2,041 | 6/7 | 3 | +$2,629 / +$6,824 / +$1,261 |
| small overnight gap (`-1% <= ON <= +1%`) | 538 | +$10,643 | 1.55 | $19.78 | $2,041 | 6/7 | 3 | +$2,567 / +$6,782 / +$1,294 |
| current open inside prior range | 337 | +$9,745 | 1.81 | $28.92 | $2,117 | 6/7 | 3 | +$2,821 / +$6,257 / +$667 |
| base all instruments | 561 | +$9,639 | 1.44 | $17.18 | $2,298 | 6/7 | 3 | +$2,299 / +$6,482 / +$858 |
| MES+MNQ only | 366 | +$8,781 | 1.53 | $23.99 | $1,838 | 7/7 | 2 | +$2,299 / +$6,482 / $0 |
| close-loc <= 25%, MES+MNQ only | 293 | +$6,973 | 1.53 | $23.80 | $1,756 | 6/7 | 2 | +$1,320 / +$5,652 / $0 |

IS selection by dollars picked `no_big_gap`, `small_gap`, `inside_open`, and base. Because MYM is
positive in IS but weak in OOS, MES+MNQ-only is reported as a **sensitivity**, not promoted from
OOS.

OOS pooled 2025+2026:

| Filter | Trades | Net | PF | Avg/trade | MaxDD | Pos years | Pos inst | MES / MNQ / MYM | Day bootstrap p05 / p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| MES+MNQ only | 79 | +$2,821 | 1.70 | $35.71 | $1,491 | 2/2 | 2 | +$1,035 / +$1,785 / $0 | -$533 / +$2,781 / +$6,195 |
| close-loc <= 25%, MES+MNQ only | 50 | +$2,271 | 1.93 | $45.42 | $1,244 | 2/2 | 2 | +$1,009 / +$1,262 / $0 | -$676 / +$2,287 / +$5,262 |
| no big overnight gap | 119 | +$2,134 | 1.36 | $17.93 | $1,936 | 2/2 | 2 | +$1,064 / +$1,779 / -$709 | -$1,789 / +$2,068 / +$6,282 |
| base all instruments | 125 | +$2,090 | 1.33 | $16.72 | $1,936 | 2/2 | 2 | +$1,035 / +$1,785 / -$731 | -$2,058 / +$2,029 / +$6,391 |

Read:

- The refinement confirms the main weakness: MYM is a drag OOS and only a small contributor IS.
- MES+MNQ-only materially improves OOS PF and average trade, and IS is not hostile to the choice
  (`7/7` positive years, PF 1.53).
- However, OOS day bootstrap still crosses below zero even for MES+MNQ-only. This is not
  deploy-level evidence yet.
- Tightening prior close location to <=25% plus MES+MNQ improves PF but reduces sample size to 50
  OOS trades and still has p05 below zero.

Refined causal verdict:

- **Best refined causal candidate:** `lag1calm_pcloc_bottom_down_long_e1000_x1555`, MES+MNQ only.
- **Status:** stronger paper/pilot candidate, still not deploy-level under strict gate.
- To promote, it needs either fresh OOS/paper sample or a predeclared rationale for excluding MYM
  that does not depend on 2025/2026.

#### Causal PCLoc Intraday Confirmation Probe

Date: 2026-08-21. Scratch probe: `scratch/calm_causal_pcloc_intraday_confirm.py`.

Scope: continue digging around the causal prior-close-location bottom-down candidate, but only with
information observable before the 10:00 entry. Features tested: 09:30-09:59 return, 10:00 price
relative to 09:30 open, entry location inside the pre-10 range, and pre-10 range caps. Regime gate
remains D-1 Calm; no same-day Calm label is used.

IS 2018-2024:

| Filter | Trades | Net | PF | Avg/trade | MaxDD | Pos years | Pos inst | MES / MNQ / MYM |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| base all instruments | 561 | +$9,639 | 1.44 | $17.18 | $2,298 | 6/7 | 3 | +$2,299 / +$6,482 / +$858 |
| pre-10 range <= 0.75% | 533 | +$9,485 | 1.49 | $17.80 | $1,892 | 6/7 | 3 | +$2,618 / +$5,986 / +$880 |
| MES+MNQ only | 366 | +$8,781 | 1.53 | $23.99 | $1,838 | 7/7 | 2 | +$2,299 / +$6,482 / $0 |
| MES+MNQ, pre-10 range <= 0.75% | 341 | +$8,604 | 1.61 | $25.23 | $1,433 | 7/7 | 2 | +$2,618 / +$5,986 / $0 |
| pre-10 range <= 0.50% | 418 | +$6,493 | 1.47 | $15.53 | $1,737 | 5/7 | 3 | +$2,606 / +$3,212 / +$674 |
| MES+MNQ, pre-10 range <= 0.50% | 259 | +$5,818 | 1.60 | $22.46 | $1,442 | 5/6 | 2 | +$2,606 / +$3,212 / $0 |

OOS pooled 2025+2026 for IS-selected filters:

| Filter | Trades | Net | PF | Avg/trade | MaxDD | Pos years | Pos inst | MES / MNQ / MYM | Day bootstrap p05 / p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| MES+MNQ only | 79 | +$2,821 | 1.70 | $35.71 | $1,491 | 2/2 | 2 | +$1,035 / +$1,785 / $0 | -$646 / +$2,747 / +$6,306 |
| base all instruments | 125 | +$2,090 | 1.33 | $16.72 | $1,936 | 2/2 | 2 | +$1,035 / +$1,785 / -$731 | -$1,878 / +$2,094 / +$6,205 |
| MES+MNQ, pre-10 range <= 0.50% | 43 | +$1,323 | 1.89 | $30.77 | $426 | 2/2 | 2 | +$445 / +$878 / $0 | -$228 / +$1,298 / +$2,934 |
| MES+MNQ, pre-10 range <= 0.75% | 64 | +$1,306 | 1.42 | $20.41 | $1,275 | 1/2 | 2 | +$657 / +$649 / $0 | -$1,441 / +$1,324 / +$3,888 |
| pre-10 range <= 0.75% | 108 | +$210 | 1.04 | $1.95 | $1,828 | 1/2 | 2 | +$657 / +$649 / -$1,096 | -$3,002 / +$241 / +$3,447 |
| pre-10 range <= 0.50% | 74 | +$205 | 1.06 | $2.77 | $727 | 1/2 | 2 | +$445 / +$878 / -$1,118 | -$1,970 / +$185 / +$2,418 |

Read:

- The 09:30-09:59 confirmation filters do **not** create a deploy-level variant.
- Pre-10 range caps improve IS smoothness, but the 0.75% cap loses 2026 and the 0.50% cap cuts OOS
  to 43 trades. Both still have OOS day-bootstrap p05 below zero.
- The best OOS row remains the previously identified MES+MNQ-only sensitivity, not a new intraday
  confirmation rule.

Intraday-confirmation verdict: **reject as deploy selector**. Keep the causal PCLoc MES+MNQ result
as a paper/pilot candidate only; do not promote from this probe.

#### Causal PCLoc MYM Exclusion Rationale

Date: 2026-08-21. Scratch probe: `scratch/calm_causal_pcloc_mym_rationale.py`.

Question: can the MES+MNQ-only sensitivity be justified from 2018-2024 IS evidence, rather than
being chosen because MYM was weak in 2025/2026?

IS-only instrument read for `lag1calm_pcloc_bottom_down_long_e1000_x1555`:

| Group | Trades | Net | PF | Avg/trade | MaxDD | Pos years | Pos months | Avg PnL / margin | Cost / gross |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MES | 170 | +$2,299 | 1.42 | $13.52 | $705 | 5/7 | 38/61 | 96.6 bp | 31.6% |
| MNQ | 196 | +$6,482 | 1.59 | $33.07 | $1,280 | 7/7 | 40/62 | 150.3 bp | 8.9% |
| MYM | 195 | +$858 | 1.16 | $4.40 | $632 | 3/7 | 35/59 | 48.9 bp | 42.4% |
| MES+MNQ | 366 | +$8,781 | 1.53 | $23.99 | $1,838 | 7/7 | 42/65 | 125.4 bp | 16.2% |
| All | 561 | +$9,639 | 1.44 | $17.18 | $2,298 | 6/7 | 39/65 | 98.8 bp | 19.5% |

IS year contribution:

| Year | MES | MNQ | MYM | MES+MNQ | All |
|---:|---:|---:|---:|---:|---:|
| 2018 | -$93 | +$190 | -$44 | +$97 | +$53 |
| 2019 | -$273 | +$333 | -$239 | +$60 | -$180 |
| 2020 | +$333 | +$674 | +$281 | +$1,006 | +$1,287 |
| 2021 | +$44 | +$83 | -$61 | +$127 | +$65 |
| 2022 | +$479 | +$889 | +$561 | +$1,367 | +$1,928 |
| 2023 | +$618 | +$2,058 | -$26 | +$2,675 | +$2,649 |
| 2024 | +$1,193 | +$2,256 | +$387 | +$3,449 | +$3,836 |

IS bootstrap by instrument:

| Group | Days | p05 | p50 | p95 | p_pos |
|---|---:|---:|---:|---:|---:|
| MES | 170 | +$87 | +$2,309 | +$4,482 | 95.6% |
| MNQ | 196 | +$2,279 | +$6,501 | +$10,708 | 99.6% |
| MYM | 195 | -$970 | +$855 | +$2,697 | 78.2% |
| MES+MNQ | 225 | +$2,802 | +$8,749 | +$14,709 | 99.2% |
| All | 283 | +$2,593 | +$9,692 | +$16,764 | 98.6% |

IS permutation test, trade-level: MYM average minus MES+MNQ average = **-$19.59/trade**.
One-sided permutation probability of a gap this bad or worse under random instrument assignment:
**p = 0.047**.

OOS check after the IS-only rationale:

| Group | 2025 | 2026 | OOS pooled | OOS bootstrap p05 / p50 / p95 |
|---|---:|---:|---:|---|
| MES | +$748 | +$288 | +$1,035 | -$142 / +$1,033 / +$2,223 |
| MNQ | +$1,159 | +$626 | +$1,785 | -$795 / +$1,816 / +$4,337 |
| MYM | -$889 | +$159 | -$731 | -$2,104 / -$694 / +$614 |
| MES+MNQ | +$1,907 | +$914 | +$2,821 | -$567 / +$2,814 / +$6,263 |
| All | +$1,018 | +$1,073 | +$2,090 | -$1,991 / +$1,983 / +$6,279 |

Read:

- Excluding MYM now has a legitimate IS-first rationale: MYM has much lower average trade, weaker
  PF, only 3/7 positive IS years, negative IS bootstrap p05, and materially worse cost drag.
- The OOS result is consistent with that rationale, but it is **not** the reason for choosing the
  filter.
- This cleans up the provenance problem for MES+MNQ-only, but it does **not** promote the sleeve to
  deploy level because MES+MNQ OOS bootstrap still crosses below zero.

MYM-rationale verdict: **MES+MNQ-only is the cleanest causal paper candidate**, no longer just an
OOS-informed sensitivity. Status remains **paper/pilot, not deploy-level**.

#### Causal PCLoc Volume Overlay

Date: 2026-08-21. Scratch probe: `scratch/calm_causal_pcloc_volume_overlay.py`.

Scope: test whether causal pre-entry volume can improve the cleanest Calm paper candidate. The
base remains `lag1calm_pcloc_bottom_down_long_e1000_x1555`; volume features use only 09:30-09:59
data before the 10:00 entry. Relative volume is measured against rolling prior-session medians
(`vol_ratio60`, shifted one session). No full-day volume and no same-day regime label is used.

IS 2018-2024:

| Filter | Trades | Net | PF | Avg/trade | MaxDD | Pos years | Pos inst | MES / MNQ / MYM |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| base all instruments | 561 | +$9,639 | 1.44 | $17.18 | $2,298 | 6/7 | 3 | +$2,299 / +$6,482 / +$858 |
| MES+MNQ | 366 | +$8,781 | 1.53 | $23.99 | $1,838 | 7/7 | 2 | +$2,299 / +$6,482 / $0 |
| MES+MNQ, vol60 <= 1.50 | 324 | +$8,754 | 1.61 | $27.02 | $1,720 | 6/7 | 2 | +$2,828 / +$5,926 / $0 |
| MES+MNQ, 0.80 <= vol60 <= 1.50 | 267 | +$7,898 | 1.64 | $29.58 | $1,767 | 7/7 | 2 | +$2,155 / +$5,743 / $0 |
| MES+MNQ, vol60 <= 1.20 | 254 | +$7,492 | 1.72 | $29.49 | $2,288 | 6/7 | 2 | +$1,946 / +$5,545 / $0 |

OOS pooled 2025+2026 for IS-selected filters:

| Filter | Trades | Net | PF | Avg/trade | MaxDD | Pos years | Pos inst | MES / MNQ / MYM | Day bootstrap p05 / p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| MES+MNQ | 79 | +$2,821 | 1.70 | $35.71 | $1,491 | 2/2 | 2 | +$1,035 / +$1,785 / $0 | -$610 / +$2,795 / +$6,163 |
| base all instruments | 125 | +$2,090 | 1.33 | $16.72 | $1,936 | 2/2 | 2 | +$1,035 / +$1,785 / -$731 | -$1,878 / +$2,094 / +$6,205 |
| MES+MNQ, vol60 <= 1.50 | 61 | +$1,254 | 1.36 | $20.56 | $1,491 | 2/2 | 2 | +$225 / +$1,029 / $0 | -$1,666 / +$1,276 / +$4,095 |
| MES+MNQ, 0.80 <= vol60 <= 1.50 | 44 | +$1,141 | 1.42 | $25.94 | $1,183 | 1/2 | 2 | +$494 / +$647 / $0 | -$1,534 / +$1,167 / +$3,758 |
| MES+MNQ, vol60 <= 1.20 | 50 | +$687 | 1.24 | $13.74 | $1,303 | 1/2 | 2 | +$230 / +$456 / $0 | -$1,955 / +$752 / +$3,086 |

Read:

- Volume caps improve IS PF/average trade, but they do not transfer OOS.
- The 2026 sanity window is the failure point: `vol60 <= 1.50` drops from +$914 baseline
  MES+MNQ to only +$37, and tighter caps go negative.
- Spike/exhaustion variants did not pass IS selection because sample size and/or dollars collapsed.
- The best OOS row remains plain MES+MNQ. Volume overlay is therefore not a useful deploy selector.

Volume-overlay verdict: **reject**. Do not add pre-10 relative-volume gates to this Calm candidate.

#### Causal PCLoc SPY D-1 Context Overlay

Date: 2026-08-21. Scratch probe: `scratch/calm_causal_pcloc_spy_context.py`.

Scope: test causal SPY context filters on the clean Calm candidate. SPY data available locally is
`spy_daily_live.csv` with close only, so this pass tests D-1 return, 3-day return, SMA50 state, and
realised-volatility caps. SPY features are assigned with a strict previous-close as-of merge; no
same-day SPY close is used. VIX, SPY OHLC close-location, and event calendar were not available in
local files for this pass.

IS thresholds are computed from 2018-2024 candidate days only:

| Threshold | Value |
|---|---:|
| SPY RV20 p50 | 0.006173 |
| SPY RV20 p70 | 0.007218 |
| SPY RV20 p80 | 0.007700 |
| SPY D-1 return p10 | -0.008278 |
| SPY D-1 return p25 | -0.005188 |
| SPY D-1 return p75 | +0.000450 |

IS 2018-2024:

| Filter | Trades | Net | PF | Avg/trade | MaxDD | Pos years | Pos inst | MES / MNQ |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| MES+MNQ baseline | 366 | +$8,781 | 1.53 | $23.99 | $1,838 | 7/7 | 2 | +$2,299 / +$6,482 |
| SPY D-1 not crash (`ret1 >= -1.5%`) | 362 | +$8,780 | 1.54 | $24.25 | $1,838 | 6/7 | 2 | +$2,287 / +$6,493 |
| SPY 3-day down | 203 | +$8,021 | 1.87 | $39.51 | $1,524 | 6/7 | 2 | +$1,907 / +$6,113 |
| SPY above SMA50 | 333 | +$7,701 | 1.54 | $23.12 | $1,611 | 6/7 | 2 | +$2,188 / +$5,513 |
| SPY D-1 return above IS p10 | 316 | +$7,579 | 1.53 | $23.98 | $1,798 | 5/7 | 2 | +$2,109 / +$5,470 |
| SPY D-1 down | 282 | +$6,488 | 1.48 | $23.01 | $1,886 | 5/7 | 2 | +$1,095 / +$5,393 |
| SPY D-1 mild down | 278 | +$6,487 | 1.50 | $23.33 | $1,886 | 5/7 | 2 | +$1,083 / +$5,404 |

Formal OOS 2025, if 2026 is treated only as sanity:

| Filter | Trades | Net | PF | Avg/trade | MaxDD | Day bootstrap p05 / p50 / p95 |
|---|---:|---:|---:|---:|---:|---|
| SPY D-1 return above IS p10 | 38 | +$1,957 | 2.86 | $51.50 | $326 | +$353 / +$1,948 / +$3,626 |
| SPY above SMA50 | 46 | +$1,913 | 2.32 | $41.59 | $357 | +$138 / +$1,908 / +$3,692 |
| MES+MNQ baseline | 48 | +$1,907 | 2.28 | $39.72 | $362 | +$135 / +$1,927 / +$3,745 |
| SPY 3-day down | 25 | +$1,753 | 4.35 | $70.11 | $362 | +$416 / +$1,742 / +$3,081 |
| SPY D-1 not crash | 46 | +$1,742 | 2.17 | $37.87 | $362 | -$11 / +$1,712 / +$3,527 |
| SPY D-1 down | 41 | +$1,002 | 1.67 | $24.45 | $362 | -$632 / +$995 / +$2,681 |
| SPY D-1 mild down | 39 | +$838 | 1.56 | $21.48 | $362 | -$747 / +$844 / +$2,492 |

2026 sanity:

| Filter | Trades | Net | PF | Read |
|---|---:|---:|---:|---|
| SPY D-1 down / mild down | 25 | +$959 | 1.42 | beats baseline, both instruments positive |
| MES+MNQ baseline | 31 | +$914 | 1.36 | still positive |
| SPY D-1 return above IS p10 | 28 | +$254 | 1.12 | weak sanity |
| SPY 3-day down | 16 | +$163 | 1.09 | weak sanity, MNQ negative |
| SPY above SMA50 | 27 | -$638 | 0.75 | fails sanity |

Read:

- RV caps did not help; lower RV filters reduced IS dollars and robustness.
- SPY D-1 down/mild-down is not useful in 2025 OOS.
- `SPY 3-day down` is the most interesting quality overlay in IS and 2025: much higher PF and
  average trade, with positive 2025 bootstrap p05. But it has only 203 IS trades and 25 2025
  trades, and 2026 sanity is weak.
- `SPY D-1 return above IS p10` is a simple tail-exclusion filter. It slightly beats baseline in
  2025 and has positive 2025 bootstrap p05, but it ranks below baseline on IS dollars and weakens
  2026 sanity.

SPY-context verdict: **keep digging / watchlist, not a spec change yet**. If 2026 is not part of
the formal OOS gate, `SPY 3-day down` and `SPY D-1 return above IS p10` are the only SPY overlays
worth retesting in a stricter WFO or paper-pilot protocol. Do not add SPY RV caps.

#### Causal PCLoc Futures Shape / Gap Overlay

Date: 2026-08-21. Scratch probe: `scratch/calm_causal_pcloc_shape_gap.py`.

Scope: test factors closer to the mechanism without using same-day labels: prior RTH day shape and
current RTH open/gap quality. Base remains D-1 Calm, prior-close bottom-down, LONG 10:00 to 15:55,
MES+MNQ only. Features are built from futures RTH OHLC and are causal at 10:00.

Repair note after independent audit: the scratch probe now matches the causal excavation convention
for prior RTH session selection. A session can become the "prior RTH session" only if it has a
15:55 bar; half-days are skipped rather than used as the prior close/range source. This changes
2026 sanity only; IS and 2025 headline `not_deep_gap` numbers are unchanged.

IS thresholds from 2018-2024 MES+MNQ candidate trades:

| Threshold | Value |
|---|---:|
| Prior RTH range p60 | 0.009885 |
| Prior RTH range p70 | 0.011293 |
| Prior RTH range p80 | 0.013053 |
| Prior body/range p50 | 0.601587 |
| Prior body/range p70 | 0.713433 |
| Gap p10 | -0.006573 |
| Gap p90 | +0.005381 |

IS 2018-2024:

| Filter | Trades | Net | PF | Avg/trade | MaxDD | Pos years | Pos inst | MES / MNQ |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| not deep gap (`gap >= -1.0%`) | 349 | +$9,718 | 1.67 | $27.85 | $1,720 | 6/7 | 2 | +$2,730 / +$6,988 |
| no gap extreme (`p10 <= gap <= p90`) | 292 | +$9,208 | 1.87 | $31.53 | $1,627 | 6/7 | 2 | +$3,153 / +$6,055 |
| small gap (`-0.5% <= gap <= +0.5%`) | 266 | +$9,203 | 1.99 | $34.60 | $1,479 | 6/7 | 2 | +$2,834 / +$6,369 |
| open inside prior range | 224 | +$9,078 | 2.05 | $40.53 | $1,627 | 7/7 | 2 | +$2,821 / +$6,257 |
| ok gap (`-1.0% <= gap <= +1.0%`) | 342 | +$8,958 | 1.62 | $26.19 | $1,854 | 6/7 | 2 | +$2,637 / +$6,322 |
| baseline MES+MNQ | 366 | +$8,781 | 1.53 | $23.99 | $1,838 | 7/7 | 2 | +$2,299 / +$6,482 |

Formal OOS 2025:

| Filter | Trades | Net | PF | Avg/trade | MaxDD | Day bootstrap p05 / p50 / p95 |
|---|---:|---:|---:|---:|---:|---|
| not deep gap | 44 | +$2,050 | 2.69 | $46.58 | $362 | +$331 / +$2,032 / +$3,818 |
| baseline MES+MNQ | 48 | +$1,907 | 2.28 | $39.72 | $362 | +$89 / +$1,881 / +$3,714 |
| no gap extreme | 29 | +$1,714 | 3.47 | $59.09 | $326 | +$356 / +$1,683 / +$3,116 |
| small gap | 27 | +$1,645 | 3.38 | $60.94 | $326 | +$329 / +$1,634 / +$3,114 |
| ok gap | 41 | +$1,601 | 2.32 | $39.04 | $399 | +$10 / +$1,620 / +$3,272 |
| open inside prior range | 33 | +$1,426 | 2.29 | $43.21 | $364 | -$188 / +$1,400 / +$3,005 |

2026 sanity:

| Filter | Trades | Net | PF | Read |
|---|---:|---:|---:|---|
| not deep gap | 28 | +$1,185 | 1.61 | positive; one half-day-prior loss is now skipped |
| baseline MES+MNQ | 31 | +$914 | 1.36 | positive |
| ok gap | 25 | +$880 | 1.48 | positive |
| no gap extreme | 18 | +$833 | 1.82 | positive but MES negative |
| small gap | 14 | +$754 | 1.99 | strong quality but very small sample |
| open inside prior range | 19 | +$685 | 1.44 | positive |

Read:

- Gap/open quality is more useful than volume and RV caps.
- `not_deep_gap` is the practical overlay: it keeps most trades, improves IS and 2025 dollars/PF,
  and remains positive in 2026 sanity. It mostly removes deep gap-down continuation risk.
- `small_gap` / `no_gap_extreme` are quality overlays: higher PF, average trade, and better
  bootstrap, but cut 2025 to 27-29 trades.
- Prior-day range/body shape by itself did not help; the useful factor is current open/gap quality,
  not "orderly down" shape.

Shape/gap verdict after audit: **PAPER/PILOT ONLY**. Promote `not_deep_gap` to the single Calm
paper-pilot spec, not deploy-level. Candidate spec becomes: D-1 Calm, PCLoc bottom-down, MES+MNQ,
LONG 10:00 to 15:55, skip if RTH open gaps more than 1.0% below prior full RTH-session close. Use
4 ticks/side for pilot sizing; do not add volume, SPY RV, or recursive instrument-pruning rules.

#### Causal PCLoc M2K/RTY Add-On Probe

Date: 2026-08-21. Scratch probe: `scratch/calm_causal_pcloc_m2k_probe.py`.

Scope: test whether M2K/RTY can add diversification to the paper-pilot Calm candidate. Same
mechanism: D-1 Calm, prior-close bottom-down, LONG 10:00 to 15:55. Gap features use the repaired
full-session prior RTH convention.

| Window | Filter | Trades | Net | PF | Avg/trade | MaxDD | Bootstrap p05 / p50 / p95 |
|---|---|---:|---:|---:|---:|---:|---|
| IS 2018-2024 | M2K base | 229 | -$504 | 0.93 | -$2.20 | $1,301 | -$2,701 / -$488 / +$1,550 |
| IS 2018-2024 | M2K not-deep-gap | 221 | -$517 | 0.92 | -$2.34 | $1,218 | -$2,618 / -$531 / +$1,455 |
| 2025 OOS | M2K base | 35 | -$306 | 0.78 | -$8.75 | $561 | -$1,119 / -$308 / +$519 |
| 2025 OOS | M2K not-deep-gap | 32 | -$421 | 0.70 | -$13.16 | $676 | -$1,222 / -$425 / +$385 |

Read: M2K fails IS and formal 2025 OOS, and `not_deep_gap` does not rescue it. No 2026 sanity run
is needed for selection because the add-on fails before the sanity step.

M2K verdict: **reject as Calm add-on**. Do not add M2K/RTY to the paper-pilot spec.

#### Causal Market-Wide MES Setup Probe

Date: 2026-08-21. Scratch probe:
`scratch/calm_causal_marketwide_setup_from_artifacts.py`.

Scope: keep D-1 Calm and the PCLoc bottom-down mechanism, but move the setup definition from
per-instrument to market-wide. MES/ES defines the setup day; if MES has the causal PCLoc
bottom-down condition, trade the MES+MNQ basket from 10:00 to 15:55. This avoids requiring MNQ to
have its own PCLoc setup on the same day. The probe uses already-audited shape/gap artifacts as the
source of D-1 Calm MES setup days, then rebuilds MES/MNQ daily execution rows from local futures
1m data.

IS 2018-2024:

| Variant | Trades | Days | Net | PF | Avg/trade | MaxDD | Pos years | MES / MNQ |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| MES setup, trade MES+MNQ, instrument not-deep gap | 324 | 165 | +$10,156 | 1.80 | $31.35 | $1,662 | 6/7 | +$2,730 / +$7,426 |
| MES setup, trade MES+MNQ, both market+instrument not-deep | 323 | 164 | +$10,105 | 1.79 | $31.29 | $1,662 | 6/7 | +$2,730 / +$7,375 |
| MES setup, market not-deep gap | 328 | 164 | +$9,404 | 1.68 | $28.67 | $1,662 | 5/7 | +$2,730 / +$6,674 |
| MES setup, no gap filter | 340 | 170 | +$8,591 | 1.58 | $25.27 | $1,878 | 5/7 | +$2,299 / +$6,292 |

Formal OOS 2025:

| Variant | Trades | Days | Net | PF | Avg/trade | MaxDD | Bootstrap p05 / p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|---|
| MES setup, market not-deep gap | 52 | 26 | +$2,606 | 2.62 | $50.11 | $589 | +$485 / +$2,576 / +$4,756 |
| MES setup, instrument not-deep gap | 51 | 26 | +$2,569 | 2.60 | $50.37 | $589 | +$451 / +$2,541 / +$4,748 |
| MES setup, both market+instrument not-deep | 51 | 26 | +$2,569 | 2.60 | $50.37 | $589 | +$427 / +$2,600 / +$4,773 |
| MES setup, no gap filter | 54 | 27 | +$2,330 | 2.24 | $43.15 | $589 | +$140 / +$2,315 / +$4,575 |

2026 sanity:

| Variant | Trades | Days | Net | PF | Read |
|---|---:|---:|---:|---:|---|
| MES setup, market not-deep gap | 28 | 14 | +$1,420 | 1.63 | positive |
| MES setup, no gap filter | 28 | 14 | +$1,420 | 1.63 | same as market gap in 2026 |
| MES setup, instrument not-deep gap | 26 | 14 | +$1,042 | 1.50 | positive |
| MES setup, both market+instrument not-deep | 26 | 14 | +$1,042 | 1.50 | positive |

Pooled 2025+2026 sanity:

| Variant | Trades | Days | Net | PF | Bootstrap p05 / p50 / p95 |
|---|---:|---:|---:|---:|---|
| MES setup, market not-deep gap | 80 | 40 | +$4,026 | 2.05 | +$277 / +$4,039 / +$7,796 |
| MES setup, instrument not-deep gap | 77 | 40 | +$3,611 | 1.98 | +$49 / +$3,688 / +$7,217 |
| MES setup, both market+instrument not-deep | 77 | 40 | +$3,611 | 1.98 | -$7 / +$3,607 / +$7,066 |
| MES setup, no gap filter | 82 | 41 | +$3,751 | 1.91 | -$251 / +$3,720 / +$7,525 |

Read:

- Market-wide MES setup improves dollars and trade count versus the current per-instrument
  paper-pilot spec, especially by letting MNQ trade on MES-defined setup days.
- Best practical row is `market not-deep gap`: 52 trades and +$2,606 in 2025, 80 trades and
  +$4,026 pooled sanity.
- This is still not deploy-level evidence. It is a new hypothesis discovered after many OOS reads,
  so it inherits the same paper/pilot-only status and needs independent paper-forward.
- If promoted to paper, this should replace rather than stack on top of the per-instrument PCLoc
  candidate, otherwise days overlap heavily and attribution becomes double-counted.

Market-wide verdict: **stronger paper/pilot candidate, not deploy-level**. Tentative spec:
D-1 Calm, MES/ES PCLoc bottom-down market setup, market gap >= -1.0%, trade MES+MNQ LONG
10:00 to 15:55.

### Calm Sample-Count Fold Protocol

Date: 2026-08-21. Scratch probe: `scratch/calm_sample_count_folds.py`.

Status after later causality audit: **SUPERSEDED for deploy evidence.** This section used
same-day Calm labels for `openloc_liveable`, `pcloc_liveable`, `prior_reclaim`, and `negon_legacy`.
Those folds are useful only as an explanation of why calendar-year 2022 was too thin; they are not
valid deploy evidence for an intraday strategy. The causal follow-up is the section immediately
above: `lag1calm_pcloc_bottom_down_long_e1000_x1555` is the best causal paper candidate, and it
still fails deploy gate.

Question: if the calendar-year fold is invalid for Calm because 2022 contains only six Calm days,
what happens if folds are built by chronological **Calm sample count** instead?

Families included:

- `negon_legacy`: raw/mod001/mod002 negative-overnight candidates. Included for comparison only;
  this family still carries the earlier OOS-informed bucket caveat.
- `openloc_liveable`: lower-third 10:00, with/without SPY-above filter.
- `pcloc_liveable`: prior close bottom-third variants.
- `prior_reclaim`: prior-day low reclaim variants.

Protocol A: expanding train 300 Calm days, held-out 150 Calm days.

| Family | Held-out folds | Aggregate selected held-out | Meaningful folds | Winner matches | Read |
|---|---:|---:|---:|---:|---|
| negon legacy | 3 | +$9,548 / 466 trades | 3/3 | 1/3 | Strong dollars, selector unstable; legacy caveat remains |
| openloc liveable | 3 | +$6,661 / 365 trades | 3/3 | 1/3 | All folds positive and meaningful |
| pcloc liveable | 2 selected folds | +$5,384 / 240 trades | 2/2 | 1/2 | First fold has no eligible train selection |
| prior reclaim | 3 | +$4,978 / 272 trades | 3/3 | 1/3 | Positive IS folds, but known 2026 OOS rejection remains |
| global all strong | 3 | +$9,548 / 466 trades | 3/3 | 0/3 | Global selector chooses negon legacy; no held-out winner match |

Openloc fold detail under Protocol A:

| Fold | Test span | Selected | Held-out net | PF | Winner | Rank |
|---|---|---|---:|---:|---|---:|
| f1 | 2019-12-31 to 2021-07-28 | lower-third 10:00 | +$2,333 | 1.56 | SPY-above lower-third | 2 |
| f2 | 2021-07-29 to 2023-09-08 | lower-third 10:00 | +$1,724 | 1.28 | lower-third 10:00 | 1 |
| f3 | 2023-09-11 to 2024-10-01 | lower-third 10:00 | +$2,604 | 1.68 | SPY-above lower-third | 2 |

Protocol B sensitivity: expanding train 300 Calm days, held-out 100 Calm days.

| Family | Held-out folds | Aggregate selected held-out | Meaningful folds | Winner matches | Read |
|---|---:|---:|---:|---:|---|
| negon legacy | 5 | +$8,949 / 532 trades | 5/5 | 1/5 | Strong but selector unstable and legacy caveat remains |
| openloc liveable | 5 | +$6,872 / 406 trades | 5/5 | 1/5 | One negative fold, aggregate remains strong |
| pcloc liveable | 4 selected folds | +$4,703 / 320 trades | 4/4 | 2/4 | Mixed middle folds, late folds strong |
| prior reclaim | 5 | +$5,906 / 299 trades | 5/5 | 1/5 | Positive aggregate, weak middle folds |
| global all strong | 5 | +$8,949 / 532 trades | 5/5 | 0/5 | Global selector still fails to pick held-out winners |

Openloc fold detail under Protocol B:

| Fold | Test span | Held-out net | PF | Winner rank |
|---|---|---:|---:|---:|
| f1 | 2019-12-31 to 2021-04-13 | +$2,770 | 2.28 | 2 |
| f2 | 2021-04-14 to 2021-11-04 | +$1,503 | 1.60 | 1 |
| f3 | 2021-11-05 to 2023-09-08 | -$216 | 0.96 | 2 |
| f4 | 2023-09-11 to 2024-05-23 | +$1,150 | 1.39 | 2 |
| f5 | 2024-05-24 to 2024-12-26 | +$1,664 | 1.47 | 2 |

Read:

- Sample-count folds solve the calendar-year 2022 denominator problem. Every openloc held-out
  fold becomes meaningful.
- Openloc 10:00 looks materially better under this validation: +$6.7k held-out across both
  fold schemes, with all 150-day folds positive and 4/5 of the 100-day folds positive.
- The selector still does not reliably choose the held-out winner. Most openloc misses are between
  lower-third and SPY-above lower-third, which are very close variants of the same mechanism.
- Global selection is not deploy-clean: it keeps selecting negative-overnight legacy variants, but
  those still carry the OOS-informed bucket problem and do not match held-out winners.
- Prior reclaim improves under sample-count folds but remains blocked by its already measured 2026
  OOS failure.

Conclusion:

- If Calm validation is changed from calendar years to Calm sample-count folds, **openloc 10:00 is
  the strongest standalone paper candidate**.
- It still should not be promoted automatically: the validation protocol itself changed after the
  candidate was discovered, and the selector/winner mismatch remains. The right label is stronger
  paper evidence, not deploy-level confirmation.

## Normal Gap/Open + SPY Context Probe

Date: 2026-08-21. Scratch probe: `scratch/normal_sleeve_gap_spy_context_probe_20260821.py`.

This is for the current Normal sleeve, not Calm. The probe uses the corrected Normal trade tables
and replays context filters without editing production engine/cap code. SPY local data currently
has only `date,close`, so SPY tests are limited to D-1 returns, SMA50, and RV20; SPY close-location
and ATR percentile are not available from this CSV.

Current corrected baseline:

| Window | Net | PF | Sharpe | Calmar | MaxDD |
|---|---:|---:|---:|---:|---:|
| floor | +$33,176 | 1.36 | 1.73 | 0.52 | 18.5% |
| 2025 | +$6,857 | 1.51 | 2.33 | 1.47 | 10.1% |
| 2026 | +$6,743 | 1.46 | 2.43 | 1.62 | 15.0% |

Best floor-ranked context filters:

| Filter | floor | 2025 | 2026 | Read |
|---|---:|---:|---:|---|
| `all_prev_range_le_p90` | +$35,168 PF 1.42 Calmar 0.80 | +$8,371 PF 1.62 Calmar 1.80 | +$5,718 PF 1.41 Calmar 1.43 | Best broad prior-day structure filter; improves floor/2025, slightly weakens 2026 |
| `r4_prev_range_le_p90` | +$33,956 PF 1.40 Calmar 0.76 | +$8,371 PF 1.62 Calmar 1.80 | +$7,036 PF 1.48 Calmar 1.76 | Cleanest balanced candidate; keeps 2026 positive/improved |
| `r4_spy_not_crash` | +$32,920 PF 1.40 Calmar 0.83 | +$5,943 PF 1.40 Calmar 1.28 | +$6,108 PF 1.42 Calmar 1.47 | Good floor drawdown cut, but both OOS windows weaker than baseline |
| `r4_short_spy_ret3_down` | +$35,116 PF 1.42 Calmar 0.79 | +$2,952 PF 1.23 Calmar 0.63 | +$8,198 PF 1.62 Calmar 2.24 | Too split: strong 2026, weak 2025 |
| `all_open_not_deep` | +$27,924 PF 1.40 Calmar 0.75 | +$4,797 PF 1.40 Calmar 1.47 | +$9,838 PF 2.15 Calmar 4.60 | Interesting risk filter, but gives up too much floor/2025 net |

Read:

- **Prior-day futures range cap** is the most useful family so far. It is causal, simple, and does
  not rely on many thresholds. `r4_prev_range_le_p90` is the best next-test candidate.
- **SPY D-1 mild-down** is probably overfit for Normal: `all_spy_ret_mild_down` ranks first on floor
  Calmar (+$21,990 PF 1.54 Calmar 0.93) but fails 2025 (-$655 PF 0.91).
- **Gap/open filters** improve 2026 strongly, but they tend to give up too much floor/2025. Keep as
  risk-control clues rather than signal filters for now.
- SPY RV20 cap is not a winner here either.

Verdict: **keep testing `r4_prev_range_le_p90`; put SPY mild-down and detailed gap/open filters in
the overfit/after bucket**. Next step is to combine `r4_prev_range_le_p90` with the earlier R4
volume band (`r4_slot_0.6_2` or `r4_slot_le_2`) and compare against strict 2.5% cap.

### Normal Context Combo Probe

Date: 2026-08-21. Scratch probe: `scratch/normal_sleeve_context_combo_probe_20260821.py`.

Status after promotion audit: **SUPERSEDED as promotion evidence.** This section is a
row-deletion/post-process read of saved trade JSON. The later promotion audit regenerated the
strategy at the decision boundary and should be used for all candidate figures.

Tested combinations of:

- `range_p90`: apply only to R4; skip R4 trades when prior-day futures RTH range is above the floor
  p90 threshold.
- `vol_06_2`: apply only to R4; require entry-bar relative volume versus same time-slot median20
  between 0.6x and 2.0x.
- `vol_le_2`: apply only to R4; skip only high-volume R4 entries above 2.0x same time-slot median20.
- Current cap versus strict 2.5% R4 cap.

Best cross-window reads:

| Rule | Cap | floor | 2025 | 2026 | Read |
|---|---|---:|---:|---:|---|
| `range_p90__vol_le_2` | current | +$34,109 PF 1.44 Calmar 1.04 | +$8,537 PF 1.71 Calmar 2.37 | +$8,313 PF 1.69 Calmar 2.77 | Best balanced current-cap candidate |
| `range_p90__vol_06_2` | current | +$34,460 PF 1.46 Calmar 1.06 | +$7,279 PF 1.60 Calmar 1.73 | +$7,947 PF 1.66 Calmar 2.65 | Slightly higher floor quality, weaker 2025 |
| `range_p90` | current | +$37,471 PF 1.44 Calmar 0.96 | +$8,371 PF 1.62 Calmar 1.80 | +$7,036 PF 1.48 Calmar 1.76 | Best dollars, less drawdown improvement than combo |
| `range_p90__vol_le_2` | strict025 | +$18,975 PF 1.34 Calmar 0.64 | +$6,280 PF 1.69 Calmar 1.86 | +$7,810 PF 1.87 Calmar 4.22 | Very strong OOS risk, but floor net/Calmar worse |

Read:

- The best current-cap combo is **R4 prior-range p90 cap + R4 high-volume skip**:
  `range_p90__vol_le_2`.
- It improves all three windows versus current corrected baseline, with floor Calmar roughly doubling
  from 0.52 to 1.04 and 2025/2026 both improving.
- Strict 2.5% cap remains useful as a conservative risk policy, but when combined with these filters
  it gives up too much floor net versus current-cap combo.

Verdict: **best Normal research candidate so far, still not production-promoted**. Next gate should
be a no-lookahead implementation audit: prove the prior-range and time-slot median20 volume features
can be computed live from data available before the R4 entry decision, then rerun fill audit and
portfolio replay from generated trades.

### Normal R4/NKD Split Read

Date: 2026-08-21. Scratch probe: `scratch/normal_sleeve_r4_nkd_split_probe_20260821.py`.

Status after promotion audit: **SUPERSEDED as promotion evidence.** The split is still useful as a
mechanism clue, but the later regenerated audit is the source of record for R4 filtered, NKD-only,
and combined sleeve numbers.

Question: should NKD be treated as its own sleeve rather than as part of one homogeneous Normal
bucket?

Split results for `range_p90__vol_le_2`:

| Variant | Cap | floor | 2025 | 2026 |
|---|---|---:|---:|---:|
| R4 filtered only | current | +$30,211 PF 1.57 Calmar 0.71 | +$6,334 PF 1.94 Calmar 3.47 | +$2,305 PF 1.39 Calmar 1.13 |
| NKD only | current | +$3,898 PF 1.15 Calmar 0.14 | +$2,203 PF 1.42 Calmar 1.23 | +$6,007 PF 1.95 Calmar 4.35 |
| R4 filtered + NKD | current | +$34,109 PF 1.44 Calmar 1.04 | +$8,537 PF 1.71 Calmar 2.37 | +$8,313 PF 1.69 Calmar 2.77 |
| R4 filtered only | strict025 | +$15,077 PF 1.48 Calmar 0.60 | +$4,077 PF 2.06 Calmar 2.59 | +$1,802 PF 1.65 Calmar 1.71 |
| R4 filtered + NKD | strict025 | +$18,975 PF 1.34 Calmar 0.64 | +$6,280 PF 1.69 Calmar 1.86 | +$7,810 PF 1.87 Calmar 4.22 |
| R4 raw + NKD | current baseline | +$33,176 PF 1.36 Calmar 0.52 | +$6,857 PF 1.51 Calmar 1.47 | +$6,743 PF 1.46 Calmar 1.62 |

Read:

- NKD is not just noise: it adds +$3.9k floor, +$2.2k in 2025, and +$6.0k in 2026 as a standalone
  component. But its floor Calmar/PF are weak, so it should not be assessed under the same R4 filter
  logic.
- R4 filtered carries most of the floor/2025 edge and fixes the raw R4 account-halt problem.
- R4 filtered + NKD is better than either alone across the three windows, but the mechanisms are
  different enough that they should be documented and risk-governed as two sleeves:
  `Normal-R4` and `Normal-NKD`.

Verdict: **treat NKD as a separate Normal sleeve for research and promotion audit**. Do not apply
the R4 range/volume filters to NKD. NKD still needs its own production gate: gap-through fill fix,
slippage stress, timezone/live execution audit, and concentration bootstrap.

### Normal promotion audit - R4 context filter and NKD as separate sleeves - 2026-08-21

Artifacts (all scratch, read-only):

- `scratch/normal_promotion_filter_lib_20260821.py` - the single filter implementation, used by both the audit and the run
- `scratch/normal_promotion_lookahead_audit_20260821.py` / `.txt` / `.json`
- `scratch/normal_promotion_regen_audit_20260821.py` / `.txt` / `.json`
- `scratch/normal_promotion_variant_matrix_20260821.py` / `.txt` / `.json`
- `scratch/normal_promotion_nkd_sleeve_audit_20260821.py` / `.txt` / `.json`
- Regenerated trade tables: `scratch/normal_promotion_trades_{floor,vault2025,vault2026}_20260821.json`

No production file was modified and nothing was committed. `global_index/deploy_sim.py`
carries another session's uncommitted change and was not touched.

Candidate: Normal regime only, Ro-4 EMA50, 2x daily ATR fixed stop armed 14:05 next
session, max_hold 5, SHORT only when SPY D-1 close is below its SMA50, 2 ticks/side,
1 micro, $50,000, Stress disabled. R4 gated by `range_p90__vol_le_2`; NKD ungated and
treated as its own sleeve.

#### Two things that had to be established before any number could be read

**The engine gap-through fix is not in production.** `futures/_validated_core.py` still
requires `bool(isg[i])` - a time break longer than `GAP_MIN = 15.0` minutes - before a
stop may fill at the bar open, and there is no diff. The corrected baseline this
candidate is measured against was produced while production was temporarily patched;
that patch has been reverted. Every run below re-applies the fix scratch-side and
anchors to the stated baseline: floor $33,176, 2025 $6,857, 2026 $6,743 - **all three
reproduced exactly**.

Related trap: `scratch/normal_sleeve_enginefix_policy_anchor_20260821.py` prints "Real
engine path after gap-through fix" but applies no fix itself - it just calls `run_case`.
Re-run today it measures the unfixed engine under a banner that says otherwise.

**The published candidate numbers are row deletions, not a filtered strategy run.** The
context probes filter the saved trade JSON. Inside the engine a rejected signal does not
empty the day: the 14:00-15:55 scan continues and can enter on a later bar, and the book
stays flat, which changes what the following sessions can do. Deleting rows models
neither effect. Reproducing the deletion exactly confirms the provenance:

| Window | Figure on record | Reproduced by row-deletion | Regenerated at the decision boundary |
|---|---|---|---|
| floor | +$34,109 PF 1.44 Sharpe 2.03 Calmar 1.04 MaxDD 9.5% | identical | **+$33,970 PF 1.40 Sharpe 1.84 Calmar 0.88 MaxDD 11.3%** |
| 2025 | +$8,537 PF 1.71 Sharpe 2.87 Calmar 2.37 MaxDD 7.8% | identical | **+$7,323 PF 1.47 Sharpe 1.84 Calmar 1.61 MaxDD 9.8%** |
| 2026 | +$8,313 PF 1.69 Sharpe 3.29 Calmar 2.77 MaxDD 10.8% | identical | **+$8,675 PF 1.67 Sharpe 3.26 Calmar 3.48 MaxDD 9.0%** |

Regenerating adds 31-44 trades per instrument on floor. The record overstates Calmar by
15% on floor and 32% on 2025 - the two windows allowed to select - and understates it on
2026, which is not.

#### 1. No-lookahead audit - PASS

Each feature is recomputed from a frame **hard cut** at the decision instant (every bar
at or after the cut physically removed) and compared with what the live filter serves.
Each check is paired with a deliberately non-causal mutation that must fail, so a green
result cannot come from a comparison with no way to disagree.

| Check | Result, all 4 instruments x 3 windows | Mutation caught |
|---|---|---|
| prior-day RTH range | 119 checked, **0 bad** everywhere | 119/119 every time |
| same-slot median20 volume | 116-119 checked, **0 bad** everywhere | 61-83 per cell |
| entry-bar volume containment | **0 bad** | - |

Prior-day range on session D uses the last RTH session ending before D 00:00. The slot
median uses only sessions ending before D 00:00.

**Is the entry bar's volume known at decision time? Yes.** The engine enters at the
resume bar's CLOSE, so the bar is complete at the fill instant, and the engine already
reads that same bar's volume in `check_volume_pattern`. The filter adds no information
the strategy was not already using. The stricter alternative that never touches the entry
bar (`rvol_prevbar`) was measured anyway - see below.

#### 2. Fill audit on the regenerated books - PASS

On every instrument and window: `outside_exit_bar` 0, `outside_exit_day` 0,
`signal_after_entry` 0, `same_or_before_bar_exit` 0, `outside_entry_bar_5m` 0.

`outside_entry_bar_1m` is non-zero (137-158 per instrument on floor) and is explained,
not a defect: `entry_time` labels the START of the 5-minute resume bar while the entry is
that bar's CLOSE, so the price sits outside the single 1-minute bar carrying that label
and inside the 5-minute aggregate. Measured directly: 0 entries fall outside the 5-minute
bar, and 0 differ from its close.

#### 3. Portfolio replay - current cap vs strict 2.5%

Replay is deploy_sim's own risk layer; the diagnostic replay was checked against
`deploy_sim.replay` and matches. Headroom is percentage points left before the 15%
breaker trip, measured on drawdown from PEAK EQUITY - the breaker's own rule, which is a
different number from MaxDD as a share of $50,000 and the only one that decides whether
trading stops.

Current cap (roska4_swing 5.0%/4.4%):

| Variant | floor $ / Calmar / headroom | 2025 $ / Calmar / headroom | 2026 $ / Calmar / headroom |
|---|---|---|---|
| R4 raw + NKD (baseline) | 33,176 / 0.52 / 1.3p | 6,857 / 1.47 / 6.7p | 6,743 / 1.62 / 0.3p |
| **R4 filtered + NKD** | **33,970 / 0.88 / 6.9p** | **7,323 / 1.61 / 6.5p** | **8,675 / 3.48 / 6.1p** |
| R4 filtered(prevbar) + NKD | 34,962 / 0.79 / 5.1p | 8,561 / 1.85 / 6.9p | 6,545 / 1.64 / 0.8p |
| R4 filtered only | 30,071 / 0.61 / 4.8p | 5,120 / 1.86 / 9.1p | 2,668 / 1.32 / 7.8p |
| NKD only | 3,898 / 0.14 / 6.9p | 2,203 / 1.23 / 11.2p | 6,007 / 4.35 / 10.1p |

Strict 2.5% cap is clearly worse for this candidate and is rejected: filtered + NKD falls
to 14,340 / 0.43 on floor, 3,990 / 1.09 on 2025, 6,254 / 2.60 on 2026. On floor the
unfiltered baseline at strict025 (20,285 / 0.68) beats the filtered book at strict025
(14,340 / 0.43): removing trades and tightening the cap together starve the book, 419 of
752 entries rejected. **Keep the current cap.**

The books are exactly additive - filtered-only plus NKD-only equals filtered + NKD to the
dollar in all three windows - because the cluster budgets are independent and the breaker
never latches. The one exception is the unfiltered floor baseline, where R4 alone latches.

#### 4. What the filter actually does

Separating the filter's edge from its effect on the breaker, R4 standalone on floor:

```
R4 raw only,      breaker ON    $8,570   Calmar 0.18   354 halts   headroom -1.3p
R4 raw only,      breaker OFF  $29,278   Calmar 0.38     0 halts   headroom -1.3p
R4 filtered only, breaker ON   $30,071   Calmar 0.61     0 halts   headroom +4.8p
```

On a like-for-like basis the filter adds **+$793 of raw edge, 2.7%**. What it actually
does is move peak-relative drawdown from 16.3% to 10.2%, which is the difference between
latching the account breaker permanently and not. **This is a drawdown-control device, not
an alpha device**, and it should be argued for on that basis. It also removes the reason
NKD was kept in the earlier audit: R4 no longer needs NKD's profits to stay under the trip.

#### 5. Entry-bar volume vs previous-bar volume

| Window | entry-bar (`rvol_slot20`) | previous bar (`rvol_prevbar`) |
|---|---|---|
| floor | 33,970 / Calmar 0.88 / 6.9p | 34,962 / Calmar 0.79 / 5.1p |
| 2025 | 7,323 / Calmar 1.61 / 6.5p | 8,561 / Calmar 1.85 / 6.9p |
| 2026 | 8,675 / Calmar 3.48 / 6.1p | 6,545 / Calmar 1.64 / 0.8p |

Mixed, and worth stating plainly: on floor the entry-bar version wins Calmar and headroom
but loses $992 of net; on 2025 the previous-bar version wins outright; on 2026 the
entry-bar version wins by a wide margin. Since only floor may select, the entry-bar choice
is supported on risk-adjusted terms and not on net, and its largest advantage sits in a
window that is not allowed to select. Not a blocker, but it is a thinner justification than
the headline table suggests.

#### 6. NKD as its own sleeve

**Fill.** Post-hoc corrected and engine-fixed NKD books are identical trade-for-trade in
**all three windows** - this extends the equivalence proof, previously run only on 2026.
What today's production engine would overstate: $5.36 on floor, $0 on 2025, $3.21 on 2026.
Real but immaterial.

**Slippage.** MNKD is $0.50/point with a 5-point tick, so one tick is $2.50 and the round
turn moves $5.00 per extra tick per side. Slippage here is a flat per-round-turn cost that
touches neither prices nor signals, so the stress is exact:

| Window | 2t (base) | 3t | 4t | 5t | 6t | breakeven |
|---|---:|---:|---:|---:|---:|---:|
| floor | $3,898 | $2,758 | $1,618 | $478 | -$662 | **5.42 t/side** |
| 2025 | $2,203 | $2,048 | $1,893 | $1,738 | $1,583 | 16.2 t/side |
| 2026 | $4,292 | $4,162 | $4,032 | $3,902 | $3,772 | 35.0 t/side |

Measured depth in the bars this sleeve claims to trade: floor entry 5-minute bar
p10/median/p90 = 9/27/95 contracts, exit 1-minute bar = 2/8/38 contracts. The floor sleeve
is 2.7x from breakeven on an assumption of 2 ticks/side, in a book whose exit bar prints a
median of 8 contracts.

**Direct alpha - cluster bootstrap, 20,000 draws, centred test of H0 mean = 0:**

| Window | day | week | month |
|---|---:|---:|---:|
| floor | p = 0.406 | p = 0.380 | p = 0.467 |
| 2025 | p = 0.439 | p = 0.396 | p = 0.436 |
| 2026 | p = 0.365 | p = 0.352 | p = 0.207 |

**No window shows NKD's direct alpha distinguishable from zero.** The p5..p95 bands do
straddle zero as well; where an uncentred band would have looked encouraging, the centred
test is the one that answers the question.

**Concentration.** Floor $3,898 becomes $2,018 after dropping one month (2022-03, $1,880)
and $400 after two (adding 2024-02, $1,618). 2025 becomes -$455 after dropping two months.
2026 becomes $483 after two.

#### Verdict

**Normal-R4 filtered sleeve: promotion candidate pending production patch.**

It clears the audit gates that were set: no lookahead, with checks proven able to fail; a
clean fill audit on books regenerated from the signal path rather than from row deletion;
and an improvement over the corrected baseline in net, Calmar, MaxDD and breaker headroom
in all three windows. It is not deploy-clean today because it depends on an engine change
that is not in the repo, and because the honest numbers are materially below the ones
currently on record.

**Normal-NKD sleeve: keep research-only.**

The fill defect is real but costs $8.57 across eight and a half years, so fills are not the
blocker. The blocker is that NKD's direct alpha is not distinguishable from zero in any
window under a properly centred cluster bootstrap, one or two months carry each window, and
the floor sleeve is only 2.7x from slippage breakeven in a book with a median exit-bar depth
of 8 contracts. "Not distinguishable from zero" is absence of evidence, not disproof - but it
is not a basis for promotion. Note also that the earlier reason to keep NKD has gone: with the
filter applied, R4 no longer needs NKD's profits to stay clear of the breaker trip.

Gates before either sleeve moves further:

1. **Patch plan, not applied.** The production change is one condition in
   `futures/_validated_core.py`: drop `bool(isg[i])` from the `gapped` test so a stop the
   market stepped over fills at the actual bar open regardless of whether a time break
   preceded the bar. `model_sameday_stop.run_loop` carries the same condition and must
   change with it. Re-run the INVARIANTS anchor gate afterwards - the pinned baseline/floor
   /vault numbers will move, and they are the contract. Write the patch, get it approved,
   then apply; nothing here has been applied.
2. Re-select the filter by walk-forward folds. The p90 threshold is a quantile of the floor
   window's own traded days and the rule was picked from a grid of 9 on that same window.
   No fold selected it.
3. Decide entry-bar versus previous-bar volume on floor evidence alone, and record why.
4. Re-state every figure quoted for this sleeve on the regenerated basis. The row-deletion
   table should not be used again.
5. If NKD is to be revisited: a live depth and spread sample for MNKD at the actual entry
   and exit slots, not a flat 2-tick assumption.

### Normal-NKD context excavation - 2026-08-21

Scratch probe: `scratch/normal_nkd_context_excavation_20260821.py`.

Question: can NKD be rescued by a small context/liquidity filter family, without applying the R4
range/volume filter and without tuning EMA/stop grids?

Floor selection gate for display: at least 60 trades, net > 0, PF >= 1.20, still positive at
4 ticks/side, and breakeven slippage >= 4.5 ticks/side.

Best floor-selected rows:

| Rule | floor | 2025 | 2026 | Read |
|---|---:|---:|---:|---|
| `rvol_ge_1__prev_range_le_p90` | +$8,534 PF 1.57 Calmar 0.66 | +$1,082 PF 1.28 Calmar 0.59 | +$2,620 PF 2.90 Calmar 3.51 | Best floor row; floor centered bootstrap passes, OOS sample thin |
| `rvol_ge_1__spy_not_crash` | +$7,108 PF 1.45 Calmar 0.47 | +$1,757 PF 1.54 Calmar 1.43 | +$2,764 PF 1.43 Calmar 2.05 | More stable OOS dollars, but floor month p weak |
| `rvol_ge_1` | +$6,955 PF 1.38 Calmar 0.35 | +$1,797 PF 1.46 Calmar 0.98 | +$2,828 PF 1.44 Calmar 2.05 | Simple liquidity rule; floor quality mediocre |
| `rvol_mid_floor` | +$3,768 PF 1.29 Calmar 0.26 | +$2,863 PF 2.02 Calmar 2.63 | +$5,628 PF 2.87 Calmar 5.16 | OOS attractive but floor does not justify selection |

Diagnostics:

- `rvol_ge_1__prev_range_le_p90` has a real floor signal: centered bootstrap p-values
  day/week/month = 0.032 / 0.017 / 0.049, and floor breakeven slippage is 12.67 ticks/side.
- But the same rule has only 23 trades in 2025 and 10 in 2026. 2025 centered p-values are
  0.626 / 0.588 / 0.673 and drop-top-month turns the result negative.
- `rvol_mid_floor` looks excellent OOS, but floor centered p-values are 0.248 / 0.242 / 0.346;
  that is not selectable under the floor-only protocol.
- The useful NKD clue is **liquidity confirmation**: `rvol_ge_1` or `rvol_ge_1` combined with a
  prior-range cap. Direction-only and open-inside variants leave sample too small or OOS too
  concentrated.

Verdict: **NKD remains research-only.** There is a better NKD research hypothesis now
(`rvol_ge_1__prev_range_le_p90`), but it does not clear promotion because OOS support is too thin
and concentration remains bad. If NKD is revisited, start from liquidity confirmation, not EMA/stop
grids, and require fresh live depth/spread evidence.

### Normal-NKD context excavation pass 2 - 2026-08-21

Scratch probe: `scratch/normal_nkd_context_excavation_pass2_20260821.py`.

Pass 2 expands only around the pass-1 clue: liquidity confirmation plus one or two simple context
constraints. Selection is still floor-only.

Best new row:

| Rule | floor | 2025 | 2026 | Read |
|---|---:|---:|---:|---|
| `rvol_ge_1__prev_range_le_p90__spy_not_crash` | +$8,603 PF 1.67 Calmar 0.73 | +$1,741 PF 1.53 Calmar 1.41 | +$2,556 PF 2.86 Calmar 3.51 | Best NKD context row so far, still OOS-thin |

Diagnostics for that row:

- floor n=141, breakeven slippage 14.20 ticks/side.
- centered bootstrap p-values floor day/week/month = 0.021 / 0.010 / 0.032.
- drop top 1 and 2 floor months leaves +$6,722 / +$5,464.
- 2025 has only 22 trades and centered p-values 0.412 / 0.424 / 0.450; drop top two months turns
  negative (-$710).
- 2026 has only 9 trades. The result is positive but not enough sample to promote.

Read:

- NKD can be made much less slippage fragile by requiring relative volume and avoiding high prior
  range / SPY crash context.
- The better floor result is not enough to overcome the same promotion blocker: OOS sample size and
  concentration.

Verdict unchanged: **Normal-NKD stays research-only**. The best future NKD hypothesis is
`rvol_ge_1__prev_range_le_p90__spy_not_crash`, but it needs more live/paper evidence and a real
depth/spread sample before it can be considered for promotion.

### Normal implementation path and decision matrix - 2026-08-21

This section is the handoff from research to implementation planning. It is not a production patch.

#### Should implementation edit the current engine directly?

**No. Start a dedicated branch / patch stack.** The current production engine is back to a clean
baseline, while the promotion candidate depends on a gap-through fill behavior change that moves
the pinned invariant numbers. That is exactly the kind of change that should be isolated, reviewed,
and gated before merge.

Recommended branch shape:

1. `normal-r4-gapfill-enginefix`: only the gap-through fill fix and invariant refresh.
2. `normal-r4-context-filter`: add the R4 context filter after the engine fix is accepted.
3. `normal-nkd-paper-logging`: optional paper-only logging for the NKD liquidity hypothesis.

Do not mix NKD promotion, cap changes, and R4 filter implementation into the engine-fix branch.

#### Decision matrix

| Item | Status | Reason | Next action |
|---|---|---|---|
| Normal-R4 filtered | **promotion candidate pending production patch** | Regenerated audit passes no-lookahead/fill and improves net, Calmar, MaxDD, and breaker headroom in floor/2025/2026 | Write patch plan, implement on branch, rerun gates |
| Normal-NKD | **research-only / paper-only** | Better liquidity hypothesis exists, but OOS sample is too thin and concentration remains bad | Add paper logging only; no deploy enable |
| `strict025` cap | **reject for this candidate** | Starves the filtered book; floor filtered + NKD drops below the unfiltered strict baseline | Keep current R4 cap |
| Row-deletion combo tables | **superseded** | They delete saved trades, not a regenerated strategy path; overstate selection windows | Do not quote as promotion evidence |
| Engine gap-through fix | **required blocker** | Production still requires `bool(isg[i])`; candidate numbers assume corrected gap-through stop fills | Patch on isolated branch |

#### Patch plan - not applied

1. Engine gap-through fill fix:
   - Files to inspect/change:
     - `futures/_validated_core.py`
     - `model_sameday_stop.py`
   - Intended rule: if a stop is crossed and the next tradable bar opens beyond the stop, fill at
     the feasible bar open even when there is no `>15m` time gap.
   - Remove the requirement that `bool(isg[i])` be true for this gap-through stop case.
   - Keep tests/anchors separate for R4 and NKD.

2. Normal-R4 filter:
   - Scope: `MES`, `MNQ`, `MYM`, `M2K` only.
   - Do not apply to `MNKD`.
   - Candidate rule: `range_p90__vol_le_2`.
   - Feature definition:
     - prior-day futures RTH range <= floor-derived R4 p90 threshold;
     - entry-bar relative volume <= 2.0x median volume of the previous 20 sessions at the same
       time slot.
   - The audit accepted entry-bar volume because the engine enters at the completed resume-bar
     close and already reads that bar's volume in `check_volume_pattern`.
   - Still record the previous-bar alternative as a sensitivity, not the main spec.

3. Normal-NKD:
   - Keep disabled from promotion.
   - Paper-only hypothesis: `rvol_ge_1__prev_range_le_p90__spy_not_crash`.
   - Log actual spread, depth, bar volume, fill/partial-fill, slippage, expected PnL, actual PnL.

#### Required gates before merge/deploy

1. Re-run invariant anchors after the engine fix. If pinned numbers move, update the invariant
   contract deliberately; do not wave it through as noise.
2. Regenerate floor / 2025 / 2026 trades from the signal path, not saved trade row deletion.
3. Fill audit must pass:
   - `outside_exit_bar = 0`
   - `signal_after_entry = 0`
   - `same_or_before_bar_exit = 0`
   - entry price inside the 5-minute resume bar.
4. No-lookahead audit must pass for prior range and median20 slot volume, with non-causal mutation
   checks still failing.
5. Portfolio replay must report:
   - net, PF, Sharpe, Calmar, MaxDD;
   - breaker headroom;
   - rejected, blocked, halted days;
   - current cap only unless a separate cap study is reopened.
6. Final decision must use regenerated candidate numbers:
   - floor: +$33,970 PF 1.40 Sharpe 1.84 Calmar 0.88 MaxDD 11.3%;
   - 2025: +$7,323 PF 1.47 Sharpe 1.84 Calmar 1.61 MaxDD 9.8%;
   - 2026: +$8,675 PF 1.67 Sharpe 3.26 Calmar 3.48 MaxDD 9.0%.

### Calm-NKD redo after regime-causality audit - 2026-08-21

This pass is Calm research for `MNKD`, not the Normal R4 sleeve. The probe uses the deploy
instrument spec (`MNKD`, data symbol `NKD`) and keeps the SPY regime causal for the Tokyo session:
only SPY closes known before the Nikkei session are available.

Scratch artifacts:

- `scratch/calm_causal_nkd_probe.py`
- `scratch/calm_causal_nkd_probe_summary.csv`
- `scratch/calm_causal_nkd_probe_trades.csv`
- `scratch/calm_nkd_swing_calm_only_probe.py`
- `scratch/calm_nkd_swing_calm_only_summary.csv`
- `scratch/calm_nkd_swing_calm_only_trades.csv`

#### Direct PCLoc / gap candidates on NKD day session

Local session convention for this probe: Tokyo day-session bars `09:00-15:59 JST`, entry at
`10:00` or `14:00` bar open, exit at `15:55` bar open. Cost is `MNKD` at 2 ticks/side.

Result: reject. The direct Calm candidates that worked on MES/MNQ do not transfer to NKD. Both
LONG and SHORT variants of:

- prior close-location bottom-third + prior day down;
- current open-location bottom-third;
- small negative gap fade / continuation;

are negative in IS 2018-2024. Best rows are still negative, e.g. `pcloc_bottom_down_long_e1400`
is 216 trades, -$2,232, PF 0.47; `pcloc_bottom_down_long_e1000__not_deep_gap` is 201 trades,
-$2,281, PF 0.67. Audit counters are zero. 2025/2026 positives on some LONG rows are therefore
not eligible for promotion because no IS candidate was selected before OOS.

#### NKD swing signal gated to D-1 Calm

This is a different mechanism: the existing NKD swing signal is measured only on D-1 Calm days.
Because the trend-follow signal generator is configured to trade `Normal`/`Stress` and skip the
literal `Calm` label, the scratch wrapper maps D-1 Calm days to `Normal` for the engine and maps
all other days to `None`. The gate remains Calm-only; this is a way to measure the signal, not a
claim that the day is Normal.

Best IS row:

| Variant | IS 2018-2024 | 2025 | 2026 sanity |
|---|---:|---:|---:|
| `nkd_swing_d1calm_as_normal_ema5_mult2.5` | 550 trades, +$7,156, PF 1.55, DD $1,318, posY 5/7 | 90 trades, +$2,477, PF 1.92, DD $736 | 44 trades, +$1,543, PF 1.51, DD $649 |

IS yearly contribution for the best row by entry year: 2018 -$117, 2019 +$559, 2020 -$122,
2021 +$3,503, 2022 +$370 on 5 trades, 2023 +$2,120, 2024 +$843.

Verdict: **candidate worth audit, not deploy-level yet**. This is not an additive Calm sleeve if
the current system already trades NKD swing agnostically; it is a possible NKD replacement/gating
variant. Before promotion, compare against the existing NKD sleeve in the same deploy replay,
audit feasible gap-through stop exits at trade level, and check live MNKD slippage/depth because
the instrument remains thin.

### Stress switch full cap/breaker replay - 2026-08-22

Scratch artifacts:

- `scratch/stress_switch_full_replay_20260822.py`
- `scratch/stress_switch_full_replay_20260822_report.md`
- `scratch/stress_switch_full_replay_20260822.json`

Purpose: rerun the Stress switch idea inside an intraday switch harness using the existing
`MultiClusterGuard` and account `CircuitBreaker`, instead of only adding trade artifacts.
Base book is `normal_promotion_trades_*_20260821.json`, bucket `filtered`, R4 only
(`MES/MNQ/MYM/M2K`), NKD excluded.

Switch semantics measured:

- if Stress is rejected by cap/breaker, existing Normal is left alone;
- if Stress is admissible, same-symbol Normal is closed at Stress entry open and Stress enters;
- if Normal later tries to enter a symbol while Stress is still open on that symbol, that Normal
  entry is suppressed;
- replay is intraday for entry/exit/switch order, while cap math is the existing cluster guard.

Key result: the earlier MNQ-only 7x candidate is not deploy-clean under realistic Stress caps.
At Stress cap 2.5%/5.0%, it takes zero 2025 and 2026 Stress entries. It only takes the 2025/2026
legs at 10.0% Stress cap, which is too high to treat as a clean hedge cap.

Follow-up cap check added 7.5%. This is the first cap level where MNQ-only 7x starts admitting OOS
legs: 2/3 in 2025 and 1/4 in 2026 sanity. Metrics look good, but the sample is too small and the
accepted/rejected split itself becomes a form of cap selection, so 7.5% is a research cap, not a
deployment decision.

#### Full replay table

Base Normal-R4 filtered replay, no NKD:

| Window | Trades attempted | Taken | Rejected | Net | PF | Sharpe | Calmar | MaxDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| floor | 752 | 546 | 206 | +$29,046 | 1.49 | 2.25 | 0.68 | $6,209 |
| 2025 | 105 | 55 | 50 | +$5,395 | 1.58 | 1.94 | 1.56 | $3,768 |
| 2026 sanity | 81 | 46 | 35 | +$1,059 | 1.16 | 0.87 | 0.47 | $4,075 |

Selected Stress-switch rows:

| Window | Scenario | Stress cap | Stress taken/rej | Net | PF | Sharpe | Calmar | MaxDD | MaxDD delta |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| floor | `mnq_only_g3_q7` | 5.0% | 32 / 18 | +$46,189 | 1.74 | 2.99 | 1.31 | $5,151 | -$1,058 |
| floor | `mnq_only_g3_q7` | 7.5% | 47 / 3 | +$49,724 | 1.72 | 2.85 | 1.09 | $6,646 | +$437 |
| 2025 | `mnq_only_g3_q7` | 7.5% | 2 / 1 | +$10,329 | 2.42 | 3.59 | 3.17 | $3,540 | -$228 |
| 2025 | `mnq_only_g3_q7` | 10.0% | 3 / 0 | +$10,167 | 2.37 | 3.49 | 3.12 | $3,540 | -$228 |
| 2026 sanity | `mnq_only_g3_q7` | 7.5% | 1 / 3 | +$2,688 | 1.40 | 1.97 | 1.33 | $3,656 | -$419 |
| 2026 sanity | `mnq_only_g3_q7` | 10.0% | 3 / 1 | +$1,890 | 1.24 | 1.21 | 0.93 | $3,656 | -$419 |
| floor | `r4_basket_g3_q1each` | 2.5% | 201 / 1 | +$33,085 | 1.56 | 2.49 | 0.75 | $6,459 | +$250 |
| 2025 | `r4_basket_g3_q1each` | 2.5% | 14 / 1 | +$4,488 | 1.67 | 3.04 | 1.23 | $3,975 | +$207 |
| 2026 sanity | `r4_basket_g3_q1each` | 2.5% | 14 / 2 | +$2,153 | 1.41 | 2.00 | 1.31 | $2,980 | -$1,094 |
| floor | `r4_basket_g3_q2each` | 5.0% | 201 / 1 | +$39,518 | 1.60 | 2.63 | 0.75 | $7,709 | +$1,500 |
| 2025 | `r4_basket_g3_q2each` | 2.5% | 10 / 5 | +$8,026 | 1.96 | 3.45 | 1.98 | $4,410 | +$642 |
| 2026 sanity | `r4_basket_g3_q2each` | 5.0% | 14 / 2 | +$2,633 | 1.54 | 2.48 | 1.90 | $2,500 | -$1,575 |

Interpretation:

- `mnq_only_g3_q7` has the best headline improvement, but only after raising Stress cap above 5%.
  The 7.5% row is a possible research threshold, while 10% admits nearly all eligible legs.
- `r4_basket_g3_q1each` fits the 2.5% Stress cap and improves 2026 sanity, but it slightly worsens
  2025 and floor MaxDD and has much thinner net improvement.
- `r4_basket_g3_q2each` is mixed: some windows improve, but floor and 2025 MaxDD worsen in the
  rows that preserve more Stress entries.

Verdict: **the switch mechanism can be run and is operationally coherent in scratch, but no Stress
switch candidate is deploy-level yet**. The nearest research direction is not MNQ 7x; it is a
smaller cap-compatible basket or a fresh detector with lower stop risk per entry.

#### Single-cap check

Scratch artifacts:

- `scratch/stress_single_cap_probe_20260822.py`
- `scratch/stress_single_cap_probe_20260822_report.md`
- `scratch/stress_single_cap_probe_20260822.json`

Question: should Normal and Stress use one cap level instead of split caps? Test candidate is
`mnq_only_g3_q7`. `single_X` means Normal gross cap = X, Normal net cap = X, and Stress gross cap = X.

Result: reject single-cap for now. It loosens Normal-R4 at the same time as Stress, so any improvement
is no longer a clean Stress sleeve improvement. The higher single caps increase Normal admissions and
materially worsen drawdown.

| Window | Policy | Normal cap | Stress cap | Normal taken/rej | Stress taken/rej | Net | PF | Sharpe | Calmar | MaxDD |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| floor | split current | 5.0% / 4.4% | 10.0% | 551 / 192 | 49 / 1 | +$52,139 | 1.75 | 2.97 | 1.15 | $6,646 |
| floor | single 7.5 | 7.5% / 7.5% | 7.5% | 704 / 39 | 47 / 3 | +$50,236 | 1.54 | 2.34 | 0.67 | $10,986 |
| floor | single 10 | 10.0% / 10.0% | 10.0% | 734 / 9 | 49 / 1 | +$53,098 | 1.55 | 2.38 | 0.72 | $10,729 |
| 2025 | split current | 5.0% / 4.4% | 10.0% | 55 / 50 | 3 / 0 | +$10,167 | 2.37 | 3.49 | 3.12 | $3,540 |
| 2025 | single 7.5 | 7.5% / 7.5% | 7.5% | 82 / 21 | 2 / 1 | +$11,360 | 1.84 | 3.15 | 2.43 | $5,077 |
| 2025 | single 10 | 10.0% / 10.0% | 10.0% | 97 / 6 | 3 / 0 | +$11,746 | 1.74 | 2.90 | 1.93 | $6,612 |
| 2026 sanity | split current | 5.0% / 4.4% | 10.0% | 46 / 35 | 3 / 1 | +$1,890 | 1.24 | 1.21 | 0.93 | $3,656 |
| 2026 sanity | single 7.5 | 7.5% / 7.5% | 7.5% | 62 / 19 | 1 / 3 | +$5,091 | 1.57 | 2.65 | 1.55 | $5,934 |
| 2026 sanity | single 10 | 10.0% / 10.0% | 10.0% | 66 / 15 | 3 / 1 | +$4,293 | 1.33 | 1.60 | 0.96 | $8,090 |

Interpretation: keep split caps. If Stress needs 10%, raise only `roska4_stress` and keep
Normal-R4 at 5.0% gross / 4.4% net. A single cap makes the Stress test inseparable from a Normal
cap expansion and gives up too much drawdown control.

#### NKD add-back check

Scratch artifacts:

- `scratch/stress_with_nkd_probe_20260822.py`
- `scratch/stress_with_nkd_probe_20260822_report.md`
- `scratch/stress_with_nkd_probe_20260822.json`

Question: what happens if the current NKD/MNKD sleeve is included as a separate `global_nkd`
cluster while Stress uses `mnq_only_g3_q7` with split caps? Policy measured:

- Normal-R4: 5.0% gross / 4.4% net, qty 1;
- Stress-MNQ: 10.0% gross, qty 7;
- NKD/MNKD: 6.0% gross / 6.0% net, qty 1;
- account breaker shared.

| Window | Book | Trades attempted | R4 taken/rej | Stress taken/rej | NKD taken/rej | Net | PF | Sharpe | Calmar | MaxDD |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| floor | R4 only | 752 | 546 / 206 | 0 / 0 | 0 / 0 | +$29,046 | 1.49 | 2.25 | 0.68 | $6,209 |
| floor | R4 + Stress | 802 | 551 / 192 | 49 / 1 | 0 / 0 | +$52,139 | 1.75 | 2.97 | 1.15 | $6,646 |
| floor | R4 + NKD | 980 | 546 / 206 | 0 / 0 | 228 / 0 | +$32,944 | 1.40 | 1.84 | 0.79 | $6,078 |
| floor | R4 + Stress + NKD | 1030 | 551 / 192 | 49 / 1 | 228 / 0 | +$56,037 | 1.61 | 2.45 | 1.67 | $4,893 |
| 2025 | R4 only | 105 | 55 / 50 | 0 / 0 | 0 / 0 | +$5,395 | 1.58 | 1.94 | 1.56 | $3,768 |
| 2025 | R4 + Stress | 108 | 55 / 50 | 3 / 0 | 0 / 0 | +$10,167 | 2.37 | 3.49 | 3.12 | $3,540 |
| 2025 | R4 + NKD | 136 | 55 / 50 | 0 / 0 | 31 / 0 | +$7,598 | 1.53 | 2.01 | 1.45 | $5,679 |
| 2025 | R4 + Stress + NKD | 139 | 55 / 50 | 3 / 0 | 31 / 0 | +$12,370 | 1.99 | 3.23 | 2.80 | $4,792 |
| 2026 sanity | R4 only | 81 | 46 / 35 | 0 / 0 | 0 / 0 | +$1,059 | 1.16 | 0.87 | 0.47 | $4,075 |
| 2026 sanity | R4 + Stress | 85 | 46 / 35 | 3 / 1 | 0 / 0 | +$1,890 | 1.24 | 1.21 | 0.93 | $3,656 |
| 2026 sanity | R4 + NKD | 107 | 46 / 35 | 0 / 0 | 24 / 2 | +$7,066 | 1.58 | 2.88 | 2.43 | $5,253 |
| 2026 sanity | R4 + Stress + NKD | 111 | 46 / 35 | 3 / 1 | 24 / 2 | +$7,898 | 1.59 | 2.89 | 2.93 | $4,877 |

Interpretation: NKD is useful as a separate portfolio diversifier, and it improves the combined
Stress book's floor MaxDD materially (`$6,646 -> $4,893`). However, this is no longer a pure Stress
sleeve result. NKD worsens 2025 MaxDD when added to R4 alone and still worsens 2025 MaxDD versus
R4+Stress alone. Treat `R4 + Stress + NKD` as a portfolio research configuration, not evidence that
the Stress candidate itself is deploy-level.
