# Track 1 — Production Feasibility Audit — 2026-08-22

Scratch-only. No production file was modified. Nothing committed.

## Verdict: **BLOCKED PENDING PATCH**

The measurement side is clean — cleaner than expected. Every fill test, every settlement test and
every position invariant passes in all three windows, and one of the two open replay-underlayer
items closes at exactly zero. Track 1 is a valid production **patch candidate**.

It is not live-ready, and the reason is larger than the expected one. The expectation going in was
that Calm A, Stress and the switch semantics are not wired. That is true. But the audit also found
that **the Normal-R4 sleeve — the largest contributor — is not what production runs today either**.
Track 1 is therefore not an additive patch on top of the live system; it changes a sleeve that is
already trading.

---

## 1. Rebuild from the closest-to-production signal path

### Gate

The replay used here is a re-implementation with instrumentation, so it had to reproduce Track 1's
published numbers first. **Exact in all three windows**, net and worst drawdown to the cent:

| Window | net | worst drawdown | PF | Sharpe | Calmar |
|---|---:|---:|---:|---:|---:|
| floor 2018-2024 | $64,902.91 | $4,845.31 | 1.62 | 2.34 | 1.92 |
| 2025 | $13,236.11 | $4,631.53 | 2.00 | 2.96 | 3.09 |
| 2026 sanity | $8,259.85 | $4,797.44 | 1.55 | 2.57 | 2.75 |

Event counts close against the sleeve tallies without slack: floor 1,160 entries = 545 Normal-R4 +
338 Calm A + 49 Stress + 228 NKD; 195 rejections = 190 + 4 + 1; 1,146 exits = 1,160 − 14 force-closes.

### What is production code and what is scratch

| Component | Where it lives |
|---|---|
| Swing engine (`backtest_swing_tf`), basket wrapper, daily ATR | **production** |
| Cluster guard, per-cluster budgets, circuit breaker | **production** |
| Cap risk convention `2.5 × daily ATR × pv` | **production** (`signal_layer.to_candidate`) |
| Current NKD sleeve: ema 10, mult 2.5 | **production** (`run_live_day.NKD_EMA`) |
| Stop arming per cluster | **production**, at 14:00 |
| Normal-R4 ema 50 | **scratch only** — production is **ema 30** |
| Normal-R4 stop = entry ± 2.0 × daily ATR, fixed, no ratchet | **scratch only** (`scratch/harness.py` + `model_sameday_stop.py`) — production places the engine chandelier level |
| R4 context filter `range_p90__vol_le_2` | **scratch only** |
| SPY short filter `below_sma50` | **scratch only** |
| Calm A PCLoc signal | **scratch only** |
| Stress intraday detector | **scratch only** |
| `roska4_calm` cluster | **does not exist anywhere in production** |
| Normal+Calm family cap | **does not exist** — the guard has no aggregate/family concept at all |
| Force-close / suppression switch logic | **scratch only** |
| The all-bars-gappable fill law used to build the artifacts | **scratch only** |

Verified by grep across `futures/`, `global_index/`, `raits/`, and by reading the live construction
path: `run_live_day.py` builds `SwingTFEngine()` with defaults, and `futures/basket.py` sets those to
`ema_period 30, chandelier_atr_mult 2.5`. No config file reaches that path — `configs/final_params.yaml`
belongs to the RAITS stocks WFO, not the futures runner. Nothing in production imports
`model_sameday_stop` or `scratch.harness`; only comments mention them by name.

### Signal-path regeneration

The promotion artifacts are themselves signal-path output — `normal_promotion_regen_audit` drives
`deploy_sim.main()` end to end. It was re-run from scratch during this audit to confirm the artifacts
are reproducible rather than a frozen dump. That script **overwrites the shared artifacts in place**,
so they were snapshotted first, the audit was pointed at the untouched snapshot, and the originals
were restored afterwards; the two jobs therefore never raced on the same file.

