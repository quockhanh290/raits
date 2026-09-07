# Stress Sleeve Audit — confirmed 10:20 liquidation SHORT

Scratch-only. No production file was modified. Every number below was measured on this
repo at 2026-08-21; the scripts are listed at the end and can be re-run.

**Verdict: keep as research hedge only.** Not a paper-only candidate yet. The blocker is
not deployment plumbing — it is that the headline floor edge is mostly attributable to a
regime label the live system cannot have at 10:20, and the walk-forward evidence that has
been quoted in support of this variant was produced by a procedure that never selects it.

---

## Findings by severity

### S1 — CRITICAL. The Stress label for the day is not knowable at 10:20

The backtest decides "is today Stress?" using the day's own closing price of SPY.

`label_regimes` builds the label for day D from `daily[daily.index <= d]`
(`futures/_validated_core.py:115`) and `predict_current` returns the state of the **last**
observation (`raits/hmm/engine.py:256`). That last observation is D's 16:00 ET close. The
trade enters at 10:20 ET on D — five hours and forty minutes before the number that decided
it exists.

This is not hypothetical. Both live paths deliberately use the previous session, with a
comment saying so: `raits/live/context_feed.py:437` ("Daily SPY close (T-1)") filters
`< day.normalize()`. The repo's own `RegimeLabels(lag_days=1)` describes the lag as
"lookahead-safe" (`global_index/regime.py:44`).

