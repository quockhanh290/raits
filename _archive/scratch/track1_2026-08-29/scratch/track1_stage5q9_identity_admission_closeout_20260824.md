# Stage 5Q-9 — closing the three blockers between a correct signal and the size that gets sent

**2026-08-24, 22:10–00:40 ET ·** no scheduler or backend started or stopped · **no IBKR
connection** · no parquet, CSV or runtime evidence written · no order · no confirmation file ·
`TRACK1_ORDERS_APPROVED` unset · B1 still blocking · overlap guard untouched · signal rules
untouched · no commit.

---

## Verdict: **IDENTITY_MATCH_CONFIRMED**

| | Stage 5Q-8 finding | now |
|---|---|---|
| **I-1** | `global_nkd` declared a stop rule it does not run — five fields | **closed.** Declaration corrected to the executed rule; the strict `xfail` is gone because the mismatch is |
| **I-3** | sizing basis differed from the artifact by exactly 1.25× | **closed by measurement, not by taste.** 166 admissions move; the route now sizes on the basis its published numbers were admitted under |
| **I-2** | the hash carried no tradable identity | **closed.** Four names added, one mutation test each |

Signal reproduction is **unchanged and still exact** — 1,223 Normal-R4 rows, 421 Calm A rows,
50/3/4 Stress rows, re-run tonight after every change in this stage.

**Paper orders remain blocked** — by the operational items from Stage 5Q-7, none of which is an
identity question. See the last section.

---

## Part A — I-1: `global_nkd` now declares the rule it runs

```text
                 declared (until tonight)          declared now  =  executed
stop_basis       chandelier_atr                    fixed_entry_atr
stop_multiple    2.5                               2.0
stop_anchor      extreme_through_prior_bar         entry
ratchet          True                              False
arm_hour         14:00                             14:05
arm_timezone     Asia/Tokyo                        Asia/Tokyo   (unchanged, and correct)
```

Unchanged because they already agreed: `ema_period` 10, `max_hold_days` 5, `label_lag_days` 1,
the NKD data identity, the MNK order identity, MNKD's $0.50 point value.

`arm_timezone` stays Tokyo and is not a second copy of anything: the day loop adds `arm_hours`
to a day taken from the frame's index, and `frozen_frame` puts that frame on the instrument's
declared session zone. 14:05 on the frame's clock **is** 14:05 JST.

**The `SOURCES` prose was wrong too, and was repaired with it.** Four entries still said
"MNKD keeps 2.5", "the promoted MNKD sleeve keeps it on", "MNKD unchanged at 14:00 JST" —
descriptions that had drifted from the thing they describe, in the one file whose job is to
say where every value comes from.

```text
global_nkd params hash   sha256:95e7bd876765e62a…  ->  sha256:19eef4ecde08b3c1…
```

**No stored Track 1 checkpoint is invalidated**, and that is checked rather than assumed:
`replay_checkpoint.track1.json` does not exist, and the legacy `replay_checkpoint.json` holds
zero `params_hash` entries. This was the cheapest possible moment to move it.

---

## Part B — I-3: the sizing basis, measured on both sides

The committed candidate stream, run through the real `Track1Book` twice, changing nothing but
`risk_dollars`. No gate re-implemented.

```text
artifact_basis       risk = 2.5 x daily ATR x pv x qty      (ROSKA4_MULT / NKD_MULT)
true_stop_distance   risk = |entry - stop| x pv x qty  =  2.0 x daily ATR x pv x qty
```

| window | candidates | taken A → B | booked P&L A → B | Δ | changed admissions |
|---|---|---|---|---|---|
| floor | 1,379 | 1,160 → **1,234** | $64,902.91 → $71,981.80 | **+$7,078.89** | 129 |
| vault2025 | 183 | 128 → **144** | $13,236.11 → $16,584.81 | **+$3,348.70** | 20 |
| vault2026 | 139 | 91 → **98** | $8,259.85 → $5,871.60 | **−$2,388.25** | 17 |
| | | | | **+$8,039.34** | **166** |

**It moves in both directions**, which is the part that settles the question:

```text
128  reject_cap        -> take
 33  take              -> reject_cap
  2  reject_family_cap -> take
  3  same-symbol shuffles
```

`process_instant` sorts same-instant candidates by risk, high first. Shrinking two sleeves and
not the other two **reorders the queue**, so some trades lose a slot they used to win. Three of
the moved rows are Calm A, whose own risk never changed at all — contention, not sizing. And
vault2026 takes **seven more trades for $2,388 less**.