**Result: byte-identical.** Re-running `normal_promotion_regen_audit` end to end reproduced all three
promotion artifacts with matching sha256 (`f4d8eea7…`, `c7eb5dd2…`, `b1e85b2c…`), and the script's own
internal anchors passed in every window ($33,176 / $6,857 / $6,743, each against its stated baseline).
The originals were then restored, so the shared files end the session exactly as they began. There is
no reproduction mismatch to attribute: Track 1's Normal-R4 and NKD books are the signal path's output,
regenerable on demand.

The NKD half of the same question was already settled independently in the previous session:
regenerating the current-NKD book on its own basis reproduced 228 / $3,898.30, 31 / $2,203.04 and
26 / $4,292.17 trade-for-trade.

---

## 2. The two remaining replay-underlayer items

### Item 6 — max-hold exit pre-empts the armed stop

Measured on the **taken** set only, not on all attempts.

| Window | armed max-hold exits | stop already traded through earlier that session | P&L cost of the ordering |
|---|---:|---:|---:|
| floor | 894 scanned | **4** | **−$423.54**, worst single case −$377 |
| 2025 | — | 0 | $0 |
| 2026 | — | 0 | $0 |

Direction is **conservative**: the backtest books a worse loss than an armed stop would have allowed,
so it is not flattering Track 1. Four events in seven years, $424 against $64,903. Real, small, and
it errs the safe way — but it is still a live-versus-backtest divergence on the days that matter.

### Item 9 — production arms at 14:00, artifacts assume 14:05

Rather than regenerate the whole book at both arm times, the question was reduced to the only thing
that can differ: for every Track 1 swing position, was its stop level touched inside the 14:00–14:05
window on the arming day?

| Window | positions scanned | stop touched in 14:00–14:05 |
|---|---:|---:|
| floor | all Track 1 swing positions | **0** |
| 2025 | " | **0** |
| 2026 | " | **0** |

**Item 9 is closed at exactly zero.** Arming at 14:00 instead of 14:05 changes nothing in this book —
not the trade count, not the net, not the drawdown. The five-minute discrepancy should still be
removed when the artifacts are next regenerated, but it carries no measurement debt.

### Item 10 — five-minute timestamp semantics

A swing entry is stamped at the **start** of its 5-minute resume bar while filling at that bar's
**close**, five minutes later. The concrete risk is ordering: anything stamped inside that window is
processed after the entry here, but would in reality happen at or before the fill.

| Window | swing entries | other-sleeve exits landing inside a fill window | family-relevant |
|---|---:|---:|---:|
| floor | 773 | **0** | 0 |
| 2025 | 86 | **2** | **2** |
| 2026 | 69 | **0** | 0 |

The two 2025 cases are the same instant: a MYM swing entry stamped 2025-08-04 15:50 (filling 15:55)
against two Calm A exits at 15:55, on MES and MNQ. The replay processes the entry while both Calm
positions are still open, so the family book is fuller and the entry is **more** likely to be
refused than it would be live. Conservative direction, two occurrences in eight years.

**Assessment: harmless today, worth a patch note.** It becomes a real defect the moment any future
sleeve trades inside 14:00–15:55, because then the ordering error is between two sleeves rather than
between a sleeve and an exit.

---

## 3. Fill audit — all four sleeves

| Window | Sleeve | n | outside entry bar | outside exit bar | signal after entry | same-bar exit | missing bars | **impossible stop fills** |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| floor | Normal-R4 | 752 | 0 | 0 | 0 | 0 | 0 | **0** |
| floor | Current NKD | 228 | 0 | 0 | 0 | 0 | 0 | **0** |
| floor | Stress-MNQ | 50 | 0 | 0 | 0 | 0 | 0 | **0** |
| floor | Calm A | 349 | 0 | 0 | 0 | 0 | 0 | **0** |
| 2025 | all four | 105 / 31 / 3 / 44 | 0 | 0 | 0 | 0 | 0 | **0** |
| 2026 | all four | 81 / 26 / 4 / 28 | 0 | 0 | 0 | 0 | 2 | **0** |