Re-running the candidate with the label the live system would actually hold at 10:20
(previous session's label):

| window | variant | as validated | live-causal (lag-1) | change |
|---|---|---:|---:|---:|
| floor 2018-2024 | breadth3_mnq_mes | +$2,749, PF 1.49 | **+$776, PF 1.14** | −72% |
| floor 2018-2024 | wide3_mnq_mes | +$2,588, PF 1.60 | **+$1,538, PF 1.38** | −41% |
| 2025 OOS | breadth3_mnq_mes | +$4,095, PF 7.10 | **+$3,246, PF 5.08** | −21% |
| 2025 OOS | wide3_mnq_mes | +$3,622, PF 10.67 | **+$3,680, PF 11.17** | +2% |

126 Stress days on the floor either way; 32 of them (25%) change identity under the lag.
The 2022 year that carries the whole floor drops from +$3,979 to +$863 — roughly four
fifths of the floor edge is the same-day label.

Two things follow. First, at PF 1.14 the primary variant's floor is near cost level, so
"positive but event-concentrated" becomes "not distinguishable from costs". Second, the
backup variant is markedly more robust to this than the primary: `wide3_mnq_mes` keeps its
2025 result intact and stays clearly positive on the floor. **On the causality test the
declared backup outranks the declared primary.**

Fairness note: this lag-0 convention is inherited from the shared research stack, not
invented for this sleeve. The validated swing engine enters 14:00–15:55
(`futures/_validated_core.py:403`) and has the same exposure, roughly two hours wide. The
10:20 entry simply makes the gap almost three times larger, and this sleeve is the one
being proposed for promotion.

### S2 — CRITICAL. Same-symbol conflict with the swing sleeve is the majority case

`MultiClusterGuard.admits` checks a proposed entry **only against its own cluster** — the
docstring states it outright (`global_index/net_exposure_multi.py:131`). Nothing in the risk
layer can see that another sleeve already holds the same contract.

The swing sleeve trades Normal **and Stress** (`futures/basket.py:57`) and holds up to five
days, so it is routinely in the book on a Stress day. Calm holds nothing in this basket, so
the conflict is swing-versus-Stress, not Calm-versus-Stress.

Counting only swing positions entered strictly before the Stress day (a swing trade entered
on the same day opens at 14:00+, after Stress has already exited):

| window | variant | swing already holding same symbol at 10:20 | of those, opposite direction | Stress P&L on the conflicted legs |
|---|---|---:|---:|---:|
| floor | breadth3_mnq_mes | 64/84 (76%) | **33/84 (39%)** | $1,627 = **59% of sleeve net** |
| floor | wide3_mnq_mes | 44/61 (72%) | 25/61 (41%) | $1,165 = 45% of net |
| 2025 | breadth3_mnq_mes | 9/19 (47%) | 4/19 (21%) | $635 = 16% of net |

The scheduler already documents what happens at the broker
(`global_index/run_scheduler.py:672-684`): a swing LONG plus a Stress SHORT on MES makes
`get_positions()` report net zero, the position file disagrees, B3 raises MISMATCH and
**halts all entries system-wide** — not just Stress. Separately, `has_working_stop(inst)` is
keyed by symbol, so whichever sleeve places its stop first blocks the other, and
`unprotected_positions()` then reports SAFE because a stop exists on that expiry. One
contract runs naked, silently.

So more than half of the primary variant's backtested P&L sits on legs that in live would
either halt the system or leave an unprotected contract. Same-symbol overlap must be blocked
before any paper run.

### S3 — HIGH. The event-cluster WFO never selects the promoted candidate

The held-out fold table in `scratch/stress_sleeve_event_validation_report.md` shows the
per-fold pick: `late_cont_break` in 8 of 13 folds, `rr25` in 3, `wide3_mnq_mes` in 2,
`breadth3_mnq_mes` in **zero**.

"Held-out event total +$2,507, positive folds 9/13" therefore describes a selection rule that
would have deployed `late_cont_break` — the same variant pass-2 rejects for weak 2025
(+$597, PF 1.44). Quoting that total as walk-forward support for `breadth3_mnq_mes` attaches
one strategy's evidence to another. Run as written, the WFO argues against the primary.

The WFO implementation itself is sound: clusters are formed by calendar proximity only
(more than three days apart, data-independent), training uses strictly prior clusters, and the
first three clusters are correctly skipped for want of training history. Two cosmetic issues:
fold E012 has zero trades yet occupies a slot in the 13 denominator, and
`stress_sleeve_validation.py:529` computes an `overall` row from a deliberately empty frame
(`if False else pd.DataFrame()`) which is then unused.

### S4 — HIGH. The live path cannot currently produce this signal, and nothing owns the exit

Four separate blockers, all in production code:

1. **Bars stop five minutes early.** `_stress_bars` cuts today's frame at 10:15
   (`global_index/run_live_day.py:586`). The candidate's `_context` requires a 10:20 bar
   (`futures/stress_liquidation_1020.py:63`); with a 10:15 cut that lookup is empty, `_context`
   returns `None`, and no signal is ever produced. The cut has to move to 10:20 or later.
2. **The signal API shapes do not match.** `signal_layer.py:353` calls
   `stress_engine.entry_signal(bars, today_regime)` once per instrument. The new engine only
   exposes `entry_signals(bars_by_inst, regime)` — batch, because breadth needs all four
   contracts at once. A per-instrument loop structurally cannot compute a 3-of-4 breadth gate.
   Worse, the `AttributeError` would be swallowed by the C4 handler at `signal_layer.py:363`
   and logged as "stress entries skipped" — a silent fail-open.
3. **The target order is never placed.** `to_candidate` (`signal_layer.py:68`) carries only
   entry and stop. The 2R target accounts for 25% of floor exits (21 of 84) and has no live
   representation at all.
4. **The 14:00 exit is a side effect, not a rule.** `_mark_held_unchanged` is deliberately not
   called for the stress cluster, so `diff_desired_vs_held` finds the key missing and closes
   the position on the next scheduler run, which happens to be 14:05. The scheduler comment
   (`run_scheduler.py:656-667`) is explicit that adding any slot between 10:20 and 14:05 would
   close the position within minutes, and that adding `_mark_held_unchanged` for stress would
   instead leave it overnight. **So yes to both risks in the audit question:** an extra slot
   closes it early, and a failed 14:05 slot leaves it overnight, because no explicit exit rule
   exists.

The 10:20 cron is currently disabled with `if False:` (`run_scheduler.py:688`) and
`--stress-entry` defaults off, so none of this is live today.

One more timing point: a cron that *fires* at 10:20 cannot fill at the 10:20 open. The
`delay1025` variant is the honest proxy for that, and it costs 2025 about a quarter of its
result (+$3,029 versus +$4,095) while leaving the floor unchanged.

### S5 — HIGH. The cap recommendation is measured on the wrong risk basis

The 7.5%–10% figure comes from charging the sleeve `2.5 × daily ATR × point_value` — the
*swing chandelier* risk — via `real_risk` in `global_index/deploy_sim.py:222`. This sleeve's
stop is an intraday swing high roughly 0.7–0.9% away, which is a completely different number.

Measured, per trade and per day at $50k:

| window | true stop risk (median / max) | ATR proxy (median / max) | ratio | per-day both legs, true / proxy |
|---|---|---|---:|---|
| floor | $136 / $398 | $1,332 / $3,235 | 9.6x | **$664 (1.3%)** / $5,956 (11.9%) |
| 2025 | $280 / $535 | $3,406 / $5,702 | 12.5x | **$858 (1.7%)** / $9,210 (18.4%) |

The pass-2 cap table already contains the tell without naming it: under `risk_mode=stop`, the
2.5%, 5%, 7.5% and 10% rows are **identical** — 84 trades, 0 rejected, every time. A cap that
produces the same answer at four different levels is not binding on anything.

So the answers to the cap questions are the opposite of what the reports suggest: the sleeve
does **not** need a high cap, the inherited 2.5% `roska4_stress` gross budget is already ample
on true stop risk, and max-concurrent-2 is affordable (worst single trade on the floor is
−$401; per-day true risk never exceeds 1.7% of the account). The "7.5%–10%" number should be
dropped, not carried into the deploy gate.

### S6 — MEDIUM. 2025 has been used in selection decisions

Three places where a choice was justified by looking at 2025:

- The report verdict rejects the 2.5% cap because "it suppresses the candidate in OOS".
- Pass-2 drops the `stop_pct` filters, though on the floor alone `stop_pct_le_012` is the
  better policy (+$3,214, PF 1.69 versus +$2,749, PF 1.49); it was dropped because 2025 falls
  to +$2,559.
- `late_cont_break` is dropped for weak 2025 despite a better floor Calmar (0.59 versus 0.26)
  and despite the WFO selecting it in 8 of 13 folds.

The research doc sets the correct rule for the Normal work — "Final selection must be
WFO/fold-based, not chosen from 2025/2026" (`docs/futures/TF_REGIME_RESEARCH_2026-08-20.md:172`,
and again at :182) — and the Stress section does not hold to it. The choice of the *primary
variant* does appear to predate 2025 inspection, so this is not a full rejection. But 2025 is
no longer a clean out-of-sample for cap, filter, or family decisions, and it should not be
quoted as one.