That is a re-rate, not a refinement. **Decision: keep `artifact_basis`** for the two ATR-stop
sleeves — the basis every published Calmar, MaxDD and net figure was measured under — and
**align the live route to it**, because the live route had been sizing on the true stop
distance and was therefore admitting against caps nobody had measured for it.

Calm A and Stress are untouched: their artifacts carry a real stop price and their two bases
are the same number (28/28 and 4/4 exact). They are the control arm, and they stayed put.

### Peak cap usage, and one thing it does not mean

| window | | `roska4_swing` | `global_nkd` | family gross | family net |
|---|---|---|---|---|---|
| floor | artifact → true stop | 0.0490 → 0.0478 | 0.0421 → 0.0337 | 0.0490 → 0.0478 | 0.0489 → 0.0440 |
| vault2025 | | 0.0496 → 0.0481 | 0.0339 → 0.0271 | 0.0496 → 0.0481 | 0.0438 → 0.0439 |
| vault2026 | | 0.0484 → 0.0491 | 0.0592 → 0.0483 | 0.0484 → 0.0491 | 0.0412 → 0.0491 |

Gross is `max(long, short) / account`, which is what the guard tests — **not** the sum. The
first version of this harness summed both sides and reported peak `roska4_swing` usage of
**0.0903 against a 0.050 cap**. A usage figure above the cap the guard enforces is impossible
by construction, and that impossibility is what caught it. The check is now an assertion in
the harness rather than something to notice.

Two windows show a **net** peak above the 0.044 cap. That is not an instrument error and not a
breach anyone caused. Tracked down rather than assumed: **zero** admissions and **zero** forced
closes ever leave `roska4_swing` net above cap; the peak is reached at an unrelated instant
after a scheduled close. A settlement removes one side, the remaining imbalance rises, and the
cap gates *new risk* — it is not an invariant of the book afterwards, and nothing can un-take a
position because another one closed. It appears on **both** bases, so it has nothing to do with
this decision.

*(Three instrumentations were needed to land that. The first two disagreed with each other, and
the reason was mine: a settlement detector that sampled inside `_book`, before `settle_due`
removes the position from the book, so it could never see the change it was looking for.)*

---

## Part C — I-2: the hash now names what the route trades

```python
"instrument": ("tradable_symbol", "point_value", "tick", "sizing_basis")
```

- **`tradable_symbol`** — read from `Contract.ibkr`, the same attribute
  `ibkr_broker._RAITS_TO_IBKR` is *built* from, so the two cannot disagree, and the broker
  module is kept out of the identity path. Deliberately separate from `data_source_identity`:
  for MNKD they differ on purpose, and a collapse in either direction is the defect.
- **`point_value`**, **`tick`** — from the same record. Slippage was already hashed as
  ticks-per-side; the size of a tick decides what that costs.
- **`sizing_basis`** — which of the two risk formulas the cap gate is fed. 166 admissions ride
  on it.

**The concrete case, now caught:** on 2026-08-14 MNKD orders were found routing to the
full-size NKD contract at ten times the intended size — −$1,400.00 at the broker against
−$140.00 in the sleeve ledger, exactly 10.0000×. Correcting that moved **no params hash at
all**. It now moves two, and a test asserts precisely that.

Every one of the eight sleeve/instrument hashes changed:

```text
roska4_swing  MES   sha256:5a74de463a33aaa4…     roska4_calm    MES   sha256:50768f105ae6bd12…
roska4_swing  MNQ   sha256:d5e700c37bcd9ac5…     roska4_calm    MNQ   sha256:c08f7cfb3be7d84c…
roska4_swing  MYM   sha256:56c4ad078705bc62…     roska4_stress  MNQ   sha256:2f8a44208af5dc44…
roska4_swing  M2K   sha256:1b6effc84e255caf…     global_nkd     MNKD  sha256:19eef4ecde08b3c1…
```

### A signature that had been promising something it did not deliver

`sleeve_config(sleeve, inst, …)` has always taken `inst`. Until tonight **it never used it** —
the instrument reached the hash only through the data path. That is precisely what let a
routing change worth ten times the position size pass without moving anything.

The four R4 instruments therefore no longer share one identity with the data pinned, and the
Stage 2 test that asserted they did has been rewritten rather than deleted: pin the *contract*
as well and they collapse to one hash again, which is the separation that test was written to
prove. Both halves are now asserted.

---

## Part D — regression