Clean. The two missing lookups are the two Calm A legs on 2026-08-19, a session the promotion
artifact's end-date clip excludes — a boundary mismatch between two data windows, not a fill defect.

Gap and open-through handling, stated per sleeve because they differ:

- **Normal-R4 and current NKD** carry the *conservative* law: the artifacts were generated with every
  bar treated as gap-eligible, so a stop the market opened beyond fills at that bar's open. This is
  stricter than the production engine, which only does that after a real time break of more than
  fifteen minutes. Measured cost of the difference on the NKD sleeve: floor −$5.36, 2025 $0, 2026
  −$3.21.
- **Stress-MNQ** fills at the open when the whole bar sits beyond the stop, and tests the stop before
  the target within a bar.
- **Calm A** fills at the open when the bar opens below the stop.

This matters because the same test is what killed the Calm-NKD tight-stop candidate — 290 of 471
exits there were booked at prices the market had already passed. Track 1's sleeves have **zero**.

---

## 4. Switch and order-flow audit

Every switch, force-close and suppression was emitted as a broker-relevant event and the position
book was re-checked for invariant violations after each one.

| Window | entries | exits | force-closes | suppressions | rejections | breaker halts | **invariant violations** |
|---|---:|---:|---:|---:|---:|---:|---:|
| floor | 1,160 | 1,146 | **14** | 22 | 195 | 2 | **0** |
| 2025 | 128 | 127 | **1** | 4 | 51 | 0 | **0** |
| 2026 | 91 | 91 | **0** | 1 | 47 | 0 | **0** |

Checks, all passing:

- **Cap admission is tested before anything is closed.** A rejected Stress emits `REJECT` with the
  note that no force-close was performed; one such rejection occurs on floor and one in 2026.
- **No same-symbol stack and no opposite-direction overlap**, at any instant, re-checked after every
  entry and after every force-close. Zero violations.
- **Settlement is exact**: floor 1,160 entered / 1,160 settled, 0 settled twice, 0 never settled.
  Same in 2025 (128/128) and 2026 (91/91).
- **No position silently dropped**: the missing-price branch of the force-close never fired.

Force-close shape:

| Window | count | victims | instrument | booked P&L on the forced legs |
|---|---:|---|---|---:|
| floor | 14 | 10 Normal-R4, 4 Calm A | **all MNQ** | −$6,072.36 |
| 2025 | 1 | 1 Normal-R4 | MNQ | −$1,744.24 |
| 2026 | 0 | — | — | — |

Fifteen force-closes in eight years, roughly two a year, every one on MNQ because Stress is
MNQ-only. Each one is a multi-leg broker sequence in a fast market — that is section 6's problem,
not a measurement problem.

---

## 5. Cap audit

Carried exposure, sampled at every event instant:

| Window | cluster | cap | carried peak gross | carried peak net |
|---|---|---|---:|---:|
| floor | roska4_swing | 5.0 / 4.4 | 4.90% | 4.89% |
| floor | roska4_calm | 5.0 gross | 3.44% | 3.44% |
| floor | **Normal+Calm family** | 5.0 / 4.4 | **4.90%** | **4.89%** |
| floor | roska4_stress | 10.0 gross | 8.36% | 8.36% |
| floor | global_nkd | 6.0 / 6.0 | 4.21% | 4.21% |
| 2025 | family | 5.0 / 4.4 | 4.96% | 4.38% |
| 2025 | roska4_stress | 10.0 | 7.96% | 7.96% |
| 2025 | global_nkd | 6.0 | 3.39% | 3.39% |
| 2026 | family | 5.0 / 4.4 | 4.84% | 4.12% |
| 2026 | roska4_stress | 10.0 | 8.54% | 8.54% |
| 2026 | global_nkd | 6.0 | **5.92%** | **5.92%** |