### S7 — MEDIUM. Sharpe and Calmar are not on the system's basis

`metrics()` computes `daily.mean() / daily.std() * sqrt(252)` (`global_index/deploy_sim.py:55`)
over `daily_from_trades` — days that traded, not calendar sessions. This sleeve is active on
3.0% of floor sessions.

| window | active days | Sharpe as reported | Sharpe on calendar basis | factor |
|---|---:|---:|---:|---:|
| floor | 44 / 1487 | 2.57 | **0.44** | 5.8x |
| 2025 | 10 / 36-session span | 10.53 | **4.96** | 2.1x |

The floor factor of 5.8x matches sqrt(1487/44) = 5.8 exactly, which is the arithmetic
confirmation that this is the mechanism and not something else. The Calmar figures of 54.09,
89.15 and 105.53 in the 2025 tables come from dividing by a $362–$658 drawdown observed on a
ten-point series; they are not comparable to the system's Calmar of roughly 2.5, and they sit
next to system-level numbers in the research doc table (:632–634) without a basis note.

### S8 — MEDIUM. Clean-label evidence is one six-week episode

The floor uses `--hmm-fit-end 2022-12-31`, so its 2018–2022 labels come from an HMM fitted on
that same span. The research doc says this plainly at :558 and directs the reader to
2023-2024 and 2025+ as the cleaner regime-label windows. Those windows contain 0 trades
(2023-2024), 19 trades (2025), and 0 trades (2026 to 08-19).

Measured concentration: the 19 trades of 2025 fall on 10 days between 2025-03-10 and
2025-04-21, and **$2,603 of the $4,095 (64%) comes from a single six-session episode,
2025-04-10 to 2025-04-21**. On the floor, 84 trades occupy 44 days; the largest positive
episode is 2022-04-29 to 2022-05-09 at +$1,485.

The effective independent sample is therefore about three events in 2025 and roughly fifteen
on the floor — not 84 and 19 trades. The trade-level bootstrap reported as P(net>0)=0.911
resamples trades as if independent and overstates confidence accordingly. The event-cluster
WFO is the correct frame, and per S3 it does not choose this variant.

### S9 — LOW. Module docstring contradicts the wiring