| suite group | result |
|---|---|
| Stage 4 three-window reproduction (`TRACK1_STAGE4_ALL=1`) | **32 passed** (17 min) |
| identity / checkpoint / route / live-source (13 files) | **446 passed, 3 skipped** |
| explain / audit / freshness / dashboard (10 files) | **436 passed** |
| Stage 5Q-9 (new) | **17 passed** |
| Stage 5Q-8 (updated) | **19 passed** |

Reproduction after every change in this stage: **1,223 / 1,223** Normal-R4 including MNKD,
**421 / 421** Calm A, **50 / 3 / 4** Stress with P&L to the cent.

### Tests changed, each for a stated reason

1. **5Q-8 `xfail(strict)` removed** — I-1 is closed, and the companion bound test flipped from
   "exactly five differing fields" to "zero", kept rather than deleted so a regression cannot
   slip back under a test that only ever counted.
2. **5Q-8's sizing test inverted** — it asserted all four sleeves record `true_stop_distance`.
   Two of them now correctly do not.
3. **Stage 1 checkpoint fixture and pinned field list** — the four new names added to both;
   the parametrised mutation test covers them automatically.
4. **Stage 2 pinned field set + the legacy bootstrap** — `sleeve_configs` now states the four
   new fields, derived from the same contract table the route reads.
5. **Stage 2 log anchor**, and this one is not mine: `EXPECTED_ALL_DAYS["matched"]` was pinned
   at **91** and read **96** tonight. Not a regression — arithmetic. The live_day logs gain
   lines every trading day, so an all-days total pinned to a literal is a description that
   leaves the thing it describes on the next session, and bumping the number would only move
   the expiry date. `diverged` stays pinned exactly (one divergence is a failure whatever the
   total), `matched` became a floor at the published figure, and the **closed** window
   2026-08-10 → 08-21 stays pinned at exactly 85 — that is the anchor that means something.

---

## What changed in production

```text
global_index/track1_params.py        global_nkd declaration corrected (I-1);
                                     SIZING_BASIS + risk_dollars() + _contract() (I-3);
                                     four new identity fields + their SOURCES (I-2);
                                     four stale SOURCES entries repaired
global_index/route_params.py         FIELDS gains the "instrument" group (I-2)
global_index/track1_live_source.py   the two proxy sleeves size through tp.risk_dollars and
                                     record the basis they used instead of a literal (I-3)
```

**One live behaviour change, stated plainly.** `roska4_swing` and `global_nkd` candidates now
report risk **25% larger** than they did this morning, so the live route will admit **fewer**
positions than it would have — the conservative direction, and the one that matches the
measured book. It is measured across three windows and 1,701 candidate rows, but it has **never
run on a live slot**; tomorrow's shadow session is the first time it will.

---

## Still blocking paper orders — none of it identity

| id | what | from |
|---|---|---|
| **B-5R-H** | the appender stores the in-progress minute, so every run leaves a partial bar; `--repair-boundary` fixes the *previous* one | 5Q-7 |
| **B-5R-E/F** | `spy_refresh_pm` and `--repair-boundary` are still source-only — the restart was blocked | 5Q-7 |
| **B-5R-I** | the legacy route still fetches MNKD bars through the order map | 5Q-7 |
| **B-5R-C** | the NKD window leaves the Tokyo band after 2026-11-01 | 5Q-2 |
| **B1** | the order gate | by design; orders remain impossible |

And one thing this stage decided rather than closed: **switching to `true_stop_distance` is a
live option, not a defect.** It is arguably the more honest number. Taking it means re-rating
Track 1 first — 166 admissions and a $2,388 swing on vault2026 — and `sizing_basis` in the hash
is now what stops it happening by accident.

---

## Files

**Production**

```text
global_index/track1_params.py · global_index/route_params.py · global_index/track1_live_source.py
```

**Scratch**

```text
added    scratch/track1_stage5q9_sizing_basis_admission_20260824.py   the Part B harness
added    scratch/_track1_stage5q9_sizing_basis.json                   its measurement
added    scratch/test_track1_stage5q9_identity_admission_20260824.py  17 tests
added    scratch/track1_stage5q9_identity_admission_closeout_20260824.md / .json
edited   scratch/test_track1_stage5q8_identity_audit_20260824.py
edited   scratch/test_track1_route_checkpoint_stage1_20260822.py
edited   scratch/test_track1_stage2_equivalence_bootstrap_20260822.py
edited   scratch/track1_bootstrap_checkpoint_20260822.py
edited   scratch/test_track1_stage4_production_clean_20260823.py      (job-count pin 60 -> 61)
```

No production data file was written. No runtime evidence row was deleted or rewritten.