**The family cap is an admission gate, not a maintained limit** — measured in the dedicated exposure
probe, which scopes "admission" strictly to family entries. No family entry was ever admitted above
its cap: the admission-time family net peak on floor is **exactly 4.40%** against a 4.4% cap. But
carried net drifts to **4.89%** on **seven** occasions in the floor window — five immediately after a
family position exits (dropping a short from a long-heavy book raises the net) and two observed at an
unrelated admission on a state that had already drifted. Zero drift breaches in 2025 and 2026.
Overshoot: **+0.49 percentage points, 11% over the cap**.

This is not something the family cap introduced. Every cluster budget in the guard behaves the same
way, including the pre-existing 4.4% net cap on Normal alone. It is stated once so nobody reads
"4.4% net" as a promise about carried exposure.

Two other observations. The Stress cap at 10% is never approached — peak 8.54% — so a lower Stress
cap would bind sooner than the sweep suggested; that is a research question, not a blocker. And the
NKD cluster in 2026 reaches **5.92% against a 6% cap**, within 0.08 percentage points, with 2
rejections. The module's own docstring already flags this: at 2026 Nikkei volatility the 6% cap
"clears by only ~5% and a further vol rise re-blocks the cluster." Track 1 inherits that.

---

## 6. Production wiring feasibility

### Direct answers

| Question | Answer |
|---|---|
| Is there a `roska4_calm` cluster? | **No.** Not in the guard, not in the arming table, not in the deferred-stop set, nowhere. |
| Is the Calm A signal path implemented? | **No.** |
| Is the Stress intraday detector implemented? | **No.** `CLUSTER_STRESS` exists in the signal layer, but it is STRESS_MID — a different sleeve, and its 10:20 slot is currently disabled. |
| Is force-close / suppress implemented for a same-symbol switch? | **No.** |
| Can the runner close first, wait for confirmation, then enter? | **Yes, the primitive exists** — but only inside the contract-roll path. |
| Can it cancel and replace stops? | **Yes**, but see the ordering defect below. |
| Can it prevent an IBKR net-zero / mismatch? | **Partly.** The B3 startup reconcile cross-checks the position file against broker positions and halts new entries on mismatch, and the M5 ledger reconcile explains account moves against sleeve bookings. Neither runs *inside* a run, immediately after a switch. |

### The close-then-enter primitive, and why it cannot be reused as-is

`ibkr_broker._handle_rollover` already does the exact shape a switch needs: place the close market
order, poll to done against a **120-second** exit deadline, verify the fill status, and only on a
confirmed fill place the open order against a **30-second** entry deadline — aborting and leaving the
position untouched if the close times out or does not fill. Worst case 150 seconds, comfortably
inside the Stress entry window of 10:35 to 12:30.

But it is bound to the roll: same instrument, same direction, same contract count, position identity
preserved, keyed on `get_roll_event`. A Stress switch flips direction (Normal LONG MNQ → Stress SHORT
MNQ), changes size (1 → 7), and crosses clusters.

**The ordering defect.** The one force-close path that does exist, `run_maxhold_exit`, sends the
CLOSE order **first** and cancels the stop **after**. Between those two steps the account is flat
while a live stop still rests at the broker. For a max-hold exit at the 09:30 open that window is
usually harmless. For the Stress switch it is not: the detector fires precisely when all four
instruments are below their open and VWAP and gapping down — the exact conditions under which a
resting sell-stop beneath a Normal MNQ long is most likely to trigger. It would open a fresh short,
on top of the seven-lot Stress short being entered.

The roll path has the same weakness from the other direction and the code already says so: a roll
whose stop cancel failed leaves the dead contract's stop counted as covering the position, and
`_roll_stop` logs CRITICAL when a rolled position has no recorded level to re-place.

### Execution shape

Track 1 needs **three new scheduler slots** — 10:00 ET for Calm A entry, 15:55 ET for the Calm A and
Stress exits — **plus a continuous monitor from 10:35 to 12:30** for the Stress entry, which fires on
a break of the 09:30–10:30 low at an unknown minute. Every slot in the scheduler today is one-shot:
09:31, 10:20, 13:45, 14:05, the NKD night slots and 23:55. There is no continuous-monitor execution
shape in the runner at all.