`futures/stress_liquidation_1020.py:8` states the module is "deliberately not wired into
deploy_sim, run_live_day, or the scheduler". It is wired into deploy_sim — `--stress-engine
liquidation1020` constructs and runs it at `global_index/deploy_sim.py:197-201`. True for
run_live_day and the scheduler, false for deploy_sim.

### S10 — LOW. The overlap proxy does not measure overlap

`stress_overlap_proxy` (`scratch/stress_event_risk_pass2.py:147-148`) computes
`mnq_mes_opposite_risk` as `int((day_inst >= 2).sum())` — character for character the same
expression as `two_inst_days` on the line above. Both count Stress days that traded two
instruments. Neither has anything to do with opposite direction or with another sleeve. The
pass-2 report prints it under "Same-day stress overlap proxy" and the verdict then lists
"same-symbol netting resolution" as the open item, so the one number offered as evidence for
that risk measures something else entirely. The real figures are in S2.

---

## Acceptable as-is — verified clean

These were checked and found correct. They are the questions the audit was asked to press on
hardest, and they hold up.

**A1 — Fill and timing mechanics.** Across all 84 floor trades: entry time is exactly 10:20 in
84/84; every exit is strictly after its entry; the earliest exit is 10:45; every exit falls on
the entry date; the latest exit is 14:00:00. No overnight carry, no same-bar exit, no signal
after entry.

**A2 — Bar labelling and resample semantics.** `resample_5m` uses `resample("5min")`
(`futures/_validated_core.py:49`), which is left-labelled and left-closed, so the bar labelled
10:15 spans 10:15 up to but not including 10:20 — exactly 10:15 through 10:19 inclusive, closed
before the entry. VWAP, the day-open comparison and the 09:45–10:15 swing high all terminate at
that bar. The signal genuinely precedes the entry.

**A3 — Entry-bar leakage, and whether the audit is sufficient.** The forward scan starts strictly
after the 10:20 bar, so in principle a stop touched inside 10:20:00–10:20:59 would be invisible.
Measured directly: **0 of 84 floor trades and 0 of 19 in 2025** have entry-bar high at or above
the stop, or low at or below the target. The exclusion costs nothing.

On whether `outside_exit_day` or gap-through checks should be added: gap-through is already
handled correctly on both sides — `_exit_short` fills at the bar open rather than the level
whenever the bar gapped past it (`futures/stress_liquidation_1020.py:52` and `:54`), which is the
pessimistic fill for stops and the honest one for targets. And since every exit is same-session
(A1), an `outside_exit_day` check would be vacuous. The existing `outside_exit_bar` audit is
sufficient for this sleeve.

**A4 — Stop/target precedence.** Within a bar the stop is tested before the target
(`futures/stress_liquidation_1020.py:51`), so a bar spanning both books the loss. Conservative.

**A5 — Subtype classification is causal, not post-hoc.** `event_features` and `classify_event`
read only `signal_close`, `open`, `vwap`, `range_pct` and `gap` — all known at 10:20. No realized
return enters the classifier. The thresholds were author-chosen and the pass-2 policies that
filter *by* subtype are post-hoc, but the classification itself does not peek.

**A6 — Event clusters.** Formed purely by calendar proximity (a new cluster whenever the gap
exceeds three days), so cluster identity carries no outcome information, and folds train on
strictly prior clusters.

**A7 — Cost model.** 2 ticks per side is genuinely applied: both scratch drivers default
`--slippage-ticks` to 2.0 and pass it into `costs_for_basket`, overriding the module default of
1.0 in `futures/cost.py:22`. Verified arithmetically rather than by reading the flag — the floor
moves from $2,749 at 2 ticks to $2,452 at 4 ticks, a difference of $297, and 43 MES trades × $5
plus 41 MNQ trades × $2 = $297 exactly. Cost robustness is good: at 6 ticks per side the floor
still nets $2,155 at PF 1.36.

**A8 — Research harness reconciles with the deploy engine.** `stress_sleeve_validation.build_variant`
and `StressLiquidation1020Engine.backtest_basket` were run side by side: identical trade sets,
zero P&L mismatches, on both windows and both variants. The published numbers do describe what
`deploy_sim` runs. This is the check that the parallel-implementation failures in this project's
history would have needed, and it passes.

Worth recording alongside: the MES leg is marginal. Floor MNQ is +$2,042 at PF 1.66 while MES is
+$707 at PF 1.28, and at 6 ticks per side MES falls to +$277 at PF 1.10. The pair is really MNQ
plus a leg that barely clears costs.

---

## Must fix before paper

1. Re-measure the candidate on lag-1 regime labels and treat those as the headline numbers
   (S1). Anything else is quoting a number the live system cannot reproduce.
2. Block same-symbol positions across clusters, or give the Stress sleeve its own account
   (S2). Until then the sleeve can halt system-wide entries and leave contracts unprotected.
3. Move the live bar cut from 10:15 to 10:20 or later (S4.1).
4. Replace the per-instrument `entry_signal` call with the batch breadth API, and make the C4
   handler distinguish "no signal" from "the call raised" (S4.2).
5. Give Stress an explicit exit rule that owns both the 2R target and the 14:00 close, instead
   of relying on the 14:05 diff (S4.3, S4.4).
6. Re-key stop tracking by position rather than by symbol before any Stress order is sent
   (S2) — this is already the scheduler's own stated re-enable condition.

## Research caveats

- The quoted WFO support belongs to `late_cont_break`, not to the primary variant (S3).
- Drop the 7.5%–10% cap figure; measure the cap on true stop distance (S5).
- 2025 is no longer clean for cap, filter or family decisions (S6).
- Report Sharpe and Calmar on the calendar basis, or label them as sleeve-active-days only,
  before placing them beside system-level numbers (S7).
- Treat the sample as roughly three 2025 events and fifteen floor events, not 19 and 84 trades;
  prefer cluster-level resampling to the trade bootstrap (S8).
- Fix the two descriptions that have drifted from their subjects (S9, S10).

## Against the stated rejection rules

| Rule | Result |
|---|---|
| Reject if the edge is only 2022 and not 2025 | Not triggered as validated. Under lag-1 the floor collapses to +$776 and the sleeve becomes close to 2025-only. |
| Reject if 2025 survives only by tuning after seeing it | Partially triggered — for the cap, filter and family choices, not for the primary variant itself. |
| Reject if the cap must be unrealistically high | **Not triggered.** True per-day risk is 1.3%–1.7% of a $50k account. The high-cap impression was a measurement artifact. |
| Reject if live timing cannot reproduce the 10:15-10:19 confirmation before entry | The 5-minute confirmation is reproducible with a one-line change to the bar cut. The **regime** confirmation is not reproducible at 10:20 — triggered in substance. |
| Reject if same-symbol netting cannot be solved | Solvable in principle, not solved today, with 39% of floor trades and 59% of floor P&L exposed. |

## Recommended next gate

Not combo/deploy feasibility, and not more parameter mining. Two research steps first, both
cheap because the harness already exists:

1. Re-run the full variant table and the event-cluster WFO on lag-1 labels, with
   `breadth3_mnq_mes` in the candidate set, and see which variant the fold procedure picks.
2. If a variant survives both, promote **that** one. On present evidence `wide3_mnq_mes` is the
   stronger candidate under causality: it keeps 2025 intact (+$3,680 versus +$3,622) and stays
   clearly positive on the floor (+$1,538), while the declared primary falls to PF 1.14.

Deploy feasibility is worth starting only after step 1, because the same-symbol and
exit-ownership work in S2 and S4 is substantial and should not be spent on a variant that a
causal WFO does not choose.

---

## Scripts

All read-only, all added under `scratch/` by this audit. Each asserts on a non-empty result
before measuring, so a silent no-op run fails instead of reporting zero.

| script | output | what it measures |
|---|---|---|
| `scratch/stress_audit_lag_leak.py` | `scratch/stress_audit_lag_leak.txt` | lag-1 labels, entry-bar leakage, cap basis (S1, S5, A3) |
| `scratch/stress_audit_overlap2.py` | `scratch/stress_audit_overlap2.txt` | cross-sleeve same-symbol conflict, strict (S2) |
| `scratch/stress_audit_metric_basis.py` | `scratch/stress_audit_metric_basis.txt` | Sharpe/Calmar basis (S7) |
| `scratch/stress_audit_engine_reconcile.py` | `scratch/stress_audit_engine_reconcile.txt` | harness versus deploy engine, episode concentration (A8, S8) |
| `scratch/stress_audit_exitday.py` | stdout | entry/exit timing on every trade (A1) |

Re-run, from `d:\raits`, roughly two to four minutes each:

```
$env:PYTHONIOENCODING="utf-8"
python scratch\stress_audit_lag_leak.py floor vault2025
python scratch\stress_audit_overlap2.py
python scratch\stress_audit_metric_basis.py
python scratch\stress_audit_engine_reconcile.py
python scratch\stress_audit_exitday.py
```

`scratch/stress_audit_overlap.py` is the superseded first version of the conflict count — it
included the swing entry day, which overstates the overlap because a swing position entered at
14:00 is not in the book at 10:20. Use `overlap2`.