### Files that would need patching

1. `global_index/net_exposure_multi.py` — add the `roska4_calm` budget, and add a family/aggregate
   concept, which does not exist today in any form.
2. `global_index/runner.py` — cluster tables (`_ARM_BY_CLUSTER`, `_DEFERRED_STOP_CLUSTERS`), the
   force-close and suppression logic, and the stop-cancel-before-close ordering.
3. `global_index/signal_layer.py` — dispatch for two new sleeves whose signals are not state-diff
   shaped like the swing sleeves.
4. `global_index/run_scheduler.py` — three new slots and a continuous monitor.
5. `global_index/ibkr_broker.py` — generalise the roll's close-confirm-then-open sequence into a
   switch primitive.
6. `global_index/deploy_sim.py` — so the simulator can still reproduce what live does.
7. **New modules** for the Calm A PCLoc signal and the Stress intraday detector.
8. **The Normal-R4 sleeve itself** — ema 30 → 50, chandelier stop → fixed 2.0 × daily ATR, ratchet
   off, plus the two filters. This is the one that changes a sleeve already trading.

### Telemetry that does not exist yet

Every event kind this audit had to invent to make the switch auditable has no counterpart in the
runner today: `FORCE_CLOSE`, `CANCEL_STOP`, `AWAIT_CLOSE_CONFIRM`, `SUPPRESS`, and a `REJECT` reason
of `family_cap`. Without them a live switch is invisible: the existing journal would show a close and
an entry with nothing tying them together, and a suppressed entry would show nothing at all — the
same blind spot that made `exit_path_coverage` read zero for MAX_HOLD.

At minimum a switch needs one correlated record per event containing the trigger, the victim
position, the cancel result, the close fill, the confirmation, the entry fill and the new stop id,
plus an alert if any step fails between the cancel and the new stop being live.

---

## 7. Verdict

**Blocked pending patch.** Production-audit **pass on measurement**; **fail on wiring**.

Nothing in this audit found a new measurement blocker. The book reproduces exactly, the fills are
clean across all four sleeves, settlement is exact, the position invariants hold at every instant,
item 9 closes at zero, and item 6 and item 10 are both small and both conservative in direction.
On the evidence, Track 1 is a legitimate production patch candidate.

What blocks it is that the patch is bigger than it looks:

1. Five components do not exist in production at all.
2. The guard has no family-cap concept, and the family cap is what holds the shared MES/MNQ tail from
   6.86–7.82% down to under 5%.
3. The switch needs a close-confirm-then-enter primitive that exists only inside the roll path, plus
   a **stop-cancel-before-close** ordering the one existing force-close path gets backwards — and the
   Stress switch fires in exactly the market conditions where that ordering matters most.
4. Track 1 needs an execution shape the runner does not have: a continuous intraday monitor.
5. **Normal-R4 as specified is not the Normal-R4 that is live.** Changing its stop from the engine
   chandelier to a fixed 2.0 × daily ATR, its ema from 30 to 50, and adding two filters is a change to
   a sleeve currently trading real orders — not an addition alongside it. It deserves its own
   before/after gate rather than riding in on a Track 1 patch.

Recommended sequencing, cheapest risk first: land the guard's family-cap concept and the switch
telemetry before any new sleeve; generalise the roll's close-confirm primitive and fix the
cancel-before-close ordering next, since both are wanted regardless of Track 1; treat the Normal-R4
parameter change as a separate, individually gated change; and wire Calm A before Stress, because
Calm A is a single-shot 10:00 entry that fits the existing slot shape, while Stress needs the
continuous monitor that does not exist.

Until at least the first three land, Track 1 is **paper/shadow only**.

## Artifacts

- `scratch/track1_production_feasibility_audit_20260822.py` / `.json` — the gated replay, the broker
  event log, items 6/9/10, the fill audit and the cap audit
